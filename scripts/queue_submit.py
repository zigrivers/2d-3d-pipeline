#!/usr/bin/env python3
"""Submit a job to the asset-pipeline queue (v0.2, experimental).

The queue is a file-based directory under the active project (or the
global workspace). Three subdirectories track lifecycle:

  queue/pending/   Jobs waiting to be claimed.
  queue/running/   Jobs a worker has atomically claimed (via mv).
  queue/done/      Successful jobs (with the worker's wrapper JSON inline).
  queue/failed/    Jobs that exited non-zero.

This script writes a single JSON file under queue/pending/<uuid>.json.
A worker (queue_worker.py) on either Mac Studio can claim it.

Why files, not SQLite: simpler to debug (cat / mv), trivially observable
(ls), no schema migrations, and `mv` rename is atomic on POSIX which
gives us multi-worker safety for free.

This is studio-tier scaffolding. On a laptop you can still submit
single-machine jobs, but the design assumption is two M3 Ultra Studios
sharing a folder (or rsync-synced folder) of pending jobs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

VALID_STAGES = ("text_to_image", "image_to_3d", "glb_to_print")


def _queue_root(assets_root: Path) -> Path:
    return assets_root / "queue"


def _ensure_queue_dirs(qr: Path) -> None:
    for sub in ("pending", "running", "done", "failed"):
        (qr / sub).mkdir(parents=True, exist_ok=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--assets-root", required=True,
                   help="Active assets root (from resolve_project_context).")
    p.add_argument("--stage", required=True, choices=VALID_STAGES)
    p.add_argument("--input", default="",
                   help="Input file (image for image_to_3d, GLB for glb_to_print) "
                        "or prompt (for text_to_image).")
    p.add_argument("--output-name", default="",
                   help="Output stem; auto-derived if empty.")
    p.add_argument("--project", default="",
                   help="Project root to pass to the wrapper via --project.")
    p.add_argument("--generator", default="",
                   help="2D model (z-image-turbo|flux-schnell|flux-dev|qwen-image) "
                        "OR 3D generator (sf3d|spar3d|trellis).")
    p.add_argument("--polycount", type=int, default=0)
    p.add_argument("--texture-resolution", type=int, default=0)
    p.add_argument("--target-size-mm", type=float, default=0.0,
                   help="For glb_to_print stage.")
    p.add_argument("--allow-oversize", action="store_true")
    p.add_argument("--license-bucket", default="",
                   help="Override the wrapper's auto-detected bucket; rarely needed.")
    p.add_argument("--priority", type=int, default=50,
                   help="Lower numbers run earlier when a worker picks the next job.")
    p.add_argument("--id", default="",
                   help="Override the job UUID (mostly for tests).")
    p.add_argument("--json", action="store_true",
                   help="Emit a JSON line describing the submitted job.")
    args = p.parse_args()

    assets_root = Path(os.path.expanduser(args.assets_root))
    qr = _queue_root(assets_root)
    _ensure_queue_dirs(qr)

    if not args.input and args.stage != "text_to_image":
        print("ERROR: --input is required for non-text stages", file=sys.stderr)
        return 2

    job_id = args.id or uuid.uuid4().hex
    now = datetime.now().isoformat(timespec="seconds")

    job = {
        "id": job_id,
        "schema_version": 1,
        "stage": args.stage,
        "input": args.input,
        "output_name": args.output_name,
        "project": args.project,
        "generator": args.generator,
        "polycount": args.polycount,
        "texture_resolution": args.texture_resolution,
        "target_size_mm": args.target_size_mm,
        "allow_oversize": args.allow_oversize,
        "license_bucket": args.license_bucket,
        "priority": args.priority,
        "status": "pending",
        "claim_count": 0,
        "created": now,
        "started": None,
        "finished": None,
        "machine": None,
        "hardware_tier": None,
        "error": None,
        "result": None,
    }

    target = qr / "pending" / f"{job_id}.json"
    # Write to a tempfile in the same dir then rename (atomic on POSIX).
    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(job, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, target)

    if args.json:
        print(json.dumps({"status": "ok", "stage": "queue_submit",
                          "job_id": job_id, "job_path": str(target),
                          "queue_root": str(qr)}))
    else:
        print(f"[queue] submitted {args.stage} job {job_id} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# Silence the unused-import lint check; shutil is imported because future
# extensions to this script (bulk-submit, archive, prune) need it.
_ = shutil
_ = time
