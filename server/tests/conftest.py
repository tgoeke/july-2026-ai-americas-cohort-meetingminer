"""Shared fixtures for story 1.2 tests.

DB-backed tests run against a per-run ``meetingminer_test_<id>`` database on
this checkout's compose Postgres (localhost:5433 in the main checkout; a
worktree's private stack publishes its own port through ``.env.worktree``),
created fresh per session with migrations applied.
When that Postgres is unreachable, DB-backed tests skip with a named reason;
schema/problem-handler tests run without it.

**The drops root (story 2.1a).** Every drop a test makes lives under one
session-scoped ``MM_DROPS_ROOT``, and ``MM_DROPS_ROOT`` is exported into the
process environment *at import time* — before any test imports
``meetingminer.api.main``, which now gates on it at startup the way the worker
does. A developer's own root would put drops in their real corpus, so this is
an assignment rather than a default.
"""

from __future__ import annotations

import atexit
import hashlib
import ipaddress
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from meetingminer import db
from meetingminer.adapters.ocr.apple_vision import AppleVisionOcr
from meetingminer.adapters.ocr.port import OcrBlock, OcrResult
from meetingminer.adapters.ocr.tesseract import TesseractOcr
from meetingminer.adapters.stt.mlx_whisper import MlxWhisperStt
from meetingminer.adapters.stt.parakeet_mlx import ParakeetMlxStt
from meetingminer.adapters.stt.port import SttResult, SttSegment
from meetingminer.config import (
    AppConfig,
    ConfigError,
    load_config,
    merged_env,
    validated_worktree_env,
)

# The repo root lives in its own module so tests do not import the plugin
# module for one constant (story 11.1); see repo_paths.py for the rule.
from repo_paths import REPO_ROOT

#: One id per pytest process, so two concurrent runs never share a database.
#: The fixed ``meetingminer_test`` name was the single reason store-backed
#: suites could not run in parallel: the session fixture below drops its
#: database ``WITH (FORCE)``, so a second run starting mid-suite deleted the
#: first run's database out from under it (story 1.2 review, story 2.7).
#: `uuid4` rather than the pid: pids are reused, and a stale database from a
#: killed run would then be dropped by an unrelated live one.
RUN_ID = uuid4().hex[:12]

#: Postgres identifiers are capped at 63 bytes. The longest name built from
#: this id is ``meetingminer_test_pending_`` + 12 hex = 38, well clear of the
#: cap — truncation would silently collide two runs onto one database.
TEST_DATABASE = f"meetingminer_test_{RUN_ID}"

# pytester provides the fixture test_fast_budget.py drives its inner pytest runs
# with; fast_budget is the fast-set budget and the slow-set rules (story 11.1).
pytest_plugins = ["pytester", "fast_budget"]

# The dedicated maintenance connection below owns this session-level advisory
# lock for each test database's whole lifetime.  `test-db-prune` takes the
# same lock non-blockingly before it drops a candidate, so a freshly-created
# suite database remains protected even before it has a target-DB backend.
_TEST_DATABASE_OWNER_LOCK_PREFIX = "meetingminer-test-owner:"


def database_owner_lock_name(database: str) -> str:
    """The shared advisory-lock name for a per-run test database."""
    return f"{_TEST_DATABASE_OWNER_LOCK_PREFIX}{database}"


@contextmanager
def database_owner_lock(pg_conninfo: str, database: str) -> Iterator[psycopg.Connection]:
    """Hold exclusive lifecycle ownership of ``database`` on Postgres.

    Session-scoped advisory locks vanish when a killed pytest process loses its
    maintenance connection.  That gives the pruner a durable ownership record
    without a second filesystem registry that could itself become stale.
    """
    conn = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        conn.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
            (database_owner_lock_name(database),),
        )
        yield conn
    finally:
        conn.close()


def drop_owned_database(conn: psycopg.Connection, database: str) -> None:
    """Drop a database while its caller holds :func:`database_owner_lock`."""
    conn.execute(
        sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            sql.Identifier(database)
        )
    )


def create_owned_database(conn: psycopg.Connection, database: str) -> None:
    """Create a database while its caller holds :func:`database_owner_lock`."""
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def cleanup_owned_database(conn: psycopg.Connection, database: str) -> None:
    """Best-effort cleanup that reports, but never masks, the primary error."""
    try:
        drop_owned_database(conn, database)
    except psycopg.Error as exc:
        # A setup error is the useful failure here; cleanup trouble must be
        # visible without replacing it, even when pytest runs with `-W error`.
        try:
            print(
                f"warning: could not clean up test database {database}: {exc}",
                file=sys.stderr,
            )
        except Exception:
            pass

# One drops root for the whole session, created before the first import of the
# api app because that import is a startup gate now. `mkdtemp` rather than
# `tmp_path_factory`: the factory is only reachable from inside a fixture, and
# this has to exist by the time `load_config()` first runs.
DROPS_ROOT = Path(tempfile.mkdtemp(prefix="meetingminer-test-drops-")).resolve()
os.environ["MM_DROPS_ROOT"] = str(DROPS_ROOT)
atexit.register(shutil.rmtree, DROPS_ROOT, True)

# Same reasoning, for the publish-root gate (story 4.3): `api.main` now fails
# fast without a usable `MM_PUBLISH_ROOT`, so one must exist in the process
# environment before that module is first imported. The `client` fixture
# below overrides `app.state.publish_root` per test with an isolated
# `tmp_path`-backed folder — this session root only satisfies the import-time
# gate and is never itself written to by a test.
PUBLISH_ROOT = Path(tempfile.mkdtemp(prefix="meetingminer-test-publish-")).resolve()
os.environ["MM_PUBLISH_ROOT"] = str(PUBLISH_ROOT)
atexit.register(shutil.rmtree, PUBLISH_ROOT, True)


