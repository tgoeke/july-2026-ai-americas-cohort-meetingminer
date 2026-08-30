"""Converting a declared transcript dialect into the trusted lineages (FR35).

A meeting exported from Zoom arrives as a ``.vtt`` whose cue payloads read
``Name: text``. The pipeline never reads a speaker out of a VTT — AD-13 puts
speaker labels with the speaker-attributed export, and every VTT in this corpus
is a speaker-less subtitle track — so minting that file as it stands produces a
meeting whose every turn is ``Unknown``/``placeholder``. The names are in the
file and the system cannot see them.

This module converts, and it converts *at acquisition*:

* the Zoom ``.vtt`` becomes a **legacy-lineage** ``transcript.txt`` —
  ``<Name> | MM:SS`` on its own line, the utterance beneath it — which is one
  of the two speaker-attributed forms ``pipeline/transcripts.py`` already
  parses, and
* a **speaker-less** ``transcript.vtt`` carrying every cue's timing, which is
  what a drop's VTT is for.

``pipeline/transcripts.py`` and the ``align`` stage are untouched by this
story, and that is the point: the converted ``.txt`` is an ordinary legacy
transcript, so a Zoom name resolves through the meeting's roster by exactly the
path a Teams label takes.

Rules this module will not bend:

**A dialect is declared, never inferred.** Nothing here sniffs content to
decide what a file is. ``plain`` is the default and is today's behaviour
bit-for-bit; ``teams-vtt`` is a pass-through *declaration* (a Teams export
already is the trusted format); ``zoom`` converts. Guessing would eventually
guess wrong on a file that looks like two things, and a drop is write-once.

**A cue's speaker is taken conservatively, or not at all.** The speaker is the
text before the first ``:`` on the cue's payload, accepted only when it reads
like a name: one to six whitespace-separated tokens, at least one letter, and
none of ``.``, ``?``, ``!``. So ``Right. So: here we go`` is not a person, and
a cue whose prefix is rejected becomes an ``Unknown`` turn — the pipeline's
placeholder — rather than inheriting the previous speaker's name. A wrong
attribution is worse than an absent one, and ``Unknown`` is a label
:func:`meetingminer.pipeline.speakers.is_placeholder_label` already refuses to
turn into a participant. The cost is a name spelled ``Dr. Alice Chen``, which
this rule declines to read; the alternative rule reads ``Well. Anyway`` as a
person.

**The converter verifies its own output.** Before anything is minted, the
produced ``.txt`` is re-parsed with the pipeline's *own* parser and checked
turn for turn against what the conversion intended. A drop is write-once, so a
transcript the ``align`` stage would fail on must never reach the drops root —
the same argument that puts schema validation inside ``mintdrop._assemble``.
This is also what makes the module safe against the shapes it cannot see
coming: a cue whose text happens to read as a ``<Name> | MM:SS`` header, or a
file long enough to overflow the header's two-digit hour field, is refused by
name instead of silently producing a transcript that means something else.

**The conversion is deterministic.** The same Zoom ``.vtt`` produces the same
bytes, which is what makes a transcript-only re-mint reach ``exists`` rather
than minting a second meeting: ``mint()``'s identity rule is unchanged — the
digest of the bytes that entered the drop — so the output bytes are part of
that identity. ``test_transcript_dialects.py`` pins them.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Iterator, Sequence

from meetingminer.domain.drops import (
    TRANSCRIPT_TEXT_FILENAME,
    TRANSCRIPT_VTT_FILENAME,
    sha256_and_size,
)
from meetingminer.pipeline import transcripts

#: The declared dialects. ``plain`` means "these files are already what a drop
#: holds"; it is the default and it changes nothing.
DIALECT_PLAIN = "plain"
DIALECT_TEAMS_VTT = "teams-vtt"
DIALECT_ZOOM = "zoom"
DIALECTS = (DIALECT_PLAIN, DIALECT_TEAMS_VTT, DIALECT_ZOOM)
DEFAULT_DIALECT = DIALECT_PLAIN

#: The provenance key this module writes, under ``metadata.provenance``. The
#: drop schema's ``provenance`` is an open object, so the record needs no
#: schema change; it is the only place the *original* file is named, because
#: ``provenance.files[]`` describes the converted bytes that entered the drop.
PROVENANCE_KEY = "transcriptDialect"

#: ``00:00:27.702 --> 00:00:28.662`` plus optional cue settings. Deliberately
#: its own pattern rather than the pipeline's: the pipeline is lenient with a
#: VTT because a bad cue there costs only an end timing, while here a skipped
#: cue is lost evidence, so this reader refuses instead.
_CUE_TIMING = re.compile(
    r"^(?P<start>\d{1,4}(?::\d{1,2}){1,2}(?:[.,]\d+)?)\s*-->\s*"
    r"(?P<end>\d{1,4}(?::\d{1,2}){1,2}(?:[.,]\d+)?)(?:\s+.*)?$"
)

_WEBVTT_HEADER = re.compile(r"WEBVTT(?:[ \t].*)?")

#: Markup a cue payload may carry. Stripped before the speaker is read, so
#: ``<b>Alice Chen</b>: hello`` still yields the name.
_TAG = re.compile(r"</?[a-z/][^>]*>", re.IGNORECASE)

#: ``Alice Chen: good morning`` — the name is everything before the *first*
#: colon, and it is only accepted as a name by :func:`_is_speaker_name`.
_PREFIXED = re.compile(r"^(?P<name>[^:]{1,60}):\s*(?P<text>.*)$")

#: Characters a display name does not contain but a sentence does. A name is
#: allowed a comma (``Chen, Alice``) and an apostrophe or hyphen.
_NOT_IN_A_NAME = ".?!"

#: More tokens than any display name this corpus carries; past it the prefix is
#: a clause, not a person.
_MAX_NAME_TOKENS = 6


class DialectError(RuntimeError):
    """A named refusal: the conversion declines and nothing is written.

    Raised before any drop exists. ``mintdrop`` prints it exactly as it prints
    a :class:`~meetingminer.mintdrop.MintError` — the operator cannot act on
    the difference between "this file is not what you said it was" and "this
    file cannot be minted", and both leave the drops root untouched.
    """


@dataclass(frozen=True)
class ZoomCue:
    """One cue: its timing, the speaker it named, and what was said."""

    start_ms: int
    end_ms: int
    speaker: str | None
    text: str


@dataclass(frozen=True)
class Turn:
    """One turn of the converted transcript — a legacy-lineage block."""

    start_ms: int
    speaker: str
    text: str


@dataclass(frozen=True)
class Conversion:
    """What to mint, and what to record about how it was produced.

    ``supplied`` is handed to ``mint()`` in place of the operator's own list:
    for ``zoom`` the source ``.vtt`` is replaced by the two converted files.
    ``provenance_extra`` goes to ``build_metadata()``'s keyword override
    (story 6.2's mechanism) and is ``None`` for ``plain``, so the default
    dialect writes exactly the metadata it wrote before this story.
    """

    supplied: list[str]
    provenance_extra: dict[str, Any] | None


@contextmanager
def workspace() -> Iterator[Path]:
    """A directory the converted files live in until the drop is finalized.

    Deliberately transient: the converted bytes belong in the write-once drop,
    not beside the operator's original. ``mint()`` copies them out of here and
    verifies the copy, so nothing outlives the command but the drop.
    """
    with TemporaryDirectory(prefix="mint-drop-dialect-") as directory:
        yield Path(directory)


def convert_supplied(
    paths: Sequence[str], *, dialect: str, into: Path
) -> Conversion:
    """The files to mint for this declared dialect, and its provenance record.

    ``plain`` and ``teams-vtt`` pass every path through untouched — the second
    records the operator's declaration and nothing else, because a Teams export
    already is a speaker-attributed ``.txt`` beside a speaker-less ``.vtt``.
    ``zoom`` converts the one supplied ``.vtt`` into both files, written under
    ``into``.
    """
    if dialect not in DIALECTS:
        raise DialectError(
            f"unknown transcript dialect {dialect!r} —"
            f" expected one of {', '.join(DIALECTS)}"
        )
    if dialect == DIALECT_PLAIN:
        return Conversion(supplied=list(paths), provenance_extra=None)
    if dialect == DIALECT_TEAMS_VTT:
        return Conversion(
            supplied=list(paths),
            provenance_extra={
                PROVENANCE_KEY: {"dialect": DIALECT_TEAMS_VTT, "converted": False}
            },
        )
    return _convert_zoom(paths, into=into)


def _convert_zoom(paths: Sequence[str], *, into: Path) -> Conversion:
    """Replace the supplied Zoom ``.vtt`` with the two files a drop holds."""
    source = _zoom_source(paths)
    cues = read_zoom_cues(_read_source(source), source=source)
    turns = zoom_turns(cues)
    text = render_legacy_text(turns)
    verify_legacy_text(text, turns, source=source)

    # Named after the operator's file, so `--title`'s default (the primary
    # file's stem) is the name they recognise rather than a temp filename.
    text_path = into / f"{source.stem}.txt"
    vtt_path = into / f"{source.stem}.vtt"
    text_path.write_text(text, encoding="utf-8", newline="\n")
    vtt_path.write_text(render_timing_vtt(cues), encoding="utf-8", newline="\n")

    digest, byte_size = sha256_and_size(source)
    # `source` is resolved, so the comparison has to be: a path spelled with
    # `~` or a relative segment is the same file and must not be minted beside
    # its own conversion.
    supplied = [
        raw
        for raw in paths
        if Path(raw).expanduser().resolve() != source
    ]
    supplied += [str(vtt_path), str(text_path)]
    return Conversion(
        supplied=supplied,
        provenance_extra={
            PROVENANCE_KEY: {
                "dialect": DIALECT_ZOOM,
                "converted": True,
                "outputs": [TRANSCRIPT_VTT_FILENAME, TRANSCRIPT_TEXT_FILENAME],
                # `provenance.files[]` describes the converted bytes and their
                # workspace path, which is gone by the time anyone reads the
                # drop. This is the record of what was actually converted.
                "source": {
                    "sourcePath": str(source),
                    "sha256": digest,
                    "byteSize": byte_size,
                },
                "cueCount": len(cues),
                "turnCount": len(turns),
                "speakerLabels": _distinct(turn.speaker for turn in turns),
            }
        },
    )


def _zoom_source(paths: Sequence[str]) -> Path:
    """The one ``.vtt`` to convert, or a refusal naming what is wrong.

    A supplied ``.txt`` is refused rather than quietly losing to the converted
    one: the conversion *produces* ``transcript.txt``, a drop holds one of
    each, and picking a winner would silently drop somebody's evidence.
    """
    vtt = [Path(raw).expanduser() for raw in paths if Path(raw).suffix.lower() == ".vtt"]
    text = [Path(raw).expanduser() for raw in paths if Path(raw).suffix.lower() == ".txt"]
    if not vtt:
        raise DialectError(
            f"--transcript-dialect {DIALECT_ZOOM} converts a Zoom .vtt export"
            " and none was supplied — pass the .vtt, or mint with"
            f" --transcript-dialect {DIALECT_PLAIN}"
        )
    if len(vtt) > 1:
        raise DialectError(
            "two .vtt files were supplied"
            f" ({', '.join(str(path) for path in vtt)}) — a drop holds one"
            " transcript.vtt, so there is one file to convert"
        )
    if text:
        raise DialectError(
            f"--transcript-dialect {DIALECT_ZOOM} produces"
            f" {TRANSCRIPT_TEXT_FILENAME} from {vtt[0]}, but {text[0]} was"
            " supplied as well and a drop holds one of each — supply only the"
            f" .vtt, or mint both files with --transcript-dialect"
            f" {DIALECT_PLAIN}"
        )
    resolved = vtt[0].resolve()
    if not resolved.is_file():
        raise DialectError(
            f"not a readable file: {vtt[0]}"
            + ("" if resolved.exists() else " (it does not exist)")
        )
    return resolved


def _read_source(source: Path) -> str:
    """The export's text, with a BOM tolerated and mojibake refused."""
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise DialectError(f"{source} could not be read: {exc}") from exc
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DialectError(
            f"{source} is not UTF-8 text ({exc}) — a transcript decoded with"
            " replacement characters would carry them into a write-once drop"
        ) from exc


def read_zoom_cues(text: str, *, source: Path) -> tuple[ZoomCue, ...]:
    """Every cue of a Zoom ``.vtt``, with the speaker its payload named.

    Stricter than :func:`meetingminer.pipeline.transcripts.parse_vtt` on
    purpose. There, a cue that will not parse costs one end timing and the
    ``.txt`` still carries the words; here the cues *are* the words, so a
    malformed timing line is a refusal that names the line rather than a cue
    quietly dropped on the floor.

    A cue with no words after its prefix is skipped: ``Alice Chen:`` with
    nothing behind it is not evidence of anything.
    """
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        raise DialectError(f"{source} is empty — an empty file is not a transcript")
    header = next(line.strip() for line in lines if line.strip())
    if _WEBVTT_HEADER.fullmatch(header) is None:
        raise DialectError(
            f"{source} does not start with a WEBVTT header (first line"
            f" {header!r}) — --transcript-dialect {DIALECT_ZOOM} reads Zoom's"
            " .vtt export"
        )

    cues: list[ZoomCue] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        number = index + 1
        index += 1
        if "->" in line and "-->" not in line:
            raise DialectError(
                f"{source} line {number}: {line!r} is not a WebVTT timing line"
                " — nothing was converted"
            )
        if "-->" not in line:
            # A cue identifier, the header, a NOTE — none of them carry words.
            continue
        match = _CUE_TIMING.match(line)
        if match is None:
            raise DialectError(
                f"{source} line {number}: {line!r} is not a WebVTT timing line"
                " — nothing was converted"
            )
        start_ms = _stamp(match.group("start"), source=source, number=number)
        end_ms = _stamp(match.group("end"), source=source, number=number)
        if end_ms < start_ms:
            raise DialectError(
                f"{source} line {number}: cue ends before it starts"
                " — nothing was converted"
            )
        body: list[str] = []
        while index < len(lines) and lines[index].strip():
            if "-->" in lines[index]:
                raise DialectError(
                    f"{source} line {index + 1}: cue timing appears before a"
                    " blank separator — nothing was converted"
                )
            body.append(lines[index].strip())
            index += 1
        if body:
            speaker, first_spoken = _split_speaker(body[0])
            continuations = [_TAG.sub("", line).strip() for line in body[1:]]
            spoken = " ".join(
                part for part in (first_spoken, *continuations) if part
            ).strip()
        else:
            speaker, spoken = None, ""
        if not spoken:
            continue
        if cues and start_ms < cues[-1].start_ms:
            raise DialectError(
                f"{source} line {number}: cue starts at {start_ms}ms before the"
                f" preceding cue at {cues[-1].start_ms}ms (out of order)"
                " — nothing was converted"
            )
        cues.append(
            ZoomCue(
                start_ms=start_ms,
                end_ms=end_ms,
                speaker=speaker,
                text=spoken,
            )
        )

    if not cues:
        raise DialectError(
            f"{source} carries no cue with any text — there is nothing to"
            " convert"
        )
    if not any(cue.speaker for cue in cues):
        raise DialectError(
            f"no cue in {source} carries a 'Name:' prefix, so declaring it"
            f" {DIALECT_ZOOM} would produce a transcript with no speakers at"
            f" all — a speaker-less export is --transcript-dialect"
            f" {DIALECT_TEAMS_VTT}"
        )
    return tuple(cues)


def _stamp(raw: str, *, source: Path, number: int) -> int:
    """One cue timestamp, through the pipeline's own parser.

    Borrowed rather than re-spelled: "what does ``00:01:02.500`` mean" must
    have one answer in this repository, and the pipeline owns it.
    """
    try:
        return transcripts.parse_timestamp(raw)
    except transcripts.TranscriptParseError as exc:
        raise DialectError(f"{source} line {number}: {exc}") from exc


def _split_speaker(payload: str) -> tuple[str | None, str]:
    """``(speaker or None, the words)`` for one cue's payload.

    When the prefix is not a name, the whole payload is the words — the text
    is never dropped along with the prefix that failed.
    """
    stripped = _TAG.sub("", payload).strip()
    match = _PREFIXED.match(stripped)
    if match is None:
        return None, stripped
    name = match.group("name").strip()
    if not _is_speaker_name(name):
        return None, stripped
    return name, (match.group("text") or "").strip()


def _is_speaker_name(name: str) -> bool:
    """Whether a cue prefix reads as a person rather than as a clause."""
    if not name or not any(character.isalpha() for character in name):
        return False
    if any(character in name for character in _NOT_IN_A_NAME):
        return False
    return len(name.split()) <= _MAX_NAME_TOKENS


def zoom_turns(cues: Sequence[ZoomCue]) -> tuple[Turn, ...]:
    """Cues folded into turns — consecutive cues by one speaker are one turn.

    Zoom emits roughly a cue per sentence, and a *turn* in both text lineages
    is "what one person said before somebody else spoke". Folding here is what
    makes a converted transcript segment the way a Teams one does; the cue
    timings all survive in the ``.vtt``, where the aligner takes each turn's
    real end from the last cue that matches it.
    """
    turns: list[Turn] = []
    for cue in cues:
        label = cue.speaker or transcripts.UNKNOWN_SPEAKER
        if turns and turns[-1].speaker == label:
            previous = turns[-1]
            turns[-1] = Turn(
                start_ms=previous.start_ms,
                speaker=label,
                text=f"{previous.text} {cue.text}".strip(),
            )
            continue
        turns.append(Turn(start_ms=cue.start_ms, speaker=label, text=cue.text))
    return tuple(turns)


def format_block_stamp(start_ms: int) -> str:
    """A legacy header stamp: ``MM:SS``, or ``HH:MM:SS`` past the hour.

    Both forms in one file is the corpus's own shape — the long legacy
    transcript reads ``08:47`` early and ``01:57:24`` late — and the pipeline
    parses by field count, so the switch costs nothing.

    Truncated, never rounded: a citation offset that rounds *up* points past
    the moment somebody started speaking.
    """
    total_seconds = max(start_ms, 0) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_cue_time(milliseconds: int) -> str:
    """A WebVTT timestamp: ``HH:MM:SS.mmm``."""
    total = max(milliseconds, 0)
    hours, remainder = divmod(total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def render_legacy_text(turns: Sequence[Turn]) -> str:
    """The legacy lineage: a ``<Name> | MM:SS`` header, then the utterance."""
    blocks = [
        f"{turn.speaker} | {format_block_stamp(turn.start_ms)}\n{turn.text}"
        for turn in turns
    ]
    return "\n\n".join(blocks) + "\n"


def render_timing_vtt(cues: Sequence[ZoomCue]) -> str:
    """The drop's ``transcript.vtt``: every cue's timing, no speakers.

    The ``Name: `` prefix comes off. A drop's VTT is a speaker-less subtitle
    track by convention and by AD-13, and the aligner matches a cue to a turn
    by token overlap — leaving the name in every payload would compare a name
    against text that no longer carries it.
    """
    body = "".join(
        f"{format_cue_time(cue.start_ms)} --> {format_cue_time(cue.end_ms)}\n"
        f"{cue.text}\n\n"
        for cue in cues
    )
    return f"WEBVTT\n\n{body}"


def verify_legacy_text(text: str, turns: Sequence[Turn], *, source: Path) -> None:
    """Re-read the converted ``.txt`` with the pipeline's parser, or refuse.

    The drop is write-once and the ``align`` stage fails the whole meeting on a
    ``.txt`` it cannot parse, so the check that matters is not "did the
    converter run" but "does the file it produced mean what the conversion
    meant". Asking the pipeline's own parser is the only way to answer that
    without a second implementation of the answer.

    It catches the shapes no amount of rendering care avoids: an utterance that
    itself reads as a ``<Name> | MM:SS`` header, a transcript long enough to
    overflow the header's two-digit hour field, a cue whose text turns the
    lineage detector towards Teams.
    """
    try:
        parsed = transcripts.parse_text_transcript(text)
    except transcripts.TranscriptParseError as exc:
        raise DialectError(
            f"the transcript converted from {source} does not parse: {exc}"
            " — nothing was minted"
        ) from exc
    if parsed.format != transcripts.FORMAT_LEGACY:
        raise DialectError(
            f"the transcript converted from {source} reads as the"
            f" {parsed.format!r} lineage rather than {transcripts.FORMAT_LEGACY!r}"
            " — its own text has the shape of another format"
        )
    if len(parsed.segments) != len(turns):
        raise DialectError(
            f"the transcript converted from {source} re-parses as"
            f" {len(parsed.segments)} turns rather than the {len(turns)}"
            " converted — an utterance has the shape of a '<Name> | MM:SS'"
            " header"
        )
    for turn, segment in zip(turns, parsed.segments):
        expected_start = max(turn.start_ms, 0) // 1000 * 1000
        if (segment.speaker_label or "") != turn.speaker:
            raise DialectError(
                f"the transcript converted from {source} re-parses turn"
                f" {segment.ordinal} as speaker"
                f" {segment.speaker_label!r} rather than {turn.speaker!r}"
            )
        if segment.start_ms != expected_start:
            raise DialectError(
                f"the transcript converted from {source} re-parses turn"
                f" {segment.ordinal} at {segment.start_ms}ms rather than"
                f" {expected_start}ms — the header stamp cannot hold this"
                " offset"
            )
        if segment.text != turn.text:
            raise DialectError(
                f"the transcript converted from {source} re-parses turn"
                f" {segment.ordinal} with different text than was converted"
            )


def _distinct(labels: Iterable[str]) -> list[str]:
    """The labels, de-duplicated, in first-appearance order."""
    seen: dict[str, None] = {}
    for label in labels:
        seen.setdefault(label, None)
    return list(seen)
