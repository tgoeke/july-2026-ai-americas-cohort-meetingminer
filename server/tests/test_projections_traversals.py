"""The graph traversal templates: registry, anchors, time order, no silent zero.

Two halves, deliberately. The store-free tests pin what needs no store: the
registry's completeness, the parameterization of the Cypher text, the refusal
taxonomy (unknown template, blank topic, non-UUID node id, unreachable store),
and AC4's import inspection — no graph-building or auto-retriever library
anywhere under ``meetingminer/``. The store-backed tests run every I/O-matrix
row against the live compose Neo4j via the `projection_stores` fixture, and
skip with a named reason when the stores are down.
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import neo4j.exceptions
import pytest
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.config import AppConfig
from meetingminer.projections.stores import ProjectionError, StoreUnavailableError
from meetingminer.projections.traversals import (
    PARTICIPANT_TOPIC_MOMENTS,
    SCREEN_HISTORY,
    TRAVERSAL_TEMPLATES,
    participant_topic_moments,
    run_template,
    screen_history,
)

from conftest import FakeEmbedder, truncate_evidence
from projection_seed import DEEP_LINK, seed_meeting
from test_projections_single_writer import imported_roots, python_files

pytestmark = pytest.mark.slow(reason="the traversals query the Neo4j test twin: 32 tests, 28.5s at e5510c7")


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


# --- store-free: the registry (AC4) ---------------------------------------


def test_the_registry_contains_exactly_the_two_templates() -> None:
    assert set(TRAVERSAL_TEMPLATES) == {SCREEN_HISTORY, PARTICIPANT_TOPIC_MOMENTS}
    for name, template in TRAVERSAL_TEMPLATES.items():
        assert template.name == name
        # The declared parameters are exactly the run function's keyword-only
        # arguments — derived from the signature, so the tuple and the
        # function cannot drift apart unnoticed.
        signature = inspect.signature(template.run)
        keyword_only = tuple(
            parameter.name
            for parameter in signature.parameters.values()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        )
        assert template.parameters == keyword_only, name
    assert TRAVERSAL_TEMPLATES[SCREEN_HISTORY].run is screen_history
    assert TRAVERSAL_TEMPLATES[PARTICIPANT_TOPIC_MOMENTS].run is participant_topic_moments


def _cypher_parameter(name: str) -> str:
    """The `$`-parameter a snake_case keyword travels as (house camelCase)."""
    head, *rest = name.split("_")
    return "$" + head + "".join(part.capitalize() for part in rest)


def test_every_template_cypher_is_parameterized_and_interpolates_nothing() -> None:
    """AD-7: values travel as query parameters, never in the statement text.

    The ``$``-tokens in each statement are exactly the declared parameters —
    an undeclared one would otherwise surface only as a runtime store error.
    And the statement contains no quote character, so no *string* literal can
    hide in it (a numeric or boolean literal needs no quote — that narrower
    class is what review, not this test, guards).
    """
    for template in TRAVERSAL_TEMPLATES.values():
        tokens = set(re.findall(r"\$\w+", template.cypher))
        expected = {_cypher_parameter(parameter) for parameter in template.parameters}
        assert tokens == expected, template.name
        assert '"' not in template.cypher, template.name
        assert "'" not in template.cypher, template.name


def test_an_unknown_template_name_is_a_named_refusal() -> None:
    with pytest.raises(ProjectionError) as excinfo:
        run_template(_UntouchableDriver(), "screen-lineage", screen_id=uuid4())
    message = str(excinfo.value)
    assert "screen-lineage" in message
    assert SCREEN_HISTORY in message
    assert PARTICIPANT_TOPIC_MOMENTS in message


def test_run_template_refuses_missing_or_extra_parameters() -> None:
    """The router calls through this door with model-classified parameters, so
    a misspelling must surface as the named taxonomy, not a raw TypeError."""
    with pytest.raises(ProjectionError) as missing:
        run_template(
            _UntouchableDriver(), PARTICIPANT_TOPIC_MOMENTS, participant_id=uuid4()
        )
    assert PARTICIPANT_TOPIC_MOMENTS in str(missing.value)
    assert "topic" in str(missing.value)

    with pytest.raises(ProjectionError) as extra:
        run_template(
            _UntouchableDriver(), SCREEN_HISTORY, screen_id=uuid4(), limit=5
        )
    assert SCREEN_HISTORY in str(extra.value)
    assert "limit" in str(extra.value)


FORBIDDEN_GRAPH_LIBRARIES = {
    "neo4j_graphrag",
    "graphdatascience",
    "langchain",
    "llama_index",
}


def test_no_graph_library_builds_or_retrieves_in_the_server_package() -> None:
    """AD-7: no library builds, extracts, or owns graph structure — and no
    auto-retriever answers over it. Same AST walk as the single-writer test."""
    offenders = [
        (str(path), root)
        for path in python_files()
        for root in imported_roots(path) & FORBIDDEN_GRAPH_LIBRARIES
    ]
    assert not offenders, offenders


# --- store-free: refusal taxonomy -----------------------------------------


class _Record:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def data(self) -> dict[str, Any]:
        return self._data


class _CannedSession:
    def __init__(self, driver: "_CannedDriver") -> None:
        self._driver = driver

    def __enter__(self) -> "_CannedSession":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def run(self, cypher: str, parameters: dict[str, Any]) -> list[_Record]:
        self._driver.parameters = parameters
        return [_Record(row) for row in self._driver.rows]


class _CannedDriver:
    """A driver whose session answers with canned records — no store.

    Records the last parameters it was sent, so a test can assert what
    actually travelled to the store.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.parameters: dict[str, Any] | None = None

    def session(self) -> _CannedSession:
        return _CannedSession(self)


