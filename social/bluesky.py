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

import requests

from feed_reader import FeedItem
from social.article_fetcher import fetch_article_metadata
from social.base import SocialReader

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
_AUTH_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"


def _extract_urls_from_post(post: dict) -> list[str]:
    """Extract article URLs from a Bluesky PostView dict.

    Checks embed link cards first (most reliable), then falls back to
    richtext facet links.
    """
    # Embed external link card — present when a link preview card is attached
    embed = post.get("embed") or {}
    external = embed.get("external") or {}
    uri = external.get("uri", "").strip()
    if uri:
        return [uri]

    # Richtext facets — inline link annotations in the post text
    urls: list[str] = []
    facets = (post.get("record") or {}).get("facets") or []
    for facet in facets:
        for feature in facet.get("features", []):
            if feature.get("$type") == "app.bsky.richtext.facet#link":
                link_uri = feature.get("uri", "").strip()
                if link_uri:
                    urls.append(link_uri)
    return urls


def _get_auth_token(handle: str, app_password: str) -> str | None:
    """Fetch a bearer token from Bluesky using handle + app password.

    POSTs to com.atproto.server.createSession and returns the accessJwt,
    or None if authentication fails (bad credentials, network error, etc.).
    """
    try:
        resp = requests.post(
            _AUTH_URL,
            json={"identifier": handle, "password": app_password},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("accessJwt")
    except requests.RequestException as e:
        logger.warning("Bluesky authentication failed: %s", e)
        return None


class BlueskyReader(SocialReader):
    """Searches Bluesky for posts linking to articles and returns FeedItems.

    Optionally authenticates using a handle and App Password. Authenticated
    requests are more reliable — unauthenticated search on public.api.bsky.app
    has intermittently returned 403 due to rate-limiting.

    Args:
        handle: Bluesky handle (e.g. "you.bsky.social"). Leave empty to skip auth.
        app_password: App Password from Bluesky Settings. Leave empty to skip auth.
    """

    def __init__(  # nosec B107 — empty string is "no auth" sentinel, not a hardcoded credential
        self,
        handle: str = "",
        app_password: str = "",
        blocked_domains: frozenset[str] = frozenset(),
    ) -> None:
        self._blocked_domains = blocked_domains
        self._token: str | None = None
        if handle and app_password:
            self._token = _get_auth_token(handle, app_password)
            if self._token:
                logger.debug("Bluesky: authenticated as %s", handle)
            else:
                logger.warning("Bluesky: authentication failed for %s — proceeding unauthenticated", handle)

    def fetch_items(self, keywords: list[str]) -> list[FeedItem]:
        """Search Bluesky for each keyword and return unique article FeedItems.

        Args:
            keywords: Search terms to query the Bluesky searchPosts API.

        Returns:
            Deduplicated list of FeedItems for articles found in social posts.
        """
        if not keywords:
            return []

        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        seen_urls: set[str] = set()
        items: list[FeedItem] = []

        for keyword in keywords:
            try:
                resp = requests.get(
                    _SEARCH_URL,
                    params={"q": keyword, "limit": 25},
                    headers=headers,
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                logger.warning("Bluesky fetch failed for keyword %r: %s", keyword, e)
                continue

            for post in data.get("posts", []):
                for url in _extract_urls_from_post(post):
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    item = fetch_article_metadata(url, blocked_domains=self._blocked_domains)
                    if item:
                        items.append(item)

        return items
