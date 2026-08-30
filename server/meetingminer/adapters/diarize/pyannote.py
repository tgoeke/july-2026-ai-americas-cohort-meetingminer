"""The pyannote engine for the `Diarizer` port (story 7.1, FR36).

`build_diarizer` constructs this only after proving `pyannote.audio` is
importable and the configured token is present, and this module never imports
pyannote at import time: the real `Pipeline` load — a torch-sized import plus
a gated Hugging Face model download — is deferred to the first
:meth:`PyannoteDiarizer.diarize` call, through an injectable factory that is
also the test seam (tests inject a fake pipeline and never load a model).

The worker executes one stage at a time in a single thread, so the lazy
load below needs no lock; a concurrent-`diarize` caller would be a new
architecture, not a latent bug here.

Labels are canonicalized to recording-local ``SPEAKER_NN`` tags by first
appearance, whatever label shape pyannote's version emits (4.x community-1
yields bare indices; 3.x already yielded ``SPEAKER_NN``). A tag is a
placeholder by the never-guess rule (`pipeline/speakers.py`) and never
resolves to a participant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from meetingminer.adapters.diarize.port import DiarizationTurn, DiarizerError

ENGINE_NAME = "pyannote"
MAX_PLACEHOLDER_SPEAKERS = 1000

# (model, token) -> a callable pipeline. The default is the real thing; tests
# inject a fake so nothing under `server/tests` imports pyannote.audio.
PipelineFactory = Callable[[str, str], Any]


def _load_pipeline(model: str, token: str) -> Any:
    """Disable provider telemetry, then load the model — the only heavy path."""
    from pyannote.audio import Pipeline
    from pyannote.audio.telemetry import set_telemetry_metrics

    set_telemetry_metrics(False)
    return Pipeline.from_pretrained(model, token=token)


def _to_turns(output: Any) -> tuple[DiarizationTurn, ...]:
    """Canonicalize one pipeline result into the port's turn tuple.

    4.x pipelines return a result object exposing ``.speaker_diarization``;
    3.x returned the annotation itself. Both iterate the same way. Turns that
    collapse to nothing after rounding (``end_ms <= start_ms``) are dropped
    before their label can claim a tag, and the result is sorted by
    ``start_ms`` (stably) so callers see one timeline order regardless of
    pyannote's iteration order.
    """
    annotation = getattr(output, "speaker_diarization", output)
    canonical: dict[str, str] = {}
    turns: list[DiarizationTurn] = []
    for segment, _track, label in annotation.itertracks(yield_label=True):
        start_ms = round(segment.start * 1000)
        end_ms = round(segment.end * 1000)
        if end_ms <= start_ms:
            continue
        raw_label = str(label)
        tag = canonical.get(raw_label)
        if tag is None:
            if len(canonical) >= MAX_PLACEHOLDER_SPEAKERS:
                raise DiarizerError(
                    f"the {ENGINE_NAME} diarizer returned more than"
                    f" {MAX_PLACEHOLDER_SPEAKERS} distinct speakers; generated"
                    " tags support at most 1000 without leaving the"
                    " never-guess placeholder namespace"
                )
            tag = f"SPEAKER_{len(canonical):02d}"
            canonical[raw_label] = tag
        turns.append(DiarizationTurn(start_ms=start_ms, end_ms=end_ms, speaker=tag))
    return tuple(sorted(turns, key=lambda turn: turn.start_ms))


class PyannoteDiarizer:
    """In-process pyannote.audio behind the `Diarizer` port.

    The worker executes one stage at a time in one thread, so the lazy
    pipeline load below needs no lock: no two ``diarize`` calls ever race.
    """

    name = ENGINE_NAME

    def __init__(
        self,
        model: str,
        token: str,
        pipeline_factory: PipelineFactory = _load_pipeline,
    ) -> None:
        self.model = model
        self._token = token
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any = None

    def diarize(self, path: Path) -> tuple[DiarizationTurn, ...]:
        if self._pipeline is None:
            try:
                pipeline = self._pipeline_factory(self.model, self._token)
            except ImportError as exc:
                raise DiarizerError(
                    f"the {ENGINE_NAME} diarizer's import failed mid-load — a"
                    " broken or partial extra install. Reinstall it with"
                    " `uv sync --project server --extra diarize`."
                ) from exc
            except Exception as exc:
                raise DiarizerError(
                    f"the {ENGINE_NAME} diarizer could not load model"
                    f" {self.model!r}: {exc}"
                ) from exc
            if pipeline is None:
                # pyannote's from_pretrained has historically returned None
                # instead of raising when the Hub refuses the download.
                raise DiarizerError(
                    f"the {ENGINE_NAME} diarizer got no pipeline for model"
                    f" {self.model!r}: from_pretrained returned None. The"
                    " likely cause is the gated model licence not being"
                    " accepted on huggingface.co for the token's account."
                )
            self._pipeline = pipeline
        try:
            output = self._pipeline(str(path))
            return _to_turns(output)
        except DiarizerError:  # pragma: no cover - nothing below raises it today
            raise
        except Exception as exc:
            raise DiarizerError(
                f"the {ENGINE_NAME} diarizer failed on {path.name}: {exc}"
            ) from exc
