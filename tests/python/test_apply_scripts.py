import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402
from tools import _embed_lib  # noqa: E402


def test_apply_scripts_materializes_all_embeds(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    result = pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    assert result["status"] == "ok"
    for src, dst in _embed_lib.EMBEDS_SCRIPTS.items():
        expected = Path(dst.replace("~/3d-pipeline", str(tmp_pipeline_root)))
        assert expected.exists(), f"missing {expected}"


def test_apply_scripts_preserves_executable_bit(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    # *.sh files must be executable
    for src, dst in _embed_lib.EMBEDS_SCRIPTS.items():
        if src.endswith(".sh"):
            expected = Path(dst.replace("~/3d-pipeline", str(tmp_pipeline_root)))
            assert os.access(expected, os.X_OK), f"{expected} not executable"


def test_apply_scripts_idempotent_no_mtime_change(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    # Snapshot mtimes recursively — EMBEDS can land sub-dirs (comfyui_workflows/, etc.)
    workspace = tmp_pipeline_root / "workspace"
    snapshots = {p: p.stat().st_mtime_ns
                 for p in workspace.rglob("*") if p.is_file()}
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    for p, ts in snapshots.items():
        assert p.stat().st_mtime_ns == ts, f"{p} mtime changed on re-apply"


def test_check_scripts_reports_drift(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    # Mutate one file
    target = tmp_pipeline_root / "workspace" / "concept.sh"
    target.write_text(target.read_text() + "\n# drift\n")
    result = pipeline_doctor.check_scripts(manifest={}, mutable_paths=[])
    assert result["status"] == "warning"
    drifted = [s for s in result["scripts"] if s["status"] == "drift"]
    assert any(s["name"] == "concept.sh" for s in drifted)
    assert any("--apply --only scripts" in s.get("fix_command", "")
               for s in drifted)


def test_check_scripts_skips_mutable_paths(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    target = tmp_pipeline_root / "workspace" / "concept.sh"
    target.write_text("drift")
    # Pass the mutated path as mutable — drift should be ignored (T0)
    result = pipeline_doctor.check_scripts(
        manifest={},
        mutable_paths=["~/3d-pipeline/workspace/concept.sh"],
    )
    drifted = [s for s in result["scripts"] if s["status"] == "drift"]
    assert not any(s["name"] == "concept.sh" for s in drifted)
