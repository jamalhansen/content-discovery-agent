"""Shared LLM-based content scoring utilities.

Tools subclass BaseScorer, provide a system_prompt, and call
score(provider, user_message).  The base class handles provider
error catching and JSON/XML response parsing.
"""

import json
import logging
from dataclasses import dataclass

from local_first_common.llm import parse_json_response, try_xml_parse
from local_first_common.providers.base import BaseProvider

logger = logging.getLogger(__name__)


@dataclass
class ScoredItem:
    """Structured output from a content-relevance scoring run."""

    score: float
    tags: list[str]
    summary: str
    language: str = "en"


class BaseScorer:
    """Base class for LLM-based content scorers.

    Subclasses set ``system_prompt`` as a class attribute.  The caller
    builds the user message (prompt construction is tool-specific) and
    passes it to :meth:`score`.

    Example::

        class MyScorer(BaseScorer):
            system_prompt = "You are a relevance scorer.  Return JSON..."

        scorer = MyScorer()
        result = scorer.score(provider, user_message)
        # result is ScoredItem | None
    """

    system_prompt: str = ""  # subclass must override

    def __init__(self) -> None:
        self.xml_fallback_count: int = 0
        self.parse_error_count: int = 0

    def score(
        self,
        provider: BaseProvider,
        user_message: str,
    ) -> ScoredItem | None:
        """Call the provider and parse the response into a ScoredItem.

        Returns None on provider error or unparseable response.
        """
        try:
            raw = provider.complete(self.system_prompt, user_message)
        except Exception as e:  # noqa: BLE001 - any provider failure should score as "no result", per this method's own contract
            logger.warning("Provider error during scoring: %s", e)
            return None
        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> ScoredItem | None:
        """Try JSON first, then XML fallback.  Returns None on complete failure."""
        # --- JSON path ---
        try:
            data = parse_json_response(raw)
            return self._coerce(data)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            pass

        # --- XML fallback (reliability for local models) ---
        xml = try_xml_parse(raw, ["score", "summary", "language", "tags"])
        if xml:
            try:
                result = self._coerce_xml(xml)
                self.xml_fallback_count += 1
                return result
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("XML parse succeeded but coercion failed: %s", e)

        logger.warning("Both JSON and XML parsing failed for scorer response. Raw: %.200s", raw)
        self.parse_error_count += 1
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _coerce(self, data: dict) -> ScoredItem:
        """Coerce a parsed JSON dict into a ScoredItem."""
        return ScoredItem(
            score=float(data["score"]),
            tags=list(data.get("tags", []))[:2],
            summary=str(data.get("summary", "")),
            language=str(data.get("language", "en")).lower()[:2],
        )

    def _coerce_xml(self, xml: dict) -> ScoredItem:
        """Coerce an XML-parsed dict into a ScoredItem.

        Tags from XML come as a raw string (e.g. ``'["ai", "llm"]'`` or
        ``'ai, llm'``); we try JSON parse first, then comma-split.
        """
        tags_raw = xml.get("tags", "")
        try:
            tags = json.loads(tags_raw)
            if not isinstance(tags, list):
                tags = [str(tags_raw)]
        except (json.JSONDecodeError, ValueError):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        return ScoredItem(
            score=float(xml["score"]),
            tags=tags[:2],
            summary=str(xml.get("summary", "")),
            language=str(xml.get("language", "en")).lower()[:2],
        )
