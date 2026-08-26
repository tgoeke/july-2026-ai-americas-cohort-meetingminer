"""Reconciling a provided transcript against the STT verification lane.

Pure functions over segment lists and an :class:`~meetingminer.config.AlignConfig`:
no database, no engine, no model call. Alignment is deterministic code output,
which is what lets the Epic 5 harness score it and what keeps AD-13's
"evidence is never model-written" true of timing as well as text.

The precedence AD-13 fixes, concretely:

* **Speaker labels and text** come from the speaker-attributed ``.txt``.
* **End timings** come from the VTT where a cue matches, because the ``.txt``
  records only a start per turn; otherwise a turn ends where the next begins,
  capped at ``max_segment_ms``.
* **The STT lane is the anchor, not a source of text.** ``alignment_delta_ms``
  is the signed offset between the provided start and the matched STT start. A
  candidate outside the anchor window, or scoring below ``min_match_score``, is
  left unmatched — never snapped to the nearest segment, because a fabricated
  offset would be indistinguishable from a verified one.

No file is ever picked wholesale, and two raw sources are never merged into one
raw source: the output is a per-segment match record the caller writes onto new
derived rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from meetingminer.config import AlignConfig
from meetingminer.pipeline.screens import jaccard, normalize_text, tokens


@dataclass(frozen=True)
class TimedText:
    """The aligner's view of one segment from either lane."""

    start_ms: int
    end_ms: int | None
    text: str

    @property
    def token_set(self) -> frozenset[str]:
        return tokens(normalize_text(self.text))


@dataclass(frozen=True)
class AlignmentMatch:
    """What one provided segment anchored to, or that it anchored to nothing.

    All four fields are ``None`` together on an unmatched segment: the schema's
    CHECK constraint enforces the same all-or-nothing rule on the row.
    """

    stt_index: int | None = None
    stt_start_ms: int | None = None
    delta_ms: int | None = None
    match_score: float | None = None

    @property
    def matched(self) -> bool:
        return self.stt_index is not None


def align_segments(
    provided: Sequence[TimedText],
    stt: Sequence[TimedText],
    config: AlignConfig,
) -> tuple[AlignmentMatch, ...]:
    """Anchor each provided segment to an STT segment, or to nothing.

    Candidates are limited to the anchor window around the provided start, then
    scored by token overlap; the best score wins, ties broken by the smallest
    absolute delta and then the lowest index so the result is stable. An STT
    segment may anchor more than one provided turn: recognizer segmentation and
    turn segmentation genuinely disagree, and refusing reuse would leave real
    turns unverified to preserve a one-to-one relation nothing needs.
    """
    window_ms = round(config.anchor_window_seconds * 1000)
    matches: list[AlignmentMatch] = []
    # The linear cursor below only ever moves forward, which is what keeps this
    # O(n) instead of O(n*m) over a two-hour meeting's thousands of segments —
    # and it is only correct on a time-ordered lane. Neither transcript parser
    # nor the STT payload guarantees that, and an out-of-order start would make
    # the cursor skip past real candidates and leave turns silently unanchored,
    # so order is established here rather than assumed.
    stt = sorted(stt, key=lambda candidate: candidate.start_ms)
    cursor = 0
    for segment in provided:
        low = segment.start_ms - window_ms
        while cursor < len(stt) and stt[cursor].start_ms < low:
            cursor += 1
        wanted = segment.token_set
        best: tuple[float, int, int] | None = None
        best_index = -1
        index = cursor
        if not wanted:
            # `jaccard` returns 1.0 for two empty sets — correct where it came
            # from (two consecutive textless frames are not a screen boundary),
            # wrong as a text-identity score. Left alone, a blank turn anchors
            # a blank STT segment at a perfect 1.0 and reports a delta, which
            # is exactly the invented timing this module must never produce.
            matches.append(AlignmentMatch())
            continue
        while index < len(stt) and stt[index].start_ms <= segment.start_ms + window_ms:
            candidate = stt[index]
            if not candidate.token_set:
                index += 1
                continue
            score = jaccard(wanted, candidate.token_set)
            delta = candidate.start_ms - segment.start_ms
            key = (score, -abs(delta), -index)
            # `score > 0` is not redundant with the floor: `min_match_score`
            # is allowed to be 0.0, and at that setting every candidate in the
            # window would anchor at zero overlap.
            if score > 0 and score >= config.min_match_score and (best is None or key > best):
                best = key
                best_index = index
            index += 1
        if best is None:
            matches.append(AlignmentMatch())
            continue
        anchor = stt[best_index]
        matches.append(
            AlignmentMatch(
                stt_index=best_index,
                stt_start_ms=anchor.start_ms,
                delta_ms=anchor.start_ms - segment.start_ms,
                match_score=round(best[0], 6),
            )
        )
    return tuple(matches)


def merge_vtt_end_timings(
    provided: Sequence[TimedText],
    cues: Sequence[TimedText],
    config: AlignConfig,
) -> tuple[int | None, ...]:
    """The real end each provided turn gets from the VTT, where a cue matches.

    A turn usually spans several cues, so every cue that starts inside the
    turn's span (allowing the anchor window at the front) and whose text
    overlaps the turn's is considered; the turn's end is the latest of their
    ends. A turn no cue matches gets ``None`` and falls back to the next turn's
    start — the VTT never supplies speakers and never replaces a start.
    """
    window_ms = round(config.anchor_window_seconds * 1000)
    ends: list[int | None] = []
    # Same forward-only cursor, same requirement (see `align_segments`).
    cues = sorted(cues, key=lambda cue: cue.start_ms)
    cursor = 0
    for position, segment in enumerate(provided):
        low = segment.start_ms - window_ms
        following = provided[position + 1].start_ms if position + 1 < len(provided) else None
        high = following if following is not None else segment.start_ms + config.max_segment_ms
        while cursor < len(cues) and cues[cursor].start_ms < low:
            cursor += 1
        wanted = segment.token_set
        best_end: int | None = None
        index = cursor
        while index < len(cues) and wanted and cues[index].start_ms <= high:
            cue = cues[index]
            # Same empty-set trap as the aligner: a blank turn must not take
            # its end from an unrelated blank cue at a perfect score.
            score = jaccard(wanted, cue.token_set) if cue.token_set else 0.0
            if cue.end_ms is not None and score > 0 and score >= config.min_match_score:
                best_end = cue.end_ms if best_end is None else max(best_end, cue.end_ms)
            index += 1
        ends.append(best_end)
    return tuple(ends)


def resolve_end_times(
    provided: Sequence[TimedText],
    vtt_ends: Sequence[int | None],
    config: AlignConfig,
) -> tuple[int, ...]:
    """Every segment's end: the VTT's where there is one, else the next start.

    The cap matters at the two places a turn would otherwise run away: the last
    turn of the meeting, and a turn followed by a long silence. A VTT end is
    never capped — overlapping speech is real, and the cue measured it.
    """
    resolved: list[int] = []
    for position, segment in enumerate(provided):
        vtt_end = vtt_ends[position] if position < len(vtt_ends) else None
        if vtt_end is not None:
            resolved.append(max(vtt_end, segment.start_ms))
            continue
        if segment.end_ms is not None:
            resolved.append(max(segment.end_ms, segment.start_ms))
            continue
        capped = segment.start_ms + config.max_segment_ms
        if position + 1 < len(provided):
            capped = min(capped, provided[position + 1].start_ms)
        resolved.append(max(capped, segment.start_ms))
    return tuple(resolved)
