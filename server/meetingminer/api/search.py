"""GET /search — corpus search over the moments index (story 3.1, FR12),
plus the keyword-only published-artifacts lane (story 4.4): an artifact hit
resolves through its source moment, so its evidence trail replays that moment.
Story 12.4 adds a third lane, and it is shaped differently on purpose.

**Extraction documents are a separate array, not a third kind of hit.** Every
extraction document is searchable the moment it is stored, approved or not —
AD-4's one deliberate exception to the publish gate, because the run whose text
somebody needs to read is exactly the run that yielded nothing worth approving.
But a document is a claim *about* evidence rather than evidence, so it is never
a citation target (AD-6): citing it would establish that the model said
something, not that the meeting did. `SearchHit` is the citation shape and its
`momentId` is required; a document has no moment. Rather than widening that
shape — which would put a null where every consumer expects a replayable
citation, the silent degradation AD-18 forbids — documents come back in
`documents`, a `DocumentHit` array with no moment id on it at all. A consumer
cannot build a citation from one because there is nothing there to build from.
Each carries its own `reviewLabel`, so a renderer labels it as unreviewed
machine-written output by displaying what it was given rather than by
remembering to.

**Meilisearch ranks; Postgres cites.** The index decides the order and
produces the snippet; every citation field that leaves this route —
``meetingId``, ``startMs``, ``endMs``, ``screenshotId``, ``sourceDeepLink``,
the meeting title — is re-read from the database of record inside the same
request (AD-2, AD-6). The cost is one extra query per search. What it buys is
that a hit is authoritative rather than as-indexed: a document the index still
holds for a moment Postgres no longer has is dropped and logged
(``search.stale_hit``) instead of being returned as a citation that resolves
nowhere.

**No ``meilisearch`` import lives here.** The query itself runs inside
``meetingminer/projections/query.py`` (AD-4). This route does bind a client —
``meili_client`` returns one and it is passed straight to ``search_moments`` —
but the client type, the index handle and every store call stay inside the
projections package, so nothing in ``meetingminer/api/`` imports
``meilisearch``. That is the property
``tests/test_projections_single_writer.py::test_the_api_package_never_reaches_a_store``
asserts, by AST walk over the imports.

**Two embedder failures, two answers.** ``EmbedderUnavailableError`` means the
model host is down, and the search degrades to keyword-only and says so
(``ranking: "keyword"``): `retrieval-prior-art.md` §7 finding 1 measured BM25
alone as unbeaten on transcript-worded queries, so keyword-only is a good
answer rather than a broken one. ``EmbedderError`` means the configured model
answered wrongly — a misconfiguration no retry fixes — and is refused with a
503 naming the model and dimension, because a config error masquerading as a
degraded search is how a corpus silently stops being searched by vector.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.adapters.embed import EmbedderError, EmbedderUnavailableError
from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.projections.publish_gate import PUBLISHED_STATE
from meetingminer.projections.query import (
    ArtifactHit,
    DocumentHit,
    MomentHit,
    search_artifacts,
    search_documents,
    search_moments,
)
from meetingminer.projections.stores import (
    ProjectionError,
    StoreUnavailableError,
    meili_client,
)

router = APIRouter()
ROUTER_ORDER = 50

# `strip_whitespace` before `min_length` is what makes `?q=%20` a 422 rather
# than a search for a space: a whitespace-only query matches everything and
# means nothing, and answering it with the top of the corpus would be worse
# than refusing it.
#
# `max_length` bounds the other end. An unbounded `q` is forwarded verbatim to
# the embedder (an HTTP body to the model host), to Meilisearch, and to every
# log line the request writes; a megabyte of query would be all three at once.
# 512 characters is far past any phrase a person types and far short of that.
SEARCH_TERM_MAX_LENGTH = 512
SearchTerm = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=SEARCH_TERM_MAX_LENGTH
    ),
]

# The two corpora a Meeting row may carry (AD-1). A closed set rather than a
# free string, so an unknown value is a 422 at the door instead of a filter
# that quietly matches nothing.
Corpus = Literal["scripted", "real"]

# Every citation field, read from Postgres in the same request that ranked the
# hit. The join is required rather than left: a moment whose meeting row is
# gone is not a citation, and the hit is dropped by the resolution step.
_RESOLVE_MOMENTS = (
    "SELECT m.id, m.meeting_id, m.start_ms, m.end_ms, m.started_at,"
    " m.started_at_precision, m.screenshot_id, m.source_deep_link,"
    " mt.title, mt.has_recording, mt.corpus"
    " FROM moment m JOIN meeting mt ON mt.id = m.meeting_id"
    " WHERE m.id = ANY(%s)"
)

# An artifact hit resolves *through its source moment* (story 4.4): the replay
# fields — `startMs`, `screenshotId`, `sourceDeepLink`, `hasRecording` — come
# from the moment whose evidence yielded the artifact, so the hit's trail
# replays that moment. The state filter is repeated here even though the index
# only ever holds published rows: a document surviving for a row whose state
# somehow moved is dropped, not returned (defense in depth, AD-2/AD-6).
_RESOLVE_ARTIFACTS = (
    "SELECT a.id, a.kind, a.title,"
    " m.id, m.meeting_id, m.start_ms, m.end_ms, m.started_at,"
    " m.started_at_precision, m.screenshot_id, m.source_deep_link,"
    " mt.title, mt.has_recording, mt.corpus"
    " FROM artifact a"
    " JOIN moment m ON m.id = a.moment_id"
    " JOIN meeting mt ON mt.id = m.meeting_id"
    " WHERE a.id = ANY(%s) AND a.state = %s"
)


# One ranked extraction document, re-read from Postgres in the same request.
# `document_text IS NOT NULL` repeats the projection's own filter: a record
# surviving for a row whose text was cleared is dropped rather than returned as
# a document with nothing to read (defense in depth, AD-2).
_RESOLVE_DOCUMENTS = (
    "SELECT es.id, es.meeting_id, es.kind, es.origin, es.model,"
    " es.prompt_hash, es.layout, es.item_count, es.artifact_count,"
    " es.byte_size, es.sha256, mt.title, mt.corpus, mt.has_recording"
    " FROM extraction_source es JOIN meeting mt ON mt.id = es.meeting_id"
    " WHERE es.id = ANY(%s) AND es.document_text IS NOT NULL"
)


class SnippetRunModel(BaseModel):
    """One run of snippet text — matched or not.

    Structured rather than marked-up on purpose. The web app wraps the
    highlighted runs itself and never receives markup it would have to trust,
    which is the AD-15 principle applied to snippets: consumers render from
    the array, they do not parse a string.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    text: str
    highlighted: bool


