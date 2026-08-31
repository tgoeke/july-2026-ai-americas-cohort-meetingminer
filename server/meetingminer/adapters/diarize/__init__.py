"""The `Diarizer` binding: the one place an engine is named (AD-8, AD-10).

``noop`` is the default. ``pyannote`` (story 7.1) is a real in-process engine
behind the optional ``diarize`` dependency extra: binding it fails closed at
build time — before any work — with a :class:`DiarizerError` naming exactly
what is missing (the extra's install command, or the Hugging Face token and
licence acceptance). When both checks pass, the returned engine has still
loaded nothing: the model load is deferred to its first ``diarize`` call.

``remote-http`` (backlog B-36) is the LAN diarization service, which needs no
token at all. It has nothing to check at build time and deliberately does not
probe the host: that box is operator-scheduled, and a ``/health`` call here
would make "is it up right now" a build-time dependency of every transcribe
run. Its failures surface on the ``diarize`` call, by name (AD-9).

Neither engine is in :data:`ENGINES`. That registry maps a name to a
*zero-argument* class and constructs it as ``engine()``; both of these need
values off the binding, so both are special-cased in :func:`build_diarizer`
and both are named in :data:`ENGINE_CHOICES`, which is what keeps the
unknown-engine diagnostic an exhaustive list of what config.yaml accepts.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Protocol

from meetingminer.adapters.diarize.noop import NoopDiarizer
from meetingminer.adapters.diarize.port import DiarizationTurn, Diarizer, DiarizerError
from meetingminer.adapters.diarize.pyannote import PyannoteDiarizer
from meetingminer.adapters.diarize.remote_http import RemoteHttpDiarizer

__all__ = [
    "ENGINES",
    "ENGINE_CHOICES",
    "DiarizationTurn",
    "Diarizer",
    "DiarizerBinding",
    "DiarizerError",
    "NoopDiarizer",
    "PYANNOTE_ENGINE",
    "PyannoteDiarizer",
    "REMOTE_HTTP_ENGINE",
    "RemoteHttpDiarizer",
    "build_diarizer",
]

PYANNOTE_ENGINE = PyannoteDiarizer.name
REMOTE_HTTP_ENGINE = RemoteHttpDiarizer.name

# Engine name in config.yaml -> zero-argument implementation. `pyannote` and
# `remote-http` are deliberately absent: the first needs the availability and
# token checks plus config arguments, the second needs the endpoint and the
# timeout off the binding, and this registry's values are constructed
# `engine()` with none.
ENGINES: dict[str, type[Diarizer]] = {NoopDiarizer.name: NoopDiarizer}

# Every engine name config.yaml accepts — the registry plus the two
# special-cased above. The unknown-engine diagnostic enumerates this, so a new
# engine cannot be bound without appearing in the message that lists them.
ENGINE_CHOICES = sorted([*ENGINES, PYANNOTE_ENGINE, REMOTE_HTTP_ENGINE])

PYANNOTE_UNAVAILABLE = (
    f"the {PYANNOTE_ENGINE} diarizer is not bundled: pyannote.audio is the"
    " optional `diarize` extra (a torch-sized runtime, gated models), installed"
    " by hand with `uv sync --project server --extra diarize`. Until then, bind"
    " diarizer.engine to 'noop' in config.yaml."
)


def _pyannote_available() -> bool:
    """Whether the exact provider symbol needed at runtime is importable."""
    try:
        if importlib.util.find_spec("pyannote.audio") is None:
            return False
        module = importlib.import_module("pyannote.audio")
        pipeline = getattr(module, "Pipeline", None)
        if not callable(getattr(pipeline, "from_pretrained", None)):
            return False
        telemetry = importlib.import_module("pyannote.audio.telemetry")
        return callable(getattr(telemetry, "set_telemetry_metrics", None))
    except Exception:  # noqa: BLE001
        # find_spec imports the parent package first: no `pyannote`
        # distribution at all raises ModuleNotFoundError, a broken parent
        # can raise while resolving its spec, and a partial provider install
        # can fail while importing torch/native dependencies. Every one means
        # the configured engine is unavailable at the build boundary.
        return False


def _pyannote_token_missing(token_env: str) -> str:
    return (
        f"the {PYANNOTE_ENGINE} diarizer needs a Hugging Face token:"
        f" {token_env} is unset or empty in the worker's process environment."
        " Accept the gated model licence on huggingface.co, store that"
        f" account's token in .env as {token_env}, and export the variable in"
        " the shell that launches the worker — the host worker does not load"
        " .env into its process environment today. Or bind diarizer.engine to"
        " 'noop' in config.yaml."
    )


class DiarizerBinding(Protocol):
    """Structural mirror of :class:`meetingminer.config.DiarizerConfig`, whole.

    Every field is always present on the real config object, and each branch
    simply ignores the ones its engine does not use: ``noop`` reads none of
    them, ``pyannote`` reads ``model`` and ``token_env``, ``remote-http``
    reads ``base_url`` and ``timeout_seconds``.
    """

    engine: str
    model: str
    token_env: str
    base_url: str
    timeout_seconds: float


def build_diarizer(diarizer_config: DiarizerBinding) -> Diarizer:
    """Construct the configured diarizer, or raise :class:`DiarizerError`.

    Every misconfiguration fails closed here, before any work: an unknown
    engine name, a missing extra, an absent token. What is checked is what
    this process can know on its own — returning the pyannote engine loads no
    model, and returning the remote engine contacts no host; both defer to
    their first ``diarize`` call, which is also where their failures are named.
    """
    engine_name = diarizer_config.engine
    if engine_name == PYANNOTE_ENGINE:
        if not _pyannote_available():
            raise DiarizerError(PYANNOTE_UNAVAILABLE)
        token = (os.environ.get(diarizer_config.token_env) or "").strip()
        if not token:
            raise DiarizerError(_pyannote_token_missing(diarizer_config.token_env))
        return PyannoteDiarizer(model=diarizer_config.model, token=token)
    if engine_name == REMOTE_HTTP_ENGINE:
        # Nothing to check and nothing to reach. Whether the LAN host is up
        # right now is a fact about the `diarize` call, not about the binding:
        # probing it here would fail an ingest that never needed diarization.
        return RemoteHttpDiarizer(
            base_url=diarizer_config.base_url,
            timeout_seconds=diarizer_config.timeout_seconds,
        )
    engine = ENGINES.get(engine_name)
    if engine is None:
        raise DiarizerError(
            f"unknown diarizer engine {engine_name!r} in config.yaml —"
            f" choose one of {', '.join(ENGINE_CHOICES)}"
        )
    return engine()
