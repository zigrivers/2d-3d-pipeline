# Multi-view backend benchmark

Scaffolding for item 12 Phase 1 in
[`docs/improvement-spec.md`](../../docs/improvement-spec.md). See also
[`docs/improvement-plan.md`](../../docs/improvement-plan.md) (P3.1a +
P3.1a.1).

The benchmark compares candidate multi-view 3D-reconstruction
backends (TRELLIS multi-view, InstantMesh, OpenLRM) against the same
dataset to produce a recommendation, written up at
`docs/multiview-backend-research.md` (P3.1b).

## Two input pipelines, one ground truth

Each "logical subject" (character / hard-surface / organic) is fed
into every candidate backend via **two** input pipelines:

| Pipeline | What it measures | How |
|---|---|---|
| **synthetic** (Option C) | Backend's intrinsic reconstruction quality | Headless-Blender-render 4 calibrated views from a known source GLB |
| **mvgen** (Option B) | Full production-chain quality (concept → MV-2D → backend) | Render 1 concept view from the source GLB, dispatch a multi-view-aware 2D model (Zero123++, etc.), use its outputs as input |

Both pipelines share the same `ground_truth.glb` — the original source.
That makes the Hausdorff-distance scoring **apples-to-apples** across
pipelines, so the **delta between synthetic and mvgen scores for the
same backend** is the most useful diagnostic in the benchmark.

Interpretation:

| synthetic score | mvgen score | What it tells you |
|---|---|---|
| high | high | backend is strong; MV-2D model integrates cleanly |
| high | low | backend works on clean input but is fragile against AI-generated views |
| low | low | backend itself is weak for this asset class |
| low | high | (rare) MV-2D model is correcting for backend weakness somehow — investigate |

## Directory layout

```
tests/multiview-bench/
├── README.md                                  (this file)
├── scoring_rubric.json                        (rubric + thresholds + candidates)
├── view_configs/
│   ├── canonical_4view.json                   (Option C default: 0/90/180/270 at elev 0)
│   └── zero123_plus_plus.json                 (Option B Zero123++ native: 6 views)
├── sources/                                   (your source GLBs go here)
│   ├── source-1-character.glb                 (e.g. a past SF3D output, or CC0)
│   ├── source-2-hardsurface.glb
│   └── source-3-organic.glb
├── subjects/                                  (built by the dataset tools)
│   ├── subject-1-character-synthetic/         (Option C: rendered from GLB)
│   ├── subject-1-character-mvgen-zero123/     (Option B: Zero123++ output)
│   ├── subject-2-hardsurface-synthetic/
│   ├── subject-2-hardsurface-mvgen-zero123/
│   └── …
└── results/                                   (per-run GLBs + benchmark_results.json)
    └── <backend>/<subject>/runNN.glb …
```

Each subject directory ships:

```
subject-1-character-synthetic/
├── front.png, right.png, back.png, left.png   (4 input views)
├── concept.png                                (Option B input — present in both)
├── ground_truth.glb                           (copy of source for self-containment)
└── meta.json                                  (records input_pipeline + view angles)
```

## How to build the dataset

### 0. Source the GLBs

Drop three source GLBs into `tests/multiview-bench/sources/`:

- **subject-1-character**: humanoid figure (asymmetric)
- **subject-2-hardsurface**: small mechanical prop, sharp edges
- **subject-3-organic**: irregular natural object (rock / plant / bark)

These can be: prior SF3D / SPAR3D / TRELLIS outputs you've kept, CC0
scans from Sketchfab / Google Scanned Objects, or anything else with
a clear license.

### 1. Build the Option C synthetic subjects

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
$BLENDER --background --python tools/render_benchmark_views.py -- \
    --source tests/multiview-bench/sources/source-1-character.glb \
    --output-dir tests/multiview-bench/subjects/subject-1-character-synthetic/ \
    --view-config tests/multiview-bench/view_configs/canonical_4view.json
```

Repeat per subject. ~10 seconds per subject on studio tier.

### 2. Build the Option B mvgen subjects

```bash
python3 tools/build_mvgen_dataset.py \
    --source tests/multiview-bench/sources/source-1-character.glb \
    --output-dir tests/multiview-bench/subjects/subject-1-character-mvgen-zero123/ \
    --mv-2d-model zero123_plus_plus
```

The tool will render a concept image from the source, then dispatch
the Zero123++ adapter. First run downloads ~3 GB of Zero123++
weights to your `pipeline-tools-env` cache.

### 3. (Optional) For Zero123++ comparisons, also render an Option C variant at Zero123++'s native angles

Useful when you want a perfectly apples-to-apples comparison between
synthetic and Zero123++ outputs:

```bash
$BLENDER --background --python tools/render_benchmark_views.py -- \
    --source tests/multiview-bench/sources/source-1-character.glb \
    --output-dir tests/multiview-bench/subjects/subject-1-character-synthetic-z123angles/ \
    --view-config tests/multiview-bench/view_configs/zero123_plus_plus.json
```

### 4. Run the benchmark

```bash
python3 scripts/multiview_benchmark.py \
    --backends trellis,instantmesh,openlrm \
    --runs-per-subject 3
```

Writes per-run GLBs to `tests/multiview-bench/results/<backend>/<subject>/`
and a `benchmark_results.json` summary.

### 5. Score + recompute

Open the result GLBs visually (Blender / glTF viewer). Fill in the
per-dimension `scores` block for each run inside
`benchmark_results.json`. Then:

```bash
python3 scripts/multiview_benchmark.py --score-only
```

…to recompute the weighted totals + per-(backend, input_pipeline)
rollup.

## What this PR (P3.1a.1) ships

- `tools/render_benchmark_views.py` — Option C builder
- `tools/build_mvgen_dataset.py` — Option B orchestrator
- `tools/multiview_2d_adapters/zero123_plus_plus.py` — Zero123++ adapter
- `view_configs/canonical_4view.json` + `zero123_plus_plus.json`
- Harness updates: per-subject `input_pipeline` metadata is read +
  surfaced in `benchmark_results.json`; `--score-only` rolls up
  scores per (backend, input_pipeline) with synth-vs-mvgen delta

## What this PR does NOT ship

- The source GLBs — you provide them (see step 0).
- 3D backend adapters at `tools/multiview_backends/*.py` — those
  ship in P3.1b alongside the real backend installs.
- A populated `benchmark_results.json` with per-run scores — that's
  the deliverable of P3.1b before the recommendation lands.

## Future MV-2D adapters

Adding more multi-view-aware 2D generators is straightforward — drop
a new file at `tools/multiview_2d_adapters/<name>.py` matching the
Zero123++ adapter's interface (`--concept PATH --output-dir DIR
--json`) and pass `--mv-2d-model <name>` to `build_mvgen_dataset.py`.
Candidates worth wiring up: **MVDream**, **Wonder3D**, **ImageDream**,
**SyncDreamer**.
