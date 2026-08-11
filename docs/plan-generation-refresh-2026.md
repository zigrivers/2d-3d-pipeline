# Generation-refresh implementation plan (2026-08)

**Status:** ready for execution · **Companion spec:**
[`spec-generation-refresh-2026.md`](spec-generation-refresh-2026.md) ·
**Executor:** an AI coding agent (written for Claude Sonnet 5, no prior
conversation context assumed)

## 0. Orientation for the executing agent (read first)

You are implementing spec items 15–25 in the `2d-3d-pipeline` repo.
Facts you must internalize before touching anything:

1. **This repo is docs + canonical scripts, not the installation.**
   The live pipeline lives in `~/3d-pipeline/` (venvs, weights) and
   `~/.claude/skills/asset-pipeline/` (deployed skill). This repo's
   `scripts/` and `skill/` are the source of truth; the HTML setup
   guides in `docs/` embed those files byte-for-byte.
2. **After ANY change under `scripts/` or `skill/`, run
   `make regenerate && make verify`** and commit the regenerated HTML
   with the script change. CI (`.github/workflows/pipeline-doctor.yml`)
   re-checks. `make bundle` must still build.
3. **Read these before coding** (in order):
   `context/asset-pipeline-ai-context.md` (architecture + reasoning),
   `context/asset-pipeline-ai-context-studio.md` (studio tier),
   `docs/improvement-spec.md` §"Cross-cutting design principles"
   (meta.json merge contract, license buckets, additive-only rule),
   `CONVENTIONS.md`, `skill/SKILL.md`.
4. **House invariants:** bash wrappers (not Python CLIs); one venv per
   tool under `~/3d-pipeline/<tool>/`; every new model registered in
   `_pipeline_lib.sh::license_bucket_for_model`; every quality pass
   writes meta.json via `scripts/meta_helper.py merge` (never raw
   writes); new subprocesses route through `json_mode_begin/end` so
   `--json` stays clean; SKILL.md updated in the same PR as the
   behavior; CHANGELOG.md entry per PR; new meta.json sections need a
   schema update in `scripts/meta_schema.json` + CHANGELOG note.
5. **Defaults never change in this plan.** Z-Image Turbo and SF3D stay
   defaults. Anything that could become a default produces bake-off
   evidence and stops (gate G6 — user decision, not yours).
6. **When reality differs from the plan** (a fork moved, a license
   changed, an install fails): the spec's principles P-A/P-B/P-C decide.
   Prefer: verify → document the delta in the PR description and the
   relevant decision doc → degrade gracefully (opt-in lane ships
   disabled with a doctor warning) → never silently substitute a
   different model or license bucket. If a *license* turns out worse
   than the spec recorded, stop that item and flag for user review.
7. **Setup guides:** new install steps go into both
   `docs/asset-pipeline-guide.html` and
   `docs/asset-pipeline-guide-studio.html` via the canonical-script
   embed mechanism (see `CONVENTIONS.md` regeneration procedure), and
   tier deltas into `docs/UPGRADES-laptop.md` / `docs/UPGRADES-studio.md`.
8. Machines available: laptop tier (128 GB M-series) and studio tier
   (M3 Ultra, 512 GB, 8 TB). All work must leave laptop tier functional.

Each phase below = one PR unless stated. Every step has an acceptance
criterion (AC). Run tests you write; paste outputs in PR descriptions.

---

## Phase R0 — spikes + license verifications (1 PR, docs-only output)

Cheap de-risking before any wiring. Output: a single
`docs/spike-report-generation-refresh.md` with one section per spike,
each ending PASS / FAIL / BLOCKED + evidence (commands, timings,
license text quotes). No pipeline code changes in this PR.

- **R0.1 — TRELLIS.2 license + install spike (gate G1).** Clone
  `shivampkumar/trellis-mac` at latest commit; record the commit hash.
  Read `LICENSE` in `microsoft/TRELLIS.2` and the HF model card for
  `microsoft/TRELLIS.2-4B`; quote the license grant lines. Note the
  DINOv3 gating steps encountered. Run one image→GLB generation on the
  studio. AC: report section contains commit hash, quoted license
  text confirming MIT (or a STOP flag if not), wall-clock time, peak
  memory (`sudo footprint` or Activity Monitor figure), and whether
  the GLB contains PBR textures (inspect with
  `python3 -c "import trimesh; ..."` or three-lines gltf JSON dump).
