"""Discover new candidate articles by mining outbound links from your own
kept history, as a source of genuinely new ideas that a fixed RSS list can't
provide on its own.

An RSS-only source list can only ever resurface things from authors already
on it -- it's structurally incapable of introducing a source you don't
already follow. Bluesky/Mastodon keyword search was the other candidate for
open-ended discovery and got dropped 2026-09-05 for a real reason: 2.4% keep
rate vs. RSS's 8.2%, with half the keywords never returning a single item.

The alternative here: an article you already trusted enough to keep links to
other things, and that's higher-signal than a random keyword hit. Citation
candidates go through the exact same score/threshold/routing path as every
other source (see orchestrator.run_discovery) -- this module only finds
links, it never decides anything is worth keeping and never adds a feed.
Each candidate is tagged platform="citations" with source=<its own domain>,
so a domain that keeps producing kept items stands out in `discover
report`'s per-source stats as a raw hostname (not a configured feed name) --
that's the signal to manually promote it to a real feed, the same
evidence-based way mastodon/bluesky got removed.
"""
import logging
from urllib.parse import urlparse

from local_first_common.article_fetcher import FeedItem, _is_blocked, fetch_article_metadata
from local_first_common.html import extract_outbound_links
from local_first_common.http import fetch_url
from local_first_common.url import normalize_url

logger = logging.getLogger(__name__)


def _registrable_domain(netloc: str) -> str:
    """Good-enough same-site check for excluding self-links, not a public-suffix parse."""
    host = netloc.lower().split(":")[0].removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def discover_citation_candidates(
    kept_items: list[dict],
    *,
    blocked_domains: frozenset[str] = frozenset(),
    max_links_per_item: int = 8,
    page_fetcher=None,
    metadata_fetcher=None,
) -> list[FeedItem]:
    """Turn outbound links from kept articles' bodies into candidate FeedItems.

    ``kept_items`` need only ``url`` and ``title`` keys (a store.get_recent_kept
    row is exactly this shape). Self-links (same registrable domain as the
    origin) and already-blocked domains are dropped before a metadata fetch
    is attempted, since that fetch is a live HTTP request per candidate.
    ``page_fetcher`` and ``metadata_fetcher`` are injectable for testing.
    """
    page_fetcher = page_fetcher or fetch_url
    metadata_fetcher = metadata_fetcher or fetch_article_metadata

    candidates: list[FeedItem] = []
    seen_urls: set[str] = set()

    for kept in kept_items:
        origin_url = kept["url"]
        origin_domain = _registrable_domain(urlparse(origin_url).netloc)
        if not origin_domain:
            continue

        try:
            html = page_fetcher(origin_url)
        except Exception as e:  # noqa: BLE001
            logger.info("Citation crawl: could not fetch %s: %s", origin_url, e)
            continue
        if not html:
            continue

        links = extract_outbound_links(html, base_url=origin_url)
        found = 0
        for link in links:
            if found >= max_links_per_item:
                break
            try:
                link = normalize_url(link)
            except Exception:  # noqa: BLE001
                pass
            if link in seen_urls:
                continue
            netloc = urlparse(link).netloc
            if not netloc:
                continue
            if _registrable_domain(netloc) == origin_domain:
                continue  # self-link, not a citation to another source
            if _is_blocked(netloc, blocked_domains):
                continue

            seen_urls.add(link)

            item = metadata_fetcher(
                link,
                blocked_domains=blocked_domains,
                source_url=origin_url,
                source_platform="citations",
            )
            if item is None:
                continue
            found += 1
            candidates.append(item)

    return candidates
