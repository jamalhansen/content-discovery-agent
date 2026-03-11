# Content Discovery Agent

CLI tool that monitors RSS feeds and social media for articles relevant to your interests, scores each item using an LLM, and surfaces candidates for interactive review. Designed to run on a cron schedule.

## What It Does

1. Fetches items from configured RSS feeds, Bluesky keyword searches, and Mastodon hashtag timelines
2. Scores each article against a natural language interest profile via an LLM
3. Stores candidates in a local SQLite database
4. Skips items already seen in previous runs (deduplication)
5. Lets you review candidates interactively — keep or dismiss each one
6. Writes only the items you keep to your Obsidian inbox

The scorer improves over time: after you review items, your kept/dismissed history is used as few-shot examples in subsequent scoring runs.

## Installation

```bash
# Requires uv
uv sync
```

## Workflow

### 1. Fetch and score

```bash
# RSS feeds only (default)
uv run content_discovery.py run

# Include Bluesky and Mastodon as additional sources
uv run content_discovery.py run --sources rss,bluesky,mastodon

# Dry run — print candidates, write nothing
uv run content_discovery.py run --dry-run

# Single feed, cloud provider
uv run content_discovery.py run --feed https://simonwillison.net/atom/everything/ --provider anthropic

# Limit items scored (useful for testing)
uv run content_discovery.py run --cached --limit 20
```

### 2. Review

```bash
uv run content_discovery.py review
```

Shows each candidate one at a time:

```
[1/8]  Agentic manual testing
  Source:  Simon Willison's Weblog
  Score:   0.90  |  Tags: #testing #agentic-engineering #ai
  Summary: Using coding agents for manual testing to catch issues automated tests miss.
  URL:     https://simonwillison.net/...
  >
```

Commands: `y` keep · `n` dismiss · `s` stop · `o` open URL in browser

Kept items are written to your Obsidian inbox. Dismissed items are recorded and used to improve future scoring.

### 3. Report

```bash
uv run content_discovery.py report
```

Prints a summary of feed performance pulled from the database:

```
════════════════════════════════════════════════════════════
  Content Discovery — Feed Report
════════════════════════════════════════════════════════════

  Overview                           Items  Avg score
────────────────────────────────────────────────────────────
  Pending                              229       0.83
  Kept                                  50       0.83
  Dismissed                            493       0.39
  Total                                772

  Activity — last 7 days
  Top sources by avg score
  Low-signal sources  (high volume, low avg score — where to cut feeds)
  Most common tags in kept items
  Pending queue — top 5 items waiting for review
```

Useful for tuning the feed list: sources with low avg scores are burning scoring budget without surfacing relevant content.

### 4. Purge blocked domains

```bash
# Preview what would be dismissed (safe — writes nothing)
uv run content_discovery.py purge-blocked --dry-run

# Dismiss all pending items whose URLs match the current blocklist
uv run content_discovery.py purge-blocked
```

Useful after updating `blocked_domains` in your config: any items already in the pending queue from newly-blocked domains are dismissed in bulk without going through interactive review. Only `status='new'` items are affected — kept items are never touched.

### 5. Rescore pending items

```bash
# Preview what would change (no writes)
uv run content_discovery.py rescore --dry-run --verbose

# Re-score all pending items with current profile
uv run content_discovery.py rescore --provider groq
```

Re-scores every pending item using the current interest profile and your latest review history as few-shot examples. Useful after significantly editing your profile or after accumulating a lot of review history. Items that fall below threshold (or are detected as non-English) are dismissed. Accepts `--limit` and `--verbose`.

### 6. Dismiss by source

```bash
# Preview
uv run content_discovery.py dismiss-source "Habr" --dry-run

# Dismiss
uv run content_discovery.py dismiss-source "Habr"
```

Dismisses all pending items whose source name contains the query string (case-insensitive). Useful after seeing a low-signal source in `--report` — dismiss its backlog before removing it from your feed list.

### 7. Feed health check

```bash
uv run content_discovery.py check-feeds
```

Fetches every configured RSS feed and reports how many items it returned. Flags feeds that return nothing or fail to load — useful for catching broken or moved feeds before they silently drop off.

### 8. Cache management

```bash
# Fetch and cache responses (auto-expires after 12 hours)
uv run content_discovery.py run --cached --sources rss,bluesky

# Wipe all cached responses manually
uv run content_discovery.py clear-cache
```

## CLI Reference

The CLI uses subcommands. Run any command with `--help` to see its options.

### Commands

| Command | Description |
|---|---|
| `run` | Fetch feeds, score items, store candidates (default operation) |
| `review` | Interactively triage pending items; write kept items to Obsidian |
| `report` | Feed trend report: source quality, score distribution, top tags |
| `rescore` | Re-score all pending items with current profile and examples |
| `purge-blocked` | Dismiss pending items from blocked domains |
| `dismiss-source QUERY` | Dismiss pending items whose source contains QUERY |
| `check-feeds` | Fetch all configured feeds and report their status |
| `clear-cache` | Delete all cached feed and social responses |
| `migrate-inbox` | Reformat existing inbox items to the current format |

