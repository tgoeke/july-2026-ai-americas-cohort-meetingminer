"""The `Stt` and `Diarizer` bindings: config picks the engine, nothing else does.

Story 1.5's first acceptance criterion is about the *ports*: mlx-whisper is the
STT default with parakeet-mlx swappable, and the diarizer defaults to noop with
pyannote documented rather than bundled.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from meetingminer.adapters.diarize import (
    DiarizerError,
    NoopDiarizer,
    build_diarizer,
)
from meetingminer.adapters.stt import ENGINES, SttError, build_stt
from meetingminer.adapters.stt.mlx_whisper import MlxWhisperStt
from meetingminer.adapters.stt.parakeet_mlx import ParakeetMlxStt
from meetingminer.config import AppConfig

from conftest import requires_stt


@dataclass(frozen=True)
class Binding:
    """Structural stand-in for SttConfig / DiarizerConfig."""

    engine: str
    model: str = "unit-test-model"
    token_env: str = "MM_TEST_HF_TOKEN"


# --- what config.yaml actually ships --------------------------------------


def test_shipped_config_binds_the_documented_defaults(app_config: AppConfig) -> None:
    assert app_config.settings.stt.engine == MlxWhisperStt.name
    assert app_config.settings.stt.model
    assert app_config.settings.diarizer.engine == NoopDiarizer.name


def test_both_stt_engines_are_registered() -> None:
    assert set(ENGINES) == {"mlx-whisper", "parakeet-mlx"}


# --- the factory returns what config asked for ----------------------------


@pytest.mark.parametrize("engine_name", ["mlx-whisper", "parakeet-mlx"])
def test_build_stt_returns_the_configured_engine_or_names_why_it_cannot(
    engine_name: str,
) -> None:
    binding = Binding(engine=engine_name, model="mlx-community/whisper-tiny")
    reason = ENGINES[engine_name].unavailable_reason()
    if reason is None:
        engine = build_stt(binding)
        assert engine.name == engine_name
        assert engine.model == "mlx-community/whisper-tiny"
        return
    with pytest.raises(SttError) as raised:
        build_stt(binding)
    # The failure an operator reads names the engine and what to do about it.
    assert engine_name in str(raised.value)


@requires_stt("mlx-whisper")
def test_the_default_engine_is_constructible_on_this_host(app_config: AppConfig) -> None:
    engine = build_stt(app_config.settings.stt)
    assert engine.name == "mlx-whisper"


def test_a_missing_package_is_reported_with_the_install_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meetingminer.adapters.stt.mlx_whisper as module

    monkeypatch.setattr(
        module.MlxWhisperStt, "unavailable_reason",
        staticmethod(lambda: "the mlx_whisper package is not importable — uv sync"),
    )
    with pytest.raises(SttError, match="uv sync"):
        build_stt(Binding(engine="mlx-whisper"))


def test_there_is_no_silent_fallback_between_stt_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 1 asks for *swappable*, not *fallback*: an unusable engine fails."""
    import meetingminer.adapters.stt.mlx_whisper as module

    monkeypatch.setattr(
        module.MlxWhisperStt, "unavailable_reason", staticmethod(lambda: "nope")
    )
    with pytest.raises(SttError):
        build_stt(Binding(engine="mlx-whisper"))


def test_an_unknown_engine_name_names_the_valid_choices() -> None:
    with pytest.raises(SttError, match="mlx-whisper, parakeet-mlx"):
        build_stt(Binding(engine="whisper.cpp"))


# --- the diarizer ---------------------------------------------------------


def test_build_diarizer_returns_the_noop_engine_which_offers_no_turns(
    tmp_path,
) -> None:
    diarizer = build_diarizer(Binding(engine="noop"))
    assert diarizer.name == "noop"
    assert diarizer.diarize(tmp_path / "audio.wav") == ()


def test_pyannote_is_documented_not_bundled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = Binding(engine="pyannote")
    monkeypatch.delenv(binding.token_env, raising=False)
    with pytest.raises(DiarizerError) as raised:
        build_diarizer(binding)
    message = str(raised.value)
    assert "noop" in message
    if "not bundled" in message:
        assert "uv sync --project server --extra diarize" in message
    else:
        assert binding.token_env in message
        assert "licence" in message


def test_an_unknown_diarizer_name_names_the_valid_choices() -> None:
    with pytest.raises(DiarizerError, match="noop"):
        build_diarizer(Binding(engine="whoisspeaking"))

# --- provider payload -> port types ----------------------------------------
#
# The mapping loops below are the only code that converts a recognizer's float
# seconds into the integer milliseconds every downstream anchor is measured in,
# and no other test reaches them: the autouse `_no_real_stt` fixture binds a
# fake that already speaks milliseconds, so `to_ms` is never executed by the
# worker suite. Drop the `* 1000` and every real segment lands at a thousandth
# of its true offset with the whole suite green. These tests stub the provider
# the way `test_ocr_adapter` stubs tesseract's TSV: payload in, port type out,
# no model download.