- **R0.2 — Hunyuan3D-Paint MLX spike.** Install
  `dgrauet/Hunyuan3D-2.1-mlx` (pin commit); paint one canned SF3D GLB.
  AC: painted GLB has albedo + metallic-roughness textures; timing +
  peak memory recorded; repo license of the port itself quoted.
- **R0.3 — mlx-vlm judge spike (gate G2).** Install mlx-vlm in a scratch
  venv; run Qwen3-VL-8B-Instruct (4-bit) scoring 5 sample concept PNGs
  with a draft rubric prompt returning JSON. Also time Qwen3.5-35B-A3B
  if download budget allows. AC: valid JSON scores 5/5 runs, s/image
  recorded per tier, chosen default tier stated with reasoning.
- **R0.4 — MV-Adapter MPS spike (item 22).** Attempt i2mv generation on
  MPS per repo README (SDXL base). Timebox: 1 day. AC: PASS (6 views
  generated; timing) or BLOCKED (exact failing op/traceback quoted).
- **R0.5 — Hunyuan3D-2mv MPS spike.** Timebox: 1 day. Attempt 2-view →
  shape on MPS (reuse Brainkeys 2.1 fork learnings; 2mv lives in the
  Hunyuan3D-2 repo). AC: PASS/BLOCKED + evidence, same format.
- **R0.6 — license reads (gates G3, G4, G5).** Quote license files/cards
  for: fal Multiple-Angles LoRA, Marigold-IID (OpenRAIL++-M — draft the
  bucket recommendation), SeedVR2 weights. AC: each has quoted text +
  proposed bucket + one-line rationale.
- **R0.7 — Marigold/StableDelight MPS spike.** Run Marigold-IID
  appearance pipeline via diffusers on MPS on one rendered texture.
  AC: PASS/BLOCKED + output maps saved.

Spike failures reroute later phases as the spec's per-item failure
modes describe; a BLOCKED R0.1 stops item 15 entirely (flag user).

## Phase R1 — Tier 1 core (items 15–18)

### R1.1 — item 16: scorer stack (PR 1)
Touch: `scripts/clip_score.py` (add `--scorer`, SigLIP 2 default;
keep CLIP path), new `scripts/preference_score.py` (ImageReward),
new `scripts/dedup_variants.py` (DreamSim), `scripts/calibrate_clip.py`
(scorer-aware bands), `pipeline-tools-env` requirements update in both
setup guides, `_pipeline_lib.sh` license map (three `commercial_safe`
entries), meta schema (`clip` section additions), SKILL.md translation
rows, CHANGELOG.
AC: fixture ordering test passes (good>bad stable per scorer, 3 runs);
`concept.sh --json` unchanged shape except additive fields;
`make verify` green.

### R1.2 — item 17: VLM judge + best-of-N (PR 2)
Touch: new `scripts/vlm_judge.py` (modes: `image`; JSON in/out; venv
`~/3d-pipeline/vlm-env/`), `concept.sh` (`--judge`, `--best-of N`),
`pipeline_doctor.py` (vlm-env + judge-weights cache checks; disk
estimates), meta schema (new top-level `judge` section), SKILL.md
(Flow 1 judge subsection + translations), setup guides (vlm-env
install step), CHANGELOG.
AC: fixture pair ranked correctly 3/3; `--best-of 4` leaves 1 winner +
3 in `concept/rejected/`; meta.json `judge` section validates against
schema; latency logged and under the R0.3-chosen budget on studio.

### R1.3 — item 18: mesh judge (PR 3, depends R1.2)
Touch: `scripts/vlm_judge.py` (`--mode mesh` using
`scripts/turntable_render.py` views), `generate.sh` (`--judge-mesh`),
meta schema (`judge.mesh`), SKILL.md Flow 2 addition, CHANGELOG.
AC: flattened-GLB fixture separated from good GLB 3/3; warn-don't-block
verified (below-floor verdict still exits 0, sets the meta.json flag,
and prints the warning); `generate.sh --json` additive-only confirmed
by diffing old/new output on a no-flag run.

