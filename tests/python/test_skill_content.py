"""SKILL.md content invariants for AC9, AC9b, AC17."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SETUP_SKILL = REPO / "setup-skill" / "SKILL.md"


def test_setup_skill_documents_git_pull_gate_ac17():
    """AC17: skill must show the commit range and ask before fast-forwarding."""
    text = SETUP_SKILL.read_text()
    assert "git fetch" in text, "AC17: skill must mention git fetch"
    assert "HEAD..origin" in text, "AC17: skill must show the commit-range diff"
    assert "ask before" in text.lower() or "ask before pulling" in text.lower(), \
        "AC17: skill must require user confirmation before pull"
    assert "silent" in text.lower(), \
        "AC17: skill should explicitly forbid silent-pull"


def test_setup_skill_documents_multi_select_ux_ac9():
    """AC9: one prompt per stage, comma-range selection, ≤8 prompts worst case."""
    text = SETUP_SKILL.read_text()
    assert "one prompt per stage" in text.lower() or \
        "one multi-select prompt" in text.lower(), \
        "AC9: skill must promise per-stage prompts (not per-item)"
    # Comma-range selection example
    assert "1,3-4" in text or "1-5,8" in text, \
        "AC9: skill must show comma-range selection syntax"
    # Skip option (AC9b)
    assert "(s) skip" in text or "skip" in text, \
        "AC9b: skill must offer a skip option per stage"


def test_setup_skill_documents_bootstrap_prompt_count():
    """Bootstrap is acknowledged as ~6-7 prompts; audit loop is ≤8."""
    text = SETUP_SKILL.read_text()
    assert "bootstrap" in text.lower()
    assert "audit" in text.lower()


def test_setup_skill_documents_studio_heartbeat_check():
    """Studio tier must verify foreign-worker heartbeat before apply."""
    text = SETUP_SKILL.read_text()
    assert "heartbeat" in text.lower(), \
        "Studio section must reference the heartbeat liveness check"
    assert "is_heartbeat_alive" in text or "heartbeat" in text.lower()
