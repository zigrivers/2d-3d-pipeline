#!/usr/bin/env python3
"""v0.3 — CLIP variant ranking + per-model soft signal.

Scores generated images against their prompts using OpenCLIP ViT-L/14
(MIT; commercial_safe). Two modes:

  single:  score one image against one prompt. Writes
           clip.similarity + clip.model + clip.model_band +
           clip.percentile_for_this_model into the meta.json.
  rank:    score N images against the same prompt. Sorts by
           similarity desc; writes a 'rank' field per variant.

Calibration per model lives in scripts/clip_calibration.json (per-
model percentile bands). Below-p25 scores trigger the "weak" band;
below-p10 triggers "very weak" — at which point the wrapper /
skill should suggest re-generation.

Usage:
    clip_score.py --prompt TEXT --image PATH --meta PATH --model-name MFLUX [--json]
    clip_score.py --prompt TEXT --images PATH1 PATH2 ... --meta PATH --rank
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
CALIBRATION = SCRIPT_DIR / "clip_calibration.json"


def _imports():
    try:
        import open_clip  # type: ignore
        import torch  # type: ignore
        from PIL import Image  # type: ignore
        return open_clip, torch, Image
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); skipping. Activate pipeline-tools-env.",
              file=sys.stderr)
        return None, None, None


def _band(model_name: str, score: float) -> tuple[str, float]:
    """Return (band_label, approx_percentile) for `score` under `model_name`'s
    per-model calibration. Falls back to a global 0.75 threshold if the
    calibration file is missing."""
    try:
        cal = json.loads(CALIBRATION.read_text())
    except Exception:
        return ("below_p25" if score < 0.75 else "p50_or_better"), -1.0
    bands = cal.get(model_name) or cal.get("default") or {"p50": 0.80, "p25": 0.75, "p10": 0.70}
    if score >= bands["p50"]:
        return "p50_or_better", 0.5
    if score >= bands["p25"]:
        return "p25", 0.25
    if score >= bands["p10"]:
        return "p10", 0.10
    return "below_p10", 0.05


def _score(prompt: str, image_paths: list[Path], open_clip, torch, Image) -> list[float]:
    model_id = "ViT-L-14"
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_id, pretrained="openai"
    )
    tokenizer = open_clip.get_tokenizer(model_id)
    model.eval()

    text_tokens = tokenizer([prompt])
    with torch.no_grad():
        text_feat = model.encode_text(text_tokens)
        text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)

        scores: list[float] = []
        for p in image_paths:
            img = Image.open(p).convert("RGB")
            img_tensor = preprocess(img).unsqueeze(0)
            img_feat = model.encode_image(img_tensor)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            sim = float((img_feat @ text_feat.T).item())
            scores.append(sim)
    return scores


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--prompt", required=True)
    p.add_argument("--image", help="Single image path (or use --images for rank mode)")
    p.add_argument("--images", nargs="+", help="Multiple image paths for --rank")
    p.add_argument("--meta", required=True)
    p.add_argument("--model-name", default="z-image-turbo",
                   help="Generator name (used to pick the calibration band)")
    p.add_argument("--rank", action="store_true", help="Rank multiple images")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    open_clip, torch, Image = _imports()
    if open_clip is None:
        # Graceful no-op
        return 0

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
    scores = _score(args.prompt, image_paths, open_clip, torch, Image)
    duration = round(time.time() - t0, 2)

    meta_path = Path(os.path.expanduser(args.meta))

    if args.rank:
        # Sort indices by score desc
        ranked = sorted(enumerate(scores), key=lambda kv: -kv[1])
        result = []
        for rank, (idx, score) in enumerate(ranked, start=1):
            band, pct = _band(args.model_name, score)
            result.append({
                "rank": rank,
                "image": str(image_paths[idx]),
                "similarity": round(score, 3),
                "model": "ViT-L-14",
                "model_band": band,
                "percentile_for_this_model": pct,
            })
        # Merge primary result into meta.json
        primary = result[0]
        subprocess.run(
            [sys.executable, str(META_HELPER), "merge", str(meta_path),
             "--section", "clip",
             "--data", json.dumps({
                 "similarity": primary["similarity"],
                 "model": primary["model"],
                 "model_band": primary["model_band"],
                 "percentile_for_this_model": primary["percentile_for_this_model"],
                 "rank": primary["rank"],
                 "duration_seconds": duration,
             })],
            check=False,
        )
        if args.json:
            print(json.dumps({"results": result}, indent=2, sort_keys=True))
        else:
            for r in result:
                print(f"[clip] #{r['rank']} {r['similarity']:.3f} ({r['model_band']}) {r['image']}")
    else:
        score = scores[0]
        band, pct = _band(args.model_name, score)
        payload = {
            "similarity": round(score, 3),
            "model": "ViT-L-14",
            "model_band": band,
            "percentile_for_this_model": pct,
            "duration_seconds": duration,
        }
        subprocess.run(
            [sys.executable, str(META_HELPER), "merge", str(meta_path),
             "--section", "clip",
             "--data", json.dumps(payload)],
            check=False,
        )
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"[clip] CLIP similarity: {score:.3f} ({band})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
