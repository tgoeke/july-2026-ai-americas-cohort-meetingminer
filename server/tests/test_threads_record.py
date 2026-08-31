"""Migration 0015 and the derivation's Postgres half (story 10.2).

Two halves. The schema contract pins what migration 0015 declares: the
`identity_key` uniqueness a rerun lands on, the one-thread-per-topic primary
key, the `linked_by`/`similarity` agreement, and the three no-orphan routes
(last link removed, link moved to another thread, `TRUNCATE`). The derivation
half runs `domain.threads.derive_threads` against the per-run test database and
pins the clause the acceptance criteria hinge on: a rerun over unchanged topics
yields the same threads, ids included.

DB-backed against the per-run test database (named skip when the compose
Postgres is down). Seeding is deliberately minimal — job, meeting, moment,
topic, mention inserted directly — so an assertion proves exactly the edge
under test and nothing a richer fixture happens to bring along. `topic`
carries a DEFERRABLE constraint trigger requiring a mention, so every topic
here is inserted with one inside the same transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import UUID

import pytest
from psycopg import Connection, errors
from psycopg_pool import ConnectionPool

from meetingminer.adapters.embed.port import EmbedderUnavailableError, Vector
from meetingminer.config import AppConfig
from meetingminer.domain.threads import derive_threads, normalized_topic_name

from conftest import truncate_evidence

STARTED_AT = datetime(2026, 8, 5, 12, 0, 19, tzinfo=timezone.utc)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


# --- seeding ---------------------------------------------------------------


def seed_meeting(conn: Connection, source_id: str, *, offset_days: int = 0) -> UUID:
    job_id = conn.execute(
        "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
        " VALUES (%s, %s, 'real', 'running') RETURNING id",
        (source_id, source_id),
    ).fetchone()[0]
    return conn.execute(
        "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
        " started_at_precision, title, has_recording, provenance)"
        " VALUES (%s, %s, 'real', %s, 'second', %s, false, '{}'::jsonb)"
        " RETURNING id",
        (job_id, source_id, STARTED_AT + timedelta(days=offset_days), source_id),
    ).fetchone()[0]


def add_moment(conn: Connection, meeting_id: UUID, start_ms: int = 0) -> UUID:
    return conn.execute(
        "INSERT INTO moment (meeting_id, identity_key, derived_from, start_ms,"
        " end_ms, started_at, started_at_precision)"
        " VALUES (%s, %s, 'transcript', %s, %s, %s, 'second') RETURNING id",
        (meeting_id, f"transcript:{start_ms}", start_ms, start_ms + 10_000, STARTED_AT),
    ).fetchone()[0]


def add_topic(conn: Connection, meeting_id: UUID, name: str, *, start_ms: int = 0) -> UUID:
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
    return topic_id


def add_thread(conn: Connection, *, identity_key: str, topic_ids: Sequence[UUID]) -> UUID:
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


# --- a deterministic stub embedder -----------------------------------------


class StubEmbedder:
    """Vectors chosen by the test, keyed on the exact text embedded.

    Not `conftest.FakeEmbedder`: that one hashes text into a vector, so the
    cosine between two chosen strings is whatever the hash happens to give and
    a similarity assertion would be pinning an accident. Here the test states
    the geometry it means, and an unlisted text is a loud KeyError rather than
    a silently-plausible vector.
    """

    model = "stub-embedder"
    dimension = 3

    def __init__(self, vectors: dict[str, Sequence[float]]) -> None:
        self._vectors = {text: tuple(float(v) for v in vec) for text, vec in vectors.items()}
        self.calls = 0

    def embed_documents(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        self.calls += 1
        return tuple(self._vectors[text] for text in texts)

    def embed_query(self, text: str) -> Vector:
        return self._vectors[text]


class DownEmbedder:
    """The model host is not running — the one failure that must roll back."""

    model = "down-embedder"
    dimension = 3

    def embed_documents(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        raise EmbedderUnavailableError("ollama is not reachable at http://localhost:11434")

    def embed_query(self, text: str) -> Vector:
        raise EmbedderUnavailableError("ollama is not reachable at http://localhost:11434")


ORTHOGONAL = {
    "Vendor feed": (1.0, 0.0, 0.0),
    "vendor feed": (1.0, 0.0, 0.0),
    "Vendor  Feed.": (1.0, 0.0, 0.0),
    "Release plan": (0.0, 1.0, 0.0),
    "Budget review": (0.0, 0.0, 1.0),
}


# --- schema contract -------------------------------------------------------


def test_identity_key_is_unique_so_a_rerun_lands_on_the_same_row(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-identity")
        first = add_topic(conn, meeting_id, "Vendor feed")
        second = add_topic(conn, meeting_id, "Release plan", start_ms=20_000)
        add_thread(conn, identity_key="vendor feed", topic_ids=[first])
        with pytest.raises(errors.UniqueViolation):
            add_thread(conn, identity_key="vendor feed", topic_ids=[second])


def test_a_topic_belongs_to_exactly_one_thread(pool: ConnectionPool) -> None:
    """`topic_thread.topic_id` is the PRIMARY KEY, not half of a composite."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-one-per-topic")
        topic_id = add_topic(conn, meeting_id, "Vendor feed")
        other = add_topic(conn, meeting_id, "Release plan", start_ms=20_000)
        add_thread(conn, identity_key="vendor feed", topic_ids=[topic_id])
        second = add_thread(conn, identity_key="release plan", topic_ids=[other])
        with pytest.raises(errors.UniqueViolation):
            conn.execute(
                "INSERT INTO topic_thread (topic_id, thread_id, linked_by)"
                " VALUES (%s, %s, 'seed')",
                (topic_id, second),
            )


