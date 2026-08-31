"""Engine-free decision core for the `extract` stage (AD-8, AD-13).

Everything here is deterministic string work: render the meeting's transcript,
build the two whole-transcript prompts, parse a summariser document strictly,
resolve an item's `[m:ss]` anchor to the moment containing it. No SQL, no
store, no SDK — the I/O around it lives in
:mod:`meetingminer.pipeline.stages.extract`, exactly the split every other
stage uses.

**Why whole-transcript.** Story 4.1 extracted per moment, and the granularity
was wrong: a decision emerges across minutes of discussion — proposal,
pushback, agreement — and almost never sits inside one moment. Extraction now
makes one pass per *document kind* over the whole meeting, and every proposed
artifact carries the `[m:ss]` anchor that resolves it back to a single moment,
so "no citation, no answer" still holds.

**One parser, two paths.** A drop may already carry the puller summariser's two
markdown documents. When it does, the stage parses those bytes and makes zero
model calls; when it does not, the same two documents are generated through the
`Llm` port. Both paths converge on :func:`parse_extraction_document`, which is
why the generate prompts below pin the same markdown shape the summariser
emits.

**The parser keys on item ID and timestamp, never on heading numbering.**
Sampled real output shows the heading style varies per meeting (``# 1️⃣
Executive Summary``, ``## 1. Header & Executive Summary``, ``# 1 Executive
Summary``, sometimes a document title line before section 1). Column headers
drift, rows go ragged, and timestamps appear as points, ranges, bracketed,
parenthesised, italicised, or comma lists — frequently with non-ASCII hyphens
and curly punctuation. What is stable is the short item ID both prompts mandate
(``D1``, ``A1``, ``R1``, ``BR1``…) and the presence of a timestamp, so those
two are what the scan keys on. Heading *text* is read only to tell the action
document's two explicitly non-action sections apart; heading *numbering* is
never depended on.

**The executive summary is kept, not only its decision rows** (story 12.2).
The architecture summary is a whole-meeting analysis, and until now only the
rows under its decisions heading survived parsing while its executive-summary
prose was read and dropped. :attr:`ParsedDocument.summary` carries that prose
verbatim, and the stage stores it as an artifact scoped to the *meeting*
rather than to a moment. Nothing about citation changes: a summary has no
`[m:ss]` anchor and never becomes one, so it is readable as stored artifact
state and reaches an answer only through the moments its individual claims
anchor to (AD-6, AD-15). A document carrying no such section yields no summary
— the parser never manufactures one.

This is the `retrieval-prior-art.md` §8 lesson made actionable rather than a
promise to be careful. Upstream's indexer understood one of two layouts,
contributed zero decisions for every meeting that used the other, and reported
success; fixing it moved decisions from 41 to 182. Both layouts — a markdown
table row and a bullet line — are parsed identically here, and a document whose
target sections plainly carry content but which yields nothing is a named
signal the stage logs, never a quiet success.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol, Sequence
from uuid import UUID

from meetingminer.pipeline.transcripts import TranscriptParseError, parse_timestamp

# Bumped whenever a prompt constant below changes, and recorded in every
# artifact's provenance, so two proposals produced by different prompt texts
# never look interchangeable to the eval harness. 2 is the whole-transcript
# rework: story 4.1's version 1 was per-moment and JSON-shaped.
PROMPT_VERSION = 2

# The artifact kinds extraction produces, exactly as the `artifact` table's
# CHECK constraint and `projections/publish_gate.py` spell them.
KIND_ADR = "adr"
KIND_ACTION_ITEM = "action-item"

# Story 12.2: the whole-meeting analysis the architecture summary already
# performs. It is an artifact like the two above — same table, same
# `extracted -> approved -> published` lifecycle — and differs only in scope:
# it hangs from the meeting rather than from a moment, so its row carries no
# `moment_id`. Which kinds are meeting-scoped is declared by migration 0022's
# `artifact_scope_matches_kind` CHECK and nowhere else; this constant is the
# kind's spelling, not a second copy of that list, and nothing anywhere reads
# it to decide whether a row is meeting-scoped — `moment_id IS NULL` is the
# observable fact readers branch on.
KIND_SUMMARY = "summary"

# The title every summary artifact carries. `artifact.title` is NOT NULL and
# the heading it would otherwise come from is drifting boilerplate: the same
# section is spelled `# 1 Executive Summary`, `# 1️⃣ Executive Summary` and
# `## 1. Header & Executive Summary` across sampled real documents, so a
# heading-derived title would carry section numbering and emoji into a column
# readers scan. The document's own prose is stored verbatim in `body`, so
# nothing is paraphrased and a constant label invents nothing.
SUMMARY_TITLE = "Executive summary"

KNOWN_KINDS: frozenset[str] = frozenset({KIND_ADR, KIND_ACTION_ITEM, KIND_SUMMARY})

# The two source documents, exactly as `extraction_source.kind` spells them.
DOC_ARCH_SUMMARY = "arch-summary"
DOC_ACTION_ITEMS = "action-items"
DOCUMENT_KINDS: tuple[str, ...] = (DOC_ARCH_SUMMARY, DOC_ACTION_ITEMS)

# Story 10.1: the topics document and its item kind. `KIND_TOPIC` is
# deliberately NOT in `KNOWN_KINDS` (that set feeds the artifact counters)
# and `DOC_TOPICS` NOT in `DOCUMENT_KINDS` (the extract stage's artifact
# loop iterates that): topics are navigation metadata, never artifacts.
KIND_TOPIC = "topic"
DOC_TOPICS = "topics"

# Story 10.4: the ranking-signals document and its two item kinds. Neither
# kind is in `KNOWN_KINDS` and the document is not in `DOCUMENT_KINDS`, for
# exactly the reason topics are excluded from both: these rows are ranking
# signals, never artifacts. They land in the worker-owned `ranking_signal`
# table, carry no `state`, and never reach the publish gate.
#
# `KIND_RISK`/`KIND_QUESTION` are spelled as migration 0018's CHECK spells
# them, so the parser's vocabulary and the record's cannot drift.
KIND_RISK = "risk"
KIND_QUESTION = "question"
RANKING_SIGNAL_KINDS: frozenset[str] = frozenset({KIND_RISK, KIND_QUESTION})
DOC_RANKING_SIGNALS = "ranking-signals"

# Every document kind `parse_extraction_document` and `build_prompt` accept.
_PARSEABLE_DOCUMENT_KINDS: tuple[str, ...] = (
    *DOCUMENT_KINDS,
    DOC_TOPICS,
    DOC_RANKING_SIGNALS,
)

# What `extraction_source.layout` may say.
LAYOUT_TABLE = "table"
LAYOUT_BULLET = "bullet"
LAYOUT_MIXED = "mixed"
LAYOUT_NONE = "none"

# How long a `title` may get before it stops being a title. The full cell text
# is kept in the body either way, so nothing is lost by cutting here.
_MAX_TITLE_CHARS = 200


class ArtifactParseError(ValueError):
    """A source document was not a shape either prompt pins.

    Named so the stage can retry once against the same completer on the
    *generate* path and then fail loudly — never silently treat an unparseable
    document as zero artifacts (SPEC "no silent zero"). The adopt path does not
    retry: re-reading the same bytes cannot parse differently.
    """


class AnchorResolutionError(ValueError):
    """An item's `[m:ss]` anchor falls outside every moment of the meeting.

    A named error path rather than a dropped artifact, deliberately. Moments
    tile the meeting contiguously, so an anchor the timeline does not contain
    is a model that invented a timestamp — and manufacturing a citation for it
    by snapping to the nearest moment is exactly the failure *no citation, no
    answer* exists to prevent. Dropping it silently would be a silent zero by
    another name.
    """


class TurnLike(Protocol):
    """What :func:`render_transcript` needs of a transcript turn."""

    start_ms: int
    text: str
    speaker_label: str


class MomentLike(Protocol):
    """What :func:`resolve_anchor` needs of a moment."""

    id: UUID
    start_ms: int
    end_ms: int


# --- rendering the transcript ----------------------------------------------


def _span(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    if seconds >= 3600:
        # `h:mm:ss` from the hour up — `m:ss` would render 90 minutes as the
        # nonsense timestamp "90:12".
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def render_transcript(turns: Sequence[TurnLike]) -> str:
    """The whole meeting as ``[m:ss] Speaker: text`` lines, in turn order.

    Exactly the shape both puller prompts declare as their input, which is what
    lets the generate path reuse prompts already proven against this corpus.
    Turns arrive from :func:`meetingminer.projections.evidence.read_meeting`
    already ordered by ordinal — the one assembly of "what the meeting says"
    (AD-4), never re-derived here.

    A turn with no text contributes no line: a blank ``[4:12] Ellis:`` is not
    evidence, and padding the transcript with them spends context window a long
    meeting cannot spare.
    """
    lines: list[str] = []
    for turn in turns:
        text = (turn.text or "").strip()
        if not text:
            continue
        label = (turn.speaker_label or "").strip() or "Unknown"
        lines.append(f"[{_span(turn.start_ms)}] {label}: {text}")
    return "\n".join(lines)


# --- the two whole-transcript prompts ---------------------------------------
#
# Story 4.2: both prompt templates now live in `config.yaml` under
# `llm.roles.extraction` (`arch_summary_prompt`/`action_items_prompt`) as the
# two documents' active, editable, complete text — the engine-free core below
# only composes whatever text it is handed with the meeting header and the
# transcript. There is no code-level default: a missing key fails config
# loading, never a silent runtime fallback (AD-10).


def _document_header(meeting_title: str | None, meeting_date: str | None) -> str:
    lines = [f"Meeting: {meeting_title or 'untitled meeting'}"]
    if meeting_date:
        # The puller grounds the model in the real meeting date for exactly one
        # reason: without it, models invent calendar due dates for vague
        # commitments like "next week".
        lines.append(f"This meeting took place on {meeting_date}.")
    lines.append(
        "Cite a due date only if one is explicitly stated in the transcript;"
        ' otherwise write "not stated".'
    )
    return "\n".join(lines)


def build_summary_prompt(
    transcript: str,
    *,
    template: str,
    meeting_title: str | None = None,
    meeting_date: str | None = None,
) -> str:
    """The whole-meeting prompt for the architecture-summary document.

    ``template`` is the config-owned, complete prompt text
    (``llm.roles.extraction.arch_summary_prompt``) — composed verbatim with
    the meeting header and transcript, never reformatted or templated further.
    """
    return "\n\n".join(
        [
            template,
            _document_header(meeting_title, meeting_date),
            "Raw transcript:\n\n" + (transcript if transcript.strip() else "(none)"),
        ]
    )


def build_actions_prompt(
    transcript: str,
    *,
    template: str,
    meeting_title: str | None = None,
    meeting_date: str | None = None,
) -> str:
    """The whole-meeting prompt for the action-items document.

    ``template`` is the config-owned, complete prompt text
    (``llm.roles.extraction.action_items_prompt``) — composed verbatim with
    the meeting header and transcript, never reformatted or templated further.
    """
    return "\n\n".join(
        [
            template,
            _document_header(meeting_title, meeting_date),
            "Raw transcript:\n\n" + (transcript if transcript.strip() else "(none)"),
        ]
    )


def build_topics_prompt(
    transcript: str,
    *,
    template: str,
    meeting_title: str | None = None,
    meeting_date: str | None = None,
) -> str:
    """The whole-meeting prompt for the topics document (story 10.1).

    ``template`` is the config-owned, complete prompt text
    (``llm.roles.extraction.topics_prompt``) — composed verbatim with the
    meeting header and transcript, never reformatted or templated further.
    """
    return "\n\n".join(
        [
            template,
            _document_header(meeting_title, meeting_date),
            "Raw transcript:\n\n" + (transcript if transcript.strip() else "(none)"),
        ]
    )


def build_signals_prompt(
    transcript: str,
    *,
    template: str,
    meeting_title: str | None = None,
    meeting_date: str | None = None,
) -> str:
    """The whole-meeting prompt for the ranking-signals document (story 10.4).

    ``template`` is the config-owned, complete prompt text
    (``llm.roles.extraction.ranking_signals_prompt``) — composed verbatim with
    the meeting header
    and transcript, never reformatted or templated further, exactly as the
    three prompts above are.
    """
    return "\n\n".join(
        [
            template,
            _document_header(meeting_title, meeting_date),
            "Raw transcript:\n\n" + (transcript if transcript.strip() else "(none)"),
        ]
    )


def build_prompt(
    document_kind: str,
    transcript: str,
    *,
    template: str,
    meeting_title: str | None = None,
    meeting_date: str | None = None,
) -> str:
    """The prompt for one document kind. Raises on an unknown kind."""
    if document_kind == DOC_ARCH_SUMMARY:
        builder = build_summary_prompt
    elif document_kind == DOC_ACTION_ITEMS:
        builder = build_actions_prompt
    elif document_kind == DOC_TOPICS:
        builder = build_topics_prompt
    elif document_kind == DOC_RANKING_SIGNALS:
        builder = build_signals_prompt
    else:
        raise ValueError(
            f"unknown extraction document kind {document_kind!r} — expected one of"
            f" {', '.join(_PARSEABLE_DOCUMENT_KINDS)}"
        )
    return builder(
        transcript,
        template=template,
        meeting_title=meeting_title,
        meeting_date=meeting_date,
    )


# --- normalization ----------------------------------------------------------

# Every dash-like codepoint a summariser has been observed writing inside a
# timestamp range, plus the curly quotes that ride along with them. Normalizing
# before matching is a stated requirement, not parser sloppiness: `4:23‑5:12`
# with U+2011 is the same anchor as `4:23-5:12`, and a parser that saw only the
# ASCII spelling would contribute zero items for whole meetings.
_DASHES = "‐‑‒–—―−﹘﹣－"
_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
}
_NORMALIZE_MAP: dict[int, str] = {ord(ch): "-" for ch in _DASHES}
_NORMALIZE_MAP.update({ord(key): value for key, value in _QUOTES.items()})
_NORMALIZE_MAP[0x00A0] = " "  # non-breaking space
_NORMALIZE_MAP[0x202F] = " "  # narrow no-break space
_NORMALIZE_MAP[0x2007] = " "  # figure space


def normalize_text(text: str) -> str:
    """Fold the punctuation variants a summariser emits onto ASCII.

    NFKC first, so a fullwidth colon or a compatibility digit becomes the plain
    one, then the dash/quote/space table above. Nothing else is changed — the
    text still has to say what it said.
    """
    return unicodedata.normalize("NFKC", text).translate(_NORMALIZE_MAP)


# `D1`, `A12`, `R3`, `BR7`, `OQ4`, `OQ Q2`, and the action document's per-owner
# initials (`TG1`, `LW2`). Anchored on purpose: this matches a *whole* cell or
# a whole bullet marker, never an ID mentioned mid-sentence, which is what
# keeps a later section's reference to D1 from becoming a second artifact.
#
# Case-insensitive: a document writing `d1` is writing the same ID, and reading
# it as prose would contribute zero artifacts for that whole meeting — the §8
# shape. The prefix is upper-cased before it is mapped to a kind, so the
# vocabulary itself stays single-spelled.
_ITEM_ID = re.compile(
    r"^(?P<prefix>[A-Za-z]{1,4})\s*-?\s*(?:[Qq]\s*)?(?P<number>\d{1,3})$"
)

# The same shape at the head of a bullet, with its markdown emphasis attached.
_BULLET_ID = re.compile(
    r"^(?P<id>[*_`]*\s*[A-Za-z]{1,4}\s*-?\s*(?:[Qq]\s*)?\d{1,3}\s*[*_`]*)"
    r"\s*(?:[:.–\-]\s*)?(?P<rest>.*)$",
    re.S,
)

# A point in the meeting: `4:23` or `1:04:23`. Bounded so a bare `12:00` inside
# prose still matches (it is a timestamp there too) while `1.2:3` does not.
_TIMESTAMP = re.compile(r"(?<![\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?![\d:])")

# Markdown emphasis and code fencing around a cell's content.
_EMPHASIS = re.compile(r"^[*_`~\s]+|[*_`~\s]+$")

# A table separator row: `|---|:--:|`.
_SEPARATOR_ROW = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

# A bullet marker: `-`, `*`, `+`, or `1.` / `1)`.
_BULLET = re.compile(r"^\s*(?:[-*+]|\d{1,2}[.)])\s+")

# The field separator inside a bullet: a dash with space on both sides. A dash
# inside `[4:23-5:12]` has neither, so a range is never split.
_BULLET_FIELD = re.compile(r"\s+-\s+")

# An ATX heading.
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s*(.*?)\s*#*\s*$")

# A status cell. The token is matched by PREFIX — `Tentative* (ownership
# inferred)` counts as Tentative, exactly the way the puller's own
# `addActionCounts` reads the trailing Status cell — but the *cell* must be
# status-shaped: the token, optionally a bracketed qualifier, and nothing else
# of substance. A bare prefix match with no word boundary and no end anchor
# swallowed real decisions ("Open the firewall port for SFTP", "Risk register
# moves to Jira", "Assigned owners are tracked in the runbook"), excluded them
# from the title candidates, and titled the artifact from its context cell
# instead. Timestamps are stripped before the match so a Status column that
# fused its stamp in — `Confirmed - [7:47-8:24]` — is still read as a status.
_STATUS_CELL = re.compile(
    r"^[\[(*_\s]*(?:confirmed|assumed|open|risk|committed|assigned|tentative)\b"
    r"[*_\s]*(?:[(\[][^)\]]*[)\]])?[*_\s.;,:\-\[\]()]*$",
    re.I,
)

# Header labels that name the column carrying an item's own anchor. Read only
# to *find* that column; the parser never depends on a label existing.
_TIMESTAMP_HEADERS = ("timestamp", "time", "when", "stamp")

# Header labels that name the column carrying an action item's owner.
_OWNER_HEADERS = ("owner", "assignee", "who")

# A section heading (or an owner cell) that says nobody owns the item.
_UNOWNED_MARKERS = ("unowned", "unassigned", "needs an owner", "no owner")

# How many leading cells are scanned for the item ID. Real rows go ragged and a
# leading empty cell is common (`|  | D4 | ... |`); before this the row was
# dropped with no trace, which is the §8 shape at row granularity. Bounded so
# an ID *mentioned* deep in a wide row cannot be mistaken for the row's own.
_ID_SCAN_CELLS = 3

# The body written when a row carried nothing beyond its own title. Named
# rather than silently duplicating the title into the body: story 4.1 refused a
# blank body by name, and 4.3's reviewer must be able to tell "no detail was
# recorded" from "the detail is the title again".
NO_DETAIL_BODY = "No detail was recorded beyond the item text."

# Sections of the action document that are explicitly NOT action items. The
# prompt that produced them says so in as many words: work already finished is
# listed under "Reported done", and a pending decision or blocker under "Watch
# items". Matched on heading *text* — never on numbering — and a document with
# no such heading simply has no excluded rows.
_EXCLUDED_ACTION_SECTIONS = ("reported done", "watch item")

# Headings whose content the no-silent-zero check treats as a *target*: a
# populated one of these yielding nothing is the §8 failure shape. The action
# document needs no keyword list — every section of it except the two excluded
# above is a target, because its section headings are owner names.
_ARCH_TARGET_HEADINGS = ("decision", "summary")

# The architecture summary's executive-summary section, whose prose becomes the
# meeting's `summary` artifact (story 12.2). Matched on the two-word phrase and
# never on numbering, the same rule the rest of this parser follows: the three
# sampled spellings — ``# 1️⃣ Executive Summary``,
# ``## 1. Header & Executive Summary`` and ``# 1 Executive Summary`` — share
# exactly this substring and nothing else. A bare ``summary`` would also match
# ``Rebuilt meeting summary``, which is a different section reporting what
# happened in meeting order.
_EXECUTIVE_SUMMARY_HEADING = "executive summary"

# A topics response may drift in wording, but it must still identify itself as
# topical either in the section heading or through the configured table shape.
# This keeps useful headings such as "Discussion themes" while refusing a
# Decisions/Notes/task document whose T-id happens to look plausible.
_TOPIC_HEADING_MARKERS = ("topic", "topics", "theme", "themes")
_TOPIC_HEADING_NEGATIONS = ("no", "non", "not")

# Topic columns are an acceptance boundary, not fuzzy hints. A foreign column
# such as ``Topic owner`` or a fused ``Topic Gist`` must not make an unrelated
# document look like the configured topics shape.
_TOPIC_NAME_HEADERS = ("topic", "topic name", "theme", "subject")
_TOPIC_GIST_HEADERS = ("gist", "summary")
_TOPIC_TIMESTAMP_HEADERS = (
    "timestamp",
    "timestamps",
    "time",
    "when",
    "stamp",
    "stamps",
    "anchor",
    "anchors",
)

# Which ID prefixes become artifacts, per document. The architecture summary
# also carries an action-items table, but those are the same commitments the
# action document lists in full — counting both would duplicate every one of
# them, so the summary contributes decisions only.
_ARCH_PREFIX_KINDS = {"D": KIND_ADR}

# Which ID prefixes become topics in the topics document (story 10.1). Only
# `T`: a risk or question id that strays into a topics table is structure,
# never a topic.
_TOPIC_PREFIX_KINDS = {"T": KIND_TOPIC}

# Which ID prefixes become ranking signals in the ranking-signals document
# (story 10.4). The prefix decides the kind, not the section heading: a risk
# the model filed under "Open questions" is still a risk, and keying on the
# heading would make one drifted word relabel a whole table. An `A`- or
# `D`-prefixed row that strays into this document is a commitment or a
# decision belonging to another document, and is skipped as structure.
_SIGNAL_PREFIX_KINDS = {"R": KIND_RISK, "Q": KIND_QUESTION}

# The ranking-signals table's two persisted text columns, by header label.
# Exact labels, the topics precedent: a fuzzy match would let a foreign
# ``Risk owner`` column become the label a reader is shown.
_SIGNAL_LABEL_HEADERS = ("risk", "question", "open question", "issue", "concern")
_SIGNAL_DETAIL_HEADERS = ("detail", "details", "note", "notes", "context")

# How short and how complete a table row has to be to be read as a header row.
# A prose line that happens to contain a pipe must not be able to relabel a
# real table's columns.
_MAX_HEADER_CELL_CHARS = 40


@dataclass(frozen=True)
class ProposedArtifact:
    """One parsed item, in the vocabulary the `artifact` table stores.

    ``anchor_ms`` is the earliest `[m:ss]` timestamp the item carried, and it
    is what :func:`resolve_anchor` turns into the moment this artifact is
    FK-linked to. ``item_id`` is the document's own short ID (``D1``), kept so
    a proposal can be traced back to the row that produced it.
    """

    kind: str
    title: str
    body: str
    anchor_ms: int
    item_id: str
    layout: str
    # Who the action document says owns this item, or ``None`` for a decision
    # and for an item nobody owns. It reaches the artifact through the body on
    # both paths — see :func:`_owner_of`, which is what keeps an adopted item
    # (owner in the `## <Owner>` heading) and a generated one (owner in a table
    # column) indistinguishable in shape.
    owner: str | None = None
    # Every `[m:ss]` stamp the item carried, in written order (story 10.1).
    # Topics need every place they were discussed; the artifact kinds keep
    # citing `anchor_ms` alone.
    anchors_ms: tuple[int, ...] = ()


@dataclass(frozen=True)
class ParsedDocument:
    """One source document, parsed.

    ``populated_target_sections`` names the sections that plainly carried
    content — table rows or bullets under a decisions/actions heading. A
    document with a populated target section and no artifacts is the
    `retrieval-prior-art.md` §8 shape, and the stage logs it by name.

    ``summary`` is the architecture summary's executive-summary prose, verbatim
    (story 12.2), or ``None`` for every other document kind and for an
    architecture summary that carries no such section — including one whose
    section is present but empty. It is deliberately **not** a
    :class:`ProposedArtifact`: every one of those carries an ``anchor_ms``, and
    the parser raises when an item has none, because an unanchored item could
    never be cited. A summary has no anchor by definition, so giving it one
    would mean either a fabricated citation or an invariant that no longer
    means anything. A separate field keeps both true.
    """

    kind: str
    artifacts: tuple[ProposedArtifact, ...]
    layout: str
    populated_target_sections: tuple[str, ...]
    summary: str | None = None


def _clean(cell: str) -> str:
    """One table cell or bullet chunk, stripped of markdown decoration."""
    return _EMPHASIS.sub("", cell.replace("\\|", "|")).strip()


def _timestamps_ms(text: str) -> tuple[int, ...]:
    """Every parseable `m:ss` point in the text, in the order written.

    Point, range (`4:23-5:12`), bracketed, parenthesised, italicised and
    comma-list forms all reduce to the same thing once the dashes are ASCII: a
    sequence of `m:ss` spellings. An unparseable one (`99:99`) contributes
    nothing rather than raising — the item may carry a usable stamp beside it,
    and the caller decides what a stampless item means.
    """
    found: list[int] = []
    for match in _TIMESTAMP.finditer(text):
        try:
            found.append(parse_timestamp(match.group(1)))
        except TranscriptParseError:
            continue
    return tuple(found)


def _validated_topic_timestamps_ms(text: str, item_id: str) -> tuple[int, ...]:
    """Parse an authoritative topics timestamp cell without silent loss."""
    matches = list(_TIMESTAMP.finditer(text))
    stamps: list[int] = []
    for match in matches:
        try:
            stamps.append(parse_timestamp(match.group(1)))
        except TranscriptParseError as exc:
            raise ArtifactParseError(
                f"item {item_id} in the topics document has a malformed"
                f" Timestamps value: {text!r}"
            ) from exc
    residue = _TIMESTAMP.sub("", text)
    if not stamps or re.sub(r"[\s\[\]()*_,;.\-]", "", residue):
        raise ArtifactParseError(
            f"item {item_id} in the topics document has an empty or malformed"
            f" Timestamps value: {text!r}"
        )
    return tuple(stamps)


def _split_row(line: str) -> list[str] | None:
    """A markdown table row's cells, or ``None`` when the line is not one.

    Ragged rows are the norm in real output — the sampled executive-summary
    table runs two or three columns depending on the meeting — so cell *count*
    is never checked. What makes a row is the pipes.
    """
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if _SEPARATOR_ROW.match(stripped):
        return None
    body = stripped
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [_clean(cell) for cell in re.split(r"(?<!\\)\|", body)]


def _split_bullet(line: str) -> list[str] | None:
    """A bullet line's leading ID and the rest, or ``None``.

    The observed spelling is ``- **D1** – text``, with any dash variant, a
    colon, or nothing at all between the ID and the text. The ID has to come
    first: an ID appearing later in the line is a *reference* to an item defined
    elsewhere, and both prompts say later sections reference IDs rather than
    restate them.
    """
    if not _BULLET.match(line):
        return None
    rest = _BULLET.sub("", line, count=1).strip()
    match = _BULLET_ID.match(rest)
    if match is None:
        return None
    # A bullet's fields are separated by a spaced dash where it has fields at
    # all — `- **D1** - decision - context - Confirmed - [4:23]`. Splitting on
    # that gives the bullet layout the same cells the table layout has, which
    # is what makes the two layouts yield the same artifacts instead of one
    # of them yielding a single fused blob. A prose bullet with no spaced dash
    # simply stays one cell.
    rest = match.group("rest").strip()
    # The ID matcher consumes the first separator. If another separator
    # follows immediately, preserve the empty first field so topic parsing can
    # report a missing name instead of promoting the gist into its place.
    if rest.startswith("- "):
        rest = " " + rest
    return [_clean(match.group("id"))] + [
        _clean(cell) for cell in _BULLET_FIELD.split(rest)
    ]


def _is_bare_stamp(cell: str) -> bool:
    """Whether the cell is only a timestamp (bracketed, ranged, or listed)."""
    residue = _TIMESTAMP.sub("", cell)
    return not re.sub(r"[\s\[\]()*_,;.\-]", "", residue)


def _is_status_cell(cell: str) -> bool:
    """Whether the cell is a status mark rather than the item's own words.

    Timestamps are removed first, so a Status column that fused its stamp in
    (`Confirmed - [7:47-8:24]`, an observed real shape) is still a status.
    """
    return bool(_STATUS_CELL.match(_TIMESTAMP.sub("", cell)))


def _labelled(headers: Sequence[str] | None, markers: Sequence[str]) -> int | None:
    """The index of the first header whose label contains one of ``markers``."""
    if headers is None:
        return None
    for index, header in enumerate(headers):
        lowered = (header or "").casefold()
        if any(marker in lowered for marker in markers):
            return index
    return None


def _normalized_header_label(header: str) -> str:
    """A header label reduced for exact, punctuation-insensitive matching."""
    return " ".join(re.findall(r"[a-z0-9]+", (header or "").casefold()))


def _exact_labelled(
    headers: Sequence[str] | None, labels: Sequence[str]
) -> int | None:
    """The first header whose complete normalized label is allowed."""
    if headers is None:
        return None
    allowed = set(labels)
    for index, header in enumerate(headers):
        if _normalized_header_label(header) in allowed:
            return index
    return None


def _anchor_stamps(
    cells: Sequence[str],
    headers: Sequence[str] | None,
    raw_line: str,
    *,
    authoritative_topic_item_id: str | None = None,
) -> tuple[int, ...]:
    """The item's own timestamps, and where they were found.

    Scanning the whole row was wrong and quietly so: a Details cell reading
    "as agreed at [2:10]", or a Timing cell naming "the 9:00 standup", becomes
    the earliest stamp on the row, resolves to a real moment, and produces a
    confidently wrong citation — the one failure *no citation, no answer*
    exists to prevent. So the item's own timestamp cell is preferred, and the
    whole row is only the last resort:

    1. the cell the header row labels Timestamp/Time/When, when it carries one;
    2. otherwise a cell that is *nothing but* timestamps;
    3. otherwise the whole row, for a prose bullet or a headerless ragged row
       that has no separable stamp cell at all.
    """
    labelled = (
        _exact_labelled(headers, _TOPIC_TIMESTAMP_HEADERS)
        if authoritative_topic_item_id is not None
        else _labelled(headers, _TIMESTAMP_HEADERS)
    )
    if labelled is not None and authoritative_topic_item_id is not None:
        value = cells[labelled] if labelled < len(cells) else ""
        return _validated_topic_timestamps_ms(value, authoritative_topic_item_id)
    if labelled is not None and labelled < len(cells):
        stamps = _timestamps_ms(cells[labelled])
        if stamps:
            return stamps
    for cell in cells:
        if cell and _is_bare_stamp(cell):
            stamps = _timestamps_ms(cell)
            if stamps:
                return stamps
    return _timestamps_ms(raw_line)


def _owner_of(
    cells: Sequence[str], headers: Sequence[str] | None, section: str
) -> tuple[str | None, int | None]:
    """The action item's owner, and the cell it came from when it came from one.

    Two shapes carry the same fact. The real summariser puts the owner in the
    `## <Owner>` section heading; the generated prompt puts it in an Owner
    column. Reading only one of them would mean an adopted item arrives with no
    owner while a generated one has it — which breaks the story's convergence
    requirement outright. Both are read here, the column first because it is
    the more specific statement.
    """
    index = _labelled(headers, _OWNER_HEADERS)
    if index is not None and index < len(cells) and cells[index]:
        return _named_owner(cells[index]), index
    return _named_owner(section), None


def _named_owner(text: str) -> str | None:
    """A person's name, or ``None`` when the text says nobody owns the item."""
    owner = (text or "").strip().strip("*_`").strip()
    if not owner:
        return None
    lowered = owner.casefold()
    if any(marker in lowered for marker in _UNOWNED_MARKERS):
        return None
    return owner


