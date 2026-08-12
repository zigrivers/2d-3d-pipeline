#!/usr/bin/env python3
"""v0.4 item 25 -- opt-in quad retopo via QuadWild bi-MDF.

Two-step external CLI pipeline (`quadwild` -> `quad_from_patches`, both
must be on PATH -- prebuilt macOS arm64+x86_64 binaries from
https://github.com/cgg-bern/quadwild-bimdf/releases, GPL-3 tool, no
weights, outputs unaffected) converts a clean GLB's mesh into a
quad-dominant retopology. Output has no UV layout at all (confirmed by
inspecting QuadWild's own OBJ output -- zero `vt` lines), so callers
should follow this with `generate.sh --reuv` before any texture pass.

Caller (generate.sh --retopo quad) is responsible for refusing to run
this on a mesh that already has baked textures -- retopo discards
topology and any UVs unconditionally.

Usage:
    retopo_quad.py --input PATH.glb --output PATH.glb --meta PATH
                    [--timeout SECONDS] [--json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
META_HELPER = SCRIPT_DIR / "meta_helper.py"

# Bundled QuadWild config, trimmed to exactly what the prep + quadrangulation
# steps below reference (verified live on this Studio, R3.3 spike -- a real
# icosphere fixture came out 100% quad faces and watertight after merge).
PREP_CONFIG = """do_remesh 1
sharp_feature_thr 35
alpha 0.01
scaleFact 1
"""

MAIN_CONFIG = """alpha 0.005
ilpMethod 1
timeLimit 200
gapLimit 0.0
callbackTimeLimit 8 3.00 5.000 10.0 20.0 30.0 60.0 90.0 120.0
callbackGapLimit 8 0.005 0.02 0.05 0.10 0.15 0.20 0.25 0.3
minimumGap 0.4
isometry 1
regularityQuadrilaterals 1
regularityNonQuadrilaterals 1
regularityNonQuadrilateralsWeight 0.9
alignSingularities 0
alignSingularitiesWeight 0.1
repeatLosingConstraintsIterations 1
repeatLosingConstraintsQuads 0
repeatLosingConstraintsNonQuads 0
repeatLosingConstraintsAlign 0
hardParityConstraint 1
scaleFact 1
fixedChartClusters 0
useFlowSolver 1
flow_config_filename "config/main_config/flow_virtual_simple.json"
satsuma_config_filename "config/satsuma/lemon.json"
"""

FLOW_VIRTUAL_SIMPLE_JSON = """{
    "paired_half_target": "simple",
    "paired_resolve_new_targets": true,
    "paired_initial": {
        "iso_weight": 1,
        "iso_objective": "quad",
        "unalign_weight": 2.0
    },
    "paired_resolve": {
        "iso_weight": 1,
        "iso_objective": "abs",
        "unalign_weight": 4.0
    }
}
"""

SATSUMA_LEMON_JSON = """{
    "double_cover": {
        "max_deviation": 5,
        "matching_solver": "Lemon",
        "evening_mode": "MST",
        "method": "HalfAsymmetric",
        "verbosity": 1
    },
    "refine_with_matching": true,
    "matching_solver": "Lemon",
    "refinement_maxdev_min": 2,
    "refinement_maxdev_max": 2,
    "deviation_limit": "NodeThroughflow",
    "verbosity": 2
}
"""


def _write_configs(workdir: Path) -> None:
    (workdir / "config" / "prep_config").mkdir(parents=True)
    (workdir / "config" / "main_config").mkdir(parents=True)
    (workdir / "config" / "satsuma").mkdir(parents=True)
    (workdir / "config" / "prep_config" / "basic_setup.txt").write_text(PREP_CONFIG)
    (workdir / "config" / "main_config" / "flow_noalign_lemon.txt").write_text(MAIN_CONFIG)
    (workdir / "config" / "main_config" / "flow_virtual_simple.json").write_text(FLOW_VIRTUAL_SIMPLE_JSON)
    (workdir / "config" / "satsuma" / "lemon.json").write_text(SATSUMA_LEMON_JSON)


def _read_obj_faces(path: Path):
    """Return (vertices, triangulated_faces, quad_count, tri_count).

    QuadWild's OBJ output is a Meshlab-style export split across several
    `usemtl` material groups that all share one vertex list.
    trimesh.load() triangulates AND splits it into a per-material Scene,
    which loses both the quad-face arity and the shared-vertex topology a
    real watertightness check needs -- parsed directly here instead.
    """
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    quad_count = 0
    tri_count = 0
    for line in path.read_text().splitlines():
        if line.startswith("v "):
            x, y, z = line.split()[1:4]
            verts.append([float(x), float(y), float(z)])
        elif line.startswith("f "):
            idxs = [int(tok.split("/")[0]) - 1 for tok in line.split()[1:]]
            if len(idxs) == 4:
                quad_count += 1
                faces.append([idxs[0], idxs[1], idxs[2]])
                faces.append([idxs[0], idxs[2], idxs[3]])
            elif len(idxs) == 3:
                tri_count += 1
                faces.append(idxs)
    return verts, faces, quad_count, tri_count


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
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    quadwild_bin = shutil.which("quadwild")
    qfp_bin = shutil.which("quad_from_patches")
    if not quadwild_bin or not qfp_bin:
        print("ERROR: quadwild and/or quad_from_patches not found on PATH.", file=sys.stderr)
        print("  Install: https://github.com/cgg-bern/quadwild-bimdf/releases (macos-binaries.zip)", file=sys.stderr)
        return 2

    import numpy as np
    import trimesh

    t0 = time.time()
    mesh = trimesh.load(Path(args.input).expanduser(), force="mesh")
    faces_before = len(mesh.faces)

    with tempfile.TemporaryDirectory(prefix="quadwild_retopo_") as tmp:
        workdir = Path(tmp)
        _write_configs(workdir)
        obj_in = workdir / "mesh_in.obj"
        mesh.export(obj_in)

        # Real finding (R3.3 spike): quad_from_patches's exit code is not a
        # reliable success signal -- a genuinely successful run (full log
        # through SMOOTHING/save) has been observed to exit 1, and a
        # genuine failure (missing sidecar patch files) has been observed
        # to exit 0. Whether the expected output file exists is the only
        # signal actually checked here for both binaries.
        try:
            r1 = subprocess.run(
                [quadwild_bin, str(obj_in), "2", "config/prep_config/basic_setup.txt"],
                cwd=workdir, capture_output=True, text=True, timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            print(f"ERROR: quadwild timed out after {args.timeout}s (step 1: prep/remesh).", file=sys.stderr)
            return 3

        rem_p0 = workdir / "mesh_in_rem_p0.obj"
        if not rem_p0.exists():
            print(f"ERROR: quadwild did not produce mesh_in_rem_p0.obj (exit {r1.returncode}):\n"
                  f"{r1.stdout}\n{r1.stderr}", file=sys.stderr)
            return 1

        try:
            r2 = subprocess.run(
                [qfp_bin, str(rem_p0), "1", "config/main_config/flow_noalign_lemon.txt"],
                cwd=workdir, capture_output=True, text=True, timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            print(f"ERROR: quad_from_patches timed out after {args.timeout}s (step 2: quadrangulation).", file=sys.stderr)
            return 3

        result_candidates = sorted(workdir.glob("mesh_in_rem_p0_*_quadrangulation_smooth.obj"))
        if not result_candidates:
            result_candidates = sorted(workdir.glob("mesh_in_rem_p0_*_quadrangulation.obj"))
        if not result_candidates:
            print(f"ERROR: quad_from_patches produced no *_quadrangulation(_smooth).obj output "
                  f"(exit {r2.returncode}):\n{r2.stdout}\n{r2.stderr}", file=sys.stderr)
            return 1
        result_obj = result_candidates[-1]

        verts, faces, quad_count, tri_count = _read_obj_faces(result_obj)
        out_mesh = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=True)
        out_mesh.export(Path(args.output).expanduser())

    faces_after = len(out_mesh.faces)
    quad_fraction = round(quad_count / max(1, quad_count + tri_count), 4)
    watertight = bool(out_mesh.is_watertight)
    duration = round(time.time() - t0, 2)

    payload = {
        "retopo": {
            "method": "quadwild-bimdf",
            "faces_before": faces_before,
            "faces_after": faces_after,
            "quad_fraction": quad_fraction,
            "watertight": watertight,
            "duration_seconds": duration,
        }
    }
    _merge_meta(Path(args.meta).expanduser(), payload)

    if args.json:
        print(json.dumps(payload["retopo"], sort_keys=True))
    else:
        print(f"[retopo] {faces_before} -> {faces_after} faces, {quad_fraction * 100:.1f}% quad-sourced, "
              f"watertight={watertight}, {duration}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
