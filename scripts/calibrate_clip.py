#!/usr/bin/env python3
"""v0.3 — auto-calibrate per-model CLIP percentile bands.

Recomputes `scripts/clip_calibration.json` from your own concept
generations so the per-model bands (p10 / p25 / p50) reflect your
actual prompts + model usage rather than the seed values from
research.

How calibration works:
  1. Walk an asset manifest (default: ~/3d-pipeline/workspace/asset_manifest.json)
     looking for entries with both a `concept_path` (PNG) AND a
     `generation.prompt` or top-level `prompt`.
  2. Group by `generator` (z-image-turbo / flux-schnell / flux-dev /
     qwen-image).
  3. For each model with >= MIN_SAMPLES generations, compute a fresh
     CLIP similarity score per (image, prompt) pair via clip_score.py
     (silent — JSON mode).
  4. Compute the new p50, p25, p10 percentiles per model.
  5. Write the result to `scripts/clip_calibration.json`, keeping
     models below MIN_SAMPLES as-is so partial calibration doesn't
     wipe known-good defaults.

Usage:
    calibrate_clip.py [--manifest PATH] [--out PATH] [--min-samples 20]
                      [--dry-run] [--json]

Recommended cadence: re-run after every ~100 new concept generations
or quarterly, whichever comes first. No manual intervention required;
add it to a cron / launchd job if you want the bands to keep up
automatically as your prompt patterns evolve.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CLIP_SCORE = SCRIPT_DIR / "clip_score.py"
DEFAULT_CALIBRATION = SCRIPT_DIR / "clip_calibration.json"
DEFAULT_MANIFEST = Path(os.path.expanduser("~/3d-pipeline/workspace/asset_manifest.json"))
MIN_SAMPLES = 20

# Models we calibrate. Anything in the manifest with a generator name
# outside this set is ignored (e.g., SF3D — that's a 3D model, not 2D).
CALIBRATABLE_MODELS = {"z-image-turbo", "flux-schnell", "flux-dev", "qwen-image"}


def _percentile(values: list[float], q: float) -> float:
    """Simple percentile (no numpy dep). q is in [0, 100]."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = (q / 100.0) * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _extract_pair(entry: dict) -> tuple[str, str, str] | None:
    """Pull (generator, concept_path, prompt) from a manifest entry."""
    generator = entry.get("generator") or (entry.get("model") or {}).get("name")
    concept_path = entry.get("concept_path")
    prompt = entry.get("prompt") or (entry.get("generation") or {}).get("prompt")
    if not (generator and concept_path and prompt):
        return None
    if generator not in CALIBRATABLE_MODELS:
        return None
    cp = Path(os.path.expanduser(concept_path))
    if not cp.exists():
        return None
    return generator, str(cp), prompt


def _score_one(image_path: str, prompt: str, model_name: str) -> float | None:
    """Run clip_score.py once, return raw similarity. None on failure."""
    if not CLIP_SCORE.exists():
        return None
    with tempfile.NamedTemporaryFile(suffix=".meta.json", delete=False) as tmp:
        meta_path = tmp.name
    try:
        cp = subprocess.run(
            [sys.executable, str(CLIP_SCORE),
             "--prompt", prompt,
             "--image", image_path,
             "--meta", meta_path,
             "--model-name", model_name,
             "--json"],
            capture_output=True, text=True, timeout=120,
        )
        if cp.returncode != 0 or not cp.stdout.strip():
            return None
        last = cp.stdout.strip().splitlines()[-1]
        data = json.loads(last)
        return float(data.get("similarity"))
    except Exception:
        return None
    finally:
        try:
            os.unlink(meta_path)
        except FileNotFoundError:
            pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST),
                   help="Path to asset_manifest.json (default: ~/3d-pipeline/workspace/...)")
    p.add_argument("--out", default=str(DEFAULT_CALIBRATION),
                   help="Where to write the new calibration JSON")
    p.add_argument("--min-samples", type=int, default=MIN_SAMPLES,
                   help="Models with fewer than N scored samples are left untouched")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute + report but don't write")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON summary on stdout")
    args = p.parse_args()

    manifest_path = Path(os.path.expanduser(args.manifest))
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: manifest is not valid JSON: {e}", file=sys.stderr)
        return 2

    # v2/v3 manifests have {assets: {name: entry, ...}}. v1 list-of-assets is
    # auto-migrated by update_manifest.py, but tolerate both shapes here.
    assets = manifest.get("assets") or {}
    if isinstance(assets, list):
        entries = assets
    else:
        entries = list(assets.values())

    pairs_by_model: dict[str, list[tuple[str, str]]] = {}
    for entry in entries:
        triple = _extract_pair(entry)
        if not triple:
            continue
        gen, img, prompt = triple
        pairs_by_model.setdefault(gen, []).append((img, prompt))

    scores_by_model: dict[str, list[float]] = {}
    for model_name, pairs in pairs_by_model.items():
        scores: list[float] = []
        for img, prompt in pairs:
            s = _score_one(img, prompt, model_name)
            if s is not None:
                scores.append(s)
        scores_by_model[model_name] = scores

    # Load existing calibration so we can keep models we didn't recalibrate.
    out_path = Path(os.path.expanduser(args.out))
    existing = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
        except Exception:
            pass

    new_calibration = dict(existing)
    new_calibration["_calibrated"] = {
        "at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "manifest": str(manifest_path),
        "min_samples": args.min_samples,
    }

    summary: list[dict] = []
    for model_name, scores in scores_by_model.items():
        if len(scores) < args.min_samples:
            summary.append({
                "model": model_name,
                "scored": len(scores),
                "status": "skipped_too_few_samples",
                "min_samples": args.min_samples,
            })
            continue
        bands = {
            "p50": round(_percentile(scores, 50), 4),
            "p25": round(_percentile(scores, 25), 4),
            "p10": round(_percentile(scores, 10), 4),
            "n_samples": len(scores),
        }
        new_calibration[model_name] = bands
        summary.append({"model": model_name, "scored": len(scores), "status": "updated", "bands": bands})

    if not args.dry_run:
        out_path.write_text(json.dumps(new_calibration, indent=2, sort_keys=True) + "\n")

    if args.json:
        print(json.dumps({
            "manifest": str(manifest_path),
            "out": str(out_path),
            "dry_run": args.dry_run,
            "summary": summary,
        }, indent=2, sort_keys=True))
    else:
        print(f"[calibrate-clip] manifest: {manifest_path}")
        for row in summary:
            if row["status"] == "updated":
                b = row["bands"]
                print(f"[calibrate-clip] {row['model']}: p50={b['p50']} p25={b['p25']} "
                      f"p10={b['p10']} (n={b['n_samples']})")
            else:
                print(f"[calibrate-clip] {row['model']}: skipped (only {row['scored']} "
                      f"sample(s); need {row['min_samples']})")
        if args.dry_run:
            print("[calibrate-clip] DRY RUN — no write")
        else:
            print(f"[calibrate-clip] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
