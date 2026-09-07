from unittest.mock import MagicMock
from discovery.scorer import SYSTEM_PROMPT, build_user_message, parse_response, score_item, ScoredItem

PROFILE = "I write and teach SQL and Python for developers. I'm interested in local AI and LLMs."


class TestBuildUserMessage:
    def test_includes_profile(self):
        msg = build_user_message("Title", "Desc", PROFILE)
        assert PROFILE in msg

    def test_includes_title_and_description(self):
        msg = build_user_message("My Title", "My Desc", PROFILE)
        assert "My Title" in msg
        assert "My Desc" in msg

    def test_truncates_long_description(self):
        long_desc = "x" * 2000
        msg = build_user_message("Title", long_desc, PROFILE)
        # Only first 500 chars should appear; the rest must be absent
        assert "x" * 500 in msg
        assert "x" * 501 not in msg

    def test_includes_kept_examples(self):
        examples = {"kept": ["Great Python Article", "DuckDB Deep Dive"], "dismissed": []}
        msg = build_user_message("Title", "Desc", PROFILE, examples=examples)
        assert "Recent items kept:" in msg
        assert '"Great Python Article"' in msg
        assert '"DuckDB Deep Dive"' in msg

    def test_includes_dismissed_examples(self):
        examples = {"kept": [], "dismissed": ["Pasta Recipes 2026"]}
        msg = build_user_message("Title", "Desc", PROFILE, examples=examples)
        assert "Recent items dismissed:" in msg
        assert '"Pasta Recipes 2026"' in msg

    def test_no_examples_section_when_none(self):
        msg = build_user_message("Title", "Desc", PROFILE, examples=None)
        assert "Recent items kept:" not in msg
        assert "Recent items dismissed:" not in msg

    def test_no_examples_section_when_empty(self):
        msg = build_user_message("Title", "Desc", PROFILE, examples={"kept": [], "dismissed": []})
        assert "Recent items kept:" not in msg
        assert "Recent items dismissed:" not in msg

    def test_includes_exclusions_when_provided(self):
        excl = "JavaScript tutorials, YouTube videos, job listings"
        msg = build_user_message("Title", "Desc", PROFILE, exclusions=excl)
        assert "Not interested in:" in msg
        assert excl in msg

    def test_no_exclusions_section_when_empty(self):
        msg = build_user_message("Title", "Desc", PROFILE, exclusions="")
        assert "Not interested in:" not in msg

    def test_exclusions_appear_after_profile(self):
        excl = "React tutorials"
        msg = build_user_message("Title", "Desc", PROFILE, exclusions=excl)
        profile_pos = msg.index(PROFILE)
        excl_pos = msg.index(excl)
        assert profile_pos < excl_pos


class TestParseResponse:
    def test_valid_json(self):
        raw = '{"score": 0.85, "tags": ["python", "llm"], "summary": "A guide.", "language": "en"}'
        result = parse_response(raw)
        assert result is not None
        assert result.score == 0.85
        assert result.tags == ["python", "llm"]
        assert result.summary == "A guide."
        assert result.language == "en"

    def test_strips_markdown_fences(self):
        raw = '```json\n{"score": 0.5, "tags": [], "summary": "Meh.", "language": "en"}\n```'
        result = parse_response(raw)
        assert result is not None
        assert result.score == 0.5

    def test_invalid_json_returns_none(self):
        result = parse_response("not json at all")
        assert result is None

    def test_missing_score_returns_none(self):
        result = parse_response('{"tags": [], "summary": "No score.", "language": "en"}')
        assert result is None

    def test_empty_tags(self):
        raw = '{"score": 0.1, "tags": [], "summary": "Irrelevant.", "language": "en"}'
        result = parse_response(raw)
        assert result is not None
        assert result.tags == []

    def test_score_zero(self):
        raw = '{"score": 0.0, "tags": [], "summary": "Not relevant.", "language": "en"}'
        result = parse_response(raw)
        assert result is not None
        assert result.score == 0.0

    def test_excess_tags_capped_at_two(self):
        raw = '{"score": 0.8, "tags": ["a", "b", "c", "d", "e", "f", "g"], "summary": "Too many tags.", "language": "en"}'
        result = parse_response(raw)
        assert result is not None
        assert result.tags == ["a", "b"]

    def test_non_english_language_parsed(self):
        raw = '{"score": 0.7, "tags": ["python"], "summary": "Руководство по Python.", "language": "ru"}'
        result = parse_response(raw)
        assert result is not None
        assert result.language == "ru"

    def test_missing_language_defaults_to_en(self):
        raw = '{"score": 0.7, "tags": ["python"], "summary": "A guide."}'
        result = parse_response(raw)
        assert result is not None
        assert result.language == "en"

    def test_language_normalised_to_lowercase(self):
        raw = '{"score": 0.7, "tags": [], "summary": "Guide.", "language": "DE"}'
        result = parse_response(raw)
        assert result is not None
        assert result.language == "de"


