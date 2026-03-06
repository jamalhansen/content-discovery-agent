#!/usr/bin/env python3
import argparse
import logging
import os
import sys

from config import (
    DEFAULT_INBOX_PATH,
    DEFAULT_PROVIDER,
    DEFAULT_THRESHOLD,
    DEFAULT_VAULT_PATH,
    FEEDS,
    STATE_FILE_PATH,
    TOPIC_TAGS,
)
from feed_reader import FeedItem, fetch_feed, filter_new_items
from inbox_writer import InboxEntry, append_to_inbox
from providers import PROVIDERS
from scorer import score_item
from state import load_state, save_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Content discovery agent: score RSS feeds and append candidates to Obsidian inbox."
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
        help="Print candidates to stdout instead of writing to inbox",
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
        default=os.environ.get("OBSIDIAN_VAULT_PATH", DEFAULT_VAULT_PATH),
        help="Path to the Obsidian vault root",
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
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not (0.0 <= args.threshold <= 1.0):
        print(f"Error: --threshold must be between 0.0 and 1.0, got {args.threshold}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run:
        vault = os.path.expanduser(args.vault_path)
        if not os.path.isdir(vault):
            print(f"Error: Vault path does not exist: {vault}", file=sys.stderr)
            sys.exit(1)


def format_candidate(entry: InboxEntry) -> str:
    tag_str = " ".join(f"#{t}" for t in entry.tags) if entry.tags else ""
    return (
        f"\n- [ ] [{entry.title}]({entry.url})\n"
        f"  - Source: {entry.source}\n"
        f"  - Score: {entry.score:.2f}\n"
        f"  - Tags: {tag_str}\n"
        f"  - Summary: {entry.summary}\n"
        f"  - Fetched: {entry.fetched}"
    )


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    validate_args(args)

    # Instantiate provider (fails fast if API key missing / Ollama unreachable)
    try:
        provider = PROVIDERS[args.provider](model=args.model)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Load deduplication state
    seen: set[str] = set()
    if not args.no_dedup:
        seen = load_state(STATE_FILE_PATH)

    feeds = [args.feed] if args.feed else FEEDS
    print(f"Fetching {len(feeds)} feed{'s' if len(feeds) != 1 else ''}...")

    all_new_items: list[FeedItem] = []
    for feed_url in feeds:
        items = fetch_feed(feed_url)
        new_items = filter_new_items(items, seen) if not args.no_dedup else items
        source = items[0].source if items else feed_url
        print(f"  {source}: {len(items)} item{'s' if len(items) != 1 else ''} ({len(new_items)} new)")
        all_new_items.extend(new_items)

    if not all_new_items:
        print("\nNo new items to score.")
        print("Done. Processed: 0, Skipped: 0")
        return

    print(f"\nScoring {len(all_new_items)} item{'s' if len(all_new_items) != 1 else ''}...")

    candidates: list[InboxEntry] = []
    scored_count = 0
    skipped_count = 0

    for item in all_new_items:
        result = score_item(provider, item.title, item.description, TOPIC_TAGS)
        if result is None:
            skipped_count += 1
            continue

        scored_count += 1

        if args.verbose:
            print(f"  [{result.score:.2f}] {item.title[:70]}")

        if result.score >= args.threshold:
            candidates.append(InboxEntry(
                title=item.title,
                url=item.url,
                source=item.source,
                score=result.score,
                tags=result.tags,
                summary=result.summary,
            ))

        # Mark as seen regardless of threshold
        seen.add(item.url)

    if not candidates:
        print(f"\nNo candidates above threshold ({args.threshold}).")
    else:
        print(f"\nCandidates above threshold ({args.threshold}):")
        for entry in candidates:
            print(format_candidate(entry))

    if args.dry_run:
        print(f"\n{len(candidates)} candidates found. Dry run -- nothing written.")
    else:
        append_to_inbox(args.vault_path, args.inbox_path, candidates)
        if not args.no_dedup:
            save_state(STATE_FILE_PATH, seen)
        print(f"\n{len(candidates)} candidates written to inbox.")

    print(f"Done. Processed: {scored_count}, Skipped: {skipped_count}")


if __name__ == "__main__":
    main()
