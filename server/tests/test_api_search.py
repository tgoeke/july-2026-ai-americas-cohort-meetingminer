"""GET /search end to end: index → ranking → Postgres-resolved citations.

Store-backed. These run against the disposable test-store twins (`neo4j-test`
/ `meilisearch-test`, via the session `app_config` endpoint override — never
the developer's dev stores) and skip with a named reason when the twins are
down. `projection_stores` takes the endpoint-keyed file lock and wipes both
test stores before yielding, so no test here inherits another run's documents.

**Naming, deliberately.** The Meilisearch client is `meili` in every test.
`client` is the TestClient fixture, and one letter of ambiguity between an
HTTP client and a search-store client is how a test ends up asserting against
the wrong thing.

What is worth pinning here rather than in `test_projections_query.py`: that
Meilisearch 1.53 actually ranks these documents (typo tolerance, OCR text,
scoping), and that every citation on the wire came out of Postgres rather than
out of the index.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.api.search import SEARCH_TERM_MAX_LENGTH
from meetingminer.config import AppConfig
from meetingminer.projections.publish_gate import ARTIFACTS_INDEX
from meetingminer.projections.query import ArtifactHit, search_moments
from meetingminer.projections.stores import (
    MOMENTS_INDEX,
    ProjectionError,
    StoreUnavailableError,
    await_task,
)

from conftest import BrokenEmbedder, DownEmbedder, truncate_evidence
from projection_seed import (
    DEEP_LINK,
    SeededMeeting,
    SeededTurn,
    seed_meeting,
)
from projection_seed import insert_artifact as seed_artifact

pytestmark = pytest.mark.slow(reason="/search runs against the Meilisearch test twin: 41 tests, 60.5s at e5510c7")

# A term that appears nowhere in the seeded transcripts, so a hit on it can
# only have come through the OCR text of the screen that was up (AC1).
OCR_ONLY_TERM = "Zylographic"
OCR_TEXT = f"Vendor Portal — {OCR_ONLY_TERM} reconciliation queue"


class SpreadEmbedder:
    """A deterministic `Embedder` whose vectors are near-orthogonal per text.

    `conftest.FakeEmbedder` derives every component from one hash seed plus the
    component index, which makes any two of its vectors almost parallel — fine
    for "did this document get *its* vector", useless here. Semantic ranking is
    the thing under test in the floor cases, and two unrelated passages have to
    score *apart* for the floor to mean anything.

    So each text gets a small set of hash-chosen components set to 1 and the
    rest zero: two different texts share a component only by coincidence, and
    the cosine between them is near zero — which is what an embedding model
    does to unrelated passages, exaggerated for determinism.
    """

    def __init__(self, model: str = "spread-embedder", dimension: int = 1024) -> None:
        self.model = model
        self.dimension = dimension

    def _vector(self, text: str) -> tuple[float, ...]:
        digest = hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest()
        positions = {
            int.from_bytes(digest[index : index + 2], "big") % self.dimension
            for index in range(0, 16, 2)
        }
        return tuple(1.0 if i in positions else 0.0 for i in range(self.dimension))

    def embed_documents(self, texts: Any) -> tuple[tuple[float, ...], ...]:
        return tuple(self._vector(text) for text in texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._vector(text)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


@pytest.fixture()
def embedder(app_config: AppConfig) -> SpreadEmbedder:
    return SpreadEmbedder(dimension=app_config.settings.embedder.dimension)


@pytest.fixture()
def search_client(client: Any, embedder: SpreadEmbedder) -> Iterator[Any]:
    """The TestClient with a stand-in embedder bound, restored afterwards.

    The route reads `app.state.embedder`, which `api/main` binds once at
    import. Swapping it per test is how the degrade/refuse split is exercised
    without a real Ollama — and restoring it is what stops one test's broken
    embedder from following the app into the next.
    """
    import meetingminer.api.main as api_main

    original = api_main.app.state.embedder
    api_main.app.state.embedder = embedder
    try:
        yield client
    finally:
        api_main.app.state.embedder = original


def bind_embedder(search_client: Any, replacement: Any) -> None:
    """Point the app at a different embedder for the rest of one test."""
    import meetingminer.api.main as api_main

    api_main.app.state.embedder = replacement


def project(
    pool: ConnectionPool, config: AppConfig, meeting_id: UUID, embedder: Any
) -> None:
    with pool.connection() as conn:
        projections.project_meeting(
            conn, config, meeting_id, embedder_factory=lambda: embedder
        )


def attach_ocr(
    pool: ConnectionPool, seeded: SeededMeeting, text: str, *, offset_ms: int = 4_000
) -> None:
    """Give the meeting's first screenshot a representative frame carrying OCR text.

    `projection_seed` builds screenshots without frames — the projections it
    was written for never read one. The path this story adds does:
    `screenshot.representative_frame_id` → `frame_ocr.text` is what carries
    OCR text into the index, so the fixture has to build both hops.
    """
    with pool.connection() as conn:
        frame_id = conn.execute(
            "INSERT INTO frame (meeting_id, offset_ms, path)"
            " VALUES (%s, %s, %s) RETURNING id",
            (
                seeded.meeting_id,
                offset_ms,
                f"meetings/{seeded.meeting_id}/frames/f.jpg",
            ),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO frame_ocr (frame_id, meeting_id, engine, text,"
            " normalized_text, block_count, text_density, mean_block_height)"
            " VALUES (%s, %s, 'apple-vision', %s, %s, 4, 0.1, 0.05)",
            (frame_id, seeded.meeting_id, text, text.casefold()),
        )
        conn.execute(
            "UPDATE screenshot SET representative_frame_id = %s WHERE id = %s",
            (frame_id, seeded.screenshot_ids[0]),
        )
        conn.commit()


def search(client: Any, **params: Any) -> dict[str, Any]:
    response = client.get("/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def moment_ids(body: dict[str, Any]) -> set[str]:
    return {hit["momentId"] for hit in body["hits"]}


# --- the happy path -------------------------------------------------------


def test_a_transcript_term_finds_its_moment_with_a_highlighted_snippet(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-keyword")
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="purchase order")
    assert body["ranking"] == "hybrid"
    assert moment_ids(body) <= {str(m) for m in seeded.moment_ids}
    assert body["hits"], body

    hit = body["hits"][0]
    # The snippet is structured runs, never markup: the web app wraps the
    # highlighted ones itself (AD-15's principle applied to snippets).
    assert isinstance(hit["snippet"], list)
    assert any(run["highlighted"] for run in hit["snippet"]), hit["snippet"]
    plain = "".join(run["text"] for run in hit["snippet"])
    # Neither markup nor the private-use delimiters reach the client: the
    # sentinels are consumed by the parser, and the runs carry plain text.
    assert "<" not in plain
    assert "\ue000" not in plain and "\ue001" not in plain
    assert "purchase" in plain.casefold()


def test_a_term_only_in_the_screens_ocr_text_still_finds_the_moment(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """AC1: the full-text index spans transcripts *and* OCR text."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-ocr")
    attach_ocr(pool, seeded, OCR_TEXT)
    project(pool, app_config, seeded.meeting_id, embedder)

    # The term is genuinely absent from every transcript segment, so a hit
    # cannot have come from the transcript half of the index.
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT count(*) FROM transcript_segment WHERE meeting_id = %s"
            " AND text ILIKE %s",
            (seeded.meeting_id, f"%{OCR_ONLY_TERM}%"),
        ).fetchone()
    assert rows[0] == 0

    body = search(search_client, q=OCR_ONLY_TERM)
    assert body["hits"], body
    assert moment_ids(body) <= {str(m) for m in seeded.moment_ids}
    # And the snippet shows the screen text, not the opening of the transcript.
    plain = "".join(run["text"] for run in body["hits"][0]["snippet"])
    assert OCR_ONLY_TERM.casefold() in plain.casefold()


