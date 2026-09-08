"""Tests for wiring the "citations" source into run_discovery: candidates it
finds must flow through the exact same score/threshold/routing path as any
other source (see discovery/citations.py for why)."""
from unittest.mock import patch

from local_first_common.article_fetcher import FeedItem
from local_first_common.scoring import ScoredItem
from local_first_common.testing import MockProvider

from discovery.orchestrator import run_discovery


def _citation_item(url="https://cited.example.com/post"):
    return FeedItem(
        title="Cited Post", description="desc", url=url, source="cited.example.com",
        found_at="https://origin.example.com/kept-article", platform="citations",
    )


class TestCitationsSource:
    def test_not_fetched_when_citations_not_in_sources(self, tmp_path):
        with patch("discovery.orchestrator.fetch_feed", return_value=[]), \
             patch("discovery.orchestrator.store.get_recent_kept") as mock_recent, \
             patch("discovery.orchestrator.store.init_db"), \
             patch("discovery.orchestrator.store.get_examples", return_value={}):
            run_discovery(
                MockProvider(response='{"score": 0.1, "tags": [], "summary": "s", "language": "en"}'),
                "rss", None, 0.5, True, False, False, None, str(tmp_path / "store.db"),
            )
        mock_recent.assert_not_called()

    def test_skipped_when_no_kept_items_yet(self, tmp_path):
        with patch("discovery.orchestrator.store.get_recent_kept", return_value=[]), \
             patch("discovery.orchestrator.discover_citation_candidates") as mock_discover, \
             patch("discovery.orchestrator.store.init_db"), \
             patch("discovery.orchestrator.store.get_examples", return_value={}):
            candidates, scored, _skipped, _dismissed = run_discovery(
                MockProvider(), "citations", None, 0.5, True, False, False, None, str(tmp_path / "store.db"),
            )
        mock_discover.assert_not_called()
        assert scored == 0

    def test_citation_candidates_flow_through_scoring_and_routing(self, tmp_path):
        item = _citation_item()
        with patch("discovery.orchestrator.store.get_recent_kept", return_value=[{"url": "https://origin.example.com/kept-article", "title": "Origin"}]), \
             patch("discovery.orchestrator.discover_citation_candidates", return_value=[item]), \
             patch("discovery.orchestrator.store.init_db"), \
             patch("discovery.orchestrator.store.get_examples", return_value={}), \
             patch("discovery.orchestrator.store.is_seen", return_value=False), \
             patch("discovery.orchestrator.store.upsert_item"), \
             patch("discovery.orchestrator.store.mark_item"), \
             patch("discovery.orchestrator.READWISE_ROUTING", True), \
             patch("discovery.orchestrator.READWISE_TOKEN", "tok"), \
             patch("discovery.orchestrator.save_to_readwise") as mock_save, \
             patch("discovery.orchestrator.score_item") as mock_score:
            mock_score.return_value = ScoredItem(score=0.9, tags=["ai"], summary="Good.", language="en")
            candidates, scored, _skipped, _dismissed = run_discovery(
                MockProvider(), "citations", None, 0.5, True, False, False, None, str(tmp_path / "store.db"),
            )

        assert scored == 1
        assert candidates[0]["url"] == item.url
        mock_save.assert_called_once()
        assert mock_save.call_args.args[1] == item.url

    def test_below_threshold_citation_item_is_dismissed_not_routed(self, tmp_path):
        item = _citation_item()
        with patch("discovery.orchestrator.store.get_recent_kept", return_value=[{"url": "https://origin.example.com/kept-article", "title": "Origin"}]), \
             patch("discovery.orchestrator.discover_citation_candidates", return_value=[item]), \
             patch("discovery.orchestrator.store.init_db"), \
             patch("discovery.orchestrator.store.get_examples", return_value={}), \
             patch("discovery.orchestrator.store.is_seen", return_value=False), \
             patch("discovery.orchestrator.store.upsert_item"), \
             patch("discovery.orchestrator.store.mark_item") as mock_mark, \
             patch("discovery.orchestrator.READWISE_ROUTING", True), \
             patch("discovery.orchestrator.READWISE_TOKEN", "tok"), \
             patch("discovery.orchestrator.save_to_readwise") as mock_save, \
             patch("discovery.orchestrator.score_item") as mock_score:
            mock_score.return_value = ScoredItem(score=0.2, tags=[], summary="Meh.", language="en")
            candidates, _scored, _skipped, _dismissed = run_discovery(
                MockProvider(), "citations", None, 0.5, True, False, False, None, str(tmp_path / "store.db"),
            )

        assert candidates == []
        mock_save.assert_not_called()
        mock_mark.assert_called_once_with(item.url, "dismissed", str(tmp_path / "store.db"))

    def test_passes_configured_limit_to_get_recent_kept(self, tmp_path):
        with patch("discovery.orchestrator.store.get_recent_kept", return_value=[]) as mock_recent, \
             patch("discovery.orchestrator.CITATION_KEPT_LIMIT", 7), \
             patch("discovery.orchestrator.store.init_db"), \
             patch("discovery.orchestrator.store.get_examples", return_value={}):
            run_discovery(
                MockProvider(), "citations", None, 0.5, True, False, False, None, str(tmp_path / "store.db"),
            )
        mock_recent.assert_called_once_with(str(tmp_path / "store.db"), limit=7)
