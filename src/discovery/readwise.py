"""Readwise Reader integration.

Saves articles to the Readwise Reader inbox via the official API.
API docs: https://readwise.io/reader_api
"""

import logging

import requests

logger = logging.getLogger(__name__)

_SAVE_URL = "https://readwise.io/api/v3/save/"
_RATE_LIMIT_PER_MIN = 50


def save_to_readwise(
    url: str,
    token: str,
    *,
    title: str = "",
    summary: str = "",
    tags: list[str] | None = None,
    published_date: str = "",
) -> bool:
    """Save a URL to the Readwise Reader inbox.

    Args:
        url:            Article URL (required by the API).
        token:          Readwise access token.
        title:          Article title (optional, Reader will fetch if omitted).
        summary:        Short summary shown in Reader (optional).
        tags:           List of tag strings (optional).
        published_date: ISO 8601 date string e.g. "2026-03-11" (optional).

    Returns:
        True on success (HTTP 200 or 201), False on any error.
    """
    if not token:
        logger.error("READWISE_TOKEN is not set — cannot save to Reader")
        return False

    payload: dict = {"url": url}
    if title:
        payload["title"] = title
    if summary:
        payload["summary"] = summary
    if tags:
        payload["tags"] = tags
    if published_date:
        payload["published_date"] = published_date

    try:
        resp = requests.post(
            _SAVE_URL,
            json=payload,
            headers={"Authorization": f"Token {token}"},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True
        logger.warning(
            "Readwise API returned %s for %s: %s",
            resp.status_code, url, resp.text[:200],
        )
        return False
    except requests.RequestException as e:
        logger.warning("Failed to save %s to Readwise: %s", url, e)
        return False
