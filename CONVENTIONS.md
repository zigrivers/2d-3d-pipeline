# Conventions

Living rules for how this repo is organized and edited. When a new convention
emerges, write it here so the next session inherits it.

## The canonical-vs-embedded rule

**Scripts in `/scripts` and `/skill` are canonical. The HTML guide embeds
them.** Never edit a script *inside* an HTML file — edit the file in
`/scripts` or `/skill`, then regenerate the embedded block.

### How to regenerate an embedded block

The HTML guide embeds each script using a heredoc pattern that survives
copy-paste into a terminal:

```
<pre>cat > <target-path> << 'PIPELINE_EOF'
<html.escape(file_contents, quote=True)>
PIPELINE_EOF</pre>
```

- Delimiter: `PIPELINE_EOF` (chosen because it's unlikely to appear in
  pipeline source). Do not change without auditing every embed.
- Escape: Python `html.escape(text, quote=True)`. This escapes `&`, `<`, `>`,
  `"`, and `'` (as `&#x27;`). Non-ASCII unicode passes through unescaped.
- Heredoc opener line (`cat > ... << 'PIPELINE_EOF'`) is intentionally
  embedded **unescaped** in the `<pre>` block — `<<` is safe in HTML because
  `<` is only parsed as a tag when followed by a letter or `/`.
- The closing `PIPELINE_EOF` must sit on its own line directly followed by
  `</pre>` (or `</pre></div>` for Python files — both forms appear in the
  current HTML and are equivalent).

Regeneration is automated via `tools/regenerate_embeds.py` (or `make
regenerate`). Drift checking is `tools/verify_embeds.py` (or `make verify`).
The shared mapping of canonical-file → embedded-path lives in
`tools/_embed_lib.py` — update it there when you add a new script worth
embedding.

A pre-commit hook in `.githooks/pre-commit` refuses commits that touch
`/scripts` or `/skill` without a matching HTML regeneration. Opt in once
per clone with `make install-hooks` (which sets `core.hooksPath`).

## CI — pipeline-doctor

`.github/workflows/pipeline-doctor.yml` runs on every PR and `main` push
that touches `scripts/**` or `tools/_embed_lib.py`. It runs two checks:

- `--check structure` — validates the catalog itself: EMBEDS source files
  exist, every venv and model references a declared feature_set, every model's
  feature_set has at least one venv that covers it, every wrappers entry is an
  executable file in `scripts/`, and every `scripts/*.sh` is either in
  `wrappers` or `internal_scripts`. Fails the job on any critical finding.
- `--check wrappers` — runs `<wrapper> --help` for each declared wrapper and
  fails the job if any wrapper's status is not `ok` (catches missing wrappers,
  non-zero exits, timeouts, and OS errors).

The workflow posts an idempotent JSON report as a PR comment (updated in
place on subsequent pushes). It does **not** install models or venvs; for
runtime checks run `pipeline_doctor.py --check all` locally.

If the workflow fails: check the PR comment for the specific finding, fix
the manifest or script, and push again. See `docs/spec-pipeline-doctor-ci.md`
for the full design rationale.

## Visual register

### User-facing HTML guides (`/docs`)

Catppuccin Mocha palette. Polished, marketing-adjacent, sidebar+main grid
layout. JetBrains Mono everywhere.

Palette (Catppuccin Mocha):

| Role          | Hex       | Token         |
| ------------- | --------- | ------------- |
| base          | `#1e1e2e` | background    |
| mantle        | `#181825` | secondary bg  |
| crust         | `#11111b` | code bg       |
| surface0      | `#313244` | borders       |
| text          | `#cdd6f4` | body          |
| subtext1      | `#bac2de` | secondary     |
| subtext0      | `#a6adc8` | tertiary      |
| mauve         | `#cba6f7` | accents       |
| pink          | `#f5c2e7` | highlights    |
| green         | `#a6e3a1` | success/run   |
| yellow        | `#f9e2af` | warning       |
| red           | `#f38ba8` | error         |
| sky           | `#89dceb` | links         |

Layout: fixed left sidebar nav, main content column, sticky section headers.
Code blocks use a dark crust background with a coloured language chip.

### AI-facing context docs (`/context`)

Same Catppuccin palette, **denser** layout, **less marketing**: no hero
sections, no decorative gradients, fewer collapsible affordances. Information
density beats visual breathing room. Markdown is the primary form; the HTML
mirror is for browsing convenience.

## Per-tier docs (v0.2)

The user runs the pipeline on two hardware tiers (`laptop` and `studio`),
both Apple Silicon. Scripts and the Claude Code skill are **singular** —
they read `~/3d-pipeline/.config` to learn which tier they're on. Docs
are **dual** — one set for each tier.

