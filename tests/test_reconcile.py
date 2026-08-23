"""Tests for reconciling the Reader queue against vault notes."""
from dataclasses import dataclass

from discovery.reconcile import (
    collect_note_source_urls,
    extract_source_url,
    reconcile,
)


@dataclass
class FakeRef:
    doc_id: str
    source_url: str
    title: str = "An Article"
    location: str = "new"


def _note(text: str) -> str:
    return text


def _write_note(tmp_path, name, source_url=None, body="A claim."):
    lines = ["---", "description: A note", "type: note", "domain: ai-tools", "status: active"]
    if source_url is not None:
        lines.append(f"source_url: {source_url}")
    lines += ["---", "", body, ""]
    p = tmp_path / name
    p.write_text("\n".join(lines))
    return p


class TestExtractSourceUrl:
    def test_reads_unquoted_value(self):
        assert extract_source_url(
            "---\ntype: note\nsource_url: https://example.com/a\n---\n\nbody\n"
        ) == "https://example.com/a"

    def test_reads_quoted_value(self):
        assert extract_source_url(
            '---\ntype: note\nsource_url: "https://example.com/a"\n---\n\nbody\n'
        ) == "https://example.com/a"

    def test_returns_empty_when_absent(self):
        assert extract_source_url("---\ntype: note\n---\n\nbody\n") == ""

    def test_returns_empty_when_value_is_the_empty_template_default(self):
        assert extract_source_url('---\ntype: note\nsource_url: ""\n---\n\nbody\n') == ""

    def test_returns_empty_when_no_frontmatter(self):
        assert extract_source_url("# A note\n\nsource_url: https://example.com/a\n") == ""

    def test_ignores_a_mention_in_the_body(self):
        text = (
            "---\ntype: note\n---\n\n"
            "The frontmatter convention is source_url: https://example.com/wrong\n"
        )
        assert extract_source_url(text) == ""


class TestCollectNoteSourceUrls:
    def test_collects_only_notes_that_have_one(self, tmp_path):
        _write_note(tmp_path, "with.md", "https://example.com/a")
        _write_note(tmp_path, "without.md")
        urls = collect_note_source_urls(str(tmp_path))
        assert len(urls) == 1
        assert list(urls.values()) == [["with.md"]]

    def test_ignores_non_markdown_files(self, tmp_path):
        _write_note(tmp_path, "note.md", "https://example.com/a")
        (tmp_path / "notes.txt").write_text("source_url: https://example.com/b")
        assert len(collect_note_source_urls(str(tmp_path))) == 1

    def test_returns_empty_for_missing_directory(self, tmp_path):
        assert collect_note_source_urls(str(tmp_path / "nope")) == {}


class TestReconcile:
    def test_archives_documents_whose_article_became_a_note(self, tmp_path):
        _write_note(tmp_path, "claim.md", "https://example.com/a")
        refs = {"new": [FakeRef("doc1", "https://example.com/a")], "later": []}
        archived = []

        result = reconcile(
            str(tmp_path), "tok",
            list_refs=lambda _t, location: refs[location],
            archive=lambda _t, doc_id: archived.append(doc_id) or True,
        )
        assert archived == ["doc1"]
        assert result.archived == 1
        assert result.notes_with_source_url == 1

    def test_leaves_unmatched_documents_alone(self, tmp_path):
        _write_note(tmp_path, "claim.md", "https://example.com/a")
        refs = {"new": [FakeRef("doc2", "https://example.com/unread")], "later": []}
        archived = []

        result = reconcile(
            str(tmp_path), "tok",
            list_refs=lambda _t, location: refs[location],
            archive=lambda _t, doc_id: archived.append(doc_id) or True,
        )
        assert archived == []
        assert result.archived == 0
        assert result.documents_checked == 1

    def test_matches_across_url_normalization(self, tmp_path):
        _write_note(tmp_path, "claim.md", "https://example.com/a/")
        refs = {"new": [FakeRef("doc1", "https://example.com/a?utm_source=news")], "later": []}
        archived = []

        reconcile(
            str(tmp_path), "tok",
            list_refs=lambda _t, location: refs[location],
            archive=lambda _t, doc_id: archived.append(doc_id) or True,
        )
        assert archived == ["doc1"]

    def test_dry_run_reports_matches_without_archiving(self, tmp_path):
        _write_note(tmp_path, "claim.md", "https://example.com/a")
        refs = {"new": [FakeRef("doc1", "https://example.com/a")], "later": []}
        archived = []

        result = reconcile(
            str(tmp_path), "tok", dry_run=True,
            list_refs=lambda _t, location: refs[location],
            archive=lambda _t, doc_id: archived.append(doc_id) or True,
        )
        assert archived == []
        assert len(result.matched) == 1
        assert result.archived == 0

    def test_records_failures_rather_than_counting_them_archived(self, tmp_path):
        _write_note(tmp_path, "claim.md", "https://example.com/a")
        refs = {"new": [FakeRef("doc1", "https://example.com/a")], "later": []}

        result = reconcile(
            str(tmp_path), "tok",
            list_refs=lambda _t, location: refs[location],
            archive=lambda _t, _d: False,
        )
        assert result.archived == 0
        assert result.failed == ["doc1"]

    def test_does_not_check_the_same_document_twice_across_locations(self, tmp_path):
        _write_note(tmp_path, "claim.md", "https://example.com/a")
        dupe = FakeRef("doc1", "https://example.com/a")
        refs = {"new": [dupe], "later": [dupe]}
        archived = []

        result = reconcile(
            str(tmp_path), "tok",
            list_refs=lambda _t, location: refs[location],
            archive=lambda _t, doc_id: archived.append(doc_id) or True,
        )
        assert archived == ["doc1"]
        assert result.documents_checked == 1


class TestSourceUrlCounting:
    def test_counts_notes_and_distinct_articles_separately(self, tmp_path):
        _write_note(tmp_path, "claim-one.md", "https://example.com/a")
        _write_note(tmp_path, "claim-two.md", "https://example.com/a")
        _write_note(tmp_path, "claim-three.md", "https://example.com/b")
        _write_note(tmp_path, "no-url.md")

        result = reconcile(
            str(tmp_path), "tok", dry_run=True,
            list_refs=lambda _t, location: [],
            archive=lambda _t, _d: True,
        )
        assert result.notes_scanned == 4
        assert result.notes_with_source_url == 3
        assert result.distinct_source_urls == 2

    def test_one_document_matches_even_when_several_notes_cite_it(self, tmp_path):
        _write_note(tmp_path, "claim-one.md", "https://example.com/a")
        _write_note(tmp_path, "claim-two.md", "https://example.com/a")
        refs = {"new": [FakeRef("doc1", "https://example.com/a")], "later": []}
        archived = []

        result = reconcile(
            str(tmp_path), "tok",
            list_refs=lambda _t, location: refs[location],
            archive=lambda _t, doc_id: archived.append(doc_id) or True,
        )
        assert archived == ["doc1"]
        assert len(result.matched) == 1
