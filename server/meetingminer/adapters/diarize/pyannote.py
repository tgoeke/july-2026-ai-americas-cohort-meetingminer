"""The pyannote engine for the `Diarizer` port (story 7.1, FR36).

`build_diarizer` constructs this only after proving `pyannote.audio` is
importable and the configured token is present, and this module never imports
pyannote at import time: the real `Pipeline` load — a torch-sized import plus
a gated Hugging Face model download — is deferred to the first
:meth:`PyannoteDiarizer.diarize` call, through an injectable factory that is
also the test seam (tests inject a fake pipeline and never load a model).

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

# (model, token) -> a callable pipeline. The default is the real thing; tests
# inject a fake so nothing under `server/tests` imports pyannote.audio.
PipelineFactory = Callable[[str, str], Any]


def _load_pipeline(model: str, token: str) -> Any:
    """Import pyannote.audio and load the model — the only heavy path."""
    from pyannote.audio import Pipeline

    return Pipeline.from_pretrained(model, token=token)


def _to_turns(output: Any) -> tuple[DiarizationTurn, ...]:
    """Canonicalize one pipeline result into the port's turn tuple.

    4.x pipelines return a result object exposing ``.speaker_diarization``;
    3.x returned the annotation itself. Both iterate the same way.
    """
    annotation = getattr(output, "speaker_diarization", output)
    canonical: dict[str, str] = {}
    turns: list[DiarizationTurn] = []
    for segment, _track, label in annotation.itertracks(yield_label=True):
        tag = canonical.setdefault(str(label), f"SPEAKER_{len(canonical):02d}")
        turns.append(
            DiarizationTurn(
                start_ms=int(round(segment.start * 1000)),
                end_ms=int(round(segment.end * 1000)),
                speaker=tag,
            )
        )
    return tuple(turns)


class PyannoteDiarizer:
    """In-process pyannote.audio behind the `Diarizer` port."""

    name = ENGINE_NAME

    def __init__(
        self,
        model: str,
        token: str,
        pipeline_factory: PipelineFactory = _load_pipeline,
    ) -> None:
        self._model = model
        self._token = token
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any = None

    def diarize(self, path: Path) -> tuple[DiarizationTurn, ...]:
        if self._pipeline is None:
            try:
                self._pipeline = self._pipeline_factory(self._model, self._token)
            except Exception as exc:
                raise DiarizerError(
                    f"the {ENGINE_NAME} diarizer could not load model"
                    f" {self._model!r}: {exc}"
                ) from exc
        try:
            output = self._pipeline(str(path))
            return _to_turns(output)
        except DiarizerError:  # pragma: no cover - nothing below raises it today
            raise
        except Exception as exc:
            raise DiarizerError(
                f"the {ENGINE_NAME} diarizer failed on {path.name}: {exc}"
            ) from exc
