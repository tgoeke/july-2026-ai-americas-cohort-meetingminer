"""Sole Neo4j + Meilisearch writers; publish gate; rebuild CLI (AD-4) — story 1.7.

One entry point per caller:

* :func:`project_meeting` — the worker, at evidence-complete.
* :func:`project_meeting_embeddings` — the resumable second pass, after a
  model-host outage or a `rebuild --embed-only`.
* :func:`unproject_meeting` — story 1.12 and the CLI, to retire a meeting.
* :func:`rebuild` — the CLI (FR24), and the answer to a corrupt store: both
  stores regenerate from Postgres + ``config.yaml`` alone (AD-4), never by
  hand-editing an index.

**Why structural and embedding are two passes and not one.**
`retrieval-prior-art.md` §3 rule 4 records the split as the difference between
a fragile pipeline and a robust one, and §7 finding 1 gives it teeth: BM25
alone beat all nine embedding models on transcript-worded queries, the
dominant query shape. A meeting that is structurally indexed with no vectors
is therefore *fully functional* on that traffic, not degraded. The structural
pass never touches the ``Embedder``, so an Ollama outage costs a nullable
timestamp and nothing else. It does mean a full projection writes each search
document twice — once without vectors, once with — which is a trivial cost for
making the boundary real rather than notional.

This module's only Postgres write is its own ``meeting_projection`` row.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, Sequence
from uuid import UUID

import meilisearch
import neo4j
from meilisearch.errors import MeilisearchError
from neo4j.exceptions import Neo4jError
from psycopg import Connection

from meetingminer.adapters.embed import (
    Embedder,
    EmbedderError,
    EmbedderUnavailableError,
    build_embedder,
)
from meetingminer.config import AppConfig
from meetingminer.projections import graph, search
from meetingminer.projections.chunking import Chunk, chunk_turns
from meetingminer.projections.documents import (
    DOCUMENTS_INDEX,
    DocumentRecordRefused,
)
from meetingminer.projections.evidence import (
    MeetingEvidence,
    extraction_documents,
    meeting_evidence_complete,
    projectable_meeting_ids,
    read_meeting,
)
from meetingminer.projections.locks import store_file_lock
from meetingminer.projections.publish_gate import (
    Artifact,
    PublishGateRefused,
    assert_publishable,
    is_publishable,
    published_artifacts,
)
from meetingminer.projections.stores import (
    DimensionMismatchError,
    ProjectionError,
    ProjectionLockedError,
    StoreUnavailableError,
    assert_recorded_dimension_matches,
    drop_all,
    ensure_artifact_graph_schema,
    ensure_artifact_search_schema,
    ensure_document_search_schema,
    ensure_graph_schema,
    ensure_search_schema,
    ensure_vector_search_schema,
    meili_client,
    neo4j_driver,
    projection_lock,
)

__all__ = [
    "ACTION_EMBED",
    "ACTION_FULL",
    "ACTION_NONE",
    "DOCUMENTS_INDEX",
    "Artifact",
    "DimensionMismatchError",
    "DocumentRecordRefused",
    "ProjectionError",
    "ProjectionLockedError",
    "ProjectionOutcome",
    "PublishGateRefused",
    "RebuildReport",
    "StoreUnavailableError",
    "assert_publishable",
    "invalidate_meeting_projection",
    "is_publishable",
    "project_extraction_documents",
    "project_meeting",
    "project_meeting_embeddings",
    "project_published_artifacts",
    "projection_action",
    "published_artifacts",
    "rebuild",
    "unproject_meeting",
]

Logger = Callable[..., None]


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


@dataclass(frozen=True)
class ProjectionOutcome:
    """What one meeting's projection did, for a caller to report."""

    meeting_id: UUID
    structural: bool
    embedded: bool
    moment_documents: int = 0
    chunk_documents: int = 0
    # Published artifacts re-projected alongside the meeting (story 4.4).
    # Always the meeting's full published set — drafts are structurally
    # excluded by `publish_gate.published_artifacts`'s own WHERE clause.
    artifact_documents: int = 0
    # Retained extraction documents re-indexed alongside the meeting (story
    # 12.4). Unlike `artifact_documents` this is *not* gated on approval — it
    # is every document `extraction_source` holds text for, which is AD-4's
    # one deliberate exception to the publish gate.
    extraction_documents: int = 0
    # A named warning that did *not* fail the projection — today, only an
    # unreachable model host. The structural rows are written and searchable.
    warning: str | None = None
    skipped_reason: str | None = None


