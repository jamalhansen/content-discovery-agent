"""Mastodon social reader.

Uses the public Mastodon REST API (no auth required for public timelines) to
search hashtag timelines for posts linking to articles, then normalises those
articles to FeedItems.
"""

import logging

from ..feed_reader import FeedItem
from .article_fetcher import fetch_article_metadata
from .interfaces import SocialReader
from local_first_common.social import mastodon
from local_first_common.tracking import Tool
from local_first_common.url import normalize_url

logger = logging.getLogger(__name__)


class MastodonReader(SocialReader):
    """Reads Mastodon hashtag timelines and returns FeedItems for linked articles."""

    def __init__(
        self,
        instances: list[str] | None = None,
        blocked_domains: frozenset[str] = frozenset(),
        tool: Tool | None = None,
    ) -> None:
        self.instances = instances or ["mastodon.social"]
        self._blocked_domains = blocked_domains
        self._tool = tool

    def fetch_items(self, keywords: list[str], session: any = None) -> list[FeedItem]:
        """Search Mastodon hashtag timelines and return unique article FeedItems."""
        if not keywords:
            return []

        items: list[FeedItem] = []
        _local_seen: set[str] = set()

        for keyword in keywords:
            raw_statuses = mastodon.fetch_posts([keyword], instances=self.instances, limit=40)
            for status in raw_statuses:
                card = status.get("card")
                if not card:
                    continue
                article_url = card.get("url", "").strip()
                if not article_url:
                    continue
                
                if session:
                    if session.should_skip_url(article_url):
                        continue
                elif normalize_url(article_url) in _local_seen:
                    continue
                    
                item = fetch_article_metadata(
                    article_url,
                    blocked_domains=self._blocked_domains,
                    tool=self._tool,
                    source_url=status.get("url"),
                    source_platform="mastodon",
                    search_term=keyword,
                    session=session,
                )
                
                if item:
                    items.append(item)
                    if session:
                        session.mark_seen(article_url)
                    else:
                        _local_seen.add(normalize_url(article_url))

        return items
