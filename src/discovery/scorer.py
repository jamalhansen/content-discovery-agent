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
- summary: one sentence (maximum 20 words) describing what the item covers, not what it concludes or claims.
- language: two-letter ISO 639-1 code for the article's language (e.g. "en", "ru", "de", "fr", "zh").

The summary is a label for triage, not a verdict. State the topic and the kind of
content (a benchmark, a tutorial, an announcement, an opinion), never the outcome
someone might read into it. This applies most where a headline overstates its
own body: an article's title can claim a comparison the article itself hedges,
qualifies, or contradicts, and repeating that framing in the summary launders it
into something that reads as a settled fact. On a headline like "X beats Y",
write what X and Y were compared on, not who won.

Bad:  "Open-weight model outperforms frontier models at lower cost."
Good: "Compares GLM-5.3 against frontier models on cost and benchmark scores."

Bad:  "New framework resolves queries more reliably than semantic search."
Good: "Proposes a filesystem-style interface as an alternative to RAG."

Separately, penalize content that reads as AI-generated rather than
human-written, regardless of topic relevance. Tells include: generic
listicle framing with no distinct voice, hedge-everything language that
never commits to a claim, transitions that restate the previous sentence
instead of adding information, buzzword density with no concrete example
or number, and a title-vs-body mismatch where the body never delivers what
the headline promises. An on-topic article that reads this way should
score no higher than 0.3 -- being about the right subject does not make
undifferentiated AI-generated filler worth surfacing.

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
