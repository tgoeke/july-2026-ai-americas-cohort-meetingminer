"""The Neo4j projection: nodes, edges, identity, and per-meeting re-index.

Store-backed. These run against the disposable test-store twins (`neo4j-test`
/ `meilisearch-test` in infra/docker-compose.yml — the session `app_config`
repoints the endpoints) and skip with a named reason when either is down (the
`projection_stores` fixture). Neo4j Community has a single database and AD-4
fixes the label and index names, so there is no per-test namespace — which is
exactly why the suite gets its own store instances: wiping the developer's
live stores and trusting `make rebuild` to refill them left search serving an
empty corpus in practice.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.config import AppConfig
from meetingminer.projections import graph, search
from meetingminer.projections.chunking import chunk_turns
from meetingminer.projections.evidence import read_meeting
from meetingminer.projections.stores import ensure_artifact_graph_schema

from conftest import FakeEmbedder, truncate_evidence
from projection_seed import (
    DEEP_LINK,
    SeededTurn,
    assign_meeting_project,
    assign_meeting_series,
    assign_project_product,
    clear_meeting_project,
    clear_meeting_series,
    seed_meeting,
    seed_product,
    seed_project,
    seed_series,
)
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


def query(driver: Any, cypher: str, **params: Any) -> list[dict[str, Any]]:
    with driver.session() as session:
        return [record.data() for record in session.run(cypher, **params)]


# --- the happy path -------------------------------------------------------


def test_artifact_graph_initializer_creates_only_its_two_schema_objects(
    projection_stores: Any,
) -> None:
    driver, _client = projection_stores
    with driver.session() as session:
        session.run("DROP INDEX artifact_meeting_id IF EXISTS").consume()
        session.run("DROP CONSTRAINT artifact_id_unique IF EXISTS").consume()
        before_constraints = {
            row["name"]
            for row in session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        }
        before_indexes = {
            row["name"] for row in session.run("SHOW INDEXES YIELD name RETURN name")
        }

    ensure_artifact_graph_schema(driver)

    with driver.session() as session:
        after_constraints = {
            row["name"]
            for row in session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        }
        after_indexes = {
            row["name"] for row in session.run("SHOW INDEXES YIELD name RETURN name")
        }
    assert after_constraints - before_constraints == {"artifact_id_unique"}
    assert after_indexes - before_indexes == {
        "artifact_id_unique",
        "artifact_meeting_id",
    }


def test_a_recording_meeting_projects_its_whole_graph(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-happy")

    project(pool, app_config, seeded.meeting_id, fake_embedder)

    labels = {
        row["label"]: row["total"]
        for row in query(
            driver, "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS total"
        )
    }
    assert labels["Meeting"] == 1
    assert labels["Moment"] == len(seeded.moment_ids)
    assert labels["Screen"] == len(seeded.screen_ids)
    assert labels["Screenshot"] == len(seeded.screenshot_ids)
    assert labels["Participant"] == len(seeded.participant_ids)
    assert labels["Chunk"] >= 1

    edges = {
        row["type"]: row["total"]
        for row in query(driver, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS total")
    }
    for name in ("HAS_MOMENT", "OF_SCREEN", "ATTENDED", "SPOKE_IN", "COVERS", "SHOWS"):
        assert edges.get(name, 0) > 0, f"expected at least one {name} edge, got {edges}"
    # The load-bearing join (`retrieval-prior-art.md` §2): what was on screen
    # when this was said.
    assert edges.get("SHOWN_DURING", 0) > 0


def test_every_node_is_keyed_on_its_postgres_uuid_never_an_ordinal(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """AD-6: the Postgres id is carried verbatim into the store."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-identity")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    for label, expected in (
        ("Moment", set(seeded.moment_ids)),
        ("Screenshot", set(seeded.screenshot_ids)),
        ("Screen", set(seeded.screen_ids)),
        ("Participant", set(seeded.participant_ids)),
    ):
        found = {
            UUID(row["id"])
            for row in query(driver, f"MATCH (n:{label}) RETURN n.id AS id")
        }
        assert found == expected, label
    # A chunk has no Postgres row of its own, so it keys on its first
    # transcript segment's UUID — still a Postgres-minted id, never a sequence.
    chunk_ids = {UUID(row["id"]) for row in query(driver, "MATCH (n:Chunk) RETURN n.id AS id")}
    assert chunk_ids <= set(seeded.segment_ids)


