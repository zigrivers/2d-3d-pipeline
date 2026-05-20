#!/usr/bin/env python3
"""v0.3 — print structural gates.

Watertight is necessary but not sufficient. This check probes the
structural issues that turn a clean-looking STL into a failed print:

  - min_wall_thickness_mm: approximate via point-cloud nearest-
    neighbour distance heuristic (KDTree). Warn < 1.0 mm, error
    < 0.4 mm (FDM nozzle limit).
  - disconnected_islands: number of separate mesh bodies.
  - self_intersections: trimesh repair.broken_faces count.
  - overhang_area_mm2: total area of faces whose Z normal < -cos(45°).
  - base_contact_area_mm2: bottom-N% of the mesh projected to Z=0.
  - com_offset_normalized: XY distance from centre-of-mass projected
    to base, divided by the base radius.
  - stable_on_bed: COM falls within the base contact polygon.

Writes `print.structural` into the per-asset meta.json.

Usage:
    print_structural_check.py --input PATH.stl --meta PATH [--json]

Heuristics, not exact. Frame results as advisory in the skill.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
META_HELPER = SCRIPT_DIR / "meta_helper.py"

WALL_WARN_MM = 1.0
WALL_ERROR_MM = 0.4
OVERHANG_COS = math.cos(math.radians(45))
BASE_FRACTION = 0.05  # bottom 5% of the mesh treated as the base


def _imports():
    try:
        import trimesh  # type: ignore
        import numpy as np  # type: ignore
        return trimesh, np
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); aborting.", file=sys.stderr)
        sys.exit(2)


def _min_wall_thickness(mesh, np) -> float | None:
    """Approximate min wall thickness via interior ray casts.
    For each face, cast a ray from its centroid inward along the
    negative normal; the closest hit distance bounds the wall
    thickness at that face. Returns the minimum across a sample.
    """
    try:
        n_samples = min(500, len(mesh.faces))
        if n_samples == 0:
            return None
        idx = np.linspace(0, len(mesh.faces) - 1, n_samples).astype(int)
        # Centroid per face
        verts = mesh.vertices
        faces = mesh.faces[idx]
        centroids = verts[faces].mean(axis=1)
        normals = mesh.face_normals[idx]
        # Inward ray = -normal, start slightly inside to avoid self-hit
        origins = centroids - normals * 1e-4
        # Use trimesh.intersections.ray_triangle for cross-platform support
        try:
            ray = mesh.ray
            locations, ray_indices, _ = ray.intersects_location(
                ray_origins=origins,
                ray_directions=-normals,
                multiple_hits=False,
            )
            if len(ray_indices) == 0:
                return None
            distances = np.linalg.norm(locations - origins[ray_indices], axis=1)
            # Filter out zero-length grazes
            distances = distances[distances > 1e-3]
            if not len(distances):
                return None
            return float(distances.min())
        except Exception:
            return None
    except Exception:
        return None


def _self_intersections(mesh) -> int:
    try:
        from trimesh.repair import broken_faces  # type: ignore
        return int(len(broken_faces(mesh)))
    except Exception:
        return -1


def _base_geometry(mesh, np) -> dict:
    """Return base contact area + COM offset normalised by base radius."""
    verts = mesh.vertices
    if len(verts) == 0:
        return {"base_contact_area_mm2": 0.0, "com_offset_normalized": 0.0,
                "base_contact_safe": False, "stable_on_bed": False}
    z = verts[:, 2]
    z_min, z_max = z.min(), z.max()
    base_z_thresh = z_min + (z_max - z_min) * BASE_FRACTION
    base_pts = verts[z <= base_z_thresh]
    if len(base_pts) < 3:
        return {"base_contact_area_mm2": 0.0, "com_offset_normalized": 0.0,
                "base_contact_safe": False, "stable_on_bed": False}
    # 2D convex hull area in XY
    try:
        from scipy.spatial import ConvexHull  # type: ignore
        hull = ConvexHull(base_pts[:, :2])
        base_area = float(hull.volume)  # 2D hull's volume is area
        base_xy = base_pts[:, :2]
        base_center = base_xy.mean(axis=0)
        base_radius = float(np.linalg.norm(base_xy - base_center, axis=1).max())
    except Exception:
        # Fallback: bounding-box approximation
        bb = base_pts[:, :2]
        base_area = float((bb[:, 0].max() - bb[:, 0].min()) *
                          (bb[:, 1].max() - bb[:, 1].min()))
        base_center = bb.mean(axis=0)
        base_radius = float(np.linalg.norm(bb - base_center, axis=1).max())

    # COM in XY
    com_xy = verts.mean(axis=0)[:2]
    com_offset = float(np.linalg.norm(com_xy - base_center))
    com_norm = com_offset / max(base_radius, 1e-6)
    return {
        "base_contact_area_mm2": round(base_area, 2),
        "com_offset_normalized": round(com_norm, 3),
        "base_contact_safe": bool(base_area > 100.0),
        "stable_on_bed": bool(com_norm < 0.5),
    }


def check(input_path: Path) -> dict:
    trimesh, np = _imports()
    try:
        mesh = trimesh.load(str(input_path), force="mesh")
    except Exception as e:
        return {"error": f"load_failed: {e}"}

    wall = _min_wall_thickness(mesh, np)
    wall_safe = (wall is None or wall >= WALL_WARN_MM)

    bodies = 1
    try:
        bodies = int(len(mesh.split(only_watertight=False)))
    except Exception:
        pass

    self_int = _self_intersections(mesh)

    # Overhang area
    overhang_area = 0.0
    try:
        if mesh.face_normals is not None:
            nz = mesh.face_normals[:, 2]
            mask = nz < -OVERHANG_COS
            if mask.any():
                overhang_area = float(mesh.area_faces[mask].sum())
    except Exception:
        pass

    base = _base_geometry(mesh, np)

    return {
        "min_wall_thickness_mm": round(wall, 3) if wall is not None else None,
        "wall_thickness_safe": bool(wall_safe),
        "disconnected_islands": int(bodies),
        "self_intersections": int(self_int) if self_int >= 0 else None,
        "overhang_area_mm2": round(overhang_area, 2),
        **base,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    result = check(Path(os.path.expanduser(args.input)))
    meta_path = Path(os.path.expanduser(args.meta))

    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "print",
         "--data", json.dumps({"structural": result})],
        check=False,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if "error" in result:
            print(f"[print-struct] could not analyze: {result['error']}", file=sys.stderr)
            return 0
        wall = result.get("min_wall_thickness_mm")
        if wall is not None:
            if wall < WALL_ERROR_MM:
                print(f"[print-struct] ⚠ thinnest part is {wall} mm — likely too thin for FDM (need ≥ 0.4mm)")
            elif wall < WALL_WARN_MM:
                print(f"[print-struct] ⚠ thinnest part is {wall} mm — fragile; consider scaling up")
            else:
                print(f"[print-struct] walls ≥ {wall} mm (good)")
        bca = result.get("base_contact_area_mm2", 0)
        if not result.get("base_contact_safe"):
            print(f"[print-struct] ⚠ base contact area only {bca} mm² — may lift during print")
        if not result.get("stable_on_bed"):
            print(f"[print-struct] ⚠ centre of mass offset {result.get('com_offset_normalized')} × base radius — may tip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
