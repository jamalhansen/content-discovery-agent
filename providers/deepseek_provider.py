import os
from openai import OpenAI, AuthenticationError, NotFoundError, APIError
from providers.base import BaseProvider


class DeepSeekProvider(BaseProvider):
    default_model = "deepseek-chat"
    known_models = ["deepseek-chat", "deepseek-reasoner"]
    models_url = "https://platform.deepseek.com/api-docs/"

    def __init__(self, model: str | None = None):
        super().__init__(model)
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set.")
        self._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    def complete(self, system_prompt: str, user_message: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=512,
            )
            return resp.choices[0].message.content
        except AuthenticationError:
            raise RuntimeError("Invalid DEEPSEEK_API_KEY.")
        except NotFoundError:
            raise RuntimeError(
                f"Model '{self.model}' not found. Known models: {self.known_models}. "
                f"See: {self.models_url}"
            )
        except APIError as e:
            raise RuntimeError(f"DeepSeek API error: {e}")
