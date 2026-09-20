"""Regression 2026-09-20: a GatewayProvider with no explicit --model has
.model == "" until the gateway resolves it server-side, during the scoring
call -- but the processing_log row's model was captured from
llm_provider.model *before* that call ran, so real production data showed
198 empty-model rows for content-discovery-agent alone. Re-read
llm_provider.model/provider_name right after score_item() returns, before
any early `continue` on a skipped item.
"""
from unittest.mock import MagicMock, patch

import duckdb
from local_first_common.scoring import ScoredItem
from local_first_common.testing import MockProvider
from local_first_common.tracking import get_tracking_db_path

from discovery.orchestrator import run_discovery


class ResolvesModelDuringScoring(MockProvider):
    default_model = ""  # matches GatewayProvider's own real default when no model is specified


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


def test_model_and_provider_reflect_post_resolution_value(tmp_path):
    llm = ResolvesModelDuringScoring()
    assert llm.model == ""

    def fake_score_item(*args, **kwargs):
        llm.model = "phi4-mini"  # simulates the gateway resolving an unspecified model
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

    conn = duckdb.connect(str(get_tracking_db_path()))
    row = conn.execute(
        "SELECT model, provider FROM processing_log WHERE tool_name = 'content-discovery-agent' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == "phi4-mini"
    assert row[1] == "mock"
