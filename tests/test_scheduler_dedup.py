"""One reminder per thing to be reminded about.

`create()` had no notion of an existing schedule, so every "remind me to X"
added another entry. On a live deployment that meant two identical "Polish
resume and apply" reminders fired the same morning — and "Check front-end with
mechanic" coexisted with "Check frontend with mechanic". The user's response
was to ask the assistant to dismiss the stale ones by hand.

The common case is a *correction*: "remind me tomorrow to polish my resume",
then "can't right now, remind me 4pm". That is one reminder being moved, not
two reminders being wanted.
"""
from datetime import datetime, timedelta, timezone

import pytest

from api.services.scheduler_store import SchedulerStore

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    # file_path isolates both the markdown vault and the index cache.
    return SchedulerStore(file_path=str(tmp_path / "scheduler_index.json"))


def _at(hours_from_now: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).isoformat()


def _once(store, name, hours, **kwargs):
    return store.create(
        name=name, schedule_type="once", schedule_value=_at(hours),
        action="notify", message_content=name, **kwargs,
    )


class TestOneOffReminders:
    def test_the_same_reminder_moved_to_a_new_time_stays_one_entry(self, store):
        first = _once(store, "Polish resume and apply", 2)
        second = _once(store, "Polish resume and apply", 8)

        assert second.id == first.id
        assert len(store.list_all()) == 1

    def test_the_new_time_wins(self, store):
        _once(store, "Polish resume and apply", 2)
        moved = _once(store, "Polish resume and apply", 8)

        assert abs(
            datetime.fromisoformat(moved.schedule_value)
            - datetime.fromisoformat(_at(8))
        ) < timedelta(minutes=1)

    def test_spelling_variation_is_the_same_reminder(self, store):
        first = _once(store, "Check front-end with mechanic", 20)
        second = _once(store, "Check frontend with mechanic", 22)

        assert second.id == first.id

    def test_a_different_reminder_is_still_created(self, store):
        _once(store, "Polish resume and apply", 2)
        _once(store, "Call the mechanic", 2)

        assert len(store.list_all()) == 2

    def test_the_same_reminder_on_another_day_is_a_new_entry(self, store):
        """Recurring-by-hand is a real pattern: reminding me of the same thing
        tomorrow does not mean cancelling today's."""
        _once(store, "Update the car repair log", 1)
        _once(store, "Update the car repair log", 25)

        assert len(store.list_all()) == 2

    def test_a_disabled_reminder_does_not_absorb_a_new_one(self, store):
        """A fired one-off is disabled; asking again must schedule again."""
        first = _once(store, "Polish resume and apply", 2)
        store.update(first.id, enabled=False)

        second = _once(store, "Polish resume and apply", 3)
        assert second.id != first.id


class TestRecurringSchedules:
    def test_the_same_recurring_schedule_is_not_created_twice(self, store):
        first = store.create(
            name="Weekly Life Inbox Review", schedule_type="cron",
            schedule_value="0 11 * * 0", action="prompt", message_content="review",
        )
        second = store.create(
            name="weekly life inbox review", schedule_type="cron",
            schedule_value="0 11 * * 0", action="prompt", message_content="review",
        )

        assert second.id == first.id

    def test_a_different_cadence_is_a_different_schedule(self, store):
        store.create(
            name="Daily car repair check", schedule_type="cron",
            schedule_value="0 20 * * *", action="notify", message_content="?",
        )
        store.create(
            name="Daily car repair check", schedule_type="cron",
            schedule_value="0 9 * * *", action="notify", message_content="?",
        )

        assert len(store.list_all()) == 2

    def test_a_recurring_schedule_never_absorbs_a_one_off(self, store):
        store.create(
            name="Polish resume and apply", schedule_type="cron",
            schedule_value="0 9 * * 1", action="notify", message_content="?",
        )
        _once(store, "Polish resume and apply", 2)

        assert len(store.list_all()) == 2
