"""Tests for discovery.support.article_fetcher."""

from pathlib import Path
from unittest.mock import patch

from local_first_common.http import FetchError

from discovery.support.article_fetcher import (
    FeedItem,
    _derive_metadata_from_rendered_text,
    _is_blocked,
    fetch_article_metadata,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_article.html"
SAMPLE_HTML = FIXTURE_PATH.read_text()

FALLBACK_HTML = """
<!DOCTYPE html>
<html><head>
  <title>Fallback Title Only</title>
  <meta name="description" content="Fallback description from meta tag." />
</head><body><p>Content.</p></body></html>
"""

NO_TITLE_HTML = """
<!DOCTYPE html>
<html><head><meta property="og:description" content="No title here." /></head>
<body></body></html>
"""


class TestFeedItem:
    def test_required_fields(self):
        item = FeedItem(title="T", description="D", url="https://example.com", source="example.com")
        assert item.title == "T"
        assert item.description == "D"
        assert item.url == "https://example.com"
        assert item.source == "example.com"

    def test_published_defaults_to_empty(self):
        item = FeedItem(title="T", description="D", url="u", source="s")
        assert item.published == ""

    def test_found_at_defaults_to_none(self):
        item = FeedItem(title="T", description="D", url="u", source="s")
        assert item.found_at is None

    def test_discovery_metadata_defaults_to_none(self):
        item = FeedItem(title="T", description="D", url="u", source="s")
        assert item.search_term is None
        assert item.platform is None


class TestFetchArticleMetadata:
    def test_extracts_og_title_and_og_description(self):
        with patch("local_first_common.http.fetch_url", return_value=SAMPLE_HTML):
            item = fetch_article_metadata("https://duckdb.org/article")

        assert item is not None
        assert item.title == "Understanding DuckDB: A Practical Guide"
        assert item.description == "A comprehensive guide to using DuckDB for fast in-process data analysis."

    def test_source_is_netloc(self):
        with patch("local_first_common.http.fetch_url", return_value=SAMPLE_HTML):
            item = fetch_article_metadata("https://duckdb.org/article")

        assert item is not None
        assert item.source == "duckdb.org"

    def test_extracts_article_published_time(self):
        with patch("local_first_common.http.fetch_url", return_value=SAMPLE_HTML):
            item = fetch_article_metadata("https://duckdb.org/article")

        assert item is not None
        assert item.published == "2026-02-15"

    def test_published_empty_when_no_date_meta(self):
        with patch("local_first_common.http.fetch_url", return_value=FALLBACK_HTML):
            item = fetch_article_metadata("https://example.com/page")

        assert item is not None
        assert item.published == ""

    def test_url_is_preserved(self):
        url = "https://duckdb.org/2026/02/05/release.html"
        with patch("local_first_common.http.fetch_url", return_value=SAMPLE_HTML):
            item = fetch_article_metadata(url)

        assert item is not None
        assert item.url == url

    def test_found_at_is_none_when_no_source_url(self):
        with patch("local_first_common.http.fetch_url", return_value=SAMPLE_HTML):
            item = fetch_article_metadata("https://duckdb.org/article")

        assert item is not None
        assert item.found_at is None

    def test_found_at_is_set_from_source_url(self):
        post_url = "https://bsky.app/profile/user.bsky.social/post/abc123"
        with patch("local_first_common.http.fetch_url", return_value=SAMPLE_HTML):
            item = fetch_article_metadata("https://duckdb.org/article", source_url=post_url)

        assert item is not None
        assert item.found_at == post_url

    def test_discovery_metadata_is_passed_through(self):
        with patch("local_first_common.http.fetch_url", return_value=SAMPLE_HTML):
            item = fetch_article_metadata("https://duckdb.org/article", search_term="duckdb", source_platform="bluesky")

        assert item is not None
        assert item.search_term == "duckdb"
        assert item.platform == "bluesky"

    def test_falls_back_to_title_tag_when_no_og_title(self):
        with patch("local_first_common.http.fetch_url", return_value=FALLBACK_HTML):
            item = fetch_article_metadata("https://example.com/page")

        assert item is not None
        assert item.title == "Fallback Title Only"

    def test_falls_back_to_meta_description_when_no_og_description(self):
        with patch("local_first_common.http.fetch_url", return_value=FALLBACK_HTML):
            item = fetch_article_metadata("https://example.com/page")

        assert item is not None
        assert item.description == "Fallback description from meta tag."

    def test_returns_none_when_no_title_found(self):
        with patch("local_first_common.http.fetch_url", return_value=NO_TITLE_HTML):
            item = fetch_article_metadata("https://example.com/no-title")

        assert item is None

    def test_returns_none_on_connection_error(self):
        with patch("local_first_common.http.fetch_url", side_effect=FetchError("connection error")):
            item = fetch_article_metadata("https://unreachable.example.com/")

        assert item is None

    def test_returns_none_on_http_error(self):
        with patch("local_first_common.http.fetch_url", side_effect=FetchError("404 Error", status_code=404)):
            item = fetch_article_metadata("https://example.com/missing")

        assert item is None

    def test_description_is_empty_string_when_none_available(self):
        no_desc_html = """
        <!DOCTYPE html><html><head>
          <meta property="og:title" content="Title Only" />
        </head><body></body></html>
        """
        with patch("local_first_common.http.fetch_url", return_value=no_desc_html):
            item = fetch_article_metadata("https://example.com/no-desc")

        assert item is not None
        assert item.title == "Title Only"
        assert item.description == ""


class TestIsBlocked:
    def test_exact_domain_match(self):
        assert _is_blocked("medium.com", frozenset({"medium.com"}))

    def test_subdomain_match(self):
        assert _is_blocked("username.medium.com", frozenset({"medium.com"}))

    def test_deep_subdomain_match(self):
        assert _is_blocked("ai.plainenglish.io", frozenset({"plainenglish.io"}))

    def test_no_match_for_unrelated_domain(self):
        assert not _is_blocked("simonwillison.net", frozenset({"medium.com"}))

    def test_no_partial_match(self):
        assert not _is_blocked("notmedium.com", frozenset({"medium.com"}))

    def test_strips_port(self):
        assert _is_blocked("medium.com:443", frozenset({"medium.com"}))

    def test_case_insensitive(self):
        assert _is_blocked("Medium.COM", frozenset({"medium.com"}))


class TestBlockedDomains:
    @patch("local_first_common.http.fetch_url")
    def test_blocked_domain_returns_none_without_fetching(self, mock_get):
        item = fetch_article_metadata("https://medium.com/some-user/some-article")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_blocked_subdomain_returns_none_without_fetching(self, mock_get):
        item = fetch_article_metadata("https://username.medium.com/article")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_discord_invite_returns_none_without_fetching(self, mock_get):
        item = fetch_article_metadata("https://discord.com/invite/2Pe5uWGcV3")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_blocked_medium_publication_returns_none(self, mock_get):
        item = fetch_article_metadata("https://ai.plainenglish.io/some-article")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_blocked_towardsdatascience_returns_none(self, mock_get):
        item = fetch_article_metadata("https://towardsdatascience.com/some-article")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_extra_blocked_domain_returns_none_without_fetching(self, mock_get):
        item = fetch_article_metadata(
            "https://nytimes.com/article",
            blocked_domains=frozenset({"nytimes.com"}),
        )
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_unblocked_domain_proceeds_to_fetch(self, mock_get):
        mock_get.return_value = SAMPLE_HTML
        item = fetch_article_metadata("https://simonwillison.net/article")
        assert item is not None
        mock_get.assert_called_once()

    @patch("local_first_common.http.fetch_url")
    def test_non_http_scheme_returns_none_without_fetching(self, mock_get):
        item = fetch_article_metadata("ftp://files.example.com/doc.tar.gz")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_empty_url_returns_none_without_fetching(self, mock_get):
        item = fetch_article_metadata("")
        assert item is None
        mock_get.assert_not_called()


class TestRenderFallback:
    RENDERED_TWEET = (
        "Don't miss what's happening\nPeople on X are the first to know.\n"
        "Log in\nSign up\nArticle\nSee new posts\nConversation\n"
        "Addy Osmani\n@addyosmani\n83\n583\n2.5K\n809K\n"
        "Starting more AI agents is easy now, but your cognitive bandwidth "
        "does not parallelize."
    )

    def test_renders_when_title_is_missing_and_host_is_in_render_domains(self):
        with patch("local_first_common.http.fetch_url", return_value=NO_TITLE_HTML):
            item = fetch_article_metadata(
                "https://x.com/a/status/1",
                render_domains=frozenset({"x.com"}),
                renderer=lambda _u: self.RENDERED_TWEET,
            )
        assert item is not None
        assert "cognitive bandwidth" in item.description
        assert item.title

    def test_derived_title_skips_the_handle_and_engagement_counts(self):
        with patch("local_first_common.http.fetch_url", return_value=NO_TITLE_HTML):
            item = fetch_article_metadata(
                "https://x.com/a/status/1",
                render_domains=frozenset({"x.com"}),
                renderer=lambda _u: self.RENDERED_TWEET,
            )
        assert item is not None
        assert "@addyosmani" not in item.title
        assert "809K" not in item.title
        assert item.title.startswith("Starting more AI agents")

    def test_does_not_render_when_host_is_not_in_render_domains(self):
        calls = []
        with patch("local_first_common.http.fetch_url", return_value=NO_TITLE_HTML):
            item = fetch_article_metadata(
                "https://example.com/no-title",
                render_domains=frozenset({"x.com"}),
                renderer=lambda u: calls.append(u) or "unused",
            )
        assert item is None
        assert calls == []

    def test_does_not_render_when_a_title_already_exists(self):
        calls = []
        with patch("local_first_common.http.fetch_url", return_value=FALLBACK_HTML):
            item = fetch_article_metadata(
                "https://x.com/a/status/1",
                render_domains=frozenset({"x.com"}),
                renderer=lambda u: calls.append(u) or "unused",
            )
        assert item is not None
        assert item.title == "Fallback Title Only"
        assert calls == []

    def test_returns_none_when_rendering_also_produces_no_usable_text(self):
        with patch("local_first_common.http.fetch_url", return_value=NO_TITLE_HTML):
            item = fetch_article_metadata(
                "https://x.com/a/status/1",
                render_domains=frozenset({"x.com"}),
                renderer=lambda _u: "",
            )
        assert item is None

    def test_returns_none_when_rendering_raises(self):
        with patch("local_first_common.http.fetch_url", return_value=NO_TITLE_HTML):
            item = fetch_article_metadata(
                "https://x.com/a/status/1",
                render_domains=frozenset({"x.com"}),
                renderer=lambda _u: (_ for _ in ()).throw(RuntimeError("no browser")),
            )
        assert item is None


class TestDeriveMetadataFromRenderedText:
    def test_uses_content_after_the_handle_line(self):
        title, description = _derive_metadata_from_rendered_text(
            "Some chrome\n@someone\n42\n1.2K\nThe actual tweet text goes here."
        )
        assert title == "The actual tweet text goes here."
        assert description == "The actual tweet text goes here."

    def test_falls_back_to_the_whole_text_when_no_handle_line_is_found(self):
        title, _ = _derive_metadata_from_rendered_text("Just some plain rendered text.")
        assert title == "Just some plain rendered text."

    def test_truncates_title_to_80_chars_and_description_to_500(self):
        long_text = "@a\n" + ("word " * 200)
        title, description = _derive_metadata_from_rendered_text(long_text)
        assert len(title) <= 80
        assert len(description) <= 500


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None):
        self.status_code = status_code
        self._json_body = json_body or {}

    def json(self):
        return self._json_body


