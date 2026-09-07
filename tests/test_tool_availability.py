"""Don't offer a tool that has nothing behind it.

The agent is handed the full catalogue every turn regardless of what is
actually set up. On a Telegram-first deployment with no Google account, no
Slack, no Monarch, an empty vault index and an empty CRM, that is most of the
catalogue — and the model does not know, so it spends rounds looking. A
measured turn made four `search_vault` calls across four model rounds against
an index holding zero vectors and zero BM25 rows; each round costs 1.5–4s of
DeepSeek time, and the user waits for all of them.

Withholding a provably-empty tool does two things: it removes those rounds,
and it lets the assistant say "Gmail isn't connected" instead of searching
nothing and reporting nothing found.

Every probe fails *open*: if we cannot prove a source is empty, the tool
stays. A wrongly withheld tool is a capability that silently vanished, which
is far worse than a wasted round.
"""
import pytest

from api.services import tool_availability as ta

pytestmark = pytest.mark.unit


TOOLS = [
    {"name": "search_vault"}, {"name": "read_vault_file"},
    {"name": "person_info"}, {"name": "get_message_history"},
    {"name": "search_email"}, {"name": "search_calendar"}, {"name": "search_drive"},
    {"name": "search_slack"}, {"name": "search_finances"},
    {"name": "save_memory"}, {"name": "manage_tasks"}, {"name": "search_web"},
]


@pytest.fixture(autouse=True)
def _no_stale_probes():
    """Probe results are cached for 5 minutes; each test starts cold."""
    ta.reset_cache()
    yield
    ta.reset_cache()


@pytest.fixture
def all_present(monkeypatch):
    """Everything configured and populated — nothing should be withheld."""
    monkeypatch.setattr(ta, "_vault_is_empty", lambda: False)
    monkeypatch.setattr(ta, "_crm_is_empty", lambda: False)
    monkeypatch.setattr(ta, "_google_is_unconfigured", lambda: False)
    monkeypatch.setattr(ta, "_slack_is_unconfigured", lambda: False)
    monkeypatch.setattr(ta, "_monarch_is_unconfigured", lambda: False)


def names(tools):
    return {t["name"] for t in tools}


class TestNothingWithheldByDefault:
    def test_a_fully_configured_system_keeps_every_tool(self, all_present):
        available, withheld = ta.filter_tools(TOOLS)
        assert names(available) == names(TOOLS)
        assert withheld == {}

    def test_the_same_list_object_is_not_mutated(self, all_present):
        before = list(TOOLS)
        ta.filter_tools(TOOLS)
        assert TOOLS == before

    def test_a_probe_that_raises_keeps_the_tool(self, monkeypatch, all_present):
        """Fail open: an unreadable index must not delete a capability."""
        def boom():
            raise RuntimeError("chroma is down")
        monkeypatch.setattr(ta, "_vault_is_empty", boom)

        available, withheld = ta.filter_tools(TOOLS)
        assert "search_vault" in names(available)
        assert "search_vault" not in withheld


class TestWithholding:
    def test_an_empty_vault_index_withholds_the_vault_tools(self, monkeypatch, all_present):
        monkeypatch.setattr(ta, "_vault_is_empty", lambda: True)
        available, withheld = ta.filter_tools(TOOLS)

        assert "search_vault" not in names(available)
        assert "read_vault_file" not in names(available)
        assert "search_vault" in withheld

    def test_an_empty_crm_withholds_the_people_tools(self, monkeypatch, all_present):
        monkeypatch.setattr(ta, "_crm_is_empty", lambda: True)
        available, _ = ta.filter_tools(TOOLS)

        assert "person_info" not in names(available)
        assert "get_message_history" not in names(available)

    def test_unconfigured_google_withholds_its_three_tools(self, monkeypatch, all_present):
        monkeypatch.setattr(ta, "_google_is_unconfigured", lambda: True)
        available, _ = ta.filter_tools(TOOLS)

        assert not {"search_email", "search_calendar", "search_drive"} & names(available)

    def test_tools_with_no_backing_source_are_never_withheld(self, monkeypatch):
        """save_memory, manage_tasks and search_web work on any deployment."""
        for probe in ("_vault_is_empty", "_crm_is_empty", "_google_is_unconfigured",
                      "_slack_is_unconfigured", "_monarch_is_unconfigured"):
            monkeypatch.setattr(ta, probe, lambda: True)

        available, _ = ta.filter_tools(TOOLS)
        assert {"save_memory", "manage_tasks", "search_web"} <= names(available)

    def test_withheld_carries_a_reason_the_user_could_read(self, monkeypatch, all_present):
        monkeypatch.setattr(ta, "_google_is_unconfigured", lambda: True)
        _, withheld = ta.filter_tools(TOOLS)

        assert "Google" in withheld["search_email"]


class TestCacheControlSurvives:
    def test_the_cache_breakpoint_moves_to_the_new_last_tool(self, monkeypatch, all_present):
        """The catalogue's final entry carries cache_control; dropping tools
        must leave exactly one breakpoint, on whatever is now last."""
        tools = [dict(t) for t in TOOLS]
        tools[-1]["cache_control"] = {"type": "ephemeral"}
        monkeypatch.setattr(ta, "_vault_is_empty", lambda: True)

        available, _ = ta.filter_tools(tools)

        marked = [t for t in available if "cache_control" in t]
        assert len(marked) == 1
        assert marked[0] is available[-1]

    def test_no_breakpoint_is_added_when_there_was_none(self, all_present):
        available, _ = ta.filter_tools(TOOLS)
        assert not any("cache_control" in t for t in available)


class TestTurnNote:
    def test_the_note_names_what_is_missing_and_why(self):
        note = ta.unavailable_note({
            "search_email": "Google account is not connected",
            "search_vault": "the vault index is empty",
        })
        assert "search_email" in note and "search_vault" in note
        assert "Google account is not connected" in note

    def test_no_note_when_nothing_is_withheld(self):
        assert ta.unavailable_note({}) == ""


class TestTheProbesActuallyRun:
    """The unit tests above stub every probe, so they would pass just as
    happily if each real one raised on import — and a raising probe fails
    open, which looks exactly like the feature working and withholding
    nothing. These call the real ones."""

    @pytest.mark.parametrize("probe", [
        "_vault_is_empty", "_crm_is_empty", "_google_is_unconfigured",
        "_slack_is_unconfigured", "_monarch_is_unconfigured",
    ])
    def test_probe_returns_a_bool_without_raising(self, probe):
        if probe == "_vault_is_empty":
            # Only this probe reaches ChromaDB, which a lint/unit-only
            # environment need not have installed.
            pytest.importorskip("chromadb")
        result = getattr(ta, probe)()
        assert isinstance(result, bool)