| Concern             | Singular         | Dual                                     |
| ------------------- | ---------------- | ---------------------------------------- |
| Scripts             | `/scripts`       |                                          |
| Skill               | `/skill`         |                                          |
| Tooling             | `/tools`         |                                          |
| Setup guide         |                  | `docs/asset-pipeline-guide{,-studio}.html` |
| AI context          |                  | `context/asset-pipeline-ai-context{,-studio}.{md,html}` |
| UPGRADES summary    |                  | `docs/UPGRADES-{laptop,studio}.md`       |

Filename rule: the laptop docs keep their original (unsuffixed) filenames
so external links stay valid. The studio docs use the `-studio` suffix
on the same stem.

Both setup guides embed the **same canonical scripts** byte-for-byte via
the heredoc blocks documented in this file. `tools/_embed_lib.py`'s
`GUIDE_PATHS` list contains both; `make regenerate` and `make verify`
iterate over both automatically.

Both AI-context md/html pairs are enforced by
`tools/check_context_parity.py`'s `PAIRS` list. Same rules per pair: H2
sections in order, callout counts per type.

Each setup guide is **independently complete**. A user on either tier
should never have to read the other tier's doc to install or run. The
guides differ only in:

- Hero / title strings.
- A `~/3d-pipeline/.config` setup step (studio only — laptop tier uses
  the default `laptop` value).
- Workflow sections for the queue (W12, studio only) and the full-suite
  bake-off (W11, studio only).
- A small pointer in each hero to the other-tier guide.

All other content (install steps, troubleshooting, reference) is
duplicated. Duplication is acceptable; ambiguity is not.

## The AI context: markdown is canonical for content

`context/asset-pipeline-ai-context.md` is the canonical source for the AI
context document's **content**. `context/asset-pipeline-ai-context.html` is
a polished mirror with additional hand-authored semantics that the markdown
does not encode (custom side-by-side `<div class="tradeoff">` grids,
section-number labels, the sticky sidebar nav).

Because the relationship is asymmetric, the HTML is **not** auto-generated
from the markdown today. Instead, `tools/check_context_parity.py` (wired
into `make verify` and the pre-commit hook) enforces structural parity:

- Every H2 section in the markdown (after stripping the `NN ·` prefix and
  inline-code backticks) appears as an `<h2>` in the HTML, in the same order.
- Callout counts match: `> **🧠 Rationale — ...**` blocks in markdown have
  matching `class="callout-rationale"` elements in the HTML (and similarly
  for `🔵`/Context, `🟢`/Decision, `🔴`/Gotcha, `⚠️`/Warn).

When you edit either file, run `make verify` before committing. The
pre-commit hook will block a commit that touches the AI context files
without keeping them in parity.

Promoting this to a full markdown→HTML generator (with extensions for the
custom block types) is a future-work item — not done today because the
HTML's polish exceeds what a stock converter produces, and a faithful
generator is a real project. See `tools/check_context_parity.py` for the
exact rules currently enforced.

## When to use HTML vs markdown

| Use HTML for                            | Use markdown for                       |
| --------------------------------------- | -------------------------------------- |
| Human-facing setup and workflow guides  | AI context docs (ingestion-friendly)   |
| Anything in `/docs`                     | Internal docs (README, CHANGELOG, etc.)|
| Embedded copy-paste install blocks      | Skill files (`SKILL.md`)               |

When in doubt: if a human is going to read it in a browser, HTML; if an LLM
or a future maintainer is going to read it in a terminal, markdown.

## File naming

- `kebab-case` for all docs.
- User-facing guides: `asset-pipeline-<topic>.html` (e.g.,
  `asset-pipeline-guide.html`, `asset-pipeline-workflows.html`).
- AI context: `asset-pipeline-ai-context.{html,md}` (HTML and md kept in
  sync; markdown is canonical, HTML is rendered from it manually for now).
- Scripts: `snake_case.{sh,py}` for canonical scripts (matches the names the
  pipeline already uses in `~/3d-pipeline/workspace/`).
- Library files prefixed with `_` (e.g., `_pipeline_lib.sh`).

## Versioning docs

Currently no formal versioning. Recommendation: add a small footer to each
HTML guide of the form `Last updated: YYYY-MM-DD` so users can tell whether
their local copy is current. Significant doc changes get a dated entry in
`CHANGELOG.md` with a short summary.

When a script's behaviour changes in a user-visible way, bump the "Last
updated" date on the guide and note the change in the changelog.
