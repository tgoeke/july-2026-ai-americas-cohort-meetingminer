"""POST /chat — cited Q&A over the evidence corpus (story 3.3, FR13/FR14, NFR4).

The spine's cited-Q&A sequence, in one module: classify the question onto a
registered traversal template, retrieve deterministically from Neo4j and
Meilisearch, synthesize through the config-bound ``Llm(chat)`` port, and put the
draft through the deterministic citation gate before anything reaches the wire.

**Validate first, stream second.** The SSE surface (``chat.token`` /
``chat.citations`` / ``chat.done``) replays an answer the gate has *already*
passed, chunk by chunk. That is why the ``Llm`` port needs no streaming method
and why a rejected answer cannot leak token by token: when the gate refuses, the
stream never opens and the client receives the same ``422``
``application/problem+json`` a JSON caller would. Content negotiation on
``Accept`` keeps one endpoint for both — the eval harness reads the structured
array (AD-16), the browser reads the stream.

**Nothing here spends money on a question the corpus cannot answer.** Retrieval
runs before synthesis, and an empty retrieval is refused with
``reason: no-evidence``. The classifier is a model call too, so it is preceded by
a guard that needs no model at all: with no moment row in Postgres, neither leg
could produce a candidate and no draft could pass the gate, so the request is
refused without contacting a provider.

**No store client is imported here** (AD-4). Meilisearch is reached through
``projections.query.search_moments`` and Neo4j through
``projections.traversals.run_template``, exactly as ``api/search.py`` reaches the
index — the property ``test_projections_single_writer.py`` asserts by AST walk.

**Postgres cites.** Every field on every citation — ``momentId``, ``meetingId``,
``startMs``, ``endMs``, ``screenshotId``, ``sourceDeepLink`` — is read from the
database of record inside this request (AD-6, AD-15). Neo4j and Meilisearch
decide *which* moments are candidates and nothing else; the model's text decides
nothing at all.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Iterable, Literal, Mapping, Sequence
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import EventSourceResponse
from fastapi.sse import format_sse_event
from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.adapters.embed import EmbedderError, EmbedderUnavailableError
from meetingminer.adapters.llm import (
    LlmError,
    LlmModelNotServedError,
    LlmUnavailableError,
    build_llm,
)
from meetingminer.api.chat_router import (
    TEMPLATE_ANCHORS,
    RouteDecision,
    build_classifier_prompt,
    parse_route,
)
from meetingminer.api.citations import (
    MomentCitation,
    Rejection,
    ValidatedAnswer,
    validate,
)
from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.domain import model_selection
from meetingminer.projections.publish_gate import PUBLISHED_STATE
from meetingminer.projections.query import (
    search_artifacts,
    search_documents,
    search_moments,
)
from meetingminer.projections.stores import (
    ProjectionError,
    StoreUnavailableError,
    meili_client,
    neo4j_driver,
)
from meetingminer.projections.traversals import SCREEN_HISTORY, run_template

router = APIRouter()
ROUTER_ORDER = 60

# The three pinned SSE event names (spine, "Cross-Cutting Conventions"). Named
# constants so a rename is a deliberate edit here rather than a typo in a format
# string — the same reasoning `api/events.py` records for the job stream.
EVENT_TOKEN = "chat.token"
EVENT_CITATIONS = "chat.citations"
EVENT_DONE = "chat.done"
WIRE_EVENT_NAMES: tuple[str, ...] = (EVENT_TOKEN, EVENT_CITATIONS, EVENT_DONE)

# The one rejection slug. Story 3.4 renders a single "no citable answer" state
# from it and reads the `reason` extension to say which kind.
NO_CITABLE_ANSWER = "no-citable-answer"

# A question is longer than a search term — it is a sentence, not a phrase — but
# it is still forwarded to the embedder, to Meilisearch, into two model prompts
# and into every log line this request writes. 1000 characters is far past any
# question a person types and far short of a payload that would be all of those
# at once. `strip_whitespace` before `min_length` is what makes a whitespace-only
# question a 422 rather than a search for a space.
CHAT_QUESTION_MAX_LENGTH = 1000
ChatQuestion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=CHAT_QUESTION_MAX_LENGTH
    ),
]

# --- the Postgres reads ----------------------------------------------------

# Whether the corpus holds any moment at all. The guard that lets an empty
# corpus be refused *before* the classifier's model call: with no moment rows,
# no leg can produce a citation, so no answer could pass the gate and there is
# nothing to spend a provider call on. An index-only check would not do — the
# question is what Postgres can cite, not what a projection currently holds.
#
# "Any moment" means any *citable* moment. A superseded row still exists so an
# existing citation stays resolvable (`pipeline/stages/moments.py`), but no new
# answer may be sent to it, so a corpus holding only superseded rows can cite
# nothing and must not bill a classification call to discover that.
_LIVE_MOMENT = "COALESCE(m.provenance->>'superseded', '') <> 'true'"

_ANY_MOMENT = f"SELECT EXISTS (SELECT 1 FROM moment m WHERE {_LIVE_MOMENT})"

# One statement for the whole retrieved set, so the context a model reads and
# the rows the gate resolves come from one snapshot. The text is assembled the
# way `projections/evidence.py:read_meeting` assembles it — "<speaker>: <text>"
# joined by newline, in the segments' own `ordinal` order — so a moment reads
# the same here as it does everywhere else in the system. LEFT JOIN on the
# segment hops: a screen-derived moment may legitimately cover no segment, and
# it still carries a screenshot worth citing.
_MOMENT_CONTEXT = (
    "SELECT m.id, m.meeting_id, m.start_ms, m.end_ms, m.screenshot_id,"
    " m.source_deep_link, mt.title, mt.started_at,"
    " COALESCE(m.provenance->>'superseded', '') = 'true',"
    " string_agg("
    "   COALESCE(NULLIF(btrim(ts.speaker_label), ''), 'Unknown')"
    "   || ': ' || btrim(ts.text), chr(10) ORDER BY ts.ordinal)"
    " FROM moment m"
    " JOIN meeting mt ON mt.id = m.meeting_id"
    " LEFT JOIN moment_segment ms ON ms.moment_id = m.id"
    " LEFT JOIN transcript_segment ts ON ts.id = ms.transcript_segment_id"
    "  AND ts.meeting_id = m.meeting_id"
    " WHERE m.id = ANY(%s)"
    " GROUP BY m.id, m.meeting_id, m.start_ms, m.end_ms, m.screenshot_id,"
    "  m.source_deep_link, mt.title, mt.started_at, m.provenance"
)

# The citation read the gate calls with the ids the model actually cited. A
# second read rather than a reuse of the context rows, deliberately: AD-6 says
# every citation field is re-resolved *in the same request that emits it*, and a
# moment deleted between retrieval and synthesis has to be caught here rather
# than served from a value read minutes of model latency earlier. The join is
# required, not left: a moment whose meeting row is gone is not a citation.
_RESOLVE_MOMENTS = (
    "SELECT m.id, m.meeting_id, m.start_ms, m.end_ms, m.screenshot_id,"
    " m.source_deep_link"
    " FROM moment m JOIN meeting mt ON mt.id = m.meeting_id"
    " WHERE m.id = ANY(%s)"
    # The same live-moment clause `_MOMENT_CONTEXT` filters on, repeated here
    # rather than inherited: this is the statement the *gate* resolves against,
    # and a moment superseded in the window between the context read and
    # validation would otherwise be emitted as a citation into evidence
    # `api/moments.py` renders as superseded.
    f" AND {_LIVE_MOMENT}"
)

# Name-to-id resolution, the router's job (story 3.2's `_input_uuid` says so in
# as many words). Exact match on either name column first, a contained-substring
# match over the *same* two columns second, and never more than two rows: the
# third selected column says whether the row matched exactly, and two rows that
# are equally exact are an ambiguous anchor rather than a guess.
#
# `ESCAPE '\'` with a `\`-escaped needle, because the anchor text is written by
# a model: an unescaped `%` in it is a pattern matching every row, and with
# `LIMIT 2` that would dispatch the traversal onto an arbitrary person. The
# escape character has to be declared — Postgres' `LIKE` default is backslash
# already, but stating it keeps the statement correct under any
# `standard_conforming_strings` setting.
#
# The trailing `id` in each ORDER BY makes the two-row window deterministic:
# without it the ambiguity check would see a different pair run to run.
_RESOLVE_PARTICIPANT = (
    "SELECT id, display_name,"
    " (normalized_name = %(needle)s OR lower(display_name) = %(needle)s)"
    " FROM participant"
    " WHERE normalized_name = %(needle)s OR lower(display_name) = %(needle)s"
    "    OR normalized_name LIKE %(contains)s ESCAPE '\\'"
    "    OR lower(display_name) LIKE %(contains)s ESCAPE '\\'"
    " ORDER BY 3 DESC, normalized_name, id"
    " LIMIT 2"
)

# The published-artifact context read (story 4.4). Re-read from Postgres, not
# served from the index (AD-2/AD-6), and re-filtered on `state = 'published'`:
# a document surviving in the artifacts index for a row that is gone or no
# longer published contributes nothing to the prompt. `moment_id` is what
# folds the artifact into its source moment's context block — the citation
# stays moment-typed, so `CitationModel` and the marker grammar are untouched.
_ARTIFACT_CONTEXT = (
    "SELECT a.id, a.moment_id, a.kind, a.title, a.body"
    " FROM artifact a"
    " WHERE a.id = ANY(%s) AND a.state = %s"
)

# The extraction-document context read (story 12.4). Re-read from Postgres for
# the same reason the artifact read is (AD-2), and re-filtered on
# `document_text IS NOT NULL`: a record surviving in the documents index for a
# row whose text is gone contributes nothing to a prompt.
#
# Keyed by *meeting*, not by moment, because a document has no moment — that is
# the whole of AD-6 as it applies here. What it means in the prompt is that a
# document is folded into the blocks of the moments retrieval already found in
# that meeting, as labelled, explicitly uncitable context. The only marker the
# model can emit is still a moment's, so the citation grammar, `CitationModel`
# and the gate are untouched by this leg.
_DOCUMENT_CONTEXT = (
    "SELECT es.id, es.meeting_id, es.kind, es.model, es.item_count,"
    " es.document_text"
    " FROM extraction_source es"
    " WHERE es.id = ANY(%s) AND es.document_text IS NOT NULL"
)

_RESOLVE_PARTICIPANT_BY_ID = (
    "SELECT id, display_name, true FROM participant WHERE id = %s"
)

# `screen.label` is the human-editable name (Epic 2) and `identity_key` the
# content hash the pipeline mints; a question names the first, an operator
# pasting from a log names the second. Both are matched exactly and both are
# matched by substring, so neither door is half open.
_RESOLVE_SCREEN = (
    "SELECT id, COALESCE(label, identity_key),"
    " (identity_key = %(needle)s OR lower(label) = %(needle)s)"
    " FROM screen"
    " WHERE identity_key = %(needle)s OR lower(label) = %(needle)s"
    "    OR lower(label) LIKE %(contains)s ESCAPE '\\'"
    "    OR identity_key LIKE %(contains)s ESCAPE '\\'"
    " ORDER BY 3 DESC, id"
    " LIMIT 2"
)

_RESOLVE_SCREEN_BY_ID = (
    "SELECT id, COALESCE(label, identity_key), true FROM screen WHERE id = %s"
)


# --- wire models -----------------------------------------------------------


class ChatRequest(BaseModel):
    """One question. camelCase in, like every other body this api takes."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    question: ChatQuestion


