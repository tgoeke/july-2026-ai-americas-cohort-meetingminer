"""The run-owned publish-gate probe: minted, approved, asserted, erased.

Story 11.3. Check 2.11 measures the approve→project transition on one
artifact the run itself mints — never on a subject's ``extracted`` rows, so
the shared corpus survives every run and two runs cannot consume each
other's gate half. The probe cites an *existing projected* subject moment,
because ``graph.project_artifacts`` rolls its whole write back when the
cited ``Moment`` node is missing, and only the worker/rebuild ever project
a meeting.

The sequence: eligibility from read-only corpus and store reads; one
``INSERT`` of an ``extracted`` artifact whose title and body carry the run
id (Postgres mints the UUID, so the run-id prefix lives in the marker text
and in the report's minted-id list); membership read; approval through the
public ``POST /moments/{id}/approve``; membership read again; then
:func:`cleanup_probe` erases every trace — the Meilisearch document, the
Neo4j node, the export file, the Postgres row — and *verifies* each target
read back absent. A leftover is a named problem, loud by design.

**The store-write sanction, and its exact width.** This module is the one
place in the evals tree allowed a write-shaped store call, and only in the
erasure direction, only on the id the run just minted.
``tests/test_harness_boundary.py`` admits this file by name in the driver
guard and pins it to delete-shaped calls textually — the probe layer can
erase its own probe, and can never fabricate the membership the check
asserts. ``harness/stores.py`` stays read-only and remains the only module
holding a ``neo4j`` import; this file's only store-driver import is the
Meilisearch error family, needed to tell "absent" from "broken" when the
erasure is verified.

Seeding through an ordinary writable psycopg connection follows the
convention ``checks/test_corpus_artifacts.py`` established: test-layer
setup, not harness production code — the harness's own connection cannot
write at all (AD-16), which is exactly why it stays out of this file.

**One residual window is accepted and detected after the fact.** A subject
``extracted`` row landing on the chosen moment *between* the eligibility
read and the approval — an operator approving or re-extracting mid-run —
is consumed by the probe's approval; the settled-``extract``-stage gate
narrows the window but cannot close it. The assembly detects the case (a
foreign published id the discovery saw as ``extracted``) and fails the
check naming the consumed ids, so the event is on the record rather than
silent.
"""

from __future__ import annotations

import hashlib
import fcntl
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import psycopg
from meilisearch.errors import MeilisearchApiError

from evals.harness import checks, retrieval, stores
from evals.harness.checks import (
    ApproveOutcome,
    CleanupReport,
    GateProbe,
    StorePresence,
)
from evals.harness.corpus import MomentRow
from evals.harness.retrieval import ApproveError
from evals.harness.stores import ARTIFACTS_INDEX, StoreAssertError

__all__ = [
    "ARTIFACTS_INDEX",
    "EXTRACT_STAGE",
    "PROBE_KIND",
    "PROBE_TITLE_PREFIX",
    "MeilisearchApiError",
    "StoreAssertError",
    "choose_order",
    "cleanup_probe",
    "eligible_moments",
    "is_probe_artifact",
    "probe_body",
    "probe_title",
    "run_gate_probe",
    "split_owned",
]

#: Every minted row is recognizably an eval probe, and recognizably one
#: run's: the title is this prefix plus the run id, so a leftover found in
#: the corpus, the search index or the publish root names the run that owes
#: its erasure.
PROBE_TITLE_PREFIX = "eval-gate-probe-"

#: ``action-item`` deliberately, not ``adr``: the approve route git-commits
#: ``adr`` exports into the publish repository, and a probe must not grow
#: the shared git history it would then have to rewrite to erase.
PROBE_KIND = "action-item"

#: The stage whose settlement gates minting. While extraction is still
#: running, a moment with no ``extracted`` rows now may hold one by the time
#: the approval lands — and the approval would then consume shared state the
#: run does not own.
EXTRACT_STAGE = "extract"

_SETTLED = frozenset({"done", "skipped"})

