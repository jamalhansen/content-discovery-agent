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
  score       REAL     — 0.0–1.0 from local_first_commonscorer
  tags        TEXT     — JSON array e.g. '["python","llm"]'
  summary     TEXT     — one-line LLM summary
  status      TEXT     — 'new' | 'kept' | 'dismissed'
  fetched_at  TEXT     — ISO date string e.g. '2026-03-07'
  found_at    TEXT     — URL of the page/post where this link was first found (NULL for older rows)
  reviewed_at TEXT     — ISO datetime string, NULL until reviewed
"""

import json
import logging
import sqlite3
from datetime import UTC, datetime

from local_first_common.url import normalize_url

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT    NOT NULL UNIQUE,
    title        TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    score        REAL    NOT NULL,
    tags         TEXT    NOT NULL DEFAULT '[]',
    summary      TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'new'
                         CHECK(status IN ('new', 'kept', 'dismissed')),
    fetched_at   TEXT    NOT NULL,
    published_at TEXT    NOT NULL DEFAULT '',
    found_at     TEXT    DEFAULT NULL,
    reviewed_at  TEXT    DEFAULT NULL,
    search_term  TEXT    DEFAULT NULL,
    platform     TEXT    DEFAULT NULL
)
"""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    if _column_exists(conn, table, column):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db(path: str) -> None:
    """Create the items table if it does not exist. Safe to call on every run.

    Also runs lightweight schema migrations for existing databases:
    - Adds published_at column if absent (added after initial release).
    """
    with _connect(path) as conn:
        conn.execute(_CREATE_TABLE)
        # Migration: add published_at for existing DBs that predate this column.
        _ensure_column(conn, "items", "published_at", "TEXT NOT NULL DEFAULT ''")
        # Migration: add found_at for existing DBs that predate this column.
        _ensure_column(conn, "items", "found_at", "TEXT DEFAULT NULL")
        # Migration: add search_term for existing DBs that predate this column.
        _ensure_column(conn, "items", "search_term", "TEXT DEFAULT NULL")
        # Migration: add platform for existing DBs that predate this column.
        _ensure_column(conn, "items", "platform", "TEXT DEFAULT NULL")


def is_seen(url: str, path: str) -> bool:
    """Return True if the URL is already in the DB (any status).

    Checks the exact URL first, then tries common variants (trailing slash, http/https)
    for backwards compatibility with data created before normalization was added.
    """
    with _connect(path) as conn:
        # 1. Exact match (should match all items after migration)
        row = conn.execute("SELECT 1 FROM items WHERE url = ?", (url,)).fetchone()
        if row:
            return True

        # 2. Legacy fallback: check with a trailing slash
        if not url.endswith("/"):
            row = conn.execute(
                "SELECT 1 FROM items WHERE url = ?", (url + "/",)
            ).fetchone()
            if row:
                return True

        # 3. Legacy fallback: check http version if searching for https
        if url.startswith("https://"):
            base = url[8:]
            row = conn.execute(
                "SELECT 1 FROM items WHERE url = ?", ("http://" + base,)
            ).fetchone()
            if row:
                return True
            row = conn.execute(
                "SELECT 1 FROM items WHERE url = ?", ("http://" + base + "/",)
            ).fetchone()
            if row:
                return True

    return False


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
    published_at: str = "",
    found_at: str | None = None,
    search_term: str | None = None,
    platform: str | None = None,
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
                (url, title, source, description, score, tags, summary, fetched_at, published_at, found_at, search_term, platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                title,
                source,
                description,
                score,
                json.dumps(tags),
                summary,
                fetched_at,
                published_at,
                found_at,
                search_term,
                platform,
            ),
        )