class CitationModel(BaseModel):
    """AD-15's citation, and exactly AD-15's citation.

    Six fields, no more: the web app and the eval harness both consume this
    array, and a field added here for one consumer's convenience is a field the
    other starts depending on. ``screenshotId`` is absent on a transcript-only
    meeting, where ``sourceDeepLink`` carries UX-DR11's transitional affordance
    in its place — consumers read the fields rather than assuming replay exists.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    moment_id: UUID
    meeting_id: UUID
    start_ms: int
    end_ms: int
    screenshot_id: UUID | None = None
    source_deep_link: str | None = None


class RouteModel(BaseModel):
    """What the router decided and what each leg produced.

    On the wire rather than only in the log: an operator comparing two answers
    to the same question has to be able to see that one was traversed and the
    other was not, and story 3.4 shows "answered from N moments" without a
    second round trip.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # The registered template that was dispatched, or null for search-only.
    template: str | None = None
    # Null when no template was dispatched *or* when dispatch never reached
    # anchor resolution; false when one was dispatched and its anchor matched no
    # row — 3.2's distinction, carried to the wire rather than collapsed into
    # "nothing found" (SPEC Constraints, "no silent zero").
    anchor_resolved: bool | None = None
    # Why the traversal leg produced what it produced, as a closed set — see
    # `TRAVERSAL_OUTCOMES`. `anchor_resolved` cannot carry this on its own: a
    # template whose *input* the registry refused is a routing failure, and
    # reporting it as `false` would have story 3.4 render "the corpus does not
    # know that person" for a question the router simply mis-filled.
    traversal_outcome: str = "not-dispatched"
    # Which `chat_router.FALLBACK_REASONS` entry produced a search-only route.
    fallback_reason: str | None = None
    search_hits: int
    traversal_rows: int
    # True when the template found more rows than `api.chat.traversal_row_limit`
    # and this answer saw only some of them. On the wire because silent
    # truncation is the sibling of the silent zero this story is built to
    # refuse: "found exactly the cap" and "found more and dropped some" are
    # different answers and must not look identical.
    traversal_truncated: bool = False
    # Distinct moments that survived the Postgres read-back and reached the
    # synthesis prompt. The upper bound on how many citations can exist.
    retrieved: int


class ChatResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    question: str
    # Markers stripped: the citation array is the contract, and the web app
    # never parses `[[moment:...]]` out of prose (AD-15).
    answer: str
    citations: list[CitationModel]
    route: RouteModel


class ChatTokenEvent(BaseModel):
    """A ``chat.token`` payload: one chunk of the already-validated answer.

    ``event`` repeats the SSE event name inside the payload for the same reason
    ``api/events.py`` does it — the generated TypeScript client yields event
    *data* without the name attached.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    event: Literal["chat.token"] = EVENT_TOKEN
    text: str


class ChatCitationsEvent(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    event: Literal["chat.citations"] = EVENT_CITATIONS
    citations: list[CitationModel]


class ChatDoneEvent(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    event: Literal["chat.done"] = EVENT_DONE
    route: RouteModel


# --- retrieval -------------------------------------------------------------


@dataclass(frozen=True)
class RetrievedMoment:
    """One moment that survived the Postgres read-back, with its prompt text."""

    citation: MomentCitation
    meeting_title: str | None
    # The meeting's wall clock. In the prompt because the questions these
    # templates answer are questions about *when* — "did I already explain this",
    # "when did we last look at this" — asked over recurring meetings that share
    # a title, and an intra-meeting offset alone cannot tell two of them apart.
    meeting_started_at: datetime | None
    text: str


@dataclass(frozen=True)
class RetrievedArtifact:
    """One published artifact folded into its source moment's context block."""

    moment_id: UUID
    kind: str
    title: str
    body: str


