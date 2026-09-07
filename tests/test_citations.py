"""Tests for citation mining: turning outbound links from kept articles into
candidate FeedItems (see discovery/citations.py for the rationale)."""
from local_first_common.article_fetcher import FeedItem

from discovery.citations import discover_citation_candidates


def _feed_item(url, source="other.com"):
    return FeedItem(
        title=f"Title for {url}", description="desc", url=url, source=source,
        found_at=None, platform="citations",
    )


class TestDiscoverCitationCandidates:
    def test_empty_kept_items_returns_empty(self):
        assert discover_citation_candidates([]) == []

    def test_extracts_links_and_fetches_metadata(self):
        def page_fetcher(url):
            return '<article><a href="https://other.com/post">Link</a></article>'

        calls = []

        def metadata_fetcher(url, **kwargs):
            calls.append((url, kwargs))
            return _feed_item(url)

        kept = [{"url": "https://origin.com/a", "title": "Origin"}]
        result = discover_citation_candidates(
            kept, page_fetcher=page_fetcher, metadata_fetcher=metadata_fetcher
        )

        assert len(result) == 1
        assert result[0].url == "https://other.com/post"
        assert calls[0][0] == "https://other.com/post"
        assert calls[0][1]["source_url"] == "https://origin.com/a"
        assert calls[0][1]["source_platform"] == "citations"

    def test_skips_self_links(self):
        def page_fetcher(url):
            return (
                '<article>'
                '<a href="https://origin.com/other-post">Self link</a>'
                '<a href="https://other.com/post">External</a>'
                "</article>"
            )

        def metadata_fetcher(url, **kwargs):
            return _feed_item(url)

        kept = [{"url": "https://origin.com/a", "title": "Origin"}]
        result = discover_citation_candidates(
            kept, page_fetcher=page_fetcher, metadata_fetcher=metadata_fetcher
        )

        assert [i.url for i in result] == ["https://other.com/post"]

    def test_skips_blocked_domains_without_fetching_metadata(self):
        def page_fetcher(url):
            return (
                '<article>'
                '<a href="https://blocked.com/post">Blocked</a>'
                '<a href="https://other.com/post">OK</a>'
                "</article>"
            )

        calls = []

        def metadata_fetcher(url, **kwargs):
            calls.append(url)
            return _feed_item(url)

        kept = [{"url": "https://origin.com/a", "title": "Origin"}]
        result = discover_citation_candidates(
            kept,
            blocked_domains=frozenset({"blocked.com"}),
            page_fetcher=page_fetcher,
            metadata_fetcher=metadata_fetcher,
        )

        assert calls == ["https://other.com/post"]
        assert [i.url for i in result] == ["https://other.com/post"]

    def test_respects_max_links_per_item(self):
        def page_fetcher(url):
            links = "".join(f'<a href="https://site{i}.com/p">L{i}</a>' for i in range(5))
            return f"<article>{links}</article>"

        def metadata_fetcher(url, **kwargs):
            return _feed_item(url)

        kept = [{"url": "https://origin.com/a", "title": "Origin"}]
        result = discover_citation_candidates(
            kept, max_links_per_item=2, page_fetcher=page_fetcher, metadata_fetcher=metadata_fetcher
        )

        assert len(result) == 2

    def test_deduplicates_across_multiple_kept_items(self):
        def page_fetcher(url):
            return '<article><a href="https://shared.com/post">Shared</a></article>'

        calls = []

        def metadata_fetcher(url, **kwargs):
            calls.append(url)
            return _feed_item(url)

        kept = [
            {"url": "https://origin-a.com/1", "title": "A"},
            {"url": "https://origin-b.com/1", "title": "B"},
        ]
        result = discover_citation_candidates(
            kept, page_fetcher=page_fetcher, metadata_fetcher=metadata_fetcher
        )

        assert len(calls) == 1
        assert len(result) == 1

    def test_metadata_fetch_failure_is_skipped(self):
        def page_fetcher(url):
            return '<article><a href="https://other.com/post">Link</a></article>'

        def metadata_fetcher(url, **kwargs):
            return None

        kept = [{"url": "https://origin.com/a", "title": "Origin"}]
        result = discover_citation_candidates(
            kept, page_fetcher=page_fetcher, metadata_fetcher=metadata_fetcher
        )

        assert result == []

    def test_page_fetch_failure_skips_that_item_only(self):
        def page_fetcher(url):
            if "bad" in url:
                raise RuntimeError("boom")
            return '<article><a href="https://other.com/post">Link</a></article>'

        def metadata_fetcher(url, **kwargs):
            return _feed_item(url)

        kept = [
            {"url": "https://bad-origin.com/a", "title": "Bad"},
            {"url": "https://good-origin.com/a", "title": "Good"},
        ]
        result = discover_citation_candidates(
            kept, page_fetcher=page_fetcher, metadata_fetcher=metadata_fetcher
        )

        assert len(result) == 1

    def test_empty_page_fetch_skips_item(self):
        def page_fetcher(url):
            return ""

        def metadata_fetcher(url, **kwargs):
            return _feed_item(url)

        kept = [{"url": "https://origin.com/a", "title": "Origin"}]
        result = discover_citation_candidates(
            kept, page_fetcher=page_fetcher, metadata_fetcher=metadata_fetcher
        )

        assert result == []
