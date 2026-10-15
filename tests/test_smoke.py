"""Offline smoke test for the bark -> go build -> run flow.

Needs no Anthropic key and no Playwright: the Bone Map comes from a fixture
(same shape `pug chew` writes) and the network smell test is skipped.
The `go build` step needs Go on PATH and the cobra module (from the Go module
cache or proxy). Tests marked `network` call jsonplaceholder.typicode.com.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.barker import bark, save_bark_config

FIXTURE = Path(__file__).parent / "fixtures" / "jsonplaceholder_bone_map.json"
BASE_URL = "https://jsonplaceholder.typicode.com"
BONE = "jp"

_NETWORK_ERRORS = ("dial tcp", "no such host", "connection refused", "i/o timeout", "proxy.golang.org", "TLS handshake")


@pytest.fixture(scope="module")
def built_bone(tmp_path_factory):
    """Lay out bones/jp/ like Pug does, then bark (without the smell test) and go build."""
    if shutil.which("go") is None:
        pytest.skip("go is not on PATH; install Go to run the generated-CLI build test")
    root = tmp_path_factory.mktemp("pugroot")
    pug_dir = root / "bones" / BONE
    pug_dir.mkdir(parents=True)
    shutil.copy(FIXTURE, pug_dir / "bone_map.json")
    save_bark_config(pug_dir, BASE_URL)
    (root / "bones" / "current").write_text(BONE)
    out_dir = bark(pug_dir / "bone_map.json", pug_dir, BONE, skip_smell_test=True)
    binary = out_dir / "bin" / BONE
    if not binary.exists():
        log = (out_dir / "build.log").read_text() if (out_dir / "build.log").exists() else ""
        if any(s in log for s in _NETWORK_ERRORS):
            pytest.skip(f"go could not download modules (offline?):\n{log}")
        pytest.fail(f"go build failed:\n{log}")
    return root, out_dir, binary


def test_fixture_has_shared_flags():
    """The fixture must keep shared flag names so it catches Go variable collisions."""
    plan = json.loads(FIXTURE.read_text())
    by_cmd = {e["command"]: e["flags"] for e in plan}
    assert "--id" in by_cmd["get-post"] and "--id" in by_cmd["delete-post"]
    assert "--user-id" in by_cmd["list-posts"] and "--user-id" in by_cmd["create-post"]


def test_generated_cli_builds(built_bone):
    _, out_dir, binary = built_bone
    assert binary.is_file()
    help_out = subprocess.run([str(binary), "--help"], capture_output=True, text=True, timeout=30).stdout
    for cmd in ("list-posts", "get-post", "list-post-comments", "create-post", "delete-post"):
        assert cmd in help_out


def _skip_if_offline(output: str):
    if any(s in output for s in _NETWORK_ERRORS) or "dial" in output:
        pytest.skip(f"jsonplaceholder.typicode.com unreachable:\n{output}")


@pytest.mark.network
def test_binary_get_post(built_bone):
    _, _, binary = built_bone
    env = {"PATH": "/usr/bin:/bin", "JP_BASE_URL": BASE_URL}
    r = subprocess.run([str(binary), "get-post", "--id", "1"], capture_output=True, text=True, env=env, timeout=60)
    _skip_if_offline(r.stdout + r.stderr)
    assert '"id": 1' in r.stdout, r.stdout + r.stderr


@pytest.mark.network
def test_pug_run_get_post(built_bone, monkeypatch, capfd):
    """`pug run get-post --id 1` from the project root (regression: relative binary path)."""
    import main

    root, _, _ = built_bone
    monkeypatch.chdir(root)
    main.cmd_run("get-post", ["--id", "1"])
    out, err = capfd.readouterr()
    _skip_if_offline(out + err)
    assert '"id": 1' in out, out + err


# --- Agent-facing contract of the generated CLI ---------------------------------

def _run(binary, *args, env_extra=None, stdin=None):
    env = {"PATH": "/usr/bin:/bin"}
    env.update(env_extra or {})
    return subprocess.run(
        [str(binary), *args], capture_output=True, text=True, env=env, input=stdin, timeout=60
    )


@pytest.fixture(scope="module")
def echo_server():
    """Local HTTP server that echoes what the CLI sent, so the contract is testable offline."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    class Handler(BaseHTTPRequestHandler):
        def _reply(self):
            u = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode() if length else ""
            if "99999" in u.path:
                status, payload = 404, {"error": "not found"}
            else:
                status = 201 if self.command == "POST" else 200
                payload = {
                    "method": self.command,
                    "path": u.path,
                    "query": {k: v[0] for k, v in parse_qs(u.query).items()},
                    "content_type": self.headers.get("Content-Type"),
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(raw) if raw else None,
                }
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = _reply

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _local(binary, base, *args, **kw):
    return _run(binary, *args, env_extra={"JP_BASE_URL": base}, **kw)


