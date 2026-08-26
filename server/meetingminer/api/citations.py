"""The AD-6 citation gate: deterministic, pure, and the only thing that can
let an answer out of ``POST /chat`` (story 3.3, FR13/FR14, NFR4).

**The gate is code, not prompt text.** AD-6 says "no citation, no answer" is
enforced by a validator rather than by instructions to a model, so everything
here is mechanical: a regular expression finds the markers, a character walk
splits the draft into sentence units, and a caller-supplied ``resolve`` re-reads
every cited id from the database of record. A model cannot talk its way past
any of it.

**No FastAPI, no store client, no config.** This module imports the standard
library and nothing else, which is what makes the whole gate unit-testable in
isolation (``tests/test_chat_citations.py``) and reviewable in one file. The
route in :mod:`meetingminer.api.chat` supplies the two things this module
refuses to know: what was actually retrieved, and how to read Postgres.

**"Every claim cited" is enforced as "every sentence cited."** Deciding whether
a sentence states a fact is a model judgment, and a model judgment cannot be
the enforcement mechanism for the property AD-6 fixes. So the rule
over-approximates on purpose: every sentence unit holding an alphanumeric
character must carry at least one marker, connective prose included. The
synthesis prompt is written to that rule, so a compliant model produces
compliant prose; a non-compliant one is rejected whole rather than repaired.

**Rejection is a value, never an exception.** :func:`validate` returns either a
:class:`ValidatedAnswer` or a :class:`Rejection` carrying one of the closed
:data:`REJECTION_REASONS`. The route turns a rejection into the RFC 9457 problem
body; nothing here knows about HTTP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Collection, Mapping, Sequence
from uuid import UUID

__all__ = [
    "MARKER_PATTERN",
    "MomentCitation",
    "REJECTION_REASONS",
    "Rejection",
    "SentenceUnit",
    "ValidatedAnswer",
    "parse_markers",
    "split_claims",
    "strip_markers",
    "validate",
]


# AD-15's wire format, matched loosely on purpose. The payload is *anything*
# that is not a bracket, so `[[moment:not-a-uuid]]` is recognized as an attempt
# to cite rather than passing as ordinary prose — the difference between
# "the model cited something that does not exist" (a named rejection an
# operator can act on) and "the model wrote a sentence with no citation".
MARKER_PATTERN = re.compile(r"\[\[moment:([^\[\]]*)\]\]")

# What ends a sentence unit. Newline ends one too, so a bulleted or numbered
# answer is split per bullet rather than being treated as one giant sentence
# that a single marker anywhere would satisfy.
_TERMINATORS = ".!?"
# Python's ``str.splitlines`` recognizes this set. A model reply may carry a
# carriage return or a Unicode separator even though the JSON transport writes
# it differently; every one starts a new sentence unit for the gate.
_LINE_BREAKS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"

# The closed set a `reason` extension may carry. Story 3.4 renders one "no
# citable answer" state; an operator still has to be able to tell "the corpus
# held nothing" from "the model cited a moment that does not exist", and a
# closed set is what makes that a contract rather than a log-grep.
REJECTION_REASONS: tuple[str, ...] = (
    # Retrieval produced no moment at all — refused before synthesis, by the
    # route rather than by this module.
    "no-evidence",
    # The draft carried no `[[moment:` marker anywhere.
    "no-citations",
    # At least one sentence unit with alphanumeric content carried no marker.
    "uncited-claim",
    # A marker whose payload is not a UUID, names a moment that was not
    # retrieved for this question, or no longer resolves in Postgres.
    "unresolvable-marker",
    # The draft held no prose once the markers were removed.
    "empty-answer",
)


@dataclass(frozen=True)
class MomentCitation:
    """One resolved citation, in the AD-15 field set.

    Every field is read from Postgres by the caller's ``resolve``; nothing here
    is ever taken from Neo4j, Meilisearch, or the model's text. ``screenshot_id``
    is absent on a transcript-only meeting, where ``source_deep_link`` carries
    UX-DR11's transitional affordance in its place.
    """

    moment_id: UUID
    meeting_id: UUID
    start_ms: int
    end_ms: int
    screenshot_id: UUID | None = None
    source_deep_link: str | None = None


@dataclass(frozen=True)
class SentenceUnit:
    """One sentence unit of a draft, with the markers that belong to it.

    ``text`` is the raw slice, markers included; ``prose`` is the same slice
    with the markers removed, which is what the alphanumeric test reads.
    """

    text: str
    prose: str
    markers: tuple[str, ...]

    @property
    def is_claim(self) -> bool:
        """Whether this unit must carry a citation.

        Any alphanumeric character makes it one. A unit of pure punctuation or
        whitespace ("---", a stray closing quote) asserts nothing and is not
        held to the rule.
        """
        return any(character.isalnum() for character in self.prose)


@dataclass(frozen=True)
class ValidatedAnswer:
    """An answer that passed the gate: prose with no markers, plus its array."""

    answer: str
    citations: tuple[MomentCitation, ...]


@dataclass(frozen=True)
class Rejection:
    """An answer that did not pass. ``reason`` is one of :data:`REJECTION_REASONS`."""

    reason: str
    detail: str

    def __post_init__(self) -> None:
        # A typo in a reason string would reach story 3.4 as an unknown state
        # and render as nothing at all, so the closed set is enforced here
        # rather than described in a comment.
        if self.reason not in REJECTION_REASONS:
            raise ValueError(
                f"{self.reason!r} is not a citation-gate rejection reason —"
                f" the closed set is {', '.join(REJECTION_REASONS)}"
            )


def parse_markers(text: str) -> tuple[str, ...]:
    """Every marker payload in ``text``, in order of appearance, duplicates kept.

    Payloads are returned as written — stripped of surrounding whitespace but
    not parsed, not lowercased, and not validated. Turning a payload into a
    :class:`~uuid.UUID` is :func:`validate`'s job, because a payload that is not
    one is a *rejection*, not a parse error.
    """
    return tuple(match.group(1).strip() for match in MARKER_PATTERN.finditer(text))


# A private-use code point standing in for a removed marker while the gap it
# left is closed. Private-use, so it cannot collide with anything a model
# legitimately writes — and any that a draft *does* carry is dropped before the
# substitution, so a draft cannot forge one.
_MARKER_SLOT = "\ue000"

# A run of horizontal whitespace around one or more removed markers. Only these
# spans are rewritten; whitespace elsewhere in the line is the model's and stays.
_SLOT_RUN = re.compile(rf"[ \t]*(?:{_MARKER_SLOT}[ \t]*)+")

# Characters that close a clause. A marker sitting before one of them leaves no
# space behind: "moved [[m]]." is "moved.", not "moved ."
_CLOSING = ",.;:!?)]}\"'"


def strip_markers(text: str) -> str:
    """``text`` with every marker removed and only the gap it left closed up.

    Removing ``[[moment:…]]`` from "the feed moved [[moment:x]]." leaves a space
    before the period, and from "moved. [[moment:x]] The PO…" leaves a double
    space. Both are tidied, because the answer string on the wire is what a
    person reads and a marker's former position must not be legible in it.

    Nothing else is touched. Interior spacing the model wrote on purpose — an
    aligned list, two spaces after a colon — survives, and so do newlines: an
    answer's line structure is the model's. Only the leading and trailing
    whitespace of the whole string is trimmed.
    """
    marked = MARKER_PATTERN.sub(_MARKER_SLOT, text.replace(_MARKER_SLOT, ""))

    def _close(match: re.Match[str]) -> str:
        start, end = match.span()
        before = marked[start - 1] if start else ""
        after = marked[end] if end < len(marked) else ""
        # At a line or string boundary, or hard against punctuation, the marker
        # occupied a position no space belongs in. Between two words it stood
        # where one space belongs.
        if before in ("", "\n") or after in ("", "\n") or after in _CLOSING:
            return ""
        return " "

    return _SLOT_RUN.sub(_close, marked).strip()


def _unit(raw: str) -> SentenceUnit:
    return SentenceUnit(text=raw, prose=strip_markers(raw), markers=parse_markers(raw))


def split_claims(text: str) -> tuple[SentenceUnit, ...]:
    """Split a draft into the sentence units the gate holds to the rule.

    A unit ends at ``.``/``!``/``?`` or at a newline. After a *terminator* — not
    after a newline — any run of spaces followed by markers is pulled back into
    the unit that just ended, so both placements a model reaches for are read
    the same way::

        The feed moved to SFTP [[moment:a]].
        The feed moved to SFTP. [[moment:a]]

    Without that pull-back the second form would leave sentence one uncited and
    sentence two carrying a citation for a claim it does not make — a gate that
    rejects correct answers over whitespace. The pull-back deliberately does not
    cross a newline: a marker opening the next line belongs to that line.

    Markers are skipped over while scanning, so a terminator *inside* a marker
    payload (a malformed ``[[moment:a.b]]``) cannot split a unit in half.
    """
    units: list[SentenceUnit] = []
    length = len(text)
    start = 0
    index = 0
    while index < length:
        marker = MARKER_PATTERN.match(text, index)
        if marker is not None:
            index = marker.end()
            continue
        character = text[index]
        if character in _LINE_BREAKS:
            index += 1
            units.append(_unit(text[start:index]))
            start = index
            continue
        if character in _TERMINATORS:
            index += 1
            while True:
                lookahead = index
                while lookahead < length and text[lookahead] in " \t":
                    lookahead += 1
                trailing = MARKER_PATTERN.match(text, lookahead)
                if trailing is None:
                    break
                index = trailing.end()
            units.append(_unit(text[start:index]))
            start = index
            continue
        index += 1
    if start < length:
        units.append(_unit(text[start:length]))
    # A unit that is nothing but whitespace carries no claim and no marker; it
    # is an artifact of the split, not part of the answer.
    return tuple(unit for unit in units if unit.text.strip())


def _parsed(payload: str) -> UUID | None:
    try:
        return UUID(payload)
    except (ValueError, AttributeError, TypeError):
        return None


def validate(
    draft: str,
    retrieved: Collection[UUID],
    resolve: Callable[[Sequence[UUID]], Mapping[UUID, MomentCitation]],
) -> ValidatedAnswer | Rejection:
    """Run the whole gate over one model draft.

    ``retrieved`` is the set of moment ids deterministic retrieval actually
    produced for this question; ``resolve`` re-reads the cited ones from
    Postgres in the same request. Both conditions are required (AD-6): a marker
    naming a real moment nobody retrieved is a model inventing a source, and a
    marker naming a retrieved moment whose row is gone is a citation that
    resolves nowhere.

    The checks run in a fixed order so one draft always earns the same reason:
    empty first (there is nothing to cite), then "cited nothing at all", then
    the markers themselves, then the per-sentence rule, then the Postgres
    read-back. "No markers anywhere" precedes the per-sentence rule because
    ``no-citations`` says something an operator can act on that a per-sentence
    ``uncited-claim`` would bury.
    """
    prose = strip_markers(draft)
    # A valid inner marker must not make an unmatched outer ``[[moment:``
    # prefix disappear from scrutiny. Apart from making the wire answer leak
    # protocol syntax, accepting it would turn malformed citation text into an
    # apparently valid answer.
    if "[[moment:" in prose:
        return Rejection(
            "unresolvable-marker",
            "the answer contains malformed [[moment:<uuid>]] citation syntax",
        )
    if not any(character.isalnum() for character in prose):
        return Rejection(
            "empty-answer",
            "the model returned no prose to cite"
            f" ({len(parse_markers(draft))} marker(s), no words)",
        )

    payloads = parse_markers(draft)
    if not payloads:
        return Rejection(
            "no-citations",
            "the answer carried no [[moment:<uuid>]] marker — every claim must"
            " name the moment it came from (AD-6)",
        )

    retrieved_ids = set(retrieved)
    # First appearance decides both the citation order on the wire and which
    # bad marker gets named, so the walk is over `payloads` in order.
    cited: list[UUID] = []
    for payload in payloads:
        moment_id = _parsed(payload)
        if moment_id is None:
            return Rejection(
                "unresolvable-marker",
                f"marker [[moment:{payload}]] does not name a UUID",
            )
        if moment_id not in retrieved_ids:
            return Rejection(
                "unresolvable-marker",
                f"marker [[moment:{payload}]] names moment {moment_id} which"
                " was not retrieved for this question",
            )
        if moment_id not in cited:
            cited.append(moment_id)

    for unit in split_claims(draft):
        if unit.is_claim and not unit.markers:
            return Rejection(
                "uncited-claim",
                "every sentence must carry at least one [[moment:<uuid>]]"
                f" marker; this one carries none: {unit.prose.strip()!r}",
            )

    rows = resolve(cited)
    missing = [moment_id for moment_id in cited if moment_id not in rows]
    if missing:
        return Rejection(
            "unresolvable-marker",
            "the database of record no longer holds cited moment(s): "
            + ", ".join(str(moment_id) for moment_id in missing),
        )

    return ValidatedAnswer(
        answer=prose, citations=tuple(rows[moment_id] for moment_id in cited)
    )
