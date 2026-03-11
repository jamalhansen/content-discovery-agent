import os
import tomllib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent
_CONFIG_FILE = _PROJECT_ROOT / ".content-discovery.toml"

_FALLBACK_FEEDS = [
    "https://simonwillison.net/atom/everything/",
    "https://realpython.com/atom.xml",
    "https://news.ycombinator.com/rss",
    "https://pycoders.com/issues.rss",
    "https://duckdb.org/feed.xml",
    "https://ollama.com/blog/rss",
]

_FALLBACK_PROFILE = (
    "I'm interested in Python, SQL, data engineering, local AI, and LLMs."
)


def _load_toml() -> dict:
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    return {}


_cfg = _load_toml()

FEEDS: list[str] = _cfg.get("feeds", {}).get("urls", _FALLBACK_FEEDS)
INTEREST_PROFILE: str = _cfg.get("interests", {}).get("profile", _FALLBACK_PROFILE)
INTEREST_EXCLUSIONS: str = _cfg.get("interests", {}).get("exclusions", "")

_settings = _cfg.get("settings", {})
DEFAULT_THRESHOLD: float = _settings.get("threshold", 0.6)
DEFAULT_PROVIDER: str = _settings.get("provider", "local")
DEFAULT_INBOX_PATH: str = _settings.get("inbox_path", "_finds/00-inbox.md")

# env var wins over toml so machine-specific paths stay out of the committed file
DEFAULT_VAULT_PATH: str | None = (
    os.environ.get("OBSIDIAN_VAULT_PATH") or _settings.get("vault_path") or None
)

# env var wins over toml so machine-specific paths (e.g. a Syncthing folder) stay out of the committed file
STORE_PATH = os.path.expanduser(
    os.environ.get("CONTENT_DISCOVERY_STORE")
    or _settings.get("store")
    or "~/.content-discovery.db"
)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

_social_cfg = _cfg.get("social", {})
SOCIAL_KEYWORDS: list[str] = _social_cfg.get("keywords", [])
SOCIAL_MASTODON_INSTANCES: list[str] = _social_cfg.get("mastodon_instances", ["mastodon.social"])
# Additional domains to skip when fetching article metadata (on top of built-in defaults).
# Subdomain matching is automatic — blocking "example.com" also blocks "sub.example.com".
SOCIAL_BLOCKED_DOMAINS: frozenset[str] = frozenset(_social_cfg.get("blocked_domains", []))

# Bluesky App Password auth (optional but recommended — unauthenticated search
# has intermittently returned 403 from public.api.bsky.app).
# Generate an App Password in Bluesky → Settings → Privacy and Security → App Passwords.
BLUESKY_HANDLE: str = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD: str = os.environ.get("BLUESKY_APP_PASSWORD", "")
