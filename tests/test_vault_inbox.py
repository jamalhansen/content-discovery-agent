"""Tests for the vault inbox capture module."""
from discovery.vault_inbox import save_to_vault_inbox


class TestSaveToVaultInbox:
    def test_writes_file_with_expected_name(self, tmp_path):
        ok = save_to_vault_inbox(
            str(tmp_path), "https://example.com/article", title="A Great Article",
        )
        assert ok is True
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1
        assert files[0].name.endswith("-a-great-article.md")

    def test_creates_inbox_dir_if_missing(self, tmp_path):
        target = tmp_path / "does" / "not" / "exist"
        ok = save_to_vault_inbox(str(target), "https://example.com/x", title="X")
        assert ok is True
        assert target.is_dir()
        assert len(list(target.glob("*.md"))) == 1

    def test_frontmatter_contains_source_url(self, tmp_path):
        save_to_vault_inbox(str(tmp_path), "https://example.com/article", title="Title")
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "source_url: https://example.com/article" in content
        assert "source_type: content-discovery-agent" in content

    def test_body_contains_title_and_summary(self, tmp_path):
        save_to_vault_inbox(
            str(tmp_path), "https://example.com/article", title="My Title",
            summary="A useful summary.",
        )
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "# My Title" in content
        assert "A useful summary." in content
        assert "Source: https://example.com/article" in content

    def test_tags_included_when_provided(self, tmp_path):
        save_to_vault_inbox(
            str(tmp_path), "https://example.com/article", title="Title",
            tags=["python", "ai"],
        )
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert 'tags: "python, ai"' in content

    def test_tags_omitted_when_empty(self, tmp_path):
        save_to_vault_inbox(str(tmp_path), "https://example.com/article", title="Title")
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "tags:" not in content

    def test_optional_fields_omitted_when_absent(self, tmp_path):
        save_to_vault_inbox(str(tmp_path), "https://example.com/article", title="Title")
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "published:" not in content
        assert "search_term:" not in content
        assert "platform:" not in content

    def test_optional_fields_included_when_provided(self, tmp_path):
        save_to_vault_inbox(
            str(tmp_path), "https://example.com/article", title="Title",
            published_date="2026-03-10", search_term="local AI", platform="bluesky",
        )
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "published: 2026-03-10" in content
        assert "search_term: local AI" in content
        assert "platform: bluesky" in content

    def test_collision_appends_suffix(self, tmp_path):
        save_to_vault_inbox(str(tmp_path), "https://example.com/1", title="Same Title")
        save_to_vault_inbox(str(tmp_path), "https://example.com/2", title="Same Title")
        names = {f.name for f in tmp_path.glob("*.md")}
        assert len(names) == 2
        assert any(n.endswith("-same-title.md") for n in names)
        assert any(n.endswith("-same-title-2.md") for n in names)

    def test_expands_user_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        ok = save_to_vault_inbox("~/inbox", "https://example.com/x", title="X")
        assert ok is True
        assert (tmp_path / "inbox").is_dir()

    def test_slugify_strips_punctuation_and_caps_length(self, tmp_path):
        long_title = "A Title: With Punctuation! " + ("word " * 30)
        save_to_vault_inbox(str(tmp_path), "https://example.com/x", title=long_title)
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1
        name = files[0].stem
        assert ":" not in name and "!" not in name

    def test_returns_false_on_oserror(self, tmp_path, monkeypatch):
        import discovery.vault_inbox as mod

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(mod.os, "makedirs", _boom)
        ok = save_to_vault_inbox(str(tmp_path), "https://example.com/x", title="X")
        assert ok is False