def get_new_items(path: str) -> list[dict]:
    """Return all items with status='new', ordered by score DESC.

    Tags are deserialized from local_first_commonJSON to list[str].
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
        raise ValueError(
            f"Invalid status: {status!r}. Must be 'new', 'kept', or 'dismissed'."
        )
    now = datetime.now(UTC).isoformat()
    with _connect(path) as conn:
        conn.execute(
            "UPDATE items SET status = ?, reviewed_at = ? WHERE url = ?",
            (status, now, url),
        )


def dismiss_items_by_urls(urls: list[str], path: str) -> int:
    """Bulk-dismiss a list of URLs that currently have status='new'.

    Only affects items with status='new' — kept items are never touched.
    Returns the number of rows actually updated.
    """
    if not urls:
        return 0
    now = datetime.now(UTC).isoformat()
    placeholders = ",".join("?" * len(urls))
    with _connect(path) as conn:
        # placeholders contains only '?' characters; URL values are parameterized — not an injection risk
        query = f"UPDATE items SET status = 'dismissed', reviewed_at = ? WHERE url IN ({placeholders}) AND status = 'new'"  # nosec B608
        cursor = conn.execute(query, [now, *urls])
    return cursor.rowcount


def get_status_summary(path: str) -> list[dict]:
    """Return per-status counts and avg scores.

    Each dict has keys: status, count, avg_score.
    """
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT status,
                   COUNT(*)        AS count,
                   ROUND(AVG(score), 2) AS avg_score
            FROM items
            GROUP BY status
            ORDER BY count DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_daily_counts(path: str, days: int = 7) -> list[dict]:
    """Return per-day item counts for the last N days.

    Each dict has keys: date, total, new, kept, dismissed.
    """
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT fetched_at AS date,
                   COUNT(*)                                   AS total,
                   SUM(CASE WHEN status='new'       THEN 1 ELSE 0 END) AS new,
                   SUM(CASE WHEN status='kept'      THEN 1 ELSE 0 END) AS kept,
                   SUM(CASE WHEN status='dismissed' THEN 1 ELSE 0 END) AS dismissed
            FROM items
            GROUP BY fetched_at
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (days,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_source_stats(path: str, min_items: int = 5) -> list[dict]:
    """Return sources sorted by avg score descending (min_items threshold).

    Each dict has keys: source, count, avg_score.
    """
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT source,
                   COUNT(*)             AS count,
                   ROUND(AVG(score), 2) AS avg_score
            FROM items
            GROUP BY source
            HAVING count >= ?
            ORDER BY avg_score DESC
            """,
            (min_items,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_tag_counts(path: str, status: str = "kept", limit: int = 15) -> list[dict]:
    """Return most common tags from local_first_commonitems of the given status.

    Parses the JSON tags column and counts individual tag occurrences.
    Each dict has keys: tag, count.
    """
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT tags FROM items WHERE status = ?", (status,)
        ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        for tag in json.loads(row["tags"]):
            tag = tag.strip().lower()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1

    sorted_tags = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [{"tag": tag, "count": count} for tag, count in sorted_tags[:limit]]


def get_examples(
    n: int,
    path: str,
    n_dismissed: int | None = None,
) -> dict[str, list[str]]:
    """Return {'kept': [titles], 'dismissed': [titles]}, most recent first.

    n controls the kept limit; n_dismissed controls the dismissed limit
    (defaults to n if not supplied). Separate limits let you weight the
    dismissed side more heavily — useful when dismissed items far outnumber
    kept ones and you want the model to see more negative signal.

    At most 3 titles from local_first_commonany single source are included per category, so a
    prolific blog reviewed in a single session cannot dominate the few-shot
    window. A candidate pool of 5× n is fetched to give the diversity filter
    enough to work with.

    Returns empty lists when no data exists — never raises.
    """
    n_kept = n
    n_dis = n_dismissed if n_dismissed is not None else n
    _PER_SOURCE = 3

    def _diverse(rows: list, limit: int) -> list[str]:
        source_counts: dict[str, int] = {}
        result = []
        for row in rows:
            src = row["source"]
            if source_counts.get(src, 0) < _PER_SOURCE:
                result.append(row["title"])
                source_counts[src] = source_counts.get(src, 0) + 1
                if len(result) >= limit:
                    break
        return result

    with _connect(path) as conn:
        kept = conn.execute(
            "SELECT title, source FROM items WHERE status = 'kept' "
            "ORDER BY reviewed_at DESC LIMIT ?",
            (n_kept * 5,),
        ).fetchall()
        dismissed = conn.execute(
            "SELECT title, source FROM items WHERE status = 'dismissed' "
            "ORDER BY reviewed_at DESC LIMIT ?",
            (n_dis * 5,),
        ).fetchall()
    return {
        "kept": _diverse(kept, n_kept),
        "dismissed": _diverse(dismissed, n_dis),
    }


def get_score_distribution(path: str, status: str = "new") -> list[dict]:
    """Return score counts in 0.1-wide buckets for items of the given status.

    Each dict has keys: bucket (lower bound, e.g. "0.7"), count.
    Buckets are returned sorted ascending (0.0 → 0.9).
    Score 1.0 is counted in the 0.9 bucket.
    """
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT score FROM items WHERE status = ?", (status,)
        ).fetchall()

    buckets: dict[str, int] = {f"{i / 10:.1f}": 0 for i in range(10)}
    for row in rows:
        idx = min(int(row["score"] * 10), 9)
        buckets[f"{idx / 10:.1f}"] += 1
    return [{"bucket": k, "count": v} for k, v in sorted(buckets.items())]


