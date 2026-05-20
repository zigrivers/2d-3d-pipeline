# Multi-view backend research

**Status:** AWAITING DATA · **P3.1b — recommendation deliverable**

This doc is the formal write-up that closes P3.1b in
[`docs/improvement-plan.md`](improvement-plan.md). The harness and
adapters are ready (see `scripts/multiview_benchmark.py` + the
backend adapters at `tools/multiview_backends/`); what's left is:

1. Source GLBs go into `tests/multiview-bench/sources/` (you provide)
2. Datasets built via the P3.1a.1 tooling
3. Backend installs at `~/3d-pipeline/{trellis-mac,InstantMesh,openlrm}/`
4. Run the benchmark
5. Fill this doc in

The skeleton below describes what each section should contain so
the analysis is structured + reproducible.

---

## 1. Methodology recap

Per [`docs/improvement-spec.md`](improvement-spec.md) item 12 Phase 1:

- 3 subjects (character / hard-surface / organic), 4 calibrated views
  each at 1024×1024 PNG, plus a ground_truth.glb per subject
- Two input pipelines per logical subject (P3.1a.1):
  - **synthetic** (Option C): rendered from the source GLB
  - **mvgen** (Option B): one rendered concept → Zero123++ → 6 views
- 3 runs per (backend × subject × pipeline) for variance
- Scoring rubric in
  [`tests/multiview-bench/scoring_rubric.json`](../tests/multiview-bench/scoring_rubric.json)
  — six weighted dimensions, pass threshold 6.5 / 10

## 2. Candidate backends

| Backend | License bucket | License score | Pre-research notes |
|---|---|---|---|
| TRELLIS multi-view | `non_commercial` | 4 | Already integrated for single-image; minimum new code |
| InstantMesh | `unclear_risky` | 0 (DQ) | Tencent license; auto-DQ until separate review completes |
| OpenLRM | `commercial_safe` | 10 | Apache 2.0; the only fully commercial-safe path |

## 3. Raw scores per (backend, subject, pipeline)

*To be filled in after the benchmark runs.* See
`tests/multiview-bench/results/benchmark_results.json` — the
`runs[].scores` sub-objects are where the per-dimension 0–10 scores
go (entered by hand after visual review). Re-run
`python3 scripts/multiview_benchmark.py --score-only` to recompute
the rollup once scores are populated.

| Backend | Pipeline | Subject | Run | Geom | Tex | Speed-S | Speed-L | Install | License | Weighted |
|---|---|---|---|---|---|---|---|---|---|---|
| trellis | synthetic | character | 0 | … | … | … | … | … | 4 | … |
| trellis | synthetic | character | 1 | … | … | … | … | … | 4 | … |
| … | … | … | … | … | … | … | … | … | … | … |

## 4. Per-(backend, pipeline) rollup

*To be filled in.* The harness computes mean weighted total per
(backend, pipeline) in `rollup_by_backend_and_pipeline` plus the
`delta_synthetic_minus_mvgen` per backend.

| Backend | Synthetic (Option C) | mvgen-zero123 (Option B) | Δ synth − mvgen |
|---|---|---|---|
| trellis | … | … | … |
| instantmesh | … | … | … |
| openlrm | … | … | … |

Interpretation:

- **High synthetic + high mvgen** → strong backend, good MV-2D pairing
- **High synthetic + low mvgen** → backend is fragile against
  AI-generated views; try a different MV-2D model
- **Low synthetic + low mvgen** → backend just isn't strong for
  this asset class
- **Low synthetic + high mvgen** (rare) → investigate; likely a
  scoring-noise artifact

## 5. Disqualifications

*To be filled in.* Per the rubric:

- License score < 4 → DQ (InstantMesh starts here)
- Any single dimension < 3.0 → DQ regardless of weighted total
- Weighted total < 6.5 → does not qualify

## 6. Recommendation

*To be filled in.* Three possible shapes for the recommendation:

- **Single winner across the board.** "Use X for all multi-view
  work; license bucket Y."
- **Per-asset-class winner.** "Character → A; hard-surface → B;
  organic → C." Add `--backend` flag to `multiview.sh` defaulting
  per intent (mirrors the generator-auto-selection matrix in
  Flow 2).
- **Chain-pair recommendation.** "Use backend X for synthetic
  workflows + chain `MV-2D model Y` → backend Z for the production
  mvgen path." If the synthetic-vs-mvgen deltas vary a lot by
  pairing, this is the honest answer.

The recommendation feeds directly into `scripts/multiview.sh` (P3.1c)
as the default backend, and into `skill/SKILL.md` Flow 9 (P3.1d) as
the routing rule.

## 7. Open follow-ups

*To be filled in.* Common ones to expect:

- If InstantMesh wins or contends: file a license review (mirror
  P2.3's Hunyuan3D-Paint review).
- If no backend clears the 6.5 threshold: revisit the rubric
  weights, or accept that single-image-to-3D remains the better
  default and multi-view is a niche tool for specific asset classes.
- If MV-2D model quality dominates the chain delta: try MVDream /
  Wonder3D / ImageDream adapters (each is a new
  `tools/multiview_2d_adapters/<name>.py` following Zero123++'s
  shape — ~2h each).

---

*Once filled in, this doc closes P3.1b and gates P3.1c (the
`multiview.sh` wrapper) on the chosen backend.*
