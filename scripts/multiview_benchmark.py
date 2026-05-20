#!/usr/bin/env python3
"""v0.4 — multi-view backend benchmark harness.

Runs the same N candidate backends against the same dataset and
emits structured scoring + per-output GLBs for visual review.

Per item 12 Phase 1 in improvement-spec.md, the dataset is fixed:
3 subjects (character / hard-surface / organic), 4 calibrated views
each (0°, 90°, 180°, 270°), all 1024×1024 PNGs. Scoring rubric:

  Geometric accuracy   weight 0.35  (Hausdorff vs GT, or visual)
  Texture / colour     weight 0.20
  Speed (studio)       weight 0.15
  Speed (laptop)       weight 0.10
  Install footprint    weight 0.10
  License clarity      weight 0.10

Pass/fail: weighted total >= 6.5 / 10. No single dimension < 3.0.
License score >= 4 (`non_commercial` floor; anything `unclear_risky`
without a separate review is disqualified).

Usage:
    multiview_benchmark.py --dataset DIR --rubric PATH
                           [--backends trellis,instantmesh,openlrm]
                           [--runs-per-subject 3]
                           [--output-dir tests/multiview-bench/results]
                           [--score-only]

The harness reads each subject's `meta.json` for the `input_pipeline`
field (synthetic / mvgen). Results are recorded per-(backend, subject,
run) with the input_pipeline carried through so `--score-only` can
roll up scores per (backend, input_pipeline) — the diagnostic that
tells you whether a backend's failure mode is "bad at reconstruction"
(both pipelines fail) or "bad at handling AI-generated views" (only
mvgen fails).

Backend adapters live in tools/multiview_backends/<name>.py — they're
maintainer tooling, not pipeline runtime, so they bypass the
canonical-vs-embedded rule. Each adapter exposes:

    adapter.py --views v0,v1,v2,v3 --output-glb PATH --json

P3.1a shipped this harness + the rubric + the dataset layout.
P3.1a.1 added the dataset builders (Option B + Option C) and the
input-pipeline-aware rollup. P3.1b will populate adapters + run the
benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ADAPTERS_DIR = REPO_ROOT / "tools" / "multiview_backends"
DEFAULT_DATASET = REPO_ROOT / "tests" / "multiview-bench" / "subjects"
DEFAULT_RUBRIC = REPO_ROOT / "tests" / "multiview-bench" / "scoring_rubric.json"
DEFAULT_OUTPUT = REPO_ROOT / "tests" / "multiview-bench" / "results"

# Subjects must have at LEAST these view names for the harness to
# consider them runnable. Other view names (e.g. Zero123++'s v030_30,
# v090_neg20) are accepted too — we pass the full set of PNGs.
MIN_VIEW_COUNT = 3


def _load_subject_meta(sub: Path) -> dict:
    meta_path = sub / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return {}


def discover_subjects(dataset_dir: Path) -> list[dict]:
    """Walk dataset_dir/* and inventory each subject directory.

    Returns one record per subject with:
      name           — directory basename
      path           — absolute path
      views          — {view_name: image_path}
      view_paths     — list of all view PNG paths (for the adapter call)
      input_pipeline — "synthetic" / "mvgen" / "" (from meta.json)
      mv_2d_model    — present when input_pipeline=mvgen (from meta.json)
      ground_truth   — path to ground_truth.glb if present, else ""
      complete       — True iff len(view_paths) >= MIN_VIEW_COUNT
    """
    subjects: list[dict] = []
    if not dataset_dir.exists():
        return subjects
    for sub in sorted(dataset_dir.iterdir()):
        if not sub.is_dir():
            continue
        meta = _load_subject_meta(sub)
        # Prefer the meta.json's view list (records both names + angles).
        if meta.get("views") and isinstance(meta["views"], list):
            views = {v["name"]: v["path"] for v in meta["views"] if "name" in v and "path" in v}
            view_paths = [v["path"] for v in meta["views"] if "path" in v]
        else:
            # Fall back to scanning PNGs by filename (concept.png excluded).
            images = sorted(p for p in sub.glob("*.png") if p.name != "concept.png")
            views = {p.stem: str(p) for p in images}
            view_paths = [str(p) for p in images]
        gt = sub / "ground_truth.glb"
        subjects.append({
            "name": sub.name,
            "path": str(sub),
            "views": views,
            "view_paths": view_paths,
            "input_pipeline": meta.get("input_pipeline", ""),
            "mv_2d_model": meta.get("mv_2d_model"),
            "ground_truth": str(gt) if gt.exists() else "",
            "complete": len(view_paths) >= MIN_VIEW_COUNT,
        })
    return subjects


def run_backend(backend: str, subject: dict, output_dir: Path,
                runs_per_subject: int) -> list[dict]:
    """Invoke a backend adapter (tools/multiview_backends/<backend>.py).
    Each adapter is expected to expose:
        adapter.py --views v0,v1,v2,v3 --output-glb PATH --json
    and report its own duration + license bucket.
    """
    adapter = ADAPTERS_DIR / f"{backend}.py"
    runs: list[dict] = []
    if not adapter.exists():
        runs.append({
            "backend": backend,
            "subject": subject["name"],
            "input_pipeline": subject.get("input_pipeline", ""),
            "run": 0,
            "status": "adapter_missing",
            "reason": f"no adapter at {adapter}",
        })
        return runs

    view_paths = subject.get("view_paths") or []
    if len(view_paths) < MIN_VIEW_COUNT:
        runs.append({
            "backend": backend,
            "subject": subject["name"],
            "input_pipeline": subject.get("input_pipeline", ""),
            "run": 0,
            "status": "skipped",
            "reason": f"insufficient views (have {len(view_paths)}, need {MIN_VIEW_COUNT})",
        })
        return runs

    for i in range(runs_per_subject):
        target_glb = output_dir / backend / subject["name"] / f"run{i:02d}.glb"
        target_glb.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            cp = subprocess.run(
                [sys.executable, str(adapter),
                 "--views", ",".join(view_paths),
                 "--output-glb", str(target_glb),
                 "--json"],
                capture_output=True, text=True, timeout=600,
            )
            duration = round(time.time() - t0, 2)
            parsed = {}
            if cp.stdout.strip():
                try:
                    parsed = json.loads(cp.stdout.strip().splitlines()[-1])
                except Exception:
                    pass
            runs.append({
                "backend": backend,
                "subject": subject["name"],
                "input_pipeline": subject.get("input_pipeline", ""),
                "mv_2d_model": subject.get("mv_2d_model"),
                "ground_truth": subject.get("ground_truth"),
                "run": i,
                "exit_code": cp.returncode,
                "duration_seconds": duration,
                "output_glb": str(target_glb) if target_glb.exists() else None,
                "adapter_result": parsed,
                "status": "ok" if cp.returncode == 0 else "failed",
                # Placeholder scores — fill in manually after visual review.
                "scores": {
                    "geometric_accuracy": None,
                    "texture_fidelity": None,
                    "speed_studio": None,
                    "speed_laptop": None,
                    "install_footprint": None,
                    "license_clarity": None,
                },
            })
        except subprocess.TimeoutExpired:
            runs.append({
                "backend": backend,
                "subject": subject["name"],
                "input_pipeline": subject.get("input_pipeline", ""),
                "run": i,
                "status": "timeout",
                "duration_seconds": round(time.time() - t0, 2),
            })
        except Exception as e:
            runs.append({
                "backend": backend,
                "subject": subject["name"],
                "input_pipeline": subject.get("input_pipeline", ""),
                "run": i,
                "status": "error",
                "error": str(e),
            })
    return runs


def _weighted_total(scores: dict, weights: dict) -> float | None:
    """Compute weighted total only when every dimension has a score."""
    parts = []
    for dim, w in weights.items():
        s = scores.get(dim)
        if s is None:
            return None
        parts.append(float(s) * float(w))
    return round(sum(parts), 2)


def _rollup_by_pipeline(runs: list[dict], rubric: dict) -> dict:
    """Per (backend, input_pipeline) average of the weighted totals.
    Surfaces the diagnostic the v3 spec calls for: a backend's
    intrinsic quality (synthetic) vs its production-chain quality
    (mvgen). Delta = the MV-2D model's tax."""
    weights = {dim: meta["weight"] for dim, meta in rubric.get("dimensions", {}).items()}
    if not weights:
        return {}
    by_key: dict[tuple[str, str], list[float]] = defaultdict(list)
    for run in runs:
        if run.get("status") != "ok":
            continue
        wt = _weighted_total(run.get("scores") or {}, weights)
        if wt is None:
            continue
        key = (run["backend"], run.get("input_pipeline", "") or "unknown")
        by_key[key].append(wt)
    rollup: dict[str, dict] = {}
    for (backend, pipeline), values in by_key.items():
        rollup.setdefault(backend, {})[pipeline] = {
            "mean_weighted_total": round(sum(values) / len(values), 2),
            "runs": len(values),
        }
    # Compute synthetic-vs-mvgen delta per backend when both exist.
    for backend, by_pipe in rollup.items():
        synth = by_pipe.get("synthetic")
        mvgen = by_pipe.get("mvgen")
        if synth and mvgen:
            by_pipe["delta_synthetic_minus_mvgen"] = round(
                synth["mean_weighted_total"] - mvgen["mean_weighted_total"], 2
            )
    return rollup


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p.add_argument("--rubric", default=str(DEFAULT_RUBRIC))
    p.add_argument("--backends", default="trellis,instantmesh,openlrm",
                   help="Comma-separated backend names; expects adapters at "
                        "tools/multiview_backends/<name>.py")
    p.add_argument("--runs-per-subject", type=int, default=3)
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    p.add_argument("--score-only", action="store_true",
                   help="Skip running backends; recompute summary from existing runs")
    args = p.parse_args()

    dataset_dir = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rubric_path = Path(args.rubric)
    rubric = json.loads(rubric_path.read_text()) if rubric_path.exists() else {}

    subjects = discover_subjects(dataset_dir)
    if not any(s["complete"] for s in subjects):
        print("ERROR: no complete subject (need >= 3 view PNGs).",
              file=sys.stderr)
        print(f"Dataset: {dataset_dir}", file=sys.stderr)
        return 2

    results_path = output_dir / "benchmark_results.json"
    if args.score_only:
        # Reload existing results and recompute rollup.
        if not results_path.exists():
            print(f"ERROR: --score-only but no prior results at {results_path}",
                  file=sys.stderr)
            return 2
        prior = json.loads(results_path.read_text())
        all_runs = prior.get("runs", [])
    else:
        backends = [b.strip() for b in args.backends.split(",") if b.strip()]
        all_runs = []
        for subject in subjects:
            if not subject["complete"]:
                continue
            for backend in backends:
                runs = run_backend(backend, subject, output_dir, args.runs_per_subject)
                all_runs.extend(runs)

    rollup = _rollup_by_pipeline(all_runs, rubric)

    summary = {
        "dataset": str(dataset_dir),
        "rubric": rubric,
        "subjects": [
            {"name": s["name"],
             "complete": s["complete"],
             "input_pipeline": s.get("input_pipeline"),
             "mv_2d_model": s.get("mv_2d_model"),
             "ground_truth": s.get("ground_truth")}
            for s in subjects
        ],
        "runs": all_runs,
        "rollup_by_backend_and_pipeline": rollup,
        "note": (
            "Per-dimension scores live under runs[].scores and are entered "
            "manually after visual review. Re-run with `--score-only` to "
            "recompute the rollup once scores are filled in."
        ),
    }
    with open(results_path, "w") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"[multiview-bench] wrote {results_path}")
    print(f"[multiview-bench] subjects: {len(subjects)} "
          f"(complete: {sum(1 for s in subjects if s['complete'])})")
    print(f"[multiview-bench] total runs: {len(all_runs)}")
    if rollup:
        print(f"[multiview-bench] backends with scored runs: {sorted(rollup.keys())}")
        for backend, by_pipe in sorted(rollup.items()):
            for pipeline, stats in sorted(by_pipe.items()):
                if pipeline.startswith("delta_"):
                    continue
                print(f"[multiview-bench]   {backend} / {pipeline}: "
                      f"{stats['mean_weighted_total']} ({stats['runs']} run(s))")
            if "delta_synthetic_minus_mvgen" in by_pipe:
                print(f"[multiview-bench]   {backend}  Δ synth-mvgen: "
                      f"{by_pipe['delta_synthetic_minus_mvgen']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
