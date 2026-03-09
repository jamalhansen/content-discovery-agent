#!/usr/bin/env python3
import argparse
import logging
import os
import sys
import webbrowser
from datetime import date

from config import (
    BLUESKY_APP_PASSWORD,
    BLUESKY_HANDLE,
    DEFAULT_INBOX_PATH,
    DEFAULT_PROVIDER,
    DEFAULT_THRESHOLD,
    DEFAULT_VAULT_PATH,
    FEEDS,
    INTEREST_PROFILE,
    SOCIAL_BLOCKED_DOMAINS,
    SOCIAL_KEYWORDS,
    SOCIAL_MASTODON_INSTANCES,
    STORE_PATH,
)
from social.bluesky import BlueskyReader
from social.mastodon import MastodonReader
from feed_cache import load_cached_feed, save_cached_feed, load_cached_social, save_cached_social, clear_cache
from feed_reader import FeedItem, fetch_feed, filter_new_items
from inbox_writer import InboxEntry, append_to_inbox
from providers import PROVIDERS
from scorer import score_item
import store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Content discovery agent: score RSS feeds and store candidates for review."
    )
    parser.add_argument(
        "--provider", "-p",
        choices=list(PROVIDERS.keys()),
        default=DEFAULT_PROVIDER,
        help=f"LLM backend (default: {DEFAULT_PROVIDER})",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Override the default model for the chosen provider",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Print candidates to stdout; do not write to DB or inbox",
    )
    parser.add_argument(
        "--feed", "-f",
        default=None,
        metavar="URL",
        help="Process a single feed URL instead of the full configured list",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Minimum relevance score 0.0-1.0 (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--vault-path", "-v",
        default=DEFAULT_VAULT_PATH,
        help="Path to the Obsidian vault root (or set OBSIDIAN_VAULT_PATH env var)",
    )
    parser.add_argument(
        "--inbox-path",
        default=DEFAULT_INBOX_PATH,
        help=f"Inbox path relative to vault root (default: {DEFAULT_INBOX_PATH})",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable seen-item tracking, re-score everything",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print scores for all items, not just those above threshold",
    )
    parser.add_argument(
        "--cached",
        action="store_true",
        help="Use cached feed responses if available; fetch and cache if not",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        metavar="N",
        help="Cap the number of items sent for scoring (applied after deduplication)",
    )
    parser.add_argument(
        "--store",
        default=STORE_PATH,
        metavar="PATH",
        help=f"Path to the SQLite database (default: {STORE_PATH})",
    )
    parser.add_argument(
        "--sources", "-s",
        default="rss",
        metavar="SOURCES",
        help="Comma-separated list of sources to fetch from: rss,bluesky,mastodon (default: rss)",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Delete all cached feed and social responses, then exit",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Review pending items interactively; write kept items to Obsidian inbox",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print a summary report of feed trends, source quality, and scoring history",
    )
    parser.add_argument(
        "--purge-blocked",
        action="store_true",
        help="Dismiss all pending items whose URLs match the current domain blocklist",
    )
    parser.add_argument(
        "--dismiss-source",
        metavar="QUERY",
        default=None,
        help="Dismiss all pending items whose source contains QUERY (case-insensitive)",
    )
    parser.add_argument(
        "--check-feeds",
        action="store_true",
        help="Validate all configured RSS feeds and report their status",
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Re-score all pending items with the current interest profile and examples",
    )
    parser.add_argument(
        "--migrate-inbox",
        action="store_true",
        help="Reformat existing inbox items to the current format (bullet, Reader link)",
    )
    return parser.parse_args()


def validate_run_args(args: argparse.Namespace) -> None:
    if not (0.0 <= args.threshold <= 1.0):
        print(f"Error: --threshold must be between 0.0 and 1.0, got {args.threshold}", file=sys.stderr)
        sys.exit(1)


def validate_vault(args: argparse.Namespace) -> None:
    """Check vault path exists. Used by both run (non-dry) and review."""
    if not args.vault_path:
        print(
            "Error: Vault path is required. Set --vault-path or OBSIDIAN_VAULT_PATH env var.",
            file=sys.stderr,
        )
        sys.exit(1)
    vault = os.path.expanduser(args.vault_path)
    if not os.path.isdir(vault):
        print(f"Error: Vault path does not exist: {vault}", file=sys.stderr)
        sys.exit(1)


def format_candidate(entry: InboxEntry) -> str:
    return "\n" + entry.format_plain()


def cmd_run(args: argparse.Namespace) -> None:
    """Fetch feeds, score items, and store candidates in the DB."""
    validate_run_args(args)

    try:
        provider = PROVIDERS[args.provider](model=args.model)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Initialise DB (idempotent)
    store.init_db(args.store)

    # Pull few-shot examples from review history (empty dicts until user reviews)
    examples = store.get_examples(10, args.store)

    sources = [s.strip() for s in args.sources.split(",")]

    # Tracks URLs seen within this run to deduplicate across sources.
    _run_seen: set[str] = set()
    all_new_items: list[FeedItem] = []

    # --- RSS source ---
    if "rss" in sources:
        feeds = [args.feed] if args.feed else FEEDS
        print(f"Fetching {len(feeds)} RSS feed{'s' if len(feeds) != 1 else ''}...")
        for feed_url in feeds:
            cached = None
            if args.cached:
                cached = load_cached_feed(feed_url)

            if cached is not None:
                items = cached
                cache_label = " (cached)"
            else:
                items = fetch_feed(feed_url)
                if args.cached and items:
                    save_cached_feed(feed_url, items)
                cache_label = ""

            if args.no_dedup:
                new_items = [i for i in items if i.url not in _run_seen]
            else:
                new_items = [
                    i for i in items
                    if i.url not in _run_seen and not store.is_seen(i.url, args.store)
                ]

            _run_seen.update(i.url for i in new_items)
            source = items[0].source if items else feed_url
            print(f"  {source}: {len(items)} item{'s' if len(items) != 1 else ''} ({len(new_items)} new){cache_label}")
            all_new_items.extend(new_items)

    # --- Bluesky source ---
    if "bluesky" in sources:
        if SOCIAL_KEYWORDS:
            kw_count = len(SOCIAL_KEYWORDS)
            cached_bluesky = load_cached_social("bluesky", SOCIAL_KEYWORDS) if args.cached else None
            if cached_bluesky is not None:
                bluesky_items = cached_bluesky
                cache_label = " (cached)"
            else:
                print(f"Searching Bluesky ({kw_count} keyword{'s' if kw_count != 1 else ''})...")
                bluesky_items = BlueskyReader(
                    handle=BLUESKY_HANDLE,
                    app_password=BLUESKY_APP_PASSWORD,
                    blocked_domains=SOCIAL_BLOCKED_DOMAINS,
                ).fetch_items(SOCIAL_KEYWORDS)
                if args.cached and bluesky_items:
                    save_cached_social("bluesky", SOCIAL_KEYWORDS, bluesky_items)
                cache_label = ""
            bluesky_new = [
                i for i in bluesky_items
                if i.url not in _run_seen
                and (args.no_dedup or not store.is_seen(i.url, args.store))
            ]
            _run_seen.update(i.url for i in bluesky_new)
            print(f"  Bluesky: {len(bluesky_items)} item{'s' if len(bluesky_items) != 1 else ''} fetched ({len(bluesky_new)} new){cache_label}")
            all_new_items.extend(bluesky_new)
        else:
            logging.warning("--sources includes bluesky but no keywords configured in [social].keywords")

    # --- Mastodon source ---
    if "mastodon" in sources:
        if SOCIAL_KEYWORDS:
            instances_str = ", ".join(SOCIAL_MASTODON_INSTANCES)
            cached_mastodon = load_cached_social("mastodon", SOCIAL_KEYWORDS) if args.cached else None
            if cached_mastodon is not None:
                mastodon_items = cached_mastodon
                cache_label = " (cached)"
            else:
                print(f"Searching Mastodon ({instances_str})...")
                mastodon_items = MastodonReader(
                    instances=SOCIAL_MASTODON_INSTANCES,
                    blocked_domains=SOCIAL_BLOCKED_DOMAINS,
                ).fetch_items(SOCIAL_KEYWORDS)
                if args.cached and mastodon_items:
                    save_cached_social("mastodon", SOCIAL_KEYWORDS, mastodon_items)
                cache_label = ""
            mastodon_new = [
                i for i in mastodon_items
                if i.url not in _run_seen
                and (args.no_dedup or not store.is_seen(i.url, args.store))
            ]
            _run_seen.update(i.url for i in mastodon_new)
            print(f"  Mastodon: {len(mastodon_items)} item{'s' if len(mastodon_items) != 1 else ''} fetched ({len(mastodon_new)} new){cache_label}")
            all_new_items.extend(mastodon_new)
        else:
            logging.warning("--sources includes mastodon but no keywords configured in [social].keywords")

    if not all_new_items:
        print("\nNo new items to score.")
        print("Done. Processed: 0, Skipped: 0")
        return

    if args.limit and len(all_new_items) > args.limit:
        print(f"\nLimiting to {args.limit} of {len(all_new_items)} new items.")
        all_new_items = all_new_items[: args.limit]

    print(f"\nScoring {len(all_new_items)} item{'s' if len(all_new_items) != 1 else ''}...")

    candidates: list[InboxEntry] = []
    scored_count = 0
    skipped_count = 0
    today = date.today().isoformat()

    for item in all_new_items:
        result = score_item(provider, item.title, item.description, INTEREST_PROFILE, examples)
        if result is None:
            skipped_count += 1
            logging.warning("Skipped (invalid LLM response): %s", item.title[:70])
            continue

        scored_count += 1

        is_english = result.language == "en"

        if args.verbose:
            lang_flag = f" [{result.language}]" if not is_english else ""
            print(f"  [{result.score:.2f}]{lang_flag} {item.title[:70]}")

        # Store every successfully scored item so it won't be re-scored next run.
        # Non-English items and items below threshold are immediately dismissed —
        # kept for deduplication and as negative few-shot examples, but never
        # surface for interactive review.
        if not args.dry_run:
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
                path=args.store,
            )
            if not is_english or result.score < args.threshold:
                store.mark_item(item.url, "dismissed", args.store)

        if not is_english:
            logging.info("Dismissed (non-English, %s): %s", result.language, item.title[:70])
            continue

        if result.score >= args.threshold:
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
        print(f"\nNo candidates above threshold ({args.threshold}).")
    else:
        print(f"\nCandidates above threshold ({args.threshold}):")
        for entry in candidates:
            print(format_candidate(entry))

    if args.dry_run:
        print(f"\n{len(candidates)} candidates found. Dry run -- nothing written.")
    else:
        print(f"\n{len(candidates)} candidates stored. Run --review to triage.")

    print(f"Done. Processed: {scored_count}, Skipped: {skipped_count}")