class _StubWhisper:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def transcribe(self, path: str, path_or_hf_repo: str = "") -> object:
        self.calls.append((path, path_or_hf_repo))
        return self.payload


def _whisper_with(payload: object) -> MlxWhisperStt:
    engine = MlxWhisperStt.__new__(MlxWhisperStt)
    engine._provider = _StubWhisper(payload)
    engine.model = "stub-model"
    return engine


def test_whisper_seconds_become_integer_milliseconds() -> None:
    result = _whisper_with(
        {
            "text": " the whole thing ",
            "language": "en",
            "segments": [
                {"start": 27.702, "end": 28.662, "text": " hi there "},
                {"start": 0.0, "end": 1.5, "text": "opening"},
            ],
        }
    ).transcribe(Path("audio.wav"))

    assert [(s.start_ms, s.end_ms, s.text) for s in result.segments] == [
        (27702, 28662, "hi there"),
        (0, 1500, "opening"),
    ]
    assert result.text == "the whole thing"
    assert result.engine == "mlx-whisper"
    assert result.model == "stub-model"
    assert result.language == "en"


def test_whisper_drops_blank_segments_and_clamps_a_backwards_end() -> None:
    result = _whisper_with(
        {
            "segments": [
                {"start": 1.0, "end": 2.0, "text": "   "},
                {"start": 5.0, "end": 4.0, "text": "backwards"},
                {"start": -0.4, "end": 0.2, "text": "negative start"},
            ]
        }
    ).transcribe(Path("audio.wav"))

    # The blank one is gone; the backwards end is clamped to its own start, so
    # `CHECK (end_ms >= start_ms)` cannot be violated; a negative start is 0.
    assert [(s.start_ms, s.end_ms, s.text) for s in result.segments] == [
        (5000, 5000, "backwards"),
        (0, 200, "negative start"),
    ]


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize("invalid", [None, "not-a-number", float("nan"), float("inf")])
def test_whisper_rejects_invalid_provider_timestamps(field: str, invalid: object) -> None:
    """A malformed provider value must never become a false 0 ms anchor."""
    segment: dict[str, object] = {"start": 0.0, "end": 1.0, "text": "anchor me"}
    segment[field] = invalid
    engine = _whisper_with(
        {"segments": [segment]}
    )

    with pytest.raises(SttError, match="timestamp .*invalid"):
        engine.transcribe(Path("audio.wav"))


def test_whisper_wraps_a_provider_failure_as_an_stt_error() -> None:
    engine = _whisper_with(None)

    def boom(path: str, path_or_hf_repo: str = "") -> object:
        raise RuntimeError("model file corrupt")

    engine._provider.transcribe = boom  # type: ignore[method-assign]
    with pytest.raises(SttError, match="model file corrupt"):
        engine.transcribe(Path("audio.wav"))


class _StubParakeetModel:
    def __init__(self, result: object) -> None:
        self.result = result

    def transcribe(self, path: object) -> object:
        return self.result


class _StubSentence:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start, self.end, self.text = start, end, text


class _StubAligned:
    def __init__(self, text: str, sentences: list[_StubSentence]) -> None:
        self.text, self.sentences = text, sentences


def test_parakeet_sentences_become_integer_milliseconds() -> None:
    engine = ParakeetMlxStt.__new__(ParakeetMlxStt)
    engine.model = "stub-parakeet"
    engine._loaded = _StubParakeetModel(
        _StubAligned(
            "full text",
            [_StubSentence(1.25, 3.5, " first "), _StubSentence(4.0, 4.0, "  ")],
        )
    )

    result = engine.transcribe(Path("audio.wav"))

    assert [(s.start_ms, s.end_ms, s.text) for s in result.segments] == [
        (1250, 3500, "first")
    ]
    assert result.engine == "parakeet-mlx"
    assert result.text == "full text"


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize("invalid", [None, "not-a-number", float("nan"), float("inf")])
def test_parakeet_rejects_invalid_provider_timestamps(field: str, invalid: object) -> None:
    """Parakeet gets the same no-fabricated-anchor contract as Whisper."""
    engine = ParakeetMlxStt.__new__(ParakeetMlxStt)
    engine.model = "stub-parakeet"
    start: object = 0.0
    end: object = 1.0
    if field == "start":
        start = invalid
    else:
        end = invalid
    engine._loaded = _StubParakeetModel(
        _StubAligned("full text", [_StubSentence(start, end, "anchor me")])
    )

    with pytest.raises(SttError, match="timestamp .*invalid"):
        engine.transcribe(Path("audio.wav"))
