"""The Meilisearch projection: document shape, settings, vectors, refusals.

Store-backed; skips with a named reason when the test stores are down. See
`test_projections_graph.py` for why these write to the disposable test-store
twins (never the developer's dev indexes).

The theme running through this file is `retrieval-prior-art.md` §7 finding 1:
BM25 alone beat all nine embedding models on transcript-worded queries, so a
meeting with no vectors is *fully functional* here. Several tests assert
exactly that, because it is what makes an Ollama outage an inconvenience
rather than a broken ingest.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from meilisearch.errors import MeilisearchCommunicationError, MeilisearchError
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.config import AppConfig
from meetingminer.projections import search
from meetingminer.projections.publish_gate import (
    Artifact,
    PublishGateRefused,
    artifact_document,
    assert_publishable,
    is_publishable,
)
from meetingminer.projections.stores import (
    CHUNKS_INDEX,
    EMBEDDER_NAME,
    MOMENTS_INDEX,
    DimensionMismatchError,
    ProjectionError,
    StoreUnavailableError,
    declared_embedders,
    ensure_artifact_search_schema,
    ensure_search_schema,
    stored_dimension,
)

from conftest import (
    DownEmbedder,
    FakeEmbedder,
    _repoint_stores_at_test_twins,
    truncate_evidence,
)
from repo_paths import REPO_ROOT
from projection_seed import DEEP_LINK, SeededTurn, seed_meeting
from projection_seed import insert_artifact as seed_artifact


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


def project(
    pool: ConnectionPool, config: AppConfig, meeting_id: UUID, embedder: Any
) -> projections.ProjectionOutcome:
    with pool.connection() as conn:
        return projections.project_meeting(
            conn, config, meeting_id, embedder_factory=lambda: embedder
        )


def settings_of(client: Any, index_uid: str) -> dict[str, Any]:
    raw = client.index(index_uid).get_settings()
    return raw if isinstance(raw, dict) else dict(getattr(raw, "__dict__", {}))


def documents_of(client: Any, index_uid: str, meeting_id: UUID) -> list[dict[str, Any]]:
    result = client.index(index_uid).get_documents(
        {"filter": f'meetingId = "{meeting_id}"', "limit": 1000}
    )
    return [dict(document) for document in result.results]


# --- document shape -------------------------------------------------------


def test_moment_documents_carry_the_citation_shape(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-moments")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    documents = documents_of(client, MOMENTS_INDEX, seeded.meeting_id)
    assert {UUID(document["id"]) for document in documents} == set(seeded.moment_ids)
    for document in documents:
        assert document["meetingId"] == str(seeded.meeting_id)
        assert document["corpus"] == "real"
        assert document["text"]
        assert document["hasScreenshot"] is True
        assert UUID(document["screenshotId"]) in set(seeded.screenshot_ids)


def test_a_transcript_only_meetings_moments_carry_a_deep_link_and_no_screenshot(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(
            conn, source_id="search-transcript-only", has_recording=False
        )
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    for document in documents_of(client, MOMENTS_INDEX, seeded.meeting_id):
        assert document["screenshotId"] is None
        assert document["hasScreenshot"] is False
        assert document["sourceDeepLink"] == DEEP_LINK
    # And its chunks are searchable, which is the point of "transcript-only is
    # first class" rather than degraded.
    hits = client.index(CHUNKS_INDEX).search(
        "purchase order", {"filter": f'meetingId = "{seeded.meeting_id}"'}
    )
    assert hits["hits"], hits


def test_chunk_documents_resolve_back_to_citable_moments(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-chunks")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    documents = documents_of(client, CHUNKS_INDEX, seeded.meeting_id)
    assert documents
    for document in documents:
        assert UUID(document["id"]) in set(seeded.segment_ids)
        assert document["momentIds"], "a chunk must resolve to a moment (AD-6)"
        assert set(document["momentIds"]) <= {str(m) for m in seeded.moment_ids}


def test_chunk_documents_retain_each_raw_speaker_label_and_resolution(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """Resolution is per turn: labels must not collapse into unsafe identity."""
    _driver, client = projection_stores
    turns = (
        SeededTurn(
            1, 0, "Please repeat that.", "Jordan", speaker_resolution="unresolved"
        ),
        SeededTurn(
            2, 3_000, "Was that Jordan?", "Jordan", speaker_resolution="ambiguous"
        ),
        SeededTurn(
            3, 6_000, "System message.", "Speaker 9", speaker_resolution="placeholder"
        ),
    )
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-speaker-resolution", turns=turns)
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    values = [
        entry
        for doc in documents_of(client, CHUNKS_INDEX, seeded.meeting_id)
        for entry in doc["speakerTurns"]
    ]
    assert values == [
        {"speakerLabel": "Jordan", "speakerResolution": "unresolved"},
        {"speakerLabel": "Jordan", "speakerResolution": "ambiguous"},
        {"speakerLabel": "Speaker 9", "speakerResolution": "placeholder"},
    ]


def test_corpus_is_filterable_so_an_eval_run_can_scope_to_scripted(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    _driver, client = projection_stores
    with pool.connection() as conn:
        scripted = seed_meeting(conn, source_id="search-scripted", corpus="scripted")
        real = seed_meeting(
            conn,
            source_id="search-real",
            corpus="real",
            screen_identity_keys=("sha256:screen-r",),
        )
    project(pool, app_config, scripted.meeting_id, fake_embedder)
    project(pool, app_config, real.meeting_id, fake_embedder)

    hits = client.index(CHUNKS_INDEX).search(
        "purchase order", {"filter": 'corpus = "scripted"'}
    )
    assert hits["hits"]
    assert {hit["meetingId"] for hit in hits["hits"]} == {str(scripted.meeting_id)}


# --- deliberate settings --------------------------------------------------


def test_index_settings_match_config_and_no_auto_embedder_is_registered(
    app_config: AppConfig, projection_stores: Any
) -> None:
    """The AC's read-back: attributes, rules, boosts, synonyms, no auto-embedder."""
    _driver, client = projection_stores
    configured = app_config.settings.projections.search
    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX as _ARTIFACTS

    for index_uid, index_config in (
        (MOMENTS_INDEX, configured.moments),
        (CHUNKS_INDEX, configured.chunks),
        (_ARTIFACTS, configured.artifacts),
    ):
        settings = settings_of(client, index_uid)
        # Order is the field boost — Meilisearch 1.53 has no per-field weight,
        # so an exact list comparison is the assertion, not a set one.
        assert settings["searchableAttributes"] == index_config.searchable_attributes
        assert settings["rankingRules"] == index_config.ranking_rules
        assert set(settings["filterableAttributes"]) == set(
            index_config.filterable_attributes
        )
        assert set(settings["sortableAttributes"]) == set(
            index_config.sortable_attributes
        )
        assert settings["synonyms"] == {
            key: list(values) for key, values in configured.synonyms.items()
        }

        declared = declared_embedders(client, index_uid)
        if index_uid == _ARTIFACTS:
            # Keyword-only (story 4.4): *no* embedder of any source — a
            # publish must never depend on the model host.
            assert declared == {}
            continue
        # `userProvided` is the whole point: this module computes every vector
        # itself through the port, so `rebuild` stays deterministic from
        # Postgres + config alone (AD-4).
        assert set(declared) == {EMBEDDER_NAME}, (
            "no store-native auto-embedder may exist"
        )
        assert declared[EMBEDDER_NAME]["source"] == "userProvided"
        assert (
            declared[EMBEDDER_NAME]["dimensions"]
            == app_config.settings.embedder.dimension
        )


