import typer
from typing import Optional
from local_first_common.providers import PROVIDERS
from local_first_common.cli import resolve_provider
from local_first_common.config import get_setting
from .config import (
    DEFAULT_PROVIDER,
    DEFAULT_MODEL,
    DEFAULT_SCORING_PROVIDER,
    DEFAULT_SCORING_MODEL,
    DEFAULT_REVIEW_PROVIDER,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_THRESHOLD,
    STORE_PATH,
    TOOL_NAME,
)

DEFAULT_SOURCES = "rss"

# ---------------------------------------------------------------------------
# Shared option factories
# ---------------------------------------------------------------------------

def provider_opt():
    val = get_setting(TOOL_NAME, "provider", default=DEFAULT_PROVIDER)
    return typer.Option(
        val, "--provider", "-p",
        help=f"LLM backend: {', '.join(PROVIDERS.keys())} (default: {val})",
    )

def model_opt():
    val = get_setting(TOOL_NAME, "model", default=DEFAULT_MODEL)
    return typer.Option(val, "--model", "-m", help="Override the default model for the chosen provider")

def scoring_provider_opt():
    val = get_setting(TOOL_NAME, "scoring_provider", default=DEFAULT_SCORING_PROVIDER)
    return typer.Option(
        val, "--scoring-provider",
        help=f"LLM backend for the fetch/score loop (default: {val})",
    )

def scoring_model_opt():
    val = get_setting(TOOL_NAME, "scoring_model", default=DEFAULT_SCORING_MODEL)
    return typer.Option(val, "--scoring-model", help="Override model for the scoring pass")

def review_provider_opt():
    val = get_setting(TOOL_NAME, "review_provider", default=DEFAULT_REVIEW_PROVIDER)
    return typer.Option(
        val, "--review-provider",
        help=f"LLM backend for interactive review (default: {val})",
    )

def review_model_opt():
    val = get_setting(TOOL_NAME, "review_model", default=DEFAULT_REVIEW_MODEL)
    return typer.Option(val, "--review-model", help="Override model for the review pass")

def dry_run_opt():
    return typer.Option(False, "--dry-run", "-n", help="Perform the action and call the LLM, but do not write to disk/vault/DB. Print result to stdout.")

def no_llm_opt():
    return typer.Option(False, "--no-llm", help="Skip calling the LLM backend. Use mock responses. Implies --dry-run.")

def threshold_opt():
    val = get_setting(TOOL_NAME, "threshold", default=DEFAULT_THRESHOLD)
    return typer.Option(val, "--threshold", "-t", help="Minimum relevance score 0.0-1.0")

def store_opt():
    val = get_setting(TOOL_NAME, "store", default=STORE_PATH)
    return typer.Option(val, "--store", help="Path to the SQLite database")

def verbose_opt():
    return typer.Option(False, "--verbose", help="Print scores for all items, not just those above threshold")

def limit_opt():
    return typer.Option(None, "--limit", "-l", help="Cap the number of items sent for scoring")

def no_dedup_opt():
    return typer.Option(False, "--no-dedup", help="Disable seen-item tracking, re-score everything")

def cached_opt():
    return typer.Option(False, "--cached", help="Use cached feed responses if available")

def sources_opt():
    val = get_setting(TOOL_NAME, "sources", default=DEFAULT_SOURCES)
    return typer.Option(val, "--sources", "-s",
                        help=f"Comma-separated list of sources: rss,bluesky,mastodon (default: {val})")

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_threshold(threshold: float) -> None:
    if not (0.0 <= threshold <= 1.0):
        typer.echo(f"Error: --threshold must be between 0.0 and 1.0, got {threshold}", err=True)
        raise typer.Exit(1)

def make_provider(provider_name: str, model: Optional[str], no_llm: bool = False):
    if model and model.startswith("@") and provider_name != "local":
        model = None
    try:
        return resolve_provider(PROVIDERS, provider_name, model, no_llm=no_llm)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

def validate_readwise_token(token: str) -> None:
    if not token or token == "your_readwise_token_here":
        typer.echo("Error: READWISE_TOKEN is not set. Get one at https://readwise.io/access_token", err=True)
        typer.echo("Set it in your environment or .content-discovery.toml", err=True)
        raise typer.Exit(1)
