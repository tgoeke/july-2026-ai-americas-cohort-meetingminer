"""Read-only membership reads against the two retrieval stores (check 2.11).

AD-4 makes an unpublished artifact visible *only* through Postgres api reads —
absence from the retrieval stores has no api surface, and ``/search``
deliberately excludes the ``artifacts`` index — so "assert it appears in
NEITHER store" can only be a direct store read. AD-16 sanctions exactly that:
"read-only store queries". This module is that sanction's whole footprint:

* it is the **only** module in the harness importing ``meilisearch`` or
  ``neo4j`` (``tests/test_harness_boundary.py`` pins both), and
* it is pinned to read-only usage — the boundary suite asserts this file
  never references a store write method, and the Neo4j session is opened with
  ``default_access_mode=READ`` so the driver itself refuses a write.

Connections are built from ``AppConfig`` settings + secrets (the one named
config allowance), duck-typed like ``corpus.read_only_conninfo`` so the
store-free suite never calls ``load_config``. Every way a store can fail to
answer raises :class:`StoreAssertError`, which the test layer records as a
blocking not-applicable — a membership assert that could not read the store
has proven nothing about the gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import meilisearch
import neo4j
from meilisearch.errors import MeilisearchApiError, MeilisearchError

from evals.harness.checks import StorePresence

#: The Meilisearch index published artifacts land in. Mirrors
#: ``server/meetingminer/projections/publish_gate.py``'s ``ARTIFACTS_INDEX``
#: — redeclared rather than imported, because ``meetingminer.projections`` is
#: the single writer to both stores and stays forbidden to the harness
#: (AD-16). If story 4-4 renames the index, this constant fails loudly: every
#: published artifact reads as absent, which is the check working.
ARTIFACTS_INDEX = "artifacts"

#: Meilisearch error codes that mean "not there", which for this check is a
#: legitimate answer rather than a failure: an index nobody ever wrote reads
#: as absent (nothing was projected — exactly what the pre-approval half
#: expects today), and so does a missing document.
_ABSENT_CODES = ("document_not_found", "index_not_found")

#: How the graph read relates an artifact node to its cited moments. The
#: artifact is matched by its UUID as a node ``id`` property — deliberately
#: label-agnostic, so whatever label story 4-4 chooses cannot quietly evade
#: the assert — and the cited moments are whatever ``Moment`` nodes the
#: artifact's node relates to, in either direction.
_ARTIFACT_IN_GRAPH = (
    "MATCH (a {id: $id})"
    " OPTIONAL MATCH (a)--(m:Moment)"
    " RETURN a.id AS id, collect(DISTINCT m.id) AS moments"
)

#: Whether a moment is projected at all — probe eligibility's graph read
#: (story 11.3). Label-pinned to ``Moment``, unlike the artifact read: the
#: probe must ride a node the approve route's ``MATCH (mo:Moment {id: ...})``
#: will find, so matching a lookalike node under another label would promise
#: a projection the route cannot use.
_MOMENT_IN_GRAPH = "MATCH (m:Moment {id: $id}) RETURN m.id AS id"

_CONNECT_TIMEOUT = 10.0


class StoreAssertError(Exception):
    """A retrieval store could not be reached or could not answer.

    One error type for every way a membership read can fail, matching
    ``corpus.CorpusQueryError``: the test layer records it as a named
    blocking not-applicable, so the run's report keeps the diagnosis.
    """


def search_client(config: Any) -> meilisearch.Client:
    """The read-only Meilisearch handle, from settings + `.env` secrets.

    ``config`` is duck-typed (``settings.stores.meilisearch.url`` and
    ``secrets.meili_master_key``). A missing key is a named refusal rather
    than an anonymous 401 later: the check must halt rather than reach for a
    second ``.env`` parsing path.
    """
    store = config.settings.stores.meilisearch
    key = config.secrets.meili_master_key
    if not key:
        raise StoreAssertError(
            "MEILI_MASTER_KEY is not set in .env — the harness cannot read"
            " the search store's membership without it"
        )
    return meilisearch.Client(store.url, key, timeout=int(_CONNECT_TIMEOUT))


def artifact_in_search(
    client: meilisearch.Client, artifact_id: str
) -> StorePresence:
    """Whether the ``artifacts`` index holds this document, and what it cites.

    A get-document against the artifact's UUID (documents are keyed on the
    Postgres-minted id, ``projections/publish_gate.py``). A missing index
    reads as *absent*, not as an error: nothing projected is exactly the
    state the pre-approval half expects. The cited moments come from the
    document's ``momentIds`` — the field ``artifact_document`` writes.
    """
    try:
        document = client.index(ARTIFACTS_INDEX).get_document(artifact_id)
    except MeilisearchApiError as exc:
        if exc.code in _ABSENT_CODES or exc.status_code == 404:
            return StorePresence(present=False)
        raise StoreAssertError(
            f"Meilisearch refused the membership read for artifact"
            f" {artifact_id}: {exc}"
        ) from exc
    except MeilisearchError as exc:
        raise StoreAssertError(
            f"Meilisearch could not be reached for artifact {artifact_id}:"
            f" {exc} — start it with 'make infra-up'"
        ) from exc
    return StorePresence(
        present=True,
        cited_moment_ids=_cited_moments_of(document, artifact_id),
    )


_UNREAD = object()


def _cited_moments_of(document: Any, artifact_id: str) -> tuple[str, ...]:
    """The ``momentIds`` a present document carries, however the client wraps it.

    Attribute access first (the meilisearch client's ``Document`` model),
    then mapping access (a client release returning plain dicts): coupling to
    one wrapper's internals would make every present document read as citing
    nothing after a client change — a false citation failure on a store that
    is fine. A present document whose fields cannot be read either way is a
    named shape error, mirroring ``retrieval.py``'s shape refusals, because
    "present but unreadable" proves nothing about the gate.
    """
    moment_ids = getattr(document, "momentIds", _UNREAD)
    if moment_ids is _UNREAD and isinstance(document, Mapping):
        moment_ids = document.get("momentIds", _UNREAD)
    if moment_ids is _UNREAD and not (
        isinstance(document, Mapping) or hasattr(document, "__dict__")
    ):
        raise StoreAssertError(
            f"Meilisearch returned a document for artifact {artifact_id} in a"
            f" shape the harness cannot read ({type(document).__name__}) —"
            " the client's document shape changed and stores.py has to change"
            " with it"
        )
    if not isinstance(moment_ids, (list, tuple)):
        return ()
    return tuple(str(moment) for moment in moment_ids)


def graph_driver(config: Any) -> neo4j.Driver:
    """The Neo4j driver, from settings + `.env` secrets, connectivity verified.

    Verified here rather than at first query so an unreachable graph is one
    named :class:`StoreAssertError` instead of a driver-family exception
    surfacing from inside a membership read. The caller closes it.
    """
    store = config.settings.stores.neo4j
    password = config.secrets.neo4j_password
    if not password:
        raise StoreAssertError(
            "NEO4J_PASSWORD is not set in .env — the harness cannot read the"
            " graph store's membership without it"
        )
    driver = neo4j.GraphDatabase.driver(
        store.uri,
        auth=(store.user, password),
        connection_timeout=_CONNECT_TIMEOUT,
    )
    try:
        driver.verify_connectivity()
    except Exception as exc:  # the neo4j driver raises a wide family here
        driver.close()
        raise StoreAssertError(
            f"Neo4j unreachable at {store.uri}"
            f" ({type(exc).__name__}: {exc}) — start it with 'make infra-up'"
        ) from exc
    return driver


def moment_in_graph(driver: neo4j.Driver, moment_id: str) -> bool:
    """Whether a ``Moment`` node with this id is in the graph. Read-only.

    Probe eligibility (story 11.3): the approve route's graph half rolls the
    whole write back when the cited ``Moment`` node is missing, so the probe
    layer asks this before minting anything. Same read-session pin as
    :func:`artifact_in_graph`, same one named error for every failure mode.
    """
    try:
        with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
            records = list(session.run(_MOMENT_IN_GRAPH, id=moment_id))
    except Exception as exc:  # the neo4j driver raises a wide family here
        raise StoreAssertError(
            f"Neo4j could not answer the membership read for moment"
            f" {moment_id} ({type(exc).__name__}: {exc})"
        ) from exc
    return bool(records)


def artifact_in_graph(driver: neo4j.Driver, artifact_id: str) -> StorePresence:
    """Whether any graph node carries this artifact's UUID, and its moments.

    Label-agnostic on purpose (see :data:`_ARTIFACT_IN_GRAPH`). The session
    is opened ``default_access_mode=READ`` so a routing-aware server refuses
    a write outright — the read-only pin as a driver setting, not a review
    convention, mirroring ``corpus.py``'s libpq option.
    """
    try:
        with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
            records = list(session.run(_ARTIFACT_IN_GRAPH, id=artifact_id))
        if not records:
            return StorePresence(present=False)
        # One row per matching node (the label-agnostic match can hit several if
        # a duplicated id ever lands). All rows are merged rather than `.single()`
        # raising: two nodes sharing the id is a *stronger* presence, and turning
        # it into a connection-style error would soften a real gate violation
        # into a not-applicable. The multiplicity is noted on the presence so the
        # report's detail shows the identity anomaly (AD-6 keys identity on the
        # Postgres-minted UUID, so more than one node is itself a finding).
        moments: list[str] = []
        for record in records:
            if not isinstance(record, Mapping):
                raise TypeError(f"record is {type(record).__name__}, not a mapping")
            record_moments = record.get("moments")
            if not isinstance(record_moments, list):
                raise TypeError("record has no list `moments` field")
            for moment in record_moments:
                if moment is not None and str(moment) not in moments:
                    moments.append(str(moment))
    except Exception as exc:  # the neo4j driver raises a wide family here
        raise StoreAssertError(
            f"Neo4j could not answer the membership read for artifact"
            f" {artifact_id} ({type(exc).__name__}: {exc})"
        ) from exc
    note = None
    if len(records) > 1:
        note = (
            f"{len(records)} graph nodes share id {artifact_id} — entity"
            " identity is one UUID, one node (AD-6), so a duplicated node is"
            " a projection defect worth its own look"
        )
    return StorePresence(
        present=True, cited_moment_ids=tuple(moments), note=note
    )
