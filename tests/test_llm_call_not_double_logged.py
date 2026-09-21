"""Regression 2026-09-20: an LLM call is logged once, inside the gateway --
this repo used to keep its own duplicate processing_log row via timed_run(),
which doubled every gateway-routed call's count on the dashboard. Now the
per-item context (title, item_count) travels to the gateway via
llm_provider.source_location/llm_provider.item_count instead of a second
write, and this repo writes nothing to processing_log itself.
"""
from unittest.mock import MagicMock, patch

from local_first_common.scoring import ScoredItem
from local_first_common.testing import MockProvider

from discovery.orchestrator import run_discovery


def _make_feed_item():
    item = MagicMock()
    item.url = "https://example.com/article"
    item.title = "Test Article"
    item.description = "A test article description."
    item.source = "Example Blog"
    item.published = "2026-09-07"
    item.found_at = None
    item.search_term = None
    item.platform = None
    return item


def test_source_location_and_item_count_set_on_provider_before_scoring(tmp_path):
    llm = MockProvider(response="ok")

    def fake_score_item(*args, **kwargs):
        assert llm.source_location == "Test Article"
        assert llm.item_count == 1
        return ScoredItem(score=0.9, tags=[], summary="s", language="en")

    with patch("discovery.orchestrator.fetch_feed", return_value=[_make_feed_item()]), \
         patch("discovery.orchestrator.store.init_db"), \
         patch("discovery.orchestrator.store.get_examples", return_value={}), \
         patch("discovery.orchestrator.store.is_seen", return_value=False), \
         patch("discovery.orchestrator.store.upsert_item"), \
         patch("discovery.orchestrator.store.mark_item"), \
         patch("discovery.orchestrator.READWISE_ROUTING", False), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", False), \
         patch("discovery.orchestrator.score_item", side_effect=fake_score_item):
        run_discovery(
            llm, "rss", None, 0.5,
            True, False, False, None, str(tmp_path / "store.db"),
            dry_run=True,
        )
