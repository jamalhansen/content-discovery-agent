import sqlite3
import pytest
from discovery.store import (
    init_db,
    is_seen,
    upsert_item,
    get_new_items,
    mark_item,
    dismiss_items_by_urls,
    update_item_score,
)


def db(tmp_path) -> str:
    return str(tmp_path / "test.db")


def make_item(**kwargs) -> dict:
    defaults = dict(
        url="https://example.com/article",
        title="Test Article",
        source="Test Blog",
        description="A test article about Python.",
        score=0.85,
        tags=["python", "llm"],
        summary="A test article.",
        fetched_at="2026-03-07",
    )
    defaults.update(kwargs)
    return defaults


class TestInitDb:
    def test_creates_items_table(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        conn = sqlite3.connect(path)
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
        ).fetchone()
        conn.close()
        assert table is not None

    def test_idempotent(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        init_db(path)  # must not raise

    def test_migration_adds_published_at_to_existing_db(self, tmp_path):
        """init_db should add published_at column to a DB that lacks it."""
        path = db(tmp_path)
        # Create table without published_at (simulates pre-migration DB)
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                source TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL, tags TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
                fetched_at TEXT NOT NULL, reviewed_at TEXT DEFAULT NULL
            )
        """)
        conn.commit()
        conn.close()
        init_db(path)  # should add published_at without raising
        conn = sqlite3.connect(path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
        conn.close()
        assert "published_at" in cols

    def test_migration_adds_found_at_to_existing_db(self, tmp_path):
        """init_db should add found_at column to a DB that lacks it."""
        path = db(tmp_path)
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                source TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL, tags TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
                fetched_at TEXT NOT NULL, published_at TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT DEFAULT NULL
            )
        """)
        conn.commit()
        conn.close()
        init_db(path)
        conn = sqlite3.connect(path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
        conn.close()
        assert "found_at" in cols

    def test_migration_failure_is_not_suppressed(self, tmp_path, monkeypatch):
        """Operational migration failures should propagate to the caller."""
        path = db(tmp_path)

        def fail_migration(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("discovery.store._ensure_column", fail_migration)

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            init_db(path)


class TestIsSeen:
    def test_false_for_unknown_url(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        assert is_seen("https://unknown.com", path) is False

    def test_true_after_upsert(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        item = make_item()
        upsert_item(**item, path=path)
        assert is_seen(item["url"], path) is True

    def test_true_for_dismissed_item(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        item = make_item()
        upsert_item(**item, path=path)
        mark_item(item["url"], "dismissed", path)
        assert is_seen(item["url"], path) is True


class TestUpsertItem:
    def test_inserts_and_retrieves_item(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        item = make_item()
        upsert_item(**item, path=path)
        rows = get_new_items(path)
        assert len(rows) == 1
        assert rows[0]["title"] == "Test Article"
        assert rows[0]["score"] == 0.85

    def test_tags_round_trip_as_list(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(tags=["duckdb", "sql", "python"]), path=path)
        rows = get_new_items(path)
        assert rows[0]["tags"] == ["duckdb", "sql", "python"]

    def test_published_at_stored_and_retrieved(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), published_at="2026-02-15", path=path)
        rows = get_new_items(path)
        assert rows[0]["published_at"] == "2026-02-15"

    def test_published_at_defaults_to_empty_string(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), path=path)
        rows = get_new_items(path)
        assert rows[0]["published_at"] == ""

    def test_default_status_is_new(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), path=path)
        rows = get_new_items(path)
        assert rows[0]["status"] == "new"

    def test_ignores_duplicate_url(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        item = make_item()
        upsert_item(**item, path=path)
        upsert_item(**item, path=path)  # duplicate — must not raise or double-insert
        rows = get_new_items(path)
        assert len(rows) == 1

    def test_found_at_stored_and_retrieved(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        post_url = "https://bsky.app/profile/user.bsky.social/post/abc123"
        upsert_item(**make_item(), found_at=post_url, path=path)
        rows = get_new_items(path)
        assert rows[0]["found_at"] == post_url

    def test_found_at_defaults_to_none(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), path=path)
        rows = get_new_items(path)
        assert rows[0]["found_at"] is None

    def test_does_not_overwrite_kept_item(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        item = make_item()
        upsert_item(**item, path=path)
        mark_item(item["url"], "kept", path)
        # Re-upsert with different score — OR IGNORE means original is preserved
        upsert_item(**{**item, "score": 0.1}, path=path)
        # Kept item should not appear in new items
        rows = get_new_items(path)
        assert len(rows) == 0


class TestGetNewItems:
    def test_returns_only_new_status(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com", title="A"), path=path)
        upsert_item(**make_item(url="https://b.com", title="B"), path=path)
        mark_item("https://a.com", "kept", path)
        rows = get_new_items(path)
        assert len(rows) == 1
        assert rows[0]["title"] == "B"

    def test_ordered_by_score_desc(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(
            **make_item(url="https://low.com", title="Low", score=0.3), path=path
        )
        upsert_item(
            **make_item(url="https://high.com", title="High", score=0.9), path=path
        )
        upsert_item(
            **make_item(url="https://mid.com", title="Mid", score=0.6), path=path
        )
        rows = get_new_items(path)
        assert [r["title"] for r in rows] == ["High", "Mid", "Low"]

    def test_empty_when_no_items(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        assert get_new_items(path) == []


class TestMarkItem:
    def test_kept_removes_from_new(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), path=path)
        mark_item(make_item()["url"], "kept", path)
        assert get_new_items(path) == []

    def test_dismissed_removes_from_new(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), path=path)
        mark_item(make_item()["url"], "dismissed", path)
        assert get_new_items(path) == []

    def test_sets_reviewed_at(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), path=path)
        mark_item(make_item()["url"], "kept", path)
        conn = sqlite3.connect(path)
        row = conn.execute("SELECT reviewed_at FROM items").fetchone()
        conn.close()
        assert row[0] is not None

    def test_invalid_status_raises(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), path=path)
        with pytest.raises(ValueError, match="Invalid status"):
            mark_item(make_item()["url"], "invalid", path)


class TestDismissItemsByUrls:
    def test_dismisses_matching_new_items(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1"), path=path)
        upsert_item(**make_item(url="https://a.com/2"), path=path)

        count = dismiss_items_by_urls(["https://a.com/1", "https://a.com/2"], path)

        assert count == 2
        remaining = get_new_items(path)
        assert remaining == []

    def test_returns_count_of_dismissed(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1"), path=path)
        upsert_item(**make_item(url="https://a.com/2"), path=path)

        count = dismiss_items_by_urls(["https://a.com/1"], path)
        assert count == 1

    def test_does_not_touch_kept_items(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1"), path=path)
        mark_item("https://a.com/1", "kept", path)

        count = dismiss_items_by_urls(["https://a.com/1"], path)

        assert count == 0
        # Verify it's still kept
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT status FROM items WHERE url = ?", ("https://a.com/1",)
        ).fetchone()
        conn.close()
        assert row[0] == "kept"

    def test_empty_list_returns_zero(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(), path=path)

        count = dismiss_items_by_urls([], path)
        assert count == 0
        assert len(get_new_items(path)) == 1

    def test_unknown_urls_are_silently_ignored(self, tmp_path):
        path = db(tmp_path)
        init_db(path)

        count = dismiss_items_by_urls(["https://ghost.example.com/"], path)
        assert count == 0

    def test_stamps_reviewed_at(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1"), path=path)

        dismiss_items_by_urls(["https://a.com/1"], path)

        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT reviewed_at FROM items WHERE url = ?", ("https://a.com/1",)
        ).fetchone()
        conn.close()
        assert row[0] is not None


class TestUpdateItemScore:
    def test_updates_score_tags_summary(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(
            **make_item(url="https://a.com/1", score=0.5, tags=["old"], summary="Old."),
            path=path,
        )

        update_item_score(
            url="https://a.com/1",
            score=0.9,
            tags=["new", "tag"],
            summary="New summary.",
            path=path,
        )

        items = get_new_items(path)
        assert items[0]["score"] == 0.9
        assert items[0]["tags"] == ["new", "tag"]
        assert items[0]["summary"] == "New summary."

    def test_does_not_change_status(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1"), path=path)

        update_item_score(
            url="https://a.com/1", score=0.3, tags=[], summary="Low.", path=path
        )

        items = get_new_items(path)
        assert len(items) == 1  # still 'new', not auto-dismissed

    def test_no_op_for_unknown_url(self, tmp_path):
        path = db(tmp_path)
        init_db(path)

        # Should not raise
        update_item_score(
            url="https://ghost.example.com/",
            score=0.9,
            tags=[],
            summary="Ghost.",
            path=path,
        )
