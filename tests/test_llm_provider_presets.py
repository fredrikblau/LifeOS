"""One-line provider selection.

Pointing LifeOS at a non-Anthropic provider used to mean hand-writing two JSON
blobs into `.env` — a `LIFEOS_LLM_PROVIDERS` map describing the endpoint and a
`LIFEOS_LLM_MODELS` map naming the same model four times. A preset turns that
into `LIFEOS_LLM_PROVIDER=deepseek` plus the provider's own API key, which is
the whole configuration for the common "use one provider for everything" case.

The explicit JSON registry still wins wherever it is set, so a deployment
already configured that way keeps behaving exactly as it did.
"""
import pytest

from api.services.llm_client import PROVIDER_PRESETS, get_llm, get_llm_registry
from config.settings import settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_registry_env(monkeypatch):
    """Start each test from "nothing configured"."""
    monkeypatch.setattr(settings, "llm_providers_json", "")
    monkeypatch.setattr(settings, "llm_models_json", "")
    monkeypatch.setattr(settings, "llm_provider_preset", "")
    monkeypatch.setattr(settings, "llm_model_override", "")
    monkeypatch.setattr(settings, "llm_fast_model_override", "")
    monkeypatch.setattr(settings, "llm_reasoning_model_override", "")
    for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                "OPENROUTER_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(var, raising=False)


class TestPresetCatalog:
    def test_every_preset_is_complete(self):
        for name, preset in PROVIDER_PRESETS.items():
            assert preset.type, name
            assert preset.default_model, name
            # "anthropic" has no URL (SDK-managed) and "local" takes its URL
            # from LIFEOS_LOCAL_LLM_URL; every hosted provider needs one here.
            if preset.type != "anthropic" and name != "local":
                assert preset.base_url, name

    def test_covers_the_providers_the_brief_asks_for(self):
        for name in ("anthropic", "openai", "deepseek", "gemini",
                     "openrouter", "local"):
            assert name in PROVIDER_PRESETS


class TestPresetSelection:
    def test_provider_name_configures_every_profile(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider_preset", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dk_test")

        providers, models = get_llm_registry()

        assert providers["deepseek"].base_url == "https://api.deepseek.com"
        assert providers["deepseek"].api_key == "dk_test"
        for profile in ("default", "fast", "specialist", "reasoning"):
            assert models[profile].provider == "deepseek", profile
            assert models[profile].model

    def test_fast_profile_uses_the_presets_cheap_model(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider_preset", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")

        _, models = get_llm_registry()

        assert models["fast"].model == PROVIDER_PRESETS["openai"].fast_model
        assert models["default"].model == PROVIDER_PRESETS["openai"].default_model

    def test_model_override_replaces_the_preset_model(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider_preset", "deepseek")
        monkeypatch.setattr(settings, "llm_model_override", "deepseek-reasoner")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dk_test")

        _, models = get_llm_registry()

        assert models["default"].model == "deepseek-reasoner"
        # An override of the general model must not silently redefine the
        # cheap profile the classifiers run on.
        assert models["fast"].model == PROVIDER_PRESETS["deepseek"].fast_model

    def test_fast_and_reasoning_overrides_are_independent(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider_preset", "deepseek")
        monkeypatch.setattr(settings, "llm_fast_model_override", "cheap-model")
        monkeypatch.setattr(settings, "llm_reasoning_model_override", "big-model")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dk_test")

        _, models = get_llm_registry()

        assert models["fast"].model == "cheap-model"
        assert models["reasoning"].model == "big-model"
        assert models["default"].model == PROVIDER_PRESETS["deepseek"].default_model

    def test_case_and_whitespace_are_forgiven(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider_preset", "  DeepSeek ")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dk_test")

        _, models = get_llm_registry()

        assert models["default"].provider == "deepseek"

    def test_unknown_preset_is_ignored_not_fatal(self, monkeypatch, caplog):
        """A typo must not take the assistant down; it falls back to the
        legacy backend and says why."""
        monkeypatch.setattr(settings, "llm_provider_preset", "deepsek")

        _, models = get_llm_registry()

        assert models["default"].provider in ("anthropic", "local")
        assert "deepsek" in caplog.text


class TestExplicitConfigStillWins:
    def test_json_registry_overrides_the_preset(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider_preset", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dk_test")
        monkeypatch.setattr(
            settings, "llm_models_json",
            '{"default": {"provider": "local", "model": "gemma"}}',
        )

        _, models = get_llm_registry()

        assert models["default"].provider == "local"
        assert models["default"].model == "gemma"
        # Profiles the explicit config doesn't mention keep the preset.
        assert models["fast"].provider == "deepseek"

    def test_nothing_configured_keeps_the_legacy_default(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_backend", "anthropic")

        _, models = get_llm_registry()

        assert models["default"].provider == "anthropic"


class TestProviderChatPath:
    def test_openai_style_providers_use_the_v1_path(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider_preset", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dk_test")

        client = get_llm("default")

        assert client.chat_path == "/v1/chat/completions"

    def test_gemini_keeps_its_own_openai_compatible_path(self, monkeypatch):
        """Gemini's OpenAI-compatible endpoint lives under /v1beta/openai, so
        a hardcoded /v1 would 404 on every call."""
        monkeypatch.setattr(settings, "llm_provider_preset", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "gk_test")

        client = get_llm("default")

        assert client.chat_path == "/v1beta/openai/chat/completions"
        assert "generativelanguage.googleapis.com" in client.base_url


class TestMalformedSetting:
    def test_non_string_preset_is_not_a_provider_name(self, monkeypatch):
        """A mocked settings object must read as "unset", not as a provider
        named after its own repr."""
        monkeypatch.setattr(settings, "llm_provider_preset", object())

        _, models = get_llm_registry()

        assert models["default"].provider in ("anthropic", "local")
