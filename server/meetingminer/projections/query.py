"""Reading the Meilisearch projection — the query half of AD-4.

AD-4 gives the projections module exactly one writer. The mirror of that rule
is this file: retrieval code *reads* the stores, and it reads them from inside
this package, so ``meilisearch`` stays imported here and nowhere near
``meetingminer/api/`` (``tests/test_projections_single_writer.py`` asserts it
by AST walk). The ``/search`` route calls :func:`search_moments`, handing it
the client ``stores.meili_client`` built for it; the index handle, the search
parameters and the store's response shape stay in here, and the api package
imports no store library.

Three decisions this module owns.

**Three lanes, three allow-lists.** :data:`SEARCHABLE_INDEXES` is the hybrid
lane's complete index set and contains the moments index alone;
:data:`ARTIFACT_SEARCHABLE_INDEXES` is the keyword-only artifact lane's
(story 4.4) and contains ``publish_gate.ARTIFACTS_INDEX`` alone;
:data:`DOCUMENT_SEARCHABLE_INDEXES` is the keyword-only extraction-document
lane's (story 12.4) and contains ``documents.DOCUMENTS_INDEX`` alone. Every
artifact query pins ``state = 'published'`` in its own filter, which keeps
"no unpublished artifact can surface through search" (NFR7) a property of the
query side as well as of the publish gate — belt and braces, because the two
are written by different stories.

The document lane is the mirror image, and deliberately so. It pins
``reviewState = 'unreviewed'`` instead — not to withhold anything (AD-4's
exception says every document is reachable) but because that is the *only*
state a document may carry, so a hit that came back claiming otherwise is a
store holding something this system did not write. And :class:`DocumentHit`
carries **no moment id and no artifact id**: a document is a claim about
evidence, never a citation target (AD-6), so there is nothing on this lane's
hit for a citation to be built out of.

**Highlights are runs, not markup.** Meilisearch marks matched terms by
wrapping them in configurable tags. Using two Unicode private-use code points
as those tags and parsing them here into ``[{text, highlighted}]`` keeps HTML
off the wire and out of React, the same reasoning AD-15 applies to citations:
a consumer renders from the array, it does not parse a string. A stray
sentinel in the source text is treated as literal text rather than as a run
boundary — see :func:`parse_highlight_runs`.

**Meilisearch ranks; it does not cite.** What comes back from here is an
ordered list of moment ids plus a snippet and a score. Every citation field
the api puts on the wire is re-read from Postgres, the database of record
(AD-2, AD-6). Nothing in this module returns a timestamp or a meeting id.

One more decision belongs here because it is a property of how this store
ranks: the **semantic floor**. The vector lane returns the k nearest moments
for any query at all, including one whose words appear nowhere, so without a
floor an empty result set is unreachable. Meilisearch's own
``rankingScoreThreshold`` cannot serve — it applies to both lanes, which do not
share a scale — so :func:`apply_semantic_floor` applies it to the vector lane
alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import UUID

import meilisearch
from meilisearch.errors import (
    MeilisearchApiError,
    MeilisearchCommunicationError,
    MeilisearchError,
    MeilisearchTimeoutError,
)

from meetingminer.adapters.embed.port import Vector
from meetingminer.config import AppConfig
from meetingminer.projections.documents import (
    AUTHORSHIP,
    DOCUMENTS_INDEX,
    REVIEW_LABEL,
    REVIEW_STATE,
)
from meetingminer.projections.publish_gate import ARTIFACTS_INDEX, PUBLISHED_STATE
from meetingminer.projections.stores import (
    EMBEDDER_NAME,
    MOMENTS_INDEX,
    ProjectionError,
    StoreUnavailableError,
)

# The allow-list for the *hybrid* (keyword + semantic) lane. One entry, on
# purpose: the moments index is the citation-shaped one (AD-6), and `chunks`
# is story 3.3's synthesis unit rather than a user-facing result.
# `publish_gate.ARTIFACTS_INDEX` is deliberately not here either — published
# artifacts are read through :func:`search_artifacts`, a keyword-only lane
# with its own allow-list below, and every artifact query pins
# `state = 'published'` in its filter (story 4.4; NFR7 stays structural for
# anything unpublished, through the publish gate plus that filter).
SEARCHABLE_INDEXES: tuple[str, ...] = (MOMENTS_INDEX,)

# The complete set of indexes the keyword-only artifact lane may read.
ARTIFACT_SEARCHABLE_INDEXES: tuple[str, ...] = (ARTIFACTS_INDEX,)

# And the extraction-document lane's (story 12.4). One entry, like the two
# above: a lane that could read a second index could rank a document against a
# moment, and the two do not share a scale or a citability.
DOCUMENT_SEARCHABLE_INDEXES: tuple[str, ...] = (DOCUMENTS_INDEX,)

# The highlight tags. U+E000 and U+E001 are in the Unicode private use area:
# they have no assigned meaning, no font renders them, and no transcript or
# OCR pipeline in this system emits them. That makes them safe *delimiters*
# rather than safe *content* — `parse_highlight_runs` still has to survive one
# appearing in the source text, because "no known producer emits this" is not
# the same as "this cannot occur".
HIGHLIGHT_PRE = "\ue000"
HIGHLIGHT_POST = "\ue001"

# The document attributes a snippet may be cut from, in preference order.
# These are *document shape*, not a retrieval knob: they must be exactly the
# attributes `config.yaml` makes searchable on the moments index, because an
# attribute that can be matched but not highlighted produces a hit with no
# highlighted run — a result the user cannot see the reason for. AC1 names
# three input kinds (a topic, a meeting name, a mention), and two of them
# match through `title` and `speakers`.
#
# The *order* is the preference, and transcript text comes first: when a query
# matches both the passage and the metadata, the passage is what tells the
# user why this moment answers them. `_snippet_of` only falls back down the
# list when nothing earlier carried a highlight.
SNIPPET_ATTRIBUTES: tuple[str, ...] = ("text", "screenText", "speakers", "title")

# The artifact document's two searchable attributes (config.yaml,
# `projections.search.artifacts`), in the same order the index boosts them:
# an artifact's title is its distilled claim, so a title match is shown first.
ARTIFACT_SNIPPET_ATTRIBUTES: tuple[str, ...] = ("title", "text")

# The extraction document's, in its own boost order (config.yaml,
# `projections.search.documents`). `text` leads because the document *is* the
# body — the inverse of an artifact, whose title is the distilled claim.
DOCUMENT_SNIPPET_ATTRIBUTES: tuple[str, ...] = ("text", "title")


@dataclass(frozen=True)
class SnippetRun:
    """One stretch of snippet text, either matched or not.

    The wire format for a highlight. A consumer concatenates ``text`` across
    the runs to get the plain snippet and emphasises the ones where
    ``highlighted`` is true; it never sees, and never parses, a tag.
    """

    text: str
    highlighted: bool


@dataclass(frozen=True)
class MomentHit:
    """One ranked moment id. Not a citation — the api builds that from Postgres."""

    moment_id: UUID
    snippet: tuple[SnippetRun, ...]
    score: float | None


@dataclass(frozen=True)
class ArtifactHit:
    """One ranked *published* artifact id, with the moments it cites.

    Not a citation and not a result row: the api re-reads the artifact and its
    source moment from Postgres in the same request (AD-2/AD-6), and a hit
    whose row is gone or no longer ``published`` is dropped there.
    """

    artifact_id: UUID
    moment_ids: tuple[UUID, ...]
    snippet: tuple[SnippetRun, ...]
    score: float | None


@dataclass(frozen=True)
class ArtifactSearchResult:
    """What one artifacts-lane query returned, in the store's ranking order."""

    hits: tuple[ArtifactHit, ...]
    # Exhaustive filtered count from Meilisearch's page-pagination response.
    # Unlike ``estimatedTotalHits`` this is safe to use as the boundary of the
    # finite leading artifact lane in the combined /search sequence.
    total: int = 0
    limit: int = 0
    offset: int = 0
    # True when the artifacts index does not exist yet — a store from before
    # story 4.4, or one that was wiped and not yet rebuilt. Nothing published
    # is reachable then, which the caller logs rather than silently zeroes.
    index_missing: bool = False


