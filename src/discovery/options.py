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


class DiscoveryOptionsError(Exception):
    """Base error for discovery CLI option handling."""


class ProviderSetupError(DiscoveryOptionsError):
    """Raised when the configured provider cannot be created."""


class ThresholdValidationError(DiscoveryOptionsError):
    """Raised when threshold is outside [0.0, 1.0]."""


class ReadwiseTokenError(DiscoveryOptionsError):
    """Raised when readwise token is missing or placeholder."""


def provider_opt():
    val = get_setting(TOOL_NAME, "provider", default=DEFAULT_PROVIDER)
    return typer.Option(val, "--provider", "-p", help=f"LLM backend (default: {val})")


def model_opt():
    val = get_setting(TOOL_NAME, "model", default=DEFAULT_MODEL)
    return typer.Option(val, "--model", "-m", help="Override default model")


def scoring_provider_opt():
    val = get_setting(TOOL_NAME, "scoring_provider", default=DEFAULT_SCORING_PROVIDER)
    return typer.Option(
        val, "--scoring-provider", help=f"LLM backend for fetch/score (default: {val})"
    )


def scoring_model_opt():
    val = get_setting(TOOL_NAME, "scoring_model", default=DEFAULT_SCORING_MODEL)
    return typer.Option(val, "--scoring-model", help="Override scoring model")


def review_provider_opt():
    val = get_setting(TOOL_NAME, "review_provider", default=DEFAULT_REVIEW_PROVIDER)
    return typer.Option(
        val, "--review-provider", help=f"LLM backend for review (default: {val})"
    )


def review_model_opt():
    val = get_setting(TOOL_NAME, "review_model", default=DEFAULT_REVIEW_MODEL)
    return typer.Option(val, "--review-model", help="Override review model")


def threshold_opt():
    val = get_setting(TOOL_NAME, "threshold", default=DEFAULT_THRESHOLD)
    return typer.Option(
        val, "--threshold", "-t", help="Minimum relevance score 0.0-1.0"
    )


def store_opt():
    val = get_setting(TOOL_NAME, "store", default=STORE_PATH)
    return typer.Option(val, "--store", help="Path to SQLite database")


def sources_opt():
    val = get_setting(TOOL_NAME, "sources", default=DEFAULT_SOURCES)
    return typer.Option(
        val, "--sources", "-s", help=f"Sources: rss,bluesky,mastodon (default: {val})"
    )


def dry_run_opt():
    return typer.Option(False, "--dry-run", "-n")


def no_llm_opt():
    return typer.Option(False, "--no-llm")


def verbose_opt():
    return typer.Option(False, "--verbose")


def limit_opt():
    return typer.Option(None, "--limit", "-l")


def no_dedup_opt():
    return typer.Option(False, "--no-dedup")


def cached_opt():
    return typer.Option(False, "--cached")


def validate_threshold(threshold: float) -> None:
    """Compatibility wrapper that exits with Typer for CLI callers."""
    try:
        validate_threshold_or_raise(threshold)
    except ThresholdValidationError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


def validate_threshold_or_raise(threshold: float) -> None:
    """Validate threshold or raise typed error for command-boundary handling."""
    if not (0.0 <= threshold <= 1.0):
        raise ThresholdValidationError("--threshold must be between 0.0 and 1.0")


def make_provider(provider_name: str, model: Optional[str], no_llm: bool = False):
    """Compatibility wrapper that exits with Typer for CLI callers."""
    try:
        return make_provider_or_raise(provider_name, model, no_llm=no_llm)
    except ProviderSetupError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


def make_provider_or_raise(
    provider_name: str,
    model: Optional[str],
    no_llm: bool = False,
):
    """Create provider or raise a typed error for command-boundary handling."""
    try:
        return resolve_provider(PROVIDERS, provider_name, model, no_llm=no_llm)
    except Exception as e:  # noqa: BLE001
        raise ProviderSetupError(str(e)) from e


def validate_readwise_token(token: str) -> None:
    """Compatibility wrapper that exits with Typer for CLI callers."""
    try:
        validate_readwise_token_or_raise(token)
    except ReadwiseTokenError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


def validate_readwise_token_or_raise(token: str) -> None:
    """Validate readwise token or raise typed error for command-boundary handling."""
    if not token or token == "your_readwise_token_here":
        raise ReadwiseTokenError("READWISE_TOKEN is not set.")
