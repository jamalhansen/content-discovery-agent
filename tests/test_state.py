import json
import os
import pytest
from state import load_state, save_state


class TestLoadState:
    def test_returns_empty_set_if_file_missing(self, tmp_path):
        path = str(tmp_path / "state.json")
        result = load_state(path)
        assert result == set()

    def test_loads_seen_urls(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"seen": ["https://a.com", "https://b.com"]}))
        result = load_state(str(path))
        assert result == {"https://a.com", "https://b.com"}

    def test_handles_corrupted_file(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("not valid json")
        result = load_state(str(path))
        assert result == set()

    def test_handles_missing_seen_key(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({}))
        result = load_state(str(path))
        assert result == set()


class TestSaveState:
    def test_saves_seen_urls(self, tmp_path):
        path = str(tmp_path / "state.json")
        seen = {"https://a.com", "https://b.com"}
        save_state(path, seen)

        with open(path) as f:
            data = json.load(f)
        assert set(data["seen"]) == seen

    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "state.json")
        seen = {"https://x.com/1", "https://x.com/2", "https://x.com/3"}
        save_state(path, seen)
        loaded = load_state(path)
        assert loaded == seen

    def test_overwrites_existing(self, tmp_path):
        path = str(tmp_path / "state.json")
        save_state(path, {"https://old.com"})
        save_state(path, {"https://new.com"})
        loaded = load_state(path)
        assert loaded == {"https://new.com"}
