#!/usr/bin/env python3
"""v0.3.6 — local VLM judge: 2D concepts (best-of-N) + 3D mesh turntables
(items 17-18 of the 2026-08 generation-quality refresh).

Uses mlx-vlm (MIT; commercial_safe) with a Qwen3-VL model (Apache 2.0;
commercial_safe).

--mode image scores concept images against a fixed rubric: subject
match, 3/4-view compliance, background cleanliness, lighting flatness,
single-subject, silhouette readability. Catches failures CLIP/SigLIP-
family scoring misses — composition and framing, not just prompt/subject
match. De-biasing protocol (arXiv:2606.20364): fixed image order, one
image per judge call (no cross-image context that could bias relative
scoring).

--mode mesh scores a set of turntable render views of ONE 3D mesh
(rendered by turntable_render.py) in a single joint call — unlike
--mode image, cross-view context is exactly what's wanted here, since
all views show the same object and back-face plausibility / geometry
artifacts can only be judged by comparing views. Catches degenerate
meshes (arXiv:2606.18451 shows heuristic checks are bimodal: they catch
catastrophic failure but miss "bad but valid" geometry).

Usage:
    vlm_judge.py --mode image --image PATH --meta PATH [--model MODEL] [--json]
    vlm_judge.py --mode image --images PATH1 PATH2 ... --meta PATH --rank [--json]
    vlm_judge.py --mode mesh --images VIEW1 VIEW2 ... --meta PATH [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
META_HELPER = SCRIPT_DIR / "meta_helper.py"

# Gate G2 (R0.3 spike): the 8B tier's raw rubric score does NOT reliably
# discriminate 3/4-view compliance (a flat front-view fixture scored
# identically to genuine 3/4-view fixtures, even with explicit few-shot-
# style anchoring in the prompt). The 30B-A3B MoE tier does discriminate
# correctly on the same fixtures — see docs/spike-report-generation-refresh.md
# R0.3 for both experiments. Default is the tier that's actually reliable.
DEFAULT_MODEL = "mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit"

RUBRIC = """You are grading a single concept-art image intended as the source photo for an
image-to-3D game-asset pipeline. Judge ONLY the image shown.

FIRST, before scoring, answer this literally: how many distinct flat faces/surfaces of
the object's outer shell can you see in this image, and name them (e.g. "front only",
"front + right side", "top + front + left side")? Objects photographed dead-on show
exactly ONE face. Objects photographed at an angle show TWO OR MORE faces meeting at a
visible corner or edge.

THEN return strict JSON, no other prose, matching exactly this schema:

{"visible_faces": "<your literal answer from above>", "subject_match": int,
"three_quarter_view": int, "background_cleanliness": int, "lighting_flatness": int,
"single_subject": int, "silhouette_readability": int, "overall": int}

Score each numeric dimension 0-10 (integers), where 10 is ideal for this purpose.

Dimension meanings:
- subject_match: does the image show one clear identifiable object (not abstract/unclear)?
- three_quarter_view: MUST be consistent with your visible_faces answer above. If you
  counted only ONE visible face, this MUST be 2-4 (front-on or side-on, not usable for
  3/4-view reconstruction). If you counted TWO OR MORE visible faces meeting at a
  corner, this MUST be 7-10. A front+top view (camera above but still centered, no
  side face) is a borderline case — score 5-7, since it gives some depth cue but not
  a true side profile.
- background_cleanliness: is the background plain/clean/white (not busy or cluttered)?
- lighting_flatness: is lighting even/diffuse (not harsh directional shadows)?
- single_subject: is there exactly one subject in frame (not multiple competing objects)?
- silhouette_readability: would this object's outline be easy to extract for 3D reconstruction?
- overall: holistic 0-10 score for suitability as image-to-3D input.

Return ONLY the JSON object, nothing before or after it."""

SCORE_KEYS = [
    "subject_match", "three_quarter_view", "background_cleanliness",
    "lighting_flatness", "single_subject", "silhouette_readability", "overall",
]
STRING_KEYS = ["visible_faces"]

# Item 18. One call sees ALL views at once (num_images=N) so the model can
# compare views against each other — the opposite of the image rubric's
# one-call-per-image isolation, and deliberately so.
MESH_RUBRIC = """You are grading a 3D mesh from a sequence of turntable render views (the
same object photographed from N evenly-spaced angles around a full rotation), intended for
use as a game asset. Judge the OBJECT across ALL views together — you are looking at one
mesh, not independent images.

FIRST, before scoring, answer this literally: across the view sequence, does the object's
silhouette maintain a consistent, believable volume (real width AND depth, not just a flat
outline), or does it collapse into a hairline- or paper-thin sliver in ANY view (apparent
width near-zero relative to height, like looking at a blade edge-on)? Name what you see
plainly, e.g. "consistent solid volume in all views" or "collapses to a hairline sliver in
several views".

