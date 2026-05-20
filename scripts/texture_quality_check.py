#!/usr/bin/env python3
"""v0.3 — texture quality validation.

Loads a GLB with trimesh, extracts PBR texture maps (baseColor /
roughness / metallic / normal), and flags degenerate patterns the
generator can emit:

  - flat-black-albedo:   pure-black albedo (model defaulted)
  - flat-color-albedo:   single-colour albedo (no real material)
  - uniform-roughness:   stdev < threshold (model defaulted)
  - uniform-metallic:    stdev < threshold (same)
  - low-detail-normal:   normal map has near-zero XY magnitude
  - uninitialised:       all-white / never-written buffer
  - no_textures:         TRELLIS-on-Mac (vertex colours only)

Writes `quality.textures` to the per-asset meta.json.

Usage:
    texture_quality_check.py --input PATH.glb --meta PATH [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
META_HELPER = SCRIPT_DIR / "meta_helper.py"

ALBEDO_FLAT_BLACK_MAX = 8       # mean luminance below this -> flat-black
FLAT_STDEV_THRESHOLD = 5        # stdev below this -> single-colour
UNIFORM_STDEV_THRESHOLD = 2     # roughness/metallic flat
NORMAL_XY_MIN = 8               # normal map detail floor (XY mag)
UNINIT_MEAN = 250               # near-white mean
UNINIT_STDEV = 2


def _imports():
    try:
        import trimesh  # type: ignore
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore
        return trimesh, np, Image
    except ImportError as e:
        print(
            f"ERROR: missing dep ({e}). Activate pipeline-tools-env first.",
            file=sys.stderr,
        )
        sys.exit(2)


def _get_pil_image(material_image, Image):
    """trimesh sometimes returns a PIL image directly, sometimes a numpy array."""
    if material_image is None:
        return None
    if hasattr(material_image, "size"):
        return material_image
    try:
        import numpy as np
        arr = np.asarray(material_image)
        if arr.ndim < 2:
            return None
        return Image.fromarray(arr)
    except Exception:
        return None


def _analyse_map(img, np, channel: str) -> dict:
    """Mean/stdev stats for a texture map."""
    arr = np.asarray(img)
    if arr.ndim == 2:
        gray = arr
    else:
        gray = arr.mean(axis=-1)
    return {
        "mean": round(float(gray.mean()), 2),
        "stdev": round(float(gray.std()), 2),
        "_arr": arr,  # consumer pops this
    }


def check(input_path: Path) -> dict:
    trimesh, np, Image = _imports()
    try:
        mesh = trimesh.load(str(input_path), force="mesh")
    except Exception as e:
        return {"textures_present": [], "issues": ["load_failed"], "error": str(e), "stats": {}}

    material = getattr(getattr(mesh, "visual", None), "material", None)
    if material is None:
        return {"textures_present": [], "issues": ["no_textures"], "stats": {}}

    textures = {
        "albedo": _get_pil_image(getattr(material, "baseColorTexture", None), Image),
        "roughness": _get_pil_image(getattr(material, "roughnessTexture", None) or getattr(material, "metallicRoughnessTexture", None), Image),
        "metallic": _get_pil_image(getattr(material, "metallicTexture", None) or getattr(material, "metallicRoughnessTexture", None), Image),
        "normal": _get_pil_image(getattr(material, "normalTexture", None), Image),
    }

    issues: list[str] = []
    stats: dict = {}
    present: list[str] = []

    for name, img in textures.items():
        if img is None:
            continue
        present.append(name)
        s = _analyse_map(img, np, name)
        mean, stdev = s["mean"], s["stdev"]
        arr = s.pop("_arr")
        # Per-map degeneracy checks
        if name == "albedo":
            if mean < ALBEDO_FLAT_BLACK_MAX:
                issues.append("flat-black-albedo")
            elif stdev < FLAT_STDEV_THRESHOLD:
                issues.append("flat-color-albedo")
        elif name == "roughness":
            if stdev < UNIFORM_STDEV_THRESHOLD:
                issues.append("uniform-roughness")
        elif name == "metallic":
            if stdev < UNIFORM_STDEV_THRESHOLD:
                issues.append("uniform-metallic")
        elif name == "normal":
            # Normal map XY magnitude (offset from 128)
            try:
                if arr.ndim == 3 and arr.shape[-1] >= 2:
                    xy = arr[..., :2].astype("int32") - 128
                    xy_mag_mean = float(np.abs(xy).mean())
                else:
                    xy_mag_mean = 0.0
                s["xy_magnitude_mean"] = round(xy_mag_mean, 2)
                if xy_mag_mean < NORMAL_XY_MIN:
                    issues.append("low-detail-normal")
            except Exception:
                pass
        if mean > UNINIT_MEAN and stdev < UNINIT_STDEV:
            issues.append(f"uninitialised-{name}")
        stats[name] = s

    if not present:
        issues.append("no_textures")

    return {
        "textures_present": present,
        "issues": issues,
        "stats": stats,
    }


def _merge(meta_path: Path, payload: dict) -> None:
    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "quality",
         "--data", json.dumps({"textures": payload})],
        check=True,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    result = check(Path(os.path.expanduser(args.input)))
    _merge(Path(os.path.expanduser(args.meta)), result)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        n = len(result["textures_present"])
        if "no_textures" in result["issues"]:
            print("[texture-check] Textures: none embedded (vertex colours only)")
        elif not result["issues"]:
            print(f"[texture-check] Textures: {n} map(s), all look healthy")
        else:
            print(f"[texture-check] Textures: {n} map(s) — ⚠ issues: " + ", ".join(result["issues"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
