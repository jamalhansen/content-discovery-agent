from social.bluesky import BlueskyReader
from social.mastodon import MastodonReader

SOCIAL_READERS = {
    "bluesky": BlueskyReader,
    "mastodon": MastodonReader,
}

__all__ = ["BlueskyReader", "MastodonReader", "SOCIAL_READERS"]
