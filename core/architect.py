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
2. Nested routes: list each as its own command. For paths with path params (e.g. /posts/1/comments, /users/1/posts), use a command name that describes the resource and add a flag for the parent ID (e.g. --post-id, --user-id). Example: GET /posts/1/comments -> command "list-post-comments", path "/posts/{id}/comments", flags ["--post-id"] (or "--id" for the post).
3. Filtering and query params: for any query parameter or filter (userId, limit, search, page, _limit, etc.), add a matching flag in kebab-case: userId -> --user-id, _limit -> --limit, postId -> --post-id. Include them in "flags" for that row.
4. Each item must have: "command" (lowercase-hyphen name), "method", "path" (use {id} or {userId} etc. for path params), "flags" (array of flag names like "--user-id", "--limit", "--post-id"), and optionally "notes" (one line).
5. Return ONLY a single JSON array. No markdown fences or explanation.

Example format:
[
  {"command": "list-posts", "method": "GET", "path": "/posts", "flags": ["--user-id", "--limit"], "notes": "List all posts, optional filter by user"},
  {"command": "get-post", "method": "GET", "path": "/posts/{id}", "flags": ["--id"], "notes": "Get a single post"},
  {"command": "list-post-comments", "method": "GET", "path": "/posts/{id}/comments", "flags": ["--post-id"], "notes": "Comments for a post"}
]"""


def chew(markdown: str, api_key: Optional[str] = None, env_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """
    Use Claude to analyze API docs Markdown and return a CLI plan.
    Query params in the docs are turned into suggested flags (--limit, --search, etc.).
    """
    key = api_key or _load_api_key(env_path)
    client = anthropic.Anthropic(api_key=key)
    user_content = (
        "Analyze this API documentation and suggest a CLI structure. "
        "For any query parameters you see, add matching flags (e.g. limit -> --limit, search -> --search). "
        "Return only a JSON array of objects with keys: command, method, path, flags (array), notes (optional).\n\n"
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
    # Strip optional markdown code fence
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    data = json.loads(text)
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
    """Persist the Bone Map as JSON (e.g. .pug/bone_map.json)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")


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
