from pathlib import Path
from unittest.mock import MagicMock, patch

import requests as req

from discovery.social.article_fetcher import fetch_article_metadata, _is_blocked
from local_first_common.http import FetchError
from local_first_common.url import clean_url

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


def _mock_response(html: str, status_code: int = 200, content_type: str = "text/html; charset=utf-8") -> MagicMock:
    mock = MagicMock()
    mock.text = html
    mock.status_code = status_code
    mock.headers = {"Content-Type": content_type}
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = req.HTTPError(f"{status_code} Error")
    return mock


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

    def test_returns_none_on_timeout(self):
        with patch("local_first_common.http.fetch_url", side_effect=FetchError("Read timed out")):
            item = fetch_article_metadata("https://slow.example.com/")

        assert item is None

    def test_returns_none_on_http_error(self):
        with patch("local_first_common.http.fetch_url", side_effect=FetchError("404 Error", status_code=404)):
            item = fetch_article_metadata("https://example.com/missing")

        assert item is None

    def test_returns_none_for_non_html_content_type(self):
        with patch("local_first_common.http.fetch_url",
                   return_value="%PDF-1.4", content_type="application/pdf"):
            item = fetch_article_metadata("https://example.com/doc.pdf")

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
        # "notmedium.com" should not match "medium.com"
        assert not _is_blocked("notmedium.com", frozenset({"medium.com"}))

    def test_strips_port(self):
        assert _is_blocked("medium.com:443", frozenset({"medium.com"}))

    def test_case_insensitive(self):
        assert _is_blocked("Medium.COM", frozenset({"medium.com"}))


class TestBlockedDomains:
    @patch("local_first_common.http.fetch_url")
    def test_blocked_domain_returns_none_without_fetching(self, mock_get):
        """Medium URLs should be skipped; no HTTP request should be made."""
        item = fetch_article_metadata("https://medium.com/some-user/some-article")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_blocked_subdomain_returns_none_without_fetching(self, mock_get):
        """username.medium.com is a Medium subdomain and should be blocked."""
        item = fetch_article_metadata("https://username.medium.com/article")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_blocked_medium_publication_returns_none(self, mock_get):
        """plainenglish.io publications should be blocked."""
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
        """User-supplied blocked_domains should also be skipped."""
        item = fetch_article_metadata(
            "https://nytimes.com/article",
            blocked_domains=frozenset({"nytimes.com"}),
        )
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_unblocked_domain_proceeds_to_fetch(self, mock_get):
        """A non-blocked domain should still make an HTTP request."""
        mock_get.return_value = SAMPLE_HTML
        item = fetch_article_metadata("https://simonwillison.net/article")
        assert item is not None
        mock_get.assert_called_once()

    @patch("local_first_common.http.fetch_url")
    def test_malformed_url_returns_none_without_crashing(self, mock_get):
        """URLs with invalid hostnames (e.g. parens) must not raise unhandled exceptions."""
        item = fetch_article_metadata("https://agentguard.auto(...)/page")
        assert item is None
        # requests.get should never be called — URL is filtered before the network call
        # (scheme is https, netloc is non-empty so it passes the scheme check,
        # but requests/urllib3 raises LocationParseError which must be caught)

    @patch("local_first_common.http.fetch_url")
    def test_non_http_scheme_returns_none_without_fetching(self, mock_get):
        """ftp://, mailto:, etc. should be silently skipped."""
        item = fetch_article_metadata("ftp://files.example.com/doc.tar.gz")
        assert item is None
        mock_get.assert_not_called()

    @patch("local_first_common.http.fetch_url")
    def test_empty_url_returns_none_without_fetching(self, mock_get):
        item = fetch_article_metadata("")
        assert item is None
        mock_get.assert_not_called()


class TestCleanUrl:
    def test_strips_utm_source(self):
        url = "https://example.com/article?utm_source=mastodon"
        assert clean_url(url) == "https://example.com/article"

    def test_strips_multiple_utm_params(self):
        url = "https://example.com/article?utm_source=mastodon&utm_medium=jetpack_social&utm_campaign=newsletter"
        assert clean_url(url) == "https://example.com/article"

    def test_preserves_non_tracking_params(self):
        url = "https://example.com/search?q=python&page=2"
        # parameters are sorted: page=2, q=python
        assert clean_url(url) == "https://example.com/search?page=2&q=python"

    def test_strips_tracking_keeps_real_params(self):
        url = "https://example.com/article?q=test&utm_source=email&page=1"
        result = clean_url(url)
        assert "utm_source" not in result
        assert "q=test" in result
        assert "page=1" in result

    def test_strips_fbclid(self):
        url = "https://example.com/article?fbclid=abc123"
        assert clean_url(url) == "https://example.com/article"

    def test_url_without_params_unchanged(self):
        url = "https://example.com/article"
        assert clean_url(url) == url

    def test_empty_string_returns_empty(self):
        assert clean_url("") == ""

    def test_case_insensitive_param_stripping(self):
        url = "https://example.com/article?UTM_SOURCE=email"
        assert clean_url(url) == "https://example.com/article"
