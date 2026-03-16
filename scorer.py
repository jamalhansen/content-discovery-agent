import json
import logging
from dataclasses import dataclass
from local_first_common.llm import strip_json_fences
from local_first_common.providers.base import BaseProvider

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


@dataclass
class ScoredItem:
    score: float
    tags: list[str]
    summary: str
    language: str = "en"


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
    try:
        data = json.loads(strip_json_fences(raw))
        return ScoredItem(
            score=float(data["score"]),
            tags=list(data.get("tags", []))[:2],  # enforce 2-tag limit
            summary=str(data.get("summary", "")),
            language=str(data.get("language", "en")).lower()[:2],
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Failed to parse scorer response: %s | Raw: %s", e, raw[:200])
        return None


def score_item(
    provider: BaseProvider,
    title: str,
    description: str,
    interest_profile: str,
    examples: dict | None = None,
    exclusions: str = "",
) -> ScoredItem | None:
    user_message = build_user_message(title, description, interest_profile, exclusions, examples)
    try:
        raw = provider.complete(SYSTEM_PROMPT, user_message)
    except RuntimeError as e:
        logger.warning("Provider error scoring '%s': %s", title[:60], e)
        return None
    return parse_response(raw)
