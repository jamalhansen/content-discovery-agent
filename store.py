"""SQLite-backed storage for scored feed items.

Replaces state.py for URL deduplication and adds a persistent staging layer
so items can be reviewed before being promoted to the Obsidian inbox.

DB path: ~/.content-discovery.db (configurable via STORE_PATH in config.py)

Schema
------
items
  id          INTEGER  PK autoincrement
  url         TEXT     UNIQUE — primary dedup key
  title       TEXT
  source      TEXT     — feed name
  description TEXT
  score       REAL     — 0.0–1.0 from scorer
  tags        TEXT     — JSON array e.g. '["python","llm"]'
  summary     TEXT     — one-line LLM summary
  status      TEXT     — 'new' | 'kept' | 'dismissed'
  fetched_at  TEXT     — ISO date string e.g. '2026-03-07'
  reviewed_at TEXT     — ISO datetime string, NULL until reviewed
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    score       REAL    NOT NULL,
    tags        TEXT    NOT NULL DEFAULT '[]',
    summary     TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'new'
                        CHECK(status IN ('new', 'kept', 'dismissed')),
    fetched_at  TEXT    NOT NULL,
    reviewed_at TEXT    DEFAULT NULL
)
"""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    """Create the items table if it does not exist. Safe to call on every run."""
    with _connect(path) as conn:
        conn.execute(_CREATE_TABLE)


def is_seen(url: str, path: str) -> bool:
    """Return True if the URL is already in the DB (any status)."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM items WHERE url = ?", (url,)
        ).fetchone()
    return row is not None


def upsert_item(
    *,
    url: str,
    title: str,
    source: str,
    description: str,
    score: float,
    tags: list[str],
    summary: str,
    fetched_at: str,
    path: str,
) -> None:
    """Insert a new item. Silently ignores duplicate URLs (INSERT OR IGNORE).

    This means kept/dismissed items are never overwritten by a subsequent run
    that re-encounters the same URL.
    """
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO items
                (url, title, source, description, score, tags, summary, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (url, title, source, description, score, json.dumps(tags), summary, fetched_at),
        )


def get_new_items(path: str) -> list[dict]:
    """Return all items with status='new', ordered by score DESC.

    Tags are deserialized from JSON to list[str].
    """
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE status = 'new' ORDER BY score DESC"
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        result.append(d)
    return result


def mark_item(url: str, status: str, path: str) -> None:
    """Update an item's status and stamp reviewed_at with the current UTC time."""
    if status not in ("new", "kept", "dismissed"):
        raise ValueError(f"Invalid status: {status!r}. Must be 'new', 'kept', or 'dismissed'.")
    now = datetime.now(timezone.utc).isoformat()
    with _connect(path) as conn:
        conn.execute(
            "UPDATE items SET status = ?, reviewed_at = ? WHERE url = ?",
            (status, now, url),
        )


def get_examples(n: int, path: str) -> dict[str, list[str]]:
    """Return {'kept': [titles], 'dismissed': [titles]}, most recent first.

    n is the per-category limit. At most 3 titles from any single source are
    included, so a prolific blog reviewed in a single session cannot dominate
    the few-shot window. A candidate pool of 5× n is fetched to give the
    diversity filter enough to work with.

    Returns empty lists when no data exists — never raises.
    """
    _PER_SOURCE = 3

    def _diverse(rows: list) -> list[str]:
        source_counts: dict[str, int] = {}
        result = []
        for row in rows:
            src = row["source"]
            if source_counts.get(src, 0) < _PER_SOURCE:
                result.append(row["title"])
                source_counts[src] = source_counts.get(src, 0) + 1
                if len(result) >= n:
                    break
        return result

    with _connect(path) as conn:
        kept = conn.execute(
            "SELECT title, source FROM items WHERE status = 'kept' "
            "ORDER BY reviewed_at DESC LIMIT ?",
            (n * 5,),
        ).fetchall()
        dismissed = conn.execute(
            "SELECT title, source FROM items WHERE status = 'dismissed' "
            "ORDER BY reviewed_at DESC LIMIT ?",
            (n * 5,),
        ).fetchall()
    return {
        "kept": _diverse(kept),
        "dismissed": _diverse(dismissed),
    }
