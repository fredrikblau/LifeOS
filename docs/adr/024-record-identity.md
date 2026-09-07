# ADR-024: Records Have Subjects, Not Just Names

**Status:** Complete
**Last Updated:** 2026-09-07
**Decision:** Accepted

## Context

Every durable store in LifeOS decided "do I already have this?" by comparing
strings exactly. `create_memory` merged only byte-identical content;
`project_store.upsert` matched `_normalise(name)`; `SchedulerStore.create` did
not look at existing schedules at all. Each is a defensible local choice. The
aggregate is a system that creates a new record every time it is told
something, and a review of a live deployment's four weeks of use shows what
that costs:

- **Memories.** 26 of 36 memories were about one car repair, 15 of them
  "Car repair status (as of ...)" snapshots, all active simultaneously. This
  is not a storage problem. Retrieval surfaced an Aug-23 snapshot saying the
  car's electronic lock was cleared, and the assistant asserted it back to the
  user days after they had explicitly corrected it — "i still don't have the
  key for the car. i never said electronic lock is cleared." The contradicting
  memories coexisted with nothing marking either as current.
- **Projects.** "Café AI product" and "Cafe AI" were two projects for one
  thing. The newer record took every update; the older one kept a summary from
  two weeks earlier that still described the stale state — and the project
  store is what a life review reads.
- **Schedules.** Two identical "Polish resume and apply" reminders fired the
  same morning, because "remind me tomorrow" followed by "can't right now,
  remind me 4pm" created two entries instead of moving one. "Check front-end
  with mechanic" and "Check frontend with mechanic" coexisted for the same
  errand. The user's response was to ask the assistant to dismiss the stale
  ones by hand.

The brief this fork is built from asks for exactly the opposite: "Avoid
duplicating memories unnecessarily", "The assistant should not create
excessive structure for trivial information."

## Decision

**A record's identity is its subject, and one shared rule computes it.**

`api/services/subject_key.py` provides `subject_key(text)`: a normalized,
order-independent key in which accents, hyphenation, punctuation, word order,
and a small set of filler words ("the", "my", "project", "product", "work",
"status") are not identity, while numbers are ("Job 1" ≠ "Job 2"). A key made
entirely of filler is empty, and an empty key matches nothing.

It is deliberately **not** a similarity score. Two records either produce the
same key or they do not, so every merge is explainable, testable, and stable
across releases. Anything subtler belongs to a person or a model, not to a
store.

Three stores use it:

1. **Memories supersede.** `status_subject()` recognizes the "<subject>:
   <details>" shape of a status update and returns its subject with date
   qualifiers ("(as of Aug 24, 2026)", "as of Aug 23") removed. A new snapshot
   deactivates every earlier active snapshot of the same subject, linking it
   with `superseded_by`/`superseded_at`. A plain statement ("My car key is
   lost") has no subject: it never supersedes and is never superseded.
2. **Projects resolve by subject** in both `upsert` and `get_project`, so a
   write and a lookup agree about what exists. The original name is kept — a
   restatement updates a project, it does not rename it.
3. **Schedules dedupe on create.** A one-off restating an enabled one-off with
   the same subject *on the same local day* moves it; a recurring schedule
   matches only an identical cadence. Different days stay separate (asking to
   be reminded again tomorrow is a new reminder), and a fired — therefore
   disabled — one-off never absorbs a new request.

**Superseded memories are kept, deletions are not.** `_save` writes retired
snapshots to a separate `superseded` list: they cannot be recalled, the
human-editable `memories` list stays the current picture, and the trail of
what was believed and when survives a restart. A memory the *user* deleted
still leaves the file entirely — "forget that" has to mean it.

`scripts/collapse_stale_records.py` applies the same rule to data written
before this, dry-run by default.

**Not built:** embedding-similarity merging (a threshold that fires on the
real corpus also merges distinct facts, and a merge nobody can explain is
worse than a duplicate); cross-store identity (a project and a memory about
the same subject stay separate records); automatic supersession of plain
statements.

## Rationale

- **The failure was never "too many rows", it was "two answers, both live".**
  Supersession is the smallest change that makes one of them current, and it
  is what lets the assistant stop quoting a fact the user already corrected.
- **A key, not a score.** Every alternative that ranks similarity has a
  threshold, and a threshold on this corpus either misses the 15 car snapshots
  or swallows "Car electrical issue" into "Car repair". A rule that can be
  read in one function and pinned by tests is worth more here than recall.
- **Identity is the same question in all three stores**, so it is one module
  rather than three near-miss heuristics that drift apart.
- **The day is part of a one-off reminder's identity.** Without it, dedup
  would silently cancel tomorrow's reminder when you asked for one today.

## Alternatives Considered

### Ask the model to check for an existing record first

**Rejected because:** it is the arrangement that produced the duplicates. The
model does call `search_memories`, and still wrote the sixteenth car status —
because a near-duplicate does not look like a duplicate in prose. Correctness
that depends on the model noticing is not correctness.

### Semantic (embedding) similarity with a threshold

**Rejected because:** measured on the real corpus, no single cosine threshold
separates the 15 snapshots of one subject from genuinely distinct car facts.
And a wrong merge is unexplainable after the fact, where a wrong key is a
readable function anyone can fix.

### Let duplicates accumulate and rank by recency at retrieval time

**Rejected because:** recency ranking still returns the stale record when the
query matches it better, which is exactly how the electronic-lock claim
surfaced. It also leaves the project store — which is read wholesale by life
reviews, not ranked — untouched.

## Consequences

### Positive

- The newest reading of a subject is the only recallable one, so a correction
  actually takes effect instead of joining a pile of equals.
- One reminder per thing to be reminded about; a correction moves it.
- Life reviews read one project per project.
- The rule is one function, so a wrong merge is diagnosable and fixable rather
  than an opaque scoring accident.

### Negative

- **The status shape is a heuristic about how the model writes.** A snapshot
  phrased without a "<subject>:" prefix supersedes nothing and will still
  accumulate. This is deliberately the safe direction to fail — a missed
  supersession leaves a duplicate; an over-eager one hides a fact.
- **Filler words are a fixed list.** A project genuinely named "The Project"
  has an empty key and never matches, falling back to exact-name behaviour.
- **A newer snapshot is assumed to be a superset of the older one, and is not
  always.** In the real corpus, the Sep-6 car-repair snapshot silently dropped
  the lost-key blocker the Aug-31 one carried; retiring the older one therefore
  retires that detail with it. Two things limit the damage here — a standalone
  fact ("My car key is lost") has no subject and is never retired, and any
  snapshot the model phrases without a "<subject>:" prefix also survives — but
  the assumption is real, and it is the reason supersession deactivates rather
  than deletes.
- **Superseded memories still occupy the file**, and a subject updated daily
  for a year keeps a year of retired snapshots. Pruning them is deferred until
  there is a reason to.
- **Same-day one-off dedup can surprise.** Someone who deliberately wants two
  identical reminders on one day now gets one, moved to the later time.

## Related Documents

### Code References

- `api/services/subject_key.py` — `subject_key()`, `status_subject()`
- `api/services/memory_store.py` — `_supersede_older_snapshots()`, `_save`'s
  `superseded` list, `get_memory(include_inactive=True)`
- `api/services/project_store.py` — `_find()`
- `api/services/scheduler_store.py` — `_find_equivalent()`, `_same_local_day()`
- `scripts/collapse_stale_records.py`
- `tests/test_subject_key.py`, `tests/test_scheduler_dedup.py`
