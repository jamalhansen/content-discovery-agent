from .bluesky import BlueskyReader
from .mastodon import MastodonReader

SOCIAL_READERS = {
    "bluesky": BlueskyReader,
    "mastodon": MastodonReader,
}

__all__ = ["BlueskyReader", "MastodonReader", "SOCIAL_READERS"]
