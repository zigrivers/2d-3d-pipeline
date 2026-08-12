"""vlm_judge.py --endpoint: remote OpenAI-compatible judge path (v0.6.1).

Runs vlm_judge.py as a subprocess against a stdlib mock server — no mlx-vlm
install needed, which is itself part of the contract: with an endpoint set,
the script must not require the vlm-env venv at all.
"""
import base64
import json
import socket
import struct
import subprocess
import sys
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
JUDGE = SCRIPTS / "vlm_judge.py"

RUBRIC_REPLY = json.dumps({
    "visible_faces": "front + right side",
    "subject_match": 9, "three_quarter_view": 8, "background_cleanliness": 9,
    "lighting_flatness": 8, "single_subject": 9, "silhouette_readability": 9,
    "overall": 9,
})

MESH_REPLY = json.dumps({
    "shape_consistency": "consistent solid volume in all views",
    "recognizable": 8, "back_face_plausibility": 7, "geometry_artifacts": 8,
    "texture_coherence": None, "artifacts_note": "", "overall": 8,
})


def _tiny_png(path: Path) -> None:
    """Write a valid 1x1 grey PNG without any imaging dependency."""
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00\x80")
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    path.write_bytes(png)


class _MockVlmServer:
    """Minimal OpenAI-compatible surface: GET /v1/models, POST /v1/chat/completions."""

    def __init__(self, reply_text: str):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.endswith("/models"):
                    body = json.dumps({"object": "list", "data": []}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                outer.requests.append({"path": self.path, "payload": payload})
                body = json.dumps({
                    "choices": [{"message": {"role": "assistant",
                                             "content": reply_text}}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "concept.png"
    _tiny_png(p)
    return p


def _run_judge(args, env_extra=None):
    import os
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(JUDGE), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_image_mode_via_endpoint(tmp_path, png):
    server = _MockVlmServer(RUBRIC_REPLY)
    try:
        meta = tmp_path / "meta.json"
        meta.write_text("{}")
        r = _run_judge(["--mode", "image", "--image", str(png),
                        "--meta", str(meta), "--json",
                        "--endpoint", server.base])
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["verdict"] == 9.0
        assert out["endpoint"] == server.base
        # request shape: one image as data URL + the rubric text
        req = server.requests[0]
        assert req["path"] == "/v1/chat/completions"
        content = req["payload"]["messages"][0]["content"]
        kinds = [c["type"] for c in content]
        assert kinds == ["image_url", "text"]
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        # round-trips to the original file bytes
        b64 = content[0]["image_url"]["url"].split(",", 1)[1]
        assert base64.b64decode(b64) == png.read_bytes()
        assert req["payload"]["temperature"] == 0.0
        # meta.json merged with the endpoint recorded
        judged = json.loads(meta.read_text())["judge"]
        assert judged["endpoint"] == server.base
    finally:
        server.stop()


def test_mesh_mode_ignores_endpoint_and_judges_in_process(tmp_path, png):
    # Multi-image judging over the served path diverges from in-process
    # (verified live 2026-08-12: same 8 views, 8/10 in-process vs 0/10 served),
    # so mesh mode must never use the endpoint. In this mlx-vlm-less test env
    # that means: no HTTP request, graceful no-op exit.
    views = []
    for i in range(3):
        v = tmp_path / f"view{i}.png"
        _tiny_png(v)
        views.append(str(v))
    server = _MockVlmServer(MESH_REPLY)
    try:
        meta = tmp_path / "meta.json"
        meta.write_text("{}")
        r = _run_judge(["--mode", "mesh", "--images", *views,
                        "--meta", str(meta), "--json",
                        "--endpoint", server.base])
        assert r.returncode == 0
        assert server.requests == []
        assert "in-process" in r.stderr
    finally:
        server.stop()


def test_rank_mode_one_call_per_image(tmp_path, png):
    imgs = []
    for i in range(2):
        v = tmp_path / f"cand{i}.png"
        _tiny_png(v)
        imgs.append(str(v))
    server = _MockVlmServer(RUBRIC_REPLY)
    try:
        meta = tmp_path / "meta.json"
        meta.write_text("{}")
        r = _run_judge(["--mode", "image", "--rank", "--images", *imgs,
                        "--meta", str(meta), "--json",
                        "--endpoint", server.base])
        assert r.returncode == 0, r.stderr
        # de-biasing protocol: one judge call per candidate, never joint
        assert len(server.requests) == 2
    finally:
        server.stop()


def test_env_var_is_honored(tmp_path, png):
    server = _MockVlmServer(RUBRIC_REPLY)
    try:
        meta = tmp_path / "meta.json"
        meta.write_text("{}")
        r = _run_judge(["--mode", "image", "--image", str(png),
                        "--meta", str(meta), "--json"],
                       env_extra={"PIPELINE_JUDGE_ENDPOINT": server.base})
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["endpoint"] == server.base
    finally:
        server.stop()


def test_unreachable_endpoint_falls_back_gracefully(tmp_path, png):
    # grab a port nothing listens on
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    meta = tmp_path / "meta.json"
    meta.write_text("{}")
    r = _run_judge(["--mode", "image", "--image", str(png),
                    "--meta", str(meta), "--json",
                    "--endpoint", f"http://127.0.0.1:{dead_port}/v1"])
    # this test env has no mlx-vlm, so fallback lands on the graceful no-op
    assert r.returncode == 0
    assert "unreachable" in r.stderr
    assert "falling back" in r.stderr
