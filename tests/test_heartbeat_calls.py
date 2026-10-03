"""The scoring loop heartbeats per item so process-doctor doesn't mistake gateway waits for a hang."""
from unittest.mock import MagicMock, patch

from local_first_common.testing import MockProvider

from discovery.orchestrator import run_discovery


def _item(n):
    item = MagicMock()
    item.url = f"https://example.com/{n}"
    item.title = f"Article {n}"
    item.description = "desc"
    item.source = "Example Blog"
    item.published = "2026-10-03"
    return item


def test_heartbeat_once_before_and_once_per_scored_item(tmp_path):
    provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
    items = [_item(i) for i in range(3)]
    with patch("discovery.orchestrator.fetch_feed", return_value=items), \
         patch("discovery.store.init_db"), \
         patch("discovery.orchestrator.store.get_kept_tag_counts_for_date", return_value={}), \
         patch("discovery.store.get_examples", return_value={}), \
         patch("discovery.store.is_seen", return_value=False), \
         patch("discovery.store.upsert_item"), \
         patch("discovery.store.mark_item"), \
         patch("discovery.orchestrator.heartbeat") as beat:
        run_discovery(provider, "rss", None, 0.5, True, False, False, None, str(tmp_path), dry_run=True)
    assert beat.call_count == 1 + len(items)


def test_heartbeat_is_a_noop_outside_launchd(tmp_path, monkeypatch):
    """Without LOCALFIRST_JOB_LABEL nothing is written -- interactive runs leave no beat behind."""
    from local_first_common import heartbeat as hb

    monkeypatch.delenv(hb.LABEL_ENV, raising=False)
    monkeypatch.setenv(hb.DIR_ENV, str(tmp_path))
    assert hb.heartbeat() is False
    assert list(tmp_path.iterdir()) == []
