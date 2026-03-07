Content Discovery Agent

## Project Overview

CLI tool that monitors RSS feeds, scores each item for relevance using an LLM, and stores candidates in SQLite for interactive review. Runs on a schedule. The user reviews candidates in the terminal and decides what gets written to the Obsidian inbox.

The LLM's job is narrow: read a feed item's title and description, score its relevance against a natural language interest profile, generate a one-line summary, and return structured JSON. No complex reasoning, no long context. A small local model handles this easily.

## What This Tool Does

1. Fetches items from a configured list of RSS feeds
2. Sends each item to an LLM with a relevance-scoring prompt (interest profile + few-shot examples)
3. Stores all scored items above the threshold in a local SQLite database
4. Skips items already in the database (deduplication)
5. User runs `--review` to triage candidates interactively (y/n/s/o)
6. Kept items are written to the Obsidian inbox; dismissed items become negative examples for future runs

## Architecture

```
content-discovery-agent/
  content_discovery.py    # CLI entrypoint (argparse) — run + review commands
  store.py                # SQLite storage layer — items, dedup, examples
  scorer.py               # Prompt construction + response parsing
  feed_reader.py          # feedparser wrapper
  feed_cache.py           # Feed response caching
  inbox_writer.py         # Obsidian inbox append logic (used at review time)
  config.py               # Feeds, interest profile, defaults, env vars
  state.py                # Legacy JSON dedup — superseded by store.py, kept for compat
  providers/
    __init__.py           # PROVIDERS dict
    base.py               # Abstract provider interface
    local.py              # Ollama provider
    anthropic_provider.py # Anthropic API (Claude)
    groq_provider.py      # Groq API
    deepseek_provider.py  # DeepSeek API
  tests/
    test_scorer.py
    test_feed_reader.py
    test_inbox_writer.py
    test_store.py
    test_state.py
    fixtures/
      sample_feed.xml
      sample_scored.json
  .content-discovery.toml         # User config (gitignored)
  .content-discovery.toml.example # Template
```

## CLI Interface

```bash
# Fetch and score all configured feeds (stores to DB)
uv run content_discovery.py

# Dry run — print candidates, write nothing
uv run content_discovery.py --dry-run

# Limit items scored (useful for testing)
uv run content_discovery.py --cached --limit 20

# Single feed
uv run content_discovery.py --feed https://simonwillison.net/atom/everything/

# Cloud provider
uv run content_discovery.py --provider anthropic

# Review pending items interactively
uv run content_discovery.py --review
```

## Arguments Reference

| Argument       | Short | Default                   | Description                                                   |
| -------------- | ----- | ------------------------- | ------------------------------------------------------------- |
| `--provider`   | `-p`  | `local`                   | LLM backend: local, anthropic, groq, deepseek                 |
| `--model`      | `-m`  | provider-specific         | Override the default model for the chosen provider            |
| `--dry-run`    | `-n`  | false                     | Print candidates to stdout; write nothing                     |
| `--review`     |       | false                     | Interactively review pending items (y/n/s/o)                  |
| `--feed`       | `-f`  | none                      | Process a single feed URL instead of the full configured list |
| `--threshold`  | `-t`  | `0.7`                     | Minimum relevance score (0.0-1.0) to store a candidate        |
| `--vault-path` | `-v`  | env or config             | Path to the Obsidian vault root                               |
| `--inbox-path` |       | `_finds/00-inbox.md`      | Path to the finds inbox, relative to vault root               |
| `--no-dedup`   |       | false                     | Disable seen-item tracking, re-score everything               |
| `--verbose`    |       | false                     | Print scores for all items, not just those above threshold    |
| `--cached`     |       | false                     | Use cached feed responses if available                        |
| `--limit`      | `-l`  | none                      | Cap items sent for scoring (after deduplication)              |
| `--store`      |       | `~/.content-discovery.db` | Path to the SQLite database                                   |

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
```

### Settings

```toml
[settings]
threshold = 0.7
provider = "local"
inbox_path = "_finds/00-inbox.md"
# vault_path = "~/vaults/BrainSync/"
```

## Environment Variables

| Variable              | Purpose           | Example                  |
| --------------------- | ----------------- | ------------------------ |
| `OBSIDIAN_VAULT_PATH` | Vault root path   | `~/vaults/BrainSync/`    |
| `ANTHROPIC_API_KEY`   | Anthropic API key | `sk-ant-...`             |
| `GROQ_API_KEY`        | Groq API key      | `gsk_...`                |
| `DEEPSEEK_API_KEY`    | DeepSeek API key  | `sk-...`                 |
| `OLLAMA_HOST`         | Ollama server URL | `http://localhost:11434` |

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