If ANY view shows a hairline/paper-thin collapse, this is a catastrophically degenerate
mesh (typically a flattened/scale-collapsed export bug) — "geometry_artifacts", "recognizable",
and "overall" MUST all score 0-1, regardless of how clean or recognizable any single
non-degenerate view looks. A mesh that is a sliver from even one angle is not a usable
asset — do not let a good-looking view elsewhere talk you out of this.

If the object appears untextured (flat grey / vertex-color-only, no photographic surface
detail), set "texture_coherence" to null and judge geometry only — do not penalize a
correctly-formed but untextured mesh for lacking texture.

Return strict JSON, no other prose, matching exactly this schema:

{"shape_consistency": "<your literal answer from above>", "recognizable": int,
"back_face_plausibility": int, "geometry_artifacts": int, "texture_coherence": int_or_null,
"artifacts_note": "<short phrase or empty string>", "overall": int}

Score each numeric dimension 0-10 (integers), where 10 is ideal.

Dimension meanings:
- recognizable: across all views, does this read as one coherent, identifiable object
  (not a formless blob, not a sliver — see the hairline-collapse rule above)?
- back_face_plausibility: do the views away from the "front" look like a plausible
  continuation of the object (not flat/blank, not missing geometry, not warped)?
- geometry_artifacts: 10 = clean mesh, no visible slivers, holes, or floating fragments
  in ANY view. Deduct heavily for each artifact type you see across the sequence — a
  hairline collapse (see above) is not a minor deduction, it scores 0-1.
- texture_coherence: is the texture consistent and seam-free across views (not smeared,
  not duplicated/mirrored oddly)? null if the mesh has no texture to judge.
