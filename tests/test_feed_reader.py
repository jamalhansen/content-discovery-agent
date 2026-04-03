import os
import pytest
from unittest.mock import patch, MagicMock
from discovery.feed_reader import fetch_feed, filter_new_items, FeedItem

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_FEED_PATH = os.path.join(FIXTURES_DIR, "sample_feed.xml")
SAMPLE_FEED_URL = "https://example.com/feed.rss"


def mock_response(path: str) -> MagicMock:
    """Return a mock requests.Response whose .content is the fixture file bytes."""
    with open(path, "rb") as f:
        content = f.read()
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def sample_feed_mock():
    with patch("discovery.feed_reader.requests.get", return_value=mock_response(SAMPLE_FEED_PATH)) as m:
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
        with patch("discovery.feed_reader.requests.get", side_effect=req.RequestException("connection error")):
            items = fetch_feed("http://localhost:9999/nonexistent-feed")
        assert items == []

    def test_description_populated(self, sample_feed_mock):
        items = fetch_feed(SAMPLE_FEED_URL)
        rag_item = next(i for i in items if "RAG" in i.title)
        assert "retrieval-augmented" in rag_item.description.lower()

    def test_published_date_extracted_when_present(self, sample_feed_mock):
        items = fetch_feed(SAMPLE_FEED_URL)
        duckdb_item = next(i for i in items if "DuckDB" in i.title)
        assert duckdb_item.published == "2026-03-07"

    def test_published_empty_when_absent(self, sample_feed_mock):
        items = fetch_feed(SAMPLE_FEED_URL)
        rag_item = next(i for i in items if i.title == "Building a Local RAG Pipeline with Ollama")
        assert rag_item.published == ""


class TestFilterNewItems:
    def test_filters_seen_urls(self):
        items = [
            FeedItem(title="A", description="desc", url="https://a.com", source="src"),
            FeedItem(title="B", description="desc", url="https://b.com", source="src"),
            FeedItem(title="C", description="desc", url="https://c.com", source="src"),
        ]
        seen = {"https://a.com", "https://c.com"}
        result = filter_new_items(items, seen)
        assert len(result) == 1
        assert result[0].url == "https://b.com"

    def test_all_new_returns_all(self):
        items = [
            FeedItem(title="A", description="desc", url="https://a.com", source="src"),
            FeedItem(title="B", description="desc", url="https://b.com", source="src"),
        ]
        result = filter_new_items(items, set())
        assert len(result) == 2

    def test_all_seen_returns_empty(self):
        items = [FeedItem(title="A", description="desc", url="https://a.com", source="src")]
        result = filter_new_items(items, {"https://a.com"})
        assert result == []
