#!/usr/bin/env python3
import logging
from typing import Optional

import typer

from .config import (
    DEFAULT_BACKUP_DIR,
    READWISE_TOKEN,
)
from .options import (
    provider_opt, model_opt, dry_run_opt, no_llm_opt, threshold_opt, store_opt,
    verbose_opt, limit_opt, no_dedup_opt, cached_opt, sources_opt,
    validate_threshold, validate_readwise_token, make_provider
)
from .orchestrator import run_discovery, run_review, run_save
from .db_commands import run_report, run_purge_blocked, run_dismiss_source, run_backup, run_restore
from .scorer import score_item
from . import store

app = typer.Typer(
    name="content-discovery",
    help="Content discovery agent: score RSS feeds and store candidates for review.",
    add_completion=False,
)

@app.command("run", help="Fetch feeds, score items, and store candidates in the DB (default command).")
def cmd_run(
    provider: str = provider_opt(),
    model: Optional[str] = model_opt(),
    dry_run: bool = dry_run_opt(),
    no_llm: bool = no_llm_opt(),
    feed: Optional[str] = typer.Option(None, "--feed", "-f", metavar="URL",
                                        help="Process a single feed URL instead of the full configured list"),
    threshold: float = threshold_opt(),
    no_dedup: bool = no_dedup_opt(),
    verbose: bool = verbose_opt(),
    cached: bool = cached_opt(),
    limit: Optional[int] = limit_opt(),
    store_path: str = store_opt(),
    sources: str = sources_opt(),
):
    """Fetch feeds, score items, and store candidates in the DB."""
    if no_llm:
        typer.echo("\n[no-llm] Skip inference mode. Previews would be shown here.")
        return
    validate_threshold(threshold)
    llm_provider = make_provider(provider, model, no_llm=no_llm)

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    candidates, scored_count, skipped_count = run_discovery(
        llm_provider, sources, feed, threshold, no_dedup, verbose, cached, limit, store_path
    )

    if candidates:
        typer.echo(f"\nCandidates above threshold ({threshold}):")
        for c in candidates:
            tag_str = " ".join(f"#{t}" for t in c["tags"]) if c["tags"] else ""
            typer.echo(f"\n  [{c['score']:.2f}] {c['title']}")
            typer.echo(f"  {c['summary']}")
            typer.echo(f"  {c['url']}  {tag_str}")

    if dry_run:
        typer.echo(f"\n{len(candidates)} candidates found. Dry run -- nothing written.")
    else:
        typer.echo(f"\n{len(candidates)} candidates stored. Run review to triage.")

    typer.echo(f"Done. Processed: {scored_count}, Skipped: {skipped_count}")


@app.command("review", help="Interactively review pending items; send kept items to Readwise Reader.")
def cmd_review(
    store_path: str = store_opt(),
    readwise_token: str = typer.Option(
        READWISE_TOKEN, "--readwise-token",
        envvar="READWISE_TOKEN",
        help="Readwise access token (or set READWISE_TOKEN env var)",
    ),
):
    """Interactively review pending items; send kept items to Readwise Reader."""
    validate_readwise_token(readwise_token)
    store.init_db(store_path)
    kept, dismissed = run_review(store_path, readwise_token)
    typer.echo(f"\nDone. Kept: {kept}, Dismissed: {dismissed}.")


@app.command("report", help="Print a summary report of feed trends, source quality, and scoring history.")
def cmd_report(
    store_path: str = store_opt(),
    days: int = typer.Option(30, "--days", "-d", help="Number of days to include in the report"),
):
    """Print a summary report of feed trends and scoring history."""
    run_report(store_path, days)


@app.command("purge-blocked", help="Dismiss all pending items whose URLs match the current domain blocklist.")
def cmd_purge_blocked(store_path: str = store_opt()):
    """Dismiss pending items from blocked domains."""
    run_purge_blocked(store_path)


@app.command("dismiss-source", help="Dismiss all pending items whose source contains QUERY (case-insensitive).")
def cmd_dismiss_source(
    query: str = typer.Argument(..., help="Source name fragment to match"),
    store_path: str = store_opt()
):
    """Dismiss pending items from a specific source."""
    run_dismiss_source(query, store_path)