_INSERT_PROBE = (
    "INSERT INTO artifact (moment_id, meeting_id, kind, title, body)"
    " VALUES (%s, %s, %s, %s, %s) RETURNING id"
)
_PROBE_STATE = "SELECT state FROM artifact WHERE id = %s"
_DELETE_PROBE = "DELETE FROM artifact WHERE id = %s"
_PROJECTION_LOCK_NAME = "meetingminer-projections"
_PROJECTION_LOCK_TIMEOUT_ENV = "MM_PROJECTION_LOCK_TIMEOUT_SECONDS"

#: The graph erasure. ``DETACH DELETE`` is scoped to
#: the one node carrying the minted UUID — label-agnostic like every other
#: graph statement in the harness, so whatever label the projection chose
#: cannot shelter a leftover.
_ERASE_NODE = "MATCH (a {id: $id}) DETACH DELETE a"


def probe_title(run_id: str) -> str:
    """The run-id-prefixed marker every minted row carries."""
    return f"{PROBE_TITLE_PREFIX}{run_id}"


def probe_body(run_id: str, manifest_id: str) -> str:
    """A body that explains the row to whoever finds it stranded."""
    return (
        f"Publish-gate probe for eval run {run_id}, measured beside manifest"
        f" {manifest_id}. This row is minted by the eval harness to exercise"
        " the approve→project gate and is erased by the same run; if you are"
        " reading it in the corpus, the run that minted it died before its"
        " cleanup — delete the row, its search document, its graph node and"
        " its export file by this artifact's id."
    )


def eligible_moments(
    moments: Sequence[MomentRow], artifacts: Sequence[Any]
) -> tuple[MomentRow, ...]:
    """Moments with no subject-owned ``extracted`` row.

    Approving a moment advances *every* ``extracted`` artifact under it, so
    a moment carrying subject ``extracted`` state may never be chosen — the
    run would consume shared rows it does not own. ``approved`` and
    ``published`` rows do not block: the route cannot advance them. A marked
    sibling probe is deferred to the per-moment lock: a live owner cleans it
    before the locked refresh; a row still present then is stranded and gets
    a named refusal, never approval or deletion by this run.
    """
    consumed = {
        str(artifact.moment_id)
        for artifact in artifacts
        if artifact.state == checks.EXTRACTED_STATE
        and not is_probe_artifact(artifact)
    }
    return tuple(moment for moment in moments if str(moment.id) not in consumed)


def is_probe_artifact(artifact: Any) -> bool:
    """Whether a corpus row carries the eval probe ownership marker."""
    return str(getattr(artifact, "title", "") or "").startswith(
        PROBE_TITLE_PREFIX
    )


def choose_order(run_id: str, moments: Sequence[MomentRow]) -> tuple[MomentRow, ...]:
    """The candidate order, deterministic per run and spread across runs.

    Keyed BLAKE2b — the run id is the key, the moment id the message —
    never the builtin ``hash``, which is salted per process: the same run
    always walks the same order, and two concurrent runs walk different
    orders, so they rarely contend for the same moment. Contention is still
    correct — the 409 race path resolves it — this only makes it rare. (A
    plain ``sha256(run:moment)`` concatenation was tried first and two real
    labels rank-collided; the keyed construction is what the spread test
    pins.) BLAKE2b keys cap at 64 bytes; a run id is at most 96 characters
    (``run.safe_name``), and truncating the key only weakens the spread,
    never the determinism.
    """
    def key(moment: MomentRow) -> str:
        return hashlib.blake2b(
            str(moment.id).encode(), key=run_id.encode()[:64]
        ).hexdigest()

    return tuple(sorted(moments, key=key))


