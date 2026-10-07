"""Compatibility shim — article fetching logic lives in discovery.support.article_fetcher."""

from discovery.support.article_fetcher import (  # noqa: F401
    _DEFAULT_BLOCKED_DOMAINS,
    FeedItem,
    _is_blocked,
    fetch_article_metadata,
)
