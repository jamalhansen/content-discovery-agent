# Content Discovery Agent

CLI tool that monitors RSS feeds, scores each item for relevance using an LLM, and surfaces candidates for review. Designed to run on a cron schedule.

## What It Does

1. Fetches items from a configured list of RSS feeds
2. Scores each item against a natural language interest profile via an LLM
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
# Run against all configured feeds (Ollama by default)
uv run content_discovery.py

# Dry run — print candidates, write nothing
uv run content_discovery.py --dry-run

# Single feed, cloud provider
uv run content_discovery.py --feed https://simonwillison.net/atom/everything/ --provider anthropic

# Limit items scored (useful for testing)
uv run content_discovery.py --cached --limit 20
```

### 2. Review

```bash
uv run content_discovery.py --review
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

## CLI Reference

| Argument       | Short | Default              | Description                                            |
|----------------|-------|----------------------|--------------------------------------------------------|
| `--provider`   | `-p`  | `local`              | LLM backend: `local`, `anthropic`, `groq`, `deepseek` |
| `--model`      | `-m`  | provider default     | Override the default model for the chosen provider     |
| `--dry-run`    | `-n`  | false                | Print candidates to stdout; write nothing              |
| `--review`     |       | false                | Interactively review pending items                     |
| `--feed`       | `-f`  | none                 | Process a single feed URL                              |
| `--threshold`  | `-t`  | `0.7`                | Minimum relevance score (0.0–1.0)                      |
| `--vault-path` | `-v`  | `OBSIDIAN_VAULT_PATH`| Path to the Obsidian vault root                        |
| `--inbox-path` |       | `_finds/00-inbox.md` | Inbox path relative to vault root                      |
| `--no-dedup`   |       | false                | Re-score items already seen                            |
| `--verbose`    |       | false                | Show scores for all items, not just candidates         |
| `--cached`     |       | false                | Use cached feed responses when available               |
| `--limit`      | `-l`  | none                 | Cap number of items scored (after deduplication)       |
| `--store`      |       | `~/.content-discovery.db` | Path to the SQLite database                       |

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

### Settings

```toml
[settings]
threshold = 0.7         # minimum score to store a candidate
provider = "local"      # default LLM backend
inbox_path = "_finds/00-inbox.md"
# vault_path = "~/vaults/MyVault/"
```

## Environment Variables

| Variable                   | Purpose                            | Example                         |
|----------------------------|------------------------------------|---------------------------------|
| `OBSIDIAN_VAULT_PATH`      | Vault root path                    | `~/vaults/BrainSync/`           |
| `CONTENT_DISCOVERY_STORE`  | SQLite DB path (machine-specific)  | `~/sync/content-discovery/store.db` |
| `ANTHROPIC_API_KEY`        | Anthropic API key                  | `sk-ant-...`                    |
| `GROQ_API_KEY`             | Groq API key                       | `gsk_...`                       |
| `DEEPSEEK_API_KEY`         | DeepSeek API key                   | `sk-...`                        |
| `OLLAMA_HOST`              | Ollama server URL                  | `http://localhost:11434`        |

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
0 8,17 * * * cd ~/projects/content-discovery-agent && uv run content_discovery.py >> ~/.content-discovery.log 2>&1
```

To use a cloud provider in the cron job (required if running on a Pi or a machine without Ollama):

```
0 8,17 * * * cd ~/projects/content-discovery-agent && uv run content_discovery.py --provider groq >> ~/.content-discovery.log 2>&1
```

Review whenever convenient — pending items accumulate in the database until you triage them.

## Project Structure

```
content-discovery-agent/
  content_discovery.py    # CLI entrypoint (run + review commands)
  config.py               # Feeds, interest profile, defaults, env vars
  store.py                # SQLite storage layer
  scorer.py               # Prompt construction and JSON parsing
  feed_reader.py          # feedparser wrapper
  feed_cache.py           # Feed response caching
  inbox_writer.py         # Obsidian inbox append logic
  state.py                # Legacy JSON dedup (superseded by store.py)
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
    test_store.py
    test_state.py
    fixtures/
      sample_feed.xml
      sample_scored.json
  .content-discovery.toml         # Your personal config (gitignored)
  .content-discovery.toml.example # Template
```

## Running Tests

```bash
uv run pytest
```