@pytest.fixture(autouse=True)
def _isolate_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every in-process test from a developer's exported overrides
    (story 1.10, finding 27): MM_CONFIG_PATH/MM_ENV_PATH must never leak in.

    Subprocess tests are unaffected — they build their env explicitly and
    set both variables themselves. The chdir pins default cwd-relative
    resolution (./config.yaml) to the repo root regardless of where pytest
    was invoked from.
    """
    monkeypatch.delenv("MM_CONFIG_PATH", raising=False)
    monkeypatch.delenv("MM_ENV_PATH", raising=False)
    monkeypatch.chdir(REPO_ROOT)

# Real-shaped provenance: the puller's _source.json content embedded (AD-1).
# Two variants exist in the pulled corpus: pulledAt vs migratedAt.
REAL_PROVENANCE_PULLED: dict[str, Any] = {
    "url": "https://example-my.sharepoint.com/personal/u/_layouts/15/stream.aspx?id=%2Frecording%2Emp4",
    "recordingName": "Daily Standup-20260805_120019UTC-Meeting Recording.mp4",
    "title": "Daily Standup",
    "date": "8.5.26",
    "dateSource": "the recording's createdDateTime",
    "pulledAt": "2026-08-06T14:33:42.341Z",
}
REAL_PROVENANCE_MIGRATED: dict[str, Any] = {
    "url": "https://example-my.sharepoint.com/personal/u/_layouts/15/stream.aspx?id=%2Fdemo%2Emp4",
    "recordingName": "Data Hub Demo-20260610_181541UTC-Meeting Recording.mp4",
    "title": "Data Hub Demo",
    "date": "6.10.26",
    "dateSource": "migrate-layout.js (from pulls.jsonl)",
    "migratedAt": "2026-08-05T21:06:38.786Z",
}


def valid_metadata(source_id: str = "source-1", **overrides: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schemaVersion": 1,
        "sourceId": source_id,
        "corpus": "real",
        "startedAt": "2026-08-05T12:00:19Z",
        "startedAtPrecision": "second",
        "provenance": dict(REAL_PROVENANCE_PULLED),
    }
    metadata.update(overrides)
    return metadata


#: The main checkout's test-store twins (infra/docker-compose.yml
#: `neo4j-test` / `meilisearch-test`); a worktree's `.env.worktree` names its
#: own (story 11.2).
DEFAULT_TEST_NEO4J_URI = "bolt://localhost:7688"
DEFAULT_TEST_MEILI_URL = "http://localhost:7701"


def linked_worktree_refusal(root: Path) -> str | None:
    """The refusal for a checkout whose `.env.worktree` state is unusable.

    `<root>/.git` is a file in a linked worktree and a directory in the main
    checkout. A linked worktree needs the file (else the loader resolves the
    main checkout's ports, and a suite here would run — and wipe twins — on
    the main stack), the file must pass the loader's whole-file validation
    (`merged_env` raises a named `ConfigError` for a truncated, hand-edited
    or foreign-keyed file), and its `MM_STACK_NAME` must be this directory's
    own `meetingminer-<name>` — a copied file must never point the session
    at another worktree's stack. A main checkout carrying the file is
    refused too: it runs the main stack. None when the checkout is fine.
    """
    linked = (root / ".git").is_file()
    stack_file = root / ".env.worktree"
    if linked and not stack_file.is_file():
        return (
            f"{root} is a linked git worktree with no .env.worktree — its"
            " store-backed tests would run against the main checkout's Docker"
            " stack. Run 'make worktree-provision' in that worktree to write"
            " the file and start its own stack (story 11.2)."
        )
    if not linked:
        if stack_file.is_file():
            return (
                f"{root} is the main checkout but carries a .env.worktree —"
                " the main checkout runs the main stack (meetingminer);"
                f" remove {stack_file}."
            )
        return None
    try:
        declared = validated_worktree_env(root / ".env")
        merged_env(root / ".env")  # also validates the base .env contract
    except ConfigError as exc:
        return str(exc)
    expected = f"meetingminer-{root.name}"
    if declared.get("MM_STACK_NAME") != expected:
        return (
            f"{stack_file} declares MM_STACK_NAME="
            f"{declared.get('MM_STACK_NAME')!r} but this checkout is {root.name!r},"
            f" whose stack is {expected!r} — a copied or moved file must not"
            " point the test session at another worktree's stack ('git"
            " worktree move' is not supported for a worktree with a stack)."
        )
    return None


def twin_endpoints(env: Mapping[str, str]) -> tuple[str, str]:
    """(neo4j-test URI, meilisearch-test URL) from a merged environment:
    `MM_TEST_NEO4J_URI` / `MM_TEST_MEILI_URL` when set and non-blank, else
    the main checkout's twins."""
    return (
        env.get("MM_TEST_NEO4J_URI") or DEFAULT_TEST_NEO4J_URI,
        env.get("MM_TEST_MEILI_URL") or DEFAULT_TEST_MEILI_URL,
    )


_STACK_REFUSAL = linked_worktree_refusal(REPO_ROOT)
if _STACK_REFUSAL is not None:
    raise RuntimeError(_STACK_REFUSAL)

#: The disposable twins this session wipes, read through the loader's merged
#: environment: the worktree's generated `.env.worktree` names its private
#: twins, the process environment still wins, and the defaults are the main
#: checkout's compose ports.
_STACK_ENV = merged_env(REPO_ROOT / ".env")
TEST_NEO4J_URI, TEST_MEILI_URL = twin_endpoints(_STACK_ENV)
REQUIRE_TEST_STORES_ENV = "MM_REQUIRE_TEST_STORES"

_DEFAULT_ENDPOINT_PORTS = {
    "bolt": 7687,
    "neo4j": 7687,
    "neo4j+s": 7687,
    "neo4j+ssc": 7687,
    "http": 80,
    "https": 443,
}


def _endpoint_identity(value: str) -> tuple[str, int]:
    """Canonical host/port identity for a destructive store endpoint.

    The safety boundary is the TCP service, not a URL string: localhost,
    127.0.0.1 and ::1 are the same host, and changing the URL scheme does not
    make a wipe on the same port safe. Other hostnames stay name-keyed; tests
    may deliberately point at a separately mapped remote disposable stack.
    """
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port or _DEFAULT_ENDPOINT_PORTS.get(parsed.scheme.lower())
    except ValueError as exc:
        raise RuntimeError(f"invalid projection store endpoint {value!r}: {exc}") from exc
    if not parsed.scheme or host is None or port is None:
        raise RuntimeError(
            f"invalid projection store endpoint {value!r}: scheme, host and port are required"
        )
    canonical_host = host.rstrip(".").lower()
    try:
        if ipaddress.ip_address(canonical_host).is_loopback:
            canonical_host = "loopback"
    except ValueError:
        if canonical_host == "localhost":
            canonical_host = "loopback"
    return canonical_host, port


