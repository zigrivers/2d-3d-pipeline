# Multi-view backend benchmark

Scaffolding for item 12 Phase 1 in
[`docs/improvement-spec.md`](../../docs/improvement-spec.md). See also
[`docs/improvement-plan.md`](../../docs/improvement-plan.md) (P3.1a).

The benchmark compares candidate multi-view 3D-reconstruction
backends (TRELLIS multi-view, InstantMesh, OpenLRM) against the same
dataset to produce a recommendation, written up at
`docs/multiview-backend-research.md` (P3.1b).

## Directory layout

```
tests/multiview-bench/
  README.md                 (this file)
  scoring_rubric.json       (rubric, thresholds, candidates)
  subjects/                 (input dataset — placeholder until populated)
    subject-1-character/
      README.md             (lists expected views)
      <front,right,back,left>.png
    subject-2-hardsurface/
    subject-3-organic/
  results/                  (per-run GLBs + benchmark_results.json)
    <backend>/<subject>/run00.glb …
```

## How to run

```bash
# Once the dataset is populated:
python3 scripts/multiview_benchmark.py \
    --backends trellis,instantmesh,openlrm \
    --runs-per-subject 3

# After visual scoring is filled into results/benchmark_results.json:
python3 scripts/multiview_benchmark.py --score-only
```

## What this PR (P3.1a) ships

- The harness (`scripts/multiview_benchmark.py`)
- The scoring rubric (`scoring_rubric.json`)
- The directory layout + placeholder subject READMEs

## What this PR does NOT ship

- Actual reference images for the three subjects (depends on
  real-world photo capture or a curated scan dataset)
- Backend adapters (`scripts/multiview_backends/*.py`) — these
  ship in P3.1b alongside the actual backend installs
- A populated `benchmark_results.json` with per-run scores — that's
  the deliverable of P3.1b before the recommendation lands

## Why this scaffolding ships separately

Per the v3 spec (item 12, Phase 1), the methodology should be
fixed and reproducible BEFORE the benchmark runs. Shipping the
scaffold first lets us:

- Review and refine the rubric in isolation
- Capture the dataset against a known target structure
- Add adapters one at a time without re-organising the layout
