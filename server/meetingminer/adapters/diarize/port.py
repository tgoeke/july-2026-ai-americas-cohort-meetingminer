"""The `Diarizer` port: who spoke when, independent of what was said (AD-8).

Nothing in this module imports a provider. The `transcribe` stage asks
:func:`~meetingminer.adapters.diarize.build_diarizer` for whatever
``config.yaml`` binds and stamps the returned turns onto the STT lane's
segments; the `align` stage then reconciles those against the provided
transcript's real speaker labels.

Diarization never produces an *identity*. A turn's ``speaker`` is a
recording-local tag (``SPEAKER_00``), which is a placeholder by the never-guess
rule — only a provided transcript's labels resolve to a participant (AD-13).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class DiarizerError(RuntimeError):
    """The configured diarizer is unavailable, or a diarization failed.

    The `transcribe` stage turns it into a recorded
    :class:`~meetingminer.pipeline.stage.StageError`.
    """


@dataclass(frozen=True)
class DiarizationTurn:
    """One contiguous span attributed to one recording-local speaker tag.

    ``start_ms``/``end_ms`` are integer milliseconds from the start of the
    audio, the same clock the `Stt` port reports on.
    """

    start_ms: int
    end_ms: int
    speaker: str


class Diarizer(Protocol):
    """What every diarizer implements and every caller may rely on."""

    name: str

    def diarize(self, path: Path) -> tuple[DiarizationTurn, ...]:
        """Segment one audio file by speaker.

        An empty tuple is a legitimate result — it is what the bundled noop
        engine always returns — and means the caller has no speaker signal
        from audio at all.
        """
        ...
