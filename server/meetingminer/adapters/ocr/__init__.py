"""The `Ocr` binding: the one place either engine is named (AD-8, AD-10).

Feature code calls :func:`build_ocr` with ``config.settings.ocr`` and gets back
something satisfying the :class:`~meetingminer.adapters.ocr.port.Ocr`
protocol. Which engine that is comes from ``config.yaml`` and nothing else, so
swapping ``apple-vision`` for ``tesseract`` changes no file outside this
package.

``fallback`` exists because the acceptance criterion is "Apple Vision primary,
Tesseract swappable fallback": the fallback engages only when the primary is
*unavailable on this host*, never to paper over a recognition failure, and the
substitution is logged so the engine actually used is visible in the job log.
"""

from __future__ import annotations

from typing import Callable, Protocol

from meetingminer.adapters.ocr.apple_vision import AppleVisionOcr
from meetingminer.adapters.ocr.port import Ocr, OcrBlock, OcrError, OcrResult
from meetingminer.adapters.ocr.tesseract import TesseractOcr

__all__ = [
    "ENGINES",
    "Ocr",
    "OcrBinding",
    "OcrBlock",
    "OcrError",
    "OcrResult",
    "build_ocr",
]

# Engine name in config.yaml -> implementation. Adding an engine is one entry
# here plus the Literal in meetingminer.config; no stage changes.
ENGINES: dict[str, type[Ocr]] = {
    AppleVisionOcr.name: AppleVisionOcr,
    TesseractOcr.name: TesseractOcr,
}


class OcrBinding(Protocol):
    """Structural stand-in for :class:`meetingminer.config.OcrConfig`.

    Typed structurally rather than by import: this package stays free of
    project imports other than its own port, which is what keeps the engines
    substitutable and the dependency direction one-way.
    """

    engine: str
    fallback: str | None


def build_ocr(
    ocr_config: OcrBinding, log: Callable[..., None] | None = None
) -> Ocr:
    """Construct the configured engine, or its fallback when it cannot run.

    Raises :class:`OcrError` naming both engines and why each is unusable when
    neither can run — the caller records that as a stage failure.
    """
    engine_name = ocr_config.engine
    primary = ENGINES.get(engine_name)
    if primary is None:  # pragma: no cover - config validation rejects this first
        raise OcrError(
            f"unknown OCR engine {engine_name!r} in config.yaml —"
            f" choose one of {', '.join(sorted(ENGINES))}"
        )

    primary_reason = primary.unavailable_reason()
    if primary_reason is None:
        return primary()

    fallback_name = ocr_config.fallback
    if fallback_name is None or fallback_name == engine_name:
        raise OcrError(
            f"no usable OCR engine: {primary_reason}."
            " Set ocr.fallback in config.yaml to an engine this host can run."
        )
    fallback = ENGINES.get(fallback_name)
    if fallback is None:  # pragma: no cover - config validation rejects this first
        raise OcrError(
            f"unknown OCR fallback engine {fallback_name!r} in config.yaml —"
            f" choose one of {', '.join(sorted(ENGINES))}"
        )
    fallback_reason = fallback.unavailable_reason()
    if fallback_reason is not None:
        raise OcrError(
            f"no usable OCR engine: {primary_reason}. Fallback"
            f" {fallback_name}: {fallback_reason}."
        )
    if log is not None:
        log(
            "ocr.engine.fallback",
            engine=engine_name,
            fallback=fallback_name,
            reason=primary_reason,
        )
    return fallback()
