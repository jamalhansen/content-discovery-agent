import os
import pytest
from unittest.mock import patch
from feed_reader import FeedItem
from feed_cache import load_cached_feed, save_cached_feed, clear_cache, CACHE_DIR


def make_items() -> list[FeedItem]:
    return [
        FeedItem("Title A", "Desc A", "https://a.com", "Blog A"),
        FeedItem("Title B", "Desc B", "https://b.com", "Blog B"),
    ]


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Redirect cache to a temp dir for each test."""
    cache_dir = str(tmp_path / "feeds")
    monkeypatch.setattr("feed_cache.CACHE_DIR", cache_dir)
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

    def test_clear_noop_if_no_cache_dir(self):
        # Should not raise even if dir doesn't exist
        clear_cache()
