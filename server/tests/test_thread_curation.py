"""Thread curation, and its one real question: does it survive the rerun?

Story 10.2a (FR42). Merge, split and rename are easy; the acceptance criterion
that carries the story is that a correction "survives every rerun and
re-derivation of story 10.2". Story 10.2's derivation re-derives every thread
from the stored topics on every pass, reusing rows by content key, rewriting
`thread.name` from the seed topic and moving memberships — so a curation that
sat in those columns would be reversed by the next pass, silently. The tests
below are therefore weighted deliberately: the API's own refusals get one
assertion each, and *every* curation gets a `derive_threads` run after it with
the correction re-asserted on the far side.

Four hazards are pinned by name, because each is a way the correction could be
lost that no ordinary end-to-end assertion would catch:

* **Rename** — the derivation rewrites `thread.name` on every pass. Pinned by
  changing the seed topic's own name between passes, so the *derived* name
  genuinely moves underneath the curated one.
* **Merge** — the absorbed thread's cluster still exists and still re-derives.
  Pinned by asserting the absorbed thread keeps its row and its ordinal while
  its memberships resolve to the survivor.
* **Split** — the curated thread is attached to exactly the topics that were
  split onto it, so the ordinary attachment-reuse path would hand it straight
  back to the cluster the split was correcting. Pinned by asserting the
  curated row keeps its own identity key and name after a pass.
* **Re-extraction** — story 10.1 replaces a meeting's `topic` rows wholesale
  with fresh UUIDs. A pin keyed on `topic_id` would vanish with them. Pinned
  by deleting and recreating the topics under their own names and re-deriving.

DB-backed against the per-run test database (named skip when the compose
Postgres is down), seeded minimally in the style of `test_threads_record.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import Connection, errors
from psycopg_pool import ConnectionPool

from meetingminer.adapters.embed.port import Vector
from meetingminer.config import AppConfig
from meetingminer.domain.thread_curation import (
    CURATED_LINK_RULE,
    ThreadCurationError,
    is_curated_identity_key,
    pin_content_key,
)
from meetingminer.domain.threads import derive_threads

from conftest import truncate_evidence

STARTED_AT = datetime(2026, 8, 5, 12, 0, 19, tzinfo=timezone.utc)

@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


class StubEmbedder:
    """Every distinct name gets its own orthogonal-ish axis, deterministically.

    Not a hashing embedder: a hash would make the cosine between two chosen
    names an accident, and every similarity assertion here would be pinning
    that accident. Each distinct text is assigned a fresh basis vector on
    first sight, so two different names never link by embedding and two
    identical names are identical by construction.
    """

    model = "stub-embedder"
    dimension = 64

    def __init__(self) -> None:
        self._axes: dict[str, int] = {}
        self.calls = 0

    def _vector(self, text: str) -> Vector:
        axis = self._axes.setdefault(text, len(self._axes))
        if axis >= self.dimension:  # pragma: no cover - tests stay far under
            raise AssertionError("StubEmbedder ran out of orthogonal axes")
        return tuple(1.0 if i == axis else 0.0 for i in range(self.dimension))

    def embed_documents(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        self.calls += 1
        return tuple(self._vector(text) for text in texts)

    def embed_query(self, text: str) -> Vector:
        return self._vector(text)


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


def add_topic(
    conn: Connection, meeting_id: UUID, name: str, *, start_ms: int = 0
) -> UUID:
    """One topic with the one mention `topic`'s deferred trigger requires."""
    moment_id = conn.execute(
        "INSERT INTO moment (meeting_id, identity_key, derived_from, start_ms,"
        " end_ms, started_at, started_at_precision)"
        " VALUES (%s, %s, 'transcript', %s, %s, %s, 'second') RETURNING id",
        (
            meeting_id,
            f"transcript:{start_ms}:{uuid4()}",
            start_ms,
            start_ms + 10_000,
            STARTED_AT,
        ),
    ).fetchone()[0]
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


def derive(conn: Connection, config: AppConfig, embedder: StubEmbedder | None = None):
    return derive_threads(conn, config, embedder=embedder or StubEmbedder())


def thread_of(conn: Connection, topic_id: UUID) -> UUID | None:
    row = conn.execute(
        "SELECT thread_id FROM topic_thread WHERE topic_id = %s", (topic_id,)
    ).fetchone()
    return None if row is None else row[0]


def thread_row(conn: Connection, thread_id: UUID) -> tuple:
    return conn.execute(
        "SELECT identity_key, name, link_rule, color_ordinal FROM thread WHERE id = %s",
        (thread_id,),
    ).fetchone()


