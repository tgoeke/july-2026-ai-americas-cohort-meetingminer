"""GET /threads and GET /threads/{threadId}/timeline (story 10.3).

The read side of a thread: the list the Threads view opens onto, and one
thread's history served at the level of detail the client is currently
rendering. Read-only over Postgres (AD-2/AD-5/AD-11): SELECTs only, no store
client, no model call, no writes.

**Four levels, four responses, exactly one tier each.** `bands` is a density
strip, `meetings` the meetings on that strip, `moments` the moments inside
them, `evidence` those moments with what backs them. The four are separate
models discriminated on `level`, so a `bands` response has no `moments` key at
all rather than an empty one — a client cannot accidentally render a tier it
did not ask for, and a leaked tier is a schema change rather than a silent
extra field.

**The coarse levels never join `moment`.** `topic_mention` already carries
both `meeting_id` and `anchor_ms` (migration 0014), so a mention's wall clock
is computable from the mention and its meeting alone. `bands` and `meetings`
therefore aggregate over `topic_thread → topic_mention → meeting` and nothing
else: the row set is bounded first by the thread (`topic_thread_thread_id_idx`,
then `topic_mention`'s primary-key prefix `topic_id`) and then by the window,
and the number of rows returned is bounded by the bucket ladder in
`domain/thread_timeline.py`. A corpus of hundreds of meetings costs a band
what one thread's mentions cost, not what the corpus's moments cost.

**One selector, two timestamps with different meanings.** At every level, a
row belongs to the requested window when its `topic_mention.anchor_ms` does.
That one predicate also owns the envelope totals, so zooming cannot move a row
across the window boundary. Fine rows still serve `startMs` as
`moment.start_ms` and derive `occurredAt` from it: that timestamp is where the
evidence begins and where a reader seeks. It may therefore precede the
requested window; it describes the returned evidence rather than selecting
it.

**Never a storage path** (AD-17). No query here selects `screenshot.path`,
`frame.path` or `meeting_media.drop_relative_path`. Media travels as opaque
ids: `screenshotId`, and at the evidence level `recordingMediaId`, which is
the meeting id because `meeting_media` is keyed by `meeting_id`. Resolving
either to bytes is the media route's job; no root, no path and no server-built
URL leaves this module.

**The wall clock is derived here, never reconstructed by the client.**
`domain/thread_timeline.py` owns the rule (meeting start + offset, midnight
anchoring at `day` precision) and the RFC 3339 spelling; this module applies
the same rule in SQL for the aggregates, and the two are pinned against each
other by test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, get_args
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.domain.thread_timeline import (
    LEVELS,
    Level,
    format_rfc3339,
    plan_buckets,
)

router = APIRouter()
# No `ROUTER_ORDER`: this module is default-order deliberately. Its own
# matching hazard — the literal `/threads` under the parameterized
# `/threads/{thread_id}/timeline` — is resolved *inside* the router by
# declaration order, the `media.py` way, and no other module claims a
# `/threads` prefix, so its position among the modules carries none.

# The most of a covering segment's text the evidence tier ships per moment. An
# excerpt orients; `GET /moments/{momentId}` owns the transcript. The cap is
# the moments list's own `PREVIEW_MAX_CHARS`, deliberately: the two are the
# same gesture at two addresses and a reader comparing them should not have to
# discover they clip differently.
EXCERPT_MAX_CHARS = 300

# The most moments a single fine-level response may carry. The level-of-detail
# contract is that a client asks for `moments` only once it has zoomed into a
# window that holds few, but a client is free to ask for `moments` over the
# whole corpus span and the wire must not grow without bound when it does.
# Truncation is reported, never silent: `truncated` says the window holds more
# than was served, so a caller narrows the window rather than believing a
# short list.
MOMENT_LEVEL_LIMIT = 500


def _occurred_at_sql(offset_column: str, meeting_alias: str = "mt") -> str:
    """The SQL twin of `domain.thread_timeline.occurred_at`, for one offset.

    Written as an expression rather than a function so `EXPLAIN` shows the
    window predicate on it, and kept in one place so the mention selector and
    evidence timestamp cannot drift apart in how they treat day precision.
    `AT TIME ZONE 'UTC'` twice is the portable form of "truncate this instant
    to its UTC date": the first converts the `timestamptz` to a naive UTC
    reading, the second reads the truncated result back as UTC.
    """
    return (
        f"(CASE WHEN {meeting_alias}.started_at_precision = 'day'"
        f" THEN date_trunc('day', {meeting_alias}.started_at AT TIME ZONE 'UTC')"
        " AT TIME ZONE 'UTC'"
        f" ELSE {meeting_alias}.started_at END"
        f" + ({offset_column} * INTERVAL '1 millisecond'))"
    )


# --- GET /threads ----------------------------------------------------------

# Every thread that is navigable, with its totals and its colour. An INNER
# JOIN on membership on purpose: migration 0015 keeps a `thread` row whose
# last `topic_thread` link went away, as a durable identity a later rerun can
# reclaim, and such a row is a reuse target rather than something to navigate
# to. Ordered most-recently-mentioned first with the id as the tie-break, so
# two threads whose last mention is the same instant do not swap places
# between requests; the view sorts by activity or recency itself, from the two
# counts and the two instants served here.
_THREAD_LIST = (
    "SELECT th.id, th.name, th.color_ordinal, COUNT(*),"
    " COUNT(DISTINCT tm.meeting_id),"
    f" MIN({_occurred_at_sql('tm.anchor_ms')}),"
    f" MAX({_occurred_at_sql('tm.anchor_ms')})"
    " FROM thread th"
    " JOIN topic_thread tt ON tt.thread_id = th.id"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " JOIN meeting mt ON mt.id = tm.meeting_id"
    " GROUP BY th.id, th.name, th.color_ordinal"
    " ORDER BY MAX("
    f"{_occurred_at_sql('tm.anchor_ms')}) DESC, th.id"
)

_THREAD_ROW = "SELECT id, name, color_ordinal FROM thread WHERE id = %(thread_id)s"

# The thread's own span, which is the default window: a client that names no
# `from`/`to` gets the whole history rather than an arbitrary recent slice.
_THREAD_SPAN = (
    f"SELECT MIN({_occurred_at_sql('tm.anchor_ms')}),"
    f" MAX({_occurred_at_sql('tm.anchor_ms')})"
    " FROM topic_thread tt"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " JOIN meeting mt ON mt.id = tm.meeting_id"
    " WHERE tt.thread_id = %(thread_id)s"
)


# --- the coarse levels: mentions only, never `moment` ----------------------

# One thread's mentions with their wall clock, the projection both coarse
# levels aggregate over. `moment_id` is carried as a *column of the mention*
# so `meetings` can count distinct moments without the `moment` table being
# reached at all — the whole reason the coarse levels are cheap.
_THREAD_MENTIONS = (
    "SELECT tm.moment_id, tm.meeting_id, tm.topic_id,"
    " mt.title AS meeting_title, mt.corpus, mt.has_recording,"
    " mt.started_at_precision AS precision,"
    f" {_occurred_at_sql('tm.anchor_ms')} AS occurred_at"
    " FROM topic_thread tt"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " JOIN meeting mt ON mt.id = tm.meeting_id"
    " WHERE tt.thread_id = %(thread_id)s"
)

# Density per bucket, computed in the database rather than by counting rows in
# Python: the point of a band is that the corpus never crosses the wire. The
# index is clamped into the band because the last bucket is closed — an item
# landing exactly on `to` belongs to the band's final bucket, not past its end.
_BANDS = (
    "SELECT LEAST(FLOOR(EXTRACT(EPOCH FROM"
    " (m.occurred_at - %(window_from)s)) * 1000 / %(bucket_ms)s),"
    " %(last_bucket)s)::bigint AS bucket,"
    " COUNT(*), COUNT(DISTINCT m.meeting_id)"
    f" FROM ({_THREAD_MENTIONS}) m"
    " WHERE m.occurred_at >= %(window_from)s AND m.occurred_at <= %(window_to)s"
    " GROUP BY 1 ORDER BY 1"
)

_MEETINGS_LEVEL = (
    "SELECT m.meeting_id, m.meeting_title, m.corpus, m.has_recording, m.precision,"
    " COUNT(*), COUNT(DISTINCT m.moment_id),"
    " MIN(m.occurred_at), MAX(m.occurred_at)"
    f" FROM ({_THREAD_MENTIONS}) m"
    " WHERE m.occurred_at >= %(window_from)s AND m.occurred_at <= %(window_to)s"
    " GROUP BY m.meeting_id, m.meeting_title, m.corpus, m.has_recording, m.precision"
    " ORDER BY MIN(m.occurred_at), m.meeting_id"
)

# The split panel's membership: which of the thread's topics this meeting
# carries, and which leg of 10.2's rule attached each. Grouped, not listed:
# one topic mentioned in five moments of one meeting is one membership row.
_MEETING_TOPICS = (
    "SELECT m.meeting_id, m.topic_id, t.name, tt.linked_by"
    f" FROM ({_THREAD_MENTIONS}) m"
    " JOIN topic t ON t.id = m.topic_id"
    " JOIN topic_thread tt ON tt.topic_id = m.topic_id"
    " WHERE m.occurred_at >= %(window_from)s AND m.occurred_at <= %(window_to)s"
    " GROUP BY m.meeting_id, m.topic_id, t.name, tt.linked_by"
    " ORDER BY m.meeting_id, t.name, m.topic_id"
)

# The window totals every level's envelope carries, so a client zooming
# between levels sees one number for "how much is in this window" rather than
# a count that changes with the tier it happens to be rendering.
_WINDOW_TOTALS = (
    "SELECT COUNT(*), COUNT(DISTINCT m.meeting_id), COUNT(DISTINCT m.moment_id)"
    f" FROM ({_THREAD_MENTIONS}) m"
    " WHERE m.occurred_at >= %(window_from)s AND m.occurred_at <= %(window_to)s"
)


# --- the fine levels: the moments themselves -------------------------------

# The thread's moments whose *mentions* fall in the window. This is the first
# query that touches `moment`, but selection is still the exact mention-anchor
# predicate used by the coarse levels and envelope totals. `occurred_at` below
# intentionally remains the moment's evidence start and may precede the
# window. Superseded rows are excluded exactly as the moments list excludes
# them (`api/moments.py`) — a timeline must not interleave ghosts with live
# moments. LIMIT one past the cap so the envelope can say `truncated` without
# a second counting query.
_MOMENTS_LEVEL = (
    "SELECT m.moment_id, m.meeting_id, m.start_ms, m.screenshot_id,"
    " m.has_recording, m.precision, m.occurred_at FROM ("
    "SELECT mo.id AS moment_id, mo.meeting_id, mo.start_ms, mo.screenshot_id,"
    " mt.has_recording, mt.started_at_precision AS precision,"
    f" {_occurred_at_sql('mo.start_ms')} AS occurred_at"
    " FROM moment mo JOIN meeting mt ON mt.id = mo.meeting_id"
    " WHERE mo.id IN (SELECT tm.moment_id FROM topic_thread tt"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " JOIN meeting anchor_mt ON anchor_mt.id = tm.meeting_id"
    " WHERE tt.thread_id = %(thread_id)s"
    f" AND {_occurred_at_sql('tm.anchor_ms', 'anchor_mt')} >= %(window_from)s"
    f" AND {_occurred_at_sql('tm.anchor_ms', 'anchor_mt')} <= %(window_to)s)"
    " AND COALESCE(mo.provenance->>'superseded', '') <> 'true'"
    ") m"
    " ORDER BY m.occurred_at, m.meeting_id, m.moment_id"
    " LIMIT %(limit)s"
)

# The row's title: the name of the thread's own topic that put this moment on
# the timeline. A moment has no title column (migration 0006 — its identity is
# its offset, not a name), and on a *thread* timeline the honest label is the
# subject being followed. DISTINCT ON with an explicit order because a moment
# may carry two of the thread's topics; earliest stamp wins, id as tie-break,
# so the label is stable across requests.
_MOMENT_TITLES = (
    "SELECT DISTINCT ON (tm.moment_id) tm.moment_id, t.name"
    " FROM topic_thread tt"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " JOIN topic t ON t.id = tt.topic_id"
    " WHERE tt.thread_id = %(thread_id)s AND tm.moment_id = ANY(%(moment_ids)s)"
    " ORDER BY tm.moment_id, tm.anchor_ms, t.id"
)

# Speakers where known, and only where known: `resolved` is the one
# `speaker_resolution` that names a person (migration 0005 — the other three
# are `unresolved`, `ambiguous`, `placeholder`, none of which a timeline may
# print as a name). First appearance order inside the moment, deduplicated.
_MOMENT_SPEAKERS = (
    "SELECT ms.moment_id, ts.speaker_label, MIN(ts.ordinal) AS first_seen"
    " FROM moment_segment ms"
    " JOIN transcript_segment ts ON ts.id = ms.transcript_segment_id"
    " WHERE ms.moment_id = ANY(%(moment_ids)s)"
    " AND ts.speaker_resolution = 'resolved'"
    " GROUP BY ms.moment_id, ts.speaker_label"
    " ORDER BY ms.moment_id, first_seen"
)

# The evidence tier's excerpt: the first covered segment, capped. Through the
# `moment_segment` join, never a `BETWEEN start_ms AND end_ms` filter — the
# rule `api/moments.py` states and for the same reason.
_MOMENT_EXCERPTS = (
    "SELECT DISTINCT ON (ms.moment_id) ms.moment_id,"
    f" LEFT(ts.text, {EXCERPT_MAX_CHARS})"
    " FROM moment_segment ms"
    " JOIN transcript_segment ts ON ts.id = ms.transcript_segment_id"
    " WHERE ms.moment_id = ANY(%(moment_ids)s)"
    " ORDER BY ms.moment_id, ts.ordinal"
)

# The artifact anchors: what this moment yielded, in mint order — the same
# order and the same reasoning as the moment view's right rail. Body is not
# carried: an anchor is a pointer to `GET /moments/{momentId}`, not a copy of
# the document.
_MOMENT_ARTIFACTS = (
    "SELECT moment_id, id, kind, state, title FROM artifact"
    " WHERE moment_id = ANY(%(moment_ids)s) ORDER BY moment_id, created_at, id"
)


# --- wire models -----------------------------------------------------------


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ThreadSummary(_Camel):
    """One thread as the Threads view lists it.

    Every instant is an RFC 3339 UTC string the server derived, never a
    timestamp the client is expected to reassemble from an offset.
    """

    thread_id: UUID
    name: str
    mention_count: int
    meeting_count: int
    first_mention_at: str
    last_mention_at: str
    # Allocated once by migration 0017's sequence and immutable afterwards, so
    # a colour derived from it survives re-sorting, renaming and merging.
    color_ordinal: int


class ThreadsResponse(_Camel):
    threads: list[ThreadSummary]


class TimelineBand(_Camel):
    """One bucket of the density strip. Half-open `[startAt, endAt)`, except
    the band's last bucket, which is closed on the window's own end."""

    start_at: str
    end_at: str
    mention_count: int
    meeting_count: int


class TimelineTopic(_Camel):
    """One of the thread's topics as a meeting carries it, with the leg of
    story 10.2's rule that attached it."""

    topic_id: UUID
    name: str
    linked_by: str