**System prompt:**

```
You are a content relevance scorer. Given a feed item and a description of someone's interests,
return a JSON object with exactly these fields:

- score: float 0.0-1.0 representing how relevant this item is to the person's interests
- tags: array of 1-3 short strings describing what this item is actually about (descriptive, not from a fixed list)
- summary: one sentence describing what this item is about.

Return only valid JSON. No preamble, no explanation.
```

**User message format** (with few-shot examples when review history exists):

```
Interests: {interest_profile}

Recent items kept:
- "Title A"
- "Title B"

Recent items dismissed:
- "Title C"

Title: {item.title}
Description: {item.description}
```

**Expected response:**

```json
{
  "score": 0.85,
  "tags": ["local AI", "ollama", "RAG"],
  "summary": "A practical guide to building RAG pipelines with local models."
}
```

Strip markdown fences before parsing. If the response is not valid JSON, log the raw output and skip the item.

## SQLite Store

`store.py` is the primary storage and deduplication layer. DB path: `~/.content-discovery.db`.

```
items table
  id, url (UNIQUE), title, source, description
  score, tags (JSON text), summary
  status: 'new' | 'kept' | 'dismissed'
  fetched_at (ISO date), reviewed_at (ISO datetime, nullable)
```

Key functions:
- `init_db(path)` — create table if not exists, idempotent
- `is_seen(url, path)` — dedup check (replaces state.py)
- `upsert_item(...)` — INSERT OR IGNORE (never overwrites kept/dismissed)
- `get_new_items(path)` — returns status='new', ordered by score DESC
- `mark_item(url, status, path)` — update status + reviewed_at
- `get_examples(n, path)` — returns `{'kept': [...titles], 'dismissed': [...titles]}` for few-shot prompt

## Inbox Format

Only kept items reach the Obsidian inbox (written at review time):

```markdown
- [ ] [Item Title](https://item-url.com)
  - **Source**: Simon Willison's Weblog
  - **Score**: 0.85
  - **Tags**: #local-ai #llm #rag
  - **Summary**: A practical guide to building RAG pipelines with local models.
  - **Fetched**: 2026-03-07
```

The inbox file is append-only. Created with a header if it does not exist.

## Error Handling

- Feed unreachable: log and continue with remaining feeds
- LLM returns invalid JSON: log raw response, skip the item (item not stored, not marked seen — will retry next run)
- Provider unavailable (Ollama not running, bad API key): fail fast before fetching any feeds
- Vault path missing: checked at review time before writing, not at score time
- `--dry-run`: skips DB write entirely, prints candidates to stdout only

## Testing

```bash
uv run pytest
```

- `test_scorer.py` — prompt construction, JSON parsing, few-shot examples
- `test_store.py` — SQLite round-trips, dedup, mark, get_examples
- `test_feed_reader.py` — feedparser wrapper, item extraction
- `test_inbox_writer.py` — append-to-existing, create-new, checkbox format
- `test_state.py` — legacy JSON state (kept for compat)
- All tests use `tmp_path` for file I/O; no real network calls; no real DB

## Dependencies

- `feedparser` — RSS/Atom parsing
- `requests` — Ollama HTTP API
- `anthropic` — Anthropic provider
- `groq` — Groq provider
- `openai` — DeepSeek provider (OpenAI-compatible API)
- `pytest` — dev dependency
- `sqlite3` — standard library, no install needed

## Scheduling

```
0 8,17 * * * cd ~/projects/content-discovery-agent && uv run content_discovery.py >> ~/.content-discovery.log 2>&1
```

Review separately whenever convenient — pending items accumulate in the DB until triaged.

---

## Phase 2: Social Feed Sources

RSS covers most of the content worth tracking, but some good signal lives on social platforms.

### Bluesky

Public AT Protocol API, no authentication required.

```
GET https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=handle.bsky.social
GET https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=duckdb
```

### Mastodon

Public REST API, no authentication for public timelines.

```
GET https://mastodon.social/api/v1/timelines/tag/duckdb
GET https://mastodon.social/api/v1/accounts/{id}/statuses
```

### Phase 2 Architecture

```
content-discovery-agent/
  social/
    __init__.py
    base.py       # Abstract SocialReader interface
    bluesky.py    # AT Protocol reader
    mastodon.py   # Mastodon REST API reader
```

All social readers normalize to the same `FeedItem` datatype. The scorer, store, and inbox writer are unchanged.

**New CLI flag:**

```bash
uv run content_discovery.py --sources rss,bluesky,mastodon
```

Default stays RSS-only so existing cron jobs are unaffected.
