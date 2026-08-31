"""Schema contract for migration 0022 (story 12.2): artifact scope.

An artifact is scoped either to a moment or to its meeting, and `0022` makes
that a checked fact rather than a convention. Two properties are under test and
they pull in opposite directions, which is why both are here:

* **Scope is declared in exactly one place.** `artifact_scope_matches_kind` is
  an equivalence — a kind is meeting-scoped if and only if its row names no
  moment — so neither half can be satisfied on its own. Every assertion below
  goes through the database rather than through a Python constant, because a
  Python constant is precisely the second copy the constraint exists to
  prevent.
* **Widening the scope must not weaken the anchor.** `0009`'s composite
  `(moment_id, meeting_id)` edge is untouched, and the point of testing it
  *after* `0022` is that dropping `NOT NULL` changes how it behaves: under the
  SQL default MATCH SIMPLE a NULL `moment_id` satisfies the FK vacuously. That
  is the intended exemption for a meeting-scoped row and it must not have
  leaked into rows that do name a moment.

DB-backed against the per-run test database (named skip when the compose
Postgres is down). Seeding is minimal and direct, the `test_migrations_topics`
way, so each refusal proves exactly the edge under test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from psycopg import Connection, errors
from psycopg_pool import ConnectionPool

from conftest import truncate_evidence

STARTED_AT = datetime(2026, 8, 31, 9, 30, 0, tzinfo=timezone.utc)


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
        " VALUES (%s, %s, 'real', %s, 'second', 'Artifact Scope Test',"
        " false, '{}'::jsonb) RETURNING id",
        (job_id, source_id, STARTED_AT),
    ).fetchone()[0]
    moment_id = conn.execute(
        "INSERT INTO moment (meeting_id, identity_key, derived_from, start_ms,"
        " end_ms, started_at, started_at_precision)"
        " VALUES (%s, %s, 'transcript', %s, %s, %s, 'second') RETURNING id",
        (meeting_id, f"transcript:{start_ms}", start_ms, start_ms + 10_000, STARTED_AT),
    ).fetchone()[0]
    return meeting_id, moment_id


def insert(
    conn: Connection,
    meeting_id: UUID,
    moment_id: UUID | None,
    kind: str,
) -> UUID:
    return conn.execute(
        "INSERT INTO artifact (moment_id, meeting_id, kind, title, body)"
        " VALUES (%s, %s, %s, 'A title', 'A body') RETURNING id",
        (moment_id, meeting_id, kind),
    ).fetchone()[0]


def test_a_meeting_scoped_artifact_is_stored_with_no_moment(pool) -> None:
    """The row story 12.2 exists to make storable at all."""
    with pool.connection() as conn:
        meeting_id, _ = seed_meeting_with_moment(conn, "scope-summary-ok")
        artifact_id = insert(conn, meeting_id, None, "summary")
        row = conn.execute(
            "SELECT moment_id, meeting_id, state FROM artifact WHERE id = %s",
            (artifact_id,),
        ).fetchone()
    # `meeting_id` stays required for both scopes, and the lifecycle default is
    # untouched: a meeting-scoped artifact enters `extracted` like every other.
    assert row == (None, meeting_id, "extracted")


def test_a_moment_anchored_artifact_still_requires_its_moment(pool) -> None:
    """The other half of the equivalence. `adr` may not go meeting-scoped."""
    with pool.connection() as conn:
        meeting_id, _ = seed_meeting_with_moment(conn, "scope-adr-null")
        with pytest.raises(errors.CheckViolation) as excinfo:
            insert(conn, meeting_id, None, "adr")
    assert "artifact_scope_matches_kind" in str(excinfo.value)


def test_a_meeting_scoped_kind_may_not_name_a_moment(pool) -> None:
    """A `summary` that names a moment is refused, so the two scopes cannot be
    confused by a writer that happened to have a moment id in hand."""
    with pool.connection() as conn:
        meeting_id, moment_id = seed_meeting_with_moment(conn, "scope-summary-moment")
        with pytest.raises(errors.CheckViolation) as excinfo:
            insert(conn, meeting_id, moment_id, "summary")
    assert "artifact_scope_matches_kind" in str(excinfo.value)


def test_the_kind_check_admits_summary_and_still_refuses_an_unknown_kind(pool) -> None:
    """0022 widened the kind CHECK rather than removing it."""
    with pool.connection() as conn:
        meeting_id, moment_id = seed_meeting_with_moment(conn, "scope-kind-check")
        insert(conn, meeting_id, moment_id, "adr")
        insert(conn, meeting_id, moment_id, "action-item")
        with pytest.raises(errors.CheckViolation) as excinfo:
            insert(conn, meeting_id, moment_id, "decision-record")
    assert "artifact_kind_check" in str(excinfo.value)


def test_an_anchored_artifact_still_cannot_name_another_meetings_moment(pool) -> None:
    """Widening the scope did not weaken the anchor.

    This is the assertion that has to be made *after* 0022 rather than assumed
    from 0009: dropping `NOT NULL` on `moment_id` changes the composite FK's
    behaviour for NULLs, and the risk is that the exemption reaches rows that
    do name a moment. It does not — both columns are populated here, so the
    pair is still checked in full.
    """
    with pool.connection() as conn:
        meeting_a, _ = seed_meeting_with_moment(conn, "scope-cross-a")
        _, moment_b = seed_meeting_with_moment(conn, "scope-cross-b")
        with pytest.raises(errors.ForeignKeyViolation) as excinfo:
            insert(conn, meeting_a, moment_b, "adr")
    # The composite edge by name, not merely "some foreign key complained":
    # `artifact_meeting_id_fkey` would also be a ForeignKeyViolation and would
    # mean something else entirely.
    assert "artifact_moment_id_meeting_id_fkey" in str(excinfo.value)


def test_the_meeting_scoped_kind_list_is_declared_only_by_the_constraint(pool) -> None:
    """The single-declaration rule, read back from the database itself.

    Asked of `pg_constraint` rather than of a Python constant on purpose: the
    requirement is that the kind list lives in the constraint and nowhere else,
    so a test that compared it against a module-level tuple would be creating
    exactly the second copy it is supposed to forbid. What it can honestly
    check is that the constraint is present, is an equivalence over both
    operands, and names the kind.
    """
    with pool.connection() as conn:
        definition = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'artifact_scope_matches_kind'"
        ).fetchone()
    assert definition is not None, (
        "artifact_scope_matches_kind is missing — it is the single declaration"
        " of which kinds are meeting-scoped, so nothing else declares it"
    )
    text = definition[0]
    assert "summary" in text
    assert "moment_id IS NULL" in text
