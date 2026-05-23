import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_apply_config_writes_tier(tmp_pipeline_root):
    result = pipeline_doctor.apply_config(manifest={}, tier="studio")
    assert result["status"] == "ok"
    content = (tmp_pipeline_root / ".config").read_text()
    assert "hardware_tier = studio" in content


def test_apply_config_idempotent(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    sha_before = pipeline_doctor._file_sha256(tmp_pipeline_root / ".config")
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    sha_after = pipeline_doctor._file_sha256(tmp_pipeline_root / ".config")
    assert sha_before == sha_after


def test_apply_config_overwrites_tier(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    pipeline_doctor.apply_config(manifest={}, tier="studio")
    assert "hardware_tier = studio" in (tmp_pipeline_root / ".config").read_text()


def test_read_tier_from_config(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="studio")
    assert pipeline_doctor.read_tier() == "studio"


def test_read_tier_returns_none_when_missing(tmp_pipeline_root):
    assert pipeline_doctor.read_tier() is None


def test_check_config_reports_drift(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    # Corrupt the config
    (tmp_pipeline_root / ".config").write_text("hardware_tier = laptop\nextra = junk\n")
    result = pipeline_doctor.check_config(manifest={}, tier="laptop")
    assert result["status"] == "warning"


def test_check_config_clean_after_apply(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    result = pipeline_doctor.check_config(manifest={}, tier="laptop")
    assert result["status"] == "ok"
