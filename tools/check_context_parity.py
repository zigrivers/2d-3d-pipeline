#!/usr/bin/env python3
"""Check structural parity between the AI context markdown and its HTML mirror.

The markdown (`context/asset-pipeline-ai-context.md`) is the canonical source
for content. The HTML mirror has additional hand-authored polish (custom
tradeoff grids, section wrappers) that we don't auto-generate yet — but we
can at least detect drift in the parts that *should* match:

  1. Top-level sections (H2 headings) appear in the same order in both files.
  2. Callout count parity: every `> **<emoji> Rationale|Context|...** ` in the
     markdown should correspond to a `class="callout-<type>"` in the HTML.

Exit 0 on parity, 1 on drift.
"""
from __future__ import annotations

import html as html_lib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "context" / "asset-pipeline-ai-context.md"
HTML = ROOT / "context" / "asset-pipeline-ai-context.html"

# Emoji prefix in the markdown callout title -> CSS class suffix in the HTML
CALLOUT_MAP = {
    "🧠": "rationale",
    "🔵": "context",
    "🟢": "decision",
    "🔴": "gotcha",
    "⚠️": "warn",
    "⚠": "warn",
}
KNOWN_CALLOUT_TYPES = set(CALLOUT_MAP.values())

# Markdown H2 form: "## 00 · Audience & purpose"  -> strip "NN · " prefix
H2_RE = re.compile(r"^## (?:\d+ · )?(.+)$", re.MULTILINE)
CALLOUT_RE = re.compile(r"^> \*\*([^\s*])([^*]*)\*\*", re.MULTILINE)
HTML_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.DOTALL)
HTML_CALLOUT_RE = re.compile(r'class="[^"]*\bcallout-([a-z]+)\b')


def normalize(s: str) -> str:
    # Strip markdown backticks and HTML tags so md `\`x\`` matches HTML <code>x</code>.
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("`", "")
    return html_lib.unescape(re.sub(r"\s+", " ", s).strip())


# Markdown sections that have no HTML <h2> counterpart (the HTML sidebar serves
# the role of TOC, so the "Table of contents" md section is intentionally absent).
MD_SECTIONS_WITHOUT_HTML_H2 = {"Table of contents"}


def main() -> int:
    if not MD.exists() or not HTML.exists():
        print(f"ERROR: missing {MD if not MD.exists() else HTML}")
        return 1

    md_text = MD.read_text()
    html_text = HTML.read_text()

    md_h2 = [
        h for h in (normalize(h) for h in H2_RE.findall(md_text))
        if h not in MD_SECTIONS_WITHOUT_HTML_H2
    ]
    html_h2 = [normalize(h) for h in HTML_H2_RE.findall(html_text)]

    md_callouts: dict[str, int] = {}
    for emoji, _rest in CALLOUT_RE.findall(md_text):
        cls = CALLOUT_MAP.get(emoji)
        if cls:
            md_callouts[cls] = md_callouts.get(cls, 0) + 1

    html_callouts: dict[str, int] = {}
    for cls in HTML_CALLOUT_RE.findall(html_text):
        if cls in KNOWN_CALLOUT_TYPES:
            html_callouts[cls] = html_callouts.get(cls, 0) + 1

    errors: list[str] = []

    # 1. Section order: md H2s should appear in the HTML's H2s in the same order.
    #    HTML may have additional H2s for sub-grouping, but every md H2 should be present and ordered.
    missing = [h for h in md_h2 if h not in html_h2]
    if missing:
        errors.append(f"MD sections missing from HTML ({len(missing)}):")
        for h in missing:
            errors.append(f"  - {h}")

    # Check ordering of the md sections within the HTML's H2 list
    md_indices = [html_h2.index(h) for h in md_h2 if h in html_h2]
    if md_indices != sorted(md_indices):
        errors.append("MD sections appear in a different order in the HTML.")

    # 2. Callout count parity
    for cls in set(md_callouts) | set(html_callouts):
        m = md_callouts.get(cls, 0)
        h = html_callouts.get(cls, 0)
        if m != h:
            errors.append(f"Callout drift: callout-{cls} appears {m}x in MD, {h}x in HTML")

    if errors:
        for e in errors:
            print(e)
        return 1

    print(
        f"OK: md and HTML in parity ({len(md_h2)} sections, "
        f"{sum(md_callouts.values())} callouts)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
