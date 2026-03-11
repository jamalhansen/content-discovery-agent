#!/usr/bin/env python3
import logging
import os
import re
import sys
import webbrowser
from datetime import date
from typing import Optional
from urllib.parse import quote

import typer

from config import (
    BLUESKY_APP_PASSWORD,
    BLUESKY_HANDLE,
    DEFAULT_INBOX_PATH,
    DEFAULT_PROVIDER,
    DEFAULT_THRESHOLD,
    DEFAULT_VAULT_PATH,
    FEEDS,
    INTEREST_EXCLUSIONS,
    INTEREST_PROFILE,
    SOCIAL_BLOCKED_DOMAINS,
    SOCIAL_KEYWORDS,
    SOCIAL_MASTODON_INSTANCES,
    STORE_PATH,
)
from social.article_fetcher import fetch_article_metadata
from social.bluesky import BlueskyReader
from social.mastodon import MastodonReader
from feed_cache import load_cached_feed, save_cached_feed, load_cached_social, save_cached_social, clear_cache
from feed_reader import FeedItem, fetch_feed, filter_new_items
from inbox_writer import InboxEntry, append_to_inbox
from providers import PROVIDERS
from scorer import score_item, ScoredItem
import store

app = typer.Typer(
    name="content-discovery",
    help="Content discovery agent: score RSS feeds and store candidates for review.",
    add_completion=False,
)

# ---------------------------------------------------------------------------
# Shared option factories
# ---------------------------------------------------------------------------

def _provider_opt():
    return typer.Option(
        DEFAULT_PROVIDER, "--provider", "-p",
        help=f"LLM backend: {', '.join(PROVIDERS.keys())} (default: {DEFAULT_PROVIDER})",
    )

def _model_opt():
    return typer.Option(None, "--model", "-m", help="Override the default model for the chosen provider")

def _dry_run_opt():
    return typer.Option(False, "--dry-run", "-n", help="Print candidates to stdout; do not write to DB or inbox")

def _threshold_opt():
    return typer.Option(DEFAULT_THRESHOLD, "--threshold", "-t", help="Minimum relevance score 0.0-1.0")

def _vault_path_opt():
    return typer.Option(DEFAULT_VAULT_PATH or "", "--vault-path", "-v",
                        help="Path to the Obsidian vault root (or set OBSIDIAN_VAULT_PATH env var)")

def _inbox_path_opt():
    return typer.Option(DEFAULT_INBOX_PATH, "--inbox-path",
                        help=f"Inbox path relative to vault root (default: {DEFAULT_INBOX_PATH})")

def _store_opt():
    return typer.Option(STORE_PATH, "--store", help="Path to the SQLite database")

def _verbose_opt():
    return typer.Option(False, "--verbose", help="Print scores for all items, not just those above threshold")

def _limit_opt():
    return typer.Option(None, "--limit", "-l", help="Cap the number of items sent for scoring")

def _no_dedup_opt():
    return typer.Option(False, "--no-dedup", help="Disable seen-item tracking, re-score everything")

def _cached_opt():
    return typer.Option(False, "--cached", help="Use cached feed responses if available")

def _sources_opt():
    return typer.Option("rss", "--sources", "-s",
                        help="Comma-separated list of sources: rss,bluesky,mastodon (default: rss)")

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_threshold(threshold: float) -> None:
    if not (0.0 <= threshold <= 1.0):
        typer.echo(f"Error: --threshold must be between 0.0 and 1.0, got {threshold}", err=True)
        raise typer.Exit(1)

def _validate_vault(vault_path: str) -> None:
    if not vault_path:
        typer.echo(
            "Error: Vault path is required. Set --vault-path or OBSIDIAN_VAULT_PATH env var.",
            err=True,
        )
        raise typer.Exit(1)
    vault = os.path.expanduser(vault_path)
    if not os.path.isdir(vault):
        typer.echo(f"Error: Vault path does not exist: {vault}", err=True)
        raise typer.Exit(1)

def _make_provider(provider_name: str, model: Optional[str]):
    if provider_name not in PROVIDERS:
        typer.echo(f"Error: Unknown provider '{provider_name}'. Valid options: {', '.join(PROVIDERS.keys())}", err=True)
        raise typer.Exit(1)
    try:
        return PROVIDERS[provider_name](model=model)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

