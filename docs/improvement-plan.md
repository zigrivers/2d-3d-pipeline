# Pipeline quality-improvement implementation plan

**Status:** ready for execution · **Companion to:** [`improvement-spec.md`](improvement-spec.md)

This plan orders the fourteen items from the spec into shippable phases,
identifies dependencies between items, and calls out which work can ship
as standalone PRs vs. what must land together. Plan assumes solo
implementation; multi-person work can parallelise across the foundation
+ per-item PRs.

## Guiding principles for the plan

1. **Land foundation first.** Three cross-cutting changes (consolidated
   venv, single meta.json, meta_helper.py) enable every Tier 1 item.
   Without them, the Tier 1 items will re-litigate the sidecar race
   condition that MMR flagged.
2. **One PR per item once foundation is in place.** Each Tier 1 item is
   independently reviewable and bisectable. Avoid bundling.
3. **Skill changes ship with the script change that motivates them**,
   never separately. A code change that doesn't surface in `SKILL.md`
   is invisible to the user.
4. **Each PR runs `make verify` clean.** No exceptions for "doc-only"
   PRs — the parity tool catches stale embeds.
5. **No breaking changes mid-cycle.** All v0.3.x releases preserve v0.2
   `--json` contracts and CLI flag behaviour. New `quality` blocks are
   additive.

## Release targets

| Release | Contents | ETA |
|---|---|---|
| **v0.3.0** | Foundation (P0) + item 10 + items 2, 4, 6 | ~1 week |
| **v0.3.1** | Items 1, 3, 5 | ~3-4 days post-v0.3.0 |
| **v0.3.2** | Items 13, 14 | ~3-4 days post-v0.3.1 |
| **v0.3.3** | Items 9, 8 | ~3-4 days post-v0.3.2 |
| **v0.3.4** | Item 7 (Hunyuan3D-Paint, approved 2026-05-20) | ~3-5 days |
| **v0.4.0** | Item 12 (multi-view, research + impl) | ~3-day research, then ~1-2 weeks |
| **v0.5.0** | Item 11 (ComfyUI consistency mode) | ~1-2 weeks |

Cumulative Tier 1 work: ~3 weeks of focused effort. Tier 2: ~1 week
(all gates resolved 2026-05-20). Tier 3: ~3-4 weeks across both items.

---

# Phase 0 — Foundation (must land first)

These three PRs unlock everything else. Land them in order; do not
start Tier 1 work until P0 is on `main`.

## P0.1 — Consolidated `pipeline-tools-env` venv

**PR boundary:** standalone, foundation.

Scope:

- Add install steps for `~/3d-pipeline/pipeline-tools-env/` to both
  setup guides (laptop + studio).
- Install: `trimesh numpy scipy Pillow rembg[cpu] open_clip_torch
  torch tqdm requests`.
- Document model-cache locations: `~/3d-pipeline/models/{rembg,clip}/`.
- Set env vars in setup guides: `U2NET_HOME`, `OPEN_CLIP_CACHE_DIR`.

What changes:

- `docs/asset-pipeline-guide.html` (new install step ~30 lines via
  heredoc embed)
- `docs/asset-pipeline-guide-studio.html` (same)
- `docs/UPGRADES-laptop.md`, `docs/UPGRADES-studio.md` (note: new
  optional venv for v0.3 features)
- `CHANGELOG.md` (entry)

No script changes yet. No skill changes yet. This PR is **just
infrastructure** — the venv is unused until P0.3 + item 10 land.

**Verification:** `make verify` passes; manual install on both tiers
works; venv contains the expected packages.

## P0.2 — `meta_helper.py` (single per-asset metadata file)

**PR boundary:** standalone, foundation. Depends on P0.1.

Scope:

- New `scripts/meta_helper.py`:
  - `merge <path> --section <name> --data <inline-json>` — file-locked
    JSON merge into a section
  - `get <path> --section <name>` — read a section
  - `validate <path>` — schema validation against
    `scripts/meta_schema.json`
- New `scripts/meta_schema.json` — JSON schema for the per-asset
  meta.json structure
- `tools/_embed_lib.py::EMBEDS` updated for both new files
- Unit tests in `scripts/test_meta_helper.py` (use pytest if any tests
  exist; else simple bash test script)

No wrapper integration yet — that comes per-item.

**Verification:** unit tests; manual: concurrent merges from two
shell instances don't corrupt the file; `make verify` clean.

## P0.3 — `update_manifest.py --meta-json` flag

**PR boundary:** standalone, foundation. Depends on P0.2.

Scope:

