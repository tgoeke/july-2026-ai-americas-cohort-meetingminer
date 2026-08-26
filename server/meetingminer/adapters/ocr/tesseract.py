"""Tesseract engine for the `Ocr` port — the portable fallback (AD-8).

A subprocess wrapper, not a library binding: ``tesseract <image> stdout tsv``
emits one row per recognized word with pixel geometry, which is aggregated
back to line-level blocks so the result is shaped like Apple Vision's
per-line observations. Everything that can go wrong — binary missing, non-zero
exit, unparseable TSV — surfaces as one named :class:`OcrError`, mirroring the
``MediaToolError`` contract the ffmpeg wrappers use.
"""

from __future__ import annotations

import csv
import io
import math
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path

from meetingminer.adapters.ocr.port import OcrBlock, OcrError, OcrResult, reading_order_text

ENGINE_NAME = "tesseract"
BINARY = "tesseract"
INSTALL_HINT = "install it with 'brew install tesseract'"

# Recognition of one sampled frame is sub-second work; a minute means the
# process is wedged rather than busy.
TIMEOUT_SECONDS = 60


def unavailable_reason() -> str | None:
    """Why this engine cannot run here, or ``None`` when it can."""
    if shutil.which(BINARY) is None:
        return f"{ENGINE_NAME} is unavailable: {BINARY} is not on PATH — {INSTALL_HINT}"
    return None


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            # tesseract writes non-UTF-8 bytes to stderr for some inputs;
            # a diagnostic must never crash the stage that is reporting it.
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise OcrError(
            f"{BINARY} not found on PATH — {INSTALL_HINT} and retry"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise OcrError(
            f"{BINARY} timed out after {TIMEOUT_SECONDS}s: {' '.join(argv)}"
        ) from exc
    except OSError as exc:
        raise OcrError(f"{BINARY} could not be executed: {exc}") from exc


def _to_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


# The columns this parser reads. A build whose TSV omits any of them cannot
# be parsed, and must say so rather than report an empty page.
REQUIRED_COLUMNS = frozenset(
    {
        "level", "block_num", "par_num", "line_num",
        "left", "top", "width", "height", "conf", "text",
    }
)


def parse_tsv(tsv: str) -> tuple[OcrBlock, ...]:
    """Aggregate tesseract's word-level TSV into normalized line blocks.

    Level 1 is the page row and carries the pixel dimensions everything is
    normalized against; level 5 rows are the words. Words are grouped by
    ``(block_num, par_num, line_num)`` — the line a word belongs to — and each
    group's bounding box is the union of its words'.
    """
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    header = set(reader.fieldnames or ())
    missing = REQUIRED_COLUMNS - header
    if missing:
        # Silence here would recognize a page of text as empty and let the
        # screens stage treat a busy UI as a blank frame.
        raise OcrError(
            f"{ENGINE_NAME} TSV output is missing the column(s)"
            f" {', '.join(sorted(missing))} — this tesseract build is not"
            " one this adapter can parse"
        )
    page_width = page_height = 0.0
    # Insertion order is tesseract's own reading order; keep it.
    lines: OrderedDict[tuple[str, str, str], dict[str, object]] = OrderedDict()
    for row in reader:
        level = row.get("level")
        if level == "1":
            page_width = _to_float(row.get("width") or "") or 0.0
            page_height = _to_float(row.get("height") or "") or 0.0
            continue
        if level != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        left = _to_float(row.get("left") or "")
        top = _to_float(row.get("top") or "")
        width = _to_float(row.get("width") or "")
        height = _to_float(row.get("height") or "")
        if None in (left, top, width, height):
            continue
        # Impossible geometry would flow straight into text_density and the
        # view-type thresholds. Drop the word instead.
        if width <= 0 or height <= 0 or left < 0 or top < 0:
            continue
        # The port promises normalized unit-square geometry. Clip unexpected
        # word boxes to the reported page before grouping them into a line.
        right = min(left + width, page_width) if page_width > 0 else left + width
        bottom = min(top + height, page_height) if page_height > 0 else top + height
        # Keep valid words until the final page-dimension check. Otherwise a
        # missing page row turns every word into an out-of-bounds no-op and the
        # parser incorrectly reports an empty page instead of its named error.
        if (
            (page_width > 0 and left >= page_width)
            or (page_height > 0 and top >= page_height)
            or right <= left
            or bottom <= top
        ):
            continue
        confidence = _to_float(row.get("conf") or "")
        if confidence is not None:
            confidence = min(confidence, 100.0)
        key = (row.get("block_num") or "", row.get("par_num") or "", row.get("line_num") or "")
        entry = lines.get(key)
        if entry is None:
            lines[key] = {
                "words": [text],
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "conf": [confidence if confidence is not None else 0.0],
            }
            continue
        entry["words"].append(text)  # type: ignore[union-attr]
        entry["left"] = min(entry["left"], left)  # type: ignore[type-var]
        entry["top"] = min(entry["top"], top)  # type: ignore[type-var]
        entry["right"] = max(entry["right"], right)  # type: ignore[type-var]
        entry["bottom"] = max(entry["bottom"], bottom)  # type: ignore[type-var]
        entry["conf"].append(confidence if confidence is not None else 0.0)  # type: ignore[union-attr]

    if page_width <= 0 or page_height <= 0:
        # Without page dimensions nothing can be normalized, and a block with
        # pixel geometry would silently poison the view-type thresholds.
        if lines:
            raise OcrError(
                f"{ENGINE_NAME} produced text without page dimensions — its TSV"
                " output is not in the expected format"
            )
        return ()

    blocks: list[OcrBlock] = []
    for entry in lines.values():
        confidences = [c for c in entry["conf"] if c >= 0]  # type: ignore[union-attr]
        blocks.append(
            OcrBlock(
                text=" ".join(entry["words"]),  # type: ignore[arg-type]
                x=float(entry["left"]) / page_width,  # type: ignore[arg-type]
                y=float(entry["top"]) / page_height,  # type: ignore[arg-type]
                width=(float(entry["right"]) - float(entry["left"])) / page_width,  # type: ignore[arg-type]
                height=(float(entry["bottom"]) - float(entry["top"])) / page_height,  # type: ignore[arg-type]
                confidence=(sum(confidences) / len(confidences) / 100.0) if confidences else 1.0,
            )
        )
    return tuple(blocks)


class TesseractOcr:
    """The `Ocr` port backed by the tesseract CLI."""

    name = ENGINE_NAME

    def __init__(self) -> None:
        reason = unavailable_reason()
        if reason is not None:
            raise OcrError(reason)

    @staticmethod
    def unavailable_reason() -> str | None:
        return unavailable_reason()

    def recognize(self, path: Path) -> OcrResult:
        if not path.is_file():
            raise OcrError(f"{ENGINE_NAME} cannot read {path}: no such file")
        result = _run([BINARY, str(path), "stdout", "tsv"])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
            raise OcrError(f"{ENGINE_NAME} failed on {path}: {detail}")
        blocks = parse_tsv(result.stdout)
        return OcrResult(blocks=blocks, text=reading_order_text(blocks), engine=ENGINE_NAME)
