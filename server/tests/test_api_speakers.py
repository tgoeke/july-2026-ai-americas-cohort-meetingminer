"""Contract tests for `GET /meetings/{meetingId}/speakers` (story 7.2).

One test per row of the story's I/O matrix, plus field-set literals for the
payload shape — the same pinning style as `test_api_moments.py`.

Segments are seeded here rather than through `projection_seed.seed_meeting`'s
`turns`: that helper hard-codes `end_ms = start_ms + 2000`, so every turn has
the same duration and neither the talk-time sum nor the longest-segment
sample selection would be observable. `seed_meeting(turns=())` still writes
the job, meeting, stage rows and `transcript_source` this route's gate and FKs
need; `_seed_segments` adds the differing durations on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID, uuid4

from fastapi.routing import APIRoute
from psycopg_pool import ConnectionPool

from meetingminer.api.registry import discover_routers
from meetingminer.api.speakers import MAX_SAMPLE_OFFSETS
from meetingminer.pipeline.speakers import RESOLUTIONS
from projection_seed import SeededMeeting, SeededTurn, seed_meeting

RESPONSE_FIELDS = {"meetingId", "speakers"}
SPEAKER_FIELDS = {
    "speakerLabel", "speakerResolution", "participantId", "displayName",
    "talkTimeMs", "segmentCount", "sampleOffsetsMs",
}


@dataclass(frozen=True)
class Seg:
    """One `transcript_segment` row, with the duration the seed cannot vary.

    `participant_index` indexes `SeededMeeting.participant_ids`; migration
    0005 constrains a non-NULL `participant_id` to `resolution='resolved'`,
    so the two travel together here.
    """

    ordinal: int
    start_ms: int
    end_ms: int
    speaker_label: str
    speaker_resolution: str = "placeholder"
    participant_index: int | None = None


# Two voices, five segments, deliberately unequal durations. Shared by the
# diarized and the name-carrying meeting so "one shape, two sources" compares
# two payloads whose timings are identical by construction.
#
#   voice 0: 5 000 + 9 000 + 3 000 = 17 000 ms over 3 segments
#   voice 1:         6 000 + 4 000 = 10 000 ms over 2 segments
_TIMINGS: tuple[tuple[int, int, int, int], ...] = (
    # (ordinal, start_ms, end_ms, voice index)
    (1, 0, 5_000, 0),
    (2, 5_000, 11_000, 1),
    (3, 20_000, 29_000, 0),
    (4, 30_000, 34_000, 1),
    (5, 40_000, 43_000, 0),
)
VOICE_TALK_TIME_MS = (17_000, 10_000)
VOICE_SEGMENT_COUNT = (3, 2)
# The `startMs` of each voice's longest segments, longest first.
VOICE_SAMPLE_OFFSETS_MS = ([20_000, 0, 40_000], [5_000, 30_000])

# What a diarizer leaves behind (story 7.1): a slot label, `placeholder`, and
# no participant — `pipeline/speakers._PLACEHOLDER_LABEL` is why `SPEAKER_NN`
# never becomes one.
DIARIZED_LABELS = ("SPEAKER_00", "SPEAKER_01")
# What a Teams-shaped (or 6.3-converted Zoom) transcript carries, resolved by
# `align` against the meeting roster — `projection_seed.DEFAULT_PARTICIPANTS`
# in the same order.
NAMED_LABELS = ("Goeke, Timothy", "Whitmore, Ellis")


def _seed(pool: ConnectionPool, **kwargs) -> SeededMeeting:
    with pool.connection() as conn:
        return seed_meeting(conn, **kwargs)


def _seed_segments(
    pool: ConnectionPool, seeded: SeededMeeting, segments: Sequence[Seg]
) -> None:
    """Insert `transcript_segment` rows in the shape migration 0005 declares.

    The label/timing sources are the meeting's one `transcript_source` row,
    which `seed_meeting` writes whether or not it seeded any turns.
    """
    with pool.connection() as conn:
        source_id = conn.execute(
            "SELECT id FROM transcript_source WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()[0]
        for segment in segments:
            participant_id = (
                seeded.participant_ids[segment.participant_index]
                if segment.participant_index is not None
                else None
            )
            conn.execute(
                "INSERT INTO transcript_segment (meeting_id, ordinal, start_ms,"
                " end_ms, text, speaker_label, participant_id,"
                " speaker_resolution, label_source_id, timing_source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    seeded.meeting_id,
                    segment.ordinal,
                    segment.start_ms,
                    segment.end_ms,
                    f"segment {segment.ordinal}",
                    segment.speaker_label,
                    participant_id,
                    segment.speaker_resolution,
                    source_id,
                    source_id,
                ),
            )


def _diarized_segments() -> tuple[Seg, ...]:
    return tuple(
        Seg(ordinal, start_ms, end_ms, DIARIZED_LABELS[voice], "placeholder", None)
        for ordinal, start_ms, end_ms, voice in _TIMINGS
    )


def _named_segments() -> tuple[Seg, ...]:
    return tuple(
        Seg(ordinal, start_ms, end_ms, NAMED_LABELS[voice], "resolved", voice)
        for ordinal, start_ms, end_ms, voice in _TIMINGS
    )


def _seed_diarized(pool: ConnectionPool, *, source_id: str) -> SeededMeeting:
    """A diarized meeting: tags, no roster, no attribution anywhere."""
    seeded = _seed(pool, source_id=source_id, turns=(), participants=())
    _seed_segments(pool, seeded, _diarized_segments())
    return seeded


def _seed_named(pool: ConnectionPool, *, source_id: str) -> SeededMeeting:
    """A meeting whose transcript arrived carrying real, resolved names."""
    seeded = _seed(pool, source_id=source_id, turns=())
    _seed_segments(pool, seeded, _named_segments())
    return seeded


def test_a_diarized_meeting_lists_its_tags_with_no_attribution(
    client, test_pool
) -> None:
    """The matrix's first row: every field present, attribution absent.

    A `placeholder` tag names a slot, not a person, so `participantId` and
    `displayName` are null on every row — never a guessed identity (AD-13).
    """
    seeded = _seed_diarized(test_pool, source_id="speakers-diarized")

    response = client.get(f"/meetings/{seeded.meeting_id}/speakers")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == RESPONSE_FIELDS
    assert body["meetingId"] == str(seeded.meeting_id)

    speakers = body["speakers"]
    assert len(speakers) == 2
    for speaker in speakers:
        assert set(speaker) == SPEAKER_FIELDS
        assert speaker["speakerResolution"] == "placeholder"
        assert speaker["participantId"] is None
        assert speaker["displayName"] is None

    # Talk time descending, so the busier tag leads.
    assert [s["speakerLabel"] for s in speakers] == list(DIARIZED_LABELS)
    assert [s["talkTimeMs"] for s in speakers] == list(VOICE_TALK_TIME_MS)
    assert [s["segmentCount"] for s in speakers] == list(VOICE_SEGMENT_COUNT)
    assert [s["sampleOffsetsMs"] for s in speakers] == list(VOICE_SAMPLE_OFFSETS_MS)


def test_a_name_carrying_meeting_lists_the_attribution_align_stored(
    client, test_pool
) -> None:
    """The matrix's second row: same fields, attribution populated.

    `speakerLabel` stays the transcript's verbatim label — that is what the
    reader has to recognize beside the transcript — and `displayName` is the
    curated `participant.display_name` alongside it.
    """
    seeded = _seed_named(test_pool, source_id="speakers-named")

    body = client.get(f"/meetings/{seeded.meeting_id}/speakers").json()
    speakers = body["speakers"]
    assert len(speakers) == 2
    for speaker in speakers:
        assert set(speaker) == SPEAKER_FIELDS
        assert speaker["speakerResolution"] == "resolved"

    assert [s["speakerLabel"] for s in speakers] == list(NAMED_LABELS)
    assert [s["participantId"] for s in speakers] == [
        str(participant_id) for participant_id in seeded.participant_ids
    ]
    assert [s["displayName"] for s in speakers] == list(NAMED_LABELS)


def test_the_two_sources_produce_one_shape(client, test_pool) -> None:
    """The acceptance criterion: identical field sets and identical
    talk-time/count/offset numbers from a diarized meeting and a name-carrying
    one seeded with identical timings — only the label and the two attribution
    fields differ."""
    diarized = _seed_diarized(test_pool, source_id="speakers-shape-diarized")
    named = _seed_named(test_pool, source_id="speakers-shape-named")

    diarized_rows = client.get(f"/meetings/{diarized.meeting_id}/speakers").json()[
        "speakers"
    ]
    named_rows = client.get(f"/meetings/{named.meeting_id}/speakers").json()["speakers"]

    assert len(diarized_rows) == len(named_rows) == 2
    for left, right in zip(diarized_rows, named_rows, strict=True):
        assert set(left) == set(right) == SPEAKER_FIELDS
        assert left["talkTimeMs"] == right["talkTimeMs"]
        assert left["segmentCount"] == right["segmentCount"]
        assert left["sampleOffsetsMs"] == right["sampleOffsetsMs"]
        # Only the named meeting carries an identity.
        assert left["participantId"] is None and left["displayName"] is None
        assert right["participantId"] is not None and right["displayName"] is not None


def test_the_samples_are_the_three_longest_segments_longest_first(
    client, test_pool
) -> None:
    """Five segments of differing durations yield exactly three offsets — the
    `startMs` of the three longest, longest first — and a tie between two
    equal durations resolves to the earlier start, not to whatever the planner
    returned. (The third ordering key, `ordinal`, is unobservable here on
    purpose: two segments tying on both duration and start have the same
    `startMs`, so which one is taken cannot change the payload; it is in the
    ORDER BY so the choice is never planner-dependent.)"""
    seeded = _seed(test_pool, source_id="speakers-samples", turns=(), participants=())
    _seed_segments(
        test_pool,
        seeded,
        (
            Seg(1, 0, 4_000, "SPEAKER_00"),  # 4 000
            Seg(2, 10_000, 18_000, "SPEAKER_00"),  # 8 000, ties with ordinal 4
            Seg(3, 20_000, 26_000, "SPEAKER_00"),  # 6 000
            Seg(4, 30_000, 38_000, "SPEAKER_00"),  # 8 000, starts later
            Seg(5, 40_000, 41_000, "SPEAKER_00"),  # 1 000
        ),
    )

    speakers = client.get(f"/meetings/{seeded.meeting_id}/speakers").json()["speakers"]
    assert len(speakers) == 1
    assert speakers[0]["segmentCount"] == 5
    assert speakers[0]["talkTimeMs"] == 27_000
    assert len(speakers[0]["sampleOffsetsMs"]) == MAX_SAMPLE_OFFSETS
    assert speakers[0]["sampleOffsetsMs"] == [10_000, 30_000, 20_000]


def test_fewer_than_three_segments_are_never_padded(client, test_pool) -> None:
    """A tag with one or two segments gets that many offsets. Story 7.4 plays
    clip *n* of what is here, and a fabricated offset would play silence."""
    seeded = _seed(test_pool, source_id="speakers-short", turns=(), participants=())
    _seed_segments(
        test_pool,
        seeded,
        (
            Seg(1, 0, 9_000, "SPEAKER_00"),
            Seg(2, 20_000, 25_000, "SPEAKER_01"),
            Seg(3, 30_000, 33_000, "SPEAKER_01"),
        ),
    )

    speakers = client.get(f"/meetings/{seeded.meeting_id}/speakers").json()["speakers"]
    by_label = {speaker["speakerLabel"]: speaker for speaker in speakers}
    assert by_label["SPEAKER_00"]["sampleOffsetsMs"] == [0]
    assert by_label["SPEAKER_01"]["sampleOffsetsMs"] == [20_000, 30_000]


def test_an_ambiguous_or_unresolved_label_is_listed_without_attribution(
    client, test_pool
) -> None:
    """A label that matched two roster entries, and one that matched none, are
    both real rows: the verbatim label and its resolution, attribution null.
    `align` refuses to pick — a wrong attribution is worse than an absent
    one — and this read repeats the refusal rather than re-deriving it."""
    seeded = _seed(test_pool, source_id="speakers-refused", turns=())
    _seed_segments(
        test_pool,
        seeded,
        (
            Seg(1, 0, 6_000, "Kendall", "ambiguous"),
            Seg(2, 10_000, 14_000, "Speaker 8", "unresolved"),
            Seg(3, 20_000, 22_000, "Goeke, Timothy", "resolved", 0),
        ),
    )

    speakers = client.get(f"/meetings/{seeded.meeting_id}/speakers").json()["speakers"]
    assert {speaker["speakerResolution"] for speaker in speakers} <= set(RESOLUTIONS)
    by_label = {speaker["speakerLabel"]: speaker for speaker in speakers}
    assert set(by_label) == {"Kendall", "Speaker 8", "Goeke, Timothy"}
    for label, resolution in (("Kendall", "ambiguous"), ("Speaker 8", "unresolved")):
        assert by_label[label]["speakerResolution"] == resolution
        assert by_label[label]["participantId"] is None
        assert by_label[label]["displayName"] is None
    # The resolved neighbour is unaffected: refusing one label never blanks
    # another.
    assert by_label["Goeke, Timothy"]["participantId"] == str(seeded.participant_ids[0])


def test_a_renamed_participant_shows_the_new_name_beside_the_old_label(
    client, test_pool
) -> None:
    """`displayName` is read live off `participant.display_name`, so a
    curator's rename (which keeps the id) shows on the next request, while
    `speakerLabel` stays the transcript's verbatim label."""
    seeded = _seed_named(test_pool, source_id="speakers-renamed")
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE participant SET display_name = 'Tim Goeke' WHERE id = %s",
            (seeded.participant_ids[0],),
        )

    speakers = client.get(f"/meetings/{seeded.meeting_id}/speakers").json()["speakers"]
    renamed = next(s for s in speakers if s["participantId"] == str(seeded.participant_ids[0]))
    assert renamed["displayName"] == "Tim Goeke"
    assert renamed["speakerLabel"] == "Goeke, Timothy"


