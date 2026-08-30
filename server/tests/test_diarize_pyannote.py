"""The pyannote engine behind the `Diarizer` port (story 7.1, FR36).

Every path here runs without pyannote.audio installed: the build-time checks
are steered by monkeypatching the availability probe and the token env var,
and the engine itself is exercised through an injected fake pipeline — no
test loads (or could load) a real model.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from types import ModuleType

import pytest

import meetingminer.adapters.diarize as diarize_binding
from meetingminer.adapters.diarize import (
    DiarizationTurn,
    DiarizerError,
    NoopDiarizer,
    PyannoteDiarizer,
    build_diarizer,
)
from meetingminer.adapters.diarize.pyannote import _load_pipeline
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
    monkeypatch.setenv(TOKEN_ENV, "  hf_unit_test_token \n")
    diarizer = build_diarizer(Binding())
    assert isinstance(diarizer, PyannoteDiarizer)
    assert diarizer.name == "pyannote"
    # Config values reach the engine: the binding's model, and the env token
    # stripped of the whitespace a paste into .env or a shell leaves behind.
    # (Private-attr read: the token deliberately has no public surface.)
    assert diarizer.model == Binding().model
    assert diarizer._token == "hf_unit_test_token"


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
    with pytest.raises(DiarizerError) as raised:
        build_diarizer(Binding(engine="whoisspeaking"))
    message = str(raised.value)
    assert "noop" in message
    assert "pyannote" in message  # a typo of the real engine must reveal it


@pytest.mark.parametrize("raised", [ImportError, ValueError])
def test_a_broken_install_probes_as_unavailable_not_as_a_crash(
    monkeypatch, raised
) -> None:
    # find_spec raises plain ImportError on a broken parent package and
    # ValueError when a module's __spec__ is None; both must mean "not
    # available", never an exception escaping build_diarizer.
    def exploding_find_spec(name: str):
        raise raised("broken install")

    monkeypatch.setattr("importlib.util.find_spec", exploding_find_spec)
    assert diarize_binding._pyannote_available() is False


def test_a_discoverable_but_unimportable_extra_fails_at_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())

    def broken_import(name: str):
        assert name == "pyannote.audio"
        raise RuntimeError("torch runtime is ABI-incompatible")

    monkeypatch.setattr("importlib.import_module", broken_import)
    monkeypatch.setenv(TOKEN_ENV, "hf_unit_test_token")

    with pytest.raises(DiarizerError, match="not bundled"):
        build_diarizer(Binding())


def test_an_imported_provider_without_a_callable_factory_fails_at_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())
    pyannote_audio = ModuleType("pyannote.audio")
    pyannote_audio.Pipeline = object()

    def import_provider(name: str):
        assert name == "pyannote.audio"
        return pyannote_audio

    monkeypatch.setattr("importlib.import_module", import_provider)
    monkeypatch.setenv(TOKEN_ENV, "hf_unit_test_token")

    with pytest.raises(DiarizerError, match="not bundled"):
        build_diarizer(Binding())


def test_an_imported_provider_without_the_telemetry_switch_fails_at_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())

    class StubPipeline:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            raise AssertionError("build must not construct a model")

    pyannote_audio = ModuleType("pyannote.audio")
    pyannote_audio.Pipeline = StubPipeline

    def import_provider(name: str):
        if name == "pyannote.audio":
            return pyannote_audio
        assert name == "pyannote.audio.telemetry"
        raise ImportError("telemetry module missing from partial install")

    monkeypatch.setattr("importlib.import_module", import_provider)
    monkeypatch.setenv(TOKEN_ENV, "hf_unit_test_token")

    with pytest.raises(DiarizerError, match="not bundled"):
        build_diarizer(Binding())


def test_the_real_probe_answers_without_raising() -> None:
    # No monkeypatch: whatever venv runs this, the probe must return a bool
    # rather than raise. In this wave's extra-free venv that answer is False,
    # but the assertion deliberately accepts an operator venv with the extra.
    assert diarize_binding._pyannote_available() in (False, True)


def test_the_pinned_pipeline_api_accepts_token() -> None:
    # Executes only where the diarize extra is installed (skips, with this
    # module named, in the extra-free venv every wave gate uses): pins the
    # 4.x `Pipeline.from_pretrained(model, token=...)` call contract the
    # default factory relies on.
    pyannote_audio = pytest.importorskip("pyannote.audio")
    parameters = inspect.signature(
        pyannote_audio.Pipeline.from_pretrained
    ).parameters
    assert "token" in parameters


def test_the_default_factory_forwards_the_configured_model_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    sentinel = object()

    class StubPipeline:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            calls.append((args, kwargs))
            return sentinel

    pyannote_package = ModuleType("pyannote")
    pyannote_package.__path__ = []
    pyannote_audio = ModuleType("pyannote.audio")
    pyannote_audio.__path__ = []
    pyannote_audio.Pipeline = StubPipeline
    pyannote_telemetry = ModuleType("pyannote.audio.telemetry")
    pyannote_telemetry.set_telemetry_metrics = lambda enabled: None
    pyannote_package.audio = pyannote_audio
    monkeypatch.setitem(sys.modules, "pyannote", pyannote_package)
    monkeypatch.setitem(sys.modules, "pyannote.audio", pyannote_audio)
    monkeypatch.setitem(
        sys.modules, "pyannote.audio.telemetry", pyannote_telemetry
    )

    assert _load_pipeline("configured-model", "configured-token") is sentinel
    assert calls == [
        (("configured-model",), {"token": "configured-token"}),
    ]


def test_the_default_factory_disables_telemetry_before_model_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    sentinel = object()

    class StubPipeline:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            events.append(("load", args, kwargs))
            return sentinel

    def set_telemetry_metrics(enabled: bool) -> None:
        events.append(("telemetry", enabled))

    pyannote_package = ModuleType("pyannote")
    pyannote_package.__path__ = []
    pyannote_audio = ModuleType("pyannote.audio")
    pyannote_audio.__path__ = []
    pyannote_audio.Pipeline = StubPipeline
    pyannote_telemetry = ModuleType("pyannote.audio.telemetry")
    pyannote_telemetry.set_telemetry_metrics = set_telemetry_metrics
    pyannote_package.audio = pyannote_audio
    monkeypatch.setitem(sys.modules, "pyannote", pyannote_package)
    monkeypatch.setitem(sys.modules, "pyannote.audio", pyannote_audio)
    monkeypatch.setitem(
        sys.modules, "pyannote.audio.telemetry", pyannote_telemetry
    )

    assert _load_pipeline("configured-model", "configured-token") is sentinel
    assert events == [
        ("telemetry", False),
        (
            "load",
            ("configured-model",),
            {"token": "configured-token"},
        ),
    ]


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


def test_a_half_installed_extra_is_named_as_such_at_load_time(tmp_path) -> None:
    # Build time only proves find_spec sees pyannote.audio; a torn install
    # surfaces as ImportError at the deferred import and must be reported as
    # an environment problem, not a model-download one.
    def factory(model: str, token: str):
        raise ImportError("libtorch missing")

    engine = PyannoteDiarizer(model="m", token="t", pipeline_factory=factory)
    with pytest.raises(DiarizerError, match="uv sync --project server --extra diarize"):
        engine.diarize(tmp_path / "audio.wav")


def test_a_factory_returning_none_is_a_licence_shaped_error(tmp_path) -> None:
    # pyannote's from_pretrained historically returns None — not an
    # exception — when the gated model's licence is unaccepted; that most
    # likely first-run failure must not surface as "'NoneType' is not
    # callable" at inference time.
    engine = PyannoteDiarizer(
        model="m", token="t", pipeline_factory=lambda model, token: None
    )
    with pytest.raises(DiarizerError, match="licence"):
        engine.diarize(tmp_path / "audio.wav")


def test_degenerate_turns_are_dropped_and_output_is_sorted(tmp_path) -> None:
    tracks = [
        # Out of order on purpose: the port contract is ascending start_ms.
        (FakeSegment(2.0, 3.0), "t1", "B"),
        # Rounds to 1000..1000: no span survives the ms clock.
        (FakeSegment(1.0, 1.0004), "t2", "C"),
        (FakeSegment(0.0, 1.0), "t0", "A"),
    ]
    engine = _engine(FakePipeline(FakeAnnotation(tracks)))
    turns = engine.diarize(tmp_path / "audio.wav")
    assert turns == (
        # Tags number by first *surviving* appearance: B first, then A.
        DiarizationTurn(start_ms=0, end_ms=1000, speaker="SPEAKER_01"),
        DiarizationTurn(start_ms=2000, end_ms=3000, speaker="SPEAKER_00"),
    )


def test_more_than_one_thousand_speakers_fails_before_a_tag_escapes_placeholder_protection(
    tmp_path,
) -> None:
    tracks = [
        (FakeSegment(float(index), float(index) + 0.5), f"t{index}", index)
        for index in range(1001)
    ]
    engine = _engine(FakePipeline(FakeAnnotation(tracks)))

    with pytest.raises(DiarizerError, match="at most 1000"):
        engine.diarize(tmp_path / "audio.wav")


def test_one_thousand_speakers_reaches_the_last_protected_placeholder(
    tmp_path,
) -> None:
    tracks = [
        (FakeSegment(float(index), float(index) + 0.5), f"t{index}", index)
        for index in range(1000)
    ]
    engine = _engine(FakePipeline(FakeAnnotation(tracks)))

    turns = engine.diarize(tmp_path / "audio.wav")

    assert len(turns) == 1000
    assert turns[-1].speaker == "SPEAKER_999"
    assert is_placeholder_label(turns[-1].speaker)


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
    # Three-digit tags stay inside the never-guess pattern too.
    assert is_placeholder_label("SPEAKER_100")
