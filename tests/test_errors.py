"""Pug's own errors and exit codes: every failure exits non-zero with a one-line message.

No Anthropic key or network needed: Anthropic is mocked in-process, HTTP goes to a local server,
and Chromium is simulated as missing with an empty PLAYWRIGHT_BROWSERS_PATH.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from types import SimpleNamespace

import anthropic
import pytest

import main
from core import architect, errors, sniffer

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "jsonplaceholder_bone_map.json"
_PUG_SCRIPT = Path(sys.executable).parent / "pug"
PUG = [str(_PUG_SCRIPT)] if _PUG_SCRIPT.exists() else [sys.executable, str(ROOT / "main.py")]


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "PUG_MODEL", "PUG_DEBUG")}
    env["COLUMNS"] = "200"
    env.update(extra)
    return env


def pug(cwd, *args, env=None, stdin_text=None):
    r = subprocess.run(
        PUG + list(args),
        cwd=cwd,
        env=env or _env(),
        input=stdin_text if stdin_text is not None else "",
        capture_output=True,
        text=True,
        timeout=120,
    )
    r.out = r.stdout + r.stderr
    return r


@pytest.fixture
def bone(tmp_path):
    """tmp working dir with an active bone 'jp'."""
    r = pug(tmp_path, "bone", "jp")
    assert r.returncode == 0, r.out
    return tmp_path


# --- help / version ---------------------------------------------------------------

def test_version():
    from core.version import __version__

    r = pug(ROOT, "--version")
    assert r.returncode == 0
    assert r.stdout.strip() == f"pug {__version__}" == "pug 1.0"


@pytest.mark.parametrize(
    "cmd, phrase",
    [
        ("init", "Validate your Anthropic API key"),
        ("bone", "Create or switch to a bone"),
        ("sniff", "headless Chromium"),
        ("chew", "Bone Map"),
        ("bark", "Smell-test the API"),
        ("refine", "Chat with Claude"),
        ("run", "Run a generated CLI"),
    ],
)
def test_every_subcommand_has_help(tmp_path, cmd, phrase):
    r = pug(tmp_path, cmd, "--help")
    assert r.returncode == 0, r.out
    assert phrase in r.out


def test_unknown_argument_is_a_usage_error(tmp_path):
    r = pug(tmp_path, "bark", "--bogus")
    assert r.returncode == 2
    assert "unrecognized arguments: --bogus" in r.out


def test_ascii_pug_keeps_its_indent(capsys):
    main.welcome(show_ascii_art=True)
    out = capsys.readouterr().out.splitlines()
    ears = next(l for l in out if "/^ ^\\" in l)
    face = next(l for l in out if "/ 0 0 \\" in l)
    assert ears.index("/^") == face.index("/ 0") + 1


# --- no active bone -------------------------------------------------------------

@pytest.mark.parametrize("cmd", [["sniff", "https://example.com"], ["chew"], ["bark"], ["refine"], ["run", "x"]])
def test_no_active_bone(tmp_path, cmd):
    r = pug(tmp_path, *cmd)
    assert r.returncode == 1, r.out
    assert "No active bone" in r.out


# --- bone names -----------------------------------------------------------------

@pytest.mark.parametrize("name", ["../escape", "a/b", "..", "Upper", "has space", "current", "dot.name"])
def test_bad_bone_names_rejected(tmp_path, name):
    work = tmp_path / "work"
    work.mkdir()
    r = pug(work, "bone", name)
    assert r.returncode == 2, r.out
    assert "Invalid bone name" in r.out
    assert not (tmp_path / "escape").exists()
    assert not (work / "bones" / "current").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["work"]


def test_empty_bone_name_rejected(tmp_path):
    r = pug(tmp_path, "bone", "")
    assert r.returncode == 2
    assert "Bone name is required" in r.out


def test_good_bone_name(tmp_path):
    r = pug(tmp_path, "bone", "my_api-2")
    assert r.returncode == 0, r.out
    assert (tmp_path / "bones" / "my_api-2").is_dir()


# --- sniff ----------------------------------------------------------------------

def test_sniff_without_url_is_usage_error(bone):
    r = pug(bone, "sniff")
    assert r.returncode == 2
    assert "pug sniff <url>" in r.out and "<project>" not in r.out


def test_sniff_invalid_url(bone):
    r = pug(bone, "sniff", "notaurl")
    assert r.returncode == 1
    assert "Invalid URL: notaurl" in r.out


def test_sniff_missing_chromium(bone, tmp_path):
    empty = tmp_path / "no-browsers"
    empty.mkdir()
    r = pug(bone, "sniff", "https://example.com/", env=_env(PLAYWRIGHT_BROWSERS_PATH=str(empty)))
    assert r.returncode == 1, r.out
    assert "Chromium isn't installed. Run: playwright install chromium" in r.out
    assert "Traceback" not in r.out


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://x.invalid/", "Couldn't load https://x.invalid/: DNS lookup failed"),
        ("Page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:1/", "connection refused"),
        ("BrowserType.launch: Executable doesn't exist at /x/chrome", "Chromium isn't installed"),
        ("Page.goto: Timeout 30000ms exceeded.", "Timed out loading"),
    ],
)
def test_playwright_errors_become_one_line(raw, expected):
    msg = str(sniffer._translate_playwright_error(Exception(raw), "https://x.invalid/" if "x.invalid" in raw else "http://localhost:1/"))
    assert expected in msg
    assert "\n" not in msg


@pytest.mark.network
def test_sniff_http_404(bone):
    r = pug(bone, "sniff", "https://jsonplaceholder.typicode.com/this-page-does-not-exist")
    if "Chromium isn't installed" in r.out:
        pytest.skip("Chromium not installed")
    assert r.returncode == 1, r.out
    assert "returned 404" in r.out


# --- Anthropic key handling (mocked in-process) -----------------------------------

def _api_error(cls, status, message="boom"):
    # Duck-typed response so this works whichever HTTP library the anthropic SDK uses
    resp = SimpleNamespace(request=SimpleNamespace(method="POST", url="https://api.anthropic.com/v1/messages"), status_code=status, headers={})
    return cls(message, response=resp, body={"type": "error", "error": {"type": "x", "message": message}})


class _FakeAnthropic:
    """Stands in for anthropic.Anthropic; records keys, raises or answers."""

    keys = []

    def __init__(self, exc=None):
        self.exc = exc

    def __call__(self, api_key=None, **kw):
        _FakeAnthropic.keys.append(api_key)
        outer = self

        class _Messages:
            def create(self, **kw):
                if outer.exc:
                    raise outer.exc
                return type("R", (), {"content": [type("B", (), {"text": "OK"})()]})()

        return type("C", (), {"messages": _Messages()})()


def _run_main(monkeypatch, *argv, stdin=""):
    monkeypatch.setattr(sys, "argv", ["pug", *argv])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    try:
        main.main()
    except SystemExit as e:
        return e.code or 0
    return 0


@pytest.fixture
def inproc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ("ANTHROPIC_API_KEY", "PUG_MODEL", "PUG_DEBUG"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COLUMNS", "200")
    _FakeAnthropic.keys = []
    return tmp_path


def test_init_invalid_key_is_not_saved(inproc, monkeypatch, capsys):
    monkeypatch.setattr(architect.anthropic, "Anthropic", _FakeAnthropic(_api_error(anthropic.AuthenticationError, 401)))
    code = _run_main(monkeypatch, "init", stdin="sk-ant-bad\n")
    out = capsys.readouterr()
    assert code == 1
    assert "Anthropic rejected the API key (401)" in out.err
    assert "Huff" not in out.out + out.err
    assert not (inproc / ".env").exists()
    assert _FakeAnthropic.keys == ["sk-ant-bad"]


def test_init_valid_key_is_saved(inproc, monkeypatch, capsys):
    monkeypatch.setattr(architect.anthropic, "Anthropic", _FakeAnthropic())
    code = _run_main(monkeypatch, "init", stdin="sk-ant-good\n")
    assert code == 0, capsys.readouterr()
    assert 'ANTHROPIC_API_KEY="sk-ant-good"' in (inproc / ".env").read_text()


def test_init_empty_key(inproc, monkeypatch, capsys):
    code = _run_main(monkeypatch, "init", stdin="")
    assert code == 1
    assert "No key entered" in capsys.readouterr().err
    assert not (inproc / ".env").exists()


def test_init_existing_bad_key_fails_and_force_replaces(inproc, monkeypatch, capsys):
    (inproc / ".env").write_text('ANTHROPIC_API_KEY="sk-ant-old"\nOTHER=1\n')
    monkeypatch.setattr(architect.anthropic, "Anthropic", _FakeAnthropic(_api_error(anthropic.AuthenticationError, 401)))
    assert _run_main(monkeypatch, "init") == 1
    assert "pug init --force" in capsys.readouterr().err
    monkeypatch.setattr(architect.anthropic, "Anthropic", _FakeAnthropic())
    assert _run_main(monkeypatch, "init", "--force", stdin="sk-ant-new\n") == 0
    text = (inproc / ".env").read_text()
    assert 'ANTHROPIC_API_KEY="sk-ant-new"' in text and "OTHER=1" in text and "sk-ant-old" not in text


def test_init_checks_environment_key(inproc, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    monkeypatch.setattr(architect.anthropic, "Anthropic", _FakeAnthropic())
    assert _run_main(monkeypatch, "init") == 0
    assert _FakeAnthropic.keys == ["sk-ant-env"]
    assert "environment" in capsys.readouterr().out


def _bone_with_sniff(root):
    (root / "bones" / "jp").mkdir(parents=True)
    (root / "bones" / "current").write_text("jp")
    (root / "bones" / "jp" / "last_sniff.md").write_text("# API\nGET /posts\n")


def test_chew_without_key(bone):
    (bone / "bones" / "jp" / "last_sniff.md").write_text("# API\n")
    r = pug(bone, "chew")
    assert r.returncode == 1
    assert "No Anthropic API key found" in r.out and "ANTHROPIC_API_KEY" in r.out and "pug init" in r.out
    assert "No .env found" not in r.out


def test_chew_uses_environment_key_over_dotenv(inproc, monkeypatch, capsys):
    _bone_with_sniff(inproc)
    (inproc / ".env").write_text('ANTHROPIC_API_KEY="sk-ant-dotenv"\n')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    monkeypatch.setattr(architect.anthropic, "Anthropic", _FakeAnthropic(_api_error(anthropic.AuthenticationError, 401)))
    assert _run_main(monkeypatch, "chew") == 1
    err = capsys.readouterr().err
    assert _FakeAnthropic.keys == ["sk-ant-env"]
    assert "No .env found" not in err and "Anthropic rejected the API key (401)" in err


@pytest.mark.parametrize(
    "exc, expected",
    [
        (_api_error(anthropic.NotFoundError, 404, "model: nope"), "PUG_MODEL"),
        (_api_error(anthropic.RateLimitError, 429), "rate limit"),
        (_api_error(anthropic.InternalServerError, 529), "overloaded"),
        (_api_error(anthropic.InternalServerError, 500), "server error (500)"),
    ],
)
def test_chew_api_errors_are_one_line(inproc, monkeypatch, capsys, exc, expected):
    _bone_with_sniff(inproc)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    monkeypatch.setattr(architect.anthropic, "Anthropic", _FakeAnthropic(exc))
    assert _run_main(monkeypatch, "chew") == 1
    err = capsys.readouterr().err
    assert expected in err
    assert "Traceback" not in err and "{'type'" not in err


def test_connection_error_message():
    e = anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="https://api.anthropic.com"))
    assert "Couldn't reach the Anthropic API" in errors.friendly_error(e)


def test_unexpected_error_and_debug(inproc, monkeypatch, capsys):
    _bone_with_sniff(inproc)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")

    def boom(*a, **k):
        raise KeyError("weird")

    monkeypatch.setattr(main, "chew", boom)
    assert _run_main(monkeypatch, "chew") == 1
    err = capsys.readouterr().err
    assert "Unexpected error: KeyError" in err and "--debug" in err and "Traceback" not in err
    monkeypatch.setenv("PUG_DEBUG", "1")
    assert _run_main(monkeypatch, "chew") == 1
    assert "Traceback" in capsys.readouterr().err


@pytest.mark.network
@pytest.mark.anthropic
def test_init_fake_key_against_real_anthropic(tmp_path):
    """Real request with a fake key: expect a clean 401 line, exit 1, and no .env."""
    r = pug(tmp_path, "init", stdin_text="sk-ant-not-a-real-key\n")
    if "Couldn't reach the Anthropic API" in r.out:
        pytest.skip("Anthropic API unreachable")
    assert r.returncode == 1, r.out
    assert "Anthropic rejected the API key (401)" in r.out
    assert not (tmp_path / ".env").exists()


# --- refine / bark / run ----------------------------------------------------------

def test_refine_without_bone_map(bone):
    r = pug(bone, "refine")
    assert r.returncode == 1 and "No Bone Map for jp" in r.out


def test_bark_without_bone_map(bone):
    r = pug(bone, "bark")
    assert r.returncode == 1 and "No Bone Map for jp" in r.out


def test_run_without_cli(bone):
    r = pug(bone, "run", "get-post")
    assert r.returncode == 1 and "No generated CLI for jp" in r.out


@pytest.fixture(scope="module")
def ok_server():
    """Answers every GET with 200 [] so the smell test passes without the internet."""

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _bark_setup(root, base_url, plan=None):
    d = root / "bones" / "jp"
    d.mkdir(parents=True, exist_ok=True)
    (root / "bones" / "current").write_text("jp")
    (d / "bone_map.json").write_text(json.dumps(plan if plan is not None else json.loads(FIXTURE.read_text())))
    (d / "bark_config.json").write_text(json.dumps({"base_url": base_url, "auth_type": "none", "api_key_env": "API_KEY"}))
    return d


def test_smell_test_failure_exits_1(tmp_path):
    _bark_setup(tmp_path, "http://127.0.0.1:9")
    r = pug(tmp_path, "bark")
    assert r.returncode == 1, r.out
    assert r.out.count("Smell test failed") == 1
    assert "Huff" not in r.out


def test_smell_test_skipped_without_get(tmp_path):
    plan = [{"command": "create-post", "method": "POST", "path": "/posts", "flags": ["--title"]}]
    _bark_setup(tmp_path, "http://127.0.0.1:9", plan)
    r = pug(tmp_path, "bark", env=_env(PATH=str(tmp_path)))  # no go: stop after generation
    assert "Smell test: skipped (no GET endpoint in the Bone Map)" in r.out


def test_bark_without_go(tmp_path, ok_server):
    _bark_setup(tmp_path, ok_server)
    r = pug(tmp_path, "bark", env=_env(PATH=str(tmp_path)))
    assert r.returncode == 1, r.out
    assert "go is not on your PATH" in r.out and "Huff" not in r.out


needs_go = pytest.mark.skipif(shutil.which("go") is None, reason="go is not on PATH")


@needs_go
def test_bark_success_hint_and_stale_binary(tmp_path, ok_server):
    plan = json.loads(FIXTURE.read_text())
    plan.insert(0, plan.pop(1))  # get-post first, so the hint needs --id
    d = _bark_setup(tmp_path, ok_server, plan)
    r = pug(tmp_path, "bark")
    log = d / "cli" / "build.log"
    if log.exists() and ("dial tcp" in log.read_text() or "proxy.golang.org" in log.read_text()):
        pytest.skip("go could not download modules")
    assert r.returncode == 0, r.out
    assert "Huff! I did it" in r.out
    assert "pug run get-post --id <id>" in r.out and "web-search" not in r.out
    binary = d / "cli" / "bin" / "jp"
    assert binary.exists()

    # Break the Bone Map so Go fails while the old binary exists
    plan.append({"command": "get.post", "method": "GET", "path": "/posts/{id}", "flags": ["--id"]})
    (d / "bone_map.json").write_text(json.dumps(plan))
    r = pug(tmp_path, "bark")
    assert r.returncode == 1, r.out
    assert "The Go build failed" in r.out and "build.log" in r.out
    assert "Huff" not in r.out
    assert not binary.exists()

    # Fix it again: removed commands must not linger in cmd/
    plan.pop()
    (d / "bone_map.json").write_text(json.dumps(plan))
    r = pug(tmp_path, "bark")
    assert r.returncode == 0, r.out
    assert not (d / "cli" / "cmd" / "get.post.go").exists()
