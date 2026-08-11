import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


@pytest.fixture
def venv_with_lockfile(tmp_path, monkeypatch):
    """Build a VENV dict whose `lockfile` points into tmp_path, not the
    real repo. Monkeypatch REPO_ROOT so apply_venv resolves the lockfile
    correctly without polluting scripts/lockfiles/."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts" / "lockfiles").mkdir(parents=True)
    monkeypatch.setattr(pipeline_doctor, "REPO_ROOT", fake_repo)

    def _make(content: str = "Pillow==10.4.0\n"):
        lockfile_rel = "scripts/lockfiles/_test_lockfile.txt"
        (fake_repo / lockfile_rel).write_text(content)
        return {
            "name": "test-env",
            "path": "~/3d-pipeline/test-env",
            "required": True,
            "feature_set": "tier1",
            "size_gb": 1,
            "purpose": "test fixture",
            "python_version": "3.12",
            "lockfile": lockfile_rel,
        }
    return _make


def test_apply_venv_creates_venv_and_installs(tmp_pipeline_root,
                                                venv_with_lockfile, monkeypatch):
    venv = venv_with_lockfile()
    # Stub the python-version probe so we don't depend on the host python
    monkeypatch.setattr(pipeline_doctor, "_active_python_version",
                         lambda v: "3.12.7")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        result = pipeline_doctor.apply_venv(venv)
    calls = [c.args[0] for c in mock_run.call_args_list
             if c.args and isinstance(c.args[0], list)]
    assert calls[0] == ["python3.12", "-m", "venv",
                         str(pipeline_doctor._expand(venv["path"]))]
    pip_path = str(pipeline_doctor._venv_pip(pipeline_doctor._expand(venv["path"])))
    expected_pip_install = [pip_path, "install", "-r",
                             str(pipeline_doctor.REPO_ROOT / venv["lockfile"])]
    assert expected_pip_install in calls, \
        f"expected {expected_pip_install} in {calls}"


def test_apply_venv_skips_when_lockfile_empty(tmp_pipeline_root, venv_with_lockfile):
    venv = venv_with_lockfile(content="")
    result = pipeline_doctor.apply_venv(venv)
    assert result["status"] == "skipped"
    assert "empty lockfile" in result["reason"].lower()


def test_apply_venv_aborts_on_python_patch_mismatch(tmp_pipeline_root,
                                                      venv_with_lockfile,
                                                      monkeypatch):
    """Spec §3.1: if active python differs from the pinned patch, refuse
    to proceed. AC3 fails-loud diagnostic."""
    venv = venv_with_lockfile()
    (pipeline_doctor.REPO_ROOT / ".python-version").write_text("3.12.999\n")
    monkeypatch.setattr(pipeline_doctor, "_active_python_version",
                         lambda v: "3.12.7")
    result = pipeline_doctor.apply_venv(venv)
    assert result["status"] == "critical"
    assert "patch" in (result.get("error") or "").lower() or \
        "python" in (result.get("error") or "").lower()


def test_apply_venv_retries_on_wheel_failure(tmp_pipeline_root,
                                              venv_with_lockfile, monkeypatch):
    venv = venv_with_lockfile()
    monkeypatch.setattr(pipeline_doctor, "_active_python_version",
                         lambda v: "3.12.7")
    outcomes = iter([
        MagicMock(returncode=0, stdout="", stderr=""),  # venv create
        MagicMock(returncode=1, stdout="",
                   stderr="ERROR: Could not build wheels for torch"),
        MagicMock(returncode=0, stdout="", stderr=""),  # pip upgrade
        MagicMock(returncode=0, stdout="", stderr=""),  # pip install retry
    ])
    with patch("subprocess.run", side_effect=lambda *a, **k: next(outcomes)):
        result = pipeline_doctor.apply_venv(venv)
    assert result["status"] == "ok"
    assert result.get("retried") is True


def test_apply_venv_double_failure_parses_failing_package(tmp_pipeline_root,
                                                            venv_with_lockfile,
                                                            monkeypatch):
    """On second pip failure, the engine parses stderr for the failing
    package name."""
    venv = venv_with_lockfile()
    monkeypatch.setattr(pipeline_doctor, "_active_python_version",
                         lambda v: "3.12.7")
    outcomes = iter([
        MagicMock(returncode=0, stdout="", stderr=""),  # venv create
        MagicMock(returncode=1, stdout="",
                   stderr="ERROR: Could not build wheels for torch"),
        MagicMock(returncode=0, stdout="", stderr=""),  # pip upgrade
        MagicMock(returncode=1, stdout="",
                   stderr="ERROR: Could not build wheels for torch"),
    ])
    with patch("subprocess.run", side_effect=lambda *a, **k: next(outcomes)):
        result = pipeline_doctor.apply_venv(venv)
    assert result["status"] == "critical"
    assert result.get("failing_package") == "torch"


# --- Task 3.4: drift detection ---

def test_check_venv_drift_against_lockfile(tmp_pipeline_root, venv_with_lockfile):
    venv = venv_with_lockfile(content="Pillow==10.4.0\nrequests==2.31.0\n")
    # Make the venv path "exist" so we get past the missing check
    path = pipeline_doctor._expand(venv["path"])
    path.mkdir(parents=True, exist_ok=True)
    (path / "bin").mkdir(exist_ok=True)
    (path / "bin" / "pip").write_text("")

    with patch("scripts.pipeline_doctor._venv_pip_freeze",
               return_value="Pillow==10.4.0\nrequests==2.31.0\n"):
        r = pipeline_doctor.check_venv(venv)
    assert r["status"] == "ok"

    with patch("scripts.pipeline_doctor._venv_pip_freeze",
               return_value="Pillow==10.5.0\nrequests==2.31.0\n"):
        r = pipeline_doctor.check_venv(venv)
    assert r["status"] == "drift"
    assert "fix_command" in r


def test_check_venv_missing(tmp_pipeline_root, venv_with_lockfile):
    venv = venv_with_lockfile(content="Pillow==10.4.0\n")
    r = pipeline_doctor.check_venv(venv)
    assert r["status"] == "drift"
    assert r.get("reason") == "missing"
