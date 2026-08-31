"""Migration 0017's colour ordinal and `GET /threads` (story 10.3).

Two halves, and the split is deliberate. The first pins what the *record*
guarantees about `thread.color_ordinal`: allocated once from a sequence,
positive, unique under concurrency, and immutable afterwards — the properties
a merge survivor and a split product rest on, enforced in Postgres rather than
in whichever caller happens to write the row. The second pins the list route
those ordinals are served through.

DB-backed against the per-run test database (a named skip when the compose
Postgres is down). Seeding is deliberately minimal — job, meeting, moment,
topic, mention, thread inserted directly — following `test_threads_record.py`,
so an assertion proves exactly the edge under test.

Nothing here asserts an *absolute* ordinal value. `TRUNCATE` does not reset a
sequence, so ordinals keep climbing across the session; only relations
(distinct, positive, unchanged, increasing) are stable facts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from psycopg import Connection, errors
from psycopg_pool import ConnectionPool

from conftest import truncate_evidence

STARTED_AT = datetime(2026, 8, 5, 12, 0, 19, tzinfo=timezone.utc)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


# --- seeding ---------------------------------------------------------------


def seed_meeting(
    conn: Connection,
    source_id: str,
    *,
    offset_days: int = 0,
    precision: str = "second",
    started_at: datetime | None = None,
    has_recording: bool = False,
) -> UUID:
    job_id = conn.execute(
        "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
        " VALUES (%s, %s, 'real', 'running') RETURNING id",
        (source_id, source_id),
    ).fetchone()[0]
    start = started_at if started_at is not None else STARTED_AT + timedelta(days=offset_days)
    return conn.execute(
        "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
        " started_at_precision, title, has_recording, provenance)"
        " VALUES (%s, %s, 'real', %s, %s, %s, %s, '{}'::jsonb)"
        " RETURNING id",
        (job_id, source_id, start, precision, source_id, has_recording),
    ).fetchone()[0]


def add_moment(conn: Connection, meeting_id: UUID, start_ms: int = 0) -> UUID:
    return conn.execute(
        "INSERT INTO moment (meeting_id, identity_key, derived_from, start_ms,"
        " end_ms, started_at, started_at_precision)"
        " VALUES (%s, %s, 'transcript', %s, %s, %s, 'second') RETURNING id",
        (meeting_id, f"transcript:{start_ms}", start_ms, start_ms + 10_000, STARTED_AT),
    ).fetchone()[0]


def add_topic(
    conn: Connection, meeting_id: UUID, name: str, *, start_ms: int = 0
) -> tuple[UUID, UUID]:
    """One topic with the one mention `topic`'s deferred trigger requires."""
    moment_id = add_moment(conn, meeting_id, start_ms)
    topic_id = conn.execute(
        "INSERT INTO topic (meeting_id, name, gist) VALUES (%s, %s, %s) RETURNING id",
        (meeting_id, name, f"a one-line gist for {name}"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)"
        " VALUES (%s, %s, %s, %s)",
        (topic_id, moment_id, meeting_id, start_ms),
    )
    return topic_id, moment_id


def add_thread(
    conn: Connection, *, identity_key: str, topic_ids: Sequence[UUID] = ()
) -> UUID:
    thread_id = conn.execute(
        "INSERT INTO thread (identity_key, name, link_rule)"
        " VALUES (%s, %s, 'normalized-name-or-embedding-similarity') RETURNING id",
        (identity_key, identity_key),
    ).fetchone()[0]
    for topic_id in topic_ids:
        conn.execute(
            "INSERT INTO topic_thread (topic_id, thread_id, linked_by)"
            " VALUES (%s, %s, 'seed')",
            (topic_id, thread_id),
        )
    return thread_id


def ordinal_of(conn: Connection, thread_id: UUID) -> int:
    return conn.execute(
        "SELECT color_ordinal FROM thread WHERE id = %s", (thread_id,)
    ).fetchone()[0]


# --- the record: migration 0017 --------------------------------------------


def test_insert_allocates_a_positive_ordinal_without_being_asked(
    pool: ConnectionPool,
) -> None:
    """A caller that names no ordinal still gets one, and it is positive.

    `domain/threads.py` inserts `(identity_key, name, link_rule, derivation)`
    and nothing else, so allocation has to happen in the record or it does not
    happen at all.
    """
    with pool.connection() as conn:
        thread_id = add_thread(conn, identity_key="sftp migration")
        assert ordinal_of(conn, thread_id) > 0


