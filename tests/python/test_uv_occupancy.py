"""UV occupancy must measure coverage, not the bounding box of the UVs.

The old implementation took the bounding box of every UV point, which is
~1.0 for any mesh that spans the square at all — however little of it the
triangles actually cover. Measured on real pipeline output:

    asset       reported    true coverage
    character      0.999            0.603
    SF3D prop      0.678            0.364

The prop's true 0.364 sits under the 0.40 threshold that is supposed to
recommend --reuv, so that recommendation could never fire.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "game_asset_check", REPO / "scripts" / "game_asset_check.py")
gac = importlib.util.module_from_spec(_spec)
sys.modules["game_asset_check"] = gac
_spec.loader.exec_module(gac)


def test_full_square_is_full_occupancy():
    """Two triangles filling the unit square cover all of it."""
    uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
    faces = [(0, 1, 2), (0, 2, 3)]
    assert gac.uv_occupancy(uv, faces) == 1.0


def test_half_square_is_half_occupancy():
    uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert gac.uv_occupancy(uv, [(0, 1, 2)]) == 0.5


def test_bounding_box_no_longer_masks_sparse_uvs():
    """The case the old metric got wrong.

    Two thin triangles pinned to opposite corners span the whole square, so
    the old bounding-box metric scored ~1.0. They cover almost none of it.
    """
    uv = [(0.0, 0.0), (0.02, 0.0), (0.0, 0.02),
          (1.0, 1.0), (0.98, 1.0), (1.0, 0.98)]
    occupancy = gac.uv_occupancy(uv, [(0, 1, 2), (3, 4, 5)])
    assert occupancy < 0.01
    assert occupancy < gac.OCCUPANCY_WARN


def test_winding_order_does_not_change_area():
    uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
    clockwise = gac.uv_occupancy(uv, [(0, 2, 1), (0, 3, 2)])
    counter = gac.uv_occupancy(uv, [(0, 1, 2), (0, 2, 3)])
    assert clockwise == counter == 1.0


def test_overlapping_uvs_are_clamped_not_overflowed():
    """Mirrored UVs stack area on the same space; occupancy is still a ratio."""
    uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
    faces = [(0, 1, 2), (0, 2, 3)] * 4
    assert gac.uv_occupancy(uv, faces) == 1.0


def test_degenerate_triangle_contributes_nothing():
    uv = [(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)]
    assert gac.uv_occupancy(uv, [(0, 1, 2)]) == 0.0


def test_no_faces_is_zero():
    assert gac.uv_occupancy([(0, 0), (1, 0), (1, 1)], []) == 0.0
