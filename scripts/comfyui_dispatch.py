#!/usr/bin/env python3
"""v0.3.2 — ComfyUI dispatcher for consistency mode (P3.2c).

Loads a consistency pack, substitutes its parameters into a ComfyUI
workflow JSON, submits it to a running ComfyUI server at
$COMFYUI_URL (default http://127.0.0.1:8188), polls for completion,
and copies the resulting PNG to the requested output path.

Called by `concept.sh --backend comfyui`. Standalone usage:

    comfyui_dispatch.py \\
        --pack ~/3d-pipeline/consistency-packs/my-character \\
        --prompt "the hero swinging a sword" \\
        --output /path/to/output.png \\
        [--negative "extra negative"] \\
        [--seed 42] [--steps 30] [--width 1024] [--height 1024] \\
        [--workflow scripts/comfyui_workflows/consistency_sdxl.json] \\
        [--server http://127.0.0.1:8188] \\
        [--json]

Output JSON:
    {
      "status": "ok",
      "backend": "comfyui",
      "pack": "...",
      "license_bucket": "commercial_threshold",
      "output_path": "...",
      "duration_seconds": 18.4,
      "comfyui_prompt_id": "abc-123-..."
    }

License bucket: derived from the pack's manifest (most-restrictive
of the pack's declared bucket and the base model's bucket; SDXL =
`commercial_threshold`). LoRA introduces no override today; if a
pack ships an `unclear_risky` LoRA the manifest should already
declare the pack as that bucket.

Requires `requests` (in pipeline-tools-env). Validation against the
consistency-pack schema is best-effort — uses `jsonschema` if
available; falls back to structural checks otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WORKFLOW = SCRIPT_DIR / "comfyui_workflows" / "consistency_sdxl.json"
DEFAULT_SCHEMA = SCRIPT_DIR / "consistency_pack_schema.json"
DEFAULT_SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")

# License bucket fallback per base model. Always takes the more
# restrictive of (pack-declared, base-model-default) — but in v1 the
# only base model is sdxl-1.0 (commercial_threshold) so the pack's
# declared bucket can only be the same or more restrictive.
BASE_MODEL_BUCKETS = {
    "sdxl-1.0": "commercial_threshold",
}
BUCKET_RANK = {
    "commercial_safe": 0,
    "commercial_threshold": 1,
    "non_commercial": 2,
    "source_available_restricted": 3,
    "unclear_risky": 4,
}


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0 if payload.get("status") == "ok" else 1


def _resolve_bucket(pack_bucket: str, base_model: str) -> str:
    base_bucket = BASE_MODEL_BUCKETS.get(base_model, "unclear_risky")
    return max([pack_bucket, base_bucket], key=lambda b: BUCKET_RANK.get(b, 99))


def _validate_pack(pack_data: dict, pack_dir: Path) -> str | None:
    """Structural validation. Returns an error string or None."""
    if pack_data.get("schema_version") != 1:
        return f"pack schema_version is {pack_data.get('schema_version')}; expected 1"
    for key in ("name", "license_bucket", "base_model", "identity"):
        if key not in pack_data:
            return f"pack missing required field: {key}"
    identity = pack_data.get("identity") or {}
    if "reference" not in identity:
        return "pack.identity.reference is required"
    ref_path = pack_dir / identity["reference"]
    if not ref_path.exists():
        return f"pack.identity.reference not found: {ref_path}"
    return None


def _http_post(url: str, data: dict, timeout: float = 30.0) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _http_get(url: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def _http_download(url: str, dest: Path, timeout: float = 60.0) -> None:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        dest.write_bytes(resp.read())


def _server_alive(server: str) -> bool:
    try:
        _http_get(f"{server}/system_stats", timeout=2.0)
        return True
    except Exception:
        return False


def _substitute(workflow: dict, pack_data: dict, pack_dir: Path, args) -> dict:
    """Walk a workflow JSON and replace `${pack.foo}`-style placeholders.

    The workflow template uses string-literal placeholders that this
    function rewrites in place. Recognised placeholders:

        ${pack.identity.reference}    absolute path to identity image
        ${pack.identity.weight}       float (default 0.8)
        ${pack.lora.path}             absolute path to LoRA (or "" if none)
        ${pack.lora.weight}           float (default 1.0)
        ${pack.controlnets[0].reference}, etc.
        ${prompt}                     user-supplied prompt
        ${negative}                   combined negative prompt
        ${seed} / ${steps} / ${width} / ${height}
    """
    identity = pack_data.get("identity") or {}
    lora = pack_data.get("lora") or {}
    controlnets = pack_data.get("controlnets") or []

    negative_default = pack_data.get("negative_prompt_default", "")
    full_negative = ", ".join(filter(None, [negative_default, args.negative]))

    subs: dict[str, str] = {
        "${prompt}": args.prompt,
        "${negative}": full_negative,
        "${seed}": str(args.seed),
        "${steps}": str(args.steps),
        "${width}": str(args.width),
        "${height}": str(args.height),
        "${pack.identity.reference}": str((pack_dir / identity["reference"]).resolve()),
        "${pack.identity.weight}": str(identity.get("weight", 0.8)),
        "${pack.identity.model}": identity.get("model", "ip-adapter-faceid-sdxl"),
        "${pack.ipadapter_file}": identity.get("ipadapter_file", "ip-adapter-faceid_sdxl.bin"),
        "${pack.clip_vision_file}": identity.get("clip_vision_file", "clip-vit-h-14.safetensors"),
        "${pack.lora.path}": str((pack_dir / lora["path"]).resolve()) if lora.get("path") else "",
        "${pack.lora.weight}": str(lora.get("weight", 1.0)),
    }
    for i, cn in enumerate(controlnets):
        subs[f"${{pack.controlnets[{i}].reference}}"] = str((pack_dir / cn["reference"]).resolve())
        subs[f"${{pack.controlnets[{i}].weight}}"] = str(cn.get("weight", 0.6))
        subs[f"${{pack.controlnets[{i}].model}}"] = cn.get("model", "")

    def _walk(node):
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, str):
            for k, v in subs.items():
                if k in node:
                    node = node.replace(k, v)
            return node
        return node

    result = _walk(workflow)

    # When no LoRA is in the pack, strip any LoraLoader node and rewire its
    # downstream consumers directly to the checkpoint loader. ComfyUI rejects
    # a LoraLoader with an empty lora_name.
    if not lora.get("path"):
        lora_nodes = {
            nid for nid, n in result.items()
            if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
        }
        for lora_nid in lora_nodes:
            lora_node = result.pop(lora_nid)
            # LoRA receives [upstream, 0] (MODEL). Its outputs are slot 0=MODEL,
            # slot 1=CLIP; map those to [upstream, 0] and [upstream, 1] respectively.
            upstream = lora_node.get("inputs", {}).get("model")  # e.g. ["3", 0]
            if not (isinstance(upstream, list) and len(upstream) == 2):
                continue
            upstream_nid = upstream[0]
            for n in result.values():
                if not isinstance(n, dict):
                    continue
                inputs = n.get("inputs") or {}
                for key, val in inputs.items():
                    if isinstance(val, list) and len(val) == 2 and val[0] == lora_nid:
                        # Preserve slot index: MODEL→slot 0, CLIP→slot 1 on the checkpoint
                        inputs[key] = [upstream_nid, val[1]]

    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pack", required=True, help="Path to consistency pack directory")
    p.add_argument("--prompt", required=True)
    p.add_argument("--output", required=True, help="Where to write the resulting PNG")
    p.add_argument("--negative", default="")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--width", type=int, default=1024)
    p.add_argument("--height", type=int, default=1024)
    p.add_argument("--workflow", default=str(DEFAULT_WORKFLOW),
                   help="ComfyUI workflow JSON template (default ships with the pipeline)")
    p.add_argument("--server", default=DEFAULT_SERVER,
                   help="ComfyUI server URL (default $COMFYUI_URL or http://127.0.0.1:8188)")
    p.add_argument("--json", action="store_true", default=True)
    args = p.parse_args()

    pack_dir = Path(os.path.expanduser(args.pack)).resolve()
    if not pack_dir.is_dir():
        return _emit({"status": "error", "error": "pack_not_a_directory", "pack": str(pack_dir)})
    pack_json = pack_dir / "pack.json"
    if not pack_json.exists():
        return _emit({"status": "error", "error": "pack_missing_manifest", "pack": str(pack_dir)})
    try:
        pack_data = json.loads(pack_json.read_text())
    except json.JSONDecodeError as e:
        return _emit({"status": "error", "error": "pack_json_invalid", "notes": str(e)})

    err = _validate_pack(pack_data, pack_dir)
    if err:
        return _emit({"status": "error", "error": "pack_invalid", "notes": err})

    license_bucket = _resolve_bucket(
        pack_data["license_bucket"],
        pack_data["base_model"],
    )

    workflow_path = Path(os.path.expanduser(args.workflow))
    if not workflow_path.exists():
        return _emit({
            "status": "error",
            "error": "workflow_not_found",
            "workflow": str(workflow_path),
            "notes": "ship a workflow JSON or pass --workflow",
        })
    try:
        raw_template = json.loads(workflow_path.read_text())
    except json.JSONDecodeError as e:
        return _emit({"status": "error", "error": "workflow_json_invalid", "notes": str(e)})
    # Strip metadata keys (leading underscore) — ComfyUI rejects non-node entries.
    workflow_template = {k: v for k, v in raw_template.items() if not k.startswith("_")}

    if not _server_alive(args.server):
        return _emit({
            "status": "error",
            "error": "comfyui_server_unreachable",
            "server": args.server,
            "notes": ("Start ComfyUI first: cd ~/3d-pipeline/ComfyUI && "
                      "source ~/3d-pipeline/comfyui-env/bin/activate && "
                      "python main.py --port 8188"),
        })

    workflow = _substitute(workflow_template, pack_data, pack_dir, args)

    # Submit to ComfyUI's /prompt endpoint
    t0 = time.time()
    try:
        post_resp = _http_post(
            f"{args.server}/prompt",
            {"prompt": workflow, "client_id": "asset-pipeline"},
            timeout=30.0,
        )
    except Exception as e:
        return _emit({
            "status": "error",
            "error": "submit_failed",
            "notes": str(e),
            "server": args.server,
        })
    prompt_id = post_resp.get("prompt_id")
    if not prompt_id:
        return _emit({
            "status": "error",
            "error": "no_prompt_id",
            "response": post_resp,
        })

    # Poll /history/<prompt_id> until the prompt finishes
    POLL_INTERVAL = 1.0
    MAX_POLL_SECONDS = 600
    history_entry = None
    elapsed = 0.0
    while elapsed < MAX_POLL_SECONDS:
        try:
            hist = _http_get(f"{args.server}/history/{prompt_id}", timeout=10.0)
        except Exception:
            time.sleep(POLL_INTERVAL); elapsed += POLL_INTERVAL; continue
        if prompt_id in hist:
            history_entry = hist[prompt_id]
            break
        time.sleep(POLL_INTERVAL); elapsed += POLL_INTERVAL
    if history_entry is None:
        return _emit({
            "status": "error",
            "error": "polling_timeout",
            "prompt_id": prompt_id,
            "elapsed_seconds": elapsed,
        })

    # Find the first output image filename in the history entry
    outputs = history_entry.get("outputs") or {}
    output_file = None
    for node_outputs in outputs.values():
        for img in (node_outputs.get("images") or []):
            output_file = img
            break
        if output_file:
            break
    if output_file is None:
        return _emit({
            "status": "error",
            "error": "no_image_in_output",
            "history": history_entry,
        })

    # Download via /view
    filename = output_file.get("filename")
    subfolder = output_file.get("subfolder", "")
    type_ = output_file.get("type", "output")
    if not filename:
        return _emit({"status": "error", "error": "output_missing_filename"})
    view_url = (
        f"{args.server}/view"
        f"?filename={filename}&subfolder={subfolder}&type={type_}"
    )
    output_path = Path(os.path.expanduser(args.output)).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _http_download(view_url, output_path)
    except Exception as e:
        return _emit({
            "status": "error",
            "error": "image_download_failed",
            "notes": str(e),
            "view_url": view_url,
        })

    duration = round(time.time() - t0, 2)
    return _emit({
        "status": "ok",
        "backend": "comfyui",
        "pack": pack_data["name"],
        "pack_path": str(pack_dir),
        "license_bucket": license_bucket,
        "base_model": pack_data["base_model"],
        "output_path": str(output_path),
        "duration_seconds": duration,
        "comfyui_prompt_id": prompt_id,
        "seed": args.seed,
    })


if __name__ == "__main__":
    sys.exit(main())
