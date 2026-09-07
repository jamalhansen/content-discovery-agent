"""Check a scoring config change against historical kept/dismissed decisions.

The problem this answers: you can't tell whether a scorer/prompt/profile
change actually helped without either trusting a vibe or re-reading
everything by hand. But every scored item -- kept, dismissed, or still
pending -- stays in the store forever (see store.py's module docstring), so
past human decisions are already a labeled dataset. `run_eval` re-scores a
random sample of that history with the *current* provider/profile/exclusions
and reports where the new scores agree or disagree with what was actually
decided at the time -- without touching the stored score or status.
"""
from dataclasses import dataclass, field

from .scorer import ContentDiscoveryScorer, score_item
from . import store


@dataclass
class EvalItem:
    title: str
    source: str
    old_score: float
    new_score: float


@dataclass
class EvalResult:
    n_kept_sampled: int = 0
    n_dismissed_sampled: int = 0
    n_scored: int = 0
    n_skipped: int = 0
    # Previously kept, would now fall below threshold -- a possible regression.
    regressions: list[EvalItem] = field(default_factory=list)
    # Previously dismissed, would now clear threshold -- worth a look, not
    # necessarily bad (could be a genuine improvement).
    drift: list[EvalItem] = field(default_factory=list)
    agreements: int = 0

    @property
    def n_compared(self) -> int:
        return self.agreements + len(self.regressions) + len(self.drift)

    @property
    def agreement_rate(self) -> float | None:
        if self.n_compared == 0:
            return None
        return self.agreements / self.n_compared


def run_eval(
    provider,
    threshold: float,
    interest_profile: str,
    interest_exclusions: str,
    store_path: str,
    n_kept: int = 40,
    n_dismissed: int = 80,
) -> EvalResult:
    """Re-score a random historical sample; report agreement with past decisions."""
    store.init_db(store_path)
    sample = store.get_eval_sample(store_path, n_kept=n_kept, n_dismissed=n_dismissed)
    result = EvalResult(
        n_kept_sampled=sum(1 for i in sample if i["status"] == "kept"),
        n_dismissed_sampled=sum(1 for i in sample if i["status"] == "dismissed"),
    )

    examples = store.get_examples(20, store_path, n_dismissed=40)
    scorer = ContentDiscoveryScorer()

    for item in sample:
        scored = score_item(
            provider,
            item["title"],
            item["description"],
            interest_profile,
            examples,
            interest_exclusions,
            scorer=scorer,
        )
        if scored is None:
            result.n_skipped += 1
            continue
        result.n_scored += 1

        passes_now = scored.score >= threshold
        was_kept = item["status"] == "kept"
        eval_item = EvalItem(
            title=item["title"],
            source=item["source"],
            old_score=item["score"],
            new_score=scored.score,
        )

        if was_kept and not passes_now:
            result.regressions.append(eval_item)
        elif not was_kept and passes_now:
            result.drift.append(eval_item)
        else:
            result.agreements += 1

    result.regressions.sort(key=lambda i: i.new_score)
    result.drift.sort(key=lambda i: i.new_score, reverse=True)
    return result