- Add `--meta-json PATH` to `scripts/update_manifest.py`.
- Document the mapping from meta.json sections to manifest entry
  fields (`quality` block).
- Keep old per-field flags working — additive change.
- Test fixture: a meta.json with all sections present, fed to
  `update_manifest.py`, results in the expected manifest entry.

**Verification:** unit / integration test; CHANGELOG note;
backward-compat manual check on a v3 manifest.

---

# Phase 1 — Tier 1 items (parallel-safe after P0)

After P0 lands, the seven Tier 1 items can ship in any order. Below
is the recommended order, optimised for incremental UX wins.

## P1.1 — Item 10: Pipeline doctor + cache manager

**Why first:** highest user-facing leverage. Fixes the "first run
hangs on multi-GB download" problem before any new model-using
feature lands. Required by items 1 (rembg model) and 8 (CLIP model)
to provide their download progress UX.

**PR boundary:** standalone (depends on P0).

Scope:

- `scripts/pipeline_doctor.py` (CLI + checks)
- `scripts/pipeline_warmcache.py` (or `pipeline_doctor.py --warm-cache`)
- `scripts/model_manifest.json` (catalog of expected models + sha256)
- Documented commands in both setup guides
- New skill section: "Before any asset work, run pipeline_doctor.py
  --check all and pipeline_warmcache.py"
- `tools/_embed_lib.py::EMBEDS` for both scripts

**Verification:** Manual run on a clean install; manual run with a
partial download; manual run with a full install.

## P1.2 — Item 4: Input quality + format normalisation

**Why next:** required by item 1 (background-removal auto mode reads
input.background_uniformity) and unlocks every subsequent item that
writes to meta.json.

**PR boundary:** standalone (depends on P0).

Scope:

- New helper `check_and_normalize_input` in `scripts/_pipeline_lib.sh`
- New script `scripts/input_quality_check.py` (in `pipeline-tools-env`)
- `generate.sh` integration — call the helper after existence check
- meta.json `input` section, written via meta_helper.py
- Skill update: Flow 2 mentions the quality check + format
  normalisation
- HTML embeds regenerated; `make verify` clean

**Verification:** Test fixtures for low-res, animated GIF, WebP,
extreme aspect ratio. End-to-end generate.sh with each.

## P1.3 — Item 6: Cleanup report

**Why next:** smallest scope; instruments existing
`clean_asset.py`; writes the first quality data after generation.
Gives the user immediate "I can see what was wrong" feedback.

**PR boundary:** standalone (depends on P0).

Scope:

- Instrument `scripts/clean_asset.py` to count deltas per pass.
- Write `cleanup` section to meta.json via meta_helper.py.
- `generate.sh` surfaces the one-line summary.
- Skill update: Flow 2 explains the cleanup report.

**Verification:** Generate against a dirty input (SPAR3D), expect
non-zero counts. Generate clean, expect ≈ 0.

## P1.4 — Item 2: Watertight + scale sanity

**Why next:** the most-requested quality signal for printing. Builds
on item 6's sidecar discipline and the meta_helper.py infrastructure.

**PR boundary:** standalone (depends on P0, P1.3 for shared sidecar
patterns).

Scope:

- New script `scripts/mesh_quality_check.py` (in `pipeline-tools-env`)
- Called from `generate.sh` after `clean_asset.py`
- Called from `prepare_for_print.py` for the print path
- meta.json `quality.manifold` + `quality.scale` sections
- Skill update: Flow 2 + Flow 4 use translation map for output
- Translation map appears in `skill/SKILL.md` (cross-cutting principle 8
  from spec)

**Verification:** Known-good asset → watertight=true. Hand-broken
asset → watertight=false with hole count. Microscopic asset →
scale warning.

## P1.5 — Item 3: Texture quality validation

**Why next:** completes the "after generation, here's what's wrong"
trio (cleanup + manifold + textures). Same script venv, same
sidecar pattern.

**PR boundary:** standalone (depends on P0; can ship before or after
P1.4).

Scope:

- New `scripts/texture_quality_check.py` (in `pipeline-tools-env`)
- Called from `generate.sh` after `clean_asset.py`
- meta.json `quality.textures` section
- Skill update: Flow 2 + translation map entries for texture issues

**Verification:** Generate from a black image → expect
`flat-black-albedo`. TRELLIS Mac output → expect `no_textures`.

## P1.6 — Item 1: Conditional background removal

**Why next:** requires items 4 + 10 to be live. Once `rembg` and
its model are managed by `pipeline_doctor`, this becomes a clean
add.

**PR boundary:** standalone (depends on P0, P1.1, P1.2).

Scope:

