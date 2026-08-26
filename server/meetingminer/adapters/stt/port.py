"""The `Stt` port: what feature code is allowed to know about speech-to-text (AD-8).

Nothing in this module imports a provider. The `transcribe` stage depends on
:class:`SttResult` and calls :meth:`Stt.transcribe`; which engine answers is
decided by ``config.yaml`` in :mod:`meetingminer.adapters.stt` and nowhere
else, so swapping ``mlx-whisper`` for ``parakeet-mlx`` is a config edit.

Timings are integer milliseconds from the start of the audio, matching the
project-wide offset convention (video offsets are integer ms from recording
start). Engines report float seconds; the conversion happens in the adapter so
no caller ever sees a float second.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SttError(RuntimeError):
    """The configured STT engine is unavailable, or a transcription failed.

    Carries a message naming the engine and, when the cause is a missing
    dependency, how to install it. The `transcribe` stage turns it into a
    recorded :class:`~meetingminer.pipeline.stage.StageError`.
    """


@dataclass(frozen=True)
class SttSegment:
    """One recognized span of speech.

    ``start_ms``/``end_ms`` are integer milliseconds from the start of the
    audio. No engine reports a speaker: attribution comes from the provided
    transcript or the `Diarizer` port, never from the recognizer.
    """

    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class SttResult:
    """Everything one transcription produced.

    ``model`` and ``language`` are recorded on the `transcript_source` row so a
    corpus mixing engines and models stays interpretable (AD-8). ``language``
    is ``None`` for engines that do not detect one.
    """

    segments: tuple[SttSegment, ...]
    text: str
    engine: str
    model: str
    language: str | None = None

    @property
    def segment_count(self) -> int:
        return len(self.segments)


class Stt(Protocol):
    """What every engine implements and every caller may rely on.

    ``unavailable_reason`` is part of the contract, not a convenience: the
    factory probes it on the class before constructing anything, so a host
    without the MLX wheels reports why instead of dying at import time.
    """

    name: str

    @staticmethod
    def unavailable_reason() -> str | None:
        """Why this engine cannot run on this host, or ``None`` when it can."""
        ...

    def transcribe(self, path: Path) -> SttResult:
        """Transcribe one audio file.

        Raises :class:`SttError` when the engine cannot read the audio or the
        underlying model fails.
        """
        ...


def to_ms(seconds: object) -> int:
    """Convert an engine's float seconds to the project's integer ms.

    Negative values are clamped to zero: a recognizer occasionally reports a
    small negative start for the first segment, and a negative offset would
    violate the `transcript_segment` CHECK constraint. Missing, non-numeric,
    and non-finite values are rejected instead of becoming a fabricated
    recording-start anchor.
    """
    if isinstance(seconds, bool):
        raise SttError(
            f"STT provider timestamp {seconds!r} is invalid; expected finite seconds"
        )
    try:
        value = float(seconds)
    except (TypeError, ValueError) as exc:
        raise SttError(
            f"STT provider timestamp {seconds!r} is invalid; expected finite seconds"
        ) from exc
    if not math.isfinite(value):
        raise SttError(
            f"STT provider timestamp {seconds!r} is invalid; expected finite seconds"
        )
    value = round(value * 1000)
    return max(value, 0)
