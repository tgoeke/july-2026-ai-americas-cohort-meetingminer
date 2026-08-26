"""mlx-whisper engine for the `Stt` port — the macOS default (AD-8, AD-9).

Whisper on Apple's MLX runtime. The provider import is *lazy* on purpose: this
module must import cleanly on a host without the MLX wheels so
:func:`unavailable_reason` can report why the engine cannot run, instead of
the process dying at import time.

``mlx_whisper.transcribe(audio, path_or_hf_repo=model)`` returns a dict with
``text``, ``language``, and ``segments`` whose ``start``/``end`` are float
seconds; the port's contract is integer milliseconds, so every timing is
converted here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from meetingminer.adapters.stt.port import SttError, SttResult, SttSegment, to_ms

ENGINE_NAME = "mlx-whisper"

INSTALL_HINT = (
    "install it with 'uv sync --project server' (mlx-whisper is a macOS-only"
    " dependency and needs Apple silicon)"
)


def _import_provider() -> Any:
    """Import mlx_whisper, or raise :class:`SttError` naming what is missing."""
    if sys.platform != "darwin":
        raise SttError(
            f"{ENGINE_NAME} needs macOS on Apple silicon (this host is"
            f" {sys.platform}) — bind stt.engine to an engine this host can run"
        )
    try:
        import mlx_whisper  # noqa: PLC0415 - deliberately lazy (see module docstring)
    except ImportError as exc:
        raise SttError(
            f"{ENGINE_NAME} is unavailable: the {exc.name} package is not"
            f" importable — {INSTALL_HINT}"
        ) from exc
    return mlx_whisper


def unavailable_reason() -> str | None:
    """Why this engine cannot run here, or ``None`` when it can."""
    try:
        _import_provider()
    except SttError as exc:
        return str(exc)
    return None


class MlxWhisperStt:
    """The `Stt` port backed by mlx-whisper."""

    name = ENGINE_NAME

    def __init__(self, model: str) -> None:
        self._provider = _import_provider()
        self.model = model

    @staticmethod
    def unavailable_reason() -> str | None:
        return unavailable_reason()

    def transcribe(self, path: Path) -> SttResult:
        try:
            payload = self._provider.transcribe(str(path), path_or_hf_repo=self.model)
        except Exception as exc:  # noqa: BLE001 - the provider raises many types
            raise SttError(
                f"{ENGINE_NAME} failed on {path} with model {self.model}:"
                f" {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(payload, dict):  # pragma: no cover - provider contract
            raise SttError(
                f"{ENGINE_NAME} returned {type(payload).__name__}, not the"
                " expected result mapping"
            )

        segments: list[SttSegment] = []
        for entry in payload.get("segments") or []:
            if not isinstance(entry, dict):  # pragma: no cover - provider contract
                continue
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            start_ms = to_ms(entry.get("start"))
            # A recognizer can report an end at or before its start on a very
            # short segment; the schema requires end >= start.
            end_ms = max(to_ms(entry.get("end")), start_ms)
            segments.append(SttSegment(start_ms=start_ms, end_ms=end_ms, text=text))

        language = payload.get("language")
        return SttResult(
            segments=tuple(segments),
            text=str(payload.get("text", "")).strip(),
            engine=ENGINE_NAME,
            model=self.model,
            language=str(language) if language else None,
        )