### `run` options

| Option | Short | Default | Description |
|---|---|---|---|
| `--provider` | `-p` | `local` | LLM backend: `local`, `anthropic`, `groq`, `deepseek` |
| `--model` | `-m` | provider default | Override the default model for the chosen provider |
| `--sources` | `-s` | `rss` | Comma-separated: `rss`, `bluesky`, `mastodon` |
| `--feed` | `-f` | none | Process a single RSS feed URL instead of the configured list |
| `--threshold` | `-t` | `0.7` | Minimum relevance score (0.0–1.0) |
| `--dry-run` | `-n` | false | Print candidates to stdout; write nothing |
| `--cached` | | false | Use cached responses when available (12h TTL) |
| `--limit` | `-l` | none | Cap items scored after deduplication |
| `--no-dedup` | | false | Re-score items already seen |
| `--verbose` | | false | Show scores for all items, not just candidates |
| `--vault-path` | `-v` | `OBSIDIAN_VAULT_PATH` | Path to the Obsidian vault root |
| `--inbox-path` | | `_finds/00-inbox.md` | Inbox path relative to vault root |
| `--store` | | `~/.content-discovery.db` | Path to the SQLite database |

### Shared options

`--provider`, `--model`, `--threshold`, `--dry-run`, `--limit`, `--verbose`, and `--store` are also available on `rescore`. `--dry-run` and `--store` are available on `purge-blocked` and `dismiss-source`. `--store` is available on `review` and `report`.

## Configuration

All personal settings live in `.content-discovery.toml` (gitignored). Copy the example to get started:

```bash
cp .content-discovery.toml.example .content-discovery.toml
```

### Feeds

```toml
[feeds]
urls = [
    "https://simonwillison.net/atom/everything/",
    "https://jvns.ca/atom.xml",
    # ...
]
```

### Interest Profile

Instead of keyword tags, the scorer uses a prose description of your interests. Edit this to tune what gets surfaced:

```toml
[interests]
profile = """
I write and teach SQL and Python for working developers. I'm interested in local-first AI,
LLM systems and evaluation, DuckDB, and practical data engineering. I also follow technical
writing craft and note-taking workflows.
"""
```

The profile is passed directly to the LLM on every scoring run. Adding a topic is as simple as mentioning it here.

### Exclusions

An optional prose list of topics, formats, and sources you don't want surfaced. Included in every prompt as "Not interested in: ..." alongside the interest profile. Use this to suppress content that scores high but you consistently dismiss.

```toml
[interests]
profile = """..."""

exclusions = """
JavaScript/React/CSS tutorials, YouTube videos, job listings,
non-English content, personal lifestyle newsletters,
security CVE feeds, generic AI opinion pieces without technical depth.
"""
```

After adding exclusions, run `rescore` to apply them to your existing pending queue.

### Social Sources

Configure keywords for Bluesky search and Mastodon hashtag timelines. Multi-word keywords work as-is in Bluesky; spaces are stripped for Mastodon hashtags (`"local ai"` → `#localai`).

```toml
[social]
keywords = ["duckdb", "python", "local ai", "ollama", "sql"]
mastodon_instances = ["mastodon.social", "fosstodon.org"]

# Extra domains to skip on top of the built-in blocklist.
# Subdomain matching is automatic — "nytimes.com" also blocks "www.nytimes.com".
blocked_domains = ["nytimes.com", "wsj.com", "youtube.com", "youtu.be"]
```

Social sources are only used when `--sources` includes `bluesky` or `mastodon`. The default (`rss`) leaves existing cron jobs unaffected.

#### Domain blocklist

The article fetcher skips known bot-blocking and low-signal domains before making any HTTP request. The following are blocked by default (no config needed):

| Domain | Reason |
|---|---|
| `medium.com` + subdomains | Blocks scrapers; includes `username.medium.com` |
| `towardsdatascience.com` | Medium publication |
| `betterprogramming.pub` | Medium publication |
| `plainenglish.io` + subdomains | Medium publication network |
| `levelup.gitconnected.com` | Medium publication |

Add any others in `[social] blocked_domains`. Common additions: `nytimes.com`, `wsj.com`, `youtube.com`, `youtu.be`, `x.com`, `bsky.app` (Bluesky search pages), `jobsfordevelopers.com`.

### Settings

```toml
[settings]
threshold = 0.7         # minimum score to store a candidate
provider = "local"      # default LLM backend
inbox_path = "_finds/00-inbox.md"
# vault_path = "~/vaults/MyVault/"
```

## Environment Variables

| Variable                   | Purpose                                      | Example                             |
|----------------------------|----------------------------------------------|-------------------------------------|
| `OBSIDIAN_VAULT_PATH`      | Vault root path                              | `~/vaults/BrainSync/`               |
| `CONTENT_DISCOVERY_STORE`  | SQLite DB path (machine-specific)            | `~/sync/content-discovery/store.db` |
| `ANTHROPIC_API_KEY`        | Anthropic API key                            | `sk-ant-...`                        |
| `GROQ_API_KEY`             | Groq API key                                 | `gsk_...`                           |
| `DEEPSEEK_API_KEY`         | DeepSeek API key                             | `sk-...`                            |
| `OLLAMA_HOST`              | Ollama server URL                            | `http://localhost:11434`            |
| `BLUESKY_HANDLE`           | Bluesky handle for authenticated search      | `you.bsky.social`                   |
| `BLUESKY_APP_PASSWORD`     | Bluesky App Password (not your main password)| `xxxx-xxxx-xxxx-xxxx`               |