class TimelineMeeting(_Camel):
    meeting_id: UUID
    title: str | None = None
    corpus: str
    has_recording: bool
    # The meeting's first mention of this thread inside the window — where the
    # meeting sits on the band — and its last, so a long meeting renders as a
    # span rather than a point.
    occurred_at: str
    last_occurred_at: str
    occurred_at_precision: str
    mention_count: int
    moment_count: int
    topics: list[TimelineTopic]


class TimelineMoment(_Camel):
    """The moments tier, exactly. No excerpt, no artifacts, no media beyond
    the opaque screenshot id — those are the evidence tier's."""

    moment_id: UUID
    meeting_id: UUID
    # The thread's topic name for this moment; `moment` has no title column.
    title: str
    start_ms: int
    occurred_at: str = Field(
        description="Evidence start and seek position, derived from moment.start_ms. "
        "Window membership is selected by the topic mention anchor, so this value "
        "may fall outside the requested window."
    )
    occurred_at_precision: str
    # Only `resolved` speaker labels, in first-appearance order. Empty when
    # the moment covers no segment whose speaker is known.
    speakers: list[str]
    # Opaque (AD-17). NULL on a transcript-only meeting or a moment past the
    # last capture, exactly as `moment.screenshot_id` is.
    screenshot_id: UUID | None = None