def cmd_report(args: argparse.Namespace) -> None:
    """Print a summary report: overview, activity, source quality, top tags."""
    store.init_db(args.store)

    W = 60  # report width

    def rule(char="─"):
        print(char * W)

    def header(title):
        rule("═")
        print(f"  {title}")
        rule("═")

    def section(title):
        print()
        print(f"  {title}")
        rule()

    # ── Overview ────────────────────────────────────────────────
    header("Content Discovery — Feed Report")

    summary = store.get_status_summary(args.store)
    total = sum(r["count"] for r in summary)
    print(f"\n  {'Overview':30s}  {'Items':>6}  {'Avg score':>9}")
    rule()
    status_order = {"new": "Pending", "kept": "Kept", "dismissed": "Dismissed"}
    by_status = {r["status"]: r for r in summary}
    for key, label in status_order.items():
        r = by_status.get(key)
        if r:
            print(f"  {label:30s}  {r['count']:>6}  {r['avg_score']:>9.2f}")
    print(f"  {'Total':30s}  {total:>6}")

    # ── Activity ─────────────────────────────────────────────────
    section("Activity — last 7 days")
    daily = store.get_daily_counts(args.store, days=7)
    if not daily:
        print("  No data yet.")
    else:
        print(f"  {'Date':12s}  {'Scored':>6}  {'Pending':>8}  {'Kept':>6}  {'Dismissed':>10}")
        rule()
        for d in daily:
            print(
                f"  {d['date']:12s}  {d['total']:>6}  "
                f"{d['new']:>8}  {d['kept']:>6}  {d['dismissed']:>10}"
            )

    # ── Top sources ───────────────────────────────────────────────
    section("Top sources by avg score  (min 5 items)")
    source_stats = store.get_source_stats(args.store, min_items=5)
    top = [s for s in source_stats if s["avg_score"] >= 0.65][:12]
    if not top:
        print("  Not enough data yet.")
    else:
        print(f"  {'Source':36s}  {'Items':>5}  {'Avg':>5}")
        rule()
        for s in top:
            name = s["source"][:36]
            print(f"  {name:36s}  {s['count']:>5}  {s['avg_score']:>5.2f}")

    # ── Low-signal feeds ──────────────────────────────────────────
    section("Low-signal sources  (avg score < 0.55, min 5 items)")
    low = [s for s in source_stats if s["avg_score"] < 0.55]
    low_sorted = sorted(low, key=lambda s: s["count"], reverse=True)[:10]
    if not low_sorted:
        print("  None — all sources are performing well.")
    else:
        print(f"  {'Source':36s}  {'Items':>5}  {'Avg':>5}")
        rule()
        for s in low_sorted:
            name = s["source"][:36]
            print(f"  {name:36s}  {s['count']:>5}  {s['avg_score']:>5.2f}")

    # ── Top tags in kept items ────────────────────────────────────
    section("Most common tags in kept items")
    tags = store.get_tag_counts(args.store, status="kept", limit=15)
    if not tags:
        print("  No kept items yet.")
    else:
        cols = 3
        rows_data = [tags[i:i + cols] for i in range(0, len(tags), cols)]
        for row in rows_data:
            parts = [f"#{t['tag']} ({t['count']})" for t in row]
            print("  " + "   ".join(f"{p:<22}" for p in parts))

    # ── Score distribution (pending) ──────────────────────────────
    pending_count = by_status.get("new", {}).get("count", 0)
    if pending_count:
        section(f"Score distribution — {pending_count} pending items")
        dist = store.get_score_distribution(args.store, status="new")
        threshold_bucket = f"{(int(args.threshold * 10)) / 10:.1f}"
        max_count = max((d["count"] for d in dist), default=1) or 1
        bar_width = 24
        for d in reversed(dist):
            bar_len = round(d["count"] / max_count * bar_width)
            bar = "█" * bar_len
            threshold_marker = "  ← threshold" if d["bucket"] == threshold_bucket else ""
            print(f"  {d['bucket']}–{float(d['bucket']) + 0.1:.1f}  {bar:<{bar_width}}  {d['count']:>4}{threshold_marker}")

    # ── Pending queue peek ────────────────────────────────────────
    if pending_count:
        section(f"Pending queue — top 5 of {pending_count} items")
        pending = store.get_new_items(args.store)[:5]
        for item in pending:
            tag_str = " ".join(f"#{t}" for t in item["tags"][:2])
            score_str = f"[{item['score']:.2f}]"
            print(f"  {score_str}  {item['title'][:48]}  {tag_str}")

    print()
    rule("═")
    print()


