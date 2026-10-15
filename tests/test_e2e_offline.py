"""Offline end-to-end test of the core flow through the real `pug` CLI:

    pug bone jp -> Bone Map in place (as `pug chew` would write it) -> pug bark -> pug run

The API is a local HTTP server, so no internet or Anthropic key is needed. `go build` needs the
cobra module from the Go module cache or proxy; the test skips if it can't be fetched, or if go is missing.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from core.architect import save_bone_map
from core.barker import save_bark_config

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "jsonplaceholder_bone_map.json"
_PUG_SCRIPT = Path(sys.executable).parent / "pug"
PUG = [str(_PUG_SCRIPT)] if _PUG_SCRIPT.exists() else [sys.executable, str(ROOT / "main.py")]

POSTS = [{"userId": 1, "id": 1, "title": "local post", "body": "served by the test"}]

pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="go is not on PATH; the e2e test builds the generated CLI")


@pytest.fixture(scope="module")
def local_api():
    """A tiny stand-in for JSONPlaceholder: /posts, /posts/1, and 404 for anything else."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/posts":
                status, payload = 200, POSTS
            elif path == "/posts/1":
                status, payload = 200, POSTS[0]
            else:
                status, payload = 404, {}
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _pug(cwd, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "PUG_MODEL", "PUG_DEBUG")}
    env["COLUMNS"] = "200"
    r = subprocess.run(PUG + list(args), cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
    r.out = r.stdout + r.stderr
    return r


def test_core_flow_offline(tmp_path, local_api):
    # 1. bone
    r = _pug(tmp_path, "bone", "jp")
    assert r.returncode == 0, r.out
    bone_dir = tmp_path / "bones" / "jp"
    assert bone_dir.is_dir()

    # 2. chew's output, written with the same functions `pug chew` uses (LLM step skipped);
    #    the base URL points at the local server instead of the docs' API
    save_bone_map(json.loads(FIXTURE.read_text()), bone_dir / "bone_map.json")
    save_bark_config(bone_dir, base_url=local_api, auth_type="none", api_key_env="API_KEY")

    # 3. bark: smell test against the local server, generate, go build
    r = _pug(tmp_path, "bark")
    log = bone_dir / "cli" / "build.log"
    if r.returncode != 0 and log.exists() and any(s in log.read_text() for s in ("dial tcp", "proxy.golang.org", "no such host")):
        pytest.skip(f"go could not download modules (offline with an empty module cache?):\n{log.read_text()}")
    assert r.returncode == 0, r.out
    assert f"GET {local_api}/posts" in r.out and "OK" in r.out
    assert "Huff! I did it" in r.out
    binary = bone_dir / "cli" / "bin" / "jp"
    assert binary.is_file()
    cli_files = {p.name for p in (bone_dir / "cli").iterdir()}
    assert {"CLAUDE.md", "SKILL.md"} <= cli_files
    assert not cli_files & {"mcp.json", "mcp-server.cjs"}

    # 4. pug run against the local server: JSON on stdout, exit 0
    r = _pug(tmp_path, "run", "get-post", "--id", "1")
    assert r.returncode == 0, r.out
    assert json.loads(r.stdout) == POSTS[0]
    assert "200 OK" in r.stderr

    # 5. a 404 exits non-zero with nothing on stdout
    r = _pug(tmp_path, "run", "get-post", "--id", "99999")
    assert r.returncode != 0, r.out
    assert r.stdout == ""
    assert "404" in r.stderr
