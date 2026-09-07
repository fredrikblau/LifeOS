"""Withhold tools that provably have nothing behind them.

The agent loop hands the model the whole catalogue every turn, whatever is
actually configured. On a Telegram-first deployment with no Google account, no
Slack, no Monarch, an empty vault index and an empty CRM, most of that
catalogue is dead — and the model cannot tell, so it spends rounds finding
out. A measured turn made four `search_vault` calls across four model rounds
against an index holding zero vectors and zero BM25 rows. Each round is
1.5-4s of provider time and the user waits for every one.

Withholding those tools buys two things. The rounds go away, and the
assistant can say "Gmail isn't connected" instead of searching nothing and
reporting that it found nothing — which reads like a broken assistant rather
than an unfinished setup.

**Every probe fails open.** If we cannot prove a source is empty, the tool
stays. A wrongly withheld tool is a capability that silently disappeared,
which is far worse than a wasted round. Results are cached briefly so a turn
costs at most one cheap check per source, and so a source that gets populated
becomes usable within minutes without a restart.
"""
import logging
import time

logger = logging.getLogger(__name__)

# How long a probe result is trusted. Long enough that a burst of turns costs
# one check; short enough that finishing a sync makes the tools appear without
# anyone restarting anything.
_CACHE_TTL_SECONDS = 300

_cache: dict[str, tuple[float, bool]] = {}

# Tool -> (probe name, reason shown when it is withheld). A tool absent from
# this map has no backing source to be empty (save_memory, manage_tasks,
# search_web work on any deployment) and is never withheld.
_GATES: dict[str, tuple[str, str]] = {
    "search_vault": ("_vault_is_empty", "the vault index is empty — nothing has been indexed yet"),
    "read_vault_file": ("_vault_is_empty", "the vault index is empty — nothing has been indexed yet"),
    "person_info": ("_crm_is_empty", "the CRM has no people in it yet"),
    "get_message_history": ("_crm_is_empty", "the CRM has no people in it yet"),
    "search_email": ("_google_is_unconfigured", "the Google account is not connected"),
    "search_calendar": ("_google_is_unconfigured", "the Google account is not connected"),
    "search_drive": ("_google_is_unconfigured", "the Google account is not connected"),
    "search_slack": ("_slack_is_unconfigured", "Slack is not connected"),
    "search_finances": ("_monarch_is_unconfigured", "Monarch is not connected"),
}


def _cached(name: str, probe) -> bool:
    hit = _cache.get(name)
    now = time.monotonic()
    if hit and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    value = bool(probe())
    _cache[name] = (now, value)
    return value


def reset_cache() -> None:
    """Forget probe results — for tests, and after a sync populates a source."""
    _cache.clear()


def _vault_is_empty() -> bool:
    """True only when both halves of hybrid search hold nothing.

    Both, deliberately: one empty half is a half-built index, and search still
    returns real results from the other.
    """
    from api.services.bm25_index import get_bm25_index
    from api.services.vectorstore import get_vector_store

    if get_bm25_index().count() > 0:
        return False
    return get_vector_store().get_document_count() == 0


def _crm_is_empty() -> bool:
    from api.services.person_entity import PersonEntityStore

    return PersonEntityStore().count() == 0


def _google_is_unconfigured() -> bool:
    """True when no Google account has a stored token.

    Credentials alone are not enough — a headless host commonly has the OAuth
    client file and no token, which is exactly the state where every Google
    tool fails after costing a round. The token file's presence is checked,
    not its validity: an expired token refreshes itself, and a network probe
    here would cost more than the round it saves.
    """
    from api.services.google_auth import get_configured_accounts, get_google_auth

    for account in get_configured_accounts():
        if get_google_auth(account).token_path.exists():
            return False
    return True


def _slack_is_unconfigured() -> bool:
    from api.services.slack_integration import get_slack_client

    return not get_slack_client().is_configured()


def _monarch_is_unconfigured() -> bool:
    from config.settings import settings

    return not (settings.monarch_email and settings.monarch_password)


def filter_tools(tools: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Split ``tools`` into what to offer this turn and what to withhold.

    Returns (available, withheld) where ``withheld`` maps a tool name to the
    plain-language reason, suitable for telling the model — and through it,
    the user — what is missing rather than leaving it to guess.
    """
    available: list[dict] = []
    withheld: dict[str, str] = {}

    for tool in tools:
        gate = _GATES.get(tool.get("name", ""))
        if gate is None:
            available.append(tool)
            continue
        probe_name, reason = gate
        try:
            empty = _cached(probe_name, globals()[probe_name])
        except Exception as exc:
            # Fail open: an unreadable index must never delete a capability.
            logger.debug("Tool availability probe %s failed (%s) — keeping %s",
                         probe_name, exc, tool.get("name"))
            available.append(tool)
            continue
        if empty:
            withheld[tool["name"]] = reason
        else:
            available.append(tool)

    if withheld:
        logger.info("Withholding %d tool(s) with no data behind them: %s",
                    len(withheld), ", ".join(sorted(withheld)))
        available = _move_cache_breakpoint(tools, available)
    return available, withheld


def _move_cache_breakpoint(original: list[dict], available: list[dict]) -> list[dict]:
    """Keep exactly one prompt-cache breakpoint, on the new final tool.

    The catalogue marks its last entry with ``cache_control`` so the provider
    caches the whole stable schema. If that entry is the one withheld, the
    marker would vanish; if an earlier one is dropped, the marker is no longer
    last. Either way the copy is shallow-per-tool so the module-level
    catalogue is never mutated.
    """
    if not available or not any("cache_control" in tool for tool in original):
        return available
    rebuilt = [{k: v for k, v in tool.items() if k != "cache_control"} for tool in available]
    rebuilt[-1]["cache_control"] = {"type": "ephemeral"}
    return rebuilt


def unavailable_note(withheld: dict[str, str]) -> str:
    """A prompt block telling the model what is missing, and why.

    Without this the model just sees a smaller catalogue and invents an
    explanation for the gap. With it, "what's on my calendar?" gets "your
    Google account isn't connected yet" instead of a confident nothing.
    """
    if not withheld:
        return ""
    lines = "\n".join(f"- {name}: {reason}" for name, reason in sorted(withheld.items()))
    return (
        "## Tools unavailable this turn\n\n"
        "These tools are not offered because there is nothing behind them yet:\n"
        f"{lines}\n\n"
        "If the user asks for something that needs one, say plainly that the source "
        "isn't set up yet and what would connect it. Never claim you searched it, "
        "and never report an empty result as though you had looked."
    )
