"""Routes kept candidates into an Obsidian vault's inbox/ directory.

Writes one markdown file per item: light frontmatter (source, tags, capture
date), the scoring summary, and the article body. Structuring beyond that is
left to the vault's own processing pipeline.

The body matters more than it looks. A file carrying only the one-line scoring
summary can only be reduced into a note that restates the headline, which is
exactly what happened to the April 2026 batch: notes written from summaries
asserted things their sources never said. Capture the text or capture the
failure, but do not capture a stub and call it a source.
"""
import logging
import os
import re
from datetime import datetime

from .config import JS_RENDER_ENABLED

logger = logging.getLogger(__name__)

# Long enough for a substantial essay, short enough that one pathological page
# cannot dominate the inbox. Truncation is marked in the file, never silent.
MAX_BODY_CHARS = 40_000

# Below this, an extraction is more likely to be navigation chrome from a
# JavaScript-rendered page than article prose. A successful fetch is not the
# same as usable text, and the file says which it got rather than implying
# quality it cannot vouch for.
THIN_BODY_CHARS = 1_200

# Opt-in delegation to http-retriever-service for the fetch+extract+render
# pipeline below, instead of this module's own local_first_common.http/html/
# js_render calls. Unset by default. This is the higher-value of the two
# content-discovery-agent integration points (see fetch_article_metadata's
# equivalent in local_first_common.article_fetcher): unlike that one, this
# function runs in discovery-loop's actual daily production path and is what
# currently forces content-discovery-agent to bundle its own separate
# Playwright install and use a hand-rolled extractor instead of the
# retriever's real Mozilla Readability.
HTTP_RETRIEVER_URL = os.environ.get("HTTP_RETRIEVER_URL") or None


def _fetch_body_via_retriever(url: str) -> tuple[str, str]:
    """POST to http-retriever-service and return (body, error).

    The service already does fetch -> extract -> render-fallback-if-thin in
    one call, so this replaces the whole local pipeline below rather than
    just one piece of it.
    """
    import httpx

    headers = {}
    api_key = os.environ.get("HTTP_RETRIEVER_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.post(
            f"{HTTP_RETRIEVER_URL.rstrip('/')}/fetch",
            json={"url": url, "toolName": "content-discovery-agent"},
            headers=headers,
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        return "", f"http-retriever-service request failed: {type(e).__name__}: {e}"

    if response.status_code == 403:
        return "", "blocked domain (via http-retriever-service)"
    if response.status_code != 200:
        return "", f"http-retriever-service returned {response.status_code}"

    data = response.json()
    content = (data.get("content") or "").strip()
    quality = data.get("quality")
    if quality == "empty":
        # The service judged the best attempt (plain fetch, or a real
        # browser render if the plain fetch was thin) unusable -- distinct
        # from a hard fetch failure. Marked LOW_QUALITY so the caller can
        # skip the inbox write entirely rather than writing a stub that
        # invites a manual-extraction pass on something not worth it. The
        # judgment itself is already logged server-side (fetch_log's
        # quality column), so nothing is lost by not writing a file too.
        return "", f"LOW_QUALITY: extraction quality too low to use ({len(content)} chars)"
    if not content:
        return "", "fetched but no article text could be extracted"
    return content, ""


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:80].rstrip("-")
    return slug or "untitled"


def _try_render(url: str, extractor, renderer) -> str:
    """Best-effort rendered fetch, narrowed through ``extractor`` the same
    way the plain-fetch path already is -- a raw render's inner_text/HTML
    carries nav/footer/ad chrome right along with the actual content, same
    as an un-narrowed plain fetch would.

    Returns "" on any failure. A missing playwright install is a
    configuration problem worth surfacing (warning, since js_render_enabled
    was already turned on for this run) rather than swallowed at info level
    like a page-specific render failure, which is expected background noise
    for a best-effort fallback.
    """
    if renderer is None:
        from local_first_common.js_render import fetch_rendered_html

        renderer = fetch_rendered_html
    try:
        html = renderer(url) or ""
    except Exception as e:  # noqa: BLE001 - rendering is a best-effort fallback; both branches below already log and degrade to ""
        from local_first_common.js_render import RenderUnavailable

        if isinstance(e, RenderUnavailable):
            logger.warning("Rendered fetch requested for %s but unavailable: %s", url, e)
        else:
            logger.info("Rendered fetch failed for %s: %s: %s", url, type(e).__name__, e)
        return ""
    if not html:
        return ""
    try:
        return (extractor(html) or "").strip()
    except Exception as e:  # noqa: BLE001 - extraction is a best-effort fallback; already logged and degraded to ""
        logger.info("Rendered-HTML extraction failed for %s: %s: %s", url, type(e).__name__, e)
        return ""


