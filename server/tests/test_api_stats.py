"""GET /corpus/stats contract tests (story ui-1, SPEC-ui-reimagine CAP-1).

Every number the home screen states must be a database-of-record count, so
each field is asserted against rows this file seeded itself — none may be
decorative, and an empty corpus must read as zeros rather than an error.
"""

from __future__ import annotations

from projection_seed import seed_meeting

STATS_FIELDS = {
    "meetings", "totalDurationMs", "moments", "screens", "screenshots",
    "artifacts", "participants", "publishedDocuments",
}
ARTIFACT_FIELDS = {"total", "byKind", "byState"}


def _seed_artifact(pool, meeting_id, moment_id, *, kind: str, state: str) -> None:
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO artifact (moment_id, meeting_id, kind, state, title, body)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (moment_id, meeting_id, kind, state, f"{kind} title", f"{kind} body"),
        )


def test_empty_corpus_is_all_zeros(client) -> None:
    response = client.get("/corpus/stats")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATS_FIELDS
    assert set(body["artifacts"]) == ARTIFACT_FIELDS
    assert body == {
        "meetings": 0,
        "totalDurationMs": 0,
        "moments": 0,
        "screens": 0,
        "screenshots": 0,
        "artifacts": {"total": 0, "byKind": {}, "byState": {}},
        "participants": 0,
        "publishedDocuments": 0,
    }


def test_counts_are_real_aggregates_over_the_seeded_corpus(client, test_pool) -> None:
    """Two meetings — one recorded, one transcript-only — with artifacts in
    every state: each stat equals what was actually inserted."""
    with test_pool.connection() as conn:
        recorded = seed_meeting(conn, source_id="stats-recorded")
        transcript_only = seed_meeting(
            conn, source_id="stats-transcript-only", has_recording=False
        )
    # Recorded meeting: 2 screens, 2 screenshots, 2 moments, 5 segments
    # (last end 46s), 2 participants. Transcript-only: same but no screens.
    # The two meetings share the two default participants (cross-meeting
    # identity), so the corpus holds 2 people, not 4.
    _seed_artifact(
        test_pool, recorded.meeting_id, recorded.moment_ids[0],
        kind="adr", state="extracted",
    )
    _seed_artifact(
        test_pool, recorded.meeting_id, recorded.moment_ids[1],
        kind="action-item", state="approved",
    )
    _seed_artifact(
        test_pool, transcript_only.meeting_id, transcript_only.moment_ids[0],
        kind="action-item", state="published",
    )

    body = client.get("/corpus/stats").json()
    assert body["meetings"] == 2
    assert body["moments"] == 4
    assert body["screens"] == 2
    assert body["screenshots"] == 2
    assert body["participants"] == 2
    assert body["artifacts"] == {
        "total": 3,
        "byKind": {"adr": 1, "action-item": 2},
        "byState": {"extracted": 1, "approved": 1, "published": 1},
    }
    # Published documents are exactly the artifacts in state 'published'.
    assert body["publishedDocuments"] == 1


def test_duration_prefers_probed_media_and_falls_back_to_transcript_end(
    client, test_pool
) -> None:
    """Evidence duration: `meeting_media.duration_ms` where probed, else the
    last transcript segment's end — a transcript-only meeting holds evidence
    too, and reporting it as zero would be a decorative number."""
    with test_pool.connection() as conn:
        recorded = seed_meeting(conn, source_id="stats-duration-recorded")
        seed_meeting(conn, source_id="stats-duration-to", has_recording=False)
        conn.execute(
            "INSERT INTO meeting_media (meeting_id, duration_ms) VALUES (%s, %s)",
            (recorded.meeting_id, 3_600_000),
        )

    body = client.get("/corpus/stats").json()
    # Recorded meeting counts its probed hour; the transcript-only one counts
    # its last segment end (44s turn start + 2s synthetic end = 46s).
    assert body["totalDurationMs"] == 3_600_000 + 46_000