def _find_item_id(cells: Sequence[str]) -> tuple[int, re.Match[str]] | None:
    """The cell holding the row's item ID, scanning past ragged leading cells."""
    for index, cell in enumerate(cells[:_ID_SCAN_CELLS]):
        match = _ITEM_ID.match(cell)
        if match is not None:
            return index, match
    return None


def _drop_index(values: Sequence[str] | None, index: int) -> list[str] | None:
    """``values`` without the element at ``index`` — used to keep header
    labels aligned with the cells they label once the ID cell is removed."""
    if values is None:
        return None
    return [value for position, value in enumerate(values) if position != index]


def _title_and_body(
    cells: Sequence[str],
    headers: Sequence[str] | None,
    owner_index: int | None = None,
) -> tuple[str, str]:
    """Pick the item's title out of its cells and render the rest as its body.

    The title is the first cell that is neither purely a timestamp nor a bare
    status — in both prompts' pinned shape that is the decision or the action
    itself. *First* rather than "the one the header calls Decision", because
    header labels drift and a drifting header must never be able to change
    which cell becomes a title; header labels are used for the body and nowhere
    else. It is also what makes the two layouts agree: a bullet's fields and a
    table row's cells are the same cells in the same order, so the same rule
    picks the same title out of either.
    """
    candidates = [
        (index, cell)
        for index, cell in enumerate(cells)
        if cell
        and len(cell) > 2
        and index != owner_index
        and not _is_bare_stamp(cell)
        and not _is_status_cell(cell)
    ]
    if candidates:
        index, title = candidates[0]
    else:
        # Nothing substantive: fall back to the first cell that is at least
        # *something* other than a timestamp, and to nothing at all when there
        # is not even that — a row carrying an ID and a stamp and no words is
        # a refusal, not an artifact titled "[4:23]".
        loose = [
            (position, cell)
            for position, cell in enumerate(cells)
            if cell and not _is_bare_stamp(cell)
        ]
        index, title = loose[0] if loose else (-1, "")
    lines: list[str] = []
    for position, cell in enumerate(cells):
        # The owner cell is omitted here and re-rendered once, canonically, by
        # the caller — otherwise a generated item would carry the owner twice
        # and an adopted one once.
        if not cell or position == index or position == owner_index:
            continue
        label = (
            headers[position]
            if headers is not None and position < len(headers) and headers[position]
            else None
        )
        lines.append(f"{label}: {cell}" if label else cell)
    return title.strip(), "\n".join(lines).strip()