def ordinal_of(conn: Connection, thread_id: UUID) -> int:
    return conn.execute(
        "SELECT color_ordinal FROM thread WHERE id = %s", (thread_id,)
    ).fetchone()[0]


def listed(client: TestClient) -> dict[str, dict]:
    return {t["threadId"]: t for t in client.get("/threads").json()["threads"]}


# --- the pure rules --------------------------------------------------------


def test_a_curated_key_cannot_collide_with_a_derived_one() -> None:
    """The two key spaces are disjoint, which is what stops a rerun claiming
    a split's thread by content key."""
    from meetingminer.domain.threads import normalized_topic_name

    for name in ["curated-split: x", "Curated-Split:1", "topic-name-sha256:ab"]:
        assert not is_curated_identity_key(normalized_topic_name(name))
    assert not is_curated_identity_key("topic-name-sha256:deadbeef")


def test_a_punctuation_only_topic_name_cannot_be_pinned() -> None:
    """It normalizes to the empty string, so two of them in one meeting would
    claim one pin and the split would move whichever the next re-extraction
    happened to produce. Refused by name rather than silently collided."""
    meeting_id = uuid4()
    with pytest.raises(ThreadCurationError, match="empty string"):
        pin_content_key(meeting_id=meeting_id, topic_name="!!! ...")
    assert pin_content_key(meeting_id=meeting_id, topic_name="SFTP Migration!") == (
        meeting_id,
        "sftp migration",
    )


def test_one_alias_hop_is_followed_and_never_a_chain() -> None:
    """Resolution is deliberately one hop: a chain that somehow existed stays
    visible as a wrong answer rather than being quietly walked to the end."""
    from meetingminer.domain.thread_curation import ThreadCuration

    a, b, c = uuid4(), uuid4(), uuid4()
    flat = ThreadCuration(curated_names={}, aliases={a: b}, pins={}, pin_topic_hints={})
    assert flat.follow_alias(a) == b
    assert flat.follow_alias(b) == b
    chained = ThreadCuration(
        curated_names={}, aliases={a: b, b: c}, pins={}, pin_topic_hints={}
    )
    assert chained.follow_alias(a) == b


# --- the record: what the tables refuse ------------------------------------


