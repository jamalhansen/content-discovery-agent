"""Tests for `discover eval` -- checking a scoring config change against
historical kept/dismissed decisions without mutating the stored data.
"""
from unittest.mock import patch

from local_first_common.scoring import ScoredItem
from local_first_common.testing import MockProvider

from discovery import store
from discovery.eval import run_eval


def _seed(path, *, kept: list[dict] | None = None, dismissed: list[dict] | None = None):
    store.init_db(path)
    for i, item in enumerate(kept or []):
        url = item.get("url", f"https://kept.example.com/{i}")
        store.upsert_item(
            url=url, title=item.get("title", f"Kept {i}"),
            source=item.get("source", "Blog"), description="desc",
            score=item.get("score", 0.9), tags=[], summary="s",
            fetched_at="2026-08-01", path=path,
        )
        store.mark_item(url, "kept", path)
    for i, item in enumerate(dismissed or []):
        url = item.get("url", f"https://dismissed.example.com/{i}")
        store.upsert_item(
            url=url, title=item.get("title", f"Dismissed {i}"),
            source=item.get("source", "Blog"), description="desc",
            score=item.get("score", 0.3), tags=[], summary="s",
            fetched_at="2026-08-01", path=path,
        )
        store.mark_item(url, "dismissed", path)


class TestRunEval:
    def test_agreement_kept_stays_above_threshold(self, tmp_path):
        path = str(tmp_path / "store.db")
        _seed(path, kept=[{"title": "Kept One"}])
        with patch("discovery.eval.score_item") as mock_score, \
             patch("discovery.eval.store.get_examples", return_value={}):
            mock_score.return_value = ScoredItem(score=0.85, tags=[], summary="s", language="en")
            result = run_eval(MockProvider(), 0.7, "profile", "", path, n_kept=1, n_dismissed=0)

        assert result.n_scored == 1
        assert result.agreements == 1
        assert result.regressions == []
        assert result.drift == []
        assert result.agreement_rate == 1.0

    def test_agreement_dismissed_stays_below_threshold(self, tmp_path):
        path = str(tmp_path / "store.db")
        _seed(path, dismissed=[{"title": "Dismissed One"}])
        with patch("discovery.eval.score_item") as mock_score, \
             patch("discovery.eval.store.get_examples", return_value={}):
            mock_score.return_value = ScoredItem(score=0.2, tags=[], summary="s", language="en")
            result = run_eval(MockProvider(), 0.7, "profile", "", path, n_kept=0, n_dismissed=1)

        assert result.agreements == 1
        assert result.regressions == []
        assert result.drift == []

    def test_regression_previously_kept_now_below_threshold(self, tmp_path):
        path = str(tmp_path / "store.db")
        _seed(path, kept=[{"title": "Kept One", "score": 0.9}])
        with patch("discovery.eval.score_item") as mock_score, \
             patch("discovery.eval.store.get_examples", return_value={}):
            mock_score.return_value = ScoredItem(score=0.4, tags=[], summary="s", language="en")
            result = run_eval(MockProvider(), 0.7, "profile", "", path, n_kept=1, n_dismissed=0)

        assert len(result.regressions) == 1
        assert result.regressions[0].title == "Kept One"
        assert result.regressions[0].old_score == 0.9
        assert result.regressions[0].new_score == 0.4
        assert result.agreements == 0

    def test_drift_previously_dismissed_now_above_threshold(self, tmp_path):
        path = str(tmp_path / "store.db")
        _seed(path, dismissed=[{"title": "Dismissed One", "score": 0.3}])
        with patch("discovery.eval.score_item") as mock_score, \
             patch("discovery.eval.store.get_examples", return_value={}):
            mock_score.return_value = ScoredItem(score=0.8, tags=[], summary="s", language="en")
            result = run_eval(MockProvider(), 0.7, "profile", "", path, n_kept=0, n_dismissed=1)

        assert len(result.drift) == 1
        assert result.drift[0].title == "Dismissed One"
        assert result.agreements == 0

    def test_skipped_items_do_not_count_as_scored(self, tmp_path):
        path = str(tmp_path / "store.db")
        _seed(path, kept=[{"title": "Kept One"}])
        with patch("discovery.eval.score_item") as mock_score, \
             patch("discovery.eval.store.get_examples", return_value={}):
            mock_score.return_value = None
            result = run_eval(MockProvider(), 0.7, "profile", "", path, n_kept=1, n_dismissed=0)

        assert result.n_scored == 0
        assert result.n_skipped == 1
        assert result.agreement_rate is None

    def test_does_not_mutate_stored_score_or_status(self, tmp_path):
        path = str(tmp_path / "store.db")
        _seed(path, kept=[{"title": "Kept One", "score": 0.9, "url": "https://k.example.com"}])
        with patch("discovery.eval.score_item") as mock_score, \
             patch("discovery.eval.store.get_examples", return_value={}):
            mock_score.return_value = ScoredItem(score=0.1, tags=[], summary="s", language="en")
            run_eval(MockProvider(), 0.7, "profile", "", path, n_kept=1, n_dismissed=0)

        row = store.get_status_summary(path)
        kept_row = next(r for r in row if r["status"] == "kept")
        assert kept_row["avg_score"] == 0.9  # untouched, not overwritten with 0.1

    def test_agreement_rate_reflects_mixed_results(self, tmp_path):
        path = str(tmp_path / "store.db")
        _seed(
            path,
            kept=[{"title": "Kept Agree", "url": "https://k1.example.com"},
                  {"title": "Kept Regress", "url": "https://k2.example.com"}],
        )
        with patch("discovery.eval.score_item") as mock_score, \
             patch("discovery.eval.store.get_examples", return_value={}):
            mock_score.side_effect = [
                ScoredItem(score=0.9, tags=[], summary="s", language="en"),
                ScoredItem(score=0.1, tags=[], summary="s", language="en"),
            ]
            result = run_eval(MockProvider(), 0.7, "profile", "", path, n_kept=2, n_dismissed=0)

        assert result.n_compared == 2
        assert result.agreement_rate == 0.5
