import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "setup-skill" / "scripts" / "audit_loop.py"


def _run(stdin_text: str):
    return subprocess.run(
        [sys.executable, str(HELPER)],
        input=stdin_text, capture_output=True, text=True,
    )


def test_empty_report_says_in_sync():
    payload = json.dumps({"check_installed": {"stages": {}}})
    r = _run(payload)
    assert r.returncode == 0
    assert "in sync" in r.stdout.lower()


def test_drifted_scripts_render_as_punch_list():
    payload = json.dumps({"check_installed": {"stages": {
        "scripts": {"status": "warning", "scripts": [
            {"name": "generate.sh", "status": "drift",
             "current": "byte-mismatch"},
            {"name": "print.sh", "status": "drift",
             "current": "byte-mismatch"},
        ]},
    }}})
    r = _run(payload)
    assert r.returncode == 0
    assert "scripts/ — 2 item(s) drifted" in r.stdout
    assert "[1] generate.sh" in r.stdout
    assert "[2] print.sh" in r.stdout
    assert "Apply:" in r.stdout


def test_multiple_stages_get_separate_blocks():
    payload = json.dumps({"check_installed": {"stages": {
        "scripts": {"status": "warning", "scripts": [
            {"name": "x", "status": "drift", "current": "?"},
        ]},
        "venvs": {"status": "warning", "venvs": [
            {"name": "mflux-env", "status": "drift", "reason": "missing"},
        ]},
    }}})
    r = _run(payload)
    assert "scripts/" in r.stdout
    assert "venvs/" in r.stdout


def test_invalid_json_exits_2():
    r = _run("not json")
    assert r.returncode == 2
