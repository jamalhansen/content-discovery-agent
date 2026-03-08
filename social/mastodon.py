"""Mastodon social reader.

Uses the public Mastodon REST API (no auth required for public timelines) to
search hashtag timelines for posts linking to articles, then normalises those
articles to FeedItems.
"""

import logging

import requests

from feed_reader import FeedItem
from social.article_fetcher import fetch_article_metadata
from social.base import SocialReader

logger = logging.getLogger(__name__)


def _keyword_to_hashtag(keyword: str) -> str:
    """Convert a keyword to a valid Mastodon hashtag (strips spaces and hyphens)."""
    return keyword.replace(" ", "").replace("-", "")


class MastodonReader(SocialReader):
    """Reads Mastodon hashtag timelines and returns FeedItems for linked articles."""

    def __init__(
        self,
        instances: list[str] | None = None,
        blocked_domains: frozenset[str] = frozenset(),
    ) -> None:
        self.instances = instances or ["mastodon.social"]
        self._blocked_domains = blocked_domains

    def fetch_items(self, keywords: list[str]) -> list[FeedItem]:
        """Search Mastodon hashtag timelines and return unique article FeedItems.

        Iterates over all configured instances and all keywords. Multi-word
        keywords are converted to single-word hashtags (spaces stripped).

        Args:
            keywords: Keywords to use as hashtags (e.g. "local ai" → "#localai").

        Returns:
            Deduplicated list of FeedItems for articles found in social posts.
        """
        seen_urls: set[str] = set()
        items: list[FeedItem] = []

        for instance in self.instances:
            for keyword in keywords:
                hashtag = _keyword_to_hashtag(keyword)
                url = f"https://{instance}/api/v1/timelines/tag/{hashtag}"

                try:
                    resp = requests.get(url, params={"limit": 40}, timeout=10)
                    resp.raise_for_status()
                    statuses = resp.json()
                except requests.RequestException as e:
                    logger.warning(
                        "Mastodon fetch failed for %s #%s: %s", instance, hashtag, e
                    )
                    continue

                for status in statuses:
                    card = status.get("card")
                    if not card:
                        continue
                    article_url = card.get("url", "").strip()
                    if not article_url or article_url in seen_urls:
                        continue
                    seen_urls.add(article_url)
                    item = fetch_article_metadata(article_url, blocked_domains=self._blocked_domains)
                    if item:
                        items.append(item)

        return items
