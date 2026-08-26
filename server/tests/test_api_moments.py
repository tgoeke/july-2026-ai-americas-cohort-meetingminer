"""Contract tests for the moment read routes (story 2.2; Postgres only).

One test per row of the story's I/O matrix, plus field-set literals for each
payload shape — the same pinning style as `test_api_meetings.py`. Seeding goes
through `projection_seed.seed_meeting`, which writes the exact shapes the
migrations declare; the superseded row is minted by the same UPDATE the
`moments` stage runs (`pipeline/stages/moments.py`), links removed the way its
rebuild leaves them.
"""

from __future__ import annotations

from typing import get_args
from uuid import UUID, uuid4

from psycopg_pool import ConnectionPool

import meetingminer.api.moments as moments_api
from meetingminer.api.moments import ArtifactKind, ArtifactState, PREVIEW_MAX_CHARS
from meetingminer.projections.publish_gate import ARTIFACT_STATES
from projection_seed import (
    DEEP_LINK,
    SeededTurn,
    STARTED_AT,
    SeededMeeting,
    seed_meeting,
)

LIST_FIELDS = {
    "meetingId", "title", "hasRecording", "corpus", "startedAt",
    "startedAtPrecision", "moments",
}
LIST_MOMENT_FIELDS = {
    "momentId", "startMs", "endMs", "startedAt", "startedAtPrecision",
    "screenshotId", "sourceDeepLink", "segmentCount", "preview",
}
DETAIL_FIELDS = {
    "momentId", "meetingId", "meetingTitle", "corpus", "hasRecording",
    "startMs", "endMs", "startedAt", "startedAtPrecision", "screenshotId",
    "screenshotPath", "sourceDeepLink", "superseded", "segments", "artifacts",
}
SEGMENT_FIELDS = {
    "startMs", "endMs", "speakerLabel", "speakerResolution", "participantId",
    "text",
}
DRILLDOWN_FIELDS = {
    "meetingId", "title", "hasRecording", "corpus", "startedAt",
    "startedAtPrecision", "sourceDeepLink", "screenshots", "segments",
}
DRILLDOWN_SCREENSHOT_FIELDS = {
    "screenshotId", "ordinal", "startOffsetMs", "endOffsetMs", "path",
    "viewType", "screenLabel", "classificationTags", "momentId",
}
DRILLDOWN_SEGMENT_FIELDS = {
    "segmentId", "ordinal", "startMs", "endMs", "speakerLabel",
    "speakerResolution", "participantId", "text", "momentId",
}


def _seed(pool: ConnectionPool, **kwargs) -> SeededMeeting:
    with pool.connection() as conn:
        return seed_meeting(conn, **kwargs)


def _supersede(pool: ConnectionPool, moment_id: UUID) -> None:
    """Mark one moment the way the `moments` stage does.

    The UPDATE mirrors `pipeline/stages/moments.py` (provenance merged, count
    squared to zero); the link DELETE mirrors the stage's link rebuild, which
    recreates links for recomputed moments only and leaves a superseded row
    with none.
    """
    with pool.connection() as conn:
        conn.execute(
            "UPDATE moment SET"
            "   provenance = provenance || '{\"superseded\": true}'::jsonb,"
            "   segment_count = 0"
            " WHERE id = %s",
            (moment_id,),
        )
        conn.execute("DELETE FROM moment_segment WHERE moment_id = %s", (moment_id,))


def test_the_moments_list_returns_the_header_and_ordered_moments(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="source-list")

    response = client.get(f"/meetings/{seeded.meeting_id}/moments")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == LIST_FIELDS
    assert body["meetingId"] == str(seeded.meeting_id)
    assert body["title"] == "Data Hub Demo"
    assert body["hasRecording"] is True
    assert body["corpus"] == "real"
    assert body["startedAtPrecision"] == "second"
    assert body["startedAt"].startswith("2026-08-05T12:00:19")

    assert len(body["moments"]) == 2
    for item in body["moments"]:
        assert set(item) == LIST_MOMENT_FIELDS
    # `start_ms` order, and ids straight from the seed.
    assert [item["momentId"] for item in body["moments"]] == [
        str(moment_id) for moment_id in seeded.moment_ids
    ]
    assert [item["startMs"] for item in body["moments"]] == [2_000, 40_000]
    # The preview is the first covered segment's text, in ordinal order.
    assert body["moments"][0]["preview"] == "Everybody, good morning."
    assert body["moments"][1]["preview"] == "We moved that feed to SFTP last week."
    assert body["moments"][0]["screenshotId"] == str(seeded.screenshot_ids[0])
    assert body["moments"][0]["sourceDeepLink"] is None


