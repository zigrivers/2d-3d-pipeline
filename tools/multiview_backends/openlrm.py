#!/usr/bin/env python3
"""Multi-view backend adapter — OpenLRM.

Dispatched by scripts/multiview_benchmark.py during P3.1b.

License: OpenLRM is Apache 2.0 — `commercial_safe`. The only fully
commercial-safe path in the benchmark; even if it doesn't win on
quality, "no license tax" is its competitive advantage.

Install layout assumed (override via env):

    $OPENLRM_DIR/.venv/bin/python      one venv per tool
    $OPENLRM_DIR/openlrm/inferrer.py   or similar inference entrypoint

OpenLRM was originally single-image. Multi-view support landed in
later releases; if your install is older, the adapter will fall
through to the not_installed error. Set OPENLRM_DIR if the repo is
elsewhere.

Usage (called by the harness; you don't typically run this by hand):

    openlrm.py --views v0,v1,v2,v3 --output-glb PATH --json

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

LICENSE_BUCKET = "commercial_safe"
DEFAULT_DIR = "~/3d-pipeline/openlrm"


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0 if payload.get("status") == "ok" else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--views", required=True)
    p.add_argument("--output-glb", required=True)
    p.add_argument("--json", action="store_true", default=True)
    args = p.parse_args()

    lrm_dir = Path(os.path.expanduser(os.environ.get("OPENLRM_DIR", DEFAULT_DIR)))
    lrm_python = lrm_dir / ".venv" / "bin" / "python"

    # OpenLRM has used different entry points across releases — accept a few.
    candidate_entries = [
        lrm_dir / "openlrm" / "inferrer.py",
        lrm_dir / "scripts" / "infer.py",
        lrm_dir / "infer.py",
    ]
    lrm_entry = next((p for p in candidate_entries if p.exists()), None)

    if not lrm_dir.exists() or not lrm_python.exists() or lrm_entry is None:
        return _emit({
            "status": "error",
            "error": "not_installed",
            "backend": "openlrm",
            "license_bucket": LICENSE_BUCKET,
            "expected_dir": str(lrm_dir),
            "candidate_entries": [str(c) for c in candidate_entries],
            "notes": ("Set OPENLRM_DIR or clone https://github.com/3DTopia/OpenLRM "
                      "with a .venv. The adapter looks for openlrm/inferrer.py, "
                      "scripts/infer.py, or infer.py in that order."),
        })

    view_paths = [v.strip() for v in args.views.split(",") if v.strip()]
    output_glb = Path(os.path.expanduser(args.output_glb))
    output_glb.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        env = os.environ.copy()
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        # OpenLRM's multi-view interface typically takes a directory of images
        # plus a model name. If your install uses a different CLI, edit here.
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as views_tmp:
            for i, v in enumerate(view_paths):
                shutil.copyfile(v, os.path.join(views_tmp, f"view_{i:02d}.png"))
            cp = subprocess.run(
                [str(lrm_python), str(lrm_entry),
                 "--source-image", views_tmp,
                 "--export-mesh", str(output_glb)],
                cwd=str(lrm_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
    except subprocess.TimeoutExpired:
        return _emit({
            "status": "error",
            "error": "timeout",
            "backend": "openlrm",
            "license_bucket": LICENSE_BUCKET,
            "duration_seconds": round(time.time() - t0, 2),
        })
    except Exception as e:
        return _emit({
            "status": "error",
            "error": "dispatch_failed",
            "backend": "openlrm",
            "license_bucket": LICENSE_BUCKET,
            "notes": str(e),
        })

    duration = round(time.time() - t0, 2)
    if cp.returncode != 0:
        return _emit({
            "status": "error",
            "error": "inference_failed",
            "backend": "openlrm",
            "license_bucket": LICENSE_BUCKET,
            "exit_code": cp.returncode,
            "stderr_tail": (cp.stderr or "")[-500:],
            "duration_seconds": duration,
        })

    # If the install uses a different output convention, allow auto-discovery
    # under output_glb.parent.
    if not output_glb.exists():
        produced = next(output_glb.parent.rglob("*.glb"), None)
        if produced is None:
            produced = next(output_glb.parent.rglob("*.obj"), None)
        if produced is None:
            return _emit({
                "status": "error",
                "error": "no_output_produced",
                "backend": "openlrm",
                "license_bucket": LICENSE_BUCKET,
                "expected": str(output_glb),
                "duration_seconds": duration,
            })
        if str(produced) != str(output_glb):
            produced.rename(output_glb)

    return _emit({
        "status": "ok",
        "backend": "openlrm",
        "license_bucket": LICENSE_BUCKET,
        "output_glb": str(output_glb),
        "duration_seconds": duration,
        "view_count": len(view_paths),
    })


if __name__ == "__main__":
    sys.exit(main())
