"""POST /ingests contract tests (run against meetingminer_test; skip without Postgres)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import meetingminer.api.ingests as ingests_module
from meetingminer.domain.jobs import (
    AUGMENTATION_STAGES,
    PARTICIPANT_AUGMENTATION_STAGES,
    STAGE_NAMES,
    VIDEO_ONLY_STAGES,
)

from meetingminer.domain.drops import drop_relative_path

from conftest import DROPS_ROOT, valid_metadata
from repo_paths import REPO_ROOT

PROBLEM = "application/problem+json"
STAGES = ["probe", "frames", "ocr", "screens", "transcribe", "align", "moments", "extract"]


def test_the_augmentation_stage_set_is_pinned_by_name_and_by_order() -> None:
    """`AUGMENTATION_STAGES` is a comprehension; this is the literal it must equal.

    Every other assertion in the suite states its expectation *in terms of* the
    constant (`ran == list(AUGMENTATION_STAGES)`), so dropping `align` or
    `transcribe` from the comprehension in `domain/jobs.py` would shrink both
    sides together and leave the whole suite green while a recovered recording
    was never transcribed, or never re-merged into the transcript. Pinning the
    literal here is what makes that edit fail — the same job the `STAGES` list
    above does for `STAGE_NAMES`.

    Order matters as much as membership: intake re-queues these and the runner
    walks `STAGE_NAMES` in order, so `align` reading a transcript `transcribe`
    has not written yet is the failure a reordering would cause.
    """
    assert AUGMENTATION_STAGES == (
        "probe",
        "frames",
        "ocr",
        "screens",
        "transcribe",
        "align",
        "moments",
    )
    assert "extract" not in AUGMENTATION_STAGES, (
        "extract is never re-armed by intake: its output carries human"
        " approval a drop must not silently re-propose (story 4.1)"
    )


def test_the_participant_augmentation_stage_set_is_pinned_by_name_and_by_order() -> None:
    """The narrow set: a drop that adds no recording re-runs only these two.

    Pinned as a literal for the same reason as above — every other assertion
    states its expectation in terms of the constant, so widening this
    comprehension to include the video stages would silently make a
    participants-only augmentation re-sample and re-OCR an unchanged recording
    with the whole suite still green, and narrowing it to `align` alone would
    leave every moment describing the roster the meeting had before.
    """
    assert PARTICIPANT_AUGMENTATION_STAGES == ("align", "moments")
    assert set(PARTICIPANT_AUGMENTATION_STAGES) < set(AUGMENTATION_STAGES)
    assert not set(PARTICIPANT_AUGMENTATION_STAGES) & VIDEO_ONLY_STAGES


def _snapshot(drop: Path) -> dict[str, tuple[int, float]]:
    return {
        p.name: (p.stat().st_size, p.stat().st_mtime) for p in sorted(drop.iterdir())
    }


def _job_and_stage_counts(pool) -> tuple[int, int]:
    with pool.connection() as conn:
        jobs = conn.execute("SELECT count(*) FROM job").fetchone()[0]
        stages = conn.execute("SELECT count(*) FROM job_stage").fetchone()[0]
    return jobs, stages


def test_valid_transcript_only_drop_returns_201_with_queued_job(
    client, test_pool, make_drop
) -> None:
    drop = make_drop(files=("transcript.txt",))
    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 201
    job_id = response.json()["jobId"]
    assert set(response.json()) == {"jobId"}

    with test_pool.connection() as conn:
        job = conn.execute(
            "SELECT status, source_id, drop_relative_path, corpus, error FROM job WHERE id = %s",
            (job_id,),
        ).fetchone()
        stage_rows = conn.execute(
            "SELECT name, status FROM job_stage WHERE job_id = %s", (job_id,)
        ).fetchall()

    assert job == ("queued", "source-1", drop.name, "real", None)
    assert sorted(name for name, _ in stage_rows) == sorted(STAGES)
    assert {status for _, status in stage_rows} == {"queued"}


def test_valid_vtt_only_drop_returns_201_with_queued_job(
    client, test_pool, make_drop
) -> None:
    """`transcript.vtt` alone is a canonical, first-class transcript-only drop.

    Teams exports VTT, so this is the shape story 1.8's puller emits most
    often. Without an executable test, dropping `transcript.vtt` from
    `EVIDENCE_FILENAMES` would turn every VTT-only drop into a 422 while the
    suite stayed green.
    """
    drop = make_drop(files=("transcript.vtt",))
    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 201
    job_id = response.json()["jobId"]
    assert set(response.json()) == {"jobId"}

    with test_pool.connection() as conn:
        job = conn.execute(
            "SELECT status, source_id, drop_relative_path, corpus, error FROM job WHERE id = %s",
            (job_id,),
        ).fetchone()
        stage_rows = conn.execute(
            "SELECT name, status FROM job_stage WHERE job_id = %s", (job_id,)
        ).fetchall()

    assert job == ("queued", "source-1", drop.name, "real", None)
    assert sorted(name for name, _ in stage_rows) == sorted(STAGES)
    assert {status for _, status in stage_rows} == {"queued"}


def test_valid_recording_drop_returns_201(client, make_drop) -> None:
    drop = make_drop(files=("recording.mp4",))
    response = client.post("/ingests", json={"dropPath": str(drop)})
    assert response.status_code == 201


def test_drop_with_neither_recording_nor_transcript_is_422_no_rows(
    client, test_pool, make_drop
) -> None:
    drop = make_drop(files=())
    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-drop"
    assert "neither a recording nor a transcript" in body["detail"]
    assert _job_and_stage_counts(test_pool) == (0, 0)


def test_invalid_metadata_is_422_with_violations_and_no_rows(
    client, test_pool, make_drop
) -> None:
    metadata = valid_metadata(corpus="synthetic")
    del metadata["sourceId"]
    drop = make_drop(metadata=metadata)
    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-drop"
    assert "sourceId" in body["detail"]
    assert "corpus" in body["detail"]
    assert len(body["violations"]) == 2
    assert _job_and_stage_counts(test_pool) == (0, 0)


def test_metadata_not_json_is_422(client, make_drop) -> None:
    drop = make_drop(raw_metadata="{not json")
    response = client.post("/ingests", json={"dropPath": str(drop)})
    assert response.status_code == 422
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-drop"


def test_missing_metadata_file_is_422(client, make_drop) -> None:
    drop = make_drop(omit_metadata=True, files=("transcript.txt",))
    response = client.post("/ingests", json={"dropPath": str(drop)})
    assert response.status_code == 422
    assert "metadata.json" in response.json()["detail"]


def test_bad_drop_paths_are_400_naming_the_problem(
    client, test_pool, tmp_path
) -> None:
    a_file = tmp_path / "not-a-dir.txt"
    a_file.write_text("x", encoding="utf-8")

    for drop_path, expected in [
        (str(tmp_path / "missing"), "does not exist"),
        (str(a_file), "not a directory"),
        ("relative/drop", "absolute"),
    ]:
        response = client.post("/ingests", json={"dropPath": drop_path})
        assert response.status_code == 400, drop_path
        assert response.headers["content-type"] == PROBLEM
        body = response.json()
        assert body["type"] == "urn:meetingminer:problem:invalid-drop-path"
        assert expected in body["detail"]
    assert _job_and_stage_counts(test_pool) == (0, 0)


def test_duplicate_source_id_is_409_with_existing_job_id(client, make_drop) -> None:
    first = client.post("/ingests", json={"dropPath": str(make_drop())})
    assert first.status_code == 201
    job_id = first.json()["jobId"]

    second = client.post("/ingests", json={"dropPath": str(make_drop())})
    assert second.status_code == 409
    assert second.headers["content-type"] == PROBLEM
    body = second.json()
    assert body["type"] == "urn:meetingminer:problem:duplicate-source"
    assert body["jobId"] == job_id


def test_failed_job_resubmit_requeues_in_place_with_same_id(
    client, test_pool, make_drop
) -> None:
    first = client.post("/ingests", json={"dropPath": str(make_drop())})
    job_id = first.json()["jobId"]

    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE job SET status = 'failed', error = 'probe blew up' WHERE id = %s",
            (job_id,),
        )
        conn.execute(
            "UPDATE job_stage SET status = 'failed', error = 'boom'"
            " WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        )

    resubmit = client.post("/ingests", json={"dropPath": str(make_drop())})
    assert resubmit.status_code == 200
    assert resubmit.json() == {"jobId": job_id}

    with test_pool.connection() as conn:
        job_count = conn.execute("SELECT count(*) FROM job").fetchone()[0]
        status, error = conn.execute(
            "SELECT status, error FROM job WHERE id = %s", (job_id,)
        ).fetchone()
        stage_states = conn.execute(
            "SELECT DISTINCT status, error FROM job_stage WHERE job_id = %s", (job_id,)
        ).fetchall()

    assert job_count == 1  # never a second job row per sourceId
    assert (status, error) == ("queued", None)
    assert stage_states == [("queued", None)]


def test_failed_post_mint_compatible_retry_requeues_the_same_job(
    client, test_pool, make_drop
) -> None:
    """A transcript-only Meeting still accepts a compatible plain retry."""
    source_id = "failed-after-mint-compatible"
    target_drop = make_drop(
        metadata=valid_metadata(source_id), files=("transcript.txt",)
    )
    job_id, _meeting_id = _ingested_occurrence(
        test_pool, source_id, target_drop, job_status="failed"
    )
    before_drop = _snapshot(target_drop)
    replacement = make_drop(
        metadata=valid_metadata(source_id), files=("transcript.txt",)
    )

    response = client.post("/ingests", json={"dropPath": str(replacement)})

    assert response.status_code == 200
    assert response.json() == {"jobId": str(job_id)}
    assert _job_row(test_pool, job_id) == (
        "queued", source_id, replacement.name, "real", None
    )
    assert _stage_map(test_pool, job_id) == {name: "queued" for name in STAGES}
    assert _job_and_stage_counts(test_pool) == (1, len(STAGES))
    assert _snapshot(target_drop) == before_drop


@pytest.mark.parametrize(
    (
        "target_overrides",
        "meeting_overrides",
        "replacement_overrides",
        "replacement_files",
        "expected_detail",
    ),
    [
        ({}, {}, {}, ("recording.mp4",), "transcript.txt"),
        ({}, {}, {"corpus": "scripted"}, ("transcript.txt",), "corpus"),
        (
            {},
            {},
            {"startedAt": "2026-08-05T13:30:00Z"},
            ("transcript.txt",),
            "startedAt",
        ),
        (
            {
                "startedAt": "2026-08-05T00:00:00Z",
                "startedAtPrecision": "day",
            },
            {
                "started_at": "2026-08-05T00:00:00Z",
                "started_at_precision": "day",
            },
            {
                "startedAt": "2026-08-05T00:00:00Z",
                "startedAtPrecision": "second",
            },
            ("transcript.txt",),
            "startedAtPrecision",
        ),
    ],
)
def test_failed_post_mint_retry_preserves_the_existing_meeting(
    client,
    test_pool,
    make_drop,
    target_overrides,
    meeting_overrides,
    replacement_overrides,
    replacement_files,
    expected_detail,
) -> None:
    """Plain retries cannot erase provided transcripts or rewrite identity."""
    source_id = "failed-after-mint"
    target_drop = make_drop(
        metadata=valid_metadata(source_id, **target_overrides), files=("transcript.txt",)
    )
    job_id, _meeting_id = _ingested_occurrence(
        test_pool, source_id, target_drop, job_status="failed", **meeting_overrides
    )
    before_job = _job_row(test_pool, job_id)
    before_stages = _stage_map(test_pool, job_id)
    before_drop = _snapshot(target_drop)

    replacement = make_drop(
        metadata=valid_metadata(source_id, **replacement_overrides),
        files=replacement_files,
    )
    response = client.post("/ingests", json={"dropPath": str(replacement)})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-augmenting-drop"
    assert expected_detail in body["detail"]
    assert _job_row(test_pool, job_id) == before_job
    assert _stage_map(test_pool, job_id) == before_stages
    assert _snapshot(target_drop) == before_drop


def test_failed_augmentation_cannot_downgrade_a_recorded_meeting(
    client, test_pool, make_drop
) -> None:
    """A failed late-recording augmentation must keep its recovered recording."""
    source_id = "failed-augmentation"
    augmented_drop = make_drop(
        metadata=valid_metadata(source_id), files=("transcript.txt", "recording.mp4")
    )
    job_id, _meeting_id = _ingested_occurrence(
        test_pool,
        source_id,
        augmented_drop,
        has_recording=True,
        job_status="failed",
    )
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'failed', error = 'augmentation failed'"
            " WHERE job_id = %s AND name = 'frames'",
            (job_id,),
        )
    before_job = _job_row(test_pool, job_id)
    before_stages = _stage_map(test_pool, job_id)
    before_drop = _snapshot(augmented_drop)
    transcript_only_retry = make_drop(
        metadata=valid_metadata(source_id), files=("transcript.txt",)
    )

    response = client.post(
        "/ingests", json={"dropPath": str(transcript_only_retry)}
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-augmenting-drop"
    assert "recorded meeting" in body["detail"]
    assert _job_row(test_pool, job_id) == before_job
    assert _stage_map(test_pool, job_id) == before_stages
    assert _snapshot(augmented_drop) == before_drop


def test_insert_race_lost_returns_409_with_winner_job_id(
    client, make_drop, monkeypatch
) -> None:
    """A competing live row committed between pre-check and INSERT → 409."""
    import meetingminer.api.ingests as api_ingests

    winner = client.post(
        "/ingests", json={"dropPath": str(make_drop(metadata=valid_metadata("race-1")))}
    )
    assert winner.status_code == 201
    winner_id = winner.json()["jobId"]

    # Blind this request's pre-check so it reaches the INSERT and loses the
    # race against the committed live row.
    monkeypatch.setattr(api_ingests, "_select_jobs", lambda conn, source_id: [])

    loser = client.post(
        "/ingests", json={"dropPath": str(make_drop(metadata=valid_metadata("race-1")))}
    )
    assert loser.status_code == 409
    assert loser.headers["content-type"] == PROBLEM
    body = loser.json()
    assert body["type"] == "urn:meetingminer:problem:duplicate-source"
    assert body["jobId"] == winner_id


def test_requeue_race_lost_returns_409_with_winner_job_id(
    client, test_pool, make_drop, monkeypatch
) -> None:
    """A live row appearing between pre-check and the re-queue UPDATE → 409."""
    import meetingminer.api.ingests as api_ingests

    with test_pool.connection() as conn:
        failed_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus, status, error)"
            " VALUES ('race-2', 'old-drop', 'real', 'failed', 'boom') RETURNING id",
        ).fetchone()[0]
        live_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
            " VALUES ('race-2', 'new-drop', 'real', 'queued') RETURNING id",
        ).fetchone()[0]

    # Pre-check sees only the failed row, so the request takes the re-queue
    # path; its UPDATE then collides with the committed live row.
    monkeypatch.setattr(
        api_ingests,
        "_select_jobs",
        lambda conn, source_id: [(failed_id, "failed")],
    )

    response = client.post(
        "/ingests", json={"dropPath": str(make_drop(metadata=valid_metadata("race-2")))}
    )
    assert response.status_code == 409
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:duplicate-source"
    assert body["jobId"] == str(live_id)

    with test_pool.connection() as conn:
        status = conn.execute(
            "SELECT status FROM job WHERE id = %s", (failed_id,)
        ).fetchone()[0]
    assert status == "failed"  # the lost re-queue rolled back cleanly


def test_unknown_files_in_drop_are_ignored_and_drop_untouched(
    client, make_drop
) -> None:
    drop = make_drop(files=("transcript.txt", "recording.mp4"))
    (drop / "summary.md").write_text("# notes", encoding="utf-8")
    (drop / "minutes.docx").write_bytes(b"docx")
    (drop / "_source.json").write_text(json.dumps({"pulledAt": "x"}), encoding="utf-8")
    before = _snapshot(drop)

    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 201
    assert _snapshot(drop) == before  # intake never writes into the drop (AD-13)


# --- story 1.12: a recording recovered after a transcript-only ingest -------


def _ingested_occurrence(
    pool,
    source_id: str,
    drop_path: Path,
    *,
    corpus: str = "real",
    has_recording: bool = False,
    stage_overrides: dict[str, str] | None = None,
    with_meeting: bool = True,
    job_status: str = "running",
    started_at: str = "2026-08-05T12:00:19Z",
    started_at_precision: str = "second",
) -> tuple[str, str | None]:
    """An occurrence the worker has already carried to evidence-complete.

    The shape intake resolves an `augments` declaration against: a non-failed
    job whose stages have settled and whose Meeting row exists. `running` with
    `extract` still `queued` is a legitimate state — a job mid-extraction, or
    one left at the pre-4.1 pause — and intake gates on `evidence_complete()`
    rather than `job.status = 'done'` precisely so it never has to wait for
    the extraction stage.
    """
    with pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
            " VALUES (%s, %s, %s, %s) RETURNING id",
            (source_id, drop_relative_path(DROPS_ROOT, drop_path), corpus, job_status),
        ).fetchone()[0]
        for name in STAGE_NAMES:
            if stage_overrides and name in stage_overrides:
                status = stage_overrides[name]
            elif name == "extract":
                status = "queued"
            elif not has_recording and name in VIDEO_ONLY_STAGES:
                status = "skipped"
            else:
                status = "done"
            conn.execute(
                "INSERT INTO job_stage (job_id, name, status) VALUES (%s, %s, %s)",
                (job_id, name, status),
            )
        meeting_id = None
        if with_meeting:
            meeting_id = conn.execute(
                "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
                " started_at_precision, title, has_recording, provenance)"
                " VALUES (%s, %s, %s, %s, %s,"
                " 'Daily Standup', %s, '{}'::jsonb) RETURNING id",
                (
                    job_id,
                    source_id,
                    corpus,
                    started_at,
                    started_at_precision,
                    has_recording,
                ),
            ).fetchone()[0]
    return job_id, meeting_id


def _augmenting_metadata(
    target_source_id: str, source_id: str | None = None, **overrides
) -> dict:
    return valid_metadata(
        source_id if source_id is not None else target_source_id,
        schemaVersion=2,
        augments={"sourceId": target_source_id},
        **overrides,
    )


def _job_row(pool, job_id) -> tuple:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT status, source_id, drop_relative_path, corpus, error FROM job WHERE id = %s",
            (job_id,),
        ).fetchone()


def _stage_map(pool, job_id) -> dict[str, str]:
    with pool.connection() as conn:
        return dict(
            conn.execute(
                "SELECT name, status FROM job_stage WHERE job_id = %s", (job_id,)
            ).fetchall()
        )


def _stage_updated_at(pool, job_id) -> dict[str, Any]:
    with pool.connection() as conn:
        return dict(
            conn.execute(
                "SELECT name, updated_at FROM job_stage WHERE job_id = %s", (job_id,)
            ).fetchall()
        )


def test_augmenting_drop_rearms_the_existing_job_and_returns_200(
    client, test_pool, make_drop
) -> None:
    """The AC: a recovered recording is accepted, not answered with a conflict.

    And it re-arms the occurrence's *existing* job — same jobId, same
    `source_id` — because `meeting.job_id` and `meeting.source_id` are UNIQUE,
    so a second job could never own the meeting (AD-14). Keeping the job keeps
    the meeting id, which is what keeps every moment id and citation valid.
    """
    target_drop = make_drop(
        metadata=valid_metadata("occ-late"), files=("transcript.txt",)
    )
    job_id, _meeting_id = _ingested_occurrence(test_pool, "occ-late", target_drop)
    before_drop = _snapshot(target_drop)
    before_stages = _stage_updated_at(test_pool, job_id)
    assert _stage_map(test_pool, job_id) == {
        "probe": "skipped", "frames": "skipped", "ocr": "skipped",
        "screens": "skipped", "transcribe": "skipped",
        "align": "done", "moments": "done", "extract": "queued",
    }

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-late"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 200
    assert response.json() == {"jobId": str(job_id)}

    assert _job_row(test_pool, job_id) == (
        "queued", "occ-late", augmenting.name, "real", None
    )
    # Every stage the recovered recording invalidates is back to `queued`: the
    # five the transcript-only ingest recorded as `skipped`, plus `align` and
    # `moments`, which were `done`. `extract` reads `queued` here too, but it
    # read `queued` before the re-arm as well, so this row proves nothing about
    # it either way.
    assert _stage_map(test_pool, job_id) == {
        "probe": "queued", "frames": "queued", "ocr": "queued",
        "screens": "queued", "transcribe": "queued",
        "align": "queued", "moments": "queued", "extract": "queued",
    }
    # This is what shows `extract` kept the checkpoint it had: its row was not
    # written at all, so whatever status it carried would have survived.
    after_stages = _stage_updated_at(test_pool, job_id)
    changed = {
        name for name in STAGES if after_stages[name] != before_stages[name]
    }
    assert changed == set(AUGMENTATION_STAGES), "extract's row was never written"

    assert _job_and_stage_counts(test_pool) == (1, len(STAGES)), "no second job row"
    # AD-1: the already-finalized drop is never modified or deleted. Write-once
    # applies to the drop, not to the meeting.
    assert _snapshot(target_drop) == before_drop


def test_an_augmenting_drop_may_carry_its_own_source_id(
    client, test_pool, make_drop
) -> None:
    """The declaration is the link, not the drop's own identity (AD-1).

    A recording recovered from the recorder's personal drive carries its own
    drive-item id; the job keeps the occurrence's sourceId regardless.
    """
    target_drop = make_drop(metadata=valid_metadata("occ-own-id"), files=("transcript.txt",))
    job_id, _ = _ingested_occurrence(test_pool, "occ-own-id", target_drop)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-own-id", source_id="drive-item-recovered"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 200
    assert response.json()["jobId"] == str(job_id)
    status, source_id, drop_path, _corpus, _error = _job_row(test_pool, job_id)
    assert (status, source_id, drop_path) == ("queued", "occ-own-id", augmenting.name)
    assert _job_and_stage_counts(test_pool) == (1, len(STAGES))


def test_an_augmenting_drop_whose_own_source_id_is_live_elsewhere_is_409(
    client, test_pool, make_drop
) -> None:
    """One drop may not claim two occurrences."""
    target_drop = make_drop(metadata=valid_metadata("occ-a"), files=("transcript.txt",))
    _ingested_occurrence(test_pool, "occ-a", target_drop)
    other_drop = make_drop(metadata=valid_metadata("occ-b"), files=("transcript.txt",))
    other_job, _ = _ingested_occurrence(test_pool, "occ-b", other_drop)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-a", source_id="occ-b"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:duplicate-source"
    assert body["jobId"] == str(other_job)


def test_augmenting_an_occurrence_that_does_not_exist_is_422(
    client, test_pool, make_drop
) -> None:
    augmenting = make_drop(
        metadata=_augmenting_metadata("never-ingested"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "urn:meetingminer:problem:unknown-augment-target"
    assert _job_and_stage_counts(test_pool) == (0, 0), "no job was opened"


def test_augmenting_a_job_that_has_no_meeting_yet_is_422(
    client, test_pool, make_drop
) -> None:
    """A queued job is not an occurrence — there is nothing to augment yet."""
    target_drop = make_drop(metadata=valid_metadata("occ-unminted"), files=("transcript.txt",))
    _ingested_occurrence(
        test_pool,
        "occ-unminted",
        target_drop,
        with_meeting=False,
        job_status="queued",
        stage_overrides={name: "queued" for name in STAGES},
    )

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-unminted"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    assert response.json()["type"] == "urn:meetingminer:problem:unknown-augment-target"


def test_augmenting_a_failed_occurrence_is_422(client, test_pool, make_drop) -> None:
    """A failed job's own re-queue path already accepts a replacement drop."""
    target_drop = make_drop(metadata=valid_metadata("occ-failed"), files=("transcript.txt",))
    _ingested_occurrence(test_pool, "occ-failed", target_drop, job_status="failed")

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-failed"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    assert response.json()["type"] == "urn:meetingminer:problem:unknown-augment-target"