def format_candidate(entry: InboxEntry) -> str:
    return "\n" + entry.format_plain()

def _write_to_inbox(vault_path: str, inbox_path: str, entries: list[InboxEntry]) -> None:
    if not entries:
        return
    _validate_vault(vault_path)
    append_to_inbox(vault_path, inbox_path, entries)
    typer.echo(f"\n{len(entries)} item{'s' if len(entries) != 1 else ''} written to inbox.")

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("run", help="Fetch feeds, score items, and store candidates in the DB (default command).")
def cmd_run(
    provider: str = _provider_opt(),
    model: Optional[str] = _model_opt(),
    dry_run: bool = _dry_run_opt(),
    feed: Optional[str] = typer.Option(None, "--feed", "-f", metavar="URL",
                                        help="Process a single feed URL instead of the full configured list"),
    threshold: float = _threshold_opt(),
    vault_path: str = _vault_path_opt(),
    inbox_path: str = _inbox_path_opt(),
    no_dedup: bool = _no_dedup_opt(),
    verbose: bool = _verbose_opt(),
    cached: bool = _cached_opt(),
    limit: Optional[int] = _limit_opt(),
    store_path: str = _store_opt(),
    sources: str = _sources_opt(),
):
    """Fetch feeds, score items, and store candidates in the DB."""
    _validate_threshold(threshold)
    llm_provider = _make_provider(provider, model)

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    store.init_db(store_path)
    examples = store.get_examples(20, store_path, n_dismissed=40)

    source_list = [s.strip() for s in sources.split(",")]
    _run_seen: set[str] = set()
    all_new_items: list[FeedItem] = []

    # --- RSS source ---
    if "rss" in source_list:
        feeds = [feed] if feed else FEEDS
        typer.echo(f"Fetching {len(feeds)} RSS feed{'s' if len(feeds) != 1 else ''}...")
        for feed_url in feeds:
            cached_data = None
            if cached:
                cached_data = load_cached_feed(feed_url)

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
            kw_count = len(SOCIAL_KEYWORDS)
            cached_bluesky = load_cached_social("bluesky", SOCIAL_KEYWORDS) if cached else None
            if cached_bluesky is not None:
                bluesky_items = cached_bluesky
                cache_label = " (cached)"
            else:
                typer.echo(f"Searching Bluesky ({kw_count} keyword{'s' if kw_count != 1 else ''})...")
                bluesky_items = BlueskyReader(
                    handle=BLUESKY_HANDLE,
                    app_password=BLUESKY_APP_PASSWORD,
                    blocked_domains=SOCIAL_BLOCKED_DOMAINS,
                ).fetch_items(SOCIAL_KEYWORDS)
                if cached and bluesky_items:
                    save_cached_social("bluesky", SOCIAL_KEYWORDS, bluesky_items)
                cache_label = ""
            bluesky_new = [
                i for i in bluesky_items
                if i.url not in _run_seen
                and (no_dedup or not store.is_seen(i.url, store_path))
            ]
            _run_seen.update(i.url for i in bluesky_new)
            typer.echo(f"  Bluesky: {len(bluesky_items)} item{'s' if len(bluesky_items) != 1 else ''} fetched ({len(bluesky_new)} new){cache_label}")
            all_new_items.extend(bluesky_new)
        else:
            logging.warning("--sources includes bluesky but no keywords configured in [social].keywords")

    # --- Mastodon source ---
    if "mastodon" in source_list:
        if SOCIAL_KEYWORDS:
            instances_str = ", ".join(SOCIAL_MASTODON_INSTANCES)
            cached_mastodon = load_cached_social("mastodon", SOCIAL_KEYWORDS) if cached else None
            if cached_mastodon is not None:
                mastodon_items = cached_mastodon
                cache_label = " (cached)"
            else:
                typer.echo(f"Searching Mastodon ({instances_str})...")
                mastodon_items = MastodonReader(
                    instances=SOCIAL_MASTODON_INSTANCES,
                    blocked_domains=SOCIAL_BLOCKED_DOMAINS,
                ).fetch_items(SOCIAL_KEYWORDS)
                if cached and mastodon_items:
                    save_cached_social("mastodon", SOCIAL_KEYWORDS, mastodon_items)
                cache_label = ""
            mastodon_new = [
                i for i in mastodon_items
                if i.url not in _run_seen
                and (no_dedup or not store.is_seen(i.url, store_path))
            ]
            _run_seen.update(i.url for i in mastodon_new)
            typer.echo(f"  Mastodon: {len(mastodon_items)} item{'s' if len(mastodon_items) != 1 else ''} fetched ({len(mastodon_new)} new){cache_label}")
            all_new_items.extend(mastodon_new)
        else:
            logging.warning("--sources includes mastodon but no keywords configured in [social].keywords")

    if not all_new_items:
        typer.echo("\nNo new items to score.")
        typer.echo("Done. Processed: 0, Skipped: 0")
        return

    if limit and len(all_new_items) > limit:
        typer.echo(f"\nLimiting to {limit} of {len(all_new_items)} new items.")
        all_new_items = all_new_items[:limit]

    typer.echo(f"\nScoring {len(all_new_items)} item{'s' if len(all_new_items) != 1 else ''}...")

    candidates: list[InboxEntry] = []
    scored_count = 0
    skipped_count = 0
    today = date.today().isoformat()

    for item in all_new_items:
        result = score_item(llm_provider, item.title, item.description, INTEREST_PROFILE, examples, INTEREST_EXCLUSIONS)
        if result is None:
            skipped_count += 1
            logging.warning("Skipped (invalid LLM response): %s", item.title[:70])
            continue

        scored_count += 1
        is_english = result.language == "en"

        if verbose:
            lang_flag = f" [{result.language}]" if not is_english else ""
            typer.echo(f"  [{result.score:.2f}]{lang_flag} {item.title[:70]}")

        if not dry_run:
            store.upsert_item(
                url=item.url,
                title=item.title,
                source=item.source,
                description=item.description or "",
                score=result.score,
                tags=result.tags,
                summary=result.summary,
                fetched_at=today,
                published_at=item.published,
                path=store_path,
            )
            if not is_english or result.score < threshold:
                store.mark_item(item.url, "dismissed", store_path)

        if not is_english:
            logging.info("Dismissed (non-English, %s): %s", result.language, item.title[:70])
            continue

        if result.score >= threshold:
            candidates.append(InboxEntry(
                title=item.title,
                url=item.url,
                source=item.source,
                score=result.score,
                tags=result.tags,
                summary=result.summary,
                published=item.published,
            ))

    if not candidates:
        typer.echo(f"\nNo candidates above threshold ({threshold}).")
    else:
        typer.echo(f"\nCandidates above threshold ({threshold}):")
        for entry in candidates:
            typer.echo(format_candidate(entry))

    if dry_run:
        typer.echo(f"\n{len(candidates)} candidates found. Dry run -- nothing written.")
    else:
        typer.echo(f"\n{len(candidates)} candidates stored. Run --review to triage.")

    typer.echo(f"Done. Processed: {scored_count}, Skipped: {skipped_count}")


