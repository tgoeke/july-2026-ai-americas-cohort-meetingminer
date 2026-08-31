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

from meetingminer import logs
from meetingminer.adapters.embed import EmbedderError, EmbedderUnavailableError
from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.domain.thread_timeline import (
    LEVELS,
    Level,
    format_rfc3339,
    plan_buckets,
)
from meetingminer.domain.thread_trace import (
    CANDIDATE_LIMIT,
    PER_MEETING_DEFAULT,
    SUGGESTION_LIMIT_DEFAULT,
    SUGGESTION_MAX_MEETINGS,
    SUGGESTION_MIN_MEETINGS,
    SUGGESTION_MIN_SPAN_DAYS,
    completeness_note,
    drop_near_duplicates,
    span_days,
)
from meetingminer.projections.query import search_moments
from meetingminer.projections.stores import (
    ProjectionError,
    StoreUnavailableError,
    meili_client,
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

# How many ranked subjects the suggestion query reads before near-duplicate
# dropping picks from them. A scan bound, not the answer: dropping duplicates
# from exactly `limit` rows would return fewer than `limit` subjects whenever
# any two of them were the same concern.
_SUGGESTION_SCAN = 200

# The sample leg's top-k. Large enough that a wording with a real history fills
# a timeline, small enough that it is plainly a sample — which is what the
# response says it is.
_SAMPLE_LIMIT_DEFAULT = 60

# Adjacent subjects offered beneath a trace.
_RELATED_LIMIT = 8


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


# --- story 10.7: threads as a query ----------------------------------------
#
# The other way in. Story 10.3 above serves one *derived* thread at four levels
# of detail, which is the right shape for a reader who already knows which
# thread they want. It is the wrong shape for the reader the acceptance
# criteria describe, who knows a subject and not a thread id, and who wants
# every meeting where it surfaced on one timeline.
#
# **One payload, every altitude.** The trace below is served once and the
# client re-renders it as it zooms. It is deliberately not the level-of-detail
# endpoint: a semantic zoom that refetches at each threshold cannot keep what
# is under the cursor under the cursor, and the payload for one subject is
# small enough that tiering it buys nothing.

# Subjects worth tracing, for the empty state.
#
# Ranked by the calendar time they span, inside a band on the meeting count —
# never by mention frequency, which surfaces only the generic subjects that
# appear in nearly every meeting and whose thread is the whole corpus. The
# band and the sort are `domain/thread_trace.py`'s; this query applies them.
# `LIMIT` here is a scan bound, not the answer: near-duplicate dropping needs
# more rows than it returns.
_SUGGESTIONS = (
    "SELECT s.id, s.name, s.color_ordinal, s.meetings, s.mentions,"
    " s.first_at, s.last_at FROM ("
    " SELECT th.id, th.name, th.color_ordinal,"
    " COUNT(DISTINCT tm.meeting_id) AS meetings, COUNT(*) AS mentions,"
    f" MIN({_occurred_at_sql('tm.anchor_ms')}) AS first_at,"
    f" MAX({_occurred_at_sql('tm.anchor_ms')}) AS last_at"
    " FROM thread th"
    " JOIN topic_thread tt ON tt.thread_id = th.id"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " JOIN meeting mt ON mt.id = tm.meeting_id"
    " GROUP BY th.id, th.name, th.color_ordinal"
    ") s"
    " WHERE s.meetings >= %(min_meetings)s AND s.meetings <= %(max_meetings)s"
    " AND s.last_at - s.first_at >= %(min_span_days)s * INTERVAL '1 day'"
    " ORDER BY s.last_at - s.first_at DESC, s.meetings DESC, s.id"
    " LIMIT %(scan)s"
)

# Does this wording plainly name one known subject?
#
# Exact and unambiguous only. A fuzzy match here would silently answer a
# different question than the one typed, which is the failure the two-legged
# design exists to remove: the exhaustive leg's whole claim is "every time this
# came up", and it may only be made about the thing that was actually asked
# for. The typed phrase is matched against the thread's display name, its
# content-derived identity key, and the names of the topics it was built from —
# a reader types the subject as they heard it, which is a topic name far more
# often than a thread name.
_EXACT_SUBJECT = (
    "SELECT DISTINCT th.id, th.name, th.color_ordinal"
    " FROM thread th"
    " JOIN topic_thread tt ON tt.thread_id = th.id"
    " JOIN topic t ON t.id = tt.topic_id"
    " WHERE lower(th.name) = %(phrase)s"
    " OR lower(th.identity_key) = %(phrase)s"
    " OR lower(t.name) = %(phrase)s"
    " LIMIT 5"
)

# The adjacent subjects a wording adjoins, offered rather than guessed between.
# Only threads that actually span meetings are offered: a one-meeting row is a
# durable identity kept as a reuse target (migration 0015), not a thread by
# `domain/threads.py`'s own definition, and offering one as a trace would send
# the reader to a timeline with a single point on it.
_CANDIDATES = (
    "SELECT s.id, s.name, s.color_ordinal, s.meetings, s.first_at, s.last_at"
    " FROM ("
    " SELECT th.id, th.name, th.color_ordinal,"
    " COUNT(DISTINCT tm.meeting_id) AS meetings,"
    f" MIN({_occurred_at_sql('tm.anchor_ms')}) AS first_at,"
    f" MAX({_occurred_at_sql('tm.anchor_ms')}) AS last_at"
    " FROM thread th"
    " JOIN topic_thread tt ON tt.thread_id = th.id"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " JOIN meeting mt ON mt.id = tm.meeting_id"
    " WHERE th.name ILIKE %(like)s OR th.id IN ("
    " SELECT tt2.thread_id FROM topic_thread tt2"
    " JOIN topic t2 ON t2.id = tt2.topic_id WHERE t2.name ILIKE %(like)s)"
    " GROUP BY th.id, th.name, th.color_ordinal"
    ") s"
    " WHERE s.meetings >= 2"
    " ORDER BY s.meetings DESC, s.last_at DESC, s.id"
    " LIMIT %(limit)s"
)

# Every meeting that mentions the subject — the stops, whole.
#
# There is no window and no overall limit on this query, and that is the point.
# An overall cap cuts the tail off a long-running subject and shows the first
# months as though they were the whole history; the capping happens in
# `_TRACE_MOMENTS` below, per meeting, so every stop survives.
#
# `moment` is joined rather than aggregated from the mention alone (which the
# coarse timeline levels can do) because superseded moments must be excluded
# here: these counts are printed beside the quoted ones, and two figures that
# count different row sets would misreport the cap as data loss.
_TRACE_STOPS = (
    "SELECT tm.meeting_id, mt.title, mt.corpus, mt.has_recording,"
    " mt.started_at_precision,"
    " COUNT(*), COUNT(DISTINCT tm.moment_id),"
    f" MIN({_occurred_at_sql('tm.anchor_ms')}),"
    f" MAX({_occurred_at_sql('tm.anchor_ms')})"
    " FROM topic_thread tt"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " JOIN moment mo ON mo.id = tm.moment_id"
    " JOIN meeting mt ON mt.id = tm.meeting_id"
    " WHERE tt.thread_id = %(thread_id)s"
    " AND COALESCE(mo.provenance->>'superseded', '') <> 'true'"
    " GROUP BY tm.meeting_id, mt.title, mt.corpus, mt.has_recording,"
    " mt.started_at_precision"
    f" ORDER BY MIN({_occurred_at_sql('tm.anchor_ms')}), tm.meeting_id"
)

# The moments quoted at each stop, capped per meeting by a window function so
# the cap is a property of the row set rather than of a Python loop that a
# later edit could reorder. Earliest first inside each meeting: the reader is
# reading a history, and the first thing said about a subject in a meeting is
# the one that places it.
_TRACE_MOMENTS = (
    "SELECT q.moment_id, q.meeting_id, q.start_ms, q.screenshot_id,"
    " q.occurred_at, q.precision FROM ("
    " SELECT mo.id AS moment_id, mo.meeting_id, mo.start_ms, mo.screenshot_id,"
    " mt.started_at_precision AS precision,"
    f" {_occurred_at_sql('mo.start_ms')} AS occurred_at,"
    " ROW_NUMBER() OVER (PARTITION BY mo.meeting_id"
    " ORDER BY mo.start_ms, mo.id) AS rn"
    " FROM moment mo JOIN meeting mt ON mt.id = mo.meeting_id"
    " WHERE mo.id IN (SELECT tm.moment_id FROM topic_thread tt"
    " JOIN topic_mention tm ON tm.topic_id = tt.topic_id"
    " WHERE tt.thread_id = %(thread_id)s)"
    " AND COALESCE(mo.provenance->>'superseded', '') <> 'true'"
    ") q WHERE q.rn <= %(per_meeting)s"
    " ORDER BY q.occurred_at, q.meeting_id, q.moment_id"
)

# The sample leg's twin of the two queries above, over the moment ids the
# index ranked. Meilisearch ranks and Postgres cites (AD-2/AD-6): not one
# field below comes from the index, and a ranked moment Postgres no longer
# holds simply does not appear.
_SAMPLE_STOPS = (
    "SELECT mo.meeting_id, mt.title, mt.corpus, mt.has_recording,"
    " mt.started_at_precision, COUNT(*), COUNT(*),"
    f" MIN({_occurred_at_sql('mo.start_ms')}),"
    f" MAX({_occurred_at_sql('mo.start_ms')})"
    " FROM moment mo JOIN meeting mt ON mt.id = mo.meeting_id"
    " WHERE mo.id = ANY(%(moment_ids)s)"
    " AND COALESCE(mo.provenance->>'superseded', '') <> 'true'"
    " GROUP BY mo.meeting_id, mt.title, mt.corpus, mt.has_recording,"
    " mt.started_at_precision"
    f" ORDER BY MIN({_occurred_at_sql('mo.start_ms')}), mo.meeting_id"
)

_SAMPLE_MOMENTS = (
    "SELECT q.moment_id, q.meeting_id, q.start_ms, q.screenshot_id,"
    " q.occurred_at, q.precision FROM ("
    " SELECT mo.id AS moment_id, mo.meeting_id, mo.start_ms, mo.screenshot_id,"
    " mt.started_at_precision AS precision,"
    f" {_occurred_at_sql('mo.start_ms')} AS occurred_at,"
    " ROW_NUMBER() OVER (PARTITION BY mo.meeting_id"
    " ORDER BY mo.start_ms, mo.id) AS rn"
    " FROM moment mo JOIN meeting mt ON mt.id = mo.meeting_id"
    " WHERE mo.id = ANY(%(moment_ids)s)"
    " AND COALESCE(mo.provenance->>'superseded', '') <> 'true'"
    ") q WHERE q.rn <= %(per_meeting)s"
    " ORDER BY q.occurred_at, q.meeting_id, q.moment_id"
)

# The subjects that co-occur with what is on screen, so a trace leads
# somewhere instead of dead-ending. Keyed on the moments actually quoted, so
# what is offered is adjacent to what the reader can see rather than to the
# subject in the abstract.
_TRACE_RELATED = (
    "SELECT th.id, th.name, th.color_ordinal, COUNT(DISTINCT tm.moment_id)"
    " FROM topic_mention tm"
    " JOIN topic_thread tt ON tt.topic_id = tm.topic_id"
    " JOIN thread th ON th.id = tt.thread_id"
    " WHERE tm.moment_id = ANY(%(moment_ids)s)"
    " AND (%(exclude_thread)s::uuid IS NULL OR th.id <> %(exclude_thread)s::uuid)"
    " GROUP BY th.id, th.name, th.color_ordinal"
    " ORDER BY COUNT(DISTINCT tm.moment_id) DESC, th.id"
    " LIMIT %(limit)s"
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


# --- story 10.7 wire models ------------------------------------------------


class SubjectReach(_Camel):
    """How far a subject runs, which is the whole basis for offering it.

    Both numbers are shown to the reader rather than only ranked on: "9
    meetings over 118 days" is what makes a suggestion a considered choice
    instead of a button whose label is the only thing known about it.
    """

    meeting_count: int
    span_days: int
    first_mention_at: str
    last_mention_at: str


class SuggestedSubject(_Camel):
    thread_id: UUID
    name: str
    color_ordinal: int
    mention_count: int
    reach: SubjectReach


class SuggestionsResponse(_Camel):
    """The empty state's offer, with the band it was drawn from.

    The band travels with the answer because an empty list means something
    specific — no subject in this corpus recurs across meetings for long enough
    to be worth tracing — and a client that cannot see the bounds would have to
    render that as a blank.
    """

    subjects: list[SuggestedSubject]
    min_meetings: int
    max_meetings: int
    min_span_days: int


class SubjectCandidate(_Camel):
    """An adjacent subject the typed wording could have meant."""

    thread_id: UUID
    name: str
    color_ordinal: int
    meeting_count: int
    span_days: int


class TraceMoment(_Camel):
    """One quoted moment at a stop."""

    moment_id: UUID
    start_ms: int
    occurred_at: str
    occurred_at_precision: str
    # Only `resolved` speaker labels, in first-appearance order (migration
    # 0005): the other three resolutions are not names and a timeline may not
    # print them as though they were.
    speakers: list[str]
    excerpt: str | None = None
    # Opaque (AD-17). NULL on a transcript-only meeting, or on a moment past
    # the last capture — the two are not distinguishable here and are not
    # reported as though they were.
    screenshot_id: UUID | None = None


class TraceStop(_Camel):
    """One meeting where the subject surfaced.

    `mentionCount` and `momentCount` describe the meeting; `quotedCount` is how
    many of them are carried in `moments`. The three are all present so a
    reader is never shown six moments from a meeting that held forty without
    being told which they are looking at.

    `hasRecording` and `screenCount` are carried as facts rather than as a
    rendered sentence about them: a stop with no screens must state its reason,
    and the reason turns on whether the absence was established (transcript-only
    ingest) or merely observed (no capture covers these moments). A client that
    derived the state from the presence of prose would be one wording change
    away from claiming the wrong one (AD-18).
    """

    meeting_id: UUID
    title: str | None = None
    corpus: str
    has_recording: bool
    occurred_at: str
    last_occurred_at: str
    occurred_at_precision: str
    mention_count: int
    moment_count: int
    quoted_count: int
    screen_count: int
    moments: list[TraceMoment]


class TraceSpan(_Camel):
    from_at: str
    to_at: str
    days: int
    meetings: int


class TraceCounts(_Camel):
    stops: int
    moments_quoted: int
    mention_total: int
    meetings_mentioning: int
    with_screen: int


class RelatedSubject(_Camel):
    thread_id: UUID
    name: str
    color_ordinal: int
    shared_moments: int


class ThreadTrace(_Camel):
    """One subject, traced across every meeting where it surfaced.

    **`mode` is the closed set; `completenessNote` is the prose.** Both are
    carried because a client that inferred completeness from the wording would
    be one edit away from presenting a sample as a full history — the same
    unverified-absence failure as claiming no recording exists, in the one view
    whose entire claim is that it shows the corpus's true shape (AD-18).
    """

    mode: Literal["exhaustive", "sample"]
    label: str
    # Present on the exhaustive leg only: a sample is not a thread and has no
    # identity to carry, and inventing one would make it linkable as though it
    # were a derived subject.
    thread_id: UUID | None = None
    color_ordinal: int | None = None
    # Set when a typed phrase was answered as a named subject, so the view is
    # never quietly showing something other than what was asked for.
    resolved_from: str | None = None
    # `keyword` or `hybrid` on the sample leg; NULL on the exhaustive leg,
    # which does not rank at all.
    ranking: Literal["hybrid", "keyword"] | None = None
    complete: bool
    completeness_note: str
    per_meeting_limit: int
    span: TraceSpan | None = None
    counts: TraceCounts
    # Offered on the sample leg so an ambiguous wording is disambiguated by the
    # reader rather than guessed at here.
    candidates: list[SubjectCandidate]
    related_subjects: list[RelatedSubject]
    stops: list[TraceStop]


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


_TRACE_PROBLEMS: dict[int | str, dict[str, Any]] = {
    400: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`invalid-request` — neither `q` nor `threadId` was given.",
    },
    404: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`not-found` — no thread with that id.",
    },
    503: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`thread-trace-store-unavailable`,"
        " `thread-trace-store-unusable` or `embedder-unusable` — the sample leg"
        " could not be served, and is refused rather than degraded to silence.",
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


def _rank_sample(
    request: Request, phrase: str, limit: int
) -> tuple[tuple[UUID, ...], Literal["hybrid", "keyword"]]:
    """Rank the moments index for a wording and return the ids, in rank order.

    The two embedder failures get two answers, exactly as `GET /search` gives
    them: an unavailable host degrades to keyword and *says so* in the response
    (`ranking`) as well as in the log, because keyword-only is a good answer
    rather than a broken one; a model that answers wrongly is a configuration
    error no retry fixes and is refused by name. A degraded search that looked
    identical to a healthy one would be an AD-18 violation in the view whose
    whole job is to be honest about what it is showing.
    """
    config = request.app.state.config
    ranking: Literal["hybrid", "keyword"] = "keyword"
    query_vector = None
    if config.settings.api.search.semantic_ratio != 0.0:
        embedder = request.app.state.embedder
        try:
            query_vector = embedder.embed_query(phrase)
            ranking = "hybrid"
        except EmbedderUnavailableError as exc:
            logs.log_event(
                "threads.trace_degraded",
                reason="embedder_unavailable",
                model=getattr(embedder, "model", None),
                detail=str(exc),
            )
        except EmbedderError as exc:
            raise Problem(
                503,
                "embedder-unusable",
                f"the configured embedder {getattr(embedder, 'model', 'unknown')!r}"
                f" could not embed the subject: {exc}",
                title="Service Unavailable",
                model=getattr(embedder, "model", None),
            ) from exc

    try:
        client = meili_client(config)
        result = search_moments(
            client, config, query=phrase, limit=limit, query_vector=query_vector
        )
    except StoreUnavailableError as exc:
        raise Problem(
            503,
            "thread-trace-store-unavailable",
            f"the search index could not be reached: {exc}",
            title="Service Unavailable",
            store="meilisearch",
        ) from exc
    except ProjectionError as exc:
        # `StoreUnavailableError` is a subclass, so this clause must stay after
        # it or every outage would be reported under the wrong slug.
        raise Problem(
            503,
            "thread-trace-store-unusable",
            f"the search index could not be queried: {exc}",
            title="Service Unavailable",
            store="meilisearch",
        ) from exc

    if result.index_missing:
        logs.log_event("threads.trace_index_missing", subject=phrase)
    return tuple(hit.moment_id for hit in result.hits), ranking


def _assemble_trace(
    conn: Any,
    *,
    mode: Literal["exhaustive", "sample"],
    label: str,
    thread_id: UUID | None,
    color_ordinal: int | None,
    stop_rows: list[tuple],
    moment_rows: list[tuple],
    per_meeting: int,
    resolved_from: str | None,
    ranking: Literal["hybrid", "keyword"] | None,
    candidates: list[SubjectCandidate],
) -> ThreadTrace:
    """Both legs converge here: same stops, same counts, same sentence.

    The two legs differ only in which rows they arrived with. Assembling them
    through one function is what keeps the sample from acquiring the
    exhaustive leg's vocabulary by accident — the counts and the note are
    computed once, from the rows actually present.

    Stops are ordered by time and never by relevance. Ranking order is what the
    sample leg was given and it is deliberately discarded here: relevance order
    destroys exactly the sequence this view exists to show.
    """
    moment_ids = [row[0] for row in moment_rows]
    lookup = {"moment_ids": moment_ids}
    speakers = (
        _group(conn.execute(_MOMENT_SPEAKERS, lookup).fetchall()) if moment_ids else {}
    )
    excerpts = (
        dict(conn.execute(_MOMENT_EXCERPTS, lookup).fetchall()) if moment_ids else {}
    )
    related_rows = (
        conn.execute(
            _TRACE_RELATED,
            {
                "moment_ids": moment_ids,
                "exclude_thread": thread_id,
                "limit": _RELATED_LIMIT,
            },
        ).fetchall()
        if moment_ids
        else []
    )

    quoted: dict[UUID, list[TraceMoment]] = {}
    for (
        moment_id,
        meeting_id,
        start_ms,
        screenshot_id,
        occurred,
        precision,
    ) in moment_rows:
        quoted.setdefault(meeting_id, []).append(
            TraceMoment(
                moment_id=moment_id,
                start_ms=start_ms,
                occurred_at=format_rfc3339(occurred),
                occurred_at_precision=precision,
                speakers=[label_ for label_, _ in speakers.get(moment_id, [])],
                excerpt=excerpts.get(moment_id),
                screenshot_id=screenshot_id,
            )
        )

    stops: list[TraceStop] = []
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
    ) in stop_rows:
        moments = quoted.get(meeting_id, [])
        stops.append(
            TraceStop(
                meeting_id=meeting_id,
                title=title,
                corpus=corpus,
                has_recording=has_recording,
                occurred_at=format_rfc3339(first_at),
                last_occurred_at=format_rfc3339(last_at),
                occurred_at_precision=precision,
                mention_count=mention_count,
                moment_count=moment_count,
                quoted_count=len(moments),
                screen_count=sum(1 for m in moments if m.screenshot_id is not None),
                moments=moments,
            )
        )

    moments_quoted = sum(stop.quoted_count for stop in stops)
    mention_total = sum(stop.mention_count for stop in stops)
    with_screen = sum(stop.screen_count for stop in stops)
    complete = mode == "exhaustive" and moments_quoted >= mention_total

    span = None
    if stop_rows:
        first = stop_rows[0][7]
        last = max(row[8] for row in stop_rows)
        span = TraceSpan(
            from_at=format_rfc3339(first),
            to_at=format_rfc3339(last),
            days=span_days(first, last),
            meetings=len(stops),
        )

    return ThreadTrace(
        mode=mode,
        label=label,
        thread_id=thread_id,
        color_ordinal=color_ordinal,
        resolved_from=resolved_from,
        ranking=ranking,
        complete=complete,
        completeness_note=completeness_note(
            mode=mode,
            stops=len(stops),
            moments_quoted=moments_quoted,
            mention_total=mention_total,
            meetings_mentioning=len(stops),
            per_meeting=per_meeting,
            ranking=ranking,
        ),
        per_meeting_limit=per_meeting,
        span=span,
        counts=TraceCounts(
            stops=len(stops),
            moments_quoted=moments_quoted,
            mention_total=mention_total,
            meetings_mentioning=len(stops),
            with_screen=with_screen,
        ),
        candidates=candidates,
        related_subjects=[
            RelatedSubject(
                thread_id=related_id,
                name=related_name,
                color_ordinal=ordinal,
                shared_moments=shared,
            )
            for related_id, related_name, ordinal, shared in related_rows
        ],
        stops=stops,
    )


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
    "/threads/suggestions",
    operation_id="listThreadSuggestions",
    response_model=SuggestionsResponse,
)
def list_thread_suggestions(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=24)] = SUGGESTION_LIMIT_DEFAULT,
    min_meetings: Annotated[
        int, Query(alias="minMeetings", ge=1)
    ] = SUGGESTION_MIN_MEETINGS,
    max_meetings: Annotated[
        int, Query(alias="maxMeetings", ge=1)
    ] = SUGGESTION_MAX_MEETINGS,
    min_span_days: Annotated[
        int, Query(alias="minSpanDays", ge=0)
    ] = SUGGESTION_MIN_SPAN_DAYS,
) -> SuggestionsResponse:
    """Subjects worth tracing, for the view's empty state.

    Not the most-mentioned subjects. Those are the generic ones — they appear
    in nearly every meeting, so their thread is the whole corpus and no story
    at all. What is offered instead is the subjects that recur across a
    middling number of meetings, ranked by how much calendar time they span,
    with near-duplicates dropped so one concern does not consume two slots.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        rows = conn.execute(
            _SUGGESTIONS,
            {
                "min_meetings": min_meetings,
                "max_meetings": max_meetings,
                "min_span_days": min_span_days,
                "scan": _SUGGESTION_SCAN,
            },
        ).fetchall()

    keep = drop_near_duplicates([row[1] for row in rows], limit=limit)
    subjects = []
    for index in keep:
        thread_id, name, color_ordinal, meetings, mentions, first_at, last_at = rows[
            index
        ]
        subjects.append(
            SuggestedSubject(
                thread_id=thread_id,
                name=name,
                color_ordinal=color_ordinal,
                mention_count=mentions,
                reach=SubjectReach(
                    meeting_count=meetings,
                    span_days=span_days(first_at, last_at),
                    first_mention_at=format_rfc3339(first_at),
                    last_mention_at=format_rfc3339(last_at),
                ),
            )
        )
    return SuggestionsResponse(
        subjects=subjects,
        min_meetings=min_meetings,
        max_meetings=max_meetings,
        min_span_days=min_span_days,
    )


@router.get(
    "/threads/trace",
    operation_id="traceThread",
    response_model=ThreadTrace,
    responses=_TRACE_PROBLEMS,
)
def trace_thread(
    request: Request,
    q: Annotated[str | None, Query(max_length=120)] = None,
    thread_id: Annotated[UUID | None, Query(alias="threadId")] = None,
    per_meeting: Annotated[
        int, Query(alias="perMeeting", ge=1, le=50)
    ] = PER_MEETING_DEFAULT,
    limit: Annotated[int, Query(ge=1, le=200)] = _SAMPLE_LIMIT_DEFAULT,
) -> ThreadTrace:
    """One subject across every meeting where it surfaced.

    **Two ways in, and the answer says which one it took.** A `threadId`, or a
    phrase that plainly names one known subject, walks the stored mentions and
    is exhaustive within the corpus. Anything else is a top-k retrieval sample,
    ranked by relevance and then re-sorted by time, carrying the adjacent
    subjects the wording could have meant so the reader disambiguates rather
    than this route guessing.

    The whole trace is served once, at every altitude the client will draw it
    at. It is deliberately not `GET /threads/{threadId}/timeline`: that
    endpoint answers one level of detail per request, which a semantic zoom
    cannot use without the view flickering between tiers it has not fetched.
    """
    phrase = (q or "").strip()
    if thread_id is None and not phrase:
        raise Problem(
            400,
            "invalid-request",
            "name a subject with `q`, or trace a known one with `threadId`",
        )

    pool = request.app.state.pool
    resolved_from: str | None = None
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if thread_id is None:
            # Exact and unambiguous only. Two subjects that both answer to this
            # wording are two different questions, and picking one would make
            # the exhaustive leg's claim about the other silently false.
            matches = conn.execute(
                _EXACT_SUBJECT, {"phrase": phrase.lower()}
            ).fetchall()
            if len(matches) == 1:
                thread_id = matches[0][0]
                resolved_from = phrase
        if thread_id is not None:
            row = conn.execute(_THREAD_ROW, {"thread_id": thread_id}).fetchone()
            if row is None:
                raise Problem(404, "not-found", f"no thread with id {thread_id}")
            _, name, color_ordinal = row
            stop_rows = conn.execute(
                _TRACE_STOPS, {"thread_id": thread_id}
            ).fetchall()
            moment_rows = conn.execute(
                _TRACE_MOMENTS,
                {"thread_id": thread_id, "per_meeting": per_meeting},
            ).fetchall()
            return _assemble_trace(
                conn,
                mode="exhaustive",
                label=name,
                thread_id=thread_id,
                color_ordinal=color_ordinal,
                stop_rows=stop_rows,
                moment_rows=moment_rows,
                per_meeting=per_meeting,
                resolved_from=resolved_from,
                ranking=None,
                candidates=[],
            )

    # The sample leg. The index is queried outside any open transaction: a
    # `REPEATABLE READ` snapshot held across a call to another service would
    # hold a Postgres transaction open for the length of a network round trip.
    ranked, ranking = _rank_sample(request, phrase, limit)

    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        candidate_rows = conn.execute(
            _CANDIDATES, {"like": f"%{phrase}%", "limit": CANDIDATE_LIMIT}
        ).fetchall()
        moment_ids = list(ranked)
        stop_rows = (
            conn.execute(_SAMPLE_STOPS, {"moment_ids": moment_ids}).fetchall()
            if moment_ids
            else []
        )
        moment_rows = (
            conn.execute(
                _SAMPLE_MOMENTS,
                {"moment_ids": moment_ids, "per_meeting": per_meeting},
            ).fetchall()
            if moment_ids
            else []
        )
        return _assemble_trace(
            conn,
            mode="sample",
            label=phrase,
            thread_id=None,
            color_ordinal=None,
            stop_rows=stop_rows,
            moment_rows=moment_rows,
            per_meeting=per_meeting,
            resolved_from=None,
            ranking=ranking,
            candidates=[
                SubjectCandidate(
                    thread_id=candidate_id,
                    name=candidate_name,
                    color_ordinal=ordinal,
                    meeting_count=meetings,
                    span_days=span_days(first_at, last_at),
                )
                for (
                    candidate_id,
                    candidate_name,
                    ordinal,
                    meetings,
                    first_at,
                    last_at,
                ) in candidate_rows
            ],
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
