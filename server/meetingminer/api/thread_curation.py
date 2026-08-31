"""PATCH /threads/{id}, POST /threads/{id}/merge, POST /threads/{id}/split
(story 10.2a, FR42).

The write half of threads. `api/threads.py` reads what the machine derived;
this module records what a human decided about it — and records it in the
three API-owned tables migration 0021 declares, never as an edit of `thread`'s
derived columns or of `topic_thread`. That distinction is the entire story: the
worker re-derives every thread from the stored topics on every pass, so a
curation written into the machine's own output is a curation the next pass
silently reverses.

**Exactly what this module writes** (AD-5):

* ``thread_curation`` — a rename.
* ``thread_alias`` — a merge, absorbed → survivor.
* ``thread_topic_pin`` — a split's pins, keyed on durable normalized content.
* ``thread`` — **one row, and only on a split**, because a split's product
  needs a `thread.id` for story 10.3's timeline to address and a
  `color_ordinal` for the view to colour, and neither can be conjured from a
  curation table. This is the narrow exception `api/speakers.py` already holds
  against worker-owned `participant`: a curator may mint the identity the
  machine could not produce on its own. The minted row is namespaced
  (`curated-split:`) into a key space the derivation cannot mint or reuse, so
  it can never be claimed by a later pass.

**Nothing here touches `color_ordinal`** (migration 0017). A merge writes an
alias row and renames nothing; a split *inserts*, so the sequence allocates.
0017's immutability trigger would refuse anything else, and no statement in
this module names the column.

**No chained aliases.** A→B→C would strand A on a thread that is itself merged
away, because every resolver in the codebase follows exactly one hop. Both
sides of a merge must therefore be canonical, the same rule
`api/participants.py` states — enforced here *and* by 0021's
`thread_alias_flat` trigger, because thread curation has two independent
resolvers (this api's read path and the worker's derivation) and a rule held
only in one of them is not a guarantee for the other.

**The effect is visible immediately, and durable separately.** A curation
shows up in the very next `GET /threads` because the read path resolves these
tables live; it survives the next derivation because `derive_threads` resolves
the same tables before it writes. Those are two different mechanisms reading
one record, which is why the view never shows a correction that the next
rerun will quietly undo.

No store client and no Neo4j write (AD-4/AD-5): curation reaches the graph at
the next projection pass, which reads the same resolved membership.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import psycopg.errors
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from pydantic.alias_generators import to_camel
from psycopg.types.json import Jsonb

from meetingminer import logs
from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.domain.thread_curation import (
    CURATED_LINK_RULE,
    CURATED_NAME_IS_CURATED_EXPR,
    EFFECTIVE_MEMBERSHIP,
    ThreadCurationError,
    curated_split_identity_key,
    pin_content_key,
)

router = APIRouter()

# A thread name is a subject line, not free text. The same cap and the same
# `strip_whitespace`-before-`min_length` ordering as `api/participants.py`'s
# display name, so a whitespace-only name is a 422 rather than a rename to
# blank — deliberately identical, because a curator meeting both screens
# should not discover that two rename boxes disagree about what a name is.
THREAD_NAME_MAX_LENGTH = 200
ThreadName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=THREAD_NAME_MAX_LENGTH),
]

# The most topics one split may move. A split is a human pointing at a handful
# of misgrouped subjects; a request naming thousands is a client bug or a
# misuse, and the cap turns it into a named refusal rather than a long
# transaction holding row locks on `thread`.
SPLIT_TOPIC_LIMIT = 500

# The thread row plus its curation state, in one statement. The two LEFT JOINs
# are the whole of what curation adds to a thread's identity: the human name
# if there is one, and the survivor if this thread has been merged away.
_THREAD_WITH_CURATION = (
    "SELECT th.id, COALESCE(tc.name, th.name), th.name,"
    f" {CURATED_NAME_IS_CURATED_EXPR},"
    " th.color_ordinal, al.merged_into_id, th.identity_key"
    " FROM thread th"
    " LEFT JOIN thread_curation tc ON tc.thread_id = th.id"
    " LEFT JOIN thread_alias al ON al.thread_id = th.id"
    " WHERE th.id = %s"
)

# The write paths' locking fetch. `FOR UPDATE OF th` for the reason
# `api/participants.py` gives: it serializes two requests naming the same
# thread, and `OF th` because a plain `FOR UPDATE` cannot apply to the nullable
# side of a LEFT JOIN. The curation tables themselves are not locked — a
# not-yet-existing alias row has nothing to lock, which is also why every
# route below runs at READ COMMITTED so the checks after the lock wait see
# what the wait resolved rather than a snapshot taken before it.
_THREAD_FOR_UPDATE = _THREAD_WITH_CURATION + " FOR UPDATE OF th"

_IS_MERGED_AWAY = "SELECT 1 FROM thread_alias WHERE thread_id = %s"

# A thread that has already absorbed another may not itself be merged away:
# that is the A→B→C chain one-hop resolution cannot follow.
_HAS_ABSORBED = "SELECT 1 FROM thread_alias WHERE merged_into_id = %s"

_UPSERT_CURATED_NAME = (
    "INSERT INTO thread_curation (thread_id, name) VALUES (%s, %s)"
    " ON CONFLICT (thread_id) DO UPDATE SET name = EXCLUDED.name"
    " WHERE thread_curation.name IS DISTINCT FROM EXCLUDED.name"
)

_CLEAR_CURATED_NAME = "DELETE FROM thread_curation WHERE thread_id = %s"

_INSERT_ALIAS = (
    "INSERT INTO thread_alias (thread_id, merged_into_id) VALUES (%s, %s)"
)

# The topics a thread actually holds right now — resolved through curation, so
# a topic another split already moved away is not offered for splitting twice
# and a merged-away thread's topics are found under its survivor.
_THREAD_TOPICS = (
    "SELECT tt.topic_id, t.meeting_id, t.name"
    f" FROM ({EFFECTIVE_MEMBERSHIP}) tt"
    " JOIN topic t ON t.id = tt.topic_id"
    " WHERE tt.thread_id = %s"
)

_MINT_CURATED_THREAD = (
    "INSERT INTO thread (identity_key, name, link_rule, derivation)"
    " VALUES (%s, %s, %s, %s) RETURNING id, color_ordinal"
)

# `ON CONFLICT DO UPDATE` because a second split of the same subject *moves*
# it: the later human decision wins over the earlier one, which is the only
# reading under which curation is a correction rather than an append-only log
# a user cannot fix. The `WHERE` keeps a no-op re-pin from touching
# `updated_at`, the same discipline the derivation's UPSERTs keep.
_UPSERT_PIN = (
    "INSERT INTO thread_topic_pin (meeting_id, normalized_name, thread_id, topic_id)"
    " VALUES (%s, %s, %s, %s)"
    " ON CONFLICT (meeting_id, normalized_name) DO UPDATE"
    " SET thread_id = EXCLUDED.thread_id, topic_id = EXCLUDED.topic_id"
    " WHERE thread_topic_pin.thread_id IS DISTINCT FROM EXCLUDED.thread_id"
    "    OR thread_topic_pin.topic_id IS DISTINCT FROM EXCLUDED.topic_id"
)

class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CuratedThread(_Camel):
    """One thread as curation leaves it.

    `name` is what to display and `derivedName` is what the machine called it,
    with `nameIsCurated` saying which of the two `name` came from. All three
    are served rather than just the winner, because a reader has to be able to
    tell a human name from a derived one — and because a curator deciding
    whether to keep their own rename needs to see what the machine now says.
    """

    thread_id: UUID
    name: str
    derived_name: str
    name_is_curated: bool
    color_ordinal: int
    # Set exactly when this thread has been merged away. A thread with this
    # field set holds no memberships of its own any more: they resolve to the
    # survivor, and `GET /threads` lists the survivor instead.
    merged_into_thread_id: UUID | None = None


class RenameThreadRequest(_Camel):
    """`null` clears the curated name and restores the machine's own.

    Clearing restores whatever the derivation *currently* calls the thread,
    not a copy taken when the rename happened: `thread.name` is live, and a
    stale copy would be a third name nobody asked for.
    """

    name: ThreadName | None

    @field_validator("name")
    @classmethod
    def name_cannot_contain_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("a thread name cannot contain a NUL character")
        return value


class MergeThreadsRequest(_Camel):
    into_thread_id: UUID


class SplitThreadRequest(_Camel):
    """Move these topics onto a new thread of their own.

    `topicIds` rather than a predicate: a split is a human pointing at the
    specific subjects that were misgrouped, and a rule would re-run itself
    against topics the user never saw.
    """

    topic_ids: list[UUID]
    name: ThreadName

    @field_validator("name")
    @classmethod
    def name_cannot_contain_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("a thread name cannot contain a NUL character")
        return value


_PROBLEM_RESPONSES = {
    422: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`invalid-request` — the route parameter is not a UUID,"
        " a name is blank, a merge names the same thread twice, or a split"
        " names no topics, topics the thread does not hold, every topic it"
        " holds, or a topic whose name has no durable normalized form.",
    },
    404: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`not-found` — no such thread.",
    },
    409: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`already-merged` — the thread was merged away, or has"
        " itself absorbed another and cannot be merged again;"
        " or `merge-target-not-canonical` — the survivor is itself merged"
        " away. The alias map is flat, never a chain.",
    },
}


def _row_to_model(row) -> CuratedThread:
    return CuratedThread(
        thread_id=row[0],
        name=row[1],
        derived_name=row[2],
        name_is_curated=row[3],
        color_ordinal=row[4],
        merged_into_thread_id=row[5],
    )


def _fetch_thread(conn, thread_id: UUID):
    row = conn.execute(_THREAD_FOR_UPDATE, (thread_id,)).fetchone()
    if row is None:
        raise Problem(404, "not-found", f"no thread with id {thread_id}")
    return row


def _refetch(conn, thread_id: UUID) -> CuratedThread:
    row = conn.execute(_THREAD_WITH_CURATION, (thread_id,)).fetchone()
    if row is None:  # pragma: no cover - the row was locked moments ago
        raise Problem(404, "not-found", f"no thread with id {thread_id}")
    return _row_to_model(row)


def _is_merged_away(conn, thread_id: UUID) -> bool:
    return conn.execute(_IS_MERGED_AWAY, (thread_id,)).fetchone() is not None


def _refuse_if_merged_away(conn, thread_id: UUID, *, verb: str) -> None:
    if _is_merged_away(conn, thread_id):
        raise Problem(
            409,
            "already-merged",
            f"thread {thread_id} was merged away and can no longer be {verb}"
            " directly — curate the thread it was merged into",
        )


@router.patch(
    "/threads/{thread_id}",
    operation_id="renameThread",
    response_model=CuratedThread,
    responses=_PROBLEM_RESPONSES,
)
def rename_thread(
    thread_id: UUID, body: RenameThreadRequest, request: Request
) -> CuratedThread:
    """Give a thread a human name, or clear one (AD-5).

    Writes `thread_curation` and never `thread.name`. That is not a style
    choice: the derivation rewrites `thread.name` from the cluster's seed
    topic on every pass, so a rename written there would survive only until
    the next rerun — and would then vanish with no record that it had ever
    been made.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        _fetch_thread(conn, thread_id)
        _refuse_if_merged_away(conn, thread_id, verb="renamed")
        if body.name is None:
            conn.execute(_CLEAR_CURATED_NAME, (thread_id,))
        else:
            conn.execute(_UPSERT_CURATED_NAME, (thread_id, body.name))
        result = _refetch(conn, thread_id)

    logs.log_event(
        "threads.renamed",
        thread_id=str(thread_id),
        cleared=body.name is None,
    )
    return result


