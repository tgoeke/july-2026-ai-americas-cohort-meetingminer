"""The publish-gate probe layer, exercised entirely over fakes — no store.

``evals/checks/gate_probe.py`` is the one module in the evals tree allowed a
write-shaped store call, and only in the erasure direction, on ids the run
minted. These tests pin its pure parts (eligibility, the run-id marker, the
ownership filter, the de-collision spread) and its seams (mint, approve via
``httpx.MockTransport``, cleanup) with fakes, so ``make evals-test`` proves
the shape with no store, no api and no run folder.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from evals.checks import gate_probe
from evals.harness.checks import GateProbe
from evals.harness.corpus import MomentRow

MEETING = "11111111-1111-7111-8111-111111111111"
MOMENT_A = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
MOMENT_B = "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb"
MOMENT_C = "cccccccc-cccc-7ccc-8ccc-cccccccccccc"
PROBE_ID = "dddddddd-dddd-7ddd-8ddd-dddddddddddd"
FOREIGN_ID = "eeeeeeee-eeee-7eee-8eee-eeeeeeeeeeee"


def moment(moment_id: str, key: str = "transcript:1000") -> MomentRow:
    return MomentRow(id=moment_id, identity_key=key)


@dataclass(frozen=True)
class FakeArtifact:
    id: str
    moment_id: str
    state: str


# --------------------------------------------------------------------------
# The marker: every minted row is recognizably this run's
# --------------------------------------------------------------------------


def test_the_probe_title_is_prefixed_with_the_run_id() -> None:
    title = gate_probe.probe_title("2026-08-30-left")
    assert title == "eval-gate-probe-2026-08-30-left"
    assert title.startswith(gate_probe.PROBE_TITLE_PREFIX)


def test_the_probe_body_names_the_run_and_the_manifest() -> None:
    body = gate_probe.probe_body("2026-08-30-left", "demo-001")
    assert "2026-08-30-left" in body
    assert "demo-001" in body
    assert "erased" in body, "a leftover row must explain itself to whoever finds it"


# --------------------------------------------------------------------------
# Eligibility and the de-collision spread
# --------------------------------------------------------------------------


def test_moments_holding_extracted_rows_are_ineligible() -> None:
    """Approving the probe's moment publishes every extracted row under it,
    so a moment carrying subject `extracted` state may never be chosen."""
    moments = (moment(MOMENT_A), moment(MOMENT_B))
    artifacts = (FakeArtifact(PROBE_ID, MOMENT_A, "extracted"),)
    assert gate_probe.eligible_moments(moments, artifacts) == (moment(MOMENT_B),)


def test_approved_and_published_rows_do_not_block_a_moment() -> None:
    """The approve route only advances `extracted` rows, so settled subject
    states on a moment cannot be mutated through it."""
    moments = (moment(MOMENT_A),)
    artifacts = (
        FakeArtifact("x", MOMENT_A, "approved"),
        FakeArtifact("y", MOMENT_A, "published"),
    )
    assert gate_probe.eligible_moments(moments, artifacts) == moments


def test_the_choice_order_is_deterministic_and_spread_by_run_id() -> None:
    moments = tuple(
        moment(f"{i}0000000-0000-7000-8000-00000000000{i}") for i in range(1, 6)
    )
    left = gate_probe.choose_order("2026-08-30-left", moments)
    right = gate_probe.choose_order("2026-08-30-right", moments)
    assert left == gate_probe.choose_order("2026-08-30-left", moments)
    assert sorted(m.id for m in left) == sorted(m.id for m in moments)
    assert left != right, "two labels must not pile onto the same moment"


# --------------------------------------------------------------------------
# The ownership filter over the approve response
# --------------------------------------------------------------------------


def test_only_the_minted_id_counts_and_foreign_rows_are_set_aside() -> None:
    returned = (
        {"id": PROBE_ID, "state": "published"},
        {"id": FOREIGN_ID, "state": "published"},
    )
    owned, foreign = gate_probe.split_owned(returned, PROBE_ID)
    assert owned == (PROBE_ID,)
    assert foreign == (FOREIGN_ID,)


def test_a_minted_row_the_approval_left_unpublished_is_not_owned() -> None:
    returned = ({"id": PROBE_ID, "state": "extracted"},)
    owned, foreign = gate_probe.split_owned(returned, PROBE_ID)
    assert owned == ()
    assert foreign == ()


# --------------------------------------------------------------------------
# Cleanup over fakes: verified per target, loud per leftover
# --------------------------------------------------------------------------


def absent_error() -> Exception:
    """A Meilisearch not-found the way the real client raises it — carrying
    its `code`. `_search_absent` is strict now (an unclassifiable error is
    "absence unproven"), so the fakes must speak the real error shape."""
    error = gate_probe.MeilisearchApiError.__new__(gate_probe.MeilisearchApiError)
    error.code = "document_not_found"
    error.status_code = 404
    return error


class FakeTask:
    task_uid = 42


class FakeIndex:
    def __init__(self, client: FakeSearchClient) -> None:
        self.client = client

    def delete_document(self, document_id: str) -> FakeTask:
        self.client.removed.append(document_id)
        if self.client.delete_error is not None:
            raise self.client.delete_error
        return FakeTask()

    def get_document(self, document_id: str) -> Any:
        if self.client.still_present:
            return {"id": document_id, "momentIds": []}
        raise absent_error()


class FakeSearchClient:
    def __init__(
        self, *, still_present: bool = False, delete_error: Exception | None = None
    ) -> None:
        self.removed: list[str] = []
        self.waited: list[int] = []
        self.still_present = still_present
        self.delete_error = delete_error

    def index(self, name: str) -> FakeIndex:
        assert name == gate_probe.ARTIFACTS_INDEX
        return FakeIndex(self)

    def wait_for_task(self, uid: int) -> None:
        self.waited.append(uid)


class FakeGraphSession:
    def __init__(self, driver: FakeGraphDriver) -> None:
        self.driver = driver

    def __enter__(self) -> FakeGraphSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def run(self, query: str, **params: Any) -> Any:
        if "DETACH DELETE" in query:
            self.driver.erased.append(params["id"])
            return SimpleNamespace(consume=lambda: None)
        # the read-only verification queries
        if self.driver.still_present:
            return [{"id": params["id"], "moments": []}]
        return []


class FakeGraphDriver:
    def __init__(self, *, still_present: bool = False) -> None:
        self.erased: list[str] = []
        self.still_present = still_present

    def session(self, **kwargs: Any) -> FakeGraphSession:
        return FakeGraphSession(self)


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None


class FakeConnection:
    """A writable-connection fake: it remembers the probe row it holds."""

    def __init__(self, *, row_state: str | None = "published") -> None:
        self.row_state = row_state
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeCursor:
        self.statements.append((sql, params))
        if sql.startswith("DELETE FROM artifact"):
            self.row_state = None
            return FakeCursor([])
        if "SELECT state" in sql:
            return FakeCursor(
                [(self.row_state,)] if self.row_state is not None else []
            )
        if sql.startswith("INSERT INTO artifact"):
            return FakeCursor([(PROBE_ID,)])
        if "pg_advisory_" in sql:
            return FakeCursor([(True,)])
        raise AssertionError(f"unexpected statement: {sql}")

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def test_a_clean_cleanup_verifies_every_target(tmp_path: Path) -> None:
    export = tmp_path / gate_probe.PROBE_KIND / f"{PROBE_ID}.md"
    export.parent.mkdir()
    export.write_text("# probe")
    search = FakeSearchClient()
    graph = FakeGraphDriver()
    connection = FakeConnection()

    report = gate_probe.cleanup_probe(
        PROBE_ID,
        search=search,
        graph=graph,
        publish_root=tmp_path,
        connection=connection,
        config=probe_config(tmp_path),
    )

    assert report.verified, report.problems
    assert search.removed == [PROBE_ID]
    assert search.waited == [FakeTask.task_uid]
    assert graph.erased == [PROBE_ID]
    assert not export.exists()
    assert connection.row_state is None


def test_cleanup_holds_the_projection_writer_lock_for_every_erasure(
    tmp_path: Path,
) -> None:
    """F1: verified absence is stable only inside the writers' lock domain."""
    held = False

    @contextmanager
    def cleanup_lock(config: object, connection: object, holder: str) -> Any:
        nonlocal held
        assert holder == f"eval gate-probe cleanup {PROBE_ID}"
        held = True
        try:
            yield
        finally:
            held = False

    class LockedIndex(FakeIndex):
        def delete_document(self, document_id: str) -> FakeTask:
            assert held
            return super().delete_document(document_id)

        def get_document(self, document_id: str) -> Any:
            assert held
            return super().get_document(document_id)

    class LockedSearch(FakeSearchClient):
        def index(self, name: str) -> LockedIndex:
            assert held
            return LockedIndex(self)

    class LockedGraph(FakeGraphDriver):
        def session(self, **kwargs: Any) -> FakeGraphSession:
            assert held
            return super().session(**kwargs)

    class LockedConnection(FakeConnection):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeCursor:
            assert held
            return super().execute(sql, params)

    report = gate_probe.cleanup_probe(
        PROBE_ID,
        search=LockedSearch(),
        graph=LockedGraph(),
        publish_root=tmp_path,
        connection=LockedConnection(),
        config=probe_config(tmp_path),
        cleanup_lock=cleanup_lock,
    )

    assert report.verified, report.problems
    assert not held