def split_owned(
    returned: Sequence[Mapping[str, Any]], probe_id: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition the approve response's ``published`` rows by ownership.

    The route returns every artifact under the moment by design, so rows
    the run did not mint are expected company — set aside for the report,
    never a divergence. Only ``published`` rows count on either side; a
    minted row the approval left unpublished is a finding the pure
    algorithm renders, not an owned id.
    """
    published = [
        str(row["id"])
        for row in returned
        if row.get("state") == checks.PUBLISHED_STATE
    ]
    owned = tuple(row_id for row_id in published if row_id == probe_id)
    foreign = tuple(row_id for row_id in published if row_id != probe_id)
    return owned, foreign


@contextmanager
def _projection_writer_lock(
    config: Any, connection: Any, holder: str
) -> Iterator[None]:
    """Join production projection writers' file/advisory exclusion domain."""
    stores_config = config.settings.stores
    key = hashlib.sha256(
        f"{stores_config.neo4j.uri}|{stores_config.meilisearch.url}".encode()
    ).hexdigest()[:16]
    lock_path = (
        Path(tempfile.gettempdir()) / f"meetingminer-projections-{key}.lock"
    )
    raw_timeout = os.environ.get(_PROJECTION_LOCK_TIMEOUT_ENV, "300")
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise RuntimeError(
            f"{_PROJECTION_LOCK_TIMEOUT_ENV} must be a positive finite number"
        ) from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeError(
            f"{_PROJECTION_LOCK_TIMEOUT_ENV} must be a positive finite number"
        )

    handle = open(lock_path, "a+")
    started = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                elapsed = time.monotonic() - started
                if elapsed >= timeout:
                    raise RuntimeError(
                        f"{holder} refused: projection store lock timed out"
                        f" after {elapsed:.2f}s waiting for {lock_path}"
                    ) from None
                time.sleep(min(0.05, timeout - elapsed))

        connection.execute(
            "SELECT pg_advisory_lock(hashtext(%s))", (_PROJECTION_LOCK_NAME,)
        )
        connection.commit()
        try:
            yield
        finally:
            connection.rollback()
            connection.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))",
                (_PROJECTION_LOCK_NAME,),
            )
            connection.commit()
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def cleanup_probe(
    artifact_id: str,
    *,
    search: Any,
    graph: Any,
    publish_root: Path | None,
    connection: Any,
    config: Any,
    expect_export: bool = False,
    cleanup_lock: Callable[[Any, Any, str], Any] | None = None,
) -> CleanupReport:
    """Erase the probe from all four places it landed, verifying each.

    One leftover never abandons the rest: every target is attempted and
    verified independently, and every failure becomes a named problem
    carrying the exact id and the manual remedy. Only ever called with the
    id this run minted — the sanction this module exists to keep narrow.
    """
    lock = cleanup_lock or _projection_writer_lock
    try:
        with lock(config, connection, f"eval gate-probe cleanup {artifact_id}"):
            return _cleanup_probe_locked(
                artifact_id,
                search=search,
                graph=graph,
                publish_root=publish_root,
                connection=connection,
                expect_export=expect_export,
            )
    except Exception as exc:  # noqa: BLE001 — the leftover must stay loud
        return CleanupReport(
            search_document_removed=False,
            graph_node_removed=False,
            export_file_removed=False,
            postgres_row_removed=False,
            problems=(
                f"probe cleanup for artifact {artifact_id} could not enter"
                f" the projection writer lock ({type(exc).__name__}: {exc})"
                " — no erasure was attempted because verified absence would"
                " not be stable against a concurrent projection writer",
            ),
        )


