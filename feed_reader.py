import logging
from dataclasses import dataclass
import feedparser
import requests
from url_utils import clean_url

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; content-discovery-agent/1.0; +https://github.com/local-first/content-discovery-agent)"
}


@dataclass
class FeedItem:
    title: str
    description: str
    url: str
    source: str


def fetch_feed(feed_url: str) -> list[FeedItem]:
    """Fetch and parse an RSS/Atom feed. Returns list of FeedItems."""
    try:
        resp = requests.get(feed_url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except requests.RequestException as e:
        logger.error("Error fetching feed %s: %s", feed_url, e)
        return []
    except Exception as e:
        logger.error("Error parsing feed %s: %s", feed_url, e)
        return []

    if parsed.bozo and not parsed.entries:
        logger.error("Failed to parse feed %s: %s", feed_url, parsed.bozo_exception)
        return []

    feed_title = parsed.feed.get("title", feed_url)
    items = []
    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        url = clean_url(entry.get("link", "").strip())
        # Try summary, then content, then fallback to empty
        description = entry.get("summary", "")
        if not description and entry.get("content"):
            description = entry["content"][0].get("value", "")
        description = description.strip()

        if not url:
            continue

        items.append(FeedItem(
            title=title,
            description=description,
            url=url,
            source=feed_title,
        ))

    return items


def filter_new_items(items: list[FeedItem], seen: set[str]) -> list[FeedItem]:
    """Return only items whose URL has not been seen before."""
    return [item for item in items if item.url not in seen]
