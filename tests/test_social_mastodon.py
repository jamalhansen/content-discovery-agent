import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests as req

from feed_reader import FeedItem
from social.mastodon import MastodonReader, _keyword_to_hashtag

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_mastodon_response.json"


def load_fixture() -> list:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _mock_api_response(data: list) -> MagicMock:
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


def _make_item(url: str = "https://example.com/article") -> FeedItem:
    return FeedItem(
        title="Test Article",
        description="A test article.",
        url=url,
        source="example.com",
    )


class TestKeywordToHashtag:
    def test_single_word_unchanged(self):
        assert _keyword_to_hashtag("python") == "python"

    def test_strips_spaces(self):
        assert _keyword_to_hashtag("local ai") == "localai"

    def test_strips_hyphens(self):
        assert _keyword_to_hashtag("duck-db") == "duckdb"

    def test_strips_spaces_and_hyphens(self):
        assert _keyword_to_hashtag("local-first ai") == "localfirstai"


class TestMastodonReader:
    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_returns_feed_items_for_posts_with_cards(self, mock_get, mock_fetch):
        data = load_fixture()
        mock_get.return_value = _mock_api_response(data)
        # Fixture has 3 statuses: 2 with cards, 1 without
        mock_fetch.side_effect = [
            _make_item("https://motherduck.com/blog/duckdb-1-2-release/"),
            _make_item("https://docs.python.org/3.14/whatsnew/3.14.html"),
        ]

        reader = MastodonReader(instances=["mastodon.social"])
        items = reader.fetch_items(["duckdb"])

        assert len(items) == 2

    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_skips_statuses_without_card(self, mock_get, mock_fetch):
        """Status with card=null should not trigger a fetch_article_metadata call."""
        data = [{"card": None, "content": "<p>No link card</p>"}]
        mock_get.return_value = _mock_api_response(data)

        reader = MastodonReader(instances=["mastodon.social"])
        reader.fetch_items(["duckdb"])

        mock_fetch.assert_not_called()

    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_deduplicates_urls_across_statuses(self, mock_get, mock_fetch):
        """Same article URL in two statuses should only be fetched once."""
        url = "https://example.com/shared-article"
        data = [
            {"card": {"url": url, "title": "Article", "type": "link"}},
            {"card": {"url": url, "title": "Article", "type": "link"}},
        ]
        mock_get.return_value = _mock_api_response(data)
        mock_fetch.return_value = _make_item(url)

        reader = MastodonReader(instances=["mastodon.social"])
        items = reader.fetch_items(["duckdb"])

        assert mock_fetch.call_count == 1
        assert len(items) == 1

    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_deduplicates_urls_across_instances(self, mock_get, mock_fetch):
        """Same URL found on two different instances should only be fetched once."""
        url = "https://example.com/article"
        data = [{"card": {"url": url, "title": "Article", "type": "link"}}]
        mock_get.return_value = _mock_api_response(data)
        mock_fetch.return_value = _make_item(url)

        reader = MastodonReader(instances=["mastodon.social", "fosstodon.org"])
        items = reader.fetch_items(["duckdb"])

        assert mock_fetch.call_count == 1
        assert len(items) == 1

    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_builds_correct_api_url(self, mock_get, mock_fetch):
        mock_get.return_value = _mock_api_response([])

        reader = MastodonReader(instances=["fosstodon.org"])
        reader.fetch_items(["python"])

        mock_get.assert_called_once()
        called_url = mock_get.call_args.args[0]
        assert called_url == "https://fosstodon.org/api/v1/timelines/tag/python"

    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_converts_multi_word_keyword_to_hashtag(self, mock_get, mock_fetch):
        mock_get.return_value = _mock_api_response([])

        reader = MastodonReader(instances=["mastodon.social"])
        reader.fetch_items(["local ai"])

        called_url = mock_get.call_args.args[0]
        assert "localai" in called_url

    @patch("social.mastodon.requests.get")
    def test_handles_network_error_gracefully(self, mock_get):
        mock_get.side_effect = req.ConnectionError("connection refused")

        reader = MastodonReader(instances=["mastodon.social"])
        items = reader.fetch_items(["duckdb"])

        assert items == []

    @patch("social.mastodon.requests.get")
    def test_continues_after_per_instance_error(self, mock_get):
        """Error on one instance should not prevent the other from running."""
        mock_get.side_effect = [
            req.ConnectionError("refused"),  # first instance fails
            _mock_api_response([]),          # second instance succeeds
        ]

        reader = MastodonReader(instances=["bad.instance", "mastodon.social"])
        items = reader.fetch_items(["duckdb"])

        assert items == []
        assert mock_get.call_count == 2

    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_skips_urls_where_metadata_fetch_fails(self, mock_get, mock_fetch):
        data = load_fixture()
        mock_get.return_value = _mock_api_response(data)
        mock_fetch.return_value = None

        reader = MastodonReader(instances=["mastodon.social"])
        items = reader.fetch_items(["duckdb"])

        assert items == []

    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_default_instance_is_mastodon_social(self, mock_get, mock_fetch):
        mock_get.return_value = _mock_api_response([])

        reader = MastodonReader()
        reader.fetch_items(["duckdb"])

        called_url = mock_get.call_args.args[0]
        assert "mastodon.social" in called_url

    @patch("social.mastodon.fetch_article_metadata")
    @patch("social.mastodon.requests.get")
    def test_returns_empty_for_empty_keywords(self, mock_get, mock_fetch):
        reader = MastodonReader(instances=["mastodon.social"])
        items = reader.fetch_items([])

        mock_get.assert_not_called()
        assert items == []
