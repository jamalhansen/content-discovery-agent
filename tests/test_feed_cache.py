import os
import pytest
from feed_reader import FeedItem
from feed_cache import (
    load_cached_feed, save_cached_feed, clear_cache, load_cached_social, save_cached_social,
)


def make_items() -> list[FeedItem]:
    return [
        FeedItem("Title A", "Desc A", "https://a.com", "Blog A"),
        FeedItem("Title B", "Desc B", "https://b.com", "Blog B"),
    ]


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Redirect both caches to temp dirs for each test."""
    cache_dir = str(tmp_path / "feeds")
    social_cache_dir = str(tmp_path / "social")
    monkeypatch.setattr("feed_cache.CACHE_DIR", cache_dir)
    monkeypatch.setattr("feed_cache.SOCIAL_CACHE_DIR", social_cache_dir)
    return cache_dir


class TestLoadCachedFeed:
    def test_returns_none_when_no_cache(self):
        result = load_cached_feed("https://example.com/feed")
        assert result is None

    def test_returns_items_after_save(self):
        items = make_items()
        save_cached_feed("https://example.com/feed", items)
        result = load_cached_feed("https://example.com/feed")
        assert result is not None
        assert len(result) == 2
        assert result[0].title == "Title A"
        assert result[0].url == "https://a.com"

    def test_different_urls_have_separate_caches(self):
        items_a = [FeedItem("A", "d", "https://a.com", "src")]
        items_b = [FeedItem("B", "d", "https://b.com", "src")]
        save_cached_feed("https://feed-a.com", items_a)
        save_cached_feed("https://feed-b.com", items_b)

        assert load_cached_feed("https://feed-a.com")[0].title == "A"
        assert load_cached_feed("https://feed-b.com")[0].title == "B"

    def test_returns_none_for_stale_cache(self, monkeypatch):
        save_cached_feed("https://example.com/feed", make_items())
        monkeypatch.setattr("feed_cache.CACHE_TTL_SECONDS", 0)
        assert load_cached_feed("https://example.com/feed") is None

    def test_returns_items_for_fresh_cache(self, monkeypatch):
        save_cached_feed("https://example.com/feed", make_items())
        # TTL far in the future — cache is always fresh
        monkeypatch.setattr("feed_cache.CACHE_TTL_SECONDS", 10 * 365 * 24 * 60 * 60)
        assert load_cached_feed("https://example.com/feed") is not None


class TestSaveCachedFeed:
    def test_creates_cache_dir_if_missing(self, isolated_cache):
        assert not os.path.exists(isolated_cache)
        save_cached_feed("https://example.com/feed", make_items())
        assert os.path.isdir(isolated_cache)

    def test_round_trip_preserves_all_fields(self):
        original = make_items()
        save_cached_feed("https://example.com/feed", original)
        loaded = load_cached_feed("https://example.com/feed")
        for orig, got in zip(original, loaded):
            assert orig.title == got.title
            assert orig.description == got.description
            assert orig.url == got.url
            assert orig.source == got.source


class TestClearCache:
    def test_clear_removes_cached_files(self, isolated_cache):
        os.makedirs(isolated_cache)
        save_cached_feed("https://a.com/feed", make_items())
        save_cached_feed("https://b.com/feed", make_items())
        clear_cache()
        assert load_cached_feed("https://a.com/feed") is None
        assert load_cached_feed("https://b.com/feed") is None

    def test_clear_also_removes_social_cache(self):
        save_cached_social("bluesky", ["duckdb"], make_items())
        clear_cache()
        assert load_cached_social("bluesky", ["duckdb"]) is None

    def test_clear_noop_if_no_cache_dir(self):
        # Should not raise even if neither dir exists
        clear_cache()


class TestSocialCache:
    def test_returns_none_when_no_cache(self):
        assert load_cached_social("bluesky", ["duckdb"]) is None

    def test_round_trip_preserves_all_fields(self):
        items = make_items()
        save_cached_social("bluesky", ["duckdb", "python"], items)
        loaded = load_cached_social("bluesky", ["duckdb", "python"])
        assert loaded is not None
        assert len(loaded) == 2
        for orig, got in zip(items, loaded):
            assert orig.title == got.title
            assert orig.description == got.description
            assert orig.url == got.url
            assert orig.source == got.source

    def test_different_sources_have_separate_caches(self):
        bluesky_items = [FeedItem("Bluesky", "d", "https://b.com", "src")]
        mastodon_items = [FeedItem("Mastodon", "d", "https://m.com", "src")]
        save_cached_social("bluesky", ["duckdb"], bluesky_items)
        save_cached_social("mastodon", ["duckdb"], mastodon_items)
        assert load_cached_social("bluesky", ["duckdb"])[0].title == "Bluesky"
        assert load_cached_social("mastodon", ["duckdb"])[0].title == "Mastodon"

    def test_cache_key_is_keyword_order_independent(self):
        items = make_items()
        save_cached_social("bluesky", ["python", "duckdb"], items)
        # Keywords in different order should hit the same cache
        loaded = load_cached_social("bluesky", ["duckdb", "python"])
        assert loaded is not None
        assert len(loaded) == 2

    def test_different_keyword_sets_have_separate_caches(self):
        items_a = [FeedItem("A", "d", "https://a.com", "src")]
        items_b = [FeedItem("B", "d", "https://b.com", "src")]
        save_cached_social("bluesky", ["duckdb"], items_a)
        save_cached_social("bluesky", ["python"], items_b)
        assert load_cached_social("bluesky", ["duckdb"])[0].title == "A"
        assert load_cached_social("bluesky", ["python"])[0].title == "B"

    def test_creates_social_cache_dir_if_missing(self, tmp_path, monkeypatch):
        social_dir = str(tmp_path / "social")
        monkeypatch.setattr("feed_cache.SOCIAL_CACHE_DIR", social_dir)
        assert not os.path.exists(social_dir)
        save_cached_social("bluesky", ["duckdb"], make_items())
        assert os.path.isdir(social_dir)

    def test_returns_none_for_stale_social_cache(self, monkeypatch):
        save_cached_social("bluesky", ["duckdb"], make_items())
        monkeypatch.setattr("feed_cache.CACHE_TTL_SECONDS", 0)
        assert load_cached_social("bluesky", ["duckdb"]) is None

    def test_returns_items_for_fresh_social_cache(self, monkeypatch):
        save_cached_social("bluesky", ["duckdb"], make_items())
        monkeypatch.setattr("feed_cache.CACHE_TTL_SECONDS", 10 * 365 * 24 * 60 * 60)
        assert load_cached_social("bluesky", ["duckdb"]) is not None
