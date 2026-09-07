"""Transcribe voice notes in the language they're actually spoken in.

The Telegram voice path runs faster-whisper with `vad_filter=True` and
nothing else — no language, so every clip is auto-detected. Auto-detection on
short clips is unreliable, and it is worst for exactly the case that matters
here: the operator's voice notes are in Persian, and a wrong guess doesn't
degrade the transcript, it produces a fluent one in the wrong language that
then gets stored as a memory.

The model size is the other half. faster-whisper defaults to `base`, the
smallest useful model, which is markedly weaker on non-English speech than
`small`. Both are now settings rather than assumptions.
"""
import pytest

from api.services import telegram_transcription as tt

pytestmark = pytest.mark.unit


class _FakeModel:
    def __init__(self, *args, **kwargs):
        self.init_args, self.init_kwargs = args, kwargs
        self.transcribe_kwargs = None

    def transcribe(self, path, **kwargs):
        self.transcribe_kwargs = kwargs
        class _Seg:
            text = " hello "
        return [_Seg()], None


@pytest.fixture
def fake_model(monkeypatch):
    holder = {}

    def factory(*args, **kwargs):
        holder["model"] = _FakeModel(*args, **kwargs)
        return holder["model"]

    monkeypatch.setattr(tt, "_MODEL", None)
    monkeypatch.setattr(tt, "_load_model_class", lambda: factory)
    return holder


class TestLanguage:
    def test_a_configured_language_is_passed_through(self, fake_model, monkeypatch):
        monkeypatch.setenv("LIFEOS_TELEGRAM_WHISPER_LANGUAGE", "fa")
        tt.transcribe("clip.ogg")
        assert fake_model["model"].transcribe_kwargs["language"] == "fa"

    def test_unset_language_still_auto_detects(self, fake_model, monkeypatch):
        monkeypatch.delenv("LIFEOS_TELEGRAM_WHISPER_LANGUAGE", raising=False)
        tt.transcribe("clip.ogg")
        assert fake_model["model"].transcribe_kwargs.get("language") is None

    def test_vad_filtering_is_unchanged(self, fake_model, monkeypatch):
        monkeypatch.delenv("LIFEOS_TELEGRAM_WHISPER_LANGUAGE", raising=False)
        tt.transcribe("clip.ogg")
        assert fake_model["model"].transcribe_kwargs["vad_filter"] is True


class TestModelChoice:
    def test_the_model_size_is_configurable(self, fake_model, monkeypatch):
        monkeypatch.setenv("LIFEOS_TELEGRAM_WHISPER_MODEL", "small")
        tt.transcribe("clip.ogg")
        assert fake_model["model"].init_args[0] == "small"

    def test_it_still_defaults_to_base(self, fake_model, monkeypatch):
        """A 4GB box should not silently start loading a bigger model."""
        monkeypatch.delenv("LIFEOS_TELEGRAM_WHISPER_MODEL", raising=False)
        tt.transcribe("clip.ogg")
        assert fake_model["model"].init_args[0] == "base"


class TestOutput:
    def test_segments_are_joined_and_stripped(self, fake_model, monkeypatch):
        monkeypatch.delenv("LIFEOS_TELEGRAM_WHISPER_LANGUAGE", raising=False)
        assert tt.transcribe("clip.ogg") == "hello"
