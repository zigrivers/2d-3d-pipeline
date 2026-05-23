"""Local-only advisory flock for --apply."""
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_lock_succeeds_on_local_fs(tmp_pipeline_root):
    with pipeline_doctor.apply_lock():
        pass  # entered + exited cleanly


def test_concurrent_lock_attempt_fails(tmp_pipeline_root, tmp_path):
    """macOS BSD flock is per-process, not per-fd, so a thread-based test
    would falsely pass (same-process threads share the kernel lock). Use a
    real subprocess for the holder so the second attempt is truly cross-process.
    """
    import os
    import subprocess
    import sys
    import time

    # Holder script: take the lock, write a sentinel, sleep until killed
    holder_code = (
        "import sys, time, os\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        f"os.environ['PIPELINE_ROOT'] = {str(tmp_pipeline_root)!r}\n"
        "from scripts import pipeline_doctor\n"
        "with pipeline_doctor.apply_lock():\n"
        f"    open({str(tmp_path / 'held')!r}, 'w').write('held')\n"
        "    time.sleep(30)\n"
    )
    holder = subprocess.Popen([sys.executable, "-c", holder_code])
    try:
        sentinel = tmp_path / "held"
        deadline = time.time() + 5
        while time.time() < deadline and not sentinel.exists():
            time.sleep(0.05)
        assert sentinel.exists(), "holder subprocess never acquired the lock"

        # Second attempt from this process should be rejected
        try:
            with pipeline_doctor.apply_lock():
                assert False, "second acquire unexpectedly succeeded"
        except pipeline_doctor.LockHeldError:
            pass
    finally:
        holder.terminate()
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()


def test_lock_refuses_network_fs(tmp_pipeline_root, monkeypatch):
    # Simulate the FS-type detection returning a network type
    monkeypatch.setattr(pipeline_doctor, "_is_network_fs", lambda p: True)
    try:
        with pipeline_doctor.apply_lock():
            assert False, "should have raised"
    except pipeline_doctor.NetworkFSError as e:
        assert "network" in str(e).lower()
