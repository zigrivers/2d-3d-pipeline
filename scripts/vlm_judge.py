#!/usr/bin/env python3
"""v0.3.5 — local VLM judge for 2D concepts, best-of-N auto-select
(item 17 of the 2026-08 generation-quality refresh).

Uses mlx-vlm (MIT; commercial_safe) with a Qwen3-VL model (Apache 2.0;
commercial_safe) to score concept images against a fixed rubric:
subject match, 3/4-view compliance, background cleanliness, lighting
flatness, single-subject, silhouette readability. Catches failures
CLIP/SigLIP-family scoring misses — composition and framing, not just
prompt/subject match.

De-biasing protocol (arXiv:2606.20364): fixed image order, one image
per judge call (no cross-image context that could bias relative
scoring).

--mode mesh (item 18) is not yet implemented — this PR ships image
concept judging only.

Usage:
    vlm_judge.py --mode image --image PATH --meta PATH [--model MODEL] [--json]
    vlm_judge.py --mode image --images PATH1 PATH2 ... --meta PATH --rank [--json]
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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mode", choices=["image"], default="image",
                   help="Judge mode. Only 'image' is implemented (item 18 adds 'mesh').")
    p.add_argument("--image", help="Single image path (or use --images for --rank)")
    p.add_argument("--images", nargs="+", help="Multiple image paths for --rank")
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

    if args.rank:
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

    results = []
    for img in image_paths:
        t_img0 = time.time()
        scores = _judge_one(mlx_vlm, apply_chat_template, model, processor, config, str(img))
        results.append({
            "image": str(img),
            "scores": scores,
            "duration_seconds": round(time.time() - t_img0, 2),
        })

    meta_path = Path(os.path.expanduser(args.meta))

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
