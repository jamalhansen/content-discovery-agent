import json
import logging
from typing import Annotated, Optional

import typer

from .config import (
    CONTEXTA_INBOX_PATH,
    CONTEXTA_NOTES_PATH,
    DEFAULT_BACKUP_DIR,
    READWISE_TOKEN,
)
from local_first_common.cli import resolve_dry_run, init_config_option, json_option
from local_first_common.logging import setup_logging
from .options import (
    provider_opt,
    model_opt,
    scoring_provider_opt,
    scoring_model_opt,
    dry_run_opt,
    no_llm_opt,
    threshold_opt,
    store_opt,
    verbose_opt,
    limit_opt,
    no_dedup_opt,
    cached_opt,
    sources_opt,
    ProviderSetupError,
    ReadwiseTokenError,
    ThresholdValidationError,
    make_provider_or_raise,
    validate_readwise_token_or_raise,
    validate_threshold_or_raise,
)
from .orchestrator import run_discovery, run_review, run_save
from .reconcile import reconcile
from .import_reader import import_reader_backlog
from .eval import run_eval
from .db_commands import (
    run_report,
    run_purge_blocked,
    run_dismiss_source,
    run_backup,
    run_restore,
    run_fix_urls,
)
from .scorer import score_item
from . import store

app = typer.Typer(
    name="content-discovery",
    help="Content discovery agent: score RSS feeds and store candidates for review.",
    add_completion=False,
)


def _setup_tool_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    try:
        setup_logging(
            level=level,
            tool_name="content-discovery-agent",
            persist_warnings=True,
        )
    except TypeError:
        # Backward compatibility with older local-first-common logging signature.
        setup_logging(level=level)