def test_an_absent_export_file_is_a_verified_removal(tmp_path: Path) -> None:
    """A probe whose approval never exported (the approve failed) has no file
    to remove — absence is the verified end state, not an error."""
    report = gate_probe.cleanup_probe(
        PROBE_ID,
        search=FakeSearchClient(),
        graph=FakeGraphDriver(),
        publish_root=tmp_path,
        connection=FakeConnection(),
        config=probe_config(tmp_path),
    )
    assert report.export_file_removed, report.problems


def test_a_surviving_search_document_is_a_named_leftover(tmp_path: Path) -> None:
    report = gate_probe.cleanup_probe(
        PROBE_ID,
        search=FakeSearchClient(still_present=True),
        graph=FakeGraphDriver(),
        publish_root=tmp_path,
        connection=FakeConnection(),
        config=probe_config(tmp_path),
    )
    assert not report.verified
    assert not report.search_document_removed
    problem = next(p for p in report.problems if "meilisearch" in p.lower())
    assert PROBE_ID in problem
    # The other targets are still erased: one leftover never abandons the rest.
    assert report.graph_node_removed
    assert report.postgres_row_removed


def test_a_surviving_graph_node_is_a_named_leftover(tmp_path: Path) -> None:
    report = gate_probe.cleanup_probe(
        PROBE_ID,
        search=FakeSearchClient(),
        graph=FakeGraphDriver(still_present=True),
        publish_root=tmp_path,
        connection=FakeConnection(),
        config=probe_config(tmp_path),
    )
    assert not report.graph_node_removed
    problem = next(p for p in report.problems if "neo4j" in p.lower())
    assert PROBE_ID in problem


