"""The claim-and-advance loop: the story 1.3 and 1.4 I/O matrices.

DB-backed, so these skip with a named reason when the compose Postgres is
down; the ones that need a real recording additionally depend on the
ffmpeg-generated fixture and skip when ffmpeg is absent.
"""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import pytest
import psycopg
from fastapi.testclient import TestClient
from PIL import Image
from psycopg_pool import ConnectionPool

from meetingminer.adapters.ocr import OcrError
from meetingminer import logs, mintdrop, projections
from meetingminer.config import AppConfig
from meetingminer.domain.jobs import EVIDENCE_STAGES, STAGE_NAMES, VIDEO_ONLY_STAGES
from meetingminer.pipeline import frameimage, media, runner
from meetingminer.pipeline import outputs
from meetingminer.pipeline import screens as screens_core
from meetingminer.pipeline.stages import ocr as ocr_stage
from meetingminer.pipeline.stages import screens as screens_stage
from meetingminer.pipeline.stages.screens import SCREENSHOTS_SUBDIR

from meetingminer.domain.drops import drop_relative_path

from conftest import (
    DROPS_ROOT,
    DropFactory,
    FFMPEG,
    FakeOcr,
    TEAMS_TRANSCRIPT,
    requires_ffmpeg,
    truncate_evidence,
    valid_metadata,
)
from repo_paths import REPO_ROOT


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    """The test database with every job/evidence table emptied."""
    truncate_evidence(test_pool)
    return test_pool


@pytest.fixture()
def make_recording_drop(
    make_drop: DropFactory, synthetic_recording: Path
) -> Callable[..., Path]:
    """A drop carrying a real (generated) recording.mp4."""

    def _make(source_id: str = "source-rec", **overrides: Any) -> Path:
        drop = make_drop(metadata=valid_metadata(source_id, **overrides), files=())
        (drop / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
        return drop

    return _make


def enqueue(pool: ConnectionPool, drop_path: Path, source_id: str, corpus: str = "real") -> UUID:
    """Insert a queued job with its 8 pre-seeded stages, exactly as intake does.

    `drop_path` is the absolute directory the test built; what the row carries
    is its path relative to MM_DROPS_ROOT, because that is what intake stores
    and what the runner resolves (story 2.1a).
    """
    with pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus)"
            " VALUES (%s, %s, %s) RETURNING id",
            (source_id, drop_relative_path(DROPS_ROOT, drop_path), corpus),
        ).fetchone()[0]
        conn.cursor().executemany(
            "INSERT INTO job_stage (job_id, name) VALUES (%s, %s)",
            [(job_id, name) for name in STAGE_NAMES],
        )
    return job_id


def job_row(pool: ConnectionPool, job_id: UUID) -> tuple[str, str | None]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT status, error FROM job WHERE id = %s", (job_id,)
        ).fetchone()


def stage_statuses(pool: ConnectionPool, job_id: UUID) -> dict[str, str]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT name, status FROM job_stage WHERE job_id = %s", (job_id,)
        ).fetchall()
    return dict(rows)


def stage_error(pool: ConnectionPool, job_id: UUID, name: str) -> str | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT error FROM job_stage WHERE job_id = %s AND name = %s", (job_id, name)
        ).fetchone()[0]


def set_stage(pool: ConnectionPool, job_id: UUID, name: str, status: str) -> None:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = %s WHERE job_id = %s AND name = %s",
            (status, job_id, name),
        )


def set_job_status(pool: ConnectionPool, job_id: UUID, status: str) -> None:
    with pool.connection() as conn:
        conn.execute("UPDATE job SET status = %s WHERE id = %s", (status, job_id))


def meetings(pool: ConnectionPool, job_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, source_id, corpus, started_at, started_at_precision, title,"
            " has_recording, provenance FROM meeting WHERE job_id = %s",
            (job_id,),
        ).fetchall()
    keys = (
        "id", "source_id", "corpus", "started_at", "started_at_precision",
        "title", "has_recording", "provenance",
    )
    return [dict(zip(keys, row)) for row in rows]


def frames(pool: ConnectionPool, meeting_id: UUID) -> list[tuple[int, str]]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT offset_ms, path FROM frame WHERE meeting_id = %s ORDER BY offset_ms",
            (meeting_id,),
        ).fetchall()


def media_row(pool: ConnectionPool, meeting_id: UUID) -> tuple[Any, ...] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT duration_ms, container, video_codec, width, height, audio_codec"
            " FROM meeting_media WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()


def frame_ocr_rows(pool: ConnectionPool, meeting_id: UUID) -> list[tuple[Any, ...]]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT f.offset_ms, o.engine, o.normalized_text, o.block_count"
            " FROM frame_ocr o JOIN frame f ON f.id = o.frame_id"
            " WHERE o.meeting_id = %s ORDER BY f.offset_ms",
            (meeting_id,),
        ).fetchall()


def screenshots(pool: ConnectionPool, meeting_id: UUID) -> list[dict[str, Any]]:
    keys = (
        "ordinal", "path", "view_type", "capture_cues", "classification_tags",
        "start_offset_ms", "end_offset_ms", "frame_count", "screen_id",
        "representative_frame_id",
    )
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT ordinal, path, view_type, capture_cues, classification_tags,"
            " start_offset_ms, end_offset_ms, frame_count, screen_id,"
            " representative_frame_id"
            " FROM screenshot WHERE meeting_id = %s ORDER BY ordinal",
            (meeting_id,),
        ).fetchall()
    return [dict(zip(keys, row)) for row in rows]


def crop_row(pool: ConnectionPool, meeting_id: UUID) -> tuple[Any, ...] | None:
    """The share region the `screens` stage detected for one meeting."""
    with pool.connection() as conn:
        return conn.execute(
            "SELECT left_fraction, top_fraction, right_fraction, bottom_fraction,"
            " detected, method FROM meeting_crop WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()


def screens(pool: ConnectionPool) -> list[tuple[Any, ...]]:
    """Every screen row in the corpus — screens are cross-meeting (AD-5)."""
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, identity_key, signature, view_type FROM screen ORDER BY identity_key"
        ).fetchall()


def with_screens_config(app_config: AppConfig, **overrides: Any) -> AppConfig:
    """A copy of the app config with the `screens` thresholds adjusted.

    Lets a worker test isolate one segmentation rule (usually by disabling the
    region-change cue, whose input is however much the generated recording
    happens to move) without asserting against the shipped defaults.
    """
    config = app_config.model_copy(deep=True)
    pipeline = config.settings.pipeline
    pipeline.screens = pipeline.screens.model_copy(update=overrides)
    return config


# The synthetic recording samples to exactly these three frames.
FRAME_FILES = ("frame-000001.jpg", "frame-000002.jpg", "frame-000003.jpg")
SCREEN_A = "Quarterly Revenue Growth"
SCREEN_B = "Deployment Pipeline Architecture"
# Both cue thresholds are bounded 0-1 diffs, so values this far above 1.0 can
# never be reached: the region-change and settled-change cues are off and the
# whole recording is one capture. A test about identity or idempotence is
# then only about that.
NO_REGION_CUE = {"change_threshold": 1000.0, "settled_change_threshold": 1000.0}


# --- empty queue -----------------------------------------------------------