def fetch_article_body(
    url: str,
    fetcher=None,
    extractor=None,
    attempt_render: bool = False,
    renderer=None,
) -> tuple[str, str]:
    """Return (body, error) for an article URL. Exactly one is non-empty.

    A failed fetch and an empty article are different states, and collapsing
    them silently corrupts the record, so the error is returned rather than
    swallowed. ``fetcher`` and ``extractor`` are injectable for testing.

    The URL is normalized before fetching (stripping things like a trailing
    slash before a query string) because some sites serve a materially
    different, worse response to the unnormalized form: x.com returns a
    "JavaScript is not available" wall for ".../status/ID/?q=1" and the real
    page for ".../status/ID?q=1", via a plain fetch, no rendering required.
    This is what actually fixed x.com's thin captures; it was never a
    rendering problem.

    ``attempt_render`` controls whether a thin/empty plain-fetch result gets
    a second attempt via a real headless-Chromium render (``renderer``,
    default ``local_first_common.js_render.fetch_rendered_html``, imported
    lazily so this module never requires playwright to be installed). No
    per-domain allowlist here, unlike fetch_article_metadata's scoring-time
    render fallback: that one runs at much higher volume (every scored
    candidate, most of which get dismissed) and genuinely needs one to bound
    cost; this only ever runs for an item that already cleared the keep
    threshold, so trying it for any thin result is cheap and doesn't require
    pre-naming every domain that turns out to need it.
    """
    if not url:
        return "", "no URL"

    if HTTP_RETRIEVER_URL and fetcher is None and extractor is None:
        # Delegating replaces the whole local pipeline below, not one piece
        # of it -- an explicit fetcher/extractor override (tests, or a
        # caller that wants the local path specifically) still wins.
        try:
            from local_first_common.url import normalize_url as _normalize

            url = _normalize(url)
        except Exception as e:  # noqa: BLE001 - normalization is an optimization, not a requirement
            logger.debug("URL normalization failed for %s, using as-is: %s", url, e)
        body, error = _fetch_body_via_retriever(url)
        if error:
            return "", error
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS].rstrip() + f"\n\n[truncated at {MAX_BODY_CHARS} characters]"
        return body, ""

    if fetcher is None or extractor is None:
        from local_first_common.html import extract_main_content
        from local_first_common.http import fetch_url

        fetcher = fetcher or fetch_url
        extractor = extractor or extract_main_content

    # A trailing slash before a query string changes what some sites serve:
    # x.com returns a "JavaScript is not available" wall for
    # ".../status/ID/?q=1" and the real page, full tweet text included, for
    # ".../status/ID?q=1". fetch_article_metadata already normalizes; this
    # fetch path did not, which is why an item scored fine but its inbox
    # capture came back thin from the exact same URL.
    try:
        from local_first_common.url import normalize_url

        url = normalize_url(url)
    except Exception as e:  # noqa: BLE001 - normalization is an optimization, not a requirement; fetch with the original URL rather than fail here
        logger.debug("URL normalization failed for %s, using as-is: %s", url, e)

    try:
        raw = fetcher(url)
    except Exception as e:  # noqa: BLE001 - per this function's own contract, the error is returned as data, not swallowed
        return "", f"{type(e).__name__}: {e}"

    try:
        body = (extractor(raw) or "").strip()
    except Exception as e:  # noqa: BLE001 - per this function's own contract, the error is returned as data, not swallowed
        return "", f"extraction failed, {type(e).__name__}: {e}"

    if len(body) < THIN_BODY_CHARS and attempt_render:
        rendered = _try_render(url, extractor, renderer)
        if len(rendered) > len(body):
            body = rendered

    if not body:
        return "", "fetched but no article text could be extracted"

    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS].rstrip() + f"\n\n[truncated at {MAX_BODY_CHARS} characters]"
    return body, ""