def test_a_missing_publish_root_is_a_named_leftover(tmp_path: Path) -> None:
    report = gate_probe.cleanup_probe(
        PROBE_ID,
        search=FakeSearchClient(),
        graph=FakeGraphDriver(),
        publish_root=None,
        connection=FakeConnection(),
        config=probe_config(tmp_path),
    )
    assert not report.export_file_removed
    assert any("MM_PUBLISH_ROOT" in p for p in report.problems)


# --------------------------------------------------------------------------
# run_gate_probe end to end over fakes, MockTransport approve included
# --------------------------------------------------------------------------


class FakeCorpus:
    def __init__(
        self,
        *,
        stage: str | None = "done",
        moments: tuple[MomentRow, ...] = (moment(MOMENT_A),),
        artifacts: tuple[FakeArtifact, ...] = (),
    ) -> None:
        self.stage = stage
        self.moments = moments
        self.artifacts = artifacts

    def stage_status(self, meeting_id: str, stage: str) -> str | None:
        assert stage == gate_probe.EXTRACT_STAGE
        return self.stage

    def moments_for(self, meeting_id: str) -> tuple[MomentRow, ...]:
        return self.moments

    def artifacts_for(self, meeting_id: str) -> tuple[FakeArtifact, ...]:
        return self.artifacts


class ProbeSearchClient(FakeSearchClient):
    """Absent until published, absent again after erasure."""

    def __init__(self) -> None:
        super().__init__()
        self.published = False

    def index(self, name: str) -> Any:
        client = self

        class Index:
            def delete_document(self, document_id: str) -> FakeTask:
                client.removed.append(document_id)
                client.published = False
                return FakeTask()

            def get_document(self, document_id: str) -> Any:
                if client.published:
                    return {"id": document_id, "momentIds": [MOMENT_A]}
                raise absent_error()

        return Index()


