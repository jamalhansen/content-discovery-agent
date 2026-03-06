import os
import anthropic
from providers.base import BaseProvider


class AnthropicProvider(BaseProvider):
    default_model = "claude-haiku-4-5-20251001"
    known_models = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-6"]
    models_url = "https://docs.anthropic.com/en/docs/about-claude/models"

    def __init__(self, model: str | None = None):
        super().__init__(model)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system_prompt: str, user_message: str) -> str:
        try:
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=512,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return msg.content[0].text
        except anthropic.AuthenticationError:
            raise RuntimeError("Invalid ANTHROPIC_API_KEY.")
        except anthropic.NotFoundError:
            raise RuntimeError(
                f"Model '{self.model}' not found. Known models: {self.known_models}. "
                f"See: {self.models_url}"
            )
        except anthropic.APIError as e:
            raise RuntimeError(f"Anthropic API error: {e}")