def test_worker_tests_stub_the_document_projection_trigger_by_default(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store-free worker test cannot silently write the documents index."""
    calls: list[UUID] = []

    def observe(
        _conn: object,
        _config: AppConfig,
        meeting_id: UUID,
        **_kwargs: object,
    ) -> int:
        calls.append(meeting_id)
        return 0

    monkeypatch.setattr(projections, "project_extraction_documents", observe)
    meeting_id = UUID("018f3f2a-0000-7000-8000-0000000000d4")
    runner._maybe_project_documents(
        object(),
        app_config,
        meeting_id,
        {"extract": "done"},
        logs.bind(stage="extract"),
        set(),
    )

    assert calls == []


def test_document_projection_fires_once_on_normal_and_resumed_passes(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    document_projection_trigger: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both runner call sites fire, but never more than once in one pass."""
    calls: list[UUID] = []

    def observe(
        _conn: object,
        _config: AppConfig,
        meeting_id: UUID,
        **_kwargs: object,
    ) -> int:
        calls.append(meeting_id)
        return 1

    monkeypatch.setattr(projections, "project_extraction_documents", observe)
    drop = make_drop(
        metadata=valid_metadata("source-document-trigger"),
        files=("transcript.txt",),
    )
    job_id = enqueue(pool, drop, "source-document-trigger")

    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    assert calls == [meeting["id"]]

    # A reclaim enters only the `stage.resumed` side of the runner loop. The
    # per-pass attempted set still permits exactly one retry in that new pass.
    set_job_status(pool, job_id, "running")
    with pool.connection() as conn:
        assert runner.requeue_orphaned_jobs(conn) == [job_id]
    assert runner.run_once(pool, app_config, content_root) is True
    assert calls == [meeting["id"], meeting["id"]]


def test_document_projection_failure_does_not_fail_the_job(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    document_projection_trigger: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A durable extraction remains a successful ingest during store outage."""
    calls = 0

    def unavailable(*_args: object, **_kwargs: object) -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("documents index unavailable")

    monkeypatch.setattr(projections, "project_extraction_documents", unavailable)
    drop = make_drop(
        metadata=valid_metadata("source-document-trigger-failure"),
        files=("transcript.txt",),
    )
    job_id = enqueue(pool, drop, "source-document-trigger-failure")

    assert runner.run_once(pool, app_config, content_root) is True
    assert calls == 1
    assert job_row(pool, job_id) == ("done", None)
    assert "projection.documents_failed" in capsys.readouterr().err


def test_empty_queue_claims_nothing(
    pool: ConnectionPool, app_config: AppConfig, content_root: Path, capsys
) -> None:
    assert runner.run_once(pool, app_config, content_root) is False
    # No log spam while idle.
    assert capsys.readouterr().out == ""


# --- recording drop --------------------------------------------------------


@requires_ffmpeg
def test_recording_drop_runs_every_stage_and_reaches_done(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-rec"), "source-rec")

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    # Every stage including `extract` (story 4.1, on the autouse zero-artifact
    # FakeLlm) checkpoints done, and the job finally reaches `done`.
    assert [statuses[n] for n in STAGE_NAMES] == ["done"] * len(STAGE_NAMES)
    assert job_row(pool, job_id) == ("done", None)

    [meeting] = meetings(pool, job_id)
    assert meeting["source_id"] == "source-rec"
    assert meeting["corpus"] == "real"
    assert meeting["has_recording"] is True
    assert meeting["title"] == "Daily Standup"
    assert meeting["started_at_precision"] == "second"
    assert meeting["provenance"]["dateSource"] == "the recording's createdDateTime"

    facts = media_row(pool, meeting["id"])
    assert facts is not None
    duration_ms, container, video_codec, width, height, audio_codec = facts
    assert duration_ms == pytest.approx(6000, abs=200)
    assert "mp4" in container
    assert (video_codec, width, height, audio_codec) == ("h264", 320, 240, "aac")

    rows = frames(pool, meeting["id"])
    assert [offset for offset, _ in rows] == [0, 2000, 4000]
    for offset, path in rows:
        assert not Path(path).is_absolute(), "AD-3: only relative paths in the DB"
        assert path.startswith(f"meetings/{meeting['id']}/frames/")
        assert (content_root / path).is_file()

    # One OCR row per frame...
    ocr_rows = frame_ocr_rows(pool, meeting["id"])
    assert [offset for offset, *_ in ocr_rows] == [0, 2000, 4000]
    assert {engine for _, engine, *_ in ocr_rows} == {"fake"}

    # ...and at least one screenshot on disk under this meeting's subtree.
    shots = screenshots(pool, meeting["id"])
    assert shots
    for shot in shots:
        assert not Path(shot["path"]).is_absolute(), "AD-3: only relative paths in the DB"
        assert shot["path"].startswith(f"meetings/{meeting['id']}/screenshots/")
        assert (content_root / shot["path"]).is_file()
        assert shot["view_type"] in screens_core.VIEW_TYPES
        assert shot["capture_cues"], "every capture records the cue that produced it"
    assert len(screens(pool)) == len({shot["screen_id"] for shot in shots})


@requires_ffmpeg
def test_drop_directory_is_untouched_by_the_run(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """AD-13: the worker reads the drop and never writes into it."""
    fake_ocr(default=SCREEN_A)
    drop = make_recording_drop("source-readonly")
    before = {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(drop.iterdir())
    }
    enqueue(pool, drop, "source-readonly")
    runner.run_once(pool, app_config, content_root)
    after = {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(drop.iterdir())
    }
    assert before == after


@requires_ffmpeg
def test_silent_video_only_drop_settles_as_viewable_screen_evidence(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    fake_ocr: Callable[..., FakeOcr],
    tmp_path: Path,
) -> None:
    """No audio means no transcript evidence, not a failed or invented one."""
    silent = tmp_path / "silent.mp4"
    proc = subprocess.run(
        [
            FFMPEG, "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=6",
            "-metadata", f"title={tmp_path.name}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0 or not silent.is_file():
        pytest.skip(f"ffmpeg could not create silent recording: {proc.stderr.strip()}")

    fake_ocr(default=SCREEN_A)
    mint_root = DROPS_ROOT / f"mint-silent-{tmp_path.name}"
    mint_root.mkdir()
    try:
        minted = mintdrop.mint(
            supplied=[str(silent)], corpus="real", drops_root=mint_root,
            identity_root=DROPS_ROOT, config_path=REPO_ROOT / "config.yaml",
            started_at_argument="2026-08-05",
        )
        job_id = enqueue(pool, minted.path, minted.source_id)

        assert runner.run_once(pool, app_config, content_root) is True
        statuses = stage_statuses(pool, job_id)
        assert {name: statuses[name] for name in EVIDENCE_STAGES} == {
            name: "done" for name in EVIDENCE_STAGES
        }
        assert statuses["extract"] == "done"
        [meeting] = meetings(pool, job_id)
        assert meeting["has_recording"] is True
        assert screenshots(pool, meeting["id"])
        with pool.connection() as conn:
            assert conn.execute(
                "SELECT count(*) FROM transcript_segment WHERE meeting_id = %s", (meeting["id"],)
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT count(*) FROM meeting_participant WHERE meeting_id = %s", (meeting["id"],)
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT count(*) FROM moment WHERE meeting_id = %s AND derived_from = 'screen'",
                (meeting["id"],),
            ).fetchone()[0] > 0

        import meetingminer.api.main as api_main

        api_main.app.state.pool = pool
        api = TestClient(api_main.app)
        item = next(row for row in api.get("/meetings").json()["meetings"] if row["jobId"] == str(job_id))
        assert item["viewable"] is True
        replay = api.get(f"/media/recordings/{meeting['id']}")
        assert replay.status_code == 200
        assert replay.content == silent.read_bytes()
    finally:
        shutil.rmtree(mint_root)


@requires_ffmpeg
def test_a_silent_rerun_clears_people_inferred_from_a_vanished_transcript(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    fake_ocr: Callable[..., FakeOcr],
    tmp_path: Path,
) -> None:
    """A prior transcript must not leave people attached to silent evidence."""
    silent = tmp_path / "silent-rerun.mp4"
    proc = subprocess.run(
        [
            FFMPEG, "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not silent.is_file():
        pytest.skip(f"ffmpeg could not create silent recording: {proc.stderr.strip()}")

    fake_ocr(default=SCREEN_A)
    drop = make_drop(metadata=valid_metadata("source-silent-rerun"), files=())
    (drop / "recording.mp4").write_bytes(silent.read_bytes())
    (drop / "transcript.txt").write_text(TEAMS_TRANSCRIPT, encoding="utf-8")
    job_id = enqueue(pool, drop, "source-silent-rerun")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    with pool.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM meeting_participant WHERE meeting_id = %s", (meeting["id"],)
        ).fetchone()[0] > 0
        conn.execute(
            "UPDATE job_stage SET status = 'queued' WHERE job_id = %s AND name = 'align'",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'queued' WHERE id = %s", (job_id,))

    (drop / "transcript.txt").unlink()
    assert runner.run_once(pool, app_config, content_root) is True
    with pool.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM transcript_segment WHERE meeting_id = %s", (meeting["id"],)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM meeting_participant WHERE meeting_id = %s", (meeting["id"],)
        ).fetchone()[0] == 0


@requires_ffmpeg
def test_a_silent_recording_retains_its_declared_participant_graph(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    fake_ocr: Callable[..., FakeOcr],
    tmp_path: Path,
) -> None:
    """A source-declared roster is lawful evidence even without speech."""
    silent = tmp_path / "silent-graph.mp4"
    proc = subprocess.run(
        [
            FFMPEG, "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not silent.is_file():
        pytest.skip(f"ffmpeg could not create silent recording: {proc.stderr.strip()}")

    fake_ocr(default=SCREEN_A)
    drop = make_drop(
        metadata=valid_metadata(
            "source-silent-graph",
            participants=[{"displayName": "Example, Alex", "foundIn": ["invite"]}],
        ),
        files=(),
    )
    (drop / "recording.mp4").write_bytes(silent.read_bytes())
    job_id = enqueue(pool, drop, "source-silent-graph")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    with pool.connection() as conn:
        [name] = conn.execute(
            "SELECT p.display_name FROM meeting_participant mp"
            " JOIN participant p ON p.id = mp.participant_id"
            " WHERE mp.meeting_id = %s",
            (meeting["id"],),
        ).fetchone()
    assert name == "Example, Alex"


# --- transcript-only drop --------------------------------------------------


def test_transcript_only_drop_skips_the_video_stages(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
) -> None:
    drop = make_drop(metadata=valid_metadata("source-txt"), files=("transcript.txt",))
    job_id = enqueue(pool, drop, "source-txt")

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert {n: statuses[n] for n in sorted(VIDEO_ONLY_STAGES)} == {
        n: "skipped" for n in sorted(VIDEO_ONLY_STAGES)
    }
    # `align`, `moments` and `extract` run on the provided transcript alone
    # (AD-1): a transcript-only job completes end to end.
    assert statuses["align"] == "done"
    assert statuses["moments"] == "done"
    assert statuses["extract"] == "done"
    assert job_row(pool, job_id) == ("done", None)

    [meeting] = meetings(pool, job_id)
    assert meeting["has_recording"] is False
    assert media_row(pool, meeting["id"]) is None
    assert frames(pool, meeting["id"]) == []
    assert not (content_root / "meetings").exists()


# --- resume, not restart ---------------------------------------------------


@requires_ffmpeg
def test_resume_reruns_only_the_unfinished_stage(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-resume"), "source-resume")
    # State after a crash: probe checkpointed done, frames still queued.
    set_stage(pool, job_id, "probe", "done")

    assert runner.run_once(pool, app_config, content_root) is True

    [meeting] = meetings(pool, job_id)
    # probe was not re-executed, so it wrote no meeting_media row...
    assert media_row(pool, meeting["id"]) is None
    # ...while frames did run.
    assert len(frames(pool, meeting["id"])) == 3
    assert stage_statuses(pool, job_id)["frames"] == "done"


@requires_ffmpeg
def test_completed_stages_do_not_re_execute_on_reclaim(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A restart over a fully-sampled job runs no media tool at all."""
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-restart"), "source-restart")
    runner.run_once(pool, app_config, content_root)

    # Orphan recovery re-queues the job; the checkpoints are left alone.
    set_job_status(pool, job_id, "running")
    with pool.connection() as conn:
        assert runner.requeue_orphaned_jobs(conn) == [job_id]
    assert job_row(pool, job_id)[0] == "queued"

    def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no media tool may run for an already-completed stage")

    monkeypatch.setattr(media, "_run", explode)

    assert runner.run_once(pool, app_config, content_root) is True
    assert stage_statuses(pool, job_id)["probe"] == "done"
    assert stage_statuses(pool, job_id)["frames"] == "done"


# --- idempotent rerun ------------------------------------------------------


@requires_ffmpeg
def test_frames_rerun_replaces_rows_and_files_without_duplicating(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    make_drop: DropFactory,
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-idem"), "source-idem")
    runner.run_once(pool, app_config, content_root)
    [meeting] = meetings(pool, job_id)
    first = frames(pool, meeting["id"])
    assert len(first) == 3

    # A second meeting whose frames must survive the other meeting's rerun.
    other_job = enqueue(
        pool,
        make_drop(metadata=valid_metadata("source-other"), files=("transcript.txt",)),
        "source-other",
    )
    runner.run_once(pool, app_config, content_root)
    [other_meeting] = meetings(pool, other_job)
    other_dir = content_root / "meetings" / str(other_meeting["id"]) / "frames"
    other_dir.mkdir(parents=True, exist_ok=True)
    sentinel = other_dir / "frame-000001.jpg"
    sentinel.write_bytes(b"another meeting's frame")

    # A stale file from an earlier, denser sampling run.
    frames_dir = content_root / "meetings" / str(meeting["id"]) / "frames"
    stale = frames_dir / "frame-000099.jpg"
    stale.write_bytes(b"stale")

    set_stage(pool, job_id, "frames", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True

    second = frames(pool, meeting["id"])
    assert second == first, "rerun must replace the rows, not duplicate them"
    assert not stale.exists(), "stale files from a previous sampling must not survive"
    assert sorted(p.name for p in frames_dir.iterdir()) == [
        "frame-000001.jpg",
        "frame-000002.jpg",
        "frame-000003.jpg",
    ]
    assert sentinel.read_bytes() == b"another meeting's frame"
    assert frames(pool, other_meeting["id"]) == []


@requires_ffmpeg
def test_failed_frames_rerun_retains_previous_rows_and_files(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A failed replacement must not leave durable DB paths dangling."""
    fake_ocr(default=SCREEN_A)
    drop = make_recording_drop("source-retain")
    job_id = enqueue(pool, drop, "source-retain")
    runner.run_once(pool, app_config, content_root)
    [meeting] = meetings(pool, job_id)
    before = frames(pool, meeting["id"])
    files_before = [
        (content_root / path).read_bytes() for _, path in before
    ]

    # Keep `probe` done so the corrupt replacement reaches frames directly.
    (drop / "recording.mp4").write_bytes(b"corrupt replacement" * 64)
    set_stage(pool, job_id, "frames", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["frames"] == "failed"
    assert frames(pool, meeting["id"]) == before
    assert [(content_root / path).read_bytes() for _, path in before] == files_before


@requires_ffmpeg
def test_transcript_only_replacement_clears_stale_video_evidence(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    make_drop: DropFactory,
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-replace"), "source-replace")
    runner.run_once(pool, app_config, content_root)
    [meeting] = meetings(pool, job_id)
    assert media_row(pool, meeting["id"]) is not None
    assert frames(pool, meeting["id"])
    assert screenshots(pool, meeting["id"])
    screens_before = screens(pool)
    assert screens_before

    replacement = make_drop(
        metadata=valid_metadata("source-replace"), files=("transcript.txt",)
    )
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job SET drop_relative_path = %s, status = 'queued' WHERE id = %s",
            (replacement.name, job_id),
        )
        conn.execute("DELETE FROM job_stage WHERE job_id = %s", (job_id,))
        conn.cursor().executemany(
            "INSERT INTO job_stage (job_id, name) VALUES (%s, %s)",
            [(job_id, name) for name in STAGE_NAMES],
        )

    assert runner.run_once(pool, app_config, content_root) is True
    assert media_row(pool, meeting["id"]) is None
    assert frames(pool, meeting["id"]) == []
    assert frame_ocr_rows(pool, meeting["id"]) == []
    assert screenshots(pool, meeting["id"]) == []
    # The crop describes a share region for frames this meeting no longer has,
    # so it goes with them — the same rule as the screenshots above.
    assert crop_row(pool, meeting["id"]) is None
    assert not (content_root / "meetings" / str(meeting["id"]) / "frames").exists()
    assert not (content_root / "meetings" / str(meeting["id"]) / "screenshots").exists()
    # Screens are cross-meeting entities: clearing one meeting's evidence must
    # not delete the screen rows other meetings may also reference (AD-5).
    assert screens(pool) == screens_before


@requires_ffmpeg
def test_reclaim_does_not_mint_a_second_meeting(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-once"), "source-once")
    runner.run_once(pool, app_config, content_root)
    first = meetings(pool, job_id)
    set_job_status(pool, job_id, "queued")
    runner.run_once(pool, app_config, content_root)
    second = meetings(pool, job_id)
    assert len(second) == 1
    assert second[0]["id"] == first[0]["id"]


# --- failure ---------------------------------------------------------------


@requires_ffmpeg
def test_probe_failure_is_recorded_on_stage_and_job(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
) -> None:
    drop = make_drop(metadata=valid_metadata("source-bad"), files=("recording.mp4",))
    (drop / "recording.mp4").write_bytes(b"definitely not an mp4" * 64)
    job_id = enqueue(pool, drop, "source-bad")

    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["probe"] == "failed"
    assert "ffprobe failed" in (stage_error(pool, job_id, "probe") or "")
    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "stage probe failed" in error
    # Later stages are untouched — the run stopped at the failure.
    assert stage_statuses(pool, job_id)["frames"] == "queued"


def test_failure_logs_carry_job_id_and_stage(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    capsys,
) -> None:
    """NFR17/NFR18: every pipeline log line names the job and the stage."""
    import json

    drop = make_drop(metadata=valid_metadata("source-log"), files=("recording.mp4",))
    (drop / "recording.mp4").write_bytes(b"not an mp4" * 64)
    job_id = enqueue(pool, drop, "source-log")
    runner.run_once(pool, app_config, content_root)

    captured = capsys.readouterr()
    records = [
        json.loads(line)
        for line in (captured.out + captured.err).splitlines()
        if line.startswith("{")
    ]
    assert records, "the runner must emit structured JSON logs"
    assert all(record["job_id"] == str(job_id) for record in records)
    assert all(record.get("stage") for record in records)
    failed = [r for r in records if r["event"] == "stage.failed"]
    assert failed and failed[0]["stage"] == "probe"
    assert "ffprobe" in failed[0]["error"]


def test_missing_drop_fails_the_job_without_a_stage(
    pool: ConnectionPool, app_config: AppConfig, content_root: Path, tmp_path: Path
) -> None:
    # Under the drops root but never created: "the drop vanished after intake"
    # is a missing directory, not a path outside the configured root.
    job_id = enqueue(pool, DROPS_ROOT / f"{tmp_path.name}-vanished", "source-gone")
    assert runner.run_once(pool, app_config, content_root) is True
    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "source drop unreadable" in error
    assert set(stage_statuses(pool, job_id).values()) == {"queued"}


def test_post_claim_schema_mutation_fails_the_job(
    pool: ConnectionPool, app_config: AppConfig, content_root: Path, make_drop: DropFactory
) -> None:
    """The intake-valid drop is validated again because it is external input."""
    drop = make_drop(metadata=valid_metadata("source-mutated"), files=("transcript.txt",))
    job_id = enqueue(pool, drop, "source-mutated")
    (drop / "metadata.json").write_text('{"sourceId":"source-mutated"}', encoding="utf-8")
    assert runner.run_once(pool, app_config, content_root) is True
    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "no longer matches the source-drop schema" in error


def test_post_claim_db_error_requeues_job(
    pool: ConnectionPool, app_config: AppConfig, content_root: Path, make_drop: DropFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = enqueue(pool, make_drop(metadata=valid_metadata("source-db")), "source-db")

    def database_failure(*_args: Any, **_kwargs: Any) -> None:
        raise psycopg.OperationalError("temporary outage")

    monkeypatch.setattr(runner, "run_job", database_failure)
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id)[0] == "queued"


def test_a_failed_job_is_not_reclaimed(
    pool: ConnectionPool, app_config: AppConfig, content_root: Path, tmp_path: Path
) -> None:
    enqueue(pool, DROPS_ROOT / f"{tmp_path.name}-vanished", "source-gone-2")
    assert runner.run_once(pool, app_config, content_root) is True
    assert runner.run_once(pool, app_config, content_root) is False


# --- orphan recovery -------------------------------------------------------


def test_requeue_orphaned_jobs_leaves_stage_checkpoints_alone(
    pool: ConnectionPool, app_config: AppConfig, content_root: Path, make_drop: DropFactory
) -> None:
    job_id = enqueue(
        pool, make_drop(metadata=valid_metadata("source-orphan")), "source-orphan"
    )
    set_job_status(pool, job_id, "running")
    set_stage(pool, job_id, "probe", "done")
    set_stage(pool, job_id, "frames", "running")

    with pool.connection() as conn:
        assert runner.requeue_orphaned_jobs(conn) == [job_id]

    assert job_row(pool, job_id)[0] == "queued"
    statuses = stage_statuses(pool, job_id)
    assert statuses["probe"] == "done"
    assert statuses["frames"] == "running"


def test_requeue_leaves_done_and_failed_jobs_alone(
    pool: ConnectionPool, make_drop: DropFactory
) -> None:
    failed = enqueue(pool, make_drop(metadata=valid_metadata("source-f")), "source-f")
    set_job_status(pool, failed, "failed")
    with pool.connection() as conn:
        assert runner.requeue_orphaned_jobs(conn) == []
    assert job_row(pool, failed)[0] == "failed"


# --- updated_at trigger (the closed deferred item) --------------------------


def test_updates_bump_updated_at_without_the_caller_saying_so(
    pool: ConnectionPool, make_drop: DropFactory
) -> None:
    job_id = enqueue(pool, make_drop(metadata=valid_metadata("source-ts")), "source-ts")
    with pool.connection() as conn:
        before = conn.execute(
            "SELECT updated_at FROM job WHERE id = %s", (job_id,)
        ).fetchone()[0]
        conn.execute("UPDATE job SET status = 'running' WHERE id = %s", (job_id,))
        after = conn.execute(
            "SELECT updated_at FROM job WHERE id = %s", (job_id,)
        ).fetchone()[0]
        stage_before = conn.execute(
            "SELECT updated_at FROM job_stage WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE job_stage SET status = 'done' WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        )
        stage_after = conn.execute(
            "SELECT updated_at FROM job_stage WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        ).fetchone()[0]
    assert after > before
    assert stage_after > stage_before


# --- story 1.4: ocr + screens ----------------------------------------------


@requires_ffmpeg
def test_distinct_screens_become_separate_screenshots(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """The region moved, so the capture split — and the text named the screens.

    Run at the shipped `change_threshold`: the generated recording is a moving
    test pattern, so consecutive samples genuinely move more than the
    threshold. The OCR text is scripted to change with it, which is what gives
    the two captures two different screen rows (story 1.11: pixels decide the
    boundary, text decides the identity).
    """
    engine = fake_ocr(
        by_frame={
            FRAME_FILES[0]: SCREEN_A,
            FRAME_FILES[1]: SCREEN_B,
            FRAME_FILES[2]: SCREEN_B,
        }
    )
    job_id = enqueue(pool, make_recording_drop("source-two"), "source-two")

    assert runner.run_once(pool, app_config, content_root) is True
    assert engine.calls == list(FRAME_FILES), "every frame is recognized, in offset order"

    [meeting] = meetings(pool, job_id)
    first, second = screenshots(pool, meeting["id"])
    assert (first["ordinal"], second["ordinal"]) == (1, 2)
    assert first["capture_cues"] == [screens_core.CUE_FIRST_FRAME]
    assert second["capture_cues"] == [screens_core.CUE_REGION_CHANGE]
    assert (first["start_offset_ms"], first["end_offset_ms"]) == (0, 0)
    assert (second["start_offset_ms"], second["end_offset_ms"]) == (2000, 4000)
    assert first["screen_id"] != second["screen_id"]
    # One image file per capture, both under this meeting's own subtree.
    directory = content_root / "meetings" / str(meeting["id"]) / "screenshots"
    assert sorted(p.name for p in directory.iterdir()) == [
        "screenshot-0001.jpg",
        "screenshot-0002.jpg",
    ]
    for shot in (first, second):
        assert (content_root / shot["path"]).is_file()
        assert shot["view_type"] == screens_core.VIEW_SLIDE
    # The stored screenshot is the whole frame, not the cropped analysis
    # region: the crop is an input to the decision (§2), not an output.
    frame_paths = dict(frames(pool, meeting["id"]))
    assert (content_root / second["path"]).read_bytes() in {
        (content_root / path).read_bytes() for path in frame_paths.values()
    }


@requires_ffmpeg
def test_text_alone_no_longer_splits_a_capture(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """Story 1.11: OCR text is screen identity, not a capture boundary.

    Every measured text cue put the run over `eval-design.md` §2.2's one
    capture per minute — 96 of the shipped 188 captures on the 57-minute
    meeting were `text-change` alone. With the region cue off, wholly
    different text on consecutive frames yields one capture.
    """
    fake_ocr(
        by_frame={
            FRAME_FILES[0]: SCREEN_A,
            FRAME_FILES[1]: SCREEN_B,
            FRAME_FILES[2]: SCREEN_B,
        }
    )
    config = with_screens_config(app_config, **NO_REGION_CUE)
    job_id = enqueue(pool, make_recording_drop("source-textonly"), "source-textonly")
    assert runner.run_once(pool, config, content_root) is True

    [meeting] = meetings(pool, job_id)
    [shot] = screenshots(pool, meeting["id"])
    assert shot["capture_cues"] == [screens_core.CUE_FIRST_FRAME]
    assert shot["frame_count"] == 3


@requires_ffmpeg
def test_textless_frames_are_captured_and_scoped_to_their_meeting(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A camera gallery yields no text — it must still be captured, not dropped."""
    fake_ocr(default="")
    config = with_screens_config(app_config, **NO_REGION_CUE)
    first_job = enqueue(pool, make_recording_drop("source-blank-1"), "source-blank-1")
    assert runner.run_once(pool, config, content_root) is True
    second_job = enqueue(pool, make_recording_drop("source-blank-2"), "source-blank-2")
    assert runner.run_once(pool, config, content_root) is True

    [first_meeting] = meetings(pool, first_job)
    [second_meeting] = meetings(pool, second_job)
    first_shots = screenshots(pool, first_meeting["id"])
    second_shots = screenshots(pool, second_meeting["id"])
    assert first_shots and second_shots
    assert first_shots[0]["view_type"] == screens_core.VIEW_PARTICIPANT_GALLERY

    keys = [key for _, key, *_ in screens(pool)]
    assert all(screens_core.is_scoped_identity(key) for key in keys)
    # Two textless meetings are two screens, not one collapsed row.
    assert first_shots[0]["screen_id"] != second_shots[0]["screen_id"]


@requires_ffmpeg
def test_the_same_screen_in_a_later_meeting_reuses_one_screen_row(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """Screen lineage: one row, referenced by both meetings' screenshots (AD-5)."""
    fake_ocr(default=SCREEN_A)
    config = with_screens_config(app_config, **NO_REGION_CUE)
    first_job = enqueue(pool, make_recording_drop("source-lin-1"), "source-lin-1")
    assert runner.run_once(pool, config, content_root) is True
    second_job = enqueue(pool, make_recording_drop("source-lin-2"), "source-lin-2")
    assert runner.run_once(pool, config, content_root) is True

    [first_meeting] = meetings(pool, first_job)
    [second_meeting] = meetings(pool, second_job)
    [first_shot] = screenshots(pool, first_meeting["id"])
    [second_shot] = screenshots(pool, second_meeting["id"])
    assert first_shot["screen_id"] == second_shot["screen_id"]
    assert len(screens(pool)) == 1

    # Re-running `screens` on either meeting leaves that row present.
    set_stage(pool, second_job, "screens", "queued")
    set_job_status(pool, second_job, "queued")
    assert runner.run_once(pool, config, content_root) is True
    assert len(screens(pool)) == 1
    assert screenshots(pool, second_meeting["id"])[0]["screen_id"] == first_shot["screen_id"]


@requires_ffmpeg
def test_ocr_rerun_replaces_rows_without_duplicating(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    make_drop: DropFactory,
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-ocr-idem"), "source-ocr-idem")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    before = frame_ocr_rows(pool, meeting["id"])
    assert len(before) == 3

    # A second meeting whose OCR rows must survive the other's rerun.
    other_job = enqueue(
        pool,
        make_drop(metadata=valid_metadata("source-ocr-other"), files=("transcript.txt",)),
        "source-ocr-other",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    [other_meeting] = meetings(pool, other_job)

    set_stage(pool, job_id, "ocr", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True

    assert frame_ocr_rows(pool, meeting["id"]) == before
    assert frame_ocr_rows(pool, other_meeting["id"]) == []


@requires_ffmpeg
def test_screens_rerun_replaces_screenshots_and_keeps_screen_rows(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    fake_ocr(default=SCREEN_A)
    config = with_screens_config(app_config, **NO_REGION_CUE)
    job_id = enqueue(pool, make_recording_drop("source-shot-idem"), "source-shot-idem")
    assert runner.run_once(pool, config, content_root) is True
    [meeting] = meetings(pool, job_id)
    before = screenshots(pool, meeting["id"])
    screens_before = screens(pool)
    assert before and screens_before

    # A stale image from a run that captured more screens.
    directory = content_root / "meetings" / str(meeting["id"]) / "screenshots"
    stale = directory / "screenshot-0099.jpg"
    stale.write_bytes(b"stale")

    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, config, content_root) is True

    after = screenshots(pool, meeting["id"])
    assert [shot["ordinal"] for shot in after] == [shot["ordinal"] for shot in before]
    assert [shot["path"] for shot in after] == [shot["path"] for shot in before]
    assert not stale.exists(), "stale screenshots from a previous run must not survive"
    # The cross-meeting screen row survives the rerun untouched (AD-5).
    assert screens(pool) == screens_before


@requires_ffmpeg
def test_failed_screens_rerun_retains_previous_rows_and_files(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rerun that dies after swapping the directory in restores the old one."""
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-shot-fail"), "source-shot-fail")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    before = screenshots(pool, meeting["id"])
    assert before
    files_before = {
        shot["path"]: (content_root / shot["path"]).read_bytes() for shot in before
    }

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("database went away mid-rerun")

    monkeypatch.setattr(screens_stage, "_ScreenUpserter", explode)
    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["screens"] == "failed"
    # Dependency invalidation is part of the successful producer transaction:
    # a failed screens rerun leaves the previous moments checkpoint intact.
    assert statuses["moments"] == "done"
    assert job_row(pool, job_id)[0] == "failed"
    assert screenshots(pool, meeting["id"]) == before
    assert {
        shot["path"]: (content_root / shot["path"]).read_bytes() for shot in before
    } == files_before


@requires_ffmpeg
def test_ocr_engine_failure_is_recorded_on_stage_and_job(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No usable engine is a named stage failure, not a silent empty result."""

    def no_engine(*_args: Any, **_kwargs: Any) -> None:
        raise OcrError("no usable OCR engine: apple-vision is unavailable here")

    monkeypatch.setattr(ocr_stage, "build_ocr", no_engine)
    job_id = enqueue(pool, make_recording_drop("source-noocr"), "source-noocr")

    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["ocr"] == "failed"
    assert "no usable OCR engine" in (stage_error(pool, job_id, "ocr") or "")
    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "stage ocr failed" in error
    # The run stopped at the failure: `screens` never started.
    assert stage_statuses(pool, job_id)["screens"] == "queued"
    [meeting] = meetings(pool, job_id)
    assert frame_ocr_rows(pool, meeting["id"]) == []
    assert screenshots(pool, meeting["id"]) == []


@requires_ffmpeg
def test_zero_frames_completes_ocr_and_screens_with_no_outputs(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """`frames` done with nothing sampled is a result, not a failure."""
    import json

    def no_engine(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("no OCR engine may be built when there is nothing to read")

    monkeypatch.setattr(ocr_stage, "build_ocr", no_engine)
    drop = make_recording_drop("source-noframes")
    # A transcript as well as the recording: this is the one case where a
    # meeting *has* a recording but produced no screenshots, which is the
    # branch that decides whether `moments` writes a transitional deep link.
    # Without turns to cut there would be no moment to observe it on.
    (drop / "transcript.txt").write_text(TEAMS_TRANSCRIPT, encoding="utf-8")
    job_id = enqueue(pool, drop, "source-noframes")
    set_stage(pool, job_id, "probe", "done")
    set_stage(pool, job_id, "frames", "done")

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["ocr"] == "done" and statuses["screens"] == "done"
    assert statuses["moments"] == "done"
    assert statuses["extract"] == "done"
    assert job_row(pool, job_id) == ("done", None)
    [meeting] = meetings(pool, job_id)
    assert frame_ocr_rows(pool, meeting["id"]) == []
    assert screenshots(pool, meeting["id"]) == []
    # No frames means no survey ran, so there is no region to claim was
    # detected — an honest absence rather than a full-frame default.
    assert crop_row(pool, meeting["id"]) is None
    screenshot_dir = content_root / "meetings" / str(meeting["id"]) / "screenshots"
    assert screenshot_dir.is_dir() and not list(screenshot_dir.iterdir())

    # The meeting has a recording, so replay is what it offers even though this
    # run captured nothing: no transitional deep link is written (UX-DR11's
    # link stands in for replay, it does not supplement it).
    with pool.connection() as conn:
        links = conn.execute(
            "SELECT source_deep_link, screenshot_id FROM moment WHERE meeting_id = %s",
            (meeting["id"],),
        ).fetchall()
    assert links, "the transcript still cuts the timeline with no screenshots"
    assert all(link is None and shot is None for link, shot in links)

    records = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    by_event = {record["event"]: record for record in records}
    assert by_event["stage.ocr.recognized"]["frame_count"] == 0
    assert by_event["stage.screens.captured"]["capture_count"] == 0
    assert all(record.get("stage") for record in records)


@requires_ffmpeg
def test_empty_screens_rerun_replaces_previously_populated_output(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A zero-frame rerun must not leave JPEGs from a previous capture."""
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-empty-screens-rerun"), "source-empty-screens-rerun")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    screenshot_dir = content_root / "meetings" / str(meeting["id"]) / "screenshots"
    assert any(screenshot_dir.iterdir())

    with pool.connection() as conn:
        conn.execute("DELETE FROM frame WHERE meeting_id = %s", (meeting["id"],))
        conn.commit()
    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")

    assert runner.run_once(pool, app_config, content_root) is True
    assert screenshots(pool, meeting["id"]) == []
    assert screenshot_dir.is_dir() and not list(screenshot_dir.iterdir())


# --- story 1.4 review findings ---------------------------------------------


def screen_row(pool: ConnectionPool, identity_key: str) -> tuple[Any, ...] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, signature, view_type, updated_at FROM screen WHERE identity_key = %s",
            (identity_key,),
        ).fetchone()


@requires_ffmpeg
def test_a_region_change_captures_a_screen_ocr_cannot_see(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """At the shipped threshold, with the OCR text deliberately held constant.

    This is the cue that fires where there is no text to compare — video, a
    camera gallery, a chart redrawing — so it is exercised here at
    `config.yaml`'s own `change_threshold` rather than with the cue disabled.
    Story 1.11 replaced the encoded-JPEG-size proxy with this: §2 showed that
    a whole-frame size signal measures the webcam column as much as the shared
    screen, and on the 57-minute meeting `size-delta` decided no capture on
    its own anyway.
    """
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-regioncue"), "source-regioncue")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)

    screens_config = app_config.settings.pipeline.screens
    assert screens_config.change_threshold == pytest.approx(0.10), (
        "this test asserts the shipped default"
    )
    # The settled-change gate ships alongside it (story demo-001-capture-
    # recall); pin its defaults from the loaded config.yaml the same way.
    assert screens_config.settled_change_threshold == pytest.approx(0.03), (
        "this test asserts the shipped default"
    )
    assert screens_config.settled_change_frames == 3, (
        "this test asserts the shipped default"
    )

    shots = screenshots(pool, meeting["id"])
    assert [shot["ordinal"] for shot in shots] == [1, 2]
    # The text never changed, so pixels are the only thing that split it.
    assert shots[1]["capture_cues"] == [screens_core.CUE_REGION_CHANGE]
    assert shots[1]["start_offset_ms"] == 2000
    assert len({shot["screen_id"] for shot in shots}) == 1, "one screen, two captures"


@requires_ffmpeg
def test_the_crop_row_records_what_change_detection_actually_saw(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """One crop row per meeting, replaced by a rerun, gone with the evidence.

    The generated recording is a full-bleed test pattern with no webcam
    column, so the honest answer is the full frame *and* a recorded
    `detected = false` — the I/O matrix's "no webcam column" row.
    """
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-crop"), "source-crop")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)

    row = crop_row(pool, meeting["id"])
    assert row is not None
    left, top, right, bottom, detected, method = row
    assert (left, top) == (0.0, 0.0)
    assert right == 1.0
    assert detected is False
    assert method == frameimage.METHOD_INCONCLUSIVE, (
        "a truthy method is not enough: 'inconclusive' and 'bottom-strip' mean"
        " different things and only one of them is right here"
    )
    assert bottom == 1.0, "nothing was cropped, so the bottom must be untouched too"

    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True
    assert crop_row(pool, meeting["id"]) == row, "one row per meeting, replaced not doubled"


@requires_ffmpeg
def test_classification_tags_are_recorded_and_survive_a_rerun(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """§4's unresolvable cases are labelled on the row, never dropped (NFR8)."""
    fake_ocr(default="")  # textless: a gallery the pixel pair cannot confirm
    config = with_screens_config(app_config, **NO_REGION_CUE)
    job_id = enqueue(pool, make_recording_drop("source-tags"), "source-tags")
    assert runner.run_once(pool, config, content_root) is True
    [meeting] = meetings(pool, job_id)

    [shot] = screenshots(pool, meeting["id"])
    assert shot["view_type"] == screens_core.VIEW_PARTICIPANT_GALLERY
    assert shot["classification_tags"] == [screens_core.TAG_AVATAR_GALLERY_UNRESOLVED]

    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, config, content_root) is True
    [after] = screenshots(pool, meeting["id"])
    assert after["classification_tags"] == shot["classification_tags"]


@requires_ffmpeg
def test_an_unreadable_frame_fails_the_stage_by_name(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A frame that will not decode is a recorded failure, not a silent skip."""
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-badframe"), "source-badframe")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)

    frames_dir = content_root / "meetings" / str(meeting["id"]) / "frames"
    (frames_dir / FRAME_FILES[1]).write_bytes(b"not a jpeg at all")
    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["screens"] == "failed"
    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert FRAME_FILES[1] in error and "frames stage" in error


@requires_ffmpeg
def test_a_near_miss_signature_reaches_the_same_screen_by_lineage(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """Two meetings whose text differs by one token land on one screen row.

    The identity keys differ, so this can only resolve through the lineage
    branch — not through an exact-key hit.
    """
    config = with_screens_config(app_config, **NO_REGION_CUE)
    first_text = "Quarterly Revenue Growth Fiscal TwentySix"
    # One extra token: 5 shared of 6 united = 0.83, above lineage_threshold.
    second_text = f"{first_text} Draft"
    assert screens_core.jaccard(
        screens_core.tokens(screens_core.normalize_text(first_text)),
        screens_core.tokens(screens_core.normalize_text(second_text)),
    ) >= config.settings.pipeline.screens.lineage_threshold

    fake_ocr(default=first_text)
    first_job = enqueue(pool, make_recording_drop("source-lineage-1"), "source-lineage-1")
    assert runner.run_once(pool, config, content_root) is True

    fake_ocr(default=second_text)
    second_job = enqueue(pool, make_recording_drop("source-lineage-2"), "source-lineage-2")
    assert runner.run_once(pool, config, content_root) is True

    [first_meeting] = meetings(pool, first_job)
    [second_meeting] = meetings(pool, second_job)
    [first_shot] = screenshots(pool, first_meeting["id"])
    [second_shot] = screenshots(pool, second_meeting["id"])

    rows = screens(pool)
    assert len(rows) == 1, "a near-miss signature must not mint a second screen"
    assert first_shot["screen_id"] == second_shot["screen_id"] == rows[0][0]
    # Lineage reuses the row; it does not rewrite the corpus screen's
    # signature with the second meeting's variant.
    assert rows[0][2] == screens_core.normalize_text(first_text)


@requires_ffmpeg
def test_a_screens_rerun_refreshes_a_meeting_scoped_screen_row(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A rerun whose segmentation changed must not leave the first run's values."""
    config = with_screens_config(app_config, **NO_REGION_CUE)
    fake_ocr(default="Login")  # one token: below the signature floor, so scoped
    job_id = enqueue(pool, make_recording_drop("source-refresh"), "source-refresh")
    assert runner.run_once(pool, config, content_root) is True
    [meeting] = meetings(pool, job_id)

    key = f"meeting:{meeting['id']}:1"
    before = screen_row(pool, key)
    assert before is not None and before[1] == "login"

    fake_ocr(default="Dashboard")
    set_stage(pool, job_id, "ocr", "queued")
    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, config, content_root) is True

    after = screen_row(pool, key)
    assert after is not None
    assert after[0] == before[0], "the same screen row, upserted rather than duplicated"
    assert after[1] == "dashboard", "the stale signature must not survive the rerun"
    assert after[3] > before[3], "the set_updated_at trigger is reachable"


@requires_ffmpeg
def test_a_first_screens_run_that_fails_leaves_no_orphan_directory(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no previous directory to fall back to, so the new one must go."""
    fake_ocr(default=SCREEN_A)

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("database went away after the directory was swapped in")

    monkeypatch.setattr(screens_stage, "_ScreenUpserter", explode)
    job_id = enqueue(pool, make_recording_drop("source-orphan"), "source-orphan")

    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["screens"] == "failed"
    [meeting] = meetings(pool, job_id)
    assert screenshots(pool, meeting["id"]) == []
    directory = content_root / "meetings" / str(meeting["id"]) / SCREENSHOTS_SUBDIR
    assert not directory.exists(), "no screenshots directory may outlive its rows"


@requires_ffmpeg
def test_a_failing_commit_hook_does_not_revert_committed_output(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """Commit hooks run where a failure cannot reach the rollback path."""
    import json

    fake_ocr(default=SCREEN_A)
    config = with_screens_config(app_config, **NO_REGION_CUE)
    job_id = enqueue(pool, make_recording_drop("source-hook"), "source-hook")
    assert runner.run_once(pool, config, content_root) is True
    [meeting] = meetings(pool, job_id)
    [shot] = screenshots(pool, meeting["id"])

    # Make the next run's output distinguishable from the current one. It has
    # to stay a decodable image: story 1.11 measures every frame's pixels.
    meeting_dir = content_root / "meetings" / str(meeting["id"])
    regenerated = meeting_dir / "frames" / FRAME_FILES[0]
    Image.new("RGB", (320, 240), (17, 34, 51)).save(regenerated, format="JPEG")
    regenerated_bytes = regenerated.read_bytes()
    (content_root / shot["path"]).write_bytes(b"previously published")

    def explode(self: Any) -> None:
        raise OSError("could not retire the backup directory")

    monkeypatch.setattr(outputs.OutputDirSwap, "_drop_backup", explode)
    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    capsys.readouterr()
    assert runner.run_once(pool, config, content_root) is True

    # The rows committed, so the files they name must be the new ones.
    assert stage_statuses(pool, job_id)["screens"] == "done"
    assert job_row(pool, job_id) == ("done", None)
    [after] = screenshots(pool, meeting["id"])
    assert (content_root / after["path"]).read_bytes() == regenerated_bytes

    records = [
        json.loads(line)
        for line in (capsys.readouterr().err).splitlines()
        if line.startswith("{")
    ]
    hook_failures = [r for r in records if r["event"] == "stage.hook_failed"]
    assert hook_failures, "a hook failure is reported, never swallowed"
    assert hook_failures[0]["phase"] == "commit"
    assert hook_failures[0]["stage"] == "screens"


@requires_ffmpeg
def test_transcript_only_replacement_removes_the_swap_backups(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    make_drop: DropFactory,
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A surviving backup would be restored onto the emptied target later."""
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_drop("source-backups"), "source-backups")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)

    # State a crash between the directory swap and the checkpoint would leave.
    meeting_dir = content_root / "meetings" / str(meeting["id"])
    for name in (".frames-previous", ".screenshots-previous"):
        backup = meeting_dir / name
        backup.mkdir()
        (backup / "stale.jpg").write_bytes(b"video evidence")

    replacement = make_drop(
        metadata=valid_metadata("source-backups"), files=("transcript.txt",)
    )
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job SET drop_relative_path = %s, status = 'queued' WHERE id = %s",
            (replacement.name, job_id),
        )
        conn.execute("DELETE FROM job_stage WHERE job_id = %s", (job_id,))
        conn.cursor().executemany(
            "INSERT INTO job_stage (job_id, name) VALUES (%s, %s)",
            [(job_id, name) for name in STAGE_NAMES],
        )

    assert runner.run_once(pool, app_config, content_root) is True

    assert sorted(p.name for p in meeting_dir.iterdir()) == []
    assert frames(pool, meeting["id"]) == []
    assert screenshots(pool, meeting["id"]) == []


@requires_ffmpeg
def test_recognized_text_containing_a_nul_does_not_fail_the_stage(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """Postgres refuses U+0000 in a text value; one bad glyph must not cost
    the whole meeting's OCR."""
    fake_ocr(default="Quarterly\x00 Revenue Growth")
    job_id = enqueue(pool, make_recording_drop("source-nul"), "source-nul")

    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["ocr"] == "done"
    [meeting] = meetings(pool, job_id)
    with pool.connection() as conn:
        texts = conn.execute(
            "SELECT text, normalized_text FROM frame_ocr WHERE meeting_id = %s",
            (meeting["id"],),
        ).fetchall()
    assert texts
    for text, normalized in texts:
        assert "\x00" not in text and "\x00" not in normalized
        assert "Quarterly" in text
        assert normalized == "quarterly revenue growth"


@requires_ffmpeg
def test_a_long_ocr_stage_reports_progress_before_it_finishes(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """~1700 serial recognitions must not look hung for minutes."""
    import json

    fake_ocr(default=SCREEN_A)
    monkeypatch.setattr(ocr_stage, "PROGRESS_EVERY_FRAMES", 2)
    enqueue(pool, make_recording_drop("source-progress"), "source-progress")
    capsys.readouterr()

    assert runner.run_once(pool, app_config, content_root) is True

    records = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    progress = [r for r in records if r["event"] == "stage.ocr.progress"]
    assert progress, "a long stage must show movement before its summary"
    assert progress[0]["frames_done"] == 2
    assert progress[0]["frame_count"] == 3
    assert progress[0]["stage"] == "ocr"
    # The heartbeat never duplicates the summary on the final frame.
    assert all(r["frames_done"] != r["frame_count"] for r in progress)


@requires_ffmpeg
def test_empty_and_populated_stage_logs_carry_the_same_fields(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """A log consumer must never have to special-case zero."""
    import json

    def records(out: str) -> dict[str, dict[str, Any]]:
        parsed = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
        return {r["event"]: r for r in parsed}

    fake_ocr(default=SCREEN_A)
    enqueue(pool, make_recording_drop("source-fields-full"), "source-fields-full")
    capsys.readouterr()
    assert runner.run_once(pool, app_config, content_root) is True
    populated = records(capsys.readouterr().out)

    # Now the zero-output path: `frames` checkpointed done with nothing sampled.
    empty_job = enqueue(
        pool, make_recording_drop("source-fields-empty"), "source-fields-empty"
    )
    set_stage(pool, empty_job, "probe", "done")
    set_stage(pool, empty_job, "frames", "done")
    capsys.readouterr()
    assert runner.run_once(pool, app_config, content_root) is True
    empty = records(capsys.readouterr().out)

    for event in (
        "stage.ocr.recognized",
        "stage.screens.captured",
        "stage.moments.identified",
    ):
        assert set(empty[event]) == set(populated[event]), event
    assert empty["stage.ocr.recognized"]["engine"] is None
    assert empty["stage.screens.captured"]["captures_per_minute"] is None
    # The empty stage still publishes its output directory: the stage creates
    # it to replace any stale screenshots from a prior populated run.
    assert empty["stage.screens.captured"]["directory"] is not None
    # NFR2's guardrail is one capture per minute; the rate is logged so the
    # tension is visible per meeting rather than only in an after-the-fact query.
    assert populated["stage.screens.captured"]["captures_per_minute"] > 0


# --- story 1.11: the crop and the pixel pair, observed through the stage ----


def _repaint_frames(content_root: Path, meeting_id: UUID, image: Image.Image) -> None:
    """Overwrite every sampled frame of a meeting with one picture.

    The `screens` stage measures the JPEGs on disk, so this is how a worker
    test puts *pixels* of a chosen kind in front of it — the generated
    recording is a test pattern and cannot be one.
    """
    for frame_path in sorted(
        (content_root / "meetings" / str(meeting_id) / "frames").glob("frame-*.jpg")
    ):
        image.save(frame_path, format="JPEG", quality=95)


@requires_ffmpeg
def test_camera_pixels_reach_the_classifier_through_the_stage(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """§4's pair must survive the trip from the JPEG to `screenshot.view_type`.

    The rule itself is unit-tested, and `measure_frame` is unit-tested, but
    nothing joined them: replacing the two measured numbers with constants
    that say "always screen share" left the whole suite green, because the
    only worker test reaching `participant-gallery` got there through the
    textless-geometry branch instead. Here the frames are dark and saturated
    while the text geometry says `ui-screen`, so only the pixel pair can
    produce the gallery verdict.
    """
    fake_ocr(default=SCREEN_A)
    config = with_screens_config(app_config, **NO_REGION_CUE)
    job_id = enqueue(pool, make_recording_drop("source-camera-pixels"), "source-camera-pixels")
    assert runner.run_once(pool, config, content_root) is True
    [meeting] = meetings(pool, job_id)
    before = screenshots(pool, meeting["id"])[0]["view_type"]
    assert before != screens_core.VIEW_PARTICIPANT_GALLERY, (
        "the text geometry alone must not already say gallery, or this proves nothing"
    )

    # Same OCR text and geometry, camera pixels underneath it.
    _repaint_frames(content_root, meeting["id"], Image.new("RGB", (320, 180), (140, 30, 20)))
    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, config, content_root) is True

    [shot] = screenshots(pool, meeting["id"])
    assert shot["view_type"] == screens_core.VIEW_PARTICIPANT_GALLERY
    assert shot["classification_tags"] == []


@requires_ffmpeg
def test_the_detected_crop_reaches_the_ocr_geometry_the_view_rules_read(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """Text in the webcam column must stop counting as page text.

    Threading the detected region into `crop_blocks` is the whole point of
    recomputing block geometry rather than reading `frame_ocr`'s whole-frame
    summary columns, and replacing that region with the full frame left the
    suite green. Here every recognized box sits in the webcam column: with the
    crop applied the share region has no text at all and the frame is a
    gallery, without it the boxes are page text and it is a `ui-screen`.
    """
    # Boxes at x=0.9 are inside the webcam column, outside any share region.
    fake_ocr(default="\n".join(f"line {index}" for index in range(10)), block_x=0.9)
    config = with_screens_config(app_config, **NO_REGION_CUE)
    job_id = enqueue(pool, make_recording_drop("source-column-text"), "source-column-text")
    assert runner.run_once(pool, config, content_root) is True
    [meeting] = meetings(pool, job_id)

    # §2's two-part layout, so the survey has a column to find.
    layout = Image.new("RGB", (320, 180), (0, 0, 0))
    layout.paste((255, 255, 255), (0, 0, 280, 172))
    _repaint_frames(content_root, meeting["id"], layout)
    set_stage(pool, job_id, "screens", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, config, content_root) is True

    row = crop_row(pool, meeting["id"])
    assert row is not None and row[4] is True, "the survey must find the column first"
    [shot] = screenshots(pool, meeting["id"])
    assert shot["view_type"] == screens_core.VIEW_PARTICIPANT_GALLERY, (
        "webcam-column text is still being counted as page text"
    )
