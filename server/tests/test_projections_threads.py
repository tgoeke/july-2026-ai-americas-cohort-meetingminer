"""Topics and threads in the graph, and the thread-timeline traversal (10.2).

Two halves, the same split `test_projections_traversals.py` uses. The
store-free tests pin the row-parsing and refusal taxonomy against canned
drivers — the aggregates, the speaker roll-up, the unknown anchor, the corrupt
node. The store-backed tests run the real projection into the compose Neo4j
twin through the `projection_stores` fixture and walk it with the registered
template, and skip with a named reason when the twins are down.

Topics are seeded straight into Postgres and threaded by `derive_threads`
rather than by hand: the point of the store-backed half is that what the
derivation writes is what the graph projects and what the traversal reads, and
a hand-built `thread` row would prove only that this file agrees with itself.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Any, Self, Sequence
from uuid import UUID, uuid4

import neo4j.exceptions
import pytest
from psycopg import Connection
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.adapters.embed.port import Vector
from meetingminer.config import AppConfig
from meetingminer.domain.threads import derive_threads
from meetingminer.projections import graph
from meetingminer.projections.evidence import TopicMentionRow, TopicRow, read_meeting
from meetingminer.projections.stores import ProjectionError, StoreUnavailableError
from meetingminer.projections.traversals import (
    THREAD_TIMELINE,
    ThreadTimelineResult,
    run_template,
    thread_timeline,
)

from conftest import FakeEmbedder, truncate_evidence
from projection_seed import STARTED_AT, seed_meeting

pytestmark = pytest.mark.slow(
    reason="projects into the Neo4j test twin and walks it: 26 tests, 46s measured 2026-08-30"
)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


# --- canned drivers, mirroring test_projections_traversals ----------------


class _CannedDriver:
    """Returns the given records for any statement, so a row parser can be
    exercised without a store."""

    def __init__(self, records: Sequence[dict[str, Any]]) -> None:
        self._records = list(records)

    def session(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def run(self, _cypher: str, _parameters: dict[str, Any]) -> list[Any]:
        return [_CannedRecord(record) for record in self._records]


class _CannedRecord:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def data(self) -> dict[str, Any]:
        return self._data


class _DownDriver:
    def session(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def run(self, _cypher: str, _parameters: dict[str, Any]) -> list[Any]:
        raise neo4j.exceptions.ServiceUnavailable("the twin is not running")


class _UntouchableDriver:
    """Any use at all is a test failure — for the refusals that must happen
    before the store is reached."""

    def session(self) -> Self:
        raise AssertionError("the store must not be touched for this input")


class StubEmbedder:
    """Vectors the test chooses, so a link is the geometry the test states."""

    model = "stub-embedder"
    dimension = 3

    def __init__(self, vectors: dict[str, Sequence[float]]) -> None:
        self._vectors = {text: tuple(float(v) for v in vec) for text, vec in vectors.items()}

    def embed_documents(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        return tuple(self._vectors[text] for text in texts)

    def embed_query(self, text: str) -> Vector:
        return self._vectors[text]


# --- canned rows -----------------------------------------------------------

THREAD_ID = UUID("00000000-0000-4000-8000-000000000001")
TOPIC_ID = UUID("00000000-0000-4000-8000-000000000002")
MEETING_ID = UUID("00000000-0000-4000-8000-000000000003")
MOMENT_ID = UUID("00000000-0000-4000-8000-000000000004")
PERSON_ID = UUID("00000000-0000-4000-8000-000000000005")


def canned_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "anchorId": str(THREAD_ID),
        "anchorName": "Vendor feed",
        "topicId": str(TOPIC_ID),
        "topicName": "Vendor feed",
        "topicGist": "The supplier data pipeline.",
        "anchorMs": 2_000,
        "momentId": str(MOMENT_ID),
        "meetingId": str(MEETING_ID),
        "meetingTitle": "Data Hub Demo",
        "meetingStartedAt": STARTED_AT.isoformat(),
        "startMs": 2_000,
        "endMs": 12_000,
        "screenshotId": None,
        "sourceDeepLink": None,
        "speakers": [[str(PERSON_ID), "mail:a@b.c", "Goeke, Timothy"]],
    }
    row.update(overrides)
    return row


# --- store-free: parsing and the refusal taxonomy -------------------------


def test_an_unknown_thread_anchor_is_none_not_an_empty_thread() -> None:
    result = thread_timeline(_CannedDriver([]), thread_id=THREAD_ID)
    assert result.thread is None
    assert result.meetings == ()
    assert result.mention_count == 0
    assert result.first_mention_at is None


def test_a_resolved_thread_with_no_mentions_is_a_valid_empty_answer() -> None:
    """The anchor row an OPTIONAL MATCH yields when nothing matched: the
    thread exists, its moment column is NULL. Distinguishable from unknown."""
    row = canned_row(momentId=None, topicId=None, momentStartedAt=None)
    result = thread_timeline(_CannedDriver([row]), thread_id=THREAD_ID)
    assert result.thread is not None
    assert result.thread.id == THREAD_ID
    assert result.meetings == ()
    assert (result.mention_count, result.meeting_count) == (0, 0)
    assert (result.first_mention_at, result.last_mention_at) == (None, None)


def test_a_non_uuid_anchor_is_refused_before_the_store_is_touched() -> None:
    with pytest.raises(ValueError) as excinfo:
        thread_timeline(_UntouchableDriver(), thread_id="not-a-uuid")
    assert "thread_id" in str(excinfo.value)


def test_an_unreachable_store_is_a_store_unavailable_error() -> None:
    with pytest.raises(StoreUnavailableError) as excinfo:
        thread_timeline(_DownDriver(), thread_id=THREAD_ID)
    assert THREAD_TIMELINE in str(excinfo.value)


def test_a_thread_node_whose_id_is_not_a_uuid_is_named_corruption() -> None:
    with pytest.raises(ProjectionError) as excinfo:
        thread_timeline(_CannedDriver([canned_row(anchorId="thread-1")]), thread_id=THREAD_ID)
    assert "Thread" in str(excinfo.value)


def test_a_naive_meeting_timestamp_is_named_corruption() -> None:
    """Mention wall clocks derive from the meeting start, so a naive value
    would be treated as though it were UTC."""
    naive = STARTED_AT.replace(tzinfo=None).isoformat()
    with pytest.raises(ProjectionError) as excinfo:
        thread_timeline(_CannedDriver([canned_row(meetingStartedAt=naive)]), thread_id=THREAD_ID)
    assert "non-UTC" in str(excinfo.value)
    assert "Meeting" in str(excinfo.value)


def test_a_moment_with_no_resolved_speaker_reports_no_participants() -> None:
    """The all-null triple the Cypher collects for a moment with no SPOKE_IN
    edge is absence, not a participant whose fields went missing."""
    result = thread_timeline(
        _CannedDriver([canned_row(speakers=[[None, None, None]])]), thread_id=THREAD_ID
    )
    assert result.participants == ()
    assert result.meetings[0].participants == ()
    assert result.mention_count == 1


def test_a_speaker_with_an_id_but_no_identity_key_is_named_corruption() -> None:
    row = canned_row(speakers=[[str(PERSON_ID), None, "Goeke, Timothy"]])
    with pytest.raises(ProjectionError) as excinfo:
        thread_timeline(_CannedDriver([row]), thread_id=THREAD_ID)
    assert "identityKey" in str(excinfo.value)


def test_the_aggregates_are_computed_per_level() -> None:
    """Mentions per meeting, the meeting's span, participants where known —
    and the same three rolled up to the thread."""
    later_meeting = UUID("00000000-0000-4000-8000-000000000009")
    other_person = UUID("00000000-0000-4000-8000-00000000000a")
    rows = [
        canned_row(startMs=2_000, endMs=12_000, anchorMs=2_000),
        canned_row(
            momentId=str(uuid4()),
            startMs=40_000,
            endMs=44_000,
            anchorMs=40_500,
            speakers=[[str(other_person), "mail:e@f.g", "Whitmore, Ellis"]],
        ),
        canned_row(
            meetingId=str(later_meeting),
            momentId=str(uuid4()),
            meetingStartedAt=(STARTED_AT + timedelta(days=7)).isoformat(),
            startMs=5_000,
            endMs=9_000,
            anchorMs=5_000,
        ),
    ]
    result = thread_timeline(_CannedDriver(rows), thread_id=THREAD_ID)

    assert result.meeting_count == 2
    assert result.mention_count == 3
    assert [meeting.mention_count for meeting in result.meetings] == [2, 1]
    # 2_000 → 44_000 in the first meeting; a single 5_000 → 9_000 in the second.
    assert [meeting.span_ms for meeting in result.meetings] == [42_000, 4_000]
    assert [
        [person.display_name for person in meeting.participants] for meeting in result.meetings
    ] == [["Goeke, Timothy", "Whitmore, Ellis"], ["Goeke, Timothy"]]
    assert [person.display_name for person in result.participants] == [
        "Goeke, Timothy",
        "Whitmore, Ellis",
    ]
    assert result.first_mention_at == STARTED_AT + timedelta(seconds=2)
    assert result.last_mention_at == STARTED_AT + timedelta(days=7, seconds=5)


def test_mention_timestamps_use_the_anchor_inside_the_moment() -> None:
    """A topic can be mentioned well after its containing moment starts; the
    timeline's first/last *mention* timestamps must use that anchor, not round
    every mention down to its moment boundary."""
    rows = [
        canned_row(
            startMs=0,
            endMs=60_000,
            anchorMs=50_000,
        ),
        canned_row(
            momentId=str(uuid4()),
            startMs=70_000,
            endMs=100_000,
            anchorMs=95_000,
        ),
    ]

    result = thread_timeline(_CannedDriver(rows), thread_id=THREAD_ID)

    expected = [
        STARTED_AT + timedelta(seconds=50),
        STARTED_AT + timedelta(seconds=95),
    ]
    assert [mention.started_at for mention in result.meetings[0].mentions] == expected
    assert result.first_mention_at == expected[0]
    assert result.last_mention_at == expected[-1]


def test_the_span_takes_the_widest_end_not_the_last_rows_end() -> None:
    """Moments can overlap, so the last row in start order need not carry the
    latest end — a span read off the final row would be short."""
    rows = [
        canned_row(startMs=0, endMs=90_000),
        canned_row(momentId=str(uuid4()), startMs=10_000, endMs=20_000),
    ]
    result = thread_timeline(_CannedDriver(rows), thread_id=THREAD_ID)
    assert result.meetings[0].span_ms == 90_000


def test_two_topics_mentioning_one_moment_are_two_mentions() -> None:
    """`topic_mention` is keyed on (topic, moment), so one moment can carry a
    mention of two topics of the same thread — and the count says two."""
    rows = [
        canned_row(),
        canned_row(topicId=str(uuid4()), topicName="Supplier data pipeline"),
    ]
    result = thread_timeline(_CannedDriver(rows), thread_id=THREAD_ID)
    assert result.mention_count == 2
    assert result.meetings[0].mention_count == 2
    assert len({mention.moment.moment_id for mention in result.meetings[0].mentions}) == 1


def test_run_template_dispatches_the_thread_timeline() -> None:
    result = run_template(_CannedDriver([]), THREAD_TIMELINE, thread_id=THREAD_ID)
    assert isinstance(result, ThreadTimelineResult)


def test_run_template_refuses_the_wrong_parameter_name() -> None:
    with pytest.raises(ProjectionError) as excinfo:
        run_template(_UntouchableDriver(), THREAD_TIMELINE, threadId=THREAD_ID)
    assert THREAD_TIMELINE in str(excinfo.value)
    assert "thread_id" in str(excinfo.value)


# --- store-backed ---------------------------------------------------------


ORTHOGONAL = {
    "Vendor feed": (1.0, 0.0, 0.0),
    "vendor  feed": (1.0, 0.0, 0.0),
    "Budget review": (0.0, 1.0, 0.0),
}


def add_topic(
    conn: Connection, *, meeting_id: UUID, name: str, moment_ids: Sequence[UUID]
) -> UUID:
    """One topic anchored to the given moments, as 10.1's extract stage writes it."""
    topic_id = conn.execute(
        "INSERT INTO topic (meeting_id, name, gist) VALUES (%s, %s, %s) RETURNING id",
        (meeting_id, name, f"a one-line gist for {name}"),
    ).fetchone()[0]
    for index, moment_id in enumerate(moment_ids):
        conn.execute(
            "INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)"
            " VALUES (%s, %s, %s, %s)",
            (topic_id, moment_id, meeting_id, 1_000 * (index + 1)),
        )
    return topic_id


