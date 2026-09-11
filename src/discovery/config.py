import os

from local_first_common.config import get_setting, load_config

TOOL_NAME = "content-discovery-agent"
_cfg = load_config(TOOL_NAME)

_settings = _cfg.get("settings", {})
_feeds = _cfg.get("feeds", {})
_interests = _cfg.get("interests", {})
_social = _cfg.get("social", {})


def _as_csv_sources(value: object) -> str:
    """Normalize configured sources into CLI-friendly comma-separated form."""
    if isinstance(value, list):
        return ",".join(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, str):
        return value
    return "rss"


FEEDS: list[str] = _feeds.get("urls", [])
INTEREST_PROFILE: str = _interests.get("profile", "")
INTEREST_EXCLUSIONS: str = _interests.get("exclusions", "")

# Substrings that disqualify an item by title alone, matched case-insensitively.
# Applied before scoring, so matches never reach the LLM, the store, or review.
# Sponsored posts are written to read as on-topic and score well otherwise.
BLOCKED_TITLE_PATTERNS: tuple[str, ...] = tuple(
    str(p).lower()
    for p in _interests.get("blocked_title_patterns", ["(sponsor)", "(sponsored)"])
)

DEFAULT_THRESHOLD: float = get_setting(
    TOOL_NAME, "threshold", default=_settings.get("threshold", 0.81)
)
DEFAULT_PROVIDER: str = get_setting(
    TOOL_NAME, "provider", env_var="MODEL_PROVIDER",
    default=_settings.get("provider", "local"),
)
DEFAULT_MODEL: str | None = get_setting(
    TOOL_NAME, "model", env_var="MODEL_NAME", default=_settings.get("model")
)
DEFAULT_SOURCES: str = _as_csv_sources(_settings.get("sources", "rss"))

DEFAULT_SCORING_PROVIDER: str = _settings.get("scoring_provider", DEFAULT_PROVIDER)
DEFAULT_SCORING_MODEL: str | None = _settings.get("scoring_model") or DEFAULT_MODEL
DEFAULT_REVIEW_PROVIDER: str = _settings.get("review_provider", DEFAULT_PROVIDER)
DEFAULT_REVIEW_MODEL: str | None = _settings.get("review_model") or None

CONTEXTA_INBOX_ROUTING: bool = bool(_settings.get("contexta_inbox_routing", False))
CONTEXTA_INBOX_PATH: str = os.path.expanduser(
    get_setting(
        TOOL_NAME, "contexta_inbox_path", env_var="CONTEXTA_INBOX_PATH",
        default=_settings.get("contexta_inbox_path", "~/vaults/Contexta/inbox"),
    )
)

# Where finished notes live. `reconcile` reads their source_url frontmatter and
# treats a note as a read receipt for the article it was made from.
CONTEXTA_NOTES_PATH: str = os.path.expanduser(
    get_setting(
        TOOL_NAME, "contexta_notes_path", env_var="CONTEXTA_NOTES_PATH",
        default=_settings.get("contexta_notes_path", "~/vaults/Contexta/notes"),
    )
)

# Real-browser fallback for pages that fetch thin because their content is
# injected by client-side JS (verified 2026-08-23: x.com serves a
# "JavaScript is not available" page to any client that doesn't run JS; a
# rendered fetch of the same URL recovered the full tweet). Off switch is
# js_render_enabled = false in [settings] — set it if playwright is not
# installed, or if you never want the slower rendered fetch attempted.
JS_RENDER_ENABLED: bool = bool(_settings.get("js_render_enabled", True))
JS_RENDER_DOMAINS: frozenset[str] = frozenset(
    str(d).lower().removeprefix("www.")
    for d in _settings.get("js_render_domains", ["x.com", "twitter.com"])
)

STORE_PATH = os.path.expanduser(
    get_setting(
        TOOL_NAME,
        "store",
        env_var="CONTENT_DISCOVERY_STORE",
        default=_settings.get("store", "~/.content-discovery.db"),
    )
)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

DEFAULT_BACKUP_DIR: str = os.path.expanduser(
    get_setting(
        TOOL_NAME,
        "backup_dir",
        env_var="CONTENT_DISCOVERY_BACKUP_DIR",
        default="~/Library/Mobile Documents/com~apple~CloudDocs/Backups/content-discovery",
    )
)

# Citation crawling: mines outbound links from your own recently-kept
# articles as a source of new candidates an RSS-only feed list can't reach
# on its own. See discovery/citations.py for the rationale.
CITATION_KEPT_LIMIT: int = int(_settings.get("citation_kept_limit", 10))
CITATION_MAX_LINKS_PER_ITEM: int = int(_settings.get("citation_max_links_per_item", 8))

SOCIAL_KEYWORDS: list[str] = _social.get("keywords", [])
SOCIAL_MASTODON_INSTANCES: list[str] = _social.get(
    "mastodon_instances", ["mastodon.social"]
)
SOCIAL_BLOCKED_DOMAINS: frozenset[str] = frozenset(_social.get("blocked_domains", []))

BLUESKY_HANDLE: str = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD: str = os.environ.get("BLUESKY_APP_PASSWORD", "")
READWISE_TOKEN: str = os.environ.get("READWISE_TOKEN", "")
READWISE_ROUTING: bool = bool(_settings.get("readwise_routing", False))

READER_LOCATION: str = _settings.get("reader_location", "new")
READER_CATEGORY: str | None = _settings.get("reader_category")