def cmd_purge_blocked(args: argparse.Namespace) -> None:
    """Dismiss all pending items whose URLs match the current domain blocklist."""
    from urllib.parse import urlparse
    from social.article_fetcher import _is_blocked, _DEFAULT_BLOCKED_DOMAINS

    store.init_db(args.store)
    all_blocked = _DEFAULT_BLOCKED_DOMAINS | SOCIAL_BLOCKED_DOMAINS

    items = store.get_new_items(args.store)
    to_dismiss = [
        item for item in items
        if _is_blocked(urlparse(item["url"]).netloc, all_blocked)
    ]

    if not to_dismiss:
        print("No blocked-domain items found in pending queue.")
        return

    # Group by domain for a readable summary
    by_domain: dict[str, int] = {}
    for item in to_dismiss:
        netloc = urlparse(item["url"]).netloc
        by_domain[netloc] = by_domain.get(netloc, 0) + 1

    print(f"Found {len(to_dismiss)} pending item{'s' if len(to_dismiss) != 1 else ''} from blocked domains:\n")
    for domain, count in sorted(by_domain.items(), key=lambda x: -x[1]):
        print(f"  {domain:<40} {count:>4} item{'s' if count != 1 else ''}")

    if args.dry_run:
        print(f"\nDry run — {len(to_dismiss)} items would be dismissed.")
        return

    dismissed = store.dismiss_items_by_urls([item["url"] for item in to_dismiss], args.store)
    print(f"\nDismissed {dismissed} item{'s' if dismissed != 1 else ''}.")