def project(
    pool: ConnectionPool, config: AppConfig, meeting_id: UUID, embedder: Any
) -> projections.ProjectionOutcome:
    with pool.connection() as conn:
        return projections.project_meeting(
            conn, config, meeting_id, embedder_factory=lambda: embedder
        )


def query(driver: Any, cypher: str, **parameters: Any) -> list[dict[str, Any]]:
    with driver.session() as session:
        return [record.data() for record in session.run(cypher, parameters)]


def counts(driver: Any) -> dict[str, int]:
    return graph.counts(driver)


def seed_two_threaded_meetings(
    pool: ConnectionPool, app_config: AppConfig
) -> tuple[UUID, UUID]:
    """Two meetings a week apart whose topics normalize to one name."""
    with pool.connection() as conn:
        first = seed_meeting(conn, source_id="threads-graph-a", started_at=STARTED_AT)
        second = seed_meeting(
            conn,
            source_id="threads-graph-b",
            started_at=STARTED_AT + timedelta(days=7),
        )
        add_topic(
            conn,
            meeting_id=first.meeting_id,
            name="Vendor feed",
            moment_ids=first.moment_ids[:2],
        )
        add_topic(
            conn,
            meeting_id=second.meeting_id,
            name="vendor  feed",
            moment_ids=second.moment_ids[:1],
        )
        add_topic(
            conn,
            meeting_id=second.meeting_id,
            name="Budget review",
            moment_ids=second.moment_ids[1:2],
        )
    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))
    return first.meeting_id, second.meeting_id