def _assert_test_store_endpoints_are_disjoint(
    dev_config: AppConfig, test_config: AppConfig
) -> None:
    """Refuse a test config that can resolve either destructive dev store."""
    dev = dev_config.settings.stores
    test = test_config.settings.stores
    comparisons = (
        ("Neo4j", dev.neo4j.uri, test.neo4j.uri),
        ("Meilisearch", dev.meilisearch.url, test.meilisearch.url),
    )
    for store_name, dev_endpoint, test_endpoint in comparisons:
        if _endpoint_identity(dev_endpoint) == _endpoint_identity(test_endpoint):
            raise RuntimeError(
                "refusing destructive projection tests: test"
                f" {store_name} endpoint {test_endpoint!r} resolves the developer"
                f" store at {dev_endpoint!r}"
            )


def _repoint_stores_at_test_twins(
    config: AppConfig,
    *,
    neo4j_uri: str = TEST_NEO4J_URI,
    meili_url: str = TEST_MEILI_URL,
) -> AppConfig:
    """Return a validated config that resolves only the disposable twins.

    `projection_stores` runs `drop_all` against whatever this config resolves,
    and before this override that was the developer's live stores: every suite
    run emptied the searchable corpus, and Postgres `meeting_projection` still
    said "projected", so nothing ever refilled it. The endpoints — and ONLY
    the endpoints — change here; index names, credentials, `drop_all`
    semantics and the store file lock are untouched. The lock keys off
    `neo4j.uri|meilisearch.url` (projections/locks.py `store_lock_paths`), so
    it self-partitions: test runs queue against test runs, dev writers
    against dev writers.
    The dev endpoints are canonicalized and compared before this config can
    reach a connection, lock, or ``drop_all``. That makes the safety invariant
    independent of pytest module selection and catches equivalent loopback
    spellings that raw string inequality would miss.
    """
    repointed = config.model_copy(deep=True)
    stores = repointed.settings.stores
    stores.neo4j = type(stores.neo4j).model_validate(
        {**stores.neo4j.model_dump(), "uri": neo4j_uri}
    )
    stores.meilisearch = type(stores.meilisearch).model_validate(
        {**stores.meilisearch.model_dump(), "url": meili_url}
    )
    _assert_test_store_endpoints_are_disjoint(config, repointed)
    return repointed


@pytest.fixture(scope="session")
def app_config() -> AppConfig:
    # Explicit paths: session-scoped, so it must not depend on the
    # function-scoped cwd/env isolation above. The store endpoints are then
    # repointed at the disposable test twins so no test can wipe the
    # developer's live corpus (see _repoint_stores_at_test_twins).
    return _repoint_stores_at_test_twins(
        load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env")
    )


@pytest.fixture(scope="session")
def pg_conninfo(app_config: AppConfig) -> str:
    """Conninfo for the compose Postgres; skips the test when unreachable."""
    info = db.conninfo(app_config)
    pg = app_config.settings.stores.postgres
    try:
        with psycopg.connect(info, connect_timeout=3):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(
            f"Postgres on {pg.host}:{pg.port} unreachable — start it with"
            f" 'make infra-up' ({exc})"
        )
    return info


@pytest.fixture(scope="session")
def test_database(app_config: AppConfig, pg_conninfo: str) -> Iterator[str]:
    """A fresh per-run test database with migrations applied, dropped after.

    The name carries :data:`RUN_ID`, so two suites running at once own
    different databases and the ``WITH (FORCE)`` drop can only ever affect
    this run's own. The drop is also what keeps the server tidy: without it
    every run would leave a database behind. A killed run still leaks one —
    `make test-db-prune` sweeps those.
    """
    with database_owner_lock(pg_conninfo, TEST_DATABASE) as owner_conn:
        created = False
        try:
            drop_owned_database(owner_conn, TEST_DATABASE)
            create_owned_database(owner_conn, TEST_DATABASE)
            created = True
            with psycopg.connect(
                db.conninfo(app_config, database=TEST_DATABASE)
            ) as conn:
                applied = db.apply_migrations(conn)
            assert applied, "expected a fresh test database to have pending migrations"
            yield TEST_DATABASE
        finally:
            if created:
                cleanup_owned_database(owner_conn, TEST_DATABASE)


@pytest.fixture(scope="session")
def test_pool(app_config: AppConfig, test_database: str) -> Iterator[ConnectionPool]:
    pool = db.create_pool(app_config, database=test_database)
    pool.open(wait=True, timeout=10.0)
    yield pool
    pool.close()


@pytest.fixture()
def client(
    test_pool: ConnectionPool, tmp_path: Path, app_config: AppConfig
) -> TestClient:
    """TestClient over the api app, pointed at the test database, tables empty.

    The lifespan is deliberately not run (no context manager): the pool is
    injected directly so tests never touch the real database. `publish_root`
    is likewise overridden per test to an isolated `tmp_path` folder — the
    process-level `MM_PUBLISH_ROOT` only exists to satisfy `api.main`'s
    import-time startup gate (story 4.3), and a shared root would leak
    exported files (and one shared `.git`) across tests.
    """
    import meetingminer.api.main as api_main

    api_main.app.state.pool = test_pool
    # `api/main` binds `app.state.config` once at import, from the real
    # config.yaml — whose store endpoints are the developer's live Neo4j and
    # Meilisearch. Store-backed route tests seed through the session
    # `app_config` (test twins), so the routes must read the same endpoints
    # or they would query the dev stores the fixtures never wrote.
    api_main.app.state.config = app_config
    api_main.app.state.publish_root = tmp_path / "publish"
    api_main.app.state.publish_root.mkdir()
    truncate_evidence(test_pool)
    return TestClient(api_main.app)