def _cleanup_probe_locked(
    artifact_id: str,
    *,
    search: Any,
    graph: Any,
    publish_root: Path | None,
    connection: Any,
    expect_export: bool,
) -> CleanupReport:
    """Erase and verify while :func:`cleanup_probe` holds writer exclusion."""
    problems: list[str] = []

    search_removed = False
    try:
        task = search.index(ARTIFACTS_INDEX).delete_document(artifact_id)
        search.wait_for_task(task.task_uid)
    except Exception as exc:  # noqa: BLE001 — a leftover must be named, not raised
        problems.append(
            f"Meilisearch refused the erasure of artifact {artifact_id}"
            f" ({type(exc).__name__}: {exc}) — delete it from the artifacts"
            " index by this id"
        )
    else:
        try:
            presence = stores.artifact_in_search(search, artifact_id)
            search_removed = not presence.present
            if presence.present:
                problems.append(
                    f"Meilisearch still holds artifact {artifact_id} after"
                    " the erasure — delete it from the artifacts index by"
                    " this id"
                )
        except StoreAssertError as exc:
            problems.append(
                f"Meilisearch could not verify the erasure of artifact"
                f" {artifact_id} ({exc})"
            )

    graph_removed = False
    try:
        with graph.session() as session:
            session.run(_ERASE_NODE, id=artifact_id).consume()
        presence = stores.artifact_in_graph(graph, artifact_id)
        if presence.present:
            problems.append(
                f"Neo4j still holds a node with id {artifact_id} after the"
                " erasure — DETACH DELETE it by this id"
            )
        else:
            graph_removed = True
    except Exception as exc:  # noqa: BLE001 — a leftover must be named, not raised
        problems.append(
            f"Neo4j could not erase or verify the node for artifact"
            f" {artifact_id} ({type(exc).__name__}: {exc})"
        )

    export_removed = False
    if publish_root is None:
        problems.append(
            "MM_PUBLISH_ROOT is not set in .env, so the probe's export file"
            f" ({PROBE_KIND}/{artifact_id}.md) cannot be located for removal"
            " — the approve route needed it to answer, so this run's"
            " configuration and the api's have diverged"
        )
    else:
        export_path = Path(publish_root) / PROBE_KIND / f"{artifact_id}.md"
        # The export verdict scopes to its own problem line — an earlier
        # target's failure must never swallow this leftover's name.
        export_problem: str | None = None
        try:
            existed = export_path.exists()
            export_path.unlink(missing_ok=True)
            export_removed = not export_path.exists()
            if not export_removed:
                export_problem = (
                    f"the probe's export file {export_path} survived its"
                    " removal"
                )
            elif expect_export and not existed:
                # The approval published the probe, so the route exported a
                # file — and none stood at the path this run's configuration
                # names. The likeliest cause is a publish root diverging
                # between this run's `.env` resolution and the api's.
                export_removed = False
                export_problem = (
                    f"no export file was found at {export_path} although the"
                    " approval published the probe — the api may write under"
                    " a different publish root; find and remove the export"
                    f" for artifact {artifact_id}"
                )
        except OSError as exc:
            export_problem = (
                f"the probe's export file {export_path} could not be removed:"
                f" {exc}"
            )
        if export_problem is not None:
            problems.append(export_problem)

    postgres_removed = False
    try:
        connection.execute(_DELETE_PROBE, (artifact_id,))
        postgres_removed = connection.execute(
            _PROBE_STATE, (artifact_id,)
        ).fetchone() is None
        if not postgres_removed:
            problems.append(
                f"Postgres still holds artifact {artifact_id} after the"
                " erasure — DELETE FROM artifact WHERE id = this id"
            )
    except Exception as exc:  # noqa: BLE001 — a leftover must be named, not raised
        problems.append(
            f"Postgres could not erase the probe row {artifact_id}"
            f" ({type(exc).__name__}: {exc})"
        )

    return CleanupReport(
        search_document_removed=search_removed,
        graph_node_removed=graph_removed,
        export_file_removed=export_removed,
        postgres_row_removed=postgres_removed,
        problems=tuple(problems),
    )


def _writable_conninfo(config: Any) -> str:
    """A normal (non-read-only) connection string for the probe's own rows.

    Deliberately not ``evals.harness.corpus.read_only_conninfo``: that
    connection cannot write, by design (AD-16), and this file is test-layer
    setup — the same convention ``checks/test_corpus_artifacts.py``
    established for its seeded evidence bundle.
    """
    pg = config.settings.stores.postgres
    return psycopg.conninfo.make_conninfo(
        host=pg.host,
        port=pg.port,
        dbname=pg.database,
        user=pg.user,
        password=config.secrets.postgres_password,
    )


def _membership(
    search: Any,
    graph: Any,
    artifact_id: str,
    recorded: dict[str, StorePresence] | None = None,
) -> dict[str, StorePresence]:
    """Accumulate each completed store read before attempting the next."""
    observed = recorded if recorded is not None else {}
    observed[checks.SEARCH_STORE] = stores.artifact_in_search(search, artifact_id)
    observed[checks.GRAPH_STORE] = stores.artifact_in_graph(graph, artifact_id)
    return observed


def _projection_wait_seconds() -> float:
    """Bound a winning request by the same wait budget its writer receives."""
    raw = os.environ.get(_PROJECTION_LOCK_TIMEOUT_ENV, "300")
    try:
        timeout = float(raw)
    except ValueError:
        raise RuntimeError(
            f"{_PROJECTION_LOCK_TIMEOUT_ENV} must be a positive finite number"
        ) from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeError(
            f"{_PROJECTION_LOCK_TIMEOUT_ENV} must be a positive finite number"
        )
    return timeout + 10.0


