#!/usr/bin/env python3
"""Per-asset meta.json read / merge / validate helper.

Every quality pass in v0.3+ writes its results into a single
`<output>.meta.json` next to the generated asset. Replaces v2's
proliferation of per-pass sidecar files.

Usage:
    meta_helper.py merge   <path> --section <name> --data <json-string>
    meta_helper.py merge   <path> --section <name> --data-file <path>
    meta_helper.py get     <path> [--section <name>]
    meta_helper.py validate <path> [--schema <path>]

Merge semantics:
  - Each pass owns exactly one top-level section. No cross-pass writes.
  - Within a section, fields are merged (dict-update at the top level
    of the section), so partial writes don't clobber prior fields.
  - The file is created if missing, with `schema_version` and an
    `asset_name` derived from the meta.json basename.
  - An advisory `fcntl.flock` is held during read-modify-write so
    concurrent merges from parallel passes don't corrupt the file.

Top-level sections (per the spec, cross-cutting principle 2):

    input            preprocessing    generation
    cleanup          quality          print
    preview          clip

Any pass writing to a section not on this list is rejected unless
`--allow-unknown-section` is passed (escape hatch for future passes
that ship before this helper is updated).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

KNOWN_SECTIONS = {
    "input",
    "preprocessing",
    "generation",
    "cleanup",
    "quality",
    "print",
    "preview",
    "clip",
}


@contextmanager
def _locked(path: Path, mode: str):
    """Open `path` and hold an advisory flock for the duration."""
    # Open with 'a+' for create-if-missing semantics; reset offset for read.
    fh = open(path, mode)
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        yield fh
    finally:
        fh.flush()
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def _load(fh) -> dict:
    """Read JSON from an open handle. Empty file → empty dict."""
    raw = fh.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def _dump(fh, data: dict) -> None:
    fh.seek(0)
    fh.truncate()
    json.dump(data, fh, indent=2, sort_keys=True)
    fh.write("\n")


def _seed_skeleton(asset_name: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "asset_name": asset_name,
    }


def cmd_merge(args: argparse.Namespace) -> int:
    section = args.section
    if section not in KNOWN_SECTIONS and not args.allow_unknown_section:
        print(
            f"ERROR: unknown section '{section}'. "
            f"Known: {sorted(KNOWN_SECTIONS)}. Pass --allow-unknown-section to override.",
            file=sys.stderr,
        )
        return 2

    if args.data_file:
        new_data = json.loads(Path(args.data_file).read_text())
    elif args.data is not None:
        new_data = json.loads(args.data)
    else:
        print("ERROR: --data or --data-file is required", file=sys.stderr)
        return 2

    if not isinstance(new_data, dict):
        print(
            "ERROR: section data must be a JSON object; got "
            f"{type(new_data).__name__}",
            file=sys.stderr,
        )
        return 2

    path = Path(args.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    asset_name = path.name
    if asset_name.endswith(".meta.json"):
        asset_name = asset_name[: -len(".meta.json")]

    with _locked(path, "r+") as fh:
        existing = _load(fh)
        if not existing:
            existing = _seed_skeleton(asset_name)
        existing.setdefault(section, {})
        if not isinstance(existing[section], dict):
            print(
                f"ERROR: existing section '{section}' is not an object "
                f"(found {type(existing[section]).__name__}); refusing to merge",
                file=sys.stderr,
            )
            return 2
        existing[section].update(new_data)
        _dump(fh, existing)

    if args.json:
        print(json.dumps({"status": "ok", "section": section, "path": str(path)}))
    else:
        print(f"[meta_helper] merged {section} into {path}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"ERROR: meta file not found: {path}", file=sys.stderr)
        return 2
    with _locked(path, "r") as fh:
        data = _load(fh)
    if args.section:
        data = data.get(args.section, {})
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Light validation. Without jsonschema the helper checks structure;
    with jsonschema, it does a full schema check against meta_schema.json."""
    path = Path(args.path)
    if not path.exists():
        print(f"ERROR: meta file not found: {path}", file=sys.stderr)
        return 2
    with _locked(path, "r") as fh:
        data = _load(fh)

    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("top-level value must be an object")
    else:
        if data.get("schema_version") != SCHEMA_VERSION:
            errors.append(
                f"schema_version is {data.get('schema_version')!r} "
                f"(expected {SCHEMA_VERSION})"
            )
        for key in data:
            if key in ("schema_version", "asset_name"):
                continue
            if key not in KNOWN_SECTIONS:
                errors.append(f"unknown top-level section: '{key}'")
            elif not isinstance(data[key], dict):
                errors.append(f"section '{key}' must be an object")

    schema_path = Path(args.schema) if args.schema else None
    if schema_path and schema_path.exists():
        try:
            import jsonschema  # type: ignore
        except ImportError:
            # Not fatal — structural checks above cover the basics. Surface
            # the gap so the user can opt in to full validation if they want.
            print(
                "[meta_helper] note: jsonschema not installed; skipped full schema "
                "validation. Install in pipeline-tools-env to enable.",
                file=sys.stderr,
            )
        else:
            schema = json.loads(schema_path.read_text())
            try:
                jsonschema.validate(data, schema)
            except jsonschema.ValidationError as exc:
                errors.append(f"schema validation: {exc.message}")

    if errors:
        for e in errors:
            print(f"INVALID: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"status": "ok", "path": str(path)}))
    else:
        print(f"[meta_helper] {path} is valid")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Per-asset meta.json helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_merge = sub.add_parser("merge", help="Merge a section into the meta.json (create if missing)")
    p_merge.add_argument("path", help="Path to <output>.meta.json")
    p_merge.add_argument("--section", required=True, help=f"One of: {sorted(KNOWN_SECTIONS)}")
    g = p_merge.add_mutually_exclusive_group()
    g.add_argument("--data", help="Inline JSON object string")
    g.add_argument("--data-file", help="Path to a JSON file with the section data")
    p_merge.add_argument("--allow-unknown-section", action="store_true")
    p_merge.add_argument("--json", action="store_true", help="Emit a single-line JSON status on stdout")
    p_merge.set_defaults(func=cmd_merge)

    p_get = sub.add_parser("get", help="Print the meta.json (or one section) to stdout")
    p_get.add_argument("path", help="Path to <output>.meta.json")
    p_get.add_argument("--section", help="Print only this section instead of the whole file")
    p_get.set_defaults(func=cmd_get)

    p_validate = sub.add_parser("validate", help="Validate structure (and schema if available)")
    p_validate.add_argument("path", help="Path to <output>.meta.json")
    p_validate.add_argument("--schema", help="Path to meta_schema.json (defaults to alongside this script)")
    p_validate.add_argument("--json", action="store_true")
    p_validate.set_defaults(func=cmd_validate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Default schema path: same directory as this script
    if args.cmd == "validate" and not args.schema:
        here = Path(__file__).resolve().parent
        default = here / "meta_schema.json"
        if default.exists():
            args.schema = str(default)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
