"""Review regressions for Story 10.3's durable thread colour ordinal."""

from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from conftest import truncate_evidence
from test_api_threads import add_thread, ordinal_of


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


def test_explicit_sequence_start_is_reserved_before_default_allocation(
    pool: ConnectionPool,
) -> None:
    """An import of the fresh sequence's first value must consume that value."""
    with pool.connection() as conn:
        conn.execute("SELECT setval('thread_color_ordinal_seq', 1, false)")
        imported = conn.execute(
            "INSERT INTO thread (identity_key, name, link_rule, color_ordinal)"
            " VALUES ('imported-first', 'imported-first', 'seed', 1) RETURNING id"
        ).fetchone()[0]
        minted = add_thread(conn, identity_key="minted-after-imported-first")

        assert ordinal_of(conn, imported) == 1
        assert ordinal_of(conn, minted) > 1
