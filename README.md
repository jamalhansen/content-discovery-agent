# Content Discovery Agent

CLI tool that monitors RSS feeds, social media, and your Readwise Reader unread queue for articles relevant to your interests, scores each item using an LLM, and surfaces candidates for interactive review. Designed to run on a cron schedule.

## What It Does

1. Fetches items from configured RSS feeds, Bluesky keyword searches, Mastodon hashtag timelines, and your Readwise Reader "new" queue (`--sources reader`, requires `READWISE_TOKEN`)
2. Scores each article against a natural language interest profile via an LLM
3. Stores candidates in a local SQLite database
4. Skips items already seen in previous runs (deduplication)
5. Optionally routes above-threshold candidates to Readwise Reader automatically during `run` (`readwise_routing = true`)
6. Optionally captures the same candidates as markdown files in an Obsidian vault's `inbox/` directory (`contexta_inbox_routing = true`)
7. Lets you review candidates interactively: keep or dismiss each one
8. Sends kept items to your Readwise Reader inbox via the API, and to the vault inbox if enabled

The scorer improves over time: after you review items, your kept/dismissed history is used as few-shot examples in subsequent scoring runs.

## Installation

```bash
# Requires uv
uv sync
```

## Configuration

The agent is configured via a `.content-discovery.toml` file in the project root. Copy the example to get started:

```bash
cp .content-discovery.toml.example .content-discovery.toml
```

Edit the file to add your RSS feeds, define your interest profile, and set your preferences.

### LLM Selection

By default, the tool uses the `@best` alias on your local provider (Ollama). This automatically selects the most capable model installed on your machine. You can override this in your config:

```toml
[settings]
provider = "local"
model = "@fast"  # Use a lower-latency model

# Optional: use a different provider/model specifically for scoring (e.g. scheduled batch on Pi)
# scoring_provider = "groq"
# scoring_model = "llama-3.3-70b-versatile"

# Optional: use a different provider/model for interactive review (e.g. better model on Mac)
# review_provider = "anthropic"
# review_model = "claude-3-5-sonnet-latest"
```

The scoring and review providers can be different. A typical setup uses a cheap/fast model for
batch scoring (runs on a schedule) and a higher-quality model for interactive review sessions.

Or via environment variables:

```bash
export MODEL_PROVIDER="anthropic"
export MODEL_NAME="claude-3-5-sonnet-latest"
```

### Vault Inbox Integration

Route kept candidates into an Obsidian vault's `inbox/` directory as individual markdown files, alongside or instead of Readwise routing:

```toml
[settings]
contexta_inbox_routing = true
contexta_inbox_path = "~/vaults/Contexta/inbox"   # default shown; override per vault
```

`CONTEXTA_INBOX_PATH` as an environment variable overrides the config value. Each kept item becomes one file (`YYYY-MM-DD-<slugified-title>.md`) with light frontmatter (source URL, tags, capture date) and the LLM-generated summary. No further structure is imposed; a vault's own processing pipeline (`/reduce`, etc.) takes it from there. This applies to all three ways an item gets kept: automatic routing during `run` (above-threshold candidates), the `review` command, and `save URL`.

During interactive `review`, routing isn't all-or-nothing: the `r` and `c` keys let you send an individual item to Readwise-only or Contexta-only regardless of the global `contexta_inbox_routing` setting. `y` still means "keep, routed per config" (both destinations if the toggle is on).

## How I use it with cloud model
```bash
uv run discover run --scoring-provider anthropic --sources rss,mastodon,bluesky    
```


## Quick Start

### 1. Set Up Your Environment

```bash
export READWISE_TOKEN="your_token"
export ANTHROPIC_API_KEY="your_key"
# See local-first-common docs for all provider keys
```

### 2. Fetch and score

```bash
# RSS feeds only (default)
uv run discover run

# Include Bluesky and Mastodon as additional sources
uv run discover run --sources rss,bluesky,mastodon

# Pull your Readwise Reader unread queue too (requires READWISE_TOKEN)
uv run discover run --sources rss,reader

# Dry run: print candidates, write nothing
uv run discover run --dry-run

# Skip LLM entirely (for testing CLI args without inference)
uv run discover run --no-llm
```

### 3. Review

```bash
uv run discover review
```

Shows each candidate one at a time. Commands: `y` keep (routes per your config) · `n` dismiss · `s` stop · `o` open URL in browser · `r` keep, Readwise only for this item · `c` keep, Contexta only for this item. `r` and `c` are per-item overrides: they work regardless of whether `contexta_inbox_routing` is on, so you can redirect a specific item to Contexta even on a run where the default is Readwise, or vice versa.

---

## CLI Reference

All tools in this series share a common set of CLI flags for model management (`-p`, `-m`, `-n`, `-v`, `-d`) via [local-first-common](https://github.com/jamalhansen/local-first-common).

### Commands

| Command | Description |
|---|---|
| `run` | Fetch feeds, score items, store candidates (default operation) |
| `review` | Interactively triage pending items; send kept items to Readwise Reader (and the vault inbox, if enabled) |
| `report` | Feed trend report: source quality, score distribution, top tags |
| `rescore` | Re-score all pending items with current profile and examples |
| `purge-blocked` | Dismiss pending items from blocked domains |
| `dismiss-source QUERY` | Dismiss pending items whose source contains QUERY |
| `check-feeds` | Fetch all configured feeds and report their status |
| `save URL` | Fetch, score, and send a URL directly to Readwise Reader as a kept item |
| `backup` | Copy the database to a timestamped backup file |
| `restore` | Restore the database from a backup (requires confirmation) |
| `clear-cache` | Delete all cached feed and social responses |

---

## Project Structure

This tool follows the [Local-First AI project blueprint](https://github.com/jamalhansen/local-first-common).

```
content-discovery-agent/
├── src/
│   ├── main.py           # Typer CLI entry point
│   ├── logic.py          # Core triage orchestration
│   ├── config.py         # Feeds, interest profile, social config
│   ├── store.py          # SQLite storage layer
│   ├── scorer.py         # Prompt construction and JSON parsing
│   ├── feed_reader.py    # RSS feed parser
│   ├── feed_cache.py     # Cache for social/RSS responses
│   ├── readwise.py       # Readwise Reader API integration
│   ├── vault_inbox.py    # Obsidian vault inbox/ capture
│   └── social/           # Readers using local_first_common.social
│       ├── article_fetcher.py
│       ├── bluesky.py
│       └── mastodon.py
├── pyproject.toml        # Managed by uv
└── tests/                # Comprehensive test suite
```

## Running Tests

```bash
uv run pytest
```

217 tests across 12 test files.
