import typer
from typing import Optional
from local_first_common.providers import PROVIDERS
from local_first_common.cli import resolve_provider
from .config import (
    DEFAULT_PROVIDER,
    DEFAULT_MODEL,
    DEFAULT_THRESHOLD,
    STORE_PATH,
)

# ---------------------------------------------------------------------------
# Shared option factories
# ---------------------------------------------------------------------------

def provider_opt():
    return typer.Option(
        DEFAULT_PROVIDER, "--provider", "-p",
        help=f"LLM backend: {', '.join(PROVIDERS.keys())} (default: {DEFAULT_PROVIDER})",
    )

def model_opt():
    return typer.Option(DEFAULT_MODEL, "--model", "-m", help="Override the default model for the chosen provider")

def dry_run_opt():
    return typer.Option(False, "--dry-run", "-n", help="Perform the action and call the LLM, but do not write to disk/vault/DB. Print result to stdout.")

def no_llm_opt():
    return typer.Option(False, "--no-llm", help="Skip calling the LLM backend. Use mock responses. Implies --dry-run.")

def threshold_opt():
    return typer.Option(DEFAULT_THRESHOLD, "--threshold", "-t", help="Minimum relevance score 0.0-1.0")

def store_opt():
    return typer.Option(STORE_PATH, "--store", help="Path to the SQLite database")

def verbose_opt():
    return typer.Option(False, "--verbose", help="Print scores for all items, not just those above threshold")

def limit_opt():
    return typer.Option(None, "--limit", "-l", help="Cap the number of items sent for scoring")

def no_dedup_opt():
    return typer.Option(False, "--no-dedup", help="Disable seen-item tracking, re-score everything")

def cached_opt():
    return typer.Option(False, "--cached", help="Use cached feed responses if available")

def sources_opt():
    return typer.Option("rss", "--sources", "-s",
                        help="Comma-separated list of sources: rss,bluesky,mastodon (default: rss)")

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_threshold(threshold: float) -> None:
    if not (0.0 <= threshold <= 1.0):
        typer.echo(f"Error: --threshold must be between 0.0 and 1.0, got {threshold}", err=True)
        raise typer.Exit(1)

def make_provider(provider_name: str, model: Optional[str], no_llm: bool = False):
    # @-prefixed model selectors (e.g. @best) are Ollama-specific; ignore for cloud providers
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
