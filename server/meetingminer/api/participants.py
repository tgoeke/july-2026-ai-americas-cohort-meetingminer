"""GET /participants, PATCH /participants/{id}, POST /participants/{id}/merge
(story 2.4).

AD-5's human half of participant management: the worker inserts `participant`
rows during intake — deduplicated by mail address or normalized display name
— but never guesses a display name and never merges two identities. This
router is the write path a curator uses to fix both, and it writes exactly
what AD-5 assigns the API: human-curated columns (`display_name`) and merge
records (`participant_alias`). It never touches `meeting_participant` or
`transcript_segment.participant_id` — those are worker-owned evidence, and a
merge's effect on already-ingested meetings appears only at the next
re-ingest or projection, because `pipeline/stages/align.py:_resolve_participants`
reads `participant_alias` first and unconditionally, before every insert.

No Neo4j write happens here (AD-5, `test_the_api_package_never_reaches_a_store`):
a rename or merge reaches `Participant` nodes only at the next projection run
(`projections/graph.py:_write_participants`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

import psycopg.errors
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.problems import Problem

router = APIRouter()

# A display name is a sentence fragment, not free text — 200 characters is far
# past any real human name and far short of a payload that would be about
# something else entirely. `strip_whitespace` before `min_length` is what
# makes a whitespace-only name a 422 rather than a rename to blank.
DISPLAY_NAME_MAX_LENGTH = 200
DisplayName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH),
]

# Every `participant` row plus its merge state, in one statement: the LEFT
# JOIN reads `mergedIntoParticipantId` from `participant_alias` keyed by this
# row's own `identity_key` — set when this row itself was merged away, NULL
# for a canonical row. Ordered by `display_name` so the list renders in a
# stable, human-legible order rather than insertion (UUIDv7 mint) order.
_LIST_PARTICIPANTS = (
    "SELECT p.id, p.identity_key, p.display_name, p.normalized_name,"
    " pa.participant_id, p.created_at, p.updated_at"
    " FROM participant p"
    " LEFT JOIN participant_alias pa ON pa.alias_key = p.identity_key"
    " ORDER BY p.display_name, p.id"
)

# Same row shape as `_LIST_PARTICIPANTS` (id, identityKey, displayName,
# normalizedName, mergedIntoParticipantId, createdAt, updatedAt) so a fetch
# feeds `_row_to_model` directly — `rename_participant` no longer hand-builds
# its response field-by-field.
_PARTICIPANT_BY_ID = (
    "SELECT p.id, p.identity_key, p.display_name, p.normalized_name,"
    " pa.participant_id, p.created_at, p.updated_at"
    " FROM participant p"
    " LEFT JOIN participant_alias pa ON pa.alias_key = p.identity_key"
    " WHERE p.id = %s"
)

# `FOR UPDATE OF p`, used only by the write paths (rename, merge) via
# `_fetch_participant`: it row-locks every participant this request touches,
# so two requests that name the *same* participant id (as either side of a
# merge, or as a rename target) serialize against each other instead of
# racing. `OF p` because plain `FOR UPDATE` cannot apply to the nullable side
# of the LEFT JOIN above; only the `participant` row itself needs locking —
# `participant_alias` has no existing row to lock for a not-yet-aliased id,
# which is exactly why the write routes below also read it under READ
# COMMITTED rather than REPEATABLE READ (see there). Deliberately plain
# `SELECT` for `list_participants` — a read has no write to serialize against
# and no reason to block one.
_PARTICIPANT_BY_ID_FOR_UPDATE = _PARTICIPANT_BY_ID + " FOR UPDATE OF p"

# The canonical check rename's 409 and merge's two 409s share: a participant
# is merged-away exactly when its own `identity_key` appears as some row's
# `alias_key`. Read under READ COMMITTED (see the write routes below) so this
# reflects whatever the row lock above just waited out, not a snapshot frozen
# before it.
_IS_ALIASED = "SELECT 1 FROM participant_alias WHERE alias_key = %s"

# An absorbed participant may not itself be absorbed again. Otherwise A->B
# followed by B->C produces a chain, while align intentionally performs one
# alias lookup. Additional aliases into one survivor remain a flat map.
_HAS_ABSORBED_ALIASES = "SELECT 1 FROM participant_alias WHERE participant_id = %s"

_RENAME_PARTICIPANT = (
    "UPDATE participant SET display_name = %s WHERE id = %s"
)

_INSERT_ALIAS = (
    "INSERT INTO participant_alias (alias_key, participant_id) VALUES (%s, %s)"
)


class ParticipantRow(BaseModel):
    """One `participant` row, canonical or merged-away.

    `mergedIntoParticipantId` is set exactly when this row's `identityKey` is
    itself an alias key elsewhere — curators see merge history, not just the
    current canonical set (`GET /participants`'s contract).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    identity_key: str
    display_name: str
    normalized_name: str
    merged_into_participant_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class RenameParticipantRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    display_name: DisplayName

    @field_validator("display_name")
    @classmethod
    def display_name_cannot_contain_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("display name cannot contain a NUL character")
        return value


class MergeParticipantsRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    into_participant_id: UUID


_PROBLEM_RESPONSES = {
    422: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`invalid-request` — the route parameter is not a UUID,"
        " the display name is blank, or a merge names the same id twice.",
    },
    404: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`not-found` — no such participant row.",
    },
    409: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`already-merged` — the target of a rename, the"
        " absorbed side of a merge, or an existing survivor with absorbed"
        " aliases cannot be merged again;"
        " or `merge-target-not-canonical` — the survivor side of a merge is"
        " itself already an alias key. No chained aliases (Design Notes).",
    },
}


