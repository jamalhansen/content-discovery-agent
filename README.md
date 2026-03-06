# Content Discovery Agent

CLI tool that monitors RSS feeds, scores each item for relevance using an LLM, and appends candidates to an Obsidian finds inbox. Designed to run on a cron schedule.

## What It Does

1. Fetches items from a configured list of RSS feeds
2. Scores each item's relevance to your topic tags via an LLM
3. Filters out items below a relevance threshold
4. Appends surviving items to `_finds/00-inbox.md` in your Obsidian vault
5. Tracks seen items to avoid duplicates across runs

## Installation

```bash
# Requires uv
uv sync
```

## Usage

```bash
# Run with default settings (Ollama, all configured feeds)
uv run content_discovery.py

# Dry run — print candidates without writing to inbox
uv run content_discovery.py --dry-run

# Use a cloud provider
uv run content_discovery.py --provider anthropic
uv run content_discovery.py --provider groq
uv run content_discovery.py --provider deepseek

# Process a single feed
uv run content_discovery.py --feed https://simonwillison.net/atom/everything/

# Adjust relevance threshold
uv run content_discovery.py --threshold 0.7

# Verbose: show scores for all items
uv run content_discovery.py --verbose

# Skip deduplication (re-score everything)
uv run content_discovery.py --no-dedup

# Custom vault and inbox path
uv run content_discovery.py --vault-path ~/vaults/MyVault/ --inbox-path _finds/00-inbox.md
```

## CLI Reference

| Argument       | Short | Default                      | Description                                              |
|----------------|-------|------------------------------|----------------------------------------------------------|
| `--provider`   | `-p`  | `local`                      | LLM backend: `local`, `anthropic`, `groq`, `deepseek`   |
| `--model`      | `-m`  | provider default             | Override the default model for the chosen provider       |
| `--dry-run`    | `-n`  | false                        | Print candidates to stdout instead of writing to inbox   |
| `--feed`       | `-f`  | none                         | Process a single feed URL instead of the full list       |
| `--threshold`  | `-t`  | `0.6`                        | Minimum relevance score (0.0–1.0) to include an item     |
| `--vault-path` | `-v`  | env or `~/vaults/BrainSync/` | Path to the Obsidian vault root                          |
| `--inbox-path` |       | `_finds/00-inbox.md`         | Inbox path relative to vault root                        |
| `--no-dedup`   |       | false                        | Disable seen-item tracking, re-score everything          |
| `--verbose`    |       | false                        | Show scores for all items, not just candidates           |

## Configuration

Edit `config.py` to set your feeds and topic tags:

```python
FEEDS = [
    "https://simonwillison.net/atom/everything/",
    "https://news.ycombinator.com/rss",
    # ...
]

TOPIC_TAGS = [
    "python", "sql", "duckdb", "local-ai", "llm",
    "data-engineering", "vector-databases", "rag", "ollama", "pydantic",
]
```

## Environment Variables

| Variable              | Purpose           | Example                  |
|-----------------------|-------------------|--------------------------|
| `OBSIDIAN_VAULT_PATH` | Vault root path   | `~/vaults/BrainSync/`    |
| `ANTHROPIC_API_KEY`   | Anthropic API key | `sk-ant-...`             |
| `GROQ_API_KEY`        | Groq API key      | `gsk_...`                |
| `DEEPSEEK_API_KEY`    | DeepSeek API key  | `sk-...`                 |
| `OLLAMA_HOST`         | Ollama server URL | `http://localhost:11434` |

## Providers

| Provider    | Default Model              | Notes                              |
|-------------|----------------------------|------------------------------------|
| `local`     | `llama3.2:3b`              | Requires Ollama running locally    |
| `anthropic` | `claude-haiku-4-5-20251001`| Requires `ANTHROPIC_API_KEY`       |
| `groq`      | `llama-3.3-70b-versatile`  | Requires `GROQ_API_KEY`            |
| `deepseek`  | `deepseek-chat`            | Requires `DEEPSEEK_API_KEY`        |

## Scheduling

Run via cron twice daily:

```
0 8,17 * * * cd ~/projects/content-discovery-agent && uv run content_discovery.py >> ~/.content-discovery.log 2>&1
```

## Project Structure

```
content-discovery-agent/
  content_discovery.py    # CLI entrypoint
  config.py               # Feeds, topic tags, defaults
  scorer.py               # Prompt construction and JSON parsing
  feed_reader.py          # feedparser wrapper and deduplication
  inbox_writer.py         # Obsidian inbox append logic
  state.py                # Seen-item tracking (JSON file)
  providers/
    __init__.py           # PROVIDERS dict
    base.py               # Abstract provider interface
    local.py              # Ollama provider
    anthropic_provider.py
    groq_provider.py
    deepseek_provider.py
  tests/
    test_scorer.py
    test_feed_reader.py
    test_inbox_writer.py
    test_state.py
    fixtures/
      sample_feed.xml
      sample_scored.json
```

## Running Tests

```bash
uv run pytest
```