@dataclass(frozen=True)
class DocumentHit:
    """One ranked extraction document. **Never a citation** (AD-6, story 12.4).

    Deliberately missing what every other hit in this module carries: no
    ``moment_id``, no ``moment_ids``, no ``artifact_id``, no timestamps. A
    document is a claim *about* evidence — citing it would establish that the
    model said something, not that the meeting did, which is the circularity
    the publish gate exists to prevent. The absence is the mechanism: a caller
    cannot build a citation out of this type, because there is nothing on it to
    build one from. Its content reaches an answer only through the moments its
    individual claims anchor to.

    ``document_id`` is the ``extraction_source`` row's UUID (the build decision
    :mod:`meetingminer.projections.documents` states). The api re-reads the row
    from Postgres in the same request, like every other lane here.

    ``review_label`` travels with the hit rather than being looked up: the
    exception is to reach, never to legibility, so the sentence that says this
    is unreviewed machine-written output comes out of the store attached to the
    thing it describes and cannot be lost between here and a renderer (AD-18).
    """

    document_id: UUID
    meeting_id: UUID
    kind: str
    review_state: str
    authorship: str
    review_label: str
    snippet: tuple[SnippetRun, ...]
    score: float | None


@dataclass(frozen=True)
class DocumentSearchResult:
    """What one extraction-document query returned, in ranking order."""

    hits: tuple[DocumentHit, ...]
    # Exhaustive filtered count, from the same page-pagination request the
    # artifacts lane uses and for the same reason: ``estimatedTotalHits`` is
    # explicitly unstable across offset/limit pages.
    total: int = 0
    limit: int = 0
    offset: int = 0
    # True when the documents index does not exist yet — a store from before
    # story 12.4, or one wiped and not yet rebuilt. Distinct from "no document
    # matched", because the repair is a rebuild rather than other words.
    index_missing: bool = False