class TimelineArtifact(_Camel):
    artifact_id: UUID
    kind: str
    state: str
    title: str


class TimelineEvidence(TimelineMoment):
    """The moments tier plus what backs it.

    `recordingMediaId` is the meeting id: `meeting_media` is keyed by
    `meeting_id` (migration 0002), so the meeting id *is* the recording's
    media id. It is NULL when the meeting has no recording, so a client never
    offers replay it cannot get bytes for.
    """

    excerpt: str | None = None
    artifacts: list[TimelineArtifact]
    has_recording: bool
    recording_media_id: UUID | None = None


class _TimelineEnvelope(_Camel):
    """What every level carries: which thread, which window, and the window's
    totals — so zooming between levels does not change the numbers."""

    thread_id: UUID
    name: str
    color_ordinal: int
    # NULL only for a thread with no mentions at all and no window named.
    window_from: str | None = None
    window_to: str | None = None
    mention_count: int
    meeting_count: int
    moment_count: int


class BandsTimeline(_TimelineEnvelope):
    level: Literal["bands"]
    bucket_ms: int | None = None
    bucket_count: int
    bands: list[TimelineBand]


class MeetingsTimeline(_TimelineEnvelope):
    level: Literal["meetings"]
    meetings: list[TimelineMeeting]


class MomentsTimeline(_TimelineEnvelope):
    level: Literal["moments"]
    # True when the window holds more moments than `MOMENT_LEVEL_LIMIT`.
    # Reported rather than silent: a short list must be distinguishable from a
    # complete one.
    truncated: bool
    moments: list[TimelineMoment]