class SearchHit(BaseModel):
    """One search result, in the AD-15 citation shape plus its snippet."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    moment_id: UUID
    meeting_id: UUID
    meeting_title: str | None = None
    start_ms: int
    end_ms: int
    # The meeting's wall clock at this moment, with the precision it was
    # derived at — a day-precision meeting must never read as second-timed.
    # Declared as a `datetime` and serialized by pydantic, like
    # `meetings.MeetingListItem.started_at`: the two endpoints describe the
    # same column, so they must publish the same `format: date-time` schema and
    # generate the same TypeScript type.
    started_at: datetime | None = None
    started_at_precision: str | None = None
    # Present when the moment has replay evidence; absent on a transcript-only
    # meeting, where `sourceDeepLink` stands in its place (UX-DR11, AD-15).
    screenshot_id: UUID | None = None
    source_deep_link: str | None = None
    # Whether the meeting has a recording, so a consumer can offer an inline
    # replay without a second round trip.
    has_recording: bool
    corpus: str
    snippet: list[SnippetRunModel]
    # Meilisearch's ranking score for this hit. Ordering is already the store's
    # answer; this is here so a caller can see *how* close a hit was.
    score: float | None = None
    # Set when this hit is a *published artifact* (story 4.4) rather than a
    # moment. `momentId` and the replay fields above then belong to the
    # artifact's source moment, so the evidence trail replays that moment;
    # these three name the artifact itself. All `None` on a moment hit.
    artifact_id: UUID | None = Field(
        default=None,
        description=(
            "The published artifact's own id when this hit is an artifact"
            " rather than a moment (story 4.4); null on a moment hit."
        ),
    )
    artifact_kind: str | None = Field(
        default=None,
        description="The artifact's kind ('adr' or 'action-item'); null on a moment hit.",
    )
    artifact_title: str | None = Field(
        default=None,
        description="The artifact's title; null on a moment hit.",
    )


class DocumentHitModel(BaseModel):
    """One ranked extraction document (story 12.4). **Not a citation.**

    Deliberately missing every field `SearchHit` carries a citation in — no
    `momentId`, no `startMs`, no `screenshotId`, no `sourceDeepLink`. That
    absence is the mechanism, not an omission: a document is a claim *about*
    evidence, and a consumer must not be able to assemble a citation out of one
    (AD-6). Its content reaches an answer only through the moments its
    individual claims anchor to — which is the published-artifact path, already
    gated and already citable.

    Reachable without approval, and labelled because of it: AD-4's exception is
    to *reach*, never to legibility, so `reviewState`, `authorship`,
    `reviewLabel` and `citable` come off the indexed record and every surface
    that renders one renders them too (AD-18).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # The `extraction_source` row's UUID — the document's indexed identity.
    document_id: UUID
    # Scope and provenance, never a citation: a meeting id cannot replay at a
    # second, which is what a citation has to do (AD-15).
    meeting_id: UUID
    meeting_title: str | None = None
    corpus: str
    # Which document this run produced: 'arch-summary', 'action-items',
    # 'topics', 'ranking-signals'. `str`, not a Literal — migration 0010 says
    # widening the kind CHECK is a story, not a serialization failure here.
    kind: str
    # 'generated' (through the `Llm` port) or 'adopted' (the drop carried it).
    origin: str
    # NULL for an adopted document, whose summariser this side never observed.
    model: str | None = None
    prompt_hash: str | None = None
    layout: str
    # What the parse yielded. `itemCount` 0 on a document that plainly carries
    # content is the named zero-yield signal, and it is the case this whole
    # exception exists for — so it is on the wire, not only in Postgres.
    item_count: int
    artifact_count: int
    byte_size: int
    # AD-18, on the wire. `citable` is always false and is sent anyway: a
    # consumer should be able to refuse to cite a document without knowing the
    # architecture.
    review_state: str
    authorship: str
    review_label: str
    citable: bool = False
    snippet: list[SnippetRunModel]
    score: float | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    query: str
    # `hybrid` when the query was embedded, `keyword` when the model host was
    # unreachable and the search degraded. Announced rather than inferred: a
    # caller comparing two result sets has to know which ranking produced each.
    ranking: Literal["hybrid", "keyword"]
    hits: list[SearchHit]
    # The sum of both indexes' estimated matches for the artifact-first
    # combined sequence, less semantic-lane hits this moment page's floor
    # discarded. Stale Postgres rows are not subtracted, so this remains an
    # estimate of paging breadth rather than a count of live response rows.
    estimated_total: int
    limit: int
    offset: int
    # Ranked extraction documents (story 12.4), in their own array because
    # they are not citations — see `DocumentHitModel`. They do not consume
    # `limit` against `hits` and are not counted in `estimatedTotal`: the two
    # sequences answer different questions ("where in the corpus was this
    # said" versus "what did the analysis say about it"), and blending them
    # would let unreviewed prose push a citable moment off the page.
    documents: list[DocumentHitModel] = []
    # How many extraction documents matched in total, for the same paging
    # reason `estimatedTotal` exists — reported separately so a caller never
    # reads a document count as a count of citable results.
    documents_total: int = 0
    # True when the moments index does not exist yet — nothing has ever been
    # projected. Distinct from "nothing matched", and on the wire rather than
    # only in the log, because they need different sentences: one asks the
    # operator to ingest a meeting, the other asks the user to try other words
    # (SPEC Constraints, "no silent zero").
    index_missing: bool = False
    # True when the extraction-documents index does not exist yet — a store
    # from before story 12.4, or one wiped and not yet rebuilt. Distinct from
    # "no document matched": the repair is a rebuild, not other words.
    documents_index_missing: bool = False


