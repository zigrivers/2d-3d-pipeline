#!/usr/bin/env python3
"""v0.3.7 — DreamSim edit-drift check (item 21).

After an instruction edit or an angle-view render, checks the result
against its source image: a good edit should be "similar but visibly
changed" — a DreamSim distance inside a target band, neither near-zero
(edit had no real effect) nor large (identity drift; no longer reads
as the same subject). Reuses the same DreamSim model/cache convention
as scripts/dedup_variants.py (item 16), but for a single source/result
pair with a banded verdict rather than N-variant duplicate grouping.

Writes generation.drift into the edited image's meta.json (spec item
21: "uses the existing generation shape").

Usage:
    edit_drift_check.py --source PATH --edited PATH --meta PATH
                        [--min 0.03] [--max 0.45] [--json]
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

DREAMSIM_CACHE_DIR = os.environ.get(
    "DREAMSIM_CACHE_DIR",
    os.path.expanduser("~/3d-pipeline/models/dreamsim"),
)

# DreamSim distance: 0 = identical, ~1 = maximally different for natural
# images. Bootstrap band, not yet calibrated against real edit history —
# recalibrate alongside clip_calibration.json once real edits accumulate.
DEFAULT_MIN = 0.03
DEFAULT_MAX = 0.45


def _imports():
    try:
        import torch  # type: ignore
        from dreamsim import dreamsim  # type: ignore
        from PIL import Image  # type: ignore
        return dreamsim, torch, Image
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); skipping. Activate pipeline-tools-env.",
              file=sys.stderr)
        return None, None, None


def _band(distance: float, min_d: float, max_d: float) -> str:
    if distance < min_d:
        return "too_similar"
    if distance > max_d:
        return "too_different"
    return "similar_but_changed"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", required=True)
    p.add_argument("--edited", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--min", type=float, default=DEFAULT_MIN,
                   help=f"below this distance, verdict is too_similar (default: {DEFAULT_MIN})")
    p.add_argument("--max", type=float, default=DEFAULT_MAX,
                   help=f"above this distance, verdict is too_different (default: {DEFAULT_MAX})")
    p.add_argument("--device", default="mps")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    dreamsim, torch, Image = _imports()
    if dreamsim is None:
        return 0  # graceful no-op, matches dedup_variants.py precedent

    t0 = time.time()
    Path(DREAMSIM_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    model, preprocess = dreamsim(pretrained=True, device=args.device, cache_dir=DREAMSIM_CACHE_DIR)

    source_img = preprocess(Image.open(os.path.expanduser(args.source)).convert("RGB")).to(args.device)
    edited_img = preprocess(Image.open(os.path.expanduser(args.edited)).convert("RGB")).to(args.device)

    with torch.no_grad():
        distance = float(model(source_img, edited_img).item())

    duration = round(time.time() - t0, 2)
    verdict = _band(distance, args.min, args.max)

    payload = {
        "drift": {
            "dreamsim_distance": round(distance, 4),
            "band": verdict,
            "min": args.min,
            "max": args.max,
            "duration_seconds": duration,
        }
    }
    meta_path = Path(os.path.expanduser(args.meta))
    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "generation",
         "--data", json.dumps(payload)],
        check=False,
        capture_output=True,
    )

    if args.json:
        print(json.dumps({**payload["drift"]}, indent=2, sort_keys=True))
    else:
        print(f"[dreamsim] edit drift: {distance:.3f} ({verdict})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
