"""`moments` end to end: the story 1.6 I/O matrix's DB-backed rows.

Kept beside `test_worker_transcripts.py` rather than inside it: this file is
entirely about the moment bundle — where the timeline is cut, what evidence
each cut names, and the idempotence rule that makes a moment id a durable
citation target (AD-6).

DB-backed, so these skip with a named reason when the compose Postgres is down;
the ones that need a real recording additionally depend on the ffmpeg-generated
fixture and skip when ffmpeg is absent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import pytest
from psycopg_pool import ConnectionPool

from meetingminer import logs
from meetingminer.config import AppConfig
from meetingminer.domain.drops import read_drop
from meetingminer.pipeline import runner
from meetingminer.pipeline.stage import StageContext
from meetingminer.pipeline.stages import moments as moments_stage

from conftest import (
    DROPS_ROOT,
    DropFactory,
    FakeOcr,
    REAL_PROVENANCE_PULLED,
    TEAMS_TRANSCRIPT,
    requires_ffmpeg,
    truncate_evidence,
    valid_metadata,
)
from test_worker_runner import (
    SCREEN_A,
    enqueue,
    job_row,
    meetings,
    set_job_status,
    set_stage,
    stage_statuses,
)
from test_worker_transcripts import segments as transcript_segments


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    """The test database with every job/evidence table emptied."""
    truncate_evidence(test_pool)
    return test_pool


@pytest.fixture()
def make_transcript_drop(make_drop: DropFactory) -> Callable[..., Path]:
    """A transcript-only drop, optionally with a rewritten provenance record."""

    def _make(source_id: str, text: str = TEAMS_TRANSCRIPT, **overrides: Any) -> Path:
        drop = make_drop(metadata=valid_metadata(source_id, **overrides), files=())
        (drop / "transcript.txt").write_text(text, encoding="utf-8")
        return drop

    return _make


@pytest.fixture()
def make_recording_transcript_drop(
    make_drop: DropFactory, synthetic_recording: Path
) -> Callable[..., Path]:
    """A drop carrying a real (generated) recording plus a transcript."""

    def _make(source_id: str, text: str = TEAMS_TRANSCRIPT, **overrides: Any) -> Path:
        drop = make_drop(metadata=valid_metadata(source_id, **overrides), files=())
        (drop / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
        (drop / "transcript.txt").write_text(text, encoding="utf-8")
        return drop

    return _make


# --- readers ---------------------------------------------------------------

MOMENT_KEYS = (
    "id",
    "identity_key",
    "derived_from",
    "start_ms",
    "end_ms",
    "started_at",
    "started_at_precision",
    "screenshot_id",
    "source_deep_link",
    "segment_count",
    "provenance",
)


def moment_rows(pool: ConnectionPool, meeting_id: UUID) -> list[dict[str, Any]]:
    """This meeting's moments in timeline order — which is `start_ms`, because
    the table deliberately has no ordinal column."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, identity_key, derived_from, start_ms, end_ms, started_at,"
            " started_at_precision, screenshot_id, source_deep_link, segment_count,"
            " provenance FROM moment WHERE meeting_id = %s ORDER BY start_ms",
            (meeting_id,),
        ).fetchall()
    return [dict(zip(MOMENT_KEYS, row)) for row in rows]


def covered_segment_ids(pool: ConnectionPool, moment_id: UUID) -> list[UUID]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT transcript_segment_id FROM moment_segment WHERE moment_id = %s",
            (moment_id,),
        ).fetchall()
    return [row[0] for row in rows]


def all_links(pool: ConnectionPool, meeting_id: UUID) -> list[tuple[UUID, UUID]]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT ms.moment_id, ms.transcript_segment_id FROM moment_segment ms"
            " JOIN moment m ON m.id = ms.moment_id WHERE m.meeting_id = %s",
            (meeting_id,),
        ).fetchall()


def insert_screenshot(
    pool: ConnectionPool, meeting_id: UUID, ordinal: int, start_ms: int, end_ms: int
) -> UUID:
    """A `screenshot` row of the shape `screens` writes, without running it.

    Story 1.12's flow (a recording recovered after a transcript-only ingest)
    has no implementation yet, so the augmentation tests introduce the
    screenshot directly and re-run only this stage.
    """
    with pool.connection() as conn:
        screen_id = conn.execute(
            "INSERT INTO screen (identity_key, signature, view_type)"
            " VALUES (%s, %s, 'slide') RETURNING id",
            (f"test:{meeting_id}:{ordinal}", f"signature {ordinal}"),
        ).fetchone()[0]
        return conn.execute(
            "INSERT INTO screenshot ("
            "  meeting_id, screen_id, ordinal, start_offset_ms, end_offset_ms,"
            "  frame_count, path, view_type"
            ") VALUES (%s, %s, %s, %s, %s, 1, %s, 'slide') RETURNING id",
            (
                meeting_id,
                screen_id,
                ordinal,
                start_ms,
                end_ms,
                f"meetings/{meeting_id}/screenshots/screenshot-{ordinal:04d}.jpg",
            ),
        ).fetchone()[0]


