"""Wall-clock derivation and band bucketing for the thread timeline (story 10.3).

Pure, store-free, and deliberately separate from ``api/threads.py``: these are
the three decisions the timeline rests on, and each is a rule a client must not
re-derive for itself.

**The wall clock is the server's answer, not the client's.** A timeline item is
anchored by a meeting-relative ``startMs``; its instant is the meeting's start
plus that offset. A client cannot compute it, because the meeting's own
precision changes the anchor: when the source declared only a date, the anchor
is that date at ``00:00:00Z`` — whatever time of day the stored timestamp
happens to carry — and the derived instant stays labelled ``day`` so nothing
downstream renders it as if it were timed to the second.

**Ties are broken the same way everywhere.** Two moments in two meetings can
land on the same instant, and a list that orders them differently on two
requests makes a timeline flicker. The chain is ``occurredAt``, then
``meetingId``, then ``momentId`` — declared once, here.

**The band's bucket width comes from a ladder, so its size is bounded by the
ladder rather than by the window.** A ten-year window and a one-hour window
both return at most :data:`TARGET_BUCKETS` rows. That bound is half of what
makes the coarse levels cheap; the other half is the query shape in
``api/threads.py``, which aggregates over mentions and never joins ``moment``.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

# The four tiers, in zoom order. The api's `level` parameter is this tuple and
# nothing else; an unlisted value is refused before any query runs.
Level = Literal["bands", "meetings", "moments", "evidence"]
LEVELS: tuple[Level, ...] = ("bands", "meetings", "moments", "evidence")

# The two that must never join `moment`. Named here rather than inferred from
# the tuple's first two entries, so the query-shape test asserts against a
# declaration rather than against an index.
COARSE_LEVELS: tuple[Level, ...] = ("bands", "meetings")

# The precisions `meeting.started_at_precision` may carry (migration 0002),
# carried through onto every derived instant as `occurredAtPrecision`.
DAY_PRECISION = "day"
SECOND_PRECISION = "second"

_MS = 1000
_MINUTE = 60 * _MS
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR

# The widths a band may use, smallest first. Chosen so every step is a unit a
# person reads off an axis — a minute, a quarter hour, an hour, a day, a week,
# four weeks, a quarter, a year — rather than an arbitrary window/N division
# that would relabel the axis on every pan.
BUCKET_LADDER_MS: tuple[int, ...] = (
    _MINUTE,
    5 * _MINUTE,
    15 * _MINUTE,
    _HOUR,
    6 * _HOUR,
    _DAY,
    7 * _DAY,
    28 * _DAY,
    91 * _DAY,
    365 * _DAY,
)

# The most buckets a band response may carry. A band is a density strip a few
# hundred pixels wide, so more buckets than this render as sub-pixel noise
# while making the response, and the GROUP BY behind it, larger for nothing.
TARGET_BUCKETS = 120


def occurred_at(
    meeting_started_at: datetime, precision: str, start_ms: int
) -> datetime:
    """The canonical UTC instant of an item ``start_ms`` into its meeting.

    ``precision`` is the *meeting's* ``started_at_precision``. At ``day`` the
    stored timestamp is only trustworthy to its date, so the anchor is that
    date at midnight UTC before the offset is added; a stored time of day is
    discarded rather than propagated as if it had been observed.
    """
    anchor = meeting_started_at.astimezone(timezone.utc)
    if precision == DAY_PRECISION:
        anchor = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    return anchor + timedelta(milliseconds=start_ms)


def format_rfc3339(value: datetime) -> str:
    """RFC 3339 UTC with a literal ``Z``, milliseconds only when non-zero.

    Written here rather than left to the serializer so the wire form is a
    decision of this story rather than a property of whichever library version
    is installed. Sub-millisecond precision is dropped: every instant on this
    timeline is derived from an integer-millisecond offset, so a microsecond
    tail could only be noise from the stored meeting start.
    """
    utc = value.astimezone(timezone.utc)
    milliseconds = utc.microsecond // 1000
    stem = utc.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stem}.{milliseconds:03d}Z" if milliseconds else f"{stem}Z"


def timeline_sort_key(
    occurred: datetime, meeting_id: UUID, moment_id: UUID
) -> tuple[datetime, str, str]:
    """The one ordering every level uses: instant, then meeting, then moment.

    The ids compare as strings so the key matches Postgres's ``ORDER BY`` on
    ``uuid`` columns for the ids this project mints: UUIDv7 text order is its
    byte order, and the api and the database must not disagree about which of
    two equal-anchor rows comes first.
    """
    return (occurred, str(meeting_id), str(moment_id))


def plan_buckets(window_from: datetime, window_to: datetime) -> tuple[int, int]:
    """``(bucket_ms, bucket_count)`` for an inclusive ``[from, to]`` window.

    The ladder step chosen is the smallest whose count fits
    :data:`TARGET_BUCKETS`. A window too wide for even the largest step falls
    back to an even division at the target count, so the response is bounded
    for any window a client can name — a band is never allowed to grow with
    the corpus.

    Raises ``ValueError`` on an inverted window: the caller answers that as a
    named refusal, and a silently swapped pair would return a band for a
    window nobody asked for.
    """
    if window_to < window_from:
        raise ValueError(
            f"window start {format_rfc3339(window_from)} is after window end"
            f" {format_rfc3339(window_to)}"
        )
    # Inclusive on both ends, so a zero-length window still spans one
    # millisecond and yields exactly one bucket rather than zero.
    span_ms = int((window_to - window_from).total_seconds() * _MS) + 1
    for step in BUCKET_LADDER_MS:
        if math.ceil(span_ms / step) <= TARGET_BUCKETS:
            return step, max(1, math.ceil(span_ms / step))
    bucket_ms = math.ceil(span_ms / TARGET_BUCKETS)
    return bucket_ms, max(1, math.ceil(span_ms / bucket_ms))


def bucket_index(
    occurred: datetime, window_from: datetime, bucket_ms: int, bucket_count: int
) -> int:
    """Which band bucket an instant falls in, clamped into the band.

    Buckets are half-open ``[start, start + bucket_ms)`` except the last, which
    is closed so an item landing exactly on ``to`` is counted rather than
    dropped off the end of its own window.
    """
    offset_ms = int((occurred - window_from).total_seconds() * _MS)
    return max(0, min(bucket_count - 1, offset_ms // bucket_ms))
