import pytest
from local_first_common.testing import isolate_tracking_db  # noqa: F401


@pytest.fixture(autouse=True)
def no_live_side_effects(monkeypatch):
    """Stop the suite from reaching real accounts through live config.

    `orchestrator.READWISE_ROUTING` and `CONTEXTA_INBOX_ROUTING` are read from
    ~/.config at import time, so their value in a test run is whatever the
    machine happens to be configured for. On 2026-08-23 turning readwise_routing
    on in the real config made the suite POST a fixture titled "Test Article"
    into the live Readwise inbox, from tests that patched the vault-inbox side
    but not the Readwise side.

    Routing defaults to off here regardless of config. A test that wants routing
    on patches it explicitly, which is what the routing tests already do, and
    those patches still win because they are applied inside the test body.
    """
    import discovery.orchestrator as orch

    monkeypatch.setattr(orch, "READWISE_ROUTING", False, raising=False)
    monkeypatch.setattr(orch, "CONTEXTA_INBOX_ROUTING", False, raising=False)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch, request):
    """Fail loudly rather than silently reaching the network.

    Any test that genuinely needs an HTTP call marks itself with
    `@pytest.mark.allow_network`.
    """
    if request.node.get_closest_marker("allow_network"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError(
            "A test attempted a real HTTP request. Patch the caller, or mark the "
            "test with @pytest.mark.allow_network if the call is intended."
        )

    import requests

    for verb in ("get", "post", "patch", "put", "delete", "request"):
        monkeypatch.setattr(requests, verb, blocked, raising=False)
