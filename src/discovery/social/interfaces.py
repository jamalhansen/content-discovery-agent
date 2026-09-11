from abc import ABC, abstractmethod
from typing import Any


class SocialReader(ABC):
    """Abstract base class for social media post readers."""

    @abstractmethod
    def fetch_items(self, keywords: list[str], session: Any | None = None) -> list:
        """Fetch feed items matching the given keywords."""
        ...
