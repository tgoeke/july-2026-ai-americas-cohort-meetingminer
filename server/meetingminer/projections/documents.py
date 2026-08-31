"""Extraction documents in the search projection — indexed without the gate.

AD-4's publish gate refuses any *artifact* that is not ``published``, and this
module is the first deliberate exception to it (owner decision 2026-08-31,
recorded in AD-4). Every extraction document is indexed as soon as it is stored,
approved or not, because the run whose text somebody needs to read is exactly
the run that yielded nothing worth approving — gating documents behind approval
would withhold them in precisely the case they exist for. Story 12.1 stores the
text on the ``extraction_source`` row; this module turns that row into an
indexed record, and :mod:`meetingminer.projections.search` writes it.

Pure by construction, like :mod:`publish_gate`: no ``meilisearch``, no
``neo4j``, no ``psycopg``. The row comes from :mod:`evidence`, the store call
lives in :mod:`search`, and everything this exception has to be *careful* about
is here, where a test can hold it without standing a store up.

**The exception is declared, not carved.** ``publish_gate`` holds
:data:`~meetingminer.projections.publish_gate.UNGATED_INDEXED_ROW_TYPES`, a
mapping of row type to the reason it was granted, and this module reads its
permission out of it at import (:data:`GATE_EXCEPTION_REASON`). So the gate
remains the one place that says who may skip it, a second row type joining is
an entry rather than a second bypass, and deleting the entry breaks this path
by name instead of leaving a silent hole. Story 12.5 — artifacts indexed before
publish — is the second entry, and it is genuinely citable where a document is
not; the declaration keeps those separate facts separate.

Two constraints ride with the exception. Neither is a polish item; both follow
from invariants already in force.

**The exception is to reach, never to legibility.** AD-18 forbids unreviewed
output that reads the same as reviewed output. So the record carries its review
status *in itself*, through the generic marking in
:mod:`meetingminer.projections.review`: ``reviewState``, ``authorship``,
``reviewLabel`` and ``citable``, refused by
:func:`assert_carries_review_label` if any is lost. A surface that renders a
document reads the label off the record rather than knowing to add it, which is
what keeps the labelling from depending on each renderer remembering. The
marking is generic because the obligation is: a document has no lifecycle and
reports :data:`~meetingminer.projections.review.NO_LIFECYCLE`, while an
artifact indexed before publish reports whichever state it is actually in — one
mechanism, two rules about what a row may report.

**A document is never a citation target.** It is a claim *about* evidence, not
evidence: citing it would establish that the model said something, not that the
meeting did — the circularity the publish gate exists to prevent. So the record
carries no ``momentId``, no ``momentIds``, and no other field the citation path
could resolve (:data:`FORBIDDEN_CITATION_KEYS`, enforced by
:func:`assert_not_citable`). Its content reaches an answer only through the
moments its individual claims anchor to (AD-6) — which in practice is the
artifacts parsed out of it, each already anchored to a moment and already
gated. Unanchored prose stays readable and findable without becoming citable.

**The indexed identity is a build decision, stated here rather than inferred.**
``chunking.py`` keys a chunk on its first transcript segment's UUID (AD-6), and
a document has no transcript segment. It is not citable, so nothing forces the
choice — and an unstated choice is one a later reader has to reverse-engineer.
The choice is: **one indexed record per ``extraction_source`` row, keyed on
that row's own UUID, with the document text unchunked.** Chunking exists to
make a passage citable at speaker-turn granularity and to bound what an
embedder is handed; a document is never cited and this index carries no
vectors, so sub-document addressing would buy nothing and would invent a second
id space (``sourceId#seq``) that a re-extraction renumbers — the exact failure
``chunking.py`` refuses for chunks. Keyed on the row, the indexed identity is a
pure function of Postgres: ``extraction_source`` carries
``UNIQUE (meeting_id, kind)`` and a rerun upserts that row rather than
inserting a second, so a re-extraction *replaces* its record instead of
accumulating one per run, and ``rebuild`` converges on exactly the rows
Postgres holds. :func:`document_id` is the whole of it, and
``test_projections_documents.py`` pins it.
"""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from meetingminer.projections.evidence import ExtractionDocumentRow
from meetingminer.projections.publish_gate import require_ungated
from meetingminer.projections.review import (
    MACHINE,
    NO_LIFECYCLE,
    REVIEW_KEYS,
    ReviewMarkingRefused,
    apply_marking,
    assert_carries_marking,
    marking,
)