def test_query_uses_original_api_names(built_bone, echo_server):
    _, _, binary = built_bone
    r = _local(binary, echo_server, "list-posts", "--user-id", "1", "--limit", "2")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["query"] == {"userId": "1", "_limit": "2"}


def test_body_from_field_flags_and_data(built_bone, echo_server):
    _, _, binary = built_bone
    r = _local(binary, echo_server, "create-post", "--data", '{"title": "base", "extra": true}', "--title", "hi", "--user-id", "1")
    assert r.returncode == 0, r.stderr
    sent = json.loads(r.stdout)
    assert sent["method"] == "POST"
    assert sent["content_type"] == "application/json"
    assert sent["body"] == {"title": "hi", "extra": True, "userId": 1}  # field flags override --data


def test_body_from_data_file(built_bone, echo_server, tmp_path):
    _, _, binary = built_bone
    f = tmp_path / "post.json"
    f.write_text('{"title": "from file"}')
    r = _local(binary, echo_server, "create-post", "--data", f"@{f}")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["body"] == {"title": "from file"}


def test_invalid_data_exits_nonzero(built_bone, echo_server):
    _, _, binary = built_bone
    r = _local(binary, echo_server, "create-post", "--data", "not json")
    assert r.returncode != 0
    assert "--data must be a JSON object" in r.stderr


def test_missing_path_param_is_an_error(built_bone, echo_server):
    _, _, binary = built_bone
    r = _local(binary, echo_server, "get-post")
    assert r.returncode != 0
    assert 'required flag(s) "id" not set' in r.stderr
    assert r.stdout == ""


def test_http_error_exit_code_and_streams(built_bone, echo_server):
    _, _, binary = built_bone
    r = _local(binary, echo_server, "get-post", "--id", "99999")
    assert r.returncode == 1
    assert "404" in r.stderr
    assert r.stdout == ""


def test_success_stdout_is_json_status_on_stderr(built_bone, echo_server):
    _, _, binary = built_bone
    r = _local(binary, echo_server, "get-post", "--id", "1")
    assert r.returncode == 0
    assert json.loads(r.stdout)["path"] == "/posts/1"
    assert "200 OK" in r.stderr and "200 OK" not in r.stdout


def test_network_error_exits_nonzero(built_bone):
    _, _, binary = built_bone
    r = _run(binary, "get-post", "--id", "1", env_extra={"JP_BASE_URL": "http://127.0.0.1:9"})
    assert r.returncode != 0
    assert r.stdout == ""


def test_base_url_is_baked_in(built_bone):
    _, out_dir, _ = built_bone
    root_go = (out_dir / "cmd" / "root.go").read_text()
    assert f'getEnv("JP_BASE_URL", "{BASE_URL}")' in root_go


def test_old_bone_map_without_api_names_still_works():
    """Backward compatibility: maps without api_names/body keep the previous behaviour."""
    from core.barker import _build_method_info

    get_info = _build_method_info({"command": "list-posts", "method": "GET", "path": "/posts", "flags": ["--user-id"]})
    assert [f["api"] for f in get_info["query_fields"]] == ["user_id"]
    post_info = _build_method_info({"command": "create-post", "method": "POST", "path": "/posts", "flags": ["--title"]})
    assert [f["api"] for f in post_info["body_fields"]] == ["title"] and post_info["query_fields"] == []


