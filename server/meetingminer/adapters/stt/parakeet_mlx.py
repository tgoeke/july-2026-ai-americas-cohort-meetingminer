"""parakeet-mlx engine for the `Stt` port — the swappable alternative (AD-8).

NVIDIA's Parakeet models on Apple's MLX runtime. Same lazy-import contract as
:mod:`meetingminer.adapters.stt.mlx_whisper`: the provider is imported inside
the call so a host without the wheel reports unavailability rather than
failing at import.

``from_pretrained(model).transcribe(path)`` returns an ``AlignedResult`` with
``.text`` and ``.sentences``, each carrying float ``.start``/``.end``/``.text``.
Parakeet is English-only and reports no detected language, so ``language``
stays ``None`` rather than being asserted.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from meetingminer.adapters.stt.port import SttError, SttResult, SttSegment, to_ms

ENGINE_NAME = "parakeet-mlx"

INSTALL_HINT = (
    "install it with 'uv sync --project server' (parakeet-mlx is a macOS-only"
    " dependency and needs Apple silicon)"
)


def _import_provider() -> Callable[..., Any]:
    """Import ``from_pretrained``, or raise :class:`SttError` naming what is missing."""
    if sys.platform != "darwin":
        raise SttError(
            f"{ENGINE_NAME} needs macOS on Apple silicon (this host is"
            f" {sys.platform}) — bind stt.engine to an engine this host can run"
        )
    try:
        from parakeet_mlx import from_pretrained  # noqa: PLC0415 - deliberately lazy
    except ImportError as exc:
        raise SttError(
            f"{ENGINE_NAME} is unavailable: the {exc.name} package is not"
            f" importable — {INSTALL_HINT}"
        ) from exc
    return from_pretrained


def unavailable_reason() -> str | None:
    """Why this engine cannot run here, or ``None`` when it can."""
    try:
        _import_provider()
    except SttError as exc:
        return str(exc)
    return None


class ParakeetMlxStt:
    """The `Stt` port backed by parakeet-mlx."""

    name = ENGINE_NAME

    def __init__(self, model: str) -> None:
        self._from_pretrained = _import_provider()
        self.model = model
        # Loading weights is the expensive part, so it is deferred to the
        # first transcription: building the binding must stay cheap enough for
        # the factory to construct it before the stage knows it has work.
        self._loaded: Any | None = None

    @staticmethod
    def unavailable_reason() -> str | None:
        return unavailable_reason()

    def _model(self) -> Any:
        if self._loaded is None:
            try:
                self._loaded = self._from_pretrained(self.model)
            except Exception as exc:  # noqa: BLE001 - the provider raises many types
                raise SttError(
                    f"{ENGINE_NAME} could not load model {self.model}:"
                    f" {type(exc).__name__}: {exc}"
                ) from exc
        return self._loaded

    def transcribe(self, path: Path) -> SttResult:
        model = self._model()
        try:
            result = model.transcribe(path)
        except Exception as exc:  # noqa: BLE001 - the provider raises many types
            raise SttError(
                f"{ENGINE_NAME} failed on {path} with model {self.model}:"
                f" {type(exc).__name__}: {exc}"
            ) from exc

        segments: list[SttSegment] = []
        for sentence in getattr(result, "sentences", ()) or ():
            text = str(getattr(sentence, "text", "")).strip()
            if not text:
                continue
            start_ms = to_ms(getattr(sentence, "start", None))
            end_ms = max(to_ms(getattr(sentence, "end", None)), start_ms)
            segments.append(SttSegment(start_ms=start_ms, end_ms=end_ms, text=text))

        return SttResult(
            segments=tuple(segments),
            text=str(getattr(result, "text", "")).strip(),
            engine=ENGINE_NAME,
            model=self.model,
            language=None,
        )