def cmd_dismiss_source(args: argparse.Namespace) -> None:
    """Dismiss all pending items whose source name contains the query string."""
    query = args.dismiss_source
    store.init_db(args.store)

    items = [
        item for item in store.get_new_items(args.store)
        if query.lower() in item["source"].lower()
    ]

    if not items:
        print(f"No pending items found matching source: {query!r}")
        return

    # Group by exact source name for display
    by_source: dict[str, int] = {}
    for item in items:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1

    total = len(items)
    print(f"Found {total} pending item{'s' if total != 1 else ''} matching {query!r}:\n")
    for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {source}  ({count} item{'s' if count != 1 else ''})")

    if args.dry_run:
        print(f"\nDry run — {total} items would be dismissed.")
        return

    dismissed = store.dismiss_items_by_urls([item["url"] for item in items], args.store)
    print(f"\nDismissed {dismissed} item{'s' if dismissed != 1 else ''}.")


def cmd_check_feeds(args: argparse.Namespace) -> None:
    """Fetch each configured RSS feed and report its status."""
    feeds = FEEDS
    print(f"Checking {len(feeds)} feed{'s' if len(feeds) != 1 else ''}...\n")

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
    print(f"  {'Feed':<{W - 8}}  {'Items':>5}")
    print("─" * W)
    for source, count in ok:
        print(f"  {source[:W - 10]:<{W - 10}}  {count:>5}")

    if failed:
        print(f"\n  ✗ Failed ({len(failed)}):")
        for url, reason in failed:
            print(f"    {url}")
            print(f"    {reason}")

    print(f"\nOK: {len(ok)}  Failed: {len(failed)}")