def test_a_configured_domain_synonym_is_actually_in_force(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """Full-text quality funded deliberately (§7): the synonym must do work."""
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-synonyms")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    # The transcript says "SFTP"; the query says "FTP". Only the configured
    # synonym connects them — "ftp" is too short for typo tolerance to bridge.
    hits = client.index(CHUNKS_INDEX).search(
        "ftp", {"filter": f'meetingId = "{seeded.meeting_id}"'}
    )
    assert hits["hits"], hits
    assert any("SFTP" in hit["text"] for hit in hits["hits"])


# --- the structural / embedding split -------------------------------------


def test_a_down_model_host_still_leaves_a_bm25_searchable_meeting(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any
) -> None:
    """§3 rule 4: structural indexing must work with the model host off."""
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-ollama-down")

    outcome = project(pool, app_config, seeded.meeting_id, DownEmbedder())
    assert outcome.structural is True
    assert outcome.embedded is False
    assert outcome.warning and "unreachable" in outcome.warning

    with pool.connection() as conn:
        row = conn.execute(
            "SELECT structural_at, embedded_at FROM meeting_projection WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()
    assert row[0] is not None
    assert row[1] is None

    hits = client.index(CHUNKS_INDEX).search(
        "revenue slide", {"filter": f'meetingId = "{seeded.meeting_id}"'}
    )
    assert hits["hits"], "BM25 retrieval must be fully functional with no vectors"


def test_embed_only_fills_the_vectors_without_a_structural_rewrite(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-embed-only")
    project(pool, app_config, seeded.meeting_id, DownEmbedder())

    def meeting_element_id() -> str:
        with driver.session() as session:
            return session.run(
                "MATCH (m:Meeting {id: $id}) RETURN elementId(m) AS eid",
                id=str(seeded.meeting_id),
            ).single()["eid"]

    before_element = meeting_element_id()
    with pool.connection() as conn:
        before_structural_at = conn.execute(
            "SELECT structural_at FROM meeting_projection WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()[0]

    with pool.connection() as conn:
        outcome = projections.project_meeting_embeddings(
            conn, app_config, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )
    assert outcome.embedded is True
    assert outcome.structural is False

    # No structural rewrite: the graph node was never deleted and recreated,
    # and the recorded structural timestamp did not move.
    assert meeting_element_id() == before_element
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT structural_at, embedded_at FROM meeting_projection WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()
    assert row[0] == before_structural_at
    assert row[1] is not None

    # The vectors are actually on the documents now.
    result = client.index(CHUNKS_INDEX).get_documents(
        {
            "filter": f'meetingId = "{seeded.meeting_id}"',
            "limit": 5,
            "retrieveVectors": True,
        }
    )
    assert result.results
    for document in result.results:
        vectors = dict(document)["_vectors"][EMBEDDER_NAME]
        assert vectors["embeddings"], document


def test_each_document_gets_its_own_vector_in_configured_batches(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any
) -> None:
    """A vector reorder is retrieval corruption even when widths still match."""
    _driver, client = projection_stores
    bounded = app_config.model_copy(deep=True)
    bounded.settings.projections.embed_batch_size = 1
    embedder = FakeEmbedder(dimension=bounded.settings.embedder.dimension)
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-vector-correspondence")

    project(pool, bounded, seeded.meeting_id, embedder)

    for index_uid in (MOMENTS_INDEX, CHUNKS_INDEX):
        result = client.index(index_uid).get_documents(
            {
                "filter": f'meetingId = "{seeded.meeting_id}"',
                "limit": 1000,
                "retrieveVectors": True,
            }
        )
        assert result.results
        for document in result.results:
            body = dict(document)
            # Meilisearch stores vectors as float32, so compare the one
            # stored vector with a tolerance rather than demanding its
            # round-trip representation equal Python's float64 output.
            embeddings = body["_vectors"][EMBEDDER_NAME]["embeddings"]
            assert len(embeddings) == 1
            assert embeddings[0] == pytest.approx(
                embedder.embed_query(body["text"]), abs=1e-7
            )
    assert embedder.calls
    assert all(
        len(batch) <= bounded.settings.projections.embed_batch_size
        for batch in embedder.calls
    )


def test_the_structural_pass_never_calls_the_embedder(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-structural-only")
        outcome = projections.project_meeting(
            conn,
            app_config,
            seeded.meeting_id,
            structural_only=True,
            embedder_factory=lambda: fake_embedder,
        )
    assert outcome.structural is True
    assert outcome.embedded is False
    assert fake_embedder.calls == []


# --- refusals -------------------------------------------------------------


def test_a_dimension_change_is_refused_before_anything_is_written(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """§3 rule 3 / AD-8: a width mismatch is a named error, never a silent write."""
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-dimension")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    before = documents_of(client, CHUNKS_INDEX, seeded.meeting_id)
    narrower = app_config.model_copy(deep=True)
    narrower.settings.embedder.dimension = 768

    with pool.connection() as conn:
        with pytest.raises(DimensionMismatchError) as excinfo:
            projections.project_meeting(
                conn,
                narrower,
                seeded.meeting_id,
                embedder_factory=lambda: FakeEmbedder(dimension=768),
            )
    assert "768" in str(excinfo.value)
    # Nothing was written under the wrong width, and the index still declares
    # the width it actually holds.
    assert documents_of(client, CHUNKS_INDEX, seeded.meeting_id) == before
    assert (
        stored_dimension(client, CHUNKS_INDEX) == app_config.settings.embedder.dimension
    )


def test_the_store_side_width_check_refuses_too(
    app_config: AppConfig, projection_stores: Any
) -> None:
    """Even with Postgres empty, the index's own recorded width refuses."""
    _driver, client = projection_stores
    with pytest.raises(DimensionMismatchError):
        ensure_search_schema(client, app_config, dimension=384)


def test_a_meili_width_refusal_precedes_neo4j_schema_mutation(
    app_config: AppConfig, projection_stores: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schema setup is a write too, so the preflight ordering is observable."""
    narrowed = app_config.model_copy(deep=True)
    narrowed.settings.embedder.dimension = 384

    def graph_schema_must_not_run(_driver: Any) -> None:
        raise AssertionError("Neo4j schema changed before Meilisearch width refusal")

    monkeypatch.setattr(projections, "ensure_graph_schema", graph_schema_must_not_run)
    with pytest.raises(DimensionMismatchError):
        with projections._open_stores(narrowed, dimension=384):
            pass


# --- the publish gate -----------------------------------------------------


def test_the_publish_gate_refuses_every_state_but_published() -> None:
    """AD-4: nothing outside `published` is ever projected."""
    for state in ("extracted", "approved", None, "draft", ""):
        assert is_publishable(state) is False
        with pytest.raises(PublishGateRefused):
            assert_publishable(state)
    assert is_publishable("published") is True
    assert_publishable("published")


def test_no_public_artifact_helper_can_write_without_the_composed_locks() -> None:
    draft = Artifact(
        id=uuid4(),
        meeting_id=uuid4(),
        corpus="real",
        kind="decision",
        state="approved",
        title="Move the feed to SFTP",
        body="We agreed to move it.",
        moment_ids=(uuid4(),),
    )
    with pytest.raises(PublishGateRefused):
        artifact_document(draft)
    assert not hasattr(projections, "project_artifact")


def test_a_published_artifact_document_carries_its_evidence_edge() -> None:
    moment_id = uuid4()
    published = Artifact(
        id=uuid4(),
        meeting_id=uuid4(),
        corpus="real",
        kind="decision",
        state="published",
        title="Move the feed to SFTP",
        body="We agreed to move it.",
        moment_ids=(moment_id,),
    )
    document = artifact_document(published)
    assert document["momentIds"] == [str(moment_id)]
    assert document["id"] == str(published.id)

    uncited = Artifact(**{**published.__dict__, "moment_ids": ()})
    with pytest.raises(PublishGateRefused):
        artifact_document(uncited)


# --- counts ---------------------------------------------------------------


def test_counts_report_both_indexes(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-counts")
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    totals = search.counts(client)
    assert totals[MOMENTS_INDEX] == len(seeded.moment_ids)
    assert totals[CHUNKS_INDEX] >= 1


# --- the write-confirmation plumbing --------------------------------------


def test_await_task_refuses_a_task_object_it_cannot_identify() -> None:
    """Every write in this module is asynchronous, so "did it land" is only
    knowable through the task id. A silent return on an unrecognized shape —
    after a client upgrade renames the field, say — would turn every write
    into fire-and-forget and let the store-backed suites race themselves
    green against indexes that were never written."""
    from meetingminer.projections.stores import ProjectionError, await_task

    class Unrecognized:
        status = "enqueued"

    with pytest.raises(ProjectionError, match="no task id"):
        await_task(None, Unrecognized())  # type: ignore[arg-type]


def test_await_task_tolerates_only_the_named_error_codes(
    projection_stores: Any,
) -> None:
    from meetingminer.projections.stores import ProjectionError, await_task

    _driver, client = projection_stores
    # Deleting an index that is not there is the state the caller wanted...
    await_task(
        client, client.delete_index("no-such-index"), tolerate=("index_not_found",)
    )
    # ...but only when it is named. Otherwise it is a failure.
    with pytest.raises(ProjectionError, match="index_not_found"):
        await_task(client, client.delete_index("no-such-index"))


def test_a_meeting_scope_that_is_not_a_uuid_is_refused(projection_stores: Any) -> None:
    """The per-meeting delete runs on every re-projection and builds a filter
    expression by interpolation, so its scope is round-tripped through UUID
    rather than trusted to be well-formed."""
    _driver, client = projection_stores
    with pytest.raises(ValueError):
        search.delete_meeting(client, 'x" OR meetingId != "y')


def test_session_config_never_resolves_the_dev_stores(app_config: AppConfig) -> None:
    """Guard: the session store endpoints differ from config.yaml's.

    `projection_stores` runs `drop_all` against whatever `app_config`
    resolves. If the override in conftest's `app_config` fixture is ever lost
    — or `MM_TEST_NEO4J_URI` / `MM_TEST_MEILI_URL` is pointed back at the dev
    endpoints — the suite silently returns to wiping the developer's live
    corpus. This test makes that regression loud. Pure config comparison: it
    needs no store running.
    """
    from meetingminer.config import load_config

    dev = load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env").settings.stores
    test = app_config.settings.stores
    assert test.neo4j.uri != dev.neo4j.uri, (
        "the test session resolves the dev Neo4j — projection tests would"
        f" wipe the live graph at {dev.neo4j.uri}"
    )
    assert test.meilisearch.url != dev.meilisearch.url, (
        "the test session resolves the dev Meilisearch — projection tests"
        f" would wipe the live indexes at {dev.meilisearch.url}"
    )


@pytest.mark.parametrize(
    ("neo4j_uri", "meili_url", "store_name"),
    (
        ("bolt://127.0.0.1:7687", "http://localhost:7701", "Neo4j"),
        ("bolt://localhost:7688", "http://127.0.0.1:7700", "Meilisearch"),
    ),
)
def test_repoint_refuses_dev_store_hostname_aliases_before_any_wipe(
    neo4j_uri: str, meili_url: str, store_name: str
) -> None:
    """Equivalent loopback spellings cannot escape the destructive guard."""
    from meetingminer.config import load_config

    dev = load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env")
    with pytest.raises(RuntimeError, match=rf"refusing.*{store_name}"):
        _repoint_stores_at_test_twins(
            dev, neo4j_uri=neo4j_uri, meili_url=meili_url
        )


def test_configured_projection_stores_are_reachable(stores_up: None) -> None:
    """Make invokes this node with skips promoted to failures."""


# --- published artifacts in the artifacts index (story 4.4) ---------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            MeilisearchError("denied"),
            ProjectionError,
            id="store-refusal",
        ),
        pytest.param(
            MeilisearchCommunicationError("down"),
            StoreUnavailableError,
            id="transport",
        ),
    ],
)
def test_artifact_schema_refuses_before_writing_when_embedders_cannot_be_read(
    app_config: AppConfig, error: Exception, expected: type[Exception]
) -> None:
    class FailingIndex:
        def get_embedders(self) -> Any:
            raise error

    class RecordingClient:
        touched = False

        def index(self, _uid: str) -> FailingIndex:
            return FailingIndex()

        def create_index(self, *_args: Any, **_kwargs: Any) -> Any:
            self.touched = True
            raise AssertionError("schema wrote before embedder inspection succeeded")

    client = RecordingClient()
    with pytest.raises(expected, match="embedder inspection"):
        ensure_artifact_search_schema(client, app_config)  # type: ignore[arg-type]
    assert client.touched is False


def _insert_artifact(
    pool: ConnectionPool,
    moment_id: UUID,
    meeting_id: UUID,
    *,
    kind: str = "adr",
    state: str = "published",
    title: str = "Move the feed to SFTP",
    body: str = "Decided during the demo.",
) -> UUID:
    # A pool adapter over the one canonical INSERT (projection_seed).
    with pool.connection() as conn:
        return seed_artifact(
            conn, moment_id, meeting_id, kind=kind, state=state, title=title, body=body
        )


def _artifact_documents_in_store(client: Any) -> list[dict[str, Any]]:
    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX

    result = client.index(ARTIFACTS_INDEX).get_documents({"limit": 100})
    return [dict(document) for document in result.results]


def test_meeting_projection_lands_published_artifacts_and_only_those(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """The document shape is the harness-frozen `artifact_document` shape:
    id = artifact UUID, source moments in `momentIds` (AD-16)."""
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-published")
    published = _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    _insert_artifact(
        pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        kind="action-item",
        state="extracted",
        title="Draft nobody approved",
    )
    _insert_artifact(
        pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        kind="action-item",
        state="approved",
        title="Approved but unpublished",
    )

    outcome = project(pool, app_config, seeded.meeting_id, fake_embedder)
    assert outcome.artifact_documents == 1

    documents = _artifact_documents_in_store(client)
    assert len(documents) == 1
    document = documents[0]
    assert document["id"] == str(published)
    assert document["meetingId"] == str(seeded.meeting_id)
    assert document["kind"] == "adr"
    assert document["state"] == "published"
    assert document["title"] == "Move the feed to SFTP"
    assert document["text"] == "Decided during the demo."
    assert document["momentIds"] == [str(seeded.moment_ids[0])]
    assert document["corpus"] == "real"


def test_the_artifacts_index_declares_no_embedder(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """Keyword-only by construction: a publish must never depend on the model
    host, so no embedder — user-provided or otherwise — exists on this index,
    and the projected documents carry no `_vectors`."""
    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX

    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-keyword-only")
    _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    assert declared_embedders(client, ARTIFACTS_INDEX) == {}


def test_project_published_artifacts_upserts_without_touching_meeting_documents(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """The approve route's path: add-only into the artifacts index, keyed on
    the artifact UUID, so a retry is an idempotent overwrite."""
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-upsert")
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    before = search.counts(client)

    published = _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    with pool.connection() as conn:
        projections.project_published_artifacts(
            conn, app_config, artifact_ids=[published]
        )
        # A second call with the same id is an overwrite, not a duplicate.
        projections.project_published_artifacts(
            conn, app_config, artifact_ids=[published]
        )

    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX

    after = search.counts(client)
    assert after[ARTIFACTS_INDEX] == 1
    assert after[MOMENTS_INDEX] == before[MOMENTS_INDEX]
    assert after[CHUNKS_INDEX] == before[CHUNKS_INDEX]


def test_artifact_projection_reads_its_source_after_both_locks_are_held(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A remap while the caller waits must be the source it projects."""
    driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-post-lock-read")
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    published = _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)

    @contextmanager
    def remap_while_waiting(_config: AppConfig, *, holder: str) -> Any:
        del holder
        with pool.connection() as other:
            other.execute(
                "UPDATE artifact SET moment_id = %s WHERE id = %s",
                (seeded.moment_ids[1], published),
            )
            other.commit()
        yield

    monkeypatch.setattr(projections, "store_file_lock", remap_while_waiting)
    with pool.connection() as conn:
        assert (
            projections.project_published_artifacts(
                conn, app_config, artifact_ids=[published]
            )
            == 1
        )

    document = dict(client.index("artifacts").get_document(str(published)))
    assert document["momentIds"] == [str(seeded.moment_ids[1])]
    with driver.session() as session:
        cited = session.run(
            "MATCH (a:Artifact {id: $id})-[:CITES]->(m:Moment) RETURN m.id AS id",
            id=str(published),
        ).single(strict=True)["id"]
    assert cited == str(seeded.moment_ids[1])


def test_project_published_artifacts_configures_an_absent_artifacts_index(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store wiped mid-run (e.g. a concurrent `rebuild --all` elsewhere)
    holds no `artifacts` index. Meilisearch auto-creates one on the first
    `add_documents` call with none of its configured filterable attributes —
    so every later `state`-filtered artifacts query would fail against it
    instead of reporting the tolerated `index_missing` case. The entrypoint
    must configure the index before writing into it, same as every other
    projection call, never rely on Meilisearch's bare auto-create."""
    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX
    from meetingminer.projections.stores import await_task

    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-wiped-store")
    # The moment/graph half is projected normally; only the artifacts index
    # is wiped, standing in for a concurrent `rebuild --all` racing this
    # meeting's publish, elsewhere in the shared store.
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    published = _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    await_task(
        client,
        client.delete_index(ARTIFACTS_INDEX),
        tolerate=("index_not_found",),
    )

    # The publish path must not run either all-store initializer: a vector
    # width change is irrelevant to this keyword-only write, and graph schema
    # outside Artifact is not its surface.
    monkeypatch.setattr(
        projections,
        "ensure_search_schema",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("artifact-only projection touched vector schema")
        ),
    )
    monkeypatch.setattr(
        projections,
        "ensure_graph_schema",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("artifact-only projection touched unrelated graph schema")
        ),
    )
    changed_width = app_config.model_copy(deep=True)
    changed_width.settings.embedder.dimension = 768

    with pool.connection() as conn:
        projected = projections.project_published_artifacts(
            conn, changed_width, artifact_ids=[published]
        )
    assert projected == 1

    settings = settings_of(client, ARTIFACTS_INDEX)
    configured = app_config.settings.projections.search.artifacts
    assert settings["searchableAttributes"] == configured.searchable_attributes
    assert set(settings["filterableAttributes"]) == set(
        configured.filterable_attributes
    )
    assert declared_embedders(client, ARTIFACTS_INDEX) == {}
    assert (
        stored_dimension(client, MOMENTS_INDEX)
        == app_config.settings.embedder.dimension
    )
    assert (
        stored_dimension(client, CHUNKS_INDEX) == app_config.settings.embedder.dimension
    )


def test_project_published_artifacts_removes_a_stale_artifact_embedder(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX
    from meetingminer.projections.stores import await_task

    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-stale-embedder")
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    published = _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    await_task(
        client,
        client.index(ARTIFACTS_INDEX).update_embedders(
            {"stale": {"source": "userProvided", "dimensions": 17}}
        ),
    )
    assert declared_embedders(client, ARTIFACTS_INDEX)

    with pool.connection() as conn:
        assert (
            projections.project_published_artifacts(
                conn, app_config, artifact_ids=[published]
            )
            == 1
        )
    assert declared_embedders(client, ARTIFACTS_INDEX) == {}


def test_project_published_artifacts_skips_unpublished_ids_without_writing(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any
) -> None:
    """Defense in depth, observable: an `extracted` id simply does not come
    back from the state-filtered read, so nothing reaches either store."""
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="search-artifact-skip-draft")
    draft = _insert_artifact(
        pool, seeded.moment_ids[0], seeded.meeting_id, state="extracted"
    )

    events: list[tuple[str, dict[str, Any]]] = []
    with pool.connection() as conn:
        projected = projections.project_published_artifacts(
            conn,
            app_config,
            artifact_ids=[draft],
            log=lambda event, **fields: events.append((event, fields)),
        )
    assert projected == 0
    assert _artifact_documents_in_store(client) == []
    assert events == [
        (
            "projection.artifact_skipped",
            {"artifact_id": draft, "reason": "not found in state 'published'"},
        )
    ]
