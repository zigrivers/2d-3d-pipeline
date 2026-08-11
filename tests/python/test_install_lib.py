import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import _install_lib  # noqa: E402


def test_dispatch_unknown_managed_by_returns_skipped():
    model = {"id": "x", "managed_by": "nope", "warm_target": "x"}
    status, detail = _install_lib.warm(model)
    assert status == "skipped"
    assert "nope" in detail.lower() or "unknown" in detail.lower()


def test_rembg_recipe_invokes_new_session():
    model = {"id": "u2net", "managed_by": "rembg",
             "warm_target": "u2net", "storage_layout": "literal",
             "cache_dir": "~/3d-pipeline/models/rembg",
             "filename": "u2net.onnx",
             "env_var": "U2NET_HOME"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        status, detail = _install_lib.warm(model)
    called = False
    for c in mock_run.call_args_list:
        argv = c.args[0] if c.args else []
        if isinstance(argv, list) and any("rembg" in a for a in argv):
            called = True
            break
    assert called, f"rembg snippet not invoked; calls: {mock_run.call_args_list}"


def test_comfyui_dispatch_by_kind_routes_to_correct_recipe():
    """RECIPES['comfyui'] is a nested dict keyed by comfyui_kind."""
    kind_to_func = {
        "checkpoint": "scripts._install_lib._comfyui_warm_checkpoint",
        "ip_adapter": "scripts._install_lib._comfyui_warm_ip_adapter",
        "controlnet": "scripts._install_lib._comfyui_warm_controlnet",
        "lora":       "scripts._install_lib._comfyui_warm_lora",
    }
    for kind, func_path in kind_to_func.items():
        model = {"id": f"x-{kind}", "managed_by": "comfyui",
                 "comfyui_kind": kind, "warm_target": f"x-{kind}",
                 "storage_layout": "hf_snapshot",
                 "hf_repo": f"test/{kind}",
                 "filename": f"x-{kind}.safetensors",
                 "cache_dir": f"~/3d-pipeline/models/{kind}"}
        with patch(func_path) as mock_func:
            mock_func.return_value = ("ok", "downloaded")
            status, detail = _install_lib.warm(model)
        mock_func.assert_called_once_with(model)
        assert status == "ok"


def test_comfyui_unknown_kind_returns_skipped():
    model = {"id": "x", "managed_by": "comfyui",
             "comfyui_kind": "bogus_kind", "warm_target": "x",
             "storage_layout": "hf_snapshot",
             "hf_repo": "test/x", "filename": "x.safetensors",
             "cache_dir": "~/3d-pipeline/models/x"}
    status, detail = _install_lib.warm(model)
    assert status == "skipped"
    assert "comfyui_kind" in detail
    assert "bogus_kind" in detail


def test_open_clip_recipe_uses_env_var():
    model = {"id": "clip-vit-l-14", "managed_by": "open_clip",
             "warm_target": "ViT-L-14", "storage_layout": "hf_snapshot",
             "hf_repo": "laion/CLIP-ViT-L-14-laion2B-s32B-b82K",
             "filename": "open_clip_pytorch_model.bin",
             "cache_dir": "~/3d-pipeline/models/clip",
             "env_var": "OPEN_CLIP_CACHE_DIR"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        status, detail = _install_lib.warm(model)
    found = False
    for c in mock_run.call_args_list:
        env = c.kwargs.get("env") or {}
        if "OPEN_CLIP_CACHE_DIR" in env:
            found = True
            break
    assert found, "OPEN_CLIP_CACHE_DIR not passed to subprocess"