@app.command("review", help="Interactively review pending items; write kept items to Obsidian.")
def cmd_review(
    vault_path: str = _vault_path_opt(),
    inbox_path: str = _inbox_path_opt(),
    store_path: str = _store_opt(),
):
    """Interactively review pending items; write kept items to Obsidian."""
    store.init_db(store_path)
    pending = store.get_new_items(store_path)

    if not pending:
        typer.echo("No pending items to review.")
        return

    total = len(pending)
    typer.echo(f"Reviewing {total} pending item{'s' if total != 1 else ''}.")
    typer.echo("  y = keep  |  n = dismiss  |  s = stop  |  o = open in browser\n")

    kept_entries: list[InboxEntry] = []

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
                kept_entries.append(InboxEntry(
                    title=item["title"],
                    url=item["url"],
                    source=item["source"],
                    score=item["score"],
                    tags=item["tags"],
                    summary=item["summary"],
                    fetched=item["fetched_at"],
                    published=item.get("published_at", ""),
                ))
                typer.echo("  Kept.\n")
                break
            elif choice == "n":
                store.mark_item(item["url"], "dismissed", store_path)
                typer.echo("  Dismissed.\n")
                break
            elif choice == "s":
                typer.echo(f"\nStopped. Reviewed {i - 1} of {total} items.")
                _write_to_inbox(vault_path, inbox_path, kept_entries)
                return
            elif choice == "o":
                webbrowser.open(item["url"])
            else:
                typer.echo("  Type y, n, s, or o.")

    _write_to_inbox(vault_path, inbox_path, kept_entries)
    dismissed = total - len(kept_entries)
    typer.echo(f"\nDone. Kept: {len(kept_entries)}, Dismissed: {dismissed}.")


