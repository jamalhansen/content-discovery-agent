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

First live batch (2026-09-07) scored 5/5 above threshold and was 0/5 good
by human review: a company's own launch-post blog linking to its own
product, an author linking to their own social profile from a different
domain (missed by the same-registrable-domain self-link check below), a
corporate blog's tool mention, and a news article's two generic
"background reading" links. All four failure shapes shared one root cause:
the destination page was scored in isolation, so a promotional CTA link and
a genuine "you should read this" citation looked identical -- neither the
scorer nor this module ever saw *why* the origin article linked out. Fixed
two ways: (1) a cheap pre-fetch filter for the most obvious shape (a bare
domain or a common marketing/account path is essentially never a specific
content citation), and (2) capturing the anchor text and surrounding
sentence for the LLM to judge citation intent from -- see the CITATION
description prefix below and scorer.py's matching prompt instruction.
"""
import logging
from urllib.parse import urlparse

from local_first_common.article_fetcher import (
    FeedItem,
    _is_blocked,
    fetch_article_metadata,
)
from local_first_common.html import extract_link_contexts
from local_first_common.http import fetch_url
from local_first_common.url import normalize_url

logger = logging.getLogger(__name__)

# First path segment implies a homepage/account/CTA page rather than a
# specific piece of content, regardless of what topic the LLM thinks it
# smells like from the title/description alone.
_MARKETING_PATH_SEGMENTS = frozenset({
    "pricing", "signup", "sign-up", "login", "log-in", "get-started",
    "getting-started", "download", "contact", "about", "careers", "jobs",
    "demo", "request-demo", "book-a-demo", "waitlist",
})

# Prefix marker scorer.py's SYSTEM_PROMPT is written to recognize -- keep
# these in sync if either changes.
_CITATION_CONTEXT_TEMPLATE = (
    '[Cited via: anchor text "{anchor}"; surrounding text: "{surrounding}"]\n\n{description}'
)


def _registrable_domain(netloc: str) -> str:
    """Good-enough same-site check for excluding self-links, not a public-suffix parse."""
    host = netloc.lower().split(":")[0].removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _looks_like_marketing_page(url: str) -> bool:
    """True for a bare domain or a common CTA/account path.

    A link to a company's root domain, or to /pricing, /signup, /demo, etc.,
    is essentially always a product mention rather than a citation to
    specific content -- cheap enough to catch before spending a live
    metadata fetch on it. Deliberately narrow (checks only the first path
    segment) so a real content path like /docs/getting-started/intro isn't
    caught by "getting-started" appearing deeper in the path.
    """
    path = urlparse(url).path.strip("/")
    if not path:
        return True
    first_segment = path.split("/")[0].lower()
    return first_segment in _MARKETING_PATH_SEGMENTS


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

        link_contexts = extract_link_contexts(html, base_url=origin_url)
        found = 0
        for lc in link_contexts:
            if found >= max_links_per_item:
                break
            try:
                link = normalize_url(lc.url)
            except Exception:  # noqa: BLE001
                link = lc.url
            if link in seen_urls:
                continue
            netloc = urlparse(link).netloc
            if not netloc:
                continue
            if _registrable_domain(netloc) == origin_domain:
                continue  # self-link, not a citation to another source
            if _is_blocked(netloc, blocked_domains):
                continue
            if _looks_like_marketing_page(link):
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

            item.description = _CITATION_CONTEXT_TEMPLATE.format(
                anchor=lc.anchor_text, surrounding=lc.surrounding_text,
                description=item.description,
            )
            found += 1
            candidates.append(item)

    return candidates