@dataclass(frozen=True)
class MomentSearchResult:
    """What one query returned, in the store's ranking order."""

    hits: tuple[MomentHit, ...]
    # Meilisearch's own estimate, less the semantic-lane hits this page's
    # floor discarded. Named "estimated" because it is: the store does not
    # count every match, the subtraction is per page against a corpus-wide
    # number, and reporting either as a total would be a number this system
    # cannot stand behind. Zero when the first page floored out entirely with
    # no keyword hits — see :func:`search_moments`.
    estimated_total: int
    limit: int
    offset: int
    # True when the index the query names does not exist yet — a corpus that
    # has never been projected. Distinct from "no matches", so a caller can
    # tell an empty corpus from an empty result set rather than reporting a
    # silent zero (SPEC Constraints).
    index_missing: bool = False
    # Semantic-lane hits the store returned and the floor discarded. Reported
    # rather than absorbed: "the vector half matched nothing above the floor"
    # is a fact about the query, and a floor that is quietly eating every
    # paraphrase hit should be visible in a log line, not inferable only from
    # a missing result.
    below_floor: int = 0


def parse_highlight_runs(formatted: str | None) -> tuple[SnippetRun, ...]:
    """Split a Meilisearch ``_formatted`` value into highlighted runs.

    The grammar is deliberately forgiving, because the input is not fully
    under this system's control:

    * Adjacent runs are kept separate rather than merged — two consecutive
      matched terms are two matched runs, and a renderer that wraps each one
      produces the same visible result either way.
    * A :data:`HIGHLIGHT_PRE` with no closing :data:`HIGHLIGHT_POST` is
      literal text, not an unterminated run. Meilisearch always closes the
      tags it opens, so an unbalanced one can only have come from the source
      document, and dropping it (or raising) would corrupt a snippet over a
      character that was simply part of the transcript.
    * A :data:`HIGHLIGHT_PRE` followed by another opener before any closer is
      literal for the same reason — the store never nests its tags, so the
      outer one is document text. This is the case that matters: pairing a
      stray opener with the *next* match's closer would mark everything
      between them as matched.
    * A :data:`HIGHLIGHT_POST` with no opener is literal text, again for the
      same reason.
    * Empty runs are dropped, so an empty match produces no run at all rather
      than an empty ``<mark>``.

    ``None`` or ``""`` yields no runs; a hit with no snippet is a hit with no
    snippet, which the api reports as an empty array.
    """
    if not formatted:
        return ()
    runs: list[SnippetRun] = []
    plain: list[str] = []
    index = 0
    length = len(formatted)
    while index < length:
        character = formatted[index]
        if character == HIGHLIGHT_PRE:
            close = formatted.find(HIGHLIGHT_POST, index + 1)
            next_open = formatted.find(HIGHLIGHT_PRE, index + 1)
            # Two ways this opener turns out to be source text rather than a
            # tag: nothing closes it at all, or a *second* opener arrives
            # first. Meilisearch never nests its tags, so an opener before the
            # next closer means the earlier one was in the document. Without
            # this second test the stray opener would pair with the *real*
            # match's closer and swallow everything between them into one
            # bogus highlight.
            if close == -1 or (next_open != -1 and next_open < close):
                plain.append(character)
                index += 1
                continue
            if plain:
                runs.append(SnippetRun("".join(plain), False))
                plain = []
            matched = formatted[index + 1 : close]
            if matched:
                runs.append(SnippetRun(matched, True))
            index = close + 1
            continue
        # A closer with nothing open is source text by the same argument.
        plain.append(character)
        index += 1
    if plain:
        runs.append(SnippetRun("".join(plain), False))
    return tuple(runs)


def _formatted_strings(value: Any) -> list[str]:
    """The formatted value(s) of one attribute, as a flat list of strings.

    ``speakers`` is an array in the document, so Meilisearch formats it as an
    array — each entry separately highlighted. Everything else is a plain
    string. Both shapes reduce to "candidate snippet strings", which is all
    :func:`_snippet_of` needs.
    """
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [entry for entry in value if isinstance(entry, str) and entry]
    return []


def _snippet_of(
    formatted: Mapping[str, Any] | None,
    attributes: tuple[str, ...] = SNIPPET_ATTRIBUTES,
) -> tuple[SnippetRun, ...]:
    """Pick the best snippet attribute from one hit's ``_formatted`` block.

    "Best" means *the one that actually matched*. Meilisearch crops every
    attribute it is asked to crop whether or not the query hit it, so a
    moment matched only through its screen's OCR text would otherwise be shown
    the opening words of its transcript — a snippet that does not contain the
    term the user searched for. So a formatted value carrying a highlight
    wins; only when none does is the first non-empty attribute used, which is
    the semantic-only case (a vector hit matches no term, so nothing is
    marked).

    :data:`SNIPPET_ATTRIBUTES` is walked in order, so transcript text wins a
    tie against the metadata attributes below it.
    """
    if not formatted:
        return ()
    fallback: tuple[SnippetRun, ...] = ()
    for attribute in attributes:
        for value in _formatted_strings(formatted.get(attribute)):
            runs = parse_highlight_runs(value)
            if any(run.highlighted for run in runs):
                return runs
            if not fallback:
                fallback = runs
    return fallback


