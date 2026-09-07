"""Load the embedding model at startup instead of on the first message.

The model loads lazily on first use. Across 60 real turns on a live
deployment, `memory_inject` has a median of 0.07s and a p90 of 6.26s — that
p90 is whichever message happens to arrive first after a restart and pays for
the load. Every deploy restarts the service, so it is a dependable ~6s
penalty on the first thing the user says afterwards, in a chat window where
they are watching it not answer.

Warming it in a background thread moves the cost to a moment when nobody is
waiting. It never blocks startup and never raises: a model that won't load is
a degraded search (memory recall falls back to keyword-only, which the store
already handles), not a reason to fail the server.
"""
import logging
import threading

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_lock = threading.Lock()


def _load_model() -> None:
    """Touch the model so its weights are resident before anyone asks."""
    from api.services.embeddings import get_embedding_service

    service = get_embedding_service()
    # The property is what triggers the load; embedding one short string also
    # pays any first-call graph setup so the real first query doesn't.
    _ = service.model
    service.embed_text("warmup")


def _run() -> None:
    try:
        logger.info("Warming the embedding model…")
        _load_model()
        logger.info("Embedding model ready")
    except Exception as exc:
        # Degraded search, not a dead server. memory_store already falls back
        # to keyword-only recall when embeddings are unavailable.
        logger.warning("Embedding warmup failed (%s) — recall will load it on "
                       "first use instead", exc)


def warm() -> None:
    """Start the warmup in the background. Safe to call more than once."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_run, name="embedding-warmup", daemon=True)
        _thread.start()


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def join(timeout: float | None = None) -> None:
    """Wait for the warmup to finish — for tests and orderly shutdown."""
    if _thread is not None:
        _thread.join(timeout)
