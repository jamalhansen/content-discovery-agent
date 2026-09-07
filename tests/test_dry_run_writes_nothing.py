"""Regression coverage for a bug found 2026-09-07: --dry-run scored and
stored every item to the local DB regardless -- only the Readwise/Contexta
routing calls were actually gated on dry_run. This contradicts the
documented contract in this repo's CLAUDE.md ("write nothing" / "skips DB
write entirely") and local-first-common's shared dry_run_option ("do not
write to disk/vault/DB"). Found when a dry-run test left 5 items sitting in
the local store as status='new' with no visible trace anywhere else.
"""
from unittest.mock import MagicMock, patch

from local_first_common.scoring import ScoredItem
from local_first_common.testing import MockProvider

from discovery.orchestrator import run_discovery


def _make_feed_item(url="https://example.com/article", title="Test Article"):
    item = MagicMock()
    item.url = url
    item.title = title
    item.description = "A test article description."
    item.source = "Example Blog"
    item.published = "2026-09-07"
    item.found_at = None
    item.search_term = None
    item.platform = None
    return item


def _run(score, threshold, dry_run, tmp_path):
    with patch("discovery.orchestrator.fetch_feed", return_value=[_make_feed_item()]), \
         patch("discovery.orchestrator.store.init_db"), \
         patch("discovery.orchestrator.store.get_examples", return_value={}), \
         patch("discovery.orchestrator.store.is_seen", return_value=False), \
         patch("discovery.orchestrator.store.upsert_item") as mock_upsert, \
         patch("discovery.orchestrator.store.mark_item") as mock_mark, \
         patch("discovery.orchestrator.READWISE_ROUTING", False), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", False), \
         patch("discovery.orchestrator.score_item") as mock_score:
        mock_score.return_value = ScoredItem(score=score, tags=[], summary="s", language="en")
        result = run_discovery(
            MockProvider(), "rss", None, threshold,
            True, False, False, None, str(tmp_path / "store.db"),
            dry_run=dry_run,
        )
    return result, mock_upsert, mock_mark


class TestDryRunWritesNothing:
    def test_dry_run_never_upserts(self, tmp_path):
        _result, mock_upsert, _mock_mark = _run(score=0.9, threshold=0.5, dry_run=True, tmp_path=tmp_path)
        mock_upsert.assert_not_called()

    def test_dry_run_never_marks_dismissed(self, tmp_path):
        _result, _mock_upsert, mock_mark = _run(score=0.2, threshold=0.5, dry_run=True, tmp_path=tmp_path)
        mock_mark.assert_not_called()

    def test_dry_run_still_populates_near_miss_data_in_memory(self, tmp_path):
        """Dry-run's near-miss reporting must survive -- it comes from the
        in-memory scoring loop, not a DB read-back, so it isn't affected by
        skipping the write."""
        (_candidates, _scored, _skipped, dismissed), _mock_upsert, _mock_mark = _run(
            score=0.4, threshold=0.5, dry_run=True, tmp_path=tmp_path
        )
        assert dismissed == [{"title": "Test Article", "score": 0.4}]

    def test_real_run_still_upserts(self, tmp_path):
        """Sanity: non-dry-run behavior is unchanged."""
        _result, mock_upsert, _mock_mark = _run(score=0.9, threshold=0.5, dry_run=False, tmp_path=tmp_path)
        mock_upsert.assert_called_once()

    def test_real_run_still_marks_dismissed(self, tmp_path):
        _result, _mock_upsert, mock_mark = _run(score=0.2, threshold=0.5, dry_run=False, tmp_path=tmp_path)
        mock_mark.assert_called_once_with("https://example.com/article", "dismissed", str(tmp_path / "store.db"))