def _topic_title_and_body(
    cells: Sequence[str], headers: Sequence[str] | None, item_id: str
) -> tuple[str, str]:
    """Read the topic name and gist as distinct, required fields.

    The configured table names both columns. Headerless tables and bullets use
    the prompt's pinned ordering: topic, gist, then timestamps. This stays
    separate from the artifact title heuristic because a two-character topic
    name is valid and neither required field may be synthesized from the
    other.
    """
    topic_index = _exact_labelled(headers, _TOPIC_NAME_HEADERS)
    gist_index = _exact_labelled(headers, _TOPIC_GIST_HEADERS)
    if topic_index is None or gist_index is None:
        topic_index, gist_index = 0, 1

    topic = cells[topic_index].strip() if topic_index < len(cells) else ""
    gist = cells[gist_index].strip() if gist_index < len(cells) else ""
    if not topic or _is_bare_stamp(topic):
        raise ArtifactParseError(
            f"item {item_id} in the topics document has no Topic value"
        )
    if not gist or _is_bare_stamp(gist):
        raise ArtifactParseError(
            f"item {item_id} in the topics document has no Gist value"
        )

    # The topic row has exactly two persisted text fields. Auxiliary model
    # bookkeeping (confidence, rank, notes) must not leak into the gist, and
    # drifted ``Summary`` must canonicalize to the same body as ``Gist``.
    return topic, f"Gist: {gist}"


