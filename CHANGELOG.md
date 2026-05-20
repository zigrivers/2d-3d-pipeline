# Changelog

Dated entries for significant changes to the docs, scripts, or skill.

## 2026-05-20 — P3.2: ComfyUI consistency mode (item 11)

Five sub-deliverables shipped:

P3.2a — ComfyUI install docs
  Third optional step in section 10 of both setup guides: ComfyUI
  repo clone, comfyui-env venv (separate from pipeline-tools-env),
  IPAdapter+ ControlNet custom-node install, model-weight layout,
  pipeline-doctor verification, server start. ~10 GB total install.

P3.2b — Consistency-pack format
  docs/consistency-pack-format.md — pack directory layout, pack.json
  schema, license-bucket resolution rules, distribution shape.
  Defined BEFORE the parser per the v3 MMR finding.
  scripts/consistency_pack_schema.json — JSON Schema (Draft 2020-12)
  for tooling validation.

P3.2c — concept.sh --backend comfyui
  New --backend {mflux, comfyui}, --consistency-pack PATH, --negative
  flags on concept.sh. mflux remains the default; comfyui activates
  only when the pack is supplied. License bucket overridden from the
  dispatcher's pack-aware resolution.

P3.2d — Reference workflow + dispatcher
  scripts/comfyui_dispatch.py — loads the pack, substitutes
  parameters into a workflow JSON, submits to ComfyUI's /prompt
  API, polls /history, downloads the result via /view. Pure stdlib
  + urllib (no diffusers import here; the heavy ML lives in
  ComfyUI itself).
  scripts/comfyui_workflows/consistency_sdxl.json — reference
  SDXL + LoRA (optional) + IP-Adapter FaceID (required) + first-
  controlnet (optional) workflow. String placeholders
  ${pack.identity.reference} etc. are substituted by the dispatcher
  pre-submission.

P3.2e — Skill update
  Flow 1 gets a "Consistency mode (v0.3.2+)" subsection: recognition
  signals, license-bucket guidance, ComfyUI prerequisites, speed
  trade-off, when-NOT-to-suggest.
  Flow 3 forwards the same flags through chained text → 2D → 3D.

** Caveats. ** The dispatcher + reference workflow are best-effort
without an actual ComfyUI install to test against — the workflow
file uses standard SDXL + IPAdapterAdvanced + LoraLoader node
class_types but ComfyUI custom-node naming evolves. If your local
install uses different node names (e.g., older IP-Adapter custom
nodes), edit the class_type strings in the workflow JSON. The
dispatcher's HTTP API calls are standard ComfyUI and should work
across versions.

## 2026-05-20 — P3.1c+d+e: multiview.sh wrapper + Flow 9 skill + embeds

scripts/multiview.sh (v0.3.2, Flow 9):

  Two input modes:
    -i v0.png,v1.png,v2.png[,v3.png]   comma-separated, 3+ required
    -m views.json                       per-view manifest (path + angles)

  Backend choice via --backend trellis|instantmesh|openlrm:
    trellis     default; non_commercial (CC BY-NC)
    openlrm     commercial_safe (Apache 2.0)
    instantmesh unclear_risky (auto-DQ in benchmark until reviewed)

  After backend runs:
    - clean_asset.py cleanup + meta.json cleanup section
    - mesh / texture / game-asset quality checks (same as generate.sh)
    - turntable preview (tier-aware default)
    - engine staging + hero PNG staging
    - --json result with backend, license_bucket, views, paths, duration

  Full --json contract identical in shape to generate.sh's so existing
  chaining patterns work transparently.

skill/SKILL.md:
  - Adds Flow 9 with trigger phrases, both input modes, backend
    recommendation matrix, when-to-suggest / when-NOT-to-suggest
    heuristics, and the future-feature note about a single-image
    chain mode once a backend is picked from P3.1b.
  - Updates the "three halves + five lanes" header.
  - Bumps the "Determine which of the EIGHT flows" section to NINE.

Embeds: multiview.sh added to both setup guides; SKILL.md
regenerated. make verify clean (31 blocks; was 30).

## 2026-05-20 — P3.1b: multi-view backend adapters + recommendation skeleton

Ships the three backend adapters the harness expects + a recommendation
doc template ready to be filled in once the benchmark actually runs:

  tools/multiview_backends/trellis.py      non_commercial (CC BY-NC)
  tools/multiview_backends/instantmesh.py  unclear_risky (auto-DQ until reviewed)
  tools/multiview_backends/openlrm.py      commercial_safe (Apache 2.0)

Each adapter has the same shape (called by multiview_benchmark.py):
  --views v0,v1,v2,v3 --output-glb PATH --json