def thread_id_of(pool: ConnectionPool, identity_key: str) -> UUID:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id FROM thread WHERE identity_key = %s", (identity_key,)
        ).fetchone()[0]


def test_the_projection_writes_topic_and_thread_nodes_with_their_edges(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)

    summary = counts(driver)
    assert summary["node:Topic"] == 3
    # Two threads: "vendor feed" (two topics, two meetings) and "budget review".
    assert summary["node:Thread"] == 2
    # Two mentions in the first meeting, one each for the second's two topics.
    assert summary["edge:MENTIONS"] == 4
    assert summary["edge:INCLUDES"] == 3

    scoped = query(
        driver,
        "MATCH (t:Topic) RETURN t.meetingId AS meetingId, t.name AS name"
        " ORDER BY t.meetingId, t.name",
    )
    assert {row["meetingId"] for row in scoped} == {str(first), str(second)}
    # A Thread is cross-meeting and carries no meetingId — deleting it in a
    # per-meeting pass would destroy the structure the traversal walks.
    threads = query(driver, "MATCH (t:Thread) RETURN t.meetingId AS meetingId")
    assert all(row["meetingId"] is None for row in threads)


def test_reprojecting_a_meeting_leaves_the_counts_unchanged(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """The whole point of the meeting-scoped/cross-meeting asymmetry: the
    per-meeting delete takes the Topic nodes and leaves the Thread standing."""
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)
    before = counts(driver)

    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)

    assert counts(driver) == before