def _signal_label_and_detail(
    cells: Sequence[str], headers: Sequence[str] | None, item_id: str
) -> tuple[str, str]:
    """Read a ranking signal's label and its detail (story 10.4).

    The label is a required field, not a heuristic title: migration 0018
    refuses a blank one, and `GET /moments/feed` drops an item whose reasons
    are all invalid — so a signal that reached the table with nothing to say
    would be a feed row that silently vanishes. Refusing it here means the
    stage names the row instead.

    The detail is genuinely optional. A risk stated in five words carries no
    elaboration, and synthesizing one from the label would be the parser
    writing rather than reporting.

    Labelled columns win; a headerless table or a bullet falls back to the
    prompt's pinned ordering — label, detail, then timestamps — which is the
    same rule :func:`_topic_title_and_body` applies.
    """
    label_index = _exact_labelled(headers, _SIGNAL_LABEL_HEADERS)
    detail_index = _exact_labelled(headers, _SIGNAL_DETAIL_HEADERS)
    if label_index is None:
        label_index = 0
    if detail_index is None or detail_index == label_index:
        detail_index = label_index + 1

    label = cells[label_index].strip() if label_index < len(cells) else ""
    detail = cells[detail_index].strip() if detail_index < len(cells) else ""
    if not label or _is_bare_stamp(label):
        raise ArtifactParseError(
            f"item {item_id} in the {DOC_RANKING_SIGNALS} document has no"
            " risk/question text, only bookkeeping"
        )
    # A trailing timestamp column read as the detail is bookkeeping, not
    # context: the anchor is already carried separately.
    if _is_bare_stamp(detail):
        detail = ""
    return label, detail


