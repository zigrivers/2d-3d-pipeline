# Changelog

Dated entries for significant changes to the docs, scripts, or skill.

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