def build_filter(meeting_id: UUID | None, corpus: str | None) -> str | None:
    """The Meilisearch filter expression for the requested scope, or ``None``.

    ``meeting_id`` is round-tripped through :class:`UUID` by its type before it
    reaches here, and ``corpus`` is validated against a closed set at the route
    — neither value is caller-shaped text by the time it is interpolated.
    """
    clauses: list[str] = []
    if meeting_id is not None:
        clauses.append(f'meetingId = "{UUID(str(meeting_id))}"')
    if corpus is not None:
        # Guarded rather than trusted: this function builds a filter
        # expression, and a filter expression is not a place to interpolate an
        # unexamined string. The route already restricts the value; this makes
        # the restriction a property of the expression builder too.
        if not corpus.isalpha():
            raise ValueError(
                f"corpus scope {corpus!r} is not a bare word — refusing to"
                " build a filter expression from it"
            )
        clauses.append(f'corpus = "{corpus}"')
    if not clauses:
        return None
    return " AND ".join(clauses)


def build_search_parameters(
    config: AppConfig,
    *,
    limit: int,
    offset: int,
    meeting_id: UUID | None = None,
    corpus: str | None = None,
    query_vector: Vector | None = None,
    semantic_ratio: float | None = None,
) -> dict[str, Any]:
    """The Meilisearch request body for one moments query.

    Split out from :func:`search_moments` so the parameters can be asserted
    without a store: whether the ``hybrid`` block is present, what the filter
    says, and which tags the highlighter is told to use are all decisions worth
    pinning in a unit test.

    The ``hybrid`` block is present **only** when the caller supplies a vector.
    Meilisearch's embedder here is ``userProvided`` (AD-4: no store-native
    auto-embedder is ever registered), so it cannot embed the query itself —
    asking for hybrid ranking without handing over a vector would be asking
    the store to do the one thing this architecture forbids it.
    """
    search = config.settings.api.search
    parameters: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        # Ids only: every other field on the wire is re-read from Postgres
        # (AD-6), so retrieving the rest of the document would invite a
        # citation built from the index instead of from the database of
        # record. `_formatted` is unaffected by this — it is a separate block.
        "attributesToRetrieve": ["id"],
        "attributesToHighlight": list(SNIPPET_ATTRIBUTES),
        "attributesToCrop": list(SNIPPET_ATTRIBUTES),
        "cropLength": search.crop_length,
        "highlightPreTag": HIGHLIGHT_PRE,
        "highlightPostTag": HIGHLIGHT_POST,
        "showRankingScore": True,
    }
    expression = build_filter(meeting_id, corpus)
    if expression is not None:
        parameters["filter"] = expression
    if query_vector is not None:
        parameters["hybrid"] = {
            "semanticRatio": search.semantic_ratio
            if semantic_ratio is None
            else semantic_ratio,
            "embedder": EMBEDDER_NAME,
        }
        parameters["vector"] = list(query_vector)
    return parameters


def _hits_of(response: Any) -> Sequence[Mapping[str, Any]]:
    if isinstance(response, Mapping):
        value = response.get("hits") or ()
    else:
        value = getattr(response, "hits", ()) or ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProjectionError("Meilisearch returned hits in an invalid shape")
    if not all(isinstance(hit, Mapping) for hit in value):
        raise ProjectionError("Meilisearch returned a hit in an invalid shape")
    return value


def _estimated_total_of(response: Any) -> int:
    if isinstance(response, Mapping):
        value = response.get("estimatedTotalHits")
    else:
        value = getattr(response, "estimated_total_hits", None)
    try:
        return int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ProjectionError(
            "Meilisearch returned an invalid estimated hit count"
        ) from exc


def _total_hits_of(response: Any) -> int:
    """Read the exhaustive count returned by page-style pagination."""
    if isinstance(response, Mapping):
        value = response.get("totalHits")
    else:
        value = getattr(response, "total_hits", None)
    if value is None:
        raise ProjectionError(
            "Meilisearch returned no exhaustive hit count for a page query"
        )
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ProjectionError(
            "Meilisearch returned an invalid exhaustive hit count"
        ) from exc


def apply_semantic_floor(
    hits: Sequence[MomentHit], floor: float
) -> tuple[tuple[MomentHit, ...], int]:
    """Drop weak hits from the separately retrieved semantic lane.

    **Why this exists.** The vector lane ranks by similarity and has no notion
    of "no match": ask it about a word that appears nowhere and it returns the
    k nearest moments anyway. Without a floor, `GET /search` could never answer
    "nothing matched" — the matrix row that says an empty result is a valid
    answer would be unreachable.

    **Why it is not Meilisearch's own ``rankingScoreThreshold``.** That
    threshold applies to both lanes at once, and the two lanes do not share a
    scale. Measured against this index: a typo-tolerant keyword hit scores as
    low as 0.15, while a semantic hit on unrelated text scores around 0.65. A
    single threshold either keeps the noise or throws away the typo tolerance
    the acceptance criteria require. So the floor is applied here, to the
    semantic lane alone.

    The lane is retrieved separately with ``semanticRatio: 1.0``. This is
    necessary because Meilisearch's ``semanticHitCount`` is exhaustive rather
    than page-local: it cannot identify the semantic members of a native hybrid
    page. A hit with no score is kept; silently discarding it would turn a
    client-shape change into lost recall.
    """
    if floor <= 0.0:
        return tuple(hits), 0
    kept: list[MomentHit] = []
    dropped = 0
    for hit in hits:
        if hit.score is not None and hit.score < floor:
            dropped += 1
            continue
        kept.append(hit)
    return tuple(kept), dropped


