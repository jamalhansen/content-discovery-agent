"""Tests for the shared Readwise Reader integration module."""

from unittest.mock import MagicMock, patch

import duckdb
import requests

from discovery.support.readwise import (
    archive_reader_document,
    list_reader_documents,
    list_reader_refs,
    save_to_readwise,
)


def _last_row(db_path, table: str = "api_call_log") -> dict:
    conn = duckdb.connect(str(db_path))
    try:
        cur = conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 1")
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        assert row is not None
        return dict(zip(cols, row))
    finally:
        conn.close()


class TestSaveToReadwise:
    def test_returns_true_on_201(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            result = save_to_readwise("tok_abc", "https://example.com/article")
        assert result is True
        mock_post.assert_called_once()

    def test_returns_true_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp):
            result = save_to_readwise("tok_abc", "https://example.com/article")
        assert result is True

    def test_returns_false_on_non_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp):
            result = save_to_readwise("tok_abc", "https://example.com/article")
        assert result is False

    def test_returns_false_on_network_error(self):
        with patch("discovery.support.readwise.requests.post", side_effect=requests.ConnectionError("timeout")):
            result = save_to_readwise("tok_abc", "https://example.com/article")
        assert result is False

    def test_returns_false_when_no_token(self):
        result = save_to_readwise("", "https://example.com/article")
        assert result is False

    def test_sends_url_in_payload(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("tok_abc", "https://example.com/article")
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["url"] == "https://example.com/article"

    def test_sends_authorization_header(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("tok_secret", "https://example.com/article")
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Token tok_secret"

    def test_optional_fields_omitted_when_empty(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("tok_abc", "https://example.com/article")
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert "title" not in payload
        assert "summary" not in payload
        assert "tags" not in payload
        assert "published_date" not in payload

    def test_optional_fields_included_when_provided(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise(
                "tok_abc",
                "https://example.com/article",
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
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("tok_abc", "https://example.com/article", tags=[])
        _, kwargs = mock_post.call_args
        assert "tags" not in kwargs["json"]

    def test_location_omitted_when_not_given(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("tok_abc", "https://example.com/article")
        _, kwargs = mock_post.call_args
        assert "location" not in kwargs["json"]

    def test_location_included_when_given(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise("tok_abc", "https://example.com/article", location="archive")
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["location"] == "archive"

    def test_includes_discovery_metadata_as_tags(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp) as mock_post:
            save_to_readwise(
                "tok_abc",
                "https://example.com/article",
                search_term="duckdb",
                platform="bluesky",
            )
        _, kwargs = mock_post.call_args
        tags = kwargs["json"]["tags"]
        assert "term:duckdb" in tags
        assert "platform:bluesky" in tags


def _page(results, next_cursor=None):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "count": len(results),
        "nextPageCursor": next_cursor,
        "results": results,
    }
    return mock_resp


_DOC = {
    "id": "abc123",
    "url": "https://read.readwise.io/read/abc123",
    "source_url": "https://example.com/original-article",
    "title": "An Article",
    "author": "Someone",
    "category": "article",
    "location": "new",
    "summary": "A short summary.",
    "published_date": "2026-03-11",
}


class TestListReaderDocuments:
    def test_returns_empty_when_no_token(self):
        result = list_reader_documents("")
        assert result == []

    def test_maps_document_fields_to_feed_item(self):
        with patch("discovery.support.readwise.requests.get", return_value=_page([_DOC])):
            result = list_reader_documents("tok_abc")
        assert len(result) == 1
        item = result[0]
        assert item.title == "An Article"
        assert item.description == "A short summary."
        assert item.url == "https://example.com/original-article"
        assert item.source == "readwise-reader"
        assert item.published == "2026-03-11"
        assert item.platform == "reader"

    def test_falls_back_to_reader_url_when_no_source_url(self):
        doc = dict(_DOC)
        del doc["source_url"]
        with patch("discovery.support.readwise.requests.get", return_value=_page([doc])):
            result = list_reader_documents("tok_abc")
        assert result[0].url == "https://read.readwise.io/read/abc123"

    def test_sends_authorization_header(self):
        with patch("discovery.support.readwise.requests.get", return_value=_page([])) as mock_get:
            list_reader_documents("tok_secret")
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Token tok_secret"

    def test_defaults_to_location_new(self):
        with patch("discovery.support.readwise.requests.get", return_value=_page([])) as mock_get:
            list_reader_documents("tok_abc")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["location"] == "new"

    def test_location_none_omits_filter(self):
        with patch("discovery.support.readwise.requests.get", return_value=_page([])) as mock_get:
            list_reader_documents("tok_abc", location=None)
        _, kwargs = mock_get.call_args
        assert "location" not in kwargs["params"]

    def test_optional_filters_included_when_provided(self):
        with patch("discovery.support.readwise.requests.get", return_value=_page([])) as mock_get:
            list_reader_documents(
                "tok_abc",
                category="article",
                updated_after="2026-01-01",
                tag="ai",
            )
        _, kwargs = mock_get.call_args
        params = kwargs["params"]
        assert params["category"] == "article"
        assert params["updatedAfter"] == "2026-01-01"
        assert params["tag"] == "ai"

    def test_paginates_through_all_pages(self):
        page1 = _page([_DOC], next_cursor="cursor-2")
        page2 = _page([_DOC])
        with patch("discovery.support.readwise.requests.get", side_effect=[page1, page2]) as mock_get:
            result = list_reader_documents("tok_abc")
        assert len(result) == 2
        assert mock_get.call_count == 2
        second_call_params = mock_get.call_args_list[1].kwargs["params"]
        assert second_call_params["pageCursor"] == "cursor-2"

    def test_stops_and_returns_partial_results_on_page_failure(self):
        page1 = _page([_DOC], next_cursor="cursor-2")
        failing_resp = MagicMock()
        failing_resp.status_code = 500
        failing_resp.text = "server error"
        with patch("discovery.support.readwise.requests.get", side_effect=[page1, failing_resp]):
            result = list_reader_documents("tok_abc")
        assert len(result) == 1

    def test_returns_partial_results_on_network_error_mid_pagination(self):
        page1 = _page([_DOC], next_cursor="cursor-2")
        with patch(
            "discovery.support.readwise.requests.get",
            side_effect=[page1, requests.ConnectionError("timeout")],
        ):
            result = list_reader_documents("tok_abc")
        assert len(result) == 1


class TestListReaderRefs:
    def test_returns_empty_when_no_token(self):
        assert list_reader_refs("") == []

    def test_maps_id_source_url_and_location(self):
        with patch("discovery.support.readwise.requests.get", return_value=_page([_DOC])):
            refs = list_reader_refs("tok_abc")
        assert len(refs) == 1
        assert refs[0].doc_id == "abc123"
        assert refs[0].source_url == "https://example.com/original-article"
        assert refs[0].title == "An Article"
        assert refs[0].location == "new"

    def test_skips_documents_without_a_source_url(self):
        note = dict(_DOC, id="note1", source_url=None)
        with patch("discovery.support.readwise.requests.get", return_value=_page([_DOC, note])):
            refs = list_reader_refs("tok_abc")
        assert [r.doc_id for r in refs] == ["abc123"]

    def test_paginates(self):
        page1 = _page([_DOC], next_cursor="cursor-2")
        page2 = _page([dict(_DOC, id="def456")])
        with patch("discovery.support.readwise.requests.get", side_effect=[page1, page2]):
            refs = list_reader_refs("tok_abc")
        assert [r.doc_id for r in refs] == ["abc123", "def456"]

    def test_retries_after_rate_limit_then_succeeds(self):
        limited = MagicMock()
        limited.status_code = 429
        limited.headers = {"Retry-After": "1"}
        with (
            patch("discovery.support.readwise.time.sleep") as mock_sleep,
            patch("discovery.support.readwise.requests.get", side_effect=[limited, _page([_DOC])]),
        ):
            refs = list_reader_refs("tok_abc")
        assert len(refs) == 1
        mock_sleep.assert_called_once_with(1)

    def test_returns_partial_results_on_network_error(self):
        page1 = _page([_DOC], next_cursor="cursor-2")
        with patch(
            "discovery.support.readwise.requests.get",
            side_effect=[page1, requests.ConnectionError("timeout")],
        ):
            refs = list_reader_refs("tok_abc")
        assert len(refs) == 1


class TestArchiveReaderDocument:
    def test_returns_false_when_no_token(self):
        assert archive_reader_document("", "abc123") is False

    def test_returns_false_when_no_doc_id(self):
        assert archive_reader_document("tok_abc", "") is False

    def test_patches_location_to_archive(self):
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        with patch("discovery.support.readwise.requests.patch", return_value=ok_resp) as mock_patch:
            assert archive_reader_document("tok_abc", "abc123") is True
        called_url = mock_patch.call_args.args[0]
        assert called_url == "https://readwise.io/api/v3/update/abc123/"
        assert mock_patch.call_args.kwargs["json"] == {"location": "archive"}

    def test_accepts_204_no_content(self):
        resp = MagicMock()
        resp.status_code = 204
        with patch("discovery.support.readwise.requests.patch", return_value=resp):
            assert archive_reader_document("tok_abc", "abc123") is True

    def test_retries_after_rate_limit(self):
        limited = MagicMock()
        limited.status_code = 429
        limited.headers = {"Retry-After": "2"}
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        with (
            patch("discovery.support.readwise.time.sleep") as mock_sleep,
            patch("discovery.support.readwise.requests.patch", side_effect=[limited, ok_resp]),
        ):
            assert archive_reader_document("tok_abc", "abc123") is True
        mock_sleep.assert_called_once_with(2)

    def test_gives_up_after_repeated_rate_limiting(self):
        limited = MagicMock()
        limited.status_code = 429
        limited.headers = {"Retry-After": "1"}
        with (
            patch("discovery.support.readwise.time.sleep"),
            patch("discovery.support.readwise.requests.patch", return_value=limited),
        ):
            assert archive_reader_document("tok_abc", "abc123") is False

    def test_returns_false_on_error_status(self):
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "not found"
        with patch("discovery.support.readwise.requests.patch", return_value=resp):
            assert archive_reader_document("tok_abc", "missing") is False

    def test_returns_false_on_network_error(self):
        with patch(
            "discovery.support.readwise.requests.patch",
            side_effect=requests.ConnectionError("timeout"),
        ):
            assert archive_reader_document("tok_abc", "abc123") is False


class TestApiCallLogging:
    """Passing tool= logs the call to api_call_log; omitting it changes nothing."""

    def test_save_logs_success(self, tmp_path):
        from local_first_common.tracking import register_tool

        db = tmp_path / "test.duckdb"
        tool = register_tool("test-tool", db_path=db)
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp):
            assert save_to_readwise("tok_abc", "https://example.com/a", tool=tool, db_path=db) is True

        row = _last_row(db, table="api_call_log")
        assert row["service"] == "readwise"
        assert row["operation"] == "save"
        assert row["success"] is True
        assert row["http_status"] == 201

    def test_save_logs_failure(self, tmp_path):
        from local_first_common.tracking import register_tool

        db = tmp_path / "test.duckdb"
        tool = register_tool("test-tool", db_path=db)
        with patch(
            "discovery.support.readwise.requests.post",
            side_effect=requests.ConnectionError("timeout"),
        ):
            assert save_to_readwise("tok_abc", "https://example.com/a", tool=tool, db_path=db) is False

        row = _last_row(db, table="api_call_log")
        assert row["success"] is False
        assert "timeout" in row["error_message"]

    def test_archive_logs_success(self, tmp_path):
        from local_first_common.tracking import register_tool

        db = tmp_path / "test.duckdb"
        tool = register_tool("test-tool", db_path=db)
        resp = MagicMock()
        resp.status_code = 200
        with patch("discovery.support.readwise.requests.patch", return_value=resp):
            assert archive_reader_document("tok_abc", "doc1", tool=tool, db_path=db) is True

        row = _last_row(db, table="api_call_log")
        assert row["operation"] == "archive"
        assert row["success"] is True

    def test_list_documents_logs_item_count(self, tmp_path):
        from local_first_common.tracking import register_tool

        db = tmp_path / "test.duckdb"
        tool = register_tool("test-tool", db_path=db)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "results": [
                {"title": "A", "source_url": "https://a.example/"},
                {"title": "B", "source_url": "https://b.example/"},
            ],
            "nextPageCursor": None,
        }
        with patch("discovery.support.readwise.requests.get", return_value=resp):
            items = list_reader_documents("tok_abc", tool=tool, db_path=db)

        assert len(items) == 2
        row = _last_row(db, table="api_call_log")
        assert row["operation"] == "list"
        assert row["item_count"] == 2

    def test_no_tool_means_no_row(self, tmp_path):
        """Backward compatible: omitting tool= is a no-op for logging, not an error."""
        db = tmp_path / "test.duckdb"
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("discovery.support.readwise.requests.post", return_value=mock_resp):
            assert save_to_readwise("tok_abc", "https://example.com/a") is True
        assert not db.exists()
