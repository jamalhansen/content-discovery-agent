"""Tests for the Readwise Reader integration module."""
from unittest.mock import MagicMock, patch

import requests

from readwise import save_to_readwise


class TestSaveToReadwise:
    def test_returns_true_on_201(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("readwise.requests.post", return_value=mock_resp) as mock_post:
            result = save_to_readwise("https://example.com/article", "tok_abc")
        assert result is True
        mock_post.assert_called_once()

    def test_returns_true_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("readwise.requests.post", return_value=mock_resp):
            result = save_to_readwise("https://example.com/article", "tok_abc")
        assert result is True

    def test_returns_false_on_non_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"
        with patch("readwise.requests.post", return_value=mock_resp):
            result = save_to_readwise("https://example.com/article", "tok_abc")
        assert result is False

    def test_returns_false_on_network_error(self):
        with patch("readwise.requests.post", side_effect=requests.ConnectionError("timeout")):
            result = save_to_readwise("https://example.com/article", "tok_abc")
        assert result is False

    def test_returns_false_when_no_token(self):
        result = save_to_readwise("https://example.com/article", "")
        assert result is False

    def test_sends_url_in_payload(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("https://example.com/article", "tok_abc")
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["url"] == "https://example.com/article"

    def test_sends_authorization_header(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("https://example.com/article", "tok_secret")
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Token tok_secret"

    def test_optional_fields_omitted_when_empty(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("https://example.com/article", "tok_abc")
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert "title" not in payload
        assert "summary" not in payload
        assert "tags" not in payload
        assert "published_date" not in payload

    def test_optional_fields_included_when_provided(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise(
                "https://example.com/article",
                "tok_abc",
                title="My Article",
                summary="A great read.",
                tags=["python", "ai"],
                published_date="2026-03-13",
            )
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["title"] == "My Article"
        assert payload["summary"] == "A great read."
        assert payload["tags"] == ["python", "ai"]
        assert payload["published_date"] == "2026-03-13"

    def test_empty_tags_list_omitted(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("https://example.com/article", "tok_abc", tags=[])
        _, kwargs = mock_post.call_args
        assert "tags" not in kwargs["json"]