@dataclass(frozen=True)
class RetrievedDocument:
    """One extraction document folded into its meeting's context blocks.

    **Never a citation** (AD-6, story 12.4). It carries no moment id because it
    has none: a document is a claim *about* evidence, and citing it would
    establish that the model said something rather than that the meeting did.
    It reaches an answer only through the moments its claims anchor to, which
    the prompt makes explicit and the citation gate enforces regardless.

    ``review_label`` travels with it so the prompt can say, in the block
    itself, that this text is unreviewed machine output — the same labelling
    requirement the indexed record and every rendering surface carry (AD-18).
    """

    document_id: UUID
    meeting_id: UUID
    kind: str
    model: str | None
    item_count: int
    review_label: str
    text: str


@dataclass(frozen=True)
class Anchor:
    """A resolved traversal anchor: the Postgres id and its display name."""

    id: UUID
    label: str


# What the traversal leg did, as a closed set. Reported on the wire (success and
# rejection alike) so a caller never has to infer a routing failure from an
# empty result.
TRAVERSAL_OUTCOMES: tuple[str, ...] = (
    # The classifier named no registered template; the search leg answered alone.
    "not-dispatched",
    # Dispatched, anchor resolved. Zero rows here is a *valid empty answer*.
    "resolved",
    # Dispatched, but the anchor matched no participant/screen — in Postgres or
    # in the graph. Distinct from "resolved with no rows" (3.2's distinction).
    "anchor-unknown",
    # Dispatched with parameters `run_template` refused. A routing miss, not a
    # statement about the corpus.
    "input-refused",
)


@dataclass(frozen=True)
class TraversalLeg:
    """One traversal leg's whole result, including what it had to drop."""

    ids: tuple[UUID, ...] = ()
    outcome: str = "not-dispatched"
    # Rows the template returned before `traversal_row_limit` was applied.
    available: int = 0

    @property
    def truncated(self) -> bool:
        return self.available > len(self.ids)

    @property
    def anchor_resolved(self) -> bool | None:
        """True/False only where anchor resolution actually happened."""
        if self.outcome == "resolved":
            return True
        if self.outcome == "anchor-unknown":
            return False
        return None


def _wants_stream(request: Request) -> bool:
    """Whether this caller asked for the SSE surface.

    JSON remains the default: only an explicitly acceptable SSE media range
    opens the stream. The small parser deliberately needs only the one media
    type this endpoint serves, but respects an explicit ``q=0`` exclusion.
    """
    for media_range in request.headers.get("accept", "").lower().split(","):
        parts = [part.strip() for part in media_range.split(";")]
        if parts[0] != "text/event-stream":
            continue
        quality = 1.0
        for parameter in parts[1:]:
            key, separator, value = parameter.partition("=")
            if key.strip() != "q" or not separator:
                continue
            try:
                quality = float(value.strip())
            except ValueError:
                quality = 0.0
        return quality > 0.0
    return False


def _embed(request: Request, question: str) -> Any | None:
    """Embed the question, degrade on an outage, refuse on a misconfiguration.

    The same split ``api/search.py`` applies, for the same reasons:
    ``EmbedderUnavailableError`` is the one embedder failure this system is
    required to survive, and the retrieval degrades to keyword-only and says so
    in the log; ``EmbedderError`` is a configured model answering *wrongly*,
    which no retry fixes and which must not masquerade as an outage.
    """
    if request.app.state.config.settings.api.search.semantic_ratio == 0.0:
        return None
    embedder = request.app.state.embedder
    try:
        return embedder.embed_query(question)
    except EmbedderUnavailableError as exc:
        logs.log_event(
            "chat.degraded",
            reason="embedder_unavailable",
            model=getattr(embedder, "model", None),
            detail=str(exc),
        )
        return None
    except EmbedderError as exc:
        raise Problem(
            503,
            "embedder-unusable",
            f"the configured embedder {getattr(embedder, 'model', 'unknown')!r}"
            f" at {getattr(embedder, 'dimension', 'unknown')} dimensions could"
            f" not embed the question: {exc}",
            title="Service Unavailable",
            model=getattr(embedder, "model", None),
            dimension=getattr(embedder, "dimension", None),
        ) from exc


def _search_leg(
    request: Request, terms: str, query_vector: Any | None
) -> tuple[UUID, ...]:
    """Rank the moments index for ``terms`` and return the ids, in rank order."""
    config = request.app.state.config
    try:
        # Built per request rather than held on app.state, like `/search`: the
        # client health-checks, so a store that went down after startup is a
        # named 503 here instead of a connection error out of the query.
        client = meili_client(config)
        result = search_moments(
            client,
            config,
            query=terms,
            limit=config.settings.api.chat.retrieval_limit,
            query_vector=query_vector,
        )
    except StoreUnavailableError as exc:
        raise Problem(
            503,
            "chat-search-store-unavailable",
            f"the search index could not be reached: {exc}",
            title="Service Unavailable",
            store="meilisearch",
        ) from exc
    except ProjectionError as exc:
        # `StoreUnavailableError` is a subclass, so this clause must stay after
        # it or every outage would be reported under the wrong slug.
        raise Problem(
            503,
            "chat-search-store-unusable",
            f"the search index could not be queried: {exc}",
            title="Service Unavailable",
            store="meilisearch",
        ) from exc
    if result.index_missing:
        # Never projected is a different statement from nothing matched, and it
        # asks the operator for a different action. The field is `terms`, not
        # `question`: every other chat log line uses `question` for what the
        # person actually asked, and the index was queried with the classifier's
        # words.
        logs.log_event("chat.index_missing", terms=terms)
    hits = tuple(hit.moment_id for hit in result.hits)
    logs.log_event(
        "chat.search_completed",
        terms=terms,
        ranking="hybrid" if query_vector is not None else "keyword",
        ranked=len(hits),
        # Carried the way `api/search.py` carries it: the story's matrix names
        # "index empty" and "all hits floored" as one refusal, and without this
        # they write identical log lines while asking for different repairs.
        below_floor=result.below_floor,
        index_missing=result.index_missing,
    )
    return hits


def _artifact_leg(request: Request, terms: str) -> tuple[UUID, ...]:
    """Rank the published-artifacts index for ``terms`` (story 4.4).

    Keyword-only — the artifacts index declares no embedder — and
    published-only, pinned in the query's own filter on top of the publish
    gate. Returns ranked artifact ids; everything else is re-read from
    Postgres by :func:`_read_artifact_context`. A missing index is an empty
    leg, logged: a store from before story 4.4 holds nothing published.

    Deliberately unscoped by meeting/corpus, matching :func:`_search_leg`:
    `/chat` accepts no `meetingId`/`corpus` on `ChatRequest` today, so neither
    retrieval leg can be scoped, and this one should not invent a filter its
    sibling lacks.
    """
    config = request.app.state.config
    try:
        client = meili_client(config)
        result = search_artifacts(
            client,
            config,
            query=terms,
            limit=config.settings.api.chat.retrieval_limit,
        )
    except StoreUnavailableError as exc:
        raise Problem(
            503,
            "chat-search-store-unavailable",
            f"the search index could not be reached: {exc}",
            title="Service Unavailable",
            store="meilisearch",
        ) from exc
    except ProjectionError as exc:
        raise Problem(
            503,
            "chat-search-store-unusable",
            f"the search index could not be queried: {exc}",
            title="Service Unavailable",
            store="meilisearch",
        ) from exc
    if result.index_missing:
        logs.log_event("chat.artifacts_index_missing", terms=terms)
    hits = tuple(hit.artifact_id for hit in result.hits)
    logs.log_event(
        "chat.artifact_search_completed",
        terms=terms,
        ranked=len(hits),
        index_missing=result.index_missing,
    )
    return hits