class EvidenceTimeline(_TimelineEnvelope):
    level: Literal["evidence"]
    truncated: bool
    evidence: list[TimelineEvidence]


TimelineResponse = Annotated[
    BandsTimeline | MeetingsTimeline | MomentsTimeline | EvidenceTimeline,
    Field(discriminator="level"),
]

_PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`invalid-window` — `from` is after `to`.",
    },
    404: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`not-found` — no thread with that id.",
    },
    422: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`invalid-request` — the id is not a UUID, or `level`"
        " is not one of `bands|meetings|moments|evidence`.",
    },
}


# --- helpers ---------------------------------------------------------------


def _as_utc(value: datetime) -> datetime:
    """A client's `from`/`to` as UTC. A naive value is read as UTC rather than
    as the server's local zone: the whole timeline is UTC, and guessing a zone
    would silently shift a window by hours."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_topics(rows: list[tuple], meeting_id: UUID) -> list[TimelineTopic]:
    return [
        TimelineTopic(topic_id=topic_id, name=name, linked_by=linked_by)
        for row_meeting, topic_id, name, linked_by in rows
        if row_meeting == meeting_id
    ]


def _group(rows: list[tuple]) -> dict[UUID, list[tuple]]:
    """Rows keyed by their first column, order preserved within each key."""
    grouped: dict[UUID, list[tuple]] = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row[1:])
    return grouped


# --- routes ----------------------------------------------------------------
#
# The literal `/threads` is declared before `/threads/{thread_id}/timeline`,
# the `media.py` rule: a parameterized route registered ahead of a literal
# sibling swallows it. These two cannot collide today (they diverge in
# length), but the declaration order is the house habit and the next route
# added under this prefix inherits it.


@router.get("/threads", operation_id="listThreads", response_model=ThreadsResponse)
def list_threads(request: Request) -> ThreadsResponse:
    pool = request.app.state.pool
    with pool.connection() as conn:
        rows = conn.execute(_THREAD_LIST).fetchall()
    return ThreadsResponse(
        threads=[
            ThreadSummary(
                thread_id=thread_id,
                name=name,
                mention_count=mention_count,
                meeting_count=meeting_count,
                first_mention_at=format_rfc3339(first_at),
                last_mention_at=format_rfc3339(last_at),
                color_ordinal=color_ordinal,
            )
            for (
                thread_id,
                name,
                color_ordinal,
                mention_count,
                meeting_count,
                first_at,
                last_at,
            ) in rows
        ]
    )


@router.get(
    "/threads/{thread_id}/timeline",
    operation_id="getThreadTimeline",
    response_model=TimelineResponse,
    responses=_PROBLEM_RESPONSES,
)
def get_thread_timeline(
    thread_id: UUID,
    request: Request,
    level: Level = "bands",
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
) -> BandsTimeline | MeetingsTimeline | MomentsTimeline | EvidenceTimeline:
    """One thread at one level of detail, bounded by an optional window.

    Window membership at every level is selected by each topic mention's
    anchor. A fine row's `occurredAt` is instead its evidence start and may
    fall outside the requested window.

    All reads for one response happen on one connection under `REPEATABLE
    READ`, the rule `api/moments.py` states: a response is one snapshot, so a
    band and the meetings under it can never come from either side of a
    concurrent derivation.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        thread = conn.execute(_THREAD_ROW, {"thread_id": thread_id}).fetchone()
        if thread is None:
            raise Problem(404, "not-found", f"no thread with id {thread_id}")
        _, name, color_ordinal = thread

        span_from, span_to = conn.execute(
            _THREAD_SPAN, {"thread_id": thread_id}
        ).fetchone()
        window_from = _as_utc(from_at) if from_at is not None else span_from
        window_to = _as_utc(to_at) if to_at is not None else span_to
        if window_from is None or window_to is None:
            # A thread with no mentions and no window named has no timeline to
            # bound. Answered as an empty tier with a null window rather than
            # as a 404: the thread exists, and 0015 keeps such rows on purpose.
            return _empty_timeline(level, thread_id, name, color_ordinal)
        if window_to < window_from:
            raise Problem(
                400,
                "invalid-window",
                f"from ({format_rfc3339(window_from)}) is after to"
                f" ({format_rfc3339(window_to)})",
            )

        params: dict[str, Any] = {
            "thread_id": thread_id,
            "window_from": window_from,
            "window_to": window_to,
        }
        mention_count, meeting_count, moment_count = conn.execute(
            _WINDOW_TOTALS, params
        ).fetchone()
        envelope: dict[str, Any] = {
            "thread_id": thread_id,
            "name": name,
            "color_ordinal": color_ordinal,
            "window_from": format_rfc3339(window_from),
            "window_to": format_rfc3339(window_to),
            "mention_count": mention_count,
            "meeting_count": meeting_count,
            "moment_count": moment_count,
        }

        if level == "bands":
            return _bands(conn, params, envelope, window_from, window_to)
        if level == "meetings":
            return _meetings(conn, params, envelope)
        return _fine(conn, params, envelope, level)