def test_a_meeting_with_no_segments_answers_an_empty_list(client, test_pool) -> None:
    seeded = _seed(test_pool, source_id="speakers-empty", turns=(), participants=())

    response = client.get(f"/meetings/{seeded.meeting_id}/speakers")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == RESPONSE_FIELDS
    assert body["speakers"] == []


def test_an_unknown_meeting_is_a_404_problem(client) -> None:
    response = client.get(f"/meetings/{uuid4()}/speakers")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_an_unsettled_meeting_is_a_409_with_the_sibling_extensions(
    client, test_pool
) -> None:
    """The gate is `moments._require_viewable` itself, so the refusal carries
    the sibling meeting reads' `meetingId`/`augmenting`/`jobStatus` verbatim
    rather than a second, drifting spelling of the same conflict."""
    seeded = _seed(
        test_pool,
        source_id="speakers-augmenting",
        turns=(),
        participants=(),
        stage_overrides={"align": "queued", "moments": "queued", "extract": "done"},
    )

    response = client.get(f"/meetings/{seeded.meeting_id}/speakers")
    assert response.status_code == 409, response.text
    body = response.json()
    assert response.headers["content-type"] == "application/problem+json"
    assert body["type"] == "urn:meetingminer:problem:meeting-not-viewable"
    assert body["meetingId"] == str(seeded.meeting_id)
    assert body["augmenting"] is True
    assert body["jobStatus"] == "running"


