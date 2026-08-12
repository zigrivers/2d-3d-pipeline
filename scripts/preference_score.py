#!/usr/bin/env python3
"""v0.3.5 — ImageReward human-preference scoring (item 16 of the
2026-08 generation-quality refresh).

ImageReward (Apache 2.0; commercial_safe) scores an image against a
prompt on learned human aesthetic/alignment preference, complementing
SigLIP2's prompt-adherence signal (scripts/clip_score.py) — a good
CLIP/SigLIP match can still look bad; this catches that case.

Writes clip.image_reward into the meta.json (same section as
clip_score.py per the merge contract — image_reward is a sibling
field, not a new section).

Usage:
    preference_score.py --prompt TEXT --image PATH --meta PATH [--json]
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

IMAGE_REWARD_MODEL = "ImageReward-v1.0"


def _apply_transformers_compat_shim() -> None:
    """ImageReward's vendored BLIP/BERT implementation imports three
    pruning-related helpers from transformers.modeling_utils that were
    relocated (apply_chunking_to_forward, prune_linear_layer, both now
    in transformers.pytorch_utils) or removed outright
    (find_pruneable_heads_and_indices) in modern transformers releases.
    SigLIP2 (clip_score.py) needs a modern transformers; ImageReward's
    upstream package hasn't been updated for it. Shimming here keeps
    both scorers in one pipeline-tools-env venv instead of forking it.
    Safe: this utility's implementation has been stable for years; the
    body below is the last version transformers shipped before removal.
    """
    import transformers.modeling_utils as mu

    if hasattr(mu, "find_pruneable_heads_and_indices"):
        return  # already present (older transformers) or already shimmed

    import torch
    import transformers.pytorch_utils as pu

    def find_pruneable_heads_and_indices(heads, n_heads, head_size, already_pruned_heads):
        mask = torch.ones(n_heads, head_size)
        heads = set(heads) - already_pruned_heads
        for head in heads:
            head = head - sum(1 if h < head else 0 for h in already_pruned_heads)
            mask[head] = 0
        mask = mask.view(-1).contiguous().eq(1)
        index = torch.arange(len(mask))[mask].long()
        return heads, index

    mu.apply_chunking_to_forward = pu.apply_chunking_to_forward
    mu.find_pruneable_heads_and_indices = find_pruneable_heads_and_indices
    mu.prune_linear_layer = pu.prune_linear_layer


def _imports():
    try:
        _apply_transformers_compat_shim()
        import ImageReward as RM  # type: ignore
        return RM
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); skipping. Activate pipeline-tools-env.",
              file=sys.stderr)
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--prompt", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--device", default="mps", help="torch device (default: mps)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    RM = _imports()
    if RM is None:
        return 0  # graceful no-op, matches clip_score.py's convention

    t0 = time.time()
    try:
        model = RM.load(IMAGE_REWARD_MODEL, device=args.device)
        score = float(model.score(args.prompt, os.path.expanduser(args.image)))
    except Exception as e:
        print(f"[image-reward] ERROR: scoring failed ({e}); skipping", file=sys.stderr)
        return 0
    duration = round(time.time() - t0, 2)

    payload = {
        "image_reward": round(score, 3),
        "image_reward_model": IMAGE_REWARD_MODEL,
        "image_reward_duration_seconds": duration,
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
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"[image-reward] score: {score:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
