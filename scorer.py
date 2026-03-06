import json
import logging
from dataclasses import dataclass
from providers.base import BaseProvider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a content relevance scorer. Given a feed item and a list of topic tags,
return a JSON object with these fields:

- score: float between 0.0 and 1.0 representing how relevant this item is to the topics
- tags: list of matching topic tags from the provided list (empty list if none)
- summary: one sentence describing what this item is about

Return only valid JSON. No preamble, no explanation."""


@dataclass
class ScoredItem:
    score: float
    tags: list[str]
    summary: str


def build_user_message(title: str, description: str, topic_tags: list[str]) -> str:
    topics = ", ".join(topic_tags)
    return f"Topics: {topics}\n\nTitle: {title}\nDescription: {description}"


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
            tags=list(data.get("tags", [])),
            summary=str(data.get("summary", "")),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Failed to parse scorer response: %s | Raw: %s", e, raw[:200])
        return None


def score_item(
    provider: BaseProvider,
    title: str,
    description: str,
    topic_tags: list[str],
) -> ScoredItem | None:
    user_message = build_user_message(title, description, topic_tags)
    raw = provider.complete(SYSTEM_PROMPT, user_message)
    return parse_response(raw)
