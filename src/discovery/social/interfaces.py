from abc import ABC, abstractmethod


class SocialReader(ABC):
    """Abstract base class for social media post readers."""

    @abstractmethod
    def fetch_items(self, keywords: list[str], session: any = None) -> list:
        """Fetch feed items matching the given keywords."""
        ...
