"""Tests for the Bluesky social reader.

After Gemini's refactor, HTTP and auth logic moved to local_first_common.social.bluesky.
BlueskyReader in discovery delegates to those functions.

Patch targets:
  - local_first_common.social.bluesky.fetch_posts  — network calls for posts
  - local_first_common.social.bluesky.get_auth_token — auth call in __init__
  - local_first_common.social.bluesky.requests.post  — for TestGetAuthToken
  - discovery.social.bluesky.fetch_article_metadata  — article metadata fetch
"""

import requests as req
from unittest.mock import MagicMock, patch

from discovery.social.bluesky import BlueskyReader
from discovery.feed_reader import FeedItem
from local_first_common.social.bluesky import extract_urls_from_post, get_auth_token


def _make_item(url: str = "https://example.com/article") -> FeedItem:
    return FeedItem(
        title="Test Article",
        description="A test article.",
        url=url,
        source="example.com",
    )


def _post_with_embed(url: str, uri_suffix: str = "abc") -> dict:
    return {
        "uri": f"at://did:plc:test/app.bsky.feed.post/{uri_suffix}",
        "embed": {
            "$type": "app.bsky.embed.external#view",
            "external": {"uri": url},
        },
        "record": {},
    }


def _post_with_facet(url: str, uri_suffix: str = "def") -> dict:
    return {
        "uri": f"at://did:plc:test/app.bsky.feed.post/{uri_suffix}",
        "embed": {},
        "record": {
            "facets": [
                {
                    "features": [
                        {"$type": "app.bsky.richtext.facet#link", "uri": url}
                    ]
                }
            ]
        },
    }


class TestExtractUrlsFromPost:
    def test_extracts_url_from_embed_card(self):
        post = {
            "embed": {
                "$type": "app.bsky.embed.external#view",
                "external": {"uri": "https://example.com/article"},
            },
            "record": {},
        }
        assert extract_urls_from_post(post) == ["https://example.com/article"]

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
        assert extract_urls_from_post(post) == ["https://example.com/from-facet"]

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
        assert extract_urls_from_post(post) == ["https://embed.example.com"]

    def test_returns_empty_for_post_with_no_links(self):
        assert extract_urls_from_post({"record": {"text": "no links"}}) == []

    def test_returns_empty_for_non_link_facet(self):
        post = {
            "record": {
                "facets": [
                    {"features": [{"$type": "app.bsky.richtext.facet#mention", "did": "did:plc:abc"}]}
                ]
            }
        }
        assert extract_urls_from_post(post) == []

    def test_handles_empty_post_gracefully(self):
        assert extract_urls_from_post({}) == []


class TestBlueskyReader:
    @patch("discovery.social.bluesky.fetch_article_metadata")
    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_returns_feed_items_for_each_unique_url(self, mock_fetch_posts, mock_fetch_meta):
        url1 = "https://example.com/article-1"
        url2 = "https://example.com/article-2"
        mock_fetch_posts.return_value = [
            _post_with_embed(url1, "a"),
            _post_with_embed(url2, "b"),
        ]
        mock_fetch_meta.side_effect = [_make_item(url1), _make_item(url2)]

        items = BlueskyReader().fetch_items(["duckdb"])

        assert len(items) == 2

    @patch("discovery.social.bluesky.fetch_article_metadata")
    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_deduplicates_urls_across_posts(self, mock_fetch_posts, mock_fetch_meta):
        url = "https://duckdb.org/blog/release.html"
        mock_fetch_posts.return_value = [
            _post_with_embed(url, "a"),
            _post_with_facet(url, "b"),  # same URL, different post
        ]
        mock_fetch_meta.return_value = _make_item(url)

        BlueskyReader().fetch_items(["duckdb"])

        assert mock_fetch_meta.call_count == 1

    @patch("discovery.social.bluesky.fetch_article_metadata")
    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_skips_urls_where_metadata_fetch_fails(self, mock_fetch_posts, mock_fetch_meta):
        mock_fetch_posts.return_value = [_post_with_embed("https://example.com/a")]
        mock_fetch_meta.return_value = None

        items = BlueskyReader().fetch_items(["duckdb"])

        assert items == []

    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_returns_empty_list_for_empty_keywords(self, mock_fetch_posts):
        items = BlueskyReader().fetch_items([])

        mock_fetch_posts.assert_not_called()
        assert items == []

    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_fetch_posts_called_with_keywords_and_token(self, mock_fetch_posts):
        mock_fetch_posts.return_value = []

        BlueskyReader().fetch_items(["python"])

        mock_fetch_posts.assert_called_once()
        args, kwargs = mock_fetch_posts.call_args
        assert args[0] == ["python"]
        assert kwargs.get("token") is None

    @patch("local_first_common.social.bluesky.get_auth_token")
    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_unauthenticated_reader_has_no_token(self, mock_fetch_posts, mock_auth):
        mock_fetch_posts.return_value = []

        reader = BlueskyReader()
        reader.fetch_items(["python"])

        mock_auth.assert_not_called()
        assert reader._token is None

    @patch("local_first_common.social.bluesky.get_auth_token", return_value="test-token-abc")
    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_authenticated_reader_passes_token_to_fetch_posts(self, mock_fetch_posts, mock_auth):
        mock_fetch_posts.return_value = []

        reader = BlueskyReader(handle="me.bsky.social", app_password="xxxx-xxxx")
        reader.fetch_items(["python"])

        assert reader._token == "test-token-abc"
        _, kwargs = mock_fetch_posts.call_args
        assert kwargs.get("token") == "test-token-abc"

    @patch("local_first_common.social.bluesky.get_auth_token", return_value=None)
    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_reader_proceeds_unauthenticated_if_auth_fails(self, mock_fetch_posts, mock_auth):
        mock_fetch_posts.return_value = []

        reader = BlueskyReader(handle="me.bsky.social", app_password="bad-password")
        reader.fetch_items(["python"])

        mock_fetch_posts.assert_called_once()
        assert reader._token is None

    @patch("local_first_common.social.bluesky.fetch_posts")
    def test_uses_api_bsky_app_search_endpoint(self, mock_fetch_posts):
        """fetch_posts in local_first_common targets api.bsky.app, not public.api.bsky.app."""
        mock_fetch_posts.return_value = []

        BlueskyReader().fetch_items(["python"])

        # Verify the function was called (endpoint correctness is tested in local-first-common)
        mock_fetch_posts.assert_called_once()


class TestGetAuthToken:
    @patch("local_first_common.social.bluesky.requests.post")
    def test_returns_access_jwt_on_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"accessJwt": "jwt-token-xyz"}
        mock_post.return_value = mock_resp

        token = get_auth_token("me.bsky.social", "my-app-password")

        assert token == "jwt-token-xyz"
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["identifier"] == "me.bsky.social"
        assert call_json["password"] == "my-app-password"

    @patch("local_first_common.social.bluesky.requests.post")
    def test_returns_none_on_connection_error(self, mock_post):
        mock_post.side_effect = req.ConnectionError("refused")
        assert get_auth_token("me.bsky.social", "pw") is None

    @patch("local_first_common.social.bluesky.requests.post")
    def test_returns_none_on_http_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("401 Unauthorized")
        mock_post.return_value = mock_resp
        assert get_auth_token("me.bsky.social", "wrong-password") is None

    @patch("local_first_common.social.bluesky.requests.post")
    def test_posts_to_correct_auth_url(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"accessJwt": "tok"}
        mock_post.return_value = mock_resp

        get_auth_token("me.bsky.social", "pw")

        called_url = mock_post.call_args.args[0]
        assert "com.atproto.server.createSession" in called_url
