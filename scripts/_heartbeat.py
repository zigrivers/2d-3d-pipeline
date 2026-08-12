"""Heartbeat write helper used by queue_worker.py.

The protocol: write to a local tmp file, then atomic-rename onto the shared
queue path. Wrap the rename in a watchdog with `timeout_seconds`. On timeout,
return a `degraded` result; caller logs and continues.

This module is intentionally tiny so it can be imported from both
`pipeline_doctor.py` and `queue_worker.py` without pulling extra deps.
"""
from __future__ import annotations

import datetime
import os
import tempfile
import threading
from pathlib import Path


def _utc_iso_now() -> str:
    """tz-aware UTC ISO timestamp; datetime.utcnow() is deprecated in 3.12+."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")


def _heartbeat_path(queue_dir: Path, machine: str,
                     template: str = ".heartbeat-<machine>") -> Path:
    """Resolve the per-machine heartbeat path against the manifest template.

    The manifest's `studio_extras.heartbeat_file` may be e.g.
    `queue/.heartbeat-<machine>` (relative, with the `<machine>` placeholder).
    queue_dir is `<workspace>/queue`, so we strip a leading `queue/` if
    present and substitute the placeholder.
    """
    rel = template
    if rel.startswith("queue/"):
        rel = rel[len("queue/"):]
    rel = rel.replace("<machine>", machine)
    return queue_dir / rel


def write(queue_dir: Path, *, machine: str,
           timeout_seconds: int = 25,
           template: str = ".heartbeat-<machine>") -> dict:
    """Write a heartbeat for `machine` into queue_dir, resolved via template.

    Watchdog protocol: write to a local tmp file, then atomic-rename through
    a watchdog with a hard timeout. On timeout, return `degraded`; caller
    logs and continues. Never raises.
    """
    queue_dir.mkdir(parents=True, exist_ok=True)
    ts = _utc_iso_now()
    dest = _heartbeat_path(queue_dir, machine, template)
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.gettempdir()) / f".heartbeat-{machine}-{os.getpid()}.tmp"
    tmp.write_text(ts)

    result: dict = {"status": "ok", "ts": ts}
    finished = threading.Event()

    def do_rename():
        try:
            tmp.replace(dest)
        except Exception as e:
            result["status"] = "failed"
            result["reason"] = f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            finished.set()

    t = threading.Thread(target=do_rename, daemon=True)
    t.start()
    if not finished.wait(timeout=timeout_seconds):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        # Fresh dict: the worker thread may still finish (or fail) later and
        # mutate `result`; the caller must see a stable "degraded" outcome.
        return {"status": "degraded", "ts": ts,
                "reason": f"rename did not complete within {timeout_seconds}s"}
    return result
