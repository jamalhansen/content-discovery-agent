from pathlib import Path

from discovery.pull_tagged import SOURCE_TYPE, collect_tagged, pull_tagged_items
from discovery.vault_inbox import save_to_vault_inbox

ARTICLE = {"id": "a1", "category": "article", "source_url": "https://example.com/post", "title": "A Post", "notes": "why I kept it"}
HIGHLIGHTS = [
    {"id": "h2", "category": "highlight", "parent_id": "a1", "content": "second", "highlight_location": 20},
    {"id": "h1", "category": "highlight", "parent_id": "a1", "content": "first", "highlight_location": 10},
    {"id": "h9", "category": "highlight", "parent_id": "other", "content": "elsewhere", "highlight_location": 1},
]


def fake_list(tagged, by_id=None):
    def list_docs(token, **params):
        if "tag" in params:
            return tagged
        if "id" in params:
            return [d for d in (by_id or []) if d["id"] in params["id"].split(",")]
        if params.get("category") == "highlight":
            return HIGHLIGHTS
        return []
    return list_docs


def test_collects_highlights_in_reading_order_for_tagged_doc_only():
    docs = collect_tagged("t", list_docs=fake_list([ARTICLE]))
    assert len(docs) == 1
    assert docs[0].highlights == ["first", "second"]
    assert docs[0].note == "why I kept it"


def test_tag_on_a_highlight_counts_as_tagging_its_document():
    tagged_highlight = {"id": "h1", "category": "highlight", "parent_id": "a1", "content": "first"}
    docs = collect_tagged("t", list_docs=fake_list([tagged_highlight], by_id=[ARTICLE]))
    assert [d.doc_id for d in docs] == ["a1"]


def test_nothing_tagged_skips_highlight_fetch():
    calls = []

    def list_docs(token, **params):
        calls.append(params)
        return []

    assert collect_tagged("t", list_docs=list_docs) == []
    assert calls == [{"tag": "contexta"}]


def test_writes_tagged_item_with_highlights_and_source_type(tmp_path: Path):
    notes, inbox = tmp_path / "notes", tmp_path / "inbox"
    notes.mkdir()
    inbox.mkdir()

    def save(inbox_path, url, title, **kw):
        return save_to_vault_inbox(inbox_path, url, title, body_fetcher=lambda u: ("body text " * 200, ""), **kw)

    result = pull_tagged_items(str(notes), str(inbox), "t", list_docs=fake_list([ARTICLE]), save=save)
    assert result.imported == ["A Post"]
    text = next(inbox.glob("*.md")).read_text()
    assert f"source_type: {SOURCE_TYPE}" in text
    assert "## Jamal's highlights" in text and text.index("> first") < text.index("> second")
    assert "## Jamal's note" in text and "why I kept it" in text


def test_already_captured_url_is_skipped(tmp_path: Path):
    notes, inbox = tmp_path / "notes", tmp_path / "inbox"
    notes.mkdir()
    inbox.mkdir()
    (inbox / "existing.md").write_text("---\nsource_url: https://example.com/post\n---\n")
    saved = []
    result = pull_tagged_items(
        str(notes), str(inbox), "t", list_docs=fake_list([ARTICLE]), save=lambda *a, **k: saved.append(a) or True
    )
    assert result.already_captured == 1
    assert saved == []


def test_default_source_type_unchanged_for_discovered_items(tmp_path: Path):
    save_to_vault_inbox(str(tmp_path), "https://example.com/x", "X", body_fetcher=lambda u: ("b " * 800, ""))
    assert "source_type: content-discovery-agent" in next(tmp_path.glob("*.md")).read_text()


def test_source_archived_in_a_subfolder_counts_as_captured(tmp_path: Path):
    """/reduce moves a source to inbox/archive/<name>/<name>.md; it must not be pulled again."""
    notes, inbox = tmp_path / "notes", tmp_path / "inbox"
    notes.mkdir()
    nested = inbox / "archive" / "2026-09-27-a-post"
    nested.mkdir(parents=True)
    (nested / "2026-09-27-a-post.md").write_text("---\nsource_url: https://example.com/post\n---\n")
    saved = []
    result = pull_tagged_items(
        str(notes), str(inbox), "t", list_docs=fake_list([ARTICLE]), save=lambda *a, **k: saved.append(a) or True
    )
    assert result.already_captured == 1
    assert saved == []