Each tries to invoke the backend at its expected install location;
emits structured `not_installed` JSON if the backend isn't there.
Each records its license bucket in the result so the harness can
DQ in scoring per the rubric.

Install layouts (override via env vars):
  $TRELLIS_DIR        default ~/3d-pipeline/trellis-mac/
  $INSTANTMESH_DIR    default ~/3d-pipeline/InstantMesh/
  $OPENLRM_DIR        default ~/3d-pipeline/openlrm/

Each adapter is intentionally close to its backend's published
canonical CLI, with notes pointing at where to edit if your local
install differs.

docs/multiview-backend-research.md — skeleton of the recommendation
deliverable. Sections (methodology recap, candidates, raw scores,
per-(backend, pipeline) rollup, DQs, recommendation, follow-ups)
in order; fill in after running the benchmark.

P3.1b is "scaffolding complete" — actual benchmark run still needs
source GLBs (you provide) + backend installs (~hours of model
downloads). Once the recommendation lands, P3.1c (multiview.sh
wrapper) can default to the chosen backend.

## 2026-05-20 — Q5 (open question): pipeline-doctor CI spec for review

`docs/spec-pipeline-doctor-ci.md` — proposal for running
`pipeline_doctor.py` in CI on PRs touching scripts/, skill/, or the
embed map. Covers a new `--check structure` subcheck (validates
the catalog itself, no model installs needed), a new GitHub Actions
workflow, what's caught vs what isn't, trade-offs, and ~2.5h effort
estimate.

Spec only — awaiting user review before implementing.

## 2026-05-20 — Q2 (open question): meta.json schema migration framework

`scripts/meta_helper.py` gains a migration framework so the per-asset
meta.json can evolve safely after v0.3 ships. Today's SCHEMA_VERSION
is 1; no migrations registered (all files are at v1 by construction).

Scaffolding added:

  - `MIGRATIONS: dict[from_version, callable]` registry; each callable
    is data->data and bumps the version.
  - `_ensure_current(data)` runs migrations forward until current.
    Invoked lazily by `merge`/`get` so old files upgrade on access.
  - `meta_helper.py migrate <path>` new subcommand for explicit
    in-place upgrades (idempotent; no-op when already current).
  - Inline documentation of best practices: additive changes don't
    bump version; renamed / restructured sections DO and ship a
    migration; archived schemas live as `meta_schema_vN.json` for
    external validators.

No behaviour change yet — the framework is dormant. When v2 of the
schema ships, it'll add a migration function + a `meta_schema_v1.json`
archived copy and the runtime upgrades happen automatically.

## 2026-05-20 — Q3 (open question): CLIP auto-calibration

`scripts/calibrate_clip.py` — recomputes per-model CLIP percentile
bands (p10 / p25 / p50) in `scripts/clip_calibration.json` from your
own concept generations. Walks the asset manifest for
(generator, concept_path, prompt) triples; calls `clip_score.py` for
each; computes percentiles per model.

  - Models with fewer than --min-samples (default 20) scored samples
    are left untouched, so partial calibration doesn't wipe seed
    defaults.
  - --dry-run reports what would change without writing.
  - Records `_calibrated.at` timestamp + manifest source in the
    output file so you can see when it last ran.
  - Pure stdlib (no numpy / pandas dep); percentiles computed
    directly. Shells out to clip_score.py for the actual scoring.

No manual intervention required — recommended cadence is after ~100
new concept generations or quarterly. Drop it in cron / launchd if
you want continuous calibration.

## 2026-05-20 — Q1 (open question): rigorous wall-thickness algorithm

Replaces the ray-cast wall-thickness heuristic in
`scripts/print_structural_check.py` with a proper signed-distance
approach. For watertight meshes:

  1. Sample N interior points uniformly inside the bounding box.
  2. Keep only points the mesh contains (`mesh.contains`).
  3. For each interior point, compute distance to the nearest surface
     via `trimesh.proximity.ProximityQuery.on_surface`.
  4. The minimum distance × 2 is the thinnest wall any of those
     interior points passes through — the true mesh-wide minimum.

Adaptive sample count from 1k to 8k based on mesh bbox diagonal.
The ray-cast algorithm is kept as a graceful fallback for non-
watertight meshes (where `mesh.contains` is unreliable) and for
environments without `rtree` (where ProximityQuery is slow but
still correct).

`print.structural.wall_thickness_method` recorded in the meta.json
so the skill can tell the user which method was used ("proximity-sdf"
= rigorous; "ray-cast" = legacy fallback).

