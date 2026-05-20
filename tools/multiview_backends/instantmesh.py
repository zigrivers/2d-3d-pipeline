#!/usr/bin/env python3
"""Multi-view backend adapter — InstantMesh.

Dispatched by scripts/multiview_benchmark.py during P3.1b.

** License warning. ** InstantMesh is released under a Tencent
research license that hasn't been reviewed in this repo. The bucket
is recorded as `unclear_risky` so the benchmark rubric auto-DQs
runs by license-clarity score alone unless a separate review
(mirror of Hunyuan3D-Paint's P2.3) ships first.

If you DO want to benchmark it anyway (the data is still useful
even if you can't ship outputs commercially), the adapter runs;
just don't pick a winner on the bare numbers without resolving the
license question first.

Install layout assumed (override via env):

    $INSTANTMESH_DIR/.venv/bin/python      one venv per tool
    $INSTANTMESH_DIR/run.py                inference entrypoint

Usage (called by the harness; you don't typically run this by hand):

    instantmesh.py --views v0,v1,v2,v3 --output-glb PATH --json

Lives in /tools/, NOT subject to the canonical-vs-embedded rule.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LICENSE_BUCKET = "unclear_risky"
DEFAULT_DIR = "~/3d-pipeline/InstantMesh"


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0 if payload.get("status") == "ok" else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--views", required=True)
    p.add_argument("--output-glb", required=True)
    p.add_argument("--json", action="store_true", default=True)
    args = p.parse_args()

    im_dir = Path(os.path.expanduser(os.environ.get("INSTANTMESH_DIR", DEFAULT_DIR)))
    im_python = im_dir / ".venv" / "bin" / "python"
    im_entry = im_dir / "run.py"

    if not im_dir.exists() or not im_python.exists() or not im_entry.exists():
        return _emit({
            "status": "error",
            "error": "not_installed",
            "backend": "instantmesh",
            "license_bucket": LICENSE_BUCKET,
            "expected_dir": str(im_dir),
            "notes": ("Set INSTANTMESH_DIR or clone "
                      "https://github.com/TencentARC/InstantMesh with a "
                      ".venv + run.py at that location. Note the license "
                      "(unclear_risky) — auto-DQ in benchmark scoring "
                      "unless a separate review approves it."),
        })

    view_paths = [v.strip() for v in args.views.split(",") if v.strip()]
    output_glb = Path(os.path.expanduser(args.output_glb))
    output_glb.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        # InstantMesh's run.py typically accepts a config + an input dir of
        # views. Adapt here if the upstream interface differs. As of release
        # the canonical call is something like:
        #   python run.py configs/instant-mesh-large.yaml <input-dir> --output-path <PATH>
        # If you've installed a fork with a different shape, edit here.
        env = os.environ.copy()
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        # Place views in a single dir for the typical InstantMesh interface.
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as views_tmp:
            for i, v in enumerate(view_paths):
                shutil.copyfile(v, os.path.join(views_tmp, f"view_{i:02d}.png"))
            cp = subprocess.run(
                [str(im_python), str(im_entry),
                 "configs/instant-mesh-large.yaml",
                 views_tmp,
                 "--output_path", str(output_glb.parent),
                 "--export_texmap"],
                cwd=str(im_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
    except subprocess.TimeoutExpired:
        return _emit({
            "status": "error",
            "error": "timeout",
            "backend": "instantmesh",
            "license_bucket": LICENSE_BUCKET,
            "duration_seconds": round(time.time() - t0, 2),
        })
    except Exception as e:
        return _emit({
            "status": "error",
            "error": "dispatch_failed",
            "backend": "instantmesh",
            "license_bucket": LICENSE_BUCKET,
            "notes": str(e),
        })

    duration = round(time.time() - t0, 2)
    if cp.returncode != 0:
        return _emit({
            "status": "error",
            "error": "inference_failed",
            "backend": "instantmesh",
            "license_bucket": LICENSE_BUCKET,
            "exit_code": cp.returncode,
            "stderr_tail": (cp.stderr or "")[-500:],
            "duration_seconds": duration,
        })

    # InstantMesh writes to <output_path>/<name>/<mesh>.obj typically;
    # find the first GLB or OBJ in the output dir and call that the result.
    produced = None
    for p in output_glb.parent.rglob("*.glb"):
        produced = p
        break
    if produced is None:
        for p in output_glb.parent.rglob("*.obj"):
            produced = p
            break
    if produced is None:
        return _emit({
            "status": "error",
            "error": "no_output_produced",
            "backend": "instantmesh",
            "license_bucket": LICENSE_BUCKET,
            "expected_dir": str(output_glb.parent),
            "duration_seconds": duration,
        })
    if str(produced) != str(output_glb):
        produced.rename(output_glb)

    return _emit({
        "status": "ok",
        "backend": "instantmesh",
        "license_bucket": LICENSE_BUCKET,
        "output_glb": str(output_glb),
        "duration_seconds": duration,
        "view_count": len(view_paths),
        "license_note": "unclear_risky — DQ from benchmark scoring without separate review",
    })


if __name__ == "__main__":
    sys.exit(main())
