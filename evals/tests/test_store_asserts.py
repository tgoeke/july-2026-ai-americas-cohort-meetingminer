"""Check 2.11's store reads, exercised with neither store running.

``stores.py`` is the harness's whole read-only footprint against Meilisearch
and Neo4j, and every way a store can fail to answer must surface as one named
:class:`StoreAssertError` — that is what the check layer records as a blocking
not-applicable, keeping the diagnosis in the run report. These tests pin that
mapping with duck-typed fakes: the client construction refusals (a missing
`.env` key must halt, never fall through to an anonymous auth failure later),
the absent-versus-error split on the Meilisearch side, the unreachable-graph
refusal, and the presence/citation extraction both stores share.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Self

import pytest

# The driver packages are deliberately NOT imported here — the boundary guard
# pins `meilisearch`/`neo4j` imports to `harness/stores.py` across the whole
# evals tree. The exception classes and driver constants these fakes need are
# reached through `stores`' own namespace: the seam under test.
from evals.harness import stores
from evals.harness.stores import (
    StoreAssertError,
    artifact_in_graph,
    artifact_in_search,
    graph_driver,
    moment_in_graph,
    search_client,
)

ARTIFACT = "33333333-3333-7333-8333-333333333333"
MOMENT = "44444444-4444-7444-8444-444444444444"


def a_config(
    *, meili_key: str | None = "masterkey", neo4j_password: str | None = "pw"
) -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(
            stores=SimpleNamespace(
                meilisearch=SimpleNamespace(url="http://localhost:7700"),
                neo4j=SimpleNamespace(uri="bolt://localhost:7687", user="neo4j"),
            )
        ),
        secrets=SimpleNamespace(
            meili_master_key=meili_key, neo4j_password=neo4j_password
        ),
    )


def api_error(code: str, status_code: int) -> Exception:
    # The real constructor wants an HTTP response; the mapping under test
    # reads only `code` and `status_code`.
    cls = stores.MeilisearchApiError
    exc = cls.__new__(cls)
    exc.code = code
    exc.status_code = status_code
    exc.message = f"fake {code}"
    exc.link = None
    exc.type = None
    return exc


class FakeIndex:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    def get_document(self, document_id: str) -> Any:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeSearchClient:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.asked_for: list[str] = []

    def index(self, name: str) -> FakeIndex:
        self.asked_for.append(name)
        return FakeIndex(self.outcome)


# --------------------------------------------------------------------------
# client construction — missing secrets are named refusals
# --------------------------------------------------------------------------


def test_a_missing_meili_key_is_a_named_refusal() -> None:
    with pytest.raises(StoreAssertError) as caught:
        search_client(a_config(meili_key=None))
    assert "MEILI_MASTER_KEY" in str(caught.value)


def test_a_missing_neo4j_password_is_a_named_refusal() -> None:
    with pytest.raises(StoreAssertError) as caught:
        graph_driver(a_config(neo4j_password=None))
    assert "NEO4J_PASSWORD" in str(caught.value)


def test_an_unreachable_graph_is_one_named_error_and_the_driver_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDriver:
        closed = False

        def verify_connectivity(self) -> None:
            raise RuntimeError("connection refused")

        def close(self) -> None:
            self.closed = True

    driver = FakeDriver()
    monkeypatch.setattr(
        stores.neo4j.GraphDatabase, "driver", lambda *a, **k: driver
    )
    with pytest.raises(StoreAssertError) as caught:
        graph_driver(a_config())
    assert "bolt://localhost:7687" in str(caught.value)
    assert driver.closed


# --------------------------------------------------------------------------
# artifact_in_search — absent versus error, and citation extraction
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        api_error("document_not_found", 404),
        api_error("index_not_found", 404),
        api_error("some_future_code", 404),
    ],
)
def test_a_missing_document_or_index_reads_as_absent(exc: Exception) -> None:
    presence = artifact_in_search(FakeSearchClient(exc), ARTIFACT)
    assert presence.present is False


def test_a_refused_read_is_a_named_error_not_an_absence() -> None:
    with pytest.raises(StoreAssertError) as caught:
        artifact_in_search(FakeSearchClient(api_error("invalid_api_key", 403)), ARTIFACT)
    assert ARTIFACT in str(caught.value)


def test_an_unreachable_search_store_is_a_named_error() -> None:
    with pytest.raises(StoreAssertError) as caught:
        artifact_in_search(
            FakeSearchClient(stores.MeilisearchError("connection refused")), ARTIFACT
        )
    assert ARTIFACT in str(caught.value)


def test_a_present_document_carries_its_cited_moments() -> None:
    document = SimpleNamespace(momentIds=[MOMENT])
    client = FakeSearchClient(document)
    presence = artifact_in_search(client, ARTIFACT)
    assert presence.present is True
    assert presence.cited_moment_ids == (MOMENT,)
    assert client.asked_for == [stores.ARTIFACTS_INDEX]


def test_a_document_without_moment_ids_is_present_but_cites_nothing() -> None:
    presence = artifact_in_search(
        FakeSearchClient(SimpleNamespace(momentIds="not-a-list")), ARTIFACT
    )
    assert presence.present is True
    assert presence.cited_moment_ids == ()


def test_a_mapping_shaped_document_carries_its_cited_moments_too() -> None:
    """A meilisearch client release returning plain dicts must not make every
    present document read as citing nothing — that would be a false citation
    failure on a store that is fine."""
    presence = artifact_in_search(
        FakeSearchClient({"id": ARTIFACT, "momentIds": [MOMENT]}), ARTIFACT
    )
    assert presence.present is True
    assert presence.cited_moment_ids == (MOMENT,)


def test_a_mapping_shaped_document_without_moment_ids_cites_nothing() -> None:
    presence = artifact_in_search(FakeSearchClient({"id": ARTIFACT}), ARTIFACT)
    assert presence.present is True
    assert presence.cited_moment_ids == ()


def test_an_unreadable_document_shape_is_a_named_error_not_a_blank_citation() -> None:
    """"Present but unreadable" proves nothing about the gate: a wrapper the
    harness cannot read either way is a shape error naming the type,
    mirroring `retrieval.py`'s shape refusals — never a silent `()`. """
    with pytest.raises(StoreAssertError) as caught:
        artifact_in_search(FakeSearchClient("just-a-string"), ARTIFACT)
    assert ARTIFACT in str(caught.value)
    assert "str" in str(caught.value)