class TestScoreItem:
    def test_returns_scored_item(self):
        provider = MagicMock()
        provider.complete.return_value = '{"score": 0.9, "tags": ["python"], "summary": "Great.", "language": "en"}'
        result = score_item(provider, "Python Tips", "Tips for Python", PROFILE)
        assert isinstance(result, ScoredItem)
        assert result.score == 0.9
        assert result.language == "en"

    def test_returns_none_on_invalid_response(self):
        provider = MagicMock()
        provider.complete.return_value = "I cannot score this."
        result = score_item(provider, "Title", "Desc", PROFILE)
        assert result is None

    def test_provider_called_with_prompts(self):
        provider = MagicMock()
        provider.complete.return_value = '{"score": 0.5, "tags": [], "summary": "Ok.", "language": "en"}'
        score_item(provider, "Title", "Desc", PROFILE)
        provider.complete.assert_called_once()
        _, user_msg = provider.complete.call_args[0]
        assert PROFILE in user_msg
        assert "Title" in user_msg

    def test_passes_examples_to_message(self):
        provider = MagicMock()
        provider.complete.return_value = '{"score": 0.8, "tags": ["python"], "summary": "Good.", "language": "en"}'
        examples = {"kept": ["A Kept Article"], "dismissed": []}
        score_item(provider, "Title", "Desc", PROFILE, examples=examples)
        _, user_msg = provider.complete.call_args[0]
        assert "A Kept Article" in user_msg

    def test_system_prompt_includes_language_field(self):
        provider = MagicMock()
        provider.complete.return_value = '{"score": 0.5, "tags": [], "summary": "Ok.", "language": "en"}'
        score_item(provider, "Title", "Desc", PROFILE)
        system_prompt, _ = provider.complete.call_args[0]
        assert "language" in system_prompt


class TestSystemPromptDescribesRatherThanConcludes:
    """The scoring summary is what gets shown next to items and written into
    Contexta inbox files, above the fetched article body. On 2026-08-23 an item
    whose body fetched cleanly still produced a summary asserting a conclusion
    ("outperforms frontier models") the article itself did not support, an
    overclaim that survived a complete, successful capture. These tests lock in
    the instruction that prevents it, so a future edit cannot drop it silently.
    """

    def test_instructs_describing_not_concluding(self):
        assert "not what it concludes" in SYSTEM_PROMPT

    def test_names_the_headline_overstatement_case(self):
        assert "headline overstates" in SYSTEM_PROMPT

    def test_gives_a_worked_bad_and_good_example(self):
        assert "Bad:" in SYSTEM_PROMPT
        assert "Good:" in SYSTEM_PROMPT


class TestSystemPromptPenalizesAIGeneratedContent:
    """Locks in the instruction to score down AI-generated-sounding content
    regardless of topic relevance, added 2026-09-06 so an on-topic item that
    is undifferentiated LLM filler doesn't automatically clear threshold."""

    def test_instructs_penalizing_ai_generated_content(self):
        assert "AI-generated" in SYSTEM_PROMPT

    def test_names_concrete_tells(self):
        assert "hedge-everything" in SYSTEM_PROMPT
        assert "listicle" in SYSTEM_PROMPT

    def test_states_relevance_does_not_override_the_penalty(self):
        assert "regardless of topic relevance" in SYSTEM_PROMPT