def test_a_first_ingest_in_flight_is_a_409_not_augmenting(client, test_pool) -> None:
    seeded = _seed(
        test_pool,
        source_id="speakers-first-ingest",
        turns=(),
        participants=(),
        stage_overrides={"moments": "running"},
    )

    body = client.get(f"/meetings/{seeded.meeting_id}/speakers").json()
    assert body["type"] == "urn:meetingminer:problem:meeting-not-viewable"
    assert body["augmenting"] is False
    assert body["jobStatus"] == "running"


def test_a_malformed_id_is_a_422_problem(client) -> None:
    response = client.get("/meetings/not-a-uuid/speakers")
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_the_route_documents_the_runtime_422_problem_contract(client) -> None:
    schema = client.app.openapi()
    response = schema["paths"]["/meetings/{meeting_id}/speakers"]["get"]["responses"][
        "422"
    ]
    assert response["content"] == {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"}
        }
    }


def test_nullable_attribution_fields_are_required_by_the_schema(client) -> None:
    """One shape means explicit nulls, not fields a generated client may omit."""
    schema = client.app.openapi()["components"]["schemas"]["SpeakerTag"]

    assert {"participantId", "displayName"} <= set(schema["required"])
    for field in ("participantId", "displayName"):
        assert {"type": "null"} in schema["properties"][field]["anyOf"]


