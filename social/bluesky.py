"""Bluesky social reader.

Uses the AT Protocol API to search for posts containing article links,
then normalises those articles to FeedItems.

Authentication via App Password is optional but recommended — the
public.api.bsky.app endpoint has intermittently returned 403 for
unauthenticated search requests. With credentials the request goes to
api.bsky.app with a bearer token and is reliably served.

Set these environment variables to enable auth:
    BLUESKY_HANDLE=your.handle.bsky.social
    BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

Generate an App Password in Bluesky → Settings → Privacy and Security →
App Passwords. App passwords grant read access without exposing your main
account credentials.
"""

import logging


from feed_reader import FeedItem
from social.article_fetcher import fetch_article_metadata
from social.base import SocialReader
from local_first_common.social import bluesky

logger = logging.getLogger(__name__)


class BlueskyReader(SocialReader):
    """Searches Bluesky for posts linking to articles and returns FeedItems."""

    def __init__(  # nosec B107 — empty string is "no auth" sentinel, not a hardcoded credential
        self,
        handle: str = "",
        app_password: str = "",
        blocked_domains: frozenset[str] = frozenset(),
    ) -> None:
        self._blocked_domains = blocked_domains
        self._token: str | None = None
        if handle and app_password:
            self._token = bluesky.get_auth_token(handle, app_password)
            if self._token:
                logger.debug("Bluesky: authenticated as %s", handle)
            else:
                logger.warning("Bluesky: authentication failed for %s — proceeding unauthenticated", handle)

    def fetch_items(self, keywords: list[str]) -> list[FeedItem]:
        """Search Bluesky for each keyword and return unique article FeedItems."""
        if not keywords:
            return []

        raw_posts = bluesky.fetch_posts(keywords, token=self._token, limit=25)
        seen_urls: set[str] = set()
        items: list[FeedItem] = []

        for post in raw_posts:
            for url in bluesky.extract_urls_from_post(post):
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                item = fetch_article_metadata(url, blocked_domains=self._blocked_domains)
                if item:
                    items.append(item)

        return items
