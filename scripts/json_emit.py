#!/usr/bin/env python3
"""Emit a JSON object built from typed key=value arguments.

Used by concept.sh / generate.sh / print.sh under `--json` to produce the
final stdout line. Python does the escaping, so prompts that contain
quotes, backslashes, or newlines round-trip safely.

Argument forms:

  status=ok                    string field
  --int width=1024             integer (empty string becomes 0)
  --float duration=42.5        float
  --bool fits=true             true/yes/1 -> true, else false
  --array outputs='["a","b"]'  JSON-encoded array literal
  --object dims='{"x":50.0}'   JSON-encoded object literal
  --null engine_path=          explicit null when value is empty
                               (without --null, empty values stay as "")

The output is a single line of compact JSON on stdout. Output ordering
follows the order of the arguments — readable for humans tailing logs.

Examples:

  json_emit.py status=ok stage=text_to_image \\
      model=z-image-turbo \\
      --int width=1024 --int height=1024 \\
      --array outputs='["/abs/path.png"]' \\
      hardware_tier=laptop
"""
from __future__ import annotations

import json
import sys


def _split(arg: str) -> tuple[str, str]:
    if "=" not in arg:
        print(f"json_emit: missing '=' in argument: {arg}", file=sys.stderr)
        sys.exit(2)
    k, _, v = arg.partition("=")
    return k, v


def _to_int(v: str) -> int:
    if v == "":
        return 0
    try:
        return int(v)
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            print(f"json_emit: not an int: {v!r}", file=sys.stderr)
            sys.exit(2)


def _to_float(v: str) -> float:
    if v == "":
        return 0.0
    try:
        return float(v)
    except ValueError:
        print(f"json_emit: not a float: {v!r}", file=sys.stderr)
        sys.exit(2)


def _to_bool(v: str) -> bool:
    return v.strip().lower() in ("true", "1", "yes", "y")


def main(argv: list[str]) -> int:
    out: dict[str, object] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--int":
            k, v = _split(argv[i + 1])
            out[k] = _to_int(v)
            i += 2
        elif a == "--float":
            k, v = _split(argv[i + 1])
            out[k] = _to_float(v)
            i += 2
        elif a == "--bool":
            k, v = _split(argv[i + 1])
            out[k] = _to_bool(v)
            i += 2
        elif a == "--array":
            k, v = _split(argv[i + 1])
            try:
                out[k] = json.loads(v) if v else []
            except json.JSONDecodeError as e:
                print(f"json_emit: --array value is not valid JSON: {e}", file=sys.stderr)
                sys.exit(2)
            i += 2
        elif a == "--object":
            k, v = _split(argv[i + 1])
            try:
                out[k] = json.loads(v) if v else {}
            except json.JSONDecodeError as e:
                print(f"json_emit: --object value is not valid JSON: {e}", file=sys.stderr)
                sys.exit(2)
            i += 2
        elif a == "--null":
            k, v = _split(argv[i + 1])
            out[k] = v if v else None
            i += 2
        elif a.startswith("--"):
            print(f"json_emit: unknown flag: {a}", file=sys.stderr)
            sys.exit(2)
        else:
            k, v = _split(a)
            out[k] = v
            i += 1

    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