def merge_search_lanes(
    keyword_hits: Sequence[MomentHit],
    semantic_hits: Sequence[MomentHit],
    semantic_ratio: float,
    count: int,
) -> tuple[MomentHit, ...]:
    """Blend independently ranked keyword and semantic lanes deterministically.

    A Bresenham-style schedule allocates approximately ``semantic_ratio`` of
    positions to the semantic lane, while preserving each lane's store ranking.
    Semantic ids already returned by keyword retrieval stay keyword results;
    this guarantees an exact/typo match is never removed because its vector is
    weak. If either lane runs out, the other fills the remaining positions.
    """
    keyword = list(keyword_hits)
    keyword_ids = {hit.moment_id for hit in keyword}
    semantic = [hit for hit in semantic_hits if hit.moment_id not in keyword_ids]
    merged: list[MomentHit] = []
    keyword_index = semantic_index = 0
    for position in range(count):
        semantic_slot = int((position + 1) * semantic_ratio) > int(
            position * semantic_ratio
        )
        preferred, other = (
            ("semantic", "keyword") if semantic_slot else ("keyword", "semantic")
        )
        for lane in (preferred, other):
            if lane == "keyword" and keyword_index < len(keyword):
                merged.append(keyword[keyword_index])
                keyword_index += 1
                break
            if lane == "semantic" and semantic_index < len(semantic):
                merged.append(semantic[semantic_index])
                semantic_index += 1
                break
        else:
            break
    return tuple(merged)


def _is_index_missing(exc: MeilisearchApiError) -> bool:
    return getattr(exc, "code", None) == "index_not_found"


def _moment_hits_of(response: Any) -> tuple[MomentHit, ...]:
    """Validate one store response and turn it into citable candidate hits."""
    hits: list[MomentHit] = []
    for hit in _hits_of(response):
        raw_id = hit.get("id")
        if raw_id is None:
            raise ProjectionError(
                f"a {MOMENTS_INDEX!r} hit carried no id — every document in this"
                " index is keyed on a Postgres moment id (AD-6)"
            )
        try:
            moment_id = UUID(str(raw_id))
        except ValueError as exc:
            raise ProjectionError(
                f"a {MOMENTS_INDEX!r} hit carried an id that is not a UUID:"
                f" {raw_id!r} — every document in this index is keyed on a"
                " Postgres moment id (AD-6)"
            ) from exc
        raw_score = hit.get("_rankingScore")
        try:
            score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError) as exc:
            raise ProjectionError(
                "Meilisearch returned an invalid ranking score"
            ) from exc
        hits.append(
            MomentHit(
                moment_id=moment_id,
                snippet=_snippet_of(hit.get("_formatted")),
                score=score,
            )
        )
    return tuple(hits)


def search_moments(
    client: meilisearch.Client,
    config: AppConfig,
    *,
    query: str,
    limit: int,
    offset: int = 0,
    meeting_id: UUID | None = None,
    corpus: str | None = None,
    query_vector: Vector | None = None,
) -> MomentSearchResult:
    """Rank the moments index for ``query`` and return ordered moment ids.

    Reads :data:`MOMENTS_INDEX` and asserts it against the allow-list before
    the call, so the one index this function may read is stated in code rather
    than only in a comment.

    An index that does not exist yet is reported as
    :attr:`MomentSearchResult.index_missing` with no hits: a corpus that has
    never been projected genuinely holds nothing, and the caller logs the
    distinction rather than reporting a bare zero. Every other store failure
    raises — :class:`StoreUnavailableError` when the store could not be
    reached, :class:`ProjectionError` when it answered and refused.
    """
    if MOMENTS_INDEX not in SEARCHABLE_INDEXES:
        raise ProjectionError(
            f"index {MOMENTS_INDEX!r} is not in the searchable allow-list"
            f" {SEARCHABLE_INDEXES!r} — refusing to query it"
        )
    # Both lanes start at zero and fetch enough candidates to assemble the
    # requested page after blending. Offset is applied to the merged result,
    # not independently to each lane; otherwise a semantic slot on page two
    # could repeat or skip a candidate from page one.
    candidate_count = offset + limit
    keyword_parameters = build_search_parameters(
        config,
        limit=candidate_count,
        offset=0,
        meeting_id=meeting_id,
        corpus=corpus,
    )
    try:
        index = client.index(MOMENTS_INDEX)
        keyword_response = index.search(query, keyword_parameters)
        semantic_response = None
        if query_vector is not None and config.settings.api.search.semantic_ratio > 0.0:
            semantic_parameters = build_search_parameters(
                config,
                limit=candidate_count,
                offset=0,
                meeting_id=meeting_id,
                corpus=corpus,
                query_vector=query_vector,
                semantic_ratio=1.0,
            )
            semantic_response = index.search(query, semantic_parameters)
    except MeilisearchApiError as exc:
        if _is_index_missing(exc):
            return MomentSearchResult(
                hits=(),
                estimated_total=0,
                limit=limit,
                offset=offset,
                index_missing=True,
            )
        raise ProjectionError(
            f"Meilisearch refused the {MOMENTS_INDEX!r} query: {exc}"
        ) from exc
    except (MeilisearchCommunicationError, MeilisearchTimeoutError) as exc:
        raise StoreUnavailableError(
            f"Meilisearch became unreachable during the {MOMENTS_INDEX!r}"
            f" query ({type(exc).__name__}: {exc})"
        ) from exc
    except MeilisearchError as exc:  # pragma: no cover - client-shape change
        raise ProjectionError(
            f"Meilisearch failed the {MOMENTS_INDEX!r} query"
            f" ({type(exc).__name__}: {exc})"
        ) from exc

    keyword_hits = _moment_hits_of(keyword_response)
    semantic_hits: tuple[MomentHit, ...] = ()
    dropped = 0
    if semantic_response is not None:
        semantic_hits, dropped = apply_semantic_floor(
            _moment_hits_of(semantic_response),
            config.settings.api.search.semantic_score_floor,
        )
    merged = merge_search_lanes(
        keyword_hits,
        semantic_hits,
        config.settings.api.search.semantic_ratio
        if semantic_response is not None
        else 0.0,
        candidate_count,
    )
    # Both Meilisearch totals are estimates. The larger is the least misleading
    # lower-bound-like estimate for the blended, de-duplicated result set.
    estimated_total = max(
        _estimated_total_of(keyword_response),
        _estimated_total_of(semantic_response) if semantic_response is not None else 0,
    )
    if offset == 0 and not keyword_hits and not semantic_hits and dropped:
        # The keyword lane proved that no lexical match exists, and every
        # semantic neighbour was below the floor. Reporting the store's raw
        # semantic estimate would claim matches that this endpoint deliberately
        # refuses to expose.
        estimated_total = 0
    return MomentSearchResult(
        hits=merged[offset : offset + limit],
        estimated_total=estimated_total,
        limit=limit,
        offset=offset,
        below_floor=dropped,
    )