def _empty_timeline(
    level: Level, thread_id: UUID, name: str, color_ordinal: int
) -> BandsTimeline | MeetingsTimeline | MomentsTimeline | EvidenceTimeline:
    envelope: dict[str, Any] = {
        "thread_id": thread_id,
        "name": name,
        "color_ordinal": color_ordinal,
        "window_from": None,
        "window_to": None,
        "mention_count": 0,
        "meeting_count": 0,
        "moment_count": 0,
    }
    if level == "bands":
        return BandsTimeline(
            **envelope, level="bands", bucket_ms=None, bucket_count=0, bands=[]
        )
    if level == "meetings":
        return MeetingsTimeline(**envelope, level="meetings", meetings=[])
    if level == "moments":
        return MomentsTimeline(
            **envelope, level="moments", truncated=False, moments=[]
        )
    return EvidenceTimeline(
        **envelope, level="evidence", truncated=False, evidence=[]
    )


def _bands(
    conn: Any,
    params: dict[str, Any],
    envelope: dict[str, Any],
    window_from: datetime,
    window_to: datetime,
) -> BandsTimeline:
    """The density strip: one aggregate query, one row per non-empty bucket.

    Empty buckets are filled in here rather than in SQL. A `generate_series`
    join would return every bucket from the database and make the coarse level
    pay for the window's *width* instead of for the thread's mentions, which
    is the cost this level exists to avoid.
    """
    bucket_ms, bucket_count = plan_buckets(window_from, window_to)
    rows = conn.execute(
        _BANDS,
        {**params, "bucket_ms": bucket_ms, "last_bucket": bucket_count - 1},
    ).fetchall()
    counted = {int(bucket): (mentions, meetings) for bucket, mentions, meetings in rows}
    bands = []
    for index in range(bucket_count):
        mentions, meetings = counted.get(index, (0, 0))
        start = window_from + timedelta(milliseconds=index * bucket_ms)
        end = window_from + timedelta(milliseconds=(index + 1) * bucket_ms)
        # The last bucket is closed on the window's own end rather than on the
        # ladder step past it, so the band never claims to cover time the
        # caller did not ask about.
        if index == bucket_count - 1:
            end = min(end, window_to)
        bands.append(
            TimelineBand(
                start_at=format_rfc3339(start),
                end_at=format_rfc3339(end),
                mention_count=mentions,
                meeting_count=meetings,
            )
        )
    return BandsTimeline(
        **envelope,
        level="bands",
        bucket_ms=bucket_ms,
        bucket_count=bucket_count,
        bands=bands,
    )


