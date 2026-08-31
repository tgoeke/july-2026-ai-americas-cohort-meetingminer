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

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.moments import _require_viewable
from meetingminer.api.problems import Problem, ProblemDetails

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
