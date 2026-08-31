"""`rebuild` (FR24): regeneration from Postgres + config alone, and the trigger.

Store-backed, and the most destructive file in the suite: a full ``rebuild``
drops both stores by design, which is what makes "no orphan nodes or documents
survive" checkable. The test process centrally repoints both the shared
``app_config`` and the rebuild CLI's independent config load at the disposable
test-store twins, so no path in this file resolves the developer's stores.

The other half of this file is the ingest-complete trigger, and the single
check that catches a mis-placed one: a job whose `extract` stage **fails after
its evidence settled** never reaches `done`, and must still be fully projected
— evidence projects at evidence-complete, not at job-done (AD-4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import psycopg
from neo4j.exceptions import ClientError
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from meetingminer import db, logs, projections
from meetingminer.pipeline import runner
from meetingminer.config import AppConfig
from meetingminer.domain.jobs import evidence_complete
from meetingminer.projections import graph, search
import meetingminer.projections.cli as rebuild_cli
from meetingminer.projections.cli import main as rebuild_main
from meetingminer.projections.stores import (
    MOMENTS_INDEX,
    ProjectionLockedError,
    projection_lock,
)

from conftest import BrokenEmbedder, DownEmbedder, FakeEmbedder, truncate_evidence
from projection_seed import STARTED_AT, seed_meeting
from projection_seed import insert_artifact as seed_artifact
from projection_seed import insert_extraction_document as seed_document

pytestmark = pytest.mark.slow(reason="rebuild writes both test twins under the projection lock: 39 tests, 81.9s at e5510c7")


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


def _rebuild(
    pool: ConnectionPool, config: AppConfig, embedder: Any, **kwargs: Any
) -> projections.RebuildReport:
    with pool.connection() as conn:
        return projections.rebuild(
            conn, config, embedder_factory=lambda: embedder, **kwargs
        )


def _sample_bodies(client: Any) -> dict[str, dict[str, Any]]:
    """A stable sample of moment documents, keyed on their moment id."""
    result = client.index(MOMENTS_INDEX).get_documents({"limit": 1000})
    bodies: dict[str, dict[str, Any]] = {}
    for document in result.results:
        body = dict(document)
        bodies[body["id"]] = {
            key: value for key, value in body.items() if key != "_vectors"
        }
    return bodies


# --- regeneration ---------------------------------------------------------


def test_rebuild_regenerates_both_stores_equivalently_after_a_wipe(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """The AC: counts and a sample of document bodies match the originals."""
    driver, client = projection_stores
    with pool.connection() as conn:
        seed_meeting(conn, source_id="rebuild-a")
        seed_meeting(conn, source_id="rebuild-b", has_recording=False)
        seed_meeting(
            conn, source_id="rebuild-c", screen_identity_keys=("sha256:screen-c",)
        )

    first = _rebuild(pool, app_config, fake_embedder)
    assert first.ok
    assert first.projected == 3
    assert first.dropped is True

    before_graph = graph.counts(driver)
    before_search = search.counts(client)
    before_bodies = _sample_bodies(client)
    assert before_search[MOMENTS_INDEX] > 0

    second = _rebuild(pool, app_config, fake_embedder)
    assert second.ok

    assert graph.counts(driver) == before_graph
    assert search.counts(client) == before_search
    assert _sample_bodies(client) == before_bodies


def test_rebuild_drops_stale_content_so_no_orphan_survives(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    driver, client = projection_stores
    with pool.connection() as conn:
        kept = seed_meeting(conn, source_id="rebuild-kept")
    _rebuild(pool, app_config, fake_embedder)

    # A meeting that is projected and then deleted from Postgres: a rebuild
    # must not leave its nodes and documents behind.
    with pool.connection() as conn:
        stale = seed_meeting(
            conn, source_id="rebuild-stale", screen_identity_keys=("sha256:screen-s",)
        )
    _rebuild(pool, app_config, fake_embedder)
    with pool.connection() as conn:
        conn.execute("DELETE FROM meeting WHERE id = %s", (stale.meeting_id,))
        conn.execute("DELETE FROM job WHERE id = %s", (stale.job_id,))
        conn.commit()

    _rebuild(pool, app_config, fake_embedder)

    with driver.session() as session:
        survivors = [
            record["id"]
            for record in session.run("MATCH (m:Meeting) RETURN m.id AS id")
        ]
    assert survivors == [str(kept.meeting_id)]
    documents = client.index(MOMENTS_INDEX).get_documents({"limit": 1000})
    assert {dict(document)["meetingId"] for document in documents.results} == {
        str(kept.meeting_id)
    }


def test_rebuild_skips_a_meeting_whose_evidence_is_not_complete(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """Driven through a *scoped* run, because that is the only way to reach it.

    An `--all` run builds its targets from `projectable_meeting_ids`, which
    already filters on `evidence_complete` — so asserting an empty report there
    tests the target query and never the in-loop guard. A `--meeting <uuid>`
    run takes the id it is given, which is exactly the case the guard exists
    for: an operator naming a meeting that is not finished yet.
    """
    with pool.connection() as conn:
        incomplete = seed_meeting(
            conn,
            source_id="rebuild-incomplete",
            stage_overrides={"moments": "queued"},
        )
        assert not evidence_complete(
            {
                name: status
                for name, status in conn.execute(
                    "SELECT name, status FROM job_stage WHERE job_id = %s",
                    (incomplete.job_id,),
                ).fetchall()
            }
        )

    scoped = _rebuild(
        pool, app_config, fake_embedder, meeting_ids=[incomplete.meeting_id]
    )
    assert [outcome.skipped_reason for outcome in scoped.outcomes] == [
        "evidence incomplete"
    ]
    assert scoped.outcomes[0].structural is False
    assert scoped.ok, "an unfinished meeting is skipped, not a failure"
    with pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM meeting_projection WHERE meeting_id = %s",
                (incomplete.meeting_id,),
            ).fetchone()[0]
            == 0
        )

    # And the corpus-wide run never offers it in the first place.
    assert _rebuild(pool, app_config, fake_embedder).outcomes == []


def test_a_scoped_rebuild_touches_only_the_named_meeting(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="rebuild-scope-a")
        second = seed_meeting(
            conn, source_id="rebuild-scope-b", screen_identity_keys=("sha256:screen-q",)
        )
    _rebuild(pool, app_config, fake_embedder)

    def element_id(meeting_id: UUID) -> str:
        with driver.session() as session:
            return session.run(
                "MATCH (m:Meeting {id: $id}) RETURN elementId(m) AS eid",
                id=str(meeting_id),
            ).single()["eid"]

    untouched = element_id(second.meeting_id)
    report = _rebuild(pool, app_config, fake_embedder, meeting_ids=[first.meeting_id])
    assert report.dropped is False, "a scoped run must never drop the stores"
    assert element_id(second.meeting_id) == untouched


def test_embed_only_rebuild_fills_vectors_for_unembedded_meetings(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rebuild-embed-only")
    down = _rebuild(pool, app_config, DownEmbedder())
    assert down.embedded == 0
    with pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT embedded_at FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()[0]
            is None
        )

    filled = _rebuild(pool, app_config, fake_embedder, embed_only=True)
    assert filled.ok
    assert filled.embedded == 1
    assert filled.dropped is False
    with pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT embedded_at FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()[0]
            is not None
        )


def test_a_dry_run_reports_and_writes_nothing(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    driver, client = projection_stores
    with pool.connection() as conn:
        seed_meeting(conn, source_id="rebuild-dry")
    report = _rebuild(pool, app_config, fake_embedder, dry_run=True)
    assert len(report.outcomes) == 1
    assert report.outcomes[0].skipped_reason == "dry run"
    assert graph.counts(driver) == {}
    assert search.counts(client) == {"moments": 0, "chunks": 0, "artifacts": 0}


def test_a_failure_on_one_meeting_does_not_stop_the_pass(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="rebuild-fail-a")
        second = seed_meeting(
            conn, source_id="rebuild-fail-b", screen_identity_keys=("sha256:screen-f",)
        )
    doomed = min(first.meeting_id, second.meeting_id, key=lambda m: str(m))
    real_read = projections.read_meeting

    def flaky(conn: Any, meeting_id: UUID) -> Any:
        if meeting_id == doomed:
            raise LookupError(f"synthetic failure for {meeting_id}")
        return real_read(conn, meeting_id)

    monkeypatch.setattr(projections, "read_meeting", flaky)
    report = _rebuild(pool, app_config, fake_embedder)
    assert not report.ok
    assert [meeting_id for meeting_id, _ in report.failures] == [doomed]
    assert report.projected == 1


def test_a_neo4j_error_on_one_meeting_is_a_recorded_failure_not_a_run_abort(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raw driver error (the `EntityNotFound` crash class) must not end the run.

    Before this fix, rebuild's per-meeting except tuple missed
    ``neo4j.exceptions.Neo4jError``, so one torn meeting aborted `rebuild
    --all` and stranded the whole corpus mid-rebuild.
    """
    driver, client = projection_stores
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="rebuild-neo4j-a")
        second = seed_meeting(
            conn, source_id="rebuild-neo4j-b", screen_identity_keys=("sha256:screen-n",)
        )
    doomed = min(first.meeting_id, second.meeting_id, key=lambda m: str(m))
    real_project = graph.project_meeting

    def torn(driver_: Any, evidence: Any, chunks: Any, artifacts: Any = ()) -> None:
        if evidence.meeting_id == doomed:
            raise ClientError("synthetic EntityNotFound stand-in")
        real_project(driver_, evidence, chunks)

    monkeypatch.setattr(graph, "project_meeting", torn)
    report = _rebuild(pool, app_config, fake_embedder)
    assert not report.ok
    assert [meeting_id for meeting_id, _ in report.failures] == [doomed]
    assert "ClientError" in report.failures[0][1]
    # The other meeting still projected in full — the loop continued.
    assert report.projected == 1
    assert graph.counts(driver)["node:Meeting"] == 1


