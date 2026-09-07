# ADR-023: Named Provider Presets in Front of the Model Registry

**Status:** Complete
**Last Updated:** 2026-09-07
**Decision:** Accepted

## Context

The provider/model registry (`LIFEOS_LLM_PROVIDERS` + `LIFEOS_LLM_MODELS`)
made LifeOS genuinely provider-independent: any Anthropic or
OpenAI-compatible endpoint can drive any named profile. What it did not do is
make that easy. The smallest real configuration — "use DeepSeek for
everything" — reads like this in `.env`:

```dotenv
LIFEOS_LLM_PROVIDERS='{"deepseek":{"type":"openai_compatible","base_url":"https://api.deepseek.com","api_key_env":"DEEPSEEK_API_KEY"}}'
LIFEOS_LLM_MODELS='{"default":{"provider":"deepseek","model":"deepseek-chat"},"fast":{"provider":"deepseek","model":"deepseek-chat"},"specialist":{"provider":"deepseek","model":"deepseek-chat"},"reasoning":{"provider":"deepseek","model":"deepseek-chat"}}'
```

Two hand-written JSON documents, one endpoint URL the operator has to look
up, and the same model id repeated four times — all to express a single
choice. It is quoting-sensitive, invisible to validation (a malformed blob is
logged and dropped, leaving the assistant silently on the wrong backend), and
it has to be redone from scratch to try a different provider for an evening.

A second, quieter problem: the OpenAI-compatible client hardcoded
`/v1/chat/completions`. Gemini's OpenAI compatibility layer lives at
`/v1beta/openai/chat/completions`, so Gemini — named in the project brief as
a provider that must work — could not actually be configured through the
registry at all.

## Decision

**A provider is selectable by name, and the JSON registry becomes the escape
hatch rather than the entry point.**

`PROVIDER_PRESETS` in `api/services/llm_client.py` holds a small catalogue of
known providers (anthropic, openai, deepseek, gemini, openrouter, groq,
mistral, local). Each preset carries the endpoint shape and starting models —
never a credential; the key is read at resolve time from the environment
variable the preset names. The DeepSeek configuration above becomes:

```dotenv
LIFEOS_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
```

`get_llm_registry()` now resolves in three layers, each overriding the last:

1. the built-in `anthropic`/`local` providers and the legacy
   `LIFEOS_LLM_BACKEND` defaults;
2. the `LIFEOS_LLM_PROVIDER` preset, which registers its provider and points
   `default`, `fast`, `specialist` and `reasoning` at it;
3. the explicit `LIFEOS_LLM_PROVIDERS` / `LIFEOS_LLM_MODELS` JSON.

Because the JSON is applied last, **a deployment already configured that way
keeps precisely its current behaviour** — including one that sets only some
profiles, where the preset fills the rest.

Individual model ids stay adjustable without abandoning the preset:
`LIFEOS_LLM_DEFAULT_MODEL`, `LIFEOS_LLM_FAST_MODEL`,
`LIFEOS_LLM_REASONING_MODEL`. (Deliberately not `LIFEOS_LLM_MODEL` — that
name already means the GGUF the `lifeos-llm` unit loads, and one variable
with two meanings is the trap this ADR exists to remove.)

A misspelled provider name is logged as an error naming the valid options and
then ignored, leaving the legacy backend in place. A typo in `.env` should not
be able to take the assistant down.

**`chat_path` moves onto the provider.** `LLMProviderConfig` and
`LocalLLMClient` carry the chat-completions path, defaulting to
`/v1/chat/completions`; the Gemini preset sets
`/v1beta/openai/chat/completions`. This is what makes Gemini reachable
without a provider-specific client, and it is available to hand-written
registry entries too.

**Not built:** provider auto-detection from whichever API key happens to be
present (magic, and wrong the moment two keys are set); a YAML config file
(one more configuration surface for a system that already reads `.env`); and
model-capability metadata beyond the existing `supports_vision` flag.

## Rationale

- **The preset encodes the part the operator cannot be expected to know** —
  the base URL, the compatibility path, which env var holds the key, which
  model belongs on the cheap profile — and leaves the part they do know (the
  provider name, their API key) as the whole configuration.
- **Layering the JSON last is what makes this safe to ship to an existing
  deployment.** There is no migration and no dual-write; the new path simply
  supplies defaults the old path can overwrite.
- **Model ids are starting points, not commitments.** They date faster than
  anything else in the file, so every one is overridable per profile without
  giving up the preset's endpoint knowledge.

## Alternatives Considered

### A YAML provider file (`config/llm.yaml`)

Closer to the shape sketched in the original project brief.

**Rejected because:** it adds a second configuration surface — precedence
questions against `.env`, a file to keep out of git, a parse step to fail —
to solve a problem that is really "the env var is hard to write." Making the
env var easy to write solves it without the new surface.

### Auto-detecting the provider from whichever API key is set

**Rejected because:** it is unpredictable exactly when it matters. An
operator with both `OPENAI_API_KEY` and `DEEPSEEK_API_KEY` present gets
whichever the implementation happens to check first, and finds out from their
bill.

### Keeping the JSON as the only path and just documenting it better

**Rejected because:** the documentation was already correct and complete.
Being correct did not stop a real deployment from carrying four copies of
`deepseek-chat` in a quoted JSON string.

## Consequences

### Positive

- Switching providers is a one-line change, which makes the
  provider-independence the architecture already had actually reachable.
- Gemini works through the registry for the first time, and any future
  provider with a non-`/v1` compatibility path needs a preset entry rather
  than client code.
- The `fast` profile gets a genuinely cheap model by default on each preset,
  so classification and extraction stop silently running on the expensive
  model.

### Negative

- **The catalogue's model ids will age.** A preset that names a retired model
  fails at call time with the provider's own error; the override variables
  are the fix, and keeping the catalogue current is now a maintenance duty.
- **Three configuration layers is one more than two.** Where a preset and the
  JSON disagree, the JSON silently wins — correct for compatibility, but it
  means a preset that "isn't taking effect" is usually a leftover
  `LIFEOS_LLM_MODELS` entry.

## Related Documents

### Design Context

- [ADR-021](021-provider-model-registry.md) — the registry these presets sit in
  front of
- [ADR-009](009-llm-backend-toggle.md) — the `LIFEOS_LLM_BACKEND` toggle both
  layer over

### Operational

- [Configuration](../guides/configuration.md) — `LIFEOS_LLM_PROVIDER` and the
  model override variables

### Code References

- `api/services/llm_client.py` — `PROVIDER_PRESETS`, `LLMProviderPreset`,
  `_resolve_preset()`, `get_llm_registry()`, `LocalLLMClient.chat_path`
- `tests/test_llm_provider_presets.py`