def _row_to_model(row) -> ParticipantRow:
    return ParticipantRow(
        id=row[0],
        identity_key=row[1],
        display_name=row[2],
        normalized_name=row[3],
        merged_into_participant_id=row[4],
        created_at=row[5],
        updated_at=row[6],
    )


def _fetch_participant(conn, participant_id: UUID):
    """The write paths' row-locking fetch (`FOR UPDATE OF p`) — see
    `_PARTICIPANT_BY_ID_FOR_UPDATE`'s comment for what the lock buys."""
    row = conn.execute(_PARTICIPANT_BY_ID_FOR_UPDATE, (participant_id,)).fetchone()
    if row is None:
        raise Problem(404, "not-found", f"no participant with id {participant_id}")
    return row


def _is_aliased(conn, identity_key: str) -> bool:
    return conn.execute(_IS_ALIASED, (identity_key,)).fetchone() is not None


def _has_absorbed_aliases(conn, participant_id: UUID) -> bool:
    return conn.execute(_HAS_ABSORBED_ALIASES, (participant_id,)).fetchone() is not None


@router.get(
    "/participants",
    operation_id="listParticipants",
    response_model=list[ParticipantRow],
)
def list_participants(request: Request) -> list[ParticipantRow]:
    pool = request.app.state.pool
    with pool.connection() as conn:
        rows = conn.execute(_LIST_PARTICIPANTS).fetchall()
    result = [_row_to_model(row) for row in rows]
    logs.log_event("participants.listed", participants=len(result))
    return result


