#!/usr/bin/env python3
"""v0.3 — input image quality check + format normalisation.

Called from generate.sh (via _pipeline_lib.sh::check_and_normalize_input)
at the top of the image-to-3D pipeline. Validates the user-supplied
image and, if needed, normalises non-PNG/JPEG formats to PNG so the
downstream generators (SF3D / SPAR3D / TRELLIS) see only the formats
they actually support.

Writes the result into the per-asset meta.json under the `input`
section via meta_helper.py. Sidecar files live under $ASSETS_ROOT,
never next to the user's input (codex P1).

Usage:
    input_quality_check.py --input PATH --output-dir DIR --meta PATH
                           [--name NAME] [--json]

Behaviour summary:
    - Resolution: warn < 512, error-level warn < 384
    - Aspect ratio: warn outside [0.5, 2.0]
    - File size: warn < 5 KB
    - Format: error if not in {png, jpg, jpeg, webp, gif}
    - Animated GIF / multi-frame: take first frame, warn
    - WebP / GIF input: convert to PNG at <output-dir>/<name>_normalized.png
    - PNG / JPEG: kept as-is; normalized_path = original_path

Issues are recorded as string tags in `input.issues` and surfaced by
the wrapper.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

VALID_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
NORMALIZE_FROM = {".webp", ".gif"}
MIN_RESOLUTION_WARN = 512
MIN_RESOLUTION_LOUD = 384
MIN_FILE_SIZE_BYTES = 5 * 1024
ASPECT_MIN = 0.5
ASPECT_MAX = 2.0
SCRIPT_DIR = Path(__file__).resolve().parent
META_HELPER = SCRIPT_DIR / "meta_helper.py"


def _check_pil() -> "type":
    try:
        from PIL import Image  # type: ignore
        return Image
    except ImportError:
        print(
            "ERROR: Pillow not installed. Activate pipeline-tools-env first:\n"
            "    source ~/3d-pipeline/pipeline-tools-env/bin/activate",
            file=sys.stderr,
        )
        sys.exit(2)


def _measure_background_uniformity(img) -> float:
    """Crude proxy: stdev of luminance across the 4 image edges.
    Returns a value in [0, 1] where 1.0 = perfectly uniform edges
    (likely studio backdrop) and 0.0 = high variance (cluttered)."""
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return -1.0  # numpy unavailable; signal "unknown"
    gray = img.convert("L")
    arr = np.array(gray)
    h, w = arr.shape
    strip = 8  # px
    edges = np.concatenate([
        arr[:strip, :].flatten(),
        arr[-strip:, :].flatten(),
        arr[:, :strip].flatten(),
        arr[:, -strip:].flatten(),
    ])
    stdev = float(edges.std())
    # Map stdev → uniformity. stdev=0 → 1.0; stdev>=64 (very cluttered) → 0.0.
    return max(0.0, min(1.0, 1.0 - stdev / 64.0))


def check_and_normalize(input_path: Path, output_dir: Path, name: str) -> dict:
    Image = _check_pil()

    issues: list[str] = []

    if not input_path.exists():
        return {"error": "input_not_found", "original_path": str(input_path), "issues": ["input_not_found"]}

    ext = input_path.suffix.lower()
    if ext not in VALID_EXTS:
        return {
            "error": "unsupported_format",
            "original_path": str(input_path),
            "format_original": ext.lstrip("."),
            "issues": ["unsupported_format"],
            "notes": f"Supported: {sorted(VALID_EXTS)}",
        }

    file_size = input_path.stat().st_size
    if file_size < MIN_FILE_SIZE_BYTES:
        issues.append("very_small_file")

    try:
        img = Image.open(input_path)
        # Force load to catch corruption early.
        img.load()
    except Exception as e:
        return {
            "error": "image_unreadable",
            "original_path": str(input_path),
            "issues": ["image_unreadable"],
            "notes": str(e),
        }

    width, height = img.size
    format_original = (img.format or ext.lstrip(".")).upper()
    aspect = width / height if height else 1.0

    if min(width, height) < MIN_RESOLUTION_LOUD:
        issues.append("very_low_resolution")
    elif min(width, height) < MIN_RESOLUTION_WARN:
        issues.append("low_resolution")

    if aspect < ASPECT_MIN or aspect > ASPECT_MAX:
        issues.append("extreme_aspect_ratio")

    # Animated / multi-frame
    is_animated = getattr(img, "is_animated", False)
    n_frames = getattr(img, "n_frames", 1)
    if is_animated or n_frames > 1:
        issues.append("multi_frame_input")

    # Normalise WebP / GIF to PNG. Always grab frame 0.
    output_dir.mkdir(parents=True, exist_ok=True)
    if ext in NORMALIZE_FROM:
        # Save first frame as PNG. Preserve RGBA if present.
        frame = img.convert("RGBA") if img.mode in ("P", "RGBA") else img.convert("RGB")
        normalized_path = output_dir / f"{name}_normalized.png"
        frame.save(normalized_path, "PNG")
        format_normalized = "PNG"
    else:
        normalized_path = input_path
        format_normalized = format_original

    # Re-open the (now possibly converted) image for background uniformity
    img_for_check = Image.open(normalized_path) if normalized_path != input_path else img
    bg_uniformity = _measure_background_uniformity(img_for_check)

    return {
        "original_path": str(input_path),
        "normalized_path": str(normalized_path) if normalized_path != input_path else None,
        "format_original": format_original,
        "format_normalized": format_normalized,
        "width": int(width),
        "height": int(height),
        "aspect_ratio": round(aspect, 3),
        "background_uniformity": round(bg_uniformity, 3) if bg_uniformity >= 0 else None,
        "file_size_bytes": int(file_size),
        "issues": issues,
    }


def _merge_into_meta(meta_path: Path, payload: dict) -> None:
    """Forward result to meta_helper.py via subprocess so we get the file lock."""
    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "input",
         "--data", json.dumps(payload)],
        check=True,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True, help="Path to user-supplied image")
    p.add_argument("--output-dir", required=True,
                   help="Directory under $ASSETS_ROOT where the normalised PNG goes")
    p.add_argument("--meta", required=True,
                   help="Path to <output>.meta.json (created if missing)")
    p.add_argument("--name", default="",
                   help="Asset name (used for the normalised filename; default: input basename)")
    p.add_argument("--json", action="store_true", help="Emit JSON result on stdout")
    args = p.parse_args()

    input_path = Path(os.path.expanduser(args.input))
    output_dir = Path(os.path.expanduser(args.output_dir))
    meta_path = Path(os.path.expanduser(args.meta))
    name = args.name or input_path.stem

    result = check_and_normalize(input_path, output_dir, name)
    _merge_into_meta(meta_path, result)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if "error" in result:
            print(f"[input-check] ERROR: {result['error']}", file=sys.stderr)
            if "notes" in result:
                print(f"[input-check]   {result['notes']}", file=sys.stderr)
            return 1
        print(f"[input-check] {result['width']}x{result['height']} {result['format_original']}"
              f" ({result['file_size_bytes'] // 1024} KB)")
        if result["normalized_path"]:
            print(f"[input-check] normalised → {result['normalized_path']}")
        if result["issues"]:
            for tag in result["issues"]:
                print(f"[input-check] ⚠ {tag}")
        if result.get("background_uniformity") is not None:
            print(f"[input-check] background_uniformity={result['background_uniformity']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