# --------------------------------------------------------------------------
# artifact_in_graph — presence, citations, and the named failure
# --------------------------------------------------------------------------


class FakeSession:
    """One query's records, as an iterable — the shape a neo4j Result offers.

    ``artifact_in_graph`` collects *all* records (a duplicated id is two rows
    and a finding, never a ``.single()`` crash), so the fake yields a list.
    """

    def __init__(self, records: Any) -> None:
        self.records = records

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def run(self, query: str, **params: Any) -> Any:
        if isinstance(self.records, Exception):
            raise self.records
        return list(self.records)


class FakeGraphDriver:
    def __init__(self, records: Any) -> None:
        self.records = records
        self.access_modes: list[Any] = []

    def session(self, *, default_access_mode: Any) -> FakeSession:
        self.access_modes.append(default_access_mode)
        return FakeSession(self.records)


def test_no_matching_node_reads_as_absent_through_a_read_session() -> None:
    driver = FakeGraphDriver(records=[])
    presence = artifact_in_graph(driver, ARTIFACT)  # type: ignore[arg-type]
    assert presence.present is False
    assert driver.access_modes == [stores.neo4j.READ_ACCESS]


def test_a_matching_node_carries_its_related_moments() -> None:
    records = [{"id": ARTIFACT, "moments": [MOMENT, None]}]
    presence = artifact_in_graph(FakeGraphDriver(records), ARTIFACT)  # type: ignore[arg-type]
    assert presence.present is True
    assert presence.cited_moment_ids == (MOMENT,)
    assert presence.note is None


def test_two_nodes_sharing_the_id_are_a_stronger_presence_with_a_note() -> None:
    """A duplicated id must never soften into a connection-style error: the
    node is *there* (a real gate finding if unpublished), and the identity
    anomaly is noted on the presence for the report's detail (AD-6)."""
    other = "55555555-5555-7555-8555-555555555555"
    records = [
        {"id": ARTIFACT, "moments": [MOMENT]},
        {"id": ARTIFACT, "moments": [MOMENT, other]},
    ]
    presence = artifact_in_graph(FakeGraphDriver(records), ARTIFACT)  # type: ignore[arg-type]
    assert presence.present is True
    assert presence.cited_moment_ids == (MOMENT, other)
    assert presence.note is not None
    assert "2 graph nodes" in presence.note
    assert ARTIFACT in presence.note


def test_a_failing_graph_read_is_a_named_error() -> None:
    driver = FakeGraphDriver(RuntimeError("defunct connection"))
    with pytest.raises(StoreAssertError) as caught:
        artifact_in_graph(driver, ARTIFACT)  # type: ignore[arg-type]
    assert ARTIFACT in str(caught.value)


@pytest.mark.parametrize("records", [[object()], [{"id": ARTIFACT, "moments": "bad"}]])
def test_a_malformed_graph_record_is_a_named_error(records: list[Any]) -> None:
    with pytest.raises(StoreAssertError) as caught:
        artifact_in_graph(FakeGraphDriver(records), ARTIFACT)  # type: ignore[arg-type]
    assert ARTIFACT in str(caught.value)


# --------------------------------------------------------------------------
# moment_in_graph — probe eligibility's projected-moment read (story 11.3)
# --------------------------------------------------------------------------


def test_a_projected_moment_reads_as_present_through_a_read_session() -> None:
    driver = FakeGraphDriver(records=[{"id": MOMENT}])
    assert moment_in_graph(driver, MOMENT) is True  # type: ignore[arg-type]
    assert driver.access_modes == [stores.neo4j.READ_ACCESS]


def test_an_unprojected_moment_reads_as_absent() -> None:
    assert moment_in_graph(FakeGraphDriver(records=[]), MOMENT) is False  # type: ignore[arg-type]


def test_a_failing_moment_read_is_a_named_error() -> None:
    driver = FakeGraphDriver(RuntimeError("defunct connection"))
    with pytest.raises(StoreAssertError) as caught:
        moment_in_graph(driver, MOMENT)  # type: ignore[arg-type]
    assert MOMENT in str(caught.value)
