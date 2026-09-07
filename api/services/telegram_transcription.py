"""Local speech-to-text for Telegram voice messages."""

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_MODEL = None
_MODEL_LOCK = threading.Lock()


def _load_model_class():
    """Return faster-whisper's WhisperModel, or explain that it isn't there."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Local transcription is not installed. Install the faster-whisper dependency."
        ) from exc
    return WhisperModel


def transcribe(path: str | Path) -> str:
    """Transcribe an audio file with a lazily loaded local Whisper model.

    ``LIFEOS_TELEGRAM_WHISPER_LANGUAGE`` (an ISO code such as ``fa``) is worth
    setting whenever voice notes are reliably in one language. Auto-detection
    is unreliable on short clips, and a wrong guess doesn't produce a poor
    transcript — it produces a fluent one in the wrong language, which then
    gets stored as a memory.
    """
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                model_class = _load_model_class()
                model_name = os.getenv("LIFEOS_TELEGRAM_WHISPER_MODEL", "base")
                device = os.getenv("LIFEOS_TELEGRAM_WHISPER_DEVICE", "cpu")
                compute_type = os.getenv("LIFEOS_TELEGRAM_WHISPER_COMPUTE_TYPE", "int8")
                logger.info("Loading Telegram Whisper model %s (%s/%s)", model_name, device, compute_type)
                _MODEL = model_class(model_name, device=device, compute_type=compute_type)

    options = {"vad_filter": True}
    language = (os.getenv("LIFEOS_TELEGRAM_WHISPER_LANGUAGE") or "").strip()
    if language:
        options["language"] = language

    segments, _info = _MODEL.transcribe(str(path), **options)
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
