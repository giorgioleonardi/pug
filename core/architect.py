"""
CHEW phase: AI interprets Markdown API docs and suggests a CLI structure (the "Bone Map").
- Query parameters and filters (e.g. userId) become flags (--user-id, --limit, --search).
- Nested routes (e.g. /posts/1/comments) become separate commands with path params as flags.
Output is a JSON Bone Map, persisted and displayed in a Rich Table.
"""

import json
import re
from pathlib import Path
from typing import Any, Optional

import anthropic

# Default .env location (caller's cwd)
def _load_api_key(env_path: Optional[Path] = None) -> str:
    path = (env_path or Path.cwd()) / ".env"
    if not path.exists():
        raise FileNotFoundError("No .env found. Run [bold tan]pug init[/] first. 🐶")
    text = path.read_text()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("ANTHROPIC_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise ValueError("ANTHROPIC_API_KEY not set in .env. Run [bold tan]pug init[/]. 🐶")


CHEW_SYSTEM = """You are a CLI architect. Given API documentation in Markdown, you produce a "Bone Map": a JSON array of CLI commands that map to the API.

Rules:
1. One row per endpoint or logical action. Include every distinct route from the docs.
2. Prefer read-only (GET) operations for the initial CLI. Include POST/PUT/PATCH/DELETE only when clearly documented; the tool will verify with read-only calls first.
3. Nested routes: list each as its own command. For paths with path params (e.g. /posts/1/comments, /users/1/posts), use a command name that describes the resource and add a flag for the parent ID (e.g. --post-id, --user-id). Example: GET /posts/1/comments -> command "list-post-comments", path "/posts/{id}/comments", flags ["--post-id"] (or "--id" for the post).
4. Filtering and query params: for any query parameter or filter (userId, limit, search, page, _limit, etc.), add a matching flag in kebab-case: userId -> --user-id, _limit -> --limit, postId -> --post-id. Include them in "flags" for that row. If the docs mention rate limits or pagination, add a note in "notes" (e.g. "Supports --limit; API may rate-limit").
5. Each item must have: "command" (lowercase-hyphen name), "method", "path" (use {id} or {userId} etc. for path params), "flags" (array of flag names like "--user-id", "--limit", "--post-id"), and optionally "notes" (one line).
6. API server and auth — read the docs carefully to determine the exact requirement:
   - If the docs specify the API base URL (e.g. "Server: https://...", "Base URL", or cURL host), output: BASE_URL: <url> (no trailing slash).
   - If the docs specify authentication, identify the scheme and output the matching lines:
     * Bearer token (Authorization: Bearer <token>) → AUTH_TYPE: bearer, and AUTH_ENV: <suggested env var e.g. API_TOKEN>.
     * API key in a header (X-API-Key, X-Subscription-Token, Api-Key, or any named header) → AUTH_TYPE: api_key_header, AUTH_HEADER: <exact header name from docs>, AUTH_ENV: <suggested env var>.
     * Basic auth (Authorization: Basic, or "username/password", "HTTP Basic") → AUTH_TYPE: basic, AUTH_ENV: <e.g. BASIC_AUTH or API_KEY> (value will be username:password).
   Put these lines before the JSON. If the docs do not specify server or auth, omit them.
7. Then output ONLY the JSON array. No markdown fences or extra explanation after the array.

Example (API key in custom header):
BASE_URL: https://api.search.brave.com/res
AUTH_TYPE: api_key_header
AUTH_HEADER: X-Subscription-Token
AUTH_ENV: BRAVE_SUBSCRIPTION_TOKEN
[{"command": "search", "method": "GET", "path": "/v1/web/search", "flags": ["--q"], "notes": "Web search"}]

Example (Bearer):
BASE_URL: https://api.example.com
AUTH_TYPE: bearer
AUTH_ENV: API_TOKEN
[{"command": "list-items", "method": "GET", "path": "/items", "flags": [], "notes": "List items"}]

Example (no auth):
[{"command": "list-posts", "method": "GET", "path": "/posts", "flags": ["--limit"], "notes": "List posts"}]"""


CHEW_MERGE_SYSTEM = """You are a CLI architect. You have an EXISTING Bone Map (JSON array of CLI commands) and NEW API documentation.

Your task: output a single JSON array that is the EXISTING commands plus any NEW commands from the new doc. Keep every existing command exactly as-is. Add only new commands that come from the new documentation (use the same format: command, method, path, flags, notes). Do not remove or change existing commands. If the new doc describes no new endpoints, output the existing array unchanged.

Output ONLY the combined JSON array. No BASE_URL or AUTH lines, no markdown fences, no explanation."""


def _parse_chew_config(lines: list[str]) -> tuple[list[str], dict[str, Any]]:
    """Extract BASE_URL, AUTH_TYPE, AUTH_HEADER, AUTH_ENV from start of response; return (remaining lines, config)."""
    config: dict[str, Any] = {}
    i = 0
    for line in lines:
        s = line.strip()
        if s.startswith("BASE_URL:"):
            config["base_url"] = s.split(":", 1)[1].strip().rstrip("/")
        elif s.startswith("AUTH_TYPE:"):
            config["auth_type"] = s.split(":", 1)[1].strip().lower()
        elif s.startswith("AUTH_HEADER:"):
            config["auth_header"] = s.split(":", 1)[1].strip()
        elif s.startswith("AUTH_ENV:"):
            config["api_key_env"] = s.split(":", 1)[1].strip() or "API_KEY"
        else:
            break
        i += 1
    return lines[i:], config


def chew(markdown: str, api_key: Optional[str] = None, env_path: Optional[Path] = None) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """
    Use Claude to analyze API docs Markdown and return (CLI plan, optional config).
    Config can have base_url, auth_type, auth_header, api_key_env when the docs specify them.
    """
    key = api_key or _load_api_key(env_path)
    client = anthropic.Anthropic(api_key=key)
    user_content = (
        "Analyze this API documentation and suggest a CLI structure. "
        "For any query parameters you see, add matching flags (e.g. limit -> --limit, search -> --search). "
        "If the docs specify an API server URL or auth (header name, Bearer), output BASE_URL / AUTH_TYPE / AUTH_HEADER / AUTH_ENV lines first, then the JSON array.\n\n"
        "---\n" + markdown
    )
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=CHEW_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
        elif isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")
    text = text.strip()
    if not text:
        raise ValueError(
            "Pug got an empty response from the model. The sniffed docs might be too short—try a URL with more API endpoints, or sniff again."
        )
    lines = text.splitlines()
    remaining, config = _parse_chew_config(lines)
    json_text = "\n".join(remaining).strip()
    # Normalize config: only return if we got at least base_url or auth_type
    if not config.get("base_url") and not config.get("auth_type"):
        config = None
    else:
        config.setdefault("auth_type", "none")
        config.setdefault("api_key_env", "API_KEY")
        if config.get("auth_type") == "api_key_header" and "auth_header" not in config:
            config["auth_header"] = "X-API-Key"
    # Try to get JSON from json_text
    for candidate in [
        json_text,
        re.sub(r"^```(?:json)?\s*", "", json_text).replace("```", "").strip(),
    ]:
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
            candidate = re.sub(r"\s*```\s*$", "", candidate).strip()
        match = re.search(r"\[[\s\S]*\]", candidate)
        if match:
            candidate = match.group(0)
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    else:
        raise ValueError(
            "Pug couldn't parse a Bone Map (no JSON array in the response). "
            "The docs might be too short or the page structure didn't scrape well—try a URL with more endpoints (e.g. jsonplaceholder.typicode.com) or run chew again."
        )
    if isinstance(data, list):
        plan = data
    elif isinstance(data, dict) and "commands" in data:
        plan = data["commands"]
    elif isinstance(data, dict) and "plan" in data:
        plan = data["plan"]
    else:
        plan = [data] if isinstance(data, dict) else []
    return plan, config


def chew_merge(
    markdown: str,
    existing_plan: list[dict[str, Any]],
    api_key: Optional[str] = None,
    env_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """
    Suggest new commands from the given doc and merge with existing_plan.
    Returns the combined Bone Map (existing + new). Config is not updated (caller keeps existing bark config).
    """
    key = api_key or _load_api_key(env_path)
    client = anthropic.Anthropic(api_key=key)
    existing_json = json.dumps(existing_plan, indent=2)
    user_content = (
        "EXISTING Bone Map (keep all of these unchanged):\n\n"
        f"{existing_json}\n\n"
        "---\n\n"
        "NEW API documentation (add any new commands from this; same JSON shape: command, method, path, flags, notes):\n\n"
        "---\n"
        + markdown
    )
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=CHEW_MERGE_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
        elif isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")
    text = text.strip()
    if not text:
        raise ValueError("Pug got an empty response during merge. Try again.")
    for candidate in [
        text,
        re.sub(r"^```(?:json)?\s*", "", text).replace("```", "").strip(),
    ]:
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
            candidate = re.sub(r"\s*```\s*$", "", candidate).strip()
        match = re.search(r"\[[\s\S]*\]", candidate)
        if match:
            candidate = match.group(0)
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    else:
        raise ValueError(
            "Pug couldn't parse the merged Bone Map (no JSON array). Try pug refine to add commands manually."
        )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "commands" in data:
        return data["commands"]
    if isinstance(data, dict) and "plan" in data:
        return data["plan"]
    return [data] if isinstance(data, dict) else []


def plan_to_bone_map_rows(plan: list[dict[str, Any]]) -> list[tuple[str, str, str, str, str]]:
    """Convert plan items to table rows: (command, method, path, flags, notes)."""
    rows = []
    for item in plan:
        command = item.get("command", "")
        method = item.get("method", "")
        path = item.get("path", "")
        flags = item.get("flags") or []
        flags_str = ", ".join(flags) if isinstance(flags, list) else str(flags)
        notes = item.get("notes") or ""
        rows.append((command, method, path, flags_str, notes))
    return rows


def save_bone_map(plan: list[dict[str, Any]], path: Path) -> None:
    """Persist the Bone Map as JSON (e.g. bones/<name>/bone_map.json)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")


REFINE_SYSTEM = """You are Pug, a helpful CLI architect. The user is refining a "Bone Map" (a JSON array of CLI commands for an API).

Current Bone Map (JSON array):
{bone_map_json}

When the user asks for changes (add/remove/rename commands, change flags, fix paths), reply briefly in character, then output the complete updated Bone Map as a JSON array inside a fenced block:
```json
[ ... ]
```

If the user is just asking a question or saying they're done, reply without outputting JSON. Only output a ```json block when the Bone Map should be updated. Keep the same structure: each object has "command", "method", "path", "flags" (array), "notes" (optional)."""


def refine_turn(
    user_message: str,
    conversation_history: list[dict[str, str]],
    bone_map: list[dict[str, Any]],
    api_key: Optional[str] = None,
    env_path: Optional[Path] = None,
) -> tuple[str, Optional[list[dict[str, Any]]]]:
    """
    One turn of refine chat. Returns (assistant_text, updated_bone_map or None).
    If the model outputs a JSON array in a fenced block, it is parsed and returned as updated_bone_map.
    """
    key = api_key or _load_api_key(env_path)
    client = anthropic.Anthropic(api_key=key)
    system = REFINE_SYSTEM.replace("{bone_map_json}", json.dumps(bone_map, indent=2))
    messages = conversation_history + [{"role": "user", "content": user_message}]
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system,
        messages=messages,
    )
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
        elif isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")
    text = text.strip()
    # Extract ```json ... ``` if present
    updated = None
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            raw = match.group(1).strip()
            updated = json.loads(raw)
            if isinstance(updated, list):
                pass
            elif isinstance(updated, dict) and "commands" in updated:
                updated = updated["commands"]
            elif isinstance(updated, dict) and "plan" in updated:
                updated = updated["plan"]
            else:
                updated = [updated] if isinstance(updated, dict) else None
        except json.JSONDecodeError:
            updated = None
    return text, updated


def validate_anthropic_key(env_path: Optional[Path] = None) -> bool:
    """PANT: Test if the Anthropic API key is valid (a treat or a trick?)."""
    key = _load_api_key(env_path)
    client = anthropic.Anthropic(api_key=key)
    client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=10,
        messages=[{"role": "user", "content": "Say OK"}],
    )
    return True
