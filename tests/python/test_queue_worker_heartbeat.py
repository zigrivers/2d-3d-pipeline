"""Integration: queue_worker writes a heartbeat each poll cycle."""
import datetime
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "scripts" / "queue_worker.py"


def _worker_argv(assets_root: Path, *extra) -> list[str]:
    base = [sys.executable, str(WORKER),
            "--assets-root", str(assets_root),
            "--script-dir", str(assets_root)]
    return base + list(extra)


def test_worker_writes_heartbeat_at_start(tmp_path):
    """Smoke: starting the worker creates a heartbeat file within 10s."""
    assets_root = tmp_path / "ws"
    for sub in ("pending", "running", "done", "failed"):
        (assets_root / "queue" / sub).mkdir(parents=True)

    proc = subprocess.Popen(
        _worker_argv(assets_root),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        machine = socket.gethostname()
        hb = assets_root / "queue" / f".heartbeat-{machine}"
        deadline = time.time() + 10
        while time.time() < deadline:
            if hb.exists():
                break
            time.sleep(0.5)
        assert hb.exists(), \
            f"worker did not write a heartbeat within 10s; stderr={proc.stderr.read()!r}"
        content = hb.read_text().strip()
        if content.endswith("Z"):
            content = content[:-1]
        ts = datetime.datetime.fromisoformat(content)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        age = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()
        assert age < 30
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_worker_survives_heartbeat_write_failure(tmp_path):
    """AC10: when the heartbeat write fails (e.g. SMB hang), the worker
    logs and continues; it must not crash."""
    import os as _os
    assets_root = tmp_path / "ws"
    for sub in ("pending", "running", "done", "failed"):
        (assets_root / "queue" / sub).mkdir(parents=True)
    proc = subprocess.Popen(
        _worker_argv(assets_root),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        machine = socket.gethostname()
        hb = assets_root / "queue" / f".heartbeat-{machine}"
        deadline = time.time() + 10
        while time.time() < deadline and not hb.exists():
            time.sleep(0.5)
        assert hb.exists()

        # Make the queue dir read-only so subsequent heartbeat writes fail
        _os.chmod(assets_root / "queue", 0o500)
        time.sleep(2)  # let the worker attempt at least one heartbeat
        assert proc.poll() is None, \
            f"worker died after heartbeat failure; stderr={proc.stderr.read()!r}"
    finally:
        try:
            _os.chmod(assets_root / "queue", 0o755)
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_worker_dry_run_does_not_write_heartbeat(tmp_path):
    """Spec §6.2: --dry-run must skip heartbeat writes entirely."""
    assets_root = tmp_path / "ws"
    for sub in ("pending", "running", "done", "failed"):
        (assets_root / "queue" / sub).mkdir(parents=True)
    proc = subprocess.Popen(
        _worker_argv(assets_root, "--dry-run"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        time.sleep(3)
        heartbeats = list((assets_root / "queue").glob(".heartbeat-*"))
        assert heartbeats == [], \
            f"--dry-run wrote heartbeats: {heartbeats}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