def test_a_typo_still_finds_the_moment(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """The `typo` ranking rule, exercised rather than assumed."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-typo")
    project(pool, app_config, seeded.meeting_id, embedder)

    exact = search(search_client, q="purchase order")
    typo = search(search_client, q="purchse order")
    assert typo["hits"], typo
    assert moment_ids(typo) & moment_ids(exact)


def test_every_citation_field_is_read_back_from_postgres(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """AC2/AD-6: the index ranks; the database of record cites.

    Proved by making the two disagree. The index document is edited in place
    to carry a wrong `startMs` and a wrong `meetingId`; the response must
    still carry the row's values, because it never read the document's.
    """
    _driver, meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-citations")
    project(pool, app_config, seeded.meeting_id, embedder)

    poisoned = str(uuid4())
    await_task(
        meili,
        meili.index(MOMENTS_INDEX).update_documents(
            [
                {"id": str(moment_id), "startMs": 999_999, "meetingId": poisoned}
                for moment_id in seeded.moment_ids
            ]
        ),
    )

    body = search(search_client, q="purchase order")
    assert body["hits"], body
    with pool.connection() as conn:
        rows = {
            str(row[0]): (row[1], row[2], row[3])
            for row in conn.execute(
                "SELECT id, start_ms, end_ms, meeting_id FROM moment"
                " WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchall()
        }
    for hit in body["hits"]:
        start_ms, end_ms, meeting_id = rows[hit["momentId"]]
        assert hit["startMs"] == start_ms
        assert hit["endMs"] == end_ms
        assert hit["meetingId"] == str(meeting_id) != poisoned
        assert hit["meetingTitle"] == "Data Hub Demo"


def test_a_transcript_only_hit_offers_the_deep_link_instead_of_replay(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """UX-DR11 / AD-15: no recording means the transitional link stands in."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(
            conn, source_id="search-api-transcript-only", has_recording=False
        )
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="purchase order")
    assert body["hits"], body
    for hit in body["hits"]:
        assert hit["hasRecording"] is False
        assert hit["screenshotId"] is None
        assert hit["sourceDeepLink"] == DEEP_LINK