class TestRemoteRetrieverDelegation:
    """fetch_article_metadata delegates to http-retriever-service when
    HTTP_RETRIEVER_URL is set, instead of doing its own fetch/extract/render.
    Patches the module attribute directly since it's read from the env var
    once at import time, not re-read per call.
    """

    def test_local_fetch_is_untouched_when_url_is_unset(self):
        with (
            patch("discovery.support.article_fetcher.HTTP_RETRIEVER_URL", None),
            patch("local_first_common.http.fetch_url", return_value=SAMPLE_HTML) as mock_fetch,
        ):
            item = fetch_article_metadata("https://duckdb.org/article")
        mock_fetch.assert_called_once()
        assert item is not None
        assert item.title == "Understanding DuckDB: A Practical Guide"

    def test_delegates_and_builds_a_feed_item_on_success(self):
        response = _FakeResponse(
            200,
            {
                "title": "A Real Title",
                "description": "A real description.",
                "publishedDate": "2026-09-19T00:00:00.000Z",
            },
        )
        with (
            patch("discovery.support.article_fetcher.HTTP_RETRIEVER_URL", "http://127.0.0.1:8787"),
            patch("httpx.post", return_value=response) as mock_post,
            patch("local_first_common.http.fetch_url") as mock_local_fetch,
        ):
            item = fetch_article_metadata(
                "https://example.com/post",
                source_url="https://bsky.app/some-post",
                source_platform="bluesky",
            )
        mock_local_fetch.assert_not_called()
        assert item is not None
        assert item.title == "A Real Title"
        assert item.description == "A real description."
        assert item.source == "example.com"
        assert item.found_at == "https://bsky.app/some-post"
        assert item.platform == "bluesky"
        sent_json = mock_post.call_args.kwargs["json"]
        assert sent_json["sourceUrl"] == "https://bsky.app/some-post"
        assert sent_json["sourcePlatform"] == "bluesky"

    def test_sends_no_auth_header_when_api_key_unset(self, monkeypatch):
        monkeypatch.delenv("HTTP_RETRIEVER_API_KEY", raising=False)
        response = _FakeResponse(200, {"title": "A Title"})
        with (
            patch("discovery.support.article_fetcher.HTTP_RETRIEVER_URL", "http://127.0.0.1:8787"),
            patch("httpx.post", return_value=response) as mock_post,
        ):
            fetch_article_metadata("https://example.com/post")
        assert "Authorization" not in mock_post.call_args.kwargs["headers"]

    def test_sends_bearer_token_when_api_key_set(self, monkeypatch):
        monkeypatch.setenv("HTTP_RETRIEVER_API_KEY", "the-real-secret")
        response = _FakeResponse(200, {"title": "A Title"})
        with (
            patch("discovery.support.article_fetcher.HTTP_RETRIEVER_URL", "http://127.0.0.1:8787"),
            patch("httpx.post", return_value=response) as mock_post,
        ):
            fetch_article_metadata("https://example.com/post")
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer the-real-secret"

    def test_thin_result_returns_none_like_the_local_no_title_case(self):
        response = _FakeResponse(200, {"title": "", "description": ""})
        with (
            patch("discovery.support.article_fetcher.HTTP_RETRIEVER_URL", "http://127.0.0.1:8787"),
            patch("httpx.post", return_value=response),
        ):
            item = fetch_article_metadata("https://example.com/thin")
        assert item is None

    def test_blocked_domain_for_returns_none_status_returns_none(self):
        response = _FakeResponse(403, {"error": "blocked"})
        with (
            patch("discovery.support.article_fetcher.HTTP_RETRIEVER_URL", "http://127.0.0.1:8787"),
            patch("httpx.post", return_value=response),
        ):
            item = fetch_article_metadata("https://example.com/blocked-remotely")
        assert item is None

    def test_request_failure_returns_none_without_raising(self):
        import httpx

        with (
            patch("discovery.support.article_fetcher.HTTP_RETRIEVER_URL", "http://127.0.0.1:8787"),
            patch("httpx.post", side_effect=httpx.ConnectError("connection refused")),
        ):
            item = fetch_article_metadata("https://example.com/service-down")
        assert item is None

    def test_local_blocklist_still_applies_before_any_remote_call(self):
        with (
            patch("discovery.support.article_fetcher.HTTP_RETRIEVER_URL", "http://127.0.0.1:8787"),
            patch("httpx.post") as mock_post,
        ):
            item = fetch_article_metadata("https://medium.com/some-post")
        mock_post.assert_not_called()
        assert item is None
