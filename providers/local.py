import requests
from config import OLLAMA_HOST
from providers.base import BaseProvider


class LocalProvider(BaseProvider):
    default_model = "llama3.2:3b"
    models_url = "http://localhost:11434/api/tags"

    @property
    def known_models(self) -> list[str]:
        try:
            resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []

    def complete(self, system_prompt: str, user_message: str) -> str:
        url = f"{OLLAMA_HOST}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            # Constrained generation: model cannot emit EOS until all JSON
            # brackets are closed, so the response is always complete.
            "format": "json",
            "options": {
                # Hard cap on output tokens as a secondary safety net.
                "num_predict": 300,
            },
        }
        try:
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Ollama request timed out for model '{self.model}'.")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {OLLAMA_HOST}. Is Ollama running?"
            )
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 404:
                installed = self.known_models
                hint = f"Installed models: {installed}" if installed else "Run `ollama pull llama3.2:3b` to install a model."
                raise RuntimeError(f"Model '{self.model}' not found in Ollama. {hint}")
            raise RuntimeError(f"Ollama request failed: {e}")
