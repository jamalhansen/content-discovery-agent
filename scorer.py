import json
import logging
from dataclasses import dataclass
from providers.base import BaseProvider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a content relevance scorer. Given a feed item and a description of someone's interests, return a JSON object with exactly these fields:

- score: float 0.0-1.0 representing how relevant this item is to the person's interests:
  - 0.0-0.3: not relevant or only tangentially related
  - 0.4-0.6: somewhat relevant, touches on related areas
  - 0.7-1.0: highly relevant, directly addresses their interests or current work
- tags: array of at most 2 short strings describing what this item is about (e.g. ["sql", "query optimization"] or ["local AI", "ollama"]).
- summary: one sentence (maximum 20 words) describing what this item is about.

Return only valid JSON. No preamble, no explanation."""


@dataclass
class ScoredItem:
    score: float
    tags: list[str]
    summary: str


def build_user_message(
    title: str,
    description: str,
    interest_profile: str,
    examples: dict | None = None,
) -> str:
    parts = [f"Interests: {interest_profile}"]

    if examples:
        kept = examples.get("kept", [])
        dismissed = examples.get("dismissed", [])
        if kept:
            kept_lines = "\n".join(f'- "{t}"' for t in kept)
            parts.append(f"Recent items kept:\n{kept_lines}")
        if dismissed:
            dismissed_lines = "\n".join(f'- "{t}"' for t in dismissed)
            parts.append(f"Recent items dismissed:\n{dismissed_lines}")

    parts.append(f"Title: {title}\nDescription: {description}")
    return "\n\n".join(parts)


def parse_response(raw: str) -> ScoredItem | None:
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first and last fence lines
        inner = []
        for line in lines[1:]:
            if line.strip() == "```":
                break
            inner.append(line)
        text = "\n".join(inner)

    try:
        data = json.loads(text)
        return ScoredItem(
            score=float(data["score"]),
            tags=list(data.get("tags", []))[:2],  # enforce 2-tag limit
            summary=str(data.get("summary", "")),
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
) -> ScoredItem | None:
    user_message = build_user_message(title, description, interest_profile, examples)
    try:
        raw = provider.complete(SYSTEM_PROMPT, user_message)
    except RuntimeError as e:
        logger.warning("Provider error scoring '%s': %s", title[:60], e)
        return None
    return parse_response(raw)
