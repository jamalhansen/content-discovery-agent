"""Fetch article metadata (title, description) from arbitrary URLs.

Used by social readers to turn a raw URL extracted from a social post into a
FeedItem that the scorer can consume.
"""

import logging
from urllib.parse import urlparse

from ..feed_reader import FeedItem
from local_first_common import html
from local_first_common.tracking import Tool, tracked_fetch
from local_first_common.url import clean_url, _TRACKING_PARAMS  # noqa: F401 — re-exported for consumers

logger = logging.getLogger(__name__)

# Domains that reliably block scrapers or sit behind paywalls — skipped before
# any HTTP request is made. Covers Medium and its publication network.
# Users can add more via [social] blocked_domains in .content-discovery.toml.
_DEFAULT_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "medium.com",            # main platform + username.medium.com subdomains
    "towardsdatascience.com",
    "betterprogramming.pub",
    "plainenglish.io",       # catches ai.plainenglish.io, javascript.plainenglish.io, etc.
    "levelup.gitconnected.com",
})


def _is_blocked(netloc: str, blocked_domains: frozenset[str]) -> bool:
    """Return True if netloc matches any domain in the blocklist (exact or subdomain)."""
    host = netloc.lower().split(":")[0]  # strip port if present
    return any(
        host == domain or host.endswith("." + domain)
        for domain in blocked_domains
    )


def fetch_article_metadata(
    url: str,
    blocked_domains: frozenset[str] = frozenset(),
    tool: Tool | None = None,
    source_url: str | None = None,
    source_platform: str | None = None,
) -> FeedItem | None:
    """Fetch a URL and extract title and description from its HTML meta tags.

    Skips URLs whose domain is in the default block list or in
    ``blocked_domains`` without making an HTTP request.

    When ``tool`` is provided the attempt is logged to the central fetch_log
    table via ``tracked_fetch``. ``source_url`` is the social post where this
    link was found; ``source_platform`` is e.g. ``'bluesky'`` or ``'mastodon'``.
    """
    url = clean_url(url)
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
    with tracked_fetch(_tool, url, source_url=source_url, source_platform=source_platform) as fetch:
        if fetch.html is None:
            logger.warning("Failed to fetch %s: %s", url, fetch.error_message)
            return None

        try:
            metadata = html.extract_metadata(fetch.html)
        except Exception as e:
            logger.warning("Failed to parse metadata for %s: %s", url, e)
            return None

        if not metadata.title:
            logger.warning("No title found for %s — skipping", url)
            return None

        fetch.title = metadata.title
        source = urlparse(url).netloc

        return FeedItem(
            title=metadata.title,
            description=metadata.description,
            url=url,
            source=source,
            published=metadata.published_date,
        )
