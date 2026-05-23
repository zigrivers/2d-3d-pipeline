import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


GATED_MODEL = {
    "id": "hunyuan3d-paint", "filename": "hunyuan3d-paint.safetensors",
    "feature_set": "hunyuan3d-paint",
    "license_bucket": "commercial_threshold",
    "size_mb": 5000,
    "cache_dir": "~/3d-pipeline/models/hunyuan3d-paint",
    "env_var": "HUNYUAN3D_HOME", "download_url": "",
    "sha256": "", "managed_by": "hunyuan3d-paint",
    "notes": "",
    "requires_hf_auth": True, "hf_repo": "tencent/Hunyuan3D-2",
    "storage_layout": "hf_snapshot", "warm_target": "hunyuan3d-paint",
    "comfyui_kind": None,
}

OPEN_MODEL = {**GATED_MODEL, "id": "open", "requires_hf_auth": False,
              "hf_repo": "stabilityai/sd-vae-ft-mse"}


def test_preflight_skipped_when_no_gated_models():
    result = pipeline_doctor.hf_preflight([OPEN_MODEL])
    assert result["status"] == "ok"
    assert result["checked"] == 0


def _mock_whoami_ok():
    m = MagicMock()
    m.returncode = 0
    m.stdout = "test-user"
    m.stderr = ""
    return patch("subprocess.run", return_value=m)


def test_preflight_passes_when_access_granted():
    with _mock_whoami_ok(), patch("huggingface_hub.HfApi") as MockApi:
        instance = MockApi.return_value
        instance.model_info.return_value = MagicMock(id="tencent/Hunyuan3D-2")
        result = pipeline_doctor.hf_preflight([GATED_MODEL])
    assert result["status"] == "ok"
    MockApi.return_value.model_info.assert_called_once()
    call = MockApi.return_value.model_info.call_args
    assert call.args[0] == "tencent/Hunyuan3D-2" or call.kwargs.get("repo_id") == "tencent/Hunyuan3D-2"


def _fake_repo_not_found(msg: str = "401 access denied"):
    """huggingface_hub 1.x requires a `response` kwarg on RepositoryNotFoundError."""
    from huggingface_hub.utils import RepositoryNotFoundError
    fake_response = MagicMock(status_code=401, headers={}, url="https://hf.co/x")
    return RepositoryNotFoundError(msg, response=fake_response)


def test_preflight_fails_with_401_per_repo():
    with _mock_whoami_ok(), patch("huggingface_hub.HfApi") as MockApi:
        instance = MockApi.return_value
        instance.model_info.side_effect = _fake_repo_not_found()
        result = pipeline_doctor.hf_preflight([GATED_MODEL])
    assert result["status"] == "critical"
    assert "tencent/Hunyuan3D-2" in result["details"]
    assert "huggingface-cli login" in result["details"] or \
        "request access" in result["details"]


def test_preflight_aborts_before_download(tmp_pipeline_root):
    """AC4: --apply --only models with auth missing must abort before any
    .part / .incomplete file is created."""
    cache = tmp_pipeline_root / "models" / "hunyuan3d-paint"
    cache.mkdir(parents=True)
    with _mock_whoami_ok(), patch("huggingface_hub.HfApi") as MockApi, \
         patch("huggingface_hub.hf_hub_download") as mock_dl:
        MockApi.return_value.model_info.side_effect = _fake_repo_not_found("401")
        result = pipeline_doctor.hf_preflight([GATED_MODEL])
    assert result["status"] == "critical"
    mock_dl.assert_not_called()
    leftovers = list(tmp_pipeline_root.rglob("*.part")) + \
        list(tmp_pipeline_root.rglob("*.incomplete"))
    assert leftovers == [], f"preflight leaked partial files: {leftovers}"


def test_preflight_whoami_first_then_per_repo():
    """Spec §3.2: whoami is used as an early 'is there any token' pre-check
    before iterating per-repo model_info calls."""
    with patch("subprocess.run") as mock_run, \
         patch("huggingface_hub.HfApi") as MockApi:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "Not logged in"
        result = pipeline_doctor.hf_preflight([GATED_MODEL])
        MockApi.return_value.model_info.assert_not_called()
    assert result["status"] == "critical"
    assert "huggingface-cli login" in result["details"]
    assert "no token" in result["details"].lower() or \
        "Not logged in" in result["details"]


def test_preflight_model_info_called_with_timeout():
    """model_info must use a bounded timeout so CI / offline hangs short."""
    with patch("huggingface_hub.HfApi") as MockApi, \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "user"
        mock_run.return_value.stderr = ""
        result = pipeline_doctor.hf_preflight([GATED_MODEL])
    call = MockApi.return_value.model_info.call_args
    assert call is not None, "model_info was never called"
    kwargs = call.kwargs
    timeout = kwargs.get("timeout")
    assert timeout is not None and timeout <= 30, \
        f"model_info must be called with timeout<=30; got {kwargs!r}"