def _limit_of(request: Request, requested: int | None) -> int:
    """The effective limit, or a 422 naming the configured bound (AD-10)."""
    search = request.app.state.config.settings.api.search
    if requested is None:
        return search.default_limit
    if requested > search.max_limit:
        raise Problem(
            422,
            "invalid-request",
            f"limit {requested} exceeds the configured api.search.max_limit"
            f" of {search.max_limit}",
            # camelCase, like every other problem extension this api emits
            # (`jobId` on the intake conflict) — the boundary convention does
            # not stop at the success payload.
            maxLimit=search.max_limit,
        )
    return requested


def _embed(
    request: Request, query: str
) -> tuple[Any | None, Literal["hybrid", "keyword"]]:
    """Embed the query, degrade on an outage, refuse on a misconfiguration."""
    if request.app.state.config.settings.api.search.semantic_ratio == 0.0:
        # Meilisearch defines a zero ratio as pure keyword search. Do not make
        # that mode depend on the embedding host or report it as hybrid merely
        # because a needless vector was calculated.
        return None, "keyword"
    embedder = request.app.state.embedder
    try:
        return embedder.embed_query(query), "hybrid"
    except EmbedderUnavailableError as exc:
        # The one embedder failure this system is required to survive
        # (`retrieval-prior-art.md` §3 rule 4). Logged rather than swallowed:
        # a search silently losing its vector half must be visible in the log.
        logs.log_event(
            "search.degraded",
            reason="embedder_unavailable",
            model=getattr(embedder, "model", None),
            detail=str(exc),
        )
        return None, "keyword"
    except EmbedderError as exc:
        # A model that answers wrongly is a config error, and no retry fixes
        # it. Refusing by name keeps it from masquerading as a degraded search
        # that would look identical to an Ollama outage in every log line.
        raise Problem(
            503,
            "embedder-unusable",
            f"the configured embedder {getattr(embedder, 'model', 'unknown')!r}"
            f" at {getattr(embedder, 'dimension', 'unknown')} dimensions could"
            f" not embed the query: {exc}",
            title="Service Unavailable",
            model=getattr(embedder, "model", None),
            dimension=getattr(embedder, "dimension", None),
        ) from exc