@app.command("report", help="Print a summary report of feed trends, source quality, and scoring history.")
def cmd_report(
    threshold: float = _threshold_opt(),
    store_path: str = _store_opt(),
):
    """Print a summary report: overview, activity, source quality, top tags."""
    store.init_db(store_path)

    W = 60  # report width

    def rule(char="─"):
        typer.echo(char * W)

    def header(title):
        rule("=")
        typer.echo(f"  {title}")
        rule("=")

    def section(title):
        typer.echo("")
        typer.echo(f"  {title}")
        rule()

    header("Content Discovery -- Feed Report")

    summary = store.get_status_summary(store_path)
    total = sum(r["count"] for r in summary)
    typer.echo(f"\n  {'Overview':30s}  {'Items':>6}  {'Avg score':>9}")
    rule()
    status_order = {"new": "Pending", "kept": "Kept", "dismissed": "Dismissed"}
    by_status = {r["status"]: r for r in summary}
    for key, label in status_order.items():
        r = by_status.get(key)
        if r:
            typer.echo(f"  {label:30s}  {r['count']:>6}  {r['avg_score']:>9.2f}")
    typer.echo(f"  {'Total':30s}  {total:>6}")

    section("Activity -- last 7 days")
    daily = store.get_daily_counts(store_path, days=7)
    if not daily:
        typer.echo("  No data yet.")
    else:
        typer.echo(f"  {'Date':12s}  {'Scored':>6}  {'Pending':>8}  {'Kept':>6}  {'Dismissed':>10}")
        rule()
        for d in daily:
            typer.echo(
                f"  {d['date']:12s}  {d['total']:>6}  "
                f"{d['new']:>8}  {d['kept']:>6}  {d['dismissed']:>10}"
            )

    section("Top sources by avg score  (min 5 items)")
    source_stats = store.get_source_stats(store_path, min_items=5)
    top = [s for s in source_stats if s["avg_score"] >= 0.65][:12]
    if not top:
        typer.echo("  Not enough data yet.")
    else:
        typer.echo(f"  {'Source':36s}  {'Items':>5}  {'Avg':>5}")
        rule()
        for s in top:
            name = s["source"][:36]
            typer.echo(f"  {name:36s}  {s['count']:>5}  {s['avg_score']:>5.2f}")

    section("Low-signal sources  (avg score < 0.55, min 5 items)")
    low = [s for s in source_stats if s["avg_score"] < 0.55]
    low_sorted = sorted(low, key=lambda s: s["count"], reverse=True)[:10]
    if not low_sorted:
        typer.echo("  None -- all sources are performing well.")
    else:
        typer.echo(f"  {'Source':36s}  {'Items':>5}  {'Avg':>5}")
        rule()
        for s in low_sorted:
            name = s["source"][:36]
            typer.echo(f"  {name:36s}  {s['count']:>5}  {s['avg_score']:>5.2f}")

    section("Most common tags in kept items")
    tags = store.get_tag_counts(store_path, status="kept", limit=15)
    if not tags:
        typer.echo("  No kept items yet.")
    else:
        cols = 3
        rows_data = [tags[i:i + cols] for i in range(0, len(tags), cols)]
        for row in rows_data:
            parts = [f"#{t['tag']} ({t['count']})" for t in row]
            typer.echo("  " + "   ".join(f"{p:<22}" for p in parts))

    pending_count = by_status.get("new", {}).get("count", 0)
    if pending_count:
        section(f"Score distribution -- {pending_count} pending items")
        dist = store.get_score_distribution(store_path, status="new")
        threshold_bucket = f"{(int(threshold * 10)) / 10:.1f}"
        max_count = max((d["count"] for d in dist), default=1) or 1
        bar_width = 24
        for d in reversed(dist):
            bar_len = round(d["count"] / max_count * bar_width)
            bar = "#" * bar_len
            threshold_marker = "  <- threshold" if d["bucket"] == threshold_bucket else ""
            typer.echo(f"  {d['bucket']}-{float(d['bucket']) + 0.1:.1f}  {bar:<{bar_width}}  {d['count']:>4}{threshold_marker}")

    if pending_count:
        section(f"Pending queue -- top 5 of {pending_count} items")
        pending = store.get_new_items(store_path)[:5]
        for item in pending:
            tag_str = " ".join(f"#{t}" for t in item["tags"][:2])
            score_str = f"[{item['score']:.2f}]"
            typer.echo(f"  {score_str}  {item['title'][:48]}  {tag_str}")

    typer.echo("")
    rule("=")
    typer.echo("")