def save_to_vault_inbox(
    inbox_path: str,
    url: str,
    title: str,
    summary: str = "",
    tags: list[str] | None = None,
    published_date: str = "",
    search_term: str = "",
    platform: str = "",
    include_body: bool = True,
    body_fetcher=None,
) -> bool:
    """Write a kept item as a new markdown file in the vault inbox.

    Fetches the article body by default so the file is reduction-ready. A fetch
    failure is written into the file as an explicit marker rather than leaving a
    stub that reads like a thin source. A LOW_QUALITY verdict from the body
    fetcher (real extraction, but judged unusable even after a render retry)
    skips the write entirely instead -- the judgment is already logged
    server-side, so a stub file here wouldn't add anything worth reducing.

    Returns True on success, False if the file could not be written or the
    extraction quality was too low to write at all.
    """
    body, fetch_error = "", ""
    if include_body:
        if body_fetcher is not None:
            body, fetch_error = body_fetcher(url)
        else:
            body, fetch_error = fetch_article_body(url, attempt_render=JS_RENDER_ENABLED)

    if fetch_error.startswith("LOW_QUALITY:"):
        logger.info("Skipping inbox write for %s: %s", url, fetch_error)
        return False

    try:
        target_dir = os.path.expanduser(inbox_path)
        os.makedirs(target_dir, exist_ok=True)

        today = datetime.now().astimezone().date().isoformat()
        slug = _slugify(title)
        filename = f"{today}-{slug}.md"
        filepath = os.path.join(target_dir, filename)

        suffix = 2
        while os.path.exists(filepath):
            filepath = os.path.join(target_dir, f"{today}-{slug}-{suffix}.md")
            suffix += 1

        lines = [
            "---",
            "source_type: content-discovery-agent",
            f"source_url: {url}",
        ]
        if published_date:
            lines.append(f"published: {published_date}")
        if tags:
            tag_str = ", ".join(tags)
            lines.append(f'tags: "{tag_str}"')
        if search_term:
            lines.append(f"search_term: {search_term}")
        if platform:
            lines.append(f"platform: {platform}")
        lines.append(f"captured: {today}")
        if include_body:
            if fetch_error:
                status = "failed"
            elif len(body) < THIN_BODY_CHARS:
                status = "thin"
            else:
                status = "ok"
            lines.append(f"fetch_status: {status}")
            lines.append(f"body_chars: {len(body)}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {title}")
        lines.append("")
        if summary:
            lines.append(f"**Scoring summary:** {summary}")
            lines.append("")
        lines.append(f"Source: {url}")
        lines.append("")

        if include_body:
            if fetch_error:
                lines.append(
                    "> [MANUAL EXTRACTION REQUIRED] The article body could not be "
                    f"retrieved: {fetch_error}."
                )
                lines.append(
                    "> Open the URL and paste the text below, or delete this file. "
                    "Do not reduce it from the summary alone: a one-line summary "
                    "can only produce a note that restates the headline."
                )
                lines.append("")
            else:
                if len(body) < THIN_BODY_CHARS:
                    lines.append(
                        f"> [THIN EXTRACTION] Only {len(body)} characters came back. "
                        "This is often navigation chrome from a JavaScript-rendered "
                        "page rather than the article. Check it against the source "
                        "before reducing."
                    )
                    lines.append("")
                lines.append("---")
                lines.append("")
                lines.append(body)
                lines.append("")

        with open(filepath, "w") as f:
            f.write("\n".join(lines))
        return True
    except OSError:
        return False