def signal_detail(artifact: ProposedArtifact) -> str:
    """The detail column of a parsed ranking signal, or the empty string.

    :class:`ProposedArtifact` substitutes :data:`NO_DETAIL_BODY` for an empty
    body, because an *artifact* with a blank body is a row story 4.1 refused
    by name. A ranking signal is not an artifact and an absent detail is
    ordinary, so the placeholder is unwound here rather than persisted —
    `ranking_signal.detail` stores `''`, and no reader has to know the
    sentence "No detail was recorded beyond the item text." is a sentinel.
    """
    return "" if artifact.body == NO_DETAIL_BODY else artifact.body


def _truncate_title(title: str) -> str:
    if len(title) <= _MAX_TITLE_CHARS:
        return title
    cut = title[:_MAX_TITLE_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or title[:_MAX_TITLE_CHARS]) + "…"


def _section_is_excluded(heading: str, document_kind: str) -> bool:
    if document_kind != DOC_ACTION_ITEMS:
        return False
    lowered = heading.casefold()
    return any(marker in lowered for marker in _EXCLUDED_ACTION_SECTIONS)


def _section_is_target(heading: str, document_kind: str) -> bool:
    if not heading or _section_is_excluded(heading, document_kind):
        return False
    if document_kind == DOC_ACTION_ITEMS:
        # Every `## <Owner>` section of the action document is a target: the
        # heading is a person's name, so there is no keyword to match on, and
        # the two non-action sections are already excluded above.
        return True
    if document_kind == DOC_TOPICS:
        # Every heading is a target for the topics document too (story
        # 10.1): real output drifts ("Discussion themes"), so a keyword
        # match would re-create the §8 shape — and this is what lets the
        # shared zero-artifact default document parse to zero topics in
        # every existing worker test. Strictness lives in the T-id/anchor
        # rules and the stage's zero-topics signal, which is keyed on
        # meeting content, not on section names.
        return True
    if document_kind == DOC_RANKING_SIGNALS:
        # Every heading is a target here for the same reason (story 10.4):
        # real output drifts ("Concerns", "Things we did not settle"), and a
        # keyword list would re-create the §8 shape — a document whose rows
        # plainly carry risks parsing to an honest-looking zero because its
        # heading used a synonym. Strictness lives in the R/Q prefix rule and
        # in the required non-empty label, not in the section name.
        return True
    lowered = heading.casefold()
    return any(marker in lowered for marker in _ARCH_TARGET_HEADINGS)


