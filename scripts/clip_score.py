#!/usr/bin/env python3
"""v0.3.5 — prompt-adherence variant ranking + per-model soft signal.

Scores generated images against their prompts. Two scorer backends:

  siglip2 (default): SigLIP 2 (Apache 2.0; commercial_safe). Better
                      prompt-adherence signal than CLIP per
                      arXiv:2606.18451 — item 16 of the 2026-08
                      generation-quality refresh.
  clip:               OpenCLIP ViT-L/14 (MIT; commercial_safe). Kept for
                      back-compat; select with --scorer clip.

Two modes:

  single:  score one image against one prompt. Writes
           clip.similarity + clip.scorer + clip.model + clip.model_band +
           clip.percentile_for_this_model into the meta.json.
  rank:    score N images against the same prompt. Sorts by
           similarity desc; writes a 'rank' field per variant.

Calibration per (scorer, model) lives in scripts/clip_calibration.json.
Below-p25 scores trigger the "weak" band; below-p10 triggers "very
weak" — at which point the wrapper / skill should suggest
re-generation.

Usage:
    clip_score.py --prompt TEXT --image PATH --meta PATH --model-name MFLUX [--scorer siglip2] [--json]
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

SIGLIP2_MODEL_ID = "google/siglip2-base-patch16-224"
CLIP_MODEL_ID = "ViT-L-14"


def _imports(scorer: str):
    try:
        import torch  # type: ignore
        from PIL import Image  # type: ignore
        if scorer == "siglip2":
            from transformers import AutoModel, AutoProcessor  # type: ignore
            return (AutoModel, AutoProcessor), torch, Image
        else:
            import open_clip  # type: ignore
            return open_clip, torch, Image
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); skipping. Activate pipeline-tools-env.",
              file=sys.stderr)
        return None, None, None


def _band(scorer: str, model_name: str, score: float) -> tuple[str, float]:
    """Return (band_label, approx_percentile) for `score` under `scorer`'s
    per-model calibration. Falls back to a global threshold if the
    calibration file is missing."""
    fallback = 0.20 if scorer == "siglip2" else 0.75
    try:
        cal = json.loads(CALIBRATION.read_text())
    except Exception:
        return ("below_p25" if score < fallback else "p50_or_better"), -1.0
    scorer_cal = cal.get(scorer) or {}
    bands = scorer_cal.get(model_name) or scorer_cal.get("default") \
        or {"p50": fallback + 0.05, "p25": fallback, "p10": fallback - 0.05}
    if score >= bands["p50"]:
        return "p50_or_better", 0.5
    if score >= bands["p25"]:
        return "p25", 0.25
    if score >= bands["p10"]:
        return "p10", 0.10
    return "below_p10", 0.05


def _score_siglip2(prompt: str, image_paths: list[Path], model_cls, torch, Image) -> list[float]:
    AutoModel, AutoProcessor = model_cls
    model = AutoModel.from_pretrained(SIGLIP2_MODEL_ID)
    processor = AutoProcessor.from_pretrained(SIGLIP2_MODEL_ID)
    model.eval()

    with torch.no_grad():
        text_inputs = processor(text=[prompt], padding="max_length", return_tensors="pt")
        text_feat = model.get_text_features(**text_inputs)
        text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)

        scores: list[float] = []
        for p in image_paths:
            img = Image.open(p).convert("RGB")
            img_inputs = processor(images=[img], return_tensors="pt")
            img_feat = model.get_image_features(**img_inputs)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            sim = float((img_feat @ text_feat.T).item())
            scores.append(sim)
    return scores


def _score_clip(prompt: str, image_paths: list[Path], open_clip, torch, Image) -> list[float]:
    model, _, preprocess = open_clip.create_model_and_transforms(
        CLIP_MODEL_ID, pretrained="openai"
    )
    tokenizer = open_clip.get_tokenizer(CLIP_MODEL_ID)
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


def _score(scorer: str, prompt: str, image_paths: list[Path], backend, torch, Image) -> list[float]:
    if scorer == "siglip2":
        return _score_siglip2(prompt, image_paths, backend, torch, Image)
    return _score_clip(prompt, image_paths, backend, torch, Image)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--prompt", required=True)
    p.add_argument("--image", help="Single image path (or use --images for rank mode)")
    p.add_argument("--images", nargs="+", help="Multiple image paths for --rank")
    p.add_argument("--meta", required=True)
    p.add_argument("--model-name", default="z-image-turbo",
                   help="Generator name (used to pick the calibration band)")
    p.add_argument("--rank", action="store_true", help="Rank multiple images")
    p.add_argument("--scorer", choices=["clip", "siglip2"], default="siglip2",
                   help="Scorer backend (default: siglip2, per item 16 refresh)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    backend, torch, Image = _imports(args.scorer)
    if backend is None:
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
    scores = _score(args.scorer, args.prompt, image_paths, backend, torch, Image)
    duration = round(time.time() - t0, 2)

    meta_path = Path(os.path.expanduser(args.meta))
    model_id = SIGLIP2_MODEL_ID if args.scorer == "siglip2" else CLIP_MODEL_ID

    if args.rank:
        # Sort indices by score desc
        ranked = sorted(enumerate(scores), key=lambda kv: -kv[1])
        result = []
        for rank, (idx, score) in enumerate(ranked, start=1):
            band, pct = _band(args.scorer, args.model_name, score)
            result.append({
                "rank": rank,
                "image": str(image_paths[idx]),
                "similarity": round(score, 3),
                "scorer": args.scorer,
                "model": model_id,
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
                 "scorer": primary["scorer"],
                 "model": primary["model"],
                 "model_band": primary["model_band"],
                 "percentile_for_this_model": primary["percentile_for_this_model"],
                 "rank": primary["rank"],
                 "duration_seconds": duration,
             })],
            check=False,
            capture_output=True,
        )
        if args.json:
            print(json.dumps({"results": result}, indent=2, sort_keys=True))
        else:
            for r in result:
                print(f"[clip] #{r['rank']} {r['similarity']:.3f} ({r['model_band']}) {r['image']}")
    else:
        score = scores[0]
        band, pct = _band(args.scorer, args.model_name, score)
        payload = {
            "similarity": round(score, 3),
            "scorer": args.scorer,
            "model": model_id,
            "model_band": band,
            "percentile_for_this_model": pct,
            "duration_seconds": duration,
        }
        subprocess.run(
            [sys.executable, str(META_HELPER), "merge", str(meta_path),
             "--section", "clip",
             "--data", json.dumps(payload)],
            check=False,
            capture_output=True,
        )
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"[clip] {args.scorer} similarity: {score:.3f} ({band})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