def cmd_rescore(args: argparse.Namespace) -> None:
    """Re-score all pending items using the current interest profile and examples."""
    validate_run_args(args)

    try:
        provider = PROVIDERS[args.provider](model=args.model)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    store.init_db(args.store)
    examples = store.get_examples(10, args.store)
    pending = store.get_new_items(args.store)

    if not pending:
        print("No pending items to rescore.")
        return

    if args.limit and len(pending) > args.limit:
        print(f"Limiting to {args.limit} of {len(pending)} pending items.")
        pending = pending[: args.limit]

    print(f"Rescoring {len(pending)} item{'s' if len(pending) != 1 else ''}...")

    updated = dismissed = skipped = 0

    for item in pending:
        result = score_item(provider, item["title"], item["description"], INTEREST_PROFILE, examples)
        if result is None:
            skipped += 1
            logging.warning("Skipped (invalid LLM response): %s", item["title"][:70])
            continue

        is_english = result.language == "en"
        below_threshold = result.score < args.threshold
        should_dismiss = not is_english or below_threshold

        if args.verbose:
            old = item["score"]
            delta = f"{result.score - old:+.2f}"
            lang_flag = f" [{result.language}]" if not is_english else ""
            print(f"  [{old:.2f}→{result.score:.2f} {delta}]{lang_flag} {item['title'][:60]}")

        if not args.dry_run:
            store.update_item_score(
                url=item["url"],
                score=result.score,
                tags=result.tags,
                summary=result.summary,
                path=args.store,
            )
            if should_dismiss:
                store.mark_item(item["url"], "dismissed", args.store)

        if should_dismiss:
            dismissed += 1
        else:
            updated += 1

    if args.dry_run:
        print(f"\nDry run — {updated} would stay pending, {dismissed} would be dismissed, {skipped} skipped.")
    else:
        print(f"\nDone. Kept pending: {updated}, Dismissed: {dismissed}, Skipped: {skipped}.")


