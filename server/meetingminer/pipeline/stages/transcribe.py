"""`transcribe` — the STT verification lane over the recording's audio (AD-8, AD-13).

The stage never names an engine. It asks
:func:`~meetingminer.adapters.stt.build_stt` and
:func:`~meetingminer.adapters.diarize.build_diarizer` for whatever
``config.yaml`` binds, so switching mlx-whisper for parakeet-mlx changes no
file outside ``adapters/stt/``.

What it produces is a *raw source*, not evidence: one ``kind='stt'``
`transcript_source` row carrying the recognizer's segments. `align` reconciles
that against the provided transcript and writes the derived rows. Keeping the
STT segments on their own source row — rather than as derived rows `align`
would then replace — is what lets `align` re-run any number of times and still
have a verification anchor to reconcile against.

Idempotent by replacement, and by *update in place*: the source row is upserted
on ``(meeting_id, 'stt')`` so its id survives a rerun and the derived rows that
name it keep valid provenance.

The audio itself rides the same staging/backup/atomic-swap protocol `frames`
and `screens` use, so a failed rerun leaves the previous WAV and rows intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from meetingminer.adapters.diarize import DiarizerError, build_diarizer
from meetingminer.adapters.diarize.port import DiarizationTurn
from meetingminer.adapters.stt import SttError, SttResult, build_stt
from meetingminer.domain.drops import sha256_and_size
from meetingminer.pipeline import media
from meetingminer.pipeline.outputs import OutputDirSwap, remove_meeting_subdir
from meetingminer.pipeline.stage import StageContext, StageError
from meetingminer.pipeline.transcripts import FORMAT_STT, strip_nuls

AUDIO_SUBDIR = "audio"
AUDIO_FILENAME = "audio.wav"

# Upsert, never delete-then-insert: the row id is provenance that derived
# `transcript_segment` rows point at, and a delete would cascade them away.
_UPSERT_SOURCE = """
INSERT INTO transcript_source (
    meeting_id, kind, format, drop_relative_path, content_path,
    sha256, byte_size, segment_count, engine, model, language, segments
) VALUES (
    %(meeting_id)s, 'stt', %(format)s, NULL, %(content_path)s,
    %(sha256)s, %(byte_size)s, %(segment_count)s, %(engine)s, %(model)s,
    %(language)s, %(segments)s
)
ON CONFLICT (meeting_id, kind) DO UPDATE SET
    format = EXCLUDED.format,
    drop_relative_path = EXCLUDED.drop_relative_path,
    content_path = EXCLUDED.content_path,
    sha256 = EXCLUDED.sha256,
    byte_size = EXCLUDED.byte_size,
    segment_count = EXCLUDED.segment_count,
    engine = EXCLUDED.engine,
    model = EXCLUDED.model,
    language = EXCLUDED.language,
    segments = EXCLUDED.segments
