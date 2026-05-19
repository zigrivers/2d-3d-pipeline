#!/usr/bin/env python3
"""Texture-inspection helper for texture.sh.

Two input shapes are supported:

  * Image file (.png / .jpg / .jpeg / .webp): reports width / height /
    mode / file size. Uses PIL when available, falls back to a tiny
    stdlib PNG/JPEG header parser otherwise.

  * Binary glTF (.glb): reads the JSON chunk directly with struct and
    counts meshes / materials / textures / images.

  * Directory: counts image files inside and reports their dimensions
    where possible.

Emits a single JSON object on stdout with the fields texture.sh expects.

Why not Blender? Blender works but starts in ~3-5s. For a quick "what's
in this GLB?" call we'd rather not pay that. This helper is honest about
what it can't determine (e.g. PBR maps) and leaves those fields null
for a later, deeper pass.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

GLB_JSON_CHUNK = 0x4E4F534A  # "JSON" little-endian
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tga", ".bmp"}


def _image_dims_pil(path: Path) -> tuple[int, int, str] | None:
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            return im.width, im.height, im.mode
    except Exception:
        return None


def _png_dims(path: Path) -> tuple[int, int, str] | None:
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return int(width), int(height), "png"


def _jpeg_dims(path: Path) -> tuple[int, int, str] | None:
    with open(path, "rb") as f:
        if f.read(2) != b"\xff\xd8":
            return None
        while True:
            byte = f.read(1)
            while byte == b"\xff":
                byte = f.read(1)
            marker = byte[0] if byte else 0
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                f.read(3)
                height, width = struct.unpack(">HH", f.read(4))
                return int(width), int(height), "jpeg"
            seg_len_bytes = f.read(2)
            if len(seg_len_bytes) < 2:
                return None
            seg_len = struct.unpack(">H", seg_len_bytes)[0]
            f.read(seg_len - 2)


def _image_dims(path: Path) -> tuple[int, int, str] | None:
    dims = _image_dims_pil(path)
    if dims:
        return dims
    suffix = path.suffix.lower()
    if suffix == ".png":
        return _png_dims(path)
    if suffix in (".jpg", ".jpeg"):
        return _jpeg_dims(path)
    return None


def _inspect_image(path: Path) -> dict[str, Any]:
    dims = _image_dims(path)
    return {
        "kind": "image",
        "input": str(path),
        "file_size_bytes": path.stat().st_size,
        "width": dims[0] if dims else None,
        "height": dims[1] if dims else None,
        "mode": dims[2] if dims else None,
    }


def _inspect_glb(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        magic = f.read(12)
        if magic[:4] != b"glTF":
            return {"kind": "glb", "input": str(path),
                    "error": "not a binary glTF (magic mismatch)"}
        chunk_len, chunk_type = struct.unpack("<II", f.read(8))
        if chunk_type != GLB_JSON_CHUNK:
            return {"kind": "glb", "input": str(path),
                    "error": f"first chunk is not JSON (got 0x{chunk_type:08x})"}
        try:
            gltf = json.loads(f.read(chunk_len))
        except json.JSONDecodeError as exc:
            return {"kind": "glb", "input": str(path),
                    "error": f"JSON chunk parse failed: {exc}"}
    return {
        "kind": "glb",
        "input": str(path),
        "file_size_bytes": path.stat().st_size,
        "mesh_count": len(gltf.get("meshes", [])),
        "material_count": len(gltf.get("materials", [])),
        "texture_count": len(gltf.get("textures", [])),
        "image_count": len(gltf.get("images", [])),
        "node_count": len(gltf.get("nodes", [])),
        "scene_count": len(gltf.get("scenes", [])),
        "asset_version": gltf.get("asset", {}).get("version", ""),
        "generator": gltf.get("asset", {}).get("generator", ""),
        # Subjective fields we can't infer from JSON alone — leave null.
        "pbr_maps_present": None,
    }


def _inspect_dir(path: Path) -> dict[str, Any]:
    files = sorted(
        p for p in path.iterdir()
        if p.is_file() and p.suffix.lower() in IMG_EXTS
    )
    images: list[dict[str, Any]] = []
    for p in files:
        d = _image_dims(p)
        images.append({
            "path": str(p),
            "file_size_bytes": p.stat().st_size,
            "width": d[0] if d else None,
            "height": d[1] if d else None,
            "mode": d[2] if d else None,
        })
    return {
        "kind": "directory",
        "input": str(path),
        "image_count": len(images),
        "images": images,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--json-only", action="store_true",
                   help="Print only the JSON object (default).")
    args = p.parse_args()

    in_path = Path(os.path.expanduser(args.input))
    if not in_path.exists():
        print(json.dumps({"kind": "error",
                          "error": f"input not found: {in_path}"}))
        return 1

    if in_path.is_dir():
        result = _inspect_dir(in_path)
    elif in_path.suffix.lower() == ".glb":
        result = _inspect_glb(in_path)
    elif in_path.suffix.lower() in IMG_EXTS:
        result = _inspect_image(in_path)
    else:
        result = {
            "kind": "unknown",
            "input": str(in_path),
            "error": f"unsupported extension: {in_path.suffix}",
        }

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