@app.command(
    "run",
    help="Fetch feeds, score items, and store candidates in the DB (default command).",
)
def cmd_run(
    provider: str = scoring_provider_opt(),
    model: Optional[str] = scoring_model_opt(),
    dry_run: bool = dry_run_opt(),
    no_llm: bool = no_llm_opt(),
    feed: Optional[str] = typer.Option(
        None,
        "--feed",
        "-f",
        metavar="URL",
        help="Process a single feed URL instead of the full configured list",
    ),
    threshold: float = threshold_opt(),
    no_dedup: bool = no_dedup_opt(),
    verbose: bool = verbose_opt(),
    cached: bool = cached_opt(),
    limit: Optional[int] = limit_opt(),
    store_path: str = store_opt(),
    sources: str = sources_opt(),
    json_output: Annotated[bool, json_option()] = False,
    init_config: Annotated[
        bool,
        init_config_option(
            "content-discovery-agent",
            {"scoring_provider": "anthropic", "sources": "rss,mastodon,bluesky"},
        ),
    ] = False,
):
    """Fetch feeds, score items, and store candidates in the DB."""
    try:
        validate_threshold_or_raise(threshold)
        llm_provider = make_provider_or_raise(provider, model, no_llm=no_llm)
    except (ThresholdValidationError, ProviderSetupError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    _setup_tool_logging(verbose)

    candidates, scored_count, skipped_count, dismissed_this_run = run_discovery(
        llm_provider,
        sources,
        feed,
        threshold,
        no_dedup,
        verbose,
        cached,
        limit,
        store_path,
        dry_run=dry_run,
    )

    min_near_miss_score = max(0.0, threshold - 0.15)
    near_misses = sorted(
        (d for d in dismissed_this_run if d["score"] >= min_near_miss_score),
        key=lambda d: d["score"],
        reverse=True,
    )[:5]

    if json_output:
        out = {
            "candidates": candidates,
            "scored_count": scored_count,
            "skipped_count": skipped_count,
            "near_misses": near_misses,
            "dry_run": dry_run,
        }
        typer.echo(json.dumps(out, indent=2, default=str))
        return

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

    if not candidates and scored_count > 0:
        suggested_threshold = max(0.0, round(threshold - 0.1, 2))
        typer.echo(
            f"No items met threshold {threshold:.2f}. "
            f"Try --threshold {suggested_threshold:.2f} for a wider net."
        )

    # Shown on every run, not just zero-candidate ones -- otherwise a
    # near-miss dismissed the same day as several above-threshold candidates
    # is invisible unless you go query the DB by hand.
    if near_misses:
        typer.echo("\nNear misses (dismissed, close to threshold):")
        for item in near_misses:
            typer.echo(f"  [{item['score']:.2f}] {item['title']}")

    typer.echo(f"Done. Processed: {scored_count}, Skipped: {skipped_count}")


@app.command(
    "review",
    help="Interactively review pending items; keep and route each to Readwise, Contexta, or both.",
)
def cmd_review(
    store_path: str = store_opt(),
    readwise_token: str = typer.Option(
        READWISE_TOKEN,
        "--readwise-token",
        envvar="READWISE_TOKEN",
        # Without this the resolved token is printed verbatim in --help output.
        show_default=False,
        help="Readwise access token (or set READWISE_TOKEN env var)",
    ),
):
    """Interactively review pending items; send kept items to Readwise Reader."""
    try:
        validate_readwise_token_or_raise(readwise_token)
    except ReadwiseTokenError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    store.init_db(store_path)
    kept, dismissed = run_review(store_path, readwise_token)
    typer.echo(f"\nDone. Kept: {kept}, Dismissed: {dismissed}.")


@app.command(
    "report",
    help="Print a summary report of feed trends, source quality, and scoring history.",
)
def cmd_report(
    store_path: str = store_opt(),
    days: int = typer.Option(
        30, "--days", "-d", help="Number of days to include in the report"
    ),
    json_output: Annotated[bool, json_option()] = False,
):
    """Print a summary report of feed trends and scoring history."""
    run_report(store_path, days, json_output=json_output)


@app.command("list-candidates", help="List pending candidate items awaiting review.")
def cmd_list_candidates(
    store_path: str = store_opt(),
    json_output: Annotated[bool, json_option()] = False,
):
    """List pending candidate items awaiting review."""
    store.init_db(store_path)
    items = store.get_new_items(store_path)
    if json_output:
        typer.echo(json.dumps(items, indent=2, default=str))
        return
    if not items:
        typer.echo("No pending items to review.")
        return
    typer.echo(f"\nPending items ({len(items)}):")
    for item in items:
        tags = item.get("tags") or []
        tag_str = " ".join(f"#{t}" for t in tags) if tags else ""
        typer.echo(f"\n  [{item['score']:.2f}] {item['title']}")
        if item.get("summary"):
            typer.echo(f"  {item['summary']}")
        typer.echo(f"  {item['url']}  {tag_str}")


@app.command(
    "purge-blocked",
    help="Dismiss all pending items whose URLs match the current domain blocklist.",
)
def cmd_purge_blocked(store_path: str = store_opt()):
    """Dismiss pending items from blocked domains."""
    run_purge_blocked(store_path)


@app.command(
    "dismiss-source",
    help="Dismiss all pending items whose source contains QUERY (case-insensitive).",
)
def cmd_dismiss_source(
    query: str = typer.Argument(..., help="Source name fragment to match"),
    store_path: str = store_opt(),
):
    """Dismiss pending items from a specific source."""
    run_dismiss_source(query, store_path)


@app.command(
    "reconcile",
    help="Archive Reader items whose article already became a vault note.",
)
def cmd_reconcile(
    notes_path: str = typer.Option(
        CONTEXTA_NOTES_PATH,
        "--notes-path",
        envvar="CONTEXTA_NOTES_PATH",
        help="Vault notes/ directory to read source_url frontmatter from",
    ),
    readwise_token: str = typer.Option(
        READWISE_TOKEN,
        "--readwise-token",
        envvar="READWISE_TOKEN",
        # Without this the resolved token is printed verbatim in --help output.
        show_default=False,
        help="Readwise access token (or set READWISE_TOKEN env var)",
    ),
    dry_run: bool = dry_run_opt(),
):
    """Treat a note's source_url as a read receipt and archive the Reader copy."""
    try:
        validate_readwise_token_or_raise(readwise_token)
    except ReadwiseTokenError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    result = reconcile(notes_path, readwise_token, dry_run=dry_run)

    typer.echo(
        f"Scanned {result.notes_scanned} notes; "
        f"{result.notes_with_source_url} carry a source_url, "
        f"covering {result.distinct_source_urls} distinct articles."
    )
    typer.echo(f"Checked {result.documents_checked} unread Reader documents.")
    if not result.matched:
        typer.echo("No Reader items matched a note. Nothing to archive.")
        return
    for title, url in result.matched:
        typer.echo(f"  {'[dry-run] ' if dry_run else ''}{title[:65]}\n    {url}")
    if dry_run:
        typer.echo(f"\nWould archive {len(result.matched)} items.")
    else:
        typer.echo(f"\nArchived {result.archived} of {len(result.matched)} matched items.")
        if result.failed:
            typer.echo(f"Failed to archive {len(result.failed)}: {', '.join(result.failed)}")


@app.command(
    "import-reader",
    help="Pull unread Reader items not yet captured into the Contexta inbox.",
)
def cmd_import_reader(
    notes_path: str = typer.Option(
        CONTEXTA_NOTES_PATH,
        "--notes-path",
        envvar="CONTEXTA_NOTES_PATH",
        help="Vault notes/ directory, checked so an already-noted article is skipped",
    ),
    inbox_path: str = typer.Option(
        CONTEXTA_INBOX_PATH,
        "--inbox-path",
        envvar="CONTEXTA_INBOX_PATH",
        help="Vault inbox/ directory to write into, and to check for an existing capture",
    ),
    readwise_token: str = typer.Option(
        READWISE_TOKEN,
        "--readwise-token",
        envvar="READWISE_TOKEN",
        show_default=False,
        help="Readwise access token (or set READWISE_TOKEN env var)",
    ),
    limit: int = typer.Option(
        10, "--limit", "-l",
        help="Maximum articles to fetch in this run (each is a live HTTP request)",
    ),
    dry_run: bool = dry_run_opt(),
):
    """Backfill the inbox from the existing Reader queue, the direction reconcile does not cover."""
    try:
        validate_readwise_token_or_raise(readwise_token)
    except ReadwiseTokenError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    result = import_reader_backlog(
        notes_path, inbox_path, readwise_token, limit=limit, dry_run=dry_run
    )

    typer.echo(f"Checked {result.documents_checked} unread Reader documents.")
    typer.echo(f"Already captured (note or inbox file exists): {result.already_captured}")
    if not result.imported and not result.failed:
        typer.echo("Nothing new to import.")
        return
    for title in result.imported:
        typer.echo(f"  {'[dry-run] ' if dry_run else ''}imported: {title[:65]}")
    for title in result.failed:
        typer.echo(f"  FAILED to write: {title[:65]}")
    if dry_run:
        typer.echo(f"\nWould import {len(result.imported)} items (limit {limit}).")
    else:
        typer.echo(f"\nImported {len(result.imported)} of {limit} requested.")
        if result.failed:
            typer.echo(f"{len(result.failed)} failed to write.")
        remaining = result.documents_checked - result.already_captured - len(result.imported) - len(result.failed)
        if remaining > 0:
            typer.echo(f"{remaining} more uncaptured items waiting; raise --limit or run again.")


@app.command(
    "fix-urls", help="Normalize all URLs in the database to prevent duplicates."
)
def cmd_fix_urls(store_path: str = store_opt()):
    """Normalize all URLs in the database to prevent duplicates."""
    run_fix_urls(store_path)


@app.command(
    "check-feeds", help="Validate all configured RSS feeds and report their status."
)
def cmd_check_feeds():
    """Validate all configured RSS feeds."""
    from .feed_reader import FeedReaderError, fetch_feed_or_raise
    from .config import FEEDS

    typer.echo(f"Checking {len(FEEDS)} feeds...\n")
    for url in FEEDS:
        try:
            items = fetch_feed_or_raise(url)
            if items:
                typer.echo(
                    f"  [OK] {items[0].source[:40]:40} | {len(items):3} items | {url}"
                )
            else:
                typer.echo(f"  [EMPTY] {url}")
        except FeedReaderError as e:
            typer.echo(f"  [FAIL] {url} | Error: {e}")


@app.command(
    "rescore",
    help="Re-score all pending items with the current interest profile and examples.",
)
def cmd_rescore(
    provider: str = provider_opt(),
    model: Optional[str] = model_opt(),
    no_llm: bool = no_llm_opt(),
    store_path: str = store_opt(),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Cap items"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose."),
):
    """Re-score all pending items."""
    from .config import INTEREST_PROFILE, INTEREST_EXCLUSIONS

    try:
        llm_provider = make_provider_or_raise(provider, model, no_llm=no_llm)
    except ProviderSetupError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
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
        result = score_item(
            llm_provider,
            item["title"],
            item["description"],
            INTEREST_PROFILE,
            examples,
            INTEREST_EXCLUSIONS,
        )
        if result:
            if verbose:
                typer.echo(
                    f"  {item['score']:.2f} -> {result.score:.2f} | {item['title'][:70]}"
                )
            store.upsert_item(
                url=item["url"],
                title=item["title"],
                source=item["source"],
                description=item["description"],
                score=result.score,
                tags=result.tags,
                summary=result.summary,
                fetched_at=item["fetched_at"],
                published_at=item["published_at"],
                path=store_path,
            )
    typer.echo("\nRe-scoring complete.")


