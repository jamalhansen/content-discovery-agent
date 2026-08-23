"""Tests for the pre-scoring title and domain filters in run_discovery()."""
from unittest.mock import MagicMock, patch


from discovery.orchestrator import run_discovery
from local_first_common.testing import MockProvider


def _make_feed_item(url="https://example.com/article", title="Test Article"):
    item = MagicMock()
    item.url = url
    item.title = title
    item.description = "A test article description."
    item.source = "Example Blog"
    item.published = "2026-08-22"
    return item


def _scored_titles(items, store_path, title_patterns=("(sponsor)",)):
    """Run run_discovery over items; return the titles that reached the scorer."""
    provider = MockProvider(
        ['{"score": 0.9, "tags": ["t"], "summary": "s", "language": "en"}'] * 20
    )
    with patch("discovery.orchestrator.fetch_feed", return_value=items), \
         patch("discovery.store.init_db"), \
         patch("discovery.store.get_examples", return_value={}), \
         patch("discovery.store.is_seen", return_value=False), \
         patch("discovery.store.upsert_item"), \
         patch("discovery.store.mark_item"), \
         patch("discovery.orchestrator.READWISE_ROUTING", False), \
         patch("discovery.orchestrator.CONTEXTA_INBOX_ROUTING", False), \
         patch("discovery.orchestrator.BLOCKED_TITLE_PATTERNS", title_patterns), \
         patch("discovery.orchestrator.score_item") as mock_score:
        mock_score.return_value = MagicMock(
            score=0.9, tags=["t"], summary="s", language="en"
        )
        run_discovery(
            provider, "rss", None, 0.5,
            True, False, False, None, str(store_path),
        )
    return [call.args[1] for call in mock_score.call_args_list]


class TestTitleFilter:

    def test_sponsor_items_never_reach_the_scorer(self, tmp_path):
        items = [
            _make_feed_item(title="Real Article About Agents"),
            _make_feed_item(
                url="https://example.com/ad",
                title="Learn how OpenAI runs durable agents (Sponsor)",
            ),
        ]

        scored = _scored_titles(items, tmp_path)

        assert scored == ["Real Article About Agents"]

    def test_title_match_is_case_insensitive(self, tmp_path):
        items = [_make_feed_item(title="Something (SPONSOR)")]

        assert _scored_titles(items, tmp_path) == []

    def test_empty_pattern_list_filters_nothing(self, tmp_path):
        items = [_make_feed_item(title="Something (Sponsor)")]

        scored = _scored_titles(items, tmp_path, title_patterns=())

        assert scored == ["Something (Sponsor)"]


class TestDomainFilter:

    def test_rss_items_on_blocked_domains_are_dropped(self, tmp_path):
        """RSS previously skipped the blocklist that social sources apply.

        x.com is not a usable example here: it was in the blocklist until
        2026-08-23, when the "no title, just warning noise" problem turned
        out to be a missing normalize_url() call rather than the domain being
        genuinely unscrapeable, so it was removed. bsky.app remains blocked
        (search/post pages get mistaken for articles) and still exercises the
        same code path.
        """
        items = [
            _make_feed_item(
                url="https://bsky.app/profile/tempo/post/123", title="A Bluesky Post"
            ),
            _make_feed_item(
                url="https://simonwillison.net/2026/Aug/21/qwen/",
                title="A Real Post",
            ),
        ]

        scored = _scored_titles(items, tmp_path)

        assert scored == ["A Real Post"]

    def test_subdomains_of_blocked_hosts_are_dropped(self, tmp_path):
        items = [
            _make_feed_item(url="https://www.youtube.com/watch?v=abc", title="A Video")
        ]

        assert _scored_titles(items, tmp_path) == []
