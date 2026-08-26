"""`digest` (FR31, story 4.5): the read-only example-email CLI.

Store-backed, following `test_projections_rebuild.py`'s pattern: seed
directly via SQL (never through story 4.3's approval endpoint — this CLI has
no dependency on it), point the CLI's own connection at the per-run test
database by monkeypatching `db.conninfo`, and assert on the file it writes
plus its return code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from meetingminer import db
from meetingminer.config import AppConfig
from meetingminer.digest.cli import main as digest_main

from conftest import truncate_evidence
from projection_seed import STARTED_AT, seed_meeting


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


@pytest.fixture(autouse=True)
def _point_cli_at_test_database(
    pool: ConnectionPool,
    monkeypatch: pytest.MonkeyPatch,
    test_database: str,
) -> None:
    # The CLI opens its own connection from config.yaml; point it at the
    # per-run test database rather than the developer's real one.
    real_conninfo = db.conninfo
    monkeypatch.setattr(
        db,
        "conninfo",
        lambda config, database=None: real_conninfo(config, database=test_database),
    )


def _insert_artifact(
    conn: Any,
    *,
    moment_id: UUID,
    meeting_id: UUID,
    kind: str,
    state: str,
    title: str,
    body: str,
) -> UUID:
    return conn.execute(
        "INSERT INTO artifact (moment_id, meeting_id, kind, state, title, body)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (moment_id, meeting_id, kind, state, title, body),
    ).fetchone()[0]


def test_happy_path_writes_both_meetings_most_recent_first_with_sections(
    pool: ConnectionPool, app_config: AppConfig, tmp_path: Path
) -> None:
    with pool.connection() as conn:
        older = seed_meeting(
            conn, source_id="digest-older", title="Older Meeting", started_at=STARTED_AT
        )
        newer = seed_meeting(
            conn,
            source_id="digest-newer",
            title="Newer Meeting",
            started_at=STARTED_AT + timedelta(days=5),
        )
        _insert_artifact(
            conn,
            moment_id=older.moment_ids[0],
            meeting_id=older.meeting_id,
            kind="adr",
            state="published",
            title="Migrate the zylographic queue",
            body="We will migrate the zylographic queue in Q4.",
        )
        _insert_artifact(
            conn,
            moment_id=older.moment_ids[0],
            meeting_id=older.meeting_id,
            kind="action-item",
            state="published",
            title="Approve the purchase order",
            body="Owner: Ellis Whitmore\nGet the PO signed off.",
        )
        _insert_artifact(
            conn,
            moment_id=newer.moment_ids[0],
            meeting_id=newer.meeting_id,
            kind="adr",
            state="published",
            title="Adopt the new intake schema",
            body="Adopt schema v2 for all future drops.",
        )
        _insert_artifact(
            conn,
            moment_id=newer.moment_ids[0],
            meeting_id=newer.meeting_id,
            kind="action-item",
            state="published",
            title="Follow up with vendor",
            body="No owner named on this one.",
        )
        conn.commit()

    output_path = tmp_path / "digest.txt"
    assert digest_main(["--output", str(output_path)]) == 0
    text = output_path.read_text(encoding="utf-8")

    assert "Newer Meeting" in text
    assert "Older Meeting" in text
    assert text.index("Newer Meeting") < text.index("Older Meeting")
    assert "### Decisions" in text
    assert "### Action Items" in text
    assert "Approve the purchase order (Owner: Ellis Whitmore)" in text
    assert "Follow up with vendor (Owner: Unassigned)" in text

    newer_block = text[text.index("## Newer Meeting") : text.index("## Older Meeting")]
    older_block = text[text.index("## Older Meeting") :]
    for meeting_block in (newer_block, older_block):
        assert "### Decisions" in meeting_block
        assert "### Action Items" in meeting_block


def test_no_published_artifacts_writes_a_file_stating_so(
    pool: ConnectionPool, app_config: AppConfig, tmp_path: Path
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="digest-none-published")
        _insert_artifact(
            conn,
            moment_id=seeded.moment_ids[0],
            meeting_id=seeded.meeting_id,
            kind="adr",
            state="extracted",
            title="Not yet approved",
            body="Draft only.",
        )
        conn.commit()

    output_path = tmp_path / "digest.txt"
    assert digest_main(["--output", str(output_path)]) == 0
    text = output_path.read_text(encoding="utf-8")
    assert "No artifacts are published yet." in text


def test_output_missing_fails_with_exit_2_and_writes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No `--output` is ever passed, so there is no path to check for a
    # written file — the CLI returns 2 before it touches the filesystem at
    # all, which is exactly what the exit code + message below verify.
    assert digest_main([]) == 2
    err = capsys.readouterr().err
    assert "fatal: digest aborted: --output PATH is required" in err


def test_database_unreachable_fails_like_rebuild(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import meetingminer.digest.cli as digest_cli

    monkeypatch.setattr(
        digest_cli.psycopg,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            psycopg.OperationalError("test database unreachable")
        ),
    )
    output_path = tmp_path / "digest.txt"

    assert digest_main(["--output", str(output_path)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("fatal: digest aborted:")
    assert not output_path.exists()


def test_migrations_pending_fails_like_rebuild(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def _pending(_conn: Any) -> None:
        raise db.MigrationsPendingError(["9999_not_applied.sql"])

    monkeypatch.setattr(db, "check_migrations_current", _pending)
    output_path = tmp_path / "digest.txt"

    assert digest_main(["--output", str(output_path)]) == 1
    err = capsys.readouterr().err
    assert "fatal: digest aborted:" in err
    assert "9999_not_applied.sql" in err
    assert not output_path.exists()


def test_mixed_states_in_one_meeting_only_published_appears(
    pool: ConnectionPool, app_config: AppConfig, tmp_path: Path
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="digest-mixed-states")
        _insert_artifact(
            conn,
            moment_id=seeded.moment_ids[0],
            meeting_id=seeded.meeting_id,
            kind="adr",
            state="extracted",
            title="Still a draft",
            body="Not ready.",
        )
        _insert_artifact(
            conn,
            moment_id=seeded.moment_ids[0],
            meeting_id=seeded.meeting_id,
            kind="adr",
            state="approved",
            title="Approved but not published",
            body="Awaiting publish.",
        )
        _insert_artifact(
            conn,
            moment_id=seeded.moment_ids[0],
            meeting_id=seeded.meeting_id,
            kind="adr",
            state="published",
            title="Published decision",
            body="This one made it.",
        )
        conn.commit()

    output_path = tmp_path / "digest.txt"
    assert digest_main(["--output", str(output_path)]) == 0
    text = output_path.read_text(encoding="utf-8")

    assert "Published decision" in text
    assert "Still a draft" not in text
    assert "Approved but not published" not in text


def test_write_failure_preserves_an_existing_digest(
    pool: ConnectionPool,
    app_config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="digest-atomic-write")
        _insert_artifact(
            conn,
            moment_id=seeded.moment_ids[0],
            meeting_id=seeded.meeting_id,
            kind="adr",
            state="published",
            title="Replacement digest",
            body="The replacement must not partially overwrite the prior file.",
        )
        conn.commit()

    output_path = tmp_path / "digest.txt"
    output_path.write_text("previous complete digest\n", encoding="utf-8")

    def _fail_replace(_temporary: Path, _destination: Path) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "replace", _fail_replace)

    assert digest_main(["--output", str(output_path)]) == 1
    assert output_path.read_text(encoding="utf-8") == "previous complete digest\n"
    assert "could not write" in capsys.readouterr().err
    assert list(tmp_path.glob(".digest.txt.*")) == []