@dataclass
class RebuildReport:
    """Per-meeting outcomes plus the summary the CLI prints."""

    outcomes: list[ProjectionOutcome] = field(default_factory=list)
    failures: list[tuple[UUID, str]] = field(default_factory=list)
    dropped: bool = False

    @property
    def projected(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.structural)

    @property
    def embedded(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.embedded)

    @property
    def ok(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class _Stores:
    driver: neo4j.Driver
    client: meilisearch.Client


@contextmanager
def _open_stores(
    config: AppConfig,
    *,
    dimension: int,
    ensure: bool = True,
    ensure_artifacts: bool = True,
    ensure_graph: bool = True,
) -> Iterator[_Stores]:
    """Open both stores and declare their schema, once per run.

    The dimension check lives inside ``ensure_search_schema`` and runs before
    anything is created, so a width change is a refusal rather than a partial
    write. Search is deliberately preflighted before Neo4j schema setup: a
    known vector-width mismatch must not leave graph constraints behind.

    ``ensure=False`` is for the one caller that must *not* be refused by that
    check: a full ``rebuild`` is exactly the remedy AD-8 prescribes for an
    embedder swap, so it drops the stale indexes first and declares the schema
    afterwards.
    """
    with neo4j_driver(config) as driver:
        client = meili_client(config)
        if ensure:
            if ensure_artifacts:
                ensure_search_schema(client, config, dimension=dimension)
            else:
                ensure_vector_search_schema(client, config, dimension=dimension)
            if ensure_graph:
                ensure_graph_schema(driver)
        yield _Stores(driver=driver, client=client)


# --- projection state -----------------------------------------------------


def _read_state(conn: Connection, meeting_id: UUID) -> tuple | None:
    return conn.execute(
        "SELECT structural_at, embedded_at, embedder_model, embedder_dimension,"
        " chunk_max_chars, chunk_overlap_turns FROM meeting_projection"
        " WHERE meeting_id = %s",
        (meeting_id,),
    ).fetchone()


# What a caller holding a `meeting_projection` row should do next.
ACTION_NONE = "none"
ACTION_FULL = "full"
ACTION_EMBED = "embed"


def projection_action(conn: Connection, config: AppConfig, meeting_id: UUID) -> str:
    """Whether this meeting needs a full projection, only vectors, or nothing.

    "Current" means more than "a row exists": an embedder swap or a chunking
    retune makes every projected vector and every chunk boundary stale (AD-8,
    `retrieval-prior-art.md` §6), so a row recorded under different values is
    not current and the meeting re-projects in full.

    A row whose ``embedded_at`` is NULL is *not* stale — it is a meeting that
    was structurally indexed while the model host was down, and it is fully
    searchable by BM25 in that state. It needs only the embedding pass, which
    is why that is a distinct answer rather than a second full projection.
    """
    row = _read_state(conn, meeting_id)
    if row is None:
        return ACTION_FULL
    embedder = config.settings.embedder
    chunking = config.settings.projections.chunking
    matches_config = (
        row[2] == embedder.model
        and row[3] == embedder.dimension
        and row[4] == chunking.chunk_max_chars
        and row[5] == chunking.chunk_overlap_turns
    )
    if not matches_config:
        return ACTION_FULL
    return ACTION_NONE if row[1] is not None else ACTION_EMBED


def _require_current_structural_state(
    conn: Connection, config: AppConfig, meeting_id: UUID
) -> None:
    """Refuse embed-only work whose stored chunks no longer match the graph.

    A vector pass rebuilds Meilisearch documents from the same chunks Neo4j's
    ``Chunk`` nodes use. This guard runs before stores are opened or documents
    are built, because scoped rebuilds bypass :func:`projection_action`.
    """
    row = _read_state(conn, meeting_id)
    if row is None:
        raise ProjectionError(
            f"meeting {meeting_id} has no meeting_projection row, so an"
            " embedding-only pass has nothing to complete — run a full"
            f" projection first ('rebuild --meeting {meeting_id}')"
        )

    embedder = config.settings.embedder
    chunking = config.settings.projections.chunking
    recorded = {
        "embedder.model": row[2],
        "embedder.dimension": row[3],
        "chunk_max_chars": row[4],
        "chunk_overlap_turns": row[5],
    }
    configured = {
        "embedder.model": embedder.model,
        "embedder.dimension": embedder.dimension,
        "chunk_max_chars": chunking.chunk_max_chars,
        "chunk_overlap_turns": chunking.chunk_overlap_turns,
    }
    changed = [
        f"{name} recorded as {recorded[name]!r} but configured as {configured[name]!r}"
        for name in recorded
        if recorded[name] != configured[name]
    ]
    if changed:
        raise ProjectionError(
            f"meeting {meeting_id} requires a full projection before embedding-only"
            f" work: {'; '.join(changed)}. Run 'rebuild --meeting {meeting_id}'"
            " without --embed-only."
        )


def _record_structural(conn: Connection, config: AppConfig, meeting_id: UUID) -> None:
    embedder = config.settings.embedder
    chunking = config.settings.projections.chunking
    conn.execute(
        "INSERT INTO meeting_projection (meeting_id, structural_at, embedded_at,"
        " embedder_model, embedder_dimension, chunk_max_chars, chunk_overlap_turns)"
        " VALUES (%s, now(), NULL, %s, %s, %s, %s)"
        " ON CONFLICT (meeting_id) DO UPDATE SET"
        "   structural_at = now(),"
        # Reset to NULL deliberately: the documents were just rewritten
        # without vectors, so claiming they are embedded would be false.
        "   embedded_at = NULL,"
        "   embedder_model = EXCLUDED.embedder_model,"
        "   embedder_dimension = EXCLUDED.embedder_dimension,"
        "   chunk_max_chars = EXCLUDED.chunk_max_chars,"
        "   chunk_overlap_turns = EXCLUDED.chunk_overlap_turns",
        (
            meeting_id,
            embedder.model,
            embedder.dimension,
            chunking.chunk_max_chars,
            chunking.chunk_overlap_turns,
        ),
    )
    conn.commit()


def _record_embedded(conn: Connection, config: AppConfig, meeting_id: UUID) -> None:
    """Mark this meeting embedded, or refuse if it was never structural.

    An UPDATE that matches no row would leave vectored documents in
    Meilisearch with nothing in Postgres saying so — the CLI would report
    ``embedded`` over a meeting the next ``rebuild`` treats as unprojected.
    The unscoped ``--embed-only`` path filters its targets to meetings that
    already have a row; a scoped ``rebuild --meeting <id> --embed-only`` has no
    such filter, so the guard belongs here where both paths pass through.
    """
    embedder = config.settings.embedder
    cursor = conn.execute(
        "UPDATE meeting_projection SET embedded_at = now(),"
        " embedder_model = %s, embedder_dimension = %s WHERE meeting_id = %s",
        (embedder.model, embedder.dimension, meeting_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        raise ProjectionError(
            f"meeting {meeting_id} has no meeting_projection row, so an"
            " embedding-only pass has nothing to complete — run a full"
            f" projection first ('rebuild --meeting {meeting_id}')"
        )
    conn.commit()


# --- the two passes -------------------------------------------------------


def _chunks(config: AppConfig, evidence: MeetingEvidence) -> tuple[Chunk, ...]:
    chunking = config.settings.projections.chunking
    return chunk_turns(
        evidence.meeting_id,
        evidence.turns,
        chunk_max_chars=chunking.chunk_max_chars,
        chunk_overlap_turns=chunking.chunk_overlap_turns,
    )


def _project_structural(
    conn: Connection,
    config: AppConfig,
    stores: _Stores,
    evidence: MeetingEvidence,
    chunks: tuple[Chunk, ...],
    artifacts: tuple[Artifact, ...],
) -> tuple[int, int, int, int]:
    """Write the graph and the search documents with no model involved.

    The ``Embedder`` is not imported, constructed, or called anywhere on this
    path — that is the whole point (`retrieval-prior-art.md` §3 rule 4).
    Published artifacts ride along (story 4.4): the per-meeting delete wipes
    their nodes and documents, so the same pass restores them from Postgres —
    which is what makes worker settle points, augmenting re-ingests and
    ``rebuild`` all preserve citability without a separate step. Retained
    extraction documents ride along for the same mechanical reason (story
    12.4), and that ride-along is what makes ``rebuild`` re-index them from
    their Postgres row alone. They reach Meilisearch only: no ``Document`` node
    is written, because the graph is traversed to *reach citable evidence* and
    a document is never a citation target (AD-6).
    """
    graph.project_meeting(stores.driver, evidence, chunks, artifacts)
    (
        moment_count,
        chunk_count,
        artifact_count,
        document_count,
    ) = search.project_meeting(stores.client, evidence, chunks, artifacts=artifacts)
    _record_structural(conn, config, evidence.meeting_id)
    return moment_count, chunk_count, artifact_count, document_count


def _embed_all(
    embedder: Embedder, texts: Sequence[str], batch_size: int
) -> list[tuple[float, ...]]:
    vectors: list[tuple[float, ...]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(embedder.embed_documents(texts[start : start + batch_size]))
    return vectors


def _project_embeddings(
    conn: Connection,
    config: AppConfig,
    stores: _Stores,
    evidence: MeetingEvidence,
    chunks: tuple[Chunk, ...],
    embedder: Embedder,
) -> tuple[int, int]:
    """Compute vectors and rewrite this meeting's search documents with them.

    Delete-and-reinsert, never an in-place vector update
    (`retrieval-prior-art.md` §3 rule 2). Neo4j and the artifacts index are
    untouched: vectors live only in the moments/chunks indexes, so an
    embedding pass is not a structural rewrite.
    """
    batch_size = config.settings.projections.embed_batch_size
    moment_documents = search.moment_documents(evidence)
    chunk_documents = search.chunk_documents(evidence, chunks)
    moment_vectors = _embed_all(
        embedder, [doc["text"] for doc in moment_documents], batch_size
    )
    chunk_vectors = _embed_all(
        embedder, [doc["text"] for doc in chunk_documents], batch_size
    )
    counts = search.project_embeddings(
        stores.client,
        evidence,
        chunks,
        moment_vectors=moment_vectors,
        chunk_vectors=chunk_vectors,
    )
    _record_embedded(conn, config, evidence.meeting_id)
    return counts


def _project_one(
    conn: Connection,
    config: AppConfig,
    stores: _Stores,
    meeting_id: UUID,
    *,
    embedder_factory: Callable[[], Embedder],
    structural_only: bool,
    embed_only: bool,
    log: Logger,
) -> ProjectionOutcome:
    evidence = read_meeting(conn, meeting_id)
    chunks = _chunks(config, evidence)
    # The meeting's published artifacts, read fresh from Postgres each pass
    # (story 4.4): the per-meeting delete removes their documents/nodes, and
    # Postgres — never a store — is what says which artifacts exist.
    artifacts = () if embed_only else published_artifacts(conn, meeting_id=meeting_id)

    structural = False
    moment_count = chunk_count = artifact_count = document_count = 0
    if not embed_only:
        (
            moment_count,
            chunk_count,
            artifact_count,
            document_count,
        ) = _project_structural(conn, config, stores, evidence, chunks, artifacts)
        structural = True
        log(
            "projection.structural",
            meeting_id=meeting_id,
            moments=moment_count,
            chunks=chunk_count,
            artifacts=artifact_count,
            # Reported apart from `artifacts` deliberately: these passed no
            # publish gate, and a reader of this line must be able to see that
            # the two counts mean different things (AD-4's exception).
            extraction_documents=document_count,
            screens=len(evidence.screens),
            participants=len(evidence.participants),
        )

    if structural_only:
        return ProjectionOutcome(
            meeting_id=meeting_id,
            structural=structural,
            embedded=False,
            moment_documents=moment_count,
            chunk_documents=chunk_count,
            artifact_documents=artifact_count,
            extraction_documents=document_count,
        )

    try:
        embedder = embedder_factory()
        moment_count, chunk_count = _project_embeddings(
            conn, config, stores, evidence, chunks, embedder
        )
    except EmbedderUnavailableError as exc:
        # The one failure this pass is required to survive. Structural rows
        # are already written and committed; BM25 retrieval over them is fully
        # functional, and `rebuild --embed-only` finishes the job later.
        conn.rollback()
        log(
            "projection.embedding_skipped",
            meeting_id=meeting_id,
            reason=str(exc),
        )
        return ProjectionOutcome(
            meeting_id=meeting_id,
            structural=structural,
            embedded=False,
            moment_documents=moment_count,
            chunk_documents=chunk_count,
            artifact_documents=artifact_count,
            extraction_documents=document_count,
            warning=str(exc),
        )
    except EmbedderError as exc:
        # Not an outage: a model id the host does not have, a wrong-width
        # vector. No retry fixes it, so it stays a failure — but the message
        # has to say that the structural half already landed, or an operator
        # reads "projection failed" and assumes the meeting is unsearchable
        # when it is fully searchable by BM25.
        conn.rollback()
        landed = (
            f" ({moment_count} moment / {chunk_count} chunk documents)"
            if structural
            else " (in an earlier pass)"
        )
        raise ProjectionError(
            f"meeting {meeting_id} is projected structurally{landed} and is"
            " searchable by BM25, but its embedding pass failed and no retry"
            f" will fix it: {exc}"
        ) from exc
    log("projection.embedded", meeting_id=meeting_id)
    return ProjectionOutcome(
        meeting_id=meeting_id,
        structural=structural,
        embedded=True,
        moment_documents=moment_count,
        chunk_documents=chunk_count,
        artifact_documents=artifact_count,
        extraction_documents=document_count,
    )


# --- public surface -------------------------------------------------------


def project_meeting(
    conn: Connection,
    config: AppConfig,
    meeting_id: UUID,
    *,
    structural_only: bool = False,
    log: Logger | None = None,
    embedder_factory: Callable[[], Embedder] | None = None,
) -> ProjectionOutcome:
    """Project one meeting into both stores. The worker's ingest-complete call.

    Takes both locks for its duration — the cross-process store file lock
    first, then the Postgres advisory lock — so a ``rebuild`` racing it is a
    named error on one side rather than a store that matches neither
    (`retrieval-prior-art.md` §3 rule 1), and a projection-test suite in
    another worktree (a different Postgres database, same stores) queues on
    the same file instead of racing freely.
    """
    emit = log or _noop
    factory = embedder_factory or (lambda: build_embedder(config, emit))
    assert_recorded_dimension_matches(conn, config)
    holder = f"projection of meeting {meeting_id}"
    with store_file_lock(config, holder=holder), projection_lock(conn, holder=holder):
        with _open_stores(
            config, dimension=config.settings.embedder.dimension
        ) as stores:
            return _project_one(
                conn,
                config,
                stores,
                meeting_id,
                embedder_factory=factory,
                structural_only=structural_only,
                embed_only=False,
                log=emit,
            )


def project_meeting_embeddings(
    conn: Connection,
    config: AppConfig,
    meeting_id: UUID,
    *,
    log: Logger | None = None,
    embedder_factory: Callable[[], Embedder] | None = None,
) -> ProjectionOutcome:
    """Fill in one already-structural meeting's vectors. No structural rewrite."""
    emit = log or _noop
    factory = embedder_factory or (lambda: build_embedder(config, emit))
    assert_recorded_dimension_matches(conn, config)
    _require_current_structural_state(conn, config, meeting_id)
    holder = f"embedding of meeting {meeting_id}"
    with store_file_lock(config, holder=holder), projection_lock(conn, holder=holder):
        # State can change while this caller waits for a full projection or
        # retirement to release the lock. Recheck before opening either store.
        _require_current_structural_state(conn, config, meeting_id)
        with _open_stores(
            config,
            dimension=config.settings.embedder.dimension,
            ensure_artifacts=False,
            ensure_graph=False,
        ) as stores:
            return _project_one(
                conn,
                config,
                stores,
                meeting_id,
                embedder_factory=factory,
                structural_only=False,
                embed_only=True,
                log=emit,
            )


def project_published_artifacts(
    conn: Connection,
    config: AppConfig,
    *,
    artifact_ids: Sequence[UUID] | None = None,
    meeting_id: UUID | None = None,
    log: Logger | None = None,
) -> int:
    """Project published artifacts into both stores. The approve route's call.

    Scoped to specific artifact ids (the approve route, post-commit) or to one
    meeting. The read is ``publish_gate.published_artifacts`` — its statement
    selects ``WHERE state = 'published'``, and :func:`assert_publishable` runs
    again per artifact before either store is opened (AD-4, both lines).

    Takes the same two locks in the same order as every other store-writing
    entrypoint — the cross-process store file lock first, then the Postgres
    advisory lock — which is what retires the unlocked-``project_artifact``
    defect recorded in deferred-work: no store write in this module runs
    outside the composed exclusion domain.

    Returns how many artifacts were projected. Ids that are missing or not
    ``published`` are logged and skipped rather than raised: the caller's rows
    are already durably published, and `rebuild --meeting <id>` is the
    recovery for anything this call could not do.
    """
    emit = log or _noop
    scope_count = len(artifact_ids) if artifact_ids is not None else 1
    holder = f"projection of {scope_count} published artifact scope(s)"
    with store_file_lock(config, holder=holder), projection_lock(conn, holder=holder):
        # The source moment may be remapped while this caller waits for either
        # lock. Read the authoritative rows only after both exclusions are
        # held, otherwise this waiter could overwrite a rebuild's fresh CITES
        # edge and search document with a stale pre-lock moment id.
        artifacts = published_artifacts(
            conn, meeting_id=meeting_id, artifact_ids=artifact_ids
        )
        if artifact_ids is not None:
            found = {artifact.id for artifact in artifacts}
            for requested in artifact_ids:
                if requested not in found:
                    emit(
                        "projection.artifact_skipped",
                        artifact_id=requested,
                        reason="not found in state 'published'",
                    )
        if not artifacts:
            return 0
        for artifact in artifacts:
            assert_publishable(artifact.state)
        with _open_stores(
            config,
            dimension=config.settings.embedder.dimension,
            ensure=False,
        ) as stores:
            ensure_artifact_search_schema(stores.client, config)
            ensure_artifact_graph_schema(stores.driver)
            graph.project_artifacts(stores.driver, artifacts)
            projected = search.project_artifacts(stores.client, artifacts)
    emit(
        "projection.artifacts",
        artifacts=projected,
        artifact_ids=[str(artifact.id) for artifact in artifacts],
    )
    return projected


_MEETING_HEADER = "SELECT source_id, corpus, title FROM meeting WHERE id = %s"

# Runs whose document was never retained (story 12.1 landed after them). Not a
# failure and not an empty document: there is nothing to index, and a
# re-extraction is what produces text. Counted so the log can say which of the
# two an empty index for this meeting is (AD-18's distinction, kept).
_UNRETAINED_DOCUMENTS = (
    "SELECT count(*) FROM extraction_source"
    " WHERE meeting_id = %s AND document_text IS NULL"
)


def project_extraction_documents(
    conn: Connection,
    config: AppConfig,
    meeting_id: UUID,
    *,
    log: Logger | None = None,
) -> int:
    """Index one meeting's retained extraction documents. **Ungated** (AD-4).

    The `extract` stage's settle point. Every other store write in this module
    either projects evidence (which is complete before `extract` runs) or
    passes the publish gate; this one does neither, and that is the whole
    point. Owner ruling 2026-08-31, recorded in AD-4: every extraction document
    is indexed as soon as it is stored, approved or not, because the run whose
    text somebody needs to read is exactly the run that yielded nothing worth
    approving. Gating documents behind approval would withhold them in
    precisely the case they exist for.

    Why it needs an entrypoint at all rather than riding the structural pass
    alone: evidence projects at evidence-complete, and `extract` runs *after*
    that, so a document stored by the extract stage would otherwise wait for
    the next `rebuild` to become findable. The structural ride-along is still
    what makes `rebuild` regenerate them from Postgres alone; this is what
    makes "as soon as it is stored" true.

    Delete-then-add, scoped to this meeting and to the documents index alone —
    a re-extraction replaces its records rather than accumulating one set per
    run, and moments, chunks and artifacts (already correct at this point) are
    never touched.

    Takes the same two locks in the same order as every other store-writing
    entrypoint here, so no store write in this module runs outside the composed
    exclusion domain.

    Returns how many document records were written. A meeting whose runs all
    predate story 12.1's retention has no text to index and returns 0 — which
    is a re-extraction backlog, named in the log rather than inferred from an
    empty index.
    """
    emit = log or _noop
    header = conn.execute(_MEETING_HEADER, (meeting_id,)).fetchone()
    if header is None:
        raise LookupError(f"no meeting {meeting_id}")
    source_id, corpus, title = header
    holder = f"extraction-document projection of meeting {meeting_id}"
    with store_file_lock(config, holder=holder), projection_lock(conn, holder=holder):
        # Read the rows only once both exclusions are held: a rerun of the
        # extract stage committing while this caller waited would otherwise
        # let a stale pre-lock document overwrite the fresh record a
        # concurrent writer just wrote.
        rows = extraction_documents(conn, meeting_id)
        records = search.documents_of(
            rows,
            meeting_id=meeting_id,
            corpus=corpus,
            meeting_title=title,
            source_id=source_id,
        )
        # This settle point owns only the keyword documents index. Opening the
        # graph here would let an unrelated Neo4j outage withhold a healthy
        # Meilisearch write, contrary to the reason this independent trigger
        # exists. There is no vector-width preflight either: the index declares
        # no embedder, so that check has nothing to protect.
        client = meili_client(config)
        ensure_document_search_schema(client, config)
        # Unconditional, including when `records` is empty: a rerun that
        # produced fewer documents than the last one must not leave the extra
        # ones standing.
        search.delete_meeting_documents(client, meeting_id)
        written = search.project_documents(client, records)
    unretained = conn.execute(_UNRETAINED_DOCUMENTS, (meeting_id,)).fetchone()[0]
    emit(
        "projection.extraction_documents",
        meeting_id=meeting_id,
        documents=written,
        # A corpus still carrying pre-12.1 rows is a re-extraction backlog, and
        # it has to be visible here rather than read as "this meeting produced
        # nothing".
        unretained=unretained,
        # Stated in the log, not only in this docstring: this is the one write
        # in the module that did not pass the publish gate, and an operator
        # reading the log should be able to see that without reading AD-4.
        gate="bypassed (AD-4 extraction-document exception)",
    )
    return written


def unproject_meeting(
    conn: Connection, config: AppConfig, meeting_id: UUID, *, log: Logger | None = None
) -> None:
    """Remove one meeting from both stores and forget its projection state.

    Cross-meeting ``Screen`` and ``Participant`` nodes survive: they belong to
    every other meeting that showed or attended them (AD-5).
    """
    emit = log or _noop
    holder = f"unprojection of meeting {meeting_id}"
    with store_file_lock(config, holder=holder), projection_lock(conn, holder=holder):
        # `ensure=False`: retiring a meeting writes no vector, so the width
        # check that exists to force a rebuild after an embedder swap must not
        # block it — otherwise a swap would leave meetings that can be neither
        # projected nor removed. Nothing is created here either; a store with
        # no index has nothing of this meeting's to delete.
        with _open_stores(
            config, dimension=config.settings.embedder.dimension, ensure=False
        ) as stores:
            graph.unproject_meeting(stores.driver, str(meeting_id))
            search.unproject_meeting(stores.client, meeting_id)
        # Inside the lock: the store deletion and the state deletion are one
        # retirement, and a `rebuild` slipping between them would see a
        # meeting recorded as projected whose documents are gone.
        conn.execute(
            "DELETE FROM meeting_projection WHERE meeting_id = %s", (meeting_id,)
        )
        conn.commit()
    emit("projection.removed", meeting_id=meeting_id)


def invalidate_meeting_projection(
    conn: Connection, meeting_id: UUID, *, log: Logger | None = None
) -> bool:
    """Forget one meeting's recorded projection state. Returns whether it had one.

    The augmentation entry point (story 1.12). A recording recovered after the
    occurrence was ingested transcript-only re-runs the video stages against the
    *same* meeting id, so the meeting's documents in both stores now describe
    evidence that has been superseded. :func:`projection_action` answers
    ``ACTION_NONE`` for a meeting with a current ``meeting_projection`` row, so
    without this the terminal projection call at the end of the augmented run
    would decline to do anything and the recovered recording would never reach
    Neo4j or Meilisearch.

    Deliberately *not* :func:`unproject_meeting`. That one opens both stores and
    deletes the meeting's nodes and documents, which would blank it from search
    for the length of the re-run — for a meeting that is still perfectly
    answerable from its transcript. This only drops the state row; the next
    :func:`projection_action` then answers ``ACTION_FULL`` and
    :func:`project_meeting`'s existing per-meeting delete-and-reinsert replaces
    the documents in one pass, scoped to this meeting id (AD-4).

    No projection lock is taken: a ``DELETE`` of one row is not a store write,
    and holding the lock across the whole re-run would block every other
    projection for the length of an ffmpeg pass. That leaves a real window: a
    ``rebuild`` that re-inserts this meeting's ``meeting_projection`` row after
    the ``DELETE`` but before the augmented run's video stages finish restores
    ``ACTION_NONE``, so the run's terminal projection call declines and the
    augmented bundle never reaches either store — the exact failure this
    invalidation exists to prevent, leaving the pre-recording documents
    standing. Nothing in Postgres is lost or corrupted by that, and the remedy
    is a targeted ``rebuild --meeting <id>`` after the run; paying for it with a
    lock held across an entire ingest is the worse trade.
    """
    emit = log or _noop
    row = conn.execute(
        "DELETE FROM meeting_projection WHERE meeting_id = %s RETURNING meeting_id",
        (meeting_id,),
    ).fetchone()
    conn.commit()
    existed = row is not None
    emit("projection.invalidated", meeting_id=meeting_id, had_state=existed)
    return existed


def rebuild(
    conn: Connection,
    config: AppConfig,
    *,
    meeting_ids: Sequence[UUID] | None = None,
    embed_only: bool = False,
    structural_only: bool = False,
    dry_run: bool = False,
    log: Logger | None = None,
    embedder_factory: Callable[[], Embedder] | None = None,
) -> RebuildReport:
    """Regenerate both stores from Postgres + ``config.yaml`` alone (FR24, AD-4).

    With no ``meeting_ids`` and no ``embed_only``, both stores are dropped
    first: that is what makes "no orphan nodes or documents survive" true
    across a renamed attribute or a removed edge. A scoped run
    (``--meeting``) and an ``--embed-only`` run never drop, because they are
    not authoritative for the meetings they do not touch.

    A per-meeting failure is reported and the pass continues; the report's
    :attr:`RebuildReport.ok` is what the CLI turns into a non-zero exit.
    """
    emit = log or _noop
    factory = embedder_factory or (lambda: build_embedder(config, emit))
    report = RebuildReport()

    if meeting_ids is None:
        targets = projectable_meeting_ids(conn)
        if embed_only:
            # Check every existing structural projection for drift before
            # filtering to the nullable embedding pass. Otherwise a retuned
            # but already-embedded corpus would misleadingly report success
            # with zero targets instead of requiring its full rebuild.
            projections_by_meeting = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT meeting_id, embedded_at FROM meeting_projection"
                ).fetchall()
            }
            targets = [mid for mid in targets if mid in projections_by_meeting]
        full_wipe = not embed_only
    else:
        targets = list(meeting_ids)
        full_wipe = False

    # A full rebuild is the prescribed remedy for an embedder swap (AD-8), so
    # it must not be refused by the width check that exists to force it. Every
    # other shape of run is.
    if not full_wipe:
        if embed_only:
            # Schema setup is itself a write path. Refuse every stale target
            # before either store is opened or changed, while allowing other
            # scoped targets to retain the normal per-meeting continuation.
            stale: list[tuple[UUID, str]] = []
            current: list[UUID] = []
            for meeting_id in targets:
                try:
                    _require_current_structural_state(conn, config, meeting_id)
                except ProjectionError as exc:
                    stale.append((meeting_id, f"{type(exc).__name__}: {exc}"))
                else:
                    current.append(meeting_id)
            if stale:
                report.failures.extend(stale)
                for meeting_id, error in stale:
                    emit("rebuild.failed", meeting_id=meeting_id, error=error)
            targets = current
            if meeting_ids is None:
                # Only current-but-unembedded rows are resumable. Stale rows
                # were intentionally considered above, rather than hidden by
                # this filter.
                targets = [
                    meeting_id
                    for meeting_id in targets
                    if projections_by_meeting[meeting_id] is None
                ]
            if not targets:
                return report
        assert_recorded_dimension_matches(conn, config)

    if dry_run:
        for meeting_id in targets:
            emit("rebuild.dry_run", meeting_id=meeting_id)
            report.outcomes.append(
                ProjectionOutcome(
                    meeting_id=meeting_id,
                    structural=False,
                    embedded=False,
                    skipped_reason="dry run",
                )
            )
        return report

    with (
        store_file_lock(config, holder="rebuild"),
        projection_lock(conn, holder="rebuild"),
    ):
        if embed_only:
            # Repeat the no-write preflight inside the lock: another process
            # may have reprojected or retired a target while this call waited.
            stale = []
            current = []
            for meeting_id in targets:
                try:
                    _require_current_structural_state(conn, config, meeting_id)
                except ProjectionError as exc:
                    stale.append((meeting_id, f"{type(exc).__name__}: {exc}"))
                else:
                    current.append(meeting_id)
            if stale:
                report.failures.extend(stale)
                for meeting_id, error in stale:
                    emit("rebuild.failed", meeting_id=meeting_id, error=error)
            targets = current
            if not targets:
                return report
        with _open_stores(
            config,
            dimension=config.settings.embedder.dimension,
            ensure=not full_wipe,
            ensure_artifacts=not embed_only,
            ensure_graph=not embed_only,
        ) as stores:
            if full_wipe:
                emit("rebuild.dropping", meetings=len(targets))
                drop_all(stores.driver, stores.client)
                conn.execute("DELETE FROM meeting_projection")
                conn.commit()
                # Declare the schema only now: the drop removed the indexes
                # whose recorded vector width would otherwise refuse a
                # deliberate embedder swap.
                ensure_graph_schema(stores.driver)
                ensure_search_schema(
                    stores.client, config, dimension=config.settings.embedder.dimension
                )
                report.dropped = True

            for meeting_id in targets:
                if not meeting_evidence_complete(conn, meeting_id):
                    emit(
                        "rebuild.skipped",
                        meeting_id=meeting_id,
                        reason="evidence incomplete",
                    )
                    report.outcomes.append(
                        ProjectionOutcome(
                            meeting_id=meeting_id,
                            structural=False,
                            embedded=False,
                            skipped_reason="evidence incomplete",
                        )
                    )
                    continue
                try:
                    report.outcomes.append(
                        _project_one(
                            conn,
                            config,
                            stores,
                            meeting_id,
                            embedder_factory=factory,
                            structural_only=structural_only,
                            embed_only=embed_only,
                            log=emit,
                        )
                    )
                except (
                    ProjectionError,
                    EmbedderError,
                    LookupError,
                    Neo4jError,
                    MeilisearchError,
                ) as exc:
                    # `Neo4jError` and `MeilisearchError` are here because a
                    # raw client error on one meeting must be a recorded
                    # per-meeting failure, not a run abort that strands the
                    # whole corpus mid-rebuild. The graph write is one
                    # transaction and rolls back whole; the search write is
                    # not — a failed meeting may leave stale or partial
                    # documents in Meilisearch until it is retried
                    # (`rebuild --meeting <id>`), which the recorded failure
                    # is the pointer to.
                    conn.rollback()
                    report.failures.append((meeting_id, f"{type(exc).__name__}: {exc}"))
                    emit("rebuild.failed", meeting_id=meeting_id, error=str(exc))
    return report