## 2026-05-20 — Q4 (open question): hero PNG staged into engine folder

When `generate.sh` stages a cleaned GLB into Unity / Unreal's
auto-import folder, the v0.3 turntable hero PNG now follows along
with matching name. Unity / Unreal can pick it up as a thumbnail or
in-editor preview without the user having to open Blender.

Silent no-op when no engine stage happened (e.g. global mode) or
no preview was rendered (`--preview none`).

## 2026-05-20 — P3.1a.2: Document the MV-2D install in section 10

Adds a second optional step to "section 10 / v0.3 prep" in both
setup guides documenting the extra `diffusers`/`transformers`/
`accelerate` install that the multi-view backend benchmark's
Option B path (P3.1a.1) needs. Detailed copy explaining:

  - What multi-view-aware 2D models are (Zero123++ as the reference);
  - Why they matter for the benchmark (full-production-chain test
    vs. backend-in-isolation; diagnostic delta against Option C);
  - Why they matter for a future feature ("auto multi-view from
    single concept" input mode for generate.sh, post-P3.1b);
  - When NOT to install (skip unless benchmarking — v0.3's regular
    generation pipeline doesn't touch these packages);
  - Disk impact (~1.5 GB packages + ~3 GB Zero123++ weights).

Both UPGRADES-{laptop,studio}.md get a parallel short note under
"What's coming next (v0.3 prep)".

Docs only. No script or skill changes. make verify clean.

## 2026-05-20 — P3.1a.1: Option B + Option C dataset tooling

Builds on P3.1a's harness with two complementary input pipelines:

- **synthetic** (Option C): render 4 calibrated views from a source
  GLB via headless Blender. Source-mesh ground truth for free
  (real Hausdorff distance, not visual guesses).
- **mvgen** (Option B): render one concept image from the source,
  dispatch a multi-view-aware 2D model (Zero123++ to start), use its
  outputs as input. Tests the full production chain.

Both pipelines share the same `ground_truth.glb` (the original
source), so synthetic-vs-mvgen scores for the same backend reveal
whether failure mode is "bad at reconstruction" (both fail) or
"bad at AI-generated views" (only mvgen fails).

New tooling (all under /tools, not subject to the embed rule):

- `tools/render_benchmark_views.py` — Blender headless, renders N
  views per a view-config JSON. Reuses the turntable rig from P1.7.
- `tools/build_mvgen_dataset.py` — Option B orchestrator. Renders
  concept → dispatches MV-2D adapter → assembles subject dir.
- `tools/multiview_2d_adapters/zero123_plus_plus.py` — first
  multi-view-2D adapter. Loads `sudo-ai/zero123plus-v1.2` via
  diffusers; splits the 6-tile grid; saves per-view PNGs.
  License bucket assigned conservatively as `commercial_threshold`.

New configs:

- `tests/multiview-bench/view_configs/canonical_4view.json` —
  default Option C spec (front/right/back/left at elev 0).
- `tests/multiview-bench/view_configs/zero123_plus_plus.json` —
  Zero123++'s native 6 angles (azimuth 30/90/150/210/270/330,
  alternating ±30°/-20° elevation). Use with Option C to produce a
  perfectly apples-to-apples comparison against a Zero123++ mvgen run.

Harness updates (`scripts/multiview_benchmark.py`):

- Adapters now live in `tools/multiview_backends/` (off the embed
  path; no subdirectory-in-EMBEDS complication).
- Per-subject `meta.json` is read for `input_pipeline` + `mv_2d_model`,
  carried through into every run record.
- New `rollup_by_backend_and_pipeline` block in `benchmark_results.json`
  summarises mean weighted totals per (backend, pipeline) and
  computes the synth-vs-mvgen delta.
- Subjects now use the per-subject `meta.json` views list instead of
  hard-coding `front/right/back/left.png`, so Zero123++'s 6 native
  views (`v030_30`, `v090_neg20`, …) work without further changes.

Docs:

- `tests/multiview-bench/README.md` rewritten to document both
  pipelines, the new directory layout, and step-by-step dataset-build
  commands.

## 2026-05-20 — P3.1a: multi-view backend benchmark scaffolding

First sub-PR of item 12. Ships the methodology + harness so the
actual benchmark run (P3.1b) has a fixed, reproducible target.

- `scripts/multiview_benchmark.py` — benchmark harness. Discovers
  subjects in `tests/multiview-bench/subjects/`, dispatches each
  candidate backend's adapter, captures runtime + output GLB,
  writes a `benchmark_results.json` ready for visual scoring.
  Supports `--score-only` for rubric-recompute passes after manual
  scoring.
- `tests/multiview-bench/scoring_rubric.json` — six-dimension
  rubric (geometric accuracy 0.35, texture 0.20, speed 0.15+0.10,
  install 0.10, license 0.10) with weighted thresholds (>= 6.5
  total; no dim < 3.0; license >= 4). Auto-DQ for unclear_risky
  licenses without a separate review.
- `tests/multiview-bench/subjects/{1,2,3}-{character,hardsurface,organic}/README.md`
  — per-subject specs (4 calibrated PNG views, optional GT scan
  for Hausdorff scoring).

What this PR does NOT ship:

- The reference images (require physical photo capture or a curated
  dataset, both outside this session's scope)
- Backend adapters (P3.1b — ships alongside the actual installs)
- Populated `benchmark_results.json` (deliverable of P3.1b)

After this PR, the remaining v0.3+ work is decision-gated and
hands-on (P3.1b backend benchmark run + recommendation,
P3.1c-e multi-view wrapper implementation, P3.2 ComfyUI).

## 2026-05-20 — P2.3: Hunyuan3D-Paint un-stub (license approved)

License review completed 2026-05-20
(`docs/license-review-hunyuan3d-paint.md`); ships paint mode for
real.

- `scripts/texture.sh --mode paint -i <glb>` — replaced the
  needs_license_review stub with the real Hunyuan3D-Paint
  invocation. Routes through `$HUNYUAN3D_PAINT_DIR/.venv` (override
  via env). Outputs land in `<assets>/textures/<name>_painted.glb`.
- `scripts/_pipeline_lib.sh::license_bucket_for_model` — bucket for
  `hunyuan3d-paint` changes from `unclear_risky` to
  `commercial_threshold` (same as SF3D / SPAR3D).
- `skill/SKILL.md` Flow 6 — replaces the "do not enable" warning
  with the routing-rules table: when to recommend paint
  (TRELLIS-Mac vertex-only outputs, degenerate textures from earlier
  generators, explicit user ask) vs when to leave the existing PBR
  alone.

Tier 2 of the v0.3 plan now complete (P2.1, P2.2, P2.3 shipped).

## 2026-05-20 — P2.2: CLIP variant ranking + per-model soft signal

- `scripts/clip_score.py` — OpenCLIP ViT-L/14 scoring with two modes:
    single: one image → similarity + per-model band
    rank:   N images → sorted by score; primary written to meta.json
  Per-model bands come from `scripts/clip_calibration.json`. Bands
  are p50 / p25 / p10 / below_p10 — below_p10 is the "consider
  re-generating" threshold (per codex v3 MMR feedback: don't use
  a global absolute threshold).
- `scripts/clip_calibration.json` — initial bands for z-image-turbo,
  flux-schnell, flux-dev, qwen-image. Refresh quarterly.
- `scripts/concept.sh` — when pipeline-tools-env is installed, runs
  the score after generation. With `-n N`, ranks variants and
  reports the order.
- Result writes to a sidecar meta.json next to the PNG
  (`<output>.png.meta.json`).

## 2026-05-20 — P2.1: generator auto-selection (skill text only)

- `skill/SKILL.md` Flow 2 — adds a six-row recommendation matrix
  (character → TRELLIS, mech/weapon → SPAR3D, quick/draft → SPAR3D,
  prop default → SF3D, visible back face → TRELLIS or multi-view,
  commercial release → SF3D/SPAR3D only). Reinforces the
  "state the bucket inline" convention for non-default choices.
- HTML embed regenerated. No code changes.

## 2026-05-20 — P1.9: print structural gates (Tier 1, ends Tier 1)

- `scripts/print_structural_check.py` — heuristic structural checks
  that complement watertightness (per codex P1 in the v3 MMR):
    min_wall_thickness_mm    — via inward ray cast (sample of faces)
    disconnected_islands     — count via `mesh.split`
    self_intersections       — trimesh.repair.broken_faces
    overhang_area_mm2        — faces with steep negative-Z normals
    base_contact_area_mm2    — convex-hull area of bottom 5% in XY
    com_offset_normalized    — COM XY offset / base radius
    stable_on_bed            — COM falls within base footprint
  Frame results as advisory in the skill — the heuristics produce
  false positives (especially wall thickness).
- `scripts/prepare_for_print.py` calls it after STL export (and the
  mesh_quality_check from P1.4), writing `print.structural` to the
  STL-side meta.json.

**Tier 1 of the v0.3 plan now complete.** Foundation (P0.1–P0.3) +
all nine Tier 1 PRs (P1.1–P1.9) shipped.

## 2026-05-20 — P1.8: UV + game-engine validation (Tier 1)

- `scripts/game_asset_check.py` — trimesh-based checks for the
  production-grade issues that AI assets actually trip on in Unity /
  Unreal (per codex's v3 MMR finding):
    - UV island count (warn > 50, error > 500 — "spaghetti UVs")
    - UV occupancy ratio (warn < 0.4)
    - UV in-bounds (all coords in [0,1])
    - Tangents present
    - Normal handedness (y_plus / y_minus); flagged when it doesn't
      match the detected project engine (Unity = -Y, Unreal = +Y)
    - Texture sizes + power-of-two check
    - Embedded image formats + color-space hints
- Writes `quality.uv` + `quality.engine` to per-asset meta.json.
- `scripts/generate.sh` hooks the check via the shared
  run_pipeline_check helper, passing the detected $PROJECT_ENGINE.

## 2026-05-20 — P1.7: turntable preview render (Tier 1)

- `scripts/turntable_render.py` — Blender-headless renderer. One
  hero PNG (1024×1024, Eevee, 32 samples) at 45° angle, OR 12-frame
  turntable at 512×512 (gif mode). Three-point light rig auto-fit to
  the asset's bounding box. Frames + a manifest written to
  `<assets>/preview/`.
- `scripts/generate.sh` — runs the renderer after cleanup. Tier-aware
  default: laptop = png, studio = gif. Override via
  `--preview {none,png,gif}` or `--no-preview`. After Blender exits,
  if mode = gif, an inline pipeline-tools-env Python snippet uses
  Pillow to assemble the 12 frames into a single GIF; the
  manifest's `gif_path` is then merged back into the per-asset
  meta.json `preview` section.
- `_pipeline_lib.sh`: `resolve_project_context` now also creates
  `$ASSETS_ROOT/preview/`.

## 2026-05-20 — P1.6: conditional background removal (Tier 1)

- `scripts/rembg_preprocess.py` (in pipeline-tools-env) — wraps rembg
  (u2net by default; isnet-general-use opt-in). Three modes:
    auto: run only when the input quality check reports a non-uniform
          background AND the input isn't already cropped (RGBA with
          sparse alpha) AND isn't grayscale.
    on:   run unconditionally.
    off:  never run.
  Post-run sanity: if foreground coverage < 5% the result is
  discarded (subject_lost fallback); > 95% means rembg didn't
  actually remove anything (nothing_to_remove). Writes
  `preprocessing.bg_removal` to the per-asset meta.json.
- `scripts/generate.sh` gains `--bg-removal {auto,on,off}` and an
  alias `--no-bg-removal`. Default reads `bg_removal_mode` from
  `~/3d-pipeline/.config` (falls back to "auto"). When applied,
  $INPUT is reassigned to the no-bg PNG so the generator sees it.

## 2026-05-20 — P1.5: texture quality validation (Tier 1)

- `scripts/texture_quality_check.py` (in pipeline-tools-env) —
  trimesh + Pillow + numpy extraction and per-map degeneracy probes.
  Flags: `flat-black-albedo`, `flat-color-albedo`, `uniform-roughness`,
  `uniform-metallic`, `low-detail-normal`, `uninitialised-<map>`,
  `no_textures` (TRELLIS Mac).
- `scripts/generate.sh` — runs both mesh_quality_check and the new
  texture_quality_check through a small shared `run_pipeline_check`
  bash helper. Easier to add new quality scripts going forward.
- Result writes to `quality.textures` in the per-asset meta.json.

## 2026-05-20 — P1.4: mesh watertight + scale sanity check (Tier 1)

- `scripts/mesh_quality_check.py` (in pipeline-tools-env) — trimesh-
  based watertight + boundary-edge + scale-sanity probe. Writes
  `quality.manifold` and `quality.scale` sections to the per-asset
  meta.json via meta_helper.py. Two modes: `normalized` for the
  cleaned GLB (longest dim ≈ 1.0) and `mm` for the printable STL.
- `scripts/generate.sh` runs it on the cleaned GLB after cleanup.
- `scripts/prepare_for_print.py` runs it on the STL after export
  (mm mode). Sidecar STL meta.json next to the file.
- `skill/SKILL.md` gains a "Translation map" section near Flow 2
  (cross-cutting principle 8 — turn "non-manifold edge" into "small
  gap in the surface") plus a "Mesh quality check" subsection.

## 2026-05-20 — P1.3: cleanup report (Tier 1)

- `scripts/clean_asset.py` — instrumented each hygiene pass to count
  what it changed (duplicate verts removed, loose elements deleted,
  holes filled, decimate before/after). Result is written to the
  per-asset meta.json `cleanup` section via meta_helper.py when an
  optional 5th positional arg (META_PATH) is passed. Defaults preserve
  v0.2 behaviour.
- `scripts/generate.sh` passes META_PATH to clean_asset.py and then
  surfaces a user-friendly one-line summary using the meta.json
  contents.
- `skill/SKILL.md` Flow 2 documents the new summary line + heuristics
  for interpreting high cleanup counts.

## 2026-05-20 — P1.2: input quality check + WebP/GIF normalisation (Tier 1)

- `scripts/input_quality_check.py` — Pillow-based check (resolution,
  aspect, file size, format) + crude background-uniformity probe
  (feeds item 1's auto-mode). WebP and animated GIF inputs are
  normalised to a single-frame PNG under `<assets>/concept/`. Result
  merges into the per-asset meta.json `input` section.
- `scripts/_pipeline_lib.sh` gains `check_and_normalize_input` — a
  graceful wrapper around the Python script. No-op when
  pipeline-tools-env or the script itself is missing (v0.2 preserved).
- `scripts/generate.sh` calls it after `OUTPUT_NAME`/`CLEAN_PATH` are
  set, before generator dispatch. `INPUT` may be reassigned to the
  normalised PNG so the generator sees only PNG/JPEG.
- `skill/SKILL.md` Flow 2 documents the new check + the issue tags
  (`low_resolution`, `extreme_aspect_ratio`, `multi_frame_input`, etc.)
  so Claude can speak them in user-friendly terms.

## 2026-05-20 — P1.1: pipeline_doctor.py + model_manifest.json (Tier 1)

First Tier 1 PR. Lands the install-and-cache doctor that every later
v0.3 PR depends on for first-run UX.

- `scripts/pipeline_doctor.py` — single CLI for disk / venv / model /
  wrapper preflight + opt-in `--warm-cache`. Pure stdlib (Python 3.10+);
  `tqdm` / `requests` are used opportunistically when available.
  Dynamic disk threshold: sums uninstalled component sizes in scope +
  5 GB margin. Hard floor 20 GB. Default scope is `tier1`; `--include`
  adds opt-in feature sets (hunyuan3d-paint, comfyui, multiview).
- `scripts/model_manifest.json` — catalog of expected venvs + models
  per feature set, with declared sizes, license buckets, env-var routing
  for caches. Source of truth for the doctor.
- `skill/SKILL.md` — new "Pre-flight check (v0.3+)" section near the
  top. Tells Claude when to recommend `pipeline_doctor.py` (stuck
  generations, "model not found", v0.3 feature installs).

Embeds: pipeline_doctor.py + model_manifest.json added to both setup
guides; SKILL.md embed re-generated. `make verify` clean (20 blocks).

## 2026-05-20 — P0.3: update_manifest.py --meta-json flag

Third foundation PR. Closes the loop from per-asset meta.json (P0.2)
back to the manifest, so future quality passes can forward all of
their data with one flag.

- `skill/scripts/update_manifest.py` gains `--meta-json PATH` plus a
  new `_merge_meta_json` helper that maps meta.json sections into the
  manifest entry per the cross-cutting principle 2 table:
    meta.input + meta.preprocessing  -> entry.generation.input
    meta.generation                  -> entry.generation (field merge)
                                        + entry.model.license_bucket
    meta.cleanup, meta.quality.*,    -> entry.quality.*
    meta.preview, meta.clip
    meta.print                       -> entry.print (field merge)
- Merge is additive: explicit per-arg flags still win when both are
  provided (`setdefault` semantics). Missing sections in the meta.json
  are silently skipped; an absent meta.json file emits a warning but
  does not abort the update.
- `tools/test_update_manifest_meta.sh` — 6-case smoke-test suite
  covering: full merge, arg-vs-meta precedence, missing file,
  idempotent re-run, and backward-compat with pre-existing v3 manifests.

No skill text changes yet — the v0.3 wrappers (Tier 1) will start
passing `--meta-json` in their `update_manifest.py` invocations. The
old per-field flags continue to work for v0.2 callers.

## 2026-05-20 — P0.2: meta_helper.py + meta_schema.json (foundation)

Second foundation PR. Establishes the single-meta.json discipline that
all v0.3+ quality passes will use.

- `scripts/meta_helper.py` — CLI with `merge`, `get`, `validate` subcommands.
  File-locked (fcntl.flock) read-modify-write so concurrent passes can't
  corrupt the meta.json. Eight known top-level sections enforced by default;
  `--allow-unknown-section` is the escape hatch for future-but-not-yet-
  shipped passes.
- `scripts/meta_schema.json` — JSON schema for the per-asset meta.json
  structure. Used by `meta_helper.py validate` when `jsonschema` is
  installed (gracefully skipped otherwise — structural checks still run).
- `tools/add_embed.py` — maintainer helper: inserts a new `<details>`
  heredoc block into both setup guides, anchored before the "What each
  script does" callout, and appends to `tools/_embed_lib.py::EMBEDS`.
  Used by every subsequent v0.3 PR that adds a /scripts file. Lives in
  /tools/ so it isn't itself subject to the canonical-vs-embedded rule.
- `tools/test_meta_helper.sh` — bash-based smoke test suite for
  `meta_helper.py` (9 cases including concurrent-merge lock test).

HTML embeds for `meta_helper.py` and `meta_schema.json` added to both
setup guides. `make verify` clean (18 blocks; was 16). No skill changes
yet — wrappers will start using `meta_helper.py` starting with P0.3 +
the Tier 1 PRs.

## 2026-05-20 — P0.1: pipeline-tools-env install step

First foundation PR for the v0.3 quality-improvement work
(see `docs/improvement-spec.md` + `docs/improvement-plan.md`).
Pure docs — no script or skill changes. The new venv is unused until
the meta_helper / update_manifest / pipeline-doctor PRs land (P0.2,
P0.3, P1.1).

- New section 10 in both setup guides (`docs/asset-pipeline-guide.html`
  and `-studio.html`): install `~/3d-pipeline/pipeline-tools-env/` with
  `trimesh numpy scipy Pillow rembg[cpu] open_clip_torch torch tqdm
  requests`. Model-cache locations under `~/3d-pipeline/models/{rembg,clip}/`
  with `U2NET_HOME` + `OPEN_CLIP_CACHE_DIR` env vars. Marked optional /
  "v0.3 prep" since v0.2 doesn't use any of it.
- Sidebar nav in both guides lists the new section.
- `docs/UPGRADES-{laptop,studio}.md` get a "What's coming next (v0.3
  prep)" section documenting the venv + the troubleshooting hint for
  `torch` wheel failures.

## 2026-05-19 — post-v0.2.0 polish

Small clean-ups landed after the v0.2.0 tag:

- Sidebar nav in the laptop AI-context HTML now lists the v0.2
  hardware-tier notes section that landed in b10bb8d.
- `print.sh --format stl|3mf` removed. STL was always the only path
  the pipeline actually produced; 3MF was scoped out and the
  "not implemented yet" stub read like a promise we'd keep. STL is now
  documented as a design choice ("Why STL, not 3MF or OBJ" already lives
  in the AI context). The JSON `format` field stays at "stl" as a stable
  schema constant.
- `hunyuan3d-paint` recorded in the licence-bucket map as
  `unclear_risky`. `texture.sh --mode paint` accepted as a deliberately
  gated placeholder: stdout emits structured
  `status=error error=needs_license_review tool=hunyuan3d-paint
   license_bucket=unclear_risky` and exits 2; stderr explains the
  Tencent Hunyuan Community License caveats. The wrapper will not run
  Hunyuan3D-Paint until the gate is removed in `scripts/texture.sh`.
- Queue worker gains an optional stuck-job reclaim:
  `queue_worker.py --reclaim-stuck-after MINUTES --max-claims N`.
  When enabled (off by default), each poll cycle scans `running/` for
  stale jobs, bumps their `claim_count`, and moves them back to
  `pending/` — or to `failed/` once they pass `--max-claims`. Cheap
  recovery from worker crashes; intentionally not a full retry policy.
  `queue_submit.py` now seeds `claim_count: 0` on new jobs. Documented
  in `UPGRADES-studio.md` and the studio AI context.

## 2026-05-19 — v0.2.0

Studio-tier upgrade + dual docs set. Defaults preserved on both tiers
(Z-Image Turbo → SF3D → Blender → Snapmaker U1). The pipeline now reads
`~/3d-pipeline/.config` to know which hardware tier it's running on
(`laptop` default, `studio` opt-in).

Wrapper changes (all behaviour-preserving by default):

- `--json` on `concept.sh`, `generate.sh`, `print.sh`, `texture.sh`,
  `benchmark.sh`. Subcommand stdout routes to stderr; final JSON line
  is alone on stdout. Every JSON includes `hardware_tier` + `machine`.
- License-bucket metadata on every wrapper. Non-commercial models
  (`flux-dev`, `trellis`) trigger a `[license] WARNING` to stderr.
- `print.sh` validates dimensions on every axis post-scale; exits 3 on
  oversize unless `--allow-oversize`. Sidecar
  `<output>.print_meta.json` always written.
- `print.sh --format stl|3mf` (3mf fails fast — not implemented yet).
- `generate.sh --overwrite-engine` + collision-aware engine staging
  (auto-suffix `<name>_2.glb` when `auto_increment_collisions=true`).
- `generate.sh -g spar3d` opt-in lane with structured install-missing
  failure message.

New scripts:

- `scripts/json_emit.py` — typed key=value → JSON helper.
- `scripts/texture.sh` + `scripts/texture_inspect.py` —
  `--mode inspect|upscale`; Real-ESRGAN ncnn-vulkan integration when
  installed (clear `status=error error=not_installed` JSON when not).
- `scripts/benchmark.sh` + `scripts/model_bakeoff.py` — model bake-off
  harness with default suite of 14 prompts, quick suite of 3, manual
  scoring scaffold per run.
- `scripts/queue_submit.py` + `scripts/queue_worker.py` — file-based
  two-machine job queue (atomic rename, `--once`/`--max-jobs`/`--dry-run`,
  graceful signal handling). Studio-tier oriented.

Manifest:

- Schema v3 with nested `model{}`, `generation{}`, `print{}`, `eval{}`
  blocks. Flat v1/v2 fields preserved at top level for backward compat.
- Legacy list-of-assets shape auto-migrates with `.bak.<timestamp>`.

Claude Code skill:

- `skill/SKILL.md` rewritten tier-aware. Eight flows (added texture
  inspect/upscale, model bake-off, queue). License-bucket call-out
  rules; doc routing by tier; engine-staging collision guidance;
  Real-ESRGAN no-fallback rule.

Docs:

- New `docs/asset-pipeline-guide-studio.html` (studio setup guide).
- New `docs/UPGRADES-laptop.md` and `docs/UPGRADES-studio.md`.
- New `context/asset-pipeline-ai-context-studio.{md,html}` enforced by
  the parity tool alongside the laptop pair.
- `docs/index.html` lists both tiers.

Tooling:

- `tools/_embed_lib.py` tracks both guides; `verify_embeds.py` and
  `regenerate_embeds.py` iterate over both.
- `tools/check_context_parity.py` checks both md/html pairs.
- Embed map up to 16 entries (was 9).

## 2026-05-19 — v0.1.0

First tagged release. Includes:

- AI context: `context/asset-pipeline-ai-context.md` declared canonical for
  content. `tools/check_context_parity.py` enforces H2-section and callout
  count parity with the HTML mirror, wired into `make verify` and the
  pre-commit hook. Full markdown→HTML auto-generation deferred — the HTML
  has hand-authored polish (tradeoff grids, sec-num labels) that exceeds
  what a stock converter produces.
- CI: `.github/workflows/verify.yml` runs `make verify` on push and PR.
- Release bundle attached as `asset-pipeline-bundle.zip` (scripts + skill
  + setup guide).

## 2026-05-19 — tooling

Maintenance tooling added on top of the initial import:

- `tools/regenerate_embeds.py` + `tools/verify_embeds.py` — programmatic
  regeneration and drift checking of the HTML heredoc embeds, sharing
  `tools/_embed_lib.py`. Round-trip verified bit-identical against the
  initial-import HTML.
- `Makefile` — `verify`, `regenerate`, `bundle`, `install-hooks`, `clean`.
- `.githooks/pre-commit` — refuses commits where `/scripts` or `/skill`
  changed without a matching HTML regeneration. Opt in via
  `make install-hooks`.
- `docs/index.html` — minimal Catppuccin Mocha landing page linking the
  three audiences' canonical docs.
- `.editorconfig` — locks indent/EOL/charset conventions across the repo.

## 2026-05-19 — initial import

Project-aware pipeline complete with three user guides
(setup, workflows, upgrade), AI context doc in HTML+markdown, and canonical
scripts extracted to `/scripts`:

- `_pipeline_lib.sh` — shared functions for wrappers
- `concept.sh`, `generate.sh`, `print.sh` — pipeline stage entry points
- `clean_asset.py`, `prepare_for_print.py` — Blender helpers
- `migrate_assets.sh` — one-shot migration to project-aware layout
- `skill/SKILL.md` + `skill/scripts/update_manifest.py` — Claude Code skill

Repo bootstrapped with README, CONVENTIONS, and this changelog. Only the
setup guide (`docs/asset-pipeline-guide.html`) and AI context doc are
committed in this initial import; `asset-pipeline-workflows.html` and
`asset-pipeline-upgrade-guide.md` exist but were not uploaded to this
working directory yet.
