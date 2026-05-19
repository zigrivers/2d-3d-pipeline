#!/usr/bin/env python3
"""
Idempotent updater for the asset pipeline manifest.

Supports three kinds of records:
  - 2D-only assets (concept image, no 3D)
  - 3D assets (concept + 3D mesh)
  - Print-ready variants (3D mesh prepared as STL for the Snapmaker U1)

A single named asset can accumulate all three over time. Running the
script with new --stl info on an existing 3D asset updates that record
in place rather than creating a duplicate.

Usage (2D only):
  update_manifest.py --manifest <path> --name <name> --concept <png> \\
      --generator z-image-turbo --category 2d-only

Usage (3D):
  update_manifest.py --manifest <path> --name <name> --concept <png> \\
      --raw <glb> --clean <glb> --generator sf3d --polycount 3000 \\
      --category prop

Usage (after print prep):
  update_manifest.py --manifest <path> --name <name> --concept <png> \\
      --stl <stl> --stl-size-mm 50 --generator sf3d --category prop
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True, help="Path to asset_manifest.json")
    p.add_argument("--name", required=True, help="Logical asset name (no extension)")
    p.add_argument("--concept", required=True, help="Path to 2D concept image")
    p.add_argument("--raw", default="", help="Path to raw 3D generator output (GLB)")
    p.add_argument("--clean", default="", help="Path to cleaned 3D GLB")
    p.add_argument("--stl", default="", help="Path to print-ready STL")
    p.add_argument("--stl-size-mm", type=float, default=0.0,
                   help="Longest dimension in mm of the STL (if provided)")
    p.add_argument("--generator", required=True,
                   choices=["sf3d", "trellis", "z-image-turbo",
                            "flux-schnell", "flux-dev", "qwen-image"])
    p.add_argument("--polycount", type=int, default=0,
                   help="Target polycount of the cleaned 3D mesh (0 for 2D-only)")
    p.add_argument("--category", required=True,
                   choices=["prop", "character", "hero", "environment",
                            "weapon", "vehicle", "2d-only"])
    p.add_argument("--notes", default="", help="One-line description")
    args = p.parse_args()

    manifest_path = Path(os.path.expanduser(args.manifest))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    if manifest_path.exists():
        with open(manifest_path) as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"ERROR: existing manifest is not valid JSON: {e}", file=sys.stderr)
                sys.exit(1)
    else:
        data = {"version": 2, "assets": {}}

    data.setdefault("version", 2)
    data.setdefault("assets", {})

    def size_or_none(path_str):
        if not path_str:
            return None
        p = Path(os.path.expanduser(path_str))
        return p.stat().st_size if p.exists() else None

    now = datetime.now().isoformat(timespec="seconds")
    existing = data["assets"].get(args.name, {})

    # Preserve fields that aren't part of this update
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

    # Only set 3D fields if the user is updating those
    if args.raw or "raw_path" not in entry:
        entry["raw_path"] = args.raw or entry.get("raw_path", "")
        entry["raw_size_bytes"] = size_or_none(args.raw) if args.raw else entry.get("raw_size_bytes")
    if args.clean or "clean_path" not in entry:
        entry["clean_path"] = args.clean or entry.get("clean_path", "")
        entry["clean_size_bytes"] = size_or_none(args.clean) if args.clean else entry.get("clean_size_bytes")
    if args.polycount or "polycount_target" not in entry:
        entry["polycount_target"] = args.polycount or entry.get("polycount_target", 0)

    # Print-output fields — only populated when this update includes --stl
    if args.stl:
        entry["stl_path"] = args.stl
        entry["stl_size_bytes"] = size_or_none(args.stl)
        entry["stl_target_size_mm"] = args.stl_size_mm
        entry["prepared_for_print"] = True
        entry["print_prepared_at"] = now
    else:
        entry.setdefault("stl_path", "")
        entry.setdefault("prepared_for_print", False)

    action = "updated" if existing else "added"
    data["assets"][args.name] = entry

    with open(manifest_path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")

    # Summary line
    flags = []
    if entry.get("clean_path"):
        flags.append(f"3D:{entry.get('polycount_target')}p")
    if entry.get("prepared_for_print"):
        flags.append(f"PRINT:{entry.get('stl_target_size_mm')}mm")
    flags_str = " ".join(flags) or "2D-only"
    print(f"[manifest] {action}: {args.name} ({args.category}, {args.generator}, {flags_str}) "
          f"-> {manifest_path}")


if __name__ == "__main__":
    main()
