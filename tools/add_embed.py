#!/usr/bin/env python3
"""Insert a new `<details>` heredoc block into both HTML setup guides.

Run this once per new canonical /scripts file *before* running
`make regenerate`:

    python3 tools/add_embed.py scripts/meta_helper.py "Per-asset meta.json merger"

The script:
  - Confirms the canonical file exists at the given path.
  - Appends an entry to `tools/_embed_lib.py::EMBEDS`.
  - Inserts an empty `<details class="script-detail">` block in both
    `docs/asset-pipeline-guide.html` and `-studio.html`, anchored just
    before the `<div class="callout callout-tip">` block in the
    scripts-install step.
  - Leaves the heredoc body empty; `make regenerate` fills it.

After this script: run `make regenerate && make verify`.

This is a maintainer tool. It lives in /tools/ (not /scripts/) so it
isn't itself subject to the canonical-vs-embedded rule.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMBED_LIB = PROJECT_ROOT / "tools" / "_embed_lib.py"
GUIDES = [
    PROJECT_ROOT / "docs" / "asset-pipeline-guide.html",
    PROJECT_ROOT / "docs" / "asset-pipeline-guide-studio.html",
]

# Anchor: insert new <details> blocks right before this "What each script
# does" callout — it sits at the very end of the scripts-install step in
# both guides. Specific enough to not collide with workflow callouts.
ANCHOR = '''          <div class="callout callout-tip">
            <div class="callout-label">What each script does</div>'''


def update_embed_lib(canonical_rel: str, embedded_path: str) -> None:
    """Append a new entry to the EMBEDS dict in _embed_lib.py."""
    text = EMBED_LIB.read_text()
    if f'"{canonical_rel}":' in text:
        print(f"[add_embed] EMBEDS already has {canonical_rel}; skipping registry update.")
        return
    # Find the closing `}` of EMBEDS — it's the line containing only `}` after
    # the last `"skill/scripts/update_manifest.py": ...` entry, or simpler:
    # the first standalone `}` after `EMBEDS: dict[str, str] = {`.
    pat = re.compile(r"(EMBEDS: dict\[str, str\] = \{[\s\S]*?)(\n\})", re.MULTILINE)
    m = pat.search(text)
    if not m:
        raise SystemExit("Could not locate EMBEDS dict in _embed_lib.py")
    # Find the longest existing key for alignment
    keys = re.findall(r'"([^"]+)":\s+"', m.group(1))
    max_key_len = max((len(k) for k in keys), default=20)
    width = max(max_key_len, len(canonical_rel))
    new_entry = f'    "{canonical_rel}":{" " * (width - len(canonical_rel) + 1)}"{embedded_path}",'
    new_text = text[: m.end(1)] + "\n" + new_entry + text[m.end(1):]
    EMBED_LIB.write_text(new_text)
    print(f"[add_embed] added {canonical_rel} to EMBEDS")


def block_template(embedded_path: str, basename: str, description: str, executable: bool) -> str:
    """Build a <details> block with an empty body. make regenerate fills it."""
    chmod_line = f"\nchmod +x {embedded_path}" if executable else ""
    return (
        '            <details class="script-detail">\n'
        '              <summary class="script-summary">\n'
        f'                <code>{basename}</code>\n'
        f'                <span class="script-summary-desc">{description}</span>\n'
        '              </summary>\n'
        '              <div class="code-block"><div class="code-header"><span class="code-lang">bash &middot; paste into terminal</span><button class="copy-btn">Copy</button></div>'
        # NOTE: the heredoc opener line uses LITERAL `>` / `<` — they're safe
        # in <pre> blocks (CONVENTIONS.md). Only the body gets html-escaped,
        # and `make regenerate` handles that.
        # The TWO `\n` between the opener line and the closing PIPELINE_EOF
        # are required so BLOCK_RE in tools/_embed_lib.py matches the empty
        # body: opener consumes one `\n`, body matches '', closer needs
        # `\nPIPELINE_EOF`. With only one `\n`, the regex never matches and
        # `make regenerate` silently leaves the body empty.
        f"<pre>cat > {embedded_path} << 'PIPELINE_EOF'\n"
        f"\nPIPELINE_EOF{chmod_line}</pre></div>\n"
        '            </details>\n'
    )


def insert_into_guide(guide: Path, block: str) -> bool:
    text = guide.read_text()
    if ANCHOR not in text:
        print(f"[add_embed] WARN: anchor not found in {guide.name}; skipping", file=sys.stderr)
        return False
    # Insert block immediately before the anchor (preserving a blank line).
    new_text = text.replace(ANCHOR, block + "\n" + ANCHOR, 1)
    guide.write_text(new_text)
    print(f"[add_embed] inserted block into {guide.name}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("canonical", help="Path relative to repo root, e.g. scripts/meta_helper.py")
    ap.add_argument("description", help="Short summary text for the <details> summary line")
    ap.add_argument(
        "--embedded-path",
        help="Override target path (default: ~/3d-pipeline/workspace/<basename>)",
        default=None,
    )
    ap.add_argument(
        "--executable",
        action="store_true",
        help="Append `chmod +x` after the heredoc (for *.sh files).",
    )
    args = ap.parse_args()

    canonical = PROJECT_ROOT / args.canonical
    if not canonical.exists():
        print(f"ERROR: canonical file not found: {args.canonical}", file=sys.stderr)
        return 1

    basename = canonical.name
    embedded_path = args.embedded_path or f"~/3d-pipeline/workspace/{basename}"

    # Auto-detect executable based on extension if --executable wasn't passed
    executable = args.executable or canonical.suffix == ".sh"

    update_embed_lib(args.canonical, embedded_path)
    block = block_template(embedded_path, basename, args.description, executable)
    for guide in GUIDES:
        insert_into_guide(guide, block)

    print(
        "\n[add_embed] done. Next: run `make regenerate && make verify`."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