def _has_topic_semantics(
    heading: str, headers: Sequence[str] | None
) -> bool:
    words = re.findall(r"[a-z0-9]+", heading.casefold())
    for index, word in enumerate(words):
        if word not in _TOPIC_HEADING_MARKERS:
            continue
        if index and words[index - 1] in _TOPIC_HEADING_NEGATIONS:
            continue
        return True
    topic_index = _exact_labelled(headers, ("topic",))
    gist_index = _exact_labelled(headers, ("gist",))
    return (
        topic_index is not None
        and gist_index is not None
        and topic_index != gist_index
    )


def _kind_for(prefix: str, document_kind: str) -> str | None:
    """The artifact kind this item ID becomes, or ``None`` for "not an artifact".

    Risks (``R``), open questions (``O``/``OQ``) and business rules (``BR``)
    are real items with real IDs, and the parser recognizes them so their rows
    are not mistaken for prose — but `artifact.kind` admits only `adr` and
    `action-item` today, and widening it is a later Epic 4 story.
    """
    if document_kind == DOC_ACTION_ITEMS:
        # The action document is action items throughout; its IDs are `A1` in
        # generated output and per-owner initials in some real ones, so the
        # prefix is not what decides the kind there — the document is.
        return KIND_ACTION_ITEM
    if document_kind == DOC_TOPICS:
        return _TOPIC_PREFIX_KINDS.get(prefix)
    if document_kind == DOC_RANKING_SIGNALS:
        return _SIGNAL_PREFIX_KINDS.get(prefix)
    return _ARCH_PREFIX_KINDS.get(prefix)


