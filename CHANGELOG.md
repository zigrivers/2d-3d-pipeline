# Changelog

Dated entries for significant changes to the docs, scripts, or skill.

## 2026-08-12 — R2.3: paint retarget (item 19)

- `scripts/texture.sh --mode paint` retargeted from item 7's original
  CUDA-only Hunyuan3D-Paint design to
  [`dgrauet/Hunyuan3D-2.1-mlx`](https://github.com/dgrauet/Hunyuan3D-2.1-mlx)
  (Apple Silicon MLX port; upstream needs CUDA
  `custom_rasterizer`/`differentiable_renderer`, unavailable on Mac).
  Pinned commit `5fe21945b790fbb7fb28c510e89babd7b9feabe6` per
  principle P-B. Bucket unchanged: `commercial_threshold`.
- New `--image PATH` flag (required in paint mode) — the port's
  pipeline needs a reference image for its multiview diffusion pass,
  not just mesh geometry.
- New `scripts/hunyuan_paint_run.py` — thin CLI driver around
  `Hunyuan3DPaintPipelineMLX`, mirroring the exact call shape verified
  in the R0.2 spike. Confirmed live on the Studio, twice: the port's
  own bundled fixture (22,447 vertices, 269.6s wall clock, matching
  R0.2) and a real generate.sh SF3D output (121s, real distinct
  albedo + metallic-roughness maps where none existed before).
- **Refusal path, verified live against a real TRELLIS.2 output:**
  `texture.sh --mode paint` now runs `texture_quality_check.py` live
  (not a possibly-stale meta.json field) and refuses with
  `status=error error=already_textured` when the input already has a
  real baked metallic-roughness map. Deliberately narrower than a
  blanket "any existing texture" check — a canned SF3D GLB has
  albedo+normal but bakes metallic/roughness as flat material
  factors, not textures, so painting it is still correct and adds a
  genuinely new MR map; a TRELLIS.2 output's real PBR bake
  (`albedo, roughness, metallic`) is correctly refused instead.
  Confirmed both directions live: SF3D input painted successfully,
  TRELLIS.2 input refused with the expected JSON + clear stderr
  explanation.
- Item 7's original regression tests re-verified live:
  `--mode inspect` and `--mode upscale` unchanged (upscale correctly
  fails `not_installed` — no `real-esrgan-ncnn-vulkan` on this Studio,
  same as before this PR).
- **Real pre-existing bug found and fixed:** `texture.sh`'s paint-mode
  extension check used `${VAR,,}` (bash 4+ lowercase parameter
  expansion), which crashes with `bad substitution` under macOS's
  system `/bin/bash` (3.2, what `env bash` resolves to without
  Homebrew bash on PATH) — confirmed live, this code path had
  apparently never been exercised before this PR. Fixed with a
  portable case-insensitive glob (`*.[Gg][Ll][Bb]`); no other script
  in the repo used the `,,` pattern.
- `generation.model_role: "paint"` and `generation.texture_backend:
  "hunyuan3d-paint"` now actually written to the painted output's
  meta.json (per item 7's original spec) — the pre-retarget stub
  never wrote either field despite the spec requiring both;
  `meta_helper.py validate` confirmed passing on a real output.
- `scripts/hunyuan_paint_run.py` added to embeds (43 blocks now,
  manually inserted per `CONVENTIONS.md`'s regenerate-can't-create-
  new-blocks limitation — same pattern as R2.2).
- `scripts/model_manifest.json` — `hunyuan3d-paint-env` venv path
  corrected to the real installed location
  (`~/3d-pipeline/hunyuan3d-paint-mlx/.venv`, was the old CUDA-era
  `hunyuan3d-paint-env`), gains `pinned_commit` + `repo_path`.
  `hunyuan3d-paint` model entry corrected to the real MLX weights
  repo (`dgrauet/hunyuan3d-2.1-mlx`, was `tencent/Hunyuan3D-2` with a
  nonexistent `hunyuan3d-paint.safetensors` filename); `requires_hf_auth`
  corrected to `false`. Verified: `pipeline_doctor.py --check venvs
  --include hunyuan3d-paint` shows the pinned-commit check passing
  against the real installed repo; `--check disk` correctly sums the
  corrected entries.
- `scripts/_install_lib.py::_hunyuan_warm` — fixed to point at the
  real venv path and to `snapshot_download` the whole repo when
  `filename` is empty (the port downloads weights per-file on demand,
  no single fixed filename covers "the model"), instead of a
  `hf_hub_download` call that referenced a venv/filename combination
  that no longer exists.
- **License review addendum**
  (`docs/license-review-hunyuan3d-paint.md`): corrects the original
  2026-05-20 review's clause 2 ("does not contain region exclusions")
  — the port's actual `LICENSE` file states verbatim "THIS LICENSE
  AGREEMENT DOES NOT APPLY IN THE EUROPEAN UNION, UNITED KINGDOM AND
  SOUTH KOREA." Fine for Ken (US) and current distribution plans; flag
  explicitly before any EU/UK/South Korea distribution decision.
  Documents the Brainkeys MPS fork is a shape-only fallback, not a
  paint fallback (its paint stage is limited/disabled) — the real
  fallback if this port bit-rots is "paint unavailable, use
  `--mode upscale`," not silently switching forks. Documents the
  undocumented `pymeshlab` dependency (README's MLX-path quickstart
  omits it; needed for the default `use_remesh=True` path).
- `skill/SKILL.md` Flow 6 — paint subsection rewritten for the MLX
  port: `--image` requirement, the metallic-roughness-based refusal
  signal (elevated from soft routing guidance to a hard wrapper
  check), region-exclusion warning, Brainkeys-not-a-fallback note.
- Both setup guides — new "Hunyuan3D-Paint MLX port" install step
  with the real, evidence-based install recipe (README's actual
  MLX-path quickstart + the `pymeshlab` fix), pinned-commit warning,
  region-exclusion and Brainkeys callouts.
- `scripts/_pipeline_lib.sh` — `hunyuan3d-paint` bucket comment
  updated to reference the MLX retarget and addendum (bucket value
  itself, `commercial_threshold`, was already correct).

## 2026-08-12 — R2.2: edit lane (item 21)

- New `scripts/edit.sh` — instruction-based concept editing and
  parametric camera-angle views via Qwen-Image-Edit-2511 (Apache 2.0,
  `commercial_safe`), both through the existing `mflux-env` venv (no
  new venv). `mflux-generate-qwen-edit`'s own default is
  Qwen/Qwen-Image-Edit-2509, not 2511 — confirmed live via the
  download log — so `edit.sh` always passes `--model
  Qwen/Qwen-Image-Edit-2511` explicitly.
- Instruction-edit mode confirmed working end to end on the Studio:
  real "make the wood darker and more weathered" edit against a real
  concept image, visually verified (chest correctly darker/weathered,
  subject and composition fully preserved), DreamSim drift 0.084–0.139
  (`similar_but_changed`) across two runs.
- `--angle H,V` camera-view mode uses the official
  `fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA` (gate G3, R0.6 spike:
  Apache 2.0 / `commercial_safe`, stronger than the spec's cautious
  `unclear_risky` default). Prompt syntax (`<sks> [azimuth] [elevation]
  [distance]`, 8×4 pose grid) read directly from the LoRA's own model
  card, not guessed.
- **`--angle`'s LoRA currently applies zero weight — confirmed live,
  documented as a known limitation, not shippable as functional in
  this PR.** mflux 0.18.1 logs `Applied to 0 layers (0/1680 keys
  matched)` for this LoRA (its diffusers-style
  `transformer_blocks.N.attn.*.lora_A/B` key names don't match
  mflux's internal Qwen-Image-Edit-2511 layer names) right before its
  own misleading `✅ All LoRA weights applied successfully` line.
  Visually confirmed the output shows no rotation at all versus the
  source (identical camera position on a requested 90° view). Tracked
  upstream at github.com/filipstrand/mflux/issues/298 — not fixable
  from this repo. `edit.sh` now parses mflux's own match-count line,
  prints a loud warning, and records `angle_lora_applied: false` in
  the output's `meta.json` instead of silently claiming the angle
  worked. Instruction-edit mode is unaffected.
- `scripts/edit_drift_check.py` — new DreamSim (MIT, `commercial_safe`)
  source-vs-result drift check, run automatically after every edit
  (`--no-drift-check` to skip). Bands the distance into
  `too_similar` / `similar_but_changed` / `too_different` against
  bootstrap thresholds (0.03 / 0.45, explicitly uncalibrated).
- `scripts/meta_schema.json` — `generation` section gains
  `edit_instruction`, `angle_azimuth_deg`, `angle_elevation_deg`,
  `angle_lora_applied`, and a `drift` object.
- `scripts/_pipeline_lib.sh` — `license_bucket_for_model` gains
  `qwen-image-edit` → `commercial_safe`.
- `scripts/model_manifest.json` — new `edit-lane` feature_set and a
  lightweight virtual venv entry pointing at the existing `mflux-env`
  path (`size_gb: 0`, so it satisfies the "every feature_set needs a
  matching venv" structural rule without double-counting disk). New
  `qwen-image-edit-2511` (~40 GB) and `qwen-multi-angle-lora`
  (~300 MB) model entries. `edit.sh` added to `wrappers`. Verified:
  `pipeline_doctor.py --check structure` clean, `--check disk
  --include edit-lane` correctly sums the new entries and detects the
  40 GB model as already-downloaded on this Studio.
- `skill/SKILL.md` — new Flow 10 (edit + angle-view), with the
  LoRA-limitation warning inline; "five new lanes" becomes "six new
  lanes".
- Both setup guides — new "Optional: edit lane (item 21)" step with
  the same LoRA-limitation callout (edit.sh needs no separate install,
  reuses the mflux-env venv from earlier in the guide).

## 2026-08-12 — R2.1: 2D model refresh (item 20)

- `scripts/concept.sh` — two new `-m` models: `flux2-klein` (FLUX.2
  klein 4B, Apache 2.0 — the FLUX.2 family's permissive exception; 9B
  and dev variants stay unadded, those are BFL non-commercial) and
  `ernie-image` (ERNIE-Image 8B, Apache 2.0, wired but currently
  non-functional — see below). Default 20 steps each. `flux-schnell` is
  not removed — still works, no longer the recommended LoRA path (see
  SKILL.md).
- `scripts/concept.sh` — `flux2-klein` dispatches through
  `mflux-generate-flux2`, not the generic `mflux-generate`: confirmed
  live that `mflux-generate` explicitly refuses FLUX.2 Klein
  (`"FLUX.2 Klein is not supported by mflux-generate. Use
  mflux-generate-flux2 instead."`). `ernie-image` uses the generic
  `mflux-generate --model ernie-image` path (that part of the CLI does
  accept it — the failure is deeper, in weight loading; see below).
  Real smoke test on the Studio: `flux2-klein` generated a correct,
  well-composed 3/4-view treasure chest in 163s (incl. first-time
  weight download), `--json` carrying the correct
  `"license_bucket": "commercial_safe"`.
- **`ernie-image` is wired but currently broken upstream, confirmed
  live, not shippable as working in this PR.** mflux 0.18.1 (the latest
  release) expects a `text_encoder_2` weight component that doesn't
  exist in either `baidu/ERNIE-Image`'s or `baidu/ERNIE-Image-Turbo`'s
  actual current Hugging Face repo layout — verified by listing both
  repos' files directly (neither has anything named `text_encoder_2`;
  both have `pe`/`pe_tokenizer`/`text_encoder`/`transformer`/`vae`
  instead). Both variants fail identically with `FileNotFoundError: No
  safetensors files found in .../text_encoder_2`. This is an upstream
  mflux/HF-repo mismatch, not a `concept.sh` wiring bug, and not fixable
  from this side — the dispatch code is correct and needs no further
  changes once mflux ships a fix. Documented clearly in `skill/SKILL.md`
  and both setup guides so nobody wastes time chasing this blind.
- `scripts/concept.sh` — `--lora` now hard-errors (not just warns) when
  combined with `flux2-klein` or `ernie-image`: FLUX.1 LoRAs (trained
  for `flux-schnell`/`flux-dev`) are a different checkpoint
  architecture and are not interchangeable with these — without this
  check, mflux would fail deep inside model loading with a confusing
  tensor-shape error instead of a clear message naming the mismatch.
  Verified live: `concept.sh "test" -m flux2-klein --lora
  /tmp/fake.safetensors` exits 1 with the mismatch message before
  touching mflux at all.
- `scripts/_pipeline_lib.sh` — `license_bucket_for_model` gains
  `flux2-klein`, `ernie-image` → `commercial_safe`.
- `scripts/pipeline_doctor.py` — new generic `min_package_version` venv
  check (parallel to R1.4's `pinned_commit` check): compares a venv's
  installed package version via `pip show` against a manifest-declared
  minimum, reports `drift` with an upgrade `fix_command` on mismatch.
  `mflux-env` now declares `mflux >= 0.18` (required for both new
  models — an older mflux parses the model name fine but fails deep
  inside model loading, not at an obvious version-check point).
  Verified both directions live: real install passes at 0.18.1,
  correctly reports `version-too-old` against an artificially high
  minimum.
- `skill/SKILL.md` — Flow 1 gains a model-selection table (mirroring
  Flow 2's generator matrix): `flux2-klein` recommended for new
  FLUX-ecosystem LoRA work or built-in editing, `ernie-image` as the
  prompt-adherence retry model when Z-Image Turbo's known
  face-the-camera weakness keeps failing 3/4-view judging, `flux-schnell`
  demoted to "legacy, still works." Z-Image Turbo stays the default
  (principle P-A — no silent default change). New translation-adjacent
  guidance on the LoRA-family-mismatch error.
- Both setup guides — mflux ≥ 0.18 upgrade callout (with the exact
  `pip show` / `pip install --upgrade mflux` commands) right after the
  venv-creation step, plus a new smoke-test step for both models with a
  warning against substituting the FLUX.2 klein 9B/dev variants.
## 2026-08-12 — R1.5: TRELLIS.2 vs SF3D/SPAR3D bake-off (docs-only)

- `docs/model-review-trellis2.md` — real bake-off results filled into
  the placeholder from R1.4: `scripts/benchmark.sh --suite default
  --generators sf3d,spar3d,trellis2 --judge-mesh` run against 14 real
  prompts. SPAR3D excluded (not installed on this Studio — documented
  honestly, not faked). SF3D vs TRELLIS.2 over 14/14 successful runs
  each: TRELLIS.2 is ~6.1× slower and produces ~14× larger GLBs (real
  PBR + denser geometry) but scores meaningfully better on item 18's
  mesh judge (21% vs 43% below-floor rejection rate). Both generators
  independently collapsed the same two prompts ("fantasy sword",
  "product prototype stand") into hairline-sliver meshes — a shared
  single-image-reconstruction limitation, not a generator-specific
  defect. **No default changed** — recommendation is TRELLIS.2 as a
  deliberate opt-in for hero/commercial assets, default-promotion
  decision (gate G6) left to the user per principle P-A.
- `scripts/model_bakeoff.py` — added `trellis2` to the allowed
  `--generators` list and its `LICENSE_BUCKET` map (was missing
  entirely — the bake-off couldn't run against it before this).
  New `--judge-mesh` flag, forwarded to each `generate.sh` call. New
  `peak_memory_mb` field per run, scraped from the wrapper's own
  stderr (`Peak Memory: ... MB` / `Peak MLX memory: ... GB`) — this
  data existed in every run already but was previously discarded on
  success (`stderr_tail` was only kept on error). SF3D's peak memory
  was captured for all 14 runs (~11 GB avg); TRELLIS.2's `generate.py`
  doesn't print a comparable figure, so that field came back empty for
  all 14 TRELLIS.2 runs — documented as a real gap in the bake-off
  writeup rather than papered over.
- `scripts/benchmark.sh` — `--judge-mesh` passthrough flag; generator
  list in `--help` gains `trellis2`.

## 2026-08-12 — R1.4: TRELLIS.2 backend (item 15)

- `scripts/generate.sh` — new `-g trellis2` generator, dispatching to a
  separate, pinned-commit install at `~/3d-pipeline/trellis2-mac`
  (distinct from the existing `-g trellis`, which is a different,
  older model and stays untouched). Produces real PBR-textured GLBs
  (baseColor + metallic/roughness, Metal-baked) — verified with
  `trimesh` against a real Studio generation. Background removal is
  forced through the pipeline's own `rembg_preprocess.py` for this
  generator specifically (`BG_REMOVAL_MODE` defaults to `on`, not
  `auto`), so the port's bundled RMBG-2.0 (CC BY-NC) never fires —
  confirmed live via a stale RMBG-2.0 cache timestamp and a real
  non-uniform alpha channel on the input the port actually received.
- `scripts/generate.sh` — also wires the `generation` meta.json section
  (`backend`, `license_bucket`, `polycount_target`, `texture_resolution`,
  `duration_seconds`) for **all** generators, not just trellis2: no
  script previously wrote this section at all, despite
  `meta_schema.json` reserving it since v0.3.
- `scripts/_pipeline_lib.sh` — `license_bucket_for_model` gains
  `trellis2` → `commercial_safe` (MIT port + MIT weights, gate G1). The
  existing `trellis` (v1) → `non_commercial` mapping is untouched.
- `scripts/pipeline_doctor.py` — new pinned-commit smoke check
  (`pinned_commit` / `repo_path` venv fields, principle P-B): compares
  a venv's `git rev-parse HEAD` against the pinned commit and reports
  `drift` with a working `fix_command` on mismatch. Verified both
  directions live: PASS at the pin, correct FAIL after a temporary
  `git checkout` to a different commit, restored afterward.
- `scripts/model_manifest.json` — new `trellis2` feature set,
  `trellis2-env` venv (pinned to commit `d58628f4f5b9c3de8274cb110074154f4b31cef2`),
  and two model entries (`trellis2-weights`, MIT; `dinov3-encoder`,
  Meta license, gated, `commercial_safe` — both self-managed by the
  port at first use via `huggingface_hub`, same pattern as R1.2's
  `qwen3-vl-judge`).
- `docs/model-review-trellis2.md` (new) — license review, port limits,
  live evidence, and a bake-off placeholder for plan phase R1.5.
- Two real bugs found and fixed while getting a smoke generation
  working end-to-end on the Studio:
  1. `generate.sh` called `info()` (in the background-removal
     "applied" branch) roughly 60 lines before `info()`/`done_()`/
     `err()` were actually defined — a pre-existing ordering bug that
     was dormant because no generator had ever forced
     `BG_REMOVAL_MODE=on` before, and the "auto" heuristic never
     applied to the clean-background fixtures used in prior testing.
     Fixed by moving the color/logging function definitions earlier,
     right after `json_mode_begin`.
  2. The new `trellis2` dispatch block didn't clean up the `.obj`
     sidecar file `generate.py` also writes alongside the GLB (the
     existing `trellis` v1 block already does this for its own
     sidecar) — fixed by adding the same cleanup line.
- `skill/SKILL.md` — generator recommendation matrix gains TRELLIS.2
  rows; new `commercial_safe` entry for `trellis2`; generator lists and
  example dialogue updated to distinguish TRELLIS (v1) from
  TRELLIS.2 (v2) explicitly.
- `context/asset-pipeline-ai-context.md` (+ HTML mirror) — correction
  pass over stale "TRELLIS.2 = CC BY-NC / vertex colors only" claims
  (§05, §08, §19 and others): those statements were accurate for the
  legacy TRELLIS (v1) port when originally written, but had drifted
  into describing the *wrong* model under the "TRELLIS.2" name. Now
  explicit throughout: TRELLIS (v1, `non_commercial`, vertex-colors-only)
  vs TRELLIS.2 (v2, item 15, `commercial_safe`, real PBR) are two
  different models, not the same one at two points in time.
- Both setup guides — the existing "Install TRELLIS.2 (optional)" step
  was actually installing the legacy v1 port under a misleading label;
  relabeled as TRELLIS (v1, legacy) and given its own verify step, and
  a new, separate TRELLIS.2 (v2) install step added with the pinned
  commit, the Metal Toolchain prerequisite (hit during the R0.1 spike —
  without it, all four Metal backend packages silently fall back to a
  slow CPU path), the `o_voxel` submodule fallback fix, and a DINOv3
  gated-access callout.

## 2026-08-12 — R1.3: mesh judge (item 18)

- `scripts/vlm_judge.py` — new `--mode mesh`. Renders of a mesh's
  turntable views are judged in a single joint VLM call (all N views in
  one prompt, `num_images=N`) rather than the item 17 image mode's
  one-call-per-image isolation — deliberately, since geometry artifacts
  and back-face plausibility can only be judged by comparing views of
  the same object. Scores `recognizable`, `back_face_plausibility`,
  `geometry_artifacts`, `texture_coherence` (nullable — the rubric
  instructs the model to skip texture judgment and score geometry-only
  on untextured/vertex-color-only meshes), and `overall`, plus a short
  `artifacts_note` when `geometry_artifacts` is low. Writes
  `judge.mesh` (nested under the existing `judge` section) via
  `meta_helper.py merge`.
- `scripts/generate.sh` — new `--judge-mesh` flag. Renders 8 turntable
  views (configurable via `mesh_judge_views` in the pipeline config,
  default floor 2/10 via `mesh_judge_floor`) independent of the
  user-facing `--preview` mode/frame count, judges them, and prints a
  plain-language "3D check: ..." summary. Warn-don't-block per
  principle 10: a below-floor verdict flags the asset in meta.json and
  the console but never fails the run. Cross-checks the judge's
  floater note against `cleanup.loose_elements_deleted` from
  `clean_asset.py`'s own report before presenting it, per the item 18
  spec's false-floater-report failure mode. No-op when `vlm-env` or
  `vlm_judge.py` isn't installed. `--json` output is additive-only:
  `judge_mesh_verdict` / `judge_mesh_rejected` only appear when
  `--judge-mesh` actually produced a verdict, so a no-flag run's JSON
  is byte-identical to before this change.
- `scripts/meta_schema.json` — `judge.mesh` subsection gains concrete
  fields (`model`, `views_rendered`, `scores.*`, `notes`, `verdict`,
  `rejected`, `duration_seconds`), replacing the generic placeholder
  object reserved in R1.2.
- `skill/SKILL.md` — new "Mesh judge" subsection under Flow 2; 3 new
  jargon-translation rows for `judge.mesh.*`.
- No new venv/model — reuses item 17's `vlm-env` + Qwen3-VL-30B-A3B
  infra; no setup-guide changes needed.
- Mesh rubric fix found during the required flattened-vs-good fixture
  test (AC: 3/3 separation): the first rubric draft scored an obviously
  degenerate fixture (a real GLB with Z scaled ×0.02 — renders as a
  hairline sliver in every view) identically to the good fixture (8/10,
  3/3 runs), even naming "sliver on left edge" in `artifacts_note`
  while still scoring `geometry_artifacts: 8` — the same rubric-text-
  vs-score disconnect gate G2 hit in item 17. Fixed the same way: added
  a `shape_consistency` field the model must answer literally (does the
  silhouette hold a consistent volume, or collapse to a hairline sliver
  in any view?) before scoring, with an explicit instruction that a
  hairline collapse forces `geometry_artifacts`/`recognizable`/`overall`
  to 0-1 regardless of any other view looking clean. Re-verified 3/3:
  good fixture 8/10 not rejected, flattened fixture 0/10 rejected, both
  consistent across runs.
- **Pre-existing bug, found blocking `generate.sh` entirely and fixed
  in this PR** (unrelated to item 18's scope, but the literal blocker
  for testing it): `meta_helper.py`'s `merge` subcommand prints
  `[meta_helper] merged ... into ...` on stdout. Nine scripts across
  the pipeline (`input_quality_check.py`, `mesh_quality_check.py`,
  `texture_quality_check.py`, `game_asset_check.py`,
  `print_structural_check.py`, `rembg_preprocess.py`, `clip_score.py`
  ×2 call sites, `dedup_variants.py` — the last two written in R1.1)
  call it via `subprocess.run` without capturing that output, so it
  leaks onto the calling script's own stdout ahead of its `--json`
  payload. Any caller that then parses that stdout as JSON (as
  `_pipeline_lib.sh`'s `check_and_normalize_input` does with
  `input_quality_check.py --json`) gets
  `json.decoder.JSONDecodeError: Expecting value: line 1 column 2` and
  — since that specific call site redirects the parse error to
  `/dev/null` — `generate.sh` died silently via `set -e` with no
  visible error at all. Same root cause and same fix as the
  `vlm_judge.py` bug fixed in R1.2: added `capture_output=True` to all
  nine call sites.
- **Pre-existing Blender bug, also found blocking `generate.sh`
  end-to-end and fixed in this PR**: `clean_asset.py`,
  `turntable_render.py`, and `prepare_for_print.py` all read
  `bpy.context.view_layer.objects.active` right after
  `bpy.ops.import_scene.gltf(...)` without ever setting it when the
  import produces exactly one mesh object (the `len(meshes) > 1` join
  branch was the only place `.active` got set). On this Studio's
  Blender 5.2.0 LTS, a single-mesh glTF import does not set an active
  object, so `obj` was `None` and every single-mesh cleanup/render
  crashed with `AttributeError: 'NoneType' object has no attribute
  'vertices'`. Fixed by setting `.active = meshes[0]` unconditionally
  right after the mesh list is validated non-empty, in all three files.

## 2026-08-12 — R1.2: local VLM judge + best-of-N (item 17)

- `scripts/vlm_judge.py` (new) — local VLM judging of 2D concept images via
  `mlx-vlm` (MIT) on Apple Silicon. Rubric asks the model to first name,
  literally, which faces of the object's outer shell are visible
  (`visible_faces`) before scoring `three_quarter_view` — a bare numeric
  rubric could not reliably tell a genuine 3/4 view from a flat front-on
  shot even at the 30B-A3B tier (see gate G2, `docs/spike-report-generation-refresh.md`
  R0.3); forcing the literal fact first produces a real, auditable score
  gap between the two cases. `--rank` mode scores N images and picks a
  winner; the winner's judge data merges into its `meta.json` `judge`
  section via `meta_helper.py merge`.
- Default judge model is `mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit`
  (Apache 2.0; commercial_safe), not the smaller 8B tier — R0.3 found the
  8B tier scores a flat front-view fixture and true 3/4-view fixtures
  identically regardless of rubric wording, so it can't be trusted for
  this judgment. Documented in code comments, `skill/SKILL.md`, and the
  setup guide callout.
- `scripts/concept.sh` — new `--judge` flag (score the concept, no
  filtering) and `--best-of N` flag (generate N variants, judge them,
  keep only the winner in `concept/`, move the rest to
  `concept/rejected/`). No-op when `vlm-env` or `vlm_judge.py` isn't
  installed. Fixes a real bug found during integration testing: the
  `--rank --json` subprocess that merges the winner's judge data into
  `meta.json` via `meta_helper.py merge` let that helper's own
  `[meta_helper] merged ...` stdout line leak ahead of the JSON payload,
  so `concept.sh`'s `json.load()` of `vlm_judge.py`'s stdout failed on
  every `--best-of` run (`json.decoder.JSONDecodeError: Expecting value:
  line 1 column 2`). Fixed by capturing that subprocess's output
  (`capture_output=True`) instead of letting it inherit the parent's
  stdout. Verified end-to-end on the Studio: `--best-of 3` correctly
  ranked 3 real generations, moved the 2 non-winners to `rejected/`, and
  wrote a correct `judge` section to the winner's `meta.json`; `--judge`
  alone (no `--best-of`) verified the same way.
- `scripts/meta_schema.json` — new `judge` top-level section (`model`,
  `mode`, `scores.*`, `verdict`, `picked`, `rank`, `rejected`,
  `duration_seconds`; `mesh` reserved for item 18).
- `scripts/meta_helper.py` — `KNOWN_SECTIONS` gains `judge`.
- `scripts/model_manifest.json` — new `vlm-judge` feature set, `vlm-env`
  venv entry, `qwen3-vl-judge` model entry (managed by `mlx_vlm`, HF repo
  `mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit`).
- `scripts/lockfiles/vlm-env.txt` (new, placeholder, matches existing
  0-byte lockfile convention).
- `skill/SKILL.md` — new "VLM judge + best-of-N" subsection under Flow 1;
  3 new jargon-translation rows (`judge.verdict`, `three_quarter_view` +
  `visible_faces`, `judge.rejected`).
- `docs/asset-pipeline-guide.html` + `-studio.html` — new `vlm-env` setup
  step with a callout explaining the 30B-A3B default (gate G2).

## 2026-08-11 — R1.1: scorer stack refresh (item 16)

- `scripts/clip_score.py` — new `--scorer {clip,siglip2}` flag, default
  `siglip2` (Apache 2.0; commercial_safe), replacing OpenCLIP ViT-L/14 as
  the default prompt-adherence scorer per arXiv:2606.18451. CLIP path kept
  for back-compat via `--scorer clip`. `clip.scorer` is a new sibling field
  in the `clip` meta.json section; `clip.model` now reports the actual
  model ID used.
- `scripts/preference_score.py` (new) — ImageReward (Apache 2.0;
  commercial_safe) human-preference scoring. Writes `clip.image_reward` +
  `clip.image_reward_model`. Includes a `transformers.modeling_utils`
  compat shim: ImageReward's vendored BLIP/BERT code imports three
  pruning-related helpers that modern `transformers` relocated or removed
  outright; the shim re-adds them so SigLIP 2 (needs recent `transformers`)
  and ImageReward (needs the old API surface) can share one
  `pipeline-tools-env` venv instead of forking it.
- `scripts/dedup_variants.py` (new) — DreamSim (MIT; commercial_safe)
  perceptual near-duplicate detection across `-n N` concept variants.
  Union-find groups pairs below a distance threshold (default 0.15).
  Writes `clip.dreamsim_dupes` + `clip.dreamsim_threshold`.
- `scripts/calibrate_clip.py` — `--scorer {clip,siglip2}` flag; calibration
  bands are now nested `calibration[scorer][model_name]` in
  `scripts/clip_calibration.json` (was flat `calibration[model_name]`).
  Also fixes a real pre-existing bug in `_score_one`: it parsed
  `clip_score.py --json`'s output by taking the last stdout line, but that
  output is pretty-printed (`indent=2`) across multiple lines — the last
  line is just `}`, so every calibration run silently scored 0 samples and
  fell back to `skipped_too_few_samples`. Now parses from the first `{`
  onward. Verified with a live 2-sample SigLIP 2 run (see PR).
- `scripts/clip_calibration.json` — restructured to
  `{"siglip2": {...}, "clip": {...}}`. SigLIP 2 bands are a small-sample
  bootstrap (n=5 real fixtures scored 2026-08-11), not a full percentile
  calibration; run `calibrate_clip.py --scorer siglip2` once real
  generation history accumulates.
- `scripts/_pipeline_lib.sh` — `license_bucket_for_model` gains `siglip2`,
  `imagereward`, `dreamsim` → `commercial_safe`.
- `scripts/meta_schema.json` — `clip` section gains `scorer`,
  `image_reward`, `image_reward_model`, `dreamsim_dupes`,
  `dreamsim_threshold` (additive; `additionalProperties: true` already
  allowed this, added for documentation/validation clarity).
- `scripts/concept.sh` — after generation, also runs
  `preference_score.py` (top-ranked variant) and, when `-n N > 1`,
  `dedup_variants.py` across all variants. Both no-op gracefully if
  `pipeline-tools-env` or the script isn't installed, matching the
  existing CLIP-scoring pattern.
- `docs/asset-pipeline-guide.html` + `-studio.html` — `pipeline-tools-env`
  install steps updated with the full working recipe: pin
  `transformers==4.57.6` (newest release with both SigLIP 2 support and
  the API surface ImageReward's vendored BLIP code needs), `dreamsim`,
  `image-reward --no-build-isolation` (its `setup.py` needs `pkg_resources`
  at build time without declaring `setuptools` as a build dep — same class
  of issue as SF3D's `texture_baker`), `git+https://github.com/openai/CLIP.git`
  (an undeclared runtime dependency of `image-reward`), and a `timm`
  re-pin (`image-reward`'s install downgrades it below what
  `open_clip_torch` needs; verified the newer `timm` still works for
  `image-reward` despite its conservative pin). Verify step updated to
  test `ImageReward` through the compat shim, not a bare import — a bare
  import fails even on the pinned `transformers` version.
- `skill/SKILL.md` — translation table: CLIP rows replaced with SigLIP
  equivalents; new rows for `image_reward` and `dreamsim_dupes`. Pre-flight
  section notes `--warm-cache` doesn't yet cover ImageReward/DreamSim
  weights (out of scope for this item; they download on first real use).
- Real evidence this round: SigLIP 2 discriminates prompt/subject match
  strongly (0.165 own-prompt vs -0.105 mismatched-prompt, stable across 3
  runs) but — like CLIP — is weak on compositional violations (view angle,
  clutter) at the raw-embedding level, consistent with why item 17's VLM
  judge exists as a complementary signal rather than a CLIP-family
  replacement.

## 2026-08-11 — heartbeat race fix + post-squash repo hygiene

- `scripts/_heartbeat.py` — `write()` timeout path now returns a fresh
  result dict. Previously the still-running rename thread could mutate
  the shared dict after return (its `tmp.replace` races the timeout
  path's `tmp.unlink`), flipping a caller's `degraded` outcome to
  `failed` (`FileNotFoundError`). Surfaced as an order-dependent
  failure of `test_heartbeat_write_timeout_returns_degraded`; suite now
  green (132 passed, verified 3 consecutive runs). Embeds regenerated.
- `docs/pipeline_decision_analysis.md` (+ `.html`) — committed the
  v0.3 nine-decision analysis record that resolved the improvement-spec
  gates (was sitting untracked from a prior session).
- `docs/plan-claude-driven-setup.md` — lockfile-generation paths
  corrected to the repo's current location (`~/Developer/...`).
- Removed a stale Finder duplicate (`plan-claude-driven-setup 2.md`,
  byte-subset of the tracked file) and a misplaced root
  `asset-pipeline-bundle.zip` (regenerable via `make bundle` into
  `dist/`). `.antigravitycli/` added to `.gitignore`.
- Note: PR #2's squash flattened 25 previously-unpushed local commits
  (P1.0–P5.8, the v0.4 Claude-driven-setup workstream) into one commit
  on `main`. Granular history preserved on the
  `archive/v0.4-setup-workstream` branch.

## 2026-05-20 — Q5: pipeline-doctor CI integration

- `scripts/pipeline_doctor.py` — new `--check structure` subcheck (CI-only,
  excluded from `--check all`). Four rules: EMBEDS source files exist on disk;
  every venv references a declared feature_set; every model references a
  declared feature_set with at least one matching venv; wrappers list ↔
  scripts/ parity (each entry is a plain executable file in scripts/; every
  .sh is in wrappers or internal_scripts).
- `scripts/model_manifest.json` — added `internal_scripts` array listing
  intentionally-non-public .sh files (_pipeline_lib.sh, migrate_assets.sh).
  Added `multiview.sh` to `wrappers` (user-facing; was omitted from P3.1).
  Updated description to note CI structural validation.
- `.github/workflows/pipeline-doctor.yml` — new workflow triggered on PRs and
  main pushes touching scripts/ or tools/_embed_lib.py. Fails on critical
  structure findings and any non-ok wrapper status. Posts an idempotent JSON
  report as a PR comment.
- `CONVENTIONS.md` — new CI / pipeline-doctor section documenting the workflow
  and how to fix failures.

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