def _resolve(pool: Any, hits: tuple[MomentHit, ...]) -> list[SearchHit]:
    """Re-read every ranked moment from Postgres, dropping what is gone.

    One statement for the whole page, so the citations in one response come
    from one snapshot rather than from N reads a worker commit could land
    between. Ranking order is the index's, so the rows are re-ordered back to
    the order they arrived in.
    """
    if not hits:
        return []
    ids = [hit.moment_id for hit in hits]
    with pool.connection() as conn:
        rows = conn.execute(_RESOLVE_MOMENTS, (ids,)).fetchall()
    by_id = {row[0]: row for row in rows}

    resolved: list[SearchHit] = []
    for hit in hits:
        row = by_id.get(hit.moment_id)
        if row is None:
            # A document the index still holds for a moment Postgres no
            # longer has. Never returned (it would be a citation resolving
            # nowhere) and never silently discarded either — the id is logged
            # so a stale index is diagnosable, and `make rebuild` is the fix.
            logs.log_event("search.stale_hit", moment_id=hit.moment_id)
            continue
        resolved.append(
            SearchHit(
                moment_id=row[0],
                meeting_id=row[1],
                start_ms=row[2],
                end_ms=row[3],
                started_at=row[4],
                started_at_precision=row[5],
                screenshot_id=row[6],
                source_deep_link=row[7],
                meeting_title=row[8],
                has_recording=row[9],
                corpus=row[10],
                snippet=[
                    SnippetRunModel(text=run.text, highlighted=run.highlighted)
                    for run in hit.snippet
                ],
                score=hit.score,
            )
        )
    return resolved


