"""The `Stt` binding: the one place either engine is named (AD-8, AD-10).

Feature code calls :func:`build_stt` with ``config.settings.stt`` and gets back
something satisfying the :class:`~meetingminer.adapters.stt.port.Stt`
protocol. Which engine that is comes from ``config.yaml`` and nothing else, so
swapping ``mlx-whisper`` for ``parakeet-mlx`` changes no file outside this
package.

There is deliberately **no fallback key** here, unlike the `Ocr` binding: the
acceptance criterion asks for mlx-whisper as the default and parakeet-mlx as
*swappable*, not as an automatic substitute. Two recognizers silently
producing one corpus's verification lane would make `alignment_delta_ms`
incomparable across meetings.
"""

from __future__ import annotations

from typing import Callable, Protocol

from meetingminer.adapters.stt.mlx_whisper import MlxWhisperStt
from meetingminer.adapters.stt.parakeet_mlx import ParakeetMlxStt
from meetingminer.adapters.stt.port import Stt, SttError, SttResult, SttSegment

__all__ = [
    "ENGINES",
    "Stt",
    "SttBinding",
    "SttError",
    "SttResult",
    "SttSegment",
    "build_stt",
]

# Engine name in config.yaml -> implementation. Adding an engine is one entry
# here plus the Literal in meetingminer.config; no stage changes.
ENGINES: dict[str, type[Stt]] = {
    MlxWhisperStt.name: MlxWhisperStt,
    ParakeetMlxStt.name: ParakeetMlxStt,
}


class SttBinding(Protocol):
    """Structural stand-in for :class:`meetingminer.config.SttConfig`.

    Typed structurally rather than by import: this package stays free of
    project imports other than its own port, which is what keeps the engines
    substitutable and the dependency direction one-way.
    """

    engine: str
    model: str


def build_stt(stt_config: SttBinding, log: Callable[..., None] | None = None) -> Stt:
    """Construct the configured engine, or raise :class:`SttError` saying why not.

    The message names the engine and how to install it, so the stage failure a
    caller records tells an operator what to do rather than only that STT
    "did not work".
    """
    engine_name = stt_config.engine
    engine = ENGINES.get(engine_name)
    if engine is None:  # pragma: no cover - config validation rejects this first
        raise SttError(
            f"unknown STT engine {engine_name!r} in config.yaml —"
            f" choose one of {', '.join(sorted(ENGINES))}"
        )
    reason = engine.unavailable_reason()
    if reason is not None:
        raise SttError(f"no usable STT engine: {reason}")
    if log is not None:
        log("stt.engine.bound", engine=engine_name, model=stt_config.model)
    return engine(stt_config.model)  # type: ignore[call-arg]
