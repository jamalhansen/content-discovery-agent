from providers.local import LocalProvider
from providers.anthropic_provider import AnthropicProvider
from providers.groq_provider import GroqProvider
from providers.deepseek_provider import DeepSeekProvider

PROVIDERS = {
    "local": LocalProvider,
    "anthropic": AnthropicProvider,
    "groq": GroqProvider,
    "deepseek": DeepSeekProvider,
}