def _resolve_artifacts(pool: Any, hits: tuple[ArtifactHit, ...]) -> list[SearchHit]:
    """Re-read every ranked artifact from Postgres, through its source moment.

    Same discipline as :func:`_resolve`: one statement for the page, ranking
    order preserved, and a hit whose artifact row is missing or no longer
    ``published`` is dropped and logged (``search.stale_artifact_hit``) rather
    than returned as a citation that resolves nowhere.
    """
    if not hits:
        return []
    ids = [hit.artifact_id for hit in hits]
    with pool.connection() as conn:
        rows = conn.execute(_RESOLVE_ARTIFACTS, (ids, PUBLISHED_STATE)).fetchall()
    by_id = {row[0]: row for row in rows}

    resolved: list[SearchHit] = []
    for hit in hits:
        row = by_id.get(hit.artifact_id)
        if row is None:
            logs.log_event("search.stale_artifact_hit", artifact_id=hit.artifact_id)
            continue
        resolved.append(
            SearchHit(
                artifact_id=row[0],
                artifact_kind=row[1],
                artifact_title=row[2],
                moment_id=row[3],
                meeting_id=row[4],
                start_ms=row[5],
                end_ms=row[6],
                started_at=row[7],
                started_at_precision=row[8],
                screenshot_id=row[9],
                source_deep_link=row[10],
                meeting_title=row[11],
                has_recording=row[12],
                corpus=row[13],
                snippet=[
                    SnippetRunModel(text=run.text, highlighted=run.highlighted)
                    for run in hit.snippet
                ],
                score=hit.score,
            )
        )
    return resolved


def _resolve_documents(pool: Any, hits: tuple[DocumentHit, ...]) -> list[DocumentHitModel]:
    """Re-read every ranked extraction document from Postgres, dropping what is gone.

    The same discipline as :func:`_resolve` and :func:`_resolve_artifacts`: one
    statement for the page, ranking order preserved, a hit whose row is gone
    dropped and logged rather than returned. Postgres is the database of record
    for a document exactly as it is for a moment (AD-2) — the index ranks, the
    row says what is true.

    ``reviewState``/``authorship``/``reviewLabel`` come off the *hit* rather
    than being reconstructed here. They were written into the indexed record on
    purpose (AD-4's exception is to reach, never to legibility), and a route
    that regenerated them would make an unlabelled record render exactly like a
    labelled one — which is the failure that labelling exists to prevent.
    """
    if not hits:
        return []
    ids = [hit.document_id for hit in hits]
    with pool.connection() as conn:
        rows = conn.execute(_RESOLVE_DOCUMENTS, (ids,)).fetchall()
    by_id = {row[0]: row for row in rows}

    resolved: list[DocumentHitModel] = []
    for hit in hits:
        row = by_id.get(hit.document_id)
        if row is None:
            logs.log_event("search.stale_document_hit", document_id=hit.document_id)
            continue
        if row[1] != hit.meeting_id or row[12] != hit.corpus:
            logs.log_event(
                "search.stale_document_scope",
                document_id=hit.document_id,
                indexed_meeting_id=hit.meeting_id,
                postgres_meeting_id=row[1],
                indexed_corpus=hit.corpus,
                postgres_corpus=row[12],
            )
            continue
        if row[10] != hit.sha256:
            logs.log_event(
                "search.stale_document_version",
                document_id=hit.document_id,
                indexed_sha256=hit.sha256,
                postgres_sha256=row[10],
            )
            continue
        resolved.append(
            DocumentHitModel(
                document_id=row[0],
                meeting_id=row[1],
                kind=row[2],
                origin=row[3],
                model=row[4],
                prompt_hash=row[5],
                layout=row[6],
                item_count=row[7],
                artifact_count=row[8],
                byte_size=row[9],
                meeting_title=row[11],
                corpus=row[12],
                review_state=hit.review_state,
                authorship=hit.authorship,
                review_label=hit.review_label,
                citable=False,
                snippet=[
                    SnippetRunModel(text=run.text, highlighted=run.highlighted)
                    for run in hit.snippet
                ],
                score=hit.score,
            )
        )
    return resolved


