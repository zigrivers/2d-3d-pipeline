"""Host-tool recipes for smoke-warming lazy-managed models.

Dispatched by `pipeline_doctor.py` keyed by `managed_by`. For ComfyUI, a
second-level dispatch by `comfyui_kind` handles the four distinct model kinds
(checkpoint, ip_adapter, controlnet, lora) that all share `managed_by:
comfyui` but need different placement.

Each recipe is a function (model_dict) -> (status, detail) where status is
one of {"ok", "skipped", "failed"} and detail is a short string.

Adding a new model under an existing managed_by + comfyui_kind requires only
a manifest edit. Adding a new managed_by or a new comfyui_kind requires a
function here.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def _run_in_venv(venv_path: Path, snippet: str, env_extra: dict | None = None) -> tuple[int, str, str]:
    """Run a one-line Python snippet inside a venv. Returns (returncode, stdout, stderr)."""
    python = venv_path / "bin" / "python"
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([str(python), "-c", snippet],
                        capture_output=True, text=True, env=env, timeout=600)
    return r.returncode, r.stdout, r.stderr


def _rembg_warm(model: dict) -> tuple[str, str]:
    venv = _expand("~/3d-pipeline/pipeline-tools-env")
    target = model["warm_target"]
    snippet = f"from rembg import new_session; new_session({target!r}); print('ok')"
    env = {model["env_var"]: str(_expand(model["cache_dir"]))} if model.get("env_var") else None
    rc, out, err = _run_in_venv(venv, snippet, env_extra=env)
    if rc == 0:
        return ("ok", f"rembg new_session({target!r}) completed")
    return ("failed", err.strip()[:300])


def _open_clip_warm(model: dict) -> tuple[str, str]:
    venv = _expand("~/3d-pipeline/pipeline-tools-env")
    target = model["warm_target"]
    snippet = (
        "import open_clip; "
        f"open_clip.create_model_and_transforms({target!r}, pretrained='laion2b_s32b_b82k'); "
        "print('ok')"
    )
    env = {model["env_var"]: str(_expand(model["cache_dir"]))} if model.get("env_var") else None
    rc, out, err = _run_in_venv(venv, snippet, env_extra=env)
    if rc == 0:
        return ("ok", f"open_clip warm {target!r} completed")
    return ("failed", err.strip()[:300])


def _hunyuan_warm(model: dict) -> tuple[str, str]:
    """Hunyuan3D-Paint (item 19: MLX port) uses huggingface_hub from inside
    its own venv. Weights are pulled per-file on demand by the port's own
    code (no single fixed filename covers the whole model), so an empty
    manifest `filename` means "warm the whole repo snapshot" rather than
    one file — same convention as edit-lane's Qwen-Image-Edit-2511 entry."""
    venv = _expand("~/3d-pipeline/hunyuan3d-paint-mlx/.venv")
    repo = model["hf_repo"]
    fn = model["filename"]
    cache = _expand(model["cache_dir"])
    if fn:
        snippet = (
            "from huggingface_hub import hf_hub_download; "
            f"hf_hub_download({repo!r}, {fn!r}, cache_dir={str(cache)!r}); "
            "print('ok')"
        )
    else:
        snippet = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download({repo!r}, cache_dir={str(cache)!r}); "
            "print('ok')"
        )
    rc, out, err = _run_in_venv(venv, snippet)
    if rc == 0:
        return ("ok", f"hunyuan {repo} {fn or '(full snapshot)'} downloaded")
    return ("failed", err.strip()[:300])


def _comfyui_download_to_cache(model: dict, kind_label: str) -> tuple[str, str]:
    """Shared HF download into the kind-specific cache_dir."""
    venv = _expand("~/3d-pipeline/comfyui-env")
    repo = model["hf_repo"]
    fn = model["filename"]
    cache = _expand(model["cache_dir"])
    snippet = (
        "from huggingface_hub import hf_hub_download; "
        f"hf_hub_download({repo!r}, {fn!r}, cache_dir={str(cache)!r}); "
        "print('ok')"
    )
    rc, out, err = _run_in_venv(venv, snippet)
    if rc == 0:
        return ("ok", f"comfyui {kind_label} {fn} downloaded")
    return ("failed", err.strip()[:300])


def _comfyui_warm_checkpoint(model: dict) -> tuple[str, str]:
    return _comfyui_download_to_cache(model, "checkpoint")


def _comfyui_warm_ip_adapter(model: dict) -> tuple[str, str]:
    return _comfyui_download_to_cache(model, "ip_adapter")


def _comfyui_warm_controlnet(model: dict) -> tuple[str, str]:
    return _comfyui_download_to_cache(model, "controlnet")


def _comfyui_warm_lora(model: dict) -> tuple[str, str]:
    return _comfyui_download_to_cache(model, "lora")


# Nested dispatch table per spec §3.3.
# Stores function NAMES (not refs) so module-level patches in tests reach
# the dispatch via `globals()[name]` lookup. Adding a new model under an
# existing (managed_by, comfyui_kind) is a manifest edit only (AC12);
# adding a new managed_by or comfyui_kind requires a function here.
RECIPES: dict = {
    "rembg":           "_rembg_warm",
    "open_clip":       "_open_clip_warm",
    "hunyuan3d-paint": "_hunyuan_warm",
    "comfyui": {
        "checkpoint": "_comfyui_warm_checkpoint",
        "ip_adapter": "_comfyui_warm_ip_adapter",
        "controlnet": "_comfyui_warm_controlnet",
        "lora":       "_comfyui_warm_lora",
    },
}


def warm(model: dict) -> tuple[str, str]:
    managed = model.get("managed_by")
    recipe = RECIPES.get(managed)
    if recipe is None:
        return ("skipped", f"unknown managed_by {managed!r}; recipe missing")
    if isinstance(recipe, dict):
        kind = model.get("comfyui_kind")
        sub_name = recipe.get(kind)
        if sub_name is None:
            return ("skipped",
                    f"unknown comfyui_kind {kind!r} for model {model.get('id')!r}; "
                    f"valid: {sorted(recipe.keys())}")
        return globals()[sub_name](model)
    return globals()[recipe](model)