- `scripts/rembg_preprocess.py` (in `pipeline-tools-env`)
- `process_input_image` helper in `_pipeline_lib.sh`
- `generate.sh` integration with `--bg-removal {auto,on,off}` flag
- meta.json `preprocessing.bg_removal` section
- Skill update: Flow 2 explains auto-mode behaviour + when to override

**Verification:** Clean studio image → skipped. Cluttered photo →
applied. Pure-black input → fallback. Skill text speaks plain
English.

## P1.7 — Item 5: Hero PNG + optional turntable GIF

**Why next:** the only Tier 1 item that's pure UX win, no engine
quality impact. Save it for the end of Tier 1 so it benefits from
the meta.json discipline established by the others.

**PR boundary:** standalone (depends on P0).

Scope:

- `scripts/turntable_render.py` (Blender headless)
- `generate.sh` integration with `--preview {none,png,gif}`
- Tier-aware default: `png` on laptop, `gif` on studio
- queue_worker.py forces `--preview none`
- meta.json `preview` section
- Skill update: surface the hero PNG path proactively

**Verification:** Generate on laptop → expect PNG only. Same on
studio → expect PNG + GIF. Queue job → expect neither.

## P1.8 — Item 13: UV + engine validation

**Why next:** depends on the same trimesh + Pillow infrastructure
as items 2 + 3 but adds more involved heuristics. Lands after the
simpler quality items so its complexity doesn't slow them down.

**PR boundary:** standalone (depends on P0, P1.4, P1.5).

Scope:

- `scripts/game_asset_check.py` (in `pipeline-tools-env`)
- Called from `generate.sh` after `clean_asset.py`
- meta.json `quality.uv` + `quality.engine` sections
- Skill update: Flow 2 surfaces engine-specific warnings (Unity =
  -Y normals, etc.) using translation map

**Verification:** Known-good SF3D output → reasonable UV counts.
Hand-broken (no UV) → flag. Mismatched normal handedness for the
detected engine → warning.

## P1.9 — Item 14: Print structural gates

**Why last in Tier 1:** depends on trimesh from P1.4 + scipy
(new dep added to `pipeline-tools-env`). Print path only; doesn't
affect game asset users.

**PR boundary:** standalone (depends on P0, P1.4). Add `scipy` to
the `pipeline-tools-env` requirements list as part of this PR
(small follow-up to P0.1).

Scope:

- `scripts/print_structural_check.py` (in `pipeline-tools-env`)
- Called from `prepare_for_print.py` after watertight check
- meta.json `print.structural` section
- Setup guide update: append `scipy` to the pipeline-tools-env
  install step
- Skill update: Flow 4 + Flow 5 use translation map for thin-wall /
  COM-tipping warnings

**Verification:** Known-printable asset → safe. Tall top-heavy →
tipping warning. Tiny figurine → thin-wall warning.

---

# Phase 2 — Tier 2 items

Tier 2 is sequential, not parallel — item 7 has a license-review
dependency and item 8 depends on item 10's cache manager.

## P2.1 — Item 9: Generator auto-selection hints

**Why first:** pure skill-text change, no code, low risk. Lands as
soon as someone has time.

**PR boundary:** standalone.

Scope:

- `skill/SKILL.md` updates: add the recommendation matrix; update
  Flow 2 polycount guidance to reference it
- HTML embed regen for both setup guides
- `make verify` clean

**Verification:** Manual walkthrough of 10 representative prompts
to confirm matrix routes correctly.

## P2.2 — Item 8: CLIP variant ranking + soft signal

**Why next:** depends on item 10 (CLIP weights managed by
`pipeline_doctor`). Don't ship CLIP without the doctor; first-run
download UX will hurt.

**PR boundary:** standalone (depends on P1.1).

Scope:

- `scripts/clip_score.py` (in `pipeline-tools-env`)
- `scripts/clip_calibration.json` (per-model bands; initial values
  approximated from research, refined post-launch)
- `concept.sh` integration with calibrated soft-signal output +
  `--rank` mode for `-n N`
- meta.json `clip` section
- Skill update: Flow 1 + Flow 3 explain per-model bands

**Verification:** Generate `-n 4` and expect ranked output. Vague
prompt → expect lower-band classification. Skill text speaks
percentile, not absolute number.

## P2.3 — Item 7: Hunyuan3D-Paint implementation

**Status: approved 2026-05-20.** License review complete; see
[`docs/license-review-hunyuan3d-paint.md`](license-review-hunyuan3d-paint.md).
Bucket: `commercial_threshold`.

**Why last in Tier 2:** largest install footprint (~5 GB model). Lands
after item 10 (pipeline-doctor) and item 3 (texture quality check) so
the new texture path benefits from both.