RETURNING id
"""

# One implementation of "did these bytes change", shared with `probe`, intake
# and the backfill (story 2.1a). Re-exported under the name this module has
# always used so its callers read unchanged.
sha256_of = sha256_and_size


def speaker_at(turns: tuple[DiarizationTurn, ...], start_ms: int, end_ms: int) -> str | None:
    """The diarization tag covering a segment, by longest overlap.

    ``None`` whenever the diarizer offered nothing — which is always, with the
    bundled noop engine — and the caller then records the ``Unknown``
    placeholder rather than a guessed name (AD-13).
    """
    best: tuple[int, str] | None = None
    for turn in turns:
        overlap = min(end_ms, turn.end_ms) - max(start_ms, turn.start_ms)
        if overlap > 0 and (best is None or overlap > best[0]):
            best = (overlap, turn.speaker)
    return best[1] if best else None


def _segment_payload(
    result: SttResult, turns: tuple[DiarizationTurn, ...]
) -> list[dict[str, Any]]:
    """The jsonb the STT lane is stored as, one entry per recognized segment."""
    payload: list[dict[str, Any]] = []
    for segment in result.segments:
        speaker = speaker_at(turns, segment.start_ms, segment.end_ms)
        payload.append(
            {
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": strip_nuls(segment.text),
                # This is stored as JSONB before align's label sanitation can
                # run, so diarizer output needs the same Postgres-safe guard.
                "speaker": strip_nuls(speaker) if speaker is not None else None,
            }
        )
    return payload


def _has_audio_stream(ctx: StageContext) -> bool:
    """Whether `probe` found an audio stream on this recording.

    A silent screen recording is a legitimate input with nothing to transcribe.
    Recording no STT source for it is an honest result; failing the job would
    cost the meeting its screens and its provided transcript over audio it
    never had.
    """
    row = ctx.conn.execute(
        "SELECT audio_codec FROM meeting_media WHERE meeting_id = %s", (ctx.meeting_id,)
    ).fetchone()
    # No probe row at all means nothing has claimed the recording is silent;
    # let ffmpeg be the judge rather than skipping on a missing fact.
    return row is None or row[0] is not None


def run(ctx: StageContext) -> None:
    recording = ctx.drop.recording_path
    if recording is None:  # pragma: no cover - the runner skips this stage without one
        raise StageError(
            "transcribe was reached for a drop with no recording.mp4 —"
            " the runner records video-only stages as skipped instead"
        )

    if not _has_audio_stream(ctx):
        ctx.conn.execute(
            "DELETE FROM transcript_source WHERE meeting_id = %s AND kind = 'stt'",
            (ctx.meeting_id,),
        )
        # An earlier run over a recording that still had audio may have
        # published `audio/`. Deleting only the row would strand the WAV on
        # disk with nothing naming it — the orphan `OutputDirSwap` exists to
        # prevent, and the same cleanup the runner does for a drop that turned
        # transcript-only. The removal takes the swap's backup and staging
        # siblings with it, so nothing can be restored onto it later.
        ctx.after_commit.append(
            lambda: remove_meeting_subdir(ctx.content_root, ctx.meeting_id, AUDIO_SUBDIR)
        )
        ctx.log(
            "stage.transcribe.no_audio",
            meeting_id=ctx.meeting_id,
            engine=None,
            segment_count=0,
        )
        return

    swap = OutputDirSwap(ctx, AUDIO_SUBDIR)
    staging = swap.open_staging()
    try:
        media.extract_audio(recording, staging / AUDIO_FILENAME)
    except media.MediaToolError as exc:
        swap.discard()
        raise StageError(str(exc)) from exc
    swap.publish()

    audio = swap.target / AUDIO_FILENAME
    try:
        try:
            engine = build_stt(ctx.config.settings.stt, log=ctx.log)
        except SttError as exc:
            raise StageError(str(exc)) from exc
        try:
            diarizer = build_diarizer(ctx.config.settings.diarizer)
        except DiarizerError as exc:
            raise StageError(str(exc)) from exc

        try:
            result = engine.transcribe(audio)
        except SttError as exc:
            raise StageError(str(exc)) from exc
        try:
            turns = tuple(diarizer.diarize(audio))
        except DiarizerError as exc:
            raise StageError(f"{diarizer.name} diarizer failed on {audio}: {exc}") from exc

        digest, byte_size = sha256_of(audio)
        payload = _segment_payload(result, turns)
        ctx.conn.execute(
            _UPSERT_SOURCE,
            {
                "meeting_id": ctx.meeting_id,
                "format": FORMAT_STT,
                "content_path": ctx.relative_path(audio),
                "sha256": digest,
                "byte_size": byte_size,
                "segment_count": len(payload),
                "engine": result.engine,
                "model": result.model,
                "language": result.language,
                "segments": Jsonb(payload),
            },
        )
    except Exception:
        swap.restore()
        raise
    swap.arm_hooks()

    ctx.log(
        "stage.transcribe.recognized",
        meeting_id=ctx.meeting_id,
        engine=result.engine,
        model=result.model,
        language=result.language,
        segment_count=len(payload),
        diarizer=diarizer.name,
        diarization_turns=len(turns),
        audio=ctx.relative_path(audio),
    )
