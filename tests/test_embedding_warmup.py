"""Load the embedding model at startup, not on the user's first message.

The model loads lazily on first use. Measured across 60 real turns,
`memory_inject` has a median of 0.07s and a p90 of 6.26s — the p90 is
whichever unlucky message arrives first after a restart and pays for the
load. Since every deploy restarts the service, that is a reliable ~6s
penalty on the first thing the user says afterwards, on the surface where
they are waiting in a chat window.

Warming it in the background at startup moves that cost to a moment when
nobody is waiting. It must never block or break startup: a missing model
file or an offline hub is a degraded search, not a dead server.
"""
import pytest

from api.services import embedding_warmup

pytestmark = pytest.mark.unit


class TestWarmup:
    def test_it_loads_the_model(self, monkeypatch):
        loaded = []
        monkeypatch.setattr(embedding_warmup, "_load_model",
                            lambda: loaded.append("model"))

        embedding_warmup.warm()
        embedding_warmup.join(timeout=5)

        assert loaded == ["model"]

    def test_a_failure_does_not_escape(self, monkeypatch):
        """A model that won't load must degrade search, not stop the server."""
        def boom():
            raise RuntimeError("no model file")
        monkeypatch.setattr(embedding_warmup, "_load_model", boom)

        embedding_warmup.warm()          # must not raise
        embedding_warmup.join(timeout=5)

    def test_it_does_not_block_the_caller(self, monkeypatch):
        """Startup must not wait on a multi-second model load."""
        import threading
        release = threading.Event()
        monkeypatch.setattr(embedding_warmup, "_load_model", release.wait)

        embedding_warmup.warm()
        try:
            assert embedding_warmup.is_running()
        finally:
            release.set()
            embedding_warmup.join(timeout=5)

    def test_a_second_call_does_not_start_a_second_load(self, monkeypatch):
        import threading
        release = threading.Event()
        calls = []
        monkeypatch.setattr(embedding_warmup, "_load_model",
                            lambda: (calls.append(1), release.wait()))

        embedding_warmup.warm()
        embedding_warmup.warm()
        try:
            assert len(calls) == 1
        finally:
            release.set()
            embedding_warmup.join(timeout=5)