def test_two_threads_never_share_an_ordinal(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        first = add_thread(conn, identity_key="one")
        second = add_thread(conn, identity_key="two")
        assert ordinal_of(conn, first) != ordinal_of(conn, second)


def test_concurrent_creates_allocate_distinct_ordinals(pool: ConnectionPool) -> None:
    """Two open transactions, neither committed, must already differ.

    This is the whole reason the allocator is a sequence rather than
    `SELECT max(color_ordinal) + 1`: that read would give both sessions the
    same answer under any isolation level that does not serialize them, and
    the `UNIQUE` constraint would turn a colour clash into a failed thread
    derivation. `nextval` is exempt from transaction visibility, so it cannot.
    """
    with pool.connection() as first_conn, pool.connection() as second_conn:
        # A bounded wait, so a *wrong* allocator fails this test instead of
        # hanging it. `max(color_ordinal) + 1` hands both sessions the same
        # number, and the second insert then blocks on the UNIQUE index until
        # the first transaction ends rather than raising — an unbounded wait
        # that would look like a hung suite rather than a caught defect.
        for conn in (first_conn, second_conn):
            conn.execute("SET lock_timeout = '5s'")
        first_conn.execute("BEGIN")
        second_conn.execute("BEGIN")
        first = add_thread(first_conn, identity_key="concurrent-a")
        second = add_thread(second_conn, identity_key="concurrent-b")
        first_ordinal = ordinal_of(first_conn, first)
        second_ordinal = ordinal_of(second_conn, second)
        assert first_ordinal != second_ordinal
        first_conn.commit()
        second_conn.commit()


def test_a_rolled_back_create_never_returns_its_ordinal(pool: ConnectionPool) -> None:
    """"Never recycled" is stronger than "no gaps": a burnt value stays burnt."""
    with pool.connection() as conn:
        conn.execute("BEGIN")
        abandoned = add_thread(conn, identity_key="abandoned")
        burnt = ordinal_of(conn, abandoned)
        conn.rollback()
        survivor = add_thread(conn, identity_key="survivor")
        assert ordinal_of(conn, survivor) > burnt


def test_a_merge_survivor_keeps_its_ordinal_across_updates(
    pool: ConnectionPool,
) -> None:
    """What 10.2a's merge does to the survivor row must not recolour it.

    A merge renames the survivor and moves the loser's memberships onto it.
    Both are `UPDATE`s on `thread` / `topic_thread`; neither may touch the
    ordinal, and the survivor's own `updated_at` trigger must not either.
    """
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "merge-source")
        survivor_topic, _ = add_topic(conn, meeting_id, "SFTP Migration")
        loser_topic, _ = add_topic(conn, meeting_id, "sftp migration", start_ms=60_000)
        survivor = add_thread(conn, identity_key="survivor", topic_ids=[survivor_topic])
        loser = add_thread(conn, identity_key="loser", topic_ids=[loser_topic])
        before = ordinal_of(conn, survivor)

        conn.execute("UPDATE thread SET name = %s WHERE id = %s", ("SFTP", survivor))
        conn.execute(
            "UPDATE topic_thread SET thread_id = %s WHERE thread_id = %s",
            (survivor, loser),
        )
        assert ordinal_of(conn, survivor) == before


