import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


MODEL_LITERAL = {
    "id": "u2net", "filename": "u2net.onnx",
    "feature_set": "tier1", "license_bucket": "commercial_safe",
    "size_mb": 170, "cache_dir": "~/3d-pipeline/models/rembg",
    "env_var": "U2NET_HOME",
    "download_url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
    "sha256": "", "managed_by": "rembg", "notes": "",
    "requires_hf_auth": False, "hf_repo": None,
    "storage_layout": "literal", "warm_target": "u2net", "comfyui_kind": None,
}


def test_apply_model_warm_then_verify_present(tmp_pipeline_root):
    """A recipe that returns 'ok' and creates the file produces 'downloaded'.

    For this test we want to take the host-tool warm path (NOT the
    engine-owned direct-URL path), so strip download_url."""
    cache = tmp_pipeline_root / "models" / "rembg"
    cache.mkdir(parents=True)

    model = dict(MODEL_LITERAL)
    model["download_url"] = ""  # force warm path

    def fake_recipe(m):
        (cache / m["filename"]).write_bytes(b"x" * (m["size_mb"] * 1024 * 1024))
        return ("ok", "completed")

    with patch("scripts._install_lib.warm", side_effect=fake_recipe):
        result = pipeline_doctor.apply_model(model)
    assert result["status"] == "ok"
    assert result.get("verified") is True


def test_apply_model_warm_succeeds_but_file_missing_fails(tmp_pipeline_root):
    """Recipe returns 'ok' but doesn't actually produce the file."""
    model = dict(MODEL_LITERAL)
    model["download_url"] = ""

    def fake_recipe(m):
        return ("ok", "completed")

    with patch("scripts._install_lib.warm", side_effect=fake_recipe):
        result = pipeline_doctor.apply_model(model)
    assert result["status"] == "critical"
    assert result.get("verified") is False


def test_apply_model_warm_failed_propagates(tmp_pipeline_root):
    model = dict(MODEL_LITERAL)
    model["download_url"] = ""

    def fake_recipe(m):
        return ("failed", "rembg crashed")
    with patch("scripts._install_lib.warm", side_effect=fake_recipe):
        result = pipeline_doctor.apply_model(model)
    assert result["status"] == "critical"
    assert "rembg crashed" in result["error"]


def test_check_model_t3_size_window(tmp_pipeline_root):
    """T3 ±5% size check. Uses a small fake declared size."""
    cache = tmp_pipeline_root / "models" / "rembg"
    cache.mkdir(parents=True)
    m = dict(MODEL_LITERAL)
    m["size_mb"] = 1
    # File at declared size (1 MB)
    (cache / "u2net.onnx").write_bytes(b"x" * (1 * 1024 * 1024))
    r = pipeline_doctor.check_model(m)
    assert r["status"] == "ok"

    # File way undersized (100 bytes)
    (cache / "u2net.onnx").write_bytes(b"x" * 100)
    r = pipeline_doctor.check_model(m)
    assert r["status"] == "drift"


def test_apply_model_routes_direct_url_through_range_downloader(tmp_pipeline_root):
    """Literal storage + download_url → _download_with_range is invoked."""
    cache = tmp_pipeline_root / "models" / "rembg"
    cache.mkdir(parents=True)

    def fake_range_download(url, dest, expected_size=None, chunk_size=65536):
        dest.write_bytes(b"x" * (1 * 1024 * 1024))
        return {"status": "ok"}

    m = dict(MODEL_LITERAL)
    m["size_mb"] = 1
    with patch("scripts.pipeline_doctor._download_with_range",
               side_effect=fake_range_download) as mock_range, \
         patch("scripts._install_lib.warm") as mock_warm:
        result = pipeline_doctor.apply_model(m)

    mock_range.assert_called_once()
    mock_warm.assert_not_called()
    assert result["status"] == "ok"
    assert result.get("verified") is True


def test_ac12_new_model_under_existing_recipe_requires_no_code_change(tmp_pipeline_root):
    """AC12: adding a new model under an existing (managed_by, comfyui_kind)
    combination dispatches through the existing recipe without touching
    pipeline_doctor.py or _install_lib.py."""
    new_controlnet = {
        "id": "controlnet-depth", "filename": "controlnet-depth-sdxl.safetensors",
        "feature_set": "comfyui", "license_bucket": "commercial_safe",
        "size_mb": 1300,
        "cache_dir": "~/3d-pipeline/models/controlnet",
        "env_var": "", "download_url": "",
        "sha256": "", "managed_by": "comfyui", "notes": "synthetic test model",
        "requires_hf_auth": False,
        "hf_repo": "xinsir/controlnet-depth-sdxl-1.0",
        "storage_layout": "hf_snapshot",
        "warm_target": "controlnet-depth-sdxl",
        "comfyui_kind": "controlnet",
    }
    cache = tmp_pipeline_root / "models" / "controlnet"
    cache.mkdir(parents=True)

    def fake_controlnet_recipe(model):
        return ("ok", "downloaded")

    with patch("scripts._install_lib._comfyui_warm_controlnet",
               side_effect=fake_controlnet_recipe) as mock_cn, \
         patch("scripts.pipeline_doctor._model_t3_check",
               return_value={"status": "ok", "actual_mb": 1300}):
        result = pipeline_doctor.apply_model(new_controlnet)

    mock_cn.assert_called_once_with(new_controlnet)
    assert result["status"] == "ok"
