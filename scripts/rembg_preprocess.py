#!/usr/bin/env python3
"""v0.3 — conditional background removal pre-generator.

Wraps `rembg` (MIT, commercial_safe; default model u2net, Apache 2.0).
Decides whether to run based on `--mode {auto,on,off}` and signals from
the input quality check (item 4) recorded in the per-asset meta.json:

  auto: run only when the input quality check measured the background
        as non-uniform (a cluttered photo, not a clean studio shot)
        AND the input doesn't already have low-coverage alpha (was
        already cropped) AND it isn't grayscale (a sketch).
  on:   run unconditionally.
  off:  never run; just record applied=false.

After rembg returns, a sanity check runs:
  - If foreground_coverage < 5% → rembg destroyed the subject; the
    fallback is the original image.
  - If foreground_coverage > 95% → rembg didn't actually remove
    anything; record applied=false, reason="nothing_to_remove".

Result writes `preprocessing.bg_removal` into the meta.json. The
wrapper script reassigns INPUT to the returned path so the generator
sees the cleaned image.

Usage:
    rembg_preprocess.py --input PATH --output-dir DIR --meta PATH
                        --mode {auto,on,off} [--model u2net|isnet-general-use]
                        [--name NAME] [--json]

The stdout JSON includes `"output_path"` — the wrapper reads this
to decide whether to swap $INPUT.
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

FOREGROUND_LOST_THRESHOLD = 0.05
FOREGROUND_TOO_HIGH_THRESHOLD = 0.95
BACKGROUND_UNIFORM_THRESHOLD = 0.85  # >= this: skip rembg


def _imports():
    try:
        from PIL import Image  # type: ignore
        import numpy as np  # type: ignore
        return Image, np
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); skipping rembg.", file=sys.stderr)
        return None, None


def _read_meta(meta_path: Path) -> dict:
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return {}


def _alpha_coverage(img, np) -> float:
    if img.mode != "RGBA":
        return 1.0
    arr = np.asarray(img)
    if arr.shape[-1] < 4:
        return 1.0
    alpha = arr[..., 3] / 255.0
    return float((alpha > 0.05).mean())


def _decide(mode: str, input_path: Path, meta: dict, Image, np) -> tuple[bool, str | None]:
    """Return (should_run, reason_if_skipped)."""
    if mode == "off":
        return False, "mode=off"
    if mode == "on":
        return True, None
    # auto
    try:
        img = Image.open(input_path)
        img.load()
    except Exception:
        return False, "input_unreadable"
    # Already cropped (RGBA with sparse alpha)?
    if img.mode == "RGBA":
        cov = _alpha_coverage(img, np)
        if cov < 0.8:
            return False, "already_cropped"
    # Grayscale / sketch?
    if img.mode in ("L", "1", "P"):
        return False, "grayscale"
    # Background uniformity from item 4?
    inp = meta.get("input") or {}
    bg_unif = inp.get("background_uniformity")
    if bg_unif is not None and bg_unif >= BACKGROUND_UNIFORM_THRESHOLD:
        return False, "uniform_background"
    return True, None


def _run_rembg(input_bytes: bytes, model_name: str):
    """Invoke rembg.remove. Returns (output_bytes, used_model)."""
    try:
        from rembg import remove, new_session  # type: ignore
    except ImportError:
        return None, None
    session = new_session(model_name)
    return remove(input_bytes, session=session), model_name


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--mode", choices=["auto", "on", "off"], default="auto")
    p.add_argument("--model", default="u2net",
                   help="rembg model name (u2net | isnet-general-use)")
    p.add_argument("--name", default="")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    Image, np = _imports()
    if Image is None:
        return 0  # graceful no-op

    input_path = Path(os.path.expanduser(args.input))
    output_dir = Path(os.path.expanduser(args.output_dir))
    meta_path = Path(os.path.expanduser(args.meta))
    name = args.name or input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    meta = _read_meta(meta_path)
    should_run, skip_reason = _decide(args.mode, input_path, meta, Image, np)

    payload: dict = {
        "applied": False,
        "mode": args.mode,
        "trigger": None,
        "model": None,
        "alpha_mean": None,
        "fallback": None,
        "duration_seconds": None,
    }
    output_path = str(input_path)  # default: no change

    if not should_run:
        payload["reason"] = skip_reason
    else:
        try:
            with open(input_path, "rb") as fh:
                in_bytes = fh.read()
            t0 = time.time()
            out_bytes, used = _run_rembg(in_bytes, args.model)
            payload["duration_seconds"] = round(time.time() - t0, 2)
            if out_bytes is None:
                payload["reason"] = "rembg_not_installed"
                print(
                    "[rembg] rembg not installed in pipeline-tools-env. "
                    "Install with: pip install rembg[cpu]",
                    file=sys.stderr,
                )
            else:
                target = output_dir / f"{name}_nobg.png"
                target.write_bytes(out_bytes)
                # Sanity check: coverage
                out_img = Image.open(target)
                out_img.load()
                cov = _alpha_coverage(out_img, np)
                payload["alpha_mean"] = round(cov, 3)
                payload["model"] = used
                if cov < FOREGROUND_LOST_THRESHOLD:
                    payload["fallback"] = "subject_lost"
                elif cov > FOREGROUND_TOO_HIGH_THRESHOLD:
                    payload["reason"] = "nothing_to_remove"
                    payload["applied"] = False
                    target.unlink(missing_ok=True)
                else:
                    payload["applied"] = True
                    payload["trigger"] = "auto" if args.mode == "auto" else args.mode
                    output_path = str(target)
        except Exception as e:
            payload["reason"] = f"rembg_failed: {e}"

    # Merge into meta.json
    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "preprocessing",
         "--data", json.dumps({"bg_removal": payload})],
        check=False,
    )

    result = {**payload, "output_path": output_path}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if payload["applied"]:
            print(f"[rembg] applied ({payload['model']}, "
                  f"coverage {payload['alpha_mean']}) → {output_path}")
        elif payload.get("fallback"):
            print(f"[rembg] result discarded ({payload['fallback']}); using original")
        else:
            print(f"[rembg] skipped: {payload.get('reason', '(unknown)')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
