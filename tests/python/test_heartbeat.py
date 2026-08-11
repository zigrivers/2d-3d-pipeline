import datetime
import socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import _heartbeat  # noqa: E402
from scripts import pipeline_doctor  # noqa: E402


def test_write_heartbeat_local_temp_then_rename(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    machine = "test-machine"
    result = _heartbeat.write(queue, machine=machine, timeout_seconds=5)
    assert result["status"] == "ok"
    hb = queue / f".heartbeat-{machine}"
    assert hb.exists()
    # ISO timestamp
    datetime.datetime.fromisoformat(hb.read_text().strip().rstrip("Z"))


def test_heartbeat_read_alive_when_recent(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    machine = "remote-studio"
    _heartbeat.write(queue, machine=machine, timeout_seconds=5)
    alive = pipeline_doctor.is_heartbeat_alive(
        queue, machine=machine, max_age_seconds=90)
    assert alive is True


def test_heartbeat_read_dead_when_stale(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    machine = "remote-studio"
    hb = queue / f".heartbeat-{machine}"
    # Write a timestamp 5 minutes ago
    stale = (datetime.datetime.utcnow() - datetime.timedelta(minutes=5))
    hb.write_text(stale.isoformat() + "Z")
    alive = pipeline_doctor.is_heartbeat_alive(
        queue, machine=machine, max_age_seconds=90)
    assert alive is False


def test_heartbeat_write_timeout_returns_degraded(tmp_path):
    """Watchdog must return 'degraded' when the rename hasn't completed
    within timeout_seconds. Use deterministic Event mocking instead of
    a real time.sleep so this test is fast and CI-stable."""
    queue = tmp_path / "queue"
    queue.mkdir()
    machine = "test-machine"

    class FakeEvent:
        def __init__(self):
            self._set = False

        def set(self):
            self._set = True

        def is_set(self):
            # threading.Thread internals use this on their own _started Event
            return self._set

        def clear(self):
            self._set = False

        def wait(self, timeout=None):
            return False  # always "timed out"

    with patch("scripts._heartbeat.threading.Event", FakeEvent):
        result = _heartbeat.write(queue, machine=machine, timeout_seconds=25)
    assert result["status"] == "degraded"
    assert "did not complete" in result["reason"].lower() or \
        "timeout" in result["reason"].lower()


def test_heartbeat_missing_file_is_dead(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    alive = pipeline_doctor.is_heartbeat_alive(
        queue, machine="nobody-home", max_age_seconds=90)
    assert alive is False
