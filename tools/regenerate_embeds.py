#!/usr/bin/env python3
"""Rewrite every `<pre>cat > ... << 'PIPELINE_EOF' ... PIPELINE_EOF</pre>`
block in the HTML guide so its body matches the corresponding canonical file
in /scripts or /skill. Writes in place; idempotent."""
from __future__ import annotations

import sys
from pathlib import Path

from _embed_lib import BLOCK_RE, EMBEDS, GUIDE_PATH, PROJECT_ROOT, expected_escaped_body


def main() -> int:
    html_text = GUIDE_PATH.read_text()

    # Build a reverse lookup: embedded path -> expected escaped body
    expected: dict[str, str] = {}
    for rel, embedded_path in EMBEDS.items():
        canonical = PROJECT_ROOT / rel
        if not canonical.exists():
            print(f"ERROR: canonical file missing: {rel}", file=sys.stderr)
            return 1
        expected[embedded_path] = expected_escaped_body(canonical)

    changed: list[str] = []
    unchanged: list[str] = []

    def replace(match):
        path = match.group("path")
        if path not in expected:
            # Unknown block — leave it alone but warn.
            print(f"WARN: HTML has block for {path} but not in EMBEDS map", file=sys.stderr)
            return match.group(0)
        new_body = expected[path]
        old_body = match.group("body")
        if new_body == old_body:
            unchanged.append(path)
        else:
            changed.append(path)
        return f"{match.group(1)}{new_body}{match.group(4)}"

    new_html = BLOCK_RE.sub(replace, html_text)

    if changed:
        GUIDE_PATH.write_text(new_html)
        print(f"Regenerated {len(changed)} block(s):")
        for p in changed:
            print(f"  - {p}")
    if unchanged:
        print(f"Unchanged: {len(unchanged)} block(s) already in sync")
    if not changed:
        print("No changes needed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