@router.post(
    "/threads/{thread_id}/merge",
    operation_id="mergeThreads",
    response_model=CuratedThread,
    responses=_PROBLEM_RESPONSES,
)
def merge_threads(
    thread_id: UUID, body: MergeThreadsRequest, request: Request
) -> CuratedThread:
    """Absorb one thread into another (AD-5). Returns the survivor.

    Writes exactly one row — `thread_alias(thread_id, merged_into_id)` — and
    moves nothing. The memberships follow at read time and at the next
    derivation, both of which resolve this table; the absorbed `thread` row
    stays as durable identity, keeping its own `color_ordinal` because nothing
    UPDATEs it (0017).
    """
    if thread_id == body.into_thread_id:
        raise Problem(422, "invalid-request", "a thread cannot be merged into itself")
    pool = request.app.state.pool
    with pool.connection() as conn:
        # Locked in a fixed (sorted) order regardless of which side is which,
        # so two merges naming the same pair in opposite roles cannot deadlock
        # against each other — `api/participants.py`'s rule, same reason.
        first_id, second_id = sorted((thread_id, body.into_thread_id))
        _fetch_thread(conn, first_id)
        _fetch_thread(conn, second_id)
        if _is_merged_away(conn, thread_id):
            raise Problem(
                409, "already-merged", f"thread {thread_id} is already merged away"
            )
        if conn.execute(_HAS_ABSORBED, (thread_id,)).fetchone() is not None:
            raise Problem(
                409,
                "already-merged",
                f"thread {thread_id} has already absorbed another thread and"
                " cannot itself be merged away without creating an alias"
                " chain — merge that thread onto"
                f" {body.into_thread_id} instead",
            )
        if _is_merged_away(conn, body.into_thread_id):
            raise Problem(
                409,
                "merge-target-not-canonical",
                f"thread {body.into_thread_id} is itself merged away and"
                " cannot be a merge target",
            )
        try:
            conn.execute(_INSERT_ALIAS, (thread_id, body.into_thread_id))
        except psycopg.errors.UniqueViolation:
            # Lost a race: another request merged this same thread between the
            # check above and this INSERT. `thread_id` is the primary key, so
            # the loser refuses cleanly rather than raising an unhandled 500.
            conn.rollback()
            raise Problem(
                409,
                "already-merged",
                f"thread {thread_id} was merged by a concurrent request",
            ) from None
        except psycopg.errors.RaiseException as exc:
            # 0021's flatness trigger, which sees a chain this transaction's
            # own checks could not (another request committing between them).
            conn.rollback()
            raise Problem(409, "already-merged", str(exc).strip()) from None
        result = _refetch(conn, body.into_thread_id)

    logs.log_event(
        "threads.merged",
        absorbed_thread_id=str(thread_id),
        into_thread_id=str(body.into_thread_id),
    )
    return result


