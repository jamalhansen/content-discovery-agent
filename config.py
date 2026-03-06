import os

FEEDS = [
    "https://simonwillison.net/atom/everything/",
    "https://realpython.com/atom.xml",
    "https://news.ycombinator.com/rss",
    "https://pycoders.com/issues.rss",
    "https://duckdb.org/feed.xml",
    "https://ollama.com/blog/rss",
]

TOPIC_TAGS = [
    "python",
    "sql",
    "duckdb",
    "local-ai",
    "llm",
    "data-engineering",
    "vector-databases",
    "rag",
    "ollama",
    "pydantic",
]

DEFAULT_THRESHOLD = 0.6
DEFAULT_PROVIDER = "local"
DEFAULT_VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "~/vaults/BrainSync/")
DEFAULT_INBOX_PATH = "_finds/00-inbox.md"
STATE_FILE_PATH = os.path.expanduser("~/.content-discovery-state.json")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
