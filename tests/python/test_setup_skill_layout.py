from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_setup_skill_directory_exists():
    assert (REPO / "setup-skill" / "SKILL.md").exists()


def test_setup_skill_not_in_embeds():
    """Per spec §1.1 the setup skill ships via repo clone, not EMBEDS."""
    import sys
    sys.path.insert(0, str(REPO))
    from tools._embed_lib import EMBEDS  # noqa
    forbidden = [src for src in EMBEDS if src.startswith("setup-skill/")]
    assert forbidden == [], \
        f"setup-skill files must not be in EMBEDS: {forbidden}"


def test_setup_skill_audit_loop_helper_exists():
    assert (REPO / "setup-skill" / "scripts" / "audit_loop.py").exists()


def test_runtime_skill_mentions_setup_skill():
    runtime = (REPO / "skill" / "SKILL.md").read_text()
    assert "asset-pipeline-setup" in runtime
    assert "When to run setup" in runtime or "When to run the setup" in runtime
