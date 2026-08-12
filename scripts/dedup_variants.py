#!/usr/bin/env python3
"""v0.3.5 — DreamSim near-duplicate detection among -n N variants
(item 16 of the 2026-08 generation-quality refresh).

DreamSim (MIT; commercial_safe) is a perceptual-similarity model
trained to match human judgments of "these look like the same image"
better than pixel or CLIP-space distance. Used to flag near-duplicate
variants among a `concept.sh -n N` batch so the skill can tell the
user "variants 2 and 4 are near-duplicates" instead of presenting N
images that are mostly the same picture.

Writes clip.dreamsim_dupes (list of duplicate-group index lists) into
the meta.json of the first/primary variant — same section as
clip_score.py per the merge contract.

Usage:
    dedup_variants.py --images PATH1 PATH2 ... --meta PATH [--threshold 0.15] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
META_HELPER = SCRIPT_DIR / "meta_helper.py"

# DreamSim defaults to a relative "./models" cache_dir, which drops ~3 GB
# wherever the caller's cwd happens to be. Route it alongside this
# pipeline's other model caches (see U2NET_HOME / OPEN_CLIP_CACHE_DIR).
DREAMSIM_CACHE_DIR = os.environ.get(
    "DREAMSIM_CACHE_DIR",
    os.path.expanduser("~/3d-pipeline/models/dreamsim"),
)

# DreamSim distance: 0 = identical, ~1 = maximally different for natural
# images. Below this threshold, two variants are considered near-dupes.
# Bootstrap default; recalibrate alongside clip_calibration.json once
# real -n N batches accumulate.
DEFAULT_THRESHOLD = 0.15


def _imports():
    try:
        import torch  # type: ignore
        from dreamsim import dreamsim  # type: ignore
        from PIL import Image  # type: ignore
        return dreamsim, torch, Image
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); skipping. Activate pipeline-tools-env.",
              file=sys.stderr)
        return None, None, None


def _dedupe_groups(distances: dict[tuple[int, int], float], n: int, threshold: float) -> list[list[int]]:
    """Union-find over pairs below threshold; returns groups of size >= 2."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (i, j), d in distances.items():
        if d < threshold:
            union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--images", nargs="+", required=True,
                   help="Variant image paths, in generation order")
    p.add_argument("--meta", required=True)
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"DreamSim distance below which two images count as "
                        f"near-duplicates (default: {DEFAULT_THRESHOLD})")
    p.add_argument("--device", default="mps", help="torch device (default: mps)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if len(args.images) < 2:
        print("[dreamsim] fewer than 2 images; nothing to dedupe", file=sys.stderr)
        return 0

    dreamsim, torch, Image = _imports()
    if dreamsim is None:
        return 0

    t0 = time.time()
    Path(DREAMSIM_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    model, preprocess = dreamsim(pretrained=True, device=args.device, cache_dir=DREAMSIM_CACHE_DIR)

    image_paths = [Path(os.path.expanduser(p)) for p in args.images]
    tensors = [preprocess(Image.open(p).convert("RGB")).to(args.device) for p in image_paths]

    distances: dict[tuple[int, int], float] = {}
    with torch.no_grad():
        for i in range(len(tensors)):
            for j in range(i + 1, len(tensors)):
                d = float(model(tensors[i], tensors[j]).item())
                distances[(i, j)] = d

    duration = round(time.time() - t0, 2)
    groups = _dedupe_groups(distances, len(tensors), args.threshold)

    payload = {
        "dreamsim_dupes": groups,
        "dreamsim_threshold": args.threshold,
        "dreamsim_duration_seconds": duration,
    }
    meta_path = Path(os.path.expanduser(args.meta))
    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "clip",
         "--data", json.dumps(payload)],
        check=False,
        capture_output=True,
    )
    if args.json:
        print(json.dumps({
            **payload,
            "pairwise_distances": {f"{i}-{j}": round(d, 3) for (i, j), d in distances.items()},
        }, indent=2, sort_keys=True))
    else:
        if groups:
            for g in groups:
                names = ", ".join(str(i + 1) for i in g)
                print(f"[dreamsim] variants {names} are near-duplicates")
        else:
            print("[dreamsim] no near-duplicate variants found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
