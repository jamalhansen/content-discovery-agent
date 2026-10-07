"""Render a page in a real browser, for content behind client-side JS.

A plain HTTP fetch sees whatever the server sends before any script runs. For
most sites that's the whole page; for a genuine client-rendered wall (x.com
serves a "JavaScript is not available" noscript page to any client that
doesn't execute JS) it's nearly nothing, and no amount of smarter HTML parsing
recovers content that was never in the response.

Optional dependency: install with `local-first-common[playwright]` and run
`playwright install chromium` once. The import happens inside the function,
not at module load, so a tool that never calls this never needs the browser
installed at all — importing this module is always safe.
"""

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RenderUnavailable(Exception):
    """Playwright is not installed, or its browser binary is missing."""


def fetch_rendered_text(
    url: str,
    timeout_ms: int = 20_000,
    settle_ms: int = 3_000,
    sync_playwright_fn=None,
) -> str:
    """Load ``url`` in headless Chromium and return the rendered page's text.

    ``settle_ms`` is a fixed wait after ``domcontentloaded`` rather than a
    smarter "network idle" signal, because feed sites keep background
    connections (analytics, ads) open indefinitely and network-idle would
    time out on exactly the pages this function exists to handle.

    Raises RenderUnavailable if playwright is not installed. Any navigation or
    browser failure propagates as whatever playwright itself raises; this is a
    fallback path and callers are expected to catch broadly, the same as they
    already do around a plain fetch.
    """
    if sync_playwright_fn is None:
        try:
            from playwright.sync_api import (  # pyright: ignore[reportMissingImports]  # optional extra
                sync_playwright as sync_playwright_fn,
            )
        except ImportError as e:
            raise RenderUnavailable(
                "playwright is not installed. Install with: "
                "uv add 'local-first-common[playwright]' && playwright install chromium"
            ) from e

    with sync_playwright_fn() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(settle_ms)
            return page.inner_text("body")
        finally:
            browser.close()


def fetch_rendered_html(
    url: str,
    timeout_ms: int = 20_000,
    settle_ms: int = 3_000,
    sync_playwright_fn=None,
) -> str:
    """Load ``url`` in headless Chromium and return the rendered page's HTML.

    Sibling to fetch_rendered_text. That one returns raw visible text, tuned
    for a caller deriving title/description from a social post's handle-then-
    counts layout. This one returns HTML so a caller that wants proper
    content extraction can run it through html.extract_main_content the same
    way a plain fetch's response already is -- inner_text("body") captures
    nav/footer/ad chrome right along with the actual content, which
    extract_main_content is specifically built to strip out.

    Raises RenderUnavailable if playwright is not installed.
    """
    if sync_playwright_fn is None:
        try:
            from playwright.sync_api import (  # pyright: ignore[reportMissingImports]  # optional extra
                sync_playwright as sync_playwright_fn,
            )
        except ImportError as e:
            raise RenderUnavailable(
                "playwright is not installed. Install with: "
                "uv add 'local-first-common[playwright]' && playwright install chromium"
            ) from e

    with sync_playwright_fn() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(settle_ms)
            return page.content()
        finally:
            browser.close()


def host_of(url: str) -> str:
    """Return the lowercased hostname of ``url``, without a leading ``www.``.

    Shared by every caller that matches a URL against a configured domain set,
    so "x.com" and "www.x.com" are treated as the same domain everywhere.
    """
    host = urlparse(url).netloc.lower()
    host = host.removeprefix("www.")
    return host