# --- the advisory lock ----------------------------------------------------


def test_a_rebuild_racing_a_held_lock_is_a_named_refusal(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """§3 rule 1: contention is a named error, not silent divergence."""
    with pool.connection() as holder:
        with projection_lock(holder, holder="a test standing in for the worker"):
            with pool.connection() as conn:
                with pytest.raises(ProjectionLockedError) as excinfo:
                    projections.rebuild(
                        conn, app_config, embedder_factory=lambda: fake_embedder
                    )
    assert "rebuild refused" in str(excinfo.value)
    assert "pid" in str(excinfo.value)


# --- the CLI --------------------------------------------------------------


def test_cli_config_resolves_the_same_test_store_twins(app_config: AppConfig) -> None:
    """The CLI's independent config load must be centrally test-isolated."""
    loaded = rebuild_cli._load_cli_config()
    assert loaded.settings.stores.neo4j.uri == app_config.settings.stores.neo4j.uri
    assert (
        loaded.settings.stores.meilisearch.url
        == app_config.settings.stores.meilisearch.url
    )


def test_the_cli_reports_per_meeting_outcomes_and_a_summary(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    test_database: str,
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="cli-run")

    # The CLI opens its own connection from config, so point it at the test
    # database rather than the developer's real one.
    real_conninfo = db.conninfo
    monkeypatch.setattr(
        db,
        "conninfo",
        lambda config, database=None: real_conninfo(config, database=test_database),
    )
    monkeypatch.setattr(projections, "build_embedder", lambda *_a, **_kw: fake_embedder)

    assert rebuild_main(["--all"]) == 0
    out = capsys.readouterr().out
    assert str(seeded.meeting_id) in out
    assert "structural+embedded" in out
    assert "rebuild: projected 1 meeting(s)" in out


def test_the_cli_refuses_a_bad_meeting_id_without_touching_anything(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert rebuild_main(["--meeting", "not-a-uuid"]) == 2
    assert "not a UUID" in capsys.readouterr().err


def test_cli_from_server_uses_root_config_and_keeps_mm_config_path_override(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server_dir = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(server_dir)
    monkeypatch.setattr(
        rebuild_cli.psycopg,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            psycopg.OperationalError("test database")
        ),
    )
    monkeypatch.setenv("MM_CONFIG_PATH", "definitely-not-the-repository-config.yaml")

    assert rebuild_main(["--all", "--dry-run"]) == 1
    assert "definitely-not-the-repository-config.yaml" in capsys.readouterr().err

    monkeypatch.delenv("MM_CONFIG_PATH")
    # Loading gets past config resolution from `server/`; the mocked connection
    # failure proves the CLI did not look for `server/config.yaml`.
    assert rebuild_main(["--all", "--dry-run"]) == 1
    assert "config file not found" not in capsys.readouterr().err


def test_the_cli_exits_non_zero_when_a_meeting_fails(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    test_database: str,
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="cli-fail")
    real_conninfo = db.conninfo
    monkeypatch.setattr(
        db,
        "conninfo",
        lambda config, database=None: real_conninfo(config, database=test_database),
    )
    monkeypatch.setattr(projections, "build_embedder", lambda *_a, **_kw: fake_embedder)

    def boom(conn: Any, meeting_id: UUID) -> Any:
        raise LookupError("synthetic")

    monkeypatch.setattr(projections, "read_meeting", boom)
    assert rebuild_main(["--all"]) == 1
    assert str(seeded.meeting_id) in capsys.readouterr().err


# --- the ingest-complete trigger ------------------------------------------


def test_a_job_that_fails_at_extract_is_still_fully_projected(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    projection_trigger: None,
    monkeypatch: pytest.MonkeyPatch,
    make_drop: Any,
    content_root: Path,
    fake_llm: Any,
) -> None:
    """The single check that catches a mis-placed trigger.

    A job whose model answers garbage fails at `extract` and never reaches
    `done`, so a projection call placed only after the runner's stage loop
    would silently never run for it. This drives a real transcript-only drop
    through `run_job` with an unusable completer and asserts the stores are
    populated at the failure — the evidence projected when it settled (AD-4),
    before extraction ever ran.
    """
    from meetingminer.pipeline import runner

    driver, client = projection_stores
    monkeypatch.setattr(projections, "build_embedder", lambda *_a, **_kw: fake_embedder)
    # One moment, one retry: two unusable replies fail the stage.
    fake_llm(replies=("not json", "still not json"))

    from conftest import TEAMS_TRANSCRIPT, valid_metadata

    drop = make_drop(metadata=valid_metadata("trigger-source"), files=())
    (drop / "transcript.txt").write_text(TEAMS_TRANSCRIPT, encoding="utf-8")

    with pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
            " VALUES ('trigger-source', %s, 'real', 'queued') RETURNING id",
            (drop.name,),
        ).fetchone()[0]
        from meetingminer.domain.jobs import STAGE_NAMES

        for name in STAGE_NAMES:
            conn.execute(
                "INSERT INTO job_stage (job_id, name) VALUES (%s, %s)", (job_id, name)
            )
        conn.commit()

        claimed = runner.claim_job(conn)
        assert claimed is not None
        runner.run_job(conn, claimed, app_config, content_root)

        job_status, stage_rows = (
            conn.execute(
                "SELECT status FROM job WHERE id = %s", (claimed.id,)
            ).fetchone()[0],
            dict(
                conn.execute(
                    "SELECT name, status FROM job_stage WHERE job_id = %s",
                    (claimed.id,),
                ).fetchall()
            ),
        )
        meeting_id = conn.execute(
            "SELECT id FROM meeting WHERE job_id = %s", (claimed.id,)
        ).fetchone()[0]
        projection_row = conn.execute(
            "SELECT structural_at, embedded_at FROM meeting_projection WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()

    # The premise: the job did NOT reach `done` — `extract` failed on the
    # unusable completer — while its evidence had already settled.
    assert job_status == "failed"
    assert stage_rows["extract"] == "failed"
    assert stage_rows["moments"] == "done"

    # And the projection happened anyway.
    assert projection_row is not None
    assert projection_row[0] is not None
    with driver.session() as session:
        assert (
            session.run(
                "MATCH (m:Meeting {id: $id}) RETURN count(*) AS total",
                id=str(meeting_id),
            ).single()["total"]
            == 1
        )
    assert search.counts(client)[MOMENTS_INDEX] > 0


def test_the_trigger_is_idempotent_across_a_reclaim(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    projection_trigger: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling it at every settle point must be harmless."""
    from meetingminer import logs
    from meetingminer.pipeline import runner

    monkeypatch.setattr(projections, "build_embedder", lambda *_a, **_kw: fake_embedder)
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trigger-idempotent")
        statuses = dict(
            conn.execute(
                "SELECT name, status FROM job_stage WHERE job_id = %s", (seeded.job_id,)
            ).fetchall()
        )
        log = logs.bind(job_id=seeded.job_id, stage="moments")
        runner._maybe_project(conn, app_config, seeded.meeting_id, statuses, log)
        first = conn.execute(
            "SELECT structural_at, embedded_at FROM meeting_projection WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()
        for _ in range(3):
            runner._maybe_project(conn, app_config, seeded.meeting_id, statuses, log)
        again = conn.execute(
            "SELECT structural_at, embedded_at FROM meeting_projection WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()
    assert first == again, "a second call must be a no-op, not a re-projection"


def test_the_trigger_does_not_fire_before_the_evidence_is_complete(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    projection_trigger: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from meetingminer import logs
    from meetingminer.pipeline import runner

    monkeypatch.setattr(projections, "build_embedder", lambda *_a, **_kw: fake_embedder)
    with pool.connection() as conn:
        seeded = seed_meeting(
            conn, source_id="trigger-early", stage_overrides={"moments": "running"}
        )
        statuses = dict(
            conn.execute(
                "SELECT name, status FROM job_stage WHERE job_id = %s", (seeded.job_id,)
            ).fetchall()
        )
        runner._maybe_project(
            conn, app_config, seeded.meeting_id, statuses, logs.bind(stage="align")
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()[0]
            == 0
        )


def test_a_store_outage_warns_and_never_fails_the_job(
    pool: ConnectionPool,
    app_config: AppConfig,
    fake_embedder: FakeEmbedder,
    projection_trigger: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Projection failure must not fail an ingest whose evidence is correct."""
    from meetingminer import logs
    from meetingminer.pipeline import runner
    from meetingminer.projections.stores import StoreUnavailableError

    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trigger-store-down")
        statuses = dict(
            conn.execute(
                "SELECT name, status FROM job_stage WHERE job_id = %s", (seeded.job_id,)
            ).fetchall()
        )

        def unreachable(*_args: Any, **_kwargs: Any) -> Any:
            raise StoreUnavailableError("Neo4j unreachable at bolt://localhost:7687")

        monkeypatch.setattr(projections, "project_meeting", unreachable)
        # No exception escapes.
        runner._maybe_project(
            conn, app_config, seeded.meeting_id, statuses, logs.bind(stage="moments")
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()[0]
            == 0
        )
    captured = capsys.readouterr()
    assert "projection.failed" in captured.err
    assert "rebuild --meeting" in captured.err


# --- migration ------------------------------------------------------------


def test_migration_0007_is_present_and_applied(test_pool: ConnectionPool) -> None:
    names = [path.name for path in db.migration_files()]
    assert "0007_projection_state.sql" in names
    with test_pool.connection() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'meeting_projection'"
            ).fetchall()
        }
    assert {
        "meeting_id",
        "structural_at",
        "embedded_at",
        "embedder_model",
        "embedder_dimension",
        "chunk_max_chars",
        "chunk_overlap_turns",
    } <= columns


# --- projection staleness: what decides full / embed-only / nothing --------


def test_an_outage_then_a_healthy_host_is_resumed_by_the_worker_itself(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    projection_trigger: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The automatic half of the Ollama-outage story.

    The spec's matrix says the embedding is "retried on the next projection or
    `rebuild --embed-only`". The CLI half is covered elsewhere; this is the
    *worker* half, and it is the only reason `projection_action` distinguishes
    `embed` from `full`. Without it, a meeting projected during an outage would
    either never gain vectors or would pay for a whole structural rewrite to
    get them.
    """
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="action-resume")
        outcome = projections.project_meeting(
            conn, app_config, seeded.meeting_id, embedder_factory=DownEmbedder
        )
        assert outcome.structural and not outcome.embedded

        # The recorded state now says "structural, not embedded".
        assert (
            projections.projection_action(conn, app_config, seeded.meeting_id)
            == projections.ACTION_EMBED
        )
        structural_at = conn.execute(
            "SELECT structural_at FROM meeting_projection WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()[0]

    def element_id() -> str:
        with driver.session() as session:
            return session.run(
                "MATCH (m:Meeting {id: $id}) RETURN elementId(m) AS eid",
                id=str(seeded.meeting_id),
            ).single()["eid"]

    before_element = element_id()

    # The host comes back, and the worker re-enters through its own trigger.
    monkeypatch.setattr(projections, "build_embedder", lambda *_a, **_kw: fake_embedder)
    with pool.connection() as conn:
        statuses = dict(
            conn.execute(
                "SELECT name, status FROM job_stage WHERE job_id = %s", (seeded.job_id,)
            ).fetchall()
        )
        runner._maybe_project(
            conn, app_config, seeded.meeting_id, statuses, logs.bind(stage="moments")
        )
        row = conn.execute(
            "SELECT structural_at, embedded_at FROM meeting_projection"
            " WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()
        # Nothing left to do now.
        assert (
            projections.projection_action(conn, app_config, seeded.meeting_id)
            == projections.ACTION_NONE
        )

    assert row[1] is not None, "the retry must fill the vectors"
    assert row[0] == structural_at, "and must not redo the structural pass"
    assert element_id() == before_element, "the graph node was never rewritten"


def test_a_chunking_retune_makes_every_projection_stale(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """Chunk size and overlap are the open tuning lever (§6-§7), so retuning
    them invalidates every chunk boundary — the columns migration 0007 records
    them in exist for exactly this comparison."""
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="action-retune")
        projections.project_meeting(
            conn, app_config, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )
        assert (
            projections.projection_action(conn, app_config, seeded.meeting_id)
            == projections.ACTION_NONE
        )

        for field, value in (("chunk_max_chars", 400), ("chunk_overlap_turns", 0)):
            retuned = app_config.model_copy(deep=True)
            setattr(retuned.settings.projections.chunking, field, value)
            assert (
                projections.projection_action(conn, retuned, seeded.meeting_id)
                == projections.ACTION_FULL
            ), field


def test_an_embedder_swap_makes_every_projection_stale(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """AD-8: the embedder's model and dimension are projection state, and
    changing either forces a full rebuild rather than a config toggle."""
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="action-swap")
        projections.project_meeting(
            conn, app_config, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )
        swapped = app_config.model_copy(deep=True)
        swapped.settings.embedder.model = "snowflake-arctic-embed2:latest"
        assert (
            projections.projection_action(conn, swapped, seeded.meeting_id)
            == projections.ACTION_FULL
        )
        # And re-projecting under the swap records the new model.
        projections.project_meeting(
            conn, swapped, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )
        assert (
            conn.execute(
                "SELECT embedder_model FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()[0]
            == "snowflake-arctic-embed2:latest"
        )


def test_an_unprojected_meeting_needs_a_full_projection(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="action-fresh")
        assert (
            projections.projection_action(conn, app_config, seeded.meeting_id)
            == projections.ACTION_FULL
        )


# --- a fatal embedder error is a failure, not a warning -------------------


def test_a_broken_embedder_fails_the_run_and_says_the_structural_half_landed(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any
) -> None:
    """The branch `DownEmbedder` cannot reach.

    A host that is *down* is survivable and warns; a host that answers with a
    model it does not have is a configuration error no retry fixes, and must
    fail. Both would be indistinguishable if the two `except` blocks were
    merged — and the corpus really did sit in this state, so the message has
    to say the meeting is still BM25-searchable rather than implying it is
    unsearchable.
    """
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="broken-embedder")

    report = _rebuild(pool, app_config, BrokenEmbedder())
    assert not report.ok
    assert [meeting_id for meeting_id, _ in report.failures] == [seeded.meeting_id]
    message = report.failures[0][1]
    assert "projected structurally" in message
    assert "BM25" in message

    # The structural half really did land and really is searchable.
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT structural_at, embedded_at FROM meeting_projection"
            " WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()
    assert row[0] is not None and row[1] is None
    hits = client.index(MOMENTS_INDEX).search(
        "revenue slide", {"filter": f'meetingId = "{seeded.meeting_id}"'}
    )
    assert hits["hits"]


def test_the_cli_exits_non_zero_on_a_broken_embedder(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    test_database: str,
) -> None:
    with pool.connection() as conn:
        seed_meeting(conn, source_id="cli-broken-embedder")
    real_conninfo = db.conninfo
    monkeypatch.setattr(
        db,
        "conninfo",
        lambda config, database=None: real_conninfo(config, database=test_database),
    )
    monkeypatch.setattr(
        projections, "build_embedder", lambda *_a, **_kw: BrokenEmbedder()
    )
    assert rebuild_main(["--all"]) == 1
    assert "projected structurally" in capsys.readouterr().err


# --- the reclaim path ------------------------------------------------------


def test_a_reclaimed_job_projects_on_the_second_pass(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    projection_trigger: None,
    monkeypatch: pytest.MonkeyPatch,
    make_drop: Any,
    content_root: Path,
) -> None:
    """The `stage.resumed` call site, which nothing else can reach.

    `requeue_orphaned_jobs` puts a crashed worker's job back to `queued`
    *without* resetting its stage checkpoints, so the next claim settles
    nothing: every stage takes the already-settled branch. If the projection
    call were only at the `done` and `skipped` branches, a meeting whose store
    was down during its one real pass would never be projected by the worker
    again.
    """
    driver, client = projection_stores
    monkeypatch.setattr(projections, "build_embedder", lambda *_a, **_kw: fake_embedder)

    from conftest import TEAMS_TRANSCRIPT, valid_metadata
    from meetingminer.domain.jobs import STAGE_NAMES
    from meetingminer.projections.stores import StoreUnavailableError

    drop = make_drop(metadata=valid_metadata("reclaim-source"), files=())
    (drop / "transcript.txt").write_text(TEAMS_TRANSCRIPT, encoding="utf-8")

    # First pass: the stores are "down", so the projection fails while the job
    # still finishes every stage (extract on the autouse zero-artifact fake).
    store_down = {"active": True}
    real_project_meeting = projections.project_meeting

    def flaky(*args: Any, **kwargs: Any) -> Any:
        if store_down["active"]:
            raise StoreUnavailableError("Neo4j unreachable at bolt://localhost:7687")
        return real_project_meeting(*args, **kwargs)

    monkeypatch.setattr(projections, "project_meeting", flaky)

    with pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
            " VALUES ('reclaim-source', %s, 'real', 'queued') RETURNING id",
            (drop.name,),
        ).fetchone()[0]
        for name in STAGE_NAMES:
            conn.execute(
                "INSERT INTO job_stage (job_id, name) VALUES (%s, %s)", (job_id, name)
            )
        conn.commit()

        first = runner.claim_job(conn)
        assert first is not None
        runner.run_job(conn, first, app_config, content_root)
        meeting_id = conn.execute(
            "SELECT id FROM meeting WHERE job_id = %s", (job_id,)
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM meeting_projection WHERE meeting_id = %s",
                (meeting_id,),
            ).fetchone()[0]
            == 0
        ), "the first pass must have failed to project"
        # The evidence itself is complete and the job settled cleanly.
        assert (
            conn.execute("SELECT status FROM job WHERE id = %s", (job_id,)).fetchone()[
                0
            ]
            == "done"
        )

        # The crash window: the worker died after its last stage settled but
        # before the job-status update landed — in the database that is a
        # `running` job whose every checkpoint is already settled.
        conn.execute("UPDATE job SET status = 'running' WHERE id = %s", (job_id,))
        conn.commit()

        # The worker restarts: orphan recovery re-queues the job and, crucially,
        # leaves every stage checkpoint settled.
        assert runner.requeue_orphaned_jobs(conn) == [job_id]
        settled = dict(
            conn.execute(
                "SELECT name, status FROM job_stage WHERE job_id = %s", (job_id,)
            ).fetchall()
        )
        assert settled["moments"] == "done" and settled["extract"] == "done"

        # Second pass, stores healthy. Nothing settles — the resumed branch is
        # the only call site that can fire.
        store_down["active"] = False
        second = runner.claim_job(conn)
        assert second is not None and second.id == job_id
        runner.run_job(conn, second, app_config, content_root)

        row = conn.execute(
            "SELECT structural_at, embedded_at FROM meeting_projection"
            " WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()

    assert row is not None and row[0] is not None
    with driver.session() as session:
        assert (
            session.run(
                "MATCH (m:Meeting {id: $id}) RETURN count(*) AS total",
                id=str(meeting_id),
            ).single()["total"]
            == 1
        )
    assert search.counts(client)[MOMENTS_INDEX] > 0


# --- scope and resumability, at the CLI boundary ---------------------------


def test_the_cli_refuses_to_pick_a_scope_for_you(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bare `rebuild` used to be a silent corpus-wide run that dropped both
    stores. `--all` is the flag that makes that deliberate."""
    assert rebuild_main([]) == 2
    message = capsys.readouterr().err
    assert "--all" in message and "--meeting" in message
    assert "drops both stores" in message


def test_embed_only_leaves_already_embedded_meetings_alone(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """`--embed-only` is a *resume*, not a re-embed.

    Without the `embedded_at IS NULL` predicate this re-embeds the whole
    corpus on every run — hours of model host time spent rewriting vectors
    that are already there — which is the opposite of what the nullable column
    exists for. `meeting_projection_embedded_at_idx` is indexed for this query.
    """
    with pool.connection() as conn:
        embedded = seed_meeting(conn, source_id="embed-only-done")
        pending = seed_meeting(
            conn,
            source_id="embed-only-pending",
            screen_identity_keys=("sha256:screen-eo",),
        )
        projections.project_meeting(
            conn,
            app_config,
            embedded.meeting_id,
            embedder_factory=lambda: fake_embedder,
        )
        projections.project_meeting(
            conn, app_config, pending.meeting_id, embedder_factory=DownEmbedder
        )
        embedded_at = conn.execute(
            "SELECT embedded_at FROM meeting_projection WHERE meeting_id = %s",
            (embedded.meeting_id,),
        ).fetchone()[0]

    fake_embedder.calls.clear()
    report = _rebuild(pool, app_config, fake_embedder, embed_only=True)

    assert [outcome.meeting_id for outcome in report.outcomes] == [pending.meeting_id]
    assert fake_embedder.calls, "the unembedded meeting must still be embedded"
    with pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT embedded_at FROM meeting_projection WHERE meeting_id = %s",
                (embedded.meeting_id,),
            ).fetchone()[0]
            == embedded_at
        ), "an already-embedded meeting must not be touched"


def test_a_scoped_embed_only_refuses_a_meeting_that_was_never_projected(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """The unscoped path filters targets to meetings that have a row; a scoped
    one takes the id it is given, so the guard has to live at the write."""
    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="embed-only-orphan")

    report = _rebuild(
        pool,
        app_config,
        fake_embedder,
        meeting_ids=[seeded.meeting_id],
        embed_only=True,
    )
    assert not report.ok
    assert "no meeting_projection row" in report.failures[0][1]
    with pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()[0]
            == 0
        ), "and nothing may be recorded as embedded"


