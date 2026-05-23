"""Host-tool recipes for smoke-warming lazy-managed models.

Each entry in RECIPES maps a model warm_target to a callable that triggers
the framework's own download on first use.  Populated incrementally in Phase 3.
"""
from __future__ import annotations

RECIPES: dict = {}


def warm(model: dict) -> tuple[str, str]:
    """Placeholder; populated in Phase 3."""
    return ("skipped", "no recipe registered yet")