@router.patch(
    "/participants/{participant_id}",
    operation_id="renameParticipant",
    response_model=ParticipantRow,
    responses=_PROBLEM_RESPONSES,
)
def rename_participant(
    participant_id: UUID, body: RenameParticipantRequest, request: Request
) -> ParticipantRow:
    """Edit a canonical participant's display name (AD-5).

    `identity_key`/`normalized_name` never change here — those are the
    worker's roster-matching keys, and a rename must not disturb intake
    matching for future meetings.

    Deliberately READ COMMITTED, not the REPEATABLE READ the read routes use
    (`moments.py`): `_fetch_participant`'s `FOR UPDATE OF p` blocks a
    concurrent rename/merge of this same id until this transaction commits,
    but the `_is_aliased` check that follows reads a *different* table
    (`participant_alias`, never locked, since a not-yet-existing row cannot
    be locked). Under REPEATABLE READ that check would keep using the
    snapshot taken when this transaction opened even after the lock wait —
    silently stale. READ COMMITTED gives every statement a fresh snapshot, so
    the check sees whatever the lock wait just resolved.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = _fetch_participant(conn, participant_id)
        if _is_aliased(conn, row[1]):
            raise Problem(
                409,
                "already-merged",
                f"participant {participant_id} was merged away and can no"
                " longer be renamed directly",
            )
        conn.execute(_RENAME_PARTICIPANT, (body.display_name, participant_id))
        refreshed = _fetch_participant(conn, participant_id)

    logs.log_event("participants.renamed", participant_id=participant_id)
    return _row_to_model(refreshed)


@router.post(
    "/participants/{participant_id}/merge",
    operation_id="mergeParticipants",
    response_model=list[ParticipantRow],
    responses=_PROBLEM_RESPONSES,
)
def merge_participants(
    participant_id: UUID, body: MergeParticipantsRequest, request: Request
) -> list[ParticipantRow]:
    """Absorb one canonical participant into another (AD-5).

    Writes exactly one row: `participant_alias(alias_key, participant_id)`
    mapping the absorbed identity key to the survivor's id — the mechanism
    `align._resolve_participants` already reads first and unconditionally, so
    the merge survives every future re-ingest and stage rerun. No chained
    aliases: both sides must be canonical (Design Notes), so a later A->B->C
    collapse is done by merging A directly onto C once B->C exists.
    """
    if participant_id == body.into_participant_id:
        raise Problem(
            422,
            "invalid-request",
            "a participant cannot be merged into itself",
        )
    pool = request.app.state.pool
    # Same READ COMMITTED reasoning as `rename_participant`'s docstring.
    # Rows are locked in a fixed (sorted) order regardless of which side is
    # absorbed/survivor here, so two merges naming the same pair of ids in
    # opposite roles cannot deadlock against each other's `FOR UPDATE`.
    with pool.connection() as conn:
        first_id, second_id = sorted((participant_id, body.into_participant_id))
        first = _fetch_participant(conn, first_id)
        second = _fetch_participant(conn, second_id)
        absorbed, survivor = (
            (first, second) if first_id == participant_id else (second, first)
        )
        if _is_aliased(conn, absorbed[1]):
            raise Problem(
                409,
                "already-merged",
                f"participant {participant_id} is already merged away",
            )
        if _has_absorbed_aliases(conn, absorbed[0]):
            raise Problem(
                409,
                "already-merged",
                f"participant {participant_id} has already absorbed another"
                " participant and cannot be merged again without creating an"
                " alias chain",
            )
        if _is_aliased(conn, survivor[1]):
            raise Problem(
                409,
                "merge-target-not-canonical",
                f"participant {body.into_participant_id} is itself merged"
                " away and cannot be a merge target",
            )
        try:
            conn.execute(_INSERT_ALIAS, (absorbed[1], survivor[0]))
        except psycopg.errors.UniqueViolation:
            # Lost a race: another request merged this exact absorbed id
            # (using the same or a different survivor) between our check and
            # this INSERT — `alias_key` is the primary key, so the loser
            # refuses cleanly instead of raising an unhandled 500.
            conn.rollback()
            raise Problem(
                409,
                "already-merged",
                f"participant {participant_id} was merged by a concurrent"
                " request",
            ) from None
        rows = conn.execute(_LIST_PARTICIPANTS).fetchall()

    result = [_row_to_model(row) for row in rows]
    logs.log_event(
        "participants.merged",
        absorbed_id=participant_id,
        into_participant_id=body.into_participant_id,
    )
    return result