# --- the artifacts lane (story 4.4) ---------------------------------------


def build_artifact_search_parameters(
    config: AppConfig,
    *,
    limit: int,
    offset: int = 0,
    meeting_id: UUID | None = None,
    corpus: str | None = None,
) -> dict[str, Any]:
    """The Meilisearch request body for one artifacts query. Keyword-only.

    No ``hybrid`` block is ever built here — the artifacts index declares no
    embedder, and asking it for vector ranking would be a store error. The
    filter *always* pins ``state = 'published'``: the publish gate keeps
    anything else out of the index, and this makes the same statement a
    property of every query too (belt and braces, NFR7).
    """
    parameters: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        # The id plus the cited moments: `momentIds` is how a hit resolves to
        # its replayable source moment. Everything else on the wire is re-read
        # from Postgres (AD-2/AD-6).
        "attributesToRetrieve": ["id", "momentIds"],
        "attributesToHighlight": list(ARTIFACT_SNIPPET_ATTRIBUTES),
        "attributesToCrop": list(ARTIFACT_SNIPPET_ATTRIBUTES),
        "cropLength": config.settings.api.search.crop_length,
        "highlightPreTag": HIGHLIGHT_PRE,
        "highlightPostTag": HIGHLIGHT_POST,
        "showRankingScore": True,
        # `frequency`, not Meilisearch's `last` default, because this lane is
        # the one that reads a *question*. `chat._artifact_leg` forwards the
        # user's whole sentence here, and `last` drops query words from the
        # end until something matches — so "What did we decide about the
        # retrieval split?" still has to match "what", "did", "we", "decide"
        # against an index of 11 published titles and bodies that contain none
        # of them, and returns nothing. Measured 2026-08-22 against the live
        # index: that question scored 0 hits under `last` and the 2 correct
        # ADR/action-item rows under `frequency`, which drops the *most
        # common* words first and leaves the terms that carry the question.
        # The moments lane needs no equivalent — it is hybrid, and its
        # embedder already carries sentence-shaped input (NFR7).
        "matchingStrategy": "frequency",
    }
    clauses = [f'state = "{PUBLISHED_STATE}"']
    scope = build_filter(meeting_id, corpus)
    if scope is not None:
        clauses.append(scope)
    parameters["filter"] = " AND ".join(clauses)
    return parameters


def _artifact_hits_of(response: Any) -> tuple[ArtifactHit, ...]:
    """Validate one artifacts-index response into resolvable candidate hits."""
    hits: list[ArtifactHit] = []
    for hit in _hits_of(response):
        raw_id = hit.get("id")
        if raw_id is None:
            raise ProjectionError(
                f"an {ARTIFACTS_INDEX!r} hit carried no id — every document in"
                " this index is keyed on a Postgres artifact id (AD-6)"
            )
        try:
            artifact_id = UUID(str(raw_id))
        except ValueError as exc:
            raise ProjectionError(
                f"an {ARTIFACTS_INDEX!r} hit carried an id that is not a UUID:"
                f" {raw_id!r} — every document in this index is keyed on a"
                " Postgres artifact id (AD-6)"
            ) from exc
        raw_moments = hit.get("momentIds")
        moment_ids: list[UUID] = []
        if isinstance(raw_moments, Sequence) and not isinstance(
            raw_moments, (str, bytes)
        ):
            for raw_moment in raw_moments:
                try:
                    moment_ids.append(UUID(str(raw_moment)))
                except ValueError:
                    # A malformed moment id costs that edge, not the hit: the
                    # api's Postgres read-back is the authority on the source
                    # moment anyway.
                    continue
        raw_score = hit.get("_rankingScore")
        try:
            score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError) as exc:
            raise ProjectionError(
                "Meilisearch returned an invalid ranking score"
            ) from exc
        hits.append(
            ArtifactHit(
                artifact_id=artifact_id,
                moment_ids=tuple(moment_ids),
                snippet=_snippet_of(hit.get("_formatted"), ARTIFACT_SNIPPET_ATTRIBUTES),
                score=score,
            )
        )
    return tuple(hits)


