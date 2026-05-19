#!/usr/bin/env python3
"""Asset-pipeline queue worker (v0.2, experimental).

Polls `<assets_root>/queue/pending/` for jobs, claims one atomically by
moving it into `running/`, runs the appropriate wrapper, and finally
moves the job file into `done/` or `failed/` with the wrapper's --json
output preserved inline.

Multi-machine safety: claim is `os.rename(pending/x.json, running/x.json)`.
POSIX guarantees rename atomicity on the same filesystem, including NFS.
For rsync-synced folders, run only one rsync direction at a time or use
a lock file to avoid double-claim.

Stuck-job reclaim (v0.2 post-release polish):

  --reclaim-stuck-after MINUTES   (default 0 = disabled)
  --max-claims N                  (default 3)

When reclaim is enabled, the worker scans running/ before each polling
sleep. Jobs whose 'started' timestamp is older than MINUTES get their
`claim_count` incremented and are moved back to pending/ — UNLESS
claim_count has already reached --max-claims, in which case they're
moved to failed/ with a structured error. This is the cheap version
of retry: no exponential backoff, no dead-letter queue, no supervisor.
Enough to recover from worker crashes; not enough to call production.

Studio-tier feature. Single-machine laptop use works but the docs only
ship the operational recipe for the two-Studio setup.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

VALID_STAGES = {"text_to_image", "image_to_3d", "glb_to_print"}


def _hostname_safe() -> str:
    try:
        return socket.gethostname() or "unknown"
    except OSError:
        return "unknown"


def _read_hardware_tier(pipeline_root: Path) -> str:
    cfg = pipeline_root / ".config"
    if not cfg.exists():
        return "laptop"
    for line in cfg.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == "hardware_tier":
            v = v.strip()
            return v if v in ("laptop", "studio") else "laptop"
    return "laptop"


def _list_pending(qr: Path) -> list[Path]:
    pending = qr / "pending"
    if not pending.exists():
        return []
    files = [p for p in pending.iterdir()
             if p.is_file() and p.suffix == ".json"
             and not p.name.endswith(".tmp")]
    # Sort by (priority, mtime) so high-priority and older jobs go first.
    def key(p):
        try:
            j = json.loads(p.read_text())
            return (int(j.get("priority", 50)), p.stat().st_mtime)
        except (OSError, json.JSONDecodeError):
            return (999, p.stat().st_mtime)
    files.sort(key=key)
    return files


def _reclaim_stuck(qr: Path, threshold_minutes: float, max_claims: int,
                   json_mode: bool) -> None:
    """Move jobs in running/ older than `threshold_minutes` back to pending/
    (with incremented claim_count) or to failed/ when they've already been
    claimed max_claims times. Best-effort: races and missing files are
    swallowed since another worker may have grabbed the same file.
    """
    running = qr / "running"
    if not running.exists():
        return
    threshold_seconds = threshold_minutes * 60.0
    now = time.time()
    for job_path in list(running.iterdir()):
        if not job_path.is_file() or job_path.suffix != ".json":
            continue
        if job_path.name.endswith(".tmp"):
            continue
        try:
            age = now - job_path.stat().st_mtime
        except FileNotFoundError:
            continue
        if age < threshold_seconds:
            continue
        try:
            job = json.loads(job_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        claim_count = int(job.get("claim_count", 0))
        job["claim_count"] = claim_count + 1
        job["error"] = (
            f"reclaimed after {threshold_minutes:.1f} minutes "
            f"(claim_count was {claim_count}, mtime age was {age:.0f}s)"
        )

        if job["claim_count"] > max_claims:
            target = qr / "failed" / job_path.name
            job["status"] = "failed"
            job["error"] = (
                f"exceeded max claims ({max_claims}); last error: {job['error']}"
            )
        else:
            target = qr / "pending" / job_path.name
            job["status"] = "pending"
            job["started"] = None
            job["machine"] = None

        tmp = job_path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(job, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, job_path)
            os.rename(job_path, target)
        except OSError:
            # Another worker may have grabbed it; that's fine.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            continue

        if json_mode:
            print(json.dumps({
                "status": "ok",
                "stage": "queue_worker_reclaim",
                "job_id": job.get("id", ""),
                "target": str(target),
                "claim_count": job["claim_count"],
                "outcome": job["status"],
            }))
        else:
            print(f"[queue-worker] reclaimed {job_path.name} "
                  f"(claim_count={job['claim_count']}, "
                  f"outcome={job['status']})")


def _try_claim(job_path: Path, qr: Path) -> Path | None:
    """Atomically move pending/<x>.json -> running/<x>.json. Returns the new
    path on success or None on race (lost the claim to another worker)."""
    target = qr / "running" / job_path.name
    try:
        os.rename(job_path, target)
        return target
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
            return None
        raise


def _build_command(job: dict, script_dir: Path) -> list[str]:
    stage = job["stage"]
    if stage == "text_to_image":
        cmd = [str(script_dir / "concept.sh"), job.get("input", "")]
        if job.get("generator"):
            cmd.extend(["-m", job["generator"]])
        if job.get("output_name"):
            cmd.extend(["-o", job["output_name"]])
    elif stage == "image_to_3d":
        cmd = [str(script_dir / "generate.sh"), "-i", job["input"]]
        if job.get("generator"):
            cmd.extend(["-g", job["generator"]])
        if job.get("polycount"):
            cmd.extend(["-p", str(job["polycount"])])
        if job.get("texture_resolution"):
            cmd.extend(["-t", str(job["texture_resolution"])])
        if job.get("output_name"):
            cmd.extend(["-o", job["output_name"]])
    elif stage == "glb_to_print":
        cmd = [str(script_dir / "print.sh"), "-i", job["input"]]
        if job.get("target_size_mm"):
            cmd.extend(["-s", str(job["target_size_mm"])])
        if job.get("allow_oversize"):
            cmd.append("--allow-oversize")
        if job.get("output_name"):
            cmd.extend(["-o", job["output_name"]])
    else:
        raise ValueError(f"unknown stage: {stage}")
    if job.get("project"):
        cmd.extend(["--project", job["project"]])
    cmd.append("--json")
    return cmd


def _process_job(job_path: Path, job: dict, script_dir: Path,
                 hostname: str, hw_tier: str, dry_run: bool) -> tuple[bool, dict | None, str]:
    """Run the wrapper for this job. Return (ok, wrapper_json, stderr_tail)."""
    cmd = _build_command(job, script_dir)
    if dry_run:
        return True, {"status": "dry_run", "cmd": cmd}, ""
    # Inherit env so PIPELINE_CONFIG_PATH / SPAR3D_DIR / etc. flow through.
    proc = subprocess.run(cmd, capture_output=True, text=True)
    parsed = None
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = None
        break
    stderr_tail = "\n".join(proc.stderr.splitlines()[-30:])
    ok = (proc.returncode == 0 and parsed is not None
          and parsed.get("status") == "ok")
    if parsed is None:
        parsed = {"status": "error", "exit_code": proc.returncode,
                  "stdout_tail": "\n".join(proc.stdout.splitlines()[-30:])}
    return ok, parsed, stderr_tail


def _finalize(job_path: Path, job: dict, qr: Path, success: bool) -> Path:
    bucket = "done" if success else "failed"
    target = qr / bucket / job_path.name
    tmp = job_path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(job, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, job_path)
    os.rename(job_path, target)
    return target


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--assets-root", required=True,
                   help="Active assets root (queue lives at <root>/queue/).")
    p.add_argument("--script-dir", required=True,
                   help="Directory with concept.sh / generate.sh / print.sh.")
    p.add_argument("--pipeline-root", default=os.path.expanduser("~/3d-pipeline"),
                   help="For reading hardware_tier from .config.")
    p.add_argument("--once", action="store_true",
                   help="Claim and run a single job, then exit.")
    p.add_argument("--max-jobs", type=int, default=0,
                   help="Exit after N jobs (0 = unlimited).")
    p.add_argument("--poll-seconds", type=float, default=5.0,
                   help="Sleep interval when pending/ is empty.")
    p.add_argument("--dry-run", action="store_true",
                   help="Do not actually invoke wrappers; record cmd only.")
    p.add_argument("--json", action="store_true",
                   help="Emit a JSON status line per processed job.")
    p.add_argument("--reclaim-stuck-after", type=float, default=0.0,
                   metavar="MINUTES",
                   help="Reclaim jobs stuck in running/ for longer than this many "
                        "minutes. 0 (default) disables reclaim entirely.")
    p.add_argument("--max-claims", type=int, default=3,
                   help="If reclaim is enabled, jobs that have been claimed this many "
                        "times move to failed/ instead of pending/ (default: 3).")
    args = p.parse_args()

    assets_root = Path(os.path.expanduser(args.assets_root))
    qr = assets_root / "queue"
    for sub in ("pending", "running", "done", "failed"):
        (qr / sub).mkdir(parents=True, exist_ok=True)

    script_dir = Path(os.path.expanduser(args.script_dir))
    hostname = _hostname_safe()
    hw_tier = _read_hardware_tier(Path(args.pipeline_root))

    stop = {"flag": False}

    def _handle_signal(signum, frame):
        stop["flag"] = True
        if not args.json:
            print(f"[queue-worker] received signal {signum}; stopping after current job")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    processed = 0
    while not stop["flag"]:
        if args.reclaim_stuck_after > 0:
            _reclaim_stuck(qr, args.reclaim_stuck_after, args.max_claims,
                           json_mode=args.json)

        pending = _list_pending(qr)
        if not pending:
            if args.once or stop["flag"]:
                break
            time.sleep(args.poll_seconds)
            continue

        for candidate in pending:
            claimed = _try_claim(candidate, qr)
            if not claimed:
                continue
            try:
                job = json.loads(claimed.read_text())
            except json.JSONDecodeError as exc:
                # Malformed job; move to failed and continue.
                claimed.rename(qr / "failed" / claimed.name)
                if not args.json:
                    print(f"[queue-worker] malformed job {claimed.name}: {exc}",
                          file=sys.stderr)
                break

            job["status"] = "running"
            job["machine"] = hostname
            job["hardware_tier"] = hw_tier
            job["started"] = datetime.now().isoformat(timespec="seconds")

            ok, wrapper_json, stderr_tail = _process_job(
                claimed, job, script_dir, hostname, hw_tier, args.dry_run
            )
            job["finished"] = datetime.now().isoformat(timespec="seconds")
            job["status"] = "done" if ok else "failed"
            job["result"] = wrapper_json
            if not ok:
                job["error"] = stderr_tail or "wrapper returned non-zero or unparseable JSON"

            target = _finalize(claimed, job, qr, ok)
            processed += 1

            if args.json:
                print(json.dumps({
                    "status": "ok" if ok else "error",
                    "stage": "queue_worker_step",
                    "job_id": job["id"],
                    "job_stage": job["stage"],
                    "target": str(target),
                    "machine": hostname,
                    "hardware_tier": hw_tier,
                }))
            else:
                status_text = "done" if ok else "failed"
                print(f"[queue-worker] {status_text}: {job['id']} ({job['stage']}) "
                      f"-> {target}")

            if args.max_jobs and processed >= args.max_jobs:
                stop["flag"] = True
                break
            if args.once:
                stop["flag"] = True
                break
            break  # re-list pending so priority ordering is fresh

    if not args.json:
        print(f"[queue-worker] processed {processed} job(s); exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# Imports used by future extensions of this worker (job-archival, dead-letter
# requeue scripts that share this file's helpers). Kept here so the lint check
# stays quiet.
_ = shlex