def test_a_meeting_name_query_finds_that_meetings_moments(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """AC1's second input kind: "a meeting name".

    `title` is a searchable attribute, so the words of the meeting's name match
    every moment in it. The snippet has to carry a highlighted run either way —
    a hit with nothing marked is a result the user cannot see the reason for.
    """
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-title", title="Data Hub Demo")
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="Data Hub Demo")
    assert body["hits"], body
    assert moment_ids(body) <= {str(m) for m in seeded.moment_ids}
    for hit in body["hits"]:
        assert any(run["highlighted"] for run in hit["snippet"]), hit["snippet"]


def test_a_speaker_name_query_finds_the_moments_they_spoke_in(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """AC1's third input kind: "a mention".

    `speakers` is an array attribute, so its `_formatted` value is an array
    too — the snippet parser has to reach inside it to find the highlight.
    """
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-speaker")
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="Whitmore")
    assert body["hits"], body
    assert moment_ids(body) <= {str(m) for m in seeded.moment_ids}
    for hit in body["hits"]:
        assert any(run["highlighted"] for run in hit["snippet"]), hit["snippet"]


# The first moment matches one query word, the second matches both — so
# Meilisearch's `words` rule ranks the *later* moment first, which is neither
# the moments' `start_ms` order nor the order Postgres minted them in. That
# disagreement is the whole point: it is what a test can see.
#
# The word order in RANKING_QUERY is load-bearing. Meilisearch's default
# `last` matching strategy drops query terms from the *end* when the full
# query returns too few documents, so the term the two moments share has to
# come first — otherwise the partial match never reaches the keyword lane at
# all and arrives as a semantic hit the floor discards.
RANKING_TURNS: tuple[SeededTurn, ...] = (
    SeededTurn(
        1, 2_000, "Quick note on the approval we still owe.", "Goeke, Timothy", 0
    ),
    SeededTurn(2, 5_000, "Understood.", "Whitmore, Ellis", 1),
    SeededTurn(
        3, 40_000, "The purchase order still needs approval.", "Whitmore, Ellis", 1
    ),
)
RANKING_QUERY = "approval purchase"


def test_the_response_is_ordered_by_the_index_not_by_the_database(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """Meilisearch ranks. The Postgres read-back cites — it must not re-sort.

    `_resolve` reads the whole page in one statement and then reconstructs the
    index's order from the rows. Nothing else in this file would notice if that
    reconstruction were dropped and the database's own row order used instead,
    because every other assertion compares sets or a single row.
    """
    _driver, meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-ranking", turns=RANKING_TURNS)
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q=RANKING_QUERY)
    returned = [hit["momentId"] for hit in body["hits"]]

    # The store's own answer for the same query, asked directly. The route is
    # required to publish this order verbatim.
    ranked = search_moments(
        meili,
        app_config,
        query=RANKING_QUERY,
        limit=app_config.settings.api.search.default_limit,
        query_vector=embedder.embed_query(RANKING_QUERY),
    )
    assert returned == [str(hit.moment_id) for hit in ranked.hits]

    # And it is a real ordering claim, not a tautology: the ranking disagrees
    # with the order the rows come out of Postgres in.
    assert len(returned) == 2, body
    with pool.connection() as conn:
        by_start = [
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM moment WHERE meeting_id = %s ORDER BY start_ms",
                (seeded.meeting_id,),
            ).fetchall()
        ]
    assert returned == list(reversed(by_start))


