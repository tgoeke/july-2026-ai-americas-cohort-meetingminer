"""The `Diarizer` binding: the one place an engine is named (AD-8, AD-10).

``noop`` is the default and the only bundled engine. ``pyannote`` is
*documented* in the architecture as the eventual alternative but is not
vendored, so binding it raises a :class:`DiarizerError` that says exactly that
and what installing it would take — rather than a stub engine module that can
never run, which would look built and fail at the worst moment.
"""

from __future__ import annotations

from typing import Protocol

from meetingminer.adapters.diarize.noop import NoopDiarizer
from meetingminer.adapters.diarize.port import DiarizationTurn, Diarizer, DiarizerError

__all__ = [
    "ENGINES",
    "DiarizationTurn",
    "Diarizer",
    "DiarizerBinding",
    "DiarizerError",
    "NoopDiarizer",
    "PYANNOTE_ENGINE",
    "build_diarizer",
]

PYANNOTE_ENGINE = "pyannote"

# Engine name in config.yaml -> implementation. `pyannote` is deliberately
# absent: it is a documented option, not a bundled one.
ENGINES: dict[str, type[Diarizer]] = {NoopDiarizer.name: NoopDiarizer}

PYANNOTE_UNAVAILABLE = (
    f"the {PYANNOTE_ENGINE} diarizer is documented in the architecture but not"
    " bundled: it is not a dependency of this project, its models are"
    " gated behind a Hugging Face licence acceptance, and it needs a PyTorch"
    " runtime the worker does not ship. Bind diarizer.engine to 'noop' in"
    " config.yaml, or vendor pyannote.audio and add an engine module beside"
    " this one."
)


class DiarizerBinding(Protocol):
    """Structural stand-in for :class:`meetingminer.config.DiarizerConfig`."""

    engine: str


def build_diarizer(diarizer_config: DiarizerBinding) -> Diarizer:
    """Construct the configured diarizer, or raise :class:`DiarizerError`."""
    engine_name = diarizer_config.engine
    if engine_name == PYANNOTE_ENGINE:
        raise DiarizerError(PYANNOTE_UNAVAILABLE)
    engine = ENGINES.get(engine_name)
    if engine is None:  # pragma: no cover - config validation rejects this first
        raise DiarizerError(
            f"unknown diarizer engine {engine_name!r} in config.yaml —"
            f" choose one of {', '.join(sorted(ENGINES))}"
        )
    return engine()