@app.command("purge-blocked", help="Dismiss all pending items whose URLs match the current domain blocklist.")
def cmd_purge_blocked(
    dry_run: bool = _dry_run_opt(),
    store_path: str = _store_opt(),
):
    """Dismiss all pending items whose URLs match the current domain blocklist."""
    from urllib.parse import urlparse
    from social.article_fetcher import _is_blocked, _DEFAULT_BLOCKED_DOMAINS

    store.init_db(store_path)
    all_blocked = _DEFAULT_BLOCKED_DOMAINS | SOCIAL_BLOCKED_DOMAINS

    items = store.get_new_items(store_path)
    to_dismiss = [
        item for item in items
        if _is_blocked(urlparse(item["url"]).netloc, all_blocked)
    ]

    if not to_dismiss:
        typer.echo("No blocked-domain items found in pending queue.")
        return

    by_domain: dict[str, int] = {}
    for item in to_dismiss:
        netloc = urlparse(item["url"]).netloc
        by_domain[netloc] = by_domain.get(netloc, 0) + 1

    typer.echo(f"Found {len(to_dismiss)} pending item{'s' if len(to_dismiss) != 1 else ''} from blocked domains:\n")
    for domain, count in sorted(by_domain.items(), key=lambda x: -x[1]):
        typer.echo(f"  {domain:<40} {count:>4} item{'s' if count != 1 else ''}")

    if dry_run:
        typer.echo(f"\nDry run -- {len(to_dismiss)} items would be dismissed.")
        return

    dismissed = store.dismiss_items_by_urls([item["url"] for item in to_dismiss], store_path)
    typer.echo(f"\nDismissed {dismissed} item{'s' if dismissed != 1 else ''}.")


@app.command("dismiss-source", help="Dismiss all pending items whose source contains QUERY (case-insensitive).")
def cmd_dismiss_source(
    query: str = typer.Argument(..., help="Case-insensitive source name substring to match"),
    dry_run: bool = _dry_run_opt(),
    store_path: str = _store_opt(),
):
    """Dismiss all pending items whose source name contains the query string."""
    store.init_db(store_path)

    items = [
        item for item in store.get_new_items(store_path)
        if query.lower() in item["source"].lower()
    ]

    if not items:
        typer.echo(f"No pending items found matching source: {query!r}")
        return

    by_source: dict[str, int] = {}
    for item in items:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1

    total = len(items)
    typer.echo(f"Found {total} pending item{'s' if total != 1 else ''} matching {query!r}:\n")
    for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
        typer.echo(f"  {source}  ({count} item{'s' if count != 1 else ''})")

    if dry_run:
        typer.echo(f"\nDry run -- {total} items would be dismissed.")
        return

    dismissed = store.dismiss_items_by_urls([item["url"] for item in items], store_path)
    typer.echo(f"\nDismissed {dismissed} item{'s' if dismissed != 1 else ''}.")


