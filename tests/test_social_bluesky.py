import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests as req

from feed_reader import FeedItem
from social.bluesky import BlueskyReader, _extract_urls_from_post, _get_auth_token

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_bluesky_response.json"


def load_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _mock_api_response(data: dict) -> MagicMock:
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


class TestExtractUrlsFromPost:
    def test_extracts_url_from_embed_card(self):
        post = {
            "embed": {
                "$type": "app.bsky.embed.external#view",
                "external": {"uri": "https://example.com/article"},
            },
            "record": {},
        }
        assert _extract_urls_from_post(post) == ["https://example.com/article"]

    def test_extracts_url_from_facets_when_no_embed(self):
        post = {
            "record": {
                "facets": [
                    {
                        "features": [
                            {
                                "$type": "app.bsky.richtext.facet#link",
                                "uri": "https://example.com/from-facet",
                            }
                        ]
                    }
                ]
            }
        }
        assert _extract_urls_from_post(post) == ["https://example.com/from-facet"]

    def test_prefers_embed_card_over_facets(self):
        post = {
            "embed": {
                "$type": "app.bsky.embed.external#view",
                "external": {"uri": "https://embed.example.com"},
            },
            "record": {
                "facets": [
                    {
                        "features": [
                            {
                                "$type": "app.bsky.richtext.facet#link",
                                "uri": "https://facet.example.com",
                            }
                        ]
                    }
                ]
            },
        }
        result = _extract_urls_from_post(post)
        assert result == ["https://embed.example.com"]

    def test_returns_empty_for_post_with_no_links(self):
        post = {"record": {"text": "No links in this post."}}
        assert _extract_urls_from_post(post) == []

    def test_returns_empty_for_non_link_facet(self):
        post = {
            "record": {
                "facets": [
                    {
                        "features": [
                            {"$type": "app.bsky.richtext.facet#mention", "did": "did:plc:abc"}
                        ]
                    }
                ]
            }
        }
        assert _extract_urls_from_post(post) == []

    def test_handles_missing_embed_and_record_gracefully(self):
        assert _extract_urls_from_post({}) == []


