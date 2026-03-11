Content Discovery Agent

## Project Overview

CLI tool that monitors RSS feeds and social platforms (Bluesky, Mastodon), scores each item for relevance using an LLM, and stores candidates in SQLite for interactive review. Runs on a cron schedule. The user reviews candidates in the terminal and decides what gets written to the Obsidian inbox.

The LLM's job is narrow: read a feed item's title and description, score its relevance against a natural language interest profile, detect the article's language, generate a one-line summary, and return structured JSON. No complex reasoning, no long context. A small local model handles this easily.

## What This Tool Does

1. Fetches items from configured RSS feeds, Bluesky keyword searches, and Mastodon hashtag timelines
2. Strips UTM and other tracking parameters from all URLs before storing
3. Skips items from blocked domains (Medium network + user-configured list)
4. Sends each item to an LLM with a relevance-scoring prompt (interest profile + few-shot examples)
5. Dismisses non-English items and items below the score threshold automatically
6. Stores all scored items in a local SQLite database (deduplication — won't re-score on next run)
7. User runs `--review` to triage candidates interactively (y/n/s/o)
8. Kept items are written to the Obsidian inbox; dismissed items become negative examples for future runs

## Architecture

```
content-discovery-agent/
  content_discovery.py    # CLI entrypoint (argparse) — all commands
  store.py                # SQLite storage layer — items, dedup, examples, reports
  scorer.py               # Prompt construction + response parsing (score, tags, summary, language)
  feed_reader.py          # feedparser wrapper + FeedItem dataclass
  feed_cache.py           # RSS and social response caching (12h TTL)
  inbox_writer.py         # Obsidian inbox append logic (used at review time)
  config.py               # Feeds, interest profile, social config, defaults, env vars
  url_utils.py            # clean_url() — strips UTM and tracking query params
  state.py                # Legacy JSON dedup — superseded by store.py, kept for compat
  providers/
    __init__.py           # PROVIDERS dict
    base.py               # Abstract provider interface
    local.py              # Ollama provider
    anthropic_provider.py # Anthropic API (Claude)
    groq_provider.py      # Groq API
    deepseek_provider.py  # DeepSeek API
  social/
    __init__.py           # SOCIAL_READERS dict
    base.py               # Abstract SocialReader interface
    article_fetcher.py    # Fetch article metadata (title, description) from URLs
    bluesky.py            # Bluesky AT Protocol reader (authenticated search)
    mastodon.py           # Mastodon REST API reader (hashtag timelines)
  tests/
    test_scorer.py
    test_store.py
    test_feed_reader.py
    test_feed_cache.py
    test_inbox_writer.py
    test_article_fetcher.py
    test_social_bluesky.py
    test_social_mastodon.py
    test_state.py
    fixtures/
      sample_feed.xml
      sample_scored.json
      sample_article.html
      sample_bluesky_response.json
      sample_mastodon_response.json
  .content-discovery.toml         # User config (gitignored)
  .content-discovery.toml.example # Template
```

## CLI Interface

The CLI uses Typer subcommands. All options are per-command (not global).

```bash
# Fetch and score RSS feeds (default)
uv run content_discovery.py run

# Include social sources
uv run content_discovery.py run --sources rss,bluesky,mastodon

# Dry run — print candidates, write nothing
uv run content_discovery.py run --dry-run

# Limit items scored (useful for testing)
uv run content_discovery.py run --cached --limit 20

# Single feed, specific provider
uv run content_discovery.py run --feed https://simonwillison.net/atom/everything/ --provider anthropic

# Review pending items interactively
uv run content_discovery.py review

# Print feed trend report (source quality, score distribution, top tags)
uv run content_discovery.py report

# Re-score all pending items with current profile + examples
uv run content_discovery.py rescore --provider groq

# Dismiss pending items from blocked domains
uv run content_discovery.py purge-blocked --dry-run
uv run content_discovery.py purge-blocked

# Dismiss pending items from a specific source (partial match, case-insensitive)
uv run content_discovery.py dismiss-source "Habr"

# Validate all configured RSS feeds
uv run content_discovery.py check-feeds

# Clear response cache
uv run content_discovery.py clear-cache
```

## Arguments Reference

Options are per-subcommand. `run` has the full set; other commands accept subsets.

### `run` options

| Option             | Short | Default                   | Description                                                   |
| ------------------ | ----- | ------------------------- | ------------------------------------------------------------- |
| `--provider`       | `-p`  | `local`                   | LLM backend: local, anthropic, groq, deepseek                 |
| `--model`          | `-m`  | provider-specific         | Override the default model for the chosen provider            |
| `--sources`        | `-s`  | `rss`                     | Comma-separated: rss, bluesky, mastodon                       |
| `--feed`           | `-f`  | none                      | Process a single feed URL instead of the full configured list |
| `--threshold`      | `-t`  | `0.7`                     | Minimum relevance score (0.0-1.0) to store a candidate        |
| `--dry-run`        | `-n`  | false                     | Print candidates to stdout; write nothing                     |
| `--cached`         |       | false                     | Use cached feed responses if available                        |
| `--limit`          | `-l`  | none                      | Cap items sent for scoring (after deduplication)              |
| `--no-dedup`       |       | false                     | Disable seen-item tracking, re-score everything               |
| `--verbose`        |       | false                     | Print scores for all items, not just those above threshold    |
| `--vault-path`     | `-v`  | env or config             | Path to the Obsidian vault root                               |
| `--inbox-path`     |       | `_finds/00-inbox.md`      | Path to the finds inbox, relative to vault root               |
| `--store`          |       | `~/.content-discovery.db` | Path to the SQLite database                                   |

### Other commands

`rescore` accepts: `--provider`, `--model`, `--threshold`, `--dry-run`, `--limit`, `--verbose`, `--store`
`purge-blocked`, `dismiss-source` accept: `--dry-run`, `--store`
`review`, `report` accept: `--store` (and `--vault-path`, `--inbox-path` for `review`)

## Configuration

All personal settings live in `.content-discovery.toml` (gitignored). Do not edit `config.py` directly.

### Feeds

```toml
[feeds]
urls = [
    "https://simonwillison.net/atom/everything/",
    # ...
]
```

### Interest Profile

Scoring uses a natural language prose description instead of keyword tags. The LLM scores each item for how relevant it is to this description. Edit to tune what gets surfaced.

```toml
[interests]
profile = """
I write and teach SQL and Python for working developers...
"""

# Optional: topics/formats to score low. Sent as "Not interested in: ..."
# exclusions = "JavaScript tutorials, YouTube videos, job listings, CVE feeds"
```

### Social Sources

```toml
[social]
keywords = ["duckdb", "python", "local ai", "ollama", "sql"]
mastodon_instances = ["mastodon.social", "fosstodon.org"]

# Extra domains to block (Medium network is blocked by default)
blocked_domains = ["nytimes.com", "youtube.com", "bsky.app"]
```

### Settings

```toml
[settings]
threshold = 0.7
provider = "local"
inbox_path = "_finds/00-inbox.md"
store = "~/sync/content-discovery/store.db"
# vault_path = "~/vaults/BrainSync/"
```

## Environment Variables

| Variable               | Purpose                                       | Example                             |
| ---------------------- | --------------------------------------------- | ----------------------------------- |
| `OBSIDIAN_VAULT_PATH`  | Vault root path                               | `~/vaults/BrainSync/`               |
| `ANTHROPIC_API_KEY`    | Anthropic API key                             | `sk-ant-...`                        |
| `GROQ_API_KEY`         | Groq API key                                  | `gsk_...`                           |
| `DEEPSEEK_API_KEY`     | DeepSeek API key                              | `sk-...`                            |
| `OLLAMA_HOST`          | Ollama server URL                             | `http://localhost:11434`            |
| `BLUESKY_HANDLE`       | Bluesky handle for authenticated search       | `you.bsky.social`                   |
| `BLUESKY_APP_PASSWORD` | Bluesky App Password (not your main password) | `xxxx-xxxx-xxxx-xxxx`               |
| `CONTENT_DISCOVERY_STORE` | SQLite DB path                             | `~/sync/content-discovery/store.db` |

## Provider Interface

Each provider implements this interface:

```python
class BaseProvider:
    def __init__(self, model: str | None = None): ...
    def complete(self, system_prompt: str, user_message: str) -> str: ...
    @property
    def default_model(self) -> str: ...
```

Default models per provider:

- **local**: `llama3.2:3b` (via Ollama)
- **anthropic**: `claude-haiku-4-5-20251001`
- **groq**: `llama-3.3-70b-versatile`
- **deepseek**: `deepseek-chat`

## The Scoring Prompt

The LLM returns a JSON object with four fields:

```json
{
  "score": 0.85,
  "tags": ["local AI", "ollama"],
  "summary": "A practical guide to building RAG pipelines with local models.",
  "language": "en"
}
```

- **score** 0.0–1.0: relevance to the interest profile
- **tags**: at most 2 short descriptive strings
- **summary**: one sentence, max 20 words
- **language**: ISO 639-1 two-letter code — non-English items are auto-dismissed

Few-shot examples from the review history (up to 10 kept + 10 dismissed titles) are included in the user message so the model learns from your actual behaviour over time.

## SQLite Store

`store.py` is the primary storage and deduplication layer. DB path configured via `[settings] store` or `CONTENT_DISCOVERY_STORE`.

```
items table
  id, url (UNIQUE), title, source, description
  score, tags (JSON text), summary
  status: 'new' | 'kept' | 'dismissed'
  fetched_at (ISO date), reviewed_at (ISO datetime, nullable)
```

Key functions:
- `init_db(path)` — create table if not exists, idempotent
- `is_seen(url, path)` — dedup check
- `upsert_item(...)` — INSERT OR IGNORE (never overwrites kept/dismissed)
- `get_new_items(path)` — returns status='new', ordered by score DESC
- `mark_item(url, status, path)` — update status + reviewed_at
- `dismiss_items_by_urls(urls, path)` — bulk dismiss by URL list
- `update_item_score(url, score, tags, summary, path)` — update scoring fields (used by --rescore)
- `get_examples(n, path)` — `{'kept': [...titles], 'dismissed': [...titles]}` for few-shot prompt
- `get_status_summary(path)` — per-status counts and avg scores
- `get_daily_counts(path, days)` — per-day item counts for report
- `get_source_stats(path, min_items)` — sources ranked by avg score
- `get_tag_counts(path, status, limit)` — most common tags for a given status
- `get_score_distribution(path, status)` — item counts in 0.1-wide score buckets

## URL Cleaning

`url_utils.clean_url()` strips tracking query parameters from all URLs before they are stored. Applied to both RSS item links and social-sourced URLs.

Stripped params: `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, `fbclid`, `gclid`, `mc_eid`, `ref`, `source`.

Non-tracking query parameters are preserved.

## Inbox Format

Only kept items reach the Obsidian inbox (written at review time):

```markdown
- [ ] [Item Title](https://item-url.com)
  - **Source**: Simon Willison's Weblog
  - **Score**: 0.85
  - **Tags**: #local-ai #llm
  - **Summary**: A practical guide to building RAG pipelines with local models.
  - **Fetched**: 2026-03-07
```

The inbox file is append-only. Created with a header if it does not exist.

## Error Handling

- Feed unreachable: log and continue with remaining feeds
- LLM returns invalid JSON: log raw response, skip the item (item not stored — will retry next run)
- Non-English article: stored dismissed automatically (not surfaced for review)
- Provider unavailable (Ollama not running, bad API key): fail fast before fetching any feeds
- Vault path missing: checked at review time before writing, not at score time
- `--dry-run`: skips DB write entirely, prints candidates to stdout only

## Testing

```bash
uv run pytest
```

178 tests across 9 test files. All use `tmp_path` for file I/O; no real network calls; no real DB.

- `test_scorer.py` — prompt construction, JSON parsing, language field, few-shot examples
- `test_store.py` — SQLite round-trips, dedup, mark, examples, report queries, score distribution
- `test_feed_reader.py` — feedparser wrapper, item extraction
- `test_feed_cache.py` — cache save/load, TTL expiry
- `test_inbox_writer.py` — append-to-existing, create-new, checkbox format
- `test_article_fetcher.py` — metadata extraction, blocked domains, URL validation, clean_url
- `test_social_bluesky.py` — AT Protocol reader, auth, URL extraction, deduplication
- `test_social_mastodon.py` — hashtag timeline reader, multi-instance, deduplication
- `test_state.py` — legacy JSON state (kept for compat)

## Dependencies

- `feedparser` — RSS/Atom parsing
- `requests` — HTTP for feeds, Ollama API, social APIs
- `beautifulsoup4` — HTML parsing for article metadata extraction
- `anthropic` — Anthropic provider
- `groq` — Groq provider
- `openai` — DeepSeek provider (OpenAI-compatible API)
- `pytest` — dev dependency
- `sqlite3` — standard library, no install needed

## Scheduling

```
0 8,17 * * * cd ~/projects/content-discovery-agent && uv run content_discovery.py >> ~/.content-discovery.log 2>&1
```

Configure the cron job on **one machine only** to avoid concurrent SQLite writes. Use a cloud provider (`--provider groq`) when running on a machine without Ollama.

Review separately whenever convenient — pending items accumulate in the DB until triaged.