def test_a_thread_with_no_topic_is_refused_at_commit(pool: ConnectionPool) -> None:
    """The DEFERRABLE constraint trigger, mirroring 0014's `topic`."""
    # `23514` is check_violation, which psycopg maps to `CheckViolation` — the
    # same errcode 0014's `topic_requires_mention` raises, deliberately, so a
    # missing-child refusal reads the same whichever table raised it.
    with pytest.raises(errors.CheckViolation) as excinfo:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO thread (identity_key, name, link_rule)"
                " VALUES ('orphan', 'orphan', 'normalized-name-or-embedding-similarity')"
            )
    assert "requires at least one topic" in str(excinfo.value)


def test_removing_the_last_membership_removes_the_thread(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-last-link")
        topic_id = add_topic(conn, meeting_id, "Vendor feed")
        thread_id = add_thread(conn, identity_key="vendor feed", topic_ids=[topic_id])
        conn.execute("DELETE FROM topic_thread WHERE topic_id = %s", (topic_id,))
        assert _thread_count(conn, thread_id) == 0


def test_moving_the_last_membership_removes_the_emptied_thread(pool: ConnectionPool) -> None:
    """The re-derivation route: a cluster's members all move elsewhere."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-move")
        moved = add_topic(conn, meeting_id, "Vendor feed")
        keeper = add_topic(conn, meeting_id, "Release plan", start_ms=20_000)
        emptied = add_thread(conn, identity_key="vendor feed", topic_ids=[moved])
        survivor = add_thread(conn, identity_key="release plan", topic_ids=[keeper])
        conn.execute(
            "UPDATE topic_thread SET thread_id = %s WHERE topic_id = %s", (survivor, moved)
        )
        assert _thread_count(conn, emptied) == 0
        assert _thread_count(conn, survivor) == 1


def test_deleting_the_topic_cascades_and_removes_the_emptied_thread(pool: ConnectionPool) -> None:
    """An extraction rerun replaces a meeting's topics wholesale (0014)."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-cascade")
        topic_id = add_topic(conn, meeting_id, "Vendor feed")
        thread_id = add_thread(conn, identity_key="vendor feed", topic_ids=[topic_id])
        conn.execute("DELETE FROM topic WHERE id = %s", (topic_id,))
        assert _thread_count(conn, thread_id) == 0


def test_truncating_memberships_removes_every_thread(pool: ConnectionPool) -> None:
    """Row triggers do not fire for TRUNCATE; the statement trigger does."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-truncate")
        topic_id = add_topic(conn, meeting_id, "Vendor feed")
        add_thread(conn, identity_key="vendor feed", topic_ids=[topic_id])
        conn.execute("TRUNCATE topic_thread")
        assert conn.execute("SELECT count(*) FROM thread").fetchone()[0] == 0


def test_an_embedding_link_must_carry_its_similarity(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-similarity")
        seed = add_topic(conn, meeting_id, "Vendor feed")
        joiner = add_topic(conn, meeting_id, "Release plan", start_ms=20_000)
        thread_id = add_thread(conn, identity_key="vendor feed", topic_ids=[seed])
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "INSERT INTO topic_thread (topic_id, thread_id, linked_by)"
                " VALUES (%s, %s, 'embedding-similarity')",
                (joiner, thread_id),
            )


def test_a_name_link_must_not_carry_a_similarity(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-name-similarity")
        seed = add_topic(conn, meeting_id, "Vendor feed")
        joiner = add_topic(conn, meeting_id, "Release plan", start_ms=20_000)
        thread_id = add_thread(conn, identity_key="vendor feed", topic_ids=[seed])
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "INSERT INTO topic_thread (topic_id, thread_id, linked_by, similarity)"
                " VALUES (%s, %s, 'normalized-name', 0.9)",
                (joiner, thread_id),
            )


def test_an_unknown_linked_by_leg_is_refused(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-leg")
        seed = add_topic(conn, meeting_id, "Vendor feed")
        joiner = add_topic(conn, meeting_id, "Release plan", start_ms=20_000)
        thread_id = add_thread(conn, identity_key="vendor feed", topic_ids=[seed])
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "INSERT INTO topic_thread (topic_id, thread_id, linked_by)"
                " VALUES (%s, %s, 'vibes')",
                (joiner, thread_id),
            )


def _thread_count(conn: Connection, thread_id: UUID) -> int:
    return conn.execute(
        "SELECT count(*) FROM thread WHERE id = %s", (thread_id,)
    ).fetchone()[0]


# --- the derivation over Postgres ------------------------------------------


def membership(conn: Connection) -> list[tuple[str, str, str, str]]:
    """(topic name, thread identity_key, thread name, linked_by), sorted."""
    return sorted(
        (row[0], row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT t.name, th.identity_key, th.name, tt.linked_by"
            " FROM topic t JOIN topic_thread tt ON tt.topic_id = t.id"
            " JOIN thread th ON th.id = tt.thread_id"
        ).fetchall()
    )


def thread_rows(conn: Connection) -> list[tuple[UUID, str, str]]:
    return sorted(
        (row[0], row[1], row[2])
        for row in conn.execute("SELECT id, identity_key, name FROM thread").fetchall()
    )


def test_topics_with_the_same_normalized_name_share_one_thread(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        first = seed_meeting(conn, "threads-name-a")
        second = seed_meeting(conn, "threads-name-b", offset_days=1)
        add_topic(conn, first, "Vendor feed")
        add_topic(conn, second, "Vendor  Feed.")

    with pool.connection() as conn:
        report = derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))

    assert report.thread_count == 1
    assert report.topic_count == 2
    with pool.connection() as conn:
        assert membership(conn) == [
            ("Vendor  Feed.", "vendor feed", "Vendor feed", "normalized-name"),
            ("Vendor feed", "vendor feed", "Vendor feed", "seed"),
        ]


def test_the_seed_is_the_earliest_topic_so_the_thread_is_named_for_where_it_started(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        later = seed_meeting(conn, "threads-seed-later", offset_days=5)
        earlier = seed_meeting(conn, "threads-seed-earlier")
        add_topic(conn, later, "Vendor  Feed.")
        add_topic(conn, earlier, "Vendor feed")

    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))

    with pool.connection() as conn:
        rows = thread_rows(conn)
    assert [(row[1], row[2]) for row in rows] == [("vendor feed", "Vendor feed")]


def test_similar_topics_link_and_the_row_records_the_score(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    threshold = app_config.settings.threads.embedding_similarity_threshold
    vectors = {"Purchase order approvals": (1.0, 0.0, 0.0), "PO sign-off": (0.95, 0.3122499, 0.0)}
    with pool.connection() as conn:
        first = seed_meeting(conn, "threads-embed-a")
        second = seed_meeting(conn, "threads-embed-b", offset_days=1)
        add_topic(conn, first, "Purchase order approvals")
        add_topic(conn, second, "PO sign-off")

    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder(vectors))

    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM thread").fetchone()[0] == 1
        score = conn.execute(
            "SELECT similarity FROM topic_thread WHERE linked_by = 'embedding-similarity'"
        ).fetchone()[0]
    assert score >= threshold


def test_dissimilar_topics_stay_in_separate_threads(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        first = seed_meeting(conn, "threads-apart-a")
        second = seed_meeting(conn, "threads-apart-b", offset_days=1)
        add_topic(conn, first, "Vendor feed")
        add_topic(conn, second, "Budget review")

    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))

    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM thread").fetchone()[0] == 2


def test_a_rerun_over_unchanged_topics_yields_the_same_threads(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    """The clause the acceptance criteria hinge on — ids included.

    Not "the same shape": the same `thread.id` values. Every downstream
    reference (the graph node key, 10.2a's curation, 10.3's timeline) keys on
    that id, so a derivation that re-minted rows on an unchanged rerun would
    satisfy a set-equality assertion and still break every one of them.
    """
    with pool.connection() as conn:
        first = seed_meeting(conn, "threads-idem-a")
        second = seed_meeting(conn, "threads-idem-b", offset_days=1)
        third = seed_meeting(conn, "threads-idem-c", offset_days=2)
        add_topic(conn, first, "Vendor feed")
        add_topic(conn, second, "vendor feed")
        add_topic(conn, third, "Budget review")

    with pool.connection() as conn:
        first_report = derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))
    with pool.connection() as conn:
        after_first = thread_rows(conn)
        membership_first = membership(conn)
        stamps_first = conn.execute(
            "SELECT id, created_at, updated_at FROM thread ORDER BY id"
        ).fetchall()

    with pool.connection() as conn:
        second_report = derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))
    with pool.connection() as conn:
        after_second = thread_rows(conn)
        membership_second = membership(conn)
        stamps_second = conn.execute(
            "SELECT id, created_at, updated_at FROM thread ORDER BY id"
        ).fetchall()

    assert after_second == after_first
    assert membership_second == membership_first
    assert stamps_second == stamps_first, (
        "an unchanged rerun re-minted or rewrote thread rows: identical"
        " created_at AND updated_at is what makes 'the derivation changed"
        " nothing' observable rather than merely plausible"
    )
    assert (second_report.thread_count, second_report.topic_count) == (
        first_report.thread_count,
        first_report.topic_count,
    )


def test_a_rerun_after_a_topic_moves_empties_and_removes_its_old_thread(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        first = seed_meeting(conn, "threads-remove-a")
        second = seed_meeting(conn, "threads-remove-b", offset_days=1)
        add_topic(conn, first, "Vendor feed")
        add_topic(conn, second, "Budget review")
    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM thread").fetchone()[0] == 2
        conn.execute("UPDATE topic SET name = 'Vendor feed' WHERE name = 'Budget review'")

    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))

    with pool.connection() as conn:
        assert [row[1] for row in thread_rows(conn)] == ["vendor feed"]


def test_an_unreachable_model_host_writes_nothing(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    """No silent fallback: the name leg alone is not a successful derivation."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-down")
        add_topic(conn, meeting_id, "Vendor feed")
        add_topic(conn, meeting_id, "Release plan", start_ms=20_000)

    with pool.connection() as conn:
        with pytest.raises(EmbedderUnavailableError):
            derive_threads(conn, app_config, embedder=DownEmbedder())

    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM thread").fetchone()[0] == 0


