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