@app.command("check-feeds", help="Validate all configured RSS feeds and report their status.")
def cmd_check_feeds():
    """Fetch each configured RSS feed and report its status."""
    feeds = FEEDS
    typer.echo(f"Checking {len(feeds)} feed{'s' if len(feeds) != 1 else ''}...\n")

    ok: list[tuple[str, int]] = []
    failed: list[tuple[str, str]] = []

    for url in feeds:
        parsed = fetch_feed(url)
        if not parsed:
            failed.append((url, "no items returned / fetch error"))
        else:
            source = parsed[0].source if parsed else url
            ok.append((source, len(parsed)))

    W = 56
    typer.echo(f"  {'Feed':<{W - 8}}  {'Items':>5}")
    typer.echo("─" * W)
    for source, count in ok:
        typer.echo(f"  {source[:W - 10]:<{W - 10}}  {count:>5}")

    if failed:
        typer.echo(f"\n  Failed ({len(failed)}):")
        for url, reason in failed:
            typer.echo(f"    {url}")
            typer.echo(f"    {reason}")

    typer.echo(f"\nOK: {len(ok)}  Failed: {len(failed)}")


@app.command("rescore", help="Re-score all pending items with the current interest profile and examples.")
def cmd_rescore(
    provider: str = _provider_opt(),
    model: Optional[str] = _model_opt(),
    dry_run: bool = _dry_run_opt(),
    threshold: float = _threshold_opt(),
    verbose: bool = _verbose_opt(),
    limit: Optional[int] = _limit_opt(),
    store_path: str = _store_opt(),
):
    """Re-score all pending items using the current interest profile and examples."""
    _validate_threshold(threshold)
    llm_provider = _make_provider(provider, model)

    store.init_db(store_path)
    examples = store.get_examples(20, store_path, n_dismissed=40)
    pending = store.get_new_items(store_path)

    if not pending:
        typer.echo("No pending items to rescore.")
        return

    if limit and len(pending) > limit:
        typer.echo(f"Limiting to {limit} of {len(pending)} pending items.")
        pending = pending[:limit]

    typer.echo(f"Rescoring {len(pending)} item{'s' if len(pending) != 1 else ''}...")

    updated = dismissed = skipped = 0

    for item in pending:
        result = score_item(llm_provider, item["title"], item["description"], INTEREST_PROFILE, examples, INTEREST_EXCLUSIONS)
        if result is None:
            skipped += 1
            logging.warning("Skipped (invalid LLM response): %s", item["title"][:70])
            continue

        is_english = result.language == "en"
        below_threshold = result.score < threshold
        should_dismiss = not is_english or below_threshold

        if verbose:
            old = item["score"]
            delta = f"{result.score - old:+.2f}"
            lang_flag = f" [{result.language}]" if not is_english else ""
            typer.echo(f"  [{old:.2f}->{result.score:.2f} {delta}]{lang_flag} {item['title'][:60]}")

        if not dry_run:
            store.update_item_score(
                url=item["url"],
                score=result.score,
                tags=result.tags,
                summary=result.summary,
                path=store_path,
            )
            if should_dismiss:
                store.mark_item(item["url"], "dismissed", store_path)

        if should_dismiss:
            dismissed += 1
        else:
            updated += 1

    if dry_run:
        typer.echo(f"\nDry run -- {updated} would stay pending, {dismissed} would be dismissed, {skipped} skipped.")
    else:
        typer.echo(f"\nDone. Kept pending: {updated}, Dismissed: {dismissed}, Skipped: {skipped}.")


