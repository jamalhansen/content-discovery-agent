import typer
import webbrowser
from datetime import date
from typing import Optional, List, Set
from local_first_common.tracking import register_tool, timed_run
from local_first_common.article_fetcher import fetch_article_metadata
from .config import (
    BLUESKY_APP_PASSWORD,
    BLUESKY_HANDLE,
    FEEDS,
    INTEREST_EXCLUSIONS,
    INTEREST_PROFILE,
    READWISE_ROUTING,
    READWISE_TOKEN,
    SOCIAL_BLOCKED_DOMAINS,
    SOCIAL_KEYWORDS,
    SOCIAL_MASTODON_INSTANCES,
)
from .social.bluesky import BlueskyReader
from .social.mastodon import MastodonReader
from .feed_cache import load_cached_feed, save_cached_feed, load_cached_social, save_cached_social
from .feed_reader import FeedItem, fetch_feed
from .scorer import ContentDiscoveryScorer, score_item, ScoredItem
from .readwise import save_to_readwise
from . import store

_TOOL = register_tool("content-discovery-agent")


def run_discovery(
    llm_provider,
    sources: str,
    feed: Optional[str],
    threshold: float,
    no_dedup: bool,
    verbose: bool,
    cached: bool,
    limit: Optional[int],
    store_path: str,
    dry_run: bool = False,
):
    """Business logic for the 'run' command."""
    store.init_db(store_path)
    examples = store.get_examples(20, store_path, n_dismissed=40)

    source_list = [s.strip() for s in sources.split(",")]
    _run_seen: Set[str] = set()
    all_new_items: List[FeedItem] = []

    # --- RSS source ---
    if "rss" in source_list:
        feeds = [feed] if feed else FEEDS
        typer.echo(f"Fetching {len(feeds)} RSS feed{'s' if len(feeds) != 1 else ''}...")
        for feed_url in feeds:
            cached_data = load_cached_feed(feed_url) if cached else None
            if cached_data is not None:
                items = cached_data
                cache_label = " (cached)"
            else:
                items = fetch_feed(feed_url)
                if cached and items:
                    save_cached_feed(feed_url, items)
                cache_label = ""

            if no_dedup:
                new_items = [i for i in items if i.url not in _run_seen]
            else:
                new_items = [
                    i for i in items
                    if i.url not in _run_seen and not store.is_seen(i.url, store_path)
                ]

            _run_seen.update(i.url for i in new_items)
            source = items[0].source if items else feed_url
            typer.echo(f"  {source}: {len(items)} item{'s' if len(items) != 1 else ''} ({len(new_items)} new){cache_label}")
            all_new_items.extend(new_items)

    # --- Bluesky source ---
    if "bluesky" in source_list:
        if SOCIAL_KEYWORDS:
            cached_bluesky = load_cached_social("bluesky", SOCIAL_KEYWORDS) if cached else None
            if cached_bluesky is not None:
                bluesky_items = cached_bluesky
                cache_label = " (cached)"
            else:
                typer.echo(f"Searching Bluesky ({len(SOCIAL_KEYWORDS)} keywords)...")
                bluesky_items = BlueskyReader(
                    handle=BLUESKY_HANDLE,
                    app_password=BLUESKY_APP_PASSWORD,
                    blocked_domains=SOCIAL_BLOCKED_DOMAINS,
                    tool=_TOOL,
                ).fetch_items(SOCIAL_KEYWORDS)
                if cached and bluesky_items:
                    save_cached_social("bluesky", SOCIAL_KEYWORDS, bluesky_items)
                cache_label = ""
            bluesky_new = [
                i for i in bluesky_items
                if i.url not in _run_seen and (no_dedup or not store.is_seen(i.url, store_path))
            ]
            _run_seen.update(i.url for i in bluesky_new)
            typer.echo(f"  Bluesky: {len(bluesky_items)} items fetched ({len(bluesky_new)} new){cache_label}")
            all_new_items.extend(bluesky_new)

    # --- Mastodon source ---
    if "mastodon" in source_list:
        if SOCIAL_KEYWORDS:
            cached_mastodon = load_cached_social("mastodon", SOCIAL_KEYWORDS) if cached else None
            if cached_mastodon is not None:
                mastodon_items = cached_mastodon
                cache_label = " (cached)"
            else:
                typer.echo(f"Searching Mastodon ({', '.join(SOCIAL_MASTODON_INSTANCES)})...")
                mastodon_items = MastodonReader(
                    instances=SOCIAL_MASTODON_INSTANCES,
                    blocked_domains=SOCIAL_BLOCKED_DOMAINS,
                    tool=_TOOL,
                ).fetch_items(SOCIAL_KEYWORDS)
                if cached and mastodon_items:
                    save_cached_social("mastodon", SOCIAL_KEYWORDS, mastodon_items)
                cache_label = ""
            mastodon_new = [
                i for i in mastodon_items
                if i.url not in _run_seen and (no_dedup or not store.is_seen(i.url, store_path))
            ]
            _run_seen.update(i.url for i in mastodon_new)
            typer.echo(f"  Mastodon: {len(mastodon_items)} items fetched ({len(mastodon_new)} new){cache_label}")
            all_new_items.extend(mastodon_new)

    if not all_new_items:
        typer.echo("\nNo new items to score.")
        return [], 0, 0

    if limit and len(all_new_items) > limit:
        typer.echo(f"\nLimiting to {limit} of {len(all_new_items)} new items.")
        all_new_items = all_new_items[:limit]

    typer.echo(f"\nScoring {len(all_new_items)} items...")

    candidates = []
    scored_count = 0
    skipped_count = 0
    today = date.today().isoformat()
    scorer = ContentDiscoveryScorer()

    with timed_run("content-discovery-agent", llm_provider.model) as _run:
        for item in all_new_items:
            result = score_item(llm_provider, item.title, item.description, INTEREST_PROFILE, examples, INTEREST_EXCLUSIONS, scorer=scorer)
            if result is None:
                skipped_count += 1
                continue

            scored_count += 1
            is_english = result.language == "en"

            if verbose:
                lang_flag = f" [{result.language}]" if not is_english else ""
                typer.echo(f"  [{result.score:.2f}]{lang_flag} {item.title[:70]}")

            store.upsert_item(
                url=item.url, title=item.title, source=item.source,
                description=item.description or "", score=result.score,
                tags=result.tags, summary=result.summary,
                fetched_at=today, published_at=item.published, path=store_path,
            )
            if not is_english or result.score < threshold:
                store.mark_item(item.url, "dismissed", store_path)

            if is_english and result.score >= threshold:
                candidates.append({
                    "title": item.title, "url": item.url, "score": result.score,
                    "tags": result.tags, "summary": result.summary,
                })
                if READWISE_ROUTING and READWISE_TOKEN:
                    if dry_run:
                        typer.echo(f"  [dry-run] Would route to Readwise: {item.title[:60]}")
                    else:
                        save_to_readwise(
                            READWISE_TOKEN,
                            item.url,
                            title=item.title,
                            summary=result.summary,
                            tags=result.tags,
                            published_date=item.published or "",
                        )

        _run.item_count = scored_count
        _run.input_tokens = getattr(llm_provider, "input_tokens", None) or None
        _run.output_tokens = getattr(llm_provider, "output_tokens", None) or None
        _run.xml_fallbacks = scorer.xml_fallback_count or None
        _run.parse_errors = scorer.parse_error_count or None

    return candidates, scored_count, skipped_count

