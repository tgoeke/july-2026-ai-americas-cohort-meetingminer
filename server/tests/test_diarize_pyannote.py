"""The pyannote engine behind the `Diarizer` port (story 7.1, FR36).

Every path here runs without pyannote.audio installed: the build-time checks
are steered by monkeypatching the availability probe and the token env var,
and the engine itself is exercised through an injected fake pipeline — no
test loads (or could load) a real model.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import meetingminer.adapters.diarize as diarize_binding
from meetingminer.adapters.diarize import (
    DiarizationTurn,
    DiarizerError,
    NoopDiarizer,
    PyannoteDiarizer,
    build_diarizer,
)
from meetingminer.adapters.stt.port import SttResult, SttSegment
from meetingminer.config import AppConfig
from meetingminer.pipeline.speakers import is_placeholder_label
from meetingminer.pipeline.stages.transcribe import _segment_payload, speaker_at

TOKEN_ENV = "HF_TOKEN"


@dataclass(frozen=True)
class Binding:
    """Structural stand-in for DiarizerConfig."""

    engine: str = "pyannote"
    model: str = "pyannote/speaker-diarization-community-1"
    token_env: str = TOKEN_ENV


def _extra_installed(monkeypatch: pytest.MonkeyPatch, available: bool) -> None:
    monkeypatch.setattr(diarize_binding, "_pyannote_available", lambda: available)


# --- fakes standing in for pyannote's pipeline ----------------------------


@dataclass(frozen=True)
class FakeSegment:
    start: float
    end: float


class FakeAnnotation:
    """The 3.x shape: the pipeline result itself yields (segment, track, label)."""

    def __init__(self, tracks) -> None:
        self._tracks = tracks

    def itertracks(self, yield_label: bool = False):
        assert yield_label, "the engine must ask for labels"
        yield from self._tracks


class FakeCommunityResult:
    """The 4.x shape: the annotation hangs off `.speaker_diarization`."""

    def __init__(self, annotation) -> None:
        self.speaker_diarization = annotation


class FakePipeline:
    def __init__(self, output) -> None:
        self._output = output
        self.calls: list[str] = []

    def __call__(self, path: str):
        self.calls.append(path)
        return self._output


# Labels in every shape pyannote has shipped: bare index (4.x community-1),
# a letter, and 3.x's own SPEAKER_NN — the last deliberately colliding with
# the canonical namespace to prove first-appearance wins.
RAW_TRACKS = [
    (FakeSegment(0.5, 1.25), "t0", 0),
    (FakeSegment(1.25, 2.0), "t1", "A"),
    (FakeSegment(2.0, 3.5), "t2", "SPEAKER_00"),
    (FakeSegment(3.5, 4.0), "t3", 0),
]


def _engine(pipeline) -> PyannoteDiarizer:
    return PyannoteDiarizer(
        model="unit-test-model",
        token="hf_unit_test_token",
        pipeline_factory=lambda model, token: pipeline,
    )


# --- build-time: fail closed with named errors ----------------------------


def test_shipped_config_still_binds_noop(app_config: AppConfig) -> None:
    assert app_config.settings.diarizer.engine == NoopDiarizer.name
    assert app_config.settings.diarizer.model
    assert app_config.settings.diarizer.token_env == TOKEN_ENV


def test_noop_still_builds_and_offers_no_turns(tmp_path) -> None:
    diarizer = build_diarizer(Binding(engine="noop"))
    assert diarizer.name == "noop"
    assert diarizer.diarize(tmp_path / "audio.wav") == ()


def test_build_returns_pyannote_without_loading_a_model(monkeypatch) -> None:
    # This venv does not carry the extra, so success here is itself proof
    # that build time imports nothing and downloads nothing.
    _extra_installed(monkeypatch, True)
    monkeypatch.setenv(TOKEN_ENV, "hf_unit_test_token")
    diarizer = build_diarizer(Binding())
    assert isinstance(diarizer, PyannoteDiarizer)
    assert diarizer.name == "pyannote"


def test_missing_extra_fails_closed_naming_the_install_command(monkeypatch) -> None:
    _extra_installed(monkeypatch, False)
    monkeypatch.setenv(TOKEN_ENV, "hf_unit_test_token")
    with pytest.raises(DiarizerError) as raised:
        build_diarizer(Binding())
    message = str(raised.value)
    assert "not bundled" in message
    assert "noop" in message
    assert "uv sync --project server --extra diarize" in message


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_empty_token_fails_closed_naming_the_env_var(
    monkeypatch, value
) -> None:
    _extra_installed(monkeypatch, True)
    if value is None:
        monkeypatch.delenv(TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(TOKEN_ENV, value)
    with pytest.raises(DiarizerError) as raised:
        build_diarizer(Binding())
    message = str(raised.value)
    assert TOKEN_ENV in message
    assert "licence" in message
    assert "noop" in message


def test_the_token_env_var_name_is_config_driven(monkeypatch) -> None:
    _extra_installed(monkeypatch, True)
    monkeypatch.delenv("MM_TEST_HF", raising=False)
    with pytest.raises(DiarizerError, match="MM_TEST_HF"):
        build_diarizer(Binding(token_env="MM_TEST_HF"))
    monkeypatch.setenv("MM_TEST_HF", "hf_unit_test_token")
    built = build_diarizer(Binding(token_env="MM_TEST_HF"))
    assert isinstance(built, PyannoteDiarizer)


def test_an_unknown_engine_still_names_the_valid_choices() -> None:
    with pytest.raises(DiarizerError, match="noop"):
        build_diarizer(Binding(engine="whoisspeaking"))


# --- the engine over an injected pipeline ---------------------------------


def test_raw_labels_canonicalize_by_first_appearance_and_seconds_become_ms(
    tmp_path,
) -> None:
    engine = _engine(FakePipeline(FakeAnnotation(RAW_TRACKS)))
    turns = engine.diarize(tmp_path / "audio.wav")
    assert turns == (
        DiarizationTurn(start_ms=500, end_ms=1250, speaker="SPEAKER_00"),
        DiarizationTurn(start_ms=1250, end_ms=2000, speaker="SPEAKER_01"),
        DiarizationTurn(start_ms=2000, end_ms=3500, speaker="SPEAKER_02"),
        DiarizationTurn(start_ms=3500, end_ms=4000, speaker="SPEAKER_00"),
    )


def test_the_4x_result_shape_is_unwrapped(tmp_path) -> None:
    engine = _engine(
        FakePipeline(FakeCommunityResult(FakeAnnotation(RAW_TRACKS[:1])))
    )
    (turn,) = engine.diarize(tmp_path / "audio.wav")
    assert turn == DiarizationTurn(start_ms=500, end_ms=1250, speaker="SPEAKER_00")


def test_the_pipeline_is_loaded_lazily_and_once(tmp_path) -> None:
    loads: list[str] = []
    pipeline = FakePipeline(FakeAnnotation([]))

    def factory(model: str, token: str):
        loads.append(model)
        return pipeline

    engine = PyannoteDiarizer(model="m", token="t", pipeline_factory=factory)
    assert loads == []  # construction loads nothing
    engine.diarize(tmp_path / "a.wav")
    engine.diarize(tmp_path / "b.wav")
    assert loads == ["m"]
    assert len(pipeline.calls) == 2


def test_a_pipeline_failure_is_wrapped_in_diarizer_error(tmp_path) -> None:
    class ExplodingPipeline:
        def __call__(self, path: str):
            raise RuntimeError("inference exploded")

    engine = _engine(ExplodingPipeline())
    with pytest.raises(DiarizerError, match="audio.wav"):
        engine.diarize(tmp_path / "audio.wav")


def test_a_model_load_failure_is_wrapped_in_diarizer_error(tmp_path) -> None:
    def factory(model: str, token: str):
        raise RuntimeError("401: gated model, licence not accepted")

    engine = PyannoteDiarizer(model="m", token="t", pipeline_factory=factory)
    with pytest.raises(DiarizerError, match="could not load model"):
        engine.diarize(tmp_path / "audio.wav")


# --- the tag contract through the transcribe stage ------------------------


def test_tags_ride_segments_by_longest_overlap_and_stay_placeholders(
    tmp_path,
) -> None:
    engine = _engine(FakePipeline(FakeAnnotation(RAW_TRACKS)))
    turns = engine.diarize(tmp_path / "audio.wav")
    result = SttResult(
        segments=(
            # Inside SPEAKER_00's turn only.
            SttSegment(start_ms=600, end_ms=1200, text="hello"),
            # Straddles three turns; SPEAKER_01 has the longest overlap.
            SttSegment(start_ms=1100, end_ms=2200, text="world"),
            # Past every turn: no speaker signal at all.
            SttSegment(start_ms=9000, end_ms=9500, text="(silence)"),
        ),
        text="hello world (silence)",
        engine="unit-test",
        model="unit-test",
    )
    assert speaker_at(turns, 600, 1200) == "SPEAKER_00"
    payload = _segment_payload(result, turns)
    assert [entry["speaker"] for entry in payload] == [
        "SPEAKER_00",
        "SPEAKER_01",
        None,
    ]
    # No tag resolves to a participant: every stamped label is a placeholder
    # by the never-guess rule in pipeline/speakers.py.
    for entry in payload:
        assert entry["speaker"] is None or is_placeholder_label(entry["speaker"])
    assert is_placeholder_label("SPEAKER_00")