def test_updating_the_ordinal_is_refused_by_the_record(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        thread_id = add_thread(conn, identity_key="immutable")
        current = ordinal_of(conn, thread_id)
        with pytest.raises(errors.RaiseException) as excinfo:
            conn.execute(
                "UPDATE thread SET color_ordinal = %s WHERE id = %s",
                (current + 1_000, thread_id),
            )
        assert "color_ordinal" in str(excinfo.value)


def test_a_split_product_receives_a_new_ordinal(pool: ConnectionPool) -> None:
    """Splitting mints a second `thread` row; it must not inherit a colour."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "split-source")
        kept_topic, _ = add_topic(conn, meeting_id, "Kept")
        moved_topic, _ = add_topic(conn, meeting_id, "Moved", start_ms=60_000)
        original = add_thread(
            conn, identity_key="original", topic_ids=[kept_topic, moved_topic]
        )
        original_ordinal = ordinal_of(conn, original)

        product = add_thread(conn, identity_key="split-product")
        conn.execute(
            "UPDATE topic_thread SET thread_id = %s WHERE topic_id = %s",
            (product, moved_topic),
        )
        assert ordinal_of(conn, product) > original_ordinal
        assert ordinal_of(conn, original) == original_ordinal


def test_a_deleted_threads_ordinal_is_not_handed_out_again(
    pool: ConnectionPool,
) -> None:
    with pool.connection() as conn:
        doomed = add_thread(conn, identity_key="doomed")
        doomed_ordinal = ordinal_of(conn, doomed)
        conn.execute("DELETE FROM thread WHERE id = %s", (doomed,))
        replacement = add_thread(conn, identity_key="replacement")
        assert ordinal_of(conn, replacement) > doomed_ordinal


def test_a_non_positive_ordinal_is_refused(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "INSERT INTO thread (identity_key, name, link_rule, color_ordinal)"
                " VALUES ('zero', 'zero', 'seed', 0)"
            )


def test_an_explicit_import_ordinal_advances_the_sequence_past_itself(
    pool: ConnectionPool,
) -> None:
    """An import may carry ordinals in; a later `nextval` must clear them.

    Without the advance, restoring a corpus whose ordinals reach 5000 would
    hand the next derived thread a colliding value and the `UNIQUE` constraint
    would fail the derivation.
    """
    with pool.connection() as conn:
        imported = conn.execute(
            "INSERT INTO thread (identity_key, name, link_rule, color_ordinal)"
            " VALUES ('imported', 'imported', 'seed', 500000) RETURNING id"
        ).fetchone()[0]
        assert ordinal_of(conn, imported) == 500000
        minted = add_thread(conn, identity_key="after-import")
        assert ordinal_of(conn, minted) > 500000


# --- GET /threads ----------------------------------------------------------


def test_thread_list_serves_the_acceptance_criteria_fields(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        first_meeting = seed_meeting(conn, "m1")
        second_meeting = seed_meeting(conn, "m2", offset_days=2)
        topic_a, _ = add_topic(conn, first_meeting, "SFTP Migration", start_ms=30_000)
        topic_b, _ = add_topic(conn, second_meeting, "SFTP Migration", start_ms=90_000)
        thread_id = add_thread(
            conn, identity_key="sftp migration", topic_ids=[topic_a, topic_b]
        )
        ordinal = ordinal_of(conn, thread_id)

    response = client.get("/threads")
    assert response.status_code == 200
    threads = response.json()["threads"]
    assert len(threads) == 1
    assert threads[0] == {
        "threadId": str(thread_id),
        "name": "sftp migration",
        "mentionCount": 2,
        "meetingCount": 2,
        "firstMentionAt": "2026-08-05T12:00:49Z",
        "lastMentionAt": "2026-08-07T12:01:49Z",
        "colorOrdinal": ordinal,
        # Story 10.2a. False here because nothing curated this thread. The
        # field is served on every row, not only curated ones, so a client can
        # tell a human name from a derived one without a second request.
        "nameIsCurated": False,
    }


def test_thread_list_omits_an_identity_row_with_no_membership(
    client: TestClient, pool: ConnectionPool
) -> None:
    """0015 keeps an emptied thread as a reuse target; it is not navigable."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "m1")
        topic_id, _ = add_topic(conn, meeting_id, "Live")
        live = add_thread(conn, identity_key="live", topic_ids=[topic_id])
        add_thread(conn, identity_key="emptied")

    threads = client.get("/threads").json()["threads"]
    assert [t["threadId"] for t in threads] == [str(live)]


def test_thread_list_orders_by_most_recent_mention_first(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        old_meeting = seed_meeting(conn, "old")
        recent_meeting = seed_meeting(conn, "recent", offset_days=5)
        old_topic, _ = add_topic(conn, old_meeting, "Old Subject")
        recent_topic, _ = add_topic(conn, recent_meeting, "Recent Subject")
        old = add_thread(conn, identity_key="old subject", topic_ids=[old_topic])
        recent = add_thread(
            conn, identity_key="recent subject", topic_ids=[recent_topic]
        )

    threads = client.get("/threads").json()["threads"]
    assert [t["threadId"] for t in threads] == [str(recent), str(old)]


def test_thread_list_ordinals_survive_a_rederivation(
    client: TestClient, pool: ConnectionPool
) -> None:
    """The list is re-read after membership churn; colours do not move."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "m1")
        topic_id, _ = add_topic(conn, meeting_id, "Subject")
        thread_id = add_thread(conn, identity_key="subject", topic_ids=[topic_id])

    before = {t["threadId"]: t["colorOrdinal"] for t in client.get("/threads").json()["threads"]}

    with pool.connection() as conn:
        second_meeting = seed_meeting(conn, "m2", offset_days=1)
        later_topic, _ = add_topic(conn, second_meeting, "Subject")
        conn.execute(
            "INSERT INTO topic_thread (topic_id, thread_id, linked_by)"
            " VALUES (%s, %s, 'normalized-name')",
            (later_topic, thread_id),
        )

    after = {t["threadId"]: t["colorOrdinal"] for t in client.get("/threads").json()["threads"]}
    assert after == before