def run_review(store_path: str, readwise_token: str):
    """Interactively review pending items."""
    pending = store.get_new_items(store_path)

    if not pending:
        typer.echo("No pending items to review.")
        return 0, 0

    total = len(pending)
    typer.echo(f"Reviewing {total} pending item{'s' if total != 1 else ''}.")
    typer.echo("  y = keep  |  n = dismiss  |  s = stop  |  o = open in browser\n")

    kept = 0
    dismissed = 0

    for i, item in enumerate(pending, start=1):
        tag_str = " ".join(f"#{t}" for t in item["tags"]) if item["tags"] else "(none)"
        typer.echo(f"[{i}/{total}]  {item['title']}")
        typer.echo(f"  {item['summary']}")
        typer.echo(f"  Source: {item['source']}  |  Score: {item['score']:.2f}  |  Tags: {tag_str}")
        typer.echo(f"  URL:    {item['url']}")

        while True:
            try:
                choice = input("  > ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "s"

            if choice == "y":
                store.mark_item(item["url"], "kept", store_path)
                ok = save_to_readwise(
                    readwise_token,
                    item["url"],
                    title=item["title"],
                    summary=item["summary"],
                    tags=item["tags"],
                    published_date=item.get("published_at", ""),
                )
                kept += 1
                typer.echo("  Sent to Readwise Reader.\n" if ok else "  Kept (Readwise save failed \u2014 check token).\n")
                break
            elif choice == "n":
                store.mark_item(item["url"], "dismissed", store_path)
                dismissed += 1
                typer.echo("  Dismissed.\n")
                break
            elif choice == "s":
                return kept, dismissed
            elif choice == "o":
                webbrowser.open(item["url"])
            else:
                typer.echo("  Type y, n, s, or o.")

    return kept, dismissed

def run_save(
    url: str,
    provider,
    no_score: bool,
    readwise_token: str,
    store_path: str,
    dry_run: bool,
) -> bool:
    """Core logic for the 'save' command."""
    from local_first_common.url import clean_url
    url = clean_url(url)

    store.init_db(store_path)

    if store.is_seen(url, store_path):
        typer.echo(f"Already in database: {url}")
        return True

    typer.echo(f"Fetching {url} ...")
    item = fetch_article_metadata(url, blocked_domains=SOCIAL_BLOCKED_DOMAINS, tool=_TOOL)
    if item is None:
        typer.echo(f"Error: Could not fetch metadata for {url}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Title:  {item.title}")

    if no_score:
        scored = ScoredItem(score=1.0, tags=[], summary=item.description[:100], language="en")
    else:
        examples = store.get_examples(20, store_path, n_dismissed=40)
        typer.echo("Scoring ...")
        scored = score_item(
            provider, item.title, item.description,
            INTEREST_PROFILE, examples=examples, exclusions=INTEREST_EXCLUSIONS,
        )
        if scored is None:
            typer.echo("Error: Scoring failed \u2014 LLM returned invalid response.", err=True)
            raise typer.Exit(1)

    typer.echo(f"Score:  {scored.score:.2f}  Tags: {scored.tags}")

    if dry_run:
        typer.echo("[dry-run] Would save to Readwise Reader. Nothing written.")
        return True

    store.upsert_item(
        url=item.url, title=item.title, source=item.source,
        description=item.description, score=scored.score,
        tags=scored.tags, summary=scored.summary,
        fetched_at=date.today().isoformat(),
        published_at=item.published,
        path=store_path,
    )
    store.mark_item(item.url, "kept", store_path)

    ok = save_to_readwise(
        readwise_token, item.url,
        title=item.title,
        summary=scored.summary,
        tags=scored.tags,
        published_date=item.published,
    )
    typer.echo(f"Saved:  {item.title}")
    typer.echo("  Sent to Readwise Reader." if ok else "  Kept in DB (Readwise save failed \u2014 check token).")
    return ok