@app.command("check-feeds", help="Validate all configured RSS feeds and report their status.")
def cmd_check_feeds():
    """Validate all configured RSS feeds."""
    from .feed_reader import fetch_feed
    from .config import FEEDS
    typer.echo(f"Checking {len(FEEDS)} feeds...\n")
    for url in FEEDS:
        try:
            items = fetch_feed(url)
            if items:
                typer.echo(f"  [OK] {items[0].source[:40]:40} | {len(items):3} items | {url}")
            else:
                typer.echo(f"  [EMPTY] {url}")
        except Exception as e:
            typer.echo(f"  [FAIL] {url} | Error: {e}")


@app.command("rescore", help="Re-score all pending items with the current interest profile and examples.")
def cmd_rescore(
    provider: str = provider_opt(),
    model: Optional[str] = model_opt(),
    no_llm: bool = no_llm_opt(),
    store_path: str = store_opt(),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Cap items"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose."),
):
    """Re-score all pending items."""
    if no_llm:
        typer.echo("\n[no-llm] Skip inference mode. Rescoring skipped.")
        return
    from .config import INTEREST_PROFILE, INTEREST_EXCLUSIONS
    llm_provider = make_provider(provider, model, no_llm=no_llm)
    store.init_db(store_path)
    pending = store.get_new_items(store_path)
    if limit:
        pending = pending[:limit]

    if not pending:
        typer.echo("No pending items to re-score.")
        return

    typer.echo(f"Re-scoring {len(pending)} items...\n")
    examples = store.get_examples(20, store_path, n_dismissed=40)

    for item in pending:
        result = score_item(llm_provider, item['title'], item['description'], INTEREST_PROFILE, examples, INTEREST_EXCLUSIONS)
        if result:
            if verbose:
                typer.echo(f"  {item['score']:.2f} -> {result.score:.2f} | {item['title'][:70]}")
            store.upsert_item(
                url=item['url'], title=item['title'], source=item['source'],
                description=item['description'], score=result.score,
                tags=result.tags, summary=result.summary,
                fetched_at=item['fetched_at'], published_at=item['published_at'],
                path=store_path
            )
    typer.echo("\nRe-scoring complete.")


@app.command("save", help="Save a URL directly to Readwise Reader as a kept item.")
def cmd_save(
    url: str = typer.Argument(..., help="URL to fetch, score, and save"),
    provider: str = provider_opt(),
    model: Optional[str] = model_opt(),
    no_llm: bool = no_llm_opt(),
    no_score: bool = typer.Option(False, "--no-score", help="Skip LLM scoring; store with score 1.0"),
    readwise_token: str = typer.Option(READWISE_TOKEN, help="Readwise token"),
    store_path: str = store_opt(),
    dry_run: bool = dry_run_opt(),
):
    """Fetch, score, and save a single URL to Readwise."""
    if no_llm:
        typer.echo(f"\n[no-llm] Skip inference mode. Would fetch and score: {url}")
        return
    validate_readwise_token(readwise_token)
    llm_provider = make_provider(provider, model, no_llm=no_llm)
    run_save(url, llm_provider, no_score, readwise_token, store_path, dry_run)


@app.command("backup", help="Back up the SQLite database to iCloud (or a custom directory).")
def cmd_backup(
    store_path: str = store_opt(),
    backup_dir: str = typer.Option(DEFAULT_BACKUP_DIR, help="Directory to store backups")
):
    """Back up the SQLite database."""
    run_backup(store_path, backup_dir)


@app.command("restore", help="Restore the database from a backup (requires confirmation).")
def cmd_restore(
    file: Optional[str] = typer.Option(None, "--file", "-f", help="Specific backup file to restore"),
    latest: bool = typer.Option(False, "--latest", help="Restore the most recent backup automatically"),
    store_path: str = store_opt(),
    backup_dir: str = typer.Option(DEFAULT_BACKUP_DIR, help="Directory containing backups"),
):
    """Restore the database from a backup."""
    run_restore(file, latest, store_path, backup_dir)


@app.command("clear-cache", help="Delete all cached feed and social responses.")
def cmd_clear_cache():
    """Delete all cached data."""
    from .feed_cache import clear_cache
    clear_cache()
    typer.echo("Cache cleared.")


if __name__ == "__main__":
    app()
