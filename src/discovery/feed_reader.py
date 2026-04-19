import logging
import time as _time
import feedparser
import requests
from local_first_common.article_fetcher import FeedItem  # noqa: F401 — re-exported for consumers
from local_first_common.url import normalize_url

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; content-discovery-agent/1.0; +https://github.com/local-first/content-discovery-agent)"
}


class FeedReaderError(Exception):
    """Base error for feed-reader strict operations."""


class FeedFetchError(FeedReaderError):
    """Raised when a feed cannot be fetched."""


class FeedParseError(FeedReaderError):
    """Raised when fetched feed content cannot be parsed."""


def _fetch_and_parse_or_raise(feed_url: str):
    try:
        resp = requests.get(feed_url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise FeedFetchError(f"Error fetching feed {feed_url}: {e}") from e

    try:
        parsed = feedparser.parse(resp.content)
    except Exception as e:  # noqa: BLE001
        raise FeedParseError(f"Error parsing feed {feed_url}: {e}") from e

    if parsed.bozo and not parsed.entries:
        raise FeedParseError(
            f"Failed to parse feed {feed_url}: {parsed.bozo_exception}"
        )

    return parsed


def fetch_feed_or_raise(feed_url: str) -> list[FeedItem]:
    """Fetch and parse an RSS/Atom feed or raise a typed error."""
    parsed = _fetch_and_parse_or_raise(feed_url)

    feed_title = parsed.feed.get("title", feed_url)
    items = []
    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        url = normalize_url(entry.get("link", "").strip())
        # Try summary, then content, then fallback to empty
        description = entry.get("summary", "")
        if not description and entry.get("content"):
            description = entry["content"][0].get("value", "")
        description = description.strip()

        if not url:
            continue

        pub_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        published = _time.strftime("%Y-%m-%d", pub_struct) if pub_struct else ""

        items.append(
            FeedItem(
                title=title,
                description=description,
                url=url,
                source=feed_title,
                published=published,
                found_at=feed_url,
                platform="rss",
            )
        )

    return items


def fetch_feed(feed_url: str) -> list[FeedItem]:
    """Compatibility wrapper: returns [] on failure for legacy callers."""
    try:
        return fetch_feed_or_raise(feed_url)
    except FeedReaderError as e:
        logger.error("%s", e)
        return []


def filter_new_items(items: list[FeedItem], seen: set[str]) -> list[FeedItem]:
    """Return only items whose URL has not been seen before."""
    return [item for item in items if item.url not in seen]