def search_artifacts(
    client: meilisearch.Client,
    config: AppConfig,
    *,
    query: str,
    limit: int,
    offset: int = 0,
    meeting_id: UUID | None = None,
    corpus: str | None = None,
) -> ArtifactSearchResult:
    """Rank the artifacts index for ``query``. Keyword-only, published-only.

    :data:`ARTIFACT_SEARCHABLE_INDEXES` states in code (and the query test
    suite pins) that this lane reads the artifacts index alone; the function
    names :data:`ARTIFACTS_INDEX` directly rather than re-checking a constant
    against a constant derived from it. A missing index is reported rather
    than raised — a store from before the artifacts index existed holds
    nothing published, and the caller logs the distinction.
    """
    parameters = build_artifact_search_parameters(
        config,
        limit=limit,
        offset=offset,
        meeting_id=meeting_id,
        corpus=corpus,
    )
    try:
        index = client.index(ARTIFACTS_INDEX)
        # ``estimatedTotalHits`` is explicitly unstable across offset/limit
        # pages and therefore cannot divide the combined artifact/moment
        # sequence. A page-style count query returns exhaustive ``totalHits``.
        # Keep the ordinary offset query for arbitrary (not page-aligned)
        # offsets and for the requested snippets/ranking metadata.
        count_parameters = dict(parameters)
        count_parameters.pop("limit", None)
        count_parameters.pop("offset", None)
        count_parameters["hitsPerPage"] = 0
        count_response = index.search(query, count_parameters)
        total = _total_hits_of(count_response)
        response = (
            index.search(query, parameters)
            if offset < total and limit > 0
            else {"hits": ()}
        )
    except MeilisearchApiError as exc:
        if _is_index_missing(exc):
            return ArtifactSearchResult(
                hits=(), limit=limit, offset=offset, index_missing=True
            )
        raise ProjectionError(
            f"Meilisearch refused the {ARTIFACTS_INDEX!r} query: {exc}"
        ) from exc
    except (MeilisearchCommunicationError, MeilisearchTimeoutError) as exc:
        raise StoreUnavailableError(
            f"Meilisearch became unreachable during the {ARTIFACTS_INDEX!r}"
            f" query ({type(exc).__name__}: {exc})"
        ) from exc
    except MeilisearchError as exc:  # pragma: no cover - client-shape change
        raise ProjectionError(
            f"Meilisearch failed the {ARTIFACTS_INDEX!r} query"
            f" ({type(exc).__name__}: {exc})"
        ) from exc
    return ArtifactSearchResult(
        hits=_artifact_hits_of(response),
        total=total,
        limit=limit,
        offset=offset,
    )


# --- the extraction-documents lane (story 12.4) ---------------------------


def build_document_search_parameters(
    config: AppConfig,
    *,
    limit: int,
    offset: int = 0,
    meeting_id: UUID | None = None,
    corpus: str | None = None,
) -> dict[str, Any]:
    """The Meilisearch request body for one extraction-document query.

    Keyword-only: the documents index declares no embedder, so asking it for
    vector ranking would be a store error — and making documents depend on the
    model host would let an Ollama outage withhold exactly the material AD-4's
    exception exists to keep reachable.

    ``attributesToRetrieve`` is the shape of the guarantee, not a bandwidth
    saving. It names the id, the meeting, the kind and the two review fields —
    and **no** moment id, because a document is never a citation target (AD-6).
    Nothing this lane can be asked for could be turned into a citation.

    The filter pins ``reviewState``. Not to withhold: every document is
    reachable, which is the whole exception. It is there because ``unreviewed``
    is the only state a document may carry (`documents.REVIEW_STATE`), so
    anything else in this index was not written by this system, and a query
    that would surface it is a query that would render unlabelled machine
    output as if it were reviewed (AD-18).

    ``matchingStrategy`` is ``frequency`` for the reason the artifacts lane
    records: this lane reads a *question* from the chat path, and ``last``
    would drop the terms that carry it.
    """
    parameters: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "attributesToRetrieve": [
            "id",
            "meetingId",
            "kind",
            "reviewState",
            "authorship",
            "reviewLabel",
            "citable",
        ],
        "attributesToHighlight": list(DOCUMENT_SNIPPET_ATTRIBUTES),
        "attributesToCrop": list(DOCUMENT_SNIPPET_ATTRIBUTES),
        "cropLength": config.settings.api.search.crop_length,
        "highlightPreTag": HIGHLIGHT_PRE,
        "highlightPostTag": HIGHLIGHT_POST,
        "showRankingScore": True,
        "matchingStrategy": "frequency",
    }
    clauses = [f'reviewState = "{REVIEW_STATE}"']
    scope = build_filter(meeting_id, corpus)
    if scope is not None:
        clauses.append(scope)
    parameters["filter"] = " AND ".join(clauses)
    return parameters