def test_a_transcript_only_meeting_has_no_screen_or_screenshot_nodes(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-transcript-only", has_recording=False)
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    assert query(driver, "MATCH (n:Screenshot) RETURN n.id AS id") == []
    assert query(driver, "MATCH (n:Screen) RETURN n.id AS id") == []
    moments = query(
        driver, "MATCH (m:Moment) RETURN m.screenshotId AS shot, m.sourceDeepLink AS link"
    )
    assert moments
    for moment in moments:
        assert moment["shot"] is None
        assert moment["link"] == DEEP_LINK
    # And its transcript is still in the graph as chunks.
    assert query(driver, "MATCH (n:Chunk) RETURN n.id AS id")


# --- re-index isolation ---------------------------------------------------


def test_reprojecting_one_meeting_leaves_every_other_meeting_untouched(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Per-meeting delete-and-reinsert (§3 rule 5) — story 1.12's path."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="graph-reindex-a")
        second = seed_meeting(
            conn,
            source_id="graph-reindex-b",
            screen_identity_keys=("sha256:screen-c",),
        )
    project(pool, app_config, first.meeting_id, fake_embedder)
    project(pool, app_config, second.meeting_id, fake_embedder)

    before = query(
        driver,
        "MATCH (m:Moment {meetingId: $id}) RETURN m.id AS id ORDER BY m.startMs",
        id=str(second.meeting_id),
    )

    project(pool, app_config, first.meeting_id, fake_embedder)

    after = query(
        driver,
        "MATCH (m:Moment {meetingId: $id}) RETURN m.id AS id ORDER BY m.startMs",
        id=str(second.meeting_id),
    )
    assert after == before

    # And the re-projected meeting is not doubled, with its moment ids intact.
    reprojected = {
        UUID(row["id"])
        for row in query(
            driver,
            "MATCH (m:Moment {meetingId: $id}) RETURN m.id AS id",
            id=str(first.meeting_id),
        )
    }
    assert reprojected == set(first.moment_ids)


def test_a_cross_meeting_screen_survives_another_meetings_reindex(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Deleting a Screen would break lineage for every meeting showing it (AD-5)."""
    driver, _client = projection_stores
    shared = ("sha256:shared-screen",)
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="graph-lineage-a", screen_identity_keys=shared)
        second = seed_meeting(conn, source_id="graph-lineage-b", screen_identity_keys=shared)
    assert first.screen_ids == second.screen_ids, "fixture must reuse the screen row"

    project(pool, app_config, first.meeting_id, fake_embedder)
    project(pool, app_config, second.meeting_id, fake_embedder)
    with pool.connection() as conn:
        projections.unproject_meeting(conn, app_config, first.meeting_id)

    screens = query(driver, "MATCH (s:Screen) RETURN s.id AS id")
    assert [UUID(row["id"]) for row in screens] == list(second.screen_ids)
    # The lineage traversal still resolves for the surviving meeting.
    lineage = query(
        driver,
        "MATCH (s:Screen {id: $screen})<-[:OF_SCREEN]-(:Screenshot)<-[:SHOWS]-"
        "(m:Moment)<-[:HAS_MOMENT]-(meeting:Meeting)"
        " RETURN meeting.id AS meetingId ORDER BY meeting.startedAt",
        screen=str(second.screen_ids[0]),
    )
    assert {row["meetingId"] for row in lineage} == {str(second.meeting_id)}


def test_a_participant_traversal_spans_meetings(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """The "I already explained this to Clarence" query: Participant → Meeting → Moment."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="graph-person-a")
        second = seed_meeting(
            conn, source_id="graph-person-b", screen_identity_keys=("sha256:screen-z",)
        )
    project(pool, app_config, first.meeting_id, fake_embedder)
    project(pool, app_config, second.meeting_id, fake_embedder)

    rows = query(
        driver,
        "MATCH (p:Participant {id: $person})-[:ATTENDED]->(meeting:Meeting)"
        "-[:HAS_MOMENT]->(m:Moment)"
        " RETURN meeting.id AS meetingId, m.id AS momentId"
        " ORDER BY meeting.startedAt, m.startMs",
        person=str(first.participant_ids[0]),
    )
    assert {row["meetingId"] for row in rows} == {
        str(first.meeting_id),
        str(second.meeting_id),
    }


def test_unprojecting_one_meeting_preserves_a_shared_participant_for_another(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="graph-person-survival-a")
        second = seed_meeting(
            conn,
            source_id="graph-person-survival-b",
            screen_identity_keys=("sha256:screen-person-survival",),
        )
    project(pool, app_config, first.meeting_id, fake_embedder)
    project(pool, app_config, second.meeting_id, fake_embedder)
    with pool.connection() as conn:
        projections.unproject_meeting(conn, app_config, first.meeting_id)

    rows = query(
        driver,
        "MATCH (p:Participant {id: $person})-[:ATTENDED]->(meeting:Meeting)"
        " RETURN p.id AS participantId, meeting.id AS meetingId",
        person=str(first.participant_ids[0]),
    )
    assert rows == [
        {"participantId": str(first.participant_ids[0]), "meetingId": str(second.meeting_id)}
    ]


def test_an_unresolved_speaker_gets_no_participant_edge(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-unresolved")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    # `Speaker 8` appears as a chunk speaker label but resolves to nobody, so
    # no Participant node is invented and no SPOKE_IN edge points from one.
    labels = {
        speaker
        for row in query(driver, "MATCH (c:Chunk) RETURN c.speakers AS speakers")
        for speaker in row["speakers"]
    }
    assert "Speaker 8" in labels
    people = {row["name"] for row in query(driver, "MATCH (p:Participant) RETURN p.displayName AS name")}
    assert "Speaker 8" not in people


def test_graph_chunks_retain_nonresolved_speaker_turn_metadata(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    turns = (
        SeededTurn(1, 0, "Please repeat that.", "Jordan", speaker_resolution="unresolved"),
        SeededTurn(2, 3_000, "Was that Jordan?", "Jordan", speaker_resolution="ambiguous"),
        SeededTurn(3, 6_000, "System message.", "Speaker 9", speaker_resolution="placeholder"),
    )
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-speaker-resolution", turns=turns)
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    stored = query(
        driver,
        "MATCH (c:Chunk {meetingId: $meeting}) RETURN c.speakerTurns AS speakerTurns",
        meeting=str(seeded.meeting_id),
    )
    assert [entry for row in stored for entry in json.loads(row["speakerTurns"])] == [
        {"speakerLabel": "Jordan", "speakerResolution": "unresolved"},
        {"speakerLabel": "Jordan", "speakerResolution": "ambiguous"},
        {"speakerLabel": "Speaker 9", "speakerResolution": "placeholder"},
    ]
    assert query(
        driver,
        "MATCH (:Participant)-[:SPOKE_IN]->(:Moment {meetingId: $meeting}) RETURN count(*) AS total",
        meeting=str(seeded.meeting_id),
    ) == [{"total": 0}]


def test_a_meeting_with_zero_moments_still_projects_and_is_not_an_error(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-no-moments", with_moments=False)
    outcome = project(pool, app_config, seeded.meeting_id, fake_embedder)

    assert outcome.structural is True
    assert outcome.moment_documents == 0
    assert query(driver, "MATCH (m:Meeting) RETURN m.id AS id") == [
        {"id": str(seeded.meeting_id)}
    ]
    assert query(driver, "MATCH (m:Moment) RETURN m.id AS id") == []


def test_shown_during_only_links_overlapping_spans(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """SHOWN_DURING precision is bounded by the chunk boundary, so it must be exact."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-shown-during")
        evidence = read_meeting(conn, seeded.meeting_id)
    chunking = app_config.settings.projections.chunking
    chunks = chunk_turns(
        seeded.meeting_id,
        evidence.turns,
        chunk_max_chars=chunking.chunk_max_chars,
        chunk_overlap_turns=chunking.chunk_overlap_turns,
    )
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    rows = query(
        driver,
        "MATCH (ss:Screenshot)-[:SHOWN_DURING]->(c:Chunk)"
        " RETURN ss.startMs AS shotStart, ss.endMs AS shotEnd,"
        "        c.startMs AS chunkStart, c.endMs AS chunkEnd",
    )
    assert rows, "expected at least one SHOWN_DURING edge"
    for row in rows:
        assert row["shotStart"] < row["chunkEnd"]
        assert row["chunkStart"] < row["shotEnd"]
    # Nothing was dropped: every genuinely overlapping pair produced an edge.
    expected = sum(
        1
        for shot in evidence.screenshots
        for chunk in chunks
        if shot.start_offset_ms < chunk.end_ms and chunk.start_ms < shot.end_offset_ms
    )
    assert len(rows) == expected


def test_counts_report_labels_and_edge_types(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-counts")
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    summary = graph.counts(driver)
    assert summary["node:Meeting"] == 1
    assert summary["edge:HAS_MOMENT"] == len(seeded.moment_ids)


def test_unprojecting_removes_the_meeting_from_both_stores(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-unproject")
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    with pool.connection() as conn:
        projections.unproject_meeting(conn, app_config, seeded.meeting_id)
        assert (
            conn.execute(
                "SELECT count(*) FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()[0]
            == 0
        )
    assert query(driver, "MATCH (m:Meeting) RETURN m.id AS id") == []
    assert search.counts(client) == {"moments": 0, "chunks": 0, "artifacts": 0}


def test_a_screenshot_that_cannot_be_linked_to_a_screen_is_a_named_failure(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Cypher's `MATCH` drops a row it cannot satisfy, silently.

    An absent `Screen` node would therefore cost the `OF_SCREEN` edge while
    the projection still reported success — and screen lineage (*every
    discussion of this screen over time*) is one of the two headline
    traversals, so the loss would surface as an empty demo rather than an
    error. This drives the case directly by handing the writer evidence whose
    screenshot names a screen that is not in the batch.
    """
    import dataclasses

    from meetingminer.projections.stores import ProjectionError

    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-orphan-screenshot")
        evidence = read_meeting(conn, seeded.meeting_id)
    assert evidence.screenshots, "the fixture must carry screenshots"

    orphaned = dataclasses.replace(evidence, screens=())
    with pytest.raises(ProjectionError) as excinfo:
        graph.project_meeting(driver, orphaned, ())
    message = str(excinfo.value)
    assert "OF_SCREEN" in message
    assert str(seeded.meeting_id) in message
    assert "rebuild --all" in message


def test_a_failure_mid_transaction_rolls_the_whole_meeting_back(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spec's atomicity row: one tx per meeting, all-or-nothing.

    Before the fix, `graph.project_meeting` was a sequence of auto-commit
    statements, so an error partway through (the `EntityNotFound` crash
    class) left a half-written meeting — deleted but not rewritten, or
    written without its moments. Now the delete+write sequence is one
    explicit transaction: a mid-sequence error must leave a first-time
    projection absent entirely, and a re-projection exactly as it was.
    """
    from neo4j.exceptions import ClientError

    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-rollback")
        evidence = read_meeting(conn, seeded.meeting_id)
    chunking = app_config.settings.projections.chunking
    chunks = chunk_turns(
        evidence.meeting_id,
        evidence.turns,
        chunk_max_chars=chunking.chunk_max_chars,
        chunk_overlap_turns=chunking.chunk_overlap_turns,
    )
    assert evidence.moments, "the fixture must carry moments to interrupt on"

    real_write_moments = graph._write_moments

    def torn(tx: Any, ev: Any, ch: Any) -> None:
        raise ClientError("synthetic EntityNotFound stand-in, mid-transaction")

    # A first-time projection that fails mid-transaction persists nothing:
    # by the time `_write_moments` raises, the meeting, participants,
    # screens, screenshots, and chunks were all written *inside the tx*.
    monkeypatch.setattr(graph, "_write_moments", torn)
    with pytest.raises(ClientError):
        graph.project_meeting(driver, evidence, chunks)
    assert graph.counts(driver) == {}

    # A successful projection, then a failed re-projection: the prior graph
    # state survives untouched — including its delete, which rolled back too.
    monkeypatch.setattr(graph, "_write_moments", real_write_moments)
    graph.project_meeting(driver, evidence, chunks)
    before = graph.counts(driver)
    assert before["node:Moment"] == len(seeded.moment_ids)

    monkeypatch.setattr(graph, "_write_moments", torn)
    with pytest.raises(ClientError):
        graph.project_meeting(driver, evidence, chunks)
    assert graph.counts(driver) == before


# --- human-declared structure (story 2.5) ---------------------------------


def test_an_assigned_meeting_projects_structure_nodes_and_edges(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Series/Project/Product nodes exist with the Postgres UUIDs verbatim,
    with the ERD-verb edges `IN_SERIES`, `SCOPES`, `OWNS`."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-structure")
        series_id = seed_series(conn, name="Weekly Sync")
        product_id = seed_product(conn, name="Data Hub")
        project_id = seed_project(conn, name="Feed Migration", product_id=product_id)
        assign_meeting_series(conn, meeting_id=seeded.meeting_id, series_id=series_id)
        assign_meeting_project(conn, meeting_id=seeded.meeting_id, project_id=project_id)
        conn.commit()

    project(pool, app_config, seeded.meeting_id, fake_embedder)

    rows = query(
        driver,
        "MATCH (m:Meeting {id: $meetingId})-[:IN_SERIES]->(s:Series)"
        " RETURN s.id AS id, s.name AS name",
        meetingId=str(seeded.meeting_id),
    )
    assert [(row["id"], row["name"]) for row in rows] == [(str(series_id), "Weekly Sync")]

    rows = query(
        driver,
        "MATCH (pd:Product)-[:OWNS]->(p:Project)-[:SCOPES]->(m:Meeting {id: $meetingId})"
        " RETURN p.id AS projectId, p.name AS projectName,"
        " pd.id AS productId, pd.name AS productName",
        meetingId=str(seeded.meeting_id),
    )
    assert [tuple(row.values()) for row in rows] == [
        (str(project_id), "Feed Migration", str(product_id), "Data Hub")
    ]


def test_an_unassigned_meeting_projects_no_structure(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-no-structure")
        conn.commit()

    project(pool, app_config, seeded.meeting_id, fake_embedder)

    counts = graph.counts(driver)
    for label in ("Series", "Project", "Product"):
        assert f"node:{label}" not in counts, counts
    for edge in ("IN_SERIES", "SCOPES", "OWNS"):
        assert f"edge:{edge}" not in counts, counts


def test_reprojection_after_clearing_drops_the_meetings_structure_edges(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """A cleared assignment loses its edge at the next re-projection (the
    DETACH DELETE on Meeting takes it); the orphaned entity nodes linger
    until `rebuild --all` — the documented disposable-projection remedy."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-structure-clear")
        series_id = seed_series(conn, name="Cleared Sync")
        project_id = seed_project(conn, name="Cleared Feed")
        assign_meeting_series(conn, meeting_id=seeded.meeting_id, series_id=series_id)
        assign_meeting_project(conn, meeting_id=seeded.meeting_id, project_id=project_id)
        conn.commit()
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    with pool.connection() as conn:
        clear_meeting_series(conn, meeting_id=seeded.meeting_id)
        clear_meeting_project(conn, meeting_id=seeded.meeting_id)
        conn.commit()
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    counts = graph.counts(driver)
    assert counts.get("edge:IN_SERIES", 0) == 0, counts
    assert counts.get("edge:SCOPES", 0) == 0, counts
    # Cross-meeting nodes are never deleted per-meeting.
    assert counts["node:Series"] == 1
    assert counts["node:Project"] == 1


def test_two_meetings_sharing_a_series_yield_one_series_node(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="graph-shared-series-1")
        second = seed_meeting(conn, source_id="graph-shared-series-2")
        series_id = seed_series(conn, name="Shared Sync")
        assign_meeting_series(conn, meeting_id=first.meeting_id, series_id=series_id)
        assign_meeting_series(conn, meeting_id=second.meeting_id, series_id=series_id)
        conn.commit()

    project(pool, app_config, first.meeting_id, fake_embedder)
    project(pool, app_config, second.meeting_id, fake_embedder)

    counts = graph.counts(driver)
    assert counts["node:Series"] == 1
    assert counts["edge:IN_SERIES"] == 2


def test_reassigning_a_projects_product_leaves_exactly_one_owns_edge(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """OWNS connects two cross-meeting nodes, so the per-meeting DETACH
    DELETE never removes a stale one — `_write_structure` reconciles the
    project's OWNS edges to its current product instead, so a PATCHed
    reassignment shows one owner after the next re-projection, not two."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-owns-reassign")
        product_a = seed_product(conn, name="Product A")
        product_b = seed_product(conn, name="Product B")
        project_id = seed_project(conn, name="Reassigned Feed", product_id=product_a)
        assign_meeting_project(conn, meeting_id=seeded.meeting_id, project_id=project_id)
        conn.commit()
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    with pool.connection() as conn:
        assign_project_product(conn, project_id=project_id, product_id=product_b)
        conn.commit()
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    owners = query(
        driver,
        "MATCH (pd:Product)-[:OWNS]->(p:Project {id: $projectId})"
        " RETURN pd.id AS id",
        projectId=str(project_id),
    )
    assert [row["id"] for row in owners] == [str(product_b)]

    # And clearing the product drops the last OWNS edge on re-projection.
    with pool.connection() as conn:
        assign_project_product(conn, project_id=project_id, product_id=None)
        conn.commit()
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    counts = graph.counts(driver)
    assert counts.get("edge:OWNS", 0) == 0, counts


# --- published artifacts (story 4.4) --------------------------------------


def insert_artifact(
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


def test_a_published_artifact_projects_a_cited_node_and_a_draft_does_not(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Epics AC1/AC2: the node exists for `published` alone, keyed on the
    Postgres artifact UUID, with a CITES edge to its source moment."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-artifact")
    published = insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    draft = insert_artifact(
        pool, seeded.moment_ids[0], seeded.meeting_id, kind="action-item", state="extracted"
    )

    project(pool, app_config, seeded.meeting_id, fake_embedder)

    rows = query(
        driver,
        "MATCH (a:Artifact)-[:CITES]->(m:Moment)"
        " RETURN a.id AS id, a.meetingId AS meetingId, a.kind AS kind,"
        " a.state AS state, a.title AS title, a.corpus AS corpus, m.id AS moment",
    )
    assert [row["id"] for row in rows] == [str(published)]
    assert rows[0]["meetingId"] == str(seeded.meeting_id)
    assert rows[0]["kind"] == "adr"
    assert rows[0]["state"] == "published"
    assert rows[0]["title"] == "Move the feed to SFTP"
    assert rows[0]["moment"] == str(seeded.moment_ids[0])
    # The draft reached neither node nor edge, in any state or label.
    assert query(driver, "MATCH (n {id: $id}) RETURN n", id=str(draft)) == []


def test_meeting_reprojection_recreates_artifact_nodes_and_their_citations(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Epics AC4: the per-meeting delete severs CITES with the Moment nodes,
    so the same pass restores artifacts from Postgres — citability survives
    every settle point and augment re-projection."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-artifact-reproject")
    published = insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)

    project(pool, app_config, seeded.meeting_id, fake_embedder)
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    rows = query(
        driver,
        "MATCH (a:Artifact {id: $id})-[c:CITES]->(m:Moment)"
        " RETURN count(a) AS nodes, count(c) AS edges",
        id=str(published),
    )
    assert rows == [{"nodes": 1, "edges": 1}]


def test_unprojecting_a_meeting_removes_its_artifact_nodes(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-artifact-unproject")
    published = insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    assert query(driver, "MATCH (a:Artifact) RETURN a.id AS id") == [
        {"id": str(published)}
    ]

    with pool.connection() as conn:
        projections.unproject_meeting(conn, app_config, seeded.meeting_id)

    assert query(driver, "MATCH (a:Artifact) RETURN a") == []


def test_project_published_artifacts_upserts_into_an_already_projected_meeting(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """The approve route's path: the meeting's graph stands; the entrypoint
    MERGEs the node and its citation without rewriting the meeting."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-artifact-upsert")
    project(pool, app_config, seeded.meeting_id, fake_embedder)
    before = graph.counts(driver)

    published = insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    with pool.connection() as conn:
        projected = projections.project_published_artifacts(
            conn, app_config, artifact_ids=[published]
        )
    assert projected == 1

    after = graph.counts(driver)
    assert after["node:Artifact"] == 1
    assert after["edge:CITES"] == 1
    # Nothing else moved: the meeting was not re-projected.
    assert {k: v for k, v in after.items() if not k.endswith(":Artifact") and k != "edge:CITES"} == before


def test_projecting_an_artifact_whose_moment_is_not_in_the_graph_is_named(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any
) -> None:
    """A Cypher MATCH that finds no Moment drops its row silently; an artifact
    with no evidence edge would be an uncited claim (AD-6), so it is a named
    refusal with the rebuild recovery — and the node write rolls back whole."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="graph-artifact-unprojected-meeting")
    published = insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)

    with pool.connection() as conn:
        with pytest.raises(projections.ProjectionError) as excinfo:
            projections.project_published_artifacts(
                conn, app_config, artifact_ids=[published]
            )
    assert "rebuild --meeting" in str(excinfo.value)
    assert query(driver, "MATCH (a:Artifact) RETURN a") == []
