"""Turn-packing: the retrieval-shaped view of a meeting's transcript.

Pure by construction — no store, no model, no database. That is deliberate:
chunk size and overlap are the *open* tuning lever (`retrieval-prior-art.md`
§6-§7; the bake-off held them fixed across all nine model configurations and
still attributed a meaningful share of its misses to the answer sitting one
chunk over), so retuning them has to be testable without standing anything up.

Two rules the packer never breaks:

* **A chunk never starts mid-turn.** Speaker attribution is what the graph
  edges and the citation timestamps hang off, so a chunk that begins in the
  middle of somebody's sentence has lost the thing that makes it citable (§6).
  A single turn longer than ``chunk_max_chars`` therefore becomes its own
  oversized chunk rather than being split.
* **A chunk's identity is a Postgres-minted UUID** — the id of its first
  transcript segment (AD-6). Never ``meetingId#seq``, never an ordinal:
  re-chunking renumbers a sequence and orphans every edge and citation
  pointing at it (§2). Overlap cannot collide two chunks onto one key because
  the packer always advances the start index by at least one turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID


@dataclass(frozen=True)
class Turn:
    """One derived ``transcript_segment`` row, as the packer sees it.

    ``participant_id`` is ``None`` for an unresolved, ambiguous, or
    placeholder speaker, and ``speaker_resolution`` says which. Both travel
    with the chunk: a chunk whose speaker did not resolve still carries the
    raw label the transcript wrote, and no Participant edge is invented for it
    (a wrong attribution is worse than an absent one).
    """

    id: UUID
    ordinal: int
    start_ms: int
    end_ms: int
    text: str
    speaker_label: str
    participant_id: UUID | None = None
    speaker_resolution: str = "placeholder"


@dataclass(frozen=True)
class Chunk:
    """One packed passage: the unit retrieval quality was measured at."""

    # The first turn's Postgres UUID, carried verbatim as the Neo4j node key
    # and the Meilisearch document id (AD-6).
    id: UUID
    meeting_id: UUID
    turns: tuple[Turn, ...]
    text: str
    start_ms: int
    end_ms: int
    # Every distinct speaker label in the chunk, in first-appearance order —
    # §6 records the speaker list as part of what a chunk carries.
    speakers: tuple[str, ...]
    # Resolved participants only. An unresolved label appears in ``speakers``
    # and contributes nothing here, which is what keeps the graph honest.
    participant_ids: tuple[UUID, ...]
    segment_ids: tuple[UUID, ...]

    @property
    def char_count(self) -> int:
        return len(self.text)


# How a turn is rendered into the chunk body. Keeping the speaker label inline
# is what lets a full-text query like "Ellis purchase order" match the passage
# rather than only the separate `speakers` attribute.
def _render(turn: Turn) -> str:
    label = turn.speaker_label.strip() or "Unknown"
    return f"{label}: {turn.text.strip()}"


def _pack(turns: Sequence[Turn], max_chars: int, overlap_turns: int) -> list[list[Turn]]:
    """Group turns into windows, never splitting one, never failing to advance.

    ``overlap_turns`` is clamped against the window length: without that, a
    window of a single oversized turn would produce a next start at or before
    its own start and the packer would never terminate.
    """
    groups: list[list[Turn]] = []
    start = 0
    total = len(turns)
    while start < total:
        end = start  # exclusive
        length = 0
        while end < total:
            rendered = len(_render(turns[end]))
            # +1 for the newline joining it to what is already in the window.
            addition = rendered + (1 if end > start else 0)
            if end > start and length + addition > max_chars:
                break
            length += addition
            end += 1
        groups.append(list(turns[start:end]))
        if end >= total:
            break
        # Always move forward by at least one turn, whatever the overlap says.
        start = max(start + 1, end - overlap_turns)
    return groups


def chunk_turns(
    meeting_id: UUID,
    turns: Iterable[Turn],
    *,
    chunk_max_chars: int,
    chunk_overlap_turns: int,
) -> tuple[Chunk, ...]:
    """Pack a meeting's turns into chunks under the configured knobs.

    Turns are taken in the order given (the caller reads them ordered by
    ``ordinal``). A meeting with no turns produces no chunks — which is not an
    error: a transcript-less meeting is legitimately structural-only.
    """
    # Validated before the empty-input shortcut, deliberately: this is the
    # pure module the chunking rules live in, and a meeting that happens to
    # have no turns must not be the thing that decides whether a nonsensical
    # tuning value is accepted.
    if chunk_max_chars <= 0:
        raise ValueError("chunk_max_chars must be positive")
    if chunk_overlap_turns < 0:
        raise ValueError("chunk_overlap_turns must not be negative")
    ordered = tuple(turns)
    if not ordered:
        return ()

    chunks: list[Chunk] = []
    for group in _pack(ordered, chunk_max_chars, chunk_overlap_turns):
        speakers: list[str] = []
        participants: list[UUID] = []
        for turn in group:
            label = turn.speaker_label.strip() or "Unknown"
            if label not in speakers:
                speakers.append(label)
            if turn.participant_id is not None and turn.participant_id not in participants:
                participants.append(turn.participant_id)
        chunks.append(
            Chunk(
                id=group[0].id,
                meeting_id=meeting_id,
                turns=tuple(group),
                text="\n".join(_render(turn) for turn in group),
                start_ms=min(turn.start_ms for turn in group),
                end_ms=max(turn.end_ms for turn in group),
                speakers=tuple(speakers),
                participant_ids=tuple(participants),
                segment_ids=tuple(turn.id for turn in group),
            )
        )
    return tuple(chunks)