def get_top_dismissed_for_date(
    path: str,
    fetched_at: str,
    limit: int = 5,
    min_score: float = 0.0,
) -> list[dict]:
    """Return top dismissed items for a given fetched_at date.

    Useful for explaining zero-candidate runs when threshold is slightly too high.
    """
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT url, title, score, status
            FROM items
            WHERE fetched_at = ?
              AND status = 'dismissed'
              AND score >= ?
            ORDER BY score DESC
            LIMIT ?
            """,
            (fetched_at, min_score, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def update_item_score(
    *,
    url: str,
    score: float,
    tags: list[str],
    summary: str,
    path: str,
) -> None:
    """Update the score, tags, and summary of an existing item.

    Does not change the item's status — the caller is responsible for
    dismissing items that fall below threshold after rescoring.
    """
    with _connect(path) as conn:
        conn.execute(
            "UPDATE items SET score = ?, tags = ?, summary = ? WHERE url = ?",
            (score, json.dumps(tags), summary, url),
        )


def get_recent_kept(path: str, limit: int = 10) -> list[dict]:
    """Return the most recently kept items, for citation crawling.

    An article you already trusted enough to keep is higher-signal for
    finding new sources than a keyword search -- see discovery/citations.py.
    Each dict has keys: url, title.
    """
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT url, title FROM items WHERE status = 'kept' "
            "ORDER BY reviewed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def search_kept_items(
    path: str,
    tags: list[str] | None = None,
    query: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search kept items by tags and/or text query.

    Matches:
    - tags: checks if any provided tag is present in the item's JSON tags array.
    - query: checks if query substring matches title, description, summary, source, or tags.

    Returns dicts with full item details (id, url, title, source, description,
    score, tags, summary, status, fetched_at, reviewed_at).
    """
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT id, url, title, source, description, score, tags, summary,
                   status, fetched_at, published_at, found_at, reviewed_at
            FROM items
            WHERE status = 'kept'
            ORDER BY reviewed_at DESC, score DESC
            """
        ).fetchall()

    target_tags = [t.strip().lower() for t in tags] if tags else []
    target_query = query.strip().lower() if query else None

    results: list[dict] = []
    for r in rows:
        item = dict(r)
        item_tags: list[str] = []
        try:
            item_tags = [
                str(t).strip().lower()
                for t in json.loads(item.get("tags") or "[]")
            ]
        except (json.JSONDecodeError, TypeError):
            pass
        item["tags"] = item_tags

        # If tags specified, check for any intersection
        if target_tags and not any(t in item_tags for t in target_tags):
            continue

        # If query specified, check against title, summary, description, source, tags
        if target_query:
            searchable = " ".join([
                item.get("title") or "",
                item.get("summary") or "",
                item.get("description") or "",
                item.get("source") or "",
                " ".join(item_tags),
            ]).lower()
            if target_query not in searchable:
                continue

        results.append(item)
        if len(results) >= limit:
            break

    return results


def get_eval_sample(
    path: str,
    n_kept: int = 40,
    n_dismissed: int = 80,
) -> list[dict]:
    """Return a random sample of historical kept/dismissed items for `discover eval`.

    Random rather than recent: a recency-biased sample would mostly reflect
    decisions already made under something close to the current prompt, which
    makes agreement look artificially high and hides drift that would only
    show up against the older end of the history.

    Each dict has keys: url, title, description, source, score (the score
    recorded at review time), status ('kept' or 'dismissed').
    """
    with _connect(path) as conn:
        rows = []
        for status, n in (("kept", n_kept), ("dismissed", n_dismissed)):
            rows.extend(
                conn.execute(
                    "SELECT url, title, description, source, score, status "
                    "FROM items WHERE status = ? ORDER BY RANDOM() LIMIT ?",
                    (status, n),
                ).fetchall()
            )
    return [dict(r) for r in rows]


def migrate_all_urls(path: str) -> tuple[int, int]:
    """Normalize all URLs in the database.

    Returns (updated_count, merged_count).
    """
    with _connect(path) as conn:
        all_items = conn.execute("SELECT id, url, status FROM items").fetchall()

        updated = 0
        merged = 0

        # We need to handle potential UNIQUE constraint violations (merging)
        for row in all_items:
            item_id = row["id"]
            old_url = row["url"]
            norm_url = normalize_url(old_url)

            if norm_url == old_url:
                continue

            # Check if normalized URL already exists
            existing = conn.execute(
                "SELECT id, status FROM items WHERE url = ? AND id != ?",
                (norm_url, item_id),
            ).fetchone()

            if existing:
                # Collision! Merge logic: keep the more "advanced" status
                # kept > dismissed > new
                status_map = {"kept": 2, "dismissed": 1, "new": 0}
                if status_map.get(row["status"], 0) > status_map.get(
                    existing["status"], 0
                ):
                    # Current item is more important — replace existing one
                    conn.execute("DELETE FROM items WHERE id = ?", (existing["id"],))
                    conn.execute(
                        "UPDATE items SET url = ? WHERE id = ?", (norm_url, item_id)
                    )
                else:
                    # Existing item is more important (or equal) — delete current one
                    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
                merged += 1
            else:
                # No collision, just update
                conn.execute(
                    "UPDATE items SET url = ? WHERE id = ?", (norm_url, item_id)
                )
                updated += 1

        conn.commit()
    return updated, merged