def run_moments_only(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    job_id: UUID,
    drop_path: Path,
    meeting_id: UUID,
) -> None:
    """Run just the `moments` stage over an existing meeting.

    Deliberately not through `runner.run_once`: a transcript-only claim runs
    `_clear_replaced_video_evidence`, which deletes exactly the screenshots
    these augmentation tests are introducing.
    """
    drop = read_drop(drop_path, config_path=app_config.config_path)
    with pool.connection() as conn:
        moments_stage.run(
            StageContext(
                conn=conn,
                config=app_config,
                job_id=job_id,
                meeting_id=meeting_id,
                drop=drop,
                content_root=content_root,
                drops_root=DROPS_ROOT,
                log=logs.bind(job_id=job_id, stage="moments"),
            )
        )
        conn.commit()


def rerun_moments(
    pool: ConnectionPool, app_config: AppConfig, content_root: Path, job_id: UUID
) -> None:
    """Put the job back to `moments` and advance it again through the runner."""
    set_stage(pool, job_id, "moments", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True


def moment_updated_at(pool: ConnectionPool, meeting_id: UUID) -> dict[UUID, Any]:
    """Each moment's `updated_at`, the trigger-maintained proof it was upserted."""
    with pool.connection() as conn:
        return dict(
            conn.execute(
                "SELECT id, updated_at FROM moment WHERE meeting_id = %s", (meeting_id,)
            ).fetchall()
        )


def shift_segments(pool: ConnectionPool, meeting_id: UUID, delta_ms: int) -> None:
    """Move every transcript segment, as a re-derived transcript would.

    `align` replaces this meeting's segments wholesale on a rerun, so from the
    `moments` stage's point of view a changed transcript is exactly this: the
    same meeting with its boundaries somewhere else.
    """
    with pool.connection() as conn:
        conn.execute(
            "UPDATE transcript_segment SET start_ms = start_ms + %s,"
            " end_ms = end_ms + %s WHERE meeting_id = %s",
            (delta_ms, delta_ms, meeting_id),
        )


def only_meeting(pool: ConnectionPool, job_id: UUID) -> dict[str, Any]:
    [meeting] = meetings(pool, job_id)
    return meeting


def stage_log(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    records = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    [record] = [r for r in records if r["event"] == "stage.moments.identified"]
    return record


# --- transcript-only meetings ---------------------------------------------


def test_a_transcript_only_drop_derives_moments_carrying_the_source_deep_link(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """Matrix: transcript-only meeting. No screenshot, a deep link on every row."""
    job_id = enqueue(
        pool, make_transcript_drop("source-moments-txt"), "source-moments-txt"
    )

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["align"] == "done" and statuses["moments"] == "done"
    # `extract` (story 4.1) completes on the autouse zero-artifact fake, so
    # the job reaches `done`.
    assert statuses["extract"] == "done"
    assert job_row(pool, job_id) == ("done", None)

    meeting = only_meeting(pool, job_id)
    rows = moment_rows(pool, meeting["id"])
    # The three turns sit 2s/5s/9s apart — well under any sane gap — so the
    # whole meeting is one moment anchored at the first turn.
    [moment] = rows
    assert moment["identity_key"] == "transcript:2000"
    assert moment["derived_from"] == "transcript"
    assert moment["start_ms"] == 2_000
    assert moment["screenshot_id"] is None
    assert moment["source_deep_link"] == REAL_PROVENANCE_PULLED["url"]
    assert moment["provenance"]["boundary"] == "first-segment"
    assert moment["provenance"]["config"] == {
        "gap_seconds": app_config.settings.pipeline.moments.gap_seconds,
        "max_duration_ms": app_config.settings.pipeline.moments.max_duration_ms,
    }

    # ISO 8601 UTC wall clock: the meeting's own start plus the offset, with
    # the meeting's precision carried alongside.
    assert moment["started_at_precision"] == meeting["started_at_precision"]
    assert (
        moment["started_at"] - meeting["started_at"]
    ).total_seconds() * 1000 == moment["start_ms"]

    written = transcript_segments(pool, meeting["id"])
    assert moment["segment_count"] == len(written) == 3
    assert sorted(covered_segment_ids(pool, moment["id"]), key=str) == sorted(
        _segment_ids(pool, meeting["id"]), key=str
    )


def _segment_ids(pool: ConnectionPool, meeting_id: UUID) -> list[UUID]:
    with pool.connection() as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT id FROM transcript_segment WHERE meeting_id = %s", (meeting_id,)
            ).fetchall()
        ]


def test_a_long_silence_and_a_long_block_each_open_their_own_moment(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """Matrix: silence gap and max-duration, over a real parsed transcript."""
    lines = ["[0:00] Goeke, Timothy: Opening remarks."]
    # A quiet minute, then continuous talk every 10s past the three-minute cap.
    lines.append("[1:00] Whitmore, Ellis: Back from the break.")
    for tick in range(10, 260, 10):
        minute, second = divmod(60 + tick, 60)
        lines.append(
            f"[{minute}:{second:02d}] Goeke, Timothy: Continuing on point {tick}."
        )
    drop = make_transcript_drop("source-moments-gaps", text="\n".join(lines) + "\n")
    job_id = enqueue(pool, drop, "source-moments-gaps")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)
    rows = moment_rows(pool, meeting["id"])
    reasons = [(row["start_ms"], row["provenance"]["boundary"]) for row in rows]
    assert reasons == [
        (0, "first-segment"),
        (60_000, "silence-gap"),
        (250_000, "max-duration"),
    ]
    # Every segment lands in exactly one moment.
    links = all_links(pool, meeting["id"])
    assert len(links) == len(_segment_ids(pool, meeting["id"]))
    assert len({segment_id for _, segment_id in links}) == len(links)
    assert sum(row["segment_count"] for row in rows) == len(links)


def test_moments_are_written_without_a_link_when_the_drop_has_no_usable_url(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Matrix: transcript-only, no `provenance.url`."""
    provenance = {k: v for k, v in REAL_PROVENANCE_PULLED.items() if k != "url"}
    drop = make_transcript_drop("source-moments-nourl", provenance=provenance)
    job_id = enqueue(pool, drop, "source-moments-nourl")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)
    [moment] = moment_rows(pool, meeting["id"])
    assert moment["source_deep_link"] is None
    record = stage_log(capsys)
    assert record["moments_without_link"] == 1
    assert record["degraded_moments_without_link"] == 1


@pytest.mark.parametrize(
    ("label", "url"),
    [
        ("javascript", "javascript:alert(1)"),
        ("file", "file:///etc/passwd"),
        ("blank", "   "),
        ("ftp", "ftp://example.test/x"),
        ("hostless", "https:/not-a-host"),
    ],
)
def test_a_link_whose_scheme_is_not_http_is_treated_as_absent(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    label: str,
    url: str,
) -> None:
    """Matrix: non-http deep link. Never stored, counted as missing."""
    provenance = dict(REAL_PROVENANCE_PULLED, url=url)
    source_id = f"source-moments-scheme-{label}"
    job_id = enqueue(
        pool, make_transcript_drop(source_id, provenance=provenance), source_id
    )

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)
    [moment] = moment_rows(pool, meeting["id"])
    assert moment["source_deep_link"] is None
    assert stage_log(capsys)["moments_without_link"] == 1


# --- recording meetings ----------------------------------------------------


@requires_ffmpeg
def test_a_recording_meeting_names_its_screenshots_and_carries_no_deep_link(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """Matrix: recording meeting. Screenshots cut the timeline; no link."""
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(
        pool, make_recording_transcript_drop("source-moments-rec"), "source-moments-rec"
    )

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["moments"] == "done" and statuses["extract"] == "done"
    assert job_row(pool, job_id) == ("done", None)

    meeting = only_meeting(pool, job_id)
    with pool.connection() as conn:
        shots = conn.execute(
            "SELECT id, start_offset_ms FROM screenshot WHERE meeting_id = %s"
            " ORDER BY start_offset_ms",
            (meeting["id"],),
        ).fetchall()
    assert shots, "the recording path must produce screenshots for moments to name"

    rows = moment_rows(pool, meeting["id"])
    assert rows
    for row in rows:
        assert row["source_deep_link"] is None, "replay exists, so no transitional link"
        assert row["end_ms"] >= row["start_ms"]
        assert row["derived_from"] in ("transcript", "screen", "both")
    # Every screenshot start is a boundary, and each moment names the shot on
    # display when it began.
    starts = {row["start_ms"] for row in rows}
    assert {start for _, start in shots} <= starts
    by_start = {row["start_ms"]: row["screenshot_id"] for row in rows}
    for shot_id, shot_start in shots:
        assert by_start[shot_start] == shot_id

    links = all_links(pool, meeting["id"])
    assert len(links) == len(_segment_ids(pool, meeting["id"]))
    assert len({segment_id for _, segment_id in links}) == len(links)


@requires_ffmpeg
def test_a_screens_rerun_rebuilds_moments_with_current_screenshot_evidence(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A successful producer rerun must re-run its dependent stage this claim."""
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(
        pool,
        make_recording_transcript_drop("source-moments-screens-rerun"),
        "source-moments-screens-rerun",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    before = {
        row["identity_key"]: row["id"] for row in moment_rows(pool, meeting["id"])
    }
    with pool.connection() as conn:
        before_screenshots = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM screenshot WHERE meeting_id = %s", (meeting["id"],)
            ).fetchall()
        }
    assert before_screenshots

    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["moments"] == "done"
    after = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    assert {key: row["id"] for key, row in after.items()} == before
    with pool.connection() as conn:
        current_screenshots = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM screenshot WHERE meeting_id = %s", (meeting["id"],)
            ).fetchall()
        }
    assert current_screenshots and current_screenshots.isdisjoint(before_screenshots)
    referenced = {
        row["screenshot_id"] for row in after.values() if row["screenshot_id"]
    }
    assert referenced and referenced <= current_screenshots