def test_an_explicit_limit_and_offset_page_through_the_ranking(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """Paging, exercised rather than only refused.

    The 422 cases pin what `limit` and `offset` reject; nothing pinned what
    they *do*. A `limit` that was accepted and then ignored, or an `offset`
    never forwarded to the store, would look identical to a caller reading only
    the refusal tests.
    """
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-paging")
    project(pool, app_config, seeded.meeting_id, embedder)

    # Every moment of the meeting matches its own title, so there are at least
    # two hits to page through.
    whole = search(search_client, q="Data Hub Demo")
    assert len(whole["hits"]) >= 2, whole

    first = search(search_client, q="Data Hub Demo", limit=1, offset=0)
    assert first["limit"] == 1
    assert first["offset"] == 0
    assert len(first["hits"]) == 1

    second = search(search_client, q="Data Hub Demo", limit=1, offset=1)
    assert second["offset"] == 1
    assert len(second["hits"]) == 1
    # A second page that repeated the first would mean `offset` never reached
    # the store.
    assert moment_ids(second) != moment_ids(first)
    assert [hit["momentId"] for hit in whole["hits"]][:2] == [
        first["hits"][0]["momentId"],
        second["hits"][0]["momentId"],
    ]


# --- scoping --------------------------------------------------------------


def test_a_meeting_scope_returns_only_that_meetings_moments(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="search-api-scope-a")
        second = seed_meeting(
            conn,
            source_id="search-api-scope-b",
            title="Second Meeting",
            screen_identity_keys=("sha256:screen-c",),
        )
    project(pool, app_config, first.meeting_id, embedder)
    project(pool, app_config, second.meeting_id, embedder)

    body = search(search_client, q="purchase order", meetingId=str(first.meeting_id))
    assert body["hits"], body
    assert {hit["meetingId"] for hit in body["hits"]} == {str(first.meeting_id)}


def test_an_unknown_meeting_id_is_an_empty_result_not_a_404(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """`meetingId` is a filter, not a lookup — nothing was asked to exist."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-unknown-scope")
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="purchase order", meetingId=str(uuid4()))
    assert body["hits"] == []
    assert body["estimatedTotal"] == 0


def test_a_corpus_scope_excludes_the_other_corpus(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """What keeps the `real` demo corpus out of a measured eval result set."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        scripted = seed_meeting(
            conn, source_id="search-api-scripted", corpus="scripted"
        )
        real = seed_meeting(
            conn,
            source_id="search-api-real",
            corpus="real",
            screen_identity_keys=("sha256:screen-d",),
        )
    project(pool, app_config, scripted.meeting_id, embedder)
    project(pool, app_config, real.meeting_id, embedder)

    body = search(search_client, q="purchase order", corpus="scripted")
    assert body["hits"], body
    assert {hit["corpus"] for hit in body["hits"]} == {"scripted"}
    assert str(real.meeting_id) not in {hit["meetingId"] for hit in body["hits"]}


def test_a_query_nothing_matches_is_an_empty_result(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """Empty is a valid answer, distinct from an error.

    Reachable only because the semantic floor exists: the vector lane returns
    the k nearest moments for any query at all, so without it a nonsense query
    would come back with the corpus.
    """
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-no-match")
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="zzzzzzzz")
    assert body["hits"] == []
    assert body["estimatedTotal"] == 0
    assert body["ranking"] == "hybrid"


# --- the publish gate's other half ---------------------------------------


def test_an_unpublished_artifact_document_never_surfaces(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """NFR7 / AC4, rewritten by story 4.4: the artifacts index *is* queried
    now, but only through the keyword lane whose every request pins
    `state = 'published'` in its filter.

    The draft document is written straight into the artifacts index — around
    the publish gate, which would have refused it — precisely so the
    assertion is about the *query* side: even a draft that somehow reached
    the store never comes back, because the lane's filter excludes it.
    """
    _driver, meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-artifact-gate")
    project(pool, app_config, seeded.meeting_id, embedder)

    await_task(
        meili,
        meili.create_index(ARTIFACTS_INDEX, {"primaryKey": "id"}),
        tolerate=("index_already_exists",),
    )
    await_task(
        meili,
        meili.index(ARTIFACTS_INDEX).add_documents(
            [
                {
                    "id": str(uuid4()),
                    "meetingId": str(seeded.meeting_id),
                    "state": "extracted",
                    "text": "the purchase order draft nobody approved",
                }
            ]
        ),
    )

    body = search(search_client, q="purchase order")
    # Every hit is a moment of the seeded meeting; the draft is nowhere.
    assert moment_ids(body) <= {str(m) for m in seeded.moment_ids}
    for hit in body["hits"]:
        assert "draft nobody approved" not in "".join(
            run["text"] for run in hit["snippet"]
        )


# --- stale documents ------------------------------------------------------


def test_a_hit_whose_moment_row_is_gone_is_dropped_not_returned(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A citation that resolves nowhere is worse than a missing hit (AD-6).

    One of the two seeded moments is deleted from Postgres while its document
    stays in the index. The surviving hit must still come back — a stale
    neighbour does not invalidate the rest of the page — and the dropped id
    must appear in the log rather than vanishing.
    """
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-stale")
    project(pool, app_config, seeded.meeting_id, embedder)

    doomed = seeded.moment_ids[-1]
    with pool.connection() as conn:
        conn.execute("DELETE FROM moment WHERE id = %s", (doomed,))
        conn.commit()

    capsys.readouterr()
    body = search(search_client, q="purchase order")
    assert str(doomed) not in moment_ids(body)
    assert moment_ids(body) <= {str(m) for m in seeded.moment_ids}
    assert "search.stale_hit" in capsys.readouterr().out


# --- the embedder split ---------------------------------------------------


def test_an_unreachable_model_host_degrades_to_keyword_ranking(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The one embedder failure this system is required to survive.

    BM25 alone carries the dominant query shape (`retrieval-prior-art.md` §7
    finding 1), so an Ollama outage must cost the vector half and nothing
    else — announced on the wire, never silently.

    "Never silently" is two claims, and the log line is the second one: a
    search that quietly loses its vector half looks identical on the wire to a
    corpus that simply has no paraphrase matches, so the reason has to reach
    the log with a name an operator can grep for.
    """
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-degraded")
    project(pool, app_config, seeded.meeting_id, embedder)

    bind_embedder(search_client, DownEmbedder())
    capsys.readouterr()
    body = search(search_client, q="purchase order")
    assert body["ranking"] == "keyword"
    assert body["hits"], body
    assert moment_ids(body) <= {str(m) for m in seeded.moment_ids}

    logged = capsys.readouterr().out
    assert '"event": "search.degraded"' in logged
    assert '"reason": "embedder_unavailable"' in logged


def test_a_zero_semantic_ratio_does_not_call_the_embedder(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """Configured pure-keyword mode is not an embedder outage in disguise."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-pure-keyword")
    project(pool, app_config, seeded.meeting_id, embedder)

    import meetingminer.api.main as api_main

    query_config = api_main.app.state.config.settings.api.search
    original_ratio = query_config.semantic_ratio
    query_config.semantic_ratio = 0.0
    try:
        bind_embedder(search_client, DownEmbedder())
        body = search(search_client, q="purchase order")
    finally:
        query_config.semantic_ratio = original_ratio
    assert body["ranking"] == "keyword"
    assert body["hits"]


def test_a_misconfigured_embedder_is_a_named_503_not_a_degraded_search(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """No silent fallback: a config error must not look like an outage."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-broken-embedder")
    project(pool, app_config, seeded.meeting_id, embedder)

    bind_embedder(search_client, BrokenEmbedder(model="wrong-model", dimension=7))
    response = search_client.get("/search", params={"q": "purchase order"})
    assert response.status_code == 503, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:embedder-unusable"
    assert body["model"] == "wrong-model"
    assert body["dimension"] == 7
    assert "wrong-model" in body["detail"]


# --- refusals -------------------------------------------------------------


def test_an_unreachable_search_store_is_a_named_503(
    monkeypatch: pytest.MonkeyPatch, search_client: Any
) -> None:
    """A store that went down after startup is refused by name, not by traceback.

    Store-free on purpose: the route builds its client per request precisely
    so this failure has somewhere to surface, and simulating the outage is the
    only way to exercise that branch without taking the real Meilisearch away
    from every other worktree sharing this compose stack.

    The distinction being pinned is against the two embedder cases above. All
    three answer 503, and a caller has to be able to tell "the index is gone"
    from "the model host is gone" to know which process to restart — so the
    problem slug, not the status code, is what carries the diagnosis.
    """
    import meetingminer.api.search as api_search

    def refuse(_config: Any) -> Any:
        raise StoreUnavailableError(
            "Meilisearch unreachable at http://localhost:7700 (simulated)"
        )

    monkeypatch.setattr(api_search, "meili_client", refuse)

    response = search_client.get("/search", params={"q": "purchase order"})
    assert response.status_code == 503, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:search-store-unavailable"
    # The store's own reason, carried through rather than flattened into a
    # generic message — it is what names the endpoint that was tried.
    assert "http://localhost:7700" in body["detail"]


def test_a_store_lost_during_the_query_is_a_named_503(
    monkeypatch: pytest.MonkeyPatch, search_client: Any
) -> None:
    """The health check can pass before the actual query loses the store."""
    from meilisearch.errors import MeilisearchCommunicationError
    import meetingminer.api.search as api_search

    class LostIndex:
        def search(self, _query: str, _parameters: dict) -> dict:
            raise MeilisearchCommunicationError("connection lost during search")

    class HealthyThenLostClient:
        def index(self, _name: str) -> LostIndex:
            return LostIndex()

    monkeypatch.setattr(
        api_search, "meili_client", lambda _config: HealthyThenLostClient()
    )
    response = search_client.get("/search", params={"q": "purchase order"})
    assert response.status_code == 503, response.text
    assert (
        response.json()["type"] == "urn:meetingminer:problem:search-store-unavailable"
    )


def test_an_unusable_search_store_is_a_different_named_503(
    monkeypatch: pytest.MonkeyPatch, search_client: Any
) -> None:
    """Reachable but unusable is a different repair from unreachable.

    `meili_client` raises `ProjectionError` when MEILI_MASTER_KEY is unset, and
    `search_moments` raises it when the store refuses the query or returns a
    document with no usable id. None of those is an outage — restarting
    Meilisearch fixes none of them — so they carry their own slug. Before this
    branch existed the whole family escaped as an opaque 500 with a traceback,
    which is the one thing the fail-fast contract forbids.

    `StoreUnavailableError` is a *subclass* of `ProjectionError`, so this test
    and the one above it together pin the clause order too: swap them and every
    outage would be reported under this slug.
    """
    import meetingminer.api.search as api_search

    def refuse(_config: Any) -> Any:
        raise ProjectionError(
            "MEILI_MASTER_KEY is not set — the search projection cannot"
            " authenticate; set it in .env"
        )

    monkeypatch.setattr(api_search, "meili_client", refuse)

    response = search_client.get("/search", params={"q": "purchase order"})
    assert response.status_code == 503, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:search-store-unusable"
    assert "MEILI_MASTER_KEY" in body["detail"]


def test_a_never_projected_index_says_so_rather_than_reporting_no_matches(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ "Never projected" and "nothing matched" need different sentences.

    A fresh install has no moments index at all. Answering that with the same
    empty result a nonsense query gets tells the user to try other words, when
    what they need is to ingest a meeting — and nobody discovers the projection
    never ran (SPEC Constraints, "no silent zero"). So the distinction is both
    logged and on the wire.
    """
    _driver, meili = projection_stores
    await_task(meili, meili.delete_index(MOMENTS_INDEX))

    capsys.readouterr()
    body = search(search_client, q="purchase order")
    assert body["indexMissing"] is True
    assert body["hits"] == []
    assert body["estimatedTotal"] == 0
    assert '"event": "search.index_missing"' in capsys.readouterr().out


def test_a_populated_index_never_claims_to_be_missing(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """The other half of the flag: an empty *result* is not a missing index."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-index-present")
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="zzzzzzzz")
    assert body["hits"] == []
    assert body["indexMissing"] is False


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"q": ""}, id="empty-query"),
        pytest.param({"q": "   "}, id="whitespace-query"),
        pytest.param({"q": "purchase order", "limit": 5000}, id="limit-above-max"),
        pytest.param({"q": "purchase order", "limit": 0}, id="limit-below-one"),
        pytest.param({"q": "purchase order", "offset": -1}, id="negative-offset"),
        pytest.param(
            {"q": "purchase order", "corpus": "invented"}, id="unknown-corpus"
        ),
        pytest.param({"q": "purchase order", "meetingId": "not-a-uuid"}, id="bad-uuid"),
        # An unbounded `q` reaches the embedder as an HTTP body, the index as a
        # query, and every log line the request writes.
        pytest.param(
            {"q": "x" * (SEARCH_TERM_MAX_LENGTH + 1)}, id="query-above-max-length"
        ),
    ],
)
def test_an_invalid_request_is_a_422_problem(
    search_client: Any, params: dict[str, Any]
) -> None:
    """Every one of these is refused at the door, none is silently repaired.

    No store fixture: FastAPI validation and the configured `max_limit` bound
    both answer before anything is queried.
    """
    response = search_client.get("/search", params=params)
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_the_limit_refusal_names_the_configured_bound(
    app_config: AppConfig, search_client: Any
) -> None:
    """Bounded by config, not clamped — and the caller is told the bound."""
    max_limit = app_config.settings.api.search.max_limit
    response = search_client.get(
        "/search", params={"q": "purchase order", "limit": max_limit + 1}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["maxLimit"] == max_limit
    assert str(max_limit) in body["detail"]


def test_the_configured_default_limit_is_reported_back(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-default-limit")
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="purchase order")
    assert body["limit"] == app_config.settings.api.search.default_limit
    assert body["offset"] == 0


# --- the published contract ----------------------------------------------


def test_the_openapi_schema_exposes_search_corpus(search_client: Any) -> None:
    """The generated TS client is built from this; the operationId is its name."""
    schema = search_client.get("/openapi.json").json()
    assert schema["paths"]["/search"]["get"]["operationId"] == "searchCorpus"
    parameters = {
        parameter["name"]
        for parameter in schema["paths"]["/search"]["get"]["parameters"]
    }
    # camelCase at the JSON boundary, including the query parameter.
    assert {"q", "limit", "offset", "meetingId", "corpus"} == parameters


def test_the_response_is_camel_case_at_the_boundary(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-api-camel")
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="purchase order")
    assert set(body) == {
        "query",
        "ranking",
        "hits",
        "estimatedTotal",
        "limit",
        "offset",
        "indexMissing",
    }
    assert body["hits"], body
    assert set(body["hits"][0]) == {
        "momentId",
        "meetingId",
        "meetingTitle",
        "startMs",
        "endMs",
        "startedAt",
        "startedAtPrecision",
        "screenshotId",
        "sourceDeepLink",
        "hasRecording",
        "corpus",
        "snippet",
        "score",
        "artifactId",
        "artifactKind",
        "artifactTitle",
    }
    for key in body["hits"][0]:
        assert "_" not in key, key


# --- published artifacts as citable knowledge (story 4.4) -----------------


def _insert_published_artifact(
    pool: ConnectionPool,
    moment_id: UUID,
    meeting_id: UUID,
    *,
    kind: str = "adr",
    state: str = "published",
    title: str = "Adopt the Quorlix feed",
    body: str = "Decided during the demo.",
) -> UUID:
    # A pool adapter over the one canonical INSERT (projection_seed).
    with pool.connection() as conn:
        return seed_artifact(
            conn, moment_id, meeting_id, kind=kind, state=state, title=title, body=body
        )


def test_a_published_artifact_surfaces_resolved_through_its_source_moment(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """Epics AC3 / CAP-9: the hit names the artifact, and every replay field
    on it is the *source moment's*, read from Postgres in the same request —
    the evidence trail replays the moment that yielded the artifact."""
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-surfaces")
    artifact_id = _insert_published_artifact(
        pool, seeded.moment_ids[0], seeded.meeting_id
    )
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="Quorlix")
    artifact_hits = [hit for hit in body["hits"] if hit["artifactId"] is not None]
    assert len(artifact_hits) == 1
    hit = artifact_hits[0]
    assert hit["artifactId"] == str(artifact_id)
    assert hit["artifactKind"] == "adr"
    assert hit["artifactTitle"] == "Adopt the Quorlix feed"
    # The replay trail is the source moment's, from Postgres.
    assert hit["momentId"] == str(seeded.moment_ids[0])
    assert hit["meetingId"] == str(seeded.meeting_id)
    assert isinstance(hit["startMs"], int)
    assert hit["hasRecording"] is True
    assert hit["screenshotId"] is not None
    # The artifact hit leads the page, ahead of any moment hits.
    assert body["hits"][0]["artifactId"] == str(artifact_id)
    # And a moment hit carries no artifact fields.
    for other in body["hits"][1:]:
        assert other["artifactId"] is None


def test_a_stale_artifact_hit_is_dropped_and_logged(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
    capsys: Any,
) -> None:
    """A document the index still holds for a row that is gone or no longer
    `published` resolves nowhere — dropped, logged, never returned (the
    artifact sibling of `search.stale_hit`)."""
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-stale")
    artifact_id = _insert_published_artifact(
        pool, seeded.moment_ids[0], seeded.meeting_id
    )
    project(pool, app_config, seeded.meeting_id, embedder)

    # The row's state moves out from under the index. There is no unpublish
    # route — this is raw surgery standing in for any index/Postgres skew.
    with pool.connection() as conn:
        conn.execute(
            "UPDATE artifact SET state = 'extracted' WHERE id = %s", (artifact_id,)
        )
        conn.commit()

    body = search(search_client, q="Quorlix")
    assert all(hit["artifactId"] is None for hit in body["hits"])
    assert "search.stale_artifact_hit" in capsys.readouterr().out


_SFTP_TURNS = (
    SeededTurn(1, 2_000, "We moved that feed to SFTP last week.", "Speaker 1", None),
    SeededTurn(
        2, 40_000, "The SFTP transfer finished successfully.", "Speaker 2", None
    ),
)


def test_a_stale_artifact_slot_does_not_duplicate_moments_across_pages(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(
            conn, source_id="search-stale-artifact-pages", turns=_SFTP_TURNS
        )
    artifact_id = _insert_published_artifact(
        pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        title="SFTP",
        body="This indexed slot will become stale.",
    )
    project(pool, app_config, seeded.meeting_id, embedder)
    with pool.connection() as conn:
        conn.execute(
            "UPDATE artifact SET state = 'extracted' WHERE id = %s", (artifact_id,)
        )
        conn.commit()

    pages = [
        search(search_client, q="SFTP", limit=1, offset=offset)
        for offset in range(3)
    ]
    # Offset zero is the consumed-but-dropped artifact slot. The two moment
    # slots follow once each; neither may fill the stale slot and repeat.
    assert pages[0]["hits"] == []
    identities = [page["hits"][0]["momentId"] for page in pages[1:]]
    assert len(identities) == len(set(identities)) == 2
    assert set(identities) == {str(moment_id) for moment_id in seeded.moment_ids}


def test_artifact_rank_survives_search_postgres_readback(
    pool: ConnectionPool,
) -> None:
    import meetingminer.api.search as api_search

    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-readback-rank")
    lower = _insert_published_artifact(
        pool, seeded.moment_ids[0], seeded.meeting_id, title="Lower ranked"
    )
    higher = _insert_published_artifact(
        pool, seeded.moment_ids[1], seeded.meeting_id, title="Higher ranked"
    )
    resolved = api_search._resolve_artifacts(
        pool,
        (
            ArtifactHit(higher, (seeded.moment_ids[1],), (), 0.9),
            ArtifactHit(lower, (seeded.moment_ids[0],), (), 0.5),
        ),
    )
    assert [hit.artifact_id for hit in resolved] == [higher, lower]


def test_the_combined_page_never_exceeds_the_requested_limit(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """A published artifact and a matching moment both rank for the same
    query: the artifacts lane is fetched up to the page limit *in addition*
    to a full moments page, so the combined first page must be capped at the
    caller's `limit` rather than silently returning up to double it."""
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-page-cap", turns=_SFTP_TURNS)
    artifact_id = _insert_published_artifact(
        pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        title="Move the feed to SFTP",
        body="Decided during the demo.",
    )
    project(pool, app_config, seeded.meeting_id, embedder)

    body = search(search_client, q="SFTP", limit=1)
    assert len(body["hits"]) == 1
    assert body["hits"][0]["artifactId"] == str(artifact_id)


def test_artifact_first_paging_reaches_every_artifact_and_moment_exactly_once(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    search_client: Any,
    embedder: SpreadEmbedder,
) -> None:
    """Two artifacts plus two moments form one four-hit paging sequence.

    This is non-vacuous against the reviewed implementation: with ``limit=1``
    it discarded the first moment behind the artifact, then began page two at
    moment offset one, making that displaced hit unreachable forever.
    """
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-page-offset", turns=_SFTP_TURNS)
    artifact_id = _insert_published_artifact(
        pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        title="Move the feed to SFTP",
        body="Decided during the demo.",
    )
    second_artifact_id = _insert_published_artifact(
        pool,
        seeded.moment_ids[1],
        seeded.meeting_id,
        title="Verify the SFTP transfer",
        body="The second published decision also matches SFTP.",
    )
    project(pool, app_config, seeded.meeting_id, embedder)

    pages = [
        search(search_client, q="SFTP", limit=1, offset=offset) for offset in range(4)
    ]
    identities = [
        (page["hits"][0]["artifactId"] or page["hits"][0]["momentId"]) for page in pages
    ]
    assert set(identities[:2]) == {str(artifact_id), str(second_artifact_id)}
    assert set(identities[2:]) == {str(moment_id) for moment_id in seeded.moment_ids}
    assert len(set(identities)) == 4
    assert [page["estimatedTotal"] for page in pages] == [4, 4, 4, 4]
