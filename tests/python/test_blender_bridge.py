"""Routing and parsing rules for the Blender LOCAL_API bridge."""
import base64
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BRIDGE_PATH = REPO / "scripts" / "blender_bridge.py"

_spec = importlib.util.spec_from_file_location("blender_bridge", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(_spec)
sys.modules["blender_bridge"] = bridge
_spec.loader.exec_module(bridge)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"payload"


@pytest.fixture
def routed(monkeypatch, tmp_path):
    """Record which pipeline path a request took, without generating anything."""
    calls = {}
    monkeypatch.setattr(bridge, "WORKSPACE", tmp_path)

    def fake_text_to_image(prompt, name):
        calls["prompt"] = prompt
        return tmp_path / f"{name}.png"

    def fake_image_to_glb(image_path):
        calls["image_path"] = image_path
        return tmp_path / "out.glb"

    monkeypatch.setattr(bridge, "text_to_image", fake_text_to_image)
    monkeypatch.setattr(bridge, "image_to_glb", fake_image_to_glb)
    return calls


def test_text_routes_through_concept(routed):
    glb, how = bridge.build_glb({"text": "a treasure chest"})
    assert how == "text_to_2d_to_3d"
    assert routed["prompt"] == "a treasure chest"
    assert glb.name == "out.glb"


def test_image_routes_straight_to_mesh(routed):
    encoded = base64.b64encode(PNG_BYTES).decode()
    _, how = bridge.build_glb({"image": encoded})
    assert how == "image_to_3d"
    assert "prompt" not in routed
    assert routed["image_path"].read_bytes() == PNG_BYTES


def test_image_wins_when_both_supplied(routed):
    encoded = base64.b64encode(PNG_BYTES).decode()
    _, how = bridge.build_glb({"text": "ignored", "image": encoded})
    assert how == "image_to_3d"
    assert "prompt" not in routed


def test_data_uri_prefix_is_stripped(routed):
    encoded = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()
    bridge.build_glb({"image": encoded})
    assert routed["image_path"].read_bytes() == PNG_BYTES


def test_empty_request_is_rejected(routed):
    with pytest.raises(bridge.PipelineError, match="'text' or 'image'"):
        bridge.build_glb({})


def test_whitespace_only_text_is_rejected(routed):
    with pytest.raises(bridge.PipelineError, match="'text' or 'image'"):
        bridge.build_glb({"text": "   "})


def test_overlong_prompt_is_rejected(routed):
    with pytest.raises(bridge.PipelineError, match="exceeds"):
        bridge.build_glb({"text": "x" * (bridge.MAX_PROMPT_CHARS + 1)})


def test_invalid_base64_is_rejected(routed):
    with pytest.raises(bridge.PipelineError, match="valid base64"):
        bridge.build_glb({"image": "not!valid!base64"})


def test_wrapper_result_is_last_json_line(monkeypatch):
    """Wrappers print progress before the JSON result; take the JSON."""
    class Proc:
        returncode = 0
        stdout = 'noise\n{"status": "ok", "outputs": ["/tmp/a.png"]}\n'
        stderr = ""

    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: Proc())
    assert bridge._run_wrapper(["x"])["outputs"] == ["/tmp/a.png"]


def test_wrapper_error_status_raises(monkeypatch):
    class Proc:
        returncode = 0
        stdout = '{"status": "error", "error": "sf3d exploded"}'
        stderr = ""

    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(bridge.PipelineError, match="sf3d exploded"):
        bridge._run_wrapper(["x"])


def test_wrapper_nonzero_exit_raises(monkeypatch):
    class Proc:
        returncode = 2
        stdout = ""
        stderr = "boom\n"

    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(bridge.PipelineError, match="exited 2"):
        bridge._run_wrapper(["x"])
