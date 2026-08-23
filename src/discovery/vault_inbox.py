"""Routes kept candidates into an Obsidian vault's inbox/ directory.

Writes one markdown file per item, matching a zero-friction capture
convention: light frontmatter (source, tags, capture date) plus the
title and summary already produced by scoring. Structuring beyond that
is left to the vault's own processing pipeline.
"""
import os
import re
from datetime import date


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:80].rstrip("-")
    return slug or "untitled"


def save_to_vault_inbox(
    inbox_path: str,
    url: str,
    title: str,
    summary: str = "",
    tags: list[str] | None = None,
    published_date: str = "",
    search_term: str = "",
    platform: str = "",
) -> bool:
    """Write a kept item as a new markdown file in the vault inbox.

    Returns True on success, False if the file could not be written.
    """
    try:
        target_dir = os.path.expanduser(inbox_path)
        os.makedirs(target_dir, exist_ok=True)

        today = date.today().isoformat()
        slug = _slugify(title)
        filename = f"{today}-{slug}.md"
        filepath = os.path.join(target_dir, filename)

        suffix = 2
        while os.path.exists(filepath):
            filepath = os.path.join(target_dir, f"{today}-{slug}-{suffix}.md")
            suffix += 1

        lines = [
            "---",
            "source_type: content-discovery-agent",
            f"source_url: {url}",
        ]
        if published_date:
            lines.append(f"published: {published_date}")
        if tags:
            tag_str = ", ".join(tags)
            lines.append(f'tags: "{tag_str}"')
        if search_term:
            lines.append(f"search_term: {search_term}")
        if platform:
            lines.append(f"platform: {platform}")
        lines.append(f"captured: {today}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {title}")
        lines.append("")
        if summary:
            lines.append(summary)
            lines.append("")
        lines.append(f"Source: {url}")
        lines.append("")

        with open(filepath, "w") as f:
            f.write("\n".join(lines))
        return True
    except OSError:
        return False
