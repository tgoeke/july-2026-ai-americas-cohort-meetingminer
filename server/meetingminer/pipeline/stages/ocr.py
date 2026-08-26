"""`ocr` — recognize the text on every sampled frame (FR6, AD-8).

The stage never names an engine. It asks
:func:`~meetingminer.adapters.ocr.build_ocr` for whatever ``config.yaml``
binds, so switching Apple Vision for Tesseract changes no file outside
``adapters/ocr/``.

Idempotent by replacement: the meeting's `frame_ocr` rows are deleted and
rewritten, so a rerun cannot duplicate or leave rows behind from a denser
earlier sampling. Nothing outside this meeting is touched (AD-11), and no file
is written at all — the recognized text is the whole output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from meetingminer.adapters.ocr import OcrError, OcrResult, build_ocr
from meetingminer.pipeline.screens import normalize_text
from meetingminer.pipeline.stage import StageContext, StageError

_SELECT_FRAMES = (
    "SELECT id, path FROM frame WHERE meeting_id = %s ORDER BY offset_ms"
)

# Heartbeat cadence for the progress event. Small enough that a long stage
# shows movement within a few seconds, large enough not to flood the log.
PROGRESS_EVERY_FRAMES = 100

_INSERT = """
INSERT INTO frame_ocr (
    frame_id, meeting_id, engine, text, normalized_text,
    block_count, text_density, mean_block_height, blocks
) VALUES (
    %(frame_id)s, %(meeting_id)s, %(engine)s, %(text)s, %(normalized_text)s,
    %(block_count)s, %(text_density)s, %(mean_block_height)s, %(blocks)s
)
"""


NUL = "\x00"


def _strip_nuls(text: str) -> str:
    """Remove U+0000, which Postgres refuses in a text *or* jsonb value.

    A recognizer can emit one from a noisy frame. Dropping the byte keeps a
    readable frame readable; failing the stage over it would lose the whole
    meeting's OCR to one bad glyph.
    """
    return text.replace(NUL, "") if NUL in text else text


def _blocks_payload(result: OcrResult) -> list[dict[str, Any]]:
    """The jsonb rows for one recognition, with NULs stripped from the text.

    ``blocks`` is jsonb, and Postgres rejects ``\u0000`` there for the same
    reason it rejects it in text — so sanitizing only the flat columns would
    still fail the INSERT.
    """
    payload = []
    for block in result.blocks:
        entry = block.as_json()
        entry["text"] = _strip_nuls(entry["text"])
        payload.append(entry)
    return payload


def run(ctx: StageContext) -> None:
    frames = ctx.conn.execute(_SELECT_FRAMES, (ctx.meeting_id,)).fetchall()

    # Replace, never accumulate — and do it even when there is nothing to
    # write, so a rerun over a meeting whose frames vanished clears the text
    # that described them.
    ctx.conn.execute("DELETE FROM frame_ocr WHERE meeting_id = %s", (ctx.meeting_id,))

    if not frames:
        # `frames` legitimately completed with nothing to sample. Recognizing
        # nothing is a result, not a failure — and building the engine for it
        # would fail the stage on a host with no OCR at all. The same fields
        # are emitted as the non-empty path so a log consumer never has to
        # special-case zero.
        ctx.log(
            "stage.ocr.recognized",
            meeting_id=ctx.meeting_id,
            engine=None,
            frame_count=0,
            frames_with_text=0,
        )
        return

    try:
        engine = build_ocr(ctx.config.settings.ocr, log=ctx.log)
    except OcrError as exc:
        raise StageError(str(exc)) from exc

    frames_with_text = 0
    total = len(frames)
    for index, (frame_id, relative_path) in enumerate(frames, start=1):
        image = Path(ctx.content_root) / relative_path
        try:
            result = engine.recognize(image)
        except OcrError as exc:
            raise StageError(f"{engine.name} failed on frame {relative_path}: {exc}") from exc
        text = _strip_nuls(result.text)
        normalized = _strip_nuls(normalize_text(text))
        if normalized:
            frames_with_text += 1
        ctx.conn.execute(
            _INSERT,
            {
                "frame_id": frame_id,
                "meeting_id": ctx.meeting_id,
                "engine": result.engine,
                "text": text,
                "normalized_text": normalized,
                "block_count": result.block_count,
                "text_density": result.text_density,
                "mean_block_height": result.mean_block_height,
                "blocks": Jsonb(_blocks_payload(result)),
            },
        )
        # A 57-minute recording is ~1700 serial recognitions. Without a
        # heartbeat the stage looks hung for minutes on end.
        if index % PROGRESS_EVERY_FRAMES == 0 and index != total:
            ctx.log(
                "stage.ocr.progress",
                meeting_id=ctx.meeting_id,
                engine=engine.name,
                frames_done=index,
                frame_count=total,
                frames_with_text=frames_with_text,
            )

    ctx.log(
        "stage.ocr.recognized",
        meeting_id=ctx.meeting_id,
        engine=engine.name,
        frame_count=total,
        frames_with_text=frames_with_text,
    )