class TestBlueskyReader:
    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_returns_feed_items_for_each_unique_url(self, mock_get, mock_fetch):
        data = load_fixture()
        mock_get.return_value = _mock_api_response(data)
        # Fixture has 3 posts: post 1 and 3 share a URL, post 2 has a unique URL
        mock_fetch.side_effect = [
            _make_item("https://duckdb.org/2026/02/05/announcing-duckdb-1.2.0.html"),
            _make_item("https://realpython.com/python-duckdb/"),
        ]

        reader = BlueskyReader()
        items = reader.fetch_items(["duckdb"])

        assert len(items) == 2

    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_deduplicates_urls_across_posts(self, mock_get, mock_fetch):
        """Same URL in 2 posts should only trigger one fetch_article_metadata call."""
        data = load_fixture()
        mock_get.return_value = _mock_api_response(data)
        mock_fetch.return_value = _make_item("https://duckdb.org/2026/02/05/announcing-duckdb-1.2.0.html")

        reader = BlueskyReader()
        reader.fetch_items(["duckdb"])

        duckdb_url = "https://duckdb.org/2026/02/05/announcing-duckdb-1.2.0.html"
        calls_for_duckdb = [c for c in mock_fetch.call_args_list if duckdb_url in str(c)]
        assert len(calls_for_duckdb) == 1

    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_deduplicates_across_keywords(self, mock_get, mock_fetch):
        """Same URL found via two different keywords should only be fetched once."""
        data = {"posts": [
            {
                "embed": {
                    "$type": "app.bsky.embed.external#view",
                    "external": {"uri": "https://shared.example.com/article"},
                },
                "record": {},
            }
        ]}
        mock_get.return_value = _mock_api_response(data)
        mock_fetch.return_value = _make_item("https://shared.example.com/article")

        reader = BlueskyReader()
        reader.fetch_items(["python", "duckdb"])

        assert mock_fetch.call_count == 1

    @patch("social.bluesky.requests.get")
    def test_handles_network_error_gracefully(self, mock_get):
        mock_get.side_effect = req.ConnectionError("connection refused")

        reader = BlueskyReader()
        items = reader.fetch_items(["duckdb"])

        assert items == []

    @patch("social.bluesky.requests.get")
    def test_continues_after_per_keyword_error(self, mock_get):
        """An error on one keyword should not prevent others from running."""
        good_response = _mock_api_response({"posts": []})
        mock_get.side_effect = [
            req.ConnectionError("refused"),  # first keyword fails
            good_response,                   # second keyword succeeds
        ]

        reader = BlueskyReader()
        items = reader.fetch_items(["duckdb", "python"])

        assert items == []  # no items since good response has empty posts
        assert mock_get.call_count == 2

    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_skips_urls_where_metadata_fetch_fails(self, mock_get, mock_fetch):
        data = load_fixture()
        mock_get.return_value = _mock_api_response(data)
        mock_fetch.return_value = None  # every metadata fetch fails

        reader = BlueskyReader()
        items = reader.fetch_items(["duckdb"])

        assert items == []

    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_passes_correct_query_params(self, mock_get, mock_fetch):
        mock_get.return_value = _mock_api_response({"posts": []})

        reader = BlueskyReader()
        reader.fetch_items(["python"])

        mock_get.assert_called_once()
        assert mock_get.call_args.kwargs["params"]["q"] == "python"
        assert mock_get.call_args.kwargs["params"]["limit"] == 25

    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_uses_api_bsky_app_endpoint(self, mock_get, mock_fetch):
        """Requests must go to api.bsky.app, not public.api.bsky.app (which 403s)."""
        mock_get.return_value = _mock_api_response({"posts": []})

        reader = BlueskyReader()
        reader.fetch_items(["python"])

        called_url = mock_get.call_args.args[0]
        assert "api.bsky.app" in called_url
        assert "public.api.bsky.app" not in called_url

    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_returns_empty_list_for_empty_keywords(self, mock_get, mock_fetch):
        reader = BlueskyReader()
        items = reader.fetch_items([])

        mock_get.assert_not_called()
        assert items == []

    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_unauthenticated_reader_sends_no_auth_header(self, mock_get, mock_fetch):
        """Without credentials, no Authorization header should be sent."""
        mock_get.return_value = _mock_api_response({"posts": []})

        reader = BlueskyReader()  # no handle/app_password
        reader.fetch_items(["python"])

        headers = mock_get.call_args.kwargs.get("headers", {})
        assert "Authorization" not in headers

    @patch("social.bluesky._get_auth_token", return_value="test-token-abc")
    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_authenticated_reader_sends_bearer_token(self, mock_get, mock_fetch, mock_auth):
        """With valid credentials, Authorization: Bearer header should be sent."""
        mock_get.return_value = _mock_api_response({"posts": []})

        reader = BlueskyReader(handle="me.bsky.social", app_password="xxxx-xxxx")
        reader.fetch_items(["python"])

        headers = mock_get.call_args.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer test-token-abc"

    @patch("social.bluesky._get_auth_token", return_value=None)
    @patch("social.bluesky.fetch_article_metadata")
    @patch("social.bluesky.requests.get")
    def test_reader_proceeds_unauthenticated_if_auth_fails(self, mock_get, mock_fetch, mock_auth):
        """If _get_auth_token returns None, reader should still fetch (no header)."""
        mock_get.return_value = _mock_api_response({"posts": []})

        reader = BlueskyReader(handle="me.bsky.social", app_password="bad-password")
        reader.fetch_items(["python"])

        mock_get.assert_called_once()
        headers = mock_get.call_args.kwargs.get("headers", {})
        assert "Authorization" not in headers


class TestGetAuthToken:
    @patch("social.bluesky.requests.post")
    def test_returns_access_jwt_on_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"accessJwt": "jwt-token-xyz", "refreshJwt": "refresh-xyz"}
        mock_post.return_value = mock_resp

        token = _get_auth_token("me.bsky.social", "my-app-password")

        assert token == "jwt-token-xyz"
        mock_post.assert_called_once()
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["identifier"] == "me.bsky.social"
        assert call_json["password"] == "my-app-password"

    @patch("social.bluesky.requests.post")
    def test_returns_none_on_connection_error(self, mock_post):
        mock_post.side_effect = req.ConnectionError("refused")
        token = _get_auth_token("me.bsky.social", "my-app-password")
        assert token is None

    @patch("social.bluesky.requests.post")
    def test_returns_none_on_http_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("401 Unauthorized")
        mock_post.return_value = mock_resp

        token = _get_auth_token("me.bsky.social", "wrong-password")
        assert token is None

    @patch("social.bluesky.requests.post")
    def test_posts_to_correct_auth_url(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"accessJwt": "tok"}
        mock_post.return_value = mock_resp

        _get_auth_token("me.bsky.social", "pw")

        called_url = mock_post.call_args.args[0]
        assert "com.atproto.server.createSession" in called_url