class ProbeGraphDriver:
    """Moment projected; artifact node appears on publish, gone on erasure."""

    def __init__(self) -> None:
        self.published = False
        self.erased: list[str] = []

    def session(self, **kwargs: Any) -> Any:
        driver = self

        class Session:
            def __enter__(self) -> Session:
                return self

            def __exit__(self, *exc_info: object) -> None:
                return None

            def run(self, query: str, **params: Any) -> Any:
                if "DETACH DELETE" in query:
                    driver.erased.append(params["id"])
                    driver.published = False
                    return SimpleNamespace(consume=lambda: None)
                # Dispatch mirrors the real query texts: the artifact
                # membership read (`stores._ARTIFACT_IN_GRAPH`) carries an
                # OPTIONAL MATCH *and* the word Moment, so it must be
                # routed before the moment-projected read
                # (`stores._MOMENT_IN_GRAPH`); the plain erasure
                # verification carries neither.
                if "OPTIONAL MATCH" in query:
                    if driver.published:
                        return [{"id": params["id"], "moments": [MOMENT_A]}]
                    return []
                if "Moment" in query:
                    return [{"id": params["id"]}] if params["id"] == MOMENT_A else []
                return [{"id": params["id"]}] if driver.published else []

        return Session()


def approve_transport(connection: FakeConnection) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/moments/{MOMENT_A}/approve"
        connection.row_state = "published"
        return httpx.Response(
            200,
            json=[
                {"id": PROBE_ID, "state": "published"},
                {"id": FOREIGN_ID, "state": "published"},
            ],
        )

    return httpx.MockTransport(handler)


def probe_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(
            stores=SimpleNamespace(
                postgres=SimpleNamespace(
                    host="localhost", port=5433, database="mm", user="mm"
                ),
                neo4j=SimpleNamespace(uri="bolt://localhost:7687"),
                meilisearch=SimpleNamespace(url="http://localhost:7700"),
            )
        ),
        secrets=SimpleNamespace(
            postgres_password="pw", mm_publish_root=tmp_path
        ),
    )


def write_export(tmp_path: Path) -> Path:
    """What the real approve route leaves under the publish root."""
    export = tmp_path / gate_probe.PROBE_KIND / f"{PROBE_ID}.md"
    export.parent.mkdir(exist_ok=True)
    export.write_text("# probe")
    return export


def run_probe(
    tmp_path: Path,
    *,
    corpus: FakeCorpus,
    search: Any,
    graph: Any,
    connection: FakeConnection,
    transport: httpx.BaseTransport | None = None,
) -> GateProbe:
    def publish_on_approve(request: httpx.Request) -> httpx.Response:
        search.published = True
        graph.published = True
        write_export(tmp_path)
        return approve_transport(connection).handler(request)

    return gate_probe.run_gate_probe(
        run_id="2026-08-30-left",
        manifest_id="demo-001",
        meeting_id=MEETING,
        base_url="http://127.0.0.1:8000",
        config=probe_config(tmp_path),
        corpus=corpus,
        search=search,
        graph=graph,
        transport=transport or httpx.MockTransport(publish_on_approve),
        connect=lambda conninfo, autocommit: connection,
    )


def test_the_clean_probe_sequence_over_fakes(tmp_path: Path) -> None:
    search = ProbeSearchClient()
    graph = ProbeGraphDriver()
    connection = FakeConnection(row_state=None)

    probe = run_probe(
        tmp_path, corpus=FakeCorpus(), search=search, graph=graph,
        connection=connection,
    )

    assert probe.problem is None
    assert probe.artifact_id == PROBE_ID
    assert probe.moment_id == MOMENT_A
    assert probe.pre is not None and not probe.pre["meilisearch"].present
    assert probe.post is not None and probe.post["neo4j"].present
    assert probe.approve.ok
    assert probe.approve.published_ids == (PROBE_ID,)
    assert probe.foreign_ids == (FOREIGN_ID,)
    assert probe.cleanup is not None and probe.cleanup.verified
    insert_sql, insert_params = connection.statements[0]
    assert insert_sql.startswith("INSERT INTO artifact")
    assert gate_probe.probe_title("2026-08-30-left") in insert_params


