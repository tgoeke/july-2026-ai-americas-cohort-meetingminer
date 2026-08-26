"""Parsing the transcript lineages, with no database and no filesystem.

Every function here takes a string and returns data, so each rule the corpus
forced on us is unit-testable without Postgres, ffmpeg, or a drop on disk —
and so none of them can quietly become a model call. The stage around this
module owns reading the file and turning a :class:`TranscriptParseError` into
a recorded stage failure.

Three lineages, all read-only inputs (AD-13):

* **Teams** — ``[m:ss] Lastname, Firstname: text``, one line per turn. The
  go-forward source of record.
* **Legacy** — ``<Name or Speaker N> | MM:SS`` on its own line with the
  utterance on the lines that follow. Still required: the two long capture-eval
  recordings carry only this form.
* **VTT** — a WebVTT subtitle track. In this corpus it is *speaker-less*, so it
  is never a substitute for the ``.txt``; it contributes cue **end** timings
  and nothing else.

Timestamps are parsed **by field count**: two fields are ``MM:SS``, three are
``HH:MM:SS``. The long legacy transcript switches form past the hour (``08:47``
early, ``01:57:24`` late), so a parser assuming a fixed field count mis-reads
half the file.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# Source formats, as recorded on `transcript_source.format`.
FORMAT_TEAMS = "teams"
FORMAT_LEGACY = "legacy"
FORMAT_VTT = "vtt"
FORMAT_STT = "stt"

# The label used wherever no source offered one (AD-13).
UNKNOWN_SPEAKER = "Unknown"

NUL = "\x00"

# `[0:16] Jarrow, Quinn: Good morning.` — the label may itself contain a
# comma (`Last, First`) or be a bare login (`oakleylangmere`), so the split
# is on the *first* colon after the closing bracket, never on the last.
# The stamp is captured loosely and validated by `parse_timestamp`, so a
# bracketed thing that claims to be a timestamp and is not fails loudly
# instead of being silently swallowed as continuation text.
_TEAMS_LINE = re.compile(r"^\[(?P<stamp>[^\]]*)\]\s*(?P<body>.*)$")

# `Ironside, Indigo | 00:00` on a line by itself.
_LEGACY_HEADER = re.compile(
    r"^(?P<label>\S.*?)\s+\|\s+(?P<stamp>\d{1,2}(?::\d{1,2}){1,2})\s*$"
)

# A legacy header with a malformed stamp must not become body text. Keep the
# whitespace around the pipe that distinguishes a header from ordinary prose.
_LEGACY_HEADER_CANDIDATE = re.compile(
    r"^(?P<label>\S.*?)\s+\|\s+(?P<stamp>\S.*?)\s*$"
)

# `Stonebridge, Finley started transcription` — the legacy export's opening line,
# which is not a speaker block.
_LEGACY_PREAMBLE = re.compile(r"^.+\s+started transcription\s*$", re.IGNORECASE)

# `00:00:27.702 --> 00:00:28.662` plus optional cue settings after the end.
_VTT_TIMING = re.compile(
    r"^(?P<start>\d{1,2}(?::\d{1,2}){1,2}[.,]?\d*)\s*-->\s*"
    r"(?P<end>\d{1,2}(?::\d{1,2}){1,2}[.,]?\d*)(?:\s+.*)?$"
)

# `<v Speaker Name>` voice spans. Stripped from the text: in this corpus no VTT
# carries them, and a VTT is never allowed to supply a speaker anyway.
_VTT_VOICE = re.compile(r"</?v[^>]*>")
_VTT_TAG = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)


class TranscriptParseError(ValueError):
    """A provided transcript could not be parsed.

    Carries the file and the line number, so the stage failure an operator
    reads names the exact line rather than only the meeting.
    """


@dataclass(frozen=True)
class ParsedSegment:
    """One turn as the file wrote it.

    ``end_ms`` is ``None`` because neither text lineage records one: a turn's
    end is derived later from the next turn's start, or replaced by a matching
    VTT cue's real end. VTT cues are the exception and arrive with both.
    """

    ordinal: int
    start_ms: int
    end_ms: int | None
    speaker_label: str | None
    text: str


@dataclass(frozen=True)
class ParsedTranscript:
    """One parsed file: its recognized lineage and the turns it yielded."""

    format: str
    segments: tuple[ParsedSegment, ...]

    @property
    def segment_count(self) -> int:
        return len(self.segments)


def parse_timestamp(raw: str, *, line_number: int | None = None) -> int:
    """Parse a transcript timestamp into integer milliseconds, by field count.

    Two fields are ``MM:SS``; three are ``HH:MM:SS``. Fractional seconds
    (``00:00:27.702``, the VTT form) are kept. Anything else raises
    :class:`TranscriptParseError` — a stamp that will not parse is never
    guessed at, because a wrong offset is a wrong citation.
    """
    text = (raw or "").strip().replace(",", ".")
    fields = text.split(":")
    if len(fields) == 2:
        hours, minutes, seconds = "0", fields[0], fields[1]
    elif len(fields) == 3:
        hours, minutes, seconds = fields
    else:
        raise TranscriptParseError(
            _at(f"timestamp {raw!r} has {len(fields)} fields; expected MM:SS or HH:MM:SS",
                line_number)
        )
    try:
        hour_value = int(hours)
        minute_value = int(minutes)
        second_value = float(seconds)
    except ValueError as exc:
        raise TranscriptParseError(
            _at(f"timestamp {raw!r} is not numeric", line_number)
        ) from exc
    if (
        hour_value < 0
        or not 0 <= minute_value < 60
        or not math.isfinite(second_value)
        or not 0 <= second_value < 60
    ):
        raise TranscriptParseError(
            _at(
                f"timestamp {raw!r} has components outside their valid ranges",
                line_number,
            )
        )
    return hour_value * 3_600_000 + minute_value * 60_000 + round(second_value * 1000)


def _at(message: str, line_number: int | None) -> str:
    return message if line_number is None else f"line {line_number}: {message}"


def detect_text_format(text: str) -> str | None:
    """Which lineage a ``.txt`` is, or ``None`` when it is neither.

    Decided by counting lines that actually match each lineage's shape rather
    than by sniffing the first line: the legacy export opens with a
    ``started transcription`` preamble, and either file may begin with a BOM or
    a blank line.
    """
    teams = legacy = 0
    for line in _lines(text):
        if _TEAMS_LINE.match(line):
            teams += 1
        elif _LEGACY_HEADER.match(line):
            legacy += 1
    if not teams and not legacy:
        return None
    return FORMAT_TEAMS if teams >= legacy else FORMAT_LEGACY


def _lines(text: str) -> list[str]:
    """Split into lines, dropping a leading BOM and trailing whitespace."""
    return (text or "").lstrip("﻿").splitlines()


def parse_teams_text(text: str) -> ParsedTranscript:
    """Parse the Teams lineage: one ``[m:ss] Label: text`` line per turn.

    A line with no timestamp is treated as a continuation of the turn above it
    (the export wraps nothing today, but losing text to a format change would
    be silent evidence loss). A line whose *bracketed* stamp will not parse is
    an error: something claimed to be a timestamp and was not.
    """
    segments: list[ParsedSegment] = []
    pending: list[str] = []

    def close() -> None:
        if not segments or not pending:
            return
        previous = segments[-1]
        joined = " ".join(part for part in (previous.text, *pending) if part).strip()
        segments[-1] = ParsedSegment(
            ordinal=previous.ordinal,
            start_ms=previous.start_ms,
            end_ms=previous.end_ms,
            speaker_label=previous.speaker_label,
            text=joined,
        )
        pending.clear()

    for number, line in enumerate(_lines(text), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        match = _TEAMS_LINE.match(stripped)
        if match is None:
            if not segments:
                raise TranscriptParseError(
                    _at("nonblank text appears before the first transcript turn", number)
                )
            pending.append(stripped)
            continue
        close()
        start_ms = parse_timestamp(match.group("stamp"), line_number=number)
        label, _, body = match.group("body").partition(":")
        if not _:
            # No colon at all: the whole body is speech with no attribution.
            label, body = "", match.group("body")
        segments.append(
            ParsedSegment(
                ordinal=len(segments) + 1,
                start_ms=start_ms,
                end_ms=None,
                speaker_label=label.strip() or None,
                text=body.strip(),
            )
        )
    close()
    return ParsedTranscript(format=FORMAT_TEAMS, segments=tuple(segments))


def parse_legacy_text(text: str) -> ParsedTranscript:
    """Parse the legacy lineage: a ``<Name> | MM:SS`` header, then its text.

    The ``<Name> started transcription`` preamble is skipped — it is not a
    speaker block. Every non-blank line after a header and before the next one
    belongs to that turn, joined into a single utterance so a turn means the
    same thing in both lineages.
    """
    segments: list[ParsedSegment] = []
    bodies: list[list[str]] = []

    for number, line in enumerate(_lines(text), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if not segments and _LEGACY_PREAMBLE.match(stripped):
            continue
        match = _LEGACY_HEADER.match(stripped)
        if match is not None:
            start_ms = parse_timestamp(match.group("stamp"), line_number=number)
            segments.append(
                ParsedSegment(
                    ordinal=len(segments) + 1,
                    start_ms=start_ms,
                    end_ms=None,
                    speaker_label=match.group("label").strip() or None,
                    text="",
                )
            )
            bodies.append([])
            continue
        candidate = _LEGACY_HEADER_CANDIDATE.match(stripped)
        if candidate is not None:
            # It has the shape of a header, so an invalid stamp is evidence of
            # a malformed source, not utterance text to attribute to the prior
            # speaker.
            parse_timestamp(candidate.group("stamp"), line_number=number)
        if segments:
            bodies[-1].append(stripped)
        else:
            raise TranscriptParseError(
                _at("nonblank text appears before the first transcript turn", number)
            )

    return ParsedTranscript(
        format=FORMAT_LEGACY,
        segments=tuple(
            ParsedSegment(
                ordinal=segment.ordinal,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                speaker_label=segment.speaker_label,
                text=" ".join(body).strip(),
            )
            for segment, body in zip(segments, bodies)
        ),
    )


def parse_vtt(text: str) -> ParsedTranscript:
    """Parse a WebVTT track into cues, never into speakers.

    Deliberately lenient: a VTT that will not parse is recorded as a source
    with zero segments and the ``.txt`` is still used, so one malformed cue
    must not cost the meeting its end timings. Cues whose timing line will not
    parse are skipped rather than raised on.
    """
    segments: list[ParsedSegment] = []
    lines = _lines(text)
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        match = _VTT_TIMING.match(line)
        if match is None:
            continue
        try:
            start_ms = parse_timestamp(match.group("start"))
            end_ms = parse_timestamp(match.group("end"))
        except TranscriptParseError:
            continue
        body: list[str] = []
        while index < len(lines) and lines[index].strip():
            body.append(lines[index].strip())
            index += 1
        payload = _VTT_TAG.sub("", _VTT_VOICE.sub("", " ".join(body))).strip()
        segments.append(
            ParsedSegment(
                ordinal=len(segments) + 1,
                start_ms=start_ms,
                end_ms=max(end_ms, start_ms),
                # A cue never supplies a speaker: in this corpus every drop's
                # VTT is a speaker-less subtitle track, and AD-13 puts labels
                # with the speaker-attributed export.
                speaker_label=None,
                text=payload,
            )
        )
    return ParsedTranscript(format=FORMAT_VTT, segments=tuple(segments))


def parse_text_transcript(text: str) -> ParsedTranscript:
    """Parse a provided ``.txt`` in whichever lineage it turns out to be.

    An empty (or whitespace-only) file is a legitimate zero-turn transcript,
    not a parse failure — the stage records it as a source with no segments and
    says so. Raises :class:`TranscriptParseError` when the file has content but
    matches neither lineage: silently ignoring a provided transcript would lose
    exactly the evidence this stage exists to preserve.
    """
    if not any(line.strip() for line in _lines(text)):
        return ParsedTranscript(format=FORMAT_TEAMS, segments=())
    detected = detect_text_format(text)
    if detected == FORMAT_TEAMS:
        return parse_teams_text(text)
    if detected == FORMAT_LEGACY:
        return parse_legacy_text(text)
    raise TranscriptParseError(
        "no line matches either transcript lineage —"
        " expected Teams '[m:ss] Lastname, Firstname: text'"
        " or legacy '<Name> | MM:SS'"
    )


def strip_nuls(text: str) -> str:
    """Remove U+0000, which Postgres refuses in a text *or* jsonb value.

    A recognizer can emit one from a noisy passage, and a transcript export can
    carry one from an encoding mishap. Dropping the byte keeps a readable
    segment readable; failing the stage over it would lose the whole meeting's
    transcript to one bad character.
    """
    return text.replace(NUL, "") if NUL in text else text