def _read_artifact_context(
    pool: Any, ids: Sequence[UUID]
) -> dict[UUID, tuple[RetrievedArtifact, ...]]:
    """Re-read ranked artifacts from Postgres, grouped by source moment.

    The same two-store discipline as :func:`_read_context`: a ranked id whose
    row is missing or no longer ``published`` is dropped and logged, never
    prompted. What survives is keyed by ``moment_id`` so each artifact's
    title/body lands inside its source moment's context block — the citation
    the answer emits is that moment's, through the unchanged gate.
    """
    if not ids:
        return {}
    with pool.connection() as conn:
        rows = conn.execute(_ARTIFACT_CONTEXT, (list(ids), PUBLISHED_STATE)).fetchall()
    by_id = {row[0]: row for row in rows}
    found = set(by_id)
    for artifact_id in ids:
        if artifact_id not in found:
            logs.log_event("chat.stale_artifact_hit", artifact_id=artifact_id)
    grouped: dict[UUID, tuple[RetrievedArtifact, ...]] = {}
    # PostgreSQL's ANY read has no ranking order of its own. Reconstruct the
    # Meilisearch order explicitly before grouping, so both cross-moment and
    # same-moment prompt cropping favor the better-ranked artifact.
    for artifact_id in ids:
        row = by_id.get(artifact_id)
        if row is None:
            continue
        artifact = RetrievedArtifact(
            moment_id=row[1], kind=row[2], title=row[3], body=row[4]
        )
        grouped[artifact.moment_id] = (*grouped.get(artifact.moment_id, ()), artifact)
    return grouped


def _document_leg(request: Request, terms: str) -> tuple[tuple[UUID, str], ...]:
    """Rank the extraction-documents index for ``terms`` (story 12.4).

    Keyword-only, and **ungated** — AD-4's one deliberate exception: every
    extraction document is retrievable as soon as it is stored, approved or
    not, because the run whose text somebody needs to read is exactly the run
    that yielded nothing worth approving.

    What this leg returns is not evidence and never becomes a citation. It
    returns (document id, review label) pairs; :func:`_read_document_context`
    re-reads the text from Postgres, and the prompt folds it into the blocks of
    moments retrieval already found in the same meeting, labelled as
    unreviewed and explicitly uncitable. **This leg contributes no moment
    ids**, so it cannot widen what an answer may cite — only what the model has
    read while writing it.

    Deliberately unscoped by meeting/corpus, matching the other two legs:
    `/chat` accepts no `meetingId`/`corpus` on `ChatRequest` today.
    """
    config = request.app.state.config
    try:
        client = meili_client(config)
        result = search_documents(
            client,
            config,
            query=terms,
            limit=config.settings.api.chat.retrieval_limit,
        )
    except StoreUnavailableError as exc:
        raise Problem(
            503,
            "chat-search-store-unavailable",
            f"the search index could not be reached: {exc}",
            title="Service Unavailable",
            store="meilisearch",
        ) from exc
    except ProjectionError as exc:
        raise Problem(
            503,
            "chat-search-store-unusable",
            f"the search index could not be queried: {exc}",
            title="Service Unavailable",
            store="meilisearch",
        ) from exc
    if result.index_missing:
        logs.log_event("chat.documents_index_missing", terms=terms)
    hits = tuple((hit.document_id, hit.review_label) for hit in result.hits)
    logs.log_event(
        "chat.document_search_completed",
        terms=terms,
        ranked=len(hits),
        index_missing=result.index_missing,
        # Stated in the log: this leg read material that passed no publish
        # gate, and an operator reading a chat trace should see that here
        # rather than have to know AD-4.
        gate="bypassed (AD-4 extraction-document exception)",
    )
    return hits


def _read_document_context(
    pool: Any, hits: Sequence[tuple[UUID, str]]
) -> dict[UUID, tuple[RetrievedDocument, ...]]:
    """Re-read ranked extraction documents from Postgres, grouped by meeting.

    Grouped by *meeting* rather than by moment because a document has no
    moment — the point of AD-6 as it applies to documents. A ranked id whose
    row is gone (or whose text was never retained) is dropped and logged, never
    prompted.

    The review label comes from the *hit*, not from a constant re-read here:
    it was written into the indexed record so that it could not be lost between
    the store and a reader, and regenerating it in every consumer would defeat
    that (AD-18).
    """
    if not hits:
        return {}
    ids = [document_id for document_id, _label in hits]
    labels = dict(hits)
    with pool.connection() as conn:
        rows = conn.execute(_DOCUMENT_CONTEXT, (ids,)).fetchall()
    by_id = {row[0]: row for row in rows}
    for document_id in ids:
        if document_id not in by_id:
            logs.log_event("chat.stale_document_hit", document_id=document_id)
    grouped: dict[UUID, tuple[RetrievedDocument, ...]] = {}
    # Meilisearch order, reconstructed before grouping, so the per-meeting
    # prompt budget favours the better-ranked document.
    for document_id in ids:
        row = by_id.get(document_id)
        if row is None:
            continue
        document = RetrievedDocument(
            document_id=row[0],
            meeting_id=row[1],
            kind=row[2],
            model=row[3],
            item_count=row[4],
            review_label=labels[document_id],
            text=row[5],
        )
        grouped[document.meeting_id] = (
            *grouped.get(document.meeting_id, ()),
            document,
        )
    return grouped


def _normalized_name(value: str) -> str:
    """The participant roster's matching key, from a name written any way.

    ``participant.normalized_name`` is written as "first last", casefolded, from
    a display name the transcript may have written "Last, First". A question
    writes it either way, so the same flip is applied here — one definition of
    the key, applied on both sides.
    """
    name = value.strip()
    if "," in name:
        last, first = (part.strip() for part in name.split(",", 1))
        name = f"{first} {last}"
    return " ".join(name.split()).casefold()


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value.strip())
    except (ValueError, AttributeError, TypeError):
        return None


def like_contains(needle: str) -> str:
    """A `LIKE` pattern matching ``needle`` anywhere, with its wildcards defused.

    The anchor text is model-written, so it is data and must never act as a
    pattern: a bare ``%`` would match every row and — behind ``LIMIT 2`` — hand
    the traversal an arbitrary participant, which is precisely the guess
    :func:`_resolve_anchor` exists to refuse. Backslash first, or the escapes
    added for ``%`` and ``_`` would themselves be escaped.
    """
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _resolve_anchor(pool: Any, kind: str, written: str) -> Anchor | None:
    """Turn one natural-language anchor into a Postgres-minted id, or None.

    None is the unknown-anchor outcome, never an exception and never a guess.
    Three ways to reach it, and all three are the same answer to the caller:

    * nothing matched;
    * the anchor normalizes to nothing — a lone comma, bare punctuation — which
      would otherwise become the pattern ``%%`` and match the whole table;
    * two candidates are *equally* exact, so neither is the answer. An exact
      match beside a mere substring match is not ambiguous: the exact one wins,
      which is what the ``ORDER BY`` and the third selected column encode.
    """
    by_id = (
        _RESOLVE_PARTICIPANT_BY_ID if kind == "participant" else _RESOLVE_SCREEN_BY_ID
    )
    by_name = _RESOLVE_PARTICIPANT if kind == "participant" else _RESOLVE_SCREEN
    needle = (
        _normalized_name(written)
        if kind == "participant"
        else written.strip().casefold()
    )
    as_id = _uuid_or_none(written)
    if as_id is None and not needle:
        logs.log_event("chat.anchor_empty", kind=kind, written=written)
        return None
    with pool.connection() as conn:
        # A caller (or an operator pasting from a log) may name the id itself.
        if as_id is not None:
            rows = conn.execute(by_id, (as_id,)).fetchall()
        else:
            rows = conn.execute(
                by_name, {"needle": needle, "contains": like_contains(needle)}
            ).fetchall()
    if not rows:
        return None
    if len(rows) > 1 and rows[0][2] == rows[1][2]:
        logs.log_event(
            "chat.anchor_ambiguous",
            kind=kind,
            written=written,
            exact=bool(rows[0][2]),
            candidates=[str(row[0]) for row in rows],
        )
        return None
    return Anchor(id=rows[0][0], label=rows[0][1])


