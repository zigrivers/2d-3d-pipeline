#!/usr/bin/env python3
"""Format pipeline_doctor --check installed --json output for the audit loop.

Reads JSON on stdin, writes a stage-grouped punch list to stdout suitable for
the multi-select prompts described in setup-skill/SKILL.md §audit loop.

This is a thin helper — the skill itself drives the actual user interaction.
"""
from __future__ import annotations

import json
import sys


def format_report(report: dict) -> str:
    out: list[str] = []
    stages = (report.get("check_installed") or {}).get("stages") or {}
    for stage_name, stage_data in stages.items():
        drifted = []
        for key in ("scripts", "skill", "venvs", "models", "items"):
            for row in (stage_data.get(key) or []):
                if row.get("status") in ("drift", "missing", "partial"):
                    drifted.append(row)
        if not drifted:
            continue
        out.append(f"{stage_name}/ — {len(drifted)} item(s) drifted")
        for i, row in enumerate(drifted, start=1):
            name = row.get("name") or row.get("id") or "<unknown>"
            reason = row.get("reason") or row.get("current") or row["status"]
            out.append(f"  [{i}] {name} — {reason}")
        out.append("")
        out.append("Apply: (a) all  (b) selected (e.g. \"1,3-4\")  (s) skip")
        out.append("")
    if not out:
        out.append("In sync. No drift detected.")
    return "\n".join(out)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON on stdin: {e}", file=sys.stderr)
        return 2
    print(format_report(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
