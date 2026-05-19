# 2d-3d-pipeline

Documentation and canonical scripts for Ken's local, Mac-native 2D/3D/print
asset pipeline. This repo is **not** a working installation of the pipeline
itself — it's the source of truth for the docs and wrapper scripts that drive
it. The actual tools (`mflux`, `SF3D`, `TRELLIS.2`, Blender) live in their own
venvs under `~/3d-pipeline/`, and the pipeline is invoked from Claude Code via
the `asset-pipeline` skill installed in `~/.claude/skills/asset-pipeline/`.

## Three audiences, three docs

| Audience               | Canonical doc                                       |
| ---------------------- | --------------------------------------------------- |
| End user (Ken)         | [`docs/asset-pipeline-guide.html`](docs/asset-pipeline-guide.html) — setup, copy-paste install, troubleshooting |
| AI assistants          | [`context/asset-pipeline-ai-context.md`](context/asset-pipeline-ai-context.md) — markdown form for ingestion; HTML mirror lives alongside it |
| Maintainer (also Ken)  | This README + [`CONVENTIONS.md`](CONVENTIONS.md) + [`CHANGELOG.md`](CHANGELOG.md) |

## Scripts are canonical; the HTML embeds them

The wrapper scripts in [`/scripts`](scripts/) and the skill files in
[`/skill`](skill/) are the **source of truth**. The user-facing HTML guide
embeds these files byte-for-byte via `cat > path << 'PIPELINE_EOF'` heredoc
blocks so that a user can copy-paste the entire install. **When a script
changes, the HTML must be regenerated.** See `CONVENTIONS.md` for the
regeneration procedure.

## Layout

```
docs/      User-facing HTML guides
context/   AI-facing context docs (HTML + markdown)
scripts/   Canonical bash wrappers and Python helpers (_pipeline_lib.sh,
           concept.sh, generate.sh, print.sh, clean_asset.py,
           prepare_for_print.py, migrate_assets.sh)
skill/     SKILL.md + scripts/update_manifest.py (deployed to
           ~/.claude/skills/asset-pipeline/)
dist/      Generated bundle zips (gitignored)
```

## Working in this repo

See [`CONVENTIONS.md`](CONVENTIONS.md) for naming, style, the
canonical-vs-embedded rule, and the visual register used across the docs.
