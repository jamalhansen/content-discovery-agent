import pytest
from unittest.mock import MagicMock
from scorer import build_user_message, parse_response, score_item, ScoredItem


class TestBuildUserMessage:
    def test_includes_topics(self):
        msg = build_user_message("Title", "Desc", ["python", "llm"])
        assert "python, llm" in msg

    def test_includes_title_and_description(self):
        msg = build_user_message("My Title", "My Desc", ["python"])
        assert "My Title" in msg
        assert "My Desc" in msg


class TestParseResponse:
    def test_valid_json(self):
        raw = '{"score": 0.85, "tags": ["python", "llm"], "summary": "A guide."}'
        result = parse_response(raw)
        assert result is not None
        assert result.score == 0.85
        assert result.tags == ["python", "llm"]
        assert result.summary == "A guide."

    def test_strips_markdown_fences(self):
        raw = '```json\n{"score": 0.5, "tags": [], "summary": "Meh."}\n```'
        result = parse_response(raw)
        assert result is not None
        assert result.score == 0.5

    def test_invalid_json_returns_none(self):
        result = parse_response("not json at all")
        assert result is None

    def test_missing_score_returns_none(self):
        result = parse_response('{"tags": [], "summary": "No score."}')
        assert result is None

    def test_empty_tags(self):
        raw = '{"score": 0.1, "tags": [], "summary": "Irrelevant."}'
        result = parse_response(raw)
        assert result is not None
        assert result.tags == []

    def test_score_zero(self):
        raw = '{"score": 0.0, "tags": [], "summary": "Not relevant."}'
        result = parse_response(raw)
        assert result is not None
        assert result.score == 0.0


class TestScoreItem:
    def test_returns_scored_item(self):
        provider = MagicMock()
        provider.complete.return_value = '{"score": 0.9, "tags": ["python"], "summary": "Great."}'
        result = score_item(provider, "Python Tips", "Tips for Python", ["python"])
        assert isinstance(result, ScoredItem)
        assert result.score == 0.9

    def test_returns_none_on_invalid_response(self):
        provider = MagicMock()
        provider.complete.return_value = "I cannot score this."
        result = score_item(provider, "Title", "Desc", ["python"])
        assert result is None

    def test_provider_called_with_prompts(self):
        provider = MagicMock()
        provider.complete.return_value = '{"score": 0.5, "tags": [], "summary": "Ok."}'
        score_item(provider, "Title", "Desc", ["python", "llm"])
        provider.complete.assert_called_once()
        _, user_msg = provider.complete.call_args[0]
        assert "python, llm" in user_msg
        assert "Title" in user_msg
