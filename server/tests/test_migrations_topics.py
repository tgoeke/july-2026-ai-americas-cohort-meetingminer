"""Schema contract for migration 0014 (story 10.1): `topic` / `topic_mention`.

DB-backed against the per-run test database (named skip when the compose
Postgres is down). Seeding is deliberately minimal — one job, one meeting,
one moment, inserted directly — so a cascade assertion proves exactly the
edge under test and nothing a richer fixture happens to bring along.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from psycopg import Connection, errors
from psycopg_pool import ConnectionPool

from conftest import truncate_evidence

STARTED_AT = datetime(2026, 8, 5, 12, 0, 19, tzinfo=timezone.utc)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


def seed_meeting_with_moment(
    conn: Connection, source_id: str, start_ms: int = 0
) -> tuple[UUID, UUID]:
    job_id = conn.execute(
        "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
        " VALUES (%s, %s, 'real', 'running') RETURNING id",
        (source_id, source_id),
    ).fetchone()[0]
    meeting_id = conn.execute(
        "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
        " started_at_precision, title, has_recording, provenance)"
        " VALUES (%s, %s, 'real', %s, 'second', 'Topics Migration Test',"
        " false, '{}'::jsonb) RETURNING id",
        (job_id, source_id, STARTED_AT),
    ).fetchone()[0]
    return meeting_id, add_moment(conn, meeting_id, start_ms)


def add_moment(conn: Connection, meeting_id: UUID, start_ms: int) -> UUID:
    return conn.execute(
        "INSERT INTO moment (meeting_id, identity_key, derived_from, start_ms,"
        " end_ms, started_at, started_at_precision)"
        " VALUES (%s, %s, 'transcript', %s, %s, %s, 'second') RETURNING id",
        (
            meeting_id,
            f"transcript:{start_ms}",
            start_ms,
            start_ms + 10_000,
            STARTED_AT,
        ),
    ).fetchone()[0]


def add_topic(conn: Connection, meeting_id: UUID, name: str = "Vendor feed") -> UUID:
    return conn.execute(
        "INSERT INTO topic (meeting_id, name, gist)"
        " VALUES (%s, %s, 'A one-line gist') RETURNING id",
        (meeting_id, name),
    ).fetchone()[0]


def add_mention(
    conn: Connection,
    topic_id: UUID,
    moment_id: UUID,
    meeting_id: UUID,
    anchor_ms: int = 1_000,
) -> None:
    conn.execute(
        "INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)"
        " VALUES (%s, %s, %s, %s)",
        (topic_id, moment_id, meeting_id, anchor_ms),
    )


def count(conn: Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_both_tables_exist_with_the_expected_columns(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        columns = {
            table: {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = %s",
                    (table,),
                ).fetchall()
            }
            for table in ("topic", "topic_mention")
        }
    assert columns["topic"] == {
        "id",
        "meeting_id",
        "name",
        "gist",
        "provenance",
        "created_at",
        "updated_at",
    }
    assert columns["topic_mention"] == {"topic_id", "moment_id", "meeting_id", "anchor_ms"}


def test_a_mention_may_only_name_a_moment_of_its_own_meeting(
    pool: ConnectionPool,
) -> None:
    with pool.connection() as conn:
        meeting_a, moment_a = seed_meeting_with_moment(conn, "mig-topics-a")
        meeting_b, moment_b = seed_meeting_with_moment(conn, "mig-topics-b")
        topic_id = add_topic(conn, meeting_a)
        # The straight case works…
        add_mention(conn, topic_id, moment_a, meeting_a)
    # …and the cross-meeting pair is refused by the composite FK: the
    # (moment, meeting) pair does not exist on `moment`.
    with pool.connection() as conn:
        with pytest.raises(errors.ForeignKeyViolation):
            add_mention(conn, topic_id, moment_b, meeting_a)
    # Supplying meeting B consistently with moment B must not smuggle topic A
    # across the meeting boundary either.
    with pool.connection() as conn:
        with pytest.raises(errors.ForeignKeyViolation):
            add_mention(conn, topic_id, moment_b, meeting_b)


def test_the_primary_key_makes_the_per_moment_collapse_a_constraint(
    pool: ConnectionPool,
) -> None:
    with pool.connection() as conn:
        meeting_id, moment_id = seed_meeting_with_moment(conn, "mig-topics-pk")
        topic_id = add_topic(conn, meeting_id)
        add_mention(conn, topic_id, moment_id, meeting_id, anchor_ms=1_000)
    with pool.connection() as conn:
        with pytest.raises(errors.UniqueViolation):
            add_mention(conn, topic_id, moment_id, meeting_id, anchor_ms=2_000)


def test_a_negative_anchor_is_refused(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id, moment_id = seed_meeting_with_moment(conn, "mig-topics-neg")
        topic_id = add_topic(conn, meeting_id)
    with pool.connection() as conn:
        with pytest.raises(errors.CheckViolation):
            add_mention(conn, topic_id, moment_id, meeting_id, anchor_ms=-1)


def test_deleting_a_topic_cascades_its_mentions(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id, moment_id = seed_meeting_with_moment(conn, "mig-topics-cascade")
        topic_id = add_topic(conn, meeting_id)
        add_mention(conn, topic_id, moment_id, meeting_id)
        conn.execute("DELETE FROM topic WHERE id = %s", (topic_id,))
        assert count(conn, "topic_mention") == 0
        # The moment itself is untouched: mentions are metadata, not evidence.
        assert count(conn, "moment") == 1


def test_deleting_a_meeting_cascades_topics_and_mentions(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id, moment_id = seed_meeting_with_moment(conn, "mig-topics-meeting")
        topic_id = add_topic(conn, meeting_id)
        add_mention(conn, topic_id, moment_id, meeting_id)
        conn.execute("DELETE FROM meeting WHERE id = %s", (meeting_id,))
        assert count(conn, "topic") == 0
        assert count(conn, "topic_mention") == 0


def test_deleting_a_topics_last_mentioned_moment_deletes_the_topic(
    pool: ConnectionPool,
) -> None:
    with pool.connection() as conn:
        meeting_id, moment_id = seed_meeting_with_moment(conn, "mig-topics-moment")
        topic_id = add_topic(conn, meeting_id)
        add_mention(conn, topic_id, moment_id, meeting_id)
        conn.execute("DELETE FROM moment WHERE id = %s", (moment_id,))
        assert count(conn, "topic_mention") == 0
        assert count(conn, "topic") == 0


def test_deleting_one_of_two_mentioned_moments_preserves_the_topic(
    pool: ConnectionPool,
) -> None:
    with pool.connection() as conn:
        meeting_id, first_moment = seed_meeting_with_moment(
            conn, "mig-topics-two-moments"
        )
        second_moment = add_moment(conn, meeting_id, 20_000)
        topic_id = add_topic(conn, meeting_id)
        add_mention(conn, topic_id, first_moment, meeting_id)
        add_mention(conn, topic_id, second_moment, meeting_id, anchor_ms=20_000)
        conn.execute("DELETE FROM moment WHERE id = %s", (first_moment,))
        assert count(conn, "topic_mention") == 1
        assert count(conn, "topic") == 1


def test_extraction_source_accepts_topics_and_rejects_a_fourth_kind(
    pool: ConnectionPool,
) -> None:
    def insert_source(conn: Connection, meeting_id: UUID, kind: str) -> None:
        conn.execute(
            "INSERT INTO extraction_source (meeting_id, kind, origin, sha256,"
            " byte_size, layout, item_count, artifact_count)"
            " VALUES (%s, %s, 'generated', 'deadbeef', 0, 'none', 0, 0)",
            (meeting_id, kind),
        )

    with pool.connection() as conn:
        meeting_id, _moment_id = seed_meeting_with_moment(conn, "mig-topics-source")
        insert_source(conn, meeting_id, "topics")
        assert count(conn, "extraction_source") == 1
    with pool.connection() as conn:
        with pytest.raises(errors.CheckViolation):
            insert_source(conn, meeting_id, "threads")
