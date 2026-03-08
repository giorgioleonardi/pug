"""Sniff a URL with Playwright: strip nav/footer, return clean Markdown."""

import threading
import time
from typing import Callable, Optional

import html2text
from playwright.sync_api import sync_playwright


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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
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

    If the operation takes longer than show_progress_after_seconds, progress_callback
    is invoked (e.g. to show a progress bar). It receives (running: bool) and is
    called with (True) when progress should show and (False) when done.
    """
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