@app.command(
    "eval",
    help="Re-score a random sample of kept/dismissed history against the current "
    "config; report where it agrees or disagrees with those past decisions.",
)
def cmd_eval(
    provider: str = scoring_provider_opt(),
    model: Optional[str] = scoring_model_opt(),
    no_llm: bool = no_llm_opt(),
    threshold: float = threshold_opt(),
    store_path: str = store_opt(),
    n_kept: int = typer.Option(40, "--n-kept", help="How many past kept items to sample"),
    n_dismissed: int = typer.Option(
        80, "--n-dismissed", help="How many past dismissed items to sample"
    ),
):
    """Measure whether a scoring/prompt/profile change agrees with past decisions.

    Doesn't write anything -- historical score/status are left untouched. Use
    this after editing the interest profile, exclusions, or scorer prompt, to
    get a number instead of a feeling for whether the change helped.
    """
    from .config import INTEREST_PROFILE, INTEREST_EXCLUSIONS

    try:
        validate_threshold_or_raise(threshold)
        llm_provider = make_provider_or_raise(provider, model, no_llm=no_llm)
    except (ThresholdValidationError, ProviderSetupError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    result = run_eval(
        llm_provider, threshold, INTEREST_PROFILE, INTEREST_EXCLUSIONS,
        store_path, n_kept=n_kept, n_dismissed=n_dismissed,
    )

    typer.echo(
        f"Sampled {result.n_kept_sampled} kept, {result.n_dismissed_sampled} dismissed. "
        f"Re-scored {result.n_scored} (skipped {result.n_skipped})."
    )

    rate = result.agreement_rate
    if rate is None:
        typer.echo("Nothing to compare.")
        return
    typer.echo(f"Agreement with past decisions: {rate:.0%} ({result.agreements}/{result.n_compared})")

    if result.regressions:
        typer.echo(
            f"\nRegressions -- previously kept, would now score below {threshold:.2f}:"
        )
        for i in result.regressions:
            typer.echo(f"  [{i.old_score:.2f} -> {i.new_score:.2f}] {i.title}  ({i.source})")

    if result.drift:
        typer.echo(
            f"\nDrift -- previously dismissed, would now score at/above {threshold:.2f} "
            "(not necessarily bad -- worth a glance):"
        )
        for i in result.drift:
            typer.echo(f"  [{i.old_score:.2f} -> {i.new_score:.2f}] {i.title}  ({i.source})")


@app.command("save", help="Save a URL directly to Readwise Reader as a kept item.")
def cmd_save(
    url: str = typer.Argument(..., help="URL to fetch, score, and save"),
    provider: str = provider_opt(),
    model: Optional[str] = model_opt(),
    no_llm: bool = no_llm_opt(),
    no_score: bool = typer.Option(
        False, "--no-score", help="Skip LLM scoring; store with score 1.0"
    ),
    readwise_token: str = typer.Option(READWISE_TOKEN, help="Readwise token"),
    store_path: str = store_opt(),
    dry_run: bool = dry_run_opt(),
):
    """Fetch, score, and save a single URL to Readwise."""
    dry_run = resolve_dry_run(dry_run, no_llm)
    if no_llm:
        no_score = True
    try:
        validate_readwise_token_or_raise(readwise_token)
        llm_provider = make_provider_or_raise(provider, model, no_llm=no_llm)
    except (ReadwiseTokenError, ProviderSetupError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    run_save(url, llm_provider, no_score, readwise_token, store_path, dry_run)


@app.command(
    "backup", help="Back up the SQLite database to iCloud (or a custom directory)."
)
def cmd_backup(
    store_path: str = store_opt(),
    backup_dir: str = typer.Option(
        DEFAULT_BACKUP_DIR, help="Directory to store backups"
    ),
):
    """Back up the SQLite database."""
    run_backup(store_path, backup_dir)


@app.command(
    "restore", help="Restore the database from a backup (requires confirmation)."
)
def cmd_restore(
    file: Optional[str] = typer.Option(
        None, "--file", "-f", help="Specific backup file to restore"
    ),
    latest: bool = typer.Option(
        False, "--latest", help="Restore the most recent backup automatically"
    ),
    store_path: str = store_opt(),
    backup_dir: str = typer.Option(
        DEFAULT_BACKUP_DIR, help="Directory containing backups"
    ),
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
