"""Turn packing: the tuning lever, tested with no store and no model.

`chunking.py` is pure on purpose — chunk size and overlap are the *open* lever
(`retrieval-prior-art.md` §6-§7) and retuning them is expected during Epic 3,
so the rules that must survive a retune are asserted here rather than through
a live index.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from meetingminer.projections.chunking import Chunk, Turn, chunk_turns

MEETING = UUID("01a0170c-bb04-78c2-832a-4fc2bc555551")


def turn(
    ordinal: int,
    text: str,
    speaker: str = "Goeke, Timothy",
    participant: UUID | None = None,
    start_ms: int | None = None,
) -> Turn:
    start = ordinal * 1000 if start_ms is None else start_ms
    return Turn(
        id=uuid4(),
        ordinal=ordinal,
        start_ms=start,
        end_ms=start + 900,
        text=text,
        speaker_label=speaker,
        participant_id=participant,
        speaker_resolution="resolved" if participant else "unresolved",
    )


def pack(turns: list[Turn], max_chars: int = 120, overlap: int = 1) -> tuple[Chunk, ...]:
    return chunk_turns(
        MEETING, turns, chunk_max_chars=max_chars, chunk_overlap_turns=overlap
    )


def test_no_chunk_starts_mid_turn() -> None:
    """A chunk always begins at a turn boundary — §6's deliberate rule.

    A chunk starting mid-sentence loses the speaker attribution that both the
    graph edges and the citation timestamps hang off.
    """
    turns = [turn(i, f"Sentence number {i} about the purchase order process.") for i in range(1, 12)]
    chunks = pack(turns)
    starts = {chunk.turns[0].id for chunk in chunks}
    assert starts <= {t.id for t in turns}
    for chunk in chunks:
        # Every turn appears whole: the rendered turn text is a substring.
        for member in chunk.turns:
            assert member.text in chunk.text


def test_chunks_honor_the_configured_maximum() -> None:
    turns = [turn(i, "word " * 10) for i in range(1, 20)]
    chunks = pack(turns, max_chars=200)
    # Only a chunk of exactly one turn may exceed the maximum, and only
    # because splitting the turn is forbidden.
    for chunk in chunks:
        assert chunk.char_count <= 200 or len(chunk.turns) == 1


def test_a_single_oversized_turn_is_its_own_chunk_never_split() -> None:
    turns = [turn(1, "x" * 5000), turn(2, "short follow up")]
    chunks = pack(turns, max_chars=100, overlap=1)
    assert chunks[0].turns == (turns[0],)
    assert "x" * 5000 in chunks[0].text
    # And the packer still advanced — an oversized turn must not loop.
    assert turns[1].id in {t.id for chunk in chunks for t in chunk.turns}


def test_overlap_repeats_exactly_the_configured_number_of_turns() -> None:
    turns = [turn(i, f"Turn {i} text that is reasonably long here.") for i in range(1, 16)]
    for overlap in (0, 1, 2):
        chunks = pack(turns, max_chars=200, overlap=overlap)
        assert len(chunks) > 1, "expected several chunks at this size"
        for earlier, later in zip(chunks, chunks[1:]):
            # The packer always advances by at least one turn, so the overlap
            # it can actually deliver is capped by the earlier chunk's length.
            expected = min(overlap, len(earlier.turns) - 1)
            # The shared turns are the *tail* of the earlier chunk and the
            # *head* of the later one, never an arbitrary intersection.
            tail = [t.id for t in earlier.turns[len(earlier.turns) - expected :]] if expected else []
            head = [t.id for t in later.turns[:expected]] if expected else []
            assert tail == head
            overlapping = {t.id for t in later.turns} & {t.id for t in earlier.turns}
            assert len(overlapping) == expected


def test_every_chunk_carries_its_timings_speakers_and_meeting_id() -> None:
    alice, bob = uuid4(), uuid4()
    turns = [
        turn(1, "Opening remarks about SFTP.", speaker="Goeke, Timothy", participant=alice),
        turn(2, "Reply about the purchase order.", speaker="Whitmore, Ellis", participant=bob),
        turn(3, "Third turn.", speaker="Goeke, Timothy", participant=alice),
    ]
    (chunk,) = pack(turns, max_chars=10_000)
    assert chunk.meeting_id == MEETING
    assert chunk.start_ms == turns[0].start_ms
    assert chunk.end_ms == turns[-1].end_ms
    # First-appearance order, deduplicated.
    assert chunk.speakers == ("Goeke, Timothy", "Whitmore, Ellis")
    assert chunk.participant_ids == (alice, bob)
    assert chunk.segment_ids == tuple(t.id for t in turns)


def test_chunk_id_is_its_first_segments_postgres_uuid_never_a_sequence() -> None:
    """AD-6: identity is a Postgres UUID, and re-chunking must not renumber it."""
    turns = [turn(i, f"Turn {i} body text goes here for length.") for i in range(1, 12)]
    chunks = pack(turns, max_chars=150)
    assert [c.id for c in chunks] == [c.turns[0].id for c in chunks]
    # Unique even with overlap: the packer always advances by a whole turn.
    assert len({c.id for c in chunks}) == len(chunks)


def test_an_unresolved_speaker_keeps_its_label_and_contributes_no_participant() -> None:
    """A wrong attribution is worse than an absent one (SPEC, story 1.5)."""
    resolved = uuid4()
    turns = [
        turn(1, "Named speaker.", speaker="Whitmore, Ellis", participant=resolved),
        turn(2, "Who is this?", speaker="Speaker 8", participant=None),
    ]
    (chunk,) = pack(turns, max_chars=10_000)
    assert "Speaker 8" in chunk.speakers
    assert chunk.participant_ids == (resolved,)


def test_a_meeting_with_no_turns_produces_no_chunks() -> None:
    assert pack([]) == ()


@pytest.mark.parametrize(
    "max_chars,overlap", [(0, 1), (-1, 0)],
)
def test_a_nonsensical_maximum_is_refused(max_chars: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        pack([turn(1, "text")], max_chars=max_chars, overlap=overlap)


def test_a_negative_overlap_is_refused() -> None:
    with pytest.raises(ValueError):
        pack([turn(1, "text")], max_chars=100, overlap=-1)


@pytest.mark.parametrize("max_chars,overlap", [(0, 1), (1400, -1)])
def test_a_nonsensical_knob_is_refused_even_with_no_turns(
    max_chars: int, overlap: int
) -> None:
    """Validation runs before the empty-input shortcut, deliberately.

    Whether a tuning value is accepted must not depend on whether the meeting
    it was handed happened to have any speech in it — this is the pure module
    the chunking rules live in, and a transcript-less meeting is a legitimate
    input, not a licence to accept `chunk_max_chars: 0`.
    """
    with pytest.raises(ValueError):
        pack([], max_chars=max_chars, overlap=overlap)


def test_the_speaker_label_is_part_of_the_searchable_body() -> None:
    """Full-text is first class (§7 finding 1), so the label is in the text."""
    (chunk,) = pack([turn(1, "we moved to SFTP", speaker="Ironside, Indigo")])
    assert chunk.text == "Ironside, Indigo: we moved to SFTP"
