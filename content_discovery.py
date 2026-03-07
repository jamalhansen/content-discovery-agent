#!/usr/bin/env python3
import argparse
import logging
import os
import sys
import webbrowser
from datetime import date

from config import (
    DEFAULT_INBOX_PATH,
    DEFAULT_PROVIDER,
    DEFAULT_THRESHOLD,
    DEFAULT_VAULT_PATH,
    FEEDS,
    INTEREST_PROFILE,
    STORE_PATH,
)
from feed_cache import load_cached_feed, save_cached_feed
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
        "--review",
        action="store_true",
        help="Review pending items interactively; write kept items to Obsidian inbox",
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

    feeds = [args.feed] if args.feed else FEEDS
    print(f"Fetching {len(feeds)} feed{'s' if len(feeds) != 1 else ''}...")

    all_new_items: list[FeedItem] = []
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
            new_items = items
        else:
            new_items = [i for i in items if not store.is_seen(i.url, args.store)]

        source = items[0].source if items else feed_url
        print(f"  {source}: {len(items)} item{'s' if len(items) != 1 else ''} ({len(new_items)} new){cache_label}")
        all_new_items.extend(new_items)

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

        if args.verbose:
            print(f"  [{result.score:.2f}] {item.title[:70]}")

        # Store every successfully scored item so it won't be re-scored next run.
        # Items below threshold are immediately dismissed — they're kept for
        # deduplication and as negative few-shot examples, but never surface
        # for interactive review.
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
                path=args.store,
            )
            if result.score < args.threshold:
                store.mark_item(item.url, "dismissed", args.store)

        if result.score >= args.threshold:
            candidates.append(InboxEntry(
                title=item.title,
                url=item.url,
                source=item.source,
                score=result.score,
                tags=result.tags,
                summary=result.summary,
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
        print(f"  Source:  {item['source']}")
        print(f"  Score:   {item['score']:.2f}  |  Tags: {tag_str}")
        print(f"  Summary: {item['summary']}")
        print(f"  URL:     {item['url']}")

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

    if args.review:
        cmd_review(args)
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