def test_an_unsettled_extract_stage_refuses_by_name(tmp_path: Path) -> None:
    probe = run_probe(
        tmp_path,
        corpus=FakeCorpus(stage="running"),
        search=ProbeSearchClient(),
        graph=ProbeGraphDriver(),
        connection=FakeConnection(),
    )
    assert probe.artifact_id is None
    assert probe.problem is not None
    assert "'running'" in probe.problem


def test_a_meeting_with_no_moments_refuses_by_name(tmp_path: Path) -> None:
    probe = run_probe(
        tmp_path,
        corpus=FakeCorpus(moments=()),
        search=ProbeSearchClient(),
        graph=ProbeGraphDriver(),
        connection=FakeConnection(),
    )
    assert probe.artifact_id is None
    assert probe.problem is not None
    assert "no moments" in probe.problem


def test_every_moment_consumed_refuses_naming_the_state(tmp_path: Path) -> None:
    probe = run_probe(
        tmp_path,
        corpus=FakeCorpus(
            artifacts=(FakeArtifact("x", MOMENT_A, "extracted"),)
        ),
        search=ProbeSearchClient(),
        graph=ProbeGraphDriver(),
        connection=FakeConnection(),
    )
    assert probe.artifact_id is None
    assert probe.problem is not None
    assert "extracted" in probe.problem


def test_an_unprojected_meeting_refuses_naming_the_rebuild(tmp_path: Path) -> None:
    probe = run_probe(
        tmp_path,
        corpus=FakeCorpus(moments=(moment(MOMENT_B),)),  # not in the fake graph
        search=ProbeSearchClient(),
        graph=ProbeGraphDriver(),
        connection=FakeConnection(),
    )
    assert probe.artifact_id is None
    assert probe.problem is not None
    assert f"rebuild --meeting {MEETING}" in probe.problem


def test_a_409_race_resolves_by_rereading_the_probe_row(tmp_path: Path) -> None:
    """The concurrent-approve row of the I/O matrix: the sibling's approval
    won, this run's 409 re-reads its own row as published, and the gate
    counts as exercised — with the race named, and cleanup still done."""
    search = ProbeSearchClient()
    graph = ProbeGraphDriver()
    connection = FakeConnection(row_state=None)

    def raced(request: httpx.Request) -> httpx.Response:
        connection.row_state = "published"
        search.published = True
        graph.published = True
        write_export(tmp_path)
        return httpx.Response(
            409,
            json={
                "type": "urn:meetingminer:problem:nothing-to-approve",
                "detail": "no extracted artifacts to approve",
            },
        )

    probe = run_probe(
        tmp_path, corpus=FakeCorpus(), search=search, graph=graph,
        connection=connection, transport=httpx.MockTransport(raced),
    )

    assert probe.approve.ok, probe.approve.detail
    assert "concurrent" in (probe.approve.detail or "")
    assert probe.approve.published_ids == (PROBE_ID,)
    assert probe.cleanup is not None and probe.cleanup.verified


def test_a_409_with_an_unpublished_row_is_a_real_refusal(tmp_path: Path) -> None:
    search = ProbeSearchClient()
    graph = ProbeGraphDriver()
    connection = FakeConnection(row_state="extracted")

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "type": "urn:meetingminer:problem:nothing-to-approve",
                "detail": "no extracted artifacts to approve",
            },
        )

    probe = run_probe(
        tmp_path, corpus=FakeCorpus(), search=search, graph=graph,
        connection=connection, transport=httpx.MockTransport(refused),
    )

    assert probe.approve.attempted and not probe.approve.ok
    assert "nothing-to-approve" in (probe.approve.detail or "")
    assert probe.cleanup is not None, "a refusal never skips the erasure"


