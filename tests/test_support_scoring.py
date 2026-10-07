"""Tests for discovery.support.scoring — BaseScorer and ScoredItem."""

import json
from unittest.mock import MagicMock

import pytest
from local_first_common.testing import MockProvider

from discovery.support.scoring import BaseScorer, ScoredItem

# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class SimpleScorer(BaseScorer):
    system_prompt = "You are a test scorer. Return JSON."


VALID_JSON_RESPONSE = json.dumps(
    {
        "score": 0.85,
        "tags": ["ai", "python"],
        "summary": "A useful article about AI.",
        "language": "en",
    }
)

VALID_XML_RESPONSE = (
    "<score>0.75</score><tags>ai, llm</tags><summary>XML fallback test.</summary><language>en</language>"
)


# ---------------------------------------------------------------------------
# ScoredItem
# ---------------------------------------------------------------------------


class TestScoredItem:
    def test_fields(self):
        item = ScoredItem(score=0.9, tags=["x"], summary="Test", language="fr")
        assert item.score == 0.9
        assert item.tags == ["x"]
        assert item.summary == "Test"
        assert item.language == "fr"

    def test_default_language(self):
        item = ScoredItem(score=0.5, tags=[], summary="")
        assert item.language == "en"


# ---------------------------------------------------------------------------
# BaseScorer.score()
# ---------------------------------------------------------------------------


class TestBaseScorerScore:
    def test_valid_json_returns_scored_item(self):
        provider = MockProvider(response=VALID_JSON_RESPONSE)
        result = SimpleScorer().score(provider, "user msg")
        assert isinstance(result, ScoredItem)
        assert result.score == pytest.approx(0.85)
        assert result.tags == ["ai", "python"]
        assert result.summary == "A useful article about AI."
        assert result.language == "en"

    def test_provider_runtime_error_returns_none(self):
        provider = MockProvider(response="ignored")
        provider.complete = MagicMock(side_effect=RuntimeError("model not found"))
        result = SimpleScorer().score(provider, "user msg")
        assert result is None

    def test_invalid_response_returns_none(self):
        provider = MockProvider(response="this is not json or xml")
        result = SimpleScorer().score(provider, "user msg")
        assert result is None


# ---------------------------------------------------------------------------
# BaseScorer._parse_response()
# ---------------------------------------------------------------------------


class TestParseResponse:
    def setup_method(self):
        self.scorer = SimpleScorer()

    def test_plain_json(self):
        result = self.scorer._parse_response(VALID_JSON_RESPONSE)
        assert result is not None
        assert result.score == pytest.approx(0.85)

    def test_json_in_fences(self):
        fenced = f"```json\n{VALID_JSON_RESPONSE}\n```"
        result = self.scorer._parse_response(fenced)
        assert result is not None
        assert result.score == pytest.approx(0.85)

    def test_xml_fallback(self):
        result = self.scorer._parse_response(VALID_XML_RESPONSE)
        assert result is not None
        assert result.score == pytest.approx(0.75)
        assert result.summary == "XML fallback test."
        assert result.language == "en"

    def test_xml_tags_as_json_array(self):
        raw = (
            '<score>0.6</score><tags>["machine learning", "nlp"]</tags><summary>Test.</summary><language>en</language>'
        )
        result = self.scorer._parse_response(raw)
        assert result is not None
        assert result.tags == ["machine learning", "nlp"]

    def test_xml_tags_as_comma_list(self):
        raw = "<score>0.6</score><tags>sql, duckdb</tags><summary>Test.</summary><language>en</language>"
        result = self.scorer._parse_response(raw)
        assert result is not None
        assert result.tags == ["sql", "duckdb"]

    def test_xml_missing_field_returns_none(self):
        # Missing <language> tag
        raw = "<score>0.7</score><summary>Missing lang.</summary><tags>ai</tags>"
        result = self.scorer._parse_response(raw)
        assert result is None

    def test_completely_invalid_returns_none(self):
        result = self.scorer._parse_response("here is some random text from the model")
        assert result is None

    def test_tags_capped_at_two(self):
        data = json.dumps({"score": 0.5, "tags": ["a", "b", "c", "d"], "summary": "x", "language": "en"})
        result = self.scorer._parse_response(data)
        assert result is not None
        assert len(result.tags) == 2

    def test_score_coerced_to_float(self):
        data = json.dumps({"score": "0.9", "tags": [], "summary": "x", "language": "en"})
        result = self.scorer._parse_response(data)
        assert result is not None
        assert isinstance(result.score, float)

    def test_missing_score_key_returns_none(self):
        data = json.dumps({"tags": ["ai"], "summary": "x", "language": "en"})
        result = self.scorer._parse_response(data)
        assert result is None

    def test_xml_fallback_increments_counter(self):
        assert self.scorer.xml_fallback_count == 0
        self.scorer._parse_response(VALID_XML_RESPONSE)
        assert self.scorer.xml_fallback_count == 1

    def test_parse_error_increments_counter(self):
        assert self.scorer.parse_error_count == 0
        self.scorer._parse_response("not json or xml")
        assert self.scorer.parse_error_count == 1

    def test_json_success_does_not_increment_counters(self):
        self.scorer._parse_response(VALID_JSON_RESPONSE)
        assert self.scorer.xml_fallback_count == 0
        assert self.scorer.parse_error_count == 0

    def test_counters_accumulate_across_calls(self):
        self.scorer._parse_response(VALID_XML_RESPONSE)
        self.scorer._parse_response(VALID_XML_RESPONSE)
        self.scorer._parse_response("garbage")
        assert self.scorer.xml_fallback_count == 2
        assert self.scorer.parse_error_count == 1
