import logging
from dataclasses import dataclass
import feedparser

logger = logging.getLogger(__name__)


@dataclass
class FeedItem:
    title: str
    description: str
    url: str
    source: str


def fetch_feed(feed_url: str) -> list[FeedItem]:
    """Fetch and parse an RSS/Atom feed. Returns list of FeedItems."""
    try:
        parsed = feedparser.parse(feed_url)
    except Exception as e:
        logger.error("Error fetching feed %s: %s", feed_url, e)
        return []

    if parsed.bozo and not parsed.entries:
        logger.error("Failed to parse feed %s: %s", feed_url, parsed.bozo_exception)
        return []

    feed_title = parsed.feed.get("title", feed_url)
    items = []
    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
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
