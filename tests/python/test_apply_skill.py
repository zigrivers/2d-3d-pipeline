import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402
from tools import _embed_lib  # noqa: E402


def test_apply_skill_materializes_to_claude_dir(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    result = pipeline_doctor.apply_skill(manifest={}, mutable_paths=[])
    assert result["status"] == "ok"
    skill_root = fake_home / ".claude" / "skills" / "asset-pipeline"
    assert (skill_root / "SKILL.md").exists()


def test_check_skill_drift_after_mutation(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    pipeline_doctor.apply_skill(manifest={}, mutable_paths=[])
    target = fake_home / ".claude" / "skills" / "asset-pipeline" / "SKILL.md"
    target.write_text(target.read_text() + "\ndrift\n")
    result = pipeline_doctor.check_skill(manifest={}, mutable_paths=[])
    assert result["status"] == "warning"


def test_check_skill_skips_mutable_paths(tmp_path, monkeypatch):
    """mutable_embed_paths entries land in T0 advisory, not T1 drift."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    pipeline_doctor.apply_skill(manifest={}, mutable_paths=[])
    target = fake_home / ".claude" / "skills" / "asset-pipeline" / "SKILL.md"
    target.write_text("mutated")
    result = pipeline_doctor.check_skill(
        manifest={},
        mutable_paths=["~/.claude/skills/asset-pipeline/SKILL.md"],
    )
    drifted = [s for s in result["skill"] if s["status"] == "drift"]
    assert not any(s["name"] == "SKILL.md" for s in drifted)
