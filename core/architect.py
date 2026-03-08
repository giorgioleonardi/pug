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
6. Return ONLY a single JSON array. No markdown fences or explanation.

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
