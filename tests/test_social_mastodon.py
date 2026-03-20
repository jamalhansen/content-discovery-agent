"""Tests for the Mastodon social reader.

After Gemini's refactor, HTTP logic moved to local_first_common.social.mastodon.
MastodonReader in discovery delegates to mastodon.fetch_posts.

Note: the original _keyword_to_hashtag() function (which stripped spaces and hyphens
from multi-word keywords) was removed during refactoring. local_first_common now uses
keyword.lstrip("#") only — multi-word keywords should be pre-normalised by the caller.

Patch targets:
  - local_first_common.social.mastodon.fetch_posts      — network calls
  - discovery.social.mastodon.fetch_article_metadata    — article metadata fetch
"""

import requests as req
from unittest.mock import MagicMock, patch

from discovery.social.mastodon import MastodonReader
from discovery.feed_reader import FeedItem


def _make_item(url: str = "https://example.com/article") -> FeedItem:
    return FeedItem(
        title="Test Article",
        description="A test article.",
        url=url,
        source="example.com",
    )


def _status_with_card(url: str) -> dict:
    return {"card": {"url": url, "title": "Article", "type": "link"}}


def _status_without_card() -> dict:
    return {"card": None, "content": "<p>No link card</p>"}


class TestMastodonReader:
    @patch("discovery.social.mastodon.fetch_article_metadata")
    @patch("local_first_common.social.mastodon.fetch_posts")
    def test_returns_feed_items_for_posts_with_cards(self, mock_fetch_posts, mock_fetch_meta):
        url1 = "https://motherduck.com/blog/release/"
        url2 = "https://docs.python.org/3.14/whatsnew/3.14.html"
        mock_fetch_posts.return_value = [
            _status_with_card(url1),
            _status_without_card(),
            _status_with_card(url2),
        ]
        mock_fetch_meta.side_effect = [_make_item(url1), _make_item(url2)]

        items = MastodonReader(instances=["mastodon.social"]).fetch_items(["duckdb"])

        assert len(items) == 2

    @patch("discovery.social.mastodon.fetch_article_metadata")
    @patch("local_first_common.social.mastodon.fetch_posts")
    def test_skips_statuses_without_card(self, mock_fetch_posts, mock_fetch_meta):
        mock_fetch_posts.return_value = [_status_without_card()]

        MastodonReader(instances=["mastodon.social"]).fetch_items(["duckdb"])

        mock_fetch_meta.assert_not_called()

    @patch("discovery.social.mastodon.fetch_article_metadata")
    @patch("local_first_common.social.mastodon.fetch_posts")
    def test_deduplicates_urls_across_statuses(self, mock_fetch_posts, mock_fetch_meta):
        url = "https://example.com/shared-article"
        mock_fetch_posts.return_value = [_status_with_card(url), _status_with_card(url)]
        mock_fetch_meta.return_value = _make_item(url)

        items = MastodonReader(instances=["mastodon.social"]).fetch_items(["duckdb"])

        assert mock_fetch_meta.call_count == 1
        assert len(items) == 1

    @patch("discovery.social.mastodon.fetch_article_metadata")
    @patch("local_first_common.social.mastodon.fetch_posts")
    def test_skips_urls_where_metadata_fetch_fails(self, mock_fetch_posts, mock_fetch_meta):
        mock_fetch_posts.return_value = [_status_with_card("https://example.com/a")]
        mock_fetch_meta.return_value = None

        items = MastodonReader(instances=["mastodon.social"]).fetch_items(["duckdb"])

        assert items == []

    @patch("local_first_common.social.mastodon.fetch_posts")
    def test_returns_empty_for_empty_keywords(self, mock_fetch_posts):
        items = MastodonReader(instances=["mastodon.social"]).fetch_items([])

        mock_fetch_posts.assert_not_called()
        assert items == []

    @patch("local_first_common.social.mastodon.requests.get")
    def test_builds_correct_api_url(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        MastodonReader(instances=["fosstodon.org"]).fetch_items(["python"])

        called_url = mock_get.call_args.args[0]
        assert called_url == "https://fosstodon.org/api/v1/timelines/tag/python"

    @patch("local_first_common.social.mastodon.requests.get")
    def test_default_instance_is_mastodon_social(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        MastodonReader().fetch_items(["duckdb"])

        called_url = mock_get.call_args.args[0]
        assert "mastodon.social" in called_url

    @patch("local_first_common.social.mastodon.requests.get")
    def test_handles_network_error_gracefully(self, mock_get):
        mock_get.side_effect = req.ConnectionError("connection refused")

        items = MastodonReader(instances=["mastodon.social"]).fetch_items(["duckdb"])

        assert items == []

    @patch("local_first_common.social.mastodon.requests.get")
    def test_continues_after_per_instance_error(self, mock_get):
        good_response = MagicMock()
        good_response.raise_for_status = MagicMock()
        good_response.json.return_value = []
        mock_get.side_effect = [
            req.ConnectionError("refused"),  # first instance fails
            good_response,                   # second succeeds
        ]

        items = MastodonReader(instances=["bad.instance", "mastodon.social"]).fetch_items(["duckdb"])

        assert items == []
        assert mock_get.call_count == 2

    @patch("discovery.social.mastodon.fetch_article_metadata")
    @patch("local_first_common.social.mastodon.fetch_posts")
    def test_fetch_posts_called_with_instances(self, mock_fetch_posts, mock_fetch_meta):
        mock_fetch_posts.return_value = []

        MastodonReader(instances=["fosstodon.org"]).fetch_items(["duckdb"])

        _, kwargs = mock_fetch_posts.call_args
        assert kwargs.get("instances") == ["fosstodon.org"]
