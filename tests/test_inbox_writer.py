import os
import pytest
from inbox_writer import append_to_inbox, InboxEntry, INBOX_HEADER


def make_entry(**kwargs) -> InboxEntry:
    defaults = dict(
        title="Test Item",
        url="https://example.com/item",
        source="Test Blog",
        score=0.85,
        tags=["python", "llm"],
        summary="A test item about Python and LLMs.",
        fetched="2026-03-06",
    )
    defaults.update(kwargs)
    return InboxEntry(**defaults)


class TestAppendToInbox:
    def test_creates_file_with_header_if_missing(self, tmp_path):
        vault = str(tmp_path / "vault")
        os.makedirs(vault)
        inbox = "_finds/00-inbox.md"
        entry = make_entry()

        append_to_inbox(vault, inbox, [entry])

        full_path = os.path.join(vault, inbox)
        assert os.path.exists(full_path)
        content = open(full_path).read()
        assert "# Finds Inbox" in content
        assert "Test Item" in content

    def test_appends_to_existing_file(self, tmp_path):
        vault = str(tmp_path / "vault")
        inbox_dir = os.path.join(vault, "_finds")
        os.makedirs(inbox_dir)
        inbox_path = os.path.join(vault, "_finds/00-inbox.md")
        with open(inbox_path, "w") as f:
            f.write(INBOX_HEADER)

        entry = make_entry(title="New Item", url="https://example.com/new")
        append_to_inbox(vault, "_finds/00-inbox.md", [entry])

        content = open(inbox_path).read()
        assert "New Item" in content
        assert "# Finds Inbox" in content  # header preserved

    def test_checkbox_format(self, tmp_path):
        vault = str(tmp_path / "vault")
        os.makedirs(vault)
        entry = make_entry()
        append_to_inbox(vault, "_finds/00-inbox.md", [entry])

        content = open(os.path.join(vault, "_finds/00-inbox.md")).read()
        assert "- [ ] [Test Item](https://example.com/item)" in content

    def test_tags_formatted_with_hash(self, tmp_path):
        vault = str(tmp_path / "vault")
        os.makedirs(vault)
        entry = make_entry(tags=["python", "rag"])
        append_to_inbox(vault, "_finds/00-inbox.md", [entry])

        content = open(os.path.join(vault, "_finds/00-inbox.md")).read()
        assert "#python" in content
        assert "#rag" in content

    def test_no_entries_does_nothing(self, tmp_path):
        vault = str(tmp_path / "vault")
        os.makedirs(vault)
        inbox = "_finds/00-inbox.md"
        append_to_inbox(vault, inbox, [])
        assert not os.path.exists(os.path.join(vault, inbox))

    def test_multiple_entries_appended(self, tmp_path):
        vault = str(tmp_path / "vault")
        os.makedirs(vault)
        entries = [
            make_entry(title="Item 1", url="https://example.com/1"),
            make_entry(title="Item 2", url="https://example.com/2"),
        ]
        append_to_inbox(vault, "_finds/00-inbox.md", entries)

        content = open(os.path.join(vault, "_finds/00-inbox.md")).read()
        assert "Item 1" in content
        assert "Item 2" in content

    def test_score_formatted_to_two_decimal_places(self, tmp_path):
        vault = str(tmp_path / "vault")
        os.makedirs(vault)
        entry = make_entry(score=0.9)
        append_to_inbox(vault, "_finds/00-inbox.md", [entry])

        content = open(os.path.join(vault, "_finds/00-inbox.md")).read()
        assert "**Score**: 0.90" in content