### R1.4 — item 15: TRELLIS.2 backend (PR 4; requires R0.1 PASS)
Touch: `generate.sh` (`-g trellis2` dispatch + validation),
`_pipeline_lib.sh` (`trellis2` → `commercial_safe`; leave `trellis`
untouched), rembg preprocessing wired in place of RMBG-2.0,
`pipeline_doctor.py` (venv/weights/pinned-commit smoke check),
`skill/SKILL.md` (generator matrix row + license note), both setup
guides (install section with pinned commit + DINOv3 gate instructions +
quarantine/xattr notes as needed), `docs/model-review-trellis2.md`
(decision record: license quotes from R0.1, port limits, bake-off
placeholder), correction pass over stale "TRELLIS.2 = CC BY-NC /
vertex colors" statements in `context/asset-pipeline-ai-context.md`
§05/§19 and SKILL.md (mark v1-vs-v2 distinction explicitly), CHANGELOG.
AC: smoke generation from canned PNG produces GLB with PBR maps;
meta.json `generation.backend == "trellis2"`; doctor check passes and
fails correctly when commit hash mismatches (test by temporarily
checking out a different commit); `make verify` green; stale-docs grep
(`grep -ri "vertex color" context/ docs/ skill/`) reviewed — every
remaining hit is accurate post-change.

### R1.5 — TRELLIS.2 vs SF3D/SPAR3D bake-off (PR 5, docs-only)
Run `scripts/model_bakeoff.py` studio `default` suite across sf3d /
spar3d / trellis2; judge outputs with R1.3's mesh judge; fill the
comparison into `docs/model-review-trellis2.md` with a recommendation.
**Stop here** — default promotion is gate G6 (user decision).
AC: doc contains per-model scores, timings, memory, judge verdicts,
and an explicit recommendation paragraph. No default changed.

## Phase R2 — model refresh lanes (items 19–22)

### R2.1 — item 20: 2D refresh (PR 6)
Touch: `concept.sh` (model cases `flux2-klein`, `ernie-image` +
validation), `_pipeline_lib.sh` license map, `pipeline_doctor.py`
(mflux ≥0.18 preflight + upgrade hint), SKILL.md (model guidance,
schnell → legacy row, Z-Image face-camera weakness note in
prompt-tips, LoRA-generation mismatch warning), setup guides
(mflux upgrade note), CHANGELOG.
AC: smoke image per new model; `--json` carries correct
`license_bucket`; FLUX.1-LoRA-with-FLUX.2-model invocation errors with
a message naming the mismatch.

### R2.2 — item 21: edit lane (PR 7; needs R0.6/G3 resolved)
Touch: new `scripts/edit.sh` (wrapper pattern; `--angle h,v`;
multiview-convention filenames), `_pipeline_lib.sh` (edit model +
LoRA buckets per G3), meta schema note (uses existing `generation`
shape — confirm no change needed, else additive), `update_manifest.py`
mapping check, SKILL.md Flow 10, doctor (weights cache ~40 GB entry +
disk estimate update), setup guides, CHANGELOG. DreamSim drift check
wired from R1.1.
AC: edit smoke (instruction applied, DreamSim in configured
similar-but-changed band); angle smoke (subject persists per judge);
`edit.sh --angle` filenames pass `multiview.sh` required-view
validation dry-run; unverified-LoRA warning appears iff G3 resolved
to `unclear_risky`.

### R2.3 — item 19: paint retarget (PR 8; requires R0.2 PASS)
Touch: `scripts/texture.sh` (`--mode paint` per original item 7 spec),
new venv install docs (MLX port, pinned commit), doctor cache checks,
`docs/license-review-hunyuan3d-paint.md` addendum (MLX-port targeting +
EU/UK/South Korea exclusion + fallback statement re Brainkeys fork
paint-disabled), `_pipeline_lib.sh` bucket (`commercial_threshold`),
SKILL.md Flow 6 paint subsection (routing rules from item 7 + territory
warning), setup guides, CHANGELOG.
AC: paint smoke on canned SF3D GLB adds albedo+MR maps distinct from
input; item 7's original test list executed; refusal path (painting an
already-PBR trellis2 output → clear explanation) verified.

