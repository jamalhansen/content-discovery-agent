"""Fetch article metadata from URLs found in social posts.

Provides ``FeedItem`` (the common article item representation) and
``fetch_article_metadata``, which wraps ``tracked_fetch`` so every URL attempt
is logged to the central ``fetch_log`` table.

Typical usage::

    from discovery.support.article_fetcher import fetch_article_metadata

    item = fetch_article_metadata(
        url,
        tool=_TOOL,  # the Tool this repo registers once, in orchestrator.py
        source_url=post_url,
        source_platform="bluesky",
    )
    if item:
        # use item.title, item.description, item.url, item.source, item.published
        ...
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from local_first_common import html
from local_first_common.tracking import Tool, tracked_fetch
from local_first_common.url import normalize_url

logger = logging.getLogger(__name__)

# Opt-in delegation to http-retriever-service instead of this module's own
# fetch/blocklist/extract/render pipeline. Unset by default -- local fetching
# stays the default until callers explicitly opt in per-deployment. See that
# service's tool doc (BrainSync #50) for why it exists: one warm Chromium
# instance shared across every caller instead of each tool installing its
# own Playwright, and one blocklist that doesn't drift across tool versions.
HTTP_RETRIEVER_URL = os.environ.get("HTTP_RETRIEVER_URL") or None

# Domains that never yield usable article content — skipped before any HTTP
# request is made. Two different reasons land here: Medium and its
# publication network reliably block scrapers or sit behind paywalls;
# discord.com is structurally incapable of it (an invite link is chat-app
# chrome, never a fetchable article body, confirmed 2026-09-13 via a
# thin-extraction capture that came back as 104 chars of "enable JavaScript").
_DEFAULT_BLOCKED_DOMAINS: frozenset[str] = frozenset(
    {
        "medium.com",
        "towardsdatascience.com",
        "betterprogramming.pub",
        "plainenglish.io",
        "levelup.gitconnected.com",
        "discord.com",
        "discord.gg",
    }
)


@dataclass
class FeedItem:
    """A fetched article with extracted metadata."""

    title: str
    description: str
    url: str
    source: str
    published: str = ""  # ISO date e.g. "2026-03-07", empty if unavailable
    found_at: str | None = None  # URL of the page/post where this link was first found
    search_term: str | None = None  # The term used to discover this link
    platform: str | None = None  # The platform where this link was discovered


def _is_blocked(netloc: str, blocked_domains: frozenset[str]) -> bool:
    """Return True if netloc matches any domain in the blocklist (exact or subdomain)."""
    host = netloc.lower().split(":")[0]  # strip port if present
    return any(host == domain or host.endswith("." + domain) for domain in blocked_domains)


_ENGAGEMENT_COUNT_RE = re.compile(r"^[\d.,]+[KMB]?$")
_HANDLE_RE = re.compile(r"^@\w+$")


def _derive_metadata_from_rendered_text(text: str) -> tuple[str, str]:
    """Best-effort (title, description) split from a rendered page's raw text.

    Used when a page's server-rendered HTML has no usable <meta> title at
    all (x.com serves none for individual tweets) but a real-browser render
    recovered the content. Social platforms share a rough shape: some fixed
    chrome, an "@handle" line, a run of engagement-count lines, then the real
    text. Keying off the handle line rather than matching specific chrome
    strings survives a UI copy change; it does not survive the platform
    dropping the handle-then-counts layout entirely. Worst case on a layout
    this doesn't recognize is a mediocre title built from the whole page,
    which still beats discarding a render that succeeded.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    handle_idx = next((i for i, line in enumerate(lines) if _HANDLE_RE.fullmatch(line)), None)
    if handle_idx is not None:
        rest = [line for line in lines[handle_idx + 1 :] if not _ENGAGEMENT_COUNT_RE.fullmatch(line)]
    else:
        rest = lines
    content = " ".join(rest) or text.strip()
    return content[:80].strip(), content[:500].strip()


def _try_render(url: str, renderer) -> str:
    """Best-effort rendered fetch. Returns "" on any failure, including a
    missing playwright install — rendering is a fallback, never a hard
    requirement, and the caller already has whatever the plain fetch found.
    """
    if renderer is None:
        from discovery.support.js_render import fetch_rendered_text

        renderer = fetch_rendered_text
    try:
        return (renderer(url) or "").strip()
    except Exception as e:  # noqa: BLE001 - rendering is a best-effort fallback, never a hard requirement
        logger.info("Rendered fetch failed for %s: %s: %s", url, type(e).__name__, e)
        return ""


