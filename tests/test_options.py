from unittest.mock import MagicMock, patch

import pytest
import typer

from discovery.options import (
    ProviderSetupError,
    ReadwiseTokenError,
    ThresholdValidationError,
    make_provider,
    make_provider_or_raise,
    validate_readwise_token,
    validate_readwise_token_or_raise,
    validate_threshold,
    validate_threshold_or_raise,
)


class TestValidateThreshold:
    def test_accepts_value_in_range(self):
        validate_threshold(0.0)
        validate_threshold(0.5)
        validate_threshold(1.0)

    def test_rejects_value_out_of_range(self):
        with pytest.raises(typer.Exit):
            validate_threshold(-0.1)

        with pytest.raises(typer.Exit):
            validate_threshold(1.1)

    def test_validate_threshold_or_raise_rejects_value_out_of_range(self):
        with pytest.raises(ThresholdValidationError, match="--threshold must be between 0.0 and 1.0"):
            validate_threshold_or_raise(-0.1)


class TestValidateReadwiseToken:
    def test_validate_readwise_token_accepts_valid_token(self):
        validate_readwise_token("tok_abc")
        validate_readwise_token_or_raise("tok_abc")

    def test_validate_readwise_token_or_raise_rejects_missing(self):
        with pytest.raises(ReadwiseTokenError, match="READWISE_TOKEN is not set"):
            validate_readwise_token_or_raise("")

    def test_validate_readwise_token_exits_for_cli_compat(self, capsys):
        with pytest.raises(typer.Exit):
            validate_readwise_token("")

        captured = capsys.readouterr()
        assert "Error: READWISE_TOKEN is not set." in captured.err


class TestMakeProvider:
    def test_make_provider_or_raise_returns_provider(self):
        provider = MagicMock()
        with patch("discovery.options.resolve_provider", return_value=provider):
            result = make_provider_or_raise("ollama", None)

        assert result is provider

    def test_make_provider_or_raise_raises_typed_error(self):
        with patch(
            "discovery.options.resolve_provider",
            side_effect=RuntimeError("bad provider"),
        ):
            with pytest.raises(ProviderSetupError, match="bad provider"):
                make_provider_or_raise("ollama", None)

    def test_make_provider_exits_for_cli_compat(self, capsys):
        with patch(
            "discovery.options.resolve_provider",
            side_effect=RuntimeError("bad provider"),
        ):
            with pytest.raises(typer.Exit):
                make_provider("ollama", None)

        captured = capsys.readouterr()
        assert "Error: bad provider" in captured.err
