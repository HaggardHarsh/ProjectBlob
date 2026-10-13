import pytest


@pytest.fixture(autouse=True)
def isolate_agent_runtime(monkeypatch):
    """Keep legacy model mocks independent of the service's .env runtime choice.

    Hermes tests select the real worker explicitly. Individual configuration
    tests can override this setting with their own monkeypatch.
    """
    monkeypatch.setenv("BLOB_AGENT_RUNTIME", "classic")