# The Meilisearch index extraction documents land in. A third index rather than
# a corner of `artifacts`: that one is filtered to `state = 'published'` by
# every query that reads it (story 4.4), and a document has no lifecycle state
# at all — putting the two in one index would mean either weakening that filter
# or inventing a lifecycle for documents that nothing in Postgres backs.
DOCUMENTS_INDEX = "documents"

# This module's row type, and the permission it reads out of the gate.
#
# Asserted at import rather than assumed: this module writes rows into a store
# without passing the publish gate, and the gate is where that permission is
# recorded. Removing the declaration makes importing this module a named
# failure, which is the point — a bypass nobody can find is the failure mode a
# declaration exists to prevent.
ROW_TYPE = "extraction-document"
GATE_EXCEPTION_REASON = require_ungated(ROW_TYPE)

# What every document record says about its own review status.
#
# `NO_LIFECYCLE`, not `'extracted'`: an artifact sitting at `extracted` is
# awaiting a human, while a document is not waiting for anything — nothing
# approves an extraction document, because there is no lifecycle behind it to
# move through. `citable=False` in every state, which for a document means
# every state there is (AD-6).
MARKING = marking(
    review_state=NO_LIFECYCLE,
    authorship=MACHINE,
    citable=False,
    subject="extraction output",
)

# Kept as module constants because they are what consumers import — the api's
# document hit, story 12.1's endpoint and the tests all read these rather than
# re-deriving a sentence, so two surfaces cannot describe one document
# differently.
REVIEW_STATE = MARKING.review_state
AUTHORSHIP = MARKING.authorship
REVIEW_LABEL = MARKING.review_label

# Field names the citation path resolves. A document record may carry none of
# them: `momentId`/`momentIds` are what `api/search.py` and
# `projections/query.py` read a citation out of, and `artifactId` is what the
# published-artifact lane resolves through its own source moment. A record
# carrying any of these would put a document one field away from being cited.
FORBIDDEN_CITATION_KEYS: frozenset[str] = frozenset(
    {"momentId", "momentIds", "artifactId", "segmentIds", "startMs", "endMs"}
)


class DocumentRecordRefused(ReviewMarkingRefused):
    """A document record was built in a shape this module forbids.

    A named refusal, not a bug: indexing a document without its unreviewed
    label is an AD-18 violation, and emitting a citation field on one would
    make a claim about evidence citable as evidence (AD-6). Either is refused
    before a store sees it.

    A subclass of the generic :class:`ReviewMarkingRefused` so a caller can
    catch "this row cannot say whether anybody reviewed it" across every row
    type, while this module's own refusals stay distinguishable.
    """


def document_id(row: ExtractionDocumentRow) -> str:
    """The indexed identity of one extraction document.

    The ``extraction_source`` row's own Postgres UUID, verbatim — the build
    decision this module's docstring states. Meilisearch restricts document ids
    to ``[A-Za-z0-9_-]``, which a hyphenated UUID satisfies, so the row id
    travels into the index unencoded exactly as a moment id does.
    """
    return str(row.id)