def test_the_route_is_registered_by_discovery_alone(client) -> None:
    """Adding the endpoint was adding a file: `api/main.py` is untouched and
    the registry (story 2.8) finds and serves the route."""
    discovered = dict(discover_routers())
    assert "speakers" in discovered
    # Story 7.3 added the write side to this same module, so the router now
    # carries two paths. The set stays exact rather than becoming a subset
    # check: a third path appearing here should still have to be declared.
    assert {route.path for route in discovered["speakers"].routes} == {
        "/meetings/{meeting_id}/speakers",
        "/meetings/{meeting_id}/speakers/{tag}",
    }

    # FastAPI keeps an included router as a nested entry, so walk the app's
    # table the way `test_api_registry.py` does rather than trusting the top
    # level.
    served: set[str] = set()
    pending = list(client.app.router.routes)
    while pending:
        route = pending.pop()
        if isinstance(route, APIRoute):
            served.add(route.path)
        elif hasattr(route, "original_router"):
            pending.extend(route.original_router.routes)
    assert served, "flattening found no APIRoutes — private-attr dependency broke?"
    assert "/meetings/{meeting_id}/speakers" in served


def test_the_drilldown_segments_carry_the_diarizer_tag(client, test_pool) -> None:
    """The other half of the AC — a transcript segment carries its tag on the
    wire — pinned where it already lives (`moments.DrilldownSegment`) rather
    than rebuilt here: a diarized meeting's segments arrive labelled
    `SPEAKER_NN`, `placeholder`, with no participant."""
    seeded = _seed(
        test_pool,
        source_id="speakers-drilldown",
        participants=(),
        turns=(
            SeededTurn(1, 0, "Morning.", "SPEAKER_00", None, "placeholder"),
            SeededTurn(2, 5_000, "Morning, all.", "SPEAKER_01", None, "placeholder"),
        ),
    )

    body = client.get(f"/meetings/{seeded.meeting_id}/drilldown").json()
    segments = body["segments"]
    assert [segment["speakerLabel"] for segment in segments] == list(DIARIZED_LABELS)
    for segment in segments:
        assert segment["speakerResolution"] == "placeholder"
        assert segment["participantId"] is None


def test_the_response_never_names_an_identity_the_segments_do_not(
    client, test_pool
) -> None:
    """The never-guess criterion, asserted against the store: every
    `participantId` on the wire is one `transcript_segment.participant_id`
    already carries, and every NULL there stays null here."""
    seeded = _seed_named(test_pool, source_id="speakers-no-guessing")
    _seed_segments(
        test_pool,
        seeded,
        (Seg(6, 50_000, 52_000, "SPEAKER_02", "placeholder"),),
    )
    with test_pool.connection() as conn:
        stored: set[UUID | None] = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT participant_id FROM transcript_segment"
                " WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchall()
        }

    speakers = client.get(f"/meetings/{seeded.meeting_id}/speakers").json()["speakers"]
    on_the_wire = {
        UUID(speaker["participantId"]) if speaker["participantId"] else None
        for speaker in speakers
    }
    assert on_the_wire == stored
    assert None in stored, "the fixture must carry an unattributed tag"
