"""Apple Vision engine for the `Ocr` port — the macOS default (AD-8, AD-9).

`VNRecognizeTextRequest` via PyObjC. The framework imports are *lazy* on
purpose: this module must import cleanly on Linux and in a container so
:func:`unavailable_reason` can report why the engine cannot run, instead of
the process dying at import time. AD-9 keeps the worker on the macOS host
precisely so this engine is reachable.

Vision reports bounding boxes in a bottom-left-origin unit square; the port's
contract is top-left, so every box is flipped here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from meetingminer.adapters.ocr.port import OcrBlock, OcrError, OcrResult, reading_order_text

ENGINE_NAME = "apple-vision"

# pyobjc ships as one wheel per framework; both are needed (Quartz decodes the
# JPEG into a CGImage, Vision recognizes it).
INSTALL_HINT = (
    "install the PyObjC bindings for it"
    " (uv sync --project server; they are macOS-only dependencies)"
)


def _import_frameworks() -> tuple[Any, Any]:
    """Import Quartz + Vision, or raise :class:`OcrError` naming what is missing."""
    if sys.platform != "darwin":
        raise OcrError(
            f"{ENGINE_NAME} needs macOS (this host is {sys.platform}) — bind"
            " ocr.engine or ocr.fallback to tesseract in config.yaml"
        )
    try:
        import Quartz  # noqa: PLC0415 - deliberately lazy (see module docstring)
        import Vision  # noqa: PLC0415
    except ImportError as exc:
        raise OcrError(
            f"{ENGINE_NAME} is unavailable: the {exc.name} framework binding is"
            f" not importable — {INSTALL_HINT}"
        ) from exc
    return Quartz, Vision


def unavailable_reason() -> str | None:
    """Why this engine cannot run here, or ``None`` when it can."""
    try:
        _import_frameworks()
    except OcrError as exc:
        return str(exc)
    return None


def _clamp_span(start: float, length: float) -> tuple[float, float]:
    """Clip a (start, length) span to the 0-1 unit interval."""
    left = min(max(start, 0.0), 1.0)
    right = min(max(start + length, 0.0), 1.0)
    return left, max(right - left, 0.0)


class AppleVisionOcr:
    """The `Ocr` port backed by Vision's text recognizer."""

    name = ENGINE_NAME

    def __init__(self) -> None:
        self._quartz, self._vision = _import_frameworks()

    @staticmethod
    def unavailable_reason() -> str | None:
        return unavailable_reason()

    def _load_image(self, path: Path) -> Any:
        quartz = self._quartz
        # Foundation is a pyobjc-core dependency of every framework wrapper.
        # Wrapped like the others: an ImportError escaping here would leave
        # the port's contract as an "unexpected ImportError" stage failure
        # rather than a named OcrError.
        try:
            from Foundation import NSURL  # noqa: PLC0415
        except ImportError as exc:
            raise OcrError(
                f"{ENGINE_NAME} is unavailable: the {exc.name} framework binding"
                f" is not importable — {INSTALL_HINT}"
            ) from exc

        url = NSURL.fileURLWithPath_(str(path))
        source = quartz.CGImageSourceCreateWithURL(url, None)
        if source is None:
            raise OcrError(f"{ENGINE_NAME} could not open {path} as an image")
        image = quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        if image is None:
            raise OcrError(f"{ENGINE_NAME} could not decode {path}")
        return image

    def recognize(self, path: Path) -> OcrResult:
        vision = self._vision
        image = self._load_image(path)
        request = vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(vision.VNRequestTextRecognitionLevelAccurate)
        # Language correction rewrites strings toward dictionary words, which
        # is wrong for the UI labels and identifiers screens are full of, and
        # it would make the identity signature depend on the OS dictionary.
        request.setUsesLanguageCorrection_(False)
        handler = vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise OcrError(f"{ENGINE_NAME} failed on {path}: {error}")

        blocks: list[OcrBlock] = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            candidate = candidates[0]
            text = str(candidate.string()).strip()
            if not text:
                continue
            box = observation.boundingBox()
            # Vision's origin is bottom-left; the port's is top-left. Vision
            # can also report an origin or size slightly outside the unit
            # square, which would inflate text_density and skew the view-type
            # classification, so every value is clamped back into it.
            x, width = _clamp_span(float(box.origin.x), float(box.size.width))
            height = float(box.size.height)
            top = 1.0 - (float(box.origin.y) + height)
            y, height = _clamp_span(top, height)
            blocks.append(
                OcrBlock(
                    text=text,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    confidence=min(max(float(candidate.confidence()), 0.0), 1.0),
                )
            )
        frozen = tuple(blocks)
        return OcrResult(blocks=frozen, text=reading_order_text(frozen), engine=ENGINE_NAME)
