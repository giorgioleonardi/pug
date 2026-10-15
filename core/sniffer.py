"""Sniff a URL with Playwright: strip nav/footer, return clean Markdown."""

import threading
import time
from typing import Callable, Optional

# Seconds to wait after load for JS-rendered API docs (e.g. OpenAPI/Swagger UIs)
SNIFF_WAIT_AFTER_LOAD = 3

from urllib.parse import urlparse

import html2text
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from core.errors import PugError

# Chromium network errors -> what to tell the user
_NET_ERRORS = {
    "ERR_NAME_NOT_RESOLVED": "DNS lookup failed (unknown domain)",
    "ERR_CONNECTION_REFUSED": "connection refused",
    "ERR_CONNECTION_RESET": "connection reset",
    "ERR_CONNECTION_CLOSED": "connection closed (the host may not exist or dropped the connection)",
    "ERR_UNSAFE_PORT": "Chromium refuses to load that port",
    "ERR_CONNECTION_TIMED_OUT": "connection timed out",
    "ERR_ADDRESS_UNREACHABLE": "address unreachable",
    "ERR_INTERNET_DISCONNECTED": "no internet connection",
    "ERR_CERT_": "TLS certificate error",
    "ERR_SSL_": "TLS error",
}


def check_url(url: str) -> None:
    """Reject anything that isn't a full http(s) URL before starting a browser."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        hint = f" Did you mean https://{url}?" if not parsed.scheme and "." in url else ""
        raise PugError(f"Invalid URL: {url} (use a full http:// or https:// URL).{hint}")


def _translate_playwright_error(e: Exception, url: str) -> PugError:
    text = str(e)
    if "Executable doesn't exist" in text or "playwright install" in text:
        return PugError("Chromium isn't installed. Run: playwright install chromium")
    for code, meaning in _NET_ERRORS.items():
        if code in text:
            return PugError(f"Couldn't load {url}: {meaning}.")
    if "invalid URL" in text or "Cannot navigate to invalid URL" in text:
        return PugError(f"Invalid URL: {url}")
    if "Timeout" in text:
        return PugError(f"Timed out loading {url} (30s).")
    first_line = text.strip().splitlines()[0] if text.strip() else type(e).__name__
    first_line = first_line.replace("Page.goto: ", "")
    return PugError(f"Couldn't load {url}: {first_line}")


def _remove_trash(page) -> None:
    """Remove nav, footer, and other clutter from the page via Playwright."""
    selectors = [
        "nav", "header", "footer",
        "[role='navigation']", "[role='banner']",
        "aside", "script", "style", "noscript", "iframe",
        ".nav", ".navbar", ".footer", ".sidebar",
    ]
    page.evaluate(
        """(selectors) => {
          selectors.forEach(sel => {
            try {
              document.querySelectorAll(sel).forEach(el => el.remove());
            } catch (e) {}
          });
        }""",
        selectors,
    )


def _sniff_impl(url: str) -> str:
    """Do the actual Playwright fetch and HTML->Markdown conversion."""
    try:
        return _sniff_page(url)
    except PlaywrightError as e:
        raise _translate_playwright_error(e, url) from e


def _sniff_page(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            # Wait for load so JS-rendered API docs have time to appear
            response = page.goto(url, wait_until="load", timeout=30000)
            if response is not None and response.status >= 400:
                raise PugError(f"{url} returned {response.status}{' ' + response.status_text if response.status_text else ''}.")
            # Give dynamic content (e.g. OpenAPI/Swagger UIs) a moment to render
            time.sleep(SNIFF_WAIT_AFTER_LOAD)
            _remove_trash(page)
            # Prefer main content: main, article, or body
            content = page.evaluate(
                """
                () => {
                  var el = document.querySelector('main') || document.querySelector('article') || document.body;
                  return el ? el.innerHTML : document.body.innerHTML;
                }
                """
            )
        finally:
            browser.close()

    if not content or not content.strip():
        return ""

    h2t = html2text.HTML2Text()
    h2t.ignore_links = False
    h2t.ignore_images = False
    h2t.body_width = 0
    return h2t.handle(content).strip()


def sniff(
    url: str,
    *,
    progress_callback: Optional[Callable[[bool], None]] = None,
    show_progress_after_seconds: float = 5.0,
) -> str:
    """
    Sniff a URL: load with Playwright, strip nav/footer/trash, return clean Markdown.
    Raises PugError with a one-line message for bad URLs, network errors, HTTP errors, or missing Chromium.

    If the operation takes longer than show_progress_after_seconds, progress_callback
    is invoked (e.g. to show a progress bar). It receives (running: bool) and is
    called with (True) when progress should show and (False) when done.
    """
    check_url(url)
    result: Optional[str] = None
    error: Optional[Exception] = None

    def run():
        nonlocal result, error
        try:
            result = _sniff_impl(url)
        except Exception as e:
            error = e

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    start = time.monotonic()
    progress_shown = False

    while thread.is_alive():
        elapsed = time.monotonic() - start
        if elapsed >= show_progress_after_seconds and progress_callback and not progress_shown:
            progress_shown = True
            progress_callback(True)
        time.sleep(0.1)

    if progress_callback and progress_shown:
        progress_callback(False)

    thread.join()
    if error:
        raise error
    return result or ""
