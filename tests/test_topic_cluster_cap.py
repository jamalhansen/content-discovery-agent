"""Tests for the same-day topic-cluster cap in run_discovery().

Jamal 2026-09-22: "it can't all be relevant and unique" -- a single news
event produces many individually on-topic, individually-unique-URL
articles that are still redundant as a group. Once CLUSTER_CAP items
sharing a tag are already kept today, an additional item needs
CLUSTER_SCORE_BONUS above the normal threshold to also get kept.
"""
from unittest.mock import MagicMock, patch

from local_first_common.testing import MockProvider

from discovery.orchestrator import run_discovery


def _make_feed_item(url, title="Test Article"):
    item = MagicMock()
    item.url = url
    item.title = title
    item.description = "A test article description."
    item.source = "Example Blog"
    item.published = "2026-03-28"
    return item


def _run(provider, items, threshold, kept_today, cluster_cap=3, cluster_bonus=0.10):
    with patch("discovery.orchestrator.fetch_feed", return_value=items), \
         patch("discovery.store.init_db"), \
         patch("discovery.store.get_examples", return_value={}), \
         patch("discovery.store.is_seen", return_value=False), \
         patch("discovery.store.upsert_item"), \
         patch("discovery.store.mark_item"), \
         patch("discovery.orchestrator.CLUSTER_CAP", cluster_cap), \
         patch("discovery.orchestrator.CLUSTER_SCORE_BONUS", cluster_bonus), \
         patch("discovery.orchestrator.store.get_kept_tag_counts_for_date", return_value=dict(kept_today)), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", True), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_PATH", "/fake"), \
         patch("discovery.orchestrator.save_to_vault_inbox") as mock_save:
        candidates, _scored, _skipped, _dismissed = run_discovery(
            provider, "rss", None, threshold,
            True, False, False, None, "fake-store-path",
            dry_run=False,
        )
    return candidates, mock_save


class TestTopicClusterCap:
    def test_items_below_cluster_cap_pass_at_normal_threshold(self):
        provider = MockProvider(response='{"score": 0.85, "tags": ["ai-safety"], "summary": "s", "language": "en"}')
        items = [_make_feed_item(f"https://example.com/{i}") for i in range(3)]
        candidates, mock_save = _run(provider, items, threshold=0.81, kept_today={})
        assert len(candidates) == 3
        assert mock_save.call_count == 3

    def test_item_past_cluster_cap_needs_higher_score(self):
        """3 already kept today puts the tag at cap; a same-scoring new item
        (0.85, below threshold+bonus=0.91) is dismissed, not kept."""
        provider = MockProvider(response='{"score": 0.85, "tags": ["ai-safety"], "summary": "s", "language": "en"}')
        items = [_make_feed_item("https://example.com/fourth")]
        candidates, mock_save = _run(provider, items, threshold=0.81, kept_today={"ai-safety": 3})
        assert candidates == []
        assert mock_save.call_count == 0

    def test_item_past_cluster_cap_with_high_enough_score_still_kept(self):
        """A genuinely stronger piece on an already-clustered topic still
        gets through -- the cap raises the bar, it doesn't hard-block."""
        provider = MockProvider(response='{"score": 0.95, "tags": ["ai-safety"], "summary": "s", "language": "en"}')
        items = [_make_feed_item("https://example.com/strong")]
        candidates, mock_save = _run(provider, items, threshold=0.81, kept_today={"ai-safety": 5})
        assert len(candidates) == 1
        assert mock_save.call_count == 1

    def test_cluster_cap_applies_within_a_single_run_not_just_across_runs(self):
        """4 items scored in one run, all sharing a tag, cap=3: the 4th needs
        the bonus even though nothing was kept today before this run started."""
        provider = MockProvider(response='{"score": 0.85, "tags": ["ai-safety"], "summary": "s", "language": "en"}')
        items = [_make_feed_item(f"https://example.com/{i}") for i in range(4)]
        candidates, mock_save = _run(provider, items, threshold=0.81, kept_today={})
        assert len(candidates) == 3
        assert mock_save.call_count == 3

    def test_different_tags_do_not_share_a_cluster_budget(self):
        provider = MockProvider(response='{"score": 0.85, "tags": ["ai-safety"], "summary": "s", "language": "en"}')
        items = [_make_feed_item(f"https://example.com/{i}") for i in range(2)]
        candidates, mock_save = _run(provider, items, threshold=0.81, kept_today={"local-llm": 5})
        assert len(candidates) == 2
        assert mock_save.call_count == 2
