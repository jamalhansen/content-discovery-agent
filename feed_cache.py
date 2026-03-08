import hashlib
import json
import logging
import os
import time
from feed_reader import FeedItem

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.cache/content-discovery/feeds/")
SOCIAL_CACHE_DIR = os.path.expanduser("~/.cache/content-discovery/social/")
CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours


def _is_stale(path: str) -> bool:
    """Return True if the cache file is older than CACHE_TTL_SECONDS."""
    try:
        age = time.time() - os.path.getmtime(path)
        return age > CACHE_TTL_SECONDS
    except OSError:
        return True


def _cache_path(feed_url: str) -> str:
    key = hashlib.md5(feed_url.encode(), usedforsecurity=False).hexdigest()
    return os.path.join(CACHE_DIR, f"{key}.json")


def load_cached_feed(feed_url: str) -> list[FeedItem] | None:
    """Return cached FeedItems for a URL, or None if no cache or cache is stale."""
    path = _cache_path(feed_url)
    if not os.path.exists(path):
        return None
    if _is_stale(path):
        logger.debug("Cache expired for feed %s", feed_url)
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
    """Delete all cached feed and social files."""
    for cache_dir in (CACHE_DIR, SOCIAL_CACHE_DIR):
        if not os.path.isdir(cache_dir):
            continue
        for fname in os.listdir(cache_dir):
            if fname.endswith(".json"):
                os.remove(os.path.join(cache_dir, fname))


# --- Social cache ---

def _social_cache_key(source: str, keywords: list[str]) -> str:
    """Stable cache key for a social source + keyword set."""
    key = f"{source}:{','.join(sorted(keywords))}"
    return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()


def load_cached_social(source: str, keywords: list[str]) -> list[FeedItem] | None:
    """Return cached FeedItems for a social source + keyword combo, or None if no cache or stale."""
    path = os.path.join(SOCIAL_CACHE_DIR, f"{_social_cache_key(source, keywords)}.json")
    if not os.path.exists(path):
        return None
    if _is_stale(path):
        logger.debug("Cache expired for social source %s", source)
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return [FeedItem(**item) for item in data]
    except (json.JSONDecodeError, TypeError, OSError) as e:
        logger.warning("Could not read social cache for %s: %s", source, e)
        return None


def save_cached_social(source: str, keywords: list[str], items: list[FeedItem]) -> None:
    """Write FeedItems to cache for a social source + keyword combo."""
    os.makedirs(SOCIAL_CACHE_DIR, exist_ok=True)
    path = os.path.join(SOCIAL_CACHE_DIR, f"{_social_cache_key(source, keywords)}.json")
    try:
        with open(path, "w") as f:
            json.dump([item.__dict__ for item in items], f, indent=2)
    except OSError as e:
        logger.warning("Could not write social cache for %s: %s", source, e)
