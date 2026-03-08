"""
BARK: System Compiler — Go CLI (Cobra), Agent Context (CLAUDE.md, SKILL.md), MCP, and Smell Test.

Reads .pug/bone_map.json and optionally .pug/bark_config.json (base_url, auth).
Runs a smell test (real API call) before generating; on failure, supports Refine Chat.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

# Optional: use requests for smell test (keep dependency light; we already have it in requirements)
try:
    import requests
except ImportError:
    requests = None


def _command_to_method_name(command: str) -> str:
    """list-post-comments -> list_post_comments"""
    return command.replace("-", "_")


def _flag_to_param_name(flag: str) -> str:
    """--post-id -> post_id"""
    return flag.lstrip("-").replace("-", "_")


def _path_param_names(path: str) -> list[str]:
    """Extract {id}, {userId} etc. from path in order."""
    return re.findall(r"\{(\w+)\}", path)


def _build_method_info(entry: dict[str, Any]) -> dict[str, Any]:
    """Turn a bone_map entry into method signature and request logic."""
    command = entry.get("command", "")
    method = (entry.get("method") or "GET").upper()
    path = entry.get("path", "")
    flags = entry.get("flags") or []

    method_name = _command_to_method_name(command)
    path_param_names = _path_param_names(path)

    param_names: list[str] = []
    for i, pname in enumerate(path_param_names):
        if i < len(flags):
            param_names.append(_flag_to_param_name(flags[i]))
        else:
            param_names.append(pname.replace("-", "_"))

    path_flag_count = len(path_param_names)
    query_flags = flags[path_flag_count:] if len(flags) > path_flag_count else []
    query_params = [_flag_to_param_name(f) for f in query_flags]

    return {
        "method_name": method_name,
        "command": command,
        "http_method": method,
        "path": path,
        "path_param_names": path_param_names,
        "param_names": param_names,
        "query_params": query_params,
        "has_body": method in ("POST", "PUT", "PATCH"),
        "notes": entry.get("notes") or "",
    }


def load_bone_map(path: Path) -> list[dict[str, Any]]:
    """Load and parse .pug/bone_map.json."""
    if not path.exists():
        raise FileNotFoundError(f"Bone Map not found: {path}. Run [bold tan]pug chew[/] first. 🐶")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("bone_map.json must be a JSON array")
    return data


# --- Bark config (base_url, auth) ---
BARK_CONFIG_PATH = Path(".pug/bark_config.json")
LAST_SNIFF_URL_PATH = Path(".pug/last_sniff_url")


def load_bark_config(pug_dir: Path) -> dict[str, Any]:
    """Load bark config; merge with last_sniff_url if present."""
    base_url = None
    auth_type = "none"
    api_key_env = "API_KEY"
    auth_header = "X-API-Key"

    if (pug_dir / "last_sniff_url").exists():
        base_url = (pug_dir / "last_sniff_url").read_text(encoding="utf-8").strip()
    config_path = pug_dir / "bark_config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            base_url = data.get("base_url") or base_url
            auth_type = data.get("auth_type", "none")
            api_key_env = data.get("api_key_env", "API_KEY")
            auth_header = data.get("auth_header", "X-API-Key")
        except Exception:
            pass
    return {
        "base_url": base_url or "https://api.example.com",
        "auth_type": auth_type,
        "api_key_env": api_key_env,
        "auth_header": auth_header,
    }


def save_bark_config(
    pug_dir: Path,
    base_url: str,
    auth_type: str = "none",
    api_key_env: str = "API_KEY",
    auth_header: Optional[str] = None,
) -> None:
    """Persist bark config for next run."""
    pug_dir.mkdir(parents=True, exist_ok=True)
    payload = {"base_url": base_url, "auth_type": auth_type, "api_key_env": api_key_env}
    if auth_header:
        payload["auth_header"] = auth_header
    (pug_dir / "bark_config.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


# --- Smell test (real API call) ---
def smell_test(
    bone_map: list[dict[str, Any]],
    base_url: str,
    auth_type: str = "none",
    api_key_env: str = "API_KEY",
    auth_header: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Run a real GET request against the API to verify base_url and auth.
    Picks the first GET entry that has no path params (or uses id=1).
    auth_header: for api_key_header, the header name (e.g. X-Subscription-Token). Default X-API-Key.
    Returns (success, error_message).
    """
    if not requests:
        return True, ""  # skip if no requests
    base_url = base_url.rstrip("/")
    # Prefer a simple GET without path params
    get_entries = [e for e in bone_map if (e.get("method") or "GET").upper() == "GET"]
    for entry in get_entries:
        path = entry.get("path", "")
        param_names = _path_param_names(path)
        if not param_names:
            # Simple path like /posts
            url = urljoin(base_url + "/", path.lstrip("/"))
            break
        # Use first GET with path param and substitute 1
        url = path
        for p in param_names:
            url = url.replace("{" + p + "}", "1", 1)
        url = urljoin(base_url + "/", url.lstrip("/"))
        break
    else:
        return True, ""  # no GET to test

    headers = {}
    if auth_type == "bearer":
        import os
        token = os.environ.get(api_key_env) or os.environ.get("BEARER_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key_header":
        import os
        key = os.environ.get(api_key_env)
        if key:
            header_name = auth_header or "X-API-Key"
            headers[header_name] = key

    try:
        r = requests.get(url, headers=headers or None, timeout=15)
        if r.status_code >= 400:
            return False, f"Smell test failed: {url} returned {r.status_code} {r.reason}"
        return True, ""
    except requests.RequestException as e:
        return False, f"Smell test failed: {url} — {e}"


# --- Project name from API base URL ---
def _base_url_to_project_name(base_url: str) -> str:
    """Derive a directory/project name from the API base URL (e.g. spotify-cli, jsonplaceholder-typicode-cli)."""
    try:
        parsed = urlparse(base_url)
        netloc = (parsed.netloc or parsed.path or "api").lower()
        # drop port if present
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        # api.spotify.com -> api-spotify-com; jsonplaceholder.typicode.com -> jsonplaceholder-typicode-com
        name = re.sub(r"[^a-z0-9.-]", "", netloc.replace(".", "-")).strip("-") or "api"
        return f"{name}-cli" if not name.endswith("-cli") else name
    except Exception:
        return "api-cli"


# --- Go/Cobra project generation ---
def _go_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def generate_go_project(bone_map: list[dict[str, Any]], config: dict[str, Any], out_dir: Path) -> None:
    """Generate Go module with Cobra: go.mod, main.go, cmd/root.go, cmd/<command>.go; build to bin/<cli_name>."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cmd").mkdir(parents=True, exist_ok=True)
    (out_dir / "bin").mkdir(parents=True, exist_ok=True)

    cli_name = out_dir.name
    env_prefix = cli_name.upper().replace("-", "_")

    base_url = config.get("base_url", "https://api.example.com")
    auth_type = config.get("auth_type", "none")
    api_key_env = config.get("api_key_env", "API_KEY")
    auth_header = config.get("auth_header") or "X-API-Key"

    # go.mod
    (out_dir / "go.mod").write_text(f"""module {cli_name}

go 1.21

require github.com/spf13/cobra v1.8.0
""", encoding="utf-8")

    # main.go
    (out_dir / "main.go").write_text(f"""package main

import "{cli_name}/cmd"

func main() {{
\tcmd.Execute()
}}
""", encoding="utf-8")

    # cmd/root.go: root command with --base-url, --bearer, --api-key
    root_go = f'''package cmd

import (
\t"fmt"
\t"net/http"
\t"os"

\t"github.com/spf13/cobra"
)

var (
\tbaseURL   string
\tbearer    string
\tapiKey    string
\tauthType  string
)

var rootCmd = &cobra.Command{{
\tUse:   "{cli_name}",
\tShort: "API CLI generated by PUG bark",
}}

func init() {{
\trootCmd.PersistentFlags().StringVar(&baseURL, "base-url", getEnv("{env_prefix}_BASE_URL", ""), "API base URL")
\trootCmd.PersistentFlags().StringVar(&bearer, "bearer", getEnv("{env_prefix}_BEARER_TOKEN", ""), "Bearer token")
\trootCmd.PersistentFlags().StringVar(&apiKey, "api-key", getEnv("{api_key_env}", ""), "API key / token")
\trootCmd.PersistentFlags().StringVar(&authType, "auth", getEnv("{env_prefix}_AUTH", "none"), "Auth: none, bearer, api_key_header")
}}

func getEnv(key, def string) string {{
\tif v := os.Getenv(key); v != "" {{
\t\treturn v
\t}}
\treturn def
}}

func Execute() {{
\tif err := rootCmd.Execute(); err != nil {{
\t\tos.Exit(1)
\t}}
}}

func doRequest(method, path string, query map[string]string, body []byte) (*http.Response, error) {{
\tif baseURL == "" {{
\t\treturn nil, fmt.Errorf("base-url required (set {env_prefix}_BASE_URL or --base-url)")
\t}}
\turl := baseURL + path
\treq, err := http.NewRequest(method, url, nil)
\tif err != nil {{
\t\treturn nil, err
\t}}
\tif authType == "bearer" && bearer != "" {{
\t\treq.Header.Set("Authorization", "Bearer "+bearer)
\t}}
\tif authType == "api_key_header" && apiKey != "" {{
\t\treq.Header.Set("{auth_header}", apiKey)
\t}}
\tq := req.URL.Query()
\tfor k, v := range query {{
\t\tif v != "" {{
\t\t\tq.Set(k, v)
\t\t}}
\t}}
\treq.URL.RawQuery = q.Encode()
\treturn http.DefaultClient.Do(req)
}}
'''
    (out_dir / "cmd" / "root.go").write_text(root_go, encoding="utf-8")

    for entry in bone_map:
        _gen_one_go_cmd(entry, out_dir)

    try:
        subprocess.run(["go", "mod", "tidy"], cwd=out_dir, capture_output=True, timeout=30)
        subprocess.run(["go", "build", "-o", f"bin/{cli_name}", "."], cwd=out_dir, capture_output=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _gen_one_go_cmd(entry: dict[str, Any], out_dir: Path) -> None:
    info = _build_method_info(entry)
    cmd_name = info["command"]
    use_name = cmd_name.replace("_", "-")
    short = (info["notes"] or info["path"])[:60].replace('"', '\\"')
    path_tpl = info["path"]
    path_params = info["path_param_names"]
    param_names = info["param_names"]
    query_params = info["query_params"]
    http_m = info["http_method"]

    go_path_expr = path_tpl
    for p in path_params:
        go_path_expr = go_path_expr.replace("{" + p + "}", "%s", 1)
    fmt_args = ", ".join(param_names) if param_names else ""
    if fmt_args:
        path_sprintf = f'fmt.Sprintf("{_go_escape(go_path_expr)}", {fmt_args})'
    else:
        path_sprintf = f'"{_go_escape(path_tpl)}"'

    all_flag_vars = param_names + query_params
    var_decls = "\n".join(f'\t{p} string' for p in all_flag_vars) if all_flag_vars else "\t_ string"
    flags_code = []
    for p in param_names:
        flag_name = p.replace("_", "-")
        flags_code.append(f'\t{info["method_name"]}Cmd.Flags().StringVar(&{p}, "{flag_name}", "", "path param")')
    for q in query_params:
        flag_name = q.replace("_", "-")
        flags_code.append(f'\t{info["method_name"]}Cmd.Flags().StringVar(&{q}, "{flag_name}", "", "query param")')

    run_lines = [
        "\t\tpath := " + path_sprintf,
        "\t\tquery := map[string]string{}",
    ]
    for q in query_params:
        run_lines.append(f'\t\tquery["{q}"] = {q}')
    run_lines.append('\t\tresp, err := doRequest("' + http_m + '", path, query, nil)')
    run_lines.append("\t\tif err != nil { fmt.Fprintln(os.Stderr, err); os.Exit(1) }")
    run_lines.append("\t\tdefer resp.Body.Close()")
    run_lines.append("\t\tfmt.Println(resp.Status)")
    run_lines.append("\t\tio.Copy(os.Stdout, resp.Body)")
    run_body = "\n".join(run_lines)
    flags_block = "\n".join(flags_code)

    vars_block = f'\nvar (\n{var_decls}\n)\n\n' if all_flag_vars else '\n'
    cmd_go = f'''package cmd

import (
\t"fmt"
\t"io"
\t"os"

\t"github.com/spf13/cobra"
){vars_block}var {info["method_name"]}Cmd = &cobra.Command{{
\tUse:   "{use_name}",
\tShort: "{_go_escape(short)}",
\tRun: func(cmd *cobra.Command, args []string) {{
{run_body}
\t}},
}}

func init() {{
{flags_block}
\trootCmd.AddCommand({info["method_name"]}Cmd)
}}
'''
    (out_dir / "cmd" / f"{info['method_name']}.go").write_text(cmd_go, encoding="utf-8")


# --- CLAUDE.md and SKILL.md ---
def generate_claude_md(bone_map: list[dict[str, Any]], base_url: str, cli_name: str) -> str:
    """Agent context: describe each command and data types for Claude."""
    lines = [
        f"# API CLI ({cli_name}) — Agent Context",
        "",
        f"Base URL: `{base_url}`",
        "",
        "## Commands",
        "",
    ]
    for entry in bone_map:
        info = _build_method_info(entry)
        path = entry.get("path", "")
        method = (entry.get("method") or "GET").upper()
        notes = entry.get("notes") or ""
        flags = entry.get("flags") or []
        lines.append(f"### `{cli_name} {info['command']}`")
        lines.append(f"- **Method:** {method} `{path}`")
        lines.append(f"- **Description:** {notes}")
        lines.append(f"- **Flags:** " + ", ".join(flags) if flags else "- **Flags:** (none)")
        if info["path_param_names"]:
            lines.append("- **Path params:** " + ", ".join(info["path_param_names"]))
        if info["query_params"]:
            lines.append("- **Query params:** " + ", ".join(info["query_params"]))
        lines.append("")
    return "\n".join(lines)


def generate_skill_md(bone_map: list[dict[str, Any]], base_url: str, cli_name: str) -> str:
    """SKILL.md for Cursor: what each tool does and data types."""
    lines = [
        f"# {cli_name} API Skill",
        "",
        "Use this skill when the user wants to call the API compiled by PUG.",
        "",
        f"**Base URL:** `{base_url}`",
        "",
        "## Tools (Commands)",
        "",
    ]
    for entry in bone_map:
        info = _build_method_info(entry)
        lines.append(f"- **{info['command']}**: {info['notes']}. HTTP {info['http_method']} {entry.get('path', '')}. ")
        lines.append(f"  Path params: {info['path_param_names']}. Query/filters: {info['query_params']}.")
        lines.append("")
    return "\n".join(lines)


# --- MCP ---
def generate_mcp_manifest(project_dir: Path, base_url: str, cli_name: str) -> str:
    """Generate mcp.json so this API can be registered in Cursor or Claude Desktop."""
    project_dir = Path(project_dir)
    mcp_path = (project_dir / "mcp-server.cjs").resolve()
    env_prefix = cli_name.upper().replace("-", "_")
    server_name = cli_name.replace("-", "_") + "_api"
    mcp = {
        "mcpServers": {
            server_name: {
                "command": "node",
                "args": [str(mcp_path)],
                "env": {
                    f"{env_prefix}_BASE_URL": base_url,
                },
            }
        }
    }
    return json.dumps(mcp, indent=2)


def generate_mcp_server_script(
    bone_map: list[dict[str, Any]], project_dir: Path, cli_name: str, config: Optional[dict[str, Any]] = None
) -> str:
    """Generate a Node MCP server (mcp-server.cjs) that exposes each endpoint as a tool."""
    config = config or {}
    tools_desc = []
    for entry in bone_map:
        info = _build_method_info(entry)
        # pathParams: names in path e.g. ["id"]; we need param_names for arg lookup (e.g. post_id)
        tools_desc.append((info["command"], info["notes"], info["http_method"], info["path"], info["path_param_names"], info["param_names"], info["query_params"]))
    env_prefix = cli_name.upper().replace("-", "_")
    api_key_env = config.get("api_key_env", "API_KEY")
    auth_header = config.get("auth_header", "X-API-Key")
    # Simple CJS script: env block as f-string, rest as plain string (JS uses { everywhere)
    script_head = f"""// Generated by PUG bark — MCP server for {cli_name} API
const http = require("http");
const https = require("https");

const baseURL = process.env.{env_prefix}_BASE_URL || "";
const bearer = process.env.{env_prefix}_BEARER_TOKEN || "";
const apiKey = process.env.{api_key_env} || "";

"""
    script = script_head + """
function request(method, path, query, body, cb) {
  const url = new URL(path, baseURL);
  Object.entries(query || {}).forEach(([k, v]) => { if (v) url.searchParams.set(k, v); });
  const opts = { method, headers: {} };
  if (bearer) opts.headers["Authorization"] = "Bearer " + bearer;
  if (apiKey) opts.headers["__AUTH_HEADER__"] = apiKey;
  const lib = url.protocol === "https:" ? https : http;
  const req = lib.request(url, opts, (res) => {
    let data = "";
    res.on("data", (c) => (data += c));
    res.on("end", () => cb(null, { status: res.statusCode, body: data }));
  });
  req.on("error", cb);
  if (body) req.write(body);
  req.end();
}

const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch (e) { return; }
  if (msg.method === "tools/list") {
    const tools = [
""" + ",\n".join(
        f'      {{ name: "{c}", description: "{n.replace(chr(34), chr(92)+chr(34))[:200]}" }}'
        for c, n, *_ in tools_desc
    ) + '''
    ];
    console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { tools } }));
  } else if (msg.method === "tools/call" && msg.params && msg.params.name) {
    const name = msg.params.name;
    const args = msg.params.arguments || {};
    // Route to the right endpoint (simplified: map name to path/method)
    const map = {
''' + ",\n".join(
        f'        "{c}": {{ method: "{m}", path: "{_go_escape(p)}", pathParamNames: {json.dumps(pp)}, paramNames: {json.dumps(pnames)}, queryParams: {json.dumps(qp)} }}'
        for c, _, m, p, pp, pnames, qp in tools_desc
    ) + '''
    };
    const spec = map[name];
    if (!spec) {
      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, error: { code: -32602, message: "Unknown tool" } }));
      return;
    }
    let path = spec.path;
    for (let i = 0; i < spec.pathParamNames.length; i++) {
      const key = spec.paramNames[i] || spec.pathParamNames[i];
      const v = args[key] || args[key.replace("_", "-")];
      path = path.replace("{" + spec.pathParamNames[i] + "}", encodeURIComponent(v || ""));
    }
    const query = {};
    for (const k of spec.queryParams) {
      const v = args[k] || args[k.replace("_", "-")];
      if (v) query[k] = v;
    }
    request(spec.method, path, query, null, (err, res) => {
      if (err) {
        console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, error: { code: -32603, message: String(err) } }));
        return;
      }
      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { content: [{ type: "text", text: res.body }] } }));
    });
  } else {
    console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: {} }));
  }
});
'''
    return script.replace("__AUTH_HEADER__", auth_header)


# --- Orchestration ---
def bark(
    bone_map_path: Path,
    pug_dir: Path,
    project_name: Optional[str] = None,
    *,
    skip_smell_test: bool = False,
    refine_chat_on_fail: Optional[Callable[..., Any]] = None,
) -> Path:
    """
    System compiler: smell test -> [refine chat if fail] -> generate Go CLI, CLAUDE.md, SKILL.md, mcp.json, MCP server.
    project_name: output directory (e.g. spotify-cli). If None, derived from API base URL.
    refine_chat_on_fail(err, pug_dir, config) returns:
      True = continue to generate anyway; False = abort;
      dict with "retry" key = config was updated, reload and retry smell test.
    Returns the generated project directory.
    """
    bone_map = load_bone_map(bone_map_path)
    config = load_bark_config(pug_dir)
    base_url = config["base_url"]
    auth_type = config["auth_type"]
    api_key_env = config["api_key_env"]

    if project_name is None:
        project_name = _base_url_to_project_name(base_url)
    out_dir = Path(project_name)
    cli_name = out_dir.name

    auth_header = config.get("auth_header")
    if not skip_smell_test:
        while True:
            ok, err = smell_test(bone_map, base_url, auth_type, api_key_env, auth_header=auth_header)
            if ok:
                break
            if not refine_chat_on_fail:
                raise RuntimeError(err)
            result = refine_chat_on_fail(err, pug_dir, config)
            if result is True:
                break
            if result is False:
                raise SystemExit(1)
            if isinstance(result, dict) and result.get("retry"):
                config = load_bark_config(pug_dir)
                base_url = config["base_url"]
                auth_type = config["auth_type"]
                api_key_env = config["api_key_env"]
                auth_header = config.get("auth_header")
                continue
            raise SystemExit(1)

    generate_go_project(bone_map, config, out_dir)
    (out_dir / "CLAUDE.md").write_text(generate_claude_md(bone_map, base_url, cli_name), encoding="utf-8")
    (out_dir / "SKILL.md").write_text(generate_skill_md(bone_map, base_url, cli_name), encoding="utf-8")
    (out_dir / "mcp.json").write_text(generate_mcp_manifest(out_dir, base_url, cli_name), encoding="utf-8")
    mcp_script = generate_mcp_server_script(bone_map, out_dir, cli_name, config)
    (out_dir / "mcp-server.cjs").write_text(mcp_script, encoding="utf-8")
    return out_dir
