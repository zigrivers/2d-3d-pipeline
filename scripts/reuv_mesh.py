#!/usr/bin/env python3
"""v0.4 — xatlas UV re-unwrap (item 23).

Re-unwraps a mesh's UVs from scratch via xatlas when item 13's UV
check (game_asset_check.py) reports low occupancy or a high island
count. Warn-suggested, never automatic — the caller (generate.sh
--reuv) decides when to invoke this, and only on meshes with no
baked image textures yet (re-unwrapping invalidates any existing
UV-mapped texture, since the new layout won't match the old pixels).

Known ceiling: rebuilds the mesh's visual from scratch around the new
UVs (trimesh.visual.TextureVisuals with no image yet — ready for a
later texture.sh --mode paint pass). Vertex colors, if present on the
input, are NOT preserved — glTF's vertex-color + baseColorTexture
combination is real but poorly supported round-trip in trimesh export,
and reuv's whole point is "about to be freshly textured" objects, not
"the vertex colors are the final look" ones. A clear warning is
printed and recorded when input vertex colors are discarded.

Usage:
    reuv_mesh.py --input PATH.glb --output PATH.glb --meta PATH [--json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
META_HELPER = SCRIPT_DIR / "meta_helper.py"


def _imports():
    try:
        import numpy as np
        import trimesh
        import xatlas
        return trimesh, np, xatlas
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); install xatlas in pipeline-tools-env.", file=sys.stderr)
        sys.exit(2)


def _occupancy(uv, np) -> float:
    if uv is None or len(uv) == 0:
        return 0.0
    u_min, v_min = uv.min(axis=0)
    u_max, v_max = uv.max(axis=0)
    return max(0.0, min(1.0, float((u_max - u_min) * (v_max - v_min))))


def _merge_meta(meta_path: Path, payload: dict) -> None:
    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "cleanup", "--data", json.dumps(payload)],
        check=False, capture_output=True,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    trimesh, np, xatlas = _imports()

    mesh = trimesh.load(Path(args.input).expanduser(), force="mesh")
    original_uv = getattr(getattr(mesh, "visual", None), "uv", None)
    occ_before = _occupancy(original_uv, np)
    had_vertex_colors = (
        isinstance(mesh.visual, trimesh.visual.color.ColorVisuals)
        and mesh.visual.vertex_colors is not None
    )

    positions = np.asarray(mesh.vertices, dtype=np.float32)
    indices = np.asarray(mesh.faces, dtype=np.uint32)
    normals = np.asarray(mesh.vertex_normals, dtype=np.float32)

    t0 = time.time()
    vmapping, new_indices, new_uvs = xatlas.parametrize(positions, indices, normals)
    duration = round(time.time() - t0, 2)

    new_vertices = positions[vmapping]
    new_mesh = trimesh.Trimesh(vertices=new_vertices, faces=new_indices, process=False)
    new_mesh.visual = trimesh.visual.TextureVisuals(uv=new_uvs)
    new_mesh.export(Path(args.output).expanduser())

    occ_after = _occupancy(new_uvs, np)

    if had_vertex_colors:
        print(
            "[reuv] WARNING: input had vertex colors; the re-unwrapped output "
            "does not preserve them (known ceiling — see script docstring).",
            file=sys.stderr,
        )

    payload = {
        "reuv": {
            "applied": True,
            "occupancy_before": round(occ_before, 3),
            "occupancy_after": round(occ_after, 3),
            "vertex_colors_discarded": had_vertex_colors,
            "duration_seconds": duration,
        }
    }
    _merge_meta(Path(args.meta).expanduser(), payload)

    if args.json:
        print(json.dumps(payload["reuv"], sort_keys=True))
    else:
        print(f"[reuv] occupancy {occ_before:.1%} -> {occ_after:.1%} ({duration}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
