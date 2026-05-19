#!/usr/bin/env python3
"""Rewrite every `<pre>cat > ... << 'PIPELINE_EOF' ... PIPELINE_EOF</pre>`
block in each user-facing HTML guide so its body matches the corresponding
canonical file in /scripts or /skill. Writes in place; idempotent.

v0.2 — iterates over both `docs/asset-pipeline-guide.html` (laptop) and
`docs/asset-pipeline-guide-studio.html` (studio). A guide that doesn't
exist yet is skipped (relevant during the Phase 11 bootstrap)."""
from __future__ import annotations

import sys
from pathlib import Path

from _embed_lib import BLOCK_RE, EMBEDS, GUIDE_PATHS, PROJECT_ROOT, expected_escaped_body


def _regen_one(guide_path: Path, expected: dict[str, str]) -> tuple[int, int]:
    if not guide_path.exists():
        print(f"SKIP: guide not present: {guide_path.relative_to(PROJECT_ROOT)}")
        return 0, 0
    html_text = guide_path.read_text()
    changed: list[str] = []
    unchanged: list[str] = []

    def replace(match):
        path = match.group("path")
        if path not in expected:
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
        guide_path.write_text(new_html)
        print(f"[{guide_path.name}] regenerated {len(changed)} block(s):")
        for p in changed:
            print(f"  - {p}")
    if unchanged:
        print(f"[{guide_path.name}] unchanged: {len(unchanged)} block(s) already in sync")
    if not changed and not unchanged:
        print(f"[{guide_path.name}] no embed blocks present")
    return len(changed), len(unchanged)


def main() -> int:
    expected: dict[str, str] = {}
    for rel, embedded_path in EMBEDS.items():
        canonical = PROJECT_ROOT / rel
        if not canonical.exists():
            print(f"ERROR: canonical file missing: {rel}", file=sys.stderr)
            return 1
        expected[embedded_path] = expected_escaped_body(canonical)

    total_changed = 0
    total_unchanged = 0
    for guide in GUIDE_PATHS:
        c, u = _regen_one(guide, expected)
        total_changed += c
        total_unchanged += u
    if not total_changed:
        print("No changes needed across all guides.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
