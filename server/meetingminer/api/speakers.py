"""GET /meetings/{meetingId}/speakers (story 7.2).

Who spoke in one meeting, and how much. Story 7.1 stamps a tag onto every
transcript segment — a diarizer's ``SPEAKER_NN`` placeholder, or the real name
a Teams-shaped source wrote — and ``align`` resolves that tag to a
``participant`` row when, and only when, the meeting's roster or an
API-recorded merge identified it. This route is the read that turns those
per-segment tags into one row per voice: talk time, segment count, and three
offsets a listener can jump to.

**One shape, two sources.** A diarized meeting and a meeting whose transcript
arrived carrying real names produce the same fields in the same order; only
``participantId``/``displayName`` differ, and they are null exactly where the
store holds no identity. Nothing here re-derives an attribution: the route
never re-runs ``pipeline/speakers.resolve_label`` and never follows
``participant_alias`` forward at read time. Both would let this route name a
person the segment rows do not name (AD-13/AD-5), and following the alias
table would additionally make ``speakers`` and ``drilldown`` disagree about
the same segment's ``participantId`` — a merge reaches the transcript at the
next ``align`` run, the documented AD-5 lag (``api/participants.py``).
``displayName`` is read live off ``participant.display_name``, so a curator's
rename — which keeps the id — shows on the next request.

Read-only over evidence (AD-5/AD-11): one SELECT, no writes, no store client.
The 404/409/422 contract and the viewability gate are the sibling meeting
reads' own — ``moments._require_viewable`` is imported rather than restated,
so the two reads of one meeting cannot drift into disagreeing about whether
that meeting is viewable.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.moments import _require_viewable
from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.domain.jobs import SPEAKER_ASSIGNMENT_STAGES
from meetingminer.domain.speaker_assignments import (
    curated_identity_key,
    speaker_alias_key,
)
from meetingminer.projections.evidence import meeting_evidence_complete

router = APIRouter()

# Existence only. The 404/409 split needs to know whether the meeting row is
# there before the gate runs, and this response carries no header fields
# beyond the id the caller already supplied — so this reads the one column
# that answers the question rather than the six `moments._MEETING_HEADER`
# needs for its header.
_MEETING_EXISTS = "SELECT id FROM meeting WHERE id = %s"

# At most this many sample offsets per speaker, and never padded to it: a
# speaker with two segments gets two. Story 7.4 plays clip *n* of what is
# here, and a fabricated offset would play silence.
MAX_SAMPLE_OFFSETS = 3

# One meeting's speakers, one statement.
#
# The grouping key is `(speaker_label, participant_id, speaker_resolution)`,
# not the label alone. `align` resolves a label deterministically once per
# meeting, so in practice this is one row per label; keying on all three means
# a store that somehow disagrees with itself — the same label written both
# `resolved` and `unresolved` — produces two honest rows instead of one row
# whose attribution this query picked. `p.display_name` joins the GROUP BY
# because Postgres recognizes a functional dependency only through the grouped
# table's own primary key; the LEFT JOIN is on `p.id`, so the column is
# already one-per-group and naming it adds no group.
#
# `SUM(...)::bigint` because `SUM` over `bigint` returns `numeric`, which
# would reach Pydantic as a `Decimal` for an `int` field. The cast keeps the
# wire integer an integer at the source.
#
# The samples are the `start_ms` of the longest segments — the sliced
# `array_agg` is what makes "three longest" one aggregate rather than a second
# query per speaker. Its ORDER BY is fully specified: duration DESC, then the
# earlier start, then the ordinal, so a tie between equal-length segments
# resolves to the earlier moment rather than to whatever the planner returned.
#
# Row order: talk time descending (the epic's ordering), then the verbatim
# label, then `participant_id` — ASC, whose Postgres default is NULLS LAST, so
# an unattributed row sorts after an attributed one sharing its label — and
# finally the resolution, which is the last component of the grouping key and
# so the tiebreak that makes the order total rather than merely usually-total.
#
# The slice bound is this module's own integer constant, interpolated at
# import time rather than bound as a parameter: an array subscript is not a
# value position Postgres infers a parameter type for the way a comparison is,
# and the only interpolated text is an `int` defined a few lines above.
# `meeting_id` stays a bound parameter, as every value reaching SQL here does.
_MEETING_SPEAKERS = (
    "SELECT ts.speaker_label, ts.speaker_resolution, ts.participant_id,"
    " p.display_name,"
    " SUM(ts.end_ms - ts.start_ms)::bigint AS talk_time_ms,"
    " COUNT(*) AS segment_count,"
    " (array_agg(ts.start_ms ORDER BY (ts.end_ms - ts.start_ms) DESC,"
    f" ts.start_ms, ts.ordinal))[1:{MAX_SAMPLE_OFFSETS}] AS sample_offsets_ms"
    " FROM transcript_segment ts"
    " LEFT JOIN participant p ON p.id = ts.participant_id"
    " WHERE ts.meeting_id = %s"
    " GROUP BY ts.speaker_label, ts.participant_id, ts.speaker_resolution,"
    " p.display_name"
    " ORDER BY talk_time_ms DESC, ts.speaker_label, ts.participant_id,"
    " ts.speaker_resolution"
)


class SpeakerTag(BaseModel):
    """One voice in one meeting, as the transcript labelled it.

    ``speakerLabel`` is ``transcript_segment.speaker_label`` verbatim — the
    diarizer's ``SPEAKER_00``, or the source's ``Goeke, Timothy`` — never a
    normalized or prettified form, and never replaced by the participant's
    display name: the label is what the reader has to recognize in the
    transcript beside it.

    ``participantId``/``displayName`` are populated exactly when
    ``transcript_segment.participant_id`` is, which migration 0005 constrains
    to ``speakerResolution == 'resolved'``. A ``placeholder``, ``unresolved``
    or ``ambiguous`` tag is listed with both null: an absent attribution, not
    a guessed one (AD-13).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    speaker_label: str
    # One of `pipeline/speakers.RESOLUTIONS` — resolved, unresolved,
    # ambiguous, placeholder — as the column's CHECK constrains it.
    speaker_resolution: str
    participant_id: UUID | None
    display_name: str | None
    # Summed `end_ms - start_ms` over this tag's segments. Wall-clock talk
    # time as the transcript timed it, not a speaking-rate estimate.
    talk_time_ms: int
    segment_count: int
    # The `startMs` of this tag's longest segments, longest first, at most
    # `MAX_SAMPLE_OFFSETS` and never padded.
    sample_offsets_ms: list[int]


