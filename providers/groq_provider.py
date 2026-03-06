import os
import groq
from providers.base import BaseProvider


class GroqProvider(BaseProvider):
    default_model = "llama-3.3-70b-versatile"
    known_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
    models_url = "https://console.groq.com/docs/models"

    def __init__(self, model: str | None = None):
        super().__init__(model)
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set.")
        self._client = groq.Groq(api_key=api_key)

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
        except groq.AuthenticationError:
            raise RuntimeError("Invalid GROQ_API_KEY.")
        except groq.NotFoundError:
            raise RuntimeError(
                f"Model '{self.model}' not found. Known models: {self.known_models}. "
                f"See: {self.models_url}"
            )
        except groq.APIError as e:
            raise RuntimeError(f"Groq API error: {e}")
