#!/usr/bin/env python3
"""Multi-view-2D adapter: Zero123++ (sudo-ai/zero123plus-v1.2).

Takes a single concept image and produces 6 multi-view-consistent
images at Zero123++'s native angles (azimuth 30/90/150/210/270/330,
alternating elevation 30°/-20°). Saves each view as a separate PNG
named per `tests/multiview-bench/view_configs/zero123_plus_plus.json`.

Used by tools/build_mvgen_dataset.py for the Option B path of the
multi-view backend benchmark.

Usage:
    python zero123_plus_plus.py --concept PATH.png --output-dir DIR --json

Output JSON shape:
    {
      "status": "ok",
      "model": "zero123plus-v1.2",
      "license_bucket": "commercial_threshold",
      "views": [
        {"name": "v030_30",   "path": "...", "azimuth_deg": 30,  "elevation_deg": 30},
        ...
      ],
      "duration_seconds": 24.1
    }

Requires diffusers + transformers + torch in pipeline-tools-env (or
in a dedicated multiview-env). Falls back to a structured error if
unavailable so the benchmark harness can record it cleanly.

License note: Zero123++ checkpoints are released by Sudo AI under a
permissive license (verify the current text upstream; bucket assigned
here is `commercial_threshold` as a conservative default — same as
SDXL / SF3D / SPAR3D). Update the bucket here and in
scripts/_pipeline_lib.sh::license_bucket_for_model if the upstream
license changes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

MODEL_ID = "sudo-ai/zero123plus-v1.2"
LICENSE_BUCKET = "commercial_threshold"

# Match tests/multiview-bench/view_configs/zero123_plus_plus.json
NATIVE_VIEWS = [
    {"name": "v030_30",    "azimuth_deg": 30,  "elevation_deg": 30},
    {"name": "v090_neg20", "azimuth_deg": 90,  "elevation_deg": -20},
    {"name": "v150_30",    "azimuth_deg": 150, "elevation_deg": 30},
    {"name": "v210_neg20", "azimuth_deg": 210, "elevation_deg": -20},
    {"name": "v270_30",    "azimuth_deg": 270, "elevation_deg": 30},
    {"name": "v330_neg20", "azimuth_deg": 330, "elevation_deg": -20},
]


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0 if payload.get("status") == "ok" else 1


def _imports():
    try:
        from PIL import Image  # type: ignore
        import torch  # type: ignore
        from diffusers import DiffusionPipeline  # type: ignore
        return Image, torch, DiffusionPipeline
    except ImportError as e:
        return None, None, None


def _split_grid(img, rows: int, cols: int):
    """Zero123++ returns a tiled grid (default 2 rows × 3 cols of 320×320).
    Slice it into individual view images in row-major order."""
    w, h = img.size
    tw, th = w // cols, h // rows
    tiles = []
    for r in range(rows):
        for c in range(cols):
            box = (c * tw, r * th, (c + 1) * tw, (r + 1) * th)
            tiles.append(img.crop(box))
    return tiles


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--concept", required=True, help="Path to single concept image (PNG)")
    p.add_argument("--output-dir", required=True, help="Directory to write per-view PNGs")
    p.add_argument("--json", action="store_true", default=True,
                   help="Emit JSON result on stdout (currently always on)")
    args = p.parse_args()

    t0 = time.time()
    Image, torch, DiffusionPipeline = _imports()
    if Image is None:
        return _emit({
            "status": "error",
            "error": "missing_deps",
            "model": MODEL_ID,
            "license_bucket": LICENSE_BUCKET,
            "notes": ("Install in pipeline-tools-env (or multiview-env): "
                      "pip install 'diffusers>=0.25' transformers torch Pillow accelerate"),
        })

    concept = Path(os.path.expanduser(args.concept))
    output_dir = Path(os.path.expanduser(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    if not concept.exists():
        return _emit({
            "status": "error",
            "error": "concept_not_found",
            "model": MODEL_ID,
            "license_bucket": LICENSE_BUCKET,
            "concept": str(concept),
        })

    # Pick device. Apple Silicon: mps. Otherwise CPU (slow).
    device = "mps" if torch.backends.mps.is_available() else (
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    try:
        pipeline = DiffusionPipeline.from_pretrained(
            MODEL_ID,
            custom_pipeline=MODEL_ID,
            torch_dtype=torch.float16 if device != "cpu" else torch.float32,
        )
        pipeline.to(device)
    except Exception as e:
        return _emit({
            "status": "error",
            "error": "pipeline_load_failed",
            "model": MODEL_ID,
            "license_bucket": LICENSE_BUCKET,
            "device": device,
            "notes": str(e),
        })

    try:
        cond = Image.open(concept).convert("RGB")
        result = pipeline(cond, num_inference_steps=75).images[0]
    except Exception as e:
        return _emit({
            "status": "error",
            "error": "inference_failed",
            "model": MODEL_ID,
            "license_bucket": LICENSE_BUCKET,
            "device": device,
            "notes": str(e),
        })

    # Default Zero123++ output is 960×640 (2×3 tiles of 320×320).
    tiles = _split_grid(result, rows=2, cols=3)
    if len(tiles) != len(NATIVE_VIEWS):
        return _emit({
            "status": "error",
            "error": "unexpected_grid_shape",
            "model": MODEL_ID,
            "license_bucket": LICENSE_BUCKET,
            "expected_tiles": len(NATIVE_VIEWS),
            "actual_tiles": len(tiles),
        })

    views: list[dict] = []
    for tile, view in zip(tiles, NATIVE_VIEWS):
        path = output_dir / f"{view['name']}.png"
        tile.save(path)
        views.append({**view, "path": str(path)})

    duration = round(time.time() - t0, 2)
    return _emit({
        "status": "ok",
        "model": MODEL_ID,
        "license_bucket": LICENSE_BUCKET,
        "device": device,
        "views": views,
        "duration_seconds": duration,
    })


if __name__ == "__main__":
    sys.exit(main())