@contextmanager
def _moment_probe_lock(config: Any, moment_id: str, holder: str) -> Iterator[None]:
    """Serialize eval-owned probe lifecycles that share one subject moment."""
    pg = config.settings.stores.postgres
    key = hashlib.sha256(
        f"{pg.host}|{pg.port}|{pg.database}|{moment_id}".encode()
    ).hexdigest()[:16]
    lock_path = Path(tempfile.gettempdir()) / f"meetingminer-eval-probe-{key}.lock"
    timeout = _projection_wait_seconds()
    handle = open(lock_path, "a+")
    started = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                elapsed = time.monotonic() - started
                if elapsed >= timeout:
                    raise RuntimeError(
                        f"eval gate-probe {holder} timed out after"
                        f" {elapsed:.2f}s waiting for moment {moment_id}"
                    ) from None
                time.sleep(min(0.05, timeout - elapsed))
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _wait_for_winning_projection(
    search: Any, graph: Any, artifact_id: str
) -> dict[str, StorePresence]:
    """Wait until a raced approval's post-commit projection reaches both stores."""
    deadline = time.monotonic() + _projection_wait_seconds()
    while True:
        observed = _membership(search, graph, artifact_id)
        if all(presence.present for presence in observed.values()):
            return observed
        if time.monotonic() >= deadline:
            return observed
        time.sleep(0.05)


def run_gate_probe(
    *,
    run_id: str,
    manifest_id: str,
    meeting_id: str,
    base_url: str,
    config: Any,
    corpus: Any,
    search: Any,
    graph: Any,
    transport: httpx.BaseTransport | None = None,
    connect: Callable[..., Any] | None = None,
    moment_lock: Callable[[Any, str, str], Any] | None = None,
) -> GateProbe:
    """One probe, start to erased end, every refusal named.

    Eligibility first, from reads alone — nothing is minted until a safe
    moment is chosen. Once minted, the erasure is unconditional: an
    interruption mid-sequence names itself on the probe and still cleans
    up, so the one way a probe row outlives its run is the process dying
    outright (the body text tells the finder what to do).
    """
    stage = corpus.stage_status(meeting_id, EXTRACT_STAGE)
    if stage not in _SETTLED:
        return GateProbe(
            problem=(
                f"meeting {meeting_id}'s {EXTRACT_STAGE} stage is {stage!r},"
                " not settled (done/skipped) — a moment safe to approve now"
                " may hold an extracted row by the time the approval lands,"
                " so nothing was minted"
            )
        )

    moments = corpus.moments_for(meeting_id)
    if not moments:
        return GateProbe(
            problem=(
                f"meeting {meeting_id} has no moments, so the probe has no"
                " projected moment to cite and nothing was minted"
            )
        )

    artifacts = corpus.artifacts_for(meeting_id)
    eligible = eligible_moments(moments, artifacts)
    if not eligible:
        # A stranded sibling probe (a run killed before its cleanup) is the
        # one 'extracted' row this refusal can diagnose outright: its title
        # carries the marker, so the remedy is erasure, not approval.
        stranded = sorted(
            str(artifact.id)
            for artifact in artifacts
            if artifact.state == checks.EXTRACTED_STATE
            and str(getattr(artifact, "title", "") or "").startswith(
                PROBE_TITLE_PREFIX
            )
        )
        hint = ""
        if stranded:
            hint = (
                f" Rows {', '.join(stranded)} carry the"
                f" {PROBE_TITLE_PREFIX!r} marker: they are another run's"
                " stranded probes — that run died before its cleanup; delete"
                " each row, its search document, its graph node and its"
                " export file by the row's id, then rerun."
            )
        return GateProbe(
            problem=(
                f"every moment of meeting {meeting_id} holds an unconsumed"
                " 'extracted' artifact — approving any of them would consume"
                " shared state the run does not own, so nothing was minted;"
                " approve them in the app (or rerun after they are settled)."
                + hint
            )
        )

    chosen: MomentRow | None = None
    for candidate in choose_order(run_id, eligible):
        try:
            if stores.moment_in_graph(graph, str(candidate.id)):
                chosen = candidate
                break
        except StoreAssertError as exc:
            return GateProbe(
                problem=(
                    f"the graph could not answer whether moment"
                    f" {candidate.id} is projected: {exc} — nothing was"
                    " minted"
                )
            )
    if chosen is None:
        return GateProbe(
            problem=(
                f"none of meeting {meeting_id}'s eligible moments has a"
                " Moment node in the graph — the meeting was never projected,"
                " and the approve route's graph write would roll back; run"
                f" `rebuild --meeting {meeting_id}` first"
            )
        )

    moment_id = str(chosen.id)
    lock = moment_lock or _moment_probe_lock
    with lock(config, moment_id, run_id):
        refreshed = corpus.artifacts_for(meeting_id)
        blockers = tuple(
            artifact
            for artifact in refreshed
            if str(artifact.moment_id) == moment_id
            and artifact.state == checks.EXTRACTED_STATE
        )
        if blockers:
            blocker_ids = ", ".join(sorted(str(row.id) for row in blockers))
            if all(is_probe_artifact(row) for row in blockers):
                return GateProbe(
                    problem=(
                        f"moment {moment_id} holds stranded probe row(s)"
                        f" {blocker_ids} after acquiring probe ownership —"
                        " no live sibling owns the moment lock, so delete each"
                        " row and its search document, graph node, and export"
                        " file by id; nothing was minted"
                    )
                )
            return GateProbe(
                problem=(
                    f"moment {moment_id} gained extracted row(s) {blocker_ids}"
                    " after acquiring probe ownership — approving it would"
                    " consume shared state, so nothing was minted"
                )
            )
        return _execute_probe(
            run_id=run_id,
            manifest_id=manifest_id,
            meeting_id=meeting_id,
            moment_id=moment_id,
            base_url=base_url,
            config=config,
            artifacts=refreshed,
            search=search,
            graph=graph,
            transport=transport,
            connect=connect,
        )


