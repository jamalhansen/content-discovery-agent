import hashlib
import json
import logging
import os
from feed_reader import FeedItem

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.cache/content-discovery/feeds/")


def _cache_path(feed_url: str) -> str:
    key = hashlib.md5(feed_url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{key}.json")


def load_cached_feed(feed_url: str) -> list[FeedItem] | None:
    """Return cached FeedItems for a URL, or None if no cache exists."""
    path = _cache_path(feed_url)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return [FeedItem(**item) for item in data]
    except (json.JSONDecodeError, TypeError, OSError) as e:
        logger.warning("Could not read feed cache for %s: %s", feed_url, e)
        return None


def save_cached_feed(feed_url: str, items: list[FeedItem]) -> None:
    """Write FeedItems to cache for a URL."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(feed_url)
    try:
        with open(path, "w") as f:
            json.dump([item.__dict__ for item in items], f, indent=2)
    except OSError as e:
        logger.warning("Could not write feed cache for %s: %s", feed_url, e)


def clear_cache() -> None:
    """Delete all cached feed files."""
    if not os.path.isdir(CACHE_DIR):
        return
    for fname in os.listdir(CACHE_DIR):
        if fname.endswith(".json"):
            os.remove(os.path.join(CACHE_DIR, fname))