class MeetingSpeakersResponse(BaseModel):
    """Every speaker tag of one meeting, talk time descending."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    speakers: list[SpeakerTag]


_PROBLEM_RESPONSES = {
    422: {
        # `model` would make FastAPI add an application/json alternative. The
        # app-wide validation handler only emits RFC 9457 problem+json, so
        # name the already-registered component directly (the `moments.py`
        # precedent) and document the exact runtime contract.
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`invalid-request` — the route parameter is not a UUID.",
    },
    404: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`not-found` — no such meeting; it was never ingested.",
    },
    409: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`meeting-not-viewable` — the meeting exists but an"
        " evidence stage has not settled; first ingest or augmentation is in"
        " flight. Transient: retry once ingestion settles. Carries the same"
        " extensions as the sibling meeting reads: `meetingId`, `augmenting`"
        " (bool) and `jobStatus` (str).",
    },
}


@router.get(
    "/meetings/{meeting_id}/speakers",
    operation_id="listMeetingSpeakers",
    response_model=MeetingSpeakersResponse,
    responses=_PROBLEM_RESPONSES,
)
def list_meeting_speakers(
    meeting_id: UUID, request: Request
) -> MeetingSpeakersResponse:
    """Aggregate one meeting's transcript segments into one row per speaker."""
    pool = request.app.state.pool
    # Three reads on one connection, split the way `moments.py` splits its
    # own: existence first (absence is the 404), the gate second (existence
    # without settled evidence is the 409), the aggregate last. REPEATABLE
    # READ so all three come from one snapshot — under the default Read
    # Committed an augmentation committing between the gate and the aggregate
    # would pass the gate on the pre-augmentation stages and then serve
    # mid-rebuild rows as viewable.
    with pool.connection() as conn:
        # First statement of the (implicit) transaction, so it governs every
        # read below; it expires with the transaction, leaving nothing set on
        # the pooled connection.
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if conn.execute(_MEETING_EXISTS, (meeting_id,)).fetchone() is None:
            raise Problem(404, "not-found", f"no meeting with id {meeting_id}")
        _require_viewable(conn, meeting_id)
        rows = conn.execute(_MEETING_SPEAKERS, (meeting_id,)).fetchall()

    speakers = [
        SpeakerTag(
            speaker_label=row[0],
            speaker_resolution=row[1],
            participant_id=row[2],
            display_name=row[3],
            talk_time_ms=row[4],
            segment_count=row[5],
            sample_offsets_ms=list(row[6]),
        )
        for row in rows
    ]
    logs.log_event(
        "speakers.listed", meeting_id=meeting_id, speakers=len(speakers)
    )
    return MeetingSpeakersResponse(meeting_id=meeting_id, speakers=speakers)