def _fetch_via_retriever(
    url: str,
    retriever_url: str,
    tool_name: str | None,
    source_url: str | None,
    source_platform: str | None,
) -> tuple[str | None, str, str]:
    """POST to http-retriever-service and return (title, description, published).

    title is None on any failure (blocked, request error, non-200, or a
    thin result the service itself couldn't improve on) -- the caller
    treats that exactly like the "no title found" case in the local path.
    The service does its own fetch_log logging (via its JSONL log + import
    script), so this makes no tracked_fetch call of its own; passing
    tool_name/source_url/source_platform through keeps that log's
    attribution the same as if this had fetched locally.
    """
    import httpx

    headers = {}
    api_key = os.environ.get("HTTP_RETRIEVER_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.post(
            f"{retriever_url.rstrip('/')}/fetch",
            json={
                "url": url,
                "toolName": tool_name or None,
                "sourceUrl": source_url,
                "sourcePlatform": source_platform,
            },
            headers=headers,
            timeout=25.0,
        )
    except httpx.HTTPError as e:
        logger.warning("http-retriever-service request failed for %s: %s", url, e)
        return None, "", ""

    if response.status_code != 200:
        logger.debug("http-retriever-service returned %s for %s", response.status_code, url)
        return None, "", ""

    data = response.json()
    return data.get("title") or None, data.get("description") or "", data.get("publishedDate") or ""


def fetch_article_metadata(
    url: str,
    blocked_domains: frozenset[str] = frozenset(),
    tool: Tool | None = None,
    source_url: str | None = None,
    source_platform: str | None = None,
    search_term: str | None = None,
    session: Any | None = None,
    render_domains: frozenset[str] = frozenset(),
    renderer=None,
) -> FeedItem | None:
    """Fetch a URL and extract title and description from its HTML meta tags.

    Skips URLs whose domain is in the default block list or in
    ``blocked_domains`` without making an HTTP request.

    When ``tool`` is provided the attempt is logged to the central fetch_log
    table via ``tracked_fetch``. ``source_url`` is the social post where this
    link was found; ``source_platform`` is e.g. ``'bluesky'`` or ``'mastodon'``.

    If ``session`` is provided and has a ``mark_failed(url, status_code)`` method,
    it is called on fetch failure.

    ``render_domains`` names hosts known to serve no usable metadata to a
    plain fetch (x.com serves no <title> at all for a tweet page). When the
    plain fetch's title comes back empty and the URL's host is in this set, a
    real-browser render is attempted as a fallback and a title/description
    are derived from its text. Empty by default: rendering only happens when
    a caller opts in.
    """
    url = normalize_url(url)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        logger.debug("Skipping invalid URL: %s", url)
        return None

    netloc = parsed.netloc
    all_blocked = _DEFAULT_BLOCKED_DOMAINS | blocked_domains
    if _is_blocked(netloc, all_blocked):
        logger.debug("Skipping blocked domain: %s", netloc)
        return None

    _tool = tool or Tool(name="", id=None)

    if HTTP_RETRIEVER_URL:
        # The service does its own logging -- no tracked_fetch here, that
        # would double-log the same event under two rows.
        title, description, published = _fetch_via_retriever(
            url, HTTP_RETRIEVER_URL, _tool.name, source_url, source_platform
        )
        if not title:
            logger.warning("No title found for %s via http-retriever-service — skipping", url)
            if session and hasattr(session, "mark_failed"):
                session.mark_failed(url)
            return None
        return FeedItem(
            title=title,
            description=description,
            url=url,
            source=netloc,
            published=published,
            found_at=source_url,
            search_term=search_term,
            platform=source_platform,
        )

    with tracked_fetch(_tool, url, source_url=source_url, source_platform=source_platform) as fetch:
        if fetch.html is None:
            logger.warning("Failed to fetch %s: %s", url, fetch.error_message)
            if session and hasattr(session, "mark_failed"):
                session.mark_failed(url, fetch.http_status)
            return None

        try:
            metadata = html.extract_metadata(fetch.html)
        except Exception as e:  # noqa: BLE001 - untrusted third-party HTML, any parse failure should degrade to None
            logger.warning("Failed to parse metadata for %s: %s", url, e)
            if session and hasattr(session, "mark_failed"):
                session.mark_failed(url)
            return None

        title, description, published = metadata.title, metadata.description, metadata.published_date

        if not title and render_domains:
            host = netloc.lower().split(":")[0]
            host = host.removeprefix("www.")
            if host in render_domains:
                rendered = _try_render(url, renderer)
                if rendered:
                    title, description = _derive_metadata_from_rendered_text(rendered)

        if not title:
            logger.warning("No title found for %s — skipping", url)
            if session and hasattr(session, "mark_failed"):
                session.mark_failed(url)
            return None

        fetch.title = title
        source = urlparse(url).netloc

        return FeedItem(
            title=title,
            description=description,
            url=url,
            source=source,
            published=published,
            found_at=source_url,
            search_term=search_term,
            platform=source_platform,
        )