def _meetings(
    conn: Any, params: dict[str, Any], envelope: dict[str, Any]
) -> MeetingsTimeline:
    rows = conn.execute(_MEETINGS_LEVEL, params).fetchall()
    topic_rows = conn.execute(_MEETING_TOPICS, params).fetchall()
    meetings = [
        TimelineMeeting(
            meeting_id=meeting_id,
            title=title,
            corpus=corpus,
            has_recording=has_recording,
            occurred_at=format_rfc3339(first_at),
            last_occurred_at=format_rfc3339(last_at),
            occurred_at_precision=precision,
            mention_count=mention_count,
            moment_count=moment_count,
            topics=_serialize_topics(topic_rows, meeting_id),
        )
        for (
            meeting_id,
            title,
            corpus,
            has_recording,
            precision,
            mention_count,
            moment_count,
            first_at,
            last_at,
        ) in rows
    ]
    return MeetingsTimeline(**envelope, level="meetings", meetings=meetings)


def _fine(
    conn: Any, params: dict[str, Any], envelope: dict[str, Any], level: Level
) -> MomentsTimeline | EvidenceTimeline:
    """The moments and evidence tiers, which differ only in what they add.

    One moment query, then lookups keyed on the moment ids it returned — so
    every follow-up read is bounded by the page rather than by the thread.
    """
    rows = conn.execute(
        _MOMENTS_LEVEL, {**params, "limit": MOMENT_LEVEL_LIMIT + 1}
    ).fetchall()
    truncated = len(rows) > MOMENT_LEVEL_LIMIT
    rows = rows[:MOMENT_LEVEL_LIMIT]
    moment_ids = [row[0] for row in rows]
    lookup = {**params, "moment_ids": moment_ids}
    titles = dict(conn.execute(_MOMENT_TITLES, lookup).fetchall())
    speakers = _group(conn.execute(_MOMENT_SPEAKERS, lookup).fetchall())

    base = [
        {
            "moment_id": moment_id,
            "meeting_id": meeting_id,
            # A moment reached through a mention always has a topic on this
            # thread; the thread's own name is the honest fallback if a
            # concurrent re-derivation moved the topic between the two reads.
            "title": titles.get(moment_id, envelope["name"]),
            "start_ms": start_ms,
            "occurred_at": format_rfc3339(occurred),
            "occurred_at_precision": precision,
            "speakers": [label for label, _ in speakers.get(moment_id, [])],
            "screenshot_id": screenshot_id,
        }
        for (
            moment_id,
            meeting_id,
            start_ms,
            screenshot_id,
            _has_recording,
            precision,
            occurred,
        ) in rows
    ]

    if level == "moments":
        return MomentsTimeline(
            **envelope,
            level="moments",
            truncated=truncated,
            moments=[TimelineMoment(**item) for item in base],
        )

    excerpts = dict(conn.execute(_MOMENT_EXCERPTS, lookup).fetchall())
    artifacts = _group(conn.execute(_MOMENT_ARTIFACTS, lookup).fetchall())
    recordings = {row[0]: row[4] for row in rows}
    evidence = [
        TimelineEvidence(
            **item,
            excerpt=excerpts.get(item["moment_id"]),
            artifacts=[
                TimelineArtifact(
                    artifact_id=artifact_id, kind=kind, state=state, title=title
                )
                for artifact_id, kind, state, title in artifacts.get(
                    item["moment_id"], []
                )
            ],
            has_recording=recordings[item["moment_id"]],
            recording_media_id=(
                item["meeting_id"] if recordings[item["moment_id"]] else None
            ),
        )
        for item in base
    ]
    return EvidenceTimeline(
        **envelope, level="evidence", truncated=truncated, evidence=evidence
    )


# A hard check rather than an `assert` (`python -O` strips asserts): the
# discriminated union and the level vocabulary must name the same four tiers,
# or a level the domain declares would have no response model to serve it.
_UNION_LEVELS = tuple(
    get_args(model.model_fields["level"].annotation)[0]
    for model in (BandsTimeline, MeetingsTimeline, MomentsTimeline, EvidenceTimeline)
)
if _UNION_LEVELS != LEVELS:
    raise RuntimeError(
        "the timeline response models must name the domain's four levels,"
        f" verbatim: {_UNION_LEVELS!r} != {LEVELS!r}"
    )
