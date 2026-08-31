"""The Meilisearch projection: four indexes, first-class full-text (AD-4).

Full-text is not a fallback behind the vector half. Measured on this corpus,
**0 of 9 embedding models beat BM25 alone** on transcript-worded queries — the
dominant query shape (`retrieval-prior-art.md` §7 finding 1). So the index
settings are declared in ``config.yaml`` and applied deliberately
(``stores.ensure_search_schema``), and a meeting with no vectors at all is
fully functional here rather than degraded.

**Two indexes, not one.**

* ``moments`` is *citation-shaped*: one document per moment, keyed on the
  Postgres-minted moment UUID, so a citation resolves to something replayable
  (AD-6). It carries the moment's ``screenshotId`` when it has one and its
  ``sourceDeepLink`` when it does not (UX-DR11).
* ``chunks`` is *retrieval-shaped*, at the turn-packed granularity the bake-off
  actually measured, keyed on the UUID of its first transcript segment.
* ``artifacts`` is *published knowledge*, keyed on the artifact UUID and
  written only through the publish gate (story 4.4).
* ``documents`` is *the analysis itself* (story 12.4), keyed on the
  ``extraction_source`` row's UUID and written **without** passing the publish
  gate — AD-4's one deliberate exception. Its records carry their unreviewed,
  machine-written status and no citation field; see
  :mod:`meetingminer.projections.documents` for both constraints and for why
  the indexed identity is one record per row rather than a chunk key.

Both carry ``meetingId`` and ``corpus`` as filterable attributes — ``corpus``
because an eval run must be able to scope to ``scripted`` meetings without the
``real`` demo corpus polluting the result set.

**Vectors are insert-only** (`retrieval-prior-art.md` §3 rule 2). Every write
here is a delete-of-this-meeting followed by an add: a changed chunk is a new
document, never a vector patched in place. That is also why the embedding pass
rebuilds whole documents rather than pushing a partial update.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from uuid import UUID

import meilisearch

from meetingminer.adapters.embed.port import Vector
from meetingminer.projections.chunking import Chunk
from meetingminer.projections.documents import (
    DOCUMENTS_INDEX,
    assert_carries_review_label,
    assert_not_citable,
    document_record,
)
from meetingminer.projections.evidence import ExtractionDocumentRow, MeetingEvidence
from meetingminer.projections.publish_gate import (
    ARTIFACTS_INDEX,
    Artifact,
    artifact_document,
)
from meetingminer.projections.stores import (
    CHUNKS_INDEX,
    EMBEDDER_NAME,
    MOMENTS_INDEX,
    await_task,
)

# Documents per add_documents call. Meilisearch handles far larger batches;
# this keeps one meeting's payload bounded and the task list readable.
_BATCH = 500


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def moment_documents(evidence: MeetingEvidence) -> list[dict[str, Any]]:
    """One document per moment — the citation-shaped index."""
    screenshot_by_id = {s.id: s for s in evidence.screenshots}
    screen_by_id = {s.id: s for s in evidence.screens}
    documents: list[dict[str, Any]] = []
    for moment in evidence.moments:
        screenshot = (
            screenshot_by_id.get(moment.screenshot_id) if moment.screenshot_id else None
        )
        screen = screen_by_id.get(screenshot.screen_id) if screenshot else None
        documents.append(
            {
                # The Postgres UUID, verbatim (AD-6). Never an ordinal.
                "id": str(moment.id),
                "meetingId": str(evidence.meeting_id),
                "corpus": evidence.corpus,
                "title": evidence.title or "",
                "sourceId": evidence.source_id,
                "text": moment.text,
                # The OCR text of the screen that was up while this was said,
                # so a term appearing only on the slide is still findable
                # (FR12). `None` on a transcript-only moment, and on a
                # recording moment whose capture has no OCR row — neither is
                # an error, and Meilisearch indexes the absent field as
                # nothing rather than refusing the document.
                "screenText": screenshot.ocr_text if screenshot else None,
                "speakers": list(moment.speakers),
                "participantIds": [str(p) for p in moment.participant_ids],
                "startMs": moment.start_ms,
                "endMs": moment.end_ms,
                "startedAt": _iso(moment.started_at),
                "startedAtPrecision": moment.started_at_precision,
                "derivedFrom": moment.derived_from,
                "segmentCount": moment.segment_count,
                # Present on a recording meeting, absent on a transcript-only
                # one — where `sourceDeepLink` is the replay affordance.
                "screenshotId": str(moment.screenshot_id)
                if moment.screenshot_id
                else None,
                "screenId": str(screenshot.screen_id) if screenshot else None,
                "screenLabel": (screen.label if screen else None),
                "screenshotPath": screenshot.path if screenshot else None,
                "sourceDeepLink": moment.source_deep_link,
                # Filterable, so "moments I can replay" is one filter rather
                # than a null-check the caller has to remember.
                "hasScreenshot": moment.screenshot_id is not None,
            }
        )
    return documents


def chunk_documents(
    evidence: MeetingEvidence, chunks: Sequence[Chunk]
) -> list[dict[str, Any]]:
    """One document per packed chunk — the retrieval-shaped index."""
    documents: list[dict[str, Any]] = []
    for chunk in chunks:
        moment_ids: list[str] = []
        for segment_id in chunk.segment_ids:
            moment_id = evidence.moment_by_segment.get(segment_id)
            if moment_id is not None and str(moment_id) not in moment_ids:
                moment_ids.append(str(moment_id))
        documents.append(
            {
                # The first turn's Postgres segment UUID (see chunking.py).
                "id": str(chunk.id),
                "meetingId": str(evidence.meeting_id),
                "corpus": evidence.corpus,
                "title": evidence.title or "",
                "text": chunk.text,
                "speakers": list(chunk.speakers),
                "participantIds": [str(p) for p in chunk.participant_ids],
                # Do not collapse by label: the same raw label can appear
                # with different resolution states in one passage.
                "speakerTurns": [
                    {
                        "speakerLabel": turn.speaker_label,
                        "speakerResolution": turn.speaker_resolution,
                    }
                    for turn in chunk.turns
                ],
                "startMs": chunk.start_ms,
                "endMs": chunk.end_ms,
                "segmentIds": [str(s) for s in chunk.segment_ids],
                # A chunk can straddle a moment boundary, so this is a list:
                # it is how a chunk hit is resolved to a citable moment (AD-6).
                "momentIds": moment_ids,
                "turnCount": len(chunk.turns),
                "charCount": chunk.char_count,
            }
        )
    return documents


def document_documents(evidence: MeetingEvidence) -> list[dict[str, Any]]:
    """One record per retained extraction document — the ungated index.

    The shape is ``documents.document_record``'s, and both of that module's
    guards run inside it: a record that lost its unreviewed label, or that
    grew a field the citation path could resolve, raises before any document
    exists. Built from ``evidence.documents`` — Postgres rows, read by
    ``evidence.extraction_documents`` — so ``rebuild`` re-indexes documents
    from the row alone and this module still opens no evidence file.

    No ``_vectors`` key, ever: the documents index declares no embedder, for
    the same reason the artifacts index does not.
    """
    return [
        document_record(
            row,
            meeting_id=evidence.meeting_id,
            corpus=evidence.corpus,
            meeting_title=evidence.title,
            source_id=evidence.source_id,
        )
        for row in evidence.documents
    ]


def documents_of(
    rows: Sequence[ExtractionDocumentRow],
    *,
    meeting_id: UUID,
    corpus: str,
    meeting_title: str | None,
    source_id: str,
) -> list[dict[str, Any]]:
    """The same records, built from rows read without a whole evidence bundle.

    The settle-point pass (`projections.project_extraction_documents`) has the
    meeting header and the document rows and nothing else; it must not pay for
    a full bundle read to index four documents. One builder, two callers.
    """
    return [
        document_record(
            row,
            meeting_id=meeting_id,
            corpus=corpus,
            meeting_title=meeting_title,
            source_id=source_id,
        )
        for row in rows
    ]


def artifact_documents(artifacts: Sequence[Artifact]) -> list[dict[str, Any]]:
    """One document per *published* artifact — the citable-knowledge index.

    The shape is ``publish_gate.artifact_document``'s, frozen by the eval
    harness (AD-16): id = artifact UUID, source moments in ``momentIds``. The
    gate runs inside that builder, so an unpublished artifact raises before
    any document exists. No ``_vectors`` key, ever: the artifacts index
    declares no embedder (story 4.4 Design Notes).
    """
    return [artifact_document(artifact) for artifact in artifacts]


def _with_vectors(
    documents: Sequence[Mapping[str, Any]], vectors: Sequence[Vector] | None
) -> list[dict[str, Any]]:
    """Attach user-provided vectors, or explicitly opt each document out.

    ``None`` means the structural pass — no ``Embedder`` was called. It is
    **not** the same as omitting ``_vectors``: with a ``userProvided`` embedder
    declared, Meilisearch rejects a document that neither supplies a vector nor
    opts out, so the structural pass writes ``_vectors.default: null``. That
    explicit opt-out is what makes "structural indexing works with the model
    host down" (`retrieval-prior-art.md` §3 rule 4) true against this store
    rather than merely intended: the documents land, BM25 serves them, and the
    embedding pass fills the vectors in later.
    """
    if vectors is None:
        return [
            {**document, "_vectors": {EMBEDDER_NAME: None}} for document in documents
        ]
    if len(vectors) != len(documents):
        raise ValueError(
            f"embedder returned {len(vectors)} vectors for {len(documents)} documents"
        )
    enriched: list[dict[str, Any]] = []
    for document, vector in zip(documents, vectors):
        body = dict(document)
        # `userProvided` — the module computed this itself through the port;
        # no store-native auto-embedder exists to compute it (AD-4).
        body["_vectors"] = {
            EMBEDDER_NAME: {"embeddings": list(vector), "regenerate": False}
        }
        enriched.append(body)
    return enriched


def delete_meeting(client: meilisearch.Client, meeting_id: UUID | str) -> None:
    """Drop one meeting's documents from both indexes, and nothing else.

    Filtered on ``meetingId``, which every document carries — that is what
    makes re-projecting one occurrence a scoped delete-and-reinsert rather
    than a full rebuild (`retrieval-prior-art.md` §3 rule 5), and it is the
    path story 1.12 re-projects through.

    The id is round-tripped through :class:`UUID` before it reaches the filter
    string. Every caller in this module passes a real UUID, but this is the
    delete that *every* re-projection runs, and a filter expression built by
    interpolation is not a place to trust a ``str`` parameter's shape.
    """
    scope = UUID(str(meeting_id))
    expression = f'meetingId = "{scope}"'
    for index_uid in (MOMENTS_INDEX, CHUNKS_INDEX, ARTIFACTS_INDEX, DOCUMENTS_INDEX):
        await_task(
            client,
            client.index(index_uid).delete_documents(filter=expression),
            # An index that does not exist holds none of this meeting's
            # documents, which is the state the delete wanted. Reached when a
            # meeting is retired against a store that was never built.
            tolerate=("index_not_found",),
        )


def delete_meeting_vectors(client: meilisearch.Client, meeting_id: UUID | str) -> None:
    """Drop only this meeting's vector-bearing documents.

    The embed-only pass owns the moments/chunks surfaces and must never even
    address the keyword-only artifacts or documents indexes.
    """
    scope = UUID(str(meeting_id))
    expression = f'meetingId = "{scope}"'
    for index_uid in (MOMENTS_INDEX, CHUNKS_INDEX):
        await_task(
            client,
            client.index(index_uid).delete_documents(filter=expression),
            tolerate=("index_not_found",),
        )


def _add(
    client: meilisearch.Client, index_uid: str, documents: Sequence[Mapping[str, Any]]
) -> None:
    index = client.index(index_uid)
    for start in range(0, len(documents), _BATCH):
        batch = [dict(document) for document in documents[start : start + _BATCH]]
        await_task(client, index.add_documents(batch))


def project_meeting(
    client: meilisearch.Client,
    evidence: MeetingEvidence,
    chunks: Sequence[Chunk],
    *,
    moment_vectors: Sequence[Vector] | None = None,
    chunk_vectors: Sequence[Vector] | None = None,
    artifacts: Sequence[Artifact] = (),
) -> tuple[int, int, int, int]:
    """Replace one meeting's documents in all four indexes; return the counts.

    Delete-then-add, always — never an in-place update. A meeting with zero
    moments writes zero moment documents and is not an error. Published
    artifacts ride along on structural/full projection because its
    meeting-scoped delete wipes theirs too, and extraction documents ride along
    for exactly the same mechanical reason — which is also what makes
    ``rebuild`` re-index them from the Postgres row alone. The separate
    embed-only pass below addresses moments and chunks exclusively, so neither
    artifacts nor documents ride or get rewritten there. Neither ever carries
    vectors: both indexes are keyword-only.
    """
    moments = _with_vectors(moment_documents(evidence), moment_vectors)
    passages = _with_vectors(chunk_documents(evidence, chunks), chunk_vectors)
    published = artifact_documents(artifacts)
    extraction = document_documents(evidence)
    delete_meeting(client, evidence.meeting_id)
    if moments:
        _add(client, MOMENTS_INDEX, moments)
    if passages:
        _add(client, CHUNKS_INDEX, passages)
    if published:
        _add(client, ARTIFACTS_INDEX, published)
    if extraction:
        _add(client, DOCUMENTS_INDEX, extraction)
    return len(moments), len(passages), len(published), len(extraction)


def project_embeddings(
    client: meilisearch.Client,
    evidence: MeetingEvidence,
    chunks: Sequence[Chunk],
    *,
    moment_vectors: Sequence[Vector],
    chunk_vectors: Sequence[Vector],
) -> tuple[int, int]:
    """Replace only vector-bearing documents for one meeting."""
    moments = _with_vectors(moment_documents(evidence), moment_vectors)
    passages = _with_vectors(chunk_documents(evidence, chunks), chunk_vectors)
    delete_meeting_vectors(client, evidence.meeting_id)
    if moments:
        _add(client, MOMENTS_INDEX, moments)
    if passages:
        _add(client, CHUNKS_INDEX, passages)
    return len(moments), len(passages)


def project_artifacts(client: meilisearch.Client, artifacts: Sequence[Artifact]) -> int:
    """Upsert published artifacts without touching the meeting's documents.

    The approve route's path (via ``projections.project_published_artifacts``):
    add-only, keyed on the artifact UUID, so a re-publish of the same ids is
    an idempotent overwrite rather than a duplicate.
    """
    documents = artifact_documents(artifacts)
    if documents:
        _add(client, ARTIFACTS_INDEX, documents)
    return len(documents)


def project_documents(
    client: meilisearch.Client, documents: Sequence[Mapping[str, Any]]
) -> int:
    """Replace the extraction-document records this caller built. Add-only.

    The settle-point path (via ``projections.project_extraction_documents``):
    the `extract` stage stores its rows *after* the evidence bundle has already
    been projected, so "indexed as soon as it is stored" needs a write that
    does not re-run the whole meeting. Keyed on the ``extraction_source`` row
    id, so a re-extraction — which upserts that row rather than inserting a
    second — is an idempotent overwrite rather than a duplicate.
    """
    # This public writer is the last boundary before the store. Keep both
    # invariants here as well as in ``document_record`` so a new caller cannot
    # bypass AD-18 or open a citation path by supplying a raw mapping. Validate
    # the whole batch before the first write: one malformed later record must
    # not leave a partially applied projection behind.
    for document in documents:
        assert_carries_review_label(document)
        assert_not_citable(document)
    if documents:
        _add(client, DOCUMENTS_INDEX, documents)
    return len(documents)


def delete_meeting_documents(
    client: meilisearch.Client, meeting_id: UUID | str
) -> None:
    """Drop one meeting's extraction-document records, and nothing else.

    The settle-point pass's delete half. Scoped to the documents index alone:
    a document projection must never touch a moment, a chunk or an artifact,
    because it runs at a point where those are already correct.
    """
    scope = UUID(str(meeting_id))
    await_task(
        client,
        client.index(DOCUMENTS_INDEX).delete_documents(
            filter=f'meetingId = "{scope}"'
        ),
        tolerate=("index_not_found",),
    )


def unproject_meeting(client: meilisearch.Client, meeting_id: UUID | str) -> None:
    """Remove one meeting's documents from every index."""
    delete_meeting(client, meeting_id)


def counts(client: meilisearch.Client) -> dict[str, int]:
    """Document counts per index, for the `rebuild` equivalence check."""
    result: dict[str, int] = {}
    for index_uid in (MOMENTS_INDEX, CHUNKS_INDEX, ARTIFACTS_INDEX, DOCUMENTS_INDEX):
        stats = client.index(index_uid).get_stats()
        total = getattr(stats, "number_of_documents", None)
        if total is None and isinstance(stats, dict):
            total = stats.get("numberOfDocuments")
        result[index_uid] = int(total or 0)
    return result