class _DownDriver:
    def session(self) -> Any:
        raise neo4j.exceptions.ServiceUnavailable("connection refused")


class _RefusingSession:
    def __enter__(self) -> "_RefusingSession":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def run(self, cypher: str, parameters: dict[str, Any]) -> Any:
        raise neo4j.exceptions.ClientError("Invalid input")


class _RefusingDriver:
    """A store that answered and refused — the other half of the taxonomy."""

    def session(self) -> _RefusingSession:
        return _RefusingSession()


class _UntouchableDriver:
    def session(self) -> Any:  # pragma: no cover - reaching it is the failure
        raise AssertionError("the store must not be touched")


def _screen_history_row(**overrides: Any) -> dict[str, Any]:
    """One otherwise-valid canned screen-history record."""
    row = {
        "screenId": str(uuid4()),
        "screenIdentityKey": "sha256:screen-a",
        "screenLabel": None,
        "screenViewType": "ui-screen",
        "momentId": str(uuid4()),
        "meetingId": str(uuid4()),
        "meetingTitle": "Data Hub Demo",
        "meetingStartedAt": "2026-08-05T12:00:19+00:00",
        "startMs": 0,
        "endMs": 2_000,
        "screenshotId": None,
        "sourceDeepLink": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("topic", ["", "   ", "\n\t"])
def test_a_blank_topic_is_refused_before_the_store_is_touched(topic: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        participant_topic_moments(
            _UntouchableDriver(), participant_id=uuid4(), topic=topic
        )
    assert "topic" in str(excinfo.value)


def test_a_none_topic_is_refused_not_matched_as_the_word_none() -> None:
    """`str(None)` is the non-blank string "None" — a type check has to catch
    it before it becomes a query for the literal word."""
    with pytest.raises(ValueError) as excinfo:
        participant_topic_moments(
            _UntouchableDriver(), participant_id=uuid4(), topic=None
        )
    assert "topic" in str(excinfo.value)


def test_a_malformed_anchor_id_is_an_input_error_not_an_unknown_anchor() -> None:
    """A garbage id could never match a node, so resolving it to the
    unknown-anchor shape would collapse a caller bug into a lookup miss."""
    with pytest.raises(ValueError) as screen:
        screen_history(_UntouchableDriver(), screen_id="garbage")
    assert "screen_id" in str(screen.value)

    with pytest.raises(ValueError) as participant:
        participant_topic_moments(
            _UntouchableDriver(), participant_id="garbage", topic="SFTP"
        )
    assert "participant_id" in str(participant.value)


def test_a_padded_topic_is_stripped_before_it_reaches_the_store() -> None:
    """`Moment.text` never carries the caller's padding, so an unstripped
    `" SFTP "` would be a literal-whitespace match — a silent false empty."""
    driver = _CannedDriver([])
    participant_topic_moments(driver, participant_id=uuid4(), topic="  SFTP  ")
    assert driver.parameters is not None
    assert driver.parameters["topic"] == "SFTP"


def test_a_non_uuid_node_id_is_a_named_projection_error() -> None:
    """AD-6: a graph node whose id does not parse is corruption, named — never
    a partial silent result."""
    row = _screen_history_row(momentId="moment-7")
    with pytest.raises(ProjectionError) as excinfo:
        screen_history(_CannedDriver([row]), screen_id=row["screenId"])
    message = str(excinfo.value)
    assert "moment-7" in message
    assert "Moment" in message


def test_non_utc_meeting_time_is_named_projection_corruption() -> None:
    row = _screen_history_row(meetingStartedAt="2026-08-05T12:00:19+01:00")
    with pytest.raises(ProjectionError) as excinfo:
        screen_history(_CannedDriver([row]), screen_id=row["screenId"])
    assert "non-UTC" in str(excinfo.value)


@pytest.mark.parametrize(
    ("start_ms", "end_ms"),
    [(-1, 2_000), (2_000, 1_999)],
)
def test_invalid_moment_offsets_are_named_projection_corruption(
    start_ms: int, end_ms: int
) -> None:
    row = _screen_history_row(startMs=start_ms, endMs=end_ms)
    with pytest.raises(ProjectionError) as excinfo:
        screen_history(_CannedDriver([row]), screen_id=row["screenId"])
    assert "invalid offsets" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value", "expected_field"),
    [
        ("meetingTitle", ["not", "a", "string"], "title"),
        ("sourceDeepLink", {"not": "a string"}, "sourceDeepLink"),
        ("screenLabel", ["not", "a", "string"], "label"),
        ("screenViewType", 7, "viewType"),
    ],
)
def test_non_string_nullable_graph_properties_are_named_corruption(
    field: str, value: Any, expected_field: str
) -> None:
    row = _screen_history_row(**{field: value})
    with pytest.raises(ProjectionError) as excinfo:
        screen_history(_CannedDriver([row]), screen_id=row["screenId"])
    assert expected_field in str(excinfo.value)


def test_an_unreachable_store_is_a_store_unavailable_error() -> None:
    """Driver failures are wrapped; no raw neo4j exception leaves the package."""
    with pytest.raises(StoreUnavailableError) as excinfo:
        screen_history(_DownDriver(), screen_id=uuid4())
    assert SCREEN_HISTORY in str(excinfo.value)


def test_a_store_that_answers_and_refuses_is_a_projection_error() -> None:
    """The other half of the taxonomy: answered-and-refused is a
    ProjectionError, not a StoreUnavailableError and not a raw Neo4jError."""
    with pytest.raises(ProjectionError) as excinfo:
        screen_history(_RefusingDriver(), screen_id=uuid4())
    assert SCREEN_HISTORY in str(excinfo.value)
    assert not isinstance(excinfo.value, StoreUnavailableError)


# --- store-backed: screen history -----------------------------------------


def test_screen_history_spans_meetings_in_time_order(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """AC1: every meeting-and-moment pair where the screen appeared, ordered
    by (meeting startedAt, meeting id, moment startMs).

    The *later* meeting is seeded and projected first, so passing proves the
    order comes from `startedAt` and not from insertion order.
    """
    driver, _client = projection_stores
    shared = ("sha256:shared-history",)
    with pool.connection() as conn:
        later = seed_meeting(
            conn,
            source_id="trav-history-later",
            title="Later Review",
            screen_identity_keys=shared,
            started_at=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        )
        earlier = seed_meeting(
            conn,
            source_id="trav-history-earlier",
            title="Earlier Review",
            screen_identity_keys=shared,
            started_at=datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc),
        )
    assert later.screen_ids == earlier.screen_ids, "fixture must reuse the screen row"
    project(pool, app_config, later.meeting_id, fake_embedder)
    project(pool, app_config, earlier.meeting_id, fake_embedder)

    result = screen_history(driver, screen_id=later.screen_ids[0])

    assert result.screen is not None
    assert result.screen.id == later.screen_ids[0]
    assert result.screen.identity_key == "sha256:shared-history"
    # Both meetings, all four moments, earlier meeting first, startMs within.
    assert [(row.meeting_id, row.moment_id) for row in result.rows] == [
        (earlier.meeting_id, earlier.moment_ids[0]),
        (earlier.meeting_id, earlier.moment_ids[1]),
        (later.meeting_id, later.moment_ids[0]),
        (later.meeting_id, later.moment_ids[1]),
    ]
    # AC3: ids come back as parsed UUIDs equal to the Postgres-minted ones.
    for row in result.rows:
        assert isinstance(row.moment_id, UUID)
        assert isinstance(row.meeting_id, UUID)
    # Row carriage: title, wall clock, offsets, evidence pointers.
    first = result.rows[0]
    assert first.meeting_title == "Earlier Review"
    assert first.meeting_started_at == datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc)
    assert (first.start_ms, first.end_ms) == (2_000, 11_000)
    assert first.screenshot_id == earlier.screenshot_ids[0]
    assert first.source_deep_link is None  # a recording meeting carries no link