def _traversal_leg(request: Request, decision: RouteDecision) -> TraversalLeg:
    """Run the classified template, or say exactly why no rows came back.

    Every non-`resolved` outcome is a value rather than an exception: the search
    leg has already run, and a routing miss must narrow the answer rather than
    fail the request.
    """
    if decision.template is None:
        return TraversalLeg()
    config = request.app.state.config
    declared = TEMPLATE_ANCHORS[decision.template]

    parameters: dict[str, Any] = {}
    for anchor_key, keyword in declared.resolved.items():
        anchor = _resolve_anchor(
            request.app.state.pool, anchor_key, decision.anchors[anchor_key]
        )
        if anchor is None:
            # An unresolved anchor is an outcome, not an error: the search leg
            # already ran, and this is logged so the empty half of the answer is
            # never a silent zero.
            logs.log_event(
                "chat.anchor_unresolved",
                template=decision.template,
                anchor=anchor_key,
                written=decision.anchors[anchor_key],
                source="postgres",
            )
            return TraversalLeg(outcome="anchor-unknown")
        parameters[keyword] = anchor.id
    for anchor_key, keyword in declared.literal.items():
        parameters[keyword] = decision.anchors[anchor_key]

    try:
        with neo4j_driver(config) as driver:
            result = run_template(driver, decision.template, **parameters)
    except StoreUnavailableError as exc:
        raise Problem(
            503,
            "chat-graph-store-unavailable",
            f"the graph store could not be reached: {exc}",
            title="Service Unavailable",
            store="neo4j",
        ) from exc
    except ProjectionError as exc:
        raise Problem(
            503,
            "chat-graph-store-unusable",
            f"the graph store could not run the {decision.template!r} traversal: {exc}",
            title="Service Unavailable",
            store="neo4j",
        ) from exc
    except ValueError as exc:
        # `run_template` refuses malformed input rather than resolving it. The
        # inputs are model-classified, so this is a routing miss, not a caller
        # bug: it degrades to the search leg exactly like an unregistered name —
        # but it is reported as its own outcome, because "the router filled the
        # template wrongly" and "the corpus does not know that anchor" are
        # different sentences for a reader.
        logs.log_event(
            "chat.traversal_refused", template=decision.template, detail=str(exc)
        )
        return TraversalLeg(outcome="input-refused")

    anchor_resolved = (
        getattr(result, "screen", None) is not None
        if decision.template == SCREEN_HISTORY
        else getattr(result, "participant", None) is not None
    )
    if not anchor_resolved:
        # Resolvable in Postgres, absent from the graph: the projection has not
        # caught up (or never ran) for the meetings this anchor appears in.
        logs.log_event(
            "chat.anchor_unresolved",
            template=decision.template,
            anchor="graph",
            written=str(decision.anchors),
            source="neo4j",
        )
        return TraversalLeg(outcome="anchor-unknown")

    limit = config.settings.api.chat.traversal_row_limit
    rows = result.rows
    # The **last** `limit` rows, not the first. Templates order ascending by
    # `meeting.startedAt`, and the questions these templates answer are recency
    # questions — "when did we last look at this screen", "did I already explain
    # this" — so slicing from the front would drop exactly the appearances the
    # question is about. Ascending order is preserved within the kept window.
    kept = rows[-limit:] if len(rows) > limit else rows
    if len(kept) < len(rows):
        logs.log_event(
            "chat.traversal_truncated",
            template=decision.template,
            available=len(rows),
            kept=len(kept),
            limit=limit,
        )
    return TraversalLeg(
        ids=tuple(row.moment_id for row in kept),
        outcome="resolved",
        available=len(rows),
    )


def _read_context(pool: Any, ids: Sequence[UUID]) -> dict[UUID, RetrievedMoment]:
    """Re-read every candidate from Postgres, dropping what cannot be cited.

    Two kinds of drop, logged apart because they ask for different repairs. A
    candidate with no row is a store holding a document Postgres no longer has —
    ``make rebuild`` is the fix. A superseded moment still *has* a row (its id
    stays resolvable by design, `pipeline/stages/moments.py`) but is not live
    evidence, and offering it to synthesis would let the answer cite a moment no
    reader should be sent to.
    """
    if not ids:
        return {}
    with pool.connection() as conn:
        rows = conn.execute(_MOMENT_CONTEXT, (list(ids),)).fetchall()
    found = {row[0] for row in rows}
    for moment_id in ids:
        if moment_id not in found:
            logs.log_event("chat.stale_hit", moment_id=moment_id)
    context: dict[UUID, RetrievedMoment] = {}
    for row in rows:
        if row[8]:
            logs.log_event("chat.superseded_moment", moment_id=row[0])
            continue
        context[row[0]] = RetrievedMoment(
            citation=MomentCitation(
                moment_id=row[0],
                meeting_id=row[1],
                start_ms=row[2],
                end_ms=row[3],
                screenshot_id=row[4],
                source_deep_link=row[5],
            ),
            meeting_title=row[6],
            meeting_started_at=row[7],
            text=(row[9] or "").strip(),
        )
    return context


def _resolver(pool: Any):
    """The gate's Postgres read: cited ids in, AD-15 citation rows out."""

    def resolve(ids: Sequence[UUID]) -> Mapping[UUID, MomentCitation]:
        if not ids:
            return {}
        with pool.connection() as conn:
            rows = conn.execute(_RESOLVE_MOMENTS, (list(ids),)).fetchall()
        return {
            row[0]: MomentCitation(
                moment_id=row[0],
                meeting_id=row[1],
                start_ms=row[2],
                end_ms=row[3],
                screenshot_id=row[4],
                source_deep_link=row[5],
            )
            for row in rows
        }

    return resolve


# --- synthesis -------------------------------------------------------------


SYNTHESIS_PROMPT = """\
You answer questions about recorded meetings using only the numbered moments
below. You never use outside knowledge and you never guess.

Citation rules — these are checked by code after you reply, and an answer that
breaks any of them is discarded whole:

1. Every sentence you write must end with one or more markers of the form
   [[moment:<uuid>]], placed after the sentence's final punctuation.
2. A marker may only name a moment listed below. Copy the uuid exactly.
3. Do not write a sentence you cannot cite — including openers, summaries and
   closers. There is no such thing as an uncited sentence here.
4. Write nothing else: no headings, no preamble, no bullet markers, no mention
   of these rules.
5. A block may include text under "Unreviewed extraction document". That text
   is machine-written analysis nobody has reviewed, and it is not evidence:
   use it only to understand the moment it sits under, never as the support
   for a sentence. There is no marker for it and it can never be cited.

If the moments below do not answer the question, say so in one cited sentence
using the moment that comes closest.

Moments:

{moments}

Question: {question}

Answer:
"""


