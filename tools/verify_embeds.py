#!/usr/bin/env python3
"""Check that every embedded heredoc block in the HTML guide matches the
canonical file in /scripts or /skill. Exit 0 on match, 1 on drift."""
from __future__ import annotations

import sys
from pathlib import Path

from _embed_lib import EMBEDS, GUIDE_PATH, PROJECT_ROOT, expected_escaped_body, parse_blocks


def main() -> int:
    html_text = GUIDE_PATH.read_text()
    blocks = parse_blocks(html_text)

    expected_paths = set(EMBEDS.values())
    found_paths = set(blocks.keys())

    missing = expected_paths - found_paths
    extra = found_paths - expected_paths
    drift: list[tuple[str, str]] = []

    for rel, embedded_path in EMBEDS.items():
        if embedded_path not in blocks:
            continue
        expected = expected_escaped_body(PROJECT_ROOT / rel)
        actual = blocks[embedded_path]
        if expected != actual:
            drift.append((rel, embedded_path))

    if not (missing or extra or drift):
        print(f"OK: all {len(EMBEDS)} embedded blocks match canonical sources")
        return 0

    if missing:
        print(f"MISSING blocks in HTML (no <pre>cat > ...</pre> for):")
        for p in sorted(missing):
            print(f"  - {p}")
    if extra:
        print(f"EXTRA blocks in HTML (not in EMBEDS map):")
        for p in sorted(extra):
            print(f"  - {p}")
    if drift:
        print(f"DRIFT: HTML embed differs from canonical file:")
        for rel, embedded in drift:
            print(f"  - {rel} -> {embedded}")
        print("\nRun `make regenerate` (or `python3 tools/regenerate_embeds.py`) to fix.")

    return 1


if __name__ == "__main__":
    sys.exit(main())