**PR boundary:** standalone. Depends on P1.1 (pipeline-doctor manages
the model cache) and P1.5 (texture-quality check runs over the painted
result).

Scope:

- Update `scripts/_pipeline_lib.sh::license_bucket_for_model` —
  change `hunyuan3d-paint` from `unclear_risky` to
  `commercial_threshold`.
- Remove the deliberate stub in `scripts/texture.sh --mode paint`;
  wire in the real Hunyuan3D-Paint invocation.
- New venv `~/3d-pipeline/hunyuan3d-paint-env/` with model cache at
  `~/3d-pipeline/models/hunyuan3d-paint/`.
- Add `hunyuan3d-paint` to `scripts/model_manifest.json` (managed by
  pipeline-doctor) including expected sha256s for the weights.
- Install steps added to both setup guides (heredoc-embedded).
- Skill update: `skill/SKILL.md` Flow 6 — replace "do not enable"
  warning with usage guidance + `commercial_threshold` bucket note.

**Verification:** Manual `texture.sh --mode paint -i <trellis-glb> --json`
end-to-end. Confirm output GLB has PBR textures; confirm item 3
texture-quality check runs cleanly on the result.

---

# Phase 3 — Tier 3 items

Both Tier 3 items are approved (2026-05-20). They remain large and
sequential; the recommendation is item 12 first (smaller surface area,
faster to ship), then item 11 (ComfyUI integration).

## P3.1 — Item 12: Multi-view reconstruction lane

**Status: approved 2026-05-20** with an explicit ~3-day backend
research phase.

**Why before P3.2:** smaller surface area; one new wrapper
(`multiview.sh`) vs. a second 2D backend.

**Dependencies:** Tier 1 complete (so multi-view outputs benefit
from the same quality checks).

**Sub-PRs:**

1. **P3.1a — Backend benchmark.** ~3 days. Run TRELLIS multi-view,
   InstantMesh, and OpenLRM against the same 4-reference-image input
   set (× 3 subject types). Score on geometric accuracy, texture
   fidelity, speed, install footprint, license. Output:
   `docs/multiview-backend-research.md` with recommendation.
2. **P3.1b — Backend decision PR.** Adopt the research doc's
   recommendation. If InstantMesh wins, file a parallel license
   review (mirrors P2.3) before code lands.
3. **P3.1c — `multiview.sh` wrapper.** New wrapper following the
   existing `generate.sh` shape; routes through the chosen backend;
   reuses `clean_asset.py` + Tier 1 quality checks.
4. **P3.1d — Skill update.** New Flow 9 in `skill/SKILL.md`. Trigger
   phrases: "I have multiple photos", "use these reference images",
   "reconstruct from these views". Always state the license bucket.
5. **P3.1e — Tests + docs.** Setup guide updates; CHANGELOG.

**Code PR boundary:** P3.1a + P3.1b are research / decision PRs;
P3.1c–e is the implementation, can be one PR or split.

## P3.2 — Item 11: LoRA + IP-Adapter consistency (Option A)

**Status: approved 2026-05-20** (Option A — add ComfyUI as second
2D backend; Option B is out of scope).

**Why last:** largest scope. Lands after item 12 ships so the team
has bandwidth.

**Dependencies:** none on other Tier 3 items. Independent from P3.1.

**Sub-PRs (format defined before parser implemented):**

1. **P3.2a — ComfyUI install.** New `~/3d-pipeline/comfyui-env/` venv
   (incompatible PyTorch build with pipeline-tools-env). Install
   steps in both setup guides. Model weights via pipeline-doctor.
2. **P3.2b — Consistency pack format (defined first).** Document
   `docs/consistency-pack-format.md`: pack manifest schema, expected
   contents (reference images, optional LoRA, optional IP-Adapter
   ref). Includes JSON Schema file so the parser in P3.2c validates
   against the same versioned contract.
3. **P3.2c — `--backend comfyui` flag in `concept.sh`.** Routes to
   ComfyUI workflow JSON; reads + validates consistency pack against
   P3.2b's schema; runs the workflow headlessly; collects output PNG.
4. **P3.2d — Reference workflow + tests.** Ship a reference
   consistency-pack and the ComfyUI workflow JSON that produces
   identity-locked outputs from it.
5. **P3.2e — Skill update.** Flow 1 + Flow 3 in `SKILL.md`: how to
   recognise consistency need; how to pass `--backend comfyui
   --consistency-pack PATH`; license-bucket disclosure rules.

---

# What can ship standalone vs. must land together

## Standalone (any order after their dependencies)