def _timestamp(start_ms: int) -> str:
    seconds, milliseconds = divmod(max(start_ms, 0), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    del milliseconds
    return f"{hours:d}:{minutes:02d}:{seconds:02d}"


# Two guards on the prompt, not two tuning knobs — which is why they are
# constants and `api.chat` is not where they live. `retrieval_limit` decides how
# much evidence the answer may draw on (AD-10, a knob Epic 5's retrieval eval
# turns); these decide only that a legitimate setting of it cannot turn into a
# provider context-length error that reads as the model's fault. Raise
# `retrieval_limit` and the prompt gets wider; raise it past what a moment's
# transcript can be worth reading and these crop rather than fail.
MOMENT_TEXT_MAX_CHARS = 1_600
PROMPT_MOMENTS_MAX_CHARS = 32_000
# The combined budget for *all* published artifacts appended to one moment's
# block (story 4.4) — shared across however many artifacts cite that moment,
# not a per-artifact allowance. Without a shared cap, N artifacts on one
# moment would each cost up to a full moment's worth of prompt, so a heavily
# annotated moment could dwarf every other block despite the overall prompt
# cap below still enforcing a hard ceiling on the whole prompt.
ARTIFACTS_PER_MOMENT_MAX_CHARS = 1_600
# The combined budget for the extraction documents appended to one moment's
# block (story 12.4) — shared across however many documents that meeting has,
# for the same reason the artifact budget is shared. Smaller than the artifact
# allowance on purpose: an artifact is human-approved knowledge that can carry
# a sentence, while a document is unreviewed prose that can only orient the
# model around evidence it must cite from elsewhere. It is not worth crowding
# a citable moment out of the prompt for.
DOCUMENTS_PER_MOMENT_MAX_CHARS = 800


def _crop(text: str, budget: int) -> tuple[str, bool]:
    if len(text) <= budget:
        return text, False
    return text[:budget].rstrip() + " …", True


def build_synthesis_prompt(
    question: str,
    moments: Iterable[RetrievedMoment],
    artifacts_by_moment: Mapping[UUID, Sequence[RetrievedArtifact]] | None = None,
    *,
    priority_moment_ids: Iterable[UUID] = (),
    documents_by_meeting: Mapping[UUID, Sequence[RetrievedDocument]] | None = None,
) -> tuple[str, tuple[UUID, ...]]:
    """The synthesis prompt: the retrieved moments, each labelled by its marker.

    Each block opens with the exact marker the model is asked to emit, so
    "copy the uuid" is a copy rather than a transcription — the single largest
    source of ``unresolvable-marker`` rejections a model can avoid on its own.
    The header then names the meeting, its date, and the offset, because a
    recurring meeting's occurrences share a title and the question is often
    about which one.

    Cropping is reported in the log rather than silently applied: a prompt that
    lost half its evidence explains an answer that cites less than it should.

    ``artifacts_by_moment`` (story 4.4) appends each published artifact's
    title/body *inside its source moment's block*, labelled as published — so
    the model reads the distilled knowledge beside the evidence that yielded
    it, and the only marker it can cite is still the moment's.

    ``documents_by_meeting`` (story 12.4) does the same for retained extraction
    documents, keyed by **meeting** because a document has no moment. A
    document is appended to the blocks of the moments this retrieval already
    found in its meeting, under a heading that names it unreviewed — so the
    analysis is read beside the evidence it was derived from, and reaches the
    answer only through those moments (AD-6). It adds **no** candidate block
    and **no** marker of its own: a document that ranked for a meeting no
    moment was retrieved from contributes nothing, which is correct — there
    would be nothing for a sentence drawn from it to cite. The label travels
    into the prompt with the text, because prose that reads like reviewed
    output is exactly what AD-18 forbids, including when the reader is a model.
    """
    artifacts = artifacts_by_moment or {}
    documents = documents_by_meeting or {}
    candidates: list[tuple[UUID, str]] = []
    cropped_moments = 0
    cropped_artifacts = 0
    cropped_documents = 0
    dropped_moments = 0
    for moment in moments:
        header = f"[[moment:{moment.citation.moment_id}]]"
        title = moment.meeting_title or "Untitled meeting"
        when = (
            moment.meeting_started_at.date().isoformat()
            if moment.meeting_started_at is not None
            else "date unknown"
        )
        body, was_cropped = _crop(
            moment.text or "(no transcript text for this moment)", MOMENT_TEXT_MAX_CHARS
        )
        cropped_moments += int(was_cropped)
        # However many artifacts cite this moment, they share one budget
        # (cropped as a whole, not each individually) so N artifacts cannot
        # make this block N times a single moment's worth of prompt.
        artifact_text = "".join(
            f"\nPublished {artifact.kind} from this moment:"
            f" {artifact.title}\n{artifact.body}"
            for artifact in artifacts.get(moment.citation.moment_id, ())
        )
        artifact_text, artifact_was_cropped = _crop(
            artifact_text, ARTIFACTS_PER_MOMENT_MAX_CHARS
        )
        cropped_artifacts += int(artifact_was_cropped)
        body += artifact_text
        # Uncitable context, under a heading rule 5 names. However many
        # documents this meeting has, they share one budget, so an analysed
        # meeting cannot make its blocks several times a plain moment's size.
        document_text = "".join(
            f"\nUnreviewed extraction document ({document.kind},"
            f" {document.model or 'model not recorded'}) — {document.review_label}"
            f"\n{document.text}"
            for document in documents.get(moment.citation.meeting_id, ())
        )
        document_text, document_was_cropped = _crop(
            document_text, DOCUMENTS_PER_MOMENT_MAX_CHARS
        )
        cropped_documents += int(document_was_cropped)
        body += document_text
        block = f"{header} {title} — {when} at {_timestamp(moment.citation.start_ms)}\n{body}"
        candidates.append((moment.citation.moment_id, block))

    # Capacity selection and presentation order are deliberately separate.
    # Published artifact sources reserve space in artifact relevance order,
    # but the blocks that survive are emitted in the caller's traversal-first
    # sequence. That keeps structural/chronological route semantics while
    # ordinary candidates cannot crowd approved knowledge out of the prompt.
    by_id = {moment_id: index for index, (moment_id, _block) in enumerate(candidates)}
    selection_order: list[int] = []
    for moment_id in priority_moment_ids:
        index = by_id.get(moment_id)
        if index is not None and index not in selection_order:
            selection_order.append(index)
    selection_order.extend(
        index for index in range(len(candidates)) if index not in selection_order
    )
    selected: set[int] = set()
    used = 0
    for index in selection_order:
        block = candidates[index][1]
        if selected and used + len(block) > PROMPT_MOMENTS_MAX_CHARS:
            continue
        selected.add(index)
        used += len(block)
    dropped_moments = len(candidates) - len(selected)
    blocks = [
        block
        for index, (_moment_id, block) in enumerate(candidates)
        if index in selected
    ]
    included_ids = [
        moment_id
        for index, (moment_id, _block) in enumerate(candidates)
        if index in selected
    ]
    if cropped_moments or cropped_artifacts or cropped_documents or dropped_moments:
        logs.log_event(
            "chat.prompt_cropped",
            moments=len(blocks),
            cropped=cropped_moments,
            cropped_artifacts=cropped_artifacts,
            cropped_documents=cropped_documents,
            dropped=dropped_moments,
            per_moment_max_chars=MOMENT_TEXT_MAX_CHARS,
            per_moment_artifacts_max_chars=ARTIFACTS_PER_MOMENT_MAX_CHARS,
            per_moment_documents_max_chars=DOCUMENTS_PER_MOMENT_MAX_CHARS,
            prompt_max_chars=PROMPT_MOMENTS_MAX_CHARS,
        )
    return (
        SYNTHESIS_PROMPT.format(moments="\n\n".join(blocks), question=question.strip()),
        tuple(included_ids),
    )


def _binding_phrase(binding: Any) -> str:
    """How the 503 detail names what failed: the config path, then its models.

    The `llm.roles.chat` path is what an operator edits, so the sentence leads
    with it; the model tag says which provider to check, and the fallback
    clause says whether a substitute was even in play — a "no fallback" turn
    must read as the primary failing alone, never as a mystery about a second
    model (SPEC CAP-4: the error names the failed binding).
    """
    model = getattr(binding, "model", None) or "unknown"
    fallback = getattr(binding, "fallback", None)
    tail = f"fallback {fallback!r}" if fallback is not None else "no fallback configured"
    return f"the `llm.roles.chat` binding ({model!r}, {tail})"


def _complete(llm: Any, prompt: str, *, purpose: str, binding: Any = None) -> str:
    """One model call, with the port's failure taxonomy turned into a 503.

    Both models down is not a 500: it names a dependency an operator restarts,
    and it must be distinguishable from a rejected answer (which is a 422 and
    means the system worked). The detail names the `llm.roles.chat` binding —
    config path, model tag, fallback state — because the reader of this
    sentence is deciding what to fix, and "the configured chat model" made
    them go find out which model that was (SPEC CAP-4).
    """
    try:
        return llm.complete(prompt).text
    except LlmModelNotServedError as exc:
        # The selected binding is wrong, not the host down: the provider
        # answered and does not have this model. 502 rather than the 503 the
        # two branches below use, because 503 promises that retrying may work
        # and this will answer identically forever — the operator has to change
        # the selection or the file. No other model was substituted (story 8.2
        # AC3, backlog B-38): `FallbackLlm` re-raised this instead of engaging
        # the fallback, and this is where that refusal reaches the wire.
        raise Problem(
            502,
            "binding-failed",
            f"the binding selected for the `chat` role, {exc.model!r},"
            f" failed {purpose}: {exc}",
            title="Bad Gateway",
            purpose=purpose,
            role="chat",
            provider=exc.provider,
            binding=exc.model,
            configPath="llm.roles.chat",
            upstreamStatus=exc.upstream_status,
        ) from exc
    except LlmUnavailableError as exc:
        raise Problem(
            503,
            "chat-model-unavailable",
            f"{_binding_phrase(binding)} could not be reached for {purpose}:"
            f" {exc}",
            title="Service Unavailable",
            purpose=purpose,
            binding="llm.roles.chat",
            model=getattr(binding, "model", None),
        ) from exc
    except LlmError as exc:
        raise Problem(
            503,
            "chat-model-unusable",
            f"{_binding_phrase(binding)} failed {purpose}: {exc}",
            title="Service Unavailable",
            purpose=purpose,
            binding="llm.roles.chat",
            model=getattr(binding, "model", None),
        ) from exc


def _reject(reason: str, detail: str, route: RouteModel) -> Problem:
    """The one refusal path — 422, `no-citable-answer`, and why.

    The body carries the same ``route`` object the success body does. Without
    it "the corpus does not know that person" and "nothing matched" would be
    byte-identical responses, and the frozen intent puts that distinction *on
    the wire* rather than in a log line an operator has to go find.
    """
    logs.log_event(
        "chat.rejected",
        reason=reason,
        detail=detail,
        template=route.template,
        traversal_outcome=route.traversal_outcome,
        anchor_resolved=route.anchor_resolved,
        retrieved=route.retrieved,
    )
    return Problem(
        422,
        NO_CITABLE_ANSWER,
        detail,
        # camelCase, like every other problem extension this api emits
        # (`maxLimit`, `jobId`): the boundary convention does not stop at the
        # success payload. Story 3.4 renders one state and reads these to say
        # which kind it was.
        reason=reason,
        route=route.model_dump(by_alias=True),
    )


# --- the route -------------------------------------------------------------


def _answer(request: Request, question: str) -> tuple[ValidatedAnswer, RouteModel]:
    """The whole orchestration, up to and including the gate.

    Raises :class:`Problem` for every refusal, so the JSON and SSE surfaces
    share one rejection path and neither can emit a partial answer.
    """
    pool = request.app.state.pool
    config = request.app.state.config

    # The deterministic guard that comes before every model call. With no moment
    # row anywhere, neither leg could produce a candidate, no draft could pass
    # the gate, and there is nothing worth spending a provider call to discover.
    with pool.connection() as conn:
        if not conn.execute(_ANY_MOMENT).fetchone()[0]:
            raise _reject(
                "no-evidence",
                "the corpus holds no moments, so no answer could be cited",
                RouteModel(search_hits=0, traversal_rows=0, retrieved=0),
            )
        # Read **inside this request** (story 8.2, FR38): a selection made a
        # moment ago must answer the next question, so nothing here is cached
        # on the app or resolved at import. The same connection the guard above
        # already holds, because it is one more indexed lookup, not a reason to
        # take a second connection out of the pool.
        binding, effective = model_selection.resolve_role(
            conn, "chat", config.settings.llm.roles.chat, log=logs.log_event
        )
    logs.log_event(
        "chat.binding_resolved",
        binding=effective.binding,
        provider=effective.provider,
        source=effective.source,
        file_default=effective.default_binding,
    )

    # The model's first and only structural job (AD-7): name a template, and
    # name the words worth putting to the index.
    llm = build_llm(binding, config.settings.providers, log=logs.log_event)
    decision = parse_route(
        _complete(
            llm,
            build_classifier_prompt(question),
            purpose="classification",
            binding=binding,
        )
    )
    logs.log_event(
        "chat.classified",
        template=decision.template,
        fallback_reason=decision.fallback_reason,
        anchors=dict(decision.anchors),
    )

    # The search leg runs on every question, including one a traversal answers
    # completely: it costs one round trip and buys a non-empty retrieval when
    # classification was wrong.
    #
    # It queries the classifier's terms rather than the question as typed, and
    # that is not a preference. Meilisearch's `last` matching strategy drops the
    # *trailing* words of a query first, and an English question puts its
    # subject last — "what happened with the purchase order?" is reduced to
    # "what happened with the" and matches nothing, measured on this index. The
    # classifier's job includes extracting those words, so the terms it returns
    # are what the index is asked. A reply that offered none falls back to the
    # question, which is still better than not searching.
    terms = decision.search_terms or question
    search_ids = _search_leg(request, terms, _embed(request, terms))

    # The published-artifacts leg (story 4.4): an artifact hit contributes its
    # *source moment* into the retrieved set — read back from Postgres, not
    # from the index — and its title/body into that moment's context block.
    # The citation contract stays moment-typed end to end.
    artifact_ids = _artifact_leg(request, terms)
    artifacts_by_moment = _read_artifact_context(pool, artifact_ids)

    # The extraction-documents leg (story 12.4), and it is shaped unlike the
    # one above it on purpose. It contributes **no moment** to `ordered` and
    # therefore nothing to what the answer may cite: a document is a claim
    # about evidence, never evidence (AD-6). What it contributes is context —
    # the analysis a run produced, folded into the blocks of moments the other
    # legs already found in that meeting, labelled unreviewed. A document that
    # ranks for a meeting no moment was retrieved from is read by nobody, which
    # is right: there would be nothing for a sentence drawn from it to cite.
    document_hits = _document_leg(request, terms)
    documents_by_meeting = _read_document_context(pool, document_hits)

    traversal = _traversal_leg(request, decision)

    # Preserve route semantics in the visible sequence: traversal rows retain
    # their own time order, followed by ordinary search rank, then artifact-
    # only source moments in artifact relevance order. Duplicates collapse on
    # first appearance. Prompt capacity is reserved separately below.
    ordered: list[UUID] = []
    for moment_id in (*traversal.ids, *search_ids, *artifacts_by_moment):
        if moment_id not in ordered:
            ordered.append(moment_id)

    # Route telemetry counts distinct source moments found by either search
    # lane. An artifact and ordinary hit resolving to the same moment are one
    # searchable evidence target, not two.
    search_hit_count = len(set(search_ids) | set(artifacts_by_moment))

    context = _read_context(pool, ordered)
    retrieved = [context[moment_id] for moment_id in ordered if moment_id in context]
    if not retrieved:
        route = RouteModel(
            template=decision.template,
            anchor_resolved=traversal.anchor_resolved,
            traversal_outcome=traversal.outcome,
            fallback_reason=decision.fallback_reason,
            search_hits=search_hit_count,
            traversal_rows=len(traversal.ids),
            traversal_truncated=traversal.truncated,
            retrieved=0,
        )
        raise _reject(
            "no-evidence",
            "no moment in the corpus matched the question, so there is nothing"
            " an answer could cite",
            route,
        )

    prompt, prompted_ids = build_synthesis_prompt(
        question,
        retrieved,
        artifacts_by_moment,
        priority_moment_ids=artifacts_by_moment,
        documents_by_meeting=documents_by_meeting,
    )
    route = RouteModel(
        template=decision.template,
        anchor_resolved=traversal.anchor_resolved,
        traversal_outcome=traversal.outcome,
        fallback_reason=decision.fallback_reason,
        search_hits=search_hit_count,
        traversal_rows=len(traversal.ids),
        traversal_truncated=traversal.truncated,
        retrieved=len(prompted_ids),
    )
    draft = _complete(llm, prompt, purpose="synthesis", binding=binding)
    outcome = validate(
        draft,
        prompted_ids,
        _resolver(pool),
    )
    if isinstance(outcome, Rejection):
        raise _reject(outcome.reason, outcome.detail, route)
    return outcome, route


# Chunks of an already-validated answer. A word plus the whitespace that follows
# it, so concatenating every `chat.token` payload reproduces the `answer` string
# exactly — which is what lets story 3.4 render the stream and the JSON body the
# same way.
_TOKEN_PATTERN = re.compile(r"\S+\s*|\s+")


def token_chunks(answer: str) -> tuple[str, ...]:
    """Split a validated answer into the chunks ``chat.token`` replays."""
    return tuple(match.group(0) for match in _TOKEN_PATTERN.finditer(answer))


def _sse_events(
    answer: ValidatedAnswer, route: RouteModel, citations: list[CitationModel]
) -> list[bytes]:
    """The whole stream, built from an answer that already passed the gate.

    A list rather than a generator on purpose: every event is known before the
    response starts, so there is no window in which the connection is open and
    the outcome is not yet decided.

    Serialized here with :func:`format_sse_event` rather than yielded as
    ``ServerSentEvent`` objects, because FastAPI's encoding layer only runs for a
    path operation that *yields* — this route returns a response so it can
    choose JSON instead. Each payload is dumped ``by_alias`` for the same reason
    `api/events.py` uses ``raw_data``: an api that is camelCase at every boundary
    must not emit snake_case field names onto its stream.
    """
    events = [
        format_sse_event(
            event=EVENT_TOKEN,
            data_str=ChatTokenEvent(text=chunk).model_dump_json(by_alias=True),
        )
        for chunk in token_chunks(answer.answer)
    ]
    events.append(
        format_sse_event(
            event=EVENT_CITATIONS,
            data_str=ChatCitationsEvent(citations=citations).model_dump_json(
                by_alias=True
            ),
        )
    )
    events.append(
        format_sse_event(
            event=EVENT_DONE,
            data_str=ChatDoneEvent(route=route).model_dump_json(by_alias=True),
        )
    )
    return events


@router.post(
    "/chat",
    operation_id="askCorpus",
    response_model=ChatResponse,
    responses={
        200: {
            "description": "The validated answer. Under `Accept:"
            " application/json` it is the whole `ChatResponse`; under `Accept:"
            " text/event-stream` the same answer is replayed as `chat.token`+"
            " (payload `{event, text}`), then `chat.citations` (payload"
            " `{event, citations}` carrying the identical array), then"
            " `chat.done` (payload `{event, route}`). Concatenating every"
            " `chat.token` text reproduces `answer` exactly.",
        },
        422: {
            "model": ProblemDetails,
            "content": {"application/problem+json": {}},
            "description": "`no-citable-answer` — retrieval or the citation gate"
            " refused the answer, with a camelCase `reason` extension naming"
            " which (`no-evidence`, `no-citations`, `uncited-claim`,"
            " `unresolvable-marker`, `empty-answer`). No answer text and no"
            " citation is returned by any surface, including the stream, which"
            " never opens. `invalid-request` — the question was blank or past"
            " the length bound and was refused at the door.",
        },
        502: {
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
            "description": "`binding-failed` — the selected model binding is"
            " not served by the provider endpoint. Retrying cannot repair the"
            " binding; select a served model or change the endpoint.",
        },
        503: {
            "model": ProblemDetails,
            "content": {"application/problem+json": {}},
            "description": "The slug names what to restart."
            " `chat-search-store-unavailable` / `chat-search-store-unusable` —"
            " Meilisearch. `chat-graph-store-unavailable` /"
            " `chat-graph-store-unusable` — Neo4j."
            " `chat-model-unavailable` / `chat-model-unusable` — the configured"
            " `llm.roles.chat` binding and its fallback."
            " `embedder-unusable` — the configured embedding model answered"
            " wrongly, which is a config error rather than an outage.",
        },
    },
)
def ask_corpus(request: Request, payload: ChatRequest) -> Any:
    """Answer one question with citations, or refuse — never anything between.

    Both representations come from the same validated answer. `Accept:
    text/event-stream` gets `chat.token` / `chat.citations` / `chat.done`;
    everything else gets the JSON body. The gate runs before either is chosen,
    so a rejection is a `422` problem in both cases and the stream never opens.
    """
    started = time.monotonic()
    answer, route = _answer(request, payload.question)
    citations = [
        CitationModel(
            moment_id=citation.moment_id,
            meeting_id=citation.meeting_id,
            start_ms=citation.start_ms,
            end_ms=citation.end_ms,
            screenshot_id=citation.screenshot_id,
            source_deep_link=citation.source_deep_link,
        )
        for citation in answer.citations
    ]
    logs.log_event(
        "chat.completed",
        question=payload.question,
        template=route.template,
        traversal_outcome=route.traversal_outcome,
        retrieved=route.retrieved,
        citations=len(citations),
        streamed=_wants_stream(request),
        # NFR4 is the requirement this endpoint exists to satisfy, and it is a
        # latency requirement — unobservable unless the answer's own line says
        # how long it took. Both model calls and both stores are inside this.
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )
    if _wants_stream(request):
        return EventSourceResponse(_sse_events(answer, route, citations))
    return ChatResponse(
        question=payload.question,
        answer=answer.answer,
        citations=citations,
        route=route,
    )
