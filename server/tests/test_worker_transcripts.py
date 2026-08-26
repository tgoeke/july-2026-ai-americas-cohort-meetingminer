"""`transcribe` and `align` end to end: the story 1.5 I/O matrix's DB-backed rows.

Kept beside `test_worker_runner.py` rather than inside it: this file is
entirely about the transcript lanes and the participants they resolve to, and
the runner file is already the story 1.3/1.4 matrix.

DB-backed, so these skip with a named reason when the compose Postgres is down;
the ones that need a real recording additionally depend on the ffmpeg-generated
fixture and skip when ffmpeg is absent. No test reaches a real recognizer — the
`fake_stt` fixture scripts what the verification lane heard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import pytest
from psycopg_pool import ConnectionPool

from meetingminer.config import AppConfig
from meetingminer.adapters.diarize.port import DiarizationTurn
from meetingminer.pipeline import runner, speakers
from meetingminer.pipeline.stages import transcribe as transcribe_stage
from meetingminer.pipeline.stages.transcribe import AUDIO_SUBDIR

from conftest import (
    DropFactory,
    FakeOcr,
    FakeStt,
    LEGACY_TRANSCRIPT,
    SPEAKERLESS_VTT,
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
    stage_error,
    stage_statuses,
)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    """The test database with every job/evidence table emptied."""
    truncate_evidence(test_pool)
    return test_pool


@pytest.fixture()
def make_transcript_drop(make_drop: DropFactory) -> Callable[..., Path]:
    """A transcript-only drop whose files carry exactly the given text."""

    def _make(
        source_id: str,
        text: str | None = TEAMS_TRANSCRIPT,
        vtt: str | None = None,
        **overrides: Any,
    ) -> Path:
        drop = make_drop(metadata=valid_metadata(source_id, **overrides), files=())
        if text is not None:
            (drop / "transcript.txt").write_text(text, encoding="utf-8")
        if vtt is not None:
            (drop / "transcript.vtt").write_text(vtt, encoding="utf-8")
        return drop

    return _make


@pytest.fixture()
def make_recording_transcript_drop(
    make_drop: DropFactory, synthetic_recording: Path
) -> Callable[..., Path]:
    """A drop carrying a real (generated) recording plus a transcript."""

    def _make(
        source_id: str,
        text: str | None = TEAMS_TRANSCRIPT,
        vtt: str | None = None,
        **overrides: Any,
    ) -> Path:
        drop = make_drop(metadata=valid_metadata(source_id, **overrides), files=())
        (drop / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
        if text is not None:
            (drop / "transcript.txt").write_text(text, encoding="utf-8")
        if vtt is not None:
            (drop / "transcript.vtt").write_text(vtt, encoding="utf-8")
        return drop

    return _make


# --- readers ---------------------------------------------------------------

SEGMENT_KEYS = (
    "ordinal", "start_ms", "end_ms", "text", "speaker_label", "participant_id",
    "speaker_resolution", "label_source_id", "timing_source_id", "stt_source_id",
    "stt_start_ms", "alignment_delta_ms", "match_score",
)


def segments(pool: ConnectionPool, meeting_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT ordinal, start_ms, end_ms, text, speaker_label, participant_id,"
            " speaker_resolution, label_source_id, timing_source_id, stt_source_id,"
            " stt_start_ms, alignment_delta_ms, match_score"
            " FROM transcript_segment WHERE meeting_id = %s ORDER BY ordinal",
            (meeting_id,),
        ).fetchall()
    return [dict(zip(SEGMENT_KEYS, row)) for row in rows]


def sources(pool: ConnectionPool, meeting_id: UUID) -> dict[str, dict[str, Any]]:
    keys = ("id", "format", "drop_relative_path", "content_path", "sha256",
            "byte_size", "segment_count", "engine", "model", "language")
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT kind, id, format, drop_relative_path, content_path, sha256,"
            " byte_size, segment_count, engine, model, language"
            " FROM transcript_source WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchall()
    return {row[0]: dict(zip(keys, row[1:])) for row in rows}


def participants(pool: ConnectionPool) -> list[tuple[Any, ...]]:
    """Every participant row in the corpus — participants are cross-meeting."""
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, identity_key, display_name FROM participant ORDER BY identity_key"
        ).fetchall()


def meeting_participants(pool: ConnectionPool, meeting_id: UUID) -> list[dict[str, Any]]:
    keys = ("participant_id", "identity_key", "derived_from", "is_external",
            "is_guest", "mail", "department", "spoke_turns", "found_in")
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT mp.participant_id, p.identity_key, mp.derived_from, mp.is_external,"
            " mp.is_guest, mp.mail, mp.department, mp.spoke_turns, mp.found_in"
            " FROM meeting_participant mp JOIN participant p ON p.id = mp.participant_id"
            " WHERE mp.meeting_id = %s ORDER BY p.identity_key",
            (meeting_id,),
        ).fetchall()
    return [dict(zip(keys, row)) for row in rows]


def only_meeting(pool: ConnectionPool, job_id: UUID) -> dict[str, Any]:
    [meeting] = meetings(pool, job_id)
    return meeting


# --- Teams lineage, transcript-only ---------------------------------------


def test_teams_transcript_only_drop_derives_attributed_segments(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    drop = make_transcript_drop("source-teams")
    job_id = enqueue(pool, drop, "source-teams")

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["align"] == "done"
    assert statuses["transcribe"] == "skipped"
    meeting = only_meeting(pool, job_id)

    recorded = sources(pool, meeting["id"])
    assert set(recorded) == {"provided-text"}
    assert recorded["provided-text"]["format"] == "teams"
    # Relative to MM_DROPS_ROOT, not to the drop's own folder (story 2.1a):
    # a bare filename is not resolvable without knowing which drop the job
    # currently points at, and an augmenting re-emit changes that.
    assert (
        recorded["provided-text"]["drop_relative_path"] == f"{drop.name}/transcript.txt"
    )
    assert recorded["provided-text"]["segment_count"] == 3
    assert len(recorded["provided-text"]["sha256"]) == 64

    rows = segments(pool, meeting["id"])
    assert [row["ordinal"] for row in rows] == [1, 2, 3]
    assert [row["speaker_label"] for row in rows] == [
        "Goeke, Timothy", "Whitmore, Ellis", "Goeke, Timothy",
    ]
    assert [row["start_ms"] for row in rows] == [2_000, 5_000, 9_000]
    # No recording, so no verification lane at all.
    assert all(row["stt_source_id"] is None for row in rows)
    assert all(row["alignment_delta_ms"] is None for row in rows)
    # Every row names the provided transcript as both label and timing source.
    assert {row["label_source_id"] for row in rows} == {recorded["provided-text"]["id"]}

    # Roster came from the labels, so both speakers resolved.
    assert all(row["speaker_resolution"] == "resolved" for row in rows)
    assert all(row["participant_id"] is not None for row in rows)
    assert [key for _, key, _ in participants(pool)] == ["name:ellis whitmore", "name:timothy goeke"]
    assert [p["derived_from"] for p in meeting_participants(pool, meeting["id"])] == [
        "transcript", "transcript",
    ]


@pytest.mark.parametrize(
    ("source_id", "text", "line"),
    [
        ("source-bad-header", "[0:01] Cameron: fine\n[broken] Cameron: not speech\n", 2),
        ("source-leading-text", "Export title\n[0:01] Cameron: actual speech\n", 1),
    ],
)
def test_malformed_or_unattributed_text_fails_align_with_its_source_line(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    source_id: str,
    text: str,
    line: int,
) -> None:
    """The stage preserves bad input as a named failure, never false evidence."""
    job_id = enqueue(pool, make_transcript_drop(source_id, text=text), source_id)

    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["align"] == "failed"
    error = stage_error(pool, job_id, "align") or ""
    assert "transcript.txt" in error and f"line {line}" in error


def test_a_turn_ends_where_the_next_begins_without_a_vtt(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    job_id = enqueue(pool, make_transcript_drop("source-ends"), "source-ends")
    runner.run_once(pool, app_config, content_root)
    rows = segments(pool, only_meeting(pool, job_id)["id"])
    assert [row["end_ms"] for row in rows[:2]] == [5_000, 9_000]
    # The last turn is capped rather than running to the end of the meeting.
    assert rows[2]["end_ms"] == 9_000 + app_config.settings.pipeline.align.max_segment_ms


# --- legacy lineage --------------------------------------------------------


def test_legacy_transcript_parses_placeholders_and_past_the_hour_stamps(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    drop = make_transcript_drop("source-legacy", text=LEGACY_TRANSCRIPT)
    job_id = enqueue(pool, drop, "source-legacy")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)
    assert sources(pool, meeting["id"])["provided-text"]["format"] == "legacy"

    rows = segments(pool, meeting["id"])
    assert [row["speaker_label"] for row in rows] == [
        "Ironside, Indigo", "Speaker 8", "Ellis",
    ]
    # `MM:SS` and `HH:MM:SS` in one file, decided by field count.
    assert [row["start_ms"] for row in rows] == [0, 12_000, 3_604_000]
    # The preamble line is not a speaker block, and a block's lines are joined.
    assert rows[0]["text"] == "Starting. Okay, perfect. So welcome, everyone."

    resolutions = {row["speaker_label"]: row["speaker_resolution"] for row in rows}
    assert resolutions["Speaker 8"] == "placeholder"
    assert resolutions["Ironside, Indigo"] == "resolved"
    # `Speaker 8` never became a person.
    # participants() sorts by identity_key, so this order follows the names.
    assert [key for _, key, _ in participants(pool)] == ["name:ellis", "name:indigo ironside"]
    for row in rows:
        if row["speaker_resolution"] != "resolved":
            assert row["participant_id"] is None


# --- the VTT contributes end timings and never a speaker -------------------


def test_a_vtt_supplies_cue_ends_while_labels_stay_with_the_text(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    drop = make_transcript_drop("source-vtt", vtt=SPEAKERLESS_VTT)
    job_id = enqueue(pool, drop, "source-vtt")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)
    recorded = sources(pool, meeting["id"])
    assert set(recorded) == {"provided-text", "provided-vtt"}
    assert recorded["provided-vtt"]["format"] == "vtt"
    assert recorded["provided-vtt"]["segment_count"] == 2

    rows = segments(pool, meeting["id"])
    # Labels came from the .txt for every row...
    assert [row["speaker_label"] for row in rows] == [
        "Goeke, Timothy", "Whitmore, Ellis", "Goeke, Timothy",
    ]
    # ...and the two matching cues supplied real ends, naming the VTT as the
    # timing source; the unmatched third turn falls back to the .txt.
    assert [row["end_ms"] for row in rows[:2]] == [4_900, 7_400]
    assert [row["timing_source_id"] for row in rows[:2]] == [
        recorded["provided-vtt"]["id"]
    ] * 2
    assert rows[2]["timing_source_id"] == recorded["provided-text"]["id"]
    assert {row["label_source_id"] for row in rows} == {recorded["provided-text"]["id"]}


def test_an_unparseable_vtt_is_recorded_empty_and_the_text_still_used(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    drop = make_transcript_drop("source-badvtt", vtt="WEBVTT\n\nnot a cue at all\n")
    job_id = enqueue(pool, drop, "source-badvtt")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)
    assert sources(pool, meeting["id"])["provided-vtt"]["segment_count"] == 0
    assert len(segments(pool, meeting["id"])) == 3


def test_a_transcript_matching_neither_lineage_fails_the_stage(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """A provided transcript is never silently ignored (AD-13)."""
    drop = make_transcript_drop("source-junk", text="just prose, no timestamps\n")
    job_id = enqueue(pool, drop, "source-junk")

    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["align"] == "failed"
    error = stage_error(pool, job_id, "align") or ""
    assert "transcript.txt" in error
    status, job_error = job_row(pool, job_id)
    assert status == "failed"
    assert job_error is not None and "stage align failed" in job_error


# --- the STT verification lane --------------------------------------------


@requires_ffmpeg
def test_recording_plus_transcript_anchors_rows_to_the_stt_lane(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    fake_stt: Callable[..., FakeStt],
) -> None:
    fake_ocr(default=SCREEN_A)
    engine = fake_stt(
        (
            (2_400, 4_800, "everybody good morning"),
            (5_100, 7_000, "morning all"),
            (30_000, 32_000, "something else entirely much later on"),
        )
    )
    job_id = enqueue(pool, make_recording_transcript_drop("source-both"), "source-both")

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["transcribe"] == "done" and statuses["align"] == "done"
    meeting = only_meeting(pool, job_id)

    # The extracted audio lives under this meeting's own subtree (AD-3).
    recorded = sources(pool, meeting["id"])
    stt = recorded["stt"]
    assert stt["format"] == "stt"
    assert stt["engine"] == "fake-stt" and stt["language"] == "en"
    assert stt["segment_count"] == 3
    assert stt["drop_relative_path"] is None
    assert stt["content_path"] == f"meetings/{meeting['id']}/{AUDIO_SUBDIR}/audio.wav"
    assert (content_root / stt["content_path"]).is_file()
    assert engine.calls and engine.calls[0].name == "audio.wav"

    rows = segments(pool, meeting["id"])
    # Two turns anchored inside the ±2s window; the third had no candidate.
    assert [row["stt_start_ms"] for row in rows] == [2_400, 5_100, None]
    assert [row["alignment_delta_ms"] for row in rows] == [400, 100, None]
    assert [row["stt_source_id"] for row in rows[:2]] == [stt["id"], stt["id"]]
    assert rows[2]["stt_source_id"] is None and rows[2]["match_score"] is None
    assert all(row["match_score"] > 0 for row in rows[:2])
    # Labels still come from the provided transcript, not from STT.
    assert rows[0]["speaker_label"] == "Goeke, Timothy"
    assert {row["label_source_id"] for row in rows} == {recorded["provided-text"]["id"]}


@requires_ffmpeg
def test_recording_without_a_transcript_yields_unknown_placeholders(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    fake_stt: Callable[..., FakeStt],
) -> None:
    """AD-13: no transcript plus the noop diarizer means `Unknown`."""
    fake_ocr(default=SCREEN_A)
    fake_stt(((0, 1_500, "everybody good morning"), (2_000, 3_500, "morning all")))
    drop = make_recording_transcript_drop("source-stt-only", text=None)
    job_id = enqueue(pool, drop, "source-stt-only")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)
    rows = segments(pool, meeting["id"])
    assert [row["text"] for row in rows] == ["everybody good morning", "morning all"]
    assert all(row["speaker_label"] == "Unknown" for row in rows)
    assert all(row["speaker_resolution"] == "placeholder" for row in rows)
    assert all(row["participant_id"] is None for row in rows)
    # An STT segment aligned to itself is not evidence of anything.
    assert all(row["alignment_delta_ms"] is None for row in rows)
    assert participants(pool) == []
    assert meeting_participants(pool, meeting["id"]) == []


@requires_ffmpeg
def test_an_stt_failure_is_recorded_on_the_stage_and_the_job(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from meetingminer.adapters.stt import SttError

    fake_ocr(default=SCREEN_A)

    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        raise SttError("no usable STT engine: mlx-whisper is unavailable — uv sync")

    monkeypatch.setattr(transcribe_stage, "build_stt", unavailable)
    job_id = enqueue(pool, make_recording_transcript_drop("source-nostt"), "source-nostt")

    assert runner.run_once(pool, app_config, content_root) is True

    assert stage_statuses(pool, job_id)["transcribe"] == "failed"
    error = stage_error(pool, job_id, "transcribe") or ""
    assert "mlx-whisper" in error and "uv sync" in error
    status, job_error = job_row(pool, job_id)
    assert status == "failed"
    assert job_error is not None and "stage transcribe failed" in job_error
    # The run stopped at the failure: `align` never started.
    assert stage_statuses(pool, job_id)["align"] == "queued"
    assert segments(pool, only_meeting(pool, job_id)["id"]) == []


@requires_ffmpeg
def test_a_pyannote_binding_fails_the_stage_with_the_documented_reason(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    fake_stt: Callable[..., FakeStt],
) -> None:
    fake_ocr(default=SCREEN_A)
    fake_stt()
    config = app_config.model_copy(deep=True)
    config.settings.diarizer = config.settings.diarizer.model_copy(
        update={"engine": "pyannote"}
    )
    job_id = enqueue(pool, make_recording_transcript_drop("source-pyannote"), "source-pyannote")

    assert runner.run_once(pool, config, content_root) is True

    assert stage_statuses(pool, job_id)["transcribe"] == "failed"
    assert "not bundled" in (stage_error(pool, job_id, "transcribe") or "")
    assert job_row(pool, job_id)[0] == "failed"


# --- the drop is read-only -------------------------------------------------


def test_the_drop_is_never_written_by_the_transcript_stages(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """AD-13: the provided transcript is parsed in place, never rewritten."""
    drop = make_transcript_drop("source-readonly-txt", vtt=SPEAKERLESS_VTT)
    before = {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(drop.iterdir())
    }
    enqueue(pool, drop, "source-readonly-txt")
    runner.run_once(pool, app_config, content_root)
    after = {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(drop.iterdir())
    }
    assert before == after


# --- reruns ----------------------------------------------------------------


def rerun_align(pool: ConnectionPool, app_config: AppConfig, content_root: Path, job_id: UUID) -> None:
    """Put the job back to `align` and advance it again."""
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'queued' WHERE job_id = %s AND name = 'align'",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'queued' WHERE id = %s", (job_id,))
    assert runner.run_once(pool, app_config, content_root) is True


def test_an_align_rerun_replaces_rows_without_duplicating_them(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    job_id = enqueue(pool, make_transcript_drop("source-rerun"), "source-rerun")
    runner.run_once(pool, app_config, content_root)
    meeting = only_meeting(pool, job_id)
    first = segments(pool, meeting["id"])
    first_participants = participants(pool)

    rerun_align(pool, app_config, content_root, job_id)

    second = segments(pool, meeting["id"])
    assert [row["ordinal"] for row in second] == [row["ordinal"] for row in first]
    assert [row["text"] for row in second] == [row["text"] for row in first]
    assert len(meeting_participants(pool, meeting["id"])) == 2
    # Cross-meeting participants are upserted, never deleted by a rerun (AD-11).
    assert [row[0] for row in participants(pool)] == [row[0] for row in first_participants]


def test_two_meetings_naming_one_person_share_one_participant_row(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    first = enqueue(pool, make_transcript_drop("source-p1"), "source-p1")
    runner.run_once(pool, app_config, content_root)
    second = enqueue(pool, make_transcript_drop("source-p2"), "source-p2")
    runner.run_once(pool, app_config, content_root)

    rows = participants(pool)
    assert [key for _, key, _ in rows] == ["name:ellis whitmore", "name:timothy goeke"]
    first_meeting = only_meeting(pool, first)["id"]
    second_meeting = only_meeting(pool, second)["id"]
    assert {p["participant_id"] for p in meeting_participants(pool, first_meeting)} == {
        p["participant_id"] for p in meeting_participants(pool, second_meeting)
    }

    rerun_align(pool, app_config, content_root, first)
    assert [row[0] for row in participants(pool)] == [row[0] for row in rows]


def test_an_alias_row_redirects_the_insert_and_survives_the_rerun(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """AD-5: an API-owned merge is resolved before any insert."""
    job_id = enqueue(pool, make_transcript_drop("source-alias"), "source-alias")
    runner.run_once(pool, app_config, content_root)
    meeting = only_meeting(pool, job_id)["id"]
    by_key = {key: pid for pid, key, _ in participants(pool)}
    survivor = by_key["name:timothy goeke"]

    # The API merges `Whitmore, Ellis` into the surviving participant.
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO participant_alias (alias_key, participant_id) VALUES (%s, %s)",
            ("name:ellis whitmore", survivor),
        )
        conn.execute("DELETE FROM meeting_participant WHERE participant_id = %s",
                     (by_key["name:ellis whitmore"],))
        conn.execute("DELETE FROM participant WHERE id = %s", (by_key["name:ellis whitmore"],))

    rerun_align(pool, app_config, content_root, job_id)

    # The merged-away identity is not re-created, and every segment points at
    # the survivor.
    assert [key for _, key, _ in participants(pool)] == ["name:timothy goeke"]
    assert {row["participant_id"] for row in segments(pool, meeting)} == {survivor}
    assert [p["participant_id"] for p in meeting_participants(pool, meeting)] == [survivor]


def test_a_vtt_only_drop_still_derives_a_transcript(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """A speaker-less VTT alone is a first-class drop shape, not a dead end.

    `read_drop` accepts a drop whose only evidence is `transcript.vtt`, and
    story 1.8's puller emits that shape often. Every other align test supplies
    a `.txt` as well, so the VTT-only label-source branch was never taken: a
    reviewer simplifying it away would fail every such meeting's job with a
    green suite.
    """
    drop = make_transcript_drop("source-vtt-only", text=None, vtt=SPEAKERLESS_VTT)
    job_id = enqueue(pool, drop, "source-vtt-only")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)["id"]
    assert stage_statuses(pool, job_id)["align"] == "done"
    recorded = sources(pool, meeting)
    assert set(recorded) == {"provided-vtt"}

    rows = segments(pool, meeting)
    assert [row["text"] for row in rows] == ["Everybody, good morning.", "Morning, all."]
    # A VTT never supplies a speaker, so every turn is an honest placeholder.
    assert all(row["speaker_resolution"] == "placeholder" for row in rows)
    assert all(row["participant_id"] is None for row in rows)
    # Its own cue timings are both the labels' source and the timing source.
    vtt_id = recorded["provided-vtt"]["id"]
    assert {row["label_source_id"] for row in rows} == {vtt_id}
    assert {row["timing_source_id"] for row in rows} == {vtt_id}
    assert [row["start_ms"] for row in rows] == [2_100, 5_000]
    assert [row["end_ms"] for row in rows] == [4_900, 7_400]
    # No graph and no non-placeholder label means nobody to invent.
    assert participants(pool) == []


def test_a_nul_in_a_provided_transcript_does_not_cost_the_meeting_its_rows(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """The transcript twin of the OCR NUL test.

    Postgres refuses U+0000 in text and in jsonb alike, so one bad byte in a
    two-hour transcript would otherwise fail `align` and cost the meeting every
    row it has.
    """
    drop = make_transcript_drop(
        "source-nul",
        text="[0:01] Goeke, Tim\x00othy: hello\x00 there\n",
    )
    job_id = enqueue(pool, drop, "source-nul")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)["id"]
    assert stage_statuses(pool, job_id)["align"] == "done"
    row = segments(pool, meeting)[0]
    assert "\x00" not in row["text"]
    assert "\x00" not in row["speaker_label"]
    assert row["text"] == "hello there"


def test_a_removed_vtt_does_not_leave_a_source_row_describing_it(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """Stale provenance is a claim about a file that is not there."""
    drop = make_transcript_drop("source-lostvtt", vtt=SPEAKERLESS_VTT)
    job_id = enqueue(pool, drop, "source-lostvtt")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)["id"]
    assert set(sources(pool, meeting)) == {"provided-text", "provided-vtt"}

    (drop / "transcript.vtt").unlink()
    rerun_align(pool, app_config, content_root, job_id)

    assert set(sources(pool, meeting)) == {"provided-text"}
    # The derived rows survive and none still names the removed source.
    rows = segments(pool, meeting)
    assert rows
    assert all(row["timing_source_id"] == sources(pool, meeting)["provided-text"]["id"] for row in rows)


# --- the drop's participant graph -----------------------------------------

# `mail` is a real address from the SharePoint user-profile service, carried on
# nearly every person-row, and NOT the employee-number login, which is a
# different field the chart does not carry. The external attendee is marked by
# `unresolved: true` with an empty mail, not by `guest`, which is false on every
# row.
GRAPH = [
    {
        "displayName": "Goeke, Timothy",
        "mail": "timothy.goeke@contoso.com",
        "title": "Director",
        "department": "CORPORATE IT 452A - 102",
        "deptCode": "452A",
        "lineOfBusiness": "Corporate",
        "office": "Reston",
        "org": "CONTOSO",
        "guest": False,
        "unresolved": False,
        "foundIn": ["invite", "transcript"],
        "spokeTurns": 2,
        "spokeWords": 11,
    },
    {
        "displayName": "Whitmore, Ellis",
        "mail": "ellis.whitmore@contoso.com",
        "guest": False,
        "unresolved": False,
        "foundIn": ["invite"],
    },
    {
        "displayName": "Holloway, Linden",
        # An external carries no mail, so identity falls back to the name.
        "mail": "",
        "guest": False,
        # The graph's `unresolved: true` marks an external vendor attendee.
        # `guest` is false on every row — keying the check on it would find
        # nobody.
        "unresolved": True,
        "foundIn": ["invite"],
    },
]


def test_a_participant_graph_becomes_the_roster_and_keeps_externals(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    drop = make_transcript_drop("source-graph", participants=GRAPH)
    job_id = enqueue(pool, drop, "source-graph")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)["id"]
    people = {p["identity_key"]: p for p in meeting_participants(pool, meeting)}
    # A person the graph gave a mail is keyed on it; the external, which has
    # none, falls back to the normalized name.
    assert set(people) == {
        "mail:timothy.goeke@contoso.com",
        "mail:ellis.whitmore@contoso.com",
        "name:linden holloway",
    }
    people = {key.split(":", 1)[1]: value for key, value in people.items()}

    # Both graph fields survive verbatim; department is the readable org name.
    assert people["timothy.goeke@contoso.com"]["mail"] == "timothy.goeke@contoso.com"
    assert people["timothy.goeke@contoso.com"]["department"] == "CORPORATE IT 452A - 102"
    assert people["timothy.goeke@contoso.com"]["spoke_turns"] == 2
    assert people["timothy.goeke@contoso.com"]["found_in"] == ["invite", "transcript"]
    # Spoke and in the graph.
    assert people["timothy.goeke@contoso.com"]["derived_from"] == "both"
    assert people["ellis.whitmore@contoso.com"]["derived_from"] == "both"
    # In the graph, never spoke — still a meeting participant.
    assert people["linden holloway"]["derived_from"] == "drop-graph"
    # The external attendee is kept as external, never dropped or merged.
    assert people["linden holloway"]["is_external"] is True
    assert people["timothy.goeke@contoso.com"]["is_external"] is False


def test_a_graph_entry_without_a_display_name_is_rejected_before_the_stage(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """The drop schema requires `displayName`, so the drop read catches it first."""
    drop = make_transcript_drop(
        "source-badgraph",
        participants=[{"displayName": "Goeke, Timothy"}, {"mail": "nobody@example.com"}],
    )
    job_id = enqueue(pool, drop, "source-badgraph")

    assert runner.run_once(pool, app_config, content_root) is True

    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "participants/1" in error
    # `align` never ran, so nothing about it is claimed either way.
    assert stage_statuses(pool, job_id)["align"] == "queued"


def test_the_stage_still_guards_a_nameless_graph_entry_by_index() -> None:
    """Defence in depth: the stage names the index even if a drop got past the schema."""
    from meetingminer.pipeline.stage import StageError
    from meetingminer.pipeline.stages.align import _graph_roster

    class _Ctx:
        class drop:  # noqa: N801 - a stand-in, not a class the code defines
            metadata = {"participants": [{"displayName": "Cameron"}, {"mail": "x@y.z"}]}

    with pytest.raises(StageError, match=r"participants\[1\]"):
        _graph_roster(_Ctx)  # type: ignore[arg-type]


def test_a_speaker_the_graph_does_not_contain_stays_unresolved(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """A label matching nobody is never merged into a resolved person."""
    drop = make_transcript_drop(
        "source-stranger", participants=[{"displayName": "Goeke, Timothy"}]
    )
    job_id = enqueue(pool, drop, "source-stranger")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)["id"]
    rows = segments(pool, meeting)
    by_label = {row["speaker_label"]: row for row in rows}
    assert by_label["Whitmore, Ellis"]["speaker_resolution"] == "unresolved"
    assert by_label["Whitmore, Ellis"]["participant_id"] is None
    assert [key for _, key, _ in participants(pool)] == ["name:timothy goeke"]


def test_two_roster_kendalls_leave_a_bare_first_name_ambiguous(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    drop = make_transcript_drop(
        "source-kendalls",
        text="[0:01] Kendall: which Kendall is this\n[0:05] Kingsley, Kendall: this one\n",
        participants=[{"displayName": "Kingsley, Kendall"}, {"displayName": "Inglewood, Kendall"}],
    )
    job_id = enqueue(pool, drop, "source-kendalls")

    assert runner.run_once(pool, app_config, content_root) is True

    rows = segments(pool, only_meeting(pool, job_id)["id"])
    assert rows[0]["speaker_resolution"] == "ambiguous"
    assert rows[0]["participant_id"] is None
    assert rows[1]["speaker_resolution"] == "resolved"
    assert rows[1]["participant_id"] is not None


def test_two_people_sharing_a_name_never_collapse_onto_one_participant(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
) -> None:
    """The failure a name-only identity key makes silent.

    Two different humans, one written name. Keyed on the name they become one
    `participant` row and every turn is attributed to whichever the upsert saw
    first — a wrong attribution with nothing recording that it happened. Keyed
    on mail they stay two people, and the shared label is honestly ambiguous.
    """
    drop = make_transcript_drop(
        "source-namesakes",
        text="[0:01] Kingsley, Kendall: which of us is this\n",
        participants=[
            {"displayName": "Kingsley, Kendall", "mail": "kendall.kingsley@contoso.com"},
            {"displayName": "Kingsley, Kendall", "mail": "kendall.kingsley2@contoso.com"},
        ],
    )
    job_id = enqueue(pool, drop, "source-namesakes")

    assert runner.run_once(pool, app_config, content_root) is True

    assert [key for _, key, _ in participants(pool)] == [
        "mail:kendall.kingsley2@contoso.com",
        "mail:kendall.kingsley@contoso.com",
    ]
    meeting = only_meeting(pool, job_id)["id"]
    assert len(meeting_participants(pool, meeting)) == 2

    # Both are real people in this meeting, so the label naming both of them
    # attributes to neither.
    row = segments(pool, meeting)[0]
    assert row["speaker_resolution"] == "ambiguous"
    assert row["participant_id"] is None


# --- the stage's summary log ----------------------------------------------


def test_align_logs_one_summary_event_with_the_resolution_split(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_transcript_drop: Callable[..., Path],
    capsys,
) -> None:
    drop = make_transcript_drop("source-log", text=LEGACY_TRANSCRIPT)
    enqueue(pool, drop, "source-log")
    runner.run_once(pool, app_config, content_root)

    records = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    [event] = [r for r in records if r["event"] == "stage.align.derived"]
    assert event["stage"] == "align"
    assert event["segment_count"] == 3
    assert event["label_format"] == "legacy"
    assert event["roster_source"] == "transcript"
    assert event["placeholder"] == 1
    assert event["resolved"] == 2
    assert sum(event[name] for name in speakers.RESOLUTIONS) == event["segment_count"]


# --- a recording job replaced by a transcript-only drop --------------------


@requires_ffmpeg
def test_a_transcript_only_retry_clears_the_stt_lane_and_re_derives(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    make_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    fake_stt: Callable[..., FakeStt],
) -> None:
    """The STT lane must not survive as evidence of a recording that is gone."""
    fake_ocr(default=SCREEN_A)
    fake_stt(((2_400, 4_800, "everybody good morning"),))
    job_id = enqueue(pool, make_recording_transcript_drop("source-swap"), "source-swap")
    runner.run_once(pool, app_config, content_root)
    meeting = only_meeting(pool, job_id)["id"]
    assert "stt" in sources(pool, meeting)
    audio_dir = content_root / "meetings" / str(meeting) / AUDIO_SUBDIR
    assert audio_dir.is_dir()

    # The job failed later and is retried against a drop with no recording.
    replacement = make_transcript_drop("source-swap")
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job SET status = 'queued', drop_relative_path = %s"
            " WHERE id = %s",
            (replacement.name, job_id),
        )
        conn.execute(
            "UPDATE job_stage SET status = 'failed' WHERE job_id = %s AND name = 'moments'",
            (job_id,),
        )

    assert runner.run_once(pool, app_config, content_root) is True

    recorded = sources(pool, meeting)
    assert "stt" not in recorded, "the STT lane is gone with the recording"
    assert not audio_dir.exists()
    statuses = stage_statuses(pool, job_id)
    assert all(statuses[name] == "skipped" for name in runner.VIDEO_ONLY_STAGES)
    # `align` was put back to queued and re-derived from the transcript alone,
    # so the meeting still has its rows rather than a `done` checkpoint over
    # nothing.
    assert statuses["align"] == "done"
    rows = segments(pool, meeting)
    assert len(rows) == 3
    assert all(row["stt_source_id"] is None for row in rows)


@requires_ffmpeg
def test_transcribe_sanitizes_a_diarizer_label_before_jsonb_persistence(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    fake_stt: Callable[..., FakeStt],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diarizer output is JSONB-bound before align can sanitize labels."""
    fake_ocr(default=SCREEN_A)
    fake_stt(((2_000, 4_000, "everybody good morning"),))

    class NulDiarizer:
        name = "nul-diarizer"

        def diarize(self, _path: Path) -> tuple[DiarizationTurn, ...]:
            return (DiarizationTurn(1_000, 5_000, "SPEAKER\x00_00"),)

    monkeypatch.setattr(transcribe_stage, "build_diarizer", lambda *_args: NulDiarizer())
    job_id = enqueue(pool, make_recording_transcript_drop("source-diarizer-nul"), "source-diarizer-nul")

    assert runner.run_once(pool, app_config, content_root) is True

    meeting = only_meeting(pool, job_id)["id"]
    with pool.connection() as conn:
        payload = conn.execute(
            "SELECT segments FROM transcript_source WHERE meeting_id = %s AND kind = 'stt'",
            (meeting,),
        ).fetchone()[0]
    assert payload[0]["speaker"] == "SPEAKER_00"


