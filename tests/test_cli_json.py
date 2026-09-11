import json
from unittest.mock import patch

from typer.testing import CliRunner

from discovery import store
from discovery.cli import app

runner = CliRunner()


def test_cmd_report_json(tmp_path):
    db_path = str(tmp_path / "test.db")
    store.init_db(db_path)
    result = runner.invoke(app, ["report", "--store", db_path, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "total" in data
    assert "pending" in data
    assert data["total"] == 0


def test_cmd_list_candidates_json(tmp_path):
    db_path = str(tmp_path / "test.db")
    store.init_db(db_path)
    store.upsert_item(
        url="https://example.com/item1",
        title="Item 1",
        source="Source 1",
        description="Desc",
        score=0.85,
        tags=["python", "ai"],
        summary="A summary",
        fetched_at="2026-09-08",
        path=db_path,
    )

    result = runner.invoke(app, ["list-candidates", "--store", db_path, "--json"])
    assert result.exit_code == 0
    items = json.loads(result.output)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/item1"
    assert items[0]["score"] == 0.85
    assert items[0]["tags"] == ["python", "ai"]


def test_cmd_run_json(tmp_path):
    db_path = str(tmp_path / "test.db")
    store.init_db(db_path)

    with patch("discovery.cli.run_discovery") as mock_disc:
        mock_disc.return_value = (
            [{"title": "Cand 1", "url": "https://example.com/1", "score": 0.9, "tags": ["tag"], "summary": "sum"}],
            1,
            0,
            [],
        )
        result = runner.invoke(
            app,
            ["run", "--json", "--no-llm", "--store", db_path],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "candidates" in data
        assert len(data["candidates"]) == 1
        assert data["scored_count"] == 1
        assert data["candidates"][0]["title"] == "Cand 1"


def test_cmd_search_kept_json(tmp_path):
    db_path = str(tmp_path / "test.db")
    store.init_db(db_path)
    store.upsert_item(
        url="https://example.com/kept1",
        title="Offline Search Strategies",
        source="Source 1",
        description="Desc",
        score=0.92,
        tags=["sqlite", "offline"],
        summary="A summary about offline search",
        fetched_at="2026-09-08",
        path=db_path,
    )
    store.mark_item("https://example.com/kept1", "kept", path=db_path)

    # Search with tag and query
    result = runner.invoke(
        app,
        ["search-kept", "--store", db_path, "--tag", "sqlite", "--query", "search", "--json"],
    )
    assert result.exit_code == 0
    items = json.loads(result.output)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/kept1"

    # Human-readable output
    result_text = runner.invoke(
        app,
        ["search-kept", "--store", db_path, "--query", "Offline"],
    )
    assert result_text.exit_code == 0
    assert "Offline Search Strategies" in result_text.output
