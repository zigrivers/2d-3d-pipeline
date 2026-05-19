#!/usr/bin/env python3
"""
Idempotent updater for the asset pipeline manifest.

Schema versions
---------------
v1, v2 — flat per-asset fields (concept_path, raw_path, clean_path,
         stl_path, polycount_target, generator, …). Still readable.
v3     — adds nested objects (model{}, generation{}, print{}, eval{})
         and an engine_path field, plus license bucket, hardware tier,
         and timing/metadata. Flat fields stay at the top level for
         tools that still read v1/v2-style.

Backward compatibility
----------------------
- Reads any of v1/v2/v3 transparently.
- Writes v3 (`version: 3` on top-level dict, nested blocks per asset).
- If the existing manifest has `"assets": [...]` (list-of-assets legacy
  shape), it's converted to the dict-by-name shape and a backup is left
  at `asset_manifest.json.bak.<timestamp>`.
- All previously-supported args still work.

Usage examples
--------------

  # v1/v2-style call still works (no new args required):
  update_manifest.py --manifest <p> --name <n> --concept <png> \\
      --generator z-image-turbo --category 2d-only

  # v3-rich call with the new optional fields:
  update_manifest.py --manifest <p> --name <n> --concept <png> \\
      --raw <glb> --clean <glb> --generator sf3d --polycount 3000 \\
      --category prop \\
      --license-bucket commercial_threshold --model-role default \\
      --prompt "..." --final-prompt "..." --seed 12345 --steps 9 \\
      --width 1024 --height 1024 --texture-resolution 2048 \\
      --duration-seconds 42 --machine mac-studio-a --hardware-tier studio \\
      --engine-path /path/to/engine/file.glb \\
      --fits-snapmaker-u1 true \\
      --final-dimensions-mm-json '{"x":50.0,"y":32.4,"z":28.9}' \\
      --oversized-axes-json '[]' \\
      --eval-json '{"prompt_match": null, ...}' \\
      --source-wrapper-json '{"status":"ok", ...}'
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# 2D models flagged as generator_2d, 3D models as generator_3d. Anything else
# leaves both slots empty and is recorded under its existing key only.
GENERATOR_2D = {"z-image-turbo", "flux-schnell", "flux-dev", "qwen-image"}
GENERATOR_3D = {"sf3d", "trellis", "spar3d"}


def _strtobool(s: str) -> bool:
    return s.strip().lower() in ("true", "1", "yes", "y")


def _json_or_default(s: str, default):
    if not s:
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in argument: {e}", file=sys.stderr)
        sys.exit(2)


def _size_or_explicit(path_str: str, explicit_bytes: int | None) -> int | None:
    """Return explicit_bytes if provided (>=0), else stat the file path, else None."""
    if explicit_bytes is not None and explicit_bytes >= 0:
        return explicit_bytes
    if not path_str:
        return None
    p = Path(os.path.expanduser(path_str))
    return p.stat().st_size if p.exists() else None


def _migrate_list_to_dict(data: dict, manifest_path: Path) -> dict:
    """If `data['assets']` is a list, back up the manifest and convert to dict."""
    if not isinstance(data.get("assets"), list):
        return data
    # Back up before changing shape.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = manifest_path.with_suffix(manifest_path.suffix + f".bak.{stamp}")
    shutil.copy2(manifest_path, bak)
    print(f"[manifest] migrated legacy list-of-assets shape; backup at {bak}",
          file=sys.stderr)
    out = {}
    for entry in data["assets"]:
        if isinstance(entry, dict) and entry.get("name"):
            out[entry["name"]] = entry
    data["assets"] = out
    return data


def _read_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {"version": 3, "assets": {}}
    with open(manifest_path) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: existing manifest is not valid JSON: {e}", file=sys.stderr)
            sys.exit(1)
    data.setdefault("version", 2)
    data.setdefault("assets", {})
    data = _migrate_list_to_dict(data, manifest_path)
    return data


def _build_model_block(existing: dict, args, now: str) -> dict:
    """Build/merge the `model` block from existing entry + new args."""
    model = dict(existing.get("model") or {})
    if args.generator in GENERATOR_2D:
        model["generator_2d"] = args.generator
    elif args.generator in GENERATOR_3D:
        model["generator_3d"] = args.generator
    if args.license_bucket:
        model["license_bucket"] = args.license_bucket
    if args.model_role:
        model["model_role"] = args.model_role
    return model


def _build_generation_block(existing: dict, args) -> dict:
    gen = dict(existing.get("generation") or {})
    field_map = {
        "prompt": args.prompt,
        "final_prompt": args.final_prompt,
        "seed": args.seed,
        "steps": args.steps,
        "width": args.width,
        "height": args.height,
        "polycount_target": args.polycount if args.polycount else None,
        "texture_resolution": args.texture_resolution,
        "duration_seconds": args.duration_seconds,
        "machine": args.machine,
        "hardware_tier": args.hardware_tier,
    }
    for k, v in field_map.items():
        if v is not None and v != "":
            gen[k] = v
    return gen


def _build_print_block(existing: dict, args) -> dict:
    prn = dict(existing.get("print") or {})
    if args.stl:
        prn["prepared_for_print"] = True
        prn["target_size_mm"] = args.stl_size_mm
    elif "prepared_for_print" not in prn:
        prn.setdefault("prepared_for_print", False)
    if args.final_dimensions_mm_json:
        prn["final_dimensions_mm"] = _json_or_default(args.final_dimensions_mm_json, {})
    if args.fits_snapmaker_u1:
        prn["fits_snapmaker_u1"] = _strtobool(args.fits_snapmaker_u1)
    if args.oversized_axes_json:
        prn["oversized_axes"] = _json_or_default(args.oversized_axes_json, [])
    return prn


def _build_eval_block(existing: dict, args) -> dict:
    if args.eval_json:
        return _json_or_default(args.eval_json, {})
    # Preserve any existing eval; otherwise stub the spec's scaffold.
    if existing.get("eval"):
        return dict(existing["eval"])
    return {
        "prompt_match": None,
        "front_accuracy": None,
        "backside_plausibility": None,
        "topology": None,
        "uv_quality": None,
        "texture_quality": None,
        "pbr_maps_present": None,
        "unity_import": "not_tested",
        "unreal_import": "not_tested",
        "print_prep": "not_tested",
        "slicer_check": "not_tested",
        "failure_type": "",
        "review_notes": "",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    # --- v1/v2 args (preserved) ---
    p.add_argument("--manifest", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--concept", required=True)
    p.add_argument("--raw", default="")
    p.add_argument("--clean", default="")
    p.add_argument("--stl", default="")
    p.add_argument("--stl-size-mm", type=float, default=0.0)
    p.add_argument("--generator", required=True,
                   choices=["sf3d", "trellis", "spar3d",
                            "z-image-turbo", "flux-schnell", "flux-dev",
                            "qwen-image"])
    p.add_argument("--polycount", type=int, default=0)
    p.add_argument("--category", required=True,
                   choices=["prop", "character", "hero", "environment",
                            "weapon", "vehicle", "2d-only"])
    p.add_argument("--notes", default="")
    # --- v3 additions ---
    p.add_argument("--license-bucket", default="",
                   choices=["", "commercial_safe", "commercial_threshold",
                            "source_available_restricted", "non_commercial",
                            "unclear_risky", "unknown"])
    p.add_argument("--model-role", default="",
                   help="default | optional | experimental | other free text")
    p.add_argument("--prompt", default="")
    p.add_argument("--final-prompt", default="")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--texture-resolution", type=int, default=None)
    p.add_argument("--duration-seconds", type=int, default=None)
    p.add_argument("--machine", default="")
    p.add_argument("--hardware-tier", default="",
                   choices=["", "laptop", "studio"])
    p.add_argument("--engine-path", default="")
    p.add_argument("--raw-size-bytes", type=int, default=None)
    p.add_argument("--clean-size-bytes", type=int, default=None)
    p.add_argument("--stl-size-bytes", type=int, default=None)
    p.add_argument("--final-dimensions-mm-json", default="",
                   help='JSON object: {"x":50.0,"y":32.4,"z":28.9}')
    p.add_argument("--fits-snapmaker-u1", default="",
                   help="true/false/empty (empty leaves existing value)")
    p.add_argument("--oversized-axes-json", default="",
                   help='JSON array of axis labels: ["X","Z"]')
    p.add_argument("--eval-json", default="",
                   help="JSON object replacing the eval{} block")
    p.add_argument("--source-wrapper-json", default="",
                   help="JSON object from the wrapper's --json output, kept for provenance")
    args = p.parse_args()

    manifest_path = Path(os.path.expanduser(args.manifest))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    data = _read_manifest(manifest_path)
    existing = data["assets"].get(args.name, {})
    now = datetime.now().isoformat(timespec="seconds")

    # ----- Top-level flat fields (kept readable for v1/v2 consumers) -----
    entry = dict(existing)
    entry.update({
        "name": args.name,
        "concept_path": args.concept,
        "generator": args.generator,
        "category": args.category,
        "notes": args.notes or entry.get("notes", ""),
        "created": existing.get("created", now),
        "updated": now,
    })

    if args.raw or "raw_path" not in entry:
        entry["raw_path"] = args.raw or entry.get("raw_path", "")
        entry["raw_size_bytes"] = _size_or_explicit(args.raw, args.raw_size_bytes) \
            if args.raw else entry.get("raw_size_bytes")
    if args.clean or "clean_path" not in entry:
        entry["clean_path"] = args.clean or entry.get("clean_path", "")
        entry["clean_size_bytes"] = _size_or_explicit(args.clean, args.clean_size_bytes) \
            if args.clean else entry.get("clean_size_bytes")
    if args.polycount or "polycount_target" not in entry:
        entry["polycount_target"] = args.polycount or entry.get("polycount_target", 0)

    if args.stl:
        entry["stl_path"] = args.stl
        entry["stl_size_bytes"] = _size_or_explicit(args.stl, args.stl_size_bytes)
        entry["stl_target_size_mm"] = args.stl_size_mm
        entry["prepared_for_print"] = True
        entry["print_prepared_at"] = now
    else:
        entry.setdefault("stl_path", "")
        entry.setdefault("prepared_for_print", False)

    if args.engine_path:
        entry["engine_path"] = args.engine_path

    # ----- Nested v3 blocks -----
    model_block = _build_model_block(existing, args, now)
    if model_block:
        entry["model"] = model_block

    generation_block = _build_generation_block(existing, args)
    if generation_block:
        entry["generation"] = generation_block

    print_block = _build_print_block(existing, args)
    if print_block:
        entry["print"] = print_block

    entry["eval"] = _build_eval_block(existing, args)

    if args.source_wrapper_json:
        entry["source_wrapper"] = _json_or_default(args.source_wrapper_json, {})

    # ----- Persist -----
    action = "updated" if existing else "added"
    data["assets"][args.name] = entry
    data["version"] = 3

    with open(manifest_path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")

    flags = []
    if entry.get("clean_path"):
        flags.append(f"3D:{entry.get('polycount_target')}p")
    if entry.get("prepared_for_print"):
        flags.append(f"PRINT:{entry.get('stl_target_size_mm')}mm")
    bucket = (entry.get("model") or {}).get("license_bucket") or args.license_bucket
    if bucket:
        flags.append(f"LIC:{bucket}")
    flags_str = " ".join(flags) or "2D-only"
    print(f"[manifest] {action}: {args.name} ({args.category}, {args.generator}, "
          f"{flags_str}) -> {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
