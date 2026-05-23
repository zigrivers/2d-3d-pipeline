"""New CLI flags introduced by v0.4."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCTOR = REPO / "scripts" / "pipeline_doctor.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(DOCTOR), *args],
        capture_output=True, text=True,
    )


def test_apply_flag_recognized():
    r = _run("--help")
    assert r.returncode == 0
    assert "--apply" in r.stdout


def test_only_flag_recognized():
    r = _run("--help")
    assert "--only" in r.stdout


def test_yes_flag_recognized():
    r = _run("--help")
    assert "--yes" in r.stdout


def test_tier_flag_recognized():
    r = _run("--help")
    assert "--tier" in r.stdout


def test_check_installed_recognized():
    r = _run("--help")
    assert "installed" in r.stdout


def test_reconsider_optionals_recognized():
    r = _run("--help")
    assert "--reconsider-optionals" in r.stdout


def test_fix_alias_warns():
    """--fix routes to --apply and prints a deprecation notice on stderr."""
    r = _run("--fix", "--check", "wrappers", "--json")
    # The deprecation notice must mention --apply explicitly so the user knows
    # the new canonical name. Exit code is whatever --apply --check wrappers
    # returns (likely 0 or 1, not 2 = usage error).
    assert r.returncode in (0, 1), f"got {r.returncode}; stderr={r.stderr}"
    assert "--apply" in r.stderr, f"deprecation notice missing --apply: {r.stderr}"
    assert "deprecat" in r.stderr.lower()
