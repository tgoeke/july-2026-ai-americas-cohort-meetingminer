"""Extraction documents in the search projection — the one exception to the gate.

AD-4's publish gate refuses anything that is not ``published``, and this module
is the single deliberate exception to it (owner decision 2026-08-31, recorded
in AD-4). Every extraction document is indexed as soon as it is stored,
approved or not, because the run whose text somebody needs to read is exactly
the run that yielded nothing worth approving — gating documents behind approval
would withhold them in precisely the case they exist for. Story 12.1 stores the
text on the ``extraction_source`` row; this module turns that row into an
indexed record, and :mod:`meetingminer.projections.search` writes it.

Pure by construction, like :mod:`publish_gate`: no ``meilisearch``, no
``neo4j``, no ``psycopg``. The row comes from :mod:`evidence`, the store call
lives in :mod:`search`, and everything this exception has to be *careful* about
is here, where a test can hold it without standing a store up.

Two constraints ride with the exception. Neither is a polish item; both follow
from invariants already in force.

**The exception is to reach, never to legibility.** AD-18 forbids unreviewed
output that reads the same as reviewed output. So the record carries its
unreviewed, machine-written status *in itself* — :data:`REVIEW_STATE`,
:data:`AUTHORSHIP` and the human sentence :data:`REVIEW_LABEL` are written onto
every document, and :func:`assert_carries_review_label` refuses one that lost
them. A surface that renders a document reads the label off the record rather
than knowing to add it, which is what keeps the labelling from depending on
each renderer remembering.

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

# The Meilisearch index extraction documents land in. A third index rather than
# a corner of `artifacts`: that one is filtered to `state = 'published'` by
# every query that reads it (story 4.4), and a document has no lifecycle state
# at all — putting the two in one index would mean either weakening that filter
# or inventing a lifecycle for documents that nothing in Postgres backs.
DOCUMENTS_INDEX = "documents"

# The status every record carries, and the sentence a surface renders.
#
# `review_state` is a closed value a filter can pin; `authorship` says who
# wrote it; `review_label` is the words. All three, not one: a machine-written
# document that a human later reads is still unreviewed, and a filter on a slug
# and a sentence for a person are different jobs. AD-18 is satisfied by the
# sentence being *in the record* — a renderer displays what it was given rather
# than being trusted to remember to add it.
REVIEW_STATE = "unreviewed"
AUTHORSHIP = "machine"
REVIEW_LABEL = (
    "Unreviewed — machine-written extraction output. No human approved this"
    " text, and it is not citable evidence."
)

# The record keys that state the above. Named as a set so the guard below and
# the test that pins it read the same list.
REVIEW_KEYS: tuple[str, ...] = ("reviewState", "authorship", "reviewLabel", "citable")

# Field names the citation path resolves. A document record may carry none of
# them: `momentId`/`momentIds` are what `api/search.py` and
# `projections/query.py` read a citation out of, and `artifactId` is what the
# published-artifact lane resolves through its own source moment. A record
# carrying any of these would put a document one field away from being cited.
FORBIDDEN_CITATION_KEYS: frozenset[str] = frozenset(
    {"momentId", "momentIds", "artifactId", "segmentIds", "startMs", "endMs"}
)


class DocumentRecordRefused(RuntimeError):
    """A document record was built in a shape this module forbids.

    A named refusal, not a bug: indexing a document without its unreviewed
    label is an AD-18 violation, and emitting a citation field on one would
    make a claim about evidence citable as evidence (AD-6). Either is refused
    before a store sees it.
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
    """Refuse a record that does not state it is unreviewed and machine-written."""
    missing = [key for key in REVIEW_KEYS if key not in record]
    if missing:
        raise DocumentRecordRefused(
            "an extraction-document record is missing "
            + ", ".join(repr(key) for key in missing)
            + " — a document is indexed without passing the publish gate, so it"
            " must carry its unreviewed, machine-written status in the record"
            " itself (AD-4's exception, AD-18)"
        )
    if record["reviewState"] != REVIEW_STATE or record["authorship"] != AUTHORSHIP:
        raise DocumentRecordRefused(
            f"an extraction-document record claims reviewState"
            f" {record['reviewState']!r}/authorship {record['authorship']!r};"
            f" the only values a document may carry are {REVIEW_STATE!r} and"
            f" {AUTHORSHIP!r} — nothing approves an extraction document (AD-18)"
        )
    if not str(record["reviewLabel"]).strip():
        raise DocumentRecordRefused(
            "an extraction-document record carries an empty reviewLabel — the"
            " sentence a surface renders lives in the record, so a blank one"
            " would let a document render indistinguishably from reviewed"
            " output (AD-18)"
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
        # AD-18, in the record itself.
        "reviewState": REVIEW_STATE,
        "authorship": AUTHORSHIP,
        "reviewLabel": REVIEW_LABEL,
        # AD-6, in the record itself: stated rather than merely implied by the
        # absence of a moment id, so a consumer reading this index can refuse
        # to cite without knowing the architecture.
        "citable": False,
    }
    assert_carries_review_label(record)
    assert_not_citable(record)
    return record
