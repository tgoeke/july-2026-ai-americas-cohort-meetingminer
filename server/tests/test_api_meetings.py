"""GET /meetings contract tests (run against meetingminer_test; skip without Postgres).

The two things a future refactor is most likely to break silently are the
viewability gate and the shape of the stage list, so both are pinned here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from meetingminer.domain.jobs import EVIDENCE_STAGES, STAGE_NAMES, VIDEO_ONLY_STAGES

ITEM_FIELDS = {
    "jobId", "meetingId", "title", "sourceId", "corpus", "startedAt",
    "startedAtPrecision", "hasRecording", "status", "error", "stages", "viewable",
    # Evidence-card roll-ups (story ui-1, SPEC-ui-reimagine CAP-1).
    "durationMs", "posterScreenshotId", "posterScreenshotPath",
    "momentCount", "screenshotCount", "artifactCount", "participantCount",
}


def _submit(client, make_drop, source_id: str = "source-1", **metadata: Any) -> str:
    from conftest import valid_metadata

    drop = make_drop(valid_metadata(source_id, **metadata))
    response = client.post("/ingests", json={"dropPath": str(drop)})
    assert response.status_code == 201, response.text
    return response.json()["jobId"]


def _set_stages(pool, job_id: str, status: str, names: tuple[str, ...]) -> None:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = %s WHERE job_id = %s AND name = ANY(%s)",
            (status, job_id, list(names)),
        )


def _mint_meeting(pool, job_id: str, *, title: str, has_recording: bool) -> str:
    """Stand in for the worker's meeting mint (the api never writes these rows)."""
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO meeting"
            " (job_id, source_id, corpus, started_at, started_at_precision,"
            "  title, has_recording)"
            " SELECT j.id, j.source_id, j.corpus, '2026-08-05T12:00:19Z', 'second',"
            "        %s, %s FROM job j WHERE j.id = %s"
            " RETURNING id",
            (title, has_recording, job_id),
        ).fetchone()
    return str(row[0])


def _item(client, job_id: str) -> dict[str, Any]:
    body = client.get("/meetings").json()
    matches = [row for row in body["meetings"] if row["jobId"] == job_id]
    assert len(matches) == 1, f"expected exactly one row for {job_id}, got {matches}"
    return matches[0]


def test_empty_corpus_returns_an_empty_list(client) -> None:
    response = client.get("/meetings")
    assert response.status_code == 200
    assert response.json() == {"meetings": []}


def test_queued_job_appears_before_any_meeting_row_exists(client, make_drop) -> None:
    job_id = _submit(client, make_drop)

    item = _item(client, job_id)
    assert set(item) == ITEM_FIELDS
    assert item["status"] == "queued"
    assert item["sourceId"] == "source-1"
    assert item["corpus"] == "real"
    # No worker has claimed it, so there is no meeting yet — and no title.
    assert item["meetingId"] is None
    assert item["title"] is None
    assert item["startedAt"] is None
    assert item["hasRecording"] is None
    assert item["viewable"] is False
    assert [stage["name"] for stage in item["stages"]] == list(STAGE_NAMES)
    assert all(stage["status"] == "queued" for stage in item["stages"])


def test_meeting_columns_appear_once_the_row_is_minted(client, test_pool, make_drop) -> None:
    job_id = _submit(client, make_drop)
    meeting_id = _mint_meeting(test_pool, job_id, title="Daily Standup", has_recording=True)

    item = _item(client, job_id)
    assert item["meetingId"] == meeting_id
    assert item["title"] == "Daily Standup"
    assert item["hasRecording"] is True
    assert item["startedAtPrecision"] == "second"
    assert item["startedAt"].startswith("2026-08-05T12:00:19")


def test_list_is_newest_first(client, make_drop) -> None:
    first = _submit(client, make_drop, source_id="source-a")
    second = _submit(client, make_drop, source_id="source-b")
    third = _submit(client, make_drop, source_id="source-c")

    ordered = [row["jobId"] for row in client.get("/meetings").json()["meetings"]]
    assert ordered == [third, second, first]


