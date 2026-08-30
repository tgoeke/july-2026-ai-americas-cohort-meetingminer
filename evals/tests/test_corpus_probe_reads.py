"""The probe-eligibility corpus reads, exercised with no store (story 11.3).

Same split as ``test_capture_rows.py``: ``corpus.py``'s SQL needs a live
Postgres, but its row mappings and result shaping are pure, and that is where
a silent corruption would live. These tests pin ``moment_from_row`` and the
``moments_for`` / ``stage_status`` result shapes over a fake connection —
the same duck-typed seam ``Corpus.connection`` already is.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from evals.harness.corpus import (
    MOMENT_COLUMNS,
    Corpus,
    CorpusQueryError,
    MomentRow,
    moment_from_row,
)

MEETING = "11111111-1111-7111-8111-111111111111"
MOMENT = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"


class FakeConnection:
    """The two attributes ``Corpus`` reads: ``closed`` and ``execute``."""

    closed = False

    def __init__(self, rows: Any) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> Any:
        self.queries.append((sql, params))
        if isinstance(self.rows, Exception):
            raise self.rows
        return SimpleNamespace(fetchall=lambda: list(self.rows))


def corpus_over(rows: Any) -> tuple[Corpus, FakeConnection]:
    reader = Corpus("host=nowhere")
    connection = FakeConnection(rows)
    reader._connection = connection  # type: ignore[assignment]
    return reader, connection


# --------------------------------------------------------------------------
# moment_from_row — the mapping is positional by contract
# --------------------------------------------------------------------------


def test_the_moment_columns_map_to_the_fields_that_carry_their_meaning() -> None:
    moment = moment_from_row((MOMENT, "transcript:1000"))
    assert moment == MomentRow(id=MOMENT, identity_key="transcript:1000")


def test_a_uuid_typed_id_arrives_as_a_string() -> None:
    """psycopg hands back UUID objects; the harness compares strings."""

    class FakeUuid:
        def __str__(self) -> str:
            return MOMENT

    assert moment_from_row((FakeUuid(), "screen:2000")).id == MOMENT


def test_a_drifted_moment_row_is_a_named_error() -> None:
    with pytest.raises(CorpusQueryError) as caught:
        moment_from_row((MOMENT, "transcript:1000", "extra"))
    assert ", ".join(MOMENT_COLUMNS) in str(caught.value)


# --------------------------------------------------------------------------
# moments_for / stage_status — result shapes over the fake connection
# --------------------------------------------------------------------------


def test_moments_for_returns_the_rows_as_moment_records() -> None:
    reader, connection = corpus_over([(MOMENT, "transcript:1000")])
    assert reader.moments_for(MEETING) == (
        MomentRow(id=MOMENT, identity_key="transcript:1000"),
    )
    sql, params = connection.queries[0]
    assert "ORDER BY start_ms" in sql
    assert params == (MEETING,)


def test_a_meeting_with_no_moments_is_an_empty_tuple() -> None:
    reader, _ = corpus_over([])
    assert reader.moments_for(MEETING) == ()


def test_stage_status_returns_the_status_for_the_named_stage() -> None:
    reader, connection = corpus_over([("done",)])
    assert reader.stage_status(MEETING, "extract") == "done"
    sql, params = connection.queries[0]
    assert "job_stage" in sql
    assert params == (MEETING, "extract")


def test_a_missing_stage_row_is_none_never_a_guess() -> None:
    reader, _ = corpus_over([])
    assert reader.stage_status(MEETING, "extract") is None


def test_a_failing_read_is_a_named_corpus_error() -> None:
    import psycopg

    reader, _ = corpus_over(psycopg.Error("connection went away"))
    with pytest.raises(CorpusQueryError) as caught:
        reader.stage_status(MEETING, "extract")
    assert MEETING in str(caught.value)