# Every table the worker or the api writes, in one place: TRUNCATE must name
# all of them (meeting references job, frame/meeting_media reference meeting,
# frame_ocr/screenshot reference frame and screen), so a new table added by a
# later story fails loudly here rather than silently leaking rows between
# tests. `screen` is included deliberately: it is a cross-meeting entity that
# no *stage* may delete (AD-5), but test isolation is not a stage.
EVIDENCE_TABLES = (
    "job", "job_stage", "meeting", "meeting_media", "meeting_crop", "frame",
    "frame_ocr", "screen", "screenshot",
    # story 1.5. `participant` and `participant_alias` are included for the
    # same reason `screen` is: they are cross-meeting entities no *stage* may
    # delete (AD-5/AD-11), but test isolation is not a stage.
    "transcript_source", "transcript_segment",
    "participant", "participant_alias", "meeting_participant",
    # story 1.6. `moment` is the one meeting-scoped table no *stage* replaces
    # wholesale (AD-6 makes its ids citation targets), which makes naming it
    # here doubly load-bearing: without the TRUNCATE its rows would survive
    # every test in the session.
    "moment", "moment_segment",
    # story 1.7. Referenced by nothing, but it references `meeting`, so
    # TRUNCATE has to name it or the whole statement is refused.
    "meeting_projection",
    # story 4.1. References `moment` without cascade, so TRUNCATE must name it
    # or the `moment` truncation is refused.
    "artifact",
    # story 4.1a. Cascades from `meeting`, but TRUNCATE names every table the
    # worker writes so a new one fails loudly here rather than leaking rows.
    "extraction_source",
    # story 2.5. API-owned structure (AD-5): the three entity tables are
    # cross-meeting rows no stage may delete, the two assignment tables
    # reference them without cascade — TRUNCATE must name all five or the
    # entity truncation is refused.
    "series", "product", "project", "meeting_series", "meeting_project",
    # story 10.1. `topic` cascades from `meeting` and `topic_mention` from
    # `topic` and `moment`, but TRUNCATE must name every table referencing
    # `meeting`/`moment` or the statement is refused.
    "topic", "topic_mention",
    # story 10.2. `topic_thread` references `topic`, so TRUNCATE must name it
    # or the `topic` truncation above is refused outright — and `thread` must
    # be named with it, because the statement trigger that empties `thread`
    # when memberships are truncated would otherwise be the only thing
    # clearing it. Both are worker-owned, machine-derived navigation metadata,
    # never artifacts.
    "thread", "topic_thread",
    # story 10.4. `ranking_signal` references `moment` (composite, cascading),
    # and TRUNCATE refuses to empty a table another one references however
    # that reference cascades on DELETE — so omitting this name would refuse
    # the `moment` truncation above and take every store-backed suite with
    # it. Worker-owned machine-derived ranking signals, never artifacts.
    "ranking_signal",
)


def truncate_evidence(pool: ConnectionPool) -> None:
    """Empty every job/evidence table on the test database."""
    with pool.connection() as conn:
        conn.execute(f"TRUNCATE {', '.join(EVIDENCE_TABLES)}")


# A drop's transcript files are real input now that the `align` stage parses
# them (story 1.5), so the factory writes parseable content rather than opaque
# bytes. Both lineages and the speaker-less VTT the corpus actually carries are
# available to tests through `files=` plus an explicit overwrite.
TEAMS_TRANSCRIPT = (
    "[0:02] Goeke, Timothy: Everybody, good morning.\n"
    "[0:05] Whitmore, Ellis: Morning, all.\n"
    "[0:09] Goeke, Timothy: Let us walk the revenue slide.\n"
)
LEGACY_TRANSCRIPT = (
    "Stonebridge, Finley started transcription\n"
    "\n"
    "Ironside, Indigo | 00:00\n"
    "Starting. Okay, perfect.\n"
    "So welcome, everyone.\n"
    "\n"
    "Speaker 8 | 00:12\n"
    "Can you say that again?\n"
    "\n"
    "Ellis | 01:00:04\n"
    "Past the hour now.\n"
)
SPEAKERLESS_VTT = (
    "WEBVTT\n"
    "\n"
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/13-0\n"
    "00:00:02.100 --> 00:00:04.900\n"
    "Everybody, good morning.\n"
    "\n"
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/14-0\n"
    "00:00:05.000 --> 00:00:07.400\n"
    "Morning, all.\n"
)
DROP_FILE_CONTENT: dict[str, bytes] = {
    "transcript.txt": TEAMS_TRANSCRIPT.encode("utf-8"),
    "transcript.vtt": SPEAKERLESS_VTT.encode("utf-8"),
}


def _placeholder(name: str) -> bytes:
    return b"placeholder content for " + name.encode()


DropFactory = Callable[..., Path]


@pytest.fixture()
def make_drop(tmp_path: Path) -> DropFactory:
    """Create a drop directory under MM_DROPS_ROOT: metadata.json + evidence.

    Under the root, not under ``tmp_path``: intake refuses a drop outside the
    configured root (story 2.1a), so a fixture that built one elsewhere would
    be testing the refusal on every test. The directory name carries the test's
    own ``tmp_path`` name so drops stay distinguishable in a shared root, and
    each is a direct child of it — the ``<drop-dir>/<filename>`` shape
    `storage-layout.md` §4 pins.
    """

    counter = iter(range(1000))

    def _make(
        metadata: dict[str, Any] | None = None,
        files: tuple[str, ...] = ("transcript.txt",),
        raw_metadata: str | None = None,
        omit_metadata: bool = False,
    ) -> Path:
        drop = DROPS_ROOT / f"{tmp_path.name}-drop-{next(counter)}"
        drop.mkdir()
        if not omit_metadata:
            if raw_metadata is not None:
                (drop / "metadata.json").write_text(raw_metadata, encoding="utf-8")
            else:
                (drop / "metadata.json").write_text(
                    json.dumps(metadata if metadata is not None else valid_metadata()),
                    encoding="utf-8",
                )
        for name in files:
            (drop / name).write_bytes(DROP_FILE_CONTENT.get(name, _placeholder(name)))
        return drop

    return _make


