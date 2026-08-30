"""One exclusion domain over the shared stores (rebuild crash recovery).

The bug this guards against: the Postgres advisory lock and the test suite's
cross-worktree file lock were two *disjoint* exclusion mechanisms over the
same Neo4j/Meilisearch containers, so a ``rebuild`` and another worktree's
projection tests raced freely — torn graph writes and mid-run index deletion.
The fix is ``meetingminer.projections.locks.store_file_lock``: every server
entrypoint that writes either store takes the file lock *first*, then the
advisory lock, and the conftest fixture delegates to the same implementation.

These tests are DB-backed but deliberately not store-backed: refusal happens
before either store is opened, which is itself part of the contract — a
refused entrypoint must not have touched anything. Contention is simulated by
flocking the lock file directly (``fcntl.flock`` treats a second descriptor
in the same process as a contender), on a per-test lock path so the tests
never queue on — or interfere with — the real machine-global lock. The real
path derivation is asserted byte-compatible with the historic conftest scheme
separately.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import pytest
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.config import AppConfig, ConfigError
from meetingminer.projections import locks
from meetingminer.projections.stores import ProjectionLockedError

from conftest import FakeEmbedder, truncate_evidence
from projection_seed import insert_artifact, seed_meeting

pytestmark = pytest.mark.slow(reason="cross-process file lock plus both test twins: 9 tests, 3.7s at e5510c7")


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


def test_lock_paths_stay_byte_compatible_with_the_conftest_scheme(
    app_config: AppConfig,
) -> None:
    """Old and new code must contend on the same files, or there is no fix."""
    stores = app_config.settings.stores
    key = hashlib.sha256(
        f"{stores.neo4j.uri}|{stores.meilisearch.url}".encode()
    ).hexdigest()[:16]
    expected = Path(tempfile.gettempdir()) / f"meetingminer-projections-{key}.lock"
    lock_path, holder_path = locks.store_lock_paths(app_config)
    assert lock_path == expected
    assert holder_path == expected.with_suffix(".holder.json")


def test_lock_key_env_override_names_its_own_file(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-14: a test-owned key is a lock nobody derives from the store URLs."""
    monkeypatch.setenv(locks.KEY_ENV, "b14-abc.DEF_1")
    lock_path, holder_path = locks.store_lock_paths(app_config)
    assert lock_path == (
        Path(tempfile.gettempdir()) / "meetingminer-projections-b14-abc.DEF_1.lock"
    )
    assert holder_path == lock_path.with_suffix(".holder.json")
    monkeypatch.delenv(locks.KEY_ENV)
    assert locks.store_lock_paths(app_config)[0] != lock_path


@pytest.mark.parametrize(
    "value", ["", " ", "has space", "a/b", "../x", "x" * 65, "\u00fc", "k=v"]
)
def test_lock_key_env_override_rejects_bad_values(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """The key is a file-name fragment: a bad value is a named ConfigError, not a path."""
    monkeypatch.setenv(locks.KEY_ENV, value)
    with pytest.raises(ConfigError, match=locks.KEY_ENV):
        locks.store_lock_paths(app_config)


def test_conftest_fixture_delegates_to_the_shared_implementation(
    app_config: AppConfig,
) -> None:
    """The suite and the server take the same lock — one implementation."""
    import conftest

    assert conftest._projection_lock_paths(app_config) == locks.store_lock_paths(
        app_config
    )
    assert conftest._projection_lock_timeout_seconds() == locks.lock_timeout_seconds()


@pytest.fixture()
def foreign_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Path, Path]]:
    """A store lock held by 'another process', on a test-scoped path.

    Redirects the path derivation to ``tmp_path`` (so this never contends
    with the real machine-global lock another worktree may hold), flocks the
    file on an independent descriptor, publishes holder metadata, and keeps
    the wait short.
    """
    lock_path = tmp_path / "store.lock"
    holder_path = tmp_path / "store.holder.json"
    monkeypatch.setattr(
        locks, "store_lock_paths", lambda _config: (lock_path, holder_path)
    )
    monkeypatch.setenv(locks.TIMEOUT_ENV, "0.2")
    holder_path.write_text(
        json.dumps({"holder": "another worktree's projection tests", "pid": 12345}),
        encoding="utf-8",
    )
    with open(lock_path, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield lock_path, holder_path
        fcntl.flock(handle, fcntl.LOCK_UN)


def _assert_named_refusal(excinfo: pytest.ExceptionInfo[Any], operation: str) -> None:
    message = str(excinfo.value)
    assert operation in message
    assert "timed out" in message
    assert "another worktree's projection tests" in message


def test_rebuild_against_a_held_file_lock_is_a_named_refusal(
    pool: ConnectionPool,
    app_config: AppConfig,
    foreign_lock: tuple[Path, Path],
    fake_embedder: FakeEmbedder,
) -> None:
    with pool.connection() as conn:
        with pytest.raises(ProjectionLockedError) as excinfo:
            projections.rebuild(
                conn, app_config, embedder_factory=lambda: fake_embedder
            )
    _assert_named_refusal(excinfo, "rebuild")


def test_project_meeting_against_a_held_file_lock_is_a_named_refusal(
    pool: ConnectionPool,
    app_config: AppConfig,
    foreign_lock: tuple[Path, Path],
    fake_embedder: FakeEmbedder,
) -> None:
    meeting_id = uuid4()
    with pool.connection() as conn:
        with pytest.raises(ProjectionLockedError) as excinfo:
            projections.project_meeting(
                conn,
                app_config,
                meeting_id,
                embedder_factory=lambda: fake_embedder,
            )
    _assert_named_refusal(excinfo, f"projection of meeting {meeting_id}")


def test_project_meeting_embeddings_against_a_held_file_lock_is_a_named_refusal(
    pool: ConnectionPool,
    app_config: AppConfig,
    foreign_lock: tuple[Path, Path],
    fake_embedder: FakeEmbedder,
) -> None:
    # The embed pass preflights its `meeting_projection` row before locking,
    # so seed one meeting and record its structural state — Postgres-only
    # writes; the refusal must still land before either store is opened.
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="locks-embed")
        projections._record_structural(conn, app_config, seeded.meeting_id)
        with pytest.raises(ProjectionLockedError) as excinfo:
            projections.project_meeting_embeddings(
                conn,
                app_config,
                seeded.meeting_id,
                embedder_factory=lambda: fake_embedder,
            )
    _assert_named_refusal(excinfo, f"embedding of meeting {seeded.meeting_id}")


