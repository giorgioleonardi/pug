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
