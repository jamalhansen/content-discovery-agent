from abc import ABC, abstractmethod


class BaseProvider(ABC):
    def __init__(self, model: str | None = None):
        self._model = model

    @property
    def model(self) -> str:
        return self._model or self.default_model

    @property
    @abstractmethod
    def default_model(self) -> str: ...

    @property
    @abstractmethod
    def known_models(self) -> list[str]: ...

    @property
    @abstractmethod
    def models_url(self) -> str: ...

    @abstractmethod
    def complete(self, system_prompt: str, user_message: str) -> str: ...