# --- story 7.3: assigning a speaker ----------------------------------------

# The job behind one meeting, and what it is doing right now. Both columns are
# needed before any write: the id to re-arm, the status to refuse re-arming a
# job the single worker (AD-9) is currently inside. The row lock closes the
# check-to-rearm window: a worker claimant that won first commits ``running``
# before this statement returns, while a claimant that arrives after this
# statement waits until the assignment and its queued stages commit together.
_JOB_FOR_MEETING = (
    "SELECT j.id, j.status FROM job j JOIN meeting m ON m.job_id = j.id"
    " WHERE m.id = %s FOR UPDATE OF j"
)

# Whether this meeting's transcript actually carries the tag being assigned.
# Without this check a typo would write an alias no segment will ever match:
# the request would look accepted, the job would re-run, and nothing would
# change — a silent no-op is exactly what this story must not ship.
_SPEAKER_TAG_EXISTS = (
    "SELECT 1 FROM transcript_segment WHERE meeting_id = %s AND speaker_label = %s"
    " LIMIT 1"
)

_PARTICIPANT_BY_ID = "SELECT id, display_name FROM participant WHERE id = %s"

# Idempotent by design: re-assigning a tag is a correction, not a second
# record, and `alias_key` is the primary key. `DO UPDATE` rather than the
# check-then-insert `participants.py` performs, because there is exactly one
# row to write here and no second table consulted between the two statements.
_UPSERT_SPEAKER_ALIAS = (
    "INSERT INTO participant_alias (alias_key, participant_id) VALUES (%s, %s)"
    " ON CONFLICT (alias_key) DO UPDATE SET participant_id = EXCLUDED.participant_id"
)

_DELETE_SPEAKER_ALIAS = "DELETE FROM participant_alias WHERE alias_key = %s"

# The participant a curator's typed name mints, in the `curated:` space.
#
# `identity_key` is deliberately *not* `pipeline/speakers.identity_key_for`'s
# `name:<normalized>`: the api may not import `pipeline`, and a second
# spelling of `normalize_display_name` here would be a second source of truth
# for identity keys — the silent-merge failure that module warns about at
# length. An api-owned space cannot collide with a roster match key, so the
# worst case is a *split* — the same human typed into two meetings gets two
# rows — which `pipeline/speakers.py` calls the recoverable direction and
# `POST /participants/{id}/merge` recovers.
#
# `curated:` and not the alias key itself: a merge is recorded as `alias_key =
# <absorbed>.identity_key`, so a row whose identity key *were* its own
# assignment's key would read as already merged away and could never be
# merged — closing the very recovery path the split relies on.
#
# `normalized_name` is the same key rather than a name-shaped value: it is the
# roster-matching column, and a curator's typed string must not start matching
# transcript labels in later meetings on a normalization this layer cannot
# perform correctly. A key never matches, which is the honest failure.
#
# `ON CONFLICT DO UPDATE` makes a re-typed name rename the one row rather than
# stranding it and minting another.
_MINT_CURATED_PARTICIPANT = (
    "INSERT INTO participant (identity_key, display_name, normalized_name)"
    " VALUES (%s, %s, %s)"
    " ON CONFLICT (identity_key) DO UPDATE SET display_name = EXCLUDED.display_name"
    " RETURNING id"
)

_REARM_JOB = (
    "UPDATE job SET status = 'queued', error = NULL, updated_at = now()"
    " WHERE id = %s"
)