# --- story 1.3: content root + synthetic recording -------------------------

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

requires_ffmpeg = pytest.mark.skipif(
    not (FFMPEG and FFPROBE),
    reason="ffmpeg/ffprobe not on PATH — install them with 'brew install ffmpeg'",
)

# Shape of the generated recording: short enough to sample in well under a
# second, long enough that a 2s interval yields several frames.
SYNTHETIC_DURATION_SECONDS = 6
SYNTHETIC_WIDTH = 320
SYNTHETIC_HEIGHT = 240
SYNTHETIC_FPS = 10


@pytest.fixture()
def content_root(tmp_path: Path) -> Path:
    """An isolated, writable MM_CONTENT_ROOT for a single test."""
    root = tmp_path / "content"
    root.mkdir()
    return root


@pytest.fixture(scope="session")
def drops_root() -> Path:
    """The session's MM_DROPS_ROOT — the root `make_drop` builds under.

    Session-scoped and not per-test, because it is the root the loaded
    `AppConfig` (and therefore the api app) was built with. Isolation between
    tests comes from `truncate_evidence` and from each drop having its own
    directory, not from a fresh root: two drops sharing a root is the
    production shape, and a per-test root would hide a path bug that only
    appears when it does not.
    """
    return DROPS_ROOT


@pytest.fixture(scope="session")
def synthetic_recording(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real (tiny) mp4 with a video and an audio stream, generated once.

    Built by ffmpeg rather than committed, so the repo carries no binary
    fixture and the file always matches the local ffmpeg build. Tests that
    need it in a drop copy it — the drop directory is the thing under test.
    """
    if not FFMPEG:
        pytest.skip("ffmpeg not on PATH — install it with 'brew install ffmpeg'")
    path = tmp_path_factory.mktemp("synthetic-media") / "recording.mp4"
    proc = subprocess.run(
        [
            FFMPEG, "-nostdin", "-v", "error", "-y",
            "-f", "lavfi",
            "-i", f"testsrc=size={SYNTHETIC_WIDTH}x{SYNTHETIC_HEIGHT}"
                  f":rate={SYNTHETIC_FPS}:duration={SYNTHETIC_DURATION_SECONDS}",
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=mono:sample_rate=16000"
                  f":duration={SYNTHETIC_DURATION_SECONDS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0 or not path.is_file():
        pytest.skip(f"ffmpeg could not build the synthetic recording: {proc.stderr.strip()}")
    return path


# --- story 1.4: OCR engines + a text image that needs no imaging library ----

OCR_ENGINES = {AppleVisionOcr.name: AppleVisionOcr, TesseractOcr.name: TesseractOcr}


def requires_ocr(engine_name: str) -> pytest.MarkDecorator:
    """Skip with the engine's own reason when it cannot run on this host."""
    reason = OCR_ENGINES[engine_name].unavailable_reason()
    return pytest.mark.skipif(reason is not None, reason=reason or "")


# A 5x7 block font, scaled up and painted into an uncompressed 24-bit BMP.
# Deliberately dependency-free: the repo carries no image fixture, no imaging
# library is installed, and this ffmpeg build has no drawtext filter — but
# every OCR engine reads BMP, and a high-contrast blocky glyph is exactly what
# a text recognizer is good at.
_GLYPHS: dict[str, tuple[str, ...]] = {
    " ": ("     ",) * 7,
    "C": (" ### ", "#   #", "#    ", "#    ", "#    ", "#   #", " ### "),
    "E": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"),
    "G": (" ### ", "#   #", "#    ", "#  ##", "#   #", "#   #", " ### "),
    "I": ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "#####"),
    "M": ("#   #", "## ##", "# # #", "#   #", "#   #", "#   #", "#   #"),
    "N": ("#   #", "##  #", "# # #", "#  ##", "#   #", "#   #", "#   #"),
    "O": (" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "R": ("#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"),
    "S": (" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "),
}

GLYPH_ALPHABET = "".join(sorted(_GLYPHS))


def write_text_bmp(path: Path, text: str, scale: int = 10, margin: int = 40) -> Path:
    """Paint ``text`` black-on-white into a BMP at ``path``.

    Only the characters in :data:`GLYPH_ALPHABET` are drawable — enough for
    the words the OCR tests assert on, and a KeyError is a clearer failure
    than a silently blank image.
    """
    rows, cols = 7 * scale, (len(text) * 6 - 1) * scale
    width, height = cols + margin * 2, rows + margin * 2
    pixels = [[255] * width for _ in range(height)]
    for index, character in enumerate(text):
        for glyph_y, line in enumerate(_GLYPHS[character]):
            for glyph_x, cell in enumerate(line):
                if cell != "#":
                    continue
                x0 = margin + (index * 6 + glyph_x) * scale
                y0 = margin + glyph_y * scale
                for dy in range(scale):
                    pixels[y0 + dy][x0 : x0 + scale] = [0] * scale

    row_bytes = width * 3
    padding = (4 - row_bytes % 4) % 4
    body = bytearray()
    for y in range(height - 1, -1, -1):  # BMP scanlines run bottom-up
        for value in pixels[y]:
            body += bytes((value, value, value))
        body += b"\x00" * padding
    header = struct.pack("<2sIHHI", b"BM", 14 + 40 + len(body), 0, 0, 14 + 40)
    info = struct.pack(
        "<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(body), 2835, 2835, 0, 0
    )
    path.write_bytes(header + info + bytes(body))
    return path


@pytest.fixture()
def text_image(tmp_path: Path) -> Callable[..., Path]:
    """Factory for high-contrast text images the OCR engines can read."""

    counter = iter(range(1000))

    def _make(text: str, name: str | None = None) -> Path:
        target = tmp_path / (name or f"ocr-{next(counter)}.bmp")
        return write_text_bmp(target, text)

    return _make


class FakeOcr:
    """A deterministic `Ocr` stand-in: the engine tests never need a real one.

    Recognition is keyed on the image's *filename*, which is how the worker
    tests script a whole meeting's screen sequence: ``frame-000002.jpg`` gets
    whatever ``by_frame`` says the second frame shows.
    """

    name = "fake"

    def __init__(
        self,
        by_frame: dict[str, str] | None = None,
        default: str = "",
        block_x: float = 0.1,
    ) -> None:
        self.by_frame = by_frame or {}
        self.default = default
        # Where the recognized boxes sit horizontally. The default is well
        # inside any share region; a test that wants boxes in the webcam
        # column (so the crop has something to exclude) raises it.
        self.block_x = block_x
        self.calls: list[str] = []

    def recognize(self, path: Path) -> OcrResult:
        self.calls.append(path.name)
        text = self.by_frame.get(path.name, self.default)
        lines = [line for line in text.splitlines() if line.strip()]
        blocks = tuple(
            OcrBlock(
                text=line.strip(),
                x=self.block_x,
                y=0.1 + index * 0.1,
                width=min(0.6, 1.0 - self.block_x),
                height=0.05,
                confidence=1.0,
            )
            for index, line in enumerate(lines)
        )
        return OcrResult(blocks=blocks, text="\n".join(b.text for b in blocks), engine=self.name)


@pytest.fixture()
def fake_ocr(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeOcr]:
    """Bind the `ocr` stage to a scripted engine instead of a real one."""

    import meetingminer.pipeline.stages.ocr as ocr_stage

    def _install(
        by_frame: dict[str, str] | None = None,
        default: str = "",
        block_x: float = 0.1,
    ) -> FakeOcr:
        engine = FakeOcr(by_frame=by_frame, default=default, block_x=block_x)
        monkeypatch.setattr(ocr_stage, "build_ocr", lambda *_a, **_kw: engine)
        return engine

    return _install


# --- story 1.5: a deterministic STT engine and the real-engine skip marker ---

STT_ENGINES = {MlxWhisperStt.name: MlxWhisperStt, ParakeetMlxStt.name: ParakeetMlxStt}


def requires_stt(engine_name: str) -> pytest.MarkDecorator:
    """Skip with the engine's own reason when it cannot run on this host."""
    reason = STT_ENGINES[engine_name].unavailable_reason()
    return pytest.mark.skipif(reason is not None, reason=reason or "")


class FakeStt:
    """A deterministic `Stt` stand-in: the worker tests never need a real one.

    Scripted as ``(start_ms, end_ms, text)`` triples, so a test states exactly
    what the verification lane heard and can then assert on the delta the
    aligner computed against a provided transcript.
    """

    name = "fake-stt"

    def __init__(
        self,
        segments: tuple[tuple[int, int, str], ...] = (),
        model: str = "fake-model",
        language: str | None = "en",
    ) -> None:
        self.segments = segments
        self.model = model
        self.language = language
        self.calls: list[Path] = []

    def transcribe(self, path: Path) -> SttResult:
        self.calls.append(path)
        parsed = tuple(
            SttSegment(start_ms=start, end_ms=end, text=text)
            for start, end, text in self.segments
        )
        return SttResult(
            segments=parsed,
            text=" ".join(segment.text for segment in parsed),
            engine=self.name,
            model=self.model,
            language=self.language,
        )


@pytest.fixture(autouse=True)
def _no_real_stt(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach a real recognizer, even by accident.

    Unlike the OCR engines, which are local and fast, binding a real `Stt`
    engine downloads a multi-gigabyte model and then spends real time on it —
    so a worker test that merely happens to walk past `transcribe` would turn
    the suite into a download. Every test starts bound to an engine that hears
    nothing; the ones that care about STT install their own through the
    `fake_stt` fixture, which is applied after this one and wins.
    """
    import meetingminer.pipeline.stages.transcribe as transcribe_stage

    monkeypatch.setattr(transcribe_stage, "build_stt", lambda *_a, **_kw: FakeStt())


@pytest.fixture()
def fake_stt(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeStt]:
    """Bind the `transcribe` stage to a scripted engine instead of a real one."""

    import meetingminer.pipeline.stages.transcribe as transcribe_stage

    def _install(
        segments: tuple[tuple[int, int, str], ...] = (), **kwargs: Any
    ) -> FakeStt:
        engine = FakeStt(segments=segments, **kwargs)
        monkeypatch.setattr(transcribe_stage, "build_stt", lambda *_a, **_kw: engine)
        return engine

    return _install


# --- story 4.1: a deterministic Llm and the no-real-model guard --------------


# The reply a default-bound fake gives: a well-formed extraction document that
# parses cleanly to zero artifacts. A bare table header is an honest "nothing
# here" — it carries no rows, so it is not a populated section and does not
# trip the no-silent-zero signal. Story 4.1a made extraction markdown-shaped;
# the JSON reply this used to be no longer parses.
EMPTY_EXTRACTION_DOCUMENT = (
    "## Decisions\n"
    "\n"
    "| ID | Item | Timestamp |\n"
    "|----|------|-----------|\n"
)


class FakeLlm:
    """A deterministic `Llm` stand-in: no test may reach a real model provider.

    Scripted per call: each entry in ``replies`` is either the reply text for
    that call or an exception instance to raise instead. Once the script runs
    out, ``default`` answers — the zero-artifact document, so a worker test
    that merely walks past `extract` completes without proposing anything.

    ``calls`` records prompts and ``options`` the per-call
    :class:`~meetingminer.adapters.llm.LlmOptions` each was given, so a test
    can assert the role's context window reached the port (story 4.1a) without
    a real provider anywhere near it.
    """

    def __init__(
        self,
        replies: tuple[Any, ...] = (),
        default: str = EMPTY_EXTRACTION_DOCUMENT,
        model: str = "fake-llm",
        fallback_engaged: bool = False,
    ) -> None:
        self.replies = list(replies)
        self.default = default
        self.model = model
        self.fallback_engaged = fallback_engaged
        self.calls: list[str] = []
        self.options: list[Any] = []

    def complete(self, prompt: str, options: Any = None) -> Any:
        from meetingminer.adapters.llm import LlmReply

        self.calls.append(prompt)
        self.options.append(options)
        item = self.replies.pop(0) if self.replies else self.default
        if isinstance(item, BaseException):
            raise item
        return LlmReply(
            text=item, model=self.model, fallback_engaged=self.fallback_engaged
        )


# Every production `build_llm` call site, by module attribute. The guard below
# patches all of them, because a call site the guard does not name is a call
# site that spends real API money the first time a test walks past it. Adding a
# role without adding it here is the failure mode, so the list is the thing that
# gets extended, not the fixture body.
LLM_CALL_SITES: tuple[tuple[str, str], ...] = (
    # story 4.1 — the `extract` stage.
    ("meetingminer.pipeline.stages.extract", "build_llm"),
    # story 3.3 — `POST /chat` classifies and synthesizes through this one.
    ("meetingminer.api.chat", "build_llm"),
)


def _bind_llm_call_sites(
    monkeypatch: pytest.MonkeyPatch, factory: Callable[..., Any]
) -> None:
    import importlib

    for module_name, attribute in LLM_CALL_SITES:
        monkeypatch.setattr(
            importlib.import_module(module_name), attribute, lambda *_a, **_kw: factory()
        )


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every production completer binding is always a fake.

    Same reasoning as `_no_real_stt`: with `extract` registered, any worker
    test that walks the pipeline to its end would otherwise spend real API
    money (or hang on a local Ollama) — and with `POST /chat` registered, so
    would any api test that happens to post a question. Every test starts with
    both call sites bound to a completer that proposes nothing; the ones that
    care install their own through `fake_llm` or `fake_chat_llm`, which are
    applied after this one and win.

    What is guarded is exactly the :data:`LLM_CALL_SITES` entries — the
    production `build_llm` call sites. Code that reached
    `meetingminer.adapters.llm.build_llm` some other way would bypass this, so
    the SDK boundary itself is exercised only against a stubbed `litellm` module
    (`test_extraction_core.py`), never a real provider.
    """
    _bind_llm_call_sites(monkeypatch, FakeLlm)


@pytest.fixture()
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeLlm]:
    """Bind the `extract` stage to a scripted completer instead of a real one."""

    import meetingminer.pipeline.stages.extract as extract_stage

    def _install(replies: tuple[Any, ...] = (), **kwargs: Any) -> FakeLlm:
        engine = FakeLlm(replies=replies, **kwargs)
        monkeypatch.setattr(extract_stage, "build_llm", lambda *_a, **_kw: engine)
        return engine

    return _install


@pytest.fixture()
def fake_chat_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeLlm]:
    """Bind `POST /chat` to a scripted completer instead of a real one.

    One instance answers both of the route's calls — classification first, then
    synthesis — so a scripted `replies` tuple is read in that order and
    `engine.calls` records both prompts. Its default reply is the classifier's
    "no template", which is also harmless as a synthesis draft: a test that
    scripts nothing gets a search-only route and an answer the citation gate
    rejects, never a model call that costs money.
    """

    import meetingminer.api.chat as chat_module

    def _install(replies: tuple[Any, ...] = (), **kwargs: Any) -> FakeLlm:
        kwargs.setdefault("default", '{"template": null}')
        engine = FakeLlm(replies=replies, **kwargs)
        monkeypatch.setattr(chat_module, "build_llm", lambda *_a, **_kw: engine)
        return engine

    return _install


