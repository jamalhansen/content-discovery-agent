import os
from local_first_common.config import get_setting, load_config

TOOL_NAME = "content-discovery-agent"
_cfg = load_config(TOOL_NAME)

_settings = _cfg.get("settings", {})
_feeds = _cfg.get("feeds", {})
_interests = _cfg.get("interests", {})
_social = _cfg.get("social", {})

FEEDS: list[str] = _feeds.get("urls", [])
INTEREST_PROFILE: str = _interests.get("profile", "")
INTEREST_EXCLUSIONS: str = _interests.get("exclusions", "")

DEFAULT_THRESHOLD: float = get_setting(TOOL_NAME, "threshold", default=0.81)
DEFAULT_PROVIDER: str = get_setting(TOOL_NAME, "provider", env_var="MODEL_PROVIDER", default="local")
DEFAULT_MODEL: str | None = get_setting(TOOL_NAME, "model", env_var="MODEL_NAME")

DEFAULT_SCORING_PROVIDER: str = _settings.get("scoring_provider", DEFAULT_PROVIDER)
DEFAULT_SCORING_MODEL: str | None = _settings.get("scoring_model") or DEFAULT_MODEL
DEFAULT_REVIEW_PROVIDER: str = _settings.get("review_provider", DEFAULT_PROVIDER)
DEFAULT_REVIEW_MODEL: str | None = _settings.get("review_model") or None

DEFAULT_INBOX_PATH: str = _settings.get("inbox_path", "_finds/0000-agent-inbox.md")
DEFAULT_VAULT_PATH: str | None = get_setting(TOOL_NAME, "vault_path", env_var="OBSIDIAN_VAULT_PATH")

STORE_PATH = os.path.expanduser(
    get_setting(TOOL_NAME, "store", env_var="CONTENT_DISCOVERY_STORE", default="~/.content-discovery.db")
)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

DEFAULT_BACKUP_DIR: str = os.path.expanduser(
    get_setting(TOOL_NAME, "backup_dir", env_var="CONTENT_DISCOVERY_BACKUP_DIR", 
                default="~/Library/Mobile Documents/com~apple~CloudDocs/Backups/content-discovery")
)

SOCIAL_KEYWORDS: list[str] = _social.get("keywords", [])
SOCIAL_MASTODON_INSTANCES: list[str] = _social.get("mastodon_instances", ["mastodon.social"])
SOCIAL_BLOCKED_DOMAINS: frozenset[str] = frozenset(_social.get("blocked_domains", []))

BLUESKY_HANDLE: str = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD: str = os.environ.get("BLUESKY_APP_PASSWORD", "")
READWISE_TOKEN: str = os.environ.get("READWISE_TOKEN", "")
READWISE_ROUTING: bool = bool(_settings.get("readwise_routing", False))