def test_a_store_failure_mid_probe_still_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-read failing leaves a minted row: the interruption is named
    on the probe and the erasure still runs."""
    search = ProbeSearchClient()
    graph = ProbeGraphDriver()
    connection = FakeConnection(row_state="extracted")

    def broken(client: Any, artifact_id: str) -> Any:
        raise gate_probe.StoreAssertError("Meilisearch could not be reached")

    monkeypatch.setattr(gate_probe.stores, "artifact_in_search", broken)
    probe = run_probe(
        tmp_path, corpus=FakeCorpus(), search=search, graph=graph,
        connection=connection,
    )

    assert probe.artifact_id == PROBE_ID
    assert probe.problem is not None
    assert "Meilisearch could not be reached" in probe.problem
    assert connection.row_state is None, "the minted row must still be erased"


def test_an_unexpected_exception_mid_probe_keeps_the_cleanup_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any exception, not only StoreAssertError: an escape here would throw
    the CleanupReport away, and a leftover on that path would be reported
    nowhere. The interruption is converted, named with its type, and the
    erasure verdict survives."""
    search = ProbeSearchClient()
    graph = ProbeGraphDriver()
    connection = FakeConnection(row_state="extracted")

    def explodes(client: Any, artifact_id: str) -> Any:
        raise RuntimeError("driver caught fire")

    monkeypatch.setattr(gate_probe.stores, "artifact_in_search", explodes)
    probe = run_probe(
        tmp_path, corpus=FakeCorpus(), search=search, graph=graph,
        connection=connection,
    )

    assert probe.problem is not None
    assert "RuntimeError" in probe.problem
    assert "driver caught fire" in probe.problem
    assert probe.cleanup is not None and probe.cleanup.verified
    assert connection.row_state is None


def test_a_stage_status_of_none_refuses_by_name(tmp_path: Path) -> None:
    """`None` — no stage row, or no meeting row — is never a green light:
    the corpus layer pins the None, this pins its consumer refusing on it."""
    probe = run_probe(
        tmp_path,
        corpus=FakeCorpus(stage=None),
        search=ProbeSearchClient(),
        graph=ProbeGraphDriver(),
        connection=FakeConnection(),
    )
    assert probe.artifact_id is None
    assert probe.problem is not None
    assert "None" in probe.problem


def test_a_sibling_publishing_before_the_pre_read_is_the_named_race(
    tmp_path: Path,
) -> None:
    """The pre-read race: a concurrent run approved the shared moment
    between this run's mint and its pre-read, so the pre-read shows the
    probe present and already `published`. That is the gate working, never
    a violation — no own approve call is made, the race is named, and the
    positive half and cleanup still hold."""
    search = ProbeSearchClient()
    graph = ProbeGraphDriver()
    search.published = True
    graph.published = True
    write_export(tmp_path)
    connection = FakeConnection(row_state="published")

    def never_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a raced probe must not approve again")

    probe = run_probe(
        tmp_path, corpus=FakeCorpus(), search=search, graph=graph,
        connection=connection, transport=httpx.MockTransport(never_called),
    )

    assert probe.raced is True
    assert probe.problem is None
    assert probe.approve.ok
    assert "before the pre-read" in (probe.approve.detail or "")
    assert probe.approve.published_ids == (PROBE_ID,)
    assert probe.pre is not None and probe.pre["meilisearch"].present
    assert probe.post is not None and probe.post["neo4j"].present
    assert probe.cleanup is not None and probe.cleanup.verified


def test_a_published_probe_with_no_export_file_is_a_named_leftover(
    tmp_path: Path,
) -> None:
    """The approval published the probe, so the route exported a file — none
    at the path this run's configuration names means the api may write under
    a different publish root, and 'verified' would be a guess."""
    report = gate_probe.cleanup_probe(
        PROBE_ID,
        search=FakeSearchClient(),
        graph=FakeGraphDriver(),
        publish_root=tmp_path,
        connection=FakeConnection(),
        config=probe_config(tmp_path),
        expect_export=True,
    )
    assert not report.export_file_removed
    problem = next(p for p in report.problems if "publish root" in p)
    assert PROBE_ID in problem


def test_run_ids_sharing_their_first_64_bytes_share_an_order(
    tmp_path: Path,
) -> None:
    """BLAKE2b keys cap at 64 bytes, so two run ids identical through byte
    64 produce the same order — documented, not hidden: determinism is
    intact, only the spread narrows, and the 409/pre-read race paths carry
    the correctness either way. (A run id caps at 96 characters.)"""
    shared = "2026-08-30-" + "x" * 60  # 71 chars: past the 64-byte key cap
    moments = tuple(
        moment(f"{i}0000000-0000-7000-8000-00000000000{i}") for i in range(1, 6)
    )
    left = gate_probe.choose_order(shared + "-left", moments)
    right = gate_probe.choose_order(shared + "-right", moments)
    assert left == right