def test_reprojecting_a_merge_removes_the_absorbed_orphan_thread_node(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """Cross-meeting identity survives a per-meeting delete only while used.

    Once curation redirects the absorbed thread's last topic, the next scoped
    projection must retire the now-orphaned graph node as well as move the
    `INCLUDES` edge.
    """
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)
    survivor = thread_id_of(pool, "vendor feed")
    absorbed = thread_id_of(pool, "budget review")

    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO thread_alias (thread_id, merged_into_id) VALUES (%s, %s)",
            (absorbed, survivor),
        )
        conn.execute("DELETE FROM meeting_projection WHERE meeting_id = %s", (second,))
        conn.commit()

    project(pool, app_config, second, fake_embedder)

    assert query(
        driver,
        "MATCH (th:Thread {id: $id}) RETURN th.id AS id",
        id=str(absorbed),
    ) == []


def test_unprojecting_a_meeting_removes_its_topics_and_keeps_the_thread(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)

    with pool.connection() as conn:
        projections.unproject_meeting(conn, app_config, first)

    summary = counts(driver)
    assert summary["node:Topic"] == 2
    assert summary["node:Thread"] == 2


def test_an_unthreaded_meeting_projects_topics_and_no_thread(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Extraction and derivation are two passes; the second may not have run."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="threads-unthreaded")
        add_topic(
            conn,
            meeting_id=seeded.meeting_id,
            name="Vendor feed",
            moment_ids=seeded.moment_ids[:1],
        )

    project(pool, app_config, seeded.meeting_id, fake_embedder)

    summary = counts(driver)
    assert summary["node:Topic"] == 1
    assert summary.get("node:Thread", 0) == 0
    assert summary["edge:MENTIONS"] == 1


def test_a_mention_of_a_moment_the_graph_does_not_have_is_a_named_refusal(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """A Cypher MATCH that finds nothing drops its row silently, so the edge
    count is verified — a topic with no evidence is navigation to nowhere."""
    driver, _client = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="threads-missing-moment")
    with pool.connection() as conn:
        evidence = read_meeting(conn, seeded.meeting_id)
    tampered = dataclasses.replace(
        evidence,
        topics=(
            TopicRow(
                id=uuid4(),
                name="Vendor feed",
                gist="a one-line gist",
                thread_id=None,
                thread_name=None,
                mentions=(TopicMentionRow(moment_id=uuid4(), anchor_ms=1_000),),
            ),
        ),
    )
    with pytest.raises(ProjectionError) as excinfo:
        graph.project_meeting(driver, tampered, ())
    assert "MENTIONS" in str(excinfo.value)
    # The whole per-meeting transaction rolled back, so no half-written graph.
    assert counts(driver).get("node:Topic", 0) == 0


def test_the_thread_traversal_walks_the_subject_in_wall_clock_order(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)

    result = run_template(
        driver, THREAD_TIMELINE, thread_id=thread_id_of(pool, "vendor feed")
    )

    assert isinstance(result, ThreadTimelineResult)
    assert result.thread is not None
    assert result.thread.name == "Vendor feed"
    assert [meeting.meeting_id for meeting in result.meetings] == [first, second]
    assert [meeting.mention_count for meeting in result.meetings] == [2, 1]
    assert result.mention_count == 3
    assert result.meeting_count == 2
    assert result.first_mention_at is not None and result.last_mention_at is not None
    assert result.first_mention_at < result.last_mention_at
    # Participants where known: the seeded turns resolve two of three speakers.
    assert [person.display_name for person in result.participants] == [
        "Goeke, Timothy",
        "Whitmore, Ellis",
    ]
    for meeting in result.meetings:
        offsets = [mention.moment.start_ms for mention in meeting.mentions]
        assert offsets == sorted(offsets)
        assert meeting.span_ms >= 0


def test_the_thread_traversal_returns_only_its_own_thread(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)

    result = run_template(
        driver, THREAD_TIMELINE, thread_id=thread_id_of(pool, "budget review")
    )

    assert isinstance(result, ThreadTimelineResult)
    assert result.mention_count == 1
    assert [meeting.meeting_id for meeting in result.meetings] == [second]
    assert {mention.topic_name for meeting in result.meetings for mention in meeting.mentions} == {
        "Budget review"
    }


def test_an_unknown_thread_id_against_the_live_store_is_an_unknown_anchor(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    driver, _client = projection_stores
    first, _second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)

    result = run_template(driver, THREAD_TIMELINE, thread_id=uuid4())

    assert isinstance(result, ThreadTimelineResult)
    assert result.thread is None
    assert result.meetings == ()


def test_a_thread_node_with_no_topics_is_a_valid_empty_answer(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Against the real store, not a canned row: the OPTIONAL MATCH has to
    yield the anchor with a NULL moment rather than no record at all."""
    driver, _client = projection_stores
    orphan = uuid4()
    with driver.session() as session:
        session.run(
            "MERGE (t:Thread {id: $id}) SET t.name = $name",
            {"id": str(orphan), "name": "Nothing yet"},
        ).consume()

    result = run_template(driver, THREAD_TIMELINE, thread_id=orphan)

    assert isinstance(result, ThreadTimelineResult)
    assert result.thread is not None
    assert result.thread.name == "Nothing yet"
    assert result.meetings == ()
    assert result.mention_count == 0


def test_the_moment_timestamps_the_span_uses_are_utc(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """The projection writes offset-aware UTC and the traversal insists on it;
    this pins that the pair actually agree against the live store."""
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)

    result = run_template(
        driver, THREAD_TIMELINE, thread_id=thread_id_of(pool, "vendor feed")
    )

    assert isinstance(result, ThreadTimelineResult)
    for meeting in result.meetings:
        for mention in meeting.mentions:
            assert mention.started_at.tzinfo is not None
            assert mention.started_at.utcoffset() == timedelta(0)
    assert result.first_mention_at == min(
        mention.started_at for meeting in result.meetings for mention in meeting.mentions
    )


def test_a_rederivation_after_a_new_meeting_keeps_the_thread_node(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """Idempotent derivation is what makes the graph stable: the same
    `thread.id` comes back, so the `Thread` node is updated and not doubled."""
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)
    before = thread_id_of(pool, "vendor feed")

    with pool.connection() as conn:
        third = seed_meeting(
            conn,
            source_id="threads-graph-c",
            started_at=STARTED_AT + timedelta(days=14),
        )
        add_topic(
            conn,
            meeting_id=third.meeting_id,
            name="Vendor Feed",
            moment_ids=third.moment_ids[:1],
        )
    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder({**ORTHOGONAL, "Vendor Feed": (1.0, 0.0, 0.0)}))
    project(pool, app_config, third.meeting_id, fake_embedder)

    assert thread_id_of(pool, "vendor feed") == before
    assert counts(driver)["node:Thread"] == 2
    result = run_template(driver, THREAD_TIMELINE, thread_id=before)
    assert isinstance(result, ThreadTimelineResult)
    assert result.meeting_count == 3
    assert result.mention_count == 4


def test_the_graph_never_gates_topics_on_a_publish_state(
    pool: ConnectionPool, app_config: AppConfig, projection_stores: Any, fake_embedder: FakeEmbedder
) -> None:
    """AD-4, as clarified for 10.2: topics and threads are navigation metadata
    outside the publish gate. A meeting with no published artifact at all
    still gets its Topic and Thread nodes."""
    driver, _client = projection_stores
    first, second = seed_two_threaded_meetings(pool, app_config)
    project(pool, app_config, first, fake_embedder)
    project(pool, app_config, second, fake_embedder)

    assert counts(driver).get("node:Artifact", 0) == 0
    assert counts(driver)["node:Topic"] == 3
    assert counts(driver)["node:Thread"] == 2


def test_the_datetimes_this_module_pins_are_the_seeded_ones() -> None:
    """A guard on the fixtures: STARTED_AT must stay offset-aware, or every
    UTC assertion above would be comparing naive values and passing."""
    assert STARTED_AT.tzinfo is not None
    assert isinstance(STARTED_AT, datetime)
    assert STARTED_AT.utcoffset() == timedelta(0)
    assert STARTED_AT.tzinfo is timezone.utc or STARTED_AT.utcoffset() == timedelta(0)