def test_meetings_sharing_a_started_at_order_by_meeting_id(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """The explicit tie-break: distinct meetings can share a startedAt (every
    day-precision drop lands on 00:00), and the order must still be stable."""
    driver, _client = projection_stores
    shared = ("sha256:shared-tie",)
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="trav-tie-a", screen_identity_keys=shared)
        second = seed_meeting(conn, source_id="trav-tie-b", screen_identity_keys=shared)
    project(pool, app_config, first.meeting_id, fake_embedder)
    project(pool, app_config, second.meeting_id, fake_embedder)

    result = screen_history(driver, screen_id=first.screen_ids[0])

    # Python's str-sort matches Neo4j's ORDER BY for these values: both are
    # plain lexicographic comparisons over lowercase-hex UUID strings.
    ordered_meetings = sorted((first, second), key=lambda s: str(s.meeting_id))
    expected = [
        (seeded.meeting_id, moment_id)
        for seeded in ordered_meetings
        for moment_id in seeded.moment_ids  # already in startMs order
    ]
    assert [(row.meeting_id, row.moment_id) for row in result.rows] == expected


def test_screen_history_breaks_same_offset_ties_by_moment_id(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """A same-offset pair remains deterministic after the required three-key
    time order is exhausted."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trav-same-offset")
        conn.execute(
            "UPDATE moment SET start_ms = %s, screenshot_id = %s WHERE id = %s",
            (2_000, seeded.screenshot_ids[0], seeded.moment_ids[1]),
        )
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    result = screen_history(driver, screen_id=seeded.screen_ids[0])

    assert [(row.meeting_id, row.moment_id) for row in result.rows] == [
        (seeded.meeting_id, moment_id)
        for moment_id in sorted(seeded.moment_ids, key=str)
    ]


def test_an_unknown_screen_is_unresolved_not_a_silent_zero(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trav-unknown-screen")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    result = screen_history(driver, screen_id=uuid4())

    assert result.screen is None
    assert result.rows == ()


def test_a_screen_with_no_moments_is_a_valid_empty_answer(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Distinct from the unknown anchor: the screen resolves, the history is
    empty, and the two must never collapse into one shape."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trav-screen-no-moment", with_moments=False)
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    result = screen_history(driver, screen_id=seeded.screen_ids[0])

    assert result.screen is not None
    assert result.screen.id == seeded.screen_ids[0]
    assert result.rows == ()


# --- store-backed: the Clarence query -------------------------------------


def test_participant_topic_moments_includes_only_attended_meetings(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """AC2: both meetings discuss the topic; only the attended one returns.

    The attended meeting is transcript-only, so the rows also prove
    `sourceDeepLink` carriage where a screenshot cannot exist (UX-DR11).
    """
    driver, _client = projection_stores
    with pool.connection() as conn:
        attended = seed_meeting(
            conn, source_id="trav-clarence-attended", has_recording=False
        )
        not_attended = seed_meeting(
            conn,
            source_id="trav-clarence-absent",
            screen_identity_keys=("sha256:screen-clarence",),
            participants=(
                ("mail:pat.jones@contoso.com", "Jones, Pat"),
                ("mail:sam.smith@contoso.com", "Smith, Sam"),
            ),
        )
    project(pool, app_config, attended.meeting_id, fake_embedder)
    project(pool, app_config, not_attended.meeting_id, fake_embedder)

    result = participant_topic_moments(
        driver, participant_id=attended.participant_ids[0], topic="SFTP"
    )

    # AC2: the anchor exposes the eval's comparison key.
    assert result.participant is not None
    assert result.participant.id == attended.participant_ids[0]
    assert result.participant.identity_key == "mail:timothy.goeke@contoso.com"
    assert result.participant.display_name == "Goeke, Timothy"
    # Only the attended meeting's SFTP moment — the second seeded moment,
    # covering the turns that mention it. The unattended meeting discusses the
    # same topic and is excluded.
    assert [(row.meeting_id, row.moment_id) for row in result.rows] == [
        (attended.meeting_id, attended.moment_ids[1])
    ]
    row = result.rows[0]
    assert isinstance(row.moment_id, UUID)
    assert row.screenshot_id is None
    assert row.source_deep_link == DEEP_LINK


def test_participant_topic_moments_are_in_deterministic_time_order(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """The Clarence template's ordering is independently pinned, not inferred
    from the screen-history template's superficially similar Cypher."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        later = seed_meeting(
            conn,
            source_id="trav-clarence-later",
            has_recording=False,
            started_at=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        )
        earlier = seed_meeting(
            conn,
            source_id="trav-clarence-earlier",
            has_recording=False,
            started_at=datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc),
        )
    project(pool, app_config, later.meeting_id, fake_embedder)
    project(pool, app_config, earlier.meeting_id, fake_embedder)

    result = participant_topic_moments(
        driver, participant_id=earlier.participant_ids[0], topic="SFTP"
    )

    assert [(row.meeting_id, row.moment_id) for row in result.rows] == [
        (earlier.meeting_id, earlier.moment_ids[1]),
        (later.meeting_id, later.moment_ids[1]),
    ]