def test_a_corpus_with_no_topics_derives_nothing(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    embedder = StubEmbedder(ORTHOGONAL)
    with pool.connection() as conn:
        report = derive_threads(conn, app_config, embedder=embedder)
    assert (report.thread_count, report.topic_count) == (0, 0)
    assert embedder.calls == 0, "an empty corpus must not call the model host at all"


def test_the_derivation_records_its_parameters_on_every_thread(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-provenance")
        add_topic(conn, meeting_id, "Vendor feed")

    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))

    with pool.connection() as conn:
        link_rule, derivation = conn.execute(
            "SELECT link_rule, derivation FROM thread"
        ).fetchone()
    assert link_rule == app_config.settings.threads.link_rule
    assert derivation["embedder_model"] == "stub-embedder"
    assert derivation["embedder_dimension"] == 3
    assert derivation["embedding_similarity_threshold"] == pytest.approx(
        app_config.settings.threads.embedding_similarity_threshold
    )


def test_normalization_is_what_the_identity_key_records(
    pool: ConnectionPool, app_config: AppConfig
) -> None:
    """The stored key is exactly `normalized_topic_name` of the seed."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "threads-key")
        add_topic(conn, meeting_id, "Vendor  Feed.")

    with pool.connection() as conn:
        derive_threads(conn, app_config, embedder=StubEmbedder(ORTHOGONAL))

    with pool.connection() as conn:
        identity_key = conn.execute("SELECT identity_key FROM thread").fetchone()[0]
    assert identity_key == normalized_topic_name("Vendor  Feed.")
