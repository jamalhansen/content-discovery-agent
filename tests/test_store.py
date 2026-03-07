import sqlite3
import pytest
from store import init_db, is_seen, upsert_item, get_new_items, mark_item, get_examples


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
        upsert_item(**make_item(url="https://low.com", title="Low", score=0.3), path=path)
        upsert_item(**make_item(url="https://high.com", title="High", score=0.9), path=path)
        upsert_item(**make_item(url="https://mid.com", title="Mid", score=0.6), path=path)
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


class TestGetExamples:
    def test_returns_kept_and_dismissed_titles(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com", title="Kept Article"), path=path)
        upsert_item(**make_item(url="https://b.com", title="Dismissed Article"), path=path)
        mark_item("https://a.com", "kept", path)
        mark_item("https://b.com", "dismissed", path)
        result = get_examples(5, path)
        assert "Kept Article" in result["kept"]
        assert "Dismissed Article" in result["dismissed"]

    def test_empty_lists_when_no_data(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        result = get_examples(5, path)
        assert result == {"kept": [], "dismissed": []}

    def test_respects_n_limit(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        for i in range(8):
            upsert_item(**make_item(url=f"https://x.com/{i}", title=f"Article {i}"), path=path)
            mark_item(f"https://x.com/{i}", "kept", path)
        result = get_examples(3, path)
        assert len(result["kept"]) == 3

    def test_most_recent_first(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://first.com", title="First"), path=path)
        upsert_item(**make_item(url="https://second.com", title="Second"), path=path)
        # Set explicit timestamps directly to avoid wall-clock timing sensitivity
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE items SET status='kept', reviewed_at=? WHERE url=?",
            ("2026-03-07T10:00:00+00:00", "https://first.com"),
        )
        conn.execute(
            "UPDATE items SET status='kept', reviewed_at=? WHERE url=?",
            ("2026-03-07T11:00:00+00:00", "https://second.com"),
        )
        conn.commit()
        conn.close()
        result = get_examples(5, path)
        assert result["kept"][0] == "Second"