def _document_hits_of(response: Any) -> tuple[DocumentHit, ...]:
    """Validate one documents-index response into resolvable candidate hits.

    A hit missing its review label is refused rather than defaulted. The label
    is the AD-18 half of the gate exception, and a lane that silently supplied
    a plausible sentence for a record that did not carry one would make an
    unlabelled document indistinguishable from a labelled one — the exact
    substitution AD-18 forbids.
    """
    hits: list[DocumentHit] = []
    for hit in _hits_of(response):
        raw_id = hit.get("id")
        if raw_id is None:
            raise ProjectionError(
                f"a {DOCUMENTS_INDEX!r} hit carried no id — every document in"
                " this index is keyed on a Postgres extraction_source id"
            )
        try:
            document_id = UUID(str(raw_id))
        except ValueError as exc:
            raise ProjectionError(
                f"a {DOCUMENTS_INDEX!r} hit carried an id that is not a UUID:"
                f" {raw_id!r} — every document in this index is keyed on a"
                " Postgres extraction_source id"
            ) from exc
        raw_meeting = hit.get("meetingId")
        try:
            meeting_id = UUID(str(raw_meeting))
        except (TypeError, ValueError) as exc:
            raise ProjectionError(
                f"a {DOCUMENTS_INDEX!r} hit carried no usable meetingId"
                f" ({raw_meeting!r}) — a document is scoped to the meeting it"
                " analyses, and the api re-reads it from Postgres by that id"
            ) from exc
        review_state = hit.get("reviewState")
        authorship = hit.get("authorship")
        review_label = hit.get("reviewLabel")
        citable = hit.get("citable")
        if (
            review_state != REVIEW_STATE
            or authorship != AUTHORSHIP
            or review_label != REVIEW_LABEL
            or citable is not False
        ):
            raise ProjectionError(
                f"a {DOCUMENTS_INDEX!r} hit carried reviewState"
                f" {review_state!r}, authorship {authorship!r} and reviewLabel"
                f" {review_label!r}, citable {citable!r} — an"
                " extraction document is indexed without passing the publish"
                " gate, so it must carry its unreviewed, machine-written status"
                " in the record itself; refusing to surface an unlabelled one"
                " (AD-18). Run 'rebuild --meeting <id>' to rewrite it."
            )
        raw_score = hit.get("_rankingScore")
        try:
            score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError) as exc:
            raise ProjectionError(
                "Meilisearch returned an invalid ranking score"
            ) from exc
        hits.append(
            DocumentHit(
                document_id=document_id,
                meeting_id=meeting_id,
                kind=str(hit.get("kind") or ""),
                review_state=str(review_state),
                authorship=str(authorship),
                review_label=str(review_label),
                snippet=_snippet_of(
                    hit.get("_formatted"), DOCUMENT_SNIPPET_ATTRIBUTES
                ),
                score=score,
            )
        )
    return tuple(hits)


def search_documents(
    client: meilisearch.Client,
    config: AppConfig,
    *,
    query: str,
    limit: int,
    offset: int = 0,
    meeting_id: UUID | None = None,
    corpus: str | None = None,
) -> DocumentSearchResult:
    """Rank the extraction-documents index for ``query``. Keyword-only, ungated.

    :data:`DOCUMENT_SEARCHABLE_INDEXES` states in code (and the query test
    suite pins) that this lane reads the documents index alone. A missing index
    is reported rather than raised — a store from before story 12.4 holds no
    documents, and the caller logs the distinction rather than reporting a
    silent zero.
    """
    parameters = build_document_search_parameters(
        config,
        limit=limit,
        offset=offset,
        meeting_id=meeting_id,
        corpus=corpus,
    )
    try:
        index = client.index(DOCUMENTS_INDEX)
        # Exhaustive `totalHits` from a page-style count query, for the same
        # reason the artifacts lane takes one: `estimatedTotalHits` is unstable
        # across offset/limit pages and cannot bound a lane.
        count_parameters = dict(parameters)
        count_parameters.pop("limit", None)
        count_parameters.pop("offset", None)
        count_parameters["hitsPerPage"] = 0
        count_response = index.search(query, count_parameters)
        total = _total_hits_of(count_response)
        response = (
            index.search(query, parameters)
            if offset < total and limit > 0
            else {"hits": ()}
        )
    except MeilisearchApiError as exc:
        if _is_index_missing(exc):
            return DocumentSearchResult(
                hits=(), limit=limit, offset=offset, index_missing=True
            )
        raise ProjectionError(
            f"Meilisearch refused the {DOCUMENTS_INDEX!r} query: {exc}"
        ) from exc
    except (MeilisearchCommunicationError, MeilisearchTimeoutError) as exc:
        raise StoreUnavailableError(
            f"Meilisearch became unreachable during the {DOCUMENTS_INDEX!r}"
            f" query ({type(exc).__name__}: {exc})"
        ) from exc
    except MeilisearchError as exc:  # pragma: no cover - client-shape change
        raise ProjectionError(
            f"Meilisearch failed the {DOCUMENTS_INDEX!r} query"
            f" ({type(exc).__name__}: {exc})"
        ) from exc
    return DocumentSearchResult(
        hits=_document_hits_of(response),
        total=total,
        limit=limit,
        offset=offset,
    )