@router.get(
    "/search",
    operation_id="searchCorpus",
    response_model=SearchResponse,
    responses={
        422: {
            "model": ProblemDetails,
            "content": {"application/problem+json": {}},
            "description": "`invalid-request` — a parameter was refused at the"
            " door rather than silently repaired.",
        },
        503: {
            "model": ProblemDetails,
            "content": {"application/problem+json": {}},
            # Four slugs share this status, and the slug is the diagnosis: it
            # says which process to restart. `embedder-unusable` is a
            # misconfigured model; `search-store-unavailable` is a Meilisearch
            # that cannot be reached; `search-store-unusable` is one that
            # answered and refused (or was never authenticated).
            "description": "`embedder-unusable` — the configured embedding"
            " model answered wrongly, which is a config error rather than an"
            " outage. `search-store-unavailable` — Meilisearch could not be"
            " reached. `search-store-unusable` — Meilisearch is reachable but"
            " the query could not be run against it (no `MEILI_MASTER_KEY`, a"
            " refused query, or a document with no id).",
        },
    },
)
def search_corpus(
    request: Request,
    q: Annotated[SearchTerm, Query(description="What to search the corpus for.")],
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    meeting_id: Annotated[
        UUID | None,
        Query(alias="meetingId", description="Scope the search to one meeting."),
    ] = None,
    corpus: Annotated[
        Corpus | None, Query(description="Scope the search to one corpus.")
    ] = None,
) -> SearchResponse:
    config = request.app.state.config
    effective_limit = _limit_of(request, limit)
    query_vector, ranking = _embed(request, q)

    try:
        # Built per request rather than held on app.state: `meili_client`
        # health-checks, so a store that went down after startup is a named
        # 503 here instead of a connection error surfacing from the query.
        client = meili_client(config)
        # One stable combined sequence: every ranked artifact, followed by
        # every ranked moment. The artifact total tells us how much of the
        # caller's global offset belongs to that finite leading lane; scores
        # from the independent indexes are never blended.
        artifact_result = search_artifacts(
            client,
            config,
            query=q,
            limit=effective_limit,
            offset=offset,
            meeting_id=meeting_id,
            corpus=corpus,
        )
        # The extraction-document lane is independent of the combined
        # artifact/moment sequence and takes the caller's `offset` unchanged:
        # documents are not citations, do not compete with moments for the
        # page, and must not shift where the citable sequence starts.
        document_result = search_documents(
            client,
            config,
            query=q,
            limit=effective_limit,
            offset=offset,
            meeting_id=meeting_id,
            corpus=corpus,
        )
        moment_offset = max(offset - artifact_result.total, 0)
        result = search_moments(
            client,
            config,
            query=q,
            limit=effective_limit,
            offset=moment_offset,
            meeting_id=meeting_id,
            corpus=corpus,
            query_vector=query_vector,
        )
    except StoreUnavailableError as exc:
        raise Problem(
            503,
            "search-store-unavailable",
            f"the search index could not be reached: {exc}",
            title="Service Unavailable",
        ) from exc
    except ProjectionError as exc:
        # Reachable but unusable, which is a different repair from an outage:
        # `meili_client` raises this when MEILI_MASTER_KEY is unset, and
        # `search_moments` raises it when the store refuses the query or
        # returns a document with no id. `StoreUnavailableError` is a subclass,
        # so this clause must stay *after* it — otherwise every outage would be
        # reported under the wrong slug. Without this branch the whole family
        # escaped as an opaque 500 with a traceback.
        raise Problem(
            503,
            "search-store-unusable",
            f"the search index could not be queried: {exc}",
            title="Service Unavailable",
        ) from exc

    if result.index_missing:
        # An index that was never built holds nothing, which is a different
        # statement from "nothing matched" — so it is logged rather than
        # reported as a bare zero (SPEC Constraints, "no silent zero").
        logs.log_event("search.index_missing", query=q)

    if artifact_result.index_missing:
        # A store from before the artifacts index existed (or one wiped and
        # not yet rebuilt) holds nothing published — logged apart from the
        # moments-index case because the repair is a targeted rebuild.
        logs.log_event("search.artifacts_index_missing", query=q)
    if document_result.index_missing:
        # A store from before story 12.4 (or one wiped and not yet rebuilt)
        # holds no extraction documents. Logged apart from the two above
        # because the repair is a targeted rebuild and because a silent zero
        # here would read as "the analysis says nothing about this".
        logs.log_event("search.documents_index_missing", query=q)
    artifact_hits = _resolve_artifacts(request.app.state.pool, artifact_result.hits)
    document_hits = _resolve_documents(request.app.state.pool, document_result.hits)
    document_stale_dropped = len(document_result.hits) - len(document_hits)
    # Meilisearch's exhaustive count includes rows Postgres just proved stale.
    # Subtract the stale rows observed on this page so a sole corrupt match is
    # not reported as "1 document" beside an empty document list.
    live_documents_total = max(
        document_result.total - document_stale_dropped,
        len(document_hits),
    )

    moment_hits = _resolve(request.app.state.pool, result.hits)
    stale_dropped = len(result.hits) - len(moment_hits)
    # Artifacts first: a published artifact is distilled, human-approved
    # knowledge, and this lane only returns keyword matches on short,
    # title-rich documents — when one matches, it is the headline answer.
    # The combined page never exceeds the caller's limit: artifacts lead,
    # moments fill whatever capacity is left (never negative — an artifact
    # lane fetched up to `effective_limit` cannot itself exceed it). This is
    # capacity truncation, distinct from a stale hit dropped because its
    # underlying row vanished — logged separately so neither obscures the
    # other.
    # Raw artifact slots, including stale documents dropped by Postgres, stay
    # consumed in this store-ranked sequence. Letting a moment fill a stale
    # slot would repeat that moment on the next global page once the offset
    # crosses the artifact lane.
    moment_capacity = max(effective_limit - len(artifact_result.hits), 0)
    capacity_truncated = max(len(moment_hits) - moment_capacity, 0)
    moment_hits = moment_hits[:moment_capacity]
    hits = [*artifact_hits, *moment_hits]
    logs.log_event(
        "search.completed",
        query=q,
        ranking=ranking,
        ranked=len(result.hits),
        returned=len(moment_hits),
        dropped=stale_dropped,
        capacity_truncated=capacity_truncated,
        artifact_ranked=len(artifact_result.hits),
        artifact_returned=len(artifact_hits),
        # Counted apart from the two citable lanes, never folded into them: a
        # document reached the reader without passing the publish gate, and a
        # log line that hid that inside one total would be the only record of
        # the exception saying nothing about it (AD-4).
        documents_ranked=len(document_result.hits),
        documents_returned=len(document_hits),
        documents_dropped=document_stale_dropped,
        documents_total=live_documents_total,
        total_returned=len(hits),
        below_floor=result.below_floor,
        meeting_id=meeting_id,
        corpus=corpus,
    )
    return SearchResponse(
        query=q,
        ranking=ranking,
        hits=hits,
        documents=document_hits,
        documents_total=live_documents_total,
        estimated_total=artifact_result.total + result.estimated_total,
        limit=effective_limit,
        offset=offset,
        index_missing=result.index_missing,
        documents_index_missing=document_result.index_missing,
    )
