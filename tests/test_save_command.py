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
    """Common CLI options pointing at a temp DB."""
    db = str(tmp_path / "test.db")
    return ["save", "https://example.com/great-article", "--store", db,
            "--readwise-token", "tok_test"]


class TestSaveCommand:
    def test_fetches_scores_and_saves(self, tmp_path):
        opts = _base_opts(tmp_path)
        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=_FAKE_SCORED), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}), \
             patch("content_discovery.save_to_readwise", return_value=True):
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
             patch("content_discovery.score_item") as mock_score, \
             patch("content_discovery.save_to_readwise", return_value=True):
            result = runner.invoke(app, opts)

        mock_score.assert_not_called()
        assert result.exit_code == 0
        assert "1.00" in result.output  # default score when --no-score

    def test_dry_run_writes_nothing(self, tmp_path):
        db = str(tmp_path / "test.db")
        opts = ["save", "https://example.com/great-article",
                "--store", db, "--readwise-token", "tok_test", "--dry-run"]

        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=_FAKE_SCORED), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}), \
             patch("content_discovery.save_to_readwise") as mock_rw:
            result = runner.invoke(app, opts)

        assert result.exit_code == 0
        assert "dry-run" in result.output
        mock_rw.assert_not_called()

    def test_scoring_failure_exits_with_error(self, tmp_path):
        opts = _base_opts(tmp_path)
        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=None), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}):
            result = runner.invoke(app, opts)

        assert result.exit_code == 1
        assert "Scoring failed" in result.output

    def test_sent_to_readwise_on_success(self, tmp_path):
        opts = _base_opts(tmp_path)
        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=_FAKE_SCORED), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}), \
             patch("content_discovery.save_to_readwise", return_value=True) as mock_rw:
            result = runner.invoke(app, opts)

        assert result.exit_code == 0, result.output
        mock_rw.assert_called_once()
        call_kwargs = mock_rw.call_args
        assert call_kwargs[0][0] == "https://example.com/great-article"
        assert "Readwise Reader" in result.output

    def test_readwise_failure_still_saves_to_db(self, tmp_path):
        opts = _base_opts(tmp_path)
        with patch("content_discovery.fetch_article_metadata", return_value=_FAKE_ITEM), \
             patch("content_discovery.score_item", return_value=_FAKE_SCORED), \
             patch("content_discovery.store.get_examples", return_value={"kept": [], "dismissed": []}), \
             patch("content_discovery.PROVIDERS", {"local": MagicMock(return_value=MagicMock())}), \
             patch("content_discovery.save_to_readwise", return_value=False):
            result = runner.invoke(app, opts)

        assert result.exit_code == 0, result.output
        assert "Saved" in result.output
        assert "failed" in result.output.lower()
