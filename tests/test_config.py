import importlib
import os


def _reload_config(monkeypatch, cfg_data):
    def fake_load_config(_tool_name):
        return cfg_data

    def fake_get_setting(_tool_name, _key, cli_val=None, env_var=None, default=None):
        if cli_val is not None:
            return cli_val
        if env_var and env_var in os.environ:
            return os.environ[env_var]
        return default

    monkeypatch.setattr("local_first_common.config.load_config", fake_load_config)
    monkeypatch.setattr("local_first_common.config.get_setting", fake_get_setting)

    from discovery import config

    return importlib.reload(config)


def test_defaults_use_settings_sources_list(monkeypatch):
    cfg = {
        "settings": {
            "sources": ["rss", "mastodon", "bluesky"],
            "store": "~/sync/content-discovery/store.db",
        }
    }

    config = _reload_config(monkeypatch, cfg)

    assert config.DEFAULT_SOURCES == "rss,mastodon,bluesky"
    assert config.STORE_PATH.endswith("/sync/content-discovery/store.db")


def test_store_env_var_overrides_settings_default(monkeypatch):
    monkeypatch.setenv("CONTENT_DISCOVERY_STORE", "~/tmp/content-discovery-override.db")

    cfg = {"settings": {"store": "~/sync/content-discovery/store.db"}}
    config = _reload_config(monkeypatch, cfg)

    assert config.STORE_PATH.endswith("/tmp/content-discovery-override.db")


def test_blocked_title_patterns_default_to_sponsor_markers(monkeypatch):
    config = _reload_config(monkeypatch, {"interests": {}})

    assert config.BLOCKED_TITLE_PATTERNS == ("(sponsor)", "(sponsored)")


def test_blocked_title_patterns_are_lowercased_from_config(monkeypatch):
    cfg = {"interests": {"blocked_title_patterns": ["(Sponsor)", "PARTNER CONTENT"]}}

    config = _reload_config(monkeypatch, cfg)

    assert config.BLOCKED_TITLE_PATTERNS == ("(sponsor)", "partner content")


def test_blocked_title_patterns_can_be_disabled(monkeypatch):
    cfg = {"interests": {"blocked_title_patterns": []}}

    config = _reload_config(monkeypatch, cfg)

    assert config.BLOCKED_TITLE_PATTERNS == ()
