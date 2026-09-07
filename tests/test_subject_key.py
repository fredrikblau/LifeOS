"""Record identity: deciding when two records are about the same thing.

LifeOS created a new record every time it was told something, in all three
stores, because each one matched on an exact string:

- 15 of 36 memories on a live deployment were "Car repair status (as of ...)"
  snapshots, all active at once. Retrieval surfaced an Aug-23 one saying the
  car's electronic lock was cleared days after the user had said it wasn't,
  and the assistant repeated it back to them as fact.
- "Café AI product" and "Cafe AI" were two projects; so were "GitHub and
  resume open-source work" and its later restatement.
- "Polish resume and apply" fired twice on the same morning from two
  identical reminders, and "Check front-end with mechanic" coexisted with
  "Check frontend with mechanic".

`subject_key` is the shared answer: a normalized, order-independent key for
what a record is *about*.
"""
import pytest

from api.services.subject_key import status_subject, subject_key

pytestmark = pytest.mark.unit


class TestSubjectKey:
    def test_accents_do_not_split_a_subject(self):
        assert subject_key("Café AI product") == subject_key("Cafe AI")

    def test_word_order_does_not_matter(self):
        assert subject_key("resume polish") == subject_key("Polish resume")

    def test_hyphenation_does_not_split_a_subject(self):
        assert subject_key("Check front-end with mechanic") == \
               subject_key("Check frontend with mechanic")

    def test_ampersand_reads_as_and(self):
        assert subject_key("Career & open-source") == subject_key("Career and opensource")

    def test_different_subjects_stay_different(self):
        assert subject_key("Car repair") != subject_key("Car insurance")
        assert subject_key("GeoQ") != subject_key("Halal Protocol")

    def test_filler_words_are_not_identity(self):
        assert subject_key("the cafe AI project") == subject_key("Cafe AI")

    def test_a_number_is_part_of_the_identity(self):
        """"Job 1" and "Job 2" are two things, not one."""
        assert subject_key("Job 1") != subject_key("Job 2")
        assert subject_key("Sprint 3 planning") != subject_key("Sprint 4 planning")

    def test_empty_input_has_no_key(self):
        assert subject_key("") == ""
        assert subject_key("   ") == ""

    def test_a_key_is_only_filler_when_nothing_distinctive_remains(self):
        assert subject_key("the project") == ""


class TestStatusSubject:
    """Which memories are *snapshots* of a subject, and so supersede."""

    def test_status_line_names_its_subject(self):
        assert status_subject("Car repair status (as of Aug 24, 2026): brakes done") \
               == subject_key("car repair")

    def test_date_qualifier_does_not_change_the_subject(self):
        keys = {
            status_subject("Car repair status (August 2026): hub done"),
            status_subject("Car repair status as of Aug 23, 2026: hub done"),
            status_subject("Car repair status (as of ~Aug 31, 2026): battery fixed"),
            status_subject("Car repair (Aug 22): wheel hub given to the turner"),
            status_subject("Car repair status: front-end issue remains"),
        }
        assert len(keys) == 1
        assert keys.pop() == subject_key("car repair")

    def test_a_leading_memory_label_is_not_the_subject(self):
        """The model habitually prefixes "Memory:"; three unrelated memories
        must not all become the same subject."""
        a = status_subject("Memory: Amir's car flipped over in 2024.")
        b = status_subject("Memory: Agreement made with the owner of the cafe Qaf.")
        assert a != b or a is None

    def test_a_url_is_not_a_subject(self):
        """"https://x.com/..." has a colon but names nothing."""
        assert status_subject("https://x.com/someone/status/123\n\nSave this") is None

    def test_plain_statements_never_supersede_anything(self):
        assert status_subject("My car key is lost") is None
        assert status_subject("Amir wants to build an AI product for cafes.") is None

    def test_generic_labels_are_not_subjects(self):
        assert status_subject("Status: fine") is None
        assert status_subject("Note: pick up milk") is None

    def test_distinct_subjects_do_not_collide(self):
        assert status_subject("Car electrical issue (Aug 23): fuses fine") != \
               status_subject("Car repair status (Aug 23): hub done")
