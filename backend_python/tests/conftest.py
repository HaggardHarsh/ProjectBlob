import pytest
import sys


@pytest.fixture(autouse=True)
def isolate_agent_runtime(monkeypatch):
    """Keep legacy model mocks independent of the service's .env runtime choice.

    Hermes tests select the real worker explicitly. Individual configuration
    tests can override this setting with their own monkeypatch.
    """
    monkeypatch.setenv("BLOB_AGENT_RUNTIME", "classic")


@pytest.fixture(autouse=True)
def release_chroma_test_clients():
    """Each synthetic test owns its clients; release Rust runtimes between tests."""
    yield
    module = sys.modules.get("chromadb.api.shared_system_client")
    if module is not None:
        shared = module.SharedSystemClient
        for system in set(shared._identifier_to_system.values()):
            system.stop()
        shared.clear_system_cache()
