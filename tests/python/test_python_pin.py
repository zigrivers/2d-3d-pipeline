import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_check_python_pin_ok(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("3.12.7\n")
    actual = "3.12.7"
    assert pipeline_doctor._patch_pin_matches(pin, actual)


def test_check_python_pin_minor_match_only_when_no_patch(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("3.12\n")
    assert pipeline_doctor._patch_pin_matches(pin, "3.12.7")
    assert pipeline_doctor._patch_pin_matches(pin, "3.12.0")


def test_check_python_pin_mismatch(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("3.12.7\n")
    assert not pipeline_doctor._patch_pin_matches(pin, "3.12.4")


def test_no_pin_file_is_acceptable(tmp_path):
    pin = tmp_path / ".python-version"  # not created
    assert pipeline_doctor._patch_pin_matches(pin, "3.12.5")