# --- story 1.7: projection stores, the embedder, and the ingest-complete trigger ---


class FakeEmbedder:
    """A deterministic `Embedder` stand-in: no test may reach a real Ollama.

    Vectors are derived from the text so two calls over the same passage agree
    and a test can assert that a *specific* document got a vector, but nothing
    about their content is meaningful — retrieval quality is measured by the
    Epic 5 harness, not here.
    """

    def __init__(self, model: str = "fake-embedder", dimension: int = 1024) -> None:
        self.model = model
        self.dimension = dimension
        self.calls: list[tuple[str, ...]] = []

    def _vector(self, text: str) -> tuple[float, ...]:
        # Hashed, not summed: a character sum collides on every anagram and on
        # most unrelated passages, which would make "this document got *its*
        # vector" unassertable — the one thing this stand-in exists to let a
        # test check. blake2b is deterministic across processes, unlike hash().
        seed = int.from_bytes(
            hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big"
        )
        return tuple(
            (((seed >> (index % 32)) + index) % 9973) / 9973.0
            for index in range(self.dimension)
        )

    def embed_documents(self, texts: Any) -> tuple[tuple[float, ...], ...]:
        batch = tuple(texts)
        self.calls.append(batch)
        return tuple(self._vector(text) for text in batch)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._vector(text)


