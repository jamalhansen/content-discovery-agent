"""Project-level providers shim.

Imports from the shared local-first-common library and maps "local" to
OllamaProvider so existing config (provider = "local") continues to work.
"""
from local_first_common.providers import (
    OllamaProvider,
    AnthropicProvider,
    GroqProvider,
    DeepSeekProvider,
)

PROVIDERS = {
    "local": OllamaProvider,
    "anthropic": AnthropicProvider,
    "groq": GroqProvider,
    "deepseek": DeepSeekProvider,
}

__all__ = ["PROVIDERS", "OllamaProvider", "AnthropicProvider", "GroqProvider", "DeepSeekProvider"]