@router.post(
    "/threads/{thread_id}/split",
    operation_id="splitThread",
    response_model=CuratedThread,
    status_code=201,
    responses=_PROBLEM_RESPONSES,
)
def split_thread(
    thread_id: UUID, body: SplitThreadRequest, request: Request
) -> CuratedThread:
    """Move some of a thread's topics onto a new thread of their own (AD-5).

    Two writes: the new `thread` row, and one `thread_topic_pin` per distinct
    subject moved. The pins are what make the split durable — they are keyed
    on `(meeting_id, normalized_name)`, the same durable content key
    `thread.identity_key` uses, so a re-extraction that replaces the meeting's
    topic rows wholesale does not take the split with it.

    The new row takes its `color_ordinal` from 0017's sequence by the ordinary
    insert path, so the split product gets a colour of its own and no existing
    thread is recoloured.
    """
    if not body.topic_ids:
        raise Problem(
            422, "invalid-request", "a split must name at least one topic to move"
        )
    if len(body.topic_ids) > SPLIT_TOPIC_LIMIT:
        raise Problem(
            422,
            "invalid-request",
            f"a split may move at most {SPLIT_TOPIC_LIMIT} topics at once;"
            f" this request named {len(body.topic_ids)}",
        )
    requested = set(body.topic_ids)

    pool = request.app.state.pool
    with pool.connection() as conn:
        _fetch_thread(conn, thread_id)
        _refuse_if_merged_away(conn, thread_id, verb="split")

        held = {
            row[0]: (row[1], row[2])
            for row in conn.execute(_THREAD_TOPICS, (thread_id,)).fetchall()
        }
        missing = sorted(str(t) for t in requested - held.keys())
        if missing:
            raise Problem(
                422,
                "invalid-request",
                f"thread {thread_id} does not hold {len(missing)} of the"
                f" topics named: {', '.join(missing)} — a split can only move"
                " topics the thread currently holds, and a topic another"
                " split already moved is held by that thread now",
            )
        if requested == held.keys():
            raise Problem(
                422,
                "invalid-request",
                "a split that moves every topic leaves the original thread"
                " empty and is a rename, not a split — PATCH the thread's"
                " name instead",
            )

        # The durable key must identify exactly one topic in the thread at the
        # instant of the split.  The live SQL reader can apply a pin only to
        # its one `topic_id` hint, while the next derivation applies the same
        # pin by `(meeting_id, normalized_name)`.  Accepting an ambiguous key
        # would therefore show one topic moved now and silently move every
        # same-key topic on rerun.  Refuse that state instead of letting the
        # human's correction widen after it appeared to land.
        held_by_key: dict[tuple[UUID, str], list[UUID]] = {}
        for held_topic_id, (meeting_id, name) in held.items():
            try:
                held_key = pin_content_key(meeting_id=meeting_id, topic_name=name)
            except ThreadCurationError:
                # A punctuation-only name matters only if the request selects
                # it; the requested loop below returns that named refusal.
                continue
            held_by_key.setdefault(held_key, []).append(held_topic_id)

        pins: dict[tuple[UUID, str], UUID] = {}
        for topic_id in sorted(requested):
            meeting_id, name = held[topic_id]
            try:
                key = pin_content_key(meeting_id=meeting_id, topic_name=name)
            except ThreadCurationError as exc:
                raise Problem(422, "invalid-request", str(exc)) from None
            collisions = held_by_key[key]
            if len(collisions) > 1:
                raise Problem(
                    422,
                    "invalid-request",
                    f"topic {topic_id} has a durable subject key shared by"
                    f" {len(collisions)} topics in meeting {meeting_id}:"
                    f" {key[1]!r} — the split cannot identify exactly which"
                    " topic should keep the correction across a re-extraction",
                )
            pins[key] = topic_id

        row = conn.execute(
            _MINT_CURATED_THREAD,
            (
                curated_split_identity_key(),
                body.name,
                CURATED_LINK_RULE,
                Jsonb(
                    {
                        "curated": True,
                        "story": "10.2a",
                        "split_from_thread_id": str(thread_id),
                    }
                ),
            ),
        ).fetchone()
        new_thread_id = row[0]

        for (meeting_id, normalized_name), topic_id in pins.items():
            try:
                conn.execute(
                    _UPSERT_PIN, (meeting_id, normalized_name, new_thread_id, topic_id)
                )
            except psycopg.errors.UniqueViolation:
                # `thread_topic_pin.topic_id` is UNIQUE. A topic has one
                # meeting and one name, so its content key is a function of
                # the topic and a second pin claiming the same topic under a
                # *different* key should be unreachable. If it happens the
                # record disagrees with that reasoning, and the honest answer
                # is to say so and write nothing rather than to guess which
                # pin the user meant.
                conn.rollback()
                raise Problem(
                    409,
                    "already-merged",
                    f"topic {topic_id} is already pinned under a different"
                    " content key; the split was not recorded",
                ) from None

        result = _refetch(conn, new_thread_id)

    logs.log_event(
        "threads.split",
        from_thread_id=str(thread_id),
        thread_id=str(new_thread_id),
        topics=len(requested),
        pins=len(pins),
    )
    return result


__all__ = [
    "CuratedThread",
    "MergeThreadsRequest",
    "ProblemDetails",
    "RenameThreadRequest",
    "SplitThreadRequest",
    "router",
]
