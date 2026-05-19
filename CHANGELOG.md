# Changelog

Dated entries for significant changes to the docs, scripts, or skill.

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
