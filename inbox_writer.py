import os
from dataclasses import dataclass
from datetime import date

INBOX_HEADER = """# Finds Inbox

Items below were surfaced by the content discovery agent. Review, promote to a find file, or delete.

---
"""


@dataclass
class InboxEntry:
    title: str
    url: str
    source: str
    score: float
    tags: list[str]
    summary: str
    fetched: str = ""

    def __post_init__(self):
        if not self.fetched:
            self.fetched = date.today().isoformat()

    def format(self) -> str:
        tag_str = " ".join(f"#{t}" for t in self.tags) if self.tags else ""
        return (
            f"- [ ] [{self.title}]({self.url})\n"
            f"  - **Source**: {self.source}\n"
            f"  - **Score**: {self.score:.2f}\n"
            f"  - **Tags**: {tag_str}\n"
            f"  - **Summary**: {self.summary}\n"
            f"  - **Fetched**: {self.fetched}"
        )


def append_to_inbox(vault_path: str, inbox_path: str, entries: list[InboxEntry]) -> None:
    """Append entries to the inbox file, creating it with a header if it doesn't exist."""
    if not entries:
        return

    full_path = os.path.join(os.path.expanduser(vault_path), inbox_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # Build the block to append
    block = "\n\n".join(entry.format() for entry in entries)

    if not os.path.exists(full_path):
        content = INBOX_HEADER + "\n" + block + "\n"
        with open(full_path, "w") as f:
            f.write(content)
    else:
        with open(full_path, "a") as f:
            f.write("\n\n" + block + "\n")
