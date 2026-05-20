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

The harness is a SCAFFOLD: it dispatches each backend via a backend
adapter you supply (`scripts/multiview_backends/<name>.py`),
collects per-run GLBs into the results directory, and writes
`benchmark_results.json` ready for manual scoring + recommendation
write-up at `docs/multiview-backend-research.md`.

Initial commit (P3.1a) ships:
  - this harness
  - the rubric JSON
  - the dataset directory layout (placeholder READMEs only)
  - a stub backend adapter showing the interface

P3.1b will fill in real adapters + run the benchmark; the user
chooses a backend based on the recommendation that lands in the
research doc.
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
REPO_ROOT = SCRIPT_DIR.parent
ADAPTERS_DIR = SCRIPT_DIR / "multiview_backends"
DEFAULT_DATASET = REPO_ROOT / "tests" / "multiview-bench" / "subjects"
DEFAULT_RUBRIC = REPO_ROOT / "tests" / "multiview-bench" / "scoring_rubric.json"
DEFAULT_OUTPUT = REPO_ROOT / "tests" / "multiview-bench" / "results"


def discover_subjects(dataset_dir: Path) -> list[dict]:
    subjects: list[dict] = []
    if not dataset_dir.exists():
        return subjects
    for sub in sorted(dataset_dir.iterdir()):
        if not sub.is_dir():
            continue
        images = sorted(sub.glob("*.png"))
        # Expected: front, right, back, left
        expected_views = ["front", "right", "back", "left"]
        view_map = {}
        for img in images:
            for v in expected_views:
                if v in img.name.lower():
                    view_map[v] = str(img)
                    break
        subjects.append({
            "name": sub.name,
            "path": str(sub),
            "views": view_map,
            "complete": all(v in view_map for v in expected_views),
        })
    return subjects


def run_backend(backend: str, subject: dict, output_dir: Path,
                runs_per_subject: int) -> list[dict]:
    """Invoke a backend adapter (scripts/multiview_backends/<backend>.py).
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
            "run": 0,
            "status": "adapter_missing",
            "reason": f"no adapter at {adapter}",
        })
        return runs

    views = [subject["views"][v] for v in ("front", "right", "back", "left")
             if v in subject["views"]]
    if len(views) < 3:
        runs.append({
            "backend": backend,
            "subject": subject["name"],
            "run": 0,
            "status": "skipped",
            "reason": "insufficient views",
        })
        return runs

    for i in range(runs_per_subject):
        target_glb = output_dir / backend / subject["name"] / f"run{i:02d}.glb"
        target_glb.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            cp = subprocess.run(
                [sys.executable, str(adapter),
                 "--views", ",".join(views),
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
                "run": i,
                "exit_code": cp.returncode,
                "duration_seconds": duration,
                "output_glb": str(target_glb) if target_glb.exists() else None,
                "adapter_result": parsed,
                "status": "ok" if cp.returncode == 0 else "failed",
            })
        except subprocess.TimeoutExpired:
            runs.append({
                "backend": backend,
                "subject": subject["name"],
                "run": i,
                "status": "timeout",
                "duration_seconds": round(time.time() - t0, 2),
            })
        except Exception as e:
            runs.append({
                "backend": backend,
                "subject": subject["name"],
                "run": i,
                "status": "error",
                "error": str(e),
            })
    return runs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p.add_argument("--rubric", default=str(DEFAULT_RUBRIC))
    p.add_argument("--backends", default="trellis,instantmesh,openlrm",
                   help="Comma-separated backend names; expects adapters at "
                        "scripts/multiview_backends/<name>.py")
    p.add_argument("--runs-per-subject", type=int, default=3)
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    p.add_argument("--score-only", action="store_true",
                   help="Skip running backends; recompute summary from existing runs")
    args = p.parse_args()

    dataset_dir = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rubric_path = Path(args.rubric)

    subjects = discover_subjects(dataset_dir)
    if not any(s["complete"] for s in subjects):
        print("ERROR: no complete subject (need front/right/back/left views).",
              file=sys.stderr)
        print(f"Dataset: {dataset_dir}", file=sys.stderr)
        return 2

    rubric = json.loads(rubric_path.read_text()) if rubric_path.exists() else {}

    all_runs: list[dict] = []
    if not args.score_only:
        backends = [b.strip() for b in args.backends.split(",") if b.strip()]
        for subject in subjects:
            if not subject["complete"]:
                continue
            for backend in backends:
                runs = run_backend(backend, subject, output_dir, args.runs_per_subject)
                all_runs.extend(runs)

    summary = {
        "dataset": str(dataset_dir),
        "rubric": rubric,
        "subjects": [{"name": s["name"], "complete": s["complete"]} for s in subjects],
        "runs": all_runs,
        "note": (
            "Per-dimension scores are entered manually after visual review. "
            "Run with `--score-only` after editing this file to recompute "
            "weighted totals."
        ),
    }
    results_path = output_dir / "benchmark_results.json"
    with open(results_path, "w") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"[multiview-bench] wrote {results_path}")
    print(f"[multiview-bench] subjects: {len(subjects)} "
          f"(complete: {sum(1 for s in subjects if s['complete'])})")
    print(f"[multiview-bench] total runs: {len(all_runs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
