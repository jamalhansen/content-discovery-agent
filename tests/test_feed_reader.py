import os
import pytest
from unittest.mock import patch, MagicMock
from feed_reader import fetch_feed, filter_new_items, FeedItem

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_FEED_PATH = os.path.join(FIXTURES_DIR, "sample_feed.xml")
SAMPLE_FEED_URL = "https://example.com/feed.rss"


def mock_response(path: str) -> MagicMock:
    """Return a mock requests.Response whose .content is the fixture file bytes."""
    content = open(path, "rb").read()
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def sample_feed_mock():
    with patch("feed_reader.requests.get", return_value=mock_response(SAMPLE_FEED_PATH)) as m:
        yield m


class TestFetchFeed:
    def test_parses_sample_feed(self, sample_feed_mock):
        items = fetch_feed(SAMPLE_FEED_URL)
        assert len(items) == 6

    def test_extracts_title_and_url(self, sample_feed_mock):
        items = fetch_feed(SAMPLE_FEED_URL)
        titles = [i.title for i in items]
        assert "DuckDB 1.2 Released" in titles
        urls = [i.url for i in items]
        assert "https://example.com/duckdb-1-2" in urls

    def test_source_is_feed_title(self, sample_feed_mock):
        items = fetch_feed(SAMPLE_FEED_URL)
        assert all(i.source == "Test Tech Blog" for i in items)

    def test_returns_empty_on_bad_url(self):
        import requests as req
        with patch("feed_reader.requests.get", side_effect=req.RequestException("connection error")):
            items = fetch_feed("http://localhost:9999/nonexistent-feed")
        assert items == []

    def test_description_populated(self, sample_feed_mock):
        items = fetch_feed(SAMPLE_FEED_URL)
        rag_item = next(i for i in items if "RAG" in i.title)
        assert "retrieval-augmented" in rag_item.description.lower()


class TestFilterNewItems:
    def test_filters_seen_urls(self):
        items = [
            FeedItem("A", "desc", "https://a.com", "src"),
            FeedItem("B", "desc", "https://b.com", "src"),
            FeedItem("C", "desc", "https://c.com", "src"),
        ]
        seen = {"https://a.com", "https://c.com"}
        result = filter_new_items(items, seen)
        assert len(result) == 1
        assert result[0].url == "https://b.com"

    def test_all_new_returns_all(self):
        items = [
            FeedItem("A", "desc", "https://a.com", "src"),
            FeedItem("B", "desc", "https://b.com", "src"),
        ]
        result = filter_new_items(items, set())
        assert len(result) == 2

    def test_all_seen_returns_empty(self):
        items = [FeedItem("A", "desc", "https://a.com", "src")]
        result = filter_new_items(items, {"https://a.com"})
        assert result == []