def test_viewable_is_false_until_moments_settles(client, test_pool, make_drop) -> None:
    job_id = _submit(client, make_drop)

    _set_stages(test_pool, job_id, "done", EVIDENCE_STAGES[:-1])
    assert _item(client, job_id)["viewable"] is False, "moments still queued"

    _set_stages(test_pool, job_id, "done", ("moments",))
    assert _item(client, job_id)["viewable"] is True


def test_transcript_only_skipped_stages_are_settled_not_failed(
    client, test_pool, make_drop
) -> None:
    """A transcript-only drop's video stages are `skipped`, and it is viewable."""
    job_id = _submit(client, make_drop)
    _set_stages(test_pool, job_id, "skipped", tuple(VIDEO_ONLY_STAGES))
    _set_stages(test_pool, job_id, "done", ("align", "moments"))
    _mint_meeting(test_pool, job_id, title="Transcript Only", has_recording=False)

    item = _item(client, job_id)
    statuses = {stage["name"]: stage["status"] for stage in item["stages"]}
    assert {statuses[name] for name in VIDEO_ONLY_STAGES} == {"skipped"}
    assert "failed" not in statuses.values()
    assert item["hasRecording"] is False
    assert item["viewable"] is True


def test_job_paused_at_extract_is_viewable_and_shows_no_failure(
    client, test_pool, make_drop
) -> None:
    """Evidence done, `extract` still queued — a job mid-extraction, or a
    pre-4.1 job left at the old pause — with the job still running.

    Gating on `job.status = 'done'` would make this meeting unopenable for
    the whole extraction run, which is the reason `evidence_complete` exists.
    """
    job_id = _submit(client, make_drop)
    _set_stages(test_pool, job_id, "done", EVIDENCE_STAGES)
    with test_pool.connection() as conn:
        conn.execute("UPDATE job SET status = 'running' WHERE id = %s", (job_id,))

    item = _item(client, job_id)
    statuses = {stage["name"]: stage["status"] for stage in item["stages"]}
    assert item["status"] == "running"
    assert statuses["extract"] == "queued"
    assert "failed" not in statuses.values()
    assert item["viewable"] is True


def test_failed_stage_surfaces_its_recorded_error_verbatim(
    client, test_pool, make_drop
) -> None:
    job_id = _submit(client, make_drop)
    recorded = "ffprobe exited 1: moov atom not found"
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'failed', error = %s"
            " WHERE job_id = %s AND name = 'probe'",
            (recorded, job_id),
        )
        conn.execute(
            "UPDATE job SET status = 'failed', error = %s WHERE id = %s",
            (f"stage probe failed: {recorded}", job_id),
        )

    item = _item(client, job_id)
    probe = next(stage for stage in item["stages"] if stage["name"] == "probe")
    assert probe["status"] == "failed"
    assert probe["error"] == recorded
    assert item["status"] == "failed"
    assert item["viewable"] is False


