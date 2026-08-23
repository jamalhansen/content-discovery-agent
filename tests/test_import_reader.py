"""Tests for pulling the existing Readwise backlog into the Contexta inbox."""
from dataclasses import dataclass

from discovery.import_reader import import_reader_backlog


@dataclass
class FakeRef:
    doc_id: str
    source_url: str
    title: str = "An Article"
    location: str = "new"


def _write_note(tmp_path, name, source_url):
    (tmp_path / name).write_text(
        f'---\ntype: note\nsource_url: "{source_url}"\n---\n\nbody\n'
    )


def _write_inbox_file(tmp_path, name, source_url):
    (tmp_path / name).write_text(
        f"---\nsource_type: content-discovery-agent\nsource_url: {source_url}\n---\n\nbody\n"
    )


class TestImportReaderBacklog:
    def test_imports_an_uncaptured_item(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        refs = {"new": [FakeRef("doc1", "https://example.com/a", "New One")], "later": []}
        saved = []

        result = import_reader_backlog(
            str(notes), str(inbox), "tok",
            list_refs=lambda _t, location: refs[location],
            save=lambda *a, **kw: saved.append(a) or True,
        )
        assert result.imported == ["New One"]
        assert len(saved) == 1

    def test_skips_an_item_already_in_a_note(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        _write_note(notes, "claim.md", "https://example.com/a")
        refs = {"new": [FakeRef("doc1", "https://example.com/a")], "later": []}
        saved = []

        result = import_reader_backlog(
            str(notes), str(inbox), "tok",
            list_refs=lambda _t, location: refs[location],
            save=lambda *a, **kw: saved.append(a) or True,
        )
        assert result.imported == []
        assert result.already_captured == 1
        assert saved == []

    def test_skips_an_item_already_in_an_unreduced_inbox_file(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        _write_inbox_file(inbox, "captured.md", "https://example.com/a")
        refs = {"new": [FakeRef("doc1", "https://example.com/a")], "later": []}
        saved = []

        result = import_reader_backlog(
            str(notes), str(inbox), "tok",
            list_refs=lambda _t, location: refs[location],
            save=lambda *a, **kw: saved.append(a) or True,
        )
        assert result.already_captured == 1
        assert saved == []

    def test_skips_an_item_already_archived_in_inbox_archive(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        archive = inbox / "archive"
        archive.mkdir()
        _write_inbox_file(archive, "old.md", "https://example.com/a")
        refs = {"new": [FakeRef("doc1", "https://example.com/a")], "later": []}
        saved = []

        result = import_reader_backlog(
            str(notes), str(inbox), "tok",
            list_refs=lambda _t, location: refs[location],
            save=lambda *a, **kw: saved.append(a) or True,
        )
        assert result.already_captured == 1
        assert saved == []

    def test_respects_the_limit(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        many = [FakeRef(f"doc{i}", f"https://example.com/{i}", f"Item {i}") for i in range(5)]
        refs = {"new": many, "later": []}
        saved = []

        result = import_reader_backlog(
            str(notes), str(inbox), "tok", limit=2,
            list_refs=lambda _t, location: refs[location],
            save=lambda *a, **kw: saved.append(a) or True,
        )
        assert len(result.imported) == 2
        assert len(saved) == 2

    def test_dry_run_reports_without_writing(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        refs = {"new": [FakeRef("doc1", "https://example.com/a", "New One")], "later": []}
        saved = []

        result = import_reader_backlog(
            str(notes), str(inbox), "tok", dry_run=True,
            list_refs=lambda _t, location: refs[location],
            save=lambda *a, **kw: saved.append(a) or True,
        )
        assert result.imported == ["New One"]
        assert saved == []

    def test_records_a_write_failure_separately_from_success(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        refs = {"new": [FakeRef("doc1", "https://example.com/a", "New One")], "later": []}

        result = import_reader_backlog(
            str(notes), str(inbox), "tok",
            list_refs=lambda _t, location: refs[location],
            save=lambda *a, **kw: False,
        )
        assert result.imported == []
        assert result.failed == ["New One"]

    def test_does_not_check_the_same_document_twice_across_locations(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        dupe = FakeRef("doc1", "https://example.com/a", "New One")
        refs = {"new": [dupe], "later": [dupe]}
        saved = []

        result = import_reader_backlog(
            str(notes), str(inbox), "tok",
            list_refs=lambda _t, location: refs[location],
            save=lambda *a, **kw: saved.append(a) or True,
        )
        assert result.documents_checked == 1
        assert len(saved) == 1
