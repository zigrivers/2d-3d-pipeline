"""Guard the turntable preview's framing fix.

Rendering needs Blender, which CI does not have, so these are source-level
assertions on the settings that were wrong.

The bug: the orbit started at 0°. Blender's glTF importer puts a model's
front on -Y, so 0° is the model's side and the hero frame — copied from
frame 0 — landed on its back. On a character that is a useless thumbnail,
and --judge-mesh scores the hero frame, so the judge was assessing the back
of the head instead of the face.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = (REPO / "scripts" / "turntable_render.py").read_text()


def test_front_angle_is_defined_at_minus_y():
    """270° puts the camera on -Y, which is where a glTF model faces."""
    assert "FRONT_ANGLE = math.radians(270.0)" in SOURCE


def test_hero_is_a_three_quarter_view():
    assert "HERO_OFFSET = math.radians(45.0)" in SOURCE


def test_still_mode_uses_the_hero_angle():
    assert "position_camera(FRONT_ANGLE + HERO_OFFSET)" in SOURCE


def test_orbit_starts_on_the_hero_view():
    """Frame 0 must be the hero, so the GIF opens on the subject."""
    assert "angle = FRONT_ANGLE + HERO_OFFSET + math.radians(i * 360.0 / frames)" in SOURCE


def test_orbit_no_longer_starts_at_zero():
    assert "angle = math.radians(i * 360.0 / frames)" not in SOURCE, \
        "starting the orbit at 0° was the framing bug"


def test_still_mode_no_longer_hardcodes_45_degrees():
    assert "position_camera(math.radians(45))" not in SOURCE