def test_topic_matching_is_a_case_insensitive_substring(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trav-case")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    person = seeded.participant_ids[0]
    lowered = participant_topic_moments(driver, participant_id=person, topic="sftp")
    seeded_case = participant_topic_moments(driver, participant_id=person, topic="SFTP")
    mixed = participant_topic_moments(driver, participant_id=person, topic="SfTp")

    assert lowered.rows, "the seeded corpus discusses SFTP"
    assert lowered == seeded_case == mixed


def test_an_unknown_participant_is_unresolved_not_a_silent_zero(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trav-unknown-person")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    result = participant_topic_moments(driver, participant_id=uuid4(), topic="SFTP")

    assert result.participant is None
    assert result.rows == ()


def test_a_participant_with_no_matching_moments_is_a_valid_empty_answer(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trav-person-no-topic")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    result = participant_topic_moments(
        driver, participant_id=seeded.participant_ids[0], topic="kubernetes"
    )

    assert result.participant is not None
    assert result.participant.id == seeded.participant_ids[0]
    assert result.rows == ()


# --- store-backed: registry dispatch --------------------------------------


def test_run_template_dispatches_to_the_same_result_as_a_direct_call(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="trav-dispatch")
    project(pool, app_config, seeded.meeting_id, fake_embedder)

    assert run_template(
        driver, SCREEN_HISTORY, screen_id=seeded.screen_ids[0]
    ) == screen_history(driver, screen_id=seeded.screen_ids[0])
    assert run_template(
        driver,
        PARTICIPANT_TOPIC_MOMENTS,
        participant_id=seeded.participant_ids[0],
        topic="purchase order",
    ) == participant_topic_moments(
        driver, participant_id=seeded.participant_ids[0], topic="purchase order"
    )
