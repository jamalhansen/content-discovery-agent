"""Tests for the contexta_inbox_routing feature in run_discovery()."""
from unittest.mock import MagicMock, patch

from local_first_common.testing import MockProvider

from discovery.orchestrator import run_discovery


def _make_feed_item(url="https://example.com/article", title="Test Article"):
    item = MagicMock()
    item.url = url
    item.title = title
    item.description = "A test article description."
    item.source = "Example Blog"
    item.published = "2026-03-28"
    return item


def _run(provider, items, threshold, dry_run, routing, inbox_path, store_path):
    """Run run_discovery with all heavy I/O patched out."""
    with patch("discovery.orchestrator.fetch_feed", return_value=items), \
         patch("discovery.store.init_db"), \
         patch("discovery.store.get_examples", return_value={}), \
         patch("discovery.store.is_seen", return_value=False), \
         patch("discovery.store.upsert_item"), \
         patch("discovery.store.mark_item"), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", routing), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_PATH", inbox_path), \
         patch("discovery.orchestrator.save_to_vault_inbox") as mock_save:
        run_discovery(
            provider, "rss", None, threshold,
            True, False, False, None, str(store_path),
            dry_run=dry_run,
        )
    return mock_save


class TestContextaInboxRouting:

    def test_routing_disabled_by_default(self, tmp_path):
        """save_to_vault_inbox is NOT called when CONTEXTA_INBOX_ROUTING is False."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        mock_save = _run(provider, [_make_feed_item()], 0.5, False, False, str(tmp_path), tmp_path)
        mock_save.assert_not_called()

    def test_routing_enabled_calls_save_for_above_threshold(self, tmp_path):
        """save_to_vault_inbox IS called for items above threshold when routing is enabled."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        item = _make_feed_item()
        mock_save = _run(provider, [item], 0.5, False, True, str(tmp_path), tmp_path)
        mock_save.assert_called_once_with(
            str(tmp_path), item.url,
            title=item.title,
            summary="Good.",
            tags=["ai"],
            published_date=item.published,
            search_term=item.search_term,
            platform=item.platform,
        )

    def test_routing_enabled_dry_run_does_not_call_save(self, tmp_path):
        """save_to_vault_inbox is NOT called when dry_run=True."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        mock_save = _run(provider, [_make_feed_item()], 0.5, True, True, str(tmp_path), tmp_path)
        mock_save.assert_not_called()

    def test_below_threshold_item_not_routed(self, tmp_path):
        """Items below the threshold are never routed to the vault inbox."""
        provider = MockProvider(response='{"score": 0.3, "tags": ["misc"], "summary": "Low.", "language": "en"}')
        mock_save = _run(provider, [_make_feed_item()], 0.6, False, True, str(tmp_path), tmp_path)
        mock_save.assert_not_called()

    def test_non_english_item_not_routed(self, tmp_path):
        """Non-English items are dismissed and never routed to the vault inbox."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ru"], "summary": "Текст.", "language": "ru"}')
        mock_save = _run(provider, [_make_feed_item()], 0.5, False, True, str(tmp_path), tmp_path)
        mock_save.assert_not_called()

    def test_both_readwise_and_vault_inbox_can_fire_together(self, tmp_path):
        """The two routing destinations are independent, not mutually exclusive."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        item = _make_feed_item()
        with patch("discovery.orchestrator.fetch_feed", return_value=[item]), \
             patch("discovery.store.init_db"), \
             patch("discovery.store.get_examples", return_value={}), \
             patch("discovery.store.is_seen", return_value=False), \
             patch("discovery.store.upsert_item"), \
             patch("discovery.store.mark_item"), \
             patch("discovery.orchestrator.READWISE_ROUTING", True), \
             patch("discovery.orchestrator.READWISE_TOKEN", "tok_abc"), \
             patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", True), \
             patch("discovery.orchestrator.CONTEXTA_INBOX_PATH", str(tmp_path)), \
             patch("discovery.orchestrator.save_to_readwise") as mock_rw, \
             patch("discovery.orchestrator.save_to_vault_inbox") as mock_inbox:
            run_discovery(
                provider, "rss", None, 0.5,
                True, False, False, None, str(tmp_path),
                dry_run=False,
            )
        mock_rw.assert_called_once()
        mock_inbox.assert_called_once()
