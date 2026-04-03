"""Tests for the readwise_routing feature in run_discovery()."""
from unittest.mock import MagicMock, patch


from discovery.orchestrator import run_discovery
from local_first_common.testing import MockProvider


def _make_feed_item(url="https://example.com/article", title="Test Article"):
    item = MagicMock()
    item.url = url
    item.title = title
    item.description = "A test article description."
    item.source = "Example Blog"
    item.published = "2026-03-28"
    return item


def _run(provider, items, threshold, dry_run, routing, token, store_path):
    """Run run_discovery with all heavy I/O patched out."""
    with patch("discovery.orchestrator.fetch_feed", return_value=items), \
         patch("discovery.store.init_db"), \
         patch("discovery.store.get_examples", return_value={}), \
         patch("discovery.store.is_seen", return_value=False), \
         patch("discovery.store.upsert_item"), \
         patch("discovery.store.mark_item"), \
         patch("discovery.orchestrator.READWISE_ROUTING", routing), \
         patch("discovery.orchestrator.READWISE_TOKEN", token), \
         patch("discovery.orchestrator.save_to_readwise") as mock_save:
        run_discovery(
            provider, "rss", None, threshold,
            True, False, False, None, str(store_path),
            dry_run=dry_run,
        )
    return mock_save


class TestReadwiseRouting:

    def test_routing_disabled_by_default(self, tmp_path):
        """save_to_readwise is NOT called when READWISE_ROUTING is False."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        mock_save = _run(provider, [_make_feed_item()], 0.5, False, False, "tok", tmp_path)
        mock_save.assert_not_called()

    def test_routing_enabled_calls_save_for_above_threshold(self, tmp_path):
        """save_to_readwise IS called for items above threshold when routing is enabled."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        item = _make_feed_item()
        mock_save = _run(provider, [item], 0.5, False, True, "tok_abc", tmp_path)
        mock_save.assert_called_once_with(
            "tok_abc", item.url,
            title=item.title,
            summary="Good.",
            tags=["ai"],
            published_date=item.published,
            search_term=item.search_term,
            platform=item.platform,
        )

    def test_routing_enabled_dry_run_does_not_call_save(self, tmp_path):
        """save_to_readwise is NOT called when dry_run=True."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        mock_save = _run(provider, [_make_feed_item()], 0.5, True, True, "tok_abc", tmp_path)
        mock_save.assert_not_called()

    def test_routing_enabled_no_token_does_not_call_save(self, tmp_path):
        """save_to_readwise is NOT called when token is empty."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        mock_save = _run(provider, [_make_feed_item()], 0.5, False, True, "", tmp_path)
        mock_save.assert_not_called()

    def test_below_threshold_item_not_routed(self, tmp_path):
        """Items below the threshold are never sent to Readwise."""
        provider = MockProvider(response='{"score": 0.3, "tags": ["misc"], "summary": "Low.", "language": "en"}')
        mock_save = _run(provider, [_make_feed_item()], 0.6, False, True, "tok_abc", tmp_path)
        mock_save.assert_not_called()

    def test_non_english_item_not_routed(self, tmp_path):
        """Non-English items are dismissed and never sent to Readwise."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ru"], "summary": "Текст.", "language": "ru"}')
        mock_save = _run(provider, [_make_feed_item()], 0.5, False, True, "tok_abc", tmp_path)
        mock_save.assert_not_called()
