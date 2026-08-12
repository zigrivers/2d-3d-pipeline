"""prompt_doctor.py: LLM prompt rewrite for judge-rejected best-of-N runs (v0.6.1)."""
import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
DOCTOR = SCRIPTS / "prompt_doctor.py"

SCORES = {
    "results": [
        {"rank": 1, "image": "a.png", "rejected": True,
         "scores": {"three_quarter_view": 2, "overall": 1, "visible_faces": "front only"}},
        {"rank": 2, "image": "b.png", "rejected": True,
         "scores": {"three_quarter_view": 3, "overall": 1, "visible_faces": "front only"}},
    ]
}


class _MockChatServer:
    def __init__(self, reply_content: str):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"data": [
                    {"id": "some/hf-repo"},
                    {"id": "/served/model/path"},
                ]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                outer.requests.append(json.loads(self.rfile.read(length)))
                body = json.dumps({
                    "choices": [{"message": {"content": reply_content}}],
                }).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _run(args, env_extra=None):
    import os
    env = dict(os.environ)
    env.pop("PIPELINE_PROMPT_DOCTOR_ENDPOINT", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(DOCTOR), *args],
                          capture_output=True, text=True, env=env, timeout=60)


@pytest.fixture
def scores_file(tmp_path):
    f = tmp_path / "judge.json"
    f.write_text(json.dumps(SCORES))
    return str(f)


def test_rewrites_prompt(scores_file):
    server = _MockChatServer('{"prompt": "treasure chest seen from a 3/4 angle showing front and right side"}')
    try:
        r = _run(["--prompt", "treasure chest", "--scores-file", scores_file,
                  "--endpoint", server.base])
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "treasure chest seen from a 3/4 angle showing front and right side"
        req = server.requests[0]
        # picked the served (filesystem-path) model, not models[0]
        assert req["model"] == "/served/model/path"
        assert req["chat_template_kwargs"] == {"enable_thinking": False}
        # judge scores made it into the user message
        assert "three_quarter_view" in req["messages"][1]["content"]
        assert "treasure chest" in req["messages"][1]["content"]
    finally:
        server.stop()


def test_env_endpoint_and_model_override(scores_file):
    server = _MockChatServer('{"prompt": "new prompt"}')
    try:
        r = _run(["--prompt", "old prompt", "--scores-file", scores_file],
                 env_extra={"PIPELINE_PROMPT_DOCTOR_ENDPOINT": server.base,
                            "PIPELINE_PROMPT_DOCTOR_MODEL": "forced-model"})
        assert r.returncode == 0, r.stderr
        assert server.requests[0]["model"] == "forced-model"
    finally:
        server.stop()


def test_unchanged_prompt_fails(scores_file):
    server = _MockChatServer('{"prompt": "same prompt"}')
    try:
        r = _run(["--prompt", "same prompt", "--scores-file", scores_file,
                  "--endpoint", server.base])
        assert r.returncode == 1
        assert r.stdout.strip() == ""
    finally:
        server.stop()


def test_no_endpoint_exits_2(scores_file):
    r = _run(["--prompt", "p", "--scores-file", scores_file])
    assert r.returncode == 2
    assert "no endpoint" in r.stderr


def test_unreachable_endpoint_fails_cleanly(scores_file):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    r = _run(["--prompt", "p", "--scores-file", scores_file,
              "--endpoint", f"http://127.0.0.1:{port}/v1"])
    assert r.returncode == 1
    assert r.stdout.strip() == ""