def test_moment_detail_returns_screenshot_segments_and_an_empty_rail(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="source-detail")

    response = client.get(f"/moments/{seeded.moment_ids[0]}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["momentId"] == str(seeded.moment_ids[0])
    assert body["meetingId"] == str(seeded.meeting_id)
    assert body["meetingTitle"] == "Data Hub Demo"
    assert body["hasRecording"] is True
    assert body["superseded"] is False
    assert body["screenshotId"] == str(seeded.screenshot_ids[0])
    # The stored content-root-relative path verbatim — never a URL, never an
    # absolute path (the containment guard at GET /media/{path} owns
    # resolution).
    assert body["screenshotPath"] == f"meetings/{seeded.meeting_id}/screenshots/1.jpg"
    assert not body["screenshotPath"].startswith("/")
    assert body["sourceDeepLink"] is None

    # The covering transcript: exactly the three seeded turns before the gap,
    # in ordinal order, with the full field set.
    assert [segment["text"] for segment in body["segments"]] == [
        "Everybody, good morning.",
        "Morning, all.",
        "Let us walk the revenue slide.",
    ]
    for segment in body["segments"]:
        assert set(segment) == SEGMENT_FIELDS
    assert body["segments"][0]["speakerLabel"] == "Goeke, Timothy"
    assert body["segments"][0]["speakerResolution"] == "resolved"
    assert body["segments"][0]["participantId"] == str(seeded.participant_ids[0])

    assert body["artifacts"] == []


def test_moment_readers_omit_cross_meeting_evidence_links(client, test_pool) -> None:
    """A malformed pair of individually-valid FKs must not disclose another
    meeting's screenshot or transcript through a moment reader."""
    seeded = _seed(test_pool, source_id="source-contained")
    foreign = _seed(
        test_pool,
        source_id="source-foreign",
        title="Foreign meeting",
        turns=(SeededTurn(1, 2_000, "Foreign meeting secret.", "Other"),),
    )
    with test_pool.connection() as conn:
        # `moment_segment` allows this repair/corruption: each side is a valid
        # FK, even though their meetings differ. Remove the foreign row first
        # because a segment has exactly one link.
        conn.execute(
            "DELETE FROM moment_segment WHERE transcript_segment_id = %s",
            (foreign.segment_ids[0],),
        )
        conn.execute(
            "UPDATE moment_segment SET transcript_segment_id = %s"
            " WHERE moment_id = %s AND transcript_segment_id = %s",
            (foreign.segment_ids[0], seeded.moment_ids[0], seeded.segment_ids[0]),
        )
        conn.execute(
            "UPDATE moment SET screenshot_id = %s WHERE id = %s",
            (foreign.screenshot_ids[0], seeded.moment_ids[0]),
        )

    listed = client.get(f"/meetings/{seeded.meeting_id}/moments")
    assert listed.status_code == 200, listed.text
    first = listed.json()["moments"][0]
    assert first["preview"] == "Morning, all."
    assert first["screenshotId"] is None
    assert "Foreign meeting secret." not in str(first)

    detail = client.get(f"/moments/{seeded.moment_ids[0]}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["screenshotId"] is None
    assert body["screenshotPath"] is None
    assert [segment["text"] for segment in body["segments"]] == [
        "Morning, all.",
        "Let us walk the revenue slide.",
    ]
    assert "Foreign meeting secret." not in str(body)


def test_transcript_only_detail_carries_the_deep_link_and_no_screenshot(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="source-transcript-only", has_recording=False)

    response = client.get(f"/moments/{seeded.moment_ids[0]}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hasRecording"] is False
    assert body["screenshotId"] is None
    assert body["screenshotPath"] is None
    # UX-DR11: the recap URL verbatim, standing where replay would be.
    assert body["sourceDeepLink"] == DEEP_LINK


def test_an_unknown_meeting_is_a_404_problem(client) -> None:
    response = client.get(f"/meetings/{uuid4()}/moments")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_an_unknown_moment_is_a_404_problem(client) -> None:
    response = client.get(f"/moments/{uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_an_unsettled_meeting_is_a_409_on_both_routes(client, test_pool) -> None:
    """Exists-but-not-viewable: the transient conflict, never data, never 404."""
    seeded = _seed(
        test_pool,
        source_id="source-unsettled",
        stage_overrides={"moments": "running"},
    )

    for path in (
        f"/meetings/{seeded.meeting_id}/moments",
        f"/moments/{seeded.moment_ids[0]}",
    ):
        response = client.get(path)
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["type"] == "urn:meetingminer:problem:meeting-not-viewable"
        assert "still being prepared" in body["detail"]
        assert body["meetingId"] == str(seeded.meeting_id)


def test_a_superseded_moment_is_hidden_from_the_list_but_served_by_id(
    client, test_pool
) -> None:
    """Citations stay valid across augmentation; the list projects no ghosts."""
    seeded = _seed(test_pool, source_id="source-superseded")
    superseded_id = seeded.moment_ids[1]
    _supersede(test_pool, superseded_id)

    listed = client.get(f"/meetings/{seeded.meeting_id}/moments").json()["moments"]
    assert [item["momentId"] for item in listed] == [str(seeded.moment_ids[0])]

    response = client.get(f"/moments/{superseded_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["superseded"] is True
    assert body["segments"] == []


def test_an_overhanging_covering_segment_is_returned_in_full(
    client, test_pool
) -> None:
    """Coverage is the `moment_segment` join, not a BETWEEN filter: a covered
    segment ending after its moment does is still the moment's transcript."""
    seeded = _seed(test_pool, source_id="source-overhang")
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE transcript_segment SET end_ms = 60000 WHERE id = %s",
            (seeded.segment_ids[2],),
        )
        moment_end = conn.execute(
            "SELECT end_ms FROM moment WHERE id = %s", (seeded.moment_ids[0],)
        ).fetchone()[0]
    assert moment_end < 60_000, "the fixture must actually overhang"

    body = client.get(f"/moments/{seeded.moment_ids[0]}").json()
    assert [segment["endMs"] for segment in body["segments"]][-1] == 60_000
    assert len(body["segments"]) == 3


def test_a_viewable_meeting_with_no_moments_answers_an_empty_list(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="source-empty", with_moments=False)

    response = client.get(f"/meetings/{seeded.meeting_id}/moments")
    assert response.status_code == 200, response.text
    assert response.json()["moments"] == []


def test_a_malformed_id_is_a_422_problem_on_both_routes(client) -> None:
    for path in ("/meetings/not-a-uuid/moments", "/moments/not-a-uuid"):
        response = client.get(path)
        assert response.status_code == 422, response.text
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_moment_routes_document_the_runtime_422_problem_contract(client) -> None:
    schema = client.app.openapi()
    for path in ("/meetings/{meeting_id}/moments", "/moments/{moment_id}"):
        response = schema["paths"][path]["get"]["responses"]["422"]
        assert response["content"] == {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        }


def test_moment_detail_reads_a_single_snapshot_across_the_evidence_gate(
    client, test_pool, monkeypatch
) -> None:
    """A writer committing after the gate cannot change this response.

    The patched gate is the deterministic coordination point: on Read
    Committed the later segment query observes `changed after gate`, while
    REPEATABLE READ returns the evidence snapshot the gate vouched for.
    """
    seeded = _seed(test_pool, source_id="source-snapshot")
    original_gate = moments_api.meeting_evidence_complete
    writer_ran = False

    def gate_then_commit(conn, meeting_id):
        nonlocal writer_ran
        viewable = original_gate(conn, meeting_id)
        if not writer_ran:
            writer_ran = True
            with test_pool.connection() as writer:
                writer.execute(
                    "UPDATE job_stage SET status = 'running'"
                    " WHERE job_id = %s AND name = 'moments'",
                    (seeded.job_id,),
                )
                writer.execute(
                    "UPDATE transcript_segment SET text = 'changed after gate'"
                    " WHERE id = %s",
                    (seeded.segment_ids[0],),
                )
        return viewable

    monkeypatch.setattr(moments_api, "meeting_evidence_complete", gate_then_commit)
    response = client.get(f"/moments/{seeded.moment_ids[0]}")

    assert writer_ran
    assert response.status_code == 200, response.text
    assert response.json()["segments"][0]["text"] == "Everybody, good morning."
    with test_pool.connection() as conn:
        assert conn.execute(
            "SELECT status FROM job_stage WHERE job_id = %s AND name = 'moments'",
            (seeded.job_id,),
        ).fetchone()[0] == "running"
        assert conn.execute(
            "SELECT text FROM transcript_segment WHERE id = %s",
            (seeded.segment_ids[0],),
        ).fetchone()[0] == "changed after gate"


def test_moments_list_reads_a_single_snapshot_across_the_evidence_gate(
    client, test_pool, monkeypatch
) -> None:
    """A post-gate transcript change cannot change this list's preview."""
    seeded = _seed(test_pool, source_id="source-list-snapshot")
    original_gate = moments_api.meeting_evidence_complete
    writer_ran = False

    def gate_then_commit(conn, meeting_id):
        nonlocal writer_ran
        viewable = original_gate(conn, meeting_id)
        if not writer_ran:
            writer_ran = True
            with test_pool.connection() as writer:
                writer.execute(
                    "UPDATE transcript_segment SET text = 'changed after gate'"
                    " WHERE id = %s",
                    (seeded.segment_ids[0],),
                )
        return viewable

    monkeypatch.setattr(moments_api, "meeting_evidence_complete", gate_then_commit)
    response = client.get(f"/meetings/{seeded.meeting_id}/moments")

    assert writer_ran
    assert response.status_code == 200, response.text
    assert response.json()["moments"][0]["preview"] == "Everybody, good morning."
    with test_pool.connection() as conn:
        assert conn.execute(
            "SELECT text FROM transcript_segment WHERE id = %s",
            (seeded.segment_ids[0],),
        ).fetchone()[0] == "changed after gate"


def test_a_live_moment_covering_no_segments_still_appears_in_the_list(
    client, test_pool
) -> None:
    """The preview LATERAL is a LEFT join: a screen-derived span nobody spoke
    in has no covered segment, and an inner join would silently drop it."""
    seeded = _seed(test_pool, source_id="source-uncovered")
    with test_pool.connection() as conn:
        conn.execute(
            "DELETE FROM moment_segment WHERE moment_id = %s",
            (seeded.moment_ids[1],),
        )

    listed = client.get(f"/meetings/{seeded.meeting_id}/moments").json()["moments"]
    assert [item["momentId"] for item in listed] == [
        str(moment_id) for moment_id in seeded.moment_ids
    ]
    uncovered = listed[1]
    assert uncovered["preview"] is None
    # The stored count, untouched: this test removed links, not the column —
    # only the `moments` stage may square the two (and it does, on supersede).
    assert uncovered["segmentCount"] == 2


def test_moments_sharing_a_start_break_the_tie_on_id(client, test_pool) -> None:
    """`ORDER BY start_ms, id`: UUIDv7 ids break ties in mint order."""
    seeded = _seed(test_pool, source_id="source-tiebreak")
    first_start = 2_000  # the seed's first moment starts here
    with test_pool.connection() as conn:
        # A screen-derived moment landing on the same instant — exactly what
        # augmentation produces — minted after, so its UUIDv7 sorts after.
        rival_id = conn.execute(
            "INSERT INTO moment (meeting_id, identity_key, derived_from,"
            " start_ms, end_ms, started_at, started_at_precision, segment_count)"
            " VALUES (%s, %s, 'screen', %s, %s, %s, 'second', 0) RETURNING id",
            (seeded.meeting_id, f"screen:{first_start}", first_start, 5_000, STARTED_AT),
        ).fetchone()[0]

    listed = client.get(f"/meetings/{seeded.meeting_id}/moments").json()["moments"]
    assert [item["momentId"] for item in listed] == [
        str(seeded.moment_ids[0]),
        str(rival_id),
        str(seeded.moment_ids[1]),
    ]


def test_a_transcript_only_meetings_list_rows_carry_the_deep_link(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="source-list-transcript-only", has_recording=False)

    body = client.get(f"/meetings/{seeded.meeting_id}/moments").json()
    assert body["hasRecording"] is False
    assert len(body["moments"]) == 2
    for item in body["moments"]:
        assert item["screenshotId"] is None
        # UX-DR11 in the list too: the recap URL verbatim on every row.
        assert item["sourceDeepLink"] == DEEP_LINK


def test_a_superseded_moment_on_an_unsettled_meeting_is_still_a_409(
    client, test_pool
) -> None:
    """Gate before flag: viewability governs every read of the meeting, so a
    superseded citation answers 409 while augmentation is in flight — never a
    200 that leaks mid-rebuild evidence."""
    seeded = _seed(
        test_pool,
        source_id="source-superseded-unsettled",
        stage_overrides={"moments": "running"},
    )
    _supersede(test_pool, seeded.moment_ids[1])

    response = client.get(f"/moments/{seeded.moment_ids[1]}")
    assert response.status_code == 409, response.text
    assert (
        response.json()["type"] == "urn:meetingminer:problem:meeting-not-viewable"
    )


def test_the_list_preview_is_capped_at_the_declared_bound(client, test_pool) -> None:
    """The wire ships at most PREVIEW_MAX_CHARS of the first segment; the web
    truncates further with CSS. The full text stays on the detail route."""
    long_text = "purchase order " * 40  # 600 chars, well past the cap
    assert len(long_text) > PREVIEW_MAX_CHARS
    seeded = _seed(
        test_pool,
        source_id="source-preview-cap",
        turns=(SeededTurn(1, 2_000, long_text, "Goeke, Timothy", 0),),
    )

    listed = client.get(f"/meetings/{seeded.meeting_id}/moments").json()["moments"]
    assert len(listed) == 1
    assert listed[0]["preview"] == long_text[:PREVIEW_MAX_CHARS]

    # The detail route is deliberately uncapped: the transcript is the point.
    detail = client.get(f"/moments/{seeded.moment_ids[0]}").json()
    assert detail["segments"][0]["text"] == long_text


def test_the_artifact_vocabulary_matches_the_publish_gate_and_cap4() -> None:
    """The rail's forward contract: states are the gate's, kinds are CAP-4's
    seven categories. Epic 4 adds rows; these spellings must not move."""
    assert get_args(ArtifactState) == ARTIFACT_STATES
    assert get_args(ArtifactKind) == (
        "action-item",
        "adr",
        "decision",
        "story",
        "requirement",
        "bug-fix",
        "change-request",
    )


# --- story 2.3: GET /meetings/{meetingId}/drilldown ---


def test_the_drilldown_returns_header_series_and_full_transcript(
    client, test_pool
) -> None:
    """The happy row of the matrix: header with the meeting-level deep link,
    screenshots in `ordinal` order with their stored classification, the full
    transcript with each segment naming its covering moment."""
    seeded = _seed(
        test_pool,
        source_id="source-drilldown",
        screen_identity_keys=("sha256:dd-slide", "sha256:dd-gallery"),
        screen_view_types=("slide", "participant-gallery"),
    )
    with test_pool.connection() as conn:
        # `screen.label` is the human-editable column (Epic 2); the seed never
        # writes it, so surfacing it takes the UPDATE curation will make.
        conn.execute(
            "UPDATE screen SET label = 'Revenue deck' WHERE id = %s",
            (seeded.screen_ids[0],),
        )
        conn.execute(
            "UPDATE screenshot SET classification_tags = %s WHERE id = %s",
            (["likely-transition", "avatar-gallery-unresolved"], seeded.screenshot_ids[0]),
        )

    response = client.get(f"/meetings/{seeded.meeting_id}/drilldown")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DRILLDOWN_FIELDS
    assert body["meetingId"] == str(seeded.meeting_id)
    assert body["title"] == "Data Hub Demo"
    assert body["hasRecording"] is True
    assert body["corpus"] == "real"
    assert body["startedAtPrecision"] == "second"
    # The meeting-level `provenance->>'url'` verbatim — raw, on every meeting.
    assert body["sourceDeepLink"] == DEEP_LINK

    shots = body["screenshots"]
    assert len(shots) == 2
    for shot in shots:
        assert set(shot) == DRILLDOWN_SCREENSHOT_FIELDS
    assert [shot["ordinal"] for shot in shots] == [1, 2]
    assert [shot["screenshotId"] for shot in shots] == [
        str(screenshot_id) for screenshot_id in seeded.screenshot_ids
    ]
    assert [shot["startOffsetMs"] for shot in shots] == [0, 30_000]
    assert [shot["endOffsetMs"] for shot in shots] == [30_000, 60_000]
    # The stored screenshot.view_type, never the screen's, and the screen's
    # human label only where curation set one.
    assert [shot["viewType"] for shot in shots] == ["slide", "participant-gallery"]
    assert shots[0]["screenLabel"] == "Revenue deck"
    assert shots[1]["screenLabel"] is None
    assert shots[0]["path"] == f"meetings/{seeded.meeting_id}/screenshots/1.jpg"
    assert shots[0]["classificationTags"] == [
        "likely-transition",
        "avatar-gallery-unresolved",
    ]
    # The live moment carrying each screenshot: the seed points moment 0 at
    # screenshot 1 and moment 1 at screenshot 2.
    assert [shot["momentId"] for shot in shots] == [
        str(moment_id) for moment_id in seeded.moment_ids
    ]

    segments = body["segments"]
    assert len(segments) == 5
    for segment in segments:
        assert set(segment) == DRILLDOWN_SEGMENT_FIELDS
    assert [segment["ordinal"] for segment in segments] == [1, 2, 3, 4, 5]
    assert [segment["segmentId"] for segment in segments] == [
        str(segment_id) for segment_id in seeded.segment_ids
    ]
    assert segments[0]["text"] == "Everybody, good morning."
    assert segments[0]["speakerLabel"] == "Goeke, Timothy"
    assert segments[0]["speakerResolution"] == "resolved"
    assert segments[0]["participantId"] == str(seeded.participant_ids[0])
    # Segment -> moment through `moment_segment`: the first three turns sit in
    # moment 0, the two after the 30s gap in moment 1.
    assert [segment["momentId"] for segment in segments] == [
        str(seeded.moment_ids[0])
    ] * 3 + [str(seeded.moment_ids[1])] * 2


def test_a_transcript_only_drilldown_is_series_free_with_the_deep_link(
    client, test_pool
) -> None:
    seeded = _seed(
        test_pool, source_id="source-drilldown-transcript-only", has_recording=False
    )

    response = client.get(f"/meetings/{seeded.meeting_id}/drilldown")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hasRecording"] is False
    assert body["screenshots"] == []
    # UX-DR11 at meeting level: the recap URL stands in for the series.
    assert body["sourceDeepLink"] == DEEP_LINK
    assert len(body["segments"]) == 5
    assert body["segments"][0]["momentId"] == str(seeded.moment_ids[0])


def test_an_uncovered_segment_is_listed_with_a_null_moment(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="source-drilldown-uncovered")
    with test_pool.connection() as conn:
        conn.execute(
            "DELETE FROM moment_segment WHERE transcript_segment_id = %s",
            (seeded.segment_ids[3],),
        )

    body = client.get(f"/meetings/{seeded.meeting_id}/drilldown").json()
    assert [segment["momentId"] for segment in body["segments"]] == [
        str(seeded.moment_ids[0]),
        str(seeded.moment_ids[0]),
        str(seeded.moment_ids[0]),
        None,
        str(seeded.moment_ids[1]),
    ]


def test_a_screen_derived_moment_with_no_segments_labels_its_screenshot(
    client, test_pool
) -> None:
    """A live moment can name a screenshot and cover nothing spoken; the
    series row still carries it, the transcript stays unclaimed."""
    seeded = _seed(test_pool, source_id="source-drilldown-screen", with_moments=False)
    with test_pool.connection() as conn:
        screen_moment_id = conn.execute(
            "INSERT INTO moment (meeting_id, identity_key, derived_from,"
            " start_ms, end_ms, started_at, started_at_precision, screenshot_id,"
            " segment_count) VALUES (%s, 'screen:0', 'screen', 0, 30000, %s,"
            " 'second', %s, 0) RETURNING id",
            (seeded.meeting_id, STARTED_AT, seeded.screenshot_ids[0]),
        ).fetchone()[0]

    body = client.get(f"/meetings/{seeded.meeting_id}/drilldown").json()
    assert body["screenshots"][0]["momentId"] == str(screen_moment_id)
    assert body["screenshots"][1]["momentId"] is None
    assert all(segment["momentId"] is None for segment in body["segments"])


def test_a_superseded_moment_never_appears_in_the_drilldown_mappings(
    client, test_pool
) -> None:
    """Supersession keeps the row (and its `screenshot_id`) for citations but
    deletes its links; neither mapping may resurrect it as live."""
    seeded = _seed(test_pool, source_id="source-drilldown-superseded")
    _supersede(test_pool, seeded.moment_ids[1])

    body = client.get(f"/meetings/{seeded.meeting_id}/drilldown").json()
    superseded = str(seeded.moment_ids[1])
    assert superseded not in [shot["momentId"] for shot in body["screenshots"]]
    assert body["screenshots"][1]["momentId"] is None
    assert superseded not in [segment["momentId"] for segment in body["segments"]]
    assert [segment["momentId"] for segment in body["segments"][3:]] == [None, None]


def test_an_unknown_meeting_drilldown_is_a_404_problem(client) -> None:
    response = client.get(f"/meetings/{uuid4()}/drilldown")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_a_first_ingest_in_flight_answers_409_not_augmenting(
    client, test_pool
) -> None:
    """Stages settled in order so far, evidence unsettled: a first ingest."""
    seeded = _seed(
        test_pool,
        source_id="source-drilldown-first-ingest",
        stage_overrides={"moments": "running"},
    )

    response = client.get(f"/meetings/{seeded.meeting_id}/drilldown")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:meeting-not-viewable"
    assert body["meetingId"] == str(seeded.meeting_id)
    assert body["augmenting"] is False
    assert body["jobStatus"] == "running"


def test_an_augmentation_in_flight_answers_409_augmenting(
    client, test_pool
) -> None:
    """Evidence stages re-queued beneath a settled `extract`: out-of-order
    settlement, which only an augmentation produces."""
    seeded = _seed(
        test_pool,
        source_id="source-drilldown-augmenting",
        stage_overrides={"align": "queued", "moments": "queued", "extract": "done"},
    )

    response = client.get(f"/meetings/{seeded.meeting_id}/drilldown")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:meeting-not-viewable"
    assert body["augmenting"] is True
    assert body["jobStatus"] == "running"


def test_both_22_routes_carry_the_enriched_409_extensions(
    client, test_pool
) -> None:
    """The 409 gained `augmenting`/`jobStatus` additively — 2.2's pinned
    `meetingId` and slug unchanged — on every gated route."""
    seeded = _seed(
        test_pool,
        source_id="source-enriched-409",
        stage_overrides={"align": "queued", "moments": "queued", "extract": "done"},
    )

    for path in (
        f"/meetings/{seeded.meeting_id}/moments",
        f"/moments/{seeded.moment_ids[0]}",
    ):
        response = client.get(path)
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["type"] == "urn:meetingminer:problem:meeting-not-viewable"
        assert body["meetingId"] == str(seeded.meeting_id)
        assert body["augmenting"] is True
        assert body["jobStatus"] == "running"


def test_a_malformed_drilldown_id_is_a_422_problem(client) -> None:
    response = client.get("/meetings/not-a-uuid/drilldown")
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_the_drilldown_documents_the_runtime_422_problem_contract(client) -> None:
    schema = client.app.openapi()
    response = schema["paths"]["/meetings/{meeting_id}/drilldown"]["get"]["responses"]["422"]
    assert response["content"] == {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"}
        }
    }


def test_the_drilldown_omits_cross_meeting_evidence_links(client, test_pool) -> None:
    """Individually-valid FKs aimed across meetings must not link another
    meeting's moment into this one's series or transcript — or leak its ids,
    text, or paths — through either new join."""
    seeded = _seed(test_pool, source_id="source-drilldown-contained")
    foreign = _seed(
        test_pool,
        source_id="source-drilldown-foreign",
        title="Foreign meeting",
        screen_identity_keys=("sha256:dd-foreign-a", "sha256:dd-foreign-b"),
        turns=(SeededTurn(1, 2_000, "Foreign drilldown secret.", "Other"),),
    )
    with test_pool.connection() as conn:
        # A foreign meeting's moment claiming this meeting's screenshot.
        conn.execute(
            "UPDATE moment SET screenshot_id = %s WHERE id = %s",
            (seeded.screenshot_ids[0], foreign.moment_ids[0]),
        )
        # This meeting's segment linked to the foreign meeting's moment.
        conn.execute(
            "UPDATE moment_segment SET moment_id = %s"
            " WHERE transcript_segment_id = %s",
            (foreign.moment_ids[0], seeded.segment_ids[0]),
        )

    body = client.get(f"/meetings/{seeded.meeting_id}/drilldown").json()
    foreign_moment = str(foreign.moment_ids[0])
    # The screenshot's live moment stays this meeting's own — the same-meeting
    # guard, not first-writer-wins.
    assert body["screenshots"][0]["momentId"] == str(seeded.moment_ids[0])
    assert foreign_moment not in str(body)
    # The corrupted link answers as uncovered rather than as foreign.
    assert body["segments"][0]["momentId"] is None
    assert "Foreign drilldown secret." not in str(body)
    assert "Foreign meeting" not in str(body)


def test_the_drilldown_reads_a_single_snapshot_across_the_evidence_gate(
    client, test_pool, monkeypatch
) -> None:
    """A writer committing after the gate cannot change this response — the
    same REPEATABLE READ guarantee the 2.2 routes pin."""
    seeded = _seed(test_pool, source_id="source-drilldown-snapshot")
    original_gate = moments_api.meeting_evidence_complete
    writer_ran = False

    def gate_then_commit(conn, meeting_id):
        nonlocal writer_ran
        viewable = original_gate(conn, meeting_id)
        if not writer_ran:
            writer_ran = True
            with test_pool.connection() as writer:
                writer.execute(
                    "UPDATE job_stage SET status = 'running'"
                    " WHERE job_id = %s AND name = 'moments'",
                    (seeded.job_id,),
                )
                writer.execute(
                    "UPDATE transcript_segment SET text = 'changed after gate'"
                    " WHERE id = %s",
                    (seeded.segment_ids[0],),
                )
        return viewable

    monkeypatch.setattr(moments_api, "meeting_evidence_complete", gate_then_commit)
    response = client.get(f"/meetings/{seeded.meeting_id}/drilldown")

    assert writer_ran
    assert response.status_code == 200, response.text
    assert response.json()["segments"][0]["text"] == "Everybody, good morning."
    with test_pool.connection() as conn:
        assert conn.execute(
            "SELECT text FROM transcript_segment WHERE id = %s",
            (seeded.segment_ids[0],),
        ).fetchone()[0] == "changed after gate"


def test_seeded_screens_can_carry_mixed_view_types(test_pool) -> None:
    """The additive seed param writes the given view type to both the screen
    and its screenshot, and the default keeps both 'ui-screen'."""
    seeded = _seed(
        test_pool,
        source_id="source-seed-view-types",
        screen_identity_keys=("sha256:vt-slide", "sha256:vt-gallery"),
        screen_view_types=("slide", "participant-gallery"),
    )
    plain = _seed(test_pool, source_id="source-seed-view-types-default")
    with test_pool.connection() as conn:
        assert [
            row[0]
            for row in conn.execute(
                "SELECT view_type FROM screenshot WHERE meeting_id = %s"
                " ORDER BY ordinal",
                (seeded.meeting_id,),
            ).fetchall()
        ] == ["slide", "participant-gallery"]
        assert [
            row[0]
            for row in conn.execute(
                "SELECT s.view_type FROM screenshot ss JOIN screen s"
                " ON s.id = ss.screen_id WHERE ss.meeting_id = %s"
                " ORDER BY ss.ordinal",
                (seeded.meeting_id,),
            ).fetchall()
        ] == ["slide", "participant-gallery"]
        assert [
            row[0]
            for row in conn.execute(
                "SELECT view_type FROM screenshot WHERE meeting_id = %s"
                " ORDER BY ordinal",
                (plain.meeting_id,),
            ).fetchall()
        ] == ["ui-screen", "ui-screen"]


def test_two_live_moments_sharing_a_screenshot_yield_one_series_row(
    client, test_pool
) -> None:
    """Nothing makes `moment.screenshot_id` unique, so the series LATERAL's
    LIMIT 1 is what keeps one row per screenshot — and its `start_ms, id`
    order pins which moment wins: the earliest live one."""
    seeded = _seed(test_pool, source_id="source-drilldown-shared-shot")
    with test_pool.connection() as conn:
        # A second live moment claiming the first screenshot, cut later —
        # exactly what augmentation can produce.
        rival_id = conn.execute(
            "INSERT INTO moment (meeting_id, identity_key, derived_from,"
            " start_ms, end_ms, started_at, started_at_precision, screenshot_id,"
            " segment_count) VALUES (%s, 'screen:50000', 'screen', 50000, 55000,"
            " %s, 'second', %s, 0) RETURNING id",
            (seeded.meeting_id, STARTED_AT, seeded.screenshot_ids[0]),
        ).fetchone()[0]

    body = client.get(f"/meetings/{seeded.meeting_id}/drilldown").json()
    # Still one row per screenshot, in ordinal order — no fan-out.
    assert [shot["ordinal"] for shot in body["screenshots"]] == [1, 2]
    assert [shot["screenshotId"] for shot in body["screenshots"]] == [
        str(screenshot_id) for screenshot_id in seeded.screenshot_ids
    ]
    # The earlier moment (start_ms 2000 < 50000) wins the tie-break.
    assert body["screenshots"][0]["momentId"] == str(seeded.moment_ids[0])
    assert str(rival_id) not in [shot["momentId"] for shot in body["screenshots"]]


def test_a_failed_first_ingest_409_carries_job_status_failed(
    client, test_pool
) -> None:
    """`jobStatus` is the job row's own status, so a failed ingest is
    distinguishable from one still running — the web's failed copy keys on
    exactly this value."""
    seeded = _seed(
        test_pool,
        source_id="source-drilldown-failed-job",
        stage_overrides={"moments": "failed"},
    )
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE job SET status = 'failed' WHERE id = %s", (seeded.job_id,)
        )

    response = client.get(f"/meetings/{seeded.meeting_id}/drilldown")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:meeting-not-viewable"
    # Stages settled in order so far (the failure is the frontier), so this
    # still reads as a first ingest — just one that will not finish.
    assert body["augmenting"] is False
    assert body["jobStatus"] == "failed"
