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
from datetime import date

from .config import JS_RENDER_DOMAINS, JS_RENDER_ENABLED

logger = logging.getLogger(__name__)

# Long enough for a substantial essay, short enough that one pathological page
# cannot dominate the inbox. Truncation is marked in the file, never silent.
MAX_BODY_CHARS = 40_000

# Below this, an extraction is more likely to be navigation chrome from a
# JavaScript-rendered page than article prose. A successful fetch is not the
# same as usable text, and the file says which it got rather than implying
# quality it cannot vouch for.
THIN_BODY_CHARS = 1_200


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:80].rstrip("-")
    return slug or "untitled"


def _try_render(url: str, renderer) -> str:
    """Best-effort rendered fetch. Returns "" on any failure, including a
    missing playwright install — rendering is a fallback, never a hard
    requirement, and the caller already has a plain-fetch result to fall
    back to.
    """
    if renderer is None:
        from local_first_common.js_render import fetch_rendered_text

        renderer = fetch_rendered_text
    try:
        return (renderer(url) or "").strip()
    except Exception as e:
        logger.info("Rendered fetch failed for %s: %s: %s", url, type(e).__name__, e)
        return ""


def fetch_article_body(
    url: str,
    fetcher=None,
    extractor=None,
    render_domains: frozenset[str] = frozenset(),
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

    ``render_domains`` names hosts known to genuinely need a real browser
    (client-side JS walls that survive normalization). When the plain fetch
    still comes back thin or empty and the URL's host is in this set, a
    second attempt is made with ``renderer`` (default:
    ``local_first_common.js_render.fetch_rendered_text``, imported lazily so
    this module never requires playwright to be installed). Empty by default:
    rendering only happens when a caller opts in, matching the config flag
    that gates it in save_to_vault_inbox.
    """
    if not url:
        return "", "no URL"

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
    except Exception:
        pass

    try:
        raw = fetcher(url)
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"

    try:
        body = (extractor(raw) or "").strip()
    except Exception as e:
        return "", f"extraction failed, {type(e).__name__}: {e}"

    if len(body) < THIN_BODY_CHARS and render_domains:
        from local_first_common.js_render import host_of

        if host_of(url) in render_domains:
            rendered = _try_render(url, renderer)
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
    stub that reads like a thin source.

    Returns True on success, False if the file could not be written.
    """
    body, fetch_error = "", ""
    if include_body:
        if body_fetcher is not None:
            body, fetch_error = body_fetcher(url)
        else:
            render_domains = JS_RENDER_DOMAINS if JS_RENDER_ENABLED else frozenset()
            body, fetch_error = fetch_article_body(url, render_domains=render_domains)

    try:
        target_dir = os.path.expanduser(inbox_path)
        os.makedirs(target_dir, exist_ok=True)

        today = date.today().isoformat()
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
