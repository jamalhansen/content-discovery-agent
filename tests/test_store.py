import sqlite3
import pytest
from store import (
    init_db, is_seen, upsert_item, get_new_items, mark_item, get_examples,
    get_status_summary, get_daily_counts, get_source_stats, get_tag_counts,
    dismiss_items_by_urls, get_score_distribution, update_item_score,
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
        # Use distinct sources so the per-source cap does not interfere
        for i in range(8):
            upsert_item(**make_item(url=f"https://x.com/{i}", title=f"Article {i}",
                                   source=f"Blog {i}"), path=path)
            mark_item(f"https://x.com/{i}", "kept", path)
        result = get_examples(3, path)
        assert len(result["kept"]) == 3

    def test_limits_per_source_to_three(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        # Flood the recent window with 7 items from the same blog
        for i in range(7):
            upsert_item(**make_item(url=f"https://a.com/{i}", title=f"Blog A Post {i}",
                                   source="Blog A"), path=path)
            mark_item(f"https://a.com/{i}", "kept", path)
        # Add 3 items from a second blog
        for i in range(3):
            upsert_item(**make_item(url=f"https://b.com/{i}", title=f"Blog B Post {i}",
                                   source="Blog B"), path=path)
            mark_item(f"https://b.com/{i}", "kept", path)
        result = get_examples(10, path)
        a_titles = [t for t in result["kept"] if t.startswith("Blog A")]
        b_titles = [t for t in result["kept"] if t.startswith("Blog B")]
        assert len(a_titles) <= 3
        assert len(b_titles) > 0


class TestGetStatusSummary:
    def test_empty_db_returns_empty_list(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        assert get_status_summary(path) == []

    def test_returns_counts_and_avg_scores(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", score=0.8), path=path)
        upsert_item(**make_item(url="https://a.com/2", score=0.9), path=path)
        mark_item("https://a.com/1", "kept", path)
        upsert_item(**make_item(url="https://a.com/3", score=0.3), path=path)
        mark_item("https://a.com/3", "dismissed", path)

        result = get_status_summary(path)
        statuses = {r["status"]: r for r in result}

        assert statuses["new"]["count"] == 1
        assert statuses["kept"]["count"] == 1
        assert statuses["dismissed"]["count"] == 1
        assert statuses["kept"]["avg_score"] == 0.8

    def test_avg_score_rounds_to_two_decimal_places(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", score=0.8), path=path)
        upsert_item(**make_item(url="https://a.com/2", score=0.9), path=path)

        result = get_status_summary(path)
        new_row = next(r for r in result if r["status"] == "new")
        assert new_row["avg_score"] == 0.85


class TestGetDailyCounts:
    def test_empty_db_returns_empty_list(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        assert get_daily_counts(path) == []

    def test_groups_by_fetched_at(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", fetched_at="2026-03-07"), path=path)
        upsert_item(**make_item(url="https://a.com/2", fetched_at="2026-03-08"), path=path)
        upsert_item(**make_item(url="https://a.com/3", fetched_at="2026-03-08"), path=path)

        result = get_daily_counts(path)
        dates = [r["date"] for r in result]
        assert "2026-03-08" in dates
        assert "2026-03-07" in dates
        day8 = next(r for r in result if r["date"] == "2026-03-08")
        assert day8["total"] == 2

    def test_counts_new_kept_dismissed_separately(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", fetched_at="2026-03-08"), path=path)
        upsert_item(**make_item(url="https://a.com/2", fetched_at="2026-03-08"), path=path)
        mark_item("https://a.com/1", "kept", path)
        mark_item("https://a.com/2", "dismissed", path)
        upsert_item(**make_item(url="https://a.com/3", fetched_at="2026-03-08"), path=path)

        result = get_daily_counts(path)
        day = result[0]
        assert day["kept"] == 1
        assert day["dismissed"] == 1
        assert day["new"] == 1

    def test_respects_days_limit(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        for i in range(10):
            upsert_item(**make_item(url=f"https://a.com/{i}",
                                   fetched_at=f"2026-03-{i+1:02d}"), path=path)

        result = get_daily_counts(path, days=3)
        assert len(result) == 3


class TestGetSourceStats:
    def test_empty_db_returns_empty_list(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        assert get_source_stats(path) == []

    def test_excludes_sources_below_min_items(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", source="Small Blog"), path=path)
        for i in range(5):
            upsert_item(**make_item(url=f"https://b.com/{i}", source="Big Blog"), path=path)

        result = get_source_stats(path, min_items=5)
        sources = [r["source"] for r in result]
        assert "Big Blog" in sources
        assert "Small Blog" not in sources

    def test_sorted_by_avg_score_desc(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        for i in range(5):
            upsert_item(**make_item(url=f"https://hi.com/{i}", source="High Blog",
                                   score=0.9), path=path)
            upsert_item(**make_item(url=f"https://lo.com/{i}", source="Low Blog",
                                   score=0.3), path=path)

        result = get_source_stats(path, min_items=5)
        assert result[0]["source"] == "High Blog"
        assert result[1]["source"] == "Low Blog"


class TestGetTagCounts:
    def test_empty_db_returns_empty_list(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        assert get_tag_counts(path) == []

    def test_counts_tags_from_kept_items(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", tags=["python", "sql"]), path=path)
        upsert_item(**make_item(url="https://a.com/2", tags=["python", "llm"]), path=path)
        mark_item("https://a.com/1", "kept", path)
        mark_item("https://a.com/2", "kept", path)

        result = get_tag_counts(path, status="kept")
        tag_map = {r["tag"]: r["count"] for r in result}
        assert tag_map["python"] == 2
        assert tag_map["sql"] == 1
        assert tag_map["llm"] == 1

    def test_filters_by_status(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", tags=["python"]), path=path)
        mark_item("https://a.com/1", "kept", path)
        upsert_item(**make_item(url="https://a.com/2", tags=["rust"]), path=path)
        mark_item("https://a.com/2", "dismissed", path)

        kept_tags = {r["tag"] for r in get_tag_counts(path, status="kept")}
        dismissed_tags = {r["tag"] for r in get_tag_counts(path, status="dismissed")}
        assert "python" in kept_tags
        assert "rust" not in kept_tags
        assert "rust" in dismissed_tags

    def test_sorted_by_count_desc(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        for i in range(3):
            upsert_item(**make_item(url=f"https://a.com/{i}", tags=["popular"]), path=path)
            mark_item(f"https://a.com/{i}", "kept", path)
        upsert_item(**make_item(url="https://a.com/99", tags=["rare"]), path=path)
        mark_item("https://a.com/99", "kept", path)

        result = get_tag_counts(path, status="kept")
        assert result[0]["tag"] == "popular"
        assert result[0]["count"] == 3

    def test_respects_limit(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        tags = [f"tag{i}" for i in range(20)]
        upsert_item(**make_item(url="https://a.com/1", tags=tags), path=path)
        mark_item("https://a.com/1", "kept", path)

        result = get_tag_counts(path, status="kept", limit=5)
        assert len(result) == 5

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
        row = conn.execute("SELECT status FROM items WHERE url = ?", ("https://a.com/1",)).fetchone()
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
        row = conn.execute("SELECT reviewed_at FROM items WHERE url = ?", ("https://a.com/1",)).fetchone()
        conn.close()
        assert row[0] is not None


class TestGetScoreDistribution:
    def test_empty_db_returns_all_zero_buckets(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        result = get_score_distribution(path)
        assert len(result) == 10
        assert all(d["count"] == 0 for d in result)

    def test_buckets_sorted_ascending(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        result = get_score_distribution(path)
        buckets = [d["bucket"] for d in result]
        assert buckets == sorted(buckets)

    def test_score_counted_in_correct_bucket(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(score=0.85), path=path)
        result = get_score_distribution(path)
        by_bucket = {d["bucket"]: d["count"] for d in result}
        assert by_bucket["0.8"] == 1
        assert by_bucket["0.9"] == 0

    def test_score_1_counted_in_0_9_bucket(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(score=1.0), path=path)
        result = get_score_distribution(path)
        by_bucket = {d["bucket"]: d["count"] for d in result}
        assert by_bucket["0.9"] == 1

    def test_filters_by_status(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", score=0.9), path=path)
        upsert_item(**make_item(url="https://a.com/2", score=0.5), path=path)
        mark_item("https://a.com/2", "dismissed", path)
        new_dist = {d["bucket"]: d["count"] for d in get_score_distribution(path, status="new")}
        dismissed_dist = {d["bucket"]: d["count"] for d in get_score_distribution(path, status="dismissed")}
        assert new_dist["0.9"] == 1
        assert dismissed_dist["0.5"] == 1


class TestUpdateItemScore:
    def test_updates_score_tags_summary(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1", score=0.5, tags=["old"], summary="Old."), path=path)

        update_item_score(url="https://a.com/1", score=0.9, tags=["new", "tag"], summary="New summary.", path=path)

        items = get_new_items(path)
        assert items[0]["score"] == 0.9
        assert items[0]["tags"] == ["new", "tag"]
        assert items[0]["summary"] == "New summary."

    def test_does_not_change_status(self, tmp_path):
        path = db(tmp_path)
        init_db(path)
        upsert_item(**make_item(url="https://a.com/1"), path=path)

        update_item_score(url="https://a.com/1", score=0.3, tags=[], summary="Low.", path=path)

        items = get_new_items(path)
        assert len(items) == 1  # still 'new', not auto-dismissed

    def test_no_op_for_unknown_url(self, tmp_path):
        path = db(tmp_path)
        init_db(path)

        # Should not raise
        update_item_score(url="https://ghost.example.com/", score=0.9, tags=[], summary="Ghost.", path=path)