def test_scoped_embed_only_refuses_stale_chunks_before_either_store_is_written(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="embed-only-stale-chunks")
    with pool.connection() as conn:
        projections.project_meeting(
            conn, app_config, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )
        before_state = conn.execute(
            "SELECT chunk_max_chars, embedded_at FROM meeting_projection WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()

    before_graph = graph.counts(driver)
    before_documents = _sample_bodies(client)
    retuned = app_config.model_copy(deep=True)
    retuned.settings.projections.chunking.chunk_max_chars = 400

    def stores_must_not_open(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "a stale embed-only pass must refuse before opening stores"
        )

    # Both public entry points must refuse before the schema/write boundary.
    # The pre-seeded stores stay available for the assertions below, but any
    # attempt by the code under test to open them is an immediate failure.
    monkeypatch.setattr(projections, "_open_stores", stores_must_not_open)
    with pool.connection() as conn:
        with pytest.raises(
            projections.ProjectionError, match="requires a full projection"
        ):
            projections.project_meeting_embeddings(
                conn, retuned, seeded.meeting_id, embedder_factory=lambda: fake_embedder
            )
    report = _rebuild(
        pool,
        retuned,
        fake_embedder,
        meeting_ids=[seeded.meeting_id],
        embed_only=True,
    )

    assert not report.ok
    assert "requires a full projection" in report.failures[0][1]
    assert graph.counts(driver) == before_graph
    assert _sample_bodies(client) == before_documents
    with pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT chunk_max_chars, embedded_at FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()
            == before_state
        )


