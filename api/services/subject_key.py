"""Record identity — deciding when two records are about the same thing.

Every store in LifeOS matched records by exact string, so it created a new one
every time it was told something. On a live deployment that produced 15
simultaneously-active "Car repair status (as of ...)" memories, two "Cafe AI"
projects, and the same reminder firing twice in a morning. The cost is not
storage: retrieval surfaced a days-old snapshot saying the car's electronic
lock was cleared, and the assistant repeated it back as current fact after the
user had corrected it.

`subject_key` is the shared, deliberately conservative answer. It is a
normalized, order-independent key for what a record is *about* — accents,
hyphenation, punctuation, word order and a small set of filler words are not
identity. It is not a similarity score: two records either produce the same
key or they don't, which keeps every merge decision explainable and testable.
Anything subtler than this belongs to a human or a model, not to a store.
"""
import re
import unicodedata

# Words that describe the *kind* of a record rather than its subject. Dropping
# them is what lets "Café AI product" and "Cafe AI" be one project — and is
# also why a key made only of these is no key at all.
_FILLER = frozenset({
    "the", "a", "an", "my", "our", "your", "this", "that", "and", "or", "of",
    "to", "for", "with", "on", "at", "in", "is", "are", "project", "product",
    "work", "item", "task", "status", "update", "idea", "note", "re",
})

# Labels the model habitually prefixes to a memory. Left in place they would
# make every "Memory: ..." line share one subject.
_LEADING_LABEL = re.compile(r"^\s*(?:memory|note|update|fyi)\s*:\s*", re.I)

# "Car repair status as of Aug 24, 2026: ..." — the date qualifier is exactly
# what differs between two snapshots of one subject, so it is not identity.
_AS_OF = re.compile(r"\s*(?:,\s*)?(?:as\s+of|for|on)\s+[^:]*$", re.I)

_PARENTHETICAL = re.compile(r"\([^)]*\)")

# A status line names its subject before its first separator. The model writes
# both "Car repair status (Aug 24): ..." and "Car repair status as of Aug 27,
# 2026 — TCM reset ...", so reading only the colon left half the snapshots
# outside supersession — and the one that survived in the corpus this came
# from was still asserting a claim the user had corrected. A hyphen counts
# only when spaced, so "front-end" stays one word.
_STATUS_LINE = re.compile(r"^(?P<subject>[^:\n—–]{3,80}?)\s*(?::\s|\s[—–-]\s)")


def subject_key(text: str) -> str:
    """Return a normalized identity key for ``text``.

    Two strings naming the same subject give the same key; an empty string
    means "nothing distinctive here", which callers must treat as *no match*
    rather than as a key that matches other empty keys.
    """
    folded = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    folded = folded.replace("&", " and ")
    # Join across intra-word punctuation ("front-end" == "frontend"), split on
    # everything else.
    folded = re.sub(r"[’'`\-_/]", "", folded)
    folded = re.sub(r"[^\w\s]", " ", folded)
    # Numbers are kept: "Job 1" and "Job 2" are different things. Dates that
    # would otherwise split one subject are removed by status_subject before
    # it gets here, not by throwing away every digit.
    tokens = {w for w in folded.split() if w not in _FILLER}
    return " ".join(sorted(tokens))


def status_subject(content: str) -> str | None:
    """Return the subject a status snapshot is about, or None.

    Only text shaped like "<subject>: <details>" has one. A plain statement
    ("My car key is lost") deliberately has no subject, so it can never be
    superseded by anything — supersession applies to running status, not to
    standalone facts.
    """
    text = _LEADING_LABEL.sub("", str(content or ""), count=1)
    match = _STATUS_LINE.match(text)
    if not match:
        return None
    subject = match.group("subject")
    # A URL's scheme colon is not a subject boundary.
    if "/" in subject or "://" in text[: match.end()]:
        return None
    subject = _PARENTHETICAL.sub(" ", subject)
    subject = _AS_OF.sub("", subject)
    return subject_key(subject) or None
