"""The `Ocr` port: the config binding, the fallback rule, and both engines.

Engine tests skip with the engine's *own* reason when it cannot run here
(no macOS Vision framework, no tesseract binary), so a skip always says what
to install rather than "unsupported".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pytest

from meetingminer.adapters.ocr import ENGINES, build_ocr
from meetingminer.adapters.ocr.apple_vision import AppleVisionOcr
from meetingminer.adapters.ocr.port import OcrBlock, OcrError, OcrResult, reading_order_text
from meetingminer.adapters.ocr.tesseract import TesseractOcr, parse_tsv
from meetingminer.config import OcrConfig, load_config

from conftest import requires_ocr
from repo_paths import REPO_ROOT


def fake_engine(name: str, reason: str | None) -> type:
    """An engine class that reports ``reason`` (or ``None``) for availability."""
    return type(
        f"Fake{name}",
        (),
        {
            "name": name,
            "unavailable_reason": staticmethod(lambda: reason),
            "recognize": lambda self, path: OcrResult((), "", name),
        },
    )


# --- the config binding ----------------------------------------------------


def test_build_ocr_returns_the_configured_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ENGINES, "apple-vision", fake_engine("apple-vision", None))
    monkeypatch.setitem(ENGINES, "tesseract", fake_engine("tesseract", None))
    engine = build_ocr(OcrConfig(engine="tesseract", fallback="apple-vision"))
    assert engine.name == "tesseract"


def test_build_ocr_falls_back_when_the_primary_cannot_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        ENGINES, "apple-vision", fake_engine("apple-vision", "no Vision here")
    )
    monkeypatch.setitem(ENGINES, "tesseract", fake_engine("tesseract", None))
    events: list[tuple[str, dict]] = []

    engine = build_ocr(
        OcrConfig(engine="apple-vision", fallback="tesseract"),
        log=lambda event, **fields: events.append((event, fields)),
    )

    assert engine.name == "tesseract"
    # The substitution is visible in the job log, not silent.
    assert events == [
        (
            "ocr.engine.fallback",
            {"engine": "apple-vision", "fallback": "tesseract", "reason": "no Vision here"},
        )
    ]


def test_build_ocr_without_a_fallback_names_the_engine_and_the_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        ENGINES, "apple-vision", fake_engine("apple-vision", "no Vision here")
    )
    with pytest.raises(OcrError, match="no Vision here"):
        build_ocr(OcrConfig(engine="apple-vision", fallback=None))


def test_build_ocr_names_both_engines_when_neither_can_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        ENGINES, "apple-vision", fake_engine("apple-vision", "no Vision here")
    )
    monkeypatch.setitem(
        ENGINES, "tesseract", fake_engine("tesseract", "no tesseract binary")
    )
    with pytest.raises(OcrError) as exc:
        build_ocr(OcrConfig(engine="apple-vision", fallback="tesseract"))
    assert "no Vision here" in str(exc.value)
    assert "no tesseract binary" in str(exc.value)


def test_a_fallback_equal_to_the_primary_is_not_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(ENGINES, "tesseract", fake_engine("tesseract", "absent"))
    with pytest.raises(OcrError, match="absent"):
        build_ocr(OcrConfig(engine="tesseract", fallback="tesseract"))


def test_the_shipped_config_binds_vision_primary_with_a_tesseract_fallback() -> None:
    """AC 1: swapping engines is a config edit, so config.yaml carries both."""
    ocr = load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env").settings.ocr
    assert ocr.engine == "apple-vision"
    assert ocr.fallback == "tesseract"


# --- the port's derived geometry ------------------------------------------


def test_result_geometry_summarizes_the_blocks() -> None:
    result = OcrResult(
        blocks=(
            OcrBlock("top", x=0.1, y=0.1, width=0.5, height=0.1),
            OcrBlock("bottom", x=0.1, y=0.4, width=0.5, height=0.3),
        ),
        text="top\nbottom",
        engine="fake",
    )
    assert result.block_count == 2
    assert result.text_density == pytest.approx(0.05 + 0.15)
    assert result.mean_block_height == pytest.approx(0.2)


def test_an_empty_result_has_no_geometry() -> None:
    empty = OcrResult(blocks=(), text="", engine="fake")
    assert (empty.block_count, empty.text_density, empty.mean_block_height) == (0, 0.0, 0.0)


def test_reading_order_is_top_to_bottom_then_left_to_right() -> None:
    blocks = (
        OcrBlock("right", x=0.6, y=0.100, width=0.2, height=0.05),
        OcrBlock("below", x=0.1, y=0.400, width=0.2, height=0.05),
        OcrBlock("left", x=0.1, y=0.101, width=0.2, height=0.05),
    )
    assert reading_order_text(blocks) == "left\nright\nbelow"


# --- tesseract's TSV parsing (no binary needed) ---------------------------

_TSV_HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
    "\tleft\ttop\twidth\theight\tconf\ttext"
)


def test_parse_tsv_groups_words_into_lines_and_normalizes_geometry() -> None:
    tsv = "\n".join(
        [
            _TSV_HEADER,
            "1\t1\t0\t0\t0\t0\t0\t0\t1000\t500\t-1\t",
            "5\t1\t1\t1\t1\t1\t100\t50\t200\t40\t90\tHello",
            "5\t1\t1\t1\t1\t2\t320\t50\t180\t40\t80\tworld",
            "5\t1\t1\t1\t2\t1\t100\t150\t300\t40\t70\tsecond",
        ]
    )
    first, second = parse_tsv(tsv)
    assert first.text == "Hello world"
    assert (first.x, first.y) == pytest.approx((0.1, 0.1))
    assert first.width == pytest.approx((320 + 180 - 100) / 1000)
    assert first.height == pytest.approx(40 / 500)
    assert first.confidence == pytest.approx(0.85)
    assert second.text == "second"


def test_parse_tsv_ignores_blank_words_and_non_word_levels() -> None:
    tsv = "\n".join(
        [
            _TSV_HEADER,
            "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t",
            "4\t1\t1\t1\t1\t0\t0\t0\t100\t20\t-1\t",
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t-1\t   ",
        ]
    )
    assert parse_tsv(tsv) == ()


def test_parse_tsv_of_an_empty_page_is_empty_not_an_error() -> None:
    assert parse_tsv(_TSV_HEADER + "\n1\t1\t0\t0\t0\t0\t0\t0\t640\t480\t-1\t") == ()


def test_parse_tsv_without_page_dimensions_is_a_named_error() -> None:
    tsv = "\n".join([_TSV_HEADER, "5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t90\tword"])
    with pytest.raises(OcrError, match="page dimensions"):
        parse_tsv(tsv)


def test_parse_tsv_of_an_unexpected_header_is_a_named_error() -> None:
    """A build whose TSV we cannot read must say so, not report a blank page."""
    tsv = "\n".join(
        [
            "level\tpage_num\tleft\ttop\twidth\theight\ttext",
            "1\t1\t0\t0\t640\t480\t",
        ]
    )
    with pytest.raises(OcrError) as exc:
        parse_tsv(tsv)
    message = str(exc.value)
    assert "missing the column" in message
    assert "block_num" in message and "conf" in message


def test_parse_tsv_drops_impossible_geometry() -> None:
    """Negative or empty boxes would poison text_density and the classifier."""
    tsv = "\n".join(
        [
            _TSV_HEADER,
            "1\t1\t0\t0\t0\t0\t0\t0\t1000\t500\t-1\t",
            "5\t1\t1\t1\t1\t1\t-5\t50\t100\t40\t90\tnegative-left",
            "5\t1\t1\t1\t2\t1\t100\t-9\t100\t40\t90\tnegative-top",
            "5\t1\t1\t1\t3\t1\t100\t50\t0\t40\t90\tzero-width",
            "5\t1\t1\t1\t4\t1\t100\t50\t100\t0\t90\tzero-height",
            "5\t1\t1\t1\t5\t1\t100\t50\t100\t40\t90\tkeep",
        ]
    )
    assert [block.text for block in parse_tsv(tsv)] == ["keep"]


def test_parse_tsv_clamps_page_overruns_and_drops_nonfinite_values() -> None:
    """Every adapter result must remain finite and inside the unit square."""
    tsv = "\n".join(
        [
            _TSV_HEADER,
            "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t",
            "5\t1\t1\t1\t1\t1\t80\t70\t30\t40\t150\tclipped",
            "5\t1\t1\t1\t2\t1\tNaN\t10\t20\t20\t90\tnot-a-number",
        ]
    )

    [block] = parse_tsv(tsv)

    assert block.text == "clipped"
    assert (block.x, block.y, block.width, block.height) == pytest.approx((0.8, 0.7, 0.2, 0.3))
    assert block.confidence == 1.0


# --- the real engines ------------------------------------------------------

RECOGNIZED_TEXT = "MEETING MINER"


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple Vision is macOS-only")
def test_apple_vision_is_available_on_the_macos_host() -> None:
    """AD-9 pins the worker to macOS so this engine is reachable.

    Without this the PyObjC bindings could go missing and every Vision test
    would quietly skip while the tesseract fallback took over unnoticed.
    """
    assert AppleVisionOcr.unavailable_reason() is None


@requires_ocr("apple-vision")
def test_apple_vision_recognizes_generated_text(text_image: Callable[..., Path]) -> None:
    result = AppleVisionOcr().recognize(text_image(RECOGNIZED_TEXT))
    assert RECOGNIZED_TEXT in result.text.upper()
    assert result.engine == "apple-vision"
    assert result.blocks
    for block in result.blocks:
        assert 0.0 <= block.x <= 1.0 and 0.0 <= block.y <= 1.0
        assert 0.0 < block.width <= 1.0 and 0.0 < block.height <= 1.0


@requires_ocr("tesseract")
def test_tesseract_recognizes_generated_text(text_image: Callable[..., Path]) -> None:
    result = TesseractOcr().recognize(text_image(RECOGNIZED_TEXT))
    assert RECOGNIZED_TEXT in result.text.upper()
    assert result.engine == "tesseract"
    assert result.blocks
    for block in result.blocks:
        assert 0.0 <= block.x <= 1.0 and 0.0 <= block.y <= 1.0
        assert 0.0 < block.width <= 1.0 and 0.0 < block.height <= 1.0


@requires_ocr("apple-vision")
def test_a_blank_frame_recognizes_no_text(text_image: Callable[..., Path]) -> None:
    assert AppleVisionOcr().recognize(text_image("   ")).blocks == ()


@requires_ocr("tesseract")
def test_tesseract_names_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OcrError, match="no such file"):
        TesseractOcr().recognize(tmp_path / "absent.bmp")


# --- the worker's startup probe -------------------------------------------


def test_worker_resolves_the_engine_name_at_startup(app_config) -> None:
    from meetingminer.worker.main import resolve_ocr_engine

    assert resolve_ocr_engine(app_config) in {"apple-vision", "tesseract"}


def test_an_unusable_binding_warns_without_stopping_the_worker(
    app_config, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Non-fatal by design: transcript-only drops skip `ocr` entirely."""
    import json

    from meetingminer.worker import main as worker_main

    def no_engine(*_args: object, **_kwargs: object) -> None:
        raise OcrError("no usable OCR engine: nothing available on this host")

    monkeypatch.setattr(worker_main, "build_ocr", no_engine)
    capsys.readouterr()

    assert worker_main.resolve_ocr_engine(app_config) is None

    records = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("{")
    ]
    warnings = [r for r in records if r["event"] == "worker.ocr_unavailable"]
    assert warnings, "an unusable binding must be named at startup, not discovered mid-pipeline"
    assert warnings[0]["engine"] == "apple-vision"
    assert "no usable OCR engine" in warnings[0]["error"]
