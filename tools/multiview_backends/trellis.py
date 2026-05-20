#!/usr/bin/env python3
"""Multi-view backend adapter — TRELLIS multi-view mode.

Dispatched by scripts/multiview_benchmark.py during P3.1b. Same shape
as the existing TRELLIS single-image integration in scripts/generate.sh:
loads from $TRELLIS_DIR (default ~/3d-pipeline/trellis-mac/) and invokes
its inference script with multiple view paths.

Usage (called by the harness; you don't typically run this by hand):

    trellis.py --views v0,v1,v2,v3 --output-glb PATH --json

License: TRELLIS is released under CC BY-NC (non_commercial). The
bucket is recorded in the JSON so the harness can DQ runs that would
otherwise be picked for commercial use.

Install layout assumed (override via env):

    $TRELLIS_DIR/.venv/bin/python      one venv per tool (Apple Silicon)
    $TRELLIS_DIR/generate.py           inference entrypoint

If your local install uses a different entrypoint or expects different
flags for multi-view, edit the python invocation below — this adapter
is intentionally close to the existing TRELLIS single-image call so
diffs are minimal.

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

LICENSE_BUCKET = "non_commercial"
DEFAULT_DIR = "~/3d-pipeline/trellis-mac"


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0 if payload.get("status") == "ok" else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--views", required=True,
                   help="Comma-separated input view image paths")
    p.add_argument("--output-glb", required=True)
    p.add_argument("--json", action="store_true", default=True)
    args = p.parse_args()

    trellis_dir = Path(os.path.expanduser(os.environ.get("TRELLIS_DIR", DEFAULT_DIR)))
    trellis_python = trellis_dir / ".venv" / "bin" / "python"
    trellis_entry = trellis_dir / "generate.py"

    if not trellis_dir.exists() or not trellis_python.exists() or not trellis_entry.exists():
        return _emit({
            "status": "error",
            "error": "not_installed",
            "backend": "trellis",
            "license_bucket": LICENSE_BUCKET,
            "expected_dir": str(trellis_dir),
            "notes": ("Set TRELLIS_DIR or install the trellis-mac repo with a .venv "
                      "+ generate.py at that location."),
        })

    view_paths = [v.strip() for v in args.views.split(",") if v.strip()]
    if len(view_paths) < 3:
        return _emit({
            "status": "error",
            "error": "insufficient_views",
            "backend": "trellis",
            "license_bucket": LICENSE_BUCKET,
            "got": len(view_paths),
            "need": 3,
        })

    output_glb = Path(os.path.expanduser(args.output_glb))
    output_glb.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        # TRELLIS multi-view interface: pass --views with multiple paths and
        # --output for the resulting GLB. If your TRELLIS fork uses different
        # flag names, edit here. The single-image flow in generate.sh today
        # calls `python generate.py INPUT --output ...`.
        env = os.environ.copy()
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        cp = subprocess.run(
            [str(trellis_python), str(trellis_entry),
             "--views", *view_paths,
             "--output", str(output_glb)],
            cwd=str(trellis_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return _emit({
            "status": "error",
            "error": "timeout",
            "backend": "trellis",
            "license_bucket": LICENSE_BUCKET,
            "duration_seconds": round(time.time() - t0, 2),
        })
    except Exception as e:
        return _emit({
            "status": "error",
            "error": "dispatch_failed",
            "backend": "trellis",
            "license_bucket": LICENSE_BUCKET,
            "notes": str(e),
        })

    duration = round(time.time() - t0, 2)
    if cp.returncode != 0:
        return _emit({
            "status": "error",
            "error": "inference_failed",
            "backend": "trellis",
            "license_bucket": LICENSE_BUCKET,
            "exit_code": cp.returncode,
            "stderr_tail": (cp.stderr or "")[-500:],
            "duration_seconds": duration,
        })

    if not output_glb.exists():
        return _emit({
            "status": "error",
            "error": "no_output_produced",
            "backend": "trellis",
            "license_bucket": LICENSE_BUCKET,
            "expected": str(output_glb),
            "duration_seconds": duration,
        })

    return _emit({
        "status": "ok",
        "backend": "trellis",
        "license_bucket": LICENSE_BUCKET,
        "output_glb": str(output_glb),
        "duration_seconds": duration,
        "view_count": len(view_paths),
    })


if __name__ == "__main__":
    sys.exit(main())