def _execute_probe(
    *,
    run_id: str,
    manifest_id: str,
    meeting_id: str,
    moment_id: str,
    base_url: str,
    config: Any,
    artifacts: Sequence[Any],
    search: Any,
    graph: Any,
    transport: httpx.BaseTransport | None,
    connect: Callable[..., Any] | None,
) -> GateProbe:
    """Mint through cleanup while the caller owns the selected moment."""
    opener = connect or psycopg.connect
    pre: dict[str, StorePresence] | None = None
    post: dict[str, StorePresence] | None = None
    approve = ApproveOutcome(attempted=False)
    foreign: tuple[str, ...] = ()
    consumed_foreign: tuple[str, ...] = ()
    problem: str | None = None

    conninfo = _writable_conninfo(config)
    with opener(conninfo, autocommit=False) as conn:
        row = conn.execute(
            _INSERT_PROBE,
            (
                moment_id,
                meeting_id,
                PROBE_KIND,
                probe_title(run_id),
                probe_body(run_id, manifest_id),
            ),
        ).fetchone()
        artifact_id = str(row[0])

        try:
            conn.commit()
        except Exception as exc:  # noqa: BLE001 — commit outcome is ambiguous
            try:
                conn.rollback()
            except Exception:
                pass
            with opener(conninfo, autocommit=True) as cleanup_conn:
                cleanup = cleanup_probe(
                    artifact_id,
                    search=search,
                    graph=graph,
                    publish_root=getattr(
                        config.secrets, "mm_publish_root", None
                    ),
                    connection=cleanup_conn,
                    config=config,
                )
            return GateProbe(
                artifact_id=artifact_id,
                moment_id=moment_id,
                cleanup=cleanup,
                problem=(
                    f"the probe mint returned id {artifact_id}, but its commit"
                    f" acknowledgement was lost ({type(exc).__name__}: {exc});"
                    " the known id was reconciled and erased through a fresh"
                    " connection, so the gate transition was not attempted"
                ),
            )
        conn.autocommit = True

        raced = False
        try:
            pre = {}
            _membership(search, graph, artifact_id, pre)
            if any(presence.present for presence in pre.values()):
                # A sibling run may have approved the shared moment between
                # this run's mint and its pre-read, publishing this probe
                # early — presence is then the gate working, not a
                # violation. Only the row's own state can tell the two
                # apart; a row still `extracted` proceeds and lets the
                # assembly fire the genuine violation.
                state_row = conn.execute(_PROBE_STATE, (artifact_id,)).fetchone()
                if (
                    state_row is not None
                    and state_row[0] == checks.PUBLISHED_STATE
                ):
                    raced = True
                    approve = ApproveOutcome(
                        attempted=True,
                        ok=True,
                        detail=(
                            "a concurrent run's approval published this"
                            " probe before the pre-read — the gate was"
                            " exercised through the public api; the race is"
                            " on the record"
                        ),
                        published_ids=(artifact_id,),
                    )
            if not raced:
                approve, foreign, consumed_foreign, raced = _approve(
                    base_url,
                    moment_id,
                    artifact_id,
                    {str(artifact.id): artifact.state for artifact in artifacts},
                    conn,
                    transport,
                )
            if raced:
                post = _wait_for_winning_projection(search, graph, artifact_id)
            else:
                post = {}
                _membership(search, graph, artifact_id, post)
        except StoreAssertError as exc:
            problem = (
                f"the probe was interrupted mid-sequence: {exc} — the gate"
                " transition went unmeasured; the minted row is still erased"
            )
        except Exception as exc:  # noqa: BLE001 — the cleanup verdict survives
            # Converted, never re-raised: an exception that escaped here
            # would discard the CleanupReport below, and a leftover on this
            # path would then be reported nowhere. The assembly renders this
            # problem as a blocking failure, so nothing is quieter for it.
            problem = (
                f"the probe was interrupted mid-sequence by"
                f" {type(exc).__name__}: {exc} — the gate transition went"
                " unmeasured; the minted row is still erased"
            )
        finally:
            cleanup = cleanup_probe(
                artifact_id,
                search=search,
                graph=graph,
                publish_root=getattr(config.secrets, "mm_publish_root", None),
                connection=conn,
                config=config,
                expect_export=(
                    approve.attempted
                    and approve.ok
                    and artifact_id in approve.published_ids
                ),
            )

    return GateProbe(
        artifact_id=artifact_id,
        moment_id=moment_id,
        pre=pre,
        post=post,
        approve=approve,
        cleanup=cleanup,
        problem=problem,
        raced=raced,
        foreign_ids=foreign,
        consumed_foreign_ids=consumed_foreign,
    )


