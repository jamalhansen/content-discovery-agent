from abc import ABC, abstractmethod

from feed_reader import FeedItem


class SocialReader(ABC):
    """Abstract base class for social media source readers.

    Each concrete reader fetches posts from a social platform, extracts linked
    article URLs, and returns them normalised as FeedItems ready for scoring.
    """

    @abstractmethod
    def fetch_items(self, keywords: list[str]) -> list[FeedItem]:
        """Fetch FeedItems from this social source using the given keywords.

        Args:
            keywords: Search terms / hashtags to query. Multi-word keywords
                      are handled per-platform (e.g. spaces stripped for hashtags).

        Returns:
            A list of FeedItems representing articles discovered via this source.
            URLs are deduplicated within a single call.
        """
        ...
