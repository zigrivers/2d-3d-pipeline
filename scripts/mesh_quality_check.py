#!/usr/bin/env python3
"""v0.3 — mesh watertight + scale sanity check.

Loads a GLB / STL with trimesh and reports:
  - is_watertight + boundary edge / hole count
  - is_winding_consistent
  - scale sanity (longest dimension within a "sane" range)

Results merge into the per-asset meta.json `quality.manifold` and
`quality.scale` sections via meta_helper.py.

Called from generate.sh after clean_asset.py finishes, and from
prepare_for_print.py after the STL is written.

Usage:
    mesh_quality_check.py --input PATH --meta PATH [--mode {normalized,mm}]
                          [--json]

--mode normalized (default): the input is the cleaned GLB whose
longest dim has been normalized to ~1.0. Scale sanity is "is the
longest dim in [0.001, 1000]?" — catches generator outputs that are
microscopic or astronomically large.

--mode mm: the input is the printable STL in millimetres. Scale
sanity is "is the longest dim in [1.0, 1000.0]?" — catches outputs
that would silently print at 0.5mm or 5m scales.
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

NORMALIZED_SANE_MIN = 0.001
NORMALIZED_SANE_MAX = 1000.0
MM_SANE_MIN = 1.0
MM_SANE_MAX = 1000.0


def _check_trimesh() -> "module":
    try:
        import trimesh  # type: ignore
        return trimesh
    except ImportError:
        print(
            "ERROR: trimesh not installed. Activate pipeline-tools-env first:\n"
            "    source ~/3d-pipeline/pipeline-tools-env/bin/activate",
            file=sys.stderr,
        )
        sys.exit(2)


def check(input_path: Path, mode: str) -> dict:
    trimesh = _check_trimesh()
    try:
        mesh = trimesh.load(str(input_path), force="mesh")
    except Exception as e:
        return {
            "manifold": {"error": f"load_failed: {e}"},
            "scale": {"error": "load_failed"},
        }

    is_watertight = bool(mesh.is_watertight)
    is_winding_consistent = bool(mesh.is_winding_consistent)

    # Boundary edges = edges that appear in exactly one face. Count by
    # finding unique edges that aren't in face_adjacency_edges (shared edges).
    boundary_edges = 0
    try:
        import numpy as np  # type: ignore
        # edges_unique: Nx2 unique edges; face_adjacency_edges: edges shared by
        # neighbouring faces (always present in a closed surface). The set
        # difference is the boundary.
        unique = {tuple(sorted(e)) for e in mesh.edges_unique.tolist()}
        shared = {tuple(sorted(e)) for e in mesh.face_adjacency_edges.tolist()}
        boundary_edges = len(unique - shared)
    except Exception:
        # Fallback: trimesh.outline() returns a Path3D whose entities are
        # the boundary loops. The entity count is a rough proxy for holes.
        try:
            outline = mesh.outline()
            boundary_edges = int(sum(len(e.points) for e in outline.entities))
        except Exception:
            boundary_edges = 0

    # Approximate hole count: each hole boundary is a closed loop, so a
    # reasonable proxy is "number of connected components of boundary
    # edges". We don't have that cheaply; use the outline-entity count
    # when available, otherwise fall back to a coarse estimate.
    hole_count = 0
    if not is_watertight:
        try:
            outline = mesh.outline()
            hole_count = int(len(outline.entities)) if outline else 1
        except Exception:
            hole_count = max(1, boundary_edges // 6)

    extents = mesh.extents if mesh.extents is not None else [0.0, 0.0, 0.0]
    longest = float(max(extents))

    if mode == "mm":
        in_range = MM_SANE_MIN <= longest <= MM_SANE_MAX
        scale_block = {
            "longest_dim_mm": round(longest, 3),
            "in_sane_range": bool(in_range),
            "mode": "mm",
        }
    else:
        in_range = NORMALIZED_SANE_MIN <= longest <= NORMALIZED_SANE_MAX
        scale_block = {
            "longest_dim_normalized": round(longest, 4),
            "in_sane_range": bool(in_range),
            "mode": "normalized",
        }

    return {
        "manifold": {
            "is_watertight": is_watertight,
            "is_winding_consistent": is_winding_consistent,
            "boundary_edges": int(boundary_edges),
            "hole_count": int(hole_count),
        },
        "scale": scale_block,
    }


def _merge_into_meta(meta_path: Path, payload: dict) -> None:
    """Each sub-key of `payload` is a top-level meta section under `quality`.
    We merge them as 'quality' but our helper merges per-section. To preserve
    keys we already had under quality, merge a quality dict containing
    manifold + scale."""
    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "quality",
         "--data", json.dumps(payload)],
        check=True,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True, help="Path to a GLB or STL")
    p.add_argument("--meta", required=True, help="Path to <output>.meta.json")
    p.add_argument("--mode", choices=["normalized", "mm"], default="normalized",
                   help="Scale-sanity mode (default: normalized)")
    p.add_argument("--json", action="store_true", help="Emit JSON result on stdout")
    args = p.parse_args()

    input_path = Path(os.path.expanduser(args.input))
    meta_path = Path(os.path.expanduser(args.meta))

    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        return 1

    result = check(input_path, args.mode)
    _merge_into_meta(meta_path, result)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        manifold = result["manifold"]
        if "error" in manifold:
            print(f"[mesh-check] could not analyze mesh: {manifold['error']}", file=sys.stderr)
            return 0
        wt = manifold["is_watertight"]
        hc = manifold["hole_count"]
        if wt:
            print(f"[mesh-check] Mesh: fully sealed (good for printing) — 0 holes")
        else:
            print(f"[mesh-check] Mesh: {hc} small gap(s) in the surface (may still print)")
        scale = result["scale"]
        if "error" in scale:
            print(f"[mesh-check] scale check unavailable", file=sys.stderr)
        elif not scale["in_sane_range"]:
            if scale["mode"] == "mm":
                dim = scale["longest_dim_mm"]
                print(f"[mesh-check] Scale: ⚠ longest dim {dim} mm is outside the sane range ({MM_SANE_MIN}–{MM_SANE_MAX} mm)")
            else:
                dim = scale["longest_dim_normalized"]
                print(f"[mesh-check] Scale: ⚠ longest dim {dim} is outside the sane normalized range")
    return 0


if __name__ == "__main__":
    sys.exit(main())
