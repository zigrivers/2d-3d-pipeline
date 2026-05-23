"""EMBEDS partition into scripts/ and skill/ destinations."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools import _embed_lib  # noqa: E402


def test_embeds_scripts_and_embeds_skill_partition():
    assert hasattr(_embed_lib, "EMBEDS_SCRIPTS")
    assert hasattr(_embed_lib, "EMBEDS_SKILL")
    scripts_dests = set(_embed_lib.EMBEDS_SCRIPTS.values())
    skill_dests = set(_embed_lib.EMBEDS_SKILL.values())
    all_dests = set(_embed_lib.EMBEDS.values())
    # Every EMBED falls in exactly one partition
    assert scripts_dests | skill_dests == all_dests
    assert scripts_dests & skill_dests == set()
    # Prefix invariant
    for d in scripts_dests:
        assert d.startswith("~/3d-pipeline/workspace/")
    for d in skill_dests:
        assert d.startswith("~/.claude/skills/asset-pipeline/")


def test_install_lib_in_embeds():
    """_install_lib.py must ship via EMBEDS so HTML fallback works."""
    assert "scripts/_install_lib.py" in _embed_lib.EMBEDS
    assert _embed_lib.EMBEDS["scripts/_install_lib.py"] == \
        "~/3d-pipeline/workspace/_install_lib.py"
