# Generation-quality refresh spec (2026-08) — v1

**Status:** shipped in v0.6.0 (2026-08-12) · **Author:** asset-pipeline
maintainers · **Shipped release:** v0.6.0 (all items 15–25, one
continuous round — see `CHANGELOG.md`) ·
**Companion plan:** [`plan-generation-refresh-2026.md`](plan-generation-refresh-2026.md)

This spec captures eleven improvements (items 15–25, continuing the
numbering of [`improvement-spec.md`](improvement-spec.md)) discovered by
an August 2026 survey of the open-source model landscape. The previous
spec round (items 1–14) built quality *measurement* and plumbing; this
round upgrades what the pipeline *generates* — and fixes the measurement
signal it ranks by.

Research provenance: every model claim below carries a citation
gathered 2026-08-11. Items whose Apple Silicon support is **unverified**
say so explicitly and carry a spike task in the plan; nothing below
assumes untested Mac support silently.

## Why this round exists

1. **The 3D generator tier is two generations old.** SF3D (2024) remains
   the default while MIT-licensed, PBR-capable models with working Apple
   Silicon ports now exist (TRELLIS.2-4B via `trellis-mac`).
2. **The licensing map moved under us.** The repo currently documents
   TRELLIS as `non_commercial` with vertex-colors-only on Mac. TRELLIS.2-4B
   weights are **MIT** ([repo](https://github.com/microsoft/TRELLIS.2),
   [HF card](https://huggingface.co/microsoft/TRELLIS.2-4B)) and the
   [`trellis-mac`](https://github.com/shivampkumar/trellis-mac) port bakes
   PBR textures on Metal. Both axes of the old decision are obsolete.
3. **Our quality signal is measurably weak.** A June 2026 study
   ([arXiv:2606.18451](https://arxiv.org/abs/2606.18451)) found
   render-space CLIP similarity performs **at chance level** for 3D mesh
   quality and geometry-validity heuristics are bimodal. The pipeline's
   CLIP score (item 8) ranks 2D variants adequately but must not be
   trusted for 3D; VLM-as-judge protocols now have published evidence.
4. **The multi-view lane (item 12 / P3.1) is stalled on a dead backend
   list.** InstantMesh hard-requires CUDA≥12.1 + nvdiffrast (no Mac
   fork); OpenLRM weights are CC-BY-NC research-only. The benchmark
   harness is fine; the candidates must change.
5. **512 GB studios are under-used.** The M3 Ultra tier can hold
   20B-class editing models and 235B-A22B MoE judges that were
   unthinkable at laptop scale.

## Hardware ceiling (hard constraint)

Everything below fits an Apple M3 Ultra with 512 GB unified memory and
well under 7 TB of disk. Worst single-model peaks cited per item; the
largest (Qwen-Image-Edit-2511 20B, ~40–60 GB quantized; Qwen3-VL judge
tiers up to ~124 GB at MLX 4-bit for the 235B MoE) leave >350 GB
headroom. Laptop-tier (128 GB) feasibility is stated per item.

## Inherited cross-cutting principles

All ten principles of [`improvement-spec.md`](improvement-spec.md)
§"Cross-cutting design principles" apply unchanged: additive-never-
breaking, one `meta.json` per asset via `meta_helper.py`, license-bucket
every model in `_pipeline_lib.sh::license_bucket_for_model`, stderr under
`--json`, skill changes are first-class, `make regenerate && make verify`
after any script change, warn-don't-block gates, jargon translation table.

Additional principles for this round:

- **P-A. Default changes require bake-off evidence + explicit user
  sign-off.** No item below silently changes a default model. Promotion
  paths run through `scripts/model_bakeoff.py` + a decision record doc,
  mirroring the item 7 license-review pattern.
- **P-B. Community-fork risk is named.** Several Mac ports are small
  community forks (single-digit stars). Each such dependency gets: a
  pinned commit hash, a smoke test in `pipeline_doctor.py`, and a
  documented fallback. A fork vanishing must degrade, not break.
- **P-C. License verification is an install-time act, not a doc claim.**
  Every new model install step includes reading the LICENSE file in the
  cloned repo / HF card and confirming the bucket recorded here. Where
  this spec's research conflicts with existing repo docs (TRELLIS), the
  installer verifies and the docs are corrected in the same PR.

---

# Tier 1 — flagship (highest quality-per-effort)

## 15. TRELLIS.2 Mac port as a first-class 3D backend (and license correction)

**Problem.** The pipeline's quality ceiling for geometry+texture is
SF3D. TRELLIS (v1) is documented as CC BY-NC, vertex-colors-only on Mac,
opt-in — all true when written, all now obsolete for TRELLIS.2.

**Approach.**
1. New venv `~/3d-pipeline/trellis2-mac/.venv` cloning
   [`shivampkumar/trellis-mac`](https://github.com/shivampkumar/trellis-mac)
   at a pinned commit. (Alternative MLX backend
   [`pedronaugusto/trellis2-apple`](https://github.com/pedronaugusto/trellis2-apple)
   is younger/smaller — note as fallback, don't install by default.)
2. `generate.sh -g trellis2` dispatch case producing PBR-textured GLB
   (baseColor/metallic/roughness) into the standard `raw/` → `clean/`
   flow. Existing `clean_asset.py` runs unchanged (GLB in, GLB out).
3. Replace the port's RMBG-2.0 preprocessing (CC BY-NC 4.0) with the
   pipeline's existing `rembg_preprocess.py` path so the chain stays
   commercial-clean.
4. License bucket: `trellis2` → `commercial_safe` (MIT weights,
   verified per P-C at install). The legacy `trellis` (v1) entry keeps
   its `non_commercial` bucket — do not touch it.
5. Bake-off vs SF3D and SPAR3D (`model_bakeoff.py`, studio `default`
   suite) → decision record `docs/model-review-trellis2.md`. Default
   promotion is a **separate, user-approved** follow-up per P-A.

**Evidence.** MIT weights: [GitHub](https://github.com/microsoft/TRELLIS.2),
[HF](https://huggingface.co/microsoft/TRELLIS.2-4B). Mac port: ~460 stars,
M4 Pro 24 GB runs 400K-vertex PBR GLB in ~3m20s generation / ~5 min cold,
~18 GB peak ([port README](https://github.com/shivampkumar/trellis-mac),
[independent hands-on](https://lilting.ch/en/articles/trellis2-apple-silicon-mps-cuda-free)).
Known port limits: hole-filling disabled, meshes pre-simplified to
~200K faces before baking, sparse attention unfused. Weights ~15 GB disk.

**Dependencies + license bucket.** trellis-mac port (MIT code),
TRELLIS.2-4B weights (MIT) → `commercial_safe`. DINOv3 encoder is a
gated Meta license — installer must surface the gate; if unacceptable,
this item blocks and says so. RMBG-2.0 explicitly NOT installed.

**Hardware tier.** Studio: comfortable. Laptop (128 GB): fits (port
floor ~24 GB); slower — document expected minutes, keep opt-in.

**Manifest / meta.json.** `generation.backend: "trellis2"`,
`generation.license_bucket: "commercial_safe"`. No schema change —
existing fields cover it.

**User-facing output.** New generator matrix row in SKILL.md; wrapper
context line names the backend + bucket. Doctor reports the ~15 GB cache.

**Failure modes.** Fork abandonment (P-B: pinned commit + doctor smoke
test + SF3D fallback); large-mesh instability (port pre-simplifies —
if bake fails, retry at lower resolution and warn); hole-filling gap
(cleanup's Blender pass partially compensates; note in cleanup report).

**Test strategy.** Golden-image smoke: one canned concept PNG → GLB;
assert PBR maps present in GLB (baseColor+metallic/roughness textures),
watertight-check runs, meta.json sections written. Doctor `--check
trellis2` verifies venv + weights + pinned commit.

**Effort.** L.

## 16. Scorer stack refresh — SigLIP 2 + ImageReward + DreamSim (CLIP demoted)

**Problem.** Variant ranking (item 8) uses OpenCLIP ViT-L/14.
[arXiv:2606.18451](https://arxiv.org/abs/2606.18451) shows render-space
CLIP at chance for 3D quality; for 2D, better commercially-safe scorers
now exist. HPSv3 (best-known preference scorer) is CC BY-NC-SA —
disqualified.

**Approach.** In `pipeline-tools-env`: add SigLIP 2 (Apache 2.0,
[README](https://github.com/google-research/big_vision/blob/main/big_vision/configs/proj/image_text/README_siglip2.md))
as the prompt-adherence scorer replacing CLIP in `clip_score.py`
(rename stays; add `--scorer {clip,siglip2}` with siglip2 default);
ImageReward (Apache 2.0, [repo](https://github.com/zai-org/ImageReward))
as human-preference score; DreamSim (MIT,
[repo](https://github.com/ssundaram21/dreamsim)) for perceptual
variant-dedup (near-duplicate detection among `-n N` variants).
Recalibrate per-model bands via existing `calibrate_clip.py` machinery.
Geometry heuristics (items 2, 13, 14) stay as **hard-fail gates only**,
never quality scores — codify in SKILL.md wording.

**Dependencies + bucket.** All three: small CLIP-scale PyTorch models,
MPS-trivial (standard transformers/diffusers stacks; low-risk,
per-model Mac benchmark not published). Buckets: `commercial_safe`.
PickScore / Aesthetic Predictor V2.5 excluded (licenses unverified);
HPSv3 excluded (CC BY-NC-SA).

**Hardware tier.** Both tiers; models are ~1–2 GB each.

**Manifest / meta.json.** `clip` section gains sibling fields:
`{"scorer": "siglip2", "similarity": …, "image_reward": …,
"dreamsim_dupes": […]}` — additive to the existing `clip` section
(CHANGELOG entry per merge contract).

**User-facing output.** Translation-table rows: "image matches your
prompt (SigLIP 0.xx)"; "people-preference score"; "variants 2 and 4 are
near-duplicates".

**Failure modes.** Scorer download failure → skip scoring, warn (never
block generation). Band drift after scorer swap → recalibration is a
required plan step, not optional.

**Test strategy.** Unit test: known-good/known-bad image pair ordering
is stable per scorer. Calibration run recorded in decision doc.

**Effort.** M.

## 17. Local VLM judge for 2D concepts + best-of-N auto-select

**Problem.** `concept.sh -n N` generates variants but selection is
manual or CLIP-ranked. No signal catches "technically on-prompt but bad
game asset" (wrong view angle, baked shadows, background clutter — the
exact failures that later ruin image-to-3D).

**Approach.**
1. New `scripts/vlm_judge.py` in a new `~/3d-pipeline/vlm-env/` venv
   running [mlx-vlm](https://github.com/Blaizzy/mlx-vlm) (MIT) with
   **Qwen3-VL-8B-Instruct** (Apache 2.0) as the default judge; config
   key `judge_model` allows larger tiers (Qwen3.5-35B-A3B MoE for
   speed/quality balance; 235B-A22B for nightly batch — measured
   ~24 tok/s MLX 4-bit @ ~124 GB on M3 Ultra 512 GB,
   [MacStories benchmark](https://www.macstories.net/notes/notes-on-early-mac-studio-ai-benchmarks-with-qwen3-235b-a22b-and-qwen2-5-vl-72b/)).
2. Rubric prompt scores each concept 0–10 on: subject match, 3/4-view
   compliance, background cleanliness, lighting flatness, single-subject,
   silhouette readability — returns JSON per image.
3. `concept.sh --judge` (opt-in; studio default-on candidate later per
   P-A): after generation, judge all variants, emit ranking to meta.json
   + stdout; `--best-of N` generates N, keeps the winner, moves losers
   to `concept/rejected/`. (Auto-retry-below-threshold deliberately
   omitted — add only if best-of-N proves insufficient in practice.)

**Dependencies + bucket.** mlx-vlm (MIT), Qwen3-VL weights (Apache 2.0)
→ `commercial_safe`. Judge output is metadata, not shipped asset —
bucket matters only for consistency.

**Hardware tier.** Studio: 8B trivial, MoE tiers available. Laptop:
8B 4-bit fine (~6 GB); larger tiers gated by config.

**Manifest / meta.json.** New top-level section `judge` (CHANGELOG +
schema addition per merge contract): `{"model": "...", "scores":
{...per-dimension...}, "verdict": float, "picked": "name_3.png"}`.

**User-facing output.** Skill translates: "Judge picked variant 3 of 4:
best silhouette, cleanest background (8.4/10)."

**Failure modes.** Judge hallucination/position bias → fixed image
order, one image per call, rubric anchored per
[arXiv:2606.20364](https://arxiv.org/abs/2606.20364) de-biasing
protocol. Slow judge → per-image latency logged; `--judge` off by
default on laptop. mlx-vlm API drift → pinned version.

**Test strategy.** Fixture pair (good 3/4-view chest vs cluttered
front-view chest) — judge must rank good > bad across 3 runs. Latency
budget assert: <30 s/image with 8B on studio.

**Effort.** M.

## 18. VLM 3D judge on turntable renders (degenerate-mesh gate that works)

**Problem.** Flat/sliver/degenerate meshes (context doc §21) are caught
today only by heuristics that arXiv:2606.18451 shows are bimodal —
they catch catastrophic failure, miss "bad but valid" meshes.

**Approach.** Extend item 17's `vlm_judge.py` with `--mode mesh`:
render the cleaned GLB via existing `turntable_render.py` at fixed
canonical views (default 8, config up to 24 per the paper's rig),
judge the view grid on: recognizable-as-prompt, back-face plausibility,
geometry artifacts (slivers, holes, floaters), texture coherence.
Wire as opt-in `generate.sh --judge-mesh` gate: warn-don't-block
(principle 10), except verdict < hard floor (config, default 2/10)
which flags the asset "likely degenerate — regenerate recommended"
in meta.json + skill output.

**Dependencies.** Item 17 infra; no new models.

**Hardware tier.** Both; render cost ~seconds, judge cost as item 17.

**Manifest / meta.json.** `judge.mesh` subsection: per-dimension scores
+ `views_rendered`.

**User-facing output.** "3D check: recognizable ✓, back side plausible ✓,
2 floating fragments detected — cleanup may fix, or regenerate."

**Failure modes.** Vertex-color-only or untextured meshes bias the
judge → rubric instructs geometry-first scoring; render with neutral
matcap fallback when no texture. False floater reports → cross-check
against cleanup report's loose-elements count before asserting.

**Test strategy.** Fixtures: one known-good GLB, one deliberately
flattened GLB (scale Z×0.02) — judge must separate them 3/3 runs.

**Effort.** M (after 17).

---

# Tier 2 — model refresh lanes

## 19. Retarget item 7: Hunyuan3D-Paint 2.1 via MLX port

**Problem.** Item 7 (approved 2026-05-20) planned Hunyuan3D-Paint
against the upstream repo, whose paint stage needs CUDA
custom_rasterizer/differentiable_renderer — unavailable on Mac. The
approved plan is unimplementable as written.

**Approach.** Retarget to
[`dgrauet/Hunyuan3D-2.1-mlx`](https://github.com/dgrauet/Hunyuan3D-2.1-mlx)
(full MLX port incl. paint: Metal rasterizer, FP16 5.7 GB weights /
~10 GB peak, INT8/INT4 options, numerically validated vs PyTorch at
1e-5; pre-converted weights at
[AgenticVibes/hunyuan3d-2.1-mlx](https://huggingface.co/AgenticVibes/hunyuan3d-2.1-mlx)).
Everything else in item 7's approved design (routing rules vs
inspect/upscale, `texture.sh --mode paint`, doctor cache management,
license bucket `commercial_threshold`) stands. Add to the license
review one fact the original missed: the Tencent license **does not
apply in the EU, UK, or South Korea** — fine for Ken (US), must be
documented in the license-review doc and SKILL.md warning text.
Fork risk is high (single-digit stars) → P-B applies in full:
pinned commit, doctor smoke test, fallback = "paint unavailable,
use texture.sh upscale path" (the MPS fork
[Brainkeys/Hunyuan3D-2.1-mac](https://github.com/Brainkeys/Hunyuan3D-2.1-mac)
has paint limited/disabled — it is NOT a viable paint fallback, only a
shape one; say so in docs).

**Dependencies + bucket.** MLX port (check repo license at install),
Hunyuan3D-2.1 weights → `commercial_threshold` (1M MAU + territory
exclusion). Existing approved decision record gets an addendum, not a
rewrite.

**Hardware tier.** Both (10 GB peak FP16); laptop uses INT8.

**Manifest / meta.json.** As item 7 spec'd (`generation.model_role:
"paint"` on the texture pass).

**Failure modes.** Fork bit-rot (P-B); xatlas issues on odd meshes →
pre-simplify before paint, warn; paint quality below upscale path →
bake-off gate before recommending in skill matrix.

**Test strategy.** Item 7's original tests + one MLX-specific: paint a
canned SF3D GLB, assert albedo+MR maps exist and differ from input.

**Effort.** M (was L against CUDA upstream).

## 20. 2D model refresh — FLUX.2 klein 4B + ERNIE-Image; Z-Image LoRA lane

**Problem.** FLUX.1 schnell's role is "the LoRA model"; FLUX.2 klein 4B
(Jan 2026, **Apache 2.0** — the family's permissive exception) beats it
generationally and adds instruction editing + multi-reference in the
same checkpoint ([BFL announcement](https://bfl.ai/blog/flux2-klein-towards-interactive-visual-intelligence),
[HF](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)).
ERNIE-Image 8B (Apr 2026, Apache 2.0) is the strongest-at-release open
t2i with mflux-native support incl. LoRA training
([repo](https://github.com/baidu/ernie-image)). Z-Image **Base**
(Jan 2026, Apache 2.0) makes LoRA training possible for the default
model family ([repo](https://github.com/Tongyi-MAI/Z-Image)).

**Approach.** mflux ≥0.18.1 already supports all three
([mflux](https://github.com/filipstrand/mflux)) — this is wiring, not
porting:
1. `concept.sh -m flux2-klein` and `-m ernie-image` model cases +
   validation + license map entries (`commercial_safe` both).
2. SKILL.md model-selection guidance: Z-Image Turbo stays default
   (per P-A, no silent change); klein 4B recommended when a
   FLUX-ecosystem LoRA or built-in edit is wanted; ERNIE as
   prompt-adherence alternate; FLUX.1 schnell demoted to legacy row
   (kept working).
3. Known Z-Image weakness recorded in prompt-tips: subjects tend to
   face camera ([benchmark note](https://miroleon.github.io/z-image-turbo-benchmark/))
   — the game-asset 3/4-view suffix + judge (item 17) compensate;
   klein/ERNIE are the retry models when 3/4 compliance fails.
4. Optional doc-only lane: training custom style LoRAs on Z-Image Base
   / klein 4B via Draw Things or mflux train — document, don't build.

**Dependencies + bucket.** Weights via mflux caches: klein 4B (Apache),
ERNIE-Image 8B (Apache) → `commercial_safe`. FLUX.2 klein 9B / dev
explicitly NOT added (BFL non-commercial).

**Hardware tier.** Both (4B/8B class; klein 4B ~30–40 s per 1024px
image on M1 Max via mflux,
[community report](https://lilting.ch/en/articles/flux2-klein-4b-mflux-iris-m1-max)
— studio much faster).

**Manifest.** Existing fields cover (`generation.backend: mflux`,
model name recorded).

**Failure modes.** mflux version below 0.18 → doctor preflight check
with upgrade hint; LoRA cross-compat confusion (FLUX.1 LoRAs ≠ FLUX.2
LoRAs) → validation error naming the mismatch.

**Test strategy.** Smoke per model: 1 image, license line correct in
`--json`; matrix rows render in SKILL.md.

**Effort.** S–M.

## 21. Editing lane — Qwen-Image-Edit-2511 + Multiple-Angles LoRA

**Problem.** Two standing gaps: no "small change to an approved
concept" tool (today: regenerate and hope), and no commercial-safe way
to produce extra views of a chosen concept for 3D (Zero123++ weights
are CC-BY-NC). Qwen-Image-Edit-2511 (**Apache 2.0**, 20B) does
instruction edits with strong identity preservation, and its official
[Multiple-Angles LoRA](https://huggingface.co/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA)
provides parametric camera rotation (−90°…90° horizontal, −30°…60°
elevation) with documented 90°/180° same-object rotation
([HF 2511](https://huggingface.co/Qwen/Qwen-Image-Edit-2511)).

**Approach.**
1. New wrapper `scripts/edit.sh` (follows wrapper pattern; sources
   `_pipeline_lib.sh`): `edit.sh -i concept/chest.png "make the wood
   darker"` → `concept/chest_edit1.png`. Backend: mflux Qwen-Image-Edit
   path; fallback backend flag for
   [qwen-image-mps](https://github.com/ivanfioravanti/qwen-image-mps)
   if mflux's edit path underperforms (both cited running 2511-class
   editing on Apple Silicon).
2. `edit.sh --angle <h,v>` applies the Multiple-Angles LoRA to produce
   rotated views: `chest_090deg.png` etc., named to match the item 12
   multi-view input convention (`_000deg/_090deg/…`) so outputs feed
   `multiview.sh` directly.
3. SKILL.md Flow 10: "Edit a concept" + "Views from one concept";
   judge (item 17) optionally scores edit fidelity.
4. **Gate:** the Multiple-Angles LoRA's license must be read at
   install (fal upload; LoRA licenses vary). Until verified:
   `unclear_risky` and the flag warns. Base 2511 model is Apache 2.0
   regardless.

**Dependencies + bucket.** Qwen-Image-Edit-2511 (Apache 2.0 →
`commercial_safe`); Multiple-Angles LoRA (verify → until then
`unclear_risky`, warn-on-use). ~40 GB-class weights disk at q8; studio
trivial, laptop tight-but-fits at q4 (documented).

**Hardware tier.** Studio primary; laptop opt-in with quantization.

**Manifest / meta.json.** `generation` on edited outputs records
`{"backend": "qwen-image-edit", "model_role": "edit", "inputs":
[source image], "edit_instruction": "...", "angle": "090"}` — uses the
existing `generation.inputs` shape.

**Failure modes.** Identity drift on edit → judge cross-check vs source
(DreamSim distance from item 16, warn if excessive); angle views
geometrically implausible → they are *plausible renders, not calibrated
geometry* — SKILL.md must say multiview reconstruction from them is
experimental (item 22 benchmarks it before recommending).

**Test strategy.** Edit smoke (color-change instruction; DreamSim says
similar-but-not-identical); angle smoke (090° output differs, subject
persists — judge check); filename convention matches multiview.sh
required-view validation.

**Effort.** M.

## 22. Multi-view lane rescue — new backend slate for the P3.1 benchmark

**Problem.** P3.1's candidate list is dead on this hardware: InstantMesh
(CUDA≥12.1 + nvdiffrast hard requirement,
[README](https://github.com/TencentARC/InstantMesh)), OpenLRM (weights
CC-BY-NC research-only,
[model card](https://github.com/3DTopia/OpenLRM/blob/main/model_card.md)),
Zero123++ view-gen (weights CC-BY-NC). The harness
(`multiview_benchmark.py`, adapters, scoring rubric) is sound.

**Approach.** Replace the backend slate; keep the harness + methodology:
- **View generation:** [MV-Adapter](https://github.com/huanngzh/MV-Adapter)
  (Apache 2.0, SDXL-based, no CUDA kernels in the i2mv path — Mac
  **unverified**, structurally MPS-compatible; 1-day spike in plan) and
  item 21's `edit.sh --angle` views (commercial-safe wildcard).
  Zero123++ may be benchmarked for research comparison only, never
  wired as a lane (NC weights).
- **Multi-view consumer:**
  [Hunyuan3D-2mv](https://huggingface.co/spaces/tencent/Hunyuan3D-2mv)
  (1.1B, 1–4 views→shape, `commercial_threshold` Tencent license; Mac
  **unverified** but same DiT family as the MPS-verified 2.1 shape
  model; spike required) and **TRELLIS.2 single-image** (item 15) as
  the "is multi-view even worth it vs a better single-image model"
  baseline — the benchmark's most important comparison.
- **SPAR3D** stays in the slate (already wired; official experimental
  MPS support, [repo](https://github.com/Stability-AI/stable-point-aware-3d)).
- Update `docs/multiview-backend-research.md` skeleton's candidate
  table + adapter list; delete InstantMesh/OpenLRM adapters from
  `tools/multiview_backends/` (or mark disqualified with reason —
  prefer marking, cheaper than deleting history).

**Dependencies + buckets.** MV-Adapter Apache 2.0 → `commercial_safe`
(SDXL base weights OpenRAIL++ — same basis as the shipped ComfyUI
consistency lane; record in doc). Hunyuan3D-2mv →
`commercial_threshold` (+ territory note as item 19).

**Hardware tier.** Studio for the benchmark suite; lane itself both
tiers once a backend wins.

**Manifest.** Already spec'd by item 12 (`generation.inputs` multi).

**Failure modes.** Both spikes fail on Mac → fall back to shipping the
lane exclusively via `edit.sh --angle` + TRELLIS.2 single-image, and
the research doc records that multi-view reconstruction is deferred —
an acceptable, evidence-backed outcome per the original P3.1 design.

**Test strategy.** The existing scoring rubric
(`tests/multiview-bench/scoring_rubric.json`, 6.5/10 pass) + the P3.1a
dataset tooling, unchanged.

**Effort.** M (harness exists; slate swap + 2 spikes + run).

---

# Tier 3 — output polish + fabric

## 23. Engine-ready mesh post: gltfpack LOD chain + xatlas UV

**Problem.** `clean_asset.py` decimates to one polycount. Engines want
LOD chains; UV quality from generators is uneven (item 13 measures it,
nothing fixes it).

**Approach.** Both tools are MIT, native macOS, no ML:
1. [meshoptimizer](https://github.com/zeux/meshoptimizer) v1.0 /
   `gltfpack` (Homebrew) — new `generate.sh --lods "3000,1000,300"`
   emits `clean/<name>_lod{0,1,2}.glb` post-cleanup; engine staging
   copies the set. Also run gltfpack's optimize pass on the default
   clean GLB (quantization off by default — engine compat first).
2. [xatlas](https://github.com/jpcy/xatlas) via
   [xatlas-python](https://github.com/mworchel/xatlas-python) in
   `pipeline-tools-env` — `--reuv` flag re-unwraps when item 13's UV
   check reports overlap/low occupancy (warn-suggested, never auto).

**Bucket.** `commercial_safe` (MIT tools, no weights).

**Hardware tier.** Both; milliseconds-to-seconds cost.

**Manifest / meta.json.** `cleanup.lods: [{path, polycount}]`,
`cleanup.reuv: {applied, occupancy_before, occupancy_after}`.

**Failure modes.** gltfpack quantization surprising Unity importers →
off by default; xatlas re-unwrap invalidates baked textures → **hard
rule: `--reuv` only before paint (item 19) or on untextured meshes;
wrapper enforces ordering and refuses otherwise.**

**Test strategy.** LOD smoke: 3 files, descending polycount, all load
in trimesh watertight-check; reuv smoke on a low-occupancy fixture
raises occupancy.

**Effort.** S.

## 24. Texture post refresh — SeedVR2 upscale engine + Marigold-IID PBR pass

**Problem.** `texture.sh --mode upscale` rides Real-ESRGAN
ncnn-vulkan — upstream unmaintained (last portable release 2022,
[SourceForge mirror](https://sourceforge.net/projects/real-esrgan.mirror/files/v0.2.5.0/)),
MoltenVK config fragile. And SF3D albedo-ish textures lack tuned
roughness/metallic.

**Approach.**
1. `texture.sh --engine {realesrgan,seedvr2}`: SeedVR2 3B/7B runs
   natively in mflux ([mflux](https://github.com/filipstrand/mflux)) —
   modern, maintained, MLX-native upscale. Real-ESRGAN stays default
   until a side-by-side on game textures (bake-off, P-A) — then flip
   default in a follow-up. **Gate: verify SeedVR2 weight license at
   install (ByteDance Seed family; unverified in research) — bucket
   recorded then; until verified treat `unclear_risky`.**
2. `texture.sh --mode pbr`: render/albedo → 
   [StableDelight](https://github.com/sakalond/StableGen) delight →
   [Marigold-IID Appearance](https://huggingface.co/prs-eth/marigold-iid-appearance-v1-1)
   roughness+metallic decomposition; write maps back into the GLB
   (vanilla diffusers UNets, MPS-supported stack
   [diffusers MPS](https://huggingface.co/docs/diffusers/en/optimization/mps);
   direct Marigold-on-MPS **unverified** — spike in plan).
   Marigold license is CreativeML OpenRAIL++-M (commercial use allowed,
   behavioral use restrictions) — **bucket decision gate**: recommend
   `commercial_safe` with a use-restriction note in the license map;
   record the call in a short decision doc.

**Hardware tier.** Both (SeedVR2 3B laptop, 7B studio; Marigold ~SD-class).

**Manifest / meta.json.** `quality.textures` gains
`{"upscale_engine": "...", "pbr_pass": {applied, maps_added}}`.

**Failure modes.** PBR pass on already-PBR GLBs (TRELLIS.2/paint
outputs) is wrong → wrapper detects existing MR maps and refuses with
explanation; delight over-flattens stylized art → opt-in flag, judge
spot-check advised.

**Test strategy.** Upscale parity fixture (both engines, dimensions +
sharpness metric recorded); pbr smoke: output GLB has
metallicRoughnessTexture where input had none.

**Effort.** M.

## 25. Opt-in quad retopo — QuadWild bi-MDF for hero assets

**Problem.** Decimated tri-soup is fine for props, poor for assets
headed to sculpt/animation/close-up. No retopo path exists.

**Approach.** [QuadWild bi-MDF](https://github.com/cgg-bern/quadwild-bimdf)
(GPL-3 CLI — tool-side copyleft only, outputs unaffected; **prebuilt
macOS arm64 binaries in Releases**; no Gurobi needed). New
`generate.sh --retopo quad` (or standalone invocation documented in
skill): clean GLB → OBJ → quadwild → quad OBJ → GLB, polycount target
respected. Ordering rule as item 23: retopo before paint, never after;
textured inputs refuse (UVs don't survive).

**Bucket.** `commercial_safe` (tool, no weights).

**Hardware tier.** Both; minutes-scale CPU.

**Manifest / meta.json.** `cleanup.retopo: {method: "quadwild-bimdf",
faces_before, faces_after}`.

**Failure modes.** Binary lacks notarization → doctor install step
documents `xattr -d com.apple.quarantine`; pathological meshes hang →
wrapper timeout (config, default 10 min) + warn.

**Test strategy.** Fixture sphere-ish GLB → quad-dominant output
(>80% quads via trimesh face inspection), watertight preserved.

**Effort.** S–M.

---

# Decision gates (resolve during implementation, evidence required)

| Gate | Item | Question | Resolution mechanism |
|---|---|---|---|
| G1 | 15 | TRELLIS.2-4B LICENSE really MIT at install time; DINOv3 gate acceptable | Read LICENSE + HF card during install; record in `docs/model-review-trellis2.md` |
| G2 | 17 | Default judge tier (8B vs 35B-A3B) | Latency+quality mini-bench on 20 fixture images; record in decision doc |
| G3 | 21 | Multiple-Angles LoRA license | Read HF repo license; bucket accordingly |
| G4 | 24 | Marigold OpenRAIL++-M bucket call | Short decision doc; recommend commercial_safe+note |
| G5 | 24 | SeedVR2 weights license | Read HF card at install; bucket accordingly |
| G6 | 15/22 | Any default-model change | Bake-off + user sign-off (P-A) — out of scope for this spec's PRs |

# Explicit non-goals this round

- Changing any default model silently (P-A).
- Auto-rigging: UniRig is MIT but spconv/flash-attn CUDA-walled on Mac
  ([repo](https://github.com/VAST-AI-Research/UniRig)) — watchlist.
- Part segmentation lane (Hunyuan3D-Part promising, Mac-unverified,
  extra license territory terms) — watchlist.
- Resident-model daemon / keep-warm server — latency play, not quality;
  revisit after this round.
- Multi-color print auto-segmentation — depends on part segmentation.

# Watchlist (re-survey trigger: next quality round or 2027-01)

- **Pixal3D** (TencentARC, MIT, May 2026, TRELLIS.2 backbone,
  near-reconstruction fidelity) — blocked only by NATTEN CUDA glue;
  a Mac fork would leapfrog item 15. [Repo](https://github.com/TencentARC/Pixal3D)
- **Qwen-Image-2.0** (Apache, 7B diffusion) — successor default
  candidate once mflux/Draw Things support lands.
- **HiDream-O1-Image** (MIT, May 2026) — best-license frontier t2i, no
  Mac runtime yet.
- **Z-Image-Edit** — unreleased; would simplify the edit lane.
- **PartSAM / MagicArticulate / Hunyuan3D-Omni** — auxiliary lanes.
- **mflux Qwen-Image-Edit-2511 + FLUX.2 klein 9B KV-cache editing**
  release notes — track for edit-lane backend upgrades.
