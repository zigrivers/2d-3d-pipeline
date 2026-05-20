#!/usr/bin/env python3
"""v0.3 — UV + game-engine validation.

Checks AI-generated meshes for the production-grade issues game
engines actually trip over (cited by codex in the v3 MMR review):
"spaghetti" UVs with hundreds of islands, normal-map handedness
mismatching Unity vs Unreal, non-PoT texture sizes, missing tangents,
exotic embedded image formats.

Writes `quality.uv` and `quality.engine` sections to the per-asset
meta.json.

Usage:
    game_asset_check.py --input PATH.glb --meta PATH
                        [--engine {unity,unreal,none}] [--json]
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

ISLAND_WARN = 50
ISLAND_ERROR = 500
OCCUPANCY_WARN = 0.40


def _imports():
    try:
        import trimesh  # type: ignore
        import numpy as np  # type: ignore
        return trimesh, np
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); aborting.", file=sys.stderr)
        sys.exit(2)


def _uv_analysis(mesh, np) -> dict:
    """Best-effort UV island count + occupancy ratio."""
    uv = getattr(mesh.visual, "uv", None) if hasattr(mesh, "visual") else None
    if uv is None or len(uv) == 0:
        return {"has_uv": False}
    in_bounds = bool(((uv >= 0.0) & (uv <= 1.0)).all())
    # Approx island count: connected components of the FACE adjacency graph
    # restricted to faces sharing UV coords. Cheap proxy: face_adjacency_unshared.
    try:
        import networkx as nx  # type: ignore
        g = nx.Graph()
        g.add_nodes_from(range(len(mesh.faces)))
        # Edges between faces are added when their shared edge has matching UVs
        # at both vertices. Implement cheaply via face_adjacency.
        for a, b in mesh.face_adjacency.tolist():
            # If two adjacent faces share the SAME UV at the shared edge's
            # vertices, they belong to the same island. Use rough equality.
            fa = mesh.faces[a]
            fb = mesh.faces[b]
            shared = set(fa.tolist()) & set(fb.tolist())
            same = True
            for v in shared:
                # Find the corresponding UV index. trimesh's uv is indexed
                # by vertex, not by face-corner, so we just compare uv[v].
                pass  # trivially same when uv is per-vertex
            if same:
                g.add_edge(a, b)
        island_count = nx.number_connected_components(g)
    except ImportError:
        # No networkx — use a tiny disjoint-set
        parent = list(range(len(mesh.faces)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for a, b in mesh.face_adjacency.tolist():
            union(a, b)
        roots = {find(i) for i in range(len(mesh.faces))}
        island_count = len(roots)

    # Occupancy = bbox area of all UV points / total UV space.
    if len(uv) > 0:
        u_min, v_min = uv.min(axis=0)
        u_max, v_max = uv.max(axis=0)
        bbox_area = float((u_max - u_min) * (v_max - v_min))
        occupancy = max(0.0, min(1.0, bbox_area))
    else:
        occupancy = 0.0

    return {
        "has_uv": True,
        "island_count": int(island_count),
        "occupancy_ratio": round(float(occupancy), 3),
        "has_overlap": None,  # full overlap detection is expensive; skip
        "in_bounds": in_bounds,
    }


def _engine_analysis(mesh, np, engine: str) -> dict:
    out: dict = {
        "tangents_present": None,
        "normal_handedness": None,
        "texture_sizes": [],
        "all_power_of_two": True,
        "embedded_formats": [],
        "color_space_hints": {},
    }
    # Tangents
    try:
        # trimesh doesn't always populate tangents; check the visual
        out["tangents_present"] = bool(
            hasattr(mesh, "vertex_tangents") and len(getattr(mesh, "vertex_tangents", []) or [])
        )
    except Exception:
        out["tangents_present"] = None

    # Textures: sizes + format
    material = getattr(getattr(mesh, "visual", None), "material", None)
    if material is not None:
        for attr in ("baseColorTexture", "normalTexture", "metallicRoughnessTexture",
                     "roughnessTexture", "metallicTexture"):
            img = getattr(material, attr, None)
            if img is None or not hasattr(img, "size"):
                continue
            w, h = img.size
            out["texture_sizes"].append([w, h])
            pot = (w & (w - 1) == 0) and (h & (h - 1) == 0)
            if not pot:
                out["all_power_of_two"] = False
            fmt = (getattr(img, "format", None) or "").lower()
            if fmt:
                out["embedded_formats"].append(fmt)
            # Color space hint
            cs_key = "albedo" if attr == "baseColorTexture" else (
                "normal" if attr == "normalTexture" else "linear"
            )
            out["color_space_hints"][attr] = "sRGB" if cs_key == "albedo" else "linear"

    # Normal handedness: sample 1000 pixels from the normal map's blue channel.
    # Unity expects -Y normals, Unreal expects +Y. Determine from the median sign of (G - 128).
    if material is not None:
        nrm = getattr(material, "normalTexture", None)
        if nrm is not None and hasattr(nrm, "convert"):
            try:
                arr = np.asarray(nrm.convert("RGB"))
                if arr.size and arr.ndim == 3 and arr.shape[-1] >= 2:
                    g = arr[..., 1].astype("int32") - 128
                    sign = float(np.median(g))
                    out["normal_handedness"] = "y_plus" if sign > 0 else "y_minus"
            except Exception:
                pass

    # Engine-specific mismatch flag
    if engine in ("unity", "unreal") and out["normal_handedness"]:
        expected = "y_minus" if engine == "unity" else "y_plus"
        out["matches_engine"] = (out["normal_handedness"] == expected)
        out["engine_target"] = engine
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--engine", choices=["unity", "unreal", "none"], default="none")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    trimesh, np = _imports()
    input_path = Path(os.path.expanduser(args.input))
    meta_path = Path(os.path.expanduser(args.meta))

    try:
        mesh = trimesh.load(str(input_path), force="mesh")
    except Exception as e:
        print(f"ERROR: load failed: {e}", file=sys.stderr)
        return 1

    uv = _uv_analysis(mesh, np)
    engine = _engine_analysis(mesh, np, args.engine)
    payload = {"uv": uv, "engine": engine}

    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "quality",
         "--data", json.dumps(payload)],
        check=False,
    )

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if not uv.get("has_uv"):
            print("[game-check] ⚠ no UV channel — asset cannot take textures in-engine")
        else:
            ic = uv["island_count"]
            occ = uv.get("occupancy_ratio", 0.0)
            mark = "✓"
            if ic > ISLAND_ERROR:
                mark = "✗"
            elif ic > ISLAND_WARN or occ < OCCUPANCY_WARN:
                mark = "⚠"
            print(f"[game-check] UVs: {mark} {ic} texture patch(es), "
                  f"{int(occ * 100)}% UV occupancy")
        if engine.get("normal_handedness") and engine.get("engine_target"):
            if engine.get("matches_engine"):
                print(f"[game-check] Engine: ✓ normals match {engine['engine_target']}")
            else:
                print(f"[game-check] Engine: ⚠ normal handedness is "
                      f"{engine['normal_handedness']}; "
                      f"{engine['engine_target']} expects the opposite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
