"""Tests for the "near misses" report shown when a run yields zero candidates.

Regression coverage for a bug found 2026-09-06: the report was built from
`store.get_top_dismissed_for_date`, which returns every dismissed item sharing
today's `fetched_at` date across ALL runs, not just the items this run
actually scored. A run scoring 2 items could (and did) show 5 "near misses"
pulled from earlier runs the same day, mislabeled "from this run".
"""
from unittest.mock import MagicMock, patch

from local_first_common.scoring import ScoredItem
from local_first_common.testing import MockProvider
from typer.testing import CliRunner

from discovery import store
from discovery.logic import app
from discovery.orchestrator import run_discovery

runner = CliRunner()


def _make_feed_item(url="https://example.com/article", title="Test Article"):
    item = MagicMock()
    item.url = url
    item.title = title
    item.description = "A test article description."
    item.source = "Example Blog"
    item.published = "2026-09-06"
    item.found_at = None
    item.search_term = None
    item.platform = None
    return item


class TestDismissedThisRun:
    """Unit-level: run_discovery's own dismissed-item tracking."""

    def test_returns_only_below_threshold_items_scored_this_run(self, tmp_path):
        items = [
            _make_feed_item(url="https://example.com/a", title="Near Miss"),
            _make_feed_item(url="https://example.com/b", title="Clears Threshold"),
        ]
        with patch("discovery.orchestrator.fetch_feed", return_value=items), \
             patch("discovery.store.init_db"), \
             patch("discovery.store.get_examples", return_value={}), \
             patch("discovery.store.is_seen", return_value=False), \
             patch("discovery.store.upsert_item"), \
             patch("discovery.store.mark_item"), \
             patch("discovery.orchestrator.READWISE_ROUTING", False), \
             patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", False), \
             patch("discovery.orchestrator.score_item") as mock_score:
            mock_score.side_effect = [
                ScoredItem(score=0.72, tags=[], summary="s", language="en"),
                ScoredItem(score=0.90, tags=[], summary="s", language="en"),
            ]
            candidates, scored, _skipped, dismissed = run_discovery(
                MockProvider(), "rss", None, 0.75,
                True, False, False, None, str(tmp_path / "store.db"),
            )

        assert scored == 2
        assert [c["title"] for c in candidates] == ["Clears Threshold"]
        assert dismissed == [{"title": "Near Miss", "score": 0.72}]

    def test_non_english_items_are_excluded_from_near_misses(self, tmp_path):
        """A high-scoring but wrong-language item is a hard exclusion, not a near miss."""
        items = [_make_feed_item()]
        with patch("discovery.orchestrator.fetch_feed", return_value=items), \
             patch("discovery.store.init_db"), \
             patch("discovery.store.get_examples", return_value={}), \
             patch("discovery.store.is_seen", return_value=False), \
             patch("discovery.store.upsert_item"), \
             patch("discovery.store.mark_item"), \
             patch("discovery.orchestrator.READWISE_ROUTING", False), \
             patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", False), \
             patch("discovery.orchestrator.score_item") as mock_score:
            mock_score.return_value = ScoredItem(score=0.95, tags=[], summary="s", language="fr")
            _, _, _, dismissed = run_discovery(
                MockProvider(), "rss", None, 0.75,
                True, False, False, None, str(tmp_path / "store.db"),
            )

        assert dismissed == []


class TestNearMissCliOutput:
    """End-to-end: the `run` command's zero-candidate report, against a real store."""

    def test_does_not_leak_dismissed_items_from_earlier_runs_today(self, tmp_path):
        """The exact bug: a prior run's dismissed item must not appear as a
        "near miss" for a later, unrelated run on the same calendar day.
        """
        db = str(tmp_path / "store.db")
        store.init_db(db)
        # Simulate an earlier run today that dismissed a high-scoring item.
        store.upsert_item(
            url="https://example.com/earlier-run-item",
            title="From An Earlier Run Today",
            source="Example Blog", description="", score=0.85, tags=[], summary="s",
            fetched_at="2026-09-06", published_at="2026-09-06",
            found_at=None, search_term=None, platform=None, path=db,
        )
        store.mark_item("https://example.com/earlier-run-item", "dismissed", db)

        items = [_make_feed_item(url="https://example.com/this-run-item", title="This Run's Near Miss")]
        with patch("discovery.orchestrator.fetch_feed", return_value=items), \
             patch("discovery.orchestrator.FEEDS", ["https://example.com/feed"]), \
             patch("discovery.orchestrator.READWISE_ROUTING", False), \
             patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", False), \
             patch("discovery.orchestrator.score_item") as mock_score:
            mock_score.return_value = ScoredItem(score=0.72, tags=[], summary="s", language="en")
            result = runner.invoke(app, ["run", "--store", db, "--threshold", "0.75", "--no-dedup"])

        assert result.exit_code == 0, result.output
        assert "This Run's Near Miss" in result.output
        assert "From An Earlier Run Today" not in result.output

    def test_near_misses_shown_even_when_candidates_clear_threshold(self, tmp_path):
        """Near misses used to only print on a zero-candidate run. A near miss
        sitting alongside several above-threshold candidates the same day was
        invisible without querying the DB by hand -- fixed 2026-09-06."""
        db = str(tmp_path / "store.db")
        items = [
            _make_feed_item(url="https://example.com/near-miss", title="Near Miss Item"),
            _make_feed_item(url="https://example.com/clears", title="Clears Threshold Item"),
        ]
        with patch("discovery.orchestrator.fetch_feed", return_value=items), \
             patch("discovery.orchestrator.FEEDS", ["https://example.com/feed"]), \
             patch("discovery.orchestrator.READWISE_ROUTING", False), \
             patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", False), \
             patch("discovery.orchestrator.score_item") as mock_score:
            mock_score.side_effect = [
                ScoredItem(score=0.72, tags=[], summary="s", language="en"),
                ScoredItem(score=0.95, tags=[], summary="s", language="en"),
            ]
            result = runner.invoke(app, ["run", "--store", db, "--threshold", "0.75", "--no-dedup"])

        assert result.exit_code == 0, result.output
        assert "Clears Threshold Item" in result.output
        assert "Near misses" in result.output
        assert "Near Miss Item" in result.output
