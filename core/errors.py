"""Turn exceptions into one-line, actionable messages (used by main.py's top-level handler)."""

from typing import Optional

MODELS_URL = "https://docs.claude.com/en/docs/about-claude/models/overview"
KEYS_URL = "https://console.anthropic.com/settings/keys"


class PugError(Exception):
    """An expected failure with a ready-to-print, one-line message."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def _anthropic_message(e: Exception) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return str(getattr(e, "message", "") or e)


def friendly_error(e: BaseException, model: Optional[str] = None) -> Optional[str]:
    """Return a one-line message for known errors, or None if unknown."""
    if isinstance(e, PugError):
        return str(e)
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        anthropic = None
    if anthropic is not None:
        if isinstance(e, anthropic.AuthenticationError):
            return f"Anthropic rejected the API key (401). Check it at {KEYS_URL}, then run pug init --force or set ANTHROPIC_API_KEY."
        if isinstance(e, anthropic.PermissionDeniedError):
            return f"Anthropic refused the request (403): {_anthropic_message(e)}"
        if isinstance(e, anthropic.NotFoundError):
            name = f"'{model}' " if model else ""
            return f"Anthropic doesn't know the model {name}(404). Set PUG_MODEL to a current model id (see {MODELS_URL})."
        if isinstance(e, anthropic.RateLimitError):
            return "Anthropic rate limit hit (429). Wait a minute and try again."
        if isinstance(e, anthropic.APITimeoutError):
            return "The request to Anthropic timed out. Check your network and try again."
        if isinstance(e, anthropic.APIConnectionError):
            return "Couldn't reach the Anthropic API (connection error). Check your network and try again."
        if isinstance(e, anthropic.APIStatusError):
            status = getattr(e, "status_code", None)
            if status == 529:
                return "Anthropic is overloaded right now (529). Try again in a minute."
            if status and status >= 500:
                return f"Anthropic had a server error ({status}). Try again in a minute."
            return f"Anthropic rejected the request ({status}): {_anthropic_message(e)}"
    return None