def test_embed_only_all_refuses_an_already_embedded_stale_projection(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--all --embed-only` must not hide drift behind its NULL-row filter."""
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="embed-only-all-stale")
        projections.project_meeting(
            conn, app_config, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )

    retuned = app_config.model_copy(deep=True)
    retuned.settings.projections.chunking.chunk_max_chars = 400
    monkeypatch.setattr(
        projections,
        "_open_stores",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a stale all/embed-only pass must not open stores")
        ),
    )

    report = _rebuild(pool, retuned, fake_embedder, embed_only=True)
    assert not report.ok
    assert report.outcomes == []
    assert "requires a full projection" in report.failures[0][1]


def test_scoped_embed_only_continues_current_targets_after_a_stale_refusal(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """A bad target must not suppress another named target's resume pass."""
    with pool.connection() as conn:
        stale = seed_meeting(conn, source_id="embed-only-mixed-stale")
        current = seed_meeting(
            conn,
            source_id="embed-only-mixed-current",
            screen_identity_keys=("sha256:embed-only-mixed-current",),
        )
        projections.project_meeting(
            conn, app_config, stale.meeting_id, embedder_factory=lambda: fake_embedder
        )

    retuned = app_config.model_copy(deep=True)
    retuned.settings.projections.chunking.chunk_max_chars = 400
    with pool.connection() as conn:
        projections.project_meeting(
            conn, retuned, current.meeting_id, embedder_factory=lambda: fake_embedder
        )

    report = _rebuild(
        pool,
        retuned,
        fake_embedder,
        meeting_ids=[stale.meeting_id, current.meeting_id],
        embed_only=True,
    )
    assert not report.ok
    assert [meeting_id for meeting_id, _error in report.failures] == [stale.meeting_id]
    assert [(outcome.meeting_id, outcome.embedded) for outcome in report.outcomes] == [
        (current.meeting_id, True)
    ]


def test_unprojecting_survives_an_embedder_swap(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """Retiring a meeting writes no vector, so the width check that exists to
    force a rebuild must not be what stops it being removed."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="unproject-after-swap")
        projections.project_meeting(
            conn, app_config, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )

    narrower = app_config.model_copy(deep=True)
    narrower.settings.embedder.dimension = 768
    with pool.connection() as conn:
        projections.unproject_meeting(conn, narrower, seeded.meeting_id)
        assert (
            conn.execute(
                "SELECT count(*) FROM meeting_projection WHERE meeting_id = %s",
                (seeded.meeting_id,),
            ).fetchone()[0]
            == 0
        )
    with driver.session() as session:
        assert (
            session.run(
                "MATCH (m:Meeting {id: $id}) RETURN count(*) AS total",
                id=str(seeded.meeting_id),
            ).single()["total"]
            == 0
        )


# --- story 1.12: augmentation makes an already-projected meeting re-project ---


def _moment_documents(client: Any, meeting_id: UUID) -> dict[str, dict[str, Any]]:
    """One meeting's moment documents, keyed on moment id."""
    result = client.index(MOMENTS_INDEX).get_documents({"limit": 1000})
    return {
        dict(document)["id"]: {
            key: value for key, value in dict(document).items() if key != "_vectors"
        }
        for document in result.results
        if dict(document)["meetingId"] == str(meeting_id)
    }


def _graph_moment_ids(driver: Any, meeting_id: UUID) -> set[str]:
    with driver.session() as session:
        return {
            record["id"]
            for record in session.run(
                "MATCH (:Meeting {id: $id})-[:HAS_MOMENT]->(mo:Moment) RETURN mo.id AS id",
                id=str(meeting_id),
            )
        }


def _augment_in_postgres(conn: psycopg.Connection, seeded: Any) -> tuple[UUID, UUID]:
    """The Postgres side-effects of an augmentation pass, without the pipeline.

    What the video stages and `moments` leave behind on a meeting that had no
    recording: the recording on the Meeting row, a screenshot, the pre-existing
    transcript-anchored moment now naming it with its deep link retired, and a
    new `screen:`-keyed moment for the capture no transcript boundary covers.
    The stage itself is tested in `test_worker_moments.py` and the whole chain
    in `test_augmentation.py`; this file is about what the *projection* then
    does with the result.
    """
    conn.execute(
        "UPDATE meeting SET has_recording = true WHERE id = %s", (seeded.meeting_id,)
    )
    screen_id = conn.execute(
        "INSERT INTO screen (identity_key, signature, view_type)"
        " VALUES (%s, 'late signature', 'slide')"
        " ON CONFLICT (identity_key) DO UPDATE SET signature = EXCLUDED.signature"
        " RETURNING id",
        (f"sha256:late-{seeded.meeting_id}",),
    ).fetchone()[0]
    screenshot_id = conn.execute(
        "INSERT INTO screenshot (meeting_id, screen_id, ordinal, start_offset_ms,"
        " end_offset_ms, frame_count, path, view_type, capture_cues)"
        " VALUES (%s, %s, 1, 0, 2000, 2, %s, 'slide', ARRAY['region-change'])"
        " RETURNING id",
        (
            seeded.meeting_id,
            screen_id,
            f"meetings/{seeded.meeting_id}/screenshots/0001.jpg",
        ),
    ).fetchone()[0]
    # The moment that existed before the recording did: same id, same identity
    # key, now naming the screenshot with its transitional deep link retired.
    conn.execute(
        "UPDATE moment SET screenshot_id = %s, source_deep_link = NULL WHERE id = %s",
        (screenshot_id, seeded.moment_ids[0]),
    )
    added = conn.execute(
        "INSERT INTO moment (meeting_id, identity_key, derived_from, start_ms, end_ms,"
        " started_at, started_at_precision, screenshot_id, segment_count, provenance)"
        " VALUES (%s, 'screen:0', 'screen', 0, 2000, %s, 'second', %s, 0, %s)"
        " RETURNING id",
        (
            seeded.meeting_id,
            STARTED_AT,
            screenshot_id,
            Jsonb({"boundary": "screenshot", "derived_from": "screen"}),
        ),
    ).fetchone()[0]
    conn.commit()
    return added, screenshot_id


def test_augmenting_a_projected_meeting_re_projects_only_that_meeting(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """The story's last AC, across the seam the invalidation exists to open.

    `projection_action` answers ACTION_NONE while a current
    `meeting_projection` row exists, so an augmented meeting would keep its
    pre-recording documents forever. `invalidate_meeting_projection` drops that
    row — and only that row — so the next action is ACTION_FULL and
    `project_meeting`'s per-meeting delete-and-reinsert replaces the meeting's
    documents in one scoped pass.
    """
    driver, client = projection_stores
    with pool.connection() as conn:
        augmented = seed_meeting(conn, source_id="augment-target", has_recording=False)
        untouched = seed_meeting(conn, source_id="augment-bystander")
        projections.project_meeting(
            conn,
            app_config,
            augmented.meeting_id,
            embedder_factory=lambda: fake_embedder,
        )
        projections.project_meeting(
            conn,
            app_config,
            untouched.meeting_id,
            embedder_factory=lambda: fake_embedder,
        )

    before = _moment_documents(client, augmented.meeting_id)
    assert set(before) == {str(m) for m in augmented.moment_ids}
    assert before[str(augmented.moment_ids[0])]["sourceDeepLink"], "UX-DR11 link"
    bystander_before = _moment_documents(client, untouched.meeting_id)
    with driver.session() as session:
        bystander_element_id = session.run(
            "MATCH (m:Meeting {id: $id}) RETURN elementId(m) AS eid",
            id=str(untouched.meeting_id),
        ).single()["eid"]

    with pool.connection() as conn:
        added, screenshot_id = _augment_in_postgres(conn, augmented)
        # Without the invalidation the projection declines to do anything.
        assert (
            projections.projection_action(conn, app_config, augmented.meeting_id)
            == projections.ACTION_NONE
        )

        assert (
            projections.invalidate_meeting_projection(conn, augmented.meeting_id)
            is True
        )
        assert (
            projections.projection_action(conn, app_config, augmented.meeting_id)
            == projections.ACTION_FULL
        )
        # Only that meeting's state row went: the bystander is still current.
        assert (
            projections.projection_action(conn, app_config, untouched.meeting_id)
            == projections.ACTION_NONE
        )

        projections.project_meeting(
            conn,
            app_config,
            augmented.meeting_id,
            embedder_factory=lambda: fake_embedder,
        )

    after = _moment_documents(client, augmented.meeting_id)
    # Delete-and-reinsert, not append: the added moment is there, every
    # pre-existing id is still there exactly once, and nothing doubled.
    assert set(after) == {str(m) for m in augmented.moment_ids} | {str(added)}
    assert _graph_moment_ids(driver, augmented.meeting_id) == set(after)
    head = after[str(augmented.moment_ids[0])]
    assert head["screenshotId"] == str(screenshot_id)
    assert not head.get("sourceDeepLink"), "the transitional deep link is retired"

    # And the other meeting's rows were never opened.
    assert _moment_documents(client, untouched.meeting_id) == bystander_before
    with driver.session() as session:
        assert (
            session.run(
                "MATCH (m:Meeting {id: $id}) RETURN elementId(m) AS eid",
                id=str(untouched.meeting_id),
            ).single()["eid"]
            == bystander_element_id
        )


def test_invalidating_an_unprojected_meeting_reports_that_it_had_no_state(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    """Idempotent, and honest about it: no row to drop is `False`, not an error.

    The worker calls this on every claim whose drop newly carries a recording,
    including one that was never projected because a store was down.
    """
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="invalidate-unprojected")
        assert (
            projections.invalidate_meeting_projection(conn, seeded.meeting_id) is False
        )
        assert (
            projections.projection_action(conn, app_config, seeded.meeting_id)
            == projections.ACTION_FULL
        )


# --- story 2.5: human-declared structure through the real rebuild path ------


def test_rebuild_projects_series_project_product_structure(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """AC3 names `rebuild` explicitly: assignments made before a rebuild must
    appear as Series/Project/Product nodes and IN_SERIES/SCOPES/OWNS edges
    after it, with the Postgres-minted UUIDs verbatim."""
    from projection_seed import (
        assign_meeting_project,
        assign_meeting_series,
        seed_product,
        seed_project,
        seed_series,
    )

    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rebuild-structure")
        series_id = seed_series(conn, name="Rebuild Sync")
        product_id = seed_product(conn, name="Rebuild Hub")
        project_id = seed_project(conn, name="Rebuild Feed", product_id=product_id)
        assign_meeting_series(conn, meeting_id=seeded.meeting_id, series_id=series_id)
        assign_meeting_project(conn, meeting_id=seeded.meeting_id, project_id=project_id)
        conn.commit()

    report = _rebuild(pool, app_config, fake_embedder)
    assert report.ok
    assert report.projected == 1

    with driver.session() as session:
        row = session.run(
            "MATCH (pd:Product)-[:OWNS]->(p:Project)-[:SCOPES]->"
            "(m:Meeting {id: $meetingId})-[:IN_SERIES]->(s:Series)"
            " RETURN s.id AS seriesId, p.id AS projectId, pd.id AS productId",
            meetingId=str(seeded.meeting_id),
        ).single()
    assert row is not None, "rebuild must project the full structure path"
    assert row["seriesId"] == str(series_id)
    assert row["projectId"] == str(project_id)
    assert row["productId"] == str(product_id)

    counts = graph.counts(driver)
    assert counts["node:Series"] == 1
    assert counts["node:Project"] == 1
    assert counts["node:Product"] == 1
    assert counts["edge:IN_SERIES"] == 1
    assert counts["edge:SCOPES"] == 1
    assert counts["edge:OWNS"] == 1


# --- published artifacts across rebuild (story 4.4) -----------------------


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


def _artifact_ids_in_search(client: Any) -> set[str]:
    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX

    result = client.index(ARTIFACTS_INDEX).get_documents({"limit": 1000})
    return {dict(document)["id"] for document in result.results}


def test_rebuild_repopulates_published_artifacts_and_excludes_drafts(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """Epics AC4: `rebuild` restores citable knowledge and only that — the
    state filter, not provenance or anything else, decides membership."""
    driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rebuild-artifacts")
    published = _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    _insert_artifact(
        pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        kind="action-item",
        state="extracted",
        title="Draft nobody approved",
    )

    report = _rebuild(pool, app_config, fake_embedder)
    assert report.ok
    assert report.outcomes[0].artifact_documents == 1

    assert _artifact_ids_in_search(client) == {str(published)}
    with driver.session() as session:
        rows = [
            record.data()
            for record in session.run(
                "MATCH (a:Artifact)-[:CITES]->(m:Moment) RETURN a.id AS id, m.id AS moment"
            )
        ]
    assert rows == [{"id": str(published), "moment": str(seeded.moment_ids[0])}]


def test_rebuild_all_wipes_a_stale_artifacts_index(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """A document for an artifact Postgres does not hold as published must not
    survive the wipe — `drop_all` covers the artifacts index too."""
    from uuid import uuid4

    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX
    from meetingminer.projections.stores import await_task

    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rebuild-artifacts-stale")
    published = _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    stale_id = str(uuid4())
    await_task(
        client,
        client.index(ARTIFACTS_INDEX).add_documents(
            [
                {
                    "id": stale_id,
                    "meetingId": str(uuid4()),
                    "state": "published",
                    "title": "orphan",
                    "text": "orphan",
                    "momentIds": [],
                }
            ]
        ),
    )

    report = _rebuild(pool, app_config, fake_embedder)
    assert report.ok and report.dropped

    assert _artifact_ids_in_search(client) == {str(published)}


def test_embed_only_rebuild_skips_artifacts_but_preserves_their_documents(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embed-only repair never addresses the artifacts index at all."""
    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX

    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rebuild-artifacts-embed-only")
    published = _insert_artifact(
        pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        body="An artifact body never embedded.",
    )

    structural = _rebuild(pool, app_config, fake_embedder, structural_only=True)
    assert structural.ok
    assert _artifact_ids_in_search(client) == {str(published)}

    class RecordingClient:
        def __init__(self, wrapped: Any) -> None:
            self.wrapped = wrapped
            self.index_calls: list[str] = []

        def index(self, uid: str) -> Any:
            self.index_calls.append(uid)
            return self.wrapped.index(uid)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.wrapped, name)

    recording = RecordingClient(client)
    monkeypatch.setattr(projections, "meili_client", lambda _config: recording)

    embedded = _rebuild(pool, app_config, fake_embedder, embed_only=True)
    assert embedded.ok
    assert embedded.embedded == 1

    assert _artifact_ids_in_search(client) == {str(published)}
    document = dict(client.index(ARTIFACTS_INDEX).get_document(str(published)))
    assert "_vectors" not in document
    assert ARTIFACTS_INDEX not in recording.index_calls
    # No embedder call carried the artifact's body: the artifacts index is
    # keyword-only end to end, not merely unconfigured.
    embedded_texts = [text for call in fake_embedder.calls for text in call]
    assert all("never embedded" not in text for text in embedded_texts)


# --- extraction documents (story 12.4) ------------------------------------


def test_rebuild_reindexes_extraction_documents_from_the_postgres_row_alone(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """The story's own requirement, and the reason 12.1 stored a column.

    A full rebuild drops both stores and regenerates them from Postgres plus
    `config.yaml` alone. Documents come back — from `extraction_source`, with
    no evidence file opened and no drop consulted. Text living only in a drop
    would have fallen out of search on exactly this pass, which is why AD-3's
    anti-copy rule does not reach a document (AD-3 as amended 2026-08-31).
    """
    from meetingminer.projections.documents import DOCUMENTS_INDEX, REVIEW_STATE

    _driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rebuild-documents")
        summary = seed_document(conn, seeded.meeting_id, kind="arch-summary")
        actions = seed_document(conn, seeded.meeting_id, kind="action-items")
        conn.commit()

    report = _rebuild(pool, app_config, fake_embedder)
    assert report.ok and report.dropped
    [outcome] = report.outcomes
    assert outcome.extraction_documents == 2

    indexed = client.index(DOCUMENTS_INDEX).get_documents({"limit": 100})
    bodies = {dict(document)["id"]: dict(document) for document in indexed.results}
    assert set(bodies) == {str(summary), str(actions)}
    # The label survives the round trip: an unlabelled document after a rebuild
    # would be an AD-18 violation reintroduced by the recovery path itself.
    for body in bodies.values():
        assert body["reviewState"] == REVIEW_STATE
        assert body["reviewLabel"]


def test_the_projection_module_opens_no_file_to_index_a_document(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-4's filesystem property, unchanged by this story.

    `projections/` opens no evidence file today and story 12.4 must not make it
    one. Asserted by making `open` itself fail for the duration of the pass: if
    any part of building or writing a document record reached the filesystem,
    the rebuild would fail rather than pass.
    """
    import meetingminer.projections.documents as documents_module
    import meetingminer.projections.evidence as evidence_module
    import meetingminer.projections.search as search_module

    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="rebuild-documents-no-file")
        seed_document(conn, seeded.meeting_id)
        conn.commit()

    # Scoped to the three modules that touch a document, rather than globally:
    # Meilisearch's HTTP client legitimately opens sockets and certificate
    # bundles, and a blanket ban would fail for a reason that is not this one.
    for module in (documents_module, evidence_module, search_module):
        monkeypatch.setattr(
            module,
            "open",
            _forbidden_open,
            raising=False,
        )

    report = _rebuild(pool, app_config, fake_embedder)
    assert report.ok, report.failures
    [outcome] = report.outcomes
    assert outcome.extraction_documents == 1


def _forbidden_open(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError(
        "the projection module opened a file to index an extraction document —"
        " it reads Postgres values only (AD-4), and text living only in a drop"
        " would fall out of search on every rebuild"
    )
