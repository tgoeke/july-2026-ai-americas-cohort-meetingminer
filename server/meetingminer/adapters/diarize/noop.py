"""The bundled no-op diarizer — the configured default (AD-8, AD-13).

It returns no turns at all, which is an honest answer rather than a stub: the
source audio is single-channel, so there is no
channel-based speaker separation to exploit, and speaker identity comes from
the transcript, not the waveform.

The consequence is written into AD-13: when no transcript is provided and this
is the bound diarizer, the derived segments carry the ``Unknown`` speaker
placeholder and a ``placeholder`` resolution — never a guessed name — and stay
editable through the API.
"""

from __future__ import annotations

from pathlib import Path

from meetingminer.adapters.diarize.port import DiarizationTurn

ENGINE_NAME = "noop"


class NoopDiarizer:
    """The `Diarizer` port with no speaker signal to offer."""

    name = ENGINE_NAME

    def diarize(self, path: Path) -> tuple[DiarizationTurn, ...]:
        return ()
