"""Readwise Reader integration.

Saves articles to, and lists articles from, the Readwise Reader inbox via
the official API. API docs: https://readwise.io/reader_api
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from local_first_common.tracking import Tool, tracked_call

from discovery.support.article_fetcher import FeedItem

logger = logging.getLogger(__name__)

_SAVE_URL = "https://readwise.io/api/v3/save/"
_LIST_URL = "https://readwise.io/api/v3/list/"
_UPDATE_URL = "https://readwise.io/api/v3/update/{doc_id}/"

# The Reader API allows 20 requests/minute per token. Listing stays well inside
# that, but archiving a backlog is one request per document and will hit the
# limit immediately, so anything that loops needs to honour Retry-After.
_MAX_RETRIES = 4
_DEFAULT_RETRY_WAIT = 15


def _sleep_for_retry(resp: requests.Response) -> int:
    """Sleep for the interval the API asked for and return the seconds waited."""
    try:
        wait = int(resp.headers.get("Retry-After", _DEFAULT_RETRY_WAIT))
    except (TypeError, ValueError):
        wait = _DEFAULT_RETRY_WAIT
    wait = max(1, wait)
    logger.info("Readwise rate limit hit, waiting %ss", wait)
    time.sleep(wait)
    return wait


@dataclass
class ReaderRef:
    """A Reader document identified well enough to be updated later.

    ``FeedItem`` deliberately drops the document id and location because it
    models content to read, not a record to mutate. Reconciliation needs both,
    so it gets its own shape rather than widening FeedItem for every caller.
    """

    doc_id: str
    source_url: str
    title: str
    location: str


def save_to_readwise(
    token: str,
    url: str,
    *,
    title: str = "",
    summary: str = "",
    tags: list[str] | None = None,
    published_date: str = "",
    search_term: str | None = None,
    platform: str | None = None,
    location: str | None = None,
    tool: Tool | None = None,
    db_path: str | Path | None = None,
) -> bool:
    """Save a URL to the Readwise Reader inbox.

    Args:
        token:          Readwise access token.
        url:            Article URL (required by the API).
        title:          Article title (optional, Reader will fetch if omitted).
        summary:        Short summary shown in Reader (optional).
        tags:           List of tag strings (optional).
        published_date: ISO 8601 date string e.g. "2026-03-11" (optional).
        search_term:    Discovery search term to add as a tag (optional).
        platform:       Discovery platform to add as a tag (optional).
        location:       Reader location to file the document under -- "new",
                         "later", "archive", or "feed" (optional; Reader
                         defaults to "new" when omitted). Pass "archive" for
                         an item that's also landing somewhere else the
                         caller already treats as the actionable copy, so it
                         doesn't sit as a second unread item competing for
                         attention.
        tool:           Registered ``Tool`` (via ``register_tool``) to log this
                         call under in ``api_call_log``. Optional — omit for no logging.

    Returns:
        True on success (HTTP 200 or 201), False on any error.
    """
    if not token:
        logger.error("Readwise token is not set — cannot save to Reader")
        return False

    # Deep copy/init tags list
    all_tags = list(tags) if tags else []
    if platform:
        all_tags.append(f"platform:{platform}")
    if search_term:
        all_tags.append(f"term:{search_term}")

    payload: dict = {"url": url}
    if title:
        payload["title"] = title
    if summary:
        payload["summary"] = summary
    if all_tags:
        payload["tags"] = all_tags
    if published_date:
        payload["published_date"] = published_date
    if location:
        payload["location"] = location

    with tracked_call(tool, "readwise", "save", db_path=db_path) as call:
        try:
            resp = requests.post(
                _SAVE_URL,
                json=payload,
                headers={"Authorization": f"Token {token}"},
                timeout=10,
            )
            call.http_status = resp.status_code
            if resp.status_code in (200, 201):
                call.success = True
                return True
            call.error_message = resp.text[:200]
            logger.warning(
                "Readwise API returned %s for %s: %s",
                resp.status_code,
                url,
                resp.text[:200],
            )
            return False
        except requests.RequestException as e:
            call.error_message = str(e)
            logger.warning("Failed to save %s to Readwise: %s", url, e)
            return False


def _document_to_feed_item(doc: dict) -> FeedItem:
    """Map a single Reader API document object onto the shared FeedItem shape.

    ``source_url`` is the original article URL (what we want to link to);
    ``url`` is Reader's own reader.readwise.io URL and is only used as a
    fallback for documents that don't carry an external source (e.g. notes).
    """
    return FeedItem(
        title=doc.get("title") or "",
        description=doc.get("summary") or "",
        url=doc.get("source_url") or doc.get("url") or "",
        source="readwise-reader",
        published=doc.get("published_date") or "",
        platform="reader",
    )


def list_reader_documents(
    token: str,
    *,
    location: str | None = "new",
    category: str | None = None,
    updated_after: str | None = None,
    tag: str | None = None,
    limit: int = 100,
    tool: Tool | None = None,
    db_path: str | Path | None = None,
) -> list[FeedItem]:
    """Fetch documents from the Readwise Reader library, paginating through all results.

    Args:
        token:         Readwise access token.
        location:      Filter by location — "new", "later", "shortlist", "archive",
                        "feed", or None to skip this filter and return all locations.
                        Defaults to "new" (unread inbox items), the ingest case this
                        function exists for.
        category:      Filter by document type — "article", "email", "rss", "pdf",
                        "epub", "tweet", "video", etc. None returns all types,
                        including "highlight"/"note" entries that aren't real content.
        updated_after: ISO 8601 timestamp; only return documents modified after this.
        tag:           Filter by a single tag.
        limit:         Page size sent to the API (1-100). Pagination is handled
                        internally regardless of this value; it only affects how
                        many requests are made.
        tool:          Registered ``Tool`` (via ``register_tool``) to log this
                        call under in ``api_call_log``. Optional — omit for no logging.

    Returns:
        A flat list of FeedItem, across all pages. Stops and returns whatever was
        gathered so far if a page request fails (partial results beat a crashed
        scheduled run).

    Note: the API is rate-limited to 20 requests/minute per token. This function
    does not implement backoff — fine for routine "new" polling, but a large
    backfill (e.g. category=None across full history) could exceed it.
    """
    if not token:
        logger.error("Readwise token is not set — cannot list Reader documents")
        return []

    items: list[FeedItem] = []
    cursor: str | None = None

    with tracked_call(tool, "readwise", "list", db_path=db_path) as call:
        call.success = True
        while True:
            params: dict = {"limit": limit}
            if location is not None:
                params["location"] = location
            if category is not None:
                params["category"] = category
            if updated_after is not None:
                params["updatedAfter"] = updated_after
            if tag is not None:
                params["tag"] = tag
            if cursor is not None:
                params["pageCursor"] = cursor

            try:
                resp = requests.get(
                    _LIST_URL,
                    params=params,
                    headers={"Authorization": f"Token {token}"},
                    timeout=10,
                )
            except requests.RequestException as e:
                logger.warning("Failed to list Reader documents: %s", e)
                call.success = False
                call.error_message = str(e)
                break

            call.http_status = resp.status_code
            if resp.status_code != 200:
                logger.warning(
                    "Readwise API returned %s listing documents: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                call.success = False
                call.error_message = resp.text[:200]
                break

            data = resp.json()
            items.extend(_document_to_feed_item(doc) for doc in data.get("results", []))

            cursor = data.get("nextPageCursor")
            if not cursor:
                break

        call.item_count = len(items)

    return items


def list_reader_refs(
    token: str,
    *,
    location: str | None = "new",
    category: str | None = None,
    tool: Tool | None = None,
    db_path: str | Path | None = None,
) -> list[ReaderRef]:
    """List Reader documents as updatable references (id, source_url, location).

    Same traversal as ``list_reader_documents`` but preserves the document id and
    location, which is what an archive or reconcile pass needs. Documents without
    a ``source_url`` (Reader notes, highlights) are skipped: there is nothing to
    match them against.

    ``tool``: registered ``Tool`` (via ``register_tool``) to log this call under
    in ``api_call_log``. Optional — omit for no logging.
    """
    if not token:
        logger.error("Readwise token is not set — cannot list Reader documents")
        return []

    refs: list[ReaderRef] = []
    cursor: str | None = None

    with tracked_call(tool, "readwise", "list_refs", db_path=db_path) as call:
        call.success = True
        while True:
            params: dict = {}
            if location is not None:
                params["location"] = location
            if category is not None:
                params["category"] = category
            if cursor is not None:
                params["pageCursor"] = cursor

            for _ in range(_MAX_RETRIES):
                try:
                    resp = requests.get(
                        _LIST_URL,
                        params=params,
                        headers={"Authorization": f"Token {token}"},
                        timeout=30,
                    )
                except requests.RequestException as e:
                    logger.warning("Failed to list Reader documents: %s", e)
                    call.success = False
                    call.error_message = str(e)
                    call.item_count = len(refs)
                    return refs

                if resp.status_code == 429:
                    _sleep_for_retry(resp)
                    continue
                break
            else:
                logger.warning("Gave up listing Reader documents after repeated rate limiting")
                call.success = False
                call.error_message = "gave up after repeated rate limiting"
                call.item_count = len(refs)
                return refs

            call.http_status = resp.status_code
            if resp.status_code != 200:
                logger.warning(
                    "Readwise API returned %s listing documents: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                call.success = False
                call.error_message = resp.text[:200]
                call.item_count = len(refs)
                return refs

            data = resp.json()
            for doc in data.get("results", []):
                source_url = doc.get("source_url") or ""
                if not source_url:
                    continue
                refs.append(
                    ReaderRef(
                        doc_id=doc.get("id") or "",
                        source_url=source_url,
                        title=doc.get("title") or "",
                        location=doc.get("location") or "",
                    )
                )

            cursor = data.get("nextPageCursor")
            if not cursor:
                break

        call.item_count = len(refs)

    return refs


def archive_reader_document(
    token: str, doc_id: str, tool: Tool | None = None, db_path: str | Path | None = None
) -> bool:
    """Move a Reader document to the archive location.

    Returns True on success, False on any error. Retries on 429 rather than
    failing, because the caller is normally archiving a backlog in a loop and a
    dropped item would silently stay in the queue.

    ``tool``: registered ``Tool`` (via ``register_tool``) to log this call under
    in ``api_call_log``. Optional — omit for no logging.
    """
    if not token:
        logger.error("Readwise token is not set — cannot archive document")
        return False
    if not doc_id:
        logger.warning("Cannot archive a Reader document without an id")
        return False

    with tracked_call(tool, "readwise", "archive", db_path=db_path) as call:
        url = _UPDATE_URL.format(doc_id=doc_id)
        for _ in range(_MAX_RETRIES):
            try:
                resp = requests.patch(
                    url,
                    json={"location": "archive"},
                    headers={"Authorization": f"Token {token}"},
                    timeout=30,
                )
            except requests.RequestException as e:
                logger.warning("Failed to archive Reader document %s: %s", doc_id, e)
                call.error_message = str(e)
                return False

            if resp.status_code == 429:
                _sleep_for_retry(resp)
                continue

            call.http_status = resp.status_code
            if resp.status_code in (200, 201, 204):
                call.success = True
                return True

            call.error_message = resp.text[:200]
            logger.warning(
                "Readwise API returned %s archiving %s: %s",
                resp.status_code,
                doc_id,
                resp.text[:200],
            )
            return False

        call.error_message = "gave up after repeated rate limiting"
        logger.warning("Gave up archiving %s after repeated rate limiting", doc_id)
        return False
