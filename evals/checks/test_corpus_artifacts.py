"""``Corpus.artifacts_for`` / ``segments_for_moment`` against real Postgres rows.

Store-5.2's capture checks proved the shape: the harness's read-only
``corpus`` fixture asserts against rows a *different*, ordinary writable
connection seeded — never against rows the harness itself wrote, since its
connection cannot write at all (AD-16). This file seeds one small evidence
bundle (job -> meeting -> transcript source/segment -> moment -> moment_segment
-> artifact) directly with SQL in the shapes the migrations declare, the same
convention ``server/tests/projection_seed.py`` uses for projection tests, and
cleans it up afterward so the shared corpus is left exactly as it was found.

**These tests hold the shared Docker stores — one agent at a time (AGENTS.md).**
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from evals.harness.corpus import Corpus

ARTIFACT_TITLE = "Keep optimistic locking"
ARTIFACT_BODY = "The team decided the Orders module keeps optimistic locking."
SEGMENT_TEXT = "We are keeping optimistic locking for the Orders module."


@dataclass(frozen=True)
class Seeded:
    meeting_id: str
    moment_id: str
    artifact_id: str
    segment_id: str


def _writable_conninfo(app_config: Any) -> str:
    """A normal (non-read-only) connection string for seeding test fixtures.

    Deliberately not ``evals.harness.corpus.read_only_conninfo``: that
    connection cannot write, by design (AD-16), and this file is test setup,
    not harness production code — the same reason
    ``checks/test_capture_checks.py``'s write-probe test imports ``psycopg``
    directly instead of reaching for a harness helper that does not exist.
    """
    pg = app_config.settings.stores.postgres
    return psycopg.conninfo.make_conninfo(
        host=pg.host,
        port=pg.port,
        dbname=pg.database,
        user=pg.user,
        password=app_config.secrets.postgres_password,
    )


@pytest.fixture()
def seeded(app_config: Any) -> Iterator[Seeded]:
    """One meeting with a moment, its covering segment, and one artifact.

    Committed, not a rolled-back transaction: the harness's ``corpus`` fixture
    reads through its *own* connection, which cannot see another session's
    uncommitted rows. Cleanup deletes every row this fixture created, in FK
    order — the composite ``artifact`` FK carries no ``ON DELETE``, so it is
    removed before the ``job`` row's cascade reaches ``meeting``.
    """
    marker = uuid4().hex
    with psycopg.connect(_writable_conninfo(app_config), autocommit=True) as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus, status)"
            " VALUES (%s, %s, 'scripted', 'running') RETURNING id",
            (f"eval-corpus-artifacts-{marker}", "n/a"),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, title, has_recording)"
            " VALUES (%s, %s, 'scripted', now(), 'second', %s, false) RETURNING id",
            (job_id, f"eval-corpus-artifacts-meeting-{marker}", "Corpus Artifacts Fixture"),
        ).fetchone()[0]
        source_id = conn.execute(
            "INSERT INTO transcript_source"
            " (meeting_id, kind, format, sha256, byte_size, segments)"
            " VALUES (%s, 'provided-text', 'teams', 'deadbeef', 0, '[]')"
            " RETURNING id",
            (meeting_id,),
        ).fetchone()[0]
        segment_id = conn.execute(
            "INSERT INTO transcript_segment"
            " (meeting_id, ordinal, start_ms, end_ms, text, speaker_label,"
            " speaker_resolution, label_source_id, timing_source_id)"
            " VALUES (%s, 1, 1000, 5000, %s, 'Tim Goeke', 'unresolved', %s, %s)"
            " RETURNING id",
            (meeting_id, SEGMENT_TEXT, source_id, source_id),
        ).fetchone()[0]
        moment_id = conn.execute(
            "INSERT INTO moment"
            " (meeting_id, identity_key, derived_from, start_ms, end_ms,"
            " started_at, started_at_precision)"
            " VALUES (%s, %s, 'transcript', 1000, 5000, now(), 'second')"
            " RETURNING id",
            (meeting_id, f"transcript:1000:{marker}"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO moment_segment (moment_id, transcript_segment_id)"
            " VALUES (%s, %s)",
            (moment_id, segment_id),
        )
        artifact_id = conn.execute(
            "INSERT INTO artifact (moment_id, meeting_id, kind, title, body)"
            " VALUES (%s, %s, 'adr', %s, %s) RETURNING id",
            (moment_id, meeting_id, ARTIFACT_TITLE, ARTIFACT_BODY),
        ).fetchone()[0]
        try:
            yield Seeded(
                meeting_id=str(meeting_id),
                moment_id=str(moment_id),
                artifact_id=str(artifact_id),
                segment_id=str(segment_id),
            )
        finally:
            conn.execute("DELETE FROM artifact WHERE id = %s", (artifact_id,))
            conn.execute("DELETE FROM job WHERE id = %s", (job_id,))


def test_artifacts_for_reads_the_seeded_row(corpus: Corpus, seeded: Seeded) -> None:
    rows = corpus.artifacts_for(seeded.meeting_id)
    assert [str(row.id) for row in rows] == [seeded.artifact_id]
    row = rows[0]
    assert str(row.moment_id) == seeded.moment_id
    assert row.kind == "adr"
    assert row.state == "extracted"
    assert row.title == ARTIFACT_TITLE
    assert row.body == ARTIFACT_BODY


def test_artifacts_for_a_meeting_with_no_artifacts_is_empty(
    corpus: Corpus, seeded: Seeded
) -> None:
    """A meeting with no proposals is a legitimate zero, not a query bug —
    ``artifacts_for`` names no other meeting id to compare it against."""
    assert corpus.artifacts_for(str(uuid4())) == ()


def test_segments_for_moment_reads_the_covering_segment(
    corpus: Corpus, seeded: Seeded
) -> None:
    rows = corpus.segments_for_moment(seeded.moment_id)
    assert len(rows) == 1
    segment = rows[0]
    assert segment.start_ms == 1000
    assert segment.end_ms == 5000
    assert segment.speaker_label == "Tim Goeke"
    assert segment.text == SEGMENT_TEXT


def test_segments_for_an_uncovered_moment_is_empty(corpus: Corpus) -> None:
    assert corpus.segments_for_moment(str(uuid4())) == ()


def test_meeting_corpus_reads_the_seeded_tag(corpus: Corpus, seeded: Seeded) -> None:
    """Check 2.11's refusal guard reads this: the tag from the database the
    approval would mutate, not the api's copy of it."""
    assert corpus.meeting_corpus(seeded.meeting_id) == "scripted"


def test_meeting_corpus_for_a_missing_meeting_is_none(
    corpus: Corpus, seeded: Seeded
) -> None:
    """``None`` means the row is gone — which the refusal guard renders as a
    vanished-row refusal, never as the string 'None'."""
    assert corpus.meeting_corpus(str(uuid4())) is None
