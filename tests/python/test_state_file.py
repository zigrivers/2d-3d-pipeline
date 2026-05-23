"""`.install_state.json` shape and operations."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_load_missing_state_returns_empty_shape(tmp_pipeline_root):
    s = pipeline_doctor.load_state()
    assert s == {"stages": {}, "declined": {}}


def test_record_stage_ok_persists(tmp_pipeline_root):
    pipeline_doctor.record_stage_outcome("scripts", ok=True,
                                          manifest_sha="abc123")
    s = pipeline_doctor.load_state()
    assert s["stages"]["scripts"]["ok"] is True
    assert s["stages"]["scripts"]["manifest_sha"] == "abc123"
    assert "ts" in s["stages"]["scripts"]


def test_record_stage_failure_persists(tmp_pipeline_root):
    pipeline_doctor.record_stage_outcome("venvs", ok=False,
                                          error="torch wheel failed")
    s = pipeline_doctor.load_state()
    assert s["stages"]["venvs"]["ok"] is False
    assert s["stages"]["venvs"]["error"] == "torch wheel failed"


def test_record_declined_optional(tmp_pipeline_root):
    pipeline_doctor.record_declined("studio_extras.launchd_plist",
                                     reason="user declined")
    s = pipeline_doctor.load_state()
    assert "studio_extras.launchd_plist" in s["declined"]


def test_clear_declined(tmp_pipeline_root):
    pipeline_doctor.record_declined("x", reason="r")
    pipeline_doctor.clear_declined()
    s = pipeline_doctor.load_state()
    assert s["declined"] == {}
