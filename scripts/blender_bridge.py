#!/usr/bin/env python3
"""Serve this pipeline over the MCP-for-Blender LOCAL_API contract.

The "MCP for Blender" add-on's Hunyuan3D integration, in LOCAL_API mode, POSTs
JSON to ``/generate`` and expects raw GLB bytes back. This server answers that
contract using the pipeline's own wrappers instead of a Hunyuan3D checkpoint:

    {"image": "<base64 png>"}  -> generate.sh                (image -> GLB)
    {"text":  "a treasure chest"} -> concept.sh + generate.sh (text -> 2D -> GLB)

Text-to-3D is the capability the add-on cannot otherwise reach: its local mode
requires an image, because the upstream local server is image-only. Routing
text through concept.sh first adds it with no add-on changes, and reuses the
cleanup, quality checks and manifest tracking the wrappers already do.

Stdlib only, so it runs under any Python on the box without a venv.

Bind address defaults to 127.0.0.1: /generate runs the pipeline wrappers, so
this must not be exposed off-host.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(os.environ.get("PIPELINE_WORKSPACE", Path.home() / "3d-pipeline" / "workspace"))
CONCEPT = WORKSPACE / "concept.sh"
GENERATE = WORKSPACE / "generate.sh"

# Generation is GPU-bound; two concurrent runs thrash unified memory and are
# slower than running them back to back.
# ponytail: one global lock, add a real job queue if batching ever matters.
_GEN_LOCK = threading.Lock()

MAX_PROMPT_CHARS = 2000
MAX_BODY_BYTES = 64 * 1024 * 1024  # a base64 PNG reference image
WRAPPER_TIMEOUT = 900  # trellis2 is the slow path at ~6 min/asset


class PipelineError(RuntimeError):
    """A wrapper failed, or returned something we could not use."""


def _run_wrapper(cmd: list[str]) -> dict:
    """Run a pipeline wrapper in --json mode and return its parsed result.

    The wrappers route human-readable output to stderr under --json, so the
    last non-empty stdout line is the JSON result.
    """
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=WRAPPER_TIMEOUT,
        cwd=str(WORKSPACE),
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        raise PipelineError(f"{Path(cmd[0]).name} exited {proc.returncode}: {' | '.join(tail)}")

    for line in reversed((proc.stdout or "").strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if result.get("status") != "ok":
            raise PipelineError(f"{Path(cmd[0]).name}: {result.get('error', result.get('status'))}")
        return result

    raise PipelineError(f"{Path(cmd[0]).name} produced no JSON result")


def _safe_name() -> str:
    return f"bridge_{uuid.uuid4().hex[:12]}"


def text_to_image(prompt: str, name: str) -> Path:
    """Generate a concept image from a text prompt. Returns the PNG path."""
    result = _run_wrapper([str(CONCEPT), prompt, "-o", name, "--json"])
    outputs = result.get("outputs") or []
    if not outputs:
        raise PipelineError("concept.sh returned no image")
    return Path(outputs[0])


def image_to_glb(image_path: Path) -> Path:
    """Generate and clean a mesh from an image. Returns the cleaned GLB path."""
    result = _run_wrapper([str(GENERATE), "-i", str(image_path), "--json"])
    clean = result.get("clean_path") or result.get("raw_path")
    if not clean:
        raise PipelineError("generate.sh returned no mesh path")
    return Path(clean)


def _decode_image(encoded: str, name: str) -> Path:
    """Write a base64 (optionally data-URI) image to disk. Returns the path."""
    payload = re.sub(r"^data:image/[a-zA-Z0-9.+-]+;base64,", "", encoded.strip())
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PipelineError(f"image is not valid base64: {exc}") from exc
    if not raw:
        raise PipelineError("image decoded to zero bytes")

    concept_dir = WORKSPACE / "concept"
    concept_dir.mkdir(parents=True, exist_ok=True)
    path = concept_dir / f"{name}.png"
    path.write_bytes(raw)
    return path


def build_glb(params: dict) -> tuple[Path, str]:
    """Route a request to the right pipeline path. Returns (glb, how)."""
    text = params.get("text")
    image = params.get("image")

    if isinstance(text, str):
        text = text.strip()
    if isinstance(image, str):
        image = image.strip()

    if not text and not image:
        raise PipelineError("request needs either 'text' or 'image'")
    if text and len(text) > MAX_PROMPT_CHARS:
        raise PipelineError(f"prompt exceeds {MAX_PROMPT_CHARS} characters")

    name = _safe_name()
    # An image wins when both are sent: it is the more specific instruction,
    # and it is what the add-on sends when the user supplied a reference.
    if image:
        image_path = _decode_image(image, name)
        how = "image_to_3d"
    else:
        image_path = text_to_image(text, name)
        how = "text_to_2d_to_3d"

    return image_to_glb(image_path), how


class Handler(BaseHTTPRequestHandler):
    server_version = "PipelineBlenderBridge/1.0"

    def log_message(self, fmt, *args):  # noqa: A003 - BaseHTTPRequestHandler API
        sys.stderr.write("[bridge] %s\n" % (fmt % args))

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip("/") == "/health":
            self._send_json(200, {
                "status": "ok",
                "backend": "2d-3d-pipeline",
                "workspace": str(WORKSPACE),
                "text_to_3d": CONCEPT.is_file(),
                "image_to_3d": GENERATE.is_file(),
            })
        else:
            self._send_json(404, {"text": "not found", "error_code": 1})

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip("/") != "/generate":
            self._send_json(404, {"text": "not found", "error_code": 1})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send_json(400, {"text": "bad Content-Length", "error_code": 1})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(400, {"text": "missing or oversized body", "error_code": 1})
            return

        try:
            params = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json(400, {"text": f"bad JSON: {exc}", "error_code": 1})
            return
        if not isinstance(params, dict):
            self._send_json(400, {"text": "body must be a JSON object", "error_code": 1})
            return

        with _GEN_LOCK:
            try:
                glb, how = build_glb(params)
                data = glb.read_bytes()
            except PipelineError as exc:
                self.log_message("failed: %s", exc)
                self._send_json(400, {"text": str(exc), "error_code": 1})
                return
            except subprocess.TimeoutExpired:
                self.log_message("timed out after %ss", WRAPPER_TIMEOUT)
                self._send_json(504, {"text": "generation timed out", "error_code": 1})
                return
            except OSError as exc:
                self.log_message("error: %s", exc)
                self._send_json(500, {"text": str(exc), "error_code": 1})
                return

        self.log_message("%s -> %s (%d bytes)", how, glb.name, len(data))
        self.send_response(200)
        self.send_header("Content-Type", "model/gltf-binary")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Pipeline-Path", str(glb))
        self.send_header("X-Pipeline-Route", how)
        self.end_headers()
        self.wfile.write(data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default: 127.0.0.1, localhost only)")
    parser.add_argument("--port", type=int, default=8081,
                        help="bind port (default: 8081, the add-on's default)")
    args = parser.parse_args(argv)

    missing = [str(p) for p in (CONCEPT, GENERATE) if not p.is_file()]
    if missing:
        print(f"[bridge] missing wrapper(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[bridge] serving {WORKSPACE} on http://{args.host}:{args.port}", file=sys.stderr)
    print("[bridge] POST /generate {\"text\":...} or {\"image\":<base64>} -> GLB bytes",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] stopped", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
