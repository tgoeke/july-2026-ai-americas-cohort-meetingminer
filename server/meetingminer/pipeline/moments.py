"""The `moments` stage's decision logic, with no database and no model call.

Where the meeting timeline is cut, which transcript segments each span covers,
which screenshot was on display when it started, and what each span's identity
key is — all pure functions over plain facts, so every rule is unit-testable
without Postgres and none of them can quietly become a model call (AD-13).
Every threshold arrives as :class:`~meetingminer.config.MomentsConfig`, never
as a constant here (AD-10).

The shape that matters is the **union**, computed in two independent passes:

* transcript boundaries come from the transcript segments alone;
* screenshot boundaries come from the screenshots alone;
* the two sets are then unioned, never interleaved during computation.

That is what makes a transcript boundary identical before and after a recording
arrives (story 1.12). A pre-existing moment keeps its start — and therefore its
identity key and its Postgres-minted id — gets shorter, and the tail it gave up
becomes a new screen-anchored moment. Interleaving the two sets during
computation would shift the transcript boundaries when video arrived and re-key
every citation minted before augmentation, which the SPEC forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from meetingminer.config import MomentsConfig

# Why a boundary exists, recorded on `moment.provenance.boundary`.
BOUNDARY_FIRST_SEGMENT = "first-segment"
BOUNDARY_SILENCE_GAP = "silence-gap"
BOUNDARY_MAX_DURATION = "max-duration"
BOUNDARY_SCREENSHOT = "screenshot"
BOUNDARY_REASONS = (
    BOUNDARY_FIRST_SEGMENT,
    BOUNDARY_SILENCE_GAP,
    BOUNDARY_MAX_DURATION,
    BOUNDARY_SCREENSHOT,
)

# What produced the span, recorded on `moment.derived_from`.
DERIVED_TRANSCRIPT = "transcript"
DERIVED_SCREEN = "screen"
DERIVED_BOTH = "both"


@dataclass(frozen=True)
class SegmentFacts:
    """One `transcript_segment` row as the planner sees it.

    ``ordinal`` is carried, not derived: two turns can share a ``start_ms``
    (second-precision transcripts round), and transcript order is the only
    correct tiebreak between them. Sorting such a pair by anything else — a
    UUID's text, say — would hand them to the planner in an order the
    transcript never had.
    """

    segment_id: UUID
    ordinal: int
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class ScreenshotFacts:
    """One `screenshot` row as the planner sees it.

    Screenshot spans are ``[first frame offset, last frame offset]`` and are
    disjoint and ordered — ``screens.segment_captures`` gives each frame to
    exactly one capture — which is what makes "the screenshot on display at
    this moment's start" single-valued.
    """

    screenshot_id: UUID
    start_offset_ms: int
    end_offset_ms: int


@dataclass(frozen=True)
class Boundary:
    """A cut in the meeting timeline: where it is and why it is there."""

    start_ms: int
    reason: str


@dataclass(frozen=True)
class PlannedMoment:
    """One span, ready to be written as a `moment` row."""

    identity_key: str
    derived_from: str
    start_ms: int
    end_ms: int
    boundary: str
    screenshot_id: UUID | None
    segment_ids: tuple[UUID, ...]

    @property
    def segment_count(self) -> int:
        return len(self.segment_ids)


def identity_key_for(derived_from: str, start_ms: int) -> str:
    """The key ``(meeting_id, identity_key)`` idempotence upserts on.

    A span the transcript anchors — including a coincident ``both`` span — is
    keyed on the transcript anchor, because that anchor is what survives a
    recording arriving later. Only a span that exists *solely* because a
    screenshot did takes a ``screen:`` key, which is also what makes it the one
    kind of moment a rerun may delete.
    """
    prefix = DERIVED_SCREEN if derived_from == DERIVED_SCREEN else DERIVED_TRANSCRIPT
    return f"{prefix}:{start_ms}"


def transcript_boundaries(
    segments: Sequence[SegmentFacts], config: MomentsConfig
) -> tuple[Boundary, ...]:
    """Where the transcript alone says a new moment starts.

    Three reasons, tested in that order for each turn after the first: the
    first segment opens the first moment; a turn starting more than
    ``gap_seconds`` after the *previous turn's start* opens one (start-to-start,
    because `align` synthesizes a turn's end as the next turn's start, so
    end-to-start gaps are zero almost everywhere and carry no signal); and a
    turn starting more than ``max_duration_ms`` after the *current block's*
    start opens one, capping an unbroken stretch of talk.

    Reads ``segments`` and nothing else, so adding screenshots to a meeting
    cannot move a single boundary this returns.
    """
    ordered = sorted(segments, key=lambda segment: (segment.start_ms, segment.ordinal))
    if not ordered:
        return ()

    gap_ms = config.gap_seconds * 1000.0
    boundaries = [Boundary(ordered[0].start_ms, BOUNDARY_FIRST_SEGMENT)]
    block_start = previous_start = ordered[0].start_ms
    for segment in ordered[1:]:
        if segment.start_ms - previous_start > gap_ms:
            reason = BOUNDARY_SILENCE_GAP
        elif segment.start_ms - block_start > config.max_duration_ms:
            reason = BOUNDARY_MAX_DURATION
        else:
            previous_start = segment.start_ms
            continue
        # Two turns sharing a start cannot open two moments; the earlier
        # boundary already covers the offset.
        if segment.start_ms != boundaries[-1].start_ms:
            boundaries.append(Boundary(segment.start_ms, reason))
        block_start = segment.start_ms
        previous_start = segment.start_ms
    return tuple(boundaries)


def screenshot_boundaries(
    screenshots: Sequence[ScreenshotFacts],
) -> tuple[Boundary, ...]:
    """Where the screenshots alone say a new moment starts: one per capture.

    Reads ``screenshots`` and nothing else, the mirror of
    :func:`transcript_boundaries`.
    """
    starts = sorted({shot.start_offset_ms for shot in screenshots})
    return tuple(Boundary(start, BOUNDARY_SCREENSHOT) for start in starts)


def _union(
    transcript: Sequence[Boundary], screen: Sequence[Boundary]
) -> list[tuple[Boundary, str]]:
    """Merge the two independently computed sets into ordered spans.

    A coincident pair collapses to one span tagged ``both`` and carrying the
    *transcript* boundary's reason — the transcript anchor is what the identity
    key is built from, so the screenshot must not displace it.
    """
    by_start: dict[int, tuple[Boundary, str]] = {}
    for boundary in transcript:
        by_start[boundary.start_ms] = (boundary, DERIVED_TRANSCRIPT)
    for boundary in screen:
        existing = by_start.get(boundary.start_ms)
        if existing is None:
            by_start[boundary.start_ms] = (boundary, DERIVED_SCREEN)
        else:
            by_start[boundary.start_ms] = (existing[0], DERIVED_BOTH)
    return [by_start[start] for start in sorted(by_start)]


def plan_moments(
    segments: Sequence[SegmentFacts],
    screenshots: Sequence[ScreenshotFacts],
    config: MomentsConfig,
) -> tuple[PlannedMoment, ...]:
    """The full set of spans for one meeting, in start order.

    Each span runs to the next span's start; the last one closes at
    ``max(last segment end, last screenshot end)``, which is the furthest point
    either kind of evidence reaches — never past it, and never before its own
    start.

    A segment belongs to the span its ``start_ms`` falls in, so every segment
    is covered exactly once.

    **A covered segment may end after its moment does, deliberately.** Spans
    tile the timeline contiguously and a segment is assigned by its *start*,
    while `align` synthesizes a turn's end as the next turn's start capped at
    ``max_segment_ms``. A turn that begins just before a boundary therefore
    overhangs it. The alternative — stretching a moment to its last segment's
    end — would make spans overlap, and overlapping spans cannot answer "which
    moment covers this instant" single-valuedly, which is what a citation
    target has to do. The overhang is the accepted cost of a clean tiling.

    The screenshot named is the one with the greatest ``start_offset_ms`` at or
    before the span's start — "on display at this moment's start" over disjoint,
    ordered captures — **except past the end of the last capture**. A
    transcript routinely outruns its recording in this corpus, and a moment
    starting after the final capture ended has no screenshot on display at all,
    so it takes ``None`` rather than inheriting the last one. The small gaps
    *between* consecutive captures are sampling artifacts, not blank screen, so
    a capture is still carried forward across those.
    """
    ordered_segments = sorted(
        segments, key=lambda segment: (segment.start_ms, segment.ordinal)
    )
    ordered_shots = sorted(
        screenshots, key=lambda shot: (shot.start_offset_ms, shot.end_offset_ms)
    )
    spans = _union(
        transcript_boundaries(ordered_segments, config),
        screenshot_boundaries(ordered_shots),
    )
    if not spans:
        return ()

    last_end = max(
        [segment.end_ms for segment in ordered_segments]
        + [shot.end_offset_ms for shot in ordered_shots]
    )
    # Past this point the recording had nothing on screen to show, so no
    # capture may be carried forward (see the docstring).
    last_capture_end = max(
        (shot.end_offset_ms for shot in ordered_shots), default=-1
    )

    covered: list[list[UUID]] = [[] for _ in spans]
    starts = [boundary.start_ms for boundary, _ in spans]
    index = 0
    for segment in ordered_segments:
        while index + 1 < len(starts) and starts[index + 1] <= segment.start_ms:
            index += 1
        covered[index].append(segment.segment_id)

    planned: list[PlannedMoment] = []
    for position, (boundary, derived_from) in enumerate(spans):
        if position + 1 < len(spans):
            end_ms = starts[position + 1]
        else:
            # Never before its own start: a screenshot-only meeting whose last
            # capture is a single frame still yields a zero-length span rather
            # than one the CHECK constraint would reject.
            end_ms = max(last_end, boundary.start_ms)
        on_display = None
        if boundary.start_ms <= last_capture_end:
            for shot in ordered_shots:
                if shot.start_offset_ms <= boundary.start_ms:
                    on_display = shot.screenshot_id
                else:
                    break
        planned.append(
            PlannedMoment(
                identity_key=identity_key_for(derived_from, boundary.start_ms),
                derived_from=derived_from,
                start_ms=boundary.start_ms,
                end_ms=end_ms,
                boundary=boundary.reason,
                screenshot_id=on_display,
                segment_ids=tuple(covered[position]),
            )
        )
    return tuple(planned)


def boundary_counts(planned: Sequence[PlannedMoment]) -> dict[str, int]:
    """How many moments each boundary reason produced, for the stage log.

    Zero-valued keys are kept: a run that cut nothing on silence should say so
    rather than being indistinguishable from a run whose gap rule stopped
    working.
    """
    counts = {reason: 0 for reason in BOUNDARY_REASONS}
    for moment in planned:
        counts[moment.boundary] = counts.get(moment.boundary, 0) + 1
    return counts