def test_the_record_refuses_an_alias_chain(pool: ConnectionPool) -> None:
    """Enforced in Postgres, not only in the api: thread curation has two
    independent resolvers, so a rule held in one of them is not a guarantee
    for the other."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "m1")
        a = add_topic(conn, meeting_id, "Alpha")
        b = add_topic(conn, meeting_id, "Beta", start_ms=10_000)
        c = add_topic(conn, meeting_id, "Gamma", start_ms=20_000)
        conn.commit()

    with pool.connection() as conn:
        thread_a = conn.execute(
            "INSERT INTO thread (identity_key, name, link_rule)"
            " VALUES ('a', 'A', 'r') RETURNING id"
        ).fetchone()[0]
        thread_b = conn.execute(
            "INSERT INTO thread (identity_key, name, link_rule)"
            " VALUES ('b', 'B', 'r') RETURNING id"
        ).fetchone()[0]
        thread_c = conn.execute(
            "INSERT INTO thread (identity_key, name, link_rule)"
            " VALUES ('c', 'C', 'r') RETURNING id"
        ).fetchone()[0]
        for topic_id, thread_id in ((a, thread_a), (b, thread_b), (c, thread_c)):
            conn.execute(
                "INSERT INTO topic_thread (topic_id, thread_id, linked_by)"
                " VALUES (%s, %s, 'seed')",
                (topic_id, thread_id),
            )
        conn.execute(
            "INSERT INTO thread_alias (thread_id, merged_into_id) VALUES (%s, %s)",
            (thread_a, thread_b),
        )
        conn.commit()

    with pool.connection() as conn:
        # B is now a survivor, so B may not itself be merged away.
        with pytest.raises(errors.RaiseException, match="already absorbed"):
            conn.execute(
                "INSERT INTO thread_alias (thread_id, merged_into_id) VALUES (%s, %s)",
                (thread_b, thread_c),
            )
        conn.rollback()
        # And A, already merged away, may not be a merge target.
        with pytest.raises(errors.RaiseException, match="itself merged away"):
            conn.execute(
                "INSERT INTO thread_alias (thread_id, merged_into_id) VALUES (%s, %s)",
                (thread_c, thread_a),
            )
        conn.rollback()


def test_the_record_refuses_a_pin_with_no_durable_name(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "m1")
        thread_id = conn.execute(
            "INSERT INTO thread (identity_key, name, link_rule)"
            " VALUES ('k', 'K', 'r') RETURNING id"
        ).fetchone()[0]
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "INSERT INTO thread_topic_pin"
                " (meeting_id, normalized_name, thread_id, topic_id)"
                " VALUES (%s, '', %s, %s)",
                (meeting_id, thread_id, uuid4()),
            )
        conn.rollback()


def test_a_blank_curated_name_is_refused_by_the_record(pool: ConnectionPool) -> None:
    """A whitespace-only curated name would render an unnamed band while
    suppressing the machine name that would have named it."""
    with pool.connection() as conn:
        thread_id = conn.execute(
            "INSERT INTO thread (identity_key, name, link_rule)"
            " VALUES ('k', 'K', 'r') RETURNING id"
        ).fetchone()[0]
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "INSERT INTO thread_curation (thread_id, name) VALUES (%s, '   ')",
                (thread_id,),
            )
        conn.rollback()


# --- the story: a curation survives the rerun ------------------------------


def test_a_rename_survives_a_rerun_that_changes_the_derived_name(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """The derivation rewrites `thread.name` from the seed topic on every
    pass. The curated name has to be untouched by that, and the derived name
    has to keep moving underneath it — otherwise this test would pass on an
    implementation that merely wrote the same string twice."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "m1")
        topic_id = add_topic(conn, meeting_id, "SFTP Migration")
        derive(conn, app_config)
        conn.commit()
        thread_id = thread_of(conn, topic_id)

    response = client.patch(f"/threads/{thread_id}", json={"name": "File transfer cutover"})
    assert response.status_code == 200
    assert response.json()["name"] == "File transfer cutover"
    assert response.json()["derivedName"] == "SFTP Migration"
    assert response.json()["nameIsCurated"] is True

    with pool.connection() as conn:
        # The machine's own name genuinely moves: same normalized identity,
        # different display name, so the derivation has something to rewrite.
        conn.execute(
            "UPDATE topic SET name = %s WHERE id = %s", ("sftp  MIGRATION.", topic_id)
        )
        derive(conn, app_config)
        conn.commit()
        identity_key, derived_name, _, _ = thread_row(conn, thread_id)

    assert identity_key == "sftp migration"
    assert derived_name == "sftp  MIGRATION."
    row = listed(client)[str(thread_id)]
    assert row["name"] == "File transfer cutover"
    assert row["nameIsCurated"] is True


