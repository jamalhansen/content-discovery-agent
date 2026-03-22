"""Compatibility shim — article fetching logic lives in local_first_common.article_fetcher."""
from local_first_common.article_fetcher import (  # noqa: F401
    FeedItem,
    _DEFAULT_BLOCKED_DOMAINS,
    _is_blocked,
    fetch_article_metadata,
)