def assert_carries_review_label(record: Mapping[str, Any]) -> None:
    """Refuse a record that does not state it is unreviewed and machine-written.

    The **document's own** rule, layered on the generic one. `review.py` checks
    that a record can say *something* explicable about its review status; this
    checks that a document says the only thing a document may say. An artifact
    indexed before publish passes the first and would rightly fail this one,
    which is why the two are separate functions rather than one.
    """
    missing = [key for key in REVIEW_KEYS if key not in record]
    if missing:
        raise DocumentRecordRefused(
            "an extraction-document record is missing "
            + ", ".join(repr(key) for key in missing)
            + " — a document is indexed without passing the publish gate, so it"
            " must carry its unreviewed, machine-written status in the record"
            " itself (AD-4's exception, AD-18)"
        )
    # The generic guard first: a state this system cannot explain to a reader
    # is refused before the document-specific check narrows it further.
    try:
        assert_carries_marking(record)
    except ReviewMarkingRefused as exc:
        raise DocumentRecordRefused(str(exc)) from exc
    if record["reviewState"] != REVIEW_STATE or record["authorship"] != AUTHORSHIP:
        raise DocumentRecordRefused(
            f"an extraction-document record claims reviewState"
            f" {record['reviewState']!r}/authorship {record['authorship']!r};"
            f" the only values a document may carry are {REVIEW_STATE!r} and"
            f" {AUTHORSHIP!r} — nothing approves an extraction document (AD-18)"
        )
    if record["reviewLabel"] != REVIEW_LABEL:
        raise DocumentRecordRefused(
            "an extraction-document record carries reviewLabel"
            f" {record['reviewLabel']!r}; the only label a document may carry"
            f" is {REVIEW_LABEL!r} — the sentence a surface renders lives in"
            " the record, so accepting a merely nonblank contradiction would"
            " let it read as reviewed output (AD-18)"
        )
    if record["citable"] is not False:
        raise DocumentRecordRefused(
            "an extraction-document record claims citable"
            f" {record['citable']!r} — a document is a claim about evidence,"
            " never evidence, and is never a citation target (AD-6)"
        )


def assert_not_citable(record: Mapping[str, Any]) -> None:
    """Refuse a record carrying any field the citation path could resolve."""
    offending = sorted(FORBIDDEN_CITATION_KEYS & set(record))
    if offending:
        raise DocumentRecordRefused(
            "an extraction-document record carries "
            + ", ".join(repr(key) for key in offending)
            + " — a document is never a citation target, so its record may name"
            " no moment and no artifact; its content reaches an answer only"
            " through the moments its individual claims anchor to (AD-6)"
        )


def document_record(
    row: ExtractionDocumentRow,
    *,
    meeting_id: UUID,
    corpus: str,
    meeting_title: str | None,
    source_id: str,
) -> dict[str, Any]:
    """The Meilisearch document for one retained extraction document.

    ``text`` is the markdown exactly as it was stored — never re-rendered,
    re-wrapped or trimmed — so the index matches what the reader will be shown
    and what the parser actually read.

    Both guards run before the record is returned, so a caller cannot hand a
    store an unlabelled or citation-bearing document even by building the dict
    itself and calling this to check it.
    """
    if row.text is None:
        raise DocumentRecordRefused(
            f"extraction_source {row.id} ({row.kind}) has no retained text —"
            " a run that predates story 12.1 retention has nothing to index,"
            " and indexing it as an empty document would make 'nothing was"
            " kept' read as 'nothing was written' (AD-18)"
        )
    record: dict[str, Any] = {
        # The `extraction_source` row's UUID, verbatim. See `document_id`.
        "id": document_id(row),
        "meetingId": str(meeting_id),
        "corpus": corpus,
        "title": meeting_title or "",
        "sourceId": source_id,
        # The markdown as stored. Unchunked, by the build decision above.
        "text": row.text,
        "kind": row.kind,
        "origin": row.origin,
        # Provenance the reader needs to weigh the text: which model and which
        # prompt wrote it. Both NULL for an adopted document, whose summariser
        # this side never observed.
        "model": row.model,
        "promptHash": row.prompt_hash,
        "promptVersion": row.prompt_version,
        # What the parse of this document yielded. `itemCount` 0 on a document
        # that plainly carries content is the named signal story 12.1 keeps,
        # and it is the case this whole exception exists for — so it is in the
        # record rather than only in Postgres.
        "layout": row.layout,
        "itemCount": row.item_count,
        "artifactCount": row.artifact_count,
        "byteSize": row.byte_size,
        # The row version Postgres and the API compare after ranking. A rerun
        # preserves this record's UUID, so identity alone cannot distinguish an
        # old indexed body from the replacement text now in the database.
        "sha256": row.sha256,
    }
    # AD-18 and AD-6, in the record itself, through the generic marking: the
    # state a reader needs, who wrote it, the sentence to render, and whether
    # it may be cited — the last stated rather than merely implied by the
    # absence of a moment id, so a consumer reading this index can refuse to
    # cite without knowing the architecture.
    apply_marking(record, MARKING)
    assert_carries_review_label(record)
    assert_not_citable(record)
    return record