def test_project_published_artifacts_against_a_held_file_lock_is_a_named_refusal(
    pool: ConnectionPool,
    app_config: AppConfig,
    foreign_lock: tuple[Path, Path],
) -> None:
    """Story 4.4's entrypoint queues on the same file as the other four.

    This is what retires the deferred `publish_gate.project_artifact` defect:
    the production artifact-projection path takes the store file lock first,
    then the advisory lock, and a foreign hold is a named refusal *before*
    either store is opened — no client is even constructed. A published row
    must exist first, because an empty read returns without needing a lock.
    """
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="locks-artifacts")
        artifact_id = insert_artifact(
            conn, seeded.moment_ids[0], seeded.meeting_id
        )
        with pytest.raises(ProjectionLockedError) as excinfo:
            projections.project_published_artifacts(
                conn, app_config, artifact_ids=[artifact_id]
            )
    _assert_named_refusal(excinfo, "published artifact")


def test_unproject_meeting_against_a_held_file_lock_is_a_named_refusal(
    pool: ConnectionPool,
    app_config: AppConfig,
    foreign_lock: tuple[Path, Path],
) -> None:
    meeting_id = uuid4()
    with pool.connection() as conn:
        with pytest.raises(ProjectionLockedError) as excinfo:
            projections.unproject_meeting(conn, app_config, meeting_id)
    _assert_named_refusal(excinfo, f"unprojection of meeting {meeting_id}")


def test_the_file_lock_is_reentrant_within_one_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, app_config: AppConfig
) -> None:
    """A test holding the lock through its fixture must not deadlock the
    entrypoint it is testing — cross-process exclusion, in-process reentry."""
    lock_path = tmp_path / "store.lock"
    holder_path = tmp_path / "store.holder.json"
    monkeypatch.setattr(
        locks, "store_lock_paths", lambda _config: (lock_path, holder_path)
    )
    monkeypatch.setenv(locks.TIMEOUT_ENV, "0.2")
    with locks.store_file_lock(app_config, holder="outer (the fixture)"):
        assert json.loads(holder_path.read_text())["holder"] == "outer (the fixture)"
        with locks.store_file_lock(app_config, holder="inner (the entrypoint)"):
            pass
        # The outer holding survives the inner release.
        assert holder_path.exists()
        with open(lock_path, "a+") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Fully released: the holder file is gone and the lock is acquirable.
    assert not holder_path.exists()
    with open(lock_path, "a+") as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe, fcntl.LOCK_UN)


def test_a_refused_rebuild_touched_neither_store_nor_the_advisory_lock(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refusal happens before any store contact, and before the advisory lock.

    Store-backed on purpose: a meeting is projected for real first, then a
    rebuild is refused by a foreign-held file lock, and both stores must hold
    exactly what they held before — a full rebuild's first write is
    `drop_all`, so any contact at all would show up in the counts. The
    Postgres advisory lock must still be free during the refusal, which pins
    the ordering: file lock first, advisory lock second.

    The foreign hold lives on a patched, test-scoped lock path — the real
    machine-global path is held by this test's own `projection_stores`
    fixture (reentrantly, which is how the initial projection under it
    works), and must not be fought over.
    """
    from meetingminer.projections import graph, search
    from meetingminer.projections.stores import PROJECTION_LOCK_NAME

    driver, client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="locks-untouched")
        projections.project_meeting(
            conn, app_config, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )
    before_graph = graph.counts(driver)
    before_search = search.counts(client)
    assert before_graph["node:Meeting"] == 1

    lock_path = tmp_path / "store.lock"
    holder_path = tmp_path / "store.holder.json"
    monkeypatch.setattr(
        locks, "store_lock_paths", lambda _config: (lock_path, holder_path)
    )
    monkeypatch.setenv(locks.TIMEOUT_ENV, "0.2")
    holder_path.write_text(
        json.dumps({"holder": "another worktree's projection tests", "pid": 12345}),
        encoding="utf-8",
    )
    with open(lock_path, "a+") as foreign:
        fcntl.flock(foreign, fcntl.LOCK_EX)
        try:
            with pool.connection() as conn:
                with pytest.raises(ProjectionLockedError) as excinfo:
                    projections.rebuild(
                        conn, app_config, embedder_factory=lambda: fake_embedder
                    )
            # The *file* lock refused — not the advisory refusal wording.
            assert "projection store lock timed out" in str(excinfo.value)
            # The advisory lock was never taken: file lock comes first.
            with pool.connection() as probe:
                acquired = probe.execute(
                    "SELECT pg_try_advisory_lock(hashtext(%s))",
                    (PROJECTION_LOCK_NAME,),
                ).fetchone()[0]
                assert acquired, "the refused rebuild is holding the advisory lock"
                probe.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))", (PROJECTION_LOCK_NAME,)
                )
        finally:
            fcntl.flock(foreign, fcntl.LOCK_UN)

    assert graph.counts(driver) == before_graph
    assert search.counts(client) == before_search