def test_requeued_job_keeps_one_row_with_reset_stages(client, test_pool, make_drop) -> None:
    """A re-queued failed job is the same row, visibly reset — never a second one."""
    from conftest import valid_metadata

    drop = make_drop(valid_metadata("source-1"))
    job_id = client.post("/ingests", json={"dropPath": str(drop)}).json()["jobId"]
    with test_pool.connection() as conn:
        conn.execute("UPDATE job SET status = 'failed' WHERE id = %s", (job_id,))
        conn.execute(
            "UPDATE job_stage SET status = 'failed', error = 'boom'"
            " WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        )

    again = client.post("/ingests", json={"dropPath": str(drop)})
    assert again.status_code in (200, 201), again.text
    assert again.json()["jobId"] == job_id

    body = client.get("/meetings").json()["meetings"]
    assert [row["jobId"] for row in body] == [job_id]
    assert body[0]["status"] == "queued"
    assert all(stage["status"] == "queued" for stage in body[0]["stages"])
    assert all(stage["error"] is None for stage in body[0]["stages"])


def test_stages_come_back_in_pipeline_order_not_insertion_order(
    client, test_pool, make_drop
) -> None:
    job_id = _submit(client, make_drop)
    # Re-insert the checkpoints in reverse so row order cannot accidentally
    # match pipeline order.
    with test_pool.connection() as conn:
        conn.execute("DELETE FROM job_stage WHERE job_id = %s", (job_id,))
        for name in reversed(STAGE_NAMES):
            conn.execute(
                "INSERT INTO job_stage (job_id, name) VALUES (%s, %s)", (job_id, name)
            )

    item = _item(client, job_id)
    assert [stage["name"] for stage in item["stages"]] == list(STAGE_NAMES)


def test_job_id_is_a_uuid(client, make_drop) -> None:
    job_id = _submit(client, make_drop)
    UUID(_item(client, job_id)["jobId"])


def test_a_job_with_no_stage_rows_still_appears_with_an_empty_stage_list(
    client, test_pool, make_drop
) -> None:
    """The LEFT JOIN's NULL-stage branch, which nothing else reaches.

    The endpoint groups rows by job and skips NULL stage columns; without that
    guard a checkpoint-less job would either vanish from the list or come back
    carrying one nameless stage.
    """
    job_id = _submit(client, make_drop, source_id="source-a")
    _submit(client, make_drop, source_id="source-b")
    with test_pool.connection() as conn:
        conn.execute("DELETE FROM job_stage WHERE job_id = %s", (job_id,))

    item = _item(client, job_id)
    assert item["stages"] == []
    assert item["viewable"] is False
    # The job with checkpoints is unaffected by its neighbour's missing ones.
    other = client.get("/meetings").json()["meetings"]
    assert len(other) == 2
    assert any(len(row["stages"]) == len(STAGE_NAMES) for row in other)


# --- evidence-card roll-ups (story ui-1, SPEC-ui-reimagine CAP-1) ----------


def test_rollups_are_empty_before_any_evidence_exists(client, make_drop) -> None:
    """A queued job's card holds no evidence yet: null duration and poster
    (never a fabricated zero-length recording), zero counts."""
    job_id = _submit(client, make_drop)

    item = _item(client, job_id)
    assert item["durationMs"] is None
    assert item["posterScreenshotId"] is None
    assert item["posterScreenshotPath"] is None
    assert item["momentCount"] == 0
    assert item["screenshotCount"] == 0
    assert item["artifactCount"] == 0
    assert item["participantCount"] == 0


def test_rollups_count_the_seeded_evidence(client, test_pool) -> None:
    from projection_seed import seed_meeting

    with test_pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rollup-counts")
        conn.execute(
            "INSERT INTO artifact (moment_id, meeting_id, kind, title, body)"
            " VALUES (%s, %s, 'adr', 'a title', 'a body')",
            (seeded.moment_ids[0], seeded.meeting_id),
        )

    item = _item(client, str(seeded.job_id))
    # The default seeded bundle: 2 moments, 2 screenshots, 2 participants.
    assert item["momentCount"] == 2
    assert item["screenshotCount"] == 2
    assert item["artifactCount"] == 1
    assert item["participantCount"] == 2
    # No probe row yet, so duration is the last transcript segment's end
    # (44s turn start + 2s synthetic end).
    assert item["durationMs"] == 46_000
    # The first (ordinal-1) capture fronts the card, path riding along for
    # `GET /media/{path}`.
    assert item["posterScreenshotId"] == str(seeded.screenshot_ids[0])
    assert item["posterScreenshotPath"] == (
        f"meetings/{seeded.meeting_id}/screenshots/1.jpg"
    )


def test_duration_prefers_the_probed_recording(client, test_pool) -> None:
    from projection_seed import seed_meeting

    with test_pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rollup-duration")
        conn.execute(
            "INSERT INTO meeting_media (meeting_id, duration_ms) VALUES (%s, %s)",
            (seeded.meeting_id, 3_421_000),
        )

    assert _item(client, str(seeded.job_id))["durationMs"] == 3_421_000


def test_poster_prefers_a_non_gallery_capture(client, test_pool) -> None:
    """Webcam tiles front a card only when nothing else was captured: a
    later slide beats an earlier participant-gallery."""
    from projection_seed import seed_meeting

    with test_pool.connection() as conn:
        seeded = seed_meeting(
            conn,
            source_id="rollup-poster",
            screen_identity_keys=("sha256:gallery", "sha256:slide"),
            screen_view_types=("participant-gallery", "slide"),
        )

    item = _item(client, str(seeded.job_id))
    assert item["posterScreenshotId"] == str(seeded.screenshot_ids[1])