# Only the named stages, so the runner's settled-stage guard resumes rather
# than restarting: the recording is untouched, so no video stage re-runs.
_REARM_STAGES = (
    "UPDATE job_stage SET status = 'queued', error = NULL"
    " WHERE job_id = %s AND name = ANY(%s)"
)


class AssignSpeakerRequest(BaseModel):
    """Exactly one of three choices, as the story's first clause names them.

    Three optional fields rather than a discriminated union, because that is
    the shape the UI's three gestures produce (pick a suggestion, type a name,
    press *Unresolved*); the validator makes the "exactly one" rule explicit
    instead of leaving a two-field request to be resolved by precedence.

    ``unresolved: false`` selects nothing, on purpose — it is the field's
    default, so counting it as a choice would make an empty body mean
    "unresolve", which is a destructive reading of silence.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    participant_id: UUID | None = None
    display_name: str | None = None
    unresolved: bool = False

    @model_validator(mode="after")
    def exactly_one_choice(self) -> AssignSpeakerRequest:
        if self.display_name is not None:
            if "\x00" in self.display_name:
                raise ValueError("display name cannot contain a NUL character")
            if not self.display_name.strip():
                raise ValueError("display name cannot be blank")
        chosen = sum(
            (
                self.participant_id is not None,
                self.display_name is not None,
                self.unresolved,
            )
        )
        if chosen != 1:
            raise ValueError(
                "name exactly one of participantId, displayName or"
                " unresolved: true"
            )
        return self


class SpeakerAssignmentResponse(BaseModel):
    """What was recorded, and what was re-armed to act on it.

    Deliberately reports the *persisted* facts rather than predicting the
    attribution the rerun will write: ``align`` decides that, and a response
    claiming it in advance would be guessing, on the one story that exists to
    stop guessing (AD-13). ``participantId``/``displayName`` are the alias
    target — both null for ``unresolved``, which stores no row at all.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    # The tag verbatim, echoed back so a caller can see which label the path
    # actually resolved to after URL decoding.
    speaker_label: str
    participant_id: UUID | None
    display_name: str | None
    job_id: UUID
    rearmed_stages: list[str]
    # This PUT is the one deliberate exception to the meeting evidence gate:
    # a failed assignment rerun must be correctable by the action that caused
    # it. Surface that exceptional acceptance instead of making it look like
    # an ordinary assignment against settled evidence.
    accepted_while_unviewable: bool = Field(
        description="Whether this PUT was accepted while meeting evidence was unviewable."
    )
    # The rearm changes the persisted job status to `queued`; preserve the
    # status it replaced so a caller can distinguish recovery from `failed`
    # from an edit made while an earlier rerun was merely queued.
    previous_job_status: Literal["queued", "done", "failed"] = Field(
        description="The job status observed before this assignment re-armed it."
    )


_ASSIGNMENT_PROBLEM_RESPONSES = {
    422: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`invalid-request` — the route parameter is not a UUID,"
        " or the body did not name exactly one of `participantId`,"
        " `displayName` or `unresolved: true` (a blank or NUL-bearing"
        " `displayName` is refused here too).",
    },
    404: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`not-found` — no such meeting."
        " `unknown-speaker-tag` — the meeting's transcript carries no segment"
        " with that label, so the assignment would never match anything."
        " `unknown-participant` — `participantId` names no participant row.",
    },
    409: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`assignment-target-busy` — the meeting's job is `running`, so"
        " re-arming it would race the worker; carries `jobId` and `jobStatus`."
        " Retry once the job settles. An unviewable meeting whose job is not"
        " running is deliberately accepted by this PUT as the curator's"
        " recovery path; no other meeting read or write receives that exception.",
    },
}


