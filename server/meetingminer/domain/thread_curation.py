"""Human corrections to machine thread grouping (story 10.2a, FR42).

Story 10.2 derives threads from topics and re-derives them, corpus-wide, on
every pass. This module is the layer that lets a human correct that grouping
**in a way the next pass preserves**, which is the only thing that makes the
correction worth making: a merge, split or rename that the next derivation
silently overwrote would be worse than no curation at all, because the user
would watch their own correction disappear and have no way to tell why.

**Curation is an input to the derivation, never an edit of its output.**
`domain/threads.py` owns `thread` and `topic_thread`; it rewrites
`thread.name` from the seed topic and moves each topic's membership onto
whichever thread the partition produced. So curation is stored in three
API-owned tables (migration 0021) that the derivation *reads before it
writes*, exactly as `pipeline/stages/align.py` reads `participant_alias`
before every participant insert (AD-5, migration 0005):

* ``thread_curation`` — a human name. The derivation writes ``thread.name``
  and never this column, so the two cannot collide. Readers display
  ``COALESCE(thread_curation.name, thread.name)`` and say which one they got,
  so a curated name is always distinguishable from a derived one.
* ``thread_alias`` — a merge, absorbed thread → survivor. The derivation
  resolves a cluster's thread through it before writing memberships, so the
  absorbed thread re-derives *into* the survivor every pass instead of
  re-separating from it.
* ``thread_topic_pin`` — a split, keyed on ``(meeting_id, normalized_name)``.
  The derivation applies the pin before the membership UPSERT, so a pinned
  topic is written once, to its pinned thread, and an unchanged rerun still
  writes nothing at all.

**One resolution rule, three readers.** The rule below — pin first, then one
alias hop — is implemented twice and only twice: here in Python for the
derivation, and in :data:`EFFECTIVE_MEMBERSHIP` for the SQL readers (the api's
thread routes and the graph projection). The SQL is kept in this module rather
than in either caller so the two spellings sit next to each other and are
pinned against each other by test.

**Why the SQL half joins pins on ``topic_id`` while the Python half joins on
normalized content.** The durable key is the content key: story 10.1 replaces
a meeting's ``topic`` rows wholesale on re-extraction, so a pin keyed on a
topic UUID would be discarded by that replacement. The derivation therefore
resolves pins by ``(meeting_id, normalized_name)``, which it can do because it
has :func:`~meetingminer.domain.threads.normalized_topic_name` — NFKC then
*casefold*, which Postgres has no equivalent of (``lower()`` differs on ``ß``
and the Turkish dotted forms, and a reader that disagreed with the writer
about a key is a bug that would surface only on the corpus that contains one).
The SQL half instead joins the pin's ``topic_id`` hint, and that is sufficient
because of what each half is for: **the SQL join only has to cover the window
between a split being made and the next derivation running.** In that window
the topic rows are the ones the split named, so the hint is exact. Once the
derivation has run, ``topic_thread`` itself carries the pinned target and its
curated provenance, so the hint is redundant. After a re-extraction the hint dangles, matches nothing,
and is redundant again — the re-extracted topics have no ``topic_thread`` row
of their own until the next derivation either way, which is story 10.2's
existing, documented un-threaded state.

**Nothing is discarded quietly** (AD-18). A pin whose durable key matches no
current topic is *not* deleted and *not* ignored in silence: it stays, and
:meth:`ThreadCuration.unmatched_pins` reports it so the derivation names it in
its own log event. The user's correction is still on record for the day the
subject comes back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence
from uuid import UUID, uuid4

from psycopg import Connection

# `domain/threads.py` imports this module at the top level, because the
# derivation resolves curation before it writes. The one call this module
# makes back into it — `normalized_topic_name`, in `pin_content_key` — is
# therefore imported inside that function rather than here: the dependency
# genuinely runs both ways (the derivation needs the rules, the rules need the
# one normalizer), and deferring the lighter half is what keeps the module
# graph loadable. It is a handful of calls per split, never a hot path.

# The `link_rule` a thread minted by a split carries, and the `linked_by` a
# derived/effective membership reports when a pin placed it. The API writes
# the former while `domain/threads.py` writes the latter from the API-owned
# pin input, so both are unambiguous evidence of a human decision.
CURATED_LINK_RULE = "curated"

# The namespace of a split thread's `identity_key`. Disjoint from every key
# the derivation can mint, and disjoint by construction rather than by luck:
# `normalized_topic_name` reduces a name to alphanumerics and single spaces,
# so a derived key contains neither ':' nor '-', and the one other derived
# form is the literal prefix 'topic-name-sha256:'. Because the spaces cannot
# overlap, `_threads_by_identity_key` can never reserve a curated row for a
# derived cluster.
CURATED_SPLIT_PREFIX = "curated-split:"


class ThreadCurationError(RuntimeError):
    """A curation that cannot be recorded coherently — named, never partial."""


def curated_split_identity_key() -> str:
    """Mint the identity key for a thread a split is creating.

    Random rather than derived from the split's content: two splits of the
    same subject in the same meeting are two deliberate human acts, and
    collapsing them onto one row because their content matched would be the
    machine overruling the user in exactly the direction this story forbids.
    """
    return f"{CURATED_SPLIT_PREFIX}{uuid4()}"


def is_curated_identity_key(identity_key: str) -> bool:
    """Whether this `thread` row was minted by a split rather than derived."""
    return identity_key.startswith(CURATED_SPLIT_PREFIX)


# The membership every reader outside `domain/threads.py` should use in place
# of `topic_thread`: the stored derivation with curation applied.
#
# Substituted for the table itself — `FROM (…) tt` — so a caller's existing
# `tt.topic_id` / `tt.thread_id` / `tt.linked_by` references keep working and
# a reader converted to it is a one-line change rather than a rewrite.
#
# The COALESCE order *is* the precedence rule: a pin overrides the derived
# thread, and a merge then applies to whatever that produced — so a thread
# created by a split and later merged away resolves all the way through to the
# survivor. Exactly one alias hop is followed, which is complete because
# migration 0021's `thread_alias_flat` trigger makes the map flat.
#
# `linked_by` is reported as 'curated' wherever a pin fired, because the row's
# stored leg ('seed', 'normalized-name', 'embedding-similarity') describes why
# the *machine* grouped the topic and would be a false explanation of a
# membership a human decided. `similarity` is dropped with it: the stored
# score is evidence for the machine's link, not for the human's.
EFFECTIVE_MEMBERSHIP = (
    "SELECT tt.topic_id,"
    " COALESCE(al.merged_into_id, pin.thread_id, tt.thread_id) AS thread_id,"
    f" CASE WHEN pin.topic_id IS NOT NULL THEN '{CURATED_LINK_RULE}'"
    " ELSE tt.linked_by END AS linked_by,"
    " CASE WHEN pin.topic_id IS NOT NULL THEN NULL"
    " ELSE tt.similarity END AS similarity,"
    " tt.created_at"
    " FROM topic_thread tt"
    " LEFT JOIN thread_topic_pin pin ON pin.topic_id = tt.topic_id"
    " LEFT JOIN thread_alias al"
    " ON al.thread_id = COALESCE(pin.thread_id, tt.thread_id)"
)

# The display name of a thread, for readers that select from `thread`.
# Written as a fragment rather than a view so the join stays visible in the
# query that uses it and in `EXPLAIN`.
CURATED_NAME_JOIN = (
    " LEFT JOIN thread_curation tc ON tc.thread_id = th.id"
)
CURATED_NAME_EXPR = "COALESCE(tc.name, th.name)"
CURATED_NAME_IS_CURATED_EXPR = (
    "(tc.thread_id IS NOT NULL OR th.link_rule = 'curated')"
)


@dataclass(frozen=True)
class ThreadCuration:
    """Every human correction on record, as one derivation pass needs it.

    Read once at the start of a pass rather than queried per topic: the three
    tables together are one row per human decision, which is orders of
    magnitude smaller than the topic set, and reading them once gives the
    whole pass a single consistent view of what the user asked for.
    """

    # thread id → the human name for it.
    curated_names: Mapping[UUID, str]
    # absorbed thread id → survivor thread id. Flat: no value is also a key.
    aliases: Mapping[UUID, UUID]
    # (meeting id, normalized topic name) → the thread that content is pinned
    # to. The durable key, which is why it survives a re-extraction.
    pins: Mapping[tuple[UUID, str], UUID]
    # (meeting id, normalized topic name) → the topic id the pin was written
    # against. Carried only so a pass can report which hints have gone stale.
    pin_topic_hints: Mapping[tuple[UUID, str], UUID]

    @property
    def is_empty(self) -> bool:
        return not (self.curated_names or self.aliases or self.pins)

    def follow_alias(self, thread_id: UUID) -> UUID:
        """One merge hop, which is all a flat map can need.

        Deliberately not a loop. If a chain ever existed — a trigger disabled
        during a restore, say — looping would hide it by quietly resolving to
        the end, while one hop leaves the wrong answer visible in a place a
        test can catch. The flatness is enforced at the record (0021).
        """
        return self.aliases.get(thread_id, thread_id)

    def thread_for(
        self, *, meeting_id: UUID, normalized_name: str, derived_thread_id: UUID
    ) -> tuple[UUID, bool]:
        """Where this topic's membership actually goes, and whether a pin sent it.

        The pin overrides the partition; the merge then applies to whatever
        that produced. Returned as one value so the caller writes the
        membership exactly once — resolving after the write would mean two
        UPDATEs of one row and would cost `derive_threads` the property that
        an unchanged rerun writes nothing at all.
        """
        pinned = self.pins.get((meeting_id, normalized_name))
        base = derived_thread_id if pinned is None else pinned
        return self.follow_alias(base), pinned is not None

    def unmatched_pins(
        self, present: Iterable[tuple[UUID, str]]
    ) -> tuple[tuple[UUID, str], ...]:
        """Pins whose subject is not in the corpus this pass can see.

        A pin is never deleted for failing to match — the meeting may simply
        not have been re-extracted yet, and the user's decision about that
        subject still stands. It is *reported*, so "your split did not apply
        this pass" is a sentence someone can read rather than an absence
        nobody can distinguish from success (AD-18).
        """
        available = set(present)
        return tuple(sorted(key for key in self.pins if key not in available))

    def stale_hints(self, topic_ids_by_key: Mapping[tuple[UUID, str], UUID]) -> int:
        """How many pins point at a topic row that no longer carries them.

        Informational, not a fault: the hint exists only to make a split
        visible between the click and the next derivation (see the module
        docstring), and a pass that has just written `topic_thread` has made
        it redundant. Counted so an operator reading the log can tell a
        lagging read path from a broken one.
        """
        stale = 0
        for key, hinted in self.pin_topic_hints.items():
            current = topic_ids_by_key.get(key)
            if current is not None and current != hinted:
                stale += 1
        return stale


def read_thread_curation(conn: Connection) -> ThreadCuration:
    """Load every curation row. One query per table, no joins, no ordering.

    Ordering is not read here because nothing downstream depends on it: the
    three maps are consulted by key. Leaving `ORDER BY` off keeps the read a
    plain sequential scan of three small tables.
    """
    curated_names = {
        row[0]: row[1]
        for row in conn.execute("SELECT thread_id, name FROM thread_curation").fetchall()
    }
    aliases = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT thread_id, merged_into_id FROM thread_alias"
        ).fetchall()
    }
    pins: dict[tuple[UUID, str], UUID] = {}
    hints: dict[tuple[UUID, str], UUID] = {}
    for meeting_id, normalized_name, thread_id, topic_id in conn.execute(
        "SELECT meeting_id, normalized_name, thread_id, topic_id FROM thread_topic_pin"
    ).fetchall():
        pins[(meeting_id, normalized_name)] = thread_id
        hints[(meeting_id, normalized_name)] = topic_id
    return ThreadCuration(
        curated_names=curated_names,
        aliases=aliases,
        pins=pins,
        pin_topic_hints=hints,
    )


def pin_content_key(*, meeting_id: UUID, topic_name: str) -> tuple[UUID, str]:
    """The durable key a pin is stored under, from a topic's own two facts.

    One function so the API that writes a pin and the derivation that reads it
    cannot disagree about what the key is — the mistake `participant`'s two
    key spaces were namespaced to prevent (migration 0005).
    """
    from meetingminer.domain.threads import normalized_topic_name

    normalized = normalized_topic_name(topic_name)
    if not normalized:
        raise ThreadCurationError(
            f"topic name {topic_name!r} normalizes to the empty string, so it"
            " has no durable identity to pin a split to — a name made only of"
            " punctuation cannot be told apart from another one in the same"
            " meeting, and pinning it would move whichever of them the next"
            " re-extraction happened to produce"
        )
    return (meeting_id, normalized)


def curated_thread_ids(conn: Connection, thread_ids: Sequence[UUID]) -> set[UUID]:
    """Which of these `thread` rows were minted by a split, not derived."""
    if not thread_ids:
        return set()
    return {
        row[0]
        for row in conn.execute(
            "SELECT id FROM thread WHERE id = ANY(%s) AND starts_with(identity_key, %s)",
            (list(thread_ids), CURATED_SPLIT_PREFIX),
        ).fetchall()
    }
