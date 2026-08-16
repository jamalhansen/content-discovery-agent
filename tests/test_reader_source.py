"""Tests for the 'reader' source in run_discovery() — pulling from Reader's unread queue."""
from unittest.mock import MagicMock, patch

from discovery.orchestrator import run_discovery
from local_first_common.testing import MockProvider


def _make_reader_item(url="https://example.com/original-article", title="Test Article", source="readwise-reader"):
    item = MagicMock()
    item.url = url
    item.title = title
    item.description = "A test article description."
    item.source = source
    item.published = "2026-03-28"
    return item


def _run(provider, items, sources="reader", token="tok_abc", routing=False, no_dedup=True):
    """Run run_discovery with reader fetch patched, all other I/O patched out."""
    with patch("discovery.orchestrator.list_reader_documents", return_value=items) as mock_list, \
         patch("discovery.store.init_db"), \
         patch("discovery.store.get_examples", return_value={}), \
         patch("discovery.store.is_seen", return_value=False), \
         patch("discovery.store.upsert_item"), \
         patch("discovery.store.mark_item"), \
         patch("discovery.orchestrator.READWISE_TOKEN", token), \
         patch("discovery.orchestrator.READWISE_ROUTING", routing), \
         patch("discovery.orchestrator.save_to_readwise") as mock_save:
        candidates, scored, skipped = run_discovery(
            provider, sources, None, 0.5,
            no_dedup, False, False, None, "unused.db",
            dry_run=False,
        )
    return mock_list, mock_save, candidates, scored, skipped


class TestReaderSource:

    def test_skipped_when_no_token(self):
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        mock_list, _, candidates, scored, _ = _run(provider, [_make_reader_item()], token="")
        mock_list.assert_not_called()
        assert scored == 0

    def test_fetches_and_scores_reader_items(self):
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        item = _make_reader_item()
        mock_list, _, candidates, scored, _ = _run(provider, [item])
        mock_list.assert_called_once()
        assert scored == 1
        assert candidates[0]["url"] == item.url

    def test_not_included_when_sources_excludes_reader(self):
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        with patch("discovery.orchestrator.fetch_feed", return_value=[]):
            mock_list, _, candidates, scored, _ = _run(provider, [_make_reader_item()], sources="rss")
        mock_list.assert_not_called()
        assert scored == 0

    def test_reader_sourced_item_not_pushed_back_to_readwise(self):
        """Items pulled from Reader shouldn't be re-saved back to Reader."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        item = _make_reader_item(source="readwise-reader")
        _, mock_save, _, _, _ = _run(provider, [item], routing=True)
        mock_save.assert_not_called()

    def test_non_reader_sourced_item_still_pushed_when_routing_enabled(self):
        """Sanity check: the reader-source guard doesn't suppress routing for other sources."""
        provider = MockProvider(response='{"score": 0.9, "tags": ["ai"], "summary": "Good.", "language": "en"}')
        item = _make_reader_item(source="Some Blog")
        with patch("discovery.orchestrator.fetch_feed", return_value=[item]), \
             patch("discovery.store.init_db"), \
             patch("discovery.store.get_examples", return_value={}), \
             patch("discovery.store.is_seen", return_value=False), \
             patch("discovery.store.upsert_item"), \
             patch("discovery.store.mark_item"), \
             patch("discovery.orchestrator.READWISE_TOKEN", "tok_abc"), \
             patch("discovery.orchestrator.READWISE_ROUTING", True), \
             patch("discovery.orchestrator.save_to_readwise") as mock_save:
            run_discovery(provider, "rss", None, 0.5, True, False, False, None, "unused.db", dry_run=False)
        mock_save.assert_called_once()
