"""Fetch article metadata (title, description) from arbitrary URLs.

Used by social readers to turn a raw URL extracted from a social post into a
FeedItem that the scorer can consume.
"""

import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from feed_reader import FeedItem
from local_first_common.url import clean_url, _TRACKING_PARAMS  # noqa: F401 — re-exported for consumers

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; content-discovery-agent/1.0; +https://github.com/jamalhansen/content-discovery-agent)"
}

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
) -> FeedItem | None:
    """Fetch a URL and extract title and description from its HTML meta tags.

    Skips URLs whose domain is in the default block list or in
    ``blocked_domains`` without making an HTTP request.

    Priority order:
      title:       og:title  → <title>
      description: og:description → <meta name="description">

    Args:
        url: The URL to fetch.
        blocked_domains: Additional domains to skip on top of the built-in list.
            Subdomain matching is supported — blocking "medium.com" also blocks
            "username.medium.com".

    Returns a FeedItem on success, or None if the fetch or parse fails.
    The ``source`` field is set to the URL's netloc (e.g. "simonwillison.net").
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

    try:
        resp = requests.get(url, timeout=8, headers=_HEADERS, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        # Catches requests.RequestException and urllib3.exceptions.LocationParseError
        # (raised for malformed hostnames like "agentguard.auto(...)") and any other
        # network-level error that escapes requests' own exception hierarchy.
        logger.warning("Failed to fetch %s: %s", url, e)
        return None

    content_type = resp.headers.get("Content-Type", "")
    if "html" not in content_type:
        logger.debug("Skipping non-HTML response for %s (Content-Type: %s)", url, content_type)
        return None

    try:
        soup = BeautifulSoup(resp.text, "html.parser")

        # Title: og:title → <title>
        og_title = soup.find("meta", attrs={"property": "og:title"})
        title = (og_title.get("content", "").strip() if og_title else "") or ""
        if not title:
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""

        if not title:
            logger.warning("No title found for %s — skipping", url)
            return None

        # Description: og:description → <meta name="description">
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        description = (og_desc.get("content", "").strip() if og_desc else "") or ""
        if not description:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            description = meta_desc.get("content", "").strip() if meta_desc else ""

        # Published date: article:published_time → datePublished (ISO 8601, truncated to date)
        pub_meta = (
            soup.find("meta", attrs={"property": "article:published_time"})
            or soup.find("meta", attrs={"name": "datePublished"})
            or soup.find("meta", attrs={"property": "og:article:published_time"})
        )
        published = ""
        if pub_meta:
            raw = pub_meta.get("content", "").strip()
            if raw:
                published = raw[:10]  # "2026-03-07T10:00:00Z" → "2026-03-07"

        source = urlparse(url).netloc

        return FeedItem(
            title=title,
            description=description,
            url=url,
            source=source,
            published=published,
        )

    except Exception as e:
        logger.warning("Failed to parse metadata for %s: %s", url, e)
        return None
