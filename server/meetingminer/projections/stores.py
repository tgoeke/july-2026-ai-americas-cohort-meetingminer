"""Store connections, schema, and the rebuild lock — the only place a driver is opened.

AD-4 says exactly one writer. This module is what makes that assertable rather
than aspirational: ``neo4j`` and ``meilisearch`` are imported here (and in the
two projection modules beside it) and nowhere else in the server, which
``tests/test_projections_single_writer.py`` checks by import inspection.

Nothing here derives evidence or reads a pipeline table. It opens connections,
applies schema that both stores treat as idempotent, and holds the advisory
lock that keeps a ``rebuild`` from racing the worker.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import meilisearch
import neo4j
import psycopg
from meilisearch.errors import (
    MeilisearchApiError,
    MeilisearchCommunicationError,
    MeilisearchError,
    MeilisearchTimeoutError,
)
from psycopg import Connection

from meetingminer.config import AppConfig, SearchIndexConfig
from meetingminer.projections.documents import DOCUMENTS_INDEX
from meetingminer.projections.publish_gate import ARTIFACTS_INDEX

# --- index and label vocabulary ------------------------------------------

# Two indexes, not one. `moments` is citation-shaped: one document per moment,
# so a citation resolves to the Postgres-minted moment id (AD-6). `chunks` is
# retrieval-shaped, at the turn-packed granularity the bake-off actually
# measured (`retrieval-prior-art.md` §6-§7). They answer different queries.
MOMENTS_INDEX = "moments"
CHUNKS_INDEX = "chunks"
# The two *vectored* indexes. `ARTIFACTS_INDEX` (publish_gate.py, story 4.4)
# and `DOCUMENTS_INDEX` (documents.py, story 12.4) are deliberately not in
# this tuple: both are keyword-only — no embedder is ever declared on either —
# so the embedder-dimension asserts and the embed-only rebuild pass must not
# touch them. Schema creation and `drop_all` name them explicitly instead.
SEARCH_INDEXES = (MOMENTS_INDEX, CHUNKS_INDEX)

# Every index this module creates, in the order schema is declared. Named once
# so `drop_all` and the rebuild equivalence check cannot drift from it — a new
# index missing from the drop is a stale document surviving a full rebuild.
ALL_SEARCH_INDEXES = (*SEARCH_INDEXES, ARTIFACTS_INDEX, DOCUMENTS_INDEX)

# The one embedder Meilisearch knows about, and it is `userProvided`: the
# module computes every vector itself through the `Embedder` port, so no
# store-native auto-embedder is ever registered (AD-4). That is what keeps
# `rebuild` deterministic from Postgres + config.yaml alone — a store-side
# embedder would make the vectors a function of Meilisearch's configuration
# too.
#
# Meilisearch restricts document ids to [A-Za-z0-9_-], which a hyphenated UUID
# satisfies — so a Postgres UUID travels into an index verbatim (AD-6), with
# no encoding step that could make the store's id and the citation's differ.
EMBEDDER_NAME = "default"

# Labels whose nodes belong to exactly one meeting. A per-meeting re-index
# deletes these by `meetingId` and reinserts them; nothing else is deleted.
# `Artifact` (story 4.4) is meeting-scoped on purpose: the per-meeting
# delete-and-reinsert would sever its `CITES` edges anyway when it DETACH
# DELETEs the `Moment` nodes, so the pass re-creates artifacts from Postgres
# (`WHERE state = 'published'`) instead of trying to exempt them. Postgres
# stays authoritative; augment preserves moment ids, so `CITES` re-resolves.
# `Topic` (story 10.2) belongs here for the same reason `Artifact` does: a
# topic is a per-meeting row that anchors to that meeting's `Moment` nodes,
# and the per-meeting DETACH DELETE would sever its `MENTIONS` edges anyway.
# The pass re-creates it from Postgres, which is what keeps a re-projection
# idempotent rather than accumulating stale topics from a superseded extract.
MEETING_SCOPED_LABELS = ("Meeting", "Moment", "Screenshot", "Chunk", "Artifact", "Topic")
# Labels that are cross-meeting and are only ever upserted. Deleting a
# `Screen` in a per-meeting pass would break screen lineage for every other
# meeting that showed it (AD-5), and deleting a `Participant` would break the
# "I already explained this to Clarence" traversal across meetings. `Series`,
# `Project` and `Product` (story 2.5) follow the same rule: many meetings hang
# off one of them, so a per-meeting pass only ever upserts them.
# `Thread` (story 10.2) is the newest member and the clearest case: a thread
# exists precisely because it spans meetings, so deleting it in a per-meeting
# pass would destroy the only structure the thread traversal walks. Like
# `Screen`, it is MERGEd by id and lingers with no edges until `rebuild --all`
# if its last topic goes away.
CROSS_MEETING_LABELS = (
    "Screen", "Participant", "Series", "Project", "Product", "Thread",
)

# One Postgres advisory lock key, taken by `rebuild` for its whole run and by
# the worker for the duration of one meeting's projection. Both stores
# tolerate concurrent writers technically; a `rebuild` racing the worker
# produces a store that matches neither, so the contention is made a named
# error instead of silent divergence (`retrieval-prior-art.md` §3 rule 1).
PROJECTION_LOCK_NAME = "meetingminer-projections"


class ProjectionError(RuntimeError):
    """A projection could not be completed. Always names what and why."""


class StoreUnavailableError(ProjectionError):
    """Neo4j or Meilisearch could not be reached."""


class ProjectionLockedError(ProjectionError):
    """Another process holds the projection lock; the run is refused."""


class DimensionMismatchError(ProjectionError):
    """config.yaml's embedder width disagrees with what a store already holds.

    Refused *before* any write. Embedding width is baked into the index
    (`retrieval-prior-art.md` §3 rule 3), so writing anyway would produce
    silently garbage neighbours — the exact failure AD-8 makes the recorded
    model and dimension exist to catch.
    """


# --- connections ----------------------------------------------------------


@contextmanager
def neo4j_driver(config: AppConfig) -> Iterator[neo4j.Driver]:
    """Open the configured Neo4j driver, verified reachable, and close it after."""
    store = config.settings.stores.neo4j
    password = config.secrets.neo4j_password
    if not password:
        raise ProjectionError(
            "NEO4J_PASSWORD is not set — the graph projection cannot"
            " authenticate; set it in .env"
        )
    driver = neo4j.GraphDatabase.driver(
        store.uri, auth=(store.user, password), connection_timeout=10.0
    )
    try:
        try:
            driver.verify_connectivity()
        except Exception as exc:  # neo4j raises a wide family here
            raise StoreUnavailableError(
                f"Neo4j unreachable at {store.uri} ({type(exc).__name__}: {exc})"
                " — start it with 'make infra-up'"
            ) from exc
        yield driver
    finally:
        driver.close()


def meili_client(config: AppConfig) -> meilisearch.Client:
    """Build the Meilisearch client and verify the server answers."""
    store = config.settings.stores.meilisearch
    key = config.secrets.meili_master_key
    if not key:
        raise ProjectionError(
            "MEILI_MASTER_KEY is not set — the search projection cannot"
            " authenticate; set it in .env"
        )
    client = meilisearch.Client(store.url, key, timeout=30)
    try:
        client.health()
    except MeilisearchError as exc:
        raise StoreUnavailableError(
            f"Meilisearch unreachable at {store.url} ({exc})"
            " — start it with 'make infra-up'"
        ) from exc
    except Exception as exc:  # requests-level connection failures
        raise StoreUnavailableError(
            f"Meilisearch unreachable at {store.url}"
            f" ({type(exc).__name__}: {exc}) — start it with 'make infra-up'"
        ) from exc
    return client


# --- Meilisearch task plumbing -------------------------------------------

# Every write is asynchronous; a projection that returned before its task
# settled would report success over an index that had not been written, and
# `rebuild`'s equivalence check would race it.
_TASK_TIMEOUT_MS = 300_000


def _as_mapping(value: Any) -> dict[str, Any]:
    """Read a meilisearch-client model or a plain mapping the same way.

    The client returns typed models (``Embedders``, ``UserProvidedEmbedder``)
    for some settings and plain dicts for others, and which is which has moved
    between client releases. Normalizing here keeps that a detail of this
    module rather than something every caller has to guess at.
    """
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump())
    return dict(getattr(value, "__dict__", {}))


def await_task(
    client: meilisearch.Client, task: Any, *, tolerate: tuple[str, ...] = ()
) -> None:
    """Block until one Meilisearch task settles; raise on failure.

    A Meilisearch write is enqueued, not applied — the client returns as soon
    as the task is accepted, and the *task* is what fails. So an error like
    "index already exists" arrives here rather than as an exception from the
    call, and ``tolerate`` names the error codes that mean "the state we
    wanted is already the state that exists".
    """
    uid = getattr(task, "task_uid", None)
    if uid is None:  # an already-materialized Task
        uid = getattr(task, "uid", None)
    if uid is None:
        # Never "assume it worked". If a client upgrade renames the field, a
        # silent return turns every write in this module into fire-and-forget
        # and the store-backed suite races itself green against an index that
        # was never written — the exact failure this function exists to
        # prevent.
        raise ProjectionError(
            f"Meilisearch returned a task object with no task id: {task!r}"
            " — the meilisearch client's task shape changed and this module's"
            " writes can no longer be confirmed"
        )
    settled = client.wait_for_task(
        uid, timeout_in_ms=_TASK_TIMEOUT_MS, interval_in_ms=50
    )
    status = getattr(settled, "status", None)
    if status == "succeeded":
        return
    error = _as_mapping(getattr(settled, "error", None) or {})
    if error.get("code") in tolerate:
        return
    raise ProjectionError(f"Meilisearch task {uid} finished {status!r}: {error}")


# --- schema ---------------------------------------------------------------

# Neo4j has no migration tool here on purpose (AD-4): both stores are
# disposable projections, so their schema is re-declared idempotently on every
# run rather than versioned. A uniqueness constraint per label is what makes
# `MERGE ... ON CREATE` cheap and makes a duplicated UUID a database error
# rather than a silently doubled node.
_NODE_KEY_CONSTRAINTS = (
    ("Meeting", "id"),
    ("Moment", "id"),
    ("Screenshot", "id"),
    ("Chunk", "id"),
    ("Screen", "id"),
    ("Participant", "id"),
    # Story 2.5: same unique-id rule for the human-declared structure labels —
    # cross-meeting, MERGEd by id, so a duplicated UUID is a database error.
    ("Series", "id"),
    ("Project", "id"),
    ("Product", "id"),
    ("Artifact", "id"),
    # Story 10.2: `Topic` and `Thread` carry Postgres-minted UUIDs like every
    # other node (AD-6). `Thread`'s constraint is what makes the cross-meeting
    # MERGE that every meeting's pass performs converge on one node.
    ("Topic", "id"),
    ("Thread", "id"),
)

# Every meeting-scoped label carries `meetingId`, which is what makes
# re-projecting one occurrence a delete-and-reinsert scoped to that meeting
# rather than a full rebuild (`retrieval-prior-art.md` §3 rule 5). Indexed
# because that delete runs on every re-projection, including story 1.12's.
_MEETING_ID_INDEXES = MEETING_SCOPED_LABELS


def ensure_graph_schema(driver: neo4j.Driver) -> None:
    """Create the uniqueness constraints and meetingId indexes, idempotently."""
    with driver.session() as session:
        for label, key in _NODE_KEY_CONSTRAINTS:
            session.run(
                f"CREATE CONSTRAINT {label.lower()}_{key}_unique IF NOT EXISTS"
                f" FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
            ).consume()
        for label in _MEETING_ID_INDEXES:
            session.run(
                f"CREATE INDEX {label.lower()}_meeting_id IF NOT EXISTS"
                f" FOR (n:{label}) ON (n.meetingId)"
            ).consume()
        # Screens are matched by their cross-meeting identity key on upsert.
        session.run(
            "CREATE INDEX screen_identity_key IF NOT EXISTS"
            " FOR (n:Screen) ON (n.identityKey)"
        ).consume()


def ensure_artifact_graph_schema(driver: neo4j.Driver) -> None:
    """Declare only the graph schema the publish gesture can need.

    Artifact-only projection must not mutate unrelated projection surfaces.
    Keeping this preflight separate also makes the absence of a vector/schema
    dependency explicit at the locked entrypoint.
    """
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT artifact_id_unique IF NOT EXISTS"
            " FOR (n:Artifact) REQUIRE n.id IS UNIQUE"
        ).consume()
        session.run(
            "CREATE INDEX artifact_meeting_id IF NOT EXISTS"
            " FOR (n:Artifact) ON (n.meetingId)"
        ).consume()


def _index_settings(index_config: SearchIndexConfig) -> dict[str, Any]:
    """The settings body for one index, straight from config.yaml.

    ``searchableAttributes`` is ordered and the order *is* the field boost:
    Meilisearch 1.53 has no per-field weight, so the ``attribute`` ranking rule
    scores an earlier attribute higher. Nothing is defaulted here — if it is
    not in config.yaml it is not a deliberate choice (SPEC Constraints).
    """
    return {
        "searchableAttributes": list(index_config.searchable_attributes),
        "filterableAttributes": list(index_config.filterable_attributes),
        "sortableAttributes": list(index_config.sortable_attributes),
        "rankingRules": list(index_config.ranking_rules),
    }


def declared_embedders(
    client: meilisearch.Client, index_uid: str
) -> dict[str, dict[str, Any]]:
    """Every embedder an index declares, as plain dicts.

    Used to assert that the *only* embedder is our ``userProvided`` one: a
    store-native auto-embedder appearing here would mean vectors were computed
    somewhere other than the `Embedder` port, and `rebuild` would stop being
    deterministic from Postgres + config alone (AD-4).
    """
    try:
        raw = client.index(index_uid).get_embedders()
    except MeilisearchApiError as exc:
        if getattr(exc, "code", None) == "index_not_found":
            return {}
        raise ProjectionError(
            f"Meilisearch refused embedder inspection for index {index_uid!r}: {exc}"
        ) from exc
    except (MeilisearchCommunicationError, MeilisearchTimeoutError) as exc:
        raise StoreUnavailableError(
            f"Meilisearch became unreachable during embedder inspection for"
            f" index {index_uid!r} ({type(exc).__name__}: {exc})"
        ) from exc
    except MeilisearchError as exc:  # pragma: no cover - client-shape change
        raise ProjectionError(
            f"Meilisearch failed embedder inspection for index {index_uid!r}"
            f" ({type(exc).__name__}: {exc})"
        ) from exc
    if raw is None:
        return {}
    mapping = _as_mapping(raw)
    # `Embedders` wraps the real mapping in an `embedders` attribute.
    inner = mapping.get("embedders")
    if isinstance(inner, dict):
        mapping = inner
    return {name: _as_mapping(entry) for name, entry in mapping.items()}


def stored_dimension(client: meilisearch.Client, index_uid: str) -> int | None:
    """The vector width an index already holds, or ``None`` if it holds none."""
    entry = declared_embedders(client, index_uid).get(EMBEDDER_NAME)
    if not entry:
        return None
    dimensions = entry.get("dimensions")
    return int(dimensions) if dimensions else None


def assert_dimension_matches(client: meilisearch.Client, dimension: int) -> None:
    """Refuse, by name, before any write, when a store holds a different width."""
    for index_uid in SEARCH_INDEXES:
        held = stored_dimension(client, index_uid)
        if held is not None and held != dimension:
            raise DimensionMismatchError(
                f"Meilisearch index {index_uid!r} already holds"
                f" {held}-dimension vectors but config.yaml declares"
                f" embedder.dimension {dimension} — refusing to write"
                " mismatched-width vectors. Run 'rebuild --all' to re-index"
                " the corpus under the new embedder (AD-8)."
            )


def assert_recorded_dimension_matches(conn: Connection, config: AppConfig) -> None:
    """Refuse when Postgres records a different width than config declares.

    The Meilisearch check above cannot see a corpus whose store was wiped but
    whose `meeting_projection` rows survive; this one can. Together they make
    a width change a named refusal from either direction.
    """
    embedder = config.settings.embedder
    row = conn.execute(
        "SELECT embedder_model, embedder_dimension FROM meeting_projection"
        " WHERE embedder_dimension <> %s LIMIT 1",
        (embedder.dimension,),
    ).fetchone()
    if row is not None:
        raise DimensionMismatchError(
            f"meeting_projection records {row[0]!r} at {row[1]} dimensions but"
            f" config.yaml declares embedder.model {embedder.model!r} at"
            f" {embedder.dimension} — an embedder swap forces a full rebuild"
            " (AD-8). Run 'rebuild --all'."
        )


def ensure_vector_search_schema(
    client: meilisearch.Client, config: AppConfig, *, dimension: int
) -> None:
    """Create the two vector indexes and apply their settings, idempotently.

    The dimension check runs first, so a width change is refused before this
    function creates or touches anything.
    """
    assert_dimension_matches(client, dimension)
    search = config.settings.projections.search
    synonyms = {key: list(values) for key, values in search.synonyms.items()}
    for index_uid, index_config in (
        (MOMENTS_INDEX, search.moments),
        (CHUNKS_INDEX, search.chunks),
    ):
        # Already existing is the state creation wanted, so it is tolerated
        # rather than raised: `ensure_search_schema` runs on every projection.
        await_task(
            client,
            client.create_index(index_uid, {"primaryKey": "id"}),
            tolerate=("index_already_exists",),
        )
        index = client.index(index_uid)
        settings = _index_settings(index_config)
        settings["synonyms"] = synonyms
        await_task(client, index.update_settings(settings))
        # `userProvided` is not an auto-embedder: it declares the width of
        # vectors this module computes itself and hands over. No `source:
        # ollama|openAi|huggingFace|rest` embedder is ever registered (AD-4).
        await_task(
            client,
            index.update_embedders(
                {EMBEDDER_NAME: {"source": "userProvided", "dimensions": dimension}}
            ),
        )


def ensure_artifact_search_schema(
    client: meilisearch.Client, config: AppConfig
) -> None:
    """Create/configure only the keyword-only artifacts index.

    This intentionally performs no vector-width check and names neither the
    moments nor chunks index.  A stale embedder on an existing artifacts
    index is actively removed rather than merely omitted from new settings.
    """
    search = config.settings.projections.search
    synonyms = {key: list(values) for key, values in search.synonyms.items()}
    # Inspect before any task is submitted. An authorization/transport failure
    # here is not evidence that no embedder exists and must leave the index
    # wholly untouched rather than applying half a schema update.
    existing_embedders = declared_embedders(client, ARTIFACTS_INDEX)
    await_task(
        client,
        client.create_index(ARTIFACTS_INDEX, {"primaryKey": "id"}),
        tolerate=("index_already_exists",),
    )
    artifacts_index = client.index(ARTIFACTS_INDEX)
    artifact_settings = _index_settings(search.artifacts)
    artifact_settings["synonyms"] = synonyms
    await_task(client, artifacts_index.update_settings(artifact_settings))
    if existing_embedders:
        await_task(client, artifacts_index.reset_embedders())


def ensure_document_search_schema(
    client: meilisearch.Client, config: AppConfig
) -> None:
    """Create/configure only the keyword-only extraction-documents index.

    The same shape as :func:`ensure_artifact_search_schema` and for the same
    reason: no vector-width check, no embedder, and a stale embedder on an
    existing index is actively removed rather than merely omitted from the new
    settings. Keyword-only is deliberate — a document is never cited and never
    ranked against a moment, so paying an embedder pass for it would make an
    Ollama outage able to withhold the very documents this index exists to keep
    reachable (AD-4's exception; `retrieval-prior-art.md` 3 rule 4).
    """
    search = config.settings.projections.search
    synonyms = {key: list(values) for key, values in search.synonyms.items()}
    # Inspected before any task is submitted, like the artifacts index: a
    # transport failure here is not evidence that no embedder exists.
    existing_embedders = declared_embedders(client, DOCUMENTS_INDEX)
    await_task(
        client,
        client.create_index(DOCUMENTS_INDEX, {"primaryKey": "id"}),
        tolerate=("index_already_exists",),
    )
    documents_index = client.index(DOCUMENTS_INDEX)
    document_settings = _index_settings(search.documents)
    document_settings["synonyms"] = synonyms
    await_task(client, documents_index.update_settings(document_settings))
    if existing_embedders:
        await_task(client, documents_index.reset_embedders())


def ensure_search_schema(
    client: meilisearch.Client, config: AppConfig, *, dimension: int
) -> None:
    """Declare all search schemas for structural/full projection."""
    ensure_vector_search_schema(client, config, dimension=dimension)
    ensure_artifact_search_schema(client, config)
    ensure_document_search_schema(client, config)


def drop_all(driver: neo4j.Driver, client: meilisearch.Client) -> None:
    """Wipe both stores so a full `rebuild` leaves no orphan behind.

    Legitimate only from `rebuild --all`: dropping the indexes is how a
    renamed attribute, a removed edge, or a stale document from an earlier
    schema stops surviving. Per-meeting projection never calls this.
    """
    with driver.session() as session:
        # Batched so a large graph does not build one transaction the size of
        # the corpus. The deletion count comes from the summary counters: a
        # deleted node cannot be returned from the query that deleted it.
        while True:
            summary = session.run(
                "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n"
            ).consume()
            if summary.counters.nodes_deleted == 0:
                break
    for index_uid in ALL_SEARCH_INDEXES:
        # Absent is the state the drop wanted.
        await_task(
            client, client.delete_index(index_uid), tolerate=("index_not_found",)
        )


# --- the rebuild lock -----------------------------------------------------


def _lock_holder(conn: Connection) -> str:
    """Describe whoever holds the projection lock, for the refusal message.

    A single-argument ``pg_advisory_lock(bigint)`` is recorded in ``pg_locks``
    split across ``classid`` (the high 32 bits) and ``objid`` (the low 32),
    with ``objsubid = 1``. The key itself is whatever ``hashtext()`` returns
    for our lock name, so it is read back from the server rather than guessed.
    """
    key = conn.execute(
        "SELECT hashtext(%s)::bigint", (PROJECTION_LOCK_NAME,)
    ).fetchone()[0]
    classid = (key >> 32) & 0xFFFFFFFF
    objid = key & 0xFFFFFFFF
    row = conn.execute(
        "SELECT a.pid, coalesce(a.application_name, ''), coalesce(a.state, '')"
        " FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
        " WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 1"
        "   AND l.classid = %s AND l.objid = %s"
        " LIMIT 1",
        (classid, objid),
    ).fetchone()
    if row is None:
        return "another process"
    pid, application, state = row
    label = application or "unnamed process"
    return f"pid {pid} ({label}, {state or 'unknown state'})"


@contextmanager
def projection_lock(conn: Connection, *, holder: str) -> Iterator[None]:
    """Hold the projection advisory lock, or refuse by name.

    Session-scoped rather than transaction-scoped: `rebuild` commits many
    times inside one run, and a transaction lock would be released by the
    first of them.
    """
    acquired = conn.execute(
        "SELECT pg_try_advisory_lock(hashtext(%s))", (PROJECTION_LOCK_NAME,)
    ).fetchone()[0]
    conn.commit()
    if not acquired:
        raise ProjectionLockedError(
            f"{holder} refused: the projection lock is held by"
            f" {_lock_holder(conn)} — wait for it to finish, or stop the"
            " worker, and retry"
        )
    try:
        yield
    finally:
        try:
            # Roll back first, unconditionally. A session-level advisory lock
            # survives rollback, but a *failed* statement leaves the
            # transaction aborted and every later statement — including the
            # unlock — is refused. Without this, one failed projection would
            # leak the lock for the lifetime of a pooled worker connection and
            # every later `rebuild` would be refused by a holder that is not
            # doing anything.
            conn.rollback()
            conn.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))", (PROJECTION_LOCK_NAME,)
            )
            conn.commit()
        except psycopg.Error:
            pass  # a broken session releases the lock on disconnect anyway
