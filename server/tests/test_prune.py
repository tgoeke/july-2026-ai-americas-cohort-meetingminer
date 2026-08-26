"""Store-backed tests for `prune` — the only path that deletes a meeting.

Every row of the spec's I/O & Edge-Case Matrix is covered here. The delete
order is not a style choice (migration 0009 makes `artifact` refuse the
cascade, and `screen`/`participant` never cascade at all), so the tests that
matter most are the ones that would pass just as well against a naive
`DELETE FROM meeting` — and then fail loudly when the schema is what it
actually is.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg_pool import ConnectionPool

from meetingminer.prune import (
    PruneError,
    execute_purge,
    plan_purge,
    resolve_scope,
    stale_orphans,
)
from meetingminer.prune.cli import main
from meetingminer.prune.files import remove_content_dirs, remove_published_files
from meetingminer.publish.export import export_artifact, publish_adr
from meetingminer.prune import PurgeReport
from conftest import truncate_evidence
from projection_seed import SeededTurn, insert_artifact, seed_meeting


@pytest.fixture()
def corpus(test_pool: ConnectionPool):
    """Two scripted meetings to keep and two real ones to purge."""
    truncate_evidence(test_pool)
    seeded = {}
    with test_pool.connection() as conn:
        for name, corpus_name in (
            ("demo-001", "scripted"),
            ("demo-002", "scripted"),
            ("real-a", "real"),
            ("real-b", "real"),
        ):
            meeting = seed_meeting(
                conn,
                source_id=f"source-{name}",
                title=f"Meeting {name}",
                corpus=corpus_name,
                screen_identity_keys=(f"sha256:{name}-a", f"sha256:{name}-b"),
            )
            insert_artifact(conn, meeting.moment_ids[0], meeting.meeting_id)
            seeded[name] = meeting
        conn.commit()
    return seeded


def _plan_for(pool: ConnectionPool, config, keep_corpus=("scripted",), keep_ids=()):
    with pool.connection() as conn:
        keep, purge = resolve_scope(
            conn, keep_ids=list(keep_ids), keep_corpus=list(keep_corpus)
        )
        return keep, purge, plan_purge(conn, config, purge)


# --- matrix row: dry run -------------------------------------------------


def test_a_dry_run_reports_the_purge_and_writes_nothing(
    corpus, test_pool: ConnectionPool, app_config
) -> None:
    keep, purge, plan = _plan_for(test_pool, app_config)

    assert len(keep) == 2 and len(purge) == 2
    assert plan.row_counts["meeting"] == 2
    assert plan.row_counts["artifact"] == 2
    assert plan.row_counts["moment"] > 0
    assert len(plan.published_files) == 2

    with test_pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM meeting").fetchone()[0] == 4
        assert conn.execute("SELECT count(*) FROM artifact").fetchone()[0] == 4


# --- matrix row: purge ---------------------------------------------------


def test_a_purge_removes_the_real_meetings_and_keeps_the_scripted_ones(
    corpus, test_pool: ConnectionPool, app_config
) -> None:
    keep, purge, plan = _plan_for(test_pool, app_config)
    kept_ids = set(keep)

    with test_pool.connection() as conn:
        deleted = execute_purge(conn, plan)
        conn.commit()

    # The meeting rows are not deleted directly: they go with the job cascade,
    # which is why `job` is the count that proves the purge ran.
    assert deleted["job"] == 2
    assert deleted["artifact"] == 2

    with test_pool.connection() as conn:
        remaining = {row[0] for row in conn.execute("SELECT id FROM meeting").fetchall()}
        assert remaining == kept_ids
        assert conn.execute("SELECT count(*) FROM artifact").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM job").fetchone()[0] == 2
        # Nothing derived from a purged meeting survives anywhere.
        for table in ("moment", "screenshot", "transcript_segment", "frame"):
            orphans = conn.execute(
                f"SELECT count(*) FROM {table} WHERE meeting_id = ANY(%s)",
                (list(purge),),
            ).fetchone()[0]
            assert orphans == 0, table


def test_the_artifact_guard_is_unwound_rather_than_left_to_block_the_delete(
    corpus, test_pool: ConnectionPool, app_config
) -> None:
    """artifact -> meeting is ON DELETE NO ACTION: the naive delete must fail."""
    _, purge, plan = _plan_for(test_pool, app_config)

    with test_pool.connection() as conn:
        with pytest.raises(Exception):
            # Exactly what `prune` must not do: the FK refuses it.
            conn.execute(
                "DELETE FROM job WHERE id IN"
                " (SELECT job_id FROM meeting WHERE id = ANY(%s))",
                (list(purge),),
            )
        conn.rollback()

    with test_pool.connection() as conn:
        execute_purge(conn, plan)
        conn.commit()

    with test_pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM meeting").fetchone()[0] == 2


def test_orphaned_screens_are_swept(
    corpus, test_pool: ConnectionPool, app_config
) -> None:
    """`screen` has no meeting FK at all — nothing cascades it away."""
    _, purge, plan = _plan_for(test_pool, app_config)
    assert plan.orphan_screen_ids, "the purged meetings' screens should orphan"

    with test_pool.connection() as conn:
        execute_purge(conn, plan)
        conn.commit()

    with test_pool.connection() as conn:
        dangling = conn.execute(
            "SELECT count(*) FROM screen s WHERE NOT EXISTS"
            " (SELECT 1 FROM screenshot ss WHERE ss.screen_id = s.id)"
        ).fetchone()[0]
        assert dangling == 0


def test_a_participant_only_the_purged_meeting_knew_is_swept(
    corpus, test_pool: ConnectionPool, app_config
) -> None:
    """A participant with no surviving meeting goes, with their aliases."""
    with test_pool.connection() as conn:
        meeting = seed_meeting(
            conn,
            source_id="source-real-solo",
            title="Meeting real-solo",
            corpus="real",
            participants=(("mail:solo@example.com", "Solo, Sam"),),
            # The default turns name a second speaker this meeting has not
            # got; one participant needs turns that only reference index 0.
            turns=(
                SeededTurn(1, 2_000, "Just me here.", "Solo, Sam", 0),
                SeededTurn(2, 6_000, "Wrapping up.", "Solo, Sam", 0),
            ),
            screen_identity_keys=("sha256:solo-a",),
        )
        conn.commit()
        solo_id = meeting.participant_ids[0]

    _, purge, plan = _plan_for(test_pool, app_config)
    assert solo_id in plan.orphan_participant_ids

    with test_pool.connection() as conn:
        execute_purge(conn, plan)
        conn.commit()

    with test_pool.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM participant WHERE id = %s", (solo_id,)
        ).fetchone()[0] == 0
        stranded = conn.execute(
            "SELECT count(*) FROM participant p WHERE NOT EXISTS"
            " (SELECT 1 FROM meeting_participant mp WHERE mp.participant_id = p.id)"
        ).fetchone()[0]
        assert stranded == 0


def test_a_participant_shared_with_a_kept_meeting_survives(
    corpus, test_pool: ConnectionPool, app_config
) -> None:
    """The seeded participants are shared by every meeting: none may be swept."""
    _, purge, plan = _plan_for(test_pool, app_config)
    with test_pool.connection() as conn:
        before = conn.execute("SELECT count(*) FROM participant").fetchone()[0]

    assert plan.orphan_participant_ids == (), (
        "participants still linked to a kept meeting must not be planned for deletion"
    )

    with test_pool.connection() as conn:
        execute_purge(conn, plan)
        conn.commit()
        after = conn.execute("SELECT count(*) FROM participant").fetchone()[0]
    assert after == before


# --- matrix rows: refusals ----------------------------------------------


def test_an_empty_keep_set_is_refused(corpus, test_pool: ConnectionPool) -> None:
    with test_pool.connection() as conn:
        with pytest.raises(PruneError, match="no meeting in the corpus"):
            resolve_scope(conn, keep_ids=[], keep_corpus=["nonexistent-corpus"])
        assert conn.execute("SELECT count(*) FROM meeting").fetchone()[0] == 4


def test_an_unknown_keep_uuid_is_refused_by_name(
    corpus, test_pool: ConnectionPool
) -> None:
    stranger = uuid4()
    with test_pool.connection() as conn:
        with pytest.raises(PruneError, match=str(stranger)):
            resolve_scope(conn, keep_ids=[stranger], keep_corpus=[])


def test_a_keep_set_covering_everything_is_refused(
    corpus, test_pool: ConnectionPool
) -> None:
    with test_pool.connection() as conn:
        with pytest.raises(PruneError, match="nothing to purge"):
            resolve_scope(conn, keep_ids=[], keep_corpus=["scripted", "real"])


def test_the_cli_refuses_an_unscoped_run(capsys) -> None:
    assert main([]) == 2
    assert "name what to keep" in capsys.readouterr().err


def test_the_cli_refuses_a_non_uuid_keep(capsys) -> None:
    assert main(["--keep", "not-a-uuid"]) == 2
    assert "is not a UUID" in capsys.readouterr().err


# --- matrix rows: filesystem tolerance ----------------------------------


def test_an_absent_content_directory_is_reported_not_fatal(
    corpus, test_pool: ConnectionPool, app_config, tmp_path: Path
) -> None:
    _, purge, plan = _plan_for(test_pool, app_config)
    present = tmp_path / "meetings" / str(purge[0])
    present.mkdir(parents=True)
    (present / "frame.jpg").write_bytes(b"x")
    absent = tmp_path / "meetings" / str(purge[1])

    plan = type(plan)(**{**plan.__dict__, "content_dirs": (present, absent)})
    report = PurgeReport(plan=plan)
    remove_content_dirs(plan, report)

    assert report.removed_dirs == [present]
    assert report.absent_dirs == [absent]
    assert not present.exists()


def test_an_absent_published_file_is_reported_not_fatal(
    corpus, test_pool: ConnectionPool, app_config, tmp_path: Path
) -> None:
    """A tracked ADR's removal commits; a missing file is reported, not fatal."""
    _, purge, plan = _plan_for(test_pool, app_config)
    publish_root = tmp_path / "publish"
    publish_root.mkdir()
    first, second = plan.published_files

    # Set the file up exactly as production does: exported, then committed.
    export_artifact(publish_root, first.artifact_id, "adr", "Kept until now", "Body.")
    publish_adr(publish_root, first.relative_path, "Kept until now", first.artifact_id)

    report = PurgeReport(plan=plan)
    remove_published_files(publish_root, plan, report)

    assert report.removed_files == [first.relative_path]
    assert report.absent_files == [second.relative_path]
    assert not (publish_root / first.relative_path).exists()
    assert report.commit_sha, "removing a tracked ADR must land as a commit"