def cmd_migrate_inbox(args: argparse.Namespace) -> None:
    """Reformat existing inbox items to the current format.

    Converts old checkbox items (- [ ] [...]) to regular bullets with a
    Readwise Reader link. Does not add Published lines (date unavailable
    for already-written items). Supports --dry-run.
    """
    import re
    validate_vault(args)
    full_path = os.path.join(os.path.expanduser(args.vault_path), args.inbox_path)

    if not os.path.exists(full_path):
        print(f"Inbox file not found: {full_path}")
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
        print("No items in old format found — nothing to migrate.")
        return

    reader_base = "https://read.readwise.io/new/"

    def _replace(m: re.Match) -> str:
        title, url, source, score, tags, summary, fetched = m.groups()
        try:
            score_str = f"{float(score):.2f}"
        except ValueError:
            score_str = score
        reader_url = f"{reader_base}{url}"
        return (
            f"- [{title}]({url}) · [Read in Reader]({reader_url})\n"
            f"  - **Source**: {source}\n"
            f"  - **Score**: {score_str}\n"
            f"  - **Tags**: {tags}\n"
            f"  - **Summary**: {summary}\n"
            f"  - **Fetched**: {fetched}"
        )

    new_content = pattern.sub(_replace, content)

    if args.dry_run:
        print(f"Would migrate {len(matches)} item(s) — dry run, nothing written.")
        return

    with open(full_path, "w") as f:
        f.write(new_content)
    print(f"Migrated {len(matches)} item(s) to new format.")


def cmd_review(args: argparse.Namespace) -> None:
    """Interactively review pending items; write kept items to Obsidian."""
    store.init_db(args.store)
    pending = store.get_new_items(args.store)

    if not pending:
        print("No pending items to review.")
        return

    total = len(pending)
    print(f"Reviewing {total} pending item{'s' if total != 1 else ''}.")
    print("  y = keep  |  n = dismiss  |  s = stop  |  o = open in browser\n")

    kept_entries: list[InboxEntry] = []

    for i, item in enumerate(pending, start=1):
        tag_str = " ".join(f"#{t}" for t in item["tags"]) if item["tags"] else "(none)"
        print(f"[{i}/{total}]  {item['title']}")
        print(f"  {item['summary']}")
        print(f"  Source: {item['source']}  |  Score: {item['score']:.2f}  |  Tags: {tag_str}")
        print(f"  URL:    {item['url']}")

        while True:
            try:
                choice = input("  > ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "s"

            if choice == "y":
                store.mark_item(item["url"], "kept", args.store)
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
                print("  ✓ Kept.\n")
                break
            elif choice == "n":
                store.mark_item(item["url"], "dismissed", args.store)
                print("  ✗ Dismissed.\n")
                break
            elif choice == "s":
                print(f"\nStopped. Reviewed {i - 1} of {total} items.")
                _write_to_inbox(args, kept_entries)
                return
            elif choice == "o":
                webbrowser.open(item["url"])
            else:
                print("  Type y, n, s, or o.")

    _write_to_inbox(args, kept_entries)
    dismissed = total - len(kept_entries)
    print(f"\nDone. Kept: {len(kept_entries)}, Dismissed: {dismissed}.")


def _write_to_inbox(args: argparse.Namespace, entries: list[InboxEntry]) -> None:
    """Write kept entries to the Obsidian inbox. No-op if nothing to write."""
    if not entries:
        return
    validate_vault(args)
    append_to_inbox(args.vault_path, args.inbox_path, entries)
    print(f"\n{len(entries)} item{'s' if len(entries) != 1 else ''} written to inbox.")


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    if args.clear_cache:
        clear_cache()
        print("Cache cleared.")
        return

    if args.migrate_inbox:
        cmd_migrate_inbox(args)
    elif args.purge_blocked:
        cmd_purge_blocked(args)
    elif args.dismiss_source:
        cmd_dismiss_source(args)
    elif args.check_feeds:
        cmd_check_feeds(args)
    elif args.rescore:
        cmd_rescore(args)
    elif args.report:
        cmd_report(args)
    elif args.review:
        cmd_review(args)
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