- artifacts_note: if geometry_artifacts < 8, briefly name what you saw (e.g. "2 floating
  fragments near the base", "collapses to a hairline sliver from the side"). Empty string
  if nothing notable.
- overall: holistic 0-10 score for suitability as a finished game asset.

Return ONLY the JSON object, nothing before or after it."""

MESH_SCORE_KEYS = [
    "recognizable", "back_face_plausibility", "geometry_artifacts",
    "texture_coherence", "overall",
]
MESH_STRING_KEYS = ["shape_consistency"]


def _imports():
    try:
        import mlx_vlm  # type: ignore
        from mlx_vlm.prompt_utils import apply_chat_template  # type: ignore
        return mlx_vlm, apply_chat_template
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); skipping. Activate vlm-env.", file=sys.stderr)
        return None, None


def _judge_one(mlx_vlm, apply_chat_template, model, processor, config, image_path: str) -> dict:
    """One judge call per image — fixed rubric, fresh conversation (no
    history from prior images), per the de-biasing protocol."""
    formatted = apply_chat_template(processor, config, RUBRIC, num_images=1)
    result = mlx_vlm.generate(
        model, processor, formatted, image=[image_path],
        max_tokens=350, temperature=0.0, verbose=False,
    )
    text = result.text.strip()
    start = text.index("{")
    end = text.rindex("}") + 1
    data = json.loads(text[start:end])
    parsed = {k: int(data[k]) for k in SCORE_KEYS if k in data}
    for k in STRING_KEYS:
        if k in data:
            parsed[k] = str(data[k])
    return parsed


def _judge_mesh(mlx_vlm, apply_chat_template, model, processor, config, image_paths: list[str]) -> dict:
    """One joint call over all turntable views of a single mesh."""
    formatted = apply_chat_template(processor, config, MESH_RUBRIC, num_images=len(image_paths))
    result = mlx_vlm.generate(
        model, processor, formatted, image=image_paths,
        max_tokens=400, temperature=0.0, verbose=False,
    )
    text = result.text.strip()
    start = text.index("{")
    end = text.rindex("}") + 1
    data = json.loads(text[start:end])
    parsed = {}
    for k in MESH_SCORE_KEYS:
        if k not in data:
            continue
        v = data[k]
        parsed[k] = int(v) if v is not None else None
    for k in MESH_STRING_KEYS:
        if k in data:
            parsed[k] = str(data[k])
    parsed["artifacts_note"] = str(data.get("artifacts_note", ""))
    return parsed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mode", choices=["image", "mesh"], default="image",
                   help="'image' judges a 2D concept; 'mesh' judges turntable views of a GLB.")
    p.add_argument("--image", help="Single image path (or use --images for --rank)")
    p.add_argument("--images", nargs="+",
                   help="Multiple image paths — variants for --rank, or turntable views for --mode mesh")
    p.add_argument("--meta", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"mlx-vlm model repo (default: {DEFAULT_MODEL})")
    p.add_argument("--rank", action="store_true", help="Judge and rank multiple images")
    p.add_argument("--floor", type=float, default=2.0,
                   help="Overall score below this (default 2.0) flags 'rejected' (warn-don't-block)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    mlx_vlm, apply_chat_template = _imports()
    if mlx_vlm is None:
        return 0  # graceful no-op

    if args.mode == "mesh":
        if not args.images:
            print("ERROR: --mode mesh requires --images VIEW1 VIEW2 ...", file=sys.stderr)
            return 2
        image_paths = [Path(os.path.expanduser(p)) for p in args.images]
    elif args.rank:
        if not args.images:
            print("ERROR: --rank requires --images PATH1 PATH2 ...", file=sys.stderr)
            return 2
        image_paths = [Path(os.path.expanduser(p)) for p in args.images]
    else:
        if not args.image:
            print("ERROR: --image is required (or use --rank --images ...)", file=sys.stderr)
            return 2
        image_paths = [Path(os.path.expanduser(args.image))]

    t0 = time.time()
    model, processor = mlx_vlm.load(args.model)
    config = model.config
    t_load = time.time()
    meta_path = Path(os.path.expanduser(args.meta))

    if args.mode == "mesh":
        t_img0 = time.time()
        scores = _judge_mesh(mlx_vlm, apply_chat_template, model, processor, config,
                              [str(p) for p in image_paths])
        verdict = float(scores.get("overall", 0))
        rejected = verdict < args.floor
        payload = {
            "model": args.model,
            "views_rendered": len(image_paths),
            "scores": {k: v for k, v in scores.items() if k != "artifacts_note"},
            "notes": scores.get("artifacts_note", ""),
            "verdict": verdict,
            "rejected": rejected,
            "duration_seconds": round(time.time() - t_img0, 2),
        }
        subprocess.run(
            [sys.executable, str(META_HELPER), "merge", str(meta_path),
             "--section", "judge",
             "--data", json.dumps({"mesh": payload})],
            check=False,
            capture_output=True,
        )
        if args.json:
            print(json.dumps({
                **payload,
                "pipeline_load_seconds": round(t_load - t0, 2),
            }, indent=2, sort_keys=True))
        else:
            flag = " (below floor — likely degenerate)" if rejected else ""
            print(f"[judge] mesh {verdict:.0f}/10{flag} ({len(image_paths)} views)")
            if payload["notes"]:
                print(f"[judge] notes: {payload['notes']}")
        return 0

    results = []
    for img in image_paths:
        t_img0 = time.time()
        scores = _judge_one(mlx_vlm, apply_chat_template, model, processor, config, str(img))
        results.append({
            "image": str(img),
            "scores": scores,
            "duration_seconds": round(time.time() - t_img0, 2),
        })

    if args.rank:
        ranked = sorted(enumerate(results), key=lambda kv: -kv[1]["scores"].get("overall", 0))
        output = []
        for rank, (idx, r) in enumerate(ranked, start=1):
            verdict = float(r["scores"].get("overall", 0))
            output.append({
                "rank": rank,
                "image": r["image"],
                "scores": r["scores"],
                "verdict": verdict,
                "rejected": verdict < args.floor,
                "duration_seconds": r["duration_seconds"],
            })
        winner = output[0]
        subprocess.run(
            [sys.executable, str(META_HELPER), "merge", str(meta_path),
             "--section", "judge",
             "--data", json.dumps({
                 "model": args.model,
                 "mode": "image",
                 "scores": winner["scores"],
                 "verdict": winner["verdict"],
                 "picked": winner["image"],
                 "rank": winner["rank"],
                 "rejected": winner["rejected"],
                 "duration_seconds": winner["duration_seconds"],
             })],
            check=False,
            capture_output=True,
        )
        if args.json:
            print(json.dumps({
                "results": output,
                "pipeline_load_seconds": round(t_load - t0, 2),
            }, indent=2, sort_keys=True))
        else:
            print(f"[judge] pipeline load: {t_load - t0:.1f}s")
            for r in output:
                flag = " (below floor — likely degenerate)" if r["rejected"] else ""
                print(f"[judge] #{r['rank']} {r['verdict']:.0f}/10 {r['image']}{flag}")
    else:
        r = results[0]
        verdict = float(r["scores"].get("overall", 0))
        rejected = verdict < args.floor
        payload = {
            "model": args.model,
            "mode": "image",
            "scores": r["scores"],
            "verdict": verdict,
            "picked": r["image"],
            "rejected": rejected,
            "duration_seconds": r["duration_seconds"],
        }
        subprocess.run(
            [sys.executable, str(META_HELPER), "merge", str(meta_path),
             "--section", "judge",
             "--data", json.dumps(payload)],
            check=False,
            capture_output=True,
        )
        if args.json:
            print(json.dumps({
                **payload,
                "pipeline_load_seconds": round(t_load - t0, 2),
            }, indent=2, sort_keys=True))
        else:
            flag = " (below floor — likely degenerate)" if rejected else ""
            print(f"[judge] {verdict:.0f}/10{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