### R2.4 — item 22: multiview slate (PR 9 research + PR 10 wiring)
PR 9 (docs): update `docs/multiview-backend-research.md` candidate
table — remove/mark-DQ InstantMesh (CUDA) + OpenLRM (NC weights) with
citations; add MV-Adapter, Hunyuan3D-2mv, `edit.sh --angle`, TRELLIS.2
single-image baseline; mark adapters in `tools/multiview_backends/`
disqualified rather than deleting. Then run the benchmark per the
existing methodology with whichever R0.4/R0.5 spikes PASSED, judge
with mesh judge, fill the research doc, write the recommendation.
PR 10 (wiring, only if a backend clears the 6.5/10 rubric):
`multiview.sh` backend case + doctor + SKILL.md Flow 9 update + guides.
AC (PR 9): research doc "AWAITING DATA" status replaced with results
or with an evidence-backed deferral (spec item 22 failure-mode path).
AC (PR 10): end-to-end multiview smoke via the winning backend.

## Phase R3 — output polish (items 23–25)

### R3.1 — item 23: LODs + UV (PR 11)
Touch: `generate.sh` (`--lods`, `--reuv` + ordering enforcement),
gltfpack via Homebrew in setup guides, xatlas-python into
`pipeline-tools-env`, meta schema (`cleanup.lods`, `cleanup.reuv`),
engine-staging copy of LOD set (respect collision rules from v0.2),
SKILL.md Flow 2, doctor (binary presence checks), CHANGELOG.
AC: LOD smoke (3 descending-polycount GLBs, all watertight-checkable);
reuv-after-texture refusal message verified; occupancy improves on
low-occupancy fixture.

### R3.2 — item 24: texture post (PR 12; needs G4/G5 resolved)
Touch: `texture.sh` (`--engine`, `--mode pbr` + already-PBR refusal),
`_pipeline_lib.sh` buckets per G4/G5, doctor caches, SKILL.md Flow 6,
guides, CHANGELOG, short `docs/decision-marigold-bucket.md` (G4).
AC: engine parity fixture recorded; pbr smoke adds MR texture; both
gates' decisions quoted in docs.

### R3.3 — item 25: retopo (PR 13)
Touch: `generate.sh` (`--retopo quad` + before-paint ordering +
timeout config), setup guides (arm64 binary install + quarantine note),
doctor, meta schema (`cleanup.retopo`), SKILL.md, CHANGELOG.
AC: fixture → >80% quad faces (trimesh inspection), watertight
preserved, timeout path tested with a tiny timeout value.

## Phase R4 — release

- CHANGELOG roll-up; version bump per repo convention (v0.5.x tags for
  Tier 1 landings, v0.6 for the full round — follow existing CHANGELOG
  precedent); `make bundle`; tag + GitHub release; update
  `docs/index.html` landing links if new docs warrant it.
- Final doc sweep: `context/asset-pipeline-ai-context*.md` §04/§05/§08
  model tables reflect the new backends/buckets; spec/plan docs for
  this round marked shipped; watchlist section carried into the AI
  context doc's extension-points area.
- AC: `make verify` green; CI green on main; release notes list every
  item with its spec number.

## Sequencing summary

```
R0 (spikes) → R1.1 → R1.2 → R1.3 ┐
R0.1 PASS  → R1.4 → R1.5 (stop at G6)
R2.1 (independent after R0)      │
R2.2 after R1.1 + G3             │
R2.3 after R0.2                  │
R2.4 after R0.4/R0.5 + R1.3      │
R3.x after R1 lands              ┘ → R4
```

Parallel-safe: R2.1 anytime post-R0; R1.4 independent of R1.1–R1.3;
R3.1/R3.3 independent of R2. Keep each PR's `make regenerate` output
in that PR.

## Disk budget check (7 TB constraint)

New weights, upper bounds: TRELLIS.2 ~15 GB · Hunyuan3D-Paint MLX
~6 GB · Qwen-Image-Edit q8 ~40 GB · judge models 6–130 GB (tier
choice) · scorers ~5 GB · MV-Adapter+SDXL ~10 GB · SeedVR2 ~15 GB ·
klein 4B + ERNIE ~25 GB. Total worst case ≈ 250 GB — comfortably
inside budget; update `pipeline_doctor.py` dynamic disk threshold
accordingly (pattern from improvement-spec v3).
