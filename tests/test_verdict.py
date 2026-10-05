"""Human verdicts (2026-10-02): Jamal's call beside the model's status, feeding the examples."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from discovery import store
from discovery.cli import app

runner = CliRunner()
THRESHOLD = 0.75


def _add(path, url, title, score, status, source="Blog", fetched_at=None, reviewed_at=None):
    store.upsert_item(
        url=url,
        title=title,
        source=source,
        description="",
        score=score,
        tags=[],
        summary=f"Summary of {title}",
        fetched_at=fetched_at or datetime.now(UTC).date().isoformat(),
        path=path,
    )
    if status != "new":
        store.mark_item(url, status, path)
    if reviewed_at:
        with store._connect(path) as conn:
            conn.execute("UPDATE items SET reviewed_at = ? WHERE url = ?", (reviewed_at, url))


def _db(tmp_path):
    path = str(tmp_path / "store.db")
    store.init_db(path)
    return path


def test_migration_adds_verdict_columns_to_existing_db(tmp_path):
    path = str(tmp_path / "old.db")
    with store._connect(path) as conn:
        conn.execute(store._CREATE_TABLE)
    store.init_db(path)
    with store._connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
    assert {"human_verdict", "human_note", "verdict_at"} <= cols


def test_set_verdict_by_id_fragment_and_url_leaves_status_alone(tmp_path):
    path = _db(tmp_path)
    _add(path, "https://a.com/x", "Alpha post", 0.9, "kept")
    _add(path, "https://b.com/y", "Beta post", 0.3, "dismissed")

    by_fragment = store.set_verdict("Alpha", "dismiss", path, note="not for me")
    assert by_fragment["human_verdict"] == "dismiss"
    assert by_fragment["human_note"] == "not for me"
    assert by_fragment["status"] == "kept"  # the model's record is untouched
    assert by_fragment["verdict_at"]

    by_id = store.set_verdict(str(by_fragment["id"]), "keep", path)
    assert by_id["human_verdict"] == "keep"
    assert by_id["human_note"] is None  # a re-rating without a note clears the old one

    by_url = store.set_verdict("https://b.com/y", "keep", path)
    assert by_url["title"] == "Beta post"


def test_set_verdict_rejects_bad_input(tmp_path):
    path = _db(tmp_path)
    _add(path, "https://a.com/1", "Post one", 0.9, "kept")
    _add(path, "https://a.com/2", "Post two", 0.9, "kept")
    for bad in ("yes", "kept"):
        try:
            store.set_verdict("Post one", bad, path)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} accepted")
    try:
        store.set_verdict("Post", "keep", path)  # matches both
    except LookupError:
        pass
    else:
        raise AssertionError("ambiguous fragment accepted")


def test_candidates_mix_latest_keeps_with_nearest_recent_misses(tmp_path):
    path = _db(tmp_path)
    now = datetime.now(UTC)
    for i in range(6):
        _add(path, f"https://k.com/{i}", f"Kept {i}", 0.9, "kept", reviewed_at=(now - timedelta(hours=i)).isoformat())
    _add(path, "https://d.com/near", "Near miss", 0.70, "dismissed")
    _add(path, "https://d.com/far", "Far miss", 0.20, "dismissed")
    _add(path, "https://d.com/mid", "Mid miss", 0.50, "dismissed")
    _add(
        path,
        "https://d.com/old",
        "Old near miss",
        0.74,
        "dismissed",
        fetched_at=(now - timedelta(days=30)).date().isoformat(),
    )
    # Non-English items can be dismissed with a score over the threshold: not a near miss.
    _add(path, "https://d.com/lang", "Hoher Score, falsche Sprache", 0.95, "dismissed")
    _add(path, "https://r.com/mine", "Saved by Jamal", 0.9, "kept", source="readwise-reader")
    _add(path, "https://n.com/new", "Still pending", 0.9, "new")
    store.set_verdict("Kept 1", "keep", path)

    items = store.verdict_candidates(path, THRESHOLD, n_routed=4, n_rejected=2)
    titles = {i["title"] for i in items}
    assert titles == {"Kept 0", "Kept 2", "Kept 3", "Kept 4", "Near miss", "Mid miss"}

    # Blind order: by URL hash, so the keeps and misses interleave by chance, not by status.
    expected = sorted(items, key=lambda d: hashlib.sha256(d["url"].encode()).hexdigest())
    assert [i["url"] for i in items] == [i["url"] for i in expected]


def test_examples_prefer_verdicts_and_verdict_overrides_status(tmp_path):
    path = _db(tmp_path)
    now = datetime.now(UTC)
    # Machine decisions, newest first.
    for i in range(3):
        _add(
            path,
            f"https://m.com/k{i}",
            f"Machine kept {i}",
            0.9,
            "kept",
            source=f"s{i}",
            reviewed_at=(now - timedelta(minutes=i)).isoformat(),
        )
        _add(
            path,
            f"https://m.com/d{i}",
            f"Machine dismissed {i}",
            0.2,
            "dismissed",
            source=f"t{i}",
            reviewed_at=(now - timedelta(minutes=i)).isoformat(),
        )
    # An older item the model dismissed that Jamal says keep, and vice versa.
    _add(
        path,
        "https://h.com/fn",
        "Human says keep",
        0.3,
        "dismissed",
        source="u",
        reviewed_at=(now - timedelta(days=5)).isoformat(),
    )
    _add(
        path,
        "https://h.com/fp",
        "Human says dismiss",
        0.95,
        "kept",
        source="v",
        reviewed_at=(now - timedelta(days=5)).isoformat(),
    )
    store.set_verdict("Human says keep", "keep", path)
    store.set_verdict("Human says dismiss", "dismiss", path)

    ex = store.get_examples(3, path, n_dismissed=3)
    assert ex["kept"][0] == "Human says keep"
    assert "Human says dismiss" not in ex["kept"]
    assert ex["dismissed"][0] == "Human says dismiss"
    assert "Human says keep" not in ex["dismissed"]
    assert len(ex["kept"]) == 3 and len(ex["dismissed"]) == 3


def test_verdict_stats_agreement_buckets_and_example_slots(tmp_path):
    path = _db(tmp_path)
    _add(path, "https://a.com/1", "Agree keep", 0.88, "kept")
    _add(path, "https://a.com/2", "Agree dismiss", 0.31, "dismissed")
    _add(path, "https://a.com/3", "False positive", 0.85, "kept")
    _add(path, "https://a.com/4", "Unrated machine keep", 0.9, "kept")
    store.set_verdict("Agree keep", "keep", path)
    store.set_verdict("Agree dismiss", "dismiss", path)
    store.set_verdict("False positive", "dismiss", path)

    s = store.get_verdict_stats(path)
    assert s["rated"] == 3 and s["agreed"] == 2
    assert s["agreement_rate"] == round(2 / 3, 3)
    assert s["by_bucket"]["0.8"] == {"rated": 2, "agreed": 1, "keep": 1}
    assert s["by_bucket"]["0.3"] == {"rated": 1, "agreed": 1, "keep": 0}
    assert s["example_slots"]["kept"] == {"human": 1, "machine": 1}
    assert s["example_slots"]["dismissed"] == {"human": 2, "machine": 0}


def test_cli_pending_set_stats(tmp_path):
    path = _db(tmp_path)
    _add(path, "https://a.com/1", "First kept", 0.9, "kept")
    _add(path, "https://a.com/2", "A near miss", 0.72, "dismissed")

    r = runner.invoke(app, ["verdict", "pending", "--store", path, "-t", str(THRESHOLD), "--json"])
    assert r.exit_code == 0, r.output
    pending = json.loads(r.output)
    assert {p["title"] for p in pending} == {"First kept", "A near miss"}

    r = runner.invoke(app, ["verdict", "set", "near miss", "keep", "--note", "actually good", "--store", path])
    assert r.exit_code == 0, r.output
    assert "DISAGREED" in r.output

    r = runner.invoke(app, ["verdict", "set", "First", "nope", "--store", path])
    assert r.exit_code == 1

    r = runner.invoke(app, ["verdict", "stats", "--store", path, "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["rated"] == 1

    r = runner.invoke(app, ["verdict", "pending", "--store", path, "-t", str(THRESHOLD), "--json"])
    assert [p["title"] for p in json.loads(r.output)] == ["First kept"]
