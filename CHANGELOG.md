# Changelog

Dated entries for significant changes to the docs, scripts, or skill.

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