def _is_header_row(cells: Sequence[str]) -> bool:
    return (
        len(cells) > 1
        and all(cell for cell in cells)
        and all(len(cell) <= _MAX_HEADER_CELL_CHARS for cell in cells)
    )


def parse_extraction_document(text: str, document_kind: str) -> ParsedDocument:
    """Parse one summariser document, or raise saying exactly what was wrong.

    Serves both paths: the bytes may be a file the drop carried or a reply the
    model just produced, and neither gets a looser reading than the other.

    Raises :class:`ArtifactParseError` when an item that would become an
    artifact carries no `[m:ss]` anchor — an unanchored decision cannot be
    cited and must not be quietly dropped — and when the document carries no
    recognizable structure at all.
    """
    if document_kind not in _PARSEABLE_DOCUMENT_KINDS:
        raise ValueError(
            f"unknown extraction document kind {document_kind!r} — expected one of"
            f" {', '.join(_PARSEABLE_DOCUMENT_KINDS)}"
        )
    normalized = normalize_text(text)
    if not normalized.strip():
        raise ArtifactParseError(
            f"the {document_kind} document is empty — nothing to parse"
        )

    section = ""
    headers: list[str] | None = None
    populated: list[str] = []
    # Keyed on (section, item_id) for the action document: real ones use
    # per-owner ID prefixes, so two owners can each legitimately carry an `A1`,
    # and a document-global key silently dropped the second owner's whole set —
    # the §8 shape. The architecture summary numbers its decisions once for the
    # whole document, so its key stays the ID alone — and so does the topics
    # document (story 10.1), whose T-ids are document-global.
    seen_ids: set[tuple[str, str]] = set()
    artifacts: list[ProposedArtifact] = []
    layouts: set[str] = set()
    # A table or bullet is only a recognizable document structure when it is
    # under one of this document kind's target sections.  In particular, an
    # unrelated ``# Notes`` table must not turn an architecture-summary into a
    # successful empty parse.  Action-item owner headings deliberately remain
    # free-form through ``_section_is_target``.
    target_structure_seen = False
    # Story 12.2: the executive-summary section's own lines, collected as they
    # are read. The section runs from its heading to the NEXT HEADING OF ANY
    # LEVEL — not to the next heading of the same or shallower level — because
    # real documents mix levels across sections (`# 1️⃣ Executive Summary` is
    # followed by `## 3. Decisions made`), so a same-or-shallower rule would
    # swallow the decisions table into the summary body.
    summary_lines: list[str] = []
    in_summary = False

    for raw_line in normalized.splitlines():
        heading = _HEADING.match(raw_line)
        if heading is not None:
            section = _clean(heading.group(2))
            headers = None
            in_summary = document_kind == DOC_ARCH_SUMMARY and (
                _EXECUTIVE_SUMMARY_HEADING in section.casefold()
            )
            continue
        # Collected IN ADDITION TO the per-line handling below, never instead
        # of it. `_ARCH_TARGET_HEADINGS` contains "summary", so this section is
        # already a *target*: its bullets mark it populated and feed the
        # no-silent-zero signal, and a stray `D1` row inside it already becomes
        # an ADR. Consuming the section as prose and skipping the rest of the
        # loop would change both of those quietly. Appending here and then
        # falling through means the only observable difference this story makes
        # to a parse is a field that used to be absent.
        if in_summary:
            summary_lines.append(raw_line)
        if not raw_line.strip():
            continue

        layout = LAYOUT_TABLE
        cells = _split_row(raw_line)
        if cells is None:
            layout = LAYOUT_BULLET
            cells = _split_bullet(raw_line)
        if cells is None:
            continue
        if _section_is_target(section, document_kind):
            target_structure_seen = True

        found = _find_item_id(cells)
        if found is None:
            # A header row is the ordinary shape of this: `| ID | Action | …`.
            # Remember it so the body can label its cells, and move on. A bare
            # header is not *content*, so it does not make its section
            # populated — a table with a header and no rows under it is an
            # honest "nothing here", not a silent zero.
            if layout == LAYOUT_TABLE and _is_header_row(cells):
                # A short data row can satisfy the deliberately broad generic
                # header heuristic. For topics, only the first row or a row
                # that itself establishes topic semantics may replace the
                # remembered header; otherwise a contentful foreign row would
                # be repeatedly reclassified as another header and parse as
                # an honest zero.
                if (
                    document_kind != DOC_TOPICS
                    or headers is None
                    or _has_topic_semantics(section, cells)
                ):
                    headers = list(cells)
                    continue
        if document_kind == DOC_TOPICS and found is None and not _has_topic_semantics(
            section, headers if layout == LAYOUT_TABLE else None
        ):
            raise ArtifactParseError(
                f"contentful row under section {section!r} in the topics document"
                " has no topic semantics in either the heading or Topic/Gist"
                " table columns"
            )
        if _section_is_target(section, document_kind) and section not in populated:
            populated.append(section)
        if found is None:
            continue

        id_index, id_match = found
        prefix = id_match.group("prefix").upper()
        item_id = f"{prefix}{id_match.group('number')}"
        if document_kind == DOC_TOPICS and not _has_topic_semantics(
            section, headers if layout == LAYOUT_TABLE else None
        ):
            raise ArtifactParseError(
                f"item {item_id} in the topics document appears under section"
                f" {section!r} without topic semantics in either the heading or"
                " Topic/Gist table columns"
            )
        kind = _kind_for(prefix, document_kind)
        if kind is None or _section_is_excluded(section, document_kind):
            # A recognized item that is not an artifact: a risk, an open
            # question, or a row under "Reported done". Counted as structure,
            # never as a proposal — and so never as a missing anchor either.
            continue
        dedup_key = (section if document_kind == DOC_ACTION_ITEMS else "", item_id)
        if dedup_key in seen_ids:
            if document_kind in (DOC_TOPICS, DOC_RANKING_SIGNALS):
                item_name = (
                    "topic"
                    if document_kind == DOC_TOPICS
                    else "ranking signal"
                )
                raise ArtifactParseError(
                    f"duplicate {item_name} ID {item_id} in the {document_kind}"
                    f" document; each {item_name} ID must be defined exactly once"
                )
            # Both prompts tell the model to reference an item's ID in later
            # sections rather than restate it, and real documents restate some
            # anyway. First definition wins; a restatement is not a second
            # decision.
            continue

        # The ID cell is removed from the cells being described, and from the
        # header labels with it, so a ragged row whose ID is not in column one
        # still labels its remaining cells correctly.
        rest = [cell for position, cell in enumerate(cells) if position != id_index]
        rest_headers = (
            _drop_index(headers, id_index)
            if headers is not None and layout == LAYOUT_TABLE
            else None
        )
        owner, owner_index = (
            _owner_of(rest, rest_headers, section)
            if document_kind == DOC_ACTION_ITEMS
            else (None, None)
        )
        stamps = _anchor_stamps(
            rest,
            rest_headers,
            raw_line,
            authoritative_topic_item_id=(
                item_id if document_kind == DOC_TOPICS else None
            ),
        )
        if not stamps:
            raise ArtifactParseError(
                f"item {item_id} in the {document_kind} document carries no [m:ss]"
                f" anchor, so it could never be cited: {raw_line.strip()[:200]!r}"
            )
        if document_kind == DOC_TOPICS:
            title, body = _topic_title_and_body(rest, rest_headers, item_id)
        elif document_kind == DOC_RANKING_SIGNALS:
            title, body = _signal_label_and_detail(rest, rest_headers, item_id)
        else:
            title, body = _title_and_body(rest, rest_headers, owner_index)
        if not title:
            raise ArtifactParseError(
                f"item {item_id} in the {document_kind} document has no text beyond"
                f" its ID: {raw_line.strip()[:200]!r}"
            )
        if owner is not None:
            # One canonical owner line, whichever shape it arrived in.
            body = f"Owner: {owner}\n{body}".strip()
        seen_ids.add(dedup_key)
        layouts.add(layout)
        artifacts.append(
            ProposedArtifact(
                kind=kind,
                title=_truncate_title(title),
                body=body or NO_DETAIL_BODY,
                # The earliest stamp is the anchor: a range `4:23-5:12` is
                # anchored where the discussion started, and a comma list
                # `(4:26, 5:08, 6:04)` at its first mention.
                anchor_ms=min(stamps),
                item_id=item_id,
                layout=layout,
                owner=owner,
                # Story 10.1: every stamp, in written order — the topics
                # pass builds one mention per containing moment from these.
                anchors_ms=stamps,
            )
        )

    if not target_structure_seen:
        raise ArtifactParseError(
            f"the {document_kind} document has neither a markdown table row nor a"
            " bullet list in a recognized target section — neither known layout"
            " matched"
        )

    if not layouts:
        resolved_layout = LAYOUT_NONE
    elif len(layouts) == 1:
        resolved_layout = next(iter(layouts))
    else:
        resolved_layout = LAYOUT_MIXED
    return ParsedDocument(
        kind=document_kind,
        artifacts=tuple(artifacts),
        layout=resolved_layout,
        populated_target_sections=tuple(populated),
        # Stripped only at the ends, so the prose keeps its own paragraph
        # breaks and bullet shape. A section that carried nothing but blank
        # lines collapses to `""` and becomes `None`: a document that plainly
        # has no executive summary must yield no summary artifact, and an empty
        # one is that case rather than an empty summary worth storing.
        summary=("\n".join(summary_lines).strip() or None),
    )