def test_an_align_rerun_rebuilds_exactly_once_segment_coverage(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """Replacing segments must rebuild their `moment_segment` links this claim."""
    job_id = enqueue(
        pool,
        make_transcript_drop("source-moments-align-rerun"),
        "source-moments-align-rerun",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    before = {
        row["identity_key"]: row["id"] for row in moment_rows(pool, meeting["id"])
    }

    set_stage(pool, job_id, "align", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["moments"] == "done"
    after = {row["identity_key"]: row["id"] for row in moment_rows(pool, meeting["id"])}
    assert after == before
    with pool.connection() as conn:
        segment_ids = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM transcript_segment WHERE meeting_id = %s",
                (meeting["id"],),
            ).fetchall()
        }
    links = all_links(pool, meeting["id"])
    assert len(links) == len(segment_ids)
    assert {segment_id for _moment_id, segment_id in links} == segment_ids


# --- idempotence -----------------------------------------------------------


def test_a_rerun_over_unchanged_inputs_keeps_every_moment_id(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """Matrix: rerun, unchanged inputs. Identical ids, no duplicates."""
    job_id = enqueue(
        pool, make_transcript_drop("source-moments-rerun"), "source-moments-rerun"
    )
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    first = moment_rows(pool, meeting["id"])
    first_links = sorted(all_links(pool, meeting["id"]), key=str)

    rerun_moments(pool, app_config, content_root, job_id)

    second = moment_rows(pool, meeting["id"])
    assert [row["id"] for row in second] == [row["id"] for row in first]
    assert [row["identity_key"] for row in second] == [
        row["identity_key"] for row in first
    ]
    assert sorted(all_links(pool, meeting["id"]), key=str) == first_links


def test_every_moment_id_is_a_postgres_minted_uuidv7(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """AD-2: the stage never supplies an id, and never a client-side one."""
    job_id = enqueue(
        pool, make_transcript_drop("source-moments-uuid"), "source-moments-uuid"
    )
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    rows = moment_rows(pool, meeting["id"])
    assert rows
    for row in rows:
        assert row["id"].version == 7


def test_a_screenshot_arriving_later_splits_the_block_and_the_head_keeps_its_id(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """Matrix: screenshot inside a block — story 1.12's acceptance, early.

    Augmentation adds, never destroys: the pre-existing moment keeps its id and
    its start, gains the screenshot on display, loses its now-redundant deep
    link, and the tail it gave up appears as a new screen-anchored moment.
    """
    drop = make_transcript_drop("source-moments-augment")
    job_id = enqueue(pool, drop, "source-moments-augment")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    [before] = moment_rows(pool, meeting["id"])
    assert before["source_deep_link"] == REAL_PROVENANCE_PULLED["url"]
    original_end = before["end_ms"]
    assert original_end > 30_000, "the block must be long enough to be split"

    first_shot = insert_screenshot(pool, meeting["id"], 1, 0, 30_000)
    second_shot = insert_screenshot(pool, meeting["id"], 2, 30_000, original_end)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])

    after = moment_rows(pool, meeting["id"])
    by_key = {row["identity_key"]: row for row in after}
    assert set(by_key) == {"screen:0", "transcript:2000", "screen:30000"}

    head = by_key["transcript:2000"]
    assert head["id"] == before["id"], "no pre-existing moment is re-keyed"
    assert head["start_ms"] == before["start_ms"]
    assert head["end_ms"] == 30_000, "it gets shorter, not deleted"
    assert head["screenshot_id"] == first_shot
    assert head["derived_from"] == "transcript"
    assert head["source_deep_link"] is None, "screen evidence retires the link"
    assert head["segment_count"] == 3

    tail = by_key["screen:30000"]
    assert tail["derived_from"] == "screen"
    assert tail["screenshot_id"] == second_shot
    assert tail["segment_count"] == 0
    assert by_key["screen:0"]["screenshot_id"] == first_shot


def test_screen_anchored_moments_go_when_their_screenshots_do(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """Matrix: rerun after screenshots vanish (the transcript-only retry).

    The only deletion this stage may perform, and the transcript-anchored
    moment keeps its id straight through it.
    """
    drop = make_transcript_drop("source-moments-vanish")
    job_id = enqueue(pool, drop, "source-moments-vanish")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    [original] = moment_rows(pool, meeting["id"])

    insert_screenshot(pool, meeting["id"], 1, 30_000, 60_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    assert {row["identity_key"] for row in moment_rows(pool, meeting["id"])} == {
        "transcript:2000",
        "screen:30000",
    }

    # The recording turns out to be unusable and the meeting goes back to
    # transcript-only — which is what `_clear_replaced_video_evidence` does.
    with pool.connection() as conn:
        conn.execute("DELETE FROM screenshot WHERE meeting_id = %s", (meeting["id"],))
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])

    rows = moment_rows(pool, meeting["id"])
    assert [row["identity_key"] for row in rows] == ["transcript:2000"]
    assert rows[0]["id"] == original["id"]
    assert rows[0]["source_deep_link"] == REAL_PROVENANCE_PULLED["url"]
    assert rows[0]["segment_count"] == 3


def test_clearing_replaced_video_evidence_requeues_moments(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """A `done` checkpoint must not sit over moments whose screenshots are gone."""
    drop = make_transcript_drop("source-moments-requeue")
    job_id = enqueue(pool, drop, "source-moments-requeue")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    insert_screenshot(pool, meeting["id"], 1, 30_000, 60_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    before = moment_rows(pool, meeting["id"])
    assert len(before) == 2
    assert stage_statuses(pool, job_id)["moments"] == "done"
    head = next(row for row in before if row["identity_key"] == "transcript:2000")
    assert head["source_deep_link"] is None, "the screenshot retired the link"
    stamps_before = moment_updated_at(pool, meeting["id"])

    # The runner claims the transcript-only drop again: it deletes the
    # screenshots, so the moments checkpoint must go back to `queued`.
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True

    # Each of these fails if the checkpoint had stayed `done` and the stage had
    # simply been resumed past: the screen-anchored row would survive, the link
    # would still be missing, and the surviving row would not have been touched.
    after = moment_rows(pool, meeting["id"])
    assert [row["identity_key"] for row in after] == ["transcript:2000"]
    assert after[0]["id"] == head["id"]
    assert after[0]["source_deep_link"] == REAL_PROVENANCE_PULLED["url"]
    assert (
        moment_updated_at(pool, meeting["id"])[after[0]["id"]]
        > stamps_before[after[0]["id"]]
    )


def test_a_moment_survives_the_deletion_of_the_screenshot_it_names(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """`screenshot_id` is ON DELETE SET NULL, never CASCADE (AD-6).

    A `screens` rerun deletes and rewrites this meeting's screenshots. If that
    took the moments with it, every citation naming one would break the moment
    the capture logic was retuned — so the dangling reference is left visible
    instead. Asserted before any `moments` re-run, because the point is what
    the *database* does, not what the stage would rebuild.
    """
    drop = make_transcript_drop("source-moments-setnull")
    job_id = enqueue(pool, drop, "source-moments-setnull")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)

    # Placed so it is on display when the transcript moment starts (2_000),
    # which is what makes `screenshot_id` non-NULL on the row under test.
    shot = insert_screenshot(pool, meeting["id"], 1, 0, 30_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    before = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    head = before["transcript:2000"]
    assert head["screenshot_id"] == shot, "the row must actually name the screenshot"

    with pool.connection() as conn:
        conn.execute("DELETE FROM screenshot WHERE id = %s", (shot,))

    after = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    assert set(after) == set(before), "no moment is deleted with its screenshot"
    assert after["transcript:2000"]["id"] == head["id"]
    assert after["transcript:2000"]["screenshot_id"] is None
    # The screen-anchored moment survives too — the stage, not the FK, is what
    # is allowed to retire it, and only on its next run.
    assert after["screen:0"]["id"] == before["screen:0"]["id"]
    assert after["screen:0"]["screenshot_id"] is None


def test_a_day_precision_meeting_writes_day_precision_moments(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """The meeting's precision is copied, never assumed to be seconds.

    A `day`-precision meeting knows only its date, so a moment's wall clock is
    date + offset and must say so — reading it as a real time of day would
    invent a precision the source side never claimed.
    """
    drop = make_transcript_drop(
        "source-moments-day",
        startedAt="2026-08-05T00:00:00Z",
        startedAtPrecision="day",
    )
    job_id = enqueue(pool, drop, "source-moments-day")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)
    assert meeting["started_at_precision"] == "day"
    [moment] = moment_rows(pool, meeting["id"])
    assert moment["started_at_precision"] == "day"
    assert (
        moment["started_at"] - meeting["started_at"]
    ).total_seconds() * 1000 == moment["start_ms"]


def test_a_screen_moment_a_transcript_boundary_takes_over_is_kept_not_re_keyed(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The deletion sweep must not become a re-key.

    When `align` later derives a transcript boundary landing exactly where a
    `screen:X` moment starts, the span becomes `both` and keys as
    `transcript:X` — a different row. Deleting the `screen:X` row would move
    that instant onto a new UUID and break every citation naming it, so it is
    kept and marked superseded instead.
    """
    drop = make_transcript_drop("source-moments-takeover")
    job_id = enqueue(pool, drop, "source-moments-takeover")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)

    insert_screenshot(pool, meeting["id"], 1, 30_000, 90_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    before = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    assert set(before) == {"transcript:2000", "screen:30000"}
    screen_moment = before["screen:30000"]
    capsys.readouterr()

    # The transcript is re-derived and now opens at 30_000 — exactly where the
    # screenshot does.
    shift_segments(pool, meeting["id"], 28_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    assert stage_log(capsys)["retained_stale"] == 1

    after = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    assert "screen:30000" in after, "the superseded row is kept, never deleted"
    assert after["screen:30000"]["id"] == screen_moment["id"], "and never re-keyed"
    assert after["screen:30000"]["provenance"]["superseded"] is True
    # The instant is now owned by a coincident `both` moment.
    assert after["transcript:30000"]["derived_from"] == "both"
    assert after["transcript:30000"]["start_ms"] == 30_000
    assert "superseded" not in after["transcript:30000"]["provenance"]


def test_published_artifact_remaps_to_the_unique_live_moment_across_augmentations(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """A superseded source never strands published citable knowledge.

    The exact-start replacement is unique on each pass. The first source id
    survives in provenance while every transition is appended in order.
    """
    drop = make_transcript_drop("source-moments-artifact-remap")
    job_id = enqueue(pool, drop, "source-moments-artifact-remap")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    insert_screenshot(pool, meeting["id"], 1, 30_000, 90_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    before = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    original = before["screen:30000"]
    with pool.connection() as conn:
        artifact_id = conn.execute(
            "INSERT INTO artifact"
            " (moment_id, meeting_id, kind, state, title, body, provenance)"
            " VALUES (%s, %s, 'adr', 'published', 'Keep it citable',"
            " 'Evidence survives augmentation.', %s::jsonb) RETURNING id",
            (original["id"], meeting["id"], json.dumps({"producer": "test"})),
        ).fetchone()[0]

    # Remove the boundary that minted the source, then create a replacement
    # that begins *before* the original 30_000ms evidence instant. Repeated
    # remaps must not drift to this replacement's 28_000ms start.
    with pool.connection() as conn:
        conn.execute("DELETE FROM screenshot WHERE meeting_id = %s", (meeting["id"],))
    shift_segments(pool, meeting["id"], 26_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    first = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    first_replacement = first["transcript:28000"]
    with pool.connection() as conn:
        moment_id, provenance = conn.execute(
            "SELECT moment_id, provenance FROM artifact WHERE id = %s", (artifact_id,)
        ).fetchone()
    assert moment_id == first_replacement["id"]
    remap = provenance["source_moment_remap"]
    assert remap["original_moment_id"] == str(original["id"])
    assert remap["original_source_instant_ms"] == 30_000
    assert remap["transitions"] == [
        {
            "from_moment_id": str(original["id"]),
            "to_moment_id": str(first_replacement["id"]),
            "source_instant_ms": 30_000,
            "rule": "unique-live-moment-containing-source-instant",
        }
    ]
    assert provenance["producer"] == "test"

    # Shift the next replacement to 29_000ms. It contains the original
    # 30_000ms instant but not the current replacement's 28_000ms start.
    shift_segments(pool, meeting["id"], 1_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    second = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    second_replacement = second["transcript:29000"]
    with pool.connection() as conn:
        moment_id, provenance = conn.execute(
            "SELECT moment_id, provenance FROM artifact WHERE id = %s", (artifact_id,)
        ).fetchone()
    assert moment_id == second_replacement["id"]
    remap = provenance["source_moment_remap"]
    assert remap["original_moment_id"] == str(original["id"])
    assert [step["from_moment_id"] for step in remap["transitions"]] == [
        str(original["id"]),
        str(first_replacement["id"]),
    ]
    assert [step["to_moment_id"] for step in remap["transitions"]] == [
        str(first_replacement["id"]),
        str(second_replacement["id"]),
    ]


def test_an_extracted_artifact_is_remapped_before_it_can_be_published(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    drop = make_transcript_drop("source-moments-artifact-before-approval")
    job_id = enqueue(pool, drop, "source-moments-artifact-before-approval")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    insert_screenshot(pool, meeting["id"], 1, 30_000, 90_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    original = {
        row["identity_key"]: row for row in moment_rows(pool, meeting["id"])
    }["screen:30000"]
    with pool.connection() as conn:
        artifact_id = conn.execute(
            "INSERT INTO artifact (moment_id, meeting_id, kind, state, title, body)"
            " VALUES (%s, %s, 'adr', 'extracted', 'Pending approval', 'Body')"
            " RETURNING id",
            (original["id"], meeting["id"]),
        ).fetchone()[0]

    shift_segments(pool, meeting["id"], 28_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    with pool.connection() as conn:
        conn.execute(
            "UPDATE artifact SET state = 'published' WHERE id = %s", (artifact_id,)
        )
        moment_id = conn.execute(
            "SELECT moment_id FROM artifact WHERE id = %s", (artifact_id,)
        ).fetchone()[0]
        superseded = conn.execute(
            "SELECT provenance->>'superseded' FROM moment WHERE id = %s", (moment_id,)
        ).fetchone()[0]
    assert moment_id != original["id"]
    assert superseded is None


@pytest.mark.parametrize(
    "reserved_value",
    [
        "not-an-object",
        {
            "original_moment_id": "not-a-uuid",
            "original_source_instant_ms": 0,
            "transitions": [],
        },
    ],
)
def test_malformed_remap_provenance_is_a_named_rollback(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    reserved_value: Any,
) -> None:
    drop = make_transcript_drop("source-moments-artifact-bad-provenance")
    job_id = enqueue(pool, drop, "source-moments-artifact-bad-provenance")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    before = moment_rows(pool, meeting["id"])
    original = before[0]
    provenance = json.dumps({"source_moment_remap": reserved_value})
    with pool.connection() as conn:
        artifact_id = conn.execute(
            "INSERT INTO artifact"
            " (moment_id, meeting_id, kind, state, title, body, provenance)"
            " VALUES (%s, %s, 'adr', 'published', 'Bad history', 'Body', %s::jsonb)"
            " RETURNING id",
            (original["id"], meeting["id"], provenance),
        ).fetchone()[0]
    shift_segments(pool, meeting["id"], 5_000)

    with pytest.raises(
        moments_stage.ArtifactMomentRemapError, match="malformed source_moment_remap"
    ):
        run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])

    assert [row["id"] for row in moment_rows(pool, meeting["id"])] == [
        row["id"] for row in before
    ]
    with pool.connection() as conn:
        moment_id = conn.execute(
            "SELECT moment_id FROM artifact WHERE id = %s", (artifact_id,)
        ).fetchone()[0]
    assert moment_id == original["id"]


def test_augmentation_refuses_before_commit_when_artifact_has_no_unique_replacement(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    drop = make_transcript_drop(
        "source-moments-artifact-no-remap",
        text="[0:00] One: Opening.\n[1:00] Two: Later.\n",
    )
    job_id = enqueue(pool, drop, "source-moments-artifact-no-remap")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    before = moment_rows(pool, meeting["id"])
    original = before[0]
    with pool.connection() as conn:
        artifact_id = conn.execute(
            "INSERT INTO artifact (moment_id, meeting_id, kind, state, title, body)"
            " VALUES (%s, %s, 'adr', 'published', 'Pinned source', 'Body')"
            " RETURNING id",
            (original["id"], meeting["id"]),
        ).fetchone()[0]

    shift_segments(pool, meeting["id"], 5_000)
    with pytest.raises(
        moments_stage.ArtifactMomentRemapError,
        match="0 live moments containing that instant",
    ):
        run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])

    # The failed stage transaction committed neither its new moments nor an
    # uncitable edge: the old source is still live and still attached.
    after = moment_rows(pool, meeting["id"])
    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert "superseded" not in after[0]["provenance"]
    with pool.connection() as conn:
        moment_id, provenance = conn.execute(
            "SELECT moment_id, provenance FROM artifact WHERE id = %s", (artifact_id,)
        ).fetchone()
    assert moment_id == original["id"]
    assert "source_moment_remap" not in provenance


def test_augmentation_refuses_an_ambiguous_artifact_replacement(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drop = make_transcript_drop(
        "source-moments-artifact-ambiguous",
        text="[0:00] One: Opening.\n",
    )
    job_id = enqueue(pool, drop, "source-moments-artifact-ambiguous")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    [original] = moment_rows(pool, meeting["id"])
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO artifact (moment_id, meeting_id, kind, state, title, body)"
            " VALUES (%s, %s, 'adr', 'published', 'Ambiguous source', 'Body')",
            (original["id"], meeting["id"]),
        )

    monkeypatch.setattr(
        moments_stage.core,
        "plan_moments",
        lambda *_args: [
            moments_stage.core.PlannedMoment(
                identity_key="transcript:replacement-a",
                derived_from="transcript",
                start_ms=0,
                end_ms=1_000,
                boundary="first-segment",
                screenshot_id=None,
                segment_ids=(),
            ),
            moments_stage.core.PlannedMoment(
                identity_key="transcript:replacement-b",
                derived_from="transcript",
                start_ms=0,
                end_ms=2_000,
                boundary="first-segment",
                screenshot_id=None,
                segment_ids=(),
            ),
        ],
    )

    with pytest.raises(
        moments_stage.ArtifactMomentRemapError,
        match="2 live moments containing that instant",
    ):
        run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])

    [after] = moment_rows(pool, meeting["id"])
    assert after["id"] == original["id"]
    assert "superseded" not in after["provenance"]


def test_replay_retires_the_link_on_a_retained_superseded_moment(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """Old citation rows keep their IDs but never keep a fallback after replay."""
    drop = make_transcript_drop(
        "source-moments-replay-superseded",
        text=(
            "[0:00] Goeke, Timothy: Opening.\n"
            "[1:00] Whitmore, Ellis: After the pause.\n"
            "[2:00] Goeke, Timothy: And again.\n"
        ),
    )
    job_id = enqueue(pool, drop, "source-moments-replay-superseded")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    before = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    assert all(row["source_deep_link"] for row in before.values())

    # A capture means replay is now available; re-derived segment boundaries
    # leave the old transcript rows superseded rather than deleting them.
    insert_screenshot(pool, meeting["id"], 1, 0, 180_000)
    shift_segments(pool, meeting["id"], 5_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])

    after = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    for key, old in before.items():
        retained = after[key]
        assert retained["id"] == old["id"]
        assert retained["provenance"]["superseded"] is True
        assert retained["source_deep_link"] is None


def test_moments_whose_boundaries_moved_are_kept_and_marked_superseded(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A full new moment set landing alongside the old one.

    Every pre-existing moment keeps its id (AD-6), but a reader ordering this
    meeting by `start_ms` must be able to tell a live moment from one whose
    boundary has moved — otherwise Epic 2 projects ghosts interleaved with real
    moments. The marker is what makes them distinguishable.
    """
    drop = make_transcript_drop(
        "source-moments-superseded",
        text=(
            "[0:00] Goeke, Timothy: Opening.\n"
            "[1:00] Whitmore, Ellis: After the pause.\n"
            "[2:00] Goeke, Timothy: And again.\n"
        ),
    )
    job_id = enqueue(pool, drop, "source-moments-superseded")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    before = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    assert set(before) == {"transcript:0", "transcript:60000", "transcript:120000"}
    capsys.readouterr()

    # Every boundary moves: a wholly new moment set, none of it coincident.
    shift_segments(pool, meeting["id"], 5_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    record = stage_log(capsys)

    after = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    assert set(after) == set(before) | {
        "transcript:5000",
        "transcript:65000",
        "transcript:125000",
    }
    assert record["moment_count"] == 3
    assert record["retained_stale"] == 3

    for key, row in before.items():
        superseded = after[key]
        assert superseded["id"] == row["id"], "no pre-existing moment is deleted"
        assert superseded["provenance"]["superseded"] is True
        assert superseded["segment_count"] == 0
        # Merged, not overwritten: what the row already recorded survives.
        assert superseded["provenance"]["boundary"] == row["provenance"]["boundary"]
        assert superseded["provenance"]["config"] == row["provenance"]["config"]

    for key in ("transcript:5000", "transcript:65000", "transcript:125000"):
        assert "superseded" not in after[key]["provenance"]
    assert sum(after[k]["segment_count"] for k in after) == 3

    # A superseded moment coming back on a later run is un-marked again.
    shift_segments(pool, meeting["id"], -5_000)
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    revived = {row["identity_key"]: row for row in moment_rows(pool, meeting["id"])}
    for key, row in before.items():
        assert revived[key]["id"] == row["id"]
        assert "superseded" not in revived[key]["provenance"]
        assert revived[key]["segment_count"] == row["segment_count"]


# --- the empty path --------------------------------------------------------


def test_an_empty_meeting_logs_the_same_fields_as_a_populated_one(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Matrix: empty meeting. Zero moments is a result, not a special case."""
    drop = make_transcript_drop("source-moments-empty")
    job_id = enqueue(pool, drop, "source-moments-empty")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)
    populated = stage_log(capsys)

    with pool.connection() as conn:
        conn.execute(
            "DELETE FROM transcript_segment WHERE meeting_id = %s", (meeting["id"],)
        )
    run_moments_only(pool, app_config, content_root, job_id, drop, meeting["id"])
    empty = stage_log(capsys)

    assert set(empty) == set(populated)
    assert empty["moment_count"] == 0
    assert empty["segments_covered"] == 0
    assert empty["boundaries"] == {
        "first-segment": 0,
        "silence-gap": 0,
        "max-duration": 0,
        "screenshot": 0,
    }
    # The transcript-anchored moment survives the transcript going away: only
    # screen-anchored moments may be deleted (AD-6).
    rows = moment_rows(pool, meeting["id"])
    assert [row["identity_key"] for row in rows] == ["transcript:2000"]
    assert rows[0]["segment_count"] == 0, "its coverage was rebuilt to nothing"
    assert rows[0]["provenance"]["superseded"] is True
    assert empty["retained_stale"] == 1


def test_the_stage_writes_no_file_and_leaves_the_drop_untouched(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """AD-13: the drop is read-only and this stage's whole output is rows."""
    drop = make_transcript_drop("source-moments-readonly")
    before = {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(drop.iterdir())
    }
    enqueue(pool, drop, "source-moments-readonly")

    assert runner.run_once(pool, app_config, content_root) is True

    after = {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(drop.iterdir())
    }
    assert before == after
    assert not (content_root / "meetings").exists()
