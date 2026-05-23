import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_apply_dirs_creates_tree(tmp_pipeline_root):
    result = pipeline_doctor.apply_dirs(manifest={"schema_version": 2})
    assert result["status"] == "ok"
    for sub in ("workspace", "models", "benchmarks"):
        assert (tmp_pipeline_root / sub).is_dir()


def test_apply_dirs_idempotent(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={"schema_version": 2})
    result = pipeline_doctor.apply_dirs(manifest={"schema_version": 2})
    assert result["status"] == "ok"


def test_check_dirs_reports_missing(tmp_pipeline_root):
    # Don't apply — check should report missing
    result = pipeline_doctor.check_dirs(manifest={"schema_version": 2})
    assert result["status"] == "warning"
    missing = {d["name"] for d in result["dirs"] if d["status"] == "missing"}
    assert missing == {"workspace", "models", "benchmarks"}


def test_check_dirs_clean_after_apply(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={"schema_version": 2})
    result = pipeline_doctor.check_dirs(manifest={"schema_version": 2})
    assert result["status"] == "ok"