# Header labels whose cell is timestamp bookkeeping rather than gist text.
_GIST_SKIP_LABELS = ("timestamp", "time", "when", "stamp")


def topic_gist(artifact: ProposedArtifact) -> str:
    """The topic's one-line gist, out of the parsed body (story 10.1).

    The body is the row's remaining cells — labelled from the header row
    when one exists — which for the pinned topics table is the gist plus the
    timestamps cell. The stamps are already carried by ``anchors_ms`` and
    the mentions built from it, so repeating them inside the stored gist
    would be noise: a labelled Gist cell is unwrapped, timestamp bookkeeping
    is dropped, and whatever remains joins into one line. A row that carried
    no words beyond its name keeps the parser's named no-detail sentence.
    """
    lines: list[str] = []
    for line in artifact.body.splitlines():
        text = line.strip()
        if not text or _is_bare_stamp(text):
            continue
        label, sep, value = text.partition(":")
        if sep:
            lowered = label.strip().casefold()
            if lowered == "gist" and value.strip():
                text = value.strip()
            elif any(
                marker in lowered for marker in _GIST_SKIP_LABELS
            ) and _is_bare_stamp(value):
                continue
        lines.append(text)
    return " ".join(lines) or NO_DETAIL_BODY


# --- anchoring --------------------------------------------------------------


def resolve_anchor(anchor_ms: int, moments: Sequence[MomentLike]) -> UUID:
    """The id of the moment containing ``anchor_ms``.

    Containment, not similarity. Moments tile the meeting contiguously and
    never overlap (`pipeline/moments.py`), so "which moment covers this
    instant" is single-valued, and the rule is the one `plan_moments` itself
    uses to assign a segment to a span: the greatest ``start_ms <= t``,
    half-open ``[start, next_start)``.

    Gaps exist only before the first moment and after the last ``end_ms``. An
    anchor landing in one raises :class:`AnchorResolutionError` rather than
    snapping to the nearest moment — snapping would manufacture a citation the
    timeline does not contain.
    """
    ordered = sorted(moments, key=lambda moment: moment.start_ms)
    if not ordered:
        raise AnchorResolutionError(
            f"anchor {_span(anchor_ms)} cannot be resolved: the meeting has no moments"
        )
    first_start = ordered[0].start_ms
    last_end = max(moment.end_ms for moment in ordered)
    if anchor_ms < first_start or anchor_ms > last_end:
        raise AnchorResolutionError(
            f"anchor {_span(anchor_ms)} ({anchor_ms} ms) falls outside the meeting's"
            f" moment span {_span(first_start)}-{_span(last_end)}"
            f" ({first_start}-{last_end} ms)"
        )
    chosen = ordered[0]
    for moment in ordered:
        if moment.start_ms <= anchor_ms:
            chosen = moment
        else:
            break
    if anchor_ms > chosen.end_ms:
        # The greatest `start_ms <= t` is the containing moment only *because*
        # moments tile contiguously. Asserted rather than assumed: if the
        # tiling ever develops a hole, this picks the moment before the hole
        # and would cite an instant that moment does not cover.
        raise AnchorResolutionError(
            f"anchor {_span(anchor_ms)} ({anchor_ms} ms) falls in a gap between"
            f" moments: the nearest preceding moment {chosen.id} spans"
            f" {_span(chosen.start_ms)}-{_span(chosen.end_ms)}"
            f" ({chosen.start_ms}-{chosen.end_ms} ms) and does not contain it"
        )
    return chosen.id
