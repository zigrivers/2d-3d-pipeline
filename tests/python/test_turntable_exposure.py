"""Guard the turntable preview's exposure fix.

The preview renderer needs Blender, so CI cannot render a frame. These are
source-level assertions on the specific settings that were wrong: they exist
to stop the fix being silently reverted, not to test Blender.

The bug: three area lights at 600/300/400 W with no ambient world, rendered
through Blender's default AgX view transform. AgX desaturates saturated
colour hard, so a textured asset came out as a featureless pale blob — and
those frames feed the VLM mesh judge, which would then score the transform
rather than the asset.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = (REPO / "scripts" / "turntable_render.py").read_text()


def test_view_transform_is_standard():
    """AgX flatters the asset and lies about its albedo."""
    assert "scene.view_settings.view_transform = 'Standard'" in SOURCE


def test_lights_are_not_back_at_blowout_wattage():
    for blown in ('"Key", 600', '"Fill", 300', '"Rim", 400'):
        assert blown not in SOURCE, f"{blown} was the overexposure bug"


def test_light_energy_scales_with_rig_distance():
    """A fixed wattage blows out small assets and under-lights large ones."""
    assert "energy_scale = (dist / 1.7) ** 2" in SOURCE
    assert "ld.energy = energy * energy_scale" in SOURCE


def test_ambient_world_is_present():
    """Without it the unlit side goes black and hides real geometry faults."""
    assert "PreviewWorld" in SOURCE
    assert "scene.world = world" in SOURCE


def test_key_light_stays_brightest():
    energies = {
        name: int(value)
        for name, value in re.findall(r'make_light\("(\w+)", (\d+),', SOURCE)
    }
    assert set(energies) == {"Key", "Fill", "Rim"}
    assert energies["Key"] > energies["Rim"] > energies["Fill"]
