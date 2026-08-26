"""The `Ocr` port: what feature code is allowed to know about OCR (AD-8).

Nothing in this module imports a provider. A stage depends on
:class:`OcrResult` and calls :meth:`Ocr.recognize`; which engine answers is
decided by ``config.yaml`` in :mod:`meetingminer.adapters.ocr` and nowhere
else, so swapping ``apple-vision`` for ``tesseract`` is a config edit.

Geometry is normalized to the 0-1 unit square with the origin at the *top*
left, whatever the engine's native convention: the `screens` stage's view-type
rules compare block heights and text density across engines and resolutions,
so they cannot depend on pixels.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class OcrError(RuntimeError):
    """The configured OCR engine is unavailable, or a recognition failed.

    Carries a message naming the engine and, when the cause is a missing
    dependency, how to install it. The `ocr` stage turns it into a recorded
    :class:`~meetingminer.pipeline.stage.StageError`.
    """


@dataclass(frozen=True)
class OcrBlock:
    """One recognized run of text and where it sits on the frame.

    ``x``/``y``/``width``/``height`` are fractions of the frame, origin top
    left. ``confidence`` is 0-1; engines that do not report one use 1.0.
    """

    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0

    def as_json(self) -> dict[str, Any]:
        """The jsonb shape persisted on ``frame_ocr.blocks``."""
        return {
            "text": self.text,
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "width": round(self.width, 6),
            "height": round(self.height, 6),
            "confidence": round(self.confidence, 6),
        }


@dataclass(frozen=True)
class OcrResult:
    """Everything one frame's recognition produced."""

    blocks: tuple[OcrBlock, ...]
    text: str
    engine: str

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def text_density(self) -> float:
        """Fraction of the frame covered by text boxes (clamped to 0-1).

        Overlapping boxes are counted twice — this is a coarse "how busy is
        this frame" signal for view-type classification, not a measurement.
        """
        total = sum(max(block.width, 0.0) * max(block.height, 0.0) for block in self.blocks)
        return min(total, 1.0)

    @property
    def mean_block_height(self) -> float:
        """Mean normalized block height; 0.0 when there are no blocks."""
        if not self.blocks:
            return 0.0
        return sum(max(block.height, 0.0) for block in self.blocks) / len(self.blocks)


class Ocr(Protocol):
    """What every engine implements and every caller may rely on.

    ``unavailable_reason`` is part of the contract, not a convenience: the
    factory probes it on the class before constructing anything, so an engine
    that omitted it would crash the binding rather than fail the protocol.
    """

    name: str

    @staticmethod
    def unavailable_reason() -> str | None:
        """Why this engine cannot run on this host, or ``None`` when it can."""
        ...

    def recognize(self, path: Path) -> OcrResult:
        """Recognize the text in one image file.

        Raises :class:`OcrError` when the engine cannot read the image or the
        underlying tool fails.
        """
        ...


def reading_order_text(blocks: tuple[OcrBlock, ...]) -> str:
    """Join blocks top-to-bottom, then left-to-right, one line each.

    Rounding ``y`` to two decimals groups blocks that share a line before the
    left-to-right sort, so two engines that disagree about sub-percent
    vertical placement still produce the same reading order.
    """
    ordered = sorted(blocks, key=lambda block: (round(block.y, 2), block.x))
    return "\n".join(block.text for block in ordered if block.text)