def _approve(
    base_url: str,
    moment_id: str,
    artifact_id: str,
    initial_states: Mapping[str, str],
    conn: Any,
    transport: httpx.BaseTransport | None,
) -> tuple[ApproveOutcome, tuple[str, ...], tuple[str, ...], bool]:
    """The one mutation, with the concurrent-run race resolved by ownership.

    A 409 ``nothing-to-approve`` — matched on the structured problem slug
    the api sent, never a substring of reworded prose — re-reads the probe's
    own row: if a sibling run's approval published it, the gate was still
    exercised through the public api — ``ok`` with the race named — and only
    a row still unpublished makes the 409 a real refusal. The third return
    is that race verdict.
    """
    try:
        returned = retrieval.approve_moment(
            base_url,
            moment_id,
            timeout=_projection_wait_seconds(),
            transport=transport,
        )
    except ApproveError as exc:
        state_row = conn.execute(_PROBE_STATE, (artifact_id,)).fetchone()
        if state_row is not None and state_row[0] == checks.PUBLISHED_STATE:
            if getattr(exc, "slug", None) == "nothing-to-approve":
                detail = (
                    "a concurrent run's approval published this"
                    f" probe first ({exc}) — the gate was exercised"
                    " through the public api; the race is on the record"
                )
            else:
                detail = (
                    f"the approval response was ambiguous ({exc}), but the"
                    " owned row is published — reconcile as a completed"
                    " public-api mutation and wait for its projection"
                )
            return (
                ApproveOutcome(
                    attempted=True,
                    ok=True,
                    detail=detail,
                    published_ids=(artifact_id,),
                ),
                (),
                (),
                True,
            )
        return (
            ApproveOutcome(attempted=True, ok=False, detail=str(exc)),
            (),
            (),
            False,
        )
    owned, foreign = split_owned(returned, artifact_id)
    consumed = tuple(
        row_id
        for row_id in foreign
        if initial_states.get(row_id, checks.EXTRACTED_STATE)
        == checks.EXTRACTED_STATE
    )
    return (
        ApproveOutcome(attempted=True, ok=True, published_ids=owned),
        foreign,
        consumed,
        False,
    )
