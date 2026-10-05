"""Exploration probes: a few rejected items a week go to Reader, blind, for the calibration study."""

import random
from unittest.mock import MagicMock, patch

from discovery import store
from discovery.orchestrator import _TOOL, _maybe_route_probe
from discovery.scorer import ScoredItem


def _item(url="https://example.com/low", title="Low scorer"):
    item = MagicMock()
    item.url = url
    item.title = title
    item.source = "Example Blog"
    item.published = "2026-09-29"
    return item


def _result(score=0.2):
    return ScoredItem(score=score, tags=["misc"], summary="Low.", language="en")


class _AlwaysRng(random.Random):
    def random(self):
        return 0.0


class _NeverRng(random.Random):
    def random(self):
        return 0.99


def _patched(cap=4, routing=True, token="tok", probes_this_week=0):
    return (
        patch("discovery.orchestrator.PROBE_WEEKLY_CAP", cap),
        patch("discovery.orchestrator.READWISE_ROUTING", routing),
        patch("discovery.orchestrator.READWISE_TOKEN", token),
        patch("discovery.orchestrator.store.count_probes_since", return_value=probes_this_week),
        patch("discovery.orchestrator.store.mark_probed"),
        patch("discovery.orchestrator.save_to_readwise", return_value=True),
    )


def _run(pool, rng, dry_run=False, **kw):
    p = _patched(**kw)
    with p[0], p[1], p[2], p[3], p[4] as mark, p[5] as save:
        picked = _maybe_route_probe(pool, "/tmp/store.db", dry_run, rng=rng)
    return picked, save, mark


def test_probe_sent_untagged_and_recorded():
    item = _item()
    picked, save, mark = _run([(item, _result())], _AlwaysRng())
    assert picked is item
    save.assert_called_once_with(
        "tok",
        item.url,
        title=item.title,
        summary="Low.",
        tags=["misc"],
        published_date=item.published,
        search_term=item.search_term,
        platform=item.platform,
        tool=_TOOL,
    )
    assert "probe" not in save.call_args.kwargs["tags"]
    mark.assert_called_once_with(item.url, "/tmp/store.db")


def test_no_probe_when_weekly_cap_reached():
    picked, save, _ = _run([(_item(), _result())], _AlwaysRng(), probes_this_week=4)
    assert picked is None
    save.assert_not_called()


def test_no_probe_when_the_dice_say_no():
    picked, save, _ = _run([(_item(), _result())], _NeverRng())
    assert picked is None
    save.assert_not_called()


def test_disabled_by_zero_cap_or_no_routing():
    for kw in ({"cap": 0}, {"routing": False}, {"token": ""}):
        picked, save, _ = _run([(_item(), _result())], _AlwaysRng(), **kw)
        assert picked is None
        save.assert_not_called()


def test_dry_run_writes_nothing():
    picked, save, mark = _run([(_item(), _result())], _AlwaysRng(), dry_run=True)
    assert picked is not None
    save.assert_not_called()
    mark.assert_not_called()


def test_empty_pool():
    picked, save, _ = _run([], _AlwaysRng())
    assert picked is None
    save.assert_not_called()


def test_store_probe_round_trip(tmp_path):
    db = str(tmp_path / "store.db")
    store.init_db(db)
    store.upsert_item(
        url="https://example.com/a",
        title="A",
        source="s",
        description="",
        score=0.2,
        tags=[],
        summary="",
        fetched_at="2026-09-29",
        published_at="",
        path=db,
    )
    assert store.count_probes_since("2000-01-01", db) == 0
    store.mark_probed("https://example.com/a", db)
    assert store.count_probes_since("2000-01-01", db) == 1
    assert store.count_probes_since("2999-01-01", db) == 0