class DownEmbedder:
    """An `Embedder` whose host is unreachable — the resumable failure."""

    def __init__(self, model: str = "fake-embedder", dimension: int = 1024) -> None:
        self.model = model
        self.dimension = dimension

    def embed_documents(self, texts: Any) -> tuple[tuple[float, ...], ...]:
        from meetingminer.adapters.embed import EmbedderUnavailableError

        raise EmbedderUnavailableError(
            "embedding model host unreachable at http://localhost:11434 (test)"
        )

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self.embed_documents([text])[0]


class BrokenEmbedder:
    """An `Embedder` that answers, wrongly — the failure no retry fixes.

    Deliberately distinct from :class:`DownEmbedder`. A host that is *down*
    leaves a structurally projected meeting and resumes later; a host that
    answers with a model it does not have, or a vector of the wrong width,
    is a configuration error, and the two must not collapse into one branch
    (`retrieval-prior-art.md` §3 rules 3 and 4).
    """

    def __init__(self, model: str = "fake-embedder", dimension: int = 1024) -> None:
        self.model = model
        self.dimension = dimension

    def embed_documents(self, texts: Any) -> tuple[tuple[float, ...], ...]:
        from meetingminer.adapters.embed import EmbedderError

        raise EmbedderError(
            f"embedder {self.model!r} on http://localhost:11434 refused the"
            ' request (HTTP 404): {"error":"model not found"}'
        )

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self.embed_documents([text])[0]


@pytest.fixture()
def fake_embedder(app_config: AppConfig) -> FakeEmbedder:
    """An embedder at the configured width, so the store settings match."""
    return FakeEmbedder(dimension=app_config.settings.embedder.dimension)