- P1.1 (item 10) — pipeline doctor
- P1.2 (item 4) — input quality
- P1.3 (item 6) — cleanup report
- P1.4 (item 2) — watertight
- P1.5 (item 3) — texture quality
- P1.7 (item 5) — preview
- P2.1 (item 9) — skill text only

## Must land together / sequential dependencies

- **P0.1 + P0.2 + P0.3** — the foundation. P0.2 depends on P0.1;
  P0.3 depends on P0.2.
- **P1.6 (item 1)** depends on P1.1 (rembg model cached by doctor)
  and P1.2 (input.background_uniformity signal).
- **P1.8 (item 13)** depends on P1.4 + P1.5 (shared sidecar
  discipline).
- **P1.9 (item 14)** depends on P1.4 (trimesh in pipeline-tools-env)
  and follows P0.1 with `scipy` addition.
- **P2.2 (item 8)** depends on P1.1 (CLIP model managed by doctor).

## Sequential by external dependency

- **P3.1a (item 12 backend research)** must complete before P3.1c
  (multi-view wrapper). If InstantMesh wins the benchmark, file a
  parallel license review before P3.1c lands.

(P2.3 and the Tier 3 user-decision gates have been resolved as of
2026-05-20.)

---

# Risk register

| Risk | Mitigation |
|---|---|
| Meta.json schema churn during Tier 1 rollout breaks already-merged manifest entries | `schema_version` field in meta.json; `update_manifest.py` ignores unknown sections |
| pipeline-tools-env install fails on a user's laptop (Torch wheels) | Setup guides include a known-good `pip install` invocation pinning major versions |
| Item 1's auto-mode misclassifies a real input and fails over to original silently | The fallback is logged in meta.json (`bg_removal.fallback="..."`); skill surfaces if user reports off output |
| Item 14's wall-thickness heuristic produces false positives | Frame skill output as advisory ("may fail to print"), not blocking |
| First-run model download fills disk | Item 10 preflight check + `--warm-cache` workflow |
| ComfyUI integration becomes a maintenance burden | Scope the surface tightly: ComfyUI is for consistency mode only; mflux remains the default for one-off generations. Document that two-backend split clearly in the skill so users don't drift |
| InstantMesh wins multi-view benchmark but its license review fails | Pre-commit to TRELLIS multi-view (`non_commercial`, already familiar) as the fallback so P3.1c isn't blocked |
| ComfyUI venv (~10 GB) on laptop tier is unworkable | Mark consistency mode as studio-recommended in the skill; provide `--backend mflux` override that proceeds without consistency (status quo) |

---

# Rollback / disable strategy

Every Tier 1 quality check ships with a disable flag:

- Item 1: `--bg-removal off` or `defaults.bg_removal_mode=off`
- Item 2: `--skip-quality-check`
- Item 3: shares item 2's flag
- Item 4: cannot disable (input check is the bare minimum); only
  the format-normalisation step can fall back if Pillow fails
- Item 5: `--preview none`
- Item 6: cannot disable (instrumentation is part of cleanup)
- Item 8: `--no-clip-check` or `defaults.clip_check_default=false`
- Item 10: not user-facing in normal flow; runs only on demand
- Item 13: shares item 2's flag
- Item 14: shares item 2's flag

Catastrophic regression on any Tier 1 item: revert the item's PR.
The meta.json sections it owned become absent; the wrapper continues
without them; nothing downstream breaks because `update_manifest.py
--meta-json` tolerates missing sections.

---

# Acceptance criteria for v0.3.0

- [ ] All P0 PRs landed
- [ ] P1.1 (pipeline doctor) landed
- [ ] P1.2 (input quality) landed
- [ ] P1.3 (cleanup report) landed
- [ ] P1.4 (watertight) landed
- [ ] All existing v0.2 wrappers pass their existing tests
- [ ] `make verify` clean
- [ ] `make bundle` produces a valid zip
- [ ] Both setup guides updated; embeds in sync
- [ ] `docs/UPGRADES-{laptop,studio}.md` document the new venv + new
      quality fields
- [ ] CHANGELOG.md entry
- [ ] Annotated git tag v0.3.0 + GitHub release with bundle attached
- [ ] Skill updated; all translation-map entries used in new outputs
- [ ] `pipeline_doctor.py --check all` on a fresh install succeeds

# Acceptance criteria for v0.3.x feature releases

Each subsequent v0.3.x release passes the same gates plus:

- [ ] The item's failure modes verified manually
- [ ] meta.json schema validation passes for new sections
- [ ] No regressions in any prior v0.3.x item's behaviour

---

*End of implementation plan.*
