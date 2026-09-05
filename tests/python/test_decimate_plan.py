"""The decimate guard: protect dense organic meshes, leave props alone.

Numbers here are real measurements from this pipeline, recorded in
scripts/decimate_plan.py's docstring — not invented fixtures.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "decimate_plan", REPO / "scripts" / "decimate_plan.py")
dp = importlib.util.module_from_spec(_spec)
sys.modules["decimate_plan"] = dp
_spec.loader.exec_module(dp)


# (source_polys, requested_target) pairs measured from real SF3D prop runs.
PROP_RUNS = [(19_059, 3_000), (32_383, 3_000), (48_530, 3_000)]


@pytest.mark.parametrize("source,target", PROP_RUNS)
def test_props_are_never_clamped(source, target):
    """Props legitimately decimate to 6-16% of source and look fine."""
    plan = dp.plan_decimate(source, target)
    assert plan["clamped"] is False
    assert plan["target"] == target


def test_dense_character_is_clamped():
    """187,974 -> 12,000 destroyed a face and never reached its target."""
    plan = dp.plan_decimate(187_974, 12_000)
    assert plan["clamped"] is True
    assert plan["target"] == int(187_974 * 0.25)
    assert plan["requested_target"] == 12_000
    assert "12,000" in plan["reason"]
    assert "--retopo quad" in plan["reason"]


def test_dense_mesh_with_reasonable_target_is_untouched():
    """187,974 -> 100,000 rendered cleanly, so it must pass through."""
    plan = dp.plan_decimate(187_974, 100_000)
    assert plan["clamped"] is False
    assert plan["target"] == 100_000


def test_guard_can_be_disabled():
    plan = dp.plan_decimate(187_974, 12_000, min_ratio=0)
    assert plan["clamped"] is False
    assert plan["target"] == 12_000


def test_sparse_mesh_never_clamps_however_aggressive():
    """A 40k prop reduced to 500 is the caller's business, not the guard's."""
    plan = dp.plan_decimate(40_000, 500)
    assert plan["clamped"] is False


def test_target_above_source_is_a_noop():
    plan = dp.plan_decimate(50_000, 200_000)
    assert plan["clamped"] is False
    assert plan["target"] == 200_000


def test_target_exactly_at_floor_is_not_clamped():
    floor = int(187_974 * 0.25)
    plan = dp.plan_decimate(187_974, floor)
    assert plan["clamped"] is False
    assert plan["target"] == floor


def test_dense_threshold_is_configurable():
    plan = dp.plan_decimate(60_000, 1_000, dense_threshold=50_000)
    assert plan["clamped"] is True


def test_target_met_detects_the_floor_out():
    """The real failure: asked for 12,000, decimator stopped at 47,626."""
    assert dp.target_met(47_626, 47_626) is True
    assert dp.target_met(47_626, 12_000) is False
    assert dp.target_met(2_999, 3_000) is True