@app.command("migrate-inbox", help="Reformat existing inbox items to the current format (bullet, Reader link).")
def cmd_migrate_inbox(
    vault_path: str = _vault_path_opt(),
    inbox_path: str = _inbox_path_opt(),
    dry_run: bool = _dry_run_opt(),
):
    """Reformat existing inbox items to the current format."""
    _validate_vault(vault_path)
    full_path = os.path.join(os.path.expanduser(vault_path), inbox_path)

    if not os.path.exists(full_path):
        typer.echo(f"Inbox file not found: {full_path}")
        return

    with open(full_path) as f:
        content = f.read()

    pattern = re.compile(
        r'- \[ \] \[(.+?)\]\((.+?)\)\n'
        r'  - \*\*Source\*\*: (.+?)\n'
        r'  - \*\*Score\*\*: (.+?)\n'
        r'  - \*\*Tags\*\*: (.*?)\n'
        r'  - \*\*Summary\*\*: (.+?)\n'
        r'  - \*\*Fetched\*\*: ([^\n]+)',
        re.MULTILINE,
    )

    matches = pattern.findall(content)
    if not matches:
        typer.echo("No items in old format found -- nothing to migrate.")
        return

    def _replace(m: re.Match) -> str:
        title, url, source, score_val, tags, summary, fetched = m.groups()
        try:
            score_str = f"{float(score_val):.2f}"
        except ValueError:
            score_str = score_val
        reader_url = f"https://readwise.io/save?url={quote(url, safe='')}"
        return (
            f"- [{title}]({url}) . [Read in Reader]({reader_url})\n"
            f"  - **Source**: {source}\n"
            f"  - **Score**: {score_str}\n"
            f"  - **Tags**: {tags}\n"
            f"  - **Summary**: {summary}\n"
            f"  - **Fetched**: {fetched}"
        )

    new_content = pattern.sub(_replace, content)

    if dry_run:
        typer.echo(f"Would migrate {len(matches)} item(s) -- dry run, nothing written.")
        return

    with open(full_path, "w") as f:
        f.write(new_content)
    typer.echo(f"Migrated {len(matches)} item(s) to new format.")


@app.command("save", help="Save a URL directly to the inbox as a kept item.")
def cmd_save(
    url: str = typer.Argument(..., help="URL to fetch, score, and save to the inbox"),
    provider: str = _provider_opt(),
    model: Optional[str] = _model_opt(),
    no_score: bool = typer.Option(False, "--no-score", help="Skip LLM scoring; store with score 1.0"),
    vault_path: str = _vault_path_opt(),
    inbox_path: str = _inbox_path_opt(),
    store_path: str = _store_opt(),
    dry_run: bool = _dry_run_opt(),
):
    """Fetch metadata for a URL, score it, store as kept, and write to the Obsidian inbox.

    Useful for saving links you find outside the normal feed pipeline. The item
    is stored as 'kept' immediately and becomes a positive few-shot example for
    future scoring runs.
    """
    from url_utils import clean_url

    store.init_db(store_path)

    url = clean_url(url)

    if store.is_seen(url, store_path):
        typer.echo(f"Already in database: {url}")
        raise typer.Exit(0)

    typer.echo(f"Fetching {url} ...")
    item = fetch_article_metadata(url, blocked_domains=SOCIAL_BLOCKED_DOMAINS)
    if item is None:
        typer.echo(f"Error: Could not fetch metadata for {url}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Title:  {item.title}")

    if no_score:
        scored: ScoredItem = ScoredItem(score=1.0, tags=[], summary=item.description[:100], language="en")
    else:
        llm_provider = _make_provider(provider, model)
        examples = store.get_examples(20, store_path, n_dismissed=40)
        typer.echo("Scoring ...")
        scored = score_item(
            llm_provider, item.title, item.description,
            INTEREST_PROFILE, examples=examples, exclusions=INTEREST_EXCLUSIONS,
        )
        if scored is None:
            typer.echo("Error: Scoring failed — LLM returned invalid response.", err=True)
            raise typer.Exit(1)

    typer.echo(f"Score:  {scored.score:.2f}  Tags: {scored.tags}")

    if dry_run:
        typer.echo("[dry-run] Would save to inbox. Nothing written.")
        return

    store.upsert_item(
        url=item.url,
        title=item.title,
        source=item.source,
        description=item.description,
        score=scored.score,
        tags=scored.tags,
        summary=scored.summary,
        fetched_at=date.today().isoformat(),
        published_at=item.published,
        path=store_path,
    )
    store.mark_item(item.url, "kept", store_path)

    _validate_vault(vault_path)
    entry = InboxEntry(
        title=item.title,
        url=item.url,
        source=item.source,
        score=scored.score,
        tags=scored.tags,
        summary=scored.summary,
        fetched=date.today().isoformat(),
        published=item.published,
    )
    append_to_inbox(vault_path, inbox_path, [entry])
    typer.echo(f"Saved:  {item.title}")


@app.command("clear-cache", help="Delete all cached feed and social responses.")
def cmd_clear_cache():
    """Delete all cached feed and social responses, then exit."""
    clear_cache()
    typer.echo("Cache cleared.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