def test_clearing_a_rename_restores_the_machine_name_as_it_now_stands(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """Not a copy taken when the rename happened — that stale third name is
    exactly what storing the old value would produce."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "m1")
        topic_id = add_topic(conn, meeting_id, "SFTP Migration")
        derive(conn, app_config)
        conn.commit()
        thread_id = thread_of(conn, topic_id)

    client.patch(f"/threads/{thread_id}", json={"name": "Cutover"})
    with pool.connection() as conn:
        conn.execute(
            "UPDATE topic SET name = %s WHERE id = %s", ("SFTP migration", topic_id)
        )
        derive(conn, app_config)
        conn.commit()

    cleared = client.patch(f"/threads/{thread_id}", json={"name": None})
    assert cleared.status_code == 200
    assert cleared.json()["name"] == "SFTP migration"
    assert cleared.json()["nameIsCurated"] is False
    assert listed(client)[str(thread_id)]["name"] == "SFTP migration"


def test_a_merge_survives_a_rerun_and_moves_the_absorbed_memberships(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """The absorbed cluster still exists and still re-derives every pass. What
    must change is only where its memberships land."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        sftp = add_topic(conn, first, "SFTP Migration")
        transfer = add_topic(conn, second, "File Transfer Cutover")
        derive(conn, app_config)
        conn.commit()
        absorbed = thread_of(conn, transfer)
        survivor = thread_of(conn, sftp)
        absorbed_ordinal = ordinal_of(conn, absorbed)
        survivor_ordinal = ordinal_of(conn, survivor)

    assert absorbed != survivor
    merged = client.post(f"/threads/{absorbed}/merge", json={"intoThreadId": str(survivor)})
    assert merged.status_code == 200
    assert merged.json()["threadId"] == str(survivor)

    # Visible immediately, before any derivation has run.
    assert str(absorbed) not in listed(client)
    assert listed(client)[str(survivor)]["mentionCount"] == 2

    with pool.connection() as conn:
        report = derive(conn, app_config)
        conn.commit()
        assert report.merged_clusters == 1
        # The membership row itself now points at the survivor: the merge is
        # not merely a read-time overlay after a pass has run.
        assert thread_of(conn, transfer) == survivor
        assert thread_of(conn, sftp) == survivor
        # The absorbed row survives as durable identity, with its own colour.
        assert thread_row(conn, absorbed) is not None
        assert ordinal_of(conn, absorbed) == absorbed_ordinal
        assert ordinal_of(conn, survivor) == survivor_ordinal

    assert str(absorbed) not in listed(client)
    assert listed(client)[str(survivor)]["mentionCount"] == 2


def test_a_split_survives_a_rerun_without_the_derivation_reclaiming_its_thread(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """The subtle one. A curated thread is attached to exactly the topics
    split onto it, so the ordinary attachment-reuse path would hand it back to
    the cluster the split was correcting and overwrite its identity and name
    while reporting a successful pass."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        stay = add_topic(conn, first, "Vendor Feed")
        move = add_topic(conn, second, "Vendor Feed")
        derive(conn, app_config)
        conn.commit()
        original = thread_of(conn, stay)
        assert thread_of(conn, move) == original
        original_ordinal = ordinal_of(conn, original)

    split = client.post(
        f"/threads/{original}/split",
        json={"topicIds": [str(move)], "name": "Vendor feed (billing)"},
    )
    assert split.status_code == 201
    curated_id = UUID(split.json()["threadId"])
    curated_ordinal = split.json()["colorOrdinal"]
    assert curated_ordinal != original_ordinal

    # Visible immediately: two bands, one topic each.
    rows = listed(client)
    assert rows[str(original)]["mentionCount"] == 1
    assert rows[str(curated_id)]["mentionCount"] == 1
    assert rows[str(curated_id)]["name"] == "Vendor feed (billing)"

    with pool.connection() as conn:
        report = derive(conn, app_config)
        conn.commit()
        assert report.curated_links == 1
        assert report.unmatched_pins == ()
        assert thread_of(conn, move) == curated_id
        assert thread_of(conn, stay) == original
        identity_key, name, link_rule, ordinal = thread_row(conn, curated_id)
        assert is_curated_identity_key(identity_key)
        assert name == "Vendor feed (billing)"
        assert link_rule == CURATED_LINK_RULE
        assert ordinal == curated_ordinal
        assert ordinal_of(conn, original) == original_ordinal

    rows = listed(client)
    assert rows[str(original)]["mentionCount"] == 1
    assert rows[str(curated_id)]["mentionCount"] == 1


def test_a_split_survives_a_re_extraction_that_replaces_every_topic_row(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """Story 10.1 replaces a meeting's topics wholesale with fresh UUIDs. A
    pin keyed on `topic_id` would be cascaded away with them and the split
    would vanish leaving no record it was ever made — which is precisely the
    silent discard this story exists to prevent."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        add_topic(conn, first, "Vendor Feed")
        move = add_topic(conn, second, "Vendor Feed")
        derive(conn, app_config)
        conn.commit()
        original = thread_of(conn, move)

    curated_id = UUID(
        client.post(
            f"/threads/{original}/split",
            json={"topicIds": [str(move)], "name": "Vendor feed (billing)"},
        ).json()["threadId"]
    )

    with pool.connection() as conn:
        # The re-extraction: same subject, same meeting, brand new row.
        conn.execute("DELETE FROM topic WHERE meeting_id = %s", (second,))
        replacement = add_topic(conn, second, "Vendor  feed.")
        assert replacement != move
        report = derive(conn, app_config)
        conn.commit()
        assert report.curated_links == 1
        assert report.unmatched_pins == ()
        assert thread_of(conn, replacement) == curated_id

    assert listed(client)[str(curated_id)]["mentionCount"] == 1


def test_a_pin_the_corpus_cannot_match_is_reported_and_never_dropped(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """AD-18. A recorded correction that did not apply and a corpus with no
    corrections are otherwise the same observation."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        add_topic(conn, first, "Vendor Feed")
        move = add_topic(conn, second, "Vendor Feed")
        derive(conn, app_config)
        conn.commit()
        original = thread_of(conn, move)

    client.post(
        f"/threads/{original}/split",
        json={"topicIds": [str(move)], "name": "Vendor feed (billing)"},
    )

    events: list[tuple[str, dict]] = []
    with pool.connection() as conn:
        # The subject goes away entirely: re-extracted under another name.
        conn.execute("DELETE FROM topic WHERE meeting_id = %s", (second,))
        add_topic(conn, second, "Something else entirely")
        report = derive_threads(
            conn,
            app_config,
            embedder=StubEmbedder(),
            log=lambda event, **fields: events.append((event, fields)),
        )
        conn.commit()

        assert report.curated_links == 0
        assert len(report.unmatched_pins) == 1
        assert report.unmatched_pins[0] == (second, "vendor feed")
        # The row is kept: the subject may come back with the next extraction.
        assert conn.execute("SELECT count(*) FROM thread_topic_pin").fetchone()[0] == 1

    named = [fields for event, fields in events if event == "threads.curation_unmatched"]
    assert len(named) == 1
    assert named[0]["pins"] == 1
    assert named[0]["keys"] == [f"{second}:vendor feed"]


def test_curation_leaves_an_unchanged_rerun_writing_nothing(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """Property 4 of `domain/threads.py`'s idempotency argument. Resolving a
    pin *before* the membership UPSERT rather than correcting the row after it
    is what keeps this true — the alternative writes every pinned row twice on
    every pass, and `updated_at` would move forever."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        stay = add_topic(conn, first, "Vendor Feed")
        move = add_topic(conn, second, "Vendor Feed")
        derive(conn, app_config)
        conn.commit()
        original = thread_of(conn, stay)

    client.post(
        f"/threads/{original}/split",
        json={"topicIds": [str(move)], "name": "Vendor feed (billing)"},
    )
    client.patch(f"/threads/{original}", json={"name": "Vendor feed (inbound)"})

    with pool.connection() as conn:
        derive(conn, app_config)
        conn.commit()
        before = conn.execute(
            "SELECT topic_id, thread_id, linked_by, similarity, created_at"
            " FROM topic_thread ORDER BY topic_id"
        ).fetchall()
        thread_before = conn.execute(
            "SELECT id, updated_at FROM thread ORDER BY id"
        ).fetchall()

    with pool.connection() as conn:
        derive(conn, app_config)
        conn.commit()
        assert (
            conn.execute(
                "SELECT topic_id, thread_id, linked_by, similarity, created_at"
                " FROM topic_thread ORDER BY topic_id"
            ).fetchall()
            == before
        )
        assert (
            conn.execute("SELECT id, updated_at FROM thread ORDER BY id").fetchall()
            == thread_before
        )


def test_a_split_then_a_merge_of_its_product_resolves_through_both(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """The precedence rule: a pin decides the base thread, the merge then
    applies to whatever that produced. One hop is enough because the map is
    flat, and this is the case that would strand a topic if it were not."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        third = seed_meeting(conn, "m3", offset_days=2)
        add_topic(conn, first, "Vendor Feed")
        move = add_topic(conn, second, "Vendor Feed")
        other = add_topic(conn, third, "Billing Portal")
        derive(conn, app_config)
        conn.commit()
        original = thread_of(conn, move)
        destination = thread_of(conn, other)

    curated_id = UUID(
        client.post(
            f"/threads/{original}/split",
            json={"topicIds": [str(move)], "name": "Vendor feed (billing)"},
        ).json()["threadId"]
    )
    merged = client.post(
        f"/threads/{curated_id}/merge", json={"intoThreadId": str(destination)}
    )
    assert merged.status_code == 200

    assert str(curated_id) not in listed(client)
    assert listed(client)[str(destination)]["mentionCount"] == 2

    with pool.connection() as conn:
        derive(conn, app_config)
        conn.commit()
        assert thread_of(conn, move) == destination


# --- the api's refusals ----------------------------------------------------


def _one_thread(conn: Connection, config: AppConfig) -> tuple[UUID, UUID, UUID]:
    first = seed_meeting(conn, "m1")
    second = seed_meeting(conn, "m2", offset_days=1)
    a = add_topic(conn, first, "Vendor Feed")
    b = add_topic(conn, second, "Vendor Feed")
    derive(conn, config)
    conn.commit()
    return thread_of(conn, a), a, b


def test_renaming_an_unknown_thread_is_a_404(client: TestClient, pool: ConnectionPool) -> None:
    response = client.patch(f"/threads/{uuid4()}", json={"name": "x"})
    assert response.status_code == 404
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_a_blank_rename_is_a_422(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        thread_id, _, _ = _one_thread(conn, app_config)
    assert client.patch(f"/threads/{thread_id}", json={"name": "   "}).status_code == 422


def test_a_merged_away_thread_cannot_be_renamed_or_split(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """Curating something nobody can see would be a correction with no visible
    effect — the shape of failure this story is about, inverted."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        a = add_topic(conn, first, "Vendor Feed")
        b = add_topic(conn, second, "Billing Portal")
        derive(conn, app_config)
        conn.commit()
        absorbed, survivor = thread_of(conn, a), thread_of(conn, b)

    client.post(f"/threads/{absorbed}/merge", json={"intoThreadId": str(survivor)})
    renamed = client.patch(f"/threads/{absorbed}", json={"name": "x"})
    assert renamed.status_code == 409
    assert renamed.json()["type"] == "urn:meetingminer:problem:already-merged"
    split = client.post(
        f"/threads/{absorbed}/split", json={"topicIds": [str(a)], "name": "x"}
    )
    assert split.status_code == 409


def test_a_thread_cannot_be_merged_into_itself(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        thread_id, _, _ = _one_thread(conn, app_config)
    response = client.post(
        f"/threads/{thread_id}/merge", json={"intoThreadId": str(thread_id)}
    )
    assert response.status_code == 422


def test_the_api_refuses_both_directions_of_an_alias_chain(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        third = seed_meeting(conn, "m3", offset_days=2)
        a = add_topic(conn, first, "Alpha")
        b = add_topic(conn, second, "Beta")
        c = add_topic(conn, third, "Gamma")
        derive(conn, app_config)
        conn.commit()
        thread_a, thread_b, thread_c = (
            thread_of(conn, a),
            thread_of(conn, b),
            thread_of(conn, c),
        )

    assert (
        client.post(f"/threads/{thread_a}/merge", json={"intoThreadId": str(thread_b)}).status_code
        == 200
    )
    # B has absorbed A, so B may not itself be merged away.
    absorbing = client.post(
        f"/threads/{thread_b}/merge", json={"intoThreadId": str(thread_c)}
    )
    assert absorbing.status_code == 409
    assert absorbing.json()["type"] == "urn:meetingminer:problem:already-merged"
    # And A, already merged away, may not be a merge target.
    targeting = client.post(
        f"/threads/{thread_c}/merge", json={"intoThreadId": str(thread_a)}
    )
    assert targeting.status_code == 409
    assert targeting.json()["type"] == "urn:meetingminer:problem:merge-target-not-canonical"


def test_a_split_must_name_topics_the_thread_actually_holds(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        a = add_topic(conn, first, "Vendor Feed")
        elsewhere = add_topic(conn, second, "Billing Portal")
        derive(conn, app_config)
        conn.commit()
        thread_id = thread_of(conn, a)

    assert (
        client.post(f"/threads/{thread_id}/split", json={"topicIds": [], "name": "x"}).status_code
        == 422
    )
    stranger = client.post(
        f"/threads/{thread_id}/split",
        json={"topicIds": [str(elsewhere)], "name": "x"},
    )
    assert stranger.status_code == 422
    assert "does not hold" in stranger.json()["detail"]


def test_a_split_that_moves_every_topic_is_a_rename_and_is_refused(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """It would empty the original thread and burn a colour ordinal to
    accomplish what PATCH does without either."""
    with pool.connection() as conn:
        thread_id, a, b = _one_thread(conn, app_config)

    response = client.post(
        f"/threads/{thread_id}/split",
        json={"topicIds": [str(a), str(b)], "name": "Everything"},
    )
    assert response.status_code == 422
    assert "is a rename, not a split" in response.json()["detail"]


def test_a_topic_already_split_away_cannot_be_split_from_its_old_thread(
    client: TestClient, pool: ConnectionPool, app_config: AppConfig
) -> None:
    """The membership the api validates against is the *effective* one, so a
    stale client offering yesterday's grouping is refused rather than silently
    re-pinning a topic the user has already moved."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "m1")
        second = seed_meeting(conn, "m2", offset_days=1)
        third = seed_meeting(conn, "m3", offset_days=2)
        a = add_topic(conn, first, "Vendor Feed")
        b = add_topic(conn, second, "Vendor Feed")
        add_topic(conn, third, "Vendor Feed")
        derive(conn, app_config)
        conn.commit()
        original = thread_of(conn, a)

    client.post(
        f"/threads/{original}/split", json={"topicIds": [str(b)], "name": "Split off"}
    )
    again = client.post(
        f"/threads/{original}/split", json={"topicIds": [str(b)], "name": "Again"}
    )
    assert again.status_code == 422
    assert "does not hold" in again.json()["detail"]
