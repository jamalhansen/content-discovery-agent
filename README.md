# Content Discovery Agent

CLI tool that monitors RSS feeds and social media for articles relevant to your interests, scores each item using an LLM, and surfaces candidates for interactive review. Designed to run on a cron schedule.

## What It Does

1. Fetches items from configured RSS feeds, Bluesky keyword searches, and Mastodon hashtag timelines
2. Scores each article against a natural language interest profile via an LLM
3. Stores candidates in a local SQLite database
4. Skips items already seen in previous runs (deduplication)
5. Lets you review candidates interactively — keep or dismiss each one
6. Sends kept items to your Readwise Reader inbox via the API

The scorer improves over time: after you review items, your kept/dismissed history is used as few-shot examples in subsequent scoring runs.

## Installation

```bash
# Requires uv
uv sync
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
uv run main.py run

# Include Bluesky and Mastodon as additional sources
uv run main.py run --sources rss,bluesky,mastodon

# Dry run — print candidates, write nothing
uv run main.py run --dry-run
```

### 3. Review

```bash
uv run main.py review
```

Shows each candidate one at a time. Commands: `y` keep · `n` dismiss · `s` stop · `o` open URL in browser.

---

## CLI Reference

All tools in this series share a common set of CLI flags for model management (`-p`, `-m`, `-n`, `-v`, `-d`).

### Commands

| Command | Description |
|---|---|
| `run` | Fetch feeds, score items, store candidates (default operation) |
| `review` | Interactively triage pending items; send kept items to Readwise Reader |
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
├── main.py               # Canonical entrypoint
├── content_discovery.py  # CLI command definitions
├── config.py             # Feeds, interest profile, social config
├── store.py              # SQLite storage layer
├── scorer.py             # Prompt construction and JSON parsing
├── feed_reader.py        # RSS feed parser
├── feed_cache.py         # Cache for social/RSS responses
├── readwise.py           # Readwise Reader API integration
├── social/               # Readers using local_first_common.social
│   ├── article_fetcher.py
│   ├── bluesky.py
│   └── mastodon.py
├── pyproject.toml        # Managed by uv
└── tests/                # Comprehensive test suite
```

## Running Tests

```bash
uv run pytest
```
