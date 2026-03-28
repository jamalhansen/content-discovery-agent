import logging
from local_first_common.providers.base import BaseProvider
from local_first_common.scoring import BaseScorer, ScoredItem

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a content relevance scorer. Given a feed item and a description of someone's interests, return a JSON object with exactly these fields:

- score: float 0.0-1.0 representing how relevant this item is to the person's interests:
  - 0.0-0.3: not relevant or only tangentially related
  - 0.4-0.6: somewhat relevant, touches on related areas
  - 0.7-1.0: highly relevant, directly addresses their interests or current work
- tags: array of at most 2 short strings describing what this item is about (e.g. ["sql", "query optimization"] or ["local AI", "ollama"]).
- summary: one sentence (maximum 20 words) describing what this item is about.
- language: two-letter ISO 639-1 code for the article's language (e.g. "en", "ru", "de", "fr", "zh").

Return only valid JSON. No preamble, no explanation."""


class ContentDiscoveryScorer(BaseScorer):
    system_prompt = SYSTEM_PROMPT


def build_user_message(
    title: str,
    description: str,
    interest_profile: str,
    exclusions: str = "",
    examples: dict | None = None,
) -> str:
    parts = [f"Interests: {interest_profile}"]

    if exclusions:
        parts.append(f"Not interested in: {exclusions}")

    if examples:
        kept = examples.get("kept", [])
        dismissed = examples.get("dismissed", [])
        if kept:
            kept_lines = "\n".join(f'- "{t}"' for t in kept)
            parts.append(f"Recent items kept:\n{kept_lines}")
        if dismissed:
            dismissed_lines = "\n".join(f'- "{t}"' for t in dismissed)
            parts.append(f"Recent items dismissed:\n{dismissed_lines}")

    # Truncate long descriptions — full article text floods the context window
    # and causes small models to ignore the JSON format instruction.
    desc = description[:500] if len(description) > 500 else description
    parts.append(f"Title: {title}\nDescription: {desc}")
    return "\n\n".join(parts)


def parse_response(raw: str) -> ScoredItem | None:
    """Parse a raw LLM scorer response into a ScoredItem.

    Backward-compatible shim — delegates to ContentDiscoveryScorer._parse_response.
    """
    return ContentDiscoveryScorer()._parse_response(raw)


def score_item(
    provider: BaseProvider,
    title: str,
    description: str,
    interest_profile: str,
    examples: dict | None = None,
    exclusions: str = "",
    scorer: ContentDiscoveryScorer | None = None,
) -> ScoredItem | None:
    if scorer is None:
        scorer = ContentDiscoveryScorer()
    user_message = build_user_message(title, description, interest_profile, exclusions, examples)
    return scorer.score(provider, user_message)