def test_generated_cli_reads_api_key_env_for_auth(tmp_path, monkeypatch):
    """Bearer and API-key auth both read the Bone Map's api_key_env (old <PREFIX>_BEARER_TOKEN is a fallback)."""
    import core.barker as barker

    monkeypatch.setattr(barker.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b""))  # skip go build
    plan = json.loads(FIXTURE.read_text())
    config = {"base_url": BASE_URL, "auth_type": "bearer", "api_key_env": "JP_API_TOKEN"}
    barker.generate_go_project(plan, config, tmp_path / "cli", cli_name="jp")
    root_go = (tmp_path / "cli" / "cmd" / "root.go").read_text()
    assert 'bearer = getEnv("JP_API_TOKEN", getEnv("JP_BEARER_TOKEN", ""))' in root_go
    assert 'apiKey = getEnv("JP_API_TOKEN", "")' in root_go
    assert 'getEnv("JP_AUTH", "bearer")' in root_go


def test_agent_docs_describe_contract(built_bone):
    _, out_dir, _ = built_bone
    for name in ("CLAUDE.md", "SKILL.md"):
        doc = (out_dir / name).read_text()
        assert "query param `userId`" in doc
        assert "JSON body field `userId`" in doc
        assert "`--data`" in doc
        assert "Exit codes" in doc and "stdout" in doc and "stderr" in doc
        assert "`--id` (required)" in doc


# --- Same contract against the real JSONPlaceholder API --------------------------

def _net(binary, *args, base=True):
    r = _run(binary, *args, env_extra={"JP_BASE_URL": BASE_URL} if base else None)
    _skip_if_offline(r.stdout + r.stderr)
    return r


@pytest.mark.network
def test_net_list_posts_filters_by_user(built_bone):
    _, _, binary = built_bone
    r = _net(binary, "list-posts", "--user-id", "1")
    posts = json.loads(r.stdout)
    assert r.returncode == 0 and posts
    assert all(p["userId"] == 1 for p in posts)


@pytest.mark.network
def test_net_list_posts_limit(built_bone):
    _, _, binary = built_bone
    r = _net(binary, "list-posts", "--limit", "2")
    assert r.returncode == 0
    assert len(json.loads(r.stdout)) == 2


@pytest.mark.network
def test_net_create_post_field_flags(built_bone):
    _, _, binary = built_bone
    r = _net(binary, "create-post", "--title", "hi", "--body", "yo", "--user-id", "1")
    assert r.returncode == 0, r.stderr
    assert "201" in r.stderr
    created = json.loads(r.stdout)
    assert created["title"] == "hi" and created["body"] == "yo" and created["userId"] == 1


@pytest.mark.network
def test_net_create_post_data(built_bone):
    _, _, binary = built_bone
    r = _net(binary, "create-post", "--data", '{"title":"x"}')
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["title"] == "x"


@pytest.mark.network
def test_net_get_post_missing_id(built_bone):
    _, _, binary = built_bone
    r = _net(binary, "get-post")
    assert r.returncode != 0
    assert 'required flag(s) "id" not set' in r.stderr


@pytest.mark.network
def test_net_get_post_404(built_bone):
    _, _, binary = built_bone
    r = _net(binary, "get-post", "--id", "99999")
    assert r.returncode != 0
    assert "404" in r.stderr and "404" not in r.stdout


@pytest.mark.network
def test_net_get_post_stdout_is_json(built_bone):
    _, _, binary = built_bone
    r = _net(binary, "get-post", "--id", "1")
    assert r.returncode == 0
    assert json.loads(r.stdout)["id"] == 1


@pytest.mark.network
def test_net_baked_base_url_without_env(built_bone):
    _, _, binary = built_bone
    r = _net(binary, "get-post", "--id", "1", base=False)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["id"] == 1


def test_pug_run_passes_stdout_and_exit_code(built_bone, echo_server):
    """`pug run` keeps stdout clean (Pug's banner goes to stderr) and returns the CLI's exit code."""
    import sys

    root, _, _ = built_bone
    main_py = Path(__file__).resolve().parent.parent / "main.py"

    def pug_run(*args):
        return subprocess.run(
            [sys.executable, str(main_py), "run", *args, "--base-url", echo_server],
            cwd=root, capture_output=True, text=True, timeout=60,
        )

    ok = pug_run("get-post", "--id", "1")
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["path"] == "/posts/1"
    missing = pug_run("get-post", "--id", "99999")
    assert missing.returncode == 1
    assert missing.stdout == ""
