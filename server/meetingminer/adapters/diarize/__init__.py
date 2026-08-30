"""The `Diarizer` binding: the one place an engine is named (AD-8, AD-10).

``noop`` is the default. ``pyannote`` (story 7.1) is a real in-process engine
behind the optional ``diarize`` dependency extra: binding it fails closed at
build time — before any work — with a :class:`DiarizerError` naming exactly
what is missing (the extra's install command, or the Hugging Face token and
licence acceptance). When both checks pass, the returned engine has still
loaded nothing: the model load is deferred to its first ``diarize`` call.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Protocol

from meetingminer.adapters.diarize.noop import NoopDiarizer
from meetingminer.adapters.diarize.port import DiarizationTurn, Diarizer, DiarizerError
from meetingminer.adapters.diarize.pyannote import PyannoteDiarizer

__all__ = [
    "ENGINES",
    "DiarizationTurn",
    "Diarizer",
    "DiarizerBinding",
    "DiarizerError",
    "NoopDiarizer",
    "PYANNOTE_ENGINE",
    "PyannoteDiarizer",
    "build_diarizer",
]

PYANNOTE_ENGINE = "pyannote"

# Engine name in config.yaml -> zero-argument implementation. `pyannote` is
# deliberately absent: it needs the availability and token checks plus config
# arguments, so `build_diarizer` special-cases it below.
ENGINES: dict[str, type[Diarizer]] = {NoopDiarizer.name: NoopDiarizer}

PYANNOTE_UNAVAILABLE = (
    f"the {PYANNOTE_ENGINE} diarizer is not bundled: pyannote.audio is the"
    " optional `diarize` extra (a torch-sized runtime, gated models), installed"
    " by hand with `uv sync --project server --extra diarize`. Until then, bind"
    " diarizer.engine to 'noop' in config.yaml."
)


def _pyannote_available() -> bool:
    """Whether `pyannote.audio` is importable — the extra-installed probe."""
    try:
        return importlib.util.find_spec("pyannote.audio") is not None
    except ModuleNotFoundError:
        # find_spec imports the parent package first; when no `pyannote`
        # distribution is installed at all, the probe lands here.
        return False


def _pyannote_token_missing(token_env: str) -> str:
    return (
        f"the {PYANNOTE_ENGINE} diarizer needs a Hugging Face token:"
        f" {token_env} is unset or empty. Accept the gated model licence on"
        f" huggingface.co, then put that account's token in .env as"
        f" {token_env} — or bind diarizer.engine to 'noop' in config.yaml."
    )


class DiarizerBinding(Protocol):
    """Structural stand-in for :class:`meetingminer.config.DiarizerConfig`."""

    engine: str
    model: str
    token_env: str


def build_diarizer(diarizer_config: DiarizerBinding) -> Diarizer:
    """Construct the configured diarizer, or raise :class:`DiarizerError`.

    Fails closed here, before any work: an unavailable engine never reaches a
    stage run. Returning the pyannote engine loads no model — that is
    deferred to its first ``diarize`` call.
    """
    engine_name = diarizer_config.engine
    if engine_name == PYANNOTE_ENGINE:
        if not _pyannote_available():
            raise DiarizerError(PYANNOTE_UNAVAILABLE)
        token = os.environ.get(diarizer_config.token_env) or ""
        if not token.strip():
            raise DiarizerError(_pyannote_token_missing(diarizer_config.token_env))
        return PyannoteDiarizer(model=diarizer_config.model, token=token)
    engine = ENGINES.get(engine_name)
    if engine is None:
        raise DiarizerError(
            f"unknown diarizer engine {engine_name!r} in config.yaml —"
            f" choose one of {', '.join(sorted(ENGINES))}"
        )
    return engine()