> **Bluesky auth note:** Bluesky's public search endpoint (`public.api.bsky.app`) intermittently returns 403 for unauthenticated requests. Setting `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` switches to authenticated requests which are reliably served. Generate an App Password in Bluesky → Settings → Privacy and Security → App Passwords.

## Providers

| Provider    | Default Model               | Notes                           |
|-------------|-----------------------------|---------------------------------|
| `local`     | `llama3.2:3b`               | Requires Ollama running locally |
| `anthropic` | `claude-haiku-4-5-20251001` | Requires `ANTHROPIC_API_KEY`    |
| `groq`      | `llama-3.3-70b-versatile`   | Requires `GROQ_API_KEY`         |
| `deepseek`  | `deepseek-chat`             | Requires `DEEPSEEK_API_KEY`     |

## How Scoring Improves Over Time

On each run, the scorer pulls your 10 most recently kept and 10 most recently dismissed item titles from the database and includes them as few-shot examples in the prompt. The model sees your actual behaviour rather than just a description of your interests.

The system works without any review history — it starts with the interest profile alone and gets sharper as you review more items.

## Multi-machine Sync

The database is a single SQLite file. [Syncthing](https://syncthing.net) keeps it in sync across machines with no cloud dependency — devices discover each other automatically on your local network, and via Syncthing's free relay servers when on different networks.

### Setup

**1. Create a dedicated sync folder on each machine:**

```bash
mkdir -p ~/sync/content-discovery
```

**2. Set the store path in `.content-discovery.toml`:**

```toml
[settings]
store = "~/sync/content-discovery/store.db"
```

**3. Install Syncthing:**

```bash
# macOS
brew install syncthing

# Raspberry Pi / Debian
sudo apt install syncthing
```

**4. Start Syncthing and open the web UI:**

```bash
syncthing &
open http://127.0.0.1:8384
```

**5. Pair devices and share the folder:**

- Copy the Device ID from one machine's web UI (Actions → Show ID)
- On the other machine, go to Add Remote Device and paste the ID
- Share the `~/sync/content-discovery/` folder with the remote device on both sides
- Syncthing will sync the folder automatically whenever both machines are reachable

### Single-writer discipline

SQLite handles one writer at a time. For a personal tool with twice-daily cron runs and manual review, this is never a real problem in practice — just avoid running the cron job on two machines simultaneously. The simplest approach: configure the cron job on one machine only, and run manually from others when you want local Ollama.

### Adding a Raspberry Pi later

A Pi makes a good always-on persistence node — it keeps the DB current so whichever Mac comes online next syncs immediately. Add it to Syncthing like any other device, then optionally move the cron job there (using a cloud provider like Groq or Anthropic) so scoring happens regardless of whether your Macs are awake.

## Scheduling

Run via cron twice daily. Configure the cron job on **one machine** to avoid concurrent writes:

```
0 8,17 * * * cd ~/projects/content-discovery-agent && uv run content_discovery.py run >> ~/.content-discovery.log 2>&1
```

To use a cloud provider (required if running on a Pi or a machine without Ollama):

```
0 8,17 * * * cd ~/projects/content-discovery-agent && uv run content_discovery.py run --provider groq >> ~/.content-discovery.log 2>&1
```

Review whenever convenient — pending items accumulate in the database until you triage them.

## Project Structure

```
content-discovery-agent/
  content_discovery.py    # CLI entrypoint (all commands)
  config.py               # Feeds, interest profile, social config, defaults, env vars
  store.py                # SQLite storage layer
  scorer.py               # Prompt construction and JSON parsing (score, tags, summary, language)
  feed_reader.py          # feedparser wrapper
  feed_cache.py           # RSS and social response caching (12h TTL)
  inbox_writer.py         # Obsidian inbox append logic
  url_utils.py            # clean_url() — strips UTM and tracking params
  social/
    __init__.py           # SOCIAL_READERS dict
    base.py               # Abstract SocialReader interface
    article_fetcher.py    # Fetch article metadata (title, description) from URLs
    bluesky.py            # Bluesky AT Protocol reader
    mastodon.py           # Mastodon REST API reader
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
    test_feed_cache.py
    test_inbox_writer.py
    test_store.py
    test_article_fetcher.py
    test_social_bluesky.py
    test_social_mastodon.py
    fixtures/
      sample_feed.xml
      sample_scored.json
      sample_article.html
      sample_bluesky_response.json
      sample_mastodon_response.json
  .content-discovery.toml         # Your personal config (gitignored)
  .content-discovery.toml.example # Template
```

## Running Tests

```bash
uv run pytest
```