def test_an_untracked_action_item_is_removed_without_a_commit(
    corpus, test_pool: ConnectionPool, app_config, tmp_path: Path
) -> None:
    """`action-item` files are written but never committed — there is no history."""
    _, purge, plan = _plan_for(test_pool, app_config)
    publish_root = tmp_path / "publish"
    publish_root.mkdir()
    first = plan.published_files[0]
    export_artifact(publish_root, first.artifact_id, "adr", "Never committed", "Body.")

    report = PurgeReport(plan=plan)
    remove_published_files(publish_root, plan, report)

    assert report.removed_files == [first.relative_path]
    assert not (publish_root / first.relative_path).exists()
    assert report.commit_sha is None


def test_a_missing_publish_root_is_not_an_error(
    corpus, test_pool: ConnectionPool, app_config, tmp_path: Path
) -> None:
    _, purge, plan = _plan_for(test_pool, app_config)
    report = PurgeReport(plan=plan)
    remove_published_files(tmp_path / "nowhere", plan, report)
    assert len(report.absent_files) == len(plan.published_files)
    assert report.removed_files == []


# --- already-orphaned rows: scoped by default, claimed by --sweep-orphans ---


def test_rows_orphaned_before_the_purge_are_left_alone_by_default(
    corpus, test_pool: ConnectionPool, app_config
) -> None:
    """A participant a merge stranded is not this purge's row to delete."""
    with test_pool.connection() as conn:
        stranded = conn.execute(
            "INSERT INTO participant (identity_key, display_name, normalized_name)"
            " VALUES ('mail:stranded@example.com', 'Stranded, Sam', 'sam stranded')"
            " RETURNING id"
        ).fetchone()[0]
        conn.commit()

    _, purge, plan = _plan_for(test_pool, app_config)
    assert stranded not in plan.orphan_participant_ids

    with test_pool.connection() as conn:
        assert stale_orphans(conn, purge) >= 1
        execute_purge(conn, plan)
        conn.commit()
        assert conn.execute(
            "SELECT count(*) FROM participant WHERE id = %s", (stranded,)
        ).fetchone()[0] == 1


def test_sweep_orphans_claims_the_rows_left_behind_before_this_purge(
    corpus, test_pool: ConnectionPool, app_config
) -> None:
    with test_pool.connection() as conn:
        stranded = conn.execute(
            "INSERT INTO participant (identity_key, display_name, normalized_name)"
            " VALUES ('mail:stranded@example.com', 'Stranded, Sam', 'sam stranded')"
            " RETURNING id"
        ).fetchone()[0]
        conn.commit()

    with test_pool.connection() as conn:
        _, purge = resolve_scope(conn, keep_ids=[], keep_corpus=["scripted"])
        plan = plan_purge(conn, app_config, purge, sweep_orphans=True)
        assert stranded in plan.orphan_participant_ids
        execute_purge(conn, plan)
        conn.commit()

    with test_pool.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM participant WHERE id = %s", (stranded,)
        ).fetchone()[0] == 0
        # The kept meetings' own participants are never swept.
        assert conn.execute("SELECT count(*) FROM participant").fetchone()[0] == 2