@pytest.fixture(autouse=True)
def _no_incidental_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    """No worker test may write to the retrieval stores by accident.

    Same reasoning as `_no_real_stt`: story 1.7 hooks a projection call into
    every stage-settle point, so a pipeline test that merely walks past
    `moments` would start writing into the developer's live Neo4j and
    Meilisearch. Projection failures are swallowed by design, so the pollution
    would be silent. Every test therefore starts with the trigger stubbed out;
    the ones that are *about* the trigger restore it through the
    `projection_trigger` fixture, which is applied after this one and wins.
    """
    from meetingminer.pipeline import runner

    monkeypatch.setattr(runner, "_maybe_project", lambda *_a, **_kw: None)
    monkeypatch.setattr(runner, "_maybe_project_documents", lambda *_a, **_kw: None)


def _real_maybe_project() -> Any:
    from meetingminer.pipeline import runner

    return runner._maybe_project


# Captured at import time, before any fixture can stub it out.
_REAL_MAYBE_PROJECT = _real_maybe_project()


def _real_maybe_project_documents() -> Any:
    from meetingminer.pipeline import runner

    return runner._maybe_project_documents


_REAL_MAYBE_PROJECT_DOCUMENTS = _real_maybe_project_documents()


@pytest.fixture()
def projection_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the real ingest-complete projection trigger back for this test."""
    from meetingminer.pipeline import runner

    monkeypatch.setattr(runner, "_maybe_project", _REAL_MAYBE_PROJECT)


@pytest.fixture()
def document_projection_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the real extraction-document settle trigger back for this test."""
    from meetingminer.pipeline import runner

    monkeypatch.setattr(
        runner, "_maybe_project_documents", _REAL_MAYBE_PROJECT_DOCUMENTS
    )


def stores_reachable(config: AppConfig) -> str | None:
    """Why the projection stores cannot be used, or ``None`` when they can.

    Mirrors the DB-test convention: a store that is down produces a *named*
    skip rather than a silently green suite.
    """
    from meetingminer.projections.stores import (
        ProjectionError,
        meili_client,
        neo4j_driver,
    )

    try:
        with neo4j_driver(config):
            pass
    except ProjectionError as exc:
        return str(exc)
    try:
        meili_client(config)
    except ProjectionError as exc:
        return str(exc)
    return None


@pytest.fixture(scope="session")
def stores_up(app_config: AppConfig) -> None:
    """Skip when the TEST stores (neo4j-test / meilisearch-test) are down.

    The session config resolves the disposable test twins, never the
    developer's dev stores — so when the twins are down the only correct
    behavior is a named skip. Falling back to the dev endpoints here would
    reintroduce the corpus wipe this isolation exists to prevent.
    """
    reason = stores_reachable(app_config)
    if reason is not None:
        message = (
            "projection test stores (meilisearch-test on"
            f" {TEST_MEILI_URL}, neo4j-test on {TEST_NEO4J_URI}) are not"
            f" reachable — start them with 'make infra-up'. Cause: {reason}"
        )
        if os.environ.get(REQUIRE_TEST_STORES_ENV) == "1":
            pytest.fail(message)
        pytest.skip(message)


def _projection_lock_paths(config: AppConfig) -> tuple[Path, Path]:
    """Return the shared projection lock and its holder metadata path."""
    from meetingminer.projections.locks import store_lock_paths

    return store_lock_paths(config)


def _projection_lock_timeout_seconds() -> float:
    from meetingminer.projections.locks import lock_timeout_seconds

    return lock_timeout_seconds()


@contextmanager
def _projection_store_lock(config: AppConfig) -> Iterator[None]:
    """Serialize projection-store tests across processes.

    Postgres tests got per-run isolation (:data:`RUN_ID`), but these two
    stores cannot: Neo4j Community serves exactly one database, and AD-4 fixes
    the Meilisearch index names, so there is no namespace to hide in and
    `drop_all` below wipes whatever is there. Rather than pretend that is
    safe, concurrent runs queue here and take turns.

    One implementation, not two: this delegates to
    ``meetingminer.projections.locks.store_file_lock`` — the same mechanism
    every server entrypoint uses, but keyed to the test-twin endpoints. Test
    writers therefore serialize with other writers of those twins; dev-store
    rebuilds and workers use a different endpoint key and do not contend. The
    lock is reentrant within this process, which lets a test already holding it
    call a locked entrypoint without deadlocking against its own fixture.
    """
    from meetingminer.projections.locks import store_file_lock

    with store_file_lock(config, holder="server test suite (projection stores)"):
        yield


@pytest.fixture(autouse=True)
def _rebuild_cli_uses_test_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Centrally isolate every rebuild CLI config load in the test process."""
    from meetingminer.projections import cli as rebuild_cli

    real_load_config = rebuild_cli.load_config
    monkeypatch.setattr(
        rebuild_cli,
        "load_config",
        lambda *args, **kwargs: _repoint_stores_at_test_twins(
            real_load_config(*args, **kwargs)
        ),
    )


@pytest.fixture()
def projection_stores(app_config: AppConfig, stores_up: None) -> Iterator[Any]:
    """Both projection stores, emptied and re-schema'd for one test.

    Neo4j Community has one database and the Meilisearch index names are fixed
    by AD-4, so there is no per-test namespace to hide in — instead the whole
    session resolves the disposable test-store twins (`neo4j-test` /
    `meilisearch-test` in infra/docker-compose.yml) via the `app_config`
    override, and `drop_all` wipes only those. The developer's dev stores are
    never touched: "make rebuild regenerates them" was the old justification
    for wiping them, and it was wrong in practice — nothing ever re-ran the
    rebuild, so search served an empty corpus. The wipe is here rather than in
    each test so no test can inherit another's nodes and pass vacuously.
    """
    from meetingminer.projections.stores import (
        drop_all,
        ensure_graph_schema,
        ensure_search_schema,
        meili_client,
        neo4j_driver,
    )

    dimension = app_config.settings.embedder.dimension
    with _projection_store_lock(app_config):
        with neo4j_driver(app_config) as driver:
            client = meili_client(app_config)
            drop_all(driver, client)
            ensure_graph_schema(driver)
            ensure_search_schema(client, app_config, dimension=dimension)
            yield driver, client
