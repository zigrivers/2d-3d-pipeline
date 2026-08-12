import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


PREREQS = [
    {"id": "python", "kind": "binary", "name": "python3",
     "min_version": "3.10", "max_version": "3.12",
     "max_version_severity": "warn",
     "install_hint": "brew install python@3.12"},
    {"id": "git", "kind": "binary", "name": "git"},
    {"id": "missing-tool", "kind": "binary", "name": "definitely-not-a-real-binary-xyz",
     "install_hint": "brew install ghost"},
]


def test_check_prereqs_finds_python_and_git():
    result = pipeline_doctor.check_prereqs(manifest={"prereqs": PREREQS})
    assert result["status"] in ("warning", "critical")  # missing-tool always fails
    names = {p["id"]: p for p in result["prereqs"]}
    assert names["python"]["status"] in ("ok", "warning")  # may exceed max_version on dev machine
    assert names["git"]["status"] in ("ok", "warning")
    assert names["missing-tool"]["status"] == "missing"
    assert "brew install ghost" in names["missing-tool"]["install_hint"]


def test_check_prereqs_max_version_warn_does_not_fail():
    # Mock python3 to report 3.13 (above max)
    with patch("scripts.pipeline_doctor._binary_version",
               side_effect=lambda name, version_flag="--version": "3.13.0" if name == "python3" else "2.40.0"):
        prereqs = [
            {"id": "python", "kind": "binary", "name": "python3",
             "min_version": "3.10", "max_version": "3.12",
             "max_version_severity": "warn"},
            {"id": "git", "kind": "binary", "name": "git"},
        ]
        result = pipeline_doctor.check_prereqs(manifest={"prereqs": prereqs})
        py = next(p for p in result["prereqs"] if p["id"] == "python")
        assert py["status"] == "warning"
        # The overall should not be critical because severity is "warn"
        assert result["status"] != "critical"


def test_check_prereqs_min_version_fails():
    with patch("scripts.pipeline_doctor._binary_version",
               side_effect=lambda name, version_flag="--version": "3.9.0" if name == "python3" else "2.40.0"):
        prereqs = [{"id": "python", "kind": "binary", "name": "python3",
                    "min_version": "3.10", "max_version_severity": "warn"}]
        result = pipeline_doctor.check_prereqs(manifest={"prereqs": prereqs})
        assert result["status"] == "critical"


def test_check_prereqs_optional_missing_does_not_escalate():
    """Item 23: required=false prereqs (e.g. gltfpack) missing -> info only."""
    with patch("scripts.pipeline_doctor._binary_version", return_value=None):
        prereqs = [
            {"id": "gltfpack", "kind": "binary", "name": "gltfpack",
             "required": False, "version_flag": ""},
        ]
        result = pipeline_doctor.check_prereqs(manifest={"prereqs": prereqs})
        entry = next(p for p in result["prereqs"] if p["id"] == "gltfpack")
        assert entry["status"] == "missing_optional"
        assert result["status"] == "ok"


def test_check_prereqs_max_version_fail_severity_escalates():
    """When max_version_severity is 'fail', exceeding max produces critical."""
    with patch("scripts.pipeline_doctor._binary_version",
               side_effect=lambda name, version_flag="--version": "3.13.0"):
        prereqs = [{"id": "python", "kind": "binary", "name": "python3",
                    "min_version": "3.10", "max_version": "3.12",
                    "max_version_severity": "fail"}]
        result = pipeline_doctor.check_prereqs(manifest={"prereqs": prereqs})
        assert result["status"] == "critical"
        py = next(p for p in result["prereqs"] if p["id"] == "python")
        assert py["status"] == "critical"


def test_apply_prereqs_never_installs():
    """--apply on prereqs is verify-only; it must not invoke install commands."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Python 3.12.7"
        result = pipeline_doctor.apply_prereqs(manifest={"prereqs": PREREQS[:2]})
        all_args = [c.args[0] for c in mock_run.call_args_list]
        for argv in all_args:
            if isinstance(argv, list):
                assert argv[0] not in ("brew", "pip", "apt-get", "yum")
