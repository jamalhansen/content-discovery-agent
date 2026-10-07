"""Tests for the optional real-browser rendering fallback."""

import sys

import pytest

from discovery.support.js_render import (
    RenderUnavailable,
    fetch_rendered_html,
    fetch_rendered_text,
    host_of,
)


class FakePage:
    def __init__(self, text, html=None):
        self._text = text
        self._html = html if html is not None else f"<html><body>{text}</body></html>"
        self.goto_calls = []

    def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append((url, timeout, wait_until))

    def wait_for_timeout(self, ms):
        pass

    def inner_text(self, selector):
        return self._text

    def content(self):
        return self._html


class FakeBrowser:
    def __init__(self, page, raise_on_new_page=None):
        self._page = page
        self._raise = raise_on_new_page
        self.closed = False

    def new_page(self):
        if self._raise:
            raise self._raise
        return self._page

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self._browser = browser

    def launch(self):
        return self._browser


class FakeSyncPlaywright:
    """A stand-in for playwright.sync_api.sync_playwright as both the factory
    function and the context manager it returns, matching how the real one
    is used: `with sync_playwright() as p: p.chromium.launch()...`.
    """

    def __init__(self, text="rendered text", html=None, raise_on_new_page=None):
        self.page = FakePage(text, html=html)
        self.browser = FakeBrowser(self.page, raise_on_new_page=raise_on_new_page)
        self.chromium = FakeChromium(self.browser)

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestFetchRenderedText:
    def test_returns_the_rendered_page_text(self):
        fake = FakeSyncPlaywright(text="Full article content here.")
        result = fetch_rendered_text("https://x.com/a/status/1", sync_playwright_fn=fake)
        assert result == "Full article content here."

    def test_navigates_to_the_given_url_with_timeout(self):
        fake = FakeSyncPlaywright()
        fetch_rendered_text("https://x.com/a/status/1", timeout_ms=5000, sync_playwright_fn=fake)
        assert fake.page.goto_calls == [("https://x.com/a/status/1", 5000, "domcontentloaded")]

    def test_closes_the_browser_after_a_successful_render(self):
        fake = FakeSyncPlaywright()
        fetch_rendered_text("https://x.com/a/status/1", sync_playwright_fn=fake)
        assert fake.browser.closed is True

    def test_closes_the_browser_even_when_rendering_raises(self):
        fake = FakeSyncPlaywright(raise_on_new_page=RuntimeError("navigation failed"))
        with pytest.raises(RuntimeError):
            fetch_rendered_text("https://x.com/a/status/1", sync_playwright_fn=fake)
        assert fake.browser.closed is True

    def test_raises_render_unavailable_when_playwright_is_not_installed(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "playwright", None)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
        with pytest.raises(RenderUnavailable):
            fetch_rendered_text("https://x.com/a/status/1")


class TestFetchRenderedHtml:
    def test_returns_the_rendered_page_html(self):
        fake = FakeSyncPlaywright(html="<html><body><article>Real content</article></body></html>")
        result = fetch_rendered_html("https://example.com/a", sync_playwright_fn=fake)
        assert result == "<html><body><article>Real content</article></body></html>"

    def test_navigates_to_the_given_url_with_timeout(self):
        fake = FakeSyncPlaywright()
        fetch_rendered_html("https://example.com/a", timeout_ms=5000, sync_playwright_fn=fake)
        assert fake.page.goto_calls == [("https://example.com/a", 5000, "domcontentloaded")]

    def test_closes_the_browser_after_a_successful_render(self):
        fake = FakeSyncPlaywright()
        fetch_rendered_html("https://example.com/a", sync_playwright_fn=fake)
        assert fake.browser.closed is True

    def test_closes_the_browser_even_when_rendering_raises(self):
        fake = FakeSyncPlaywright(raise_on_new_page=RuntimeError("navigation failed"))
        with pytest.raises(RuntimeError):
            fetch_rendered_html("https://example.com/a", sync_playwright_fn=fake)
        assert fake.browser.closed is True

    def test_raises_render_unavailable_when_playwright_is_not_installed(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "playwright", None)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
        with pytest.raises(RenderUnavailable):
            fetch_rendered_html("https://example.com/a")


class TestHostOf:
    def test_strips_www_prefix(self):
        assert host_of("https://www.x.com/a/status/1") == "x.com"

    def test_lowercases(self):
        assert host_of("https://X.COM/a") == "x.com"

    def test_leaves_bare_host_unchanged(self):
        assert host_of("https://x.com/a") == "x.com"
