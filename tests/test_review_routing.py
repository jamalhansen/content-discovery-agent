"""Tests for per-item destination routing in run_review()."""
from unittest.mock import patch

from discovery.orchestrator import run_review


def _make_item(url="https://example.com/article", title="Test Article"):
    return {
        "url": url,
        "title": title,
        "summary": "A summary.",
        "tags": ["ai"],
        "source": "Example Blog",
        "score": 0.9,
        "published_at": "2026-03-28",
        "platform": None,
        "search_term": None,
    }


def _run(items, inputs, contexta_routing):
    with patch("discovery.orchestrator.store.get_new_items", return_value=items), \
         patch("discovery.orchestrator.store.mark_item"), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", contexta_routing), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_PATH", "/fake/inbox"), \
         patch("builtins.input", side_effect=inputs), \
         patch("discovery.orchestrator.save_to_readwise", return_value=True) as mock_rw, \
         patch("discovery.orchestrator.save_to_vault_inbox", return_value=True) as mock_inbox:
        result = run_review("/fake/store.db", "tok_abc")
    return result, mock_rw, mock_inbox


class TestReviewRouting:
    def test_y_routes_to_readwise_only_when_contexta_disabled(self):
        (kept, dismissed), mock_rw, mock_inbox = _run([_make_item()], ["y"], contexta_routing=False)
        assert kept == 1
        mock_rw.assert_called_once()
        mock_inbox.assert_not_called()

    def test_y_routes_to_both_when_contexta_enabled(self):
        (kept, dismissed), mock_rw, mock_inbox = _run([_make_item()], ["y"], contexta_routing=True)
        assert kept == 1
        mock_rw.assert_called_once()
        mock_inbox.assert_called_once()

    def test_r_routes_to_readwise_only_even_when_contexta_enabled(self):
        """'r' is a per-item override: skip Contexta for this item regardless of global config."""
        (kept, dismissed), mock_rw, mock_inbox = _run([_make_item()], ["r"], contexta_routing=True)
        assert kept == 1
        mock_rw.assert_called_once()
        mock_inbox.assert_not_called()

    def test_c_routes_to_contexta_only_even_when_contexta_disabled(self):
        """'c' is a per-item override: redirect this item to Contexta even if the global toggle is off."""
        (kept, dismissed), mock_rw, mock_inbox = _run([_make_item()], ["c"], contexta_routing=False)
        assert kept == 1
        mock_rw.assert_not_called()
        mock_inbox.assert_called_once()

    def test_n_dismisses_without_routing(self):
        (kept, dismissed), mock_rw, mock_inbox = _run([_make_item()], ["n"], contexta_routing=True)
        assert kept == 0
        assert dismissed == 1
        mock_rw.assert_not_called()
        mock_inbox.assert_not_called()

    def test_mixed_choices_across_multiple_items(self):
        items = [_make_item(url="https://a.com"), _make_item(url="https://b.com"), _make_item(url="https://c.com")]
        (kept, dismissed), mock_rw, mock_inbox = _run(items, ["r", "c", "n"], contexta_routing=False)
        assert kept == 2
        assert dismissed == 1
        assert mock_rw.call_count == 1
        assert mock_inbox.call_count == 1

    def test_invalid_choice_reprompts(self):
        (kept, dismissed), mock_rw, mock_inbox = _run([_make_item()], ["x", "y"], contexta_routing=False)
        assert kept == 1
        mock_rw.assert_called_once()

    def test_empty_queue_returns_zero_zero(self):
        with patch("discovery.orchestrator.store.get_new_items", return_value=[]):
            result = run_review("/fake/store.db", "tok_abc")
        assert result == (0, 0)