@router.put(
    "/meetings/{meeting_id}/speakers/{tag:path}",
    operation_id="assignMeetingSpeaker",
    response_model=SpeakerAssignmentResponse,
    responses=_ASSIGNMENT_PROBLEM_RESPONSES,
)
def assign_meeting_speaker(
    meeting_id: UUID, tag: str, body: AssignSpeakerRequest, request: Request
) -> SpeakerAssignmentResponse:
    """Record who a voice belongs to, and re-arm the meeting to act on it.

    Two writes and nothing else (AD-5): an api-owned `participant_alias` row
    in the `speaker:<meetingId>:<tag>` namespace, and the job re-armed for
    `align → moments → extract`. This route never touches
    `transcript_segment`, `moment` or `artifact`. `align` reads the alias back
    and re-derives the attribution, which is what makes an assignment survive
    every later rerun and re-ingest instead of being a one-off edit the next
    ingest would undo.

    Deliberately READ COMMITTED, not the REPEATABLE READ the read routes use:
    the checks below span `meeting`, `job`, `job_stage`, `transcript_segment`
    and `participant_alias`, and a snapshot frozen at the first of them would
    let this accept against a job whose status changed after the transaction
    opened. `assignment-target-busy` is the refusal that has to see the
    current row, because re-arming a claimed job would race the single
    worker's own final status write (AD-9) and could drop the assignment
    silently.
    """
    pool = request.app.state.pool
    alias_key = speaker_alias_key(meeting_id, tag)
    with pool.connection() as conn:
        if conn.execute(_MEETING_EXISTS, (meeting_id,)).fetchone() is None:
            raise Problem(404, "not-found", f"no meeting with id {meeting_id}")
        job_id, job_status = conn.execute(_JOB_FOR_MEETING, (meeting_id,)).fetchone()
        if job_status == "running":
            raise Problem(
                409,
                "assignment-target-busy",
                f"meeting {meeting_id}'s job is still running — a speaker"
                " assignment re-arms that job, which would race the worker"
                " currently inside it; retry once it settles",
                jobId=str(job_id),
                jobStatus=job_status,
            )
        # Deliberate, route-local recovery exception: every other meeting read
        # and write still calls `_require_viewable`, including the GET beside
        # this PUT. A failed speaker rerun is unviewable because of the
        # assignment the curator must correct, so gating this exact action on
        # viewability would make the lockout self-perpetuating. Do not move
        # this policy into `_require_viewable` or generalize it to the router.
        accepted_while_unviewable = not meeting_evidence_complete(conn, meeting_id)
        if conn.execute(_SPEAKER_TAG_EXISTS, (meeting_id, tag)).fetchone() is None:
            raise Problem(
                404,
                "unknown-speaker-tag",
                f"meeting {meeting_id} has no transcript segment labelled"
                f" {tag!r} — assign one of the labels the meeting's speakers"
                " read returns",
            )

        participant_id: UUID | None
        display_name: str | None
        if body.unresolved:
            # No row, rather than a row naming nobody: `participant_alias`
            # requires a participant, and deleting the key restores `align`'s
            # own answer — `placeholder`, with nothing guessed (AD-13).
            conn.execute(_DELETE_SPEAKER_ALIAS, (alias_key,))
            participant_id = None
            display_name = None
        elif body.participant_id is not None:
            row = conn.execute(_PARTICIPANT_BY_ID, (body.participant_id,)).fetchone()
            if row is None:
                raise Problem(
                    404,
                    "unknown-participant",
                    f"no participant with id {body.participant_id}",
                )
            participant_id, display_name = row
            conn.execute(_UPSERT_SPEAKER_ALIAS, (alias_key, participant_id))
        else:
            display_name = body.display_name
            identity_key = curated_identity_key(meeting_id, tag)
            participant_id = conn.execute(
                _MINT_CURATED_PARTICIPANT, (identity_key, display_name, identity_key)
            ).fetchone()[0]
            conn.execute(_UPSERT_SPEAKER_ALIAS, (alias_key, participant_id))

        conn.execute(_REARM_JOB, (job_id,))
        conn.execute(_REARM_STAGES, (job_id, list(SPEAKER_ASSIGNMENT_STAGES)))

    logs.log_event(
        "speakers.assigned",
        meeting_id=meeting_id,
        speaker_label=tag,
        participant_id=participant_id,
        unresolved=body.unresolved,
        job_id=job_id,
        accepted_while_unviewable=accepted_while_unviewable,
        previous_job_status=job_status,
    )
    return SpeakerAssignmentResponse(
        meeting_id=meeting_id,
        speaker_label=tag,
        participant_id=participant_id,
        display_name=display_name,
        job_id=job_id,
        rearmed_stages=list(SPEAKER_ASSIGNMENT_STAGES),
        accepted_while_unviewable=accepted_while_unviewable,
        previous_job_status=job_status,
    )