def test_augmenting_an_occurrence_still_ingesting_is_409(
    client, test_pool, make_drop
) -> None:
    target_drop = make_drop(metadata=valid_metadata("occ-busy"), files=("transcript.txt",))
    job_id, _ = _ingested_occurrence(
        test_pool, "occ-busy", target_drop, stage_overrides={"moments": "queued"}
    )
    before = _job_row(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-busy"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:augment-target-incomplete"
    assert body["jobId"] == str(job_id)
    assert _job_row(test_pool, job_id) == before, "the refusal changed nothing"


def test_a_participants_only_augmenting_drop_rearms_only_align_and_moments(
    client, test_pool, make_drop
) -> None:
    """Story 1.13's intake AC: the participant graph is evidence too.

    The occurrence was ingested from a drop with no `participants` key, so every
    person in it is keyed on how their name was typed. A drop that brings the
    graph adds evidence the meeting lacks, so it is accepted — and only the two
    stages that consume the graph go back to `queued`, because re-sampling and
    re-OCRing an unchanged recording would re-derive identical frames at real
    cost.
    """
    target_drop = make_drop(
        metadata=valid_metadata("occ-graph"), files=("transcript.txt", "recording.mp4")
    )
    job_id, _ = _ingested_occurrence(
        test_pool, "occ-graph", target_drop, has_recording=True
    )
    before_stages = _stage_updated_at(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata(
            "occ-graph",
            participants=[
                {"displayName": "Maplewood, Micah (CNTR)", "mail": "micah.maplewood@contoso.com"},
                {"displayName": "Tremaine, Kendall", "mail": "kendall.tremaine@contoso.com"},
            ],
        ),
        # The recording comes along because the meeting has one: a replacement
        # for a recorded meeting may not shed it (`_check_meeting_replacement`).
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 200
    assert response.json() == {"jobId": str(job_id)}
    assert _job_row(test_pool, job_id) == (
        "queued", "occ-graph", augmenting.name, "real", None
    )
    assert _stage_map(test_pool, job_id) == {
        "probe": "done", "frames": "done", "ocr": "done",
        "screens": "done", "transcribe": "done",
        "align": "queued", "moments": "queued", "extract": "queued",
    }
    after_stages = _stage_updated_at(test_pool, job_id)
    changed = {name for name in STAGES if after_stages[name] != before_stages[name]}
    assert changed == set(PARTICIPANT_AUGMENTATION_STAGES)
    assert _job_and_stage_counts(test_pool) == (1, len(STAGES)), "no second job row"


def test_an_augmenting_drop_that_adds_nothing_is_409(
    client, test_pool, make_drop
) -> None:
    """The door is "brings evidence this occurrence lacks", and this brings none.

    The occurrence already has a recording and its drop already carries the
    participant graph, so re-arming would re-derive the bundle it already has —
    409 under its own problem type: nothing about the drop is invalid — the
    identical drop would be accepted against an occurrence that still lacked
    this evidence — so what refuses it is the target's current state. Same
    status as the `augment-target-has-recording` refusal this supersedes.
    """
    graph = [{"displayName": "Maplewood, Micah (CNTR)", "mail": "micah.maplewood@contoso.com"}]
    target_drop = make_drop(
        metadata=valid_metadata("occ-nothing-new", participants=graph),
        files=("recording.mp4",),
    )
    job_id, _ = _ingested_occurrence(
        test_pool, "occ-nothing-new", target_drop, has_recording=True
    )
    before = _job_row(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-nothing-new", participants=graph),
        files=("recording.mp4",),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:augment-adds-nothing"
    assert body["jobId"] == str(job_id)
    # Both halves of "nothing new" are named, so the refusal says what to fix.
    assert "already has a recording" in body["detail"]
    assert "already carries a participants array" in body["detail"]
    assert _job_row(test_pool, job_id) == before


def test_an_augmenting_drop_with_neither_a_recording_nor_a_graph_is_409(
    client, test_pool, make_drop
) -> None:
    """The other way to add nothing: a transcript-only re-statement."""
    target_drop = make_drop(metadata=valid_metadata("occ-norec"), files=("transcript.txt",))
    job_id, _ = _ingested_occurrence(test_pool, "occ-norec", target_drop)
    before = _job_row(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-norec"), files=("transcript.txt",)
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:augment-adds-nothing"
    assert body["jobId"] == str(job_id)
    assert "carries no recording.mp4" in body["detail"]
    assert "carries no participants array" in body["detail"]
    assert _job_row(test_pool, job_id) == before


def test_an_empty_participants_array_is_not_a_graph_on_either_side(
    client, test_pool, make_drop
) -> None:
    """`[]` asserts "the source found nobody"; it neither adds nor duplicates.

    `align` reads an empty array as an assertion and does *not* fall back to
    transcript labels, so a drop carrying one brings no participants to add —
    and a target carrying one has no graph a later drop would be repeating.
    Both directions are checked here, because getting either wrong silently
    breaks the migration: the first would accept a no-op re-arm, the second
    would refuse the drop that finally supplies the real roster.
    """
    # Direction 1: an empty array on the incoming drop adds nothing.
    bare = make_drop(metadata=valid_metadata("occ-empty-in"), files=("transcript.txt",))
    job_id, _ = _ingested_occurrence(test_pool, "occ-empty-in", bare)
    before = _job_row(test_pool, job_id)
    empty = make_drop(
        metadata=_augmenting_metadata("occ-empty-in", participants=[]),
        files=("transcript.txt",),
    )
    refused = client.post("/ingests", json={"dropPath": str(empty)})
    assert refused.status_code == 409
    assert refused.json()["type"] == "urn:meetingminer:problem:augment-adds-nothing"
    assert _job_row(test_pool, job_id) == before

    # Direction 2: an empty array on the target does not block a real graph.
    target = make_drop(
        metadata=valid_metadata("occ-empty-target", participants=[]),
        files=("transcript.txt",),
    )
    target_job, _ = _ingested_occurrence(test_pool, "occ-empty-target", target)
    real = make_drop(
        metadata=_augmenting_metadata(
            "occ-empty-target",
            participants=[{"displayName": "Maplewood, Micah (CNTR)"}],
        ),
        files=("transcript.txt",),
    )
    accepted = client.post("/ingests", json={"dropPath": str(real)})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["jobId"] == str(target_job)


def test_a_participants_drop_may_not_downgrade_a_recorded_meeting(
    client, test_pool, make_drop
) -> None:
    """Widening the door must not weaken the Meeting-preservation checks.

    The graph is new evidence, so the drop passes the "adds something" gate —
    and is then refused anyway, because it would take the meeting's recording
    away with it. That guard is what the target's *real* `has_recording` now
    feeds; before story 1.13 it was hard-coded to False and unreachable here.
    """
    target_drop = make_drop(
        metadata=valid_metadata("occ-no-downgrade"), files=("transcript.txt", "recording.mp4")
    )
    job_id, _ = _ingested_occurrence(
        test_pool, "occ-no-downgrade", target_drop, has_recording=True
    )
    before = _job_row(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata(
            "occ-no-downgrade",
            participants=[{"displayName": "Maplewood, Micah (CNTR)"}],
        ),
        files=("transcript.txt",),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-augmenting-drop"
    assert "recording.mp4" in body["detail"]
    assert _job_row(test_pool, job_id) == before


def test_a_recording_recovery_may_not_shed_an_existing_participant_graph(
    client, test_pool, make_drop
) -> None:
    graph = [{"displayName": "Maplewood, Micah (CNTR)", "mail": "micah.maplewood@contoso.com"}]
    target_drop = make_drop(
        metadata=valid_metadata("occ-preserve-graph", participants=graph), files=("transcript.txt",)
    )
    _ingested_occurrence(test_pool, "occ-preserve-graph", target_drop)
    incoming = make_drop(
        metadata=_augmenting_metadata("occ-preserve-graph"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(incoming)})
    assert response.status_code == 422
    assert "participant graph" in response.json()["detail"]


def test_a_participant_augmentation_may_not_replace_an_existing_recording(
    client, test_pool, make_drop
) -> None:
    target_drop = make_drop(
        metadata=valid_metadata("occ-preserve-recording"),
        files=("transcript.txt", "recording.mp4"),
    )
    _ingested_occurrence(
        test_pool, "occ-preserve-recording", target_drop, has_recording=True
    )
    incoming = make_drop(
        metadata=_augmenting_metadata(
            "occ-preserve-recording", participants=[{"displayName": "Maplewood, Micah (CNTR)"}]
        ),
        files=("transcript.txt", "recording.mp4"),
    )
    (incoming / "recording.mp4").write_bytes(b"different recording bytes")
    response = client.post("/ingests", json={"dropPath": str(incoming)})
    assert response.status_code == 422
    assert "same recording.mp4" in response.json()["detail"]


def test_an_augmenting_drop_that_sheds_a_transcript_is_422(
    client, test_pool, make_drop
) -> None:
    """AD-13: `align` deletes the row for a provided kind that is gone.

    A recording-only augmenting drop would therefore erase the provided
    transcript and move every boundary derived from it, superseding every
    existing moment. Refusing at the door is what protects it.
    """
    target_drop = make_drop(
        metadata=valid_metadata("occ-shed"), files=("transcript.txt", "transcript.vtt")
    )
    job_id, _ = _ingested_occurrence(test_pool, "occ-shed", target_drop)
    before = _job_row(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-shed"),
        files=("recording.mp4", "transcript.vtt"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-augmenting-drop"
    assert "transcript.txt" in body["detail"]
    assert _job_row(test_pool, job_id) == before


def test_an_augmenting_drop_whose_target_drop_is_unreadable_is_422(
    client, test_pool, make_drop
) -> None:
    """"No transcripts found" and "cannot tell" must not be the same answer."""
    target_drop = make_drop(metadata=valid_metadata("occ-gone"), files=("transcript.txt",))
    job_id, _ = _ingested_occurrence(
        test_pool, "occ-gone", target_drop / "does-not-exist"
    )

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-gone"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-augmenting-drop"
    assert _job_row(test_pool, job_id)[0] == "running"


def test_an_augmenting_drop_with_a_different_corpus_is_422(
    client, test_pool, make_drop
) -> None:
    """`corpus` decides whether a meeting is an eval subject (AD-1)."""
    target_drop = make_drop(
        metadata=valid_metadata("occ-corpus", corpus="scripted"), files=("transcript.txt",)
    )
    job_id, _ = _ingested_occurrence(
        test_pool, "occ-corpus", target_drop, corpus="scripted"
    )
    before = _job_row(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-corpus", corpus="real"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-augmenting-drop"
    assert "corpus" in body["detail"]
    assert _job_row(test_pool, job_id) == before


def test_an_augmenting_drop_with_a_different_started_at_is_422(
    client, test_pool, make_drop
) -> None:
    """The meeting's wall clock is the origin every moment's start hangs off.

    `mint_meeting`'s ON CONFLICT rewrites `meeting.started_at` from whichever
    drop the job points at, and `moments` re-stamps each moment's absolute
    `started_at` as `meeting.started_at + start_ms`. An augmenting drop with a
    different `startedAt` would silently move exactly the moments whose ids
    augmentation exists to preserve, so it is refused at the door.
    """
    target_drop = make_drop(
        metadata=valid_metadata("occ-clock"), files=("transcript.txt",)
    )
    job_id, _ = _ingested_occurrence(test_pool, "occ-clock", target_drop)
    before = _job_row(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-clock", startedAt="2026-08-05T13:30:00Z"),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-augmenting-drop"
    assert "startedAt" in body["detail"]
    assert _job_row(test_pool, job_id) == before, "the refusal changed nothing"


def test_an_augmenting_drop_with_a_different_started_at_precision_is_422(
    client, test_pool, make_drop
) -> None:
    """Same instant, different precision, is still a rewrite of the clock.

    `started_at_precision` is stamped onto every moment beside its start, so a
    drop that promotes a `day`-precision meeting to `second` would relabel every
    preserved moment's timestamp as something it is not.
    """
    target_drop = make_drop(
        metadata=valid_metadata(
            "occ-precision",
            startedAt="2026-08-05T00:00:00Z",
            startedAtPrecision="day",
        ),
        files=("transcript.txt",),
    )
    job_id, _ = _ingested_occurrence(
        test_pool,
        "occ-precision",
        target_drop,
        started_at="2026-08-05T00:00:00Z",
        started_at_precision="day",
    )
    before = _job_row(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata(
            "occ-precision",
            startedAt="2026-08-05T00:00:00Z",
            startedAtPrecision="second",
        ),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-augmenting-drop"
    assert "startedAtPrecision" in body["detail"]
    assert _job_row(test_pool, job_id) == before, "the refusal changed nothing"


def test_an_augmenting_drop_may_restate_the_title(client, test_pool, make_drop) -> None:
    """The descriptive fields are deliberately *not* pinned.

    Nothing is keyed on `title` or `provenance`, the recovered recording is the
    better source for both, and the provenance deep link retires anyway once a
    screenshot replaces it (UX-DR11). Only the clock fields are refused. The
    matching half of this — the meeting's title actually changing while every
    preserved moment's id and `started_at` stay put — is in
    `test_augmentation.py`.
    """
    target_drop = make_drop(
        metadata=valid_metadata("occ-retitled"), files=("transcript.txt",)
    )
    job_id, _ = _ingested_occurrence(test_pool, "occ-retitled", target_drop)

    augmenting = make_drop(
        metadata=_augmenting_metadata(
            "occ-retitled",
            provenance={"title": "Daily Standup (recording recovered)"},
        ),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(augmenting)})

    assert response.status_code == 200
    assert response.json() == {"jobId": str(job_id)}


def test_a_second_drop_without_augments_is_still_a_duplicate_conflict(
    client, test_pool, make_drop
) -> None:
    """The augmentation branch must not weaken the plain duplicate rule."""
    target_drop = make_drop(metadata=valid_metadata("occ-plain"), files=("transcript.txt",))
    job_id, _ = _ingested_occurrence(test_pool, "occ-plain", target_drop)

    second = make_drop(
        metadata=valid_metadata("occ-plain"), files=("transcript.txt", "recording.mp4")
    )
    response = client.post("/ingests", json={"dropPath": str(second)})

    assert response.status_code == 409
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:duplicate-source"
    assert body["jobId"] == str(job_id)


def test_a_version_1_drop_declaring_augments_is_rejected_as_invalid(
    client, test_pool, make_drop
) -> None:
    """Fail-closed at the schema, before any of the augmentation logic runs."""
    drop = make_drop(
        metadata=valid_metadata("occ-v1", augments={"sourceId": "occ-v1"}),
        files=("transcript.txt", "recording.mp4"),
    )
    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-drop"
    assert body["violations"]
    assert _job_and_stage_counts(test_pool) == (0, 0)


# --- story 2-6: source-drop schema reloaded on change ------------------------
#
# The api loads docs/source-drop.schema.json once at startup; on 2026-08-19 a
# stale in-process copy refused 28 drops the on-disk schema accepted, for six
# hours, presenting a process fault as `422 invalid-drop`. `_validator()` now
# re-stats the file per ingest and reloads on change, failing *closed* (500,
# `drop-schema-unreadable`) when the new content cannot be loaded. These tests
# install a temp copy of the schema and restore module state — they never write
# to the repo's real docs/source-drop.schema.json.

REAL_SCHEMA_TEXT = (
    REPO_ROOT / "docs" / "source-drop.schema.json"
).read_text(encoding="utf-8")


# Monotonic floor for `_write_schema`'s mtime bumps. Bumping relative to a
# write's own observed mtime is not enough: on a filesystem with coarse
# timestamp granularity, two same-size writes could observe the same tick and
# be issued the same bumped value. Remembering the last issued value makes
# every consecutive write carry a strictly increasing — hence distinct —
# mtime_ns.
_LAST_ISSUED_MTIME_NS = 0


def _write_schema(path: Path, text: str) -> None:
    """Write schema content with a guaranteed-new, strictly increasing mtime.

    The reload trigger is the (st_mtime_ns, st_size, st_ino) signature; the
    explicit bump makes the mtime half of the change deterministic regardless
    of filesystem timestamp granularity.
    """
    global _LAST_ISSUED_MTIME_NS
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    _LAST_ISSUED_MTIME_NS = max(stat.st_mtime_ns, _LAST_ISSUED_MTIME_NS + 1_000_000)
    os.utime(path, ns=(stat.st_atime_ns, _LAST_ISSUED_MTIME_NS))


def _version_1_only_schema() -> str:
    """The incident's stale shape: the real schema with the enum pinned at [1]."""
    schema = json.loads(REAL_SCHEMA_TEXT)
    schema["properties"]["schemaVersion"]["enum"] = [1]
    return json.dumps(schema)


def _same_size_version_1_only_schema() -> str:
    """The version-1-only schema, padded so atomic replacement keeps its size."""
    replacement = REAL_SCHEMA_TEXT.replace(
        '"enum": [1, 2, 3]', '"enum": [1]      ', 1
    )
    assert replacement != REAL_SCHEMA_TEXT, (
        "the enum spelling this pads moved; without a real substitution the"
        " replacement schema is identical to the real one and this test proves"
        " nothing"
    )
    assert len(replacement.encode("utf-8")) == len(REAL_SCHEMA_TEXT.encode("utf-8"))
    return replacement


@pytest.fixture()
def schema_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp copy of the real drop schema, installed as the loaded schema.

    `monkeypatch.setattr` records the module's current `_SCHEMA` (the real
    repo copy installed when `api.main` was imported) and restores it at
    teardown, so no test leaks a temp path into the rest of the suite.
    """
    monkeypatch.setattr(ingests_module, "_SCHEMA", ingests_module._SCHEMA)
    path = tmp_path / "source-drop.schema.json"
    path.write_text(REAL_SCHEMA_TEXT, encoding="utf-8")
    ingests_module.install_drop_schema(path)
    return path


def test_schema_widened_on_disk_is_picked_up_without_a_restart(
    client, make_drop, schema_file
) -> None:
    """The incident, replayed: the loaded copy pins schemaVersion at [1], the
    on-disk file is widened to the real schema, and the *same* POST that was
    refused is accepted — no restart in between."""
    _write_schema(schema_file, _version_1_only_schema())
    drop = make_drop(metadata=valid_metadata("reload-widen", schemaVersion=2))

    refused = client.post("/ingests", json={"dropPath": str(drop)})
    assert refused.status_code == 422
    assert refused.json()["type"] == "urn:meetingminer:problem:invalid-drop"

    _write_schema(schema_file, REAL_SCHEMA_TEXT)
    accepted = client.post("/ingests", json={"dropPath": str(drop)})
    assert accepted.status_code == 201


def test_schema_tightened_on_disk_refuses_on_the_next_request(
    client, make_drop, schema_file
) -> None:
    """The other direction: a runtime tightening takes effect immediately, and
    the 422 cites the *new* schema's violation."""
    before = make_drop(metadata=valid_metadata("tighten-before", schemaVersion=2))
    assert client.post("/ingests", json={"dropPath": str(before)}).status_code == 201

    _write_schema(schema_file, _version_1_only_schema())
    after = make_drop(metadata=valid_metadata("tighten-after", schemaVersion=2))
    response = client.post("/ingests", json={"dropPath": str(after)})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-drop"
    assert any("schemaVersion" in v for v in body["violations"])


def test_an_unchanged_schema_file_is_not_reparsed_between_ingests(
    client, make_drop, schema_file
) -> None:
    """The reload check is a stat, not a read: same mtime_ns and size must
    reuse the installed validator object itself."""
    first = make_drop(metadata=valid_metadata("reuse-1"))
    assert client.post("/ingests", json={"dropPath": str(first)}).status_code == 201
    validator = ingests_module._SCHEMA.validator

    second = make_drop(metadata=valid_metadata("reuse-2"))
    assert client.post("/ingests", json={"dropPath": str(second)}).status_code == 201

    assert ingests_module._SCHEMA.validator is validator


def test_a_size_change_alone_triggers_the_reload_when_mtime_is_preserved(
    client, make_drop, schema_file
) -> None:
    """The size half of the signature, pinned on its own: content replaced
    in-place (same inode) with the ORIGINAL mtime_ns restored — a `cp -p`-style
    deploy — must still reload, and the new schema's verdict must apply."""
    original = schema_file.stat()
    tightened = _version_1_only_schema()
    assert len(tightened.encode("utf-8")) != original.st_size

    schema_file.write_text(tightened, encoding="utf-8")
    os.utime(schema_file, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert schema_file.stat().st_mtime_ns == original.st_mtime_ns

    drop = make_drop(metadata=valid_metadata("size-only", schemaVersion=2))
    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 422
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-drop"


def test_an_atomic_same_size_same_mtime_schema_replacement_triggers_the_reload(
    client, make_drop, schema_file, tmp_path
) -> None:
    """The inode half of the signature catches a metadata-preserving rename."""
    original = schema_file.stat()
    replacement = tmp_path / "replacement-schema.json"
    replacement.write_text(_same_size_version_1_only_schema(), encoding="utf-8")
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    os.replace(replacement, schema_file)
    installed = schema_file.stat()
    assert installed.st_size == original.st_size
    assert installed.st_mtime_ns == original.st_mtime_ns
    assert installed.st_ino != original.st_ino

    drop = make_drop(metadata=valid_metadata("inode-change", schemaVersion=2))
    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 422
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-drop"


@pytest.mark.parametrize(
    "sabotage",
    [
        pytest.param(
            lambda path: _write_schema(path, "{ this is not json"),
            id="invalid-json",
        ),
        pytest.param(
            lambda path: _write_schema(path, json.dumps({"type": 42})),
            id="invalid-schema",
        ),
        pytest.param(lambda path: _write_schema(path, "true"), id="boolean-schema"),
        pytest.param(lambda path: path.unlink(), id="file-deleted"),
        pytest.param(
            lambda path: _write_schema(
                path, json.dumps({"$ref": "https://meetingminer.invalid/drop.json"})
            ),
            id="unresolvable-reference",
        ),
    ],
)
def test_an_unloadable_schema_fails_closed_as_500_never_as_invalid_drop(
    client, test_pool, make_drop, schema_file, sabotage, capsys
) -> None:
    """When the schema itself cannot be loaded, no judgment about the drop is
    possible: the refusal blames the server and names the schema file."""
    sabotage(schema_file)
    drop = make_drop(metadata=valid_metadata("fail-closed"))
    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 500
    assert response.status_code != 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:drop-schema-unreadable"
    assert str(schema_file) in body["detail"]
    assert _job_and_stage_counts(test_pool) == (0, 0)
    events = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if '"drop_schema_load_failed"' in line
    ]
    assert len(events) == 1
    assert events[0]["event"] == "drop_schema_load_failed"
    assert events[0]["path"] == str(schema_file)
    assert events[0]["error"]


def test_an_unloadable_schema_precedes_malformed_metadata(
    client, test_pool, make_drop, schema_file
) -> None:
    """The schema's own failure is never misreported as a drop failure."""
    schema_file.unlink()
    drop = make_drop(metadata=valid_metadata("schema-precedence"))
    (drop / "metadata.json").write_text("{ malformed", encoding="utf-8")

    response = client.post("/ingests", json={"dropPath": str(drop)})

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:drop-schema-unreadable"
    assert _job_and_stage_counts(test_pool) == (0, 0)


def test_a_repaired_schema_recovers_on_the_next_request_without_a_restart(
    client, make_drop, schema_file
) -> None:
    """A failed reload leaves the old record in place, so restoring the file
    is the whole fix — the next POST validates normally."""
    schema_file.unlink()
    drop = make_drop(metadata=valid_metadata("recovery"))
    failed = client.post("/ingests", json={"dropPath": str(drop)})
    assert failed.status_code == 500
    assert failed.json()["type"] == "urn:meetingminer:problem:drop-schema-unreadable"

    _write_schema(schema_file, REAL_SCHEMA_TEXT)
    recovered = client.post("/ingests", json={"dropPath": str(drop)})
    assert recovered.status_code == 201


def test_every_schema_reload_emits_one_drop_schema_loaded_event(
    client, make_drop, schema_file, capsys
) -> None:
    """One stdout JSON event per (re)load — path, schemaId, mtime, mtimeNs,
    size — so "which copy got loaded" is observable; an unchanged file emits
    none. `mtimeNs` is the exact integer the reload check keys on; the ISO
    `mtime` is the human-readable form and loses precision to float division."""
    _write_schema(schema_file, REAL_SCHEMA_TEXT)
    capsys.readouterr()  # discard the fixture install's own event

    first = make_drop(metadata=valid_metadata("observed-1"))
    assert client.post("/ingests", json={"dropPath": str(first)}).status_code == 201

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if '"drop_schema_loaded"' in line
    ]
    assert len(events) == 1
    event = events[0]
    stat = schema_file.stat()
    assert event["event"] == "drop_schema_loaded"
    assert event["path"] == str(schema_file)
    assert event["schemaId"] == json.loads(REAL_SCHEMA_TEXT)["$id"]
    assert event["size"] == stat.st_size
    assert event["mtimeNs"] == stat.st_mtime_ns
    assert event["mtime"] == datetime.fromtimestamp(
        stat.st_mtime_ns / 1_000_000_000, tz=timezone.utc
    ).isoformat()

    # An unchanged file on the next ingest reloads nothing and logs nothing.
    second = make_drop(metadata=valid_metadata("observed-2"))
    assert client.post("/ingests", json={"dropPath": str(second)}).status_code == 201
    assert '"drop_schema_loaded"' not in capsys.readouterr().out
