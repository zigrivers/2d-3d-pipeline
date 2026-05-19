#!/usr/bin/env python3
"""Check that every embedded heredoc block in each HTML guide matches the
canonical file in /scripts or /skill. Exit 0 on match, 1 on drift.

v0.2 — iterates over both guides; a guide that doesn't exist is skipped."""
from __future__ import annotations

import sys
from pathlib import Path

from _embed_lib import EMBEDS, GUIDE_PATHS, PROJECT_ROOT, expected_escaped_body, parse_blocks


def _check_one(guide_path: Path) -> tuple[int, list[str], bool]:
    """Return (in_sync_count, error_lines, was_skipped). error_lines is
    empty on clean. was_skipped=True when the guide isn't present yet
    (relevant during Phase 11 bootstrap)."""
    if not guide_path.exists():
        return 0, [], True
    html_text = guide_path.read_text()
    blocks = parse_blocks(html_text)

    expected_paths = set(EMBEDS.values())
    found_paths = set(blocks.keys())

    missing = expected_paths - found_paths
    extra = found_paths - expected_paths
    drift: list[tuple[str, str]] = []
    in_sync = 0

    for rel, embedded_path in EMBEDS.items():
        if embedded_path not in blocks:
            continue
        expected = expected_escaped_body(PROJECT_ROOT / rel)
        actual = blocks[embedded_path]
        if expected != actual:
            drift.append((rel, embedded_path))
        else:
            in_sync += 1

    errors: list[str] = []
    if missing:
        errors.append(f"[{guide_path.name}] MISSING blocks (no <pre>cat > ...</pre>):")
        for p in sorted(missing):
            errors.append(f"  - {p}")
    if extra:
        errors.append(f"[{guide_path.name}] EXTRA blocks not in EMBEDS map:")
        for p in sorted(extra):
            errors.append(f"  - {p}")
    if drift:
        errors.append(f"[{guide_path.name}] DRIFT: embed differs from canonical:")
        for rel, embedded in drift:
            errors.append(f"  - {rel} -> {embedded}")
    return in_sync, errors, False


def main() -> int:
    any_errors: list[str] = []
    grand_total = 0
    for guide in GUIDE_PATHS:
        in_sync, errors, skipped = _check_one(guide)
        grand_total += in_sync
        if skipped:
            print(f"SKIP [{guide.name}]: not present yet")
            continue
        if errors:
            any_errors.extend(errors)
        else:
            print(f"OK [{guide.name}]: {in_sync} blocks match canonical sources")

    if any_errors:
        for line in any_errors:
            print(line)
        print("\nRun `make regenerate` (or `python3 tools/regenerate_embeds.py`) to fix.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
