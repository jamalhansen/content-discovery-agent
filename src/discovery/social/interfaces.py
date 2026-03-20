from abc import ABC, abstractmethod
from typing import Sequence

class SocialReader(ABC):
    """Abstract base class for social media post readers."""

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> Sequence:
        """Search for posts matching a query."""
        pass
