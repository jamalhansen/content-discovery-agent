"""Tests for the `save` CLI command."""
import os
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from content_discovery import app
from feed_reader import FeedItem
from scorer import ScoredItem

runner = CliRunner()

_FAKE_ITEM = FeedItem(
    title="A Great Article",
    description="This article is about local AI and DuckDB.",
    url="https://example.com/great-article",
    source="example.com",
    published="2026-03-10",
)

_FAKE_SCORED = ScoredItem(
    score=0.92,
    tags=["local AI", "duckdb"],
    summary="A practical guide to local AI with DuckDB.",
    language="en",
)


def _base_opts(tmp_path) -> list[str]:
    """Common CLI options pointing at a temp DB and vault."""
    vault = str(tmp_path / "vault")
    os.makedirs(vault)
    db = str(tmp_path / "test.db")
    return ["save", "https://example.com/great-article",
            "--store", db, "--vault-path", vault]


class TestSaveCommand:
    def test_fetches_scores_and_saves(self, tmp_path):
        opts = _base_opts(tmp_path)
        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=_FAKE_SCORED), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}):
            result = runner.invoke(app, opts)

        assert result.exit_code == 0, result.output
        assert "A Great Article" in result.output
        assert "0.92" in result.output
        assert "Saved" in result.output

    def test_already_seen_exits_early(self, tmp_path):
        opts = _base_opts(tmp_path)
        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.store.is_seen", return_value=True):
            result = runner.invoke(app, opts)

        assert result.exit_code == 0
        assert "Already in database" in result.output

    def test_fetch_failure_exits_with_error(self, tmp_path):
        opts = _base_opts(tmp_path)
        with patch("content_discovery.fetch_article_metadata", return_value=None):
            result = runner.invoke(app, opts)

        assert result.exit_code == 1
        assert "Could not fetch metadata" in result.output

    def test_no_score_skips_llm(self, tmp_path):
        opts = _base_opts(tmp_path) + ["--no-score"]
        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item") as mock_score:
            result = runner.invoke(app, opts)

        mock_score.assert_not_called()
        assert result.exit_code == 0
        assert "1.00" in result.output  # default score when --no-score

    def test_dry_run_writes_nothing(self, tmp_path):
        vault = str(tmp_path / "vault")
        os.makedirs(vault)
        db = str(tmp_path / "test.db")
        opts = ["save", "https://example.com/great-article",
                "--store", db, "--vault-path", vault, "--dry-run"]
        inbox = os.path.join(vault, "00-inbox.md")

        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=_FAKE_SCORED), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}):
            result = runner.invoke(app, opts)

        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert not os.path.exists(inbox)

    def test_scoring_failure_exits_with_error(self, tmp_path):
        opts = _base_opts(tmp_path)
        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=None), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}):
            result = runner.invoke(app, opts)

        assert result.exit_code == 1
        assert "Scoring failed" in result.output

    def test_item_written_to_inbox(self, tmp_path):
        vault = str(tmp_path / "vault")
        os.makedirs(vault)
        db = str(tmp_path / "test.db")
        opts = ["save", "https://example.com/great-article",
                "--store", db, "--vault-path", vault,
                "--inbox-path", "inbox.md"]

        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=_FAKE_SCORED), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}):
            result = runner.invoke(app, opts)

        assert result.exit_code == 0, result.output
        inbox_content = open(os.path.join(vault, "inbox.md")).read()
        assert "A Great Article" in inbox_content
        assert "example.com/great-article" in inbox_content
        assert "0.92" in inbox_content
