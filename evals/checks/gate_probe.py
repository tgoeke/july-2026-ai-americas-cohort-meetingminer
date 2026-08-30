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
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
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

#: The graph erasure and its verification. ``DETACH DELETE`` is scoped to
#: the one node carrying the minted UUID — label-agnostic like every other
#: graph statement in the harness, so whatever label the projection chose
#: cannot shelter a leftover.
_ERASE_NODE = "MATCH (a {id: $id}) DETACH DELETE a"
_NODE_PRESENT = "MATCH (a {id: $id}) RETURN a.id AS id"


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
    """The moments a probe may ride: none holding an ``extracted`` row.

    Approving a moment advances *every* ``extracted`` artifact under it, so
    a moment carrying subject ``extracted`` state may never be chosen — the
    run would consume shared rows it does not own. ``approved`` and
    ``published`` rows do not block: the route cannot advance them.
    """
    consumed = {
        str(artifact.moment_id)
        for artifact in artifacts
        if artifact.state == checks.EXTRACTED_STATE
    }
    return tuple(moment for moment in moments if str(moment.id) not in consumed)


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


def _search_absent(search: Any, artifact_id: str) -> tuple[bool, str | None]:
    """Whether the erased document reads back absent, or the leftover line.

    Tolerates an error object with no ``code`` attribute: absence is the
    expected answer, and only an error *naming* a non-absent condition is a
    leftover. A document that reads back is the unambiguous leftover.
    """
    try:
        search.index(ARTIFACTS_INDEX).get_document(artifact_id)
    except MeilisearchApiError as exc:
        code = getattr(exc, "code", None)
        status = getattr(exc, "status_code", None)
        if code in (None, "document_not_found", "index_not_found") or status == 404:
            return True, None
        return False, (
            f"Meilisearch answered the erasure verification for artifact"
            f" {artifact_id} with {code!r} — the document's absence is"
            " unproven; delete it from the artifacts index by this id"
        )
    except Exception as exc:  # noqa: BLE001 — a leftover must be named, not raised
        return False, (
            f"Meilisearch could not verify the erasure of artifact"
            f" {artifact_id} ({type(exc).__name__}: {exc})"
        )
    return False, (
        f"Meilisearch still holds artifact {artifact_id} after the erasure"
        " — delete it from the artifacts index by this id"
    )


def cleanup_probe(
    artifact_id: str,
    *,
    search: Any,
    graph: Any,
    publish_root: Path | None,
    connection: Any,
) -> CleanupReport:
    """Erase the probe from all four places it landed, verifying each.

    One leftover never abandons the rest: every target is attempted and
    verified independently, and every failure becomes a named problem
    carrying the exact id and the manual remedy. Only ever called with the
    id this run minted — the sanction this module exists to keep narrow.
    """
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
        search_removed, leftover = _search_absent(search, artifact_id)
        if leftover:
            problems.append(leftover)

    graph_removed = False
    try:
        with graph.session() as session:
            session.run(_ERASE_NODE, id=artifact_id).consume()
        with graph.session() as session:
            records = list(session.run(_NODE_PRESENT, id=artifact_id))
        if records:
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
        try:
            export_path.unlink(missing_ok=True)
            export_removed = not export_path.exists()
        except OSError as exc:
            problems.append(
                f"the probe's export file {export_path} could not be removed:"
                f" {exc}"
            )
        if not export_removed and not problems:
            problems.append(
                f"the probe's export file {export_path} survived its removal"
            )

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


def _membership(search: Any, graph: Any, artifact_id: str) -> dict[str, StorePresence]:
    return {
        checks.SEARCH_STORE: stores.artifact_in_search(search, artifact_id),
        checks.GRAPH_STORE: stores.artifact_in_graph(graph, artifact_id),
    }


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
        return GateProbe(
            problem=(
                f"every moment of meeting {meeting_id} holds an unconsumed"
                " 'extracted' artifact — approving any of them would consume"
                " shared state the run does not own, so nothing was minted;"
                " approve them in the app (or rerun after they are settled)"
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
    opener = connect or psycopg.connect
    pre: dict[str, StorePresence] | None = None
    post: dict[str, StorePresence] | None = None
    approve = ApproveOutcome(attempted=False)
    foreign: tuple[str, ...] = ()
    problem: str | None = None

    with opener(_writable_conninfo(config), autocommit=True) as conn:
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
            pre = _membership(search, graph, artifact_id)
            approve, foreign = _approve(
                base_url, moment_id, artifact_id, conn, transport
            )
            post = _membership(search, graph, artifact_id)
        except StoreAssertError as exc:
            problem = (
                f"the probe was interrupted mid-sequence: {exc} — the gate"
                " transition went unmeasured; the minted row is still erased"
            )
        finally:
            cleanup = cleanup_probe(
                artifact_id,
                search=search,
                graph=graph,
                publish_root=getattr(config.secrets, "mm_publish_root", None),
                connection=conn,
            )

    return GateProbe(
        artifact_id=artifact_id,
        moment_id=moment_id,
        pre=pre,
        post=post,
        approve=approve,
        cleanup=cleanup,
        problem=problem,
        foreign_ids=foreign,
    )


def _approve(
    base_url: str,
    moment_id: str,
    artifact_id: str,
    conn: Any,
    transport: httpx.BaseTransport | None,
) -> tuple[ApproveOutcome, tuple[str, ...]]:
    """The one mutation, with the concurrent-run race resolved by ownership.

    A 409 ``nothing-to-approve`` re-reads the probe's own row: if a sibling
    run's approval published it, the gate was still exercised through the
    public api — ``ok`` with the race named — and only a row still
    unpublished makes the 409 a real refusal.
    """
    try:
        returned = retrieval.approve_moment(base_url, moment_id, transport=transport)
    except ApproveError as exc:
        if "nothing-to-approve" in str(exc):
            state_row = conn.execute(_PROBE_STATE, (artifact_id,)).fetchone()
            if state_row is not None and state_row[0] == checks.PUBLISHED_STATE:
                return (
                    ApproveOutcome(
                        attempted=True,
                        ok=True,
                        detail=(
                            "a concurrent run's approval published this"
                            f" probe first ({exc}) — the gate was exercised"
                            " through the public api; the race is on the"
                            " record"
                        ),
                        published_ids=(artifact_id,),
                    ),
                    (),
                )
        return ApproveOutcome(attempted=True, ok=False, detail=str(exc)), ()
    owned, foreign = split_owned(returned, artifact_id)
    return ApproveOutcome(attempted=True, ok=True, published_ids=owned), foreign