@requires_ffmpeg
def test_a_transcribe_rerun_keeps_the_source_id_the_derived_rows_name(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
    fake_stt: Callable[..., FakeStt],
) -> None:
    """`transcribe` upserts its lane; it must never delete-then-insert it.

    `transcript_segment.stt_source_id` is `ON DELETE CASCADE`, so a delete
    would take every anchored derived row with it while `align` still reads
    `done` — a meeting with a green checkpoint over a half-emptied transcript.
    No other test re-runs `transcribe` with an audio stream present, so the
    `ON CONFLICT` arm was never executed.
    """
    fake_ocr(default=SCREEN_A)
    fake_stt(segments=[(2_000, 4_000, "good morning everybody")])
    job_id = enqueue(pool, make_recording_transcript_drop("source-reset"), "source-reset")
    assert runner.run_once(pool, app_config, content_root) is True
    meeting = only_meeting(pool, job_id)["id"]

    first_id = sources(pool, meeting)["stt"]["id"]
    assert first_id is not None
    assert [row["stt_source_id"] for row in segments(pool, meeting)].count(first_id) >= 1

    with pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'queued' WHERE job_id = %s"
            " AND name IN ('transcribe', 'align')",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'queued' WHERE id = %s", (job_id,))

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["transcribe"] == "done" and statuses["align"] == "done"
    # Same row, same id — the provenance the derived rows point at is stable.
    assert sources(pool, meeting)["stt"]["id"] == first_id
    rows = segments(pool, meeting)
    assert rows
    assert {row["stt_source_id"] for row in rows if row["stt_source_id"]} == {first_id}


def test_a_recording_with_no_audio_stream_records_no_stt_lane(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_transcript_drop: Callable[..., Path],
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """A silent recording has nothing to transcribe; that is a result, not a failure."""
    fake_ocr(default=SCREEN_A)
    job_id = enqueue(pool, make_recording_transcript_drop("source-silent"), "source-silent")
    runner.run_once(pool, app_config, content_root)
    meeting = only_meeting(pool, job_id)["id"]

    with pool.connection() as conn:
        conn.execute(
            "UPDATE meeting_media SET audio_codec = NULL WHERE meeting_id = %s", (meeting,)
        )
        conn.execute(
            "UPDATE job_stage SET status = 'queued' WHERE job_id = %s"
            " AND name IN ('transcribe', 'align')",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'queued' WHERE id = %s", (job_id,))

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["transcribe"] == "done" and statuses["align"] == "done"
    assert "stt" not in sources(pool, meeting)
    # The provided transcript still produced its rows, unanchored.
    rows = segments(pool, meeting)
    assert len(rows) == 3
    assert all(row["stt_source_id"] is None for row in rows)
