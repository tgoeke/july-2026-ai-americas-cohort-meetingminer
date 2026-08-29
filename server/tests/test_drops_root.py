"""Story 2.1a: every stored evidence path is anchored to a configured root.

The regression this file exists to prevent is a single one, stated three ways:
moving the drops folder must not break replay, must not break a stage rerun's
transcript re-parse, and must not break the augmentation door's comparison —
while the frames and screenshots anchored to MM_CONTENT_ROOT keep working.
`test_relocating_both_roots_breaks_nothing` is the whole story in one test; the
rest pin the pieces it is built from, because a relocation test that fails
tells you nothing about *which* anchor slipped.

The pure-path tests run without a store. Everything below the fixtures needs
Postgres (`meetingminer_test`), and the relocation and provenance tests also
need ffmpeg.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import psycopg
import pytest
import yaml
from psycopg_pool import ConnectionPool

from meetingminer import backfill
from meetingminer.backfill import backfill_drop_paths
from meetingminer.config import AppConfig, ConfigError, require_drops_root
from meetingminer.domain.drops import (
    CANONICAL_FILENAMES,
    DropPathError,
    SymlinkedEvidenceError,
    assert_unlinked_evidence,
    drop_relative_path,
    read_drop,
    resolve_drop_path,
    sha256_and_size,
)
from meetingminer.domain.jobs import UNBACKFILLED_DROP_PATH_ERROR
from meetingminer.pipeline import runner

from conftest import (
    DROPS_ROOT,
    TEST_DATABASE,
    DropFactory,
    requires_ffmpeg,
    truncate_evidence,
    valid_metadata,
)
from repo_paths import REPO_ROOT


def _cli_config(app_config: AppConfig) -> AppConfig:
    """`app_config`, but pointed at the test database.

    `backfill.main()` builds its own connection from `config.settings`, so
    driving the real entry point means giving it a config whose Postgres
    database is `meetingminer_test` — otherwise the command under test would
    reach for the developer's own data.
    """
    stores = app_config.settings.stores
    return app_config.model_copy(
        update={
            "settings": app_config.settings.model_copy(
                update={
                    "stores": stores.model_copy(
                        update={
                            "postgres": stores.postgres.model_copy(
                                update={"database": TEST_DATABASE}
                            )
                        }
                    )
                }
            )
        }
    )
from test_worker_runner import enqueue, meetings, stage_statuses

PROBLEM = "application/problem+json"

# A minimal participant graph: enough for the augmentation door to have a
# non-empty array to compare, which is what makes reading the *target* drop's
# metadata.json observable in the relocation test.
GRAPH = [{"displayName": "Goeke, Timothy", "mail": "timothy.goeke@contoso.com"}]


@pytest.fixture()
def make_recording_drop(
    make_drop: DropFactory, synthetic_recording: Path
) -> Callable[..., Path]:
    """A drop carrying a real (generated) recording.mp4.

    A copy of `test_worker_runner`'s fixture rather than an import, because a
    fixture defined in a test module is not visible from another one.
    """

    def _make(source_id: str = "source-rec", **overrides: Any) -> Path:
        drop = make_drop(metadata=valid_metadata(source_id, **overrides), files=())
        (drop / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
        return drop

    return _make


def _slug(response: Any) -> str:
    return response.json()["type"].removeprefix("urn:meetingminer:problem:")


_LEGACY_TRANSCRIPT_CONSTRAINT = """
ALTER TABLE transcript_source
ADD CONSTRAINT transcript_source_drop_relative_path_is_root_relative
CHECK (
    drop_relative_path IS NULL
    OR (
        drop_relative_path <> ''
        AND drop_relative_path NOT LIKE '/%'
        AND drop_relative_path !~ '(^|/)\\.\\.(/|$)'
        AND drop_relative_path !~ '(^|/)\\.(/|$)'
        AND drop_relative_path !~ '//'
        AND drop_relative_path !~ '/$'
        AND drop_relative_path ~ '^[^/]+/[^/]+.*$'
    )
) NOT VALID
"""


def _insert_pre_migration_transcript(
    conn: Any,
    meeting_id: Any,
    kind: str,
    format_: str,
    path: str,
    digest: str,
    size: int,
) -> None:
    """Seed a legacy bare path that existed before migration 0008.

    PostgreSQL checks a NOT VALID constraint for new writes, so tests running
    against the current schema temporarily recreate it around the historical
    insert.  The restored constraint keeps every later direct-SQL assertion
    honest while modelling the upgrade state the backfill must handle.
    """
    conn.execute(
        "ALTER TABLE transcript_source DROP CONSTRAINT"
        " transcript_source_drop_relative_path_is_root_relative"
    )
    try:
        conn.execute(
            "INSERT INTO transcript_source (meeting_id, kind, format,"
            " drop_relative_path, sha256, byte_size)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (meeting_id, kind, format_, path, digest, size),
        )
    finally:
        conn.execute(_LEGACY_TRANSCRIPT_CONSTRAINT)


# --- the two directions, without a store ------------------------------------


def test_a_path_under_the_root_relativizes_to_its_directory_name(tmp_path: Path) -> None:
    root = tmp_path / "drops"
    (root / "2026-08-05-standup-abc12345").mkdir(parents=True)
    assert (
        drop_relative_path(root, root / "2026-08-05-standup-abc12345")
        == "2026-08-05-standup-abc12345"
    )


def test_a_path_outside_the_root_is_refused_naming_both(tmp_path: Path) -> None:
    root = tmp_path / "drops"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "drop"
    outside.mkdir(parents=True)
    with pytest.raises(DropPathError) as exc:
        drop_relative_path(root, outside)
    assert str(outside) in str(exc.value)
    assert str(root.resolve()) in str(exc.value)


def test_the_root_itself_is_not_a_drop(tmp_path: Path) -> None:
    root = tmp_path / "drops"
    root.mkdir()
    with pytest.raises(DropPathError):
        drop_relative_path(root, root)


def test_a_symlinked_ancestor_of_the_posted_path_is_not_an_escape(
    tmp_path: Path,
) -> None:
    """`/tmp` against `/private/tmp` is the everyday macOS case, not an attack.

    The poster's spelling and the configured root may differ by a symlinked
    ancestor and still mean the same directory; refusing that would refuse
    every ordinary drop on this machine.
    """
    real = tmp_path / "real-drops"
    (real / "drop-1").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert drop_relative_path(real, alias / "drop-1") == "drop-1"


def test_resolution_round_trips_a_relativized_path(tmp_path: Path) -> None:
    root = tmp_path / "drops"
    drop = root / "drop-1"
    drop.mkdir(parents=True)
    assert resolve_drop_path(root, drop_relative_path(root, drop)) == drop


@pytest.mark.parametrize(
    "stored",
    [
        "../escape",
        "drop/../../escape",
        "/absolute/drop",
        "",
        "drop\x00name",
        "./drop",
        "drop//recording.mp4",
        "drop/",
    ],
)
def test_resolution_refuses_a_noncanonical_path_under_the_root(
    tmp_path: Path, stored: str
) -> None:
    root = tmp_path / "drops"
    root.mkdir()
    with pytest.raises(DropPathError):
        resolve_drop_path(root, stored)


def test_resolution_refuses_a_symlinked_component(tmp_path: Path) -> None:
    root = tmp_path / "drops"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "drop-1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SymlinkedEvidenceError):
        resolve_drop_path(root, "drop-1")


def test_resolution_does_not_require_the_file_to_exist(tmp_path: Path) -> None:
    """Containment and existence are separate questions with separate answers."""
    root = tmp_path / "drops"
    root.mkdir()
    assert resolve_drop_path(root, "drop-1/recording.mp4") == (
        root / "drop-1" / "recording.mp4"
    )


# Parametrized over the constant, not over a copy of it: a canonical filename
# added by a later story (story 4.1a added two) would otherwise inherit no
# symlink coverage at all, which is precisely the file whose checksum is
# recorded and whose target could then be repointed.
@pytest.mark.parametrize("name", CANONICAL_FILENAMES)
def test_a_symlinked_canonical_file_is_refused(tmp_path: Path, name: str) -> None:
    drop = tmp_path / "drop"
    drop.mkdir()
    target = tmp_path / "target"
    target.write_bytes(b"elsewhere")
    (drop / name).symlink_to(target)
    with pytest.raises(SymlinkedEvidenceError) as exc:
        assert_unlinked_evidence(drop)
    assert name in str(exc.value)


def test_a_hard_link_is_not_a_symlink(tmp_path: Path) -> None:
    """A hard link is the same inode, so the bytes cannot change under the row."""
    drop = tmp_path / "drop"
    drop.mkdir()
    source = tmp_path / "recording-source.mp4"
    source.write_bytes(b"video")
    (drop / "recording.mp4").hardlink_to(source)
    assert_unlinked_evidence(drop)  # does not raise


# --- the config gate --------------------------------------------------------


def _with_drops_root(config: AppConfig, root: Path | None) -> AppConfig:
    return config.model_copy(
        update={"secrets": config.secrets.model_copy(update={"mm_drops_root": root})}
    )


def test_require_drops_root_rejects_an_unset_root(app_config: AppConfig) -> None:
    with pytest.raises(ConfigError) as exc:
        require_drops_root(_with_drops_root(app_config, None))
    assert "MM_DROPS_ROOT is not set" in str(exc.value)


def test_require_drops_root_rejects_a_missing_root(
    app_config: AppConfig, tmp_path: Path
) -> None:
    """Absent is a fatal misconfiguration, never a directory to create.

    Creating it would turn "the drops volume is not mounted" into "no meetings
    have ingested yet", and nothing in MeetingMiner writes inside a drop
    anyway (AD-13).
    """
    missing = tmp_path / "not-mounted"
    with pytest.raises(ConfigError) as exc:
        require_drops_root(_with_drops_root(app_config, missing))
    assert str(missing) in str(exc.value)
    assert not missing.exists()


def test_require_drops_root_rejects_a_file(
    app_config: AppConfig, tmp_path: Path
) -> None:
    a_file = tmp_path / "drops"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        require_drops_root(_with_drops_root(app_config, a_file))
    assert "not a directory" in str(exc.value)


def test_require_drops_root_rejects_an_unreadable_directory(
    app_config: AppConfig, drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mounted-but-unreadable root fails at startup, without a write probe."""
    import meetingminer.config as config_module

    def denied(_path: Path) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(config_module.os, "scandir", denied)
    with pytest.raises(ConfigError, match="not readable and traversable"):
        require_drops_root(_with_drops_root(app_config, drops_root))


def test_require_drops_root_returns_the_configured_root(
    app_config: AppConfig, drops_root: Path
) -> None:
    assert require_drops_root(app_config) == drops_root


# --- intake (store-backed) --------------------------------------------------


def _submit(client: Any, drop: Path) -> Any:
    return client.post("/ingests", json={"dropPath": str(drop)})


def _job_count(pool: ConnectionPool) -> int:
    with pool.connection() as conn:
        return conn.execute("SELECT count(*) FROM job").fetchone()[0]


def test_intake_stores_the_path_relative_to_the_root(
    client: Any, test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    drop = make_drop()
    job_id = _submit(client, drop).json()["jobId"]

    with test_pool.connection() as conn:
        stored, legacy = conn.execute(
            "SELECT drop_relative_path, drop_path FROM job WHERE id = %s", (job_id,)
        ).fetchone()

    assert stored == drop.name
    assert not Path(stored).is_absolute()
    assert legacy is None, "no absolute path is written anywhere"
    assert resolve_drop_path(drops_root, stored) == drop


def test_intake_refuses_a_drop_outside_the_root(
    client: Any, test_pool: ConnectionPool, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "metadata.json").write_text('{"x": 1}', encoding="utf-8")

    response = _submit(client, outside)

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM
    assert _slug(response) == "invalid-drop-path"
    detail = response.json()["detail"]
    assert str(outside) in detail, "the refusal names the path"
    assert str(DROPS_ROOT) in detail, "and the configured root"
    assert _job_count(test_pool) == 0, "no job row is created"


@pytest.mark.parametrize(
    "name", ["metadata.json", "recording.mp4", "transcript.vtt", "transcript.txt"]
)
def test_intake_refuses_symlinked_evidence(
    client: Any,
    test_pool: ConnectionPool,
    make_drop: DropFactory,
    tmp_path: Path,
    name: str,
) -> None:
    """Refused before a job row exists, where today it 404s at replay.

    `present()` uses `is_file()`, which follows links, so a symlinked
    recording is admitted, reports `has_recording=true`, and only fails when
    something asks for the bytes.
    """
    drop = make_drop(files=("transcript.txt",))
    (drop / name).unlink(missing_ok=True)
    target = tmp_path / f"target-{name}"
    target.write_text("elsewhere", encoding="utf-8")
    (drop / name).symlink_to(target)

    response = _submit(client, drop)

    assert response.status_code == 400
    assert _slug(response) == "symlinked-evidence"
    assert _job_count(test_pool) == 0


def test_intake_refuses_a_symlinked_drop_directory(
    client: Any, test_pool: ConnectionPool, make_drop: DropFactory
) -> None:
    real = make_drop()
    link = DROPS_ROOT / f"{real.name}-via-symlink"
    link.symlink_to(real, target_is_directory=True)
    try:
        response = _submit(client, link)
    finally:
        link.unlink()

    assert response.status_code == 400
    assert _slug(response) == "symlinked-evidence"
    assert _job_count(test_pool) == 0


# --- the recording's provenance row -----------------------------------------


def _recording_row(pool: ConnectionPool, meeting_id: Any) -> tuple[Any, ...] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT drop_relative_path, sha256, size_bytes FROM meeting_media"
            " WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()


@requires_ffmpeg
def test_probe_records_the_recording_path_checksum_and_size(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
) -> None:
    truncate_evidence(test_pool)
    drop = make_recording_drop("rec-provenance")
    job_id = enqueue(test_pool, drop, "rec-provenance")

    assert runner.run_once(test_pool, app_config, content_root) is True

    meeting_id = meetings(test_pool, job_id)[0]["id"]
    relative, digest, size = _recording_row(test_pool, meeting_id)
    assert relative == f"{drop.name}/recording.mp4"
    assert len(digest) == 64
    assert size == (drop / "recording.mp4").stat().st_size


@requires_ffmpeg
def test_a_transcript_only_meeting_records_no_recording_path(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
) -> None:
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("rec-none"), files=("transcript.txt",))
    job_id = enqueue(test_pool, drop, "rec-none")

    assert runner.run_once(test_pool, app_config, content_root) is True

    meeting_id = meetings(test_pool, job_id)[0]["id"]
    assert stage_statuses(test_pool, job_id)["probe"] == "skipped"
    assert _recording_row(test_pool, meeting_id) is None


@requires_ffmpeg
def test_a_rerun_over_unchanged_bytes_records_the_same_checksum(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
) -> None:
    truncate_evidence(test_pool)
    job_id = enqueue(test_pool, make_recording_drop("rec-rerun"), "rec-rerun")
    assert runner.run_once(test_pool, app_config, content_root) is True
    meeting_id = meetings(test_pool, job_id)[0]["id"]
    before = _recording_row(test_pool, meeting_id)

    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'queued' WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'queued' WHERE id = %s", (job_id,))
    assert runner.run_once(test_pool, app_config, content_root) is True

    assert _recording_row(test_pool, meeting_id) == before


@requires_ffmpeg
def test_a_substituted_recording_is_detected_on_rerun(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
) -> None:
    """The whole reason the checksum comes along now.

    A swapped transcript has always been detectable; the recording is the
    larger and more consequential input and had no such protection.
    """
    truncate_evidence(test_pool)
    drop = make_recording_drop("rec-substituted")
    job_id = enqueue(test_pool, drop, "rec-substituted")
    assert runner.run_once(test_pool, app_config, content_root) is True
    meeting_id = meetings(test_pool, job_id)[0]["id"]
    original = _recording_row(test_pool, meeting_id)

    recording = drop / "recording.mp4"
    recording.write_bytes(recording.read_bytes() + b"\x00" * 64)
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'queued' WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'queued' WHERE id = %s", (job_id,))
    assert runner.run_once(test_pool, app_config, content_root) is True

    with test_pool.connection() as conn:
        status, error = conn.execute(
            "SELECT status, error FROM job WHERE id = %s", (job_id,)
        ).fetchone()
    assert status == "failed"
    assert "same drop-relative path" in error
    assert _recording_row(test_pool, meeting_id) == original


@requires_ffmpeg
def test_a_sibling_drop_recording_is_a_legitimate_augmentation(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
) -> None:
    """A different anchored path is new arrived evidence, not substitution."""
    truncate_evidence(test_pool)
    first = make_recording_drop("rec-sibling")
    job_id = enqueue(test_pool, first, "rec-sibling")
    assert runner.run_once(test_pool, app_config, content_root) is True
    meeting_id = meetings(test_pool, job_id)[0]["id"]
    original = _recording_row(test_pool, meeting_id)

    sibling = make_recording_drop("rec-sibling")
    recording = sibling / "recording.mp4"
    recording.write_bytes(recording.read_bytes() + b"\x00" * 64)
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE job SET drop_relative_path = %s, status = 'queued' WHERE id = %s",
            (sibling.name, job_id),
        )
        conn.execute(
            "UPDATE job_stage SET status = 'queued' WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        )

    assert runner.run_once(test_pool, app_config, content_root) is True

    changed = _recording_row(test_pool, meeting_id)
    assert changed[0] == f"{sibling.name}/recording.mp4"
    assert changed[1] != original[1]


# --- the regression this story exists to prevent ----------------------------


@requires_ffmpeg
def test_relocating_both_roots_breaks_nothing(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    make_drop: DropFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move both roots, update the environment, change no data.

    Replay serves the recording, a stage rerun re-parses the transcript from
    the drop, and the augmentation door reads the target's `metadata.json` —
    all three resolve through the configured roots, so all three survive. Under
    the old absolute `job.drop_path` every one of them broke together.
    """
    import meetingminer.api.main as api_main

    truncate_evidence(test_pool)
    # The target carries a participant graph, so the augmentation check below
    # has an answer that differs depending on whether the relocated drop's
    # metadata.json was actually read: readable means "already has a graph"
    # (409), unreadable means "no graph, so this drop adds one" (422).
    drop = make_recording_drop("relocate-1", participants=GRAPH)
    (drop / "transcript.txt").write_text(
        "[0:02] Goeke, Timothy: Everybody, good morning.\n", encoding="utf-8"
    )
    job_id = enqueue(test_pool, drop, "relocate-1")
    assert runner.run_once(test_pool, app_config, content_root) is True
    meeting_id = meetings(test_pool, job_id)[0]["id"]

    def segment_texts() -> list[str]:
        with test_pool.connection() as conn:
            return [
                row[0]
                for row in conn.execute(
                    "SELECT text FROM transcript_segment WHERE meeting_id = %s"
                    " ORDER BY ordinal",
                    (meeting_id,),
                ).fetchall()
            ]

    assert segment_texts() == ["Everybody, good morning."]

    # --- the relocation itself: files move, the database does not change ----
    new_drops = tmp_path / "relocated-drops"
    new_drops.mkdir()
    shutil.move(str(drop), str(new_drops / drop.name))
    new_content = tmp_path / "relocated-content"
    shutil.move(str(content_root), str(new_content))
    relocated = app_config.model_copy(
        update={
            "secrets": app_config.secrets.model_copy(
                update={"mm_drops_root": new_drops, "mm_content_root": new_content}
            )
        }
    )
    monkeypatch.setattr(api_main.app.state, "config", relocated)

    # 1. replay still serves the recording, byte for byte.
    response = client.get(f"/media/recordings/{meeting_id}")
    assert response.status_code == 200, response.text
    assert response.content == (new_drops / drop.name / "recording.mp4").read_bytes()

    # 2. a stage rerun still re-parses the provided transcript from the drop.
    with test_pool.connection() as conn:
        conn.execute("DELETE FROM transcript_segment WHERE meeting_id = %s", (meeting_id,))
        conn.execute(
            "UPDATE job_stage SET status = 'queued'"
            " WHERE job_id = %s AND name IN ('align', 'moments')",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'queued' WHERE id = %s", (job_id,))
    assert segment_texts() == []
    assert runner.run_once(test_pool, relocated, new_content) is True
    assert segment_texts() == ["Everybody, good morning."]

    # 3. the augmentation door still reads the target occurrence's metadata.
    #    It re-reads `metadata.json` out of the relocated drop to decide the
    #    incoming drop adds nothing — a comparison that answers "no graph" for
    #    an unreadable target, which is the failure this guards against.
    augmenting = make_drop(
        metadata=valid_metadata(
            "relocate-1",
            schemaVersion=2,
            augments={"sourceId": "relocate-1"},
            participants=GRAPH,
        ),
        files=("transcript.txt",),
    )
    shutil.move(str(augmenting), str(new_drops / augmenting.name))
    refused = _submit(client, new_drops / augmenting.name)
    assert refused.status_code == 409, refused.text
    assert _slug(refused) == "augment-adds-nothing"


# --- the backfill -----------------------------------------------------------


def test_backfill_converts_a_legacy_absolute_path(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("legacy-1"))
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')"
            " RETURNING id",
            ("legacy-1", str(drop)),
        ).fetchone()[0]

        report = backfill_drop_paths(conn, drops_root)

        stored, legacy = conn.execute(
            "SELECT drop_relative_path, drop_path FROM job WHERE id = %s", (job_id,)
        ).fetchone()

    assert report.ok
    assert report.converted_jobs == [(str(job_id), drop.name)]
    assert (stored, legacy) == (drop.name, None)


def test_backfill_names_every_row_it_cannot_place_and_is_not_ok(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """A partial backfill must not be able to look like a clean one."""
    truncate_evidence(test_pool)
    placeable = make_drop(metadata=valid_metadata("legacy-ok"))
    with test_pool.connection() as conn:
        conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')",
            ("legacy-ok", str(placeable)),
        )
        conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')",
            ("legacy-elsewhere", "/somewhere/else/drop-9"),
        )

        report = backfill_drop_paths(conn, drops_root)

    assert not report.ok
    assert len(report.converted_jobs) == 1, "the placeable row is still converted"
    assert len(report.problems) == 1
    assert "/somewhere/else/drop-9" in report.problems[0]


def test_backfill_is_idempotent(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("legacy-twice"))
    with test_pool.connection() as conn:
        conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')",
            ("legacy-twice", str(drop)),
        )
        first = backfill_drop_paths(conn, drops_root)
        second = backfill_drop_paths(conn, drops_root)

    assert len(first.converted_jobs) == 1
    assert second.converted_jobs == []
    assert second.already_relative == 1
    assert second.ok


def test_backfill_widens_a_bare_transcript_filename(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """`storage-layout.md` §5: a recorded path is never relative to the drop."""
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("legacy-transcript"))
    transcript_digest, transcript_size = sha256_and_size(drop / "transcript.txt")
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')"
            " RETURNING id",
            ("legacy-transcript", str(drop)),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'legacy-transcript', 'real', '2026-08-05T12:00:19Z',"
            " 'second', false) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        _insert_pre_migration_transcript(
            conn,
            meeting_id,
            "provided-text",
            "teams",
            "transcript.txt",
            transcript_digest,
            transcript_size,
        )

        report = backfill_drop_paths(conn, drops_root)

        widened = conn.execute(
            "SELECT drop_relative_path FROM transcript_source WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()[0]

    assert report.ok
    assert report.converted_transcripts == 1
    assert widened == f"{drop.name}/transcript.txt"


@requires_ffmpeg
def test_backfill_records_the_recording_row_for_an_ingested_meeting(
    test_pool: ConnectionPool,
    make_recording_drop: Callable[..., Path],
    drops_root: Path,
) -> None:
    """A meeting ingested before 2.1a has no recording row; replay needs one."""
    truncate_evidence(test_pool)
    drop = make_recording_drop("legacy-recorded")
    recording = drop / "recording.mp4"
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')"
            " RETURNING id",
            ("legacy-recorded", str(drop)),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'legacy-recorded', 'real', '2026-08-05T12:00:19Z',"
            " 'second', true) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO meeting_media (meeting_id, size_bytes) VALUES (%s, %s)",
            (meeting_id, recording.stat().st_size),
        )

        report = backfill_drop_paths(conn, drops_root)

        stored, digest, size = conn.execute(
            "SELECT drop_relative_path, sha256, size_bytes FROM meeting_media"
            " WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()

    assert report.ok
    assert report.converted_media == 1
    assert stored == f"{drop.name}/recording.mp4"
    assert len(digest) == 64
    assert size == recording.stat().st_size


def test_backfill_reports_a_recording_it_cannot_read(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    truncate_evidence(test_pool)
    drop = make_drop(
        metadata=valid_metadata("legacy-gone"), files=("transcript.txt",)
    )  # no recording.mp4 on disk
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')"
            " RETURNING id",
            ("legacy-gone", str(drop)),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'legacy-gone', 'real', '2026-08-05T12:00:19Z',"
            " 'second', true) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO meeting_media (meeting_id, size_bytes) VALUES (%s, 1)",
            (meeting_id,),
        )

        report = backfill_drop_paths(conn, drops_root)

    assert not report.ok
    assert len(report.problems) == 1
    assert "recording.mp4" in report.problems[0]


def test_backfill_refuses_a_symlink_file_or_malformed_legacy_drop(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """Contained is not enough: only a real, readable source drop can anchor."""
    truncate_evidence(test_pool)
    valid = make_drop()
    symlink = drops_root / f"{valid.name}-symlink"
    symlink.symlink_to(valid, target_is_directory=True)
    regular_file = drops_root / "legacy-not-a-directory"
    regular_file.write_text("not a drop", encoding="utf-8")
    malformed = drops_root / "legacy-malformed"
    malformed.mkdir()
    try:
        with test_pool.connection() as conn:
            job_ids = [
                _seed_legacy_job(conn, "legacy-symlink", symlink),
                _seed_legacy_job(conn, "legacy-file", regular_file),
                _seed_legacy_job(conn, "legacy-malformed", malformed),
            ]
            report = backfill_drop_paths(conn, drops_root)
            stored = conn.execute(
                "SELECT id, drop_relative_path FROM job WHERE id = ANY(%s)",
                (job_ids,),
            ).fetchall()
    finally:
        symlink.unlink()

    assert not report.ok
    assert len(report.problems) == 3
    assert {relative for _, relative in stored} == {None}


def test_backfill_refuses_tampered_transcript_provenance(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("tampered-transcript"))
    transcript = drop / "transcript.txt"
    digest, size = sha256_and_size(transcript)
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(conn, "tampered-transcript", drop)
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'tampered-transcript', 'real', '2026-08-05T12:00:19Z',"
            " 'second', false) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        _insert_pre_migration_transcript(
            conn,
            meeting_id,
            "provided-text",
            "teams",
            "transcript.txt",
            digest,
            size,
        )
        transcript.write_bytes(transcript.read_bytes() + b"tampered")

        report = backfill_drop_paths(conn, drops_root)
        stored = conn.execute(
            "SELECT drop_relative_path FROM transcript_source WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()[0]

    assert not report.ok
    assert "does not match its recorded sha256 and byte_size" in report.problems[0]
    assert stored == "transcript.txt"


def test_backfill_refuses_a_tampered_already_anchored_transcript(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """Existing anchors are revalidated, not trusted because they have a slash."""
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("anchored-tampered-transcript"))
    transcript = drop / "transcript.txt"
    digest, size = sha256_and_size(transcript)
    stored_path = f"{drop.name}/transcript.txt"
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus)"
            " VALUES ('anchored-tampered-transcript', %s, 'real') RETURNING id",
            (drop.name,),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'anchored-tampered-transcript', 'real',"
            " '2026-08-05T12:00:19Z', 'second', false) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO transcript_source (meeting_id, kind, format,"
            " drop_relative_path, sha256, byte_size)"
            " VALUES (%s, 'provided-text', 'teams', %s, %s, %s)",
            (meeting_id, stored_path, digest, size),
        )
        transcript.write_bytes(transcript.read_bytes() + b"tampered")

        report = backfill_drop_paths(conn, drops_root)
        stored = conn.execute(
            "SELECT drop_relative_path, sha256, byte_size FROM transcript_source"
            " WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()

    assert not report.ok
    assert "does not match its recorded sha256 and byte_size" in report.problems[0]
    assert stored == (stored_path, digest, size)


def test_backfill_refuses_a_valid_drop_for_a_different_job(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """Containment and schema validity do not make another job's drop ours."""
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("other-source", corpus="scripted"))
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(conn, "expected-source", drop)
        report = backfill_drop_paths(conn, drops_root)
        stored = conn.execute(
            "SELECT drop_path, drop_relative_path FROM job WHERE id = %s", (job_id,)
        ).fetchone()

    assert not report.ok
    assert "other-source" in report.problems[0]
    assert "scripted" in report.problems[0]
    assert stored == (str(drop), None)


@requires_ffmpeg
def test_backfill_checks_an_already_anchored_recording_provenance(
    test_pool: ConnectionPool,
    make_recording_drop: Callable[..., Path],
    drops_root: Path,
) -> None:
    truncate_evidence(test_pool)
    drop = make_recording_drop("anchored-tampered-recording")
    recording = drop / "recording.mp4"
    digest, size = sha256_and_size(recording)
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus)"
            " VALUES ('anchored-tampered-recording', %s, 'real') RETURNING id",
            (drop.name,),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'anchored-tampered-recording', 'real', '2026-08-05T12:00:19Z',"
            " 'second', true) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO meeting_media (meeting_id, drop_relative_path, sha256, size_bytes)"
            " VALUES (%s, %s, %s, %s)",
            (meeting_id, f"{drop.name}/recording.mp4", digest, size),
        )
        recording.write_bytes(recording.read_bytes() + b"tampered")

        report = backfill_drop_paths(conn, drops_root)
        stored = conn.execute(
            "SELECT drop_relative_path, sha256 FROM meeting_media WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()

    assert not report.ok
    assert "does not match its recorded sha256 and size_bytes" in report.problems[0]
    assert stored == (f"{drop.name}/recording.mp4", digest)


# --- a row the backfill never reached ---------------------------------------


def test_a_job_with_no_relative_path_fails_naming_the_backfill(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
) -> None:
    """The worker says what to run rather than failing as a missing directory."""
    truncate_evidence(test_pool)
    drop = make_drop()
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')"
            " RETURNING id",
            ("unbackfilled", str(drop)),
        ).fetchone()[0]

    assert runner.run_once(test_pool, app_config, content_root) is True

    with test_pool.connection() as conn:
        status, error = conn.execute(
            "SELECT status, error FROM job WHERE id = %s", (job_id,)
        ).fetchone()
    assert status == "failed"
    assert "backfill" in error


@pytest.mark.parametrize(
    "escaping",
    ["/absolute/drop", "../outside", "drop/../x", "", ".", "./", "drop//leaf", "drop/"],
)
def test_the_database_refuses_a_job_path_that_is_not_root_relative(
    test_pool: ConnectionPool, escaping: str
) -> None:
    """Migration 0008 makes the anchor rule the database's, not a convention.

    The application guards refuse these at resolution time; the CHECK makes a
    row carrying one impossible to write at all, from any client — including a
    psql session no reviewer is watching.
    """
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO job (source_id, drop_relative_path, corpus)"
                " VALUES (%s, %s, 'real')",
                ("escaping", escaping),
            )
        conn.rollback()


@pytest.mark.parametrize(
    "escaping",
    [
        "/absolute/x.mp4",
        "../outside.mp4",
        "recording.mp4",
        "./recording.mp4",
        "drop//recording.mp4",
        "drop/",
    ],
)
def test_the_database_refuses_a_recording_path_that_is_not_root_relative(
    test_pool: ConnectionPool, make_drop: DropFactory, escaping: str
) -> None:
    """The same constraint on the recording's own column."""
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus)"
            " VALUES ('check-media', %s, 'real') RETURNING id",
            (make_drop().name,),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'check-media', 'real', '2026-08-05T12:00:19Z',"
            " 'second', true) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO meeting_media (meeting_id, drop_relative_path, sha256)"
                " VALUES (%s, %s, %s)",
                (meeting_id, escaping, "0" * 64),
            )
        conn.rollback()


def test_the_database_refuses_a_recording_path_without_its_checksum(
    test_pool: ConnectionPool, make_drop: DropFactory
) -> None:
    """A path with no checksum is provenance that proves nothing."""
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus)"
            " VALUES ('check-half', %s, 'real') RETURNING id",
            (make_drop().name,),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'check-half', 'real', '2026-08-05T12:00:19Z',"
            " 'second', true) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO meeting_media (meeting_id, drop_relative_path)"
                " VALUES (%s, 'drop-1/recording.mp4')",
                (meeting_id,),
            )
        conn.rollback()


def test_the_database_refuses_two_job_anchors(
    test_pool: ConnectionPool, make_drop: DropFactory
) -> None:
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO job (source_id, drop_path, drop_relative_path, corpus)"
                " VALUES ('two-anchors', %s, %s, 'real')",
                ("/legacy/drop", make_drop().name),
            )
        conn.rollback()


@pytest.mark.parametrize(
    "stored",
    ["transcript.txt", "./transcript.txt", "drop//transcript.txt", "drop/"],
)
def test_the_database_refuses_a_transcript_path_without_a_drop_directory(
    test_pool: ConnectionPool, make_drop: DropFactory, stored: str
) -> None:
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus)"
            " VALUES ('check-transcript', %s, 'real') RETURNING id",
            (make_drop().name,),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'check-transcript', 'real', '2026-08-05T12:00:19Z',"
            " 'second', false) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO transcript_source (meeting_id, kind, format,"
                " drop_relative_path, sha256, byte_size)"
                " VALUES (%s, 'provided-text', 'teams', %s, %s, 1)",
                (meeting_id, stored, "0" * 64),
            )
        conn.rollback()


@pytest.mark.parametrize(
    "stored",
    [
        "extraction-summary.md",  # no drop-directory component
        "/abs/drop/extraction-summary.md",
        "drop/../../etc/extraction-summary.md",
        "./drop/extraction-summary.md",
        "drop//extraction-summary.md",
        "drop/",
    ],
)
def test_the_database_refuses_an_extraction_source_path_outside_the_anchor(
    test_pool: ConnectionPool, make_drop: DropFactory, stored: str
) -> None:
    """Migration 0010 copies 0008's root-relative CHECK; it has to hold.

    The application guards refuse these at resolution time; the constraint
    makes a row carrying one impossible to write from any client, psql
    included.
    """
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        meeting_id = _meeting_for_constraint(conn, make_drop, "check-extraction")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO extraction_source (meeting_id, kind, origin,"
                " drop_relative_path, sha256, byte_size, layout)"
                " VALUES (%s, 'arch-summary', 'adopted', %s, %s, 1, 'table')",
                (meeting_id, stored, "0" * 64),
            )
        conn.rollback()


@pytest.mark.parametrize(
    "origin, path",
    [
        # A generated document has no drop file, so a path describes one
        # nothing wrote.
        ("generated", "drop-1/extraction-summary.md"),
        # And an adopted one is arrived material (AD-17): a row with no path
        # names no file at all.
        ("adopted", None),
    ],
)
def test_the_database_refuses_an_extraction_source_whose_path_contradicts_its_origin(
    test_pool: ConnectionPool, make_drop: DropFactory, origin: str, path: str | None
) -> None:
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        meeting_id = _meeting_for_constraint(conn, make_drop, "check-origin")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO extraction_source (meeting_id, kind, origin,"
                " drop_relative_path, sha256, byte_size, layout)"
                " VALUES (%s, 'arch-summary', %s, %s, %s, 1, 'table')",
                (meeting_id, origin, path, "0" * 64),
            )
        conn.rollback()


def test_the_database_refuses_more_artifacts_than_the_document_parsed(
    test_pool: ConnectionPool, make_drop: DropFactory
) -> None:
    """`artifact_count <= item_count`: inserted is a subset of parsed."""
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        meeting_id = _meeting_for_constraint(conn, make_drop, "check-counts")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO extraction_source (meeting_id, kind, origin,"
                " drop_relative_path, sha256, byte_size, layout, item_count,"
                " artifact_count) VALUES (%s, 'arch-summary', 'generated', NULL,"
                " %s, 1, 'table', 1, 2)",
                (meeting_id, "0" * 64),
            )
        conn.rollback()


def _meeting_for_constraint(
    conn: Any, make_drop: DropFactory, source_id: str
) -> Any:
    """One job + meeting, the minimum a constraint test needs to insert against."""
    job_id = conn.execute(
        "INSERT INTO job (source_id, drop_relative_path, corpus)"
        " VALUES (%s, %s, 'real') RETURNING id",
        (source_id, make_drop().name),
    ).fetchone()[0]
    return conn.execute(
        "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
        " started_at_precision, has_recording)"
        " VALUES (%s, %s, 'real', '2026-08-05T12:00:19Z', 'second', false)"
        " RETURNING id",
        (job_id, source_id),
    ).fetchone()[0]


def test_a_stored_path_resolving_through_a_symlink_fails_the_job(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
) -> None:
    """The escape the CHECK cannot see: a legal-looking name that is a link.

    `..` and a leading `/` are refused by the column constraint, so the only
    way a stored path leaves the root is a component that became a symlink
    after the row was written. The runner refuses it rather than following it.
    """
    truncate_evidence(test_pool)
    real = make_drop()
    link = DROPS_ROOT / f"{real.name}-link"
    link.symlink_to(real, target_is_directory=True)
    try:
        with test_pool.connection() as conn:
            job_id = conn.execute(
                "INSERT INTO job (source_id, drop_relative_path, corpus)"
                " VALUES (%s, %s, 'real') RETURNING id",
                ("escaping", link.name),
            ).fetchone()[0]

        assert runner.run_once(test_pool, app_config, content_root) is True

        with test_pool.connection() as conn:
            status, error = conn.execute(
                "SELECT status, error FROM job WHERE id = %s", (job_id,)
            ).fetchone()
    finally:
        link.unlink()
    assert status == "failed"
    assert "MM_DROPS_ROOT" in error


# --- the startup gate, through the real entry points ------------------------


def _unreachable_config(tmp_path: Path) -> Path:
    """A config whose Postgres cannot be reached.

    The root gates run *before* the migration gate, so a failure here surfaces
    as the root error even though the database is unusable — which is what
    lets these tests run without Postgres.
    """
    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    raw["stores"]["postgres"]["port"] = 1  # nothing ever listens here
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    (tmp_path / "docs").symlink_to(REPO_ROOT / "docs", target_is_directory=True)
    return path


def _run_without_a_drops_root(
    tmp_path: Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    """Start a real entry point with MM_CONTENT_ROOT set and no drops root."""
    envfile = tmp_path / "env"
    content = tmp_path / "content"
    envfile.write_text(f"MM_CONTENT_ROOT={content}\n", encoding="utf-8")
    env = os.environ.copy()
    env["MM_CONFIG_PATH"] = str(_unreachable_config(tmp_path))
    env["MM_ENV_PATH"] = str(envfile)
    env.pop("MM_DROPS_ROOT", None)
    env.pop("MM_CONTENT_ROOT", None)
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_the_worker_exits_1_when_the_drops_root_is_unset(tmp_path: Path) -> None:
    proc = _run_without_a_drops_root(tmp_path, ["-m", "meetingminer.worker.main"])
    assert proc.returncode == 1
    assert '"event": "worker.fatal"' in proc.stderr
    assert "MM_DROPS_ROOT is not set" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "worker.startup" not in proc.stdout


def test_the_api_exits_1_when_the_drops_root_is_unset(tmp_path: Path) -> None:
    """Named at startup, not discovered on the first ingest.

    Without the root the api can convert no posted path, re-read no target
    drop and serve no recording — three first-use failures where one startup
    failure is the honest answer.
    """
    proc = _run_without_a_drops_root(tmp_path, ["-c", "import meetingminer.api.main"])
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "MM_DROPS_ROOT is not set" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_the_root_gates_run_before_the_database_gate(tmp_path: Path) -> None:
    """Nothing is claimed before both roots are known good."""
    proc = _run_without_a_drops_root(tmp_path, ["-m", "meetingminer.worker.main"])
    assert "database unreachable" not in proc.stderr
    assert "MM_DROPS_ROOT" in proc.stderr


# --- a recording that arrives after the meeting has ingested ----------------


@requires_ffmpeg
def test_a_late_arriving_recording_is_recorded_like_a_first_pass_one(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    synthetic_recording: Path,
) -> None:
    """The augmentation case, held to the same provenance contract.

    A recovered recording re-arms the occurrence's existing job, so `probe`
    runs against the *new* drop — and the row it writes has to name that drop,
    not the transcript-only one the meeting opened with.
    """
    truncate_evidence(test_pool)
    opened = make_drop(metadata=valid_metadata("late-video"), files=("transcript.txt",))
    job_id = client.post("/ingests", json={"dropPath": str(opened)}).json()["jobId"]
    assert runner.run_once(test_pool, app_config, content_root) is True
    meeting_id = meetings(test_pool, job_id)[0]["id"]
    assert _recording_row(test_pool, meeting_id) is None

    recovered = make_drop(
        metadata=valid_metadata(
            "late-video", schemaVersion=2, augments={"sourceId": "late-video"}
        ),
        files=("transcript.txt",),
    )
    (recovered / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
    accepted = client.post("/ingests", json={"dropPath": str(recovered)})
    assert accepted.status_code == 200, accepted.text
    assert runner.run_once(test_pool, app_config, content_root) is True

    assert meetings(test_pool, job_id)[0]["id"] == meeting_id, "the meeting id survives"
    relative, digest, size = _recording_row(test_pool, meeting_id)
    assert relative == f"{recovered.name}/recording.mp4"
    assert len(digest) == 64
    assert size == (recovered / "recording.mp4").stat().st_size


# --- the guards that would otherwise be deletable without a failing test ----


@requires_ffmpeg
def test_probe_fails_when_ffprobe_and_the_file_disagree_about_size(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`size_bytes` is one number, corroborated — never two that can drift.

    A disagreement means the file changed between ffprobe and the checksum
    read, or that ffprobe read a different file. Either way nothing derived
    from it can be trusted, so the stage fails and writes no row at all rather
    than recording a checksum over bytes that were never probed.
    """
    from meetingminer.pipeline import media as pipeline_media
    from meetingminer.pipeline.stages import probe as probe_stage

    truncate_evidence(test_pool)
    drop = make_recording_drop("size-disagreement")
    job_id = enqueue(test_pool, drop, "size-disagreement")

    real_probe = pipeline_media.probe_media

    def off_by_one(path: Path):
        facts = real_probe(path)
        return replace(facts, size_bytes=(facts.size_bytes or 0) + 1)

    monkeypatch.setattr(probe_stage, "probe_media", off_by_one)

    assert runner.run_once(test_pool, app_config, content_root) is True

    with test_pool.connection() as conn:
        status, error = conn.execute(
            "SELECT status, error FROM job WHERE id = %s", (job_id,)
        ).fetchone()
        media_rows = conn.execute("SELECT count(*) FROM meeting_media").fetchone()[0]
    assert status == "failed"
    assert "size disagrees" in error
    assert media_rows == 0, "a stage that failed must leave no provenance row"


@requires_ffmpeg
def test_a_changed_recording_fails_before_overwriting_provenance(
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_recording_drop: Callable[..., Path],
) -> None:
    """Same-path substitutions leave the arrived-evidence row untouched."""
    truncate_evidence(test_pool)
    drop = make_recording_drop("changed-logged")
    job_id = enqueue(test_pool, drop, "changed-logged")
    assert runner.run_once(test_pool, app_config, content_root) is True
    meeting_id = meetings(test_pool, job_id)[0]["id"]
    before = _recording_row(test_pool, meeting_id)
    recording = drop / "recording.mp4"
    recording.write_bytes(recording.read_bytes() + b"\x00" * 64)
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'queued' WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'queued' WHERE id = %s", (job_id,))
    assert runner.run_once(test_pool, app_config, content_root) is True

    with test_pool.connection() as conn:
        status, error = conn.execute(
            "SELECT status, error FROM job WHERE id = %s", (job_id,)
        ).fetchone()
    assert status == "failed"
    assert "same drop-relative path" in error
    assert _recording_row(test_pool, meeting_id) == before


def _without_drops_root(monkeypatch: pytest.MonkeyPatch, value: Path | None) -> None:
    """Point the running api at an unusable drops root for one test."""
    import meetingminer.api.main as api_main

    config = api_main.app.state.config
    monkeypatch.setattr(
        api_main.app.state,
        "config",
        config.model_copy(
            update={"secrets": config.secrets.model_copy(update={"mm_drops_root": value})}
        ),
    )


def _seed_recorded_meeting(
    client: Any, pool: ConnectionPool, drop: Path
) -> str:
    """A meeting with a recording and its provenance row, minus the worker.

    Enough to reach the root read in `get_recording`: the bytes never matter
    to these tests, only that the route gets past `has_recording` and past the
    missing-path branch.
    """
    job_id = client.post("/ingests", json={"dropPath": str(drop)}).json()["jobId"]
    with pool.connection() as conn:
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " SELECT j.id, j.source_id, j.corpus, '2026-08-05T12:00:19Z', 'second',"
            " true FROM job j WHERE j.id = %s RETURNING id",
            (job_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO meeting_media (meeting_id, drop_relative_path, sha256)"
            " VALUES (%s, %s, %s)",
            (meeting_id, f"{drop.name}/recording.mp4", "0" * 64),
        )
    return str(meeting_id)


@pytest.mark.parametrize("value", [None, "not-a-directory"])
def test_an_unusable_drops_root_is_a_500_on_replay(
    client: Any,
    test_pool: ConnectionPool,
    make_drop: DropFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: Any,
) -> None:
    """Answered, never assumed: assuming resolves every path against `/`."""
    truncate_evidence(test_pool)
    meeting_id = _seed_recorded_meeting(
        client, test_pool, make_drop(files=("recording.mp4",))
    )
    if value == "not-a-directory":
        a_file = tmp_path / "drops"
        a_file.write_text("x", encoding="utf-8")
        value = a_file
    _without_drops_root(monkeypatch, value)

    response = client.get(f"/media/recordings/{meeting_id}")

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM
    assert _slug(response) == "drops-root-unconfigured"
    assert "MM_DROPS_ROOT" in response.json()["detail"]


@pytest.mark.parametrize("value", [None, "not-a-directory"])
def test_an_unusable_drops_root_is_a_500_at_intake(
    client: Any,
    test_pool: ConnectionPool,
    make_drop: DropFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: Any,
) -> None:
    """One misconfiguration, one problem type, whichever door reports it."""
    truncate_evidence(test_pool)
    drop = make_drop()
    if value == "not-a-directory":
        a_file = tmp_path / "drops"
        a_file.write_text("x", encoding="utf-8")
        value = a_file
    _without_drops_root(monkeypatch, value)

    response = _submit(client, drop)

    assert response.status_code == 500
    assert _slug(response) == "drops-root-unconfigured"
    assert "MM_DROPS_ROOT" in response.json()["detail"]
    assert _job_count(test_pool) == 0


def test_an_unreadable_drops_root_is_a_500_at_request_time(
    client: Any,
    make_drop: DropFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intake reuses startup's non-mutating traversal check after boot."""
    import meetingminer.config as config_module

    def denied(_path: Path) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(config_module.os, "scandir", denied)

    response = _submit(client, make_drop())

    assert response.status_code == 500
    assert _slug(response) == "drops-root-unconfigured"


@pytest.mark.parametrize("value", [None, "not-a-directory"])
def test_a_transcript_only_meeting_still_404s_on_a_broken_drops_root(
    client: Any,
    test_pool: ConnectionPool,
    make_drop: DropFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: Any,
) -> None:
    """The frozen matrix says this 404 is unchanged — including here.

    Nothing about "this meeting has no recording" depends on the drops root,
    so reading the root before that branch turned every transcript-only replay
    into a 500 on a server whose root was misconfigured.
    """
    truncate_evidence(test_pool)
    drop = make_drop(files=("transcript.txt",))
    job_id = client.post("/ingests", json={"dropPath": str(drop)}).json()["jobId"]
    with test_pool.connection() as conn:
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " SELECT j.id, j.source_id, j.corpus, '2026-08-05T12:00:19Z', 'second',"
            " false FROM job j WHERE j.id = %s RETURNING id",
            (job_id,),
        ).fetchone()[0]
    if value == "not-a-directory":
        a_file = tmp_path / "drops"
        a_file.write_text("x", encoding="utf-8")
        value = a_file
    _without_drops_root(monkeypatch, value)

    response = client.get(f"/media/recordings/{meeting_id}")

    assert response.status_code == 404
    assert _slug(response) == "media-no-recording"


def test_a_recording_with_no_provenance_row_is_a_404(
    client: Any, test_pool: ConnectionPool, make_drop: DropFactory
) -> None:
    """`has_recording` true and `probe` not settled: a 404, never a 500.

    Nothing recorded where the bytes are, so there is nothing to resolve. The
    client is never told the difference between this and an absent file.
    """
    truncate_evidence(test_pool)
    drop = make_drop(files=("recording.mp4",))
    job_id = client.post("/ingests", json={"dropPath": str(drop)}).json()["jobId"]
    with test_pool.connection() as conn:
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " SELECT j.id, j.source_id, j.corpus, '2026-08-05T12:00:19Z', 'second',"
            " true FROM job j WHERE j.id = %s RETURNING id",
            (job_id,),
        ).fetchone()[0]

    response = client.get(f"/media/recordings/{meeting_id}")

    assert response.status_code == 404
    assert _slug(response) == "media-not-found"


def test_read_drop_refuses_a_recording_that_became_a_symlink(
    make_drop: DropFactory, app_config: AppConfig, tmp_path: Path
) -> None:
    """Intake's check is not the only one: the worker looks again.

    A drop validated at intake can be tampered with before the worker claims
    it, and `present()` uses `is_file()`, which follows links.
    """
    drop = make_drop(files=("transcript.txt",))
    elsewhere = tmp_path / "elsewhere.mp4"
    elsewhere.write_bytes(b"not yours")
    (drop / "recording.mp4").symlink_to(elsewhere)
    try:
        with pytest.raises(SymlinkedEvidenceError) as exc:
            read_drop(drop, config_path=app_config.config_path)
    finally:
        (drop / "recording.mp4").unlink()
    assert "recording.mp4" in str(exc.value)


# --- the backfill's repair and reporting contracts --------------------------


def _seed_legacy_job(
    conn: Any, source_id: str, drop: Path, *, status: str = "queued", error: str | None = None
) -> Any:
    """A job row in its pre-2.1a shape: absolute path, no relative one."""
    return conn.execute(
        "INSERT INTO job (source_id, drop_path, corpus, status, error)"
        " VALUES (%s, %s, 'real', %s, %s) RETURNING id",
        (source_id, str(drop), status, error),
    ).fetchone()[0]


def test_backfill_requeues_a_job_a_too_early_worker_failed(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """The ordering hazard, repaired.

    A worker started between the migration and the backfill fails every
    un-backfilled job it claims. Converting the path without putting those
    jobs back would mean an operator who ran things in the wrong order lost
    them, with nothing in the output saying so.
    """
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("requeue-me"))
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(
            conn,
            "requeue-me",
            drop,
            status="failed",
            error=UNBACKFILLED_DROP_PATH_ERROR,
        )

        report = backfill_drop_paths(conn, drops_root)

        status, error, relative = conn.execute(
            "SELECT status, error, drop_relative_path FROM job WHERE id = %s",
            (job_id,),
        ).fetchone()

    assert report.ok
    assert report.requeued_jobs == [str(job_id)]
    assert (status, error, relative) == ("queued", None, drop.name)


def test_backfill_keeps_a_early_failed_job_unconverted_when_provenance_is_tampered(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """The missing-anchor failure is not recoverable until evidence validates."""
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("failed-tampered-transcript"))
    transcript = drop / "transcript.txt"
    digest, size = sha256_and_size(transcript)
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(
            conn,
            "failed-tampered-transcript",
            drop,
            status="failed",
            error=UNBACKFILLED_DROP_PATH_ERROR,
        )
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'failed-tampered-transcript', 'real',"
            " '2026-08-05T12:00:19Z', 'second', false) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        _insert_pre_migration_transcript(
            conn,
            meeting_id,
            "provided-text",
            "teams",
            "transcript.txt",
            digest,
            size,
        )
        transcript.write_bytes(transcript.read_bytes() + b"tampered")

        report = backfill_drop_paths(conn, drops_root)
        status, error, absolute, relative = conn.execute(
            "SELECT status, error, drop_path, drop_relative_path FROM job"
            " WHERE id = %s",
            (job_id,),
        ).fetchone()
        transcript_path = conn.execute(
            "SELECT drop_relative_path FROM transcript_source WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()[0]

    assert not report.ok
    assert report.converted_jobs == []
    assert report.requeued_jobs == []
    assert (status, error, absolute, relative) == (
        "failed",
        UNBACKFILLED_DROP_PATH_ERROR,
        str(drop),
        None,
    )
    assert transcript_path == "transcript.txt"


def test_backfill_leaves_an_unrelated_failure_failed(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """Matched on the error text, never on `failed` generally.

    A job that failed because ffprobe rejected its recording is a human's
    decision to revisit, not this command's to undo.
    """
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("leave-me"))
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(
            conn,
            "leave-me",
            drop,
            status="failed",
            error="stage probe failed: ffprobe could not read the recording",
        )

        report = backfill_drop_paths(conn, drops_root)

        status, error = conn.execute(
            "SELECT status, error FROM job WHERE id = %s", (job_id,)
        ).fetchone()

    assert report.requeued_jobs == []
    assert status == "failed"
    assert "ffprobe" in error, "the original diagnosis survives"


class _RearmAfterEnumeration:
    """Connection proxy that makes the enumeration/lock race deterministic."""

    def __init__(self, conn: Any, pool: ConnectionPool, job_id: Any, relative: str) -> None:
        self._conn = conn
        self._pool = pool
        self._job_id = job_id
        self._relative = relative
        self._fired = False

    def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
        cursor = self._conn.execute(query, params, **kwargs)
        if not self._fired and "SELECT id FROM job ORDER BY created_at" in str(query):
            self._fired = True
            with self._pool.connection() as concurrent:
                concurrent.execute(
                    "UPDATE job SET drop_relative_path = %s, drop_path = NULL"
                    " WHERE id = %s",
                    (self._relative, self._job_id),
                )
        return cursor


def test_backfill_locks_and_fetches_the_current_job_before_conversion(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """A re-arm after enumeration must survive instead of restoring old data."""
    truncate_evidence(test_pool)
    legacy = make_drop()
    current = make_drop(metadata=valid_metadata("rearmed-during-backfill"))
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(conn, "rearmed-during-backfill", legacy)

    with test_pool.connection() as conn:
        report = backfill_drop_paths(
            _RearmAfterEnumeration(conn, test_pool, job_id, current.name), drops_root
        )

    with test_pool.connection() as conn:
        relative, absolute = conn.execute(
            "SELECT drop_relative_path, drop_path FROM job WHERE id = %s", (job_id,)
        ).fetchone()
    assert report.ok
    assert report.converted_jobs == []
    assert report.already_relative == 1
    assert (relative, absolute) == (current.name, None)


def test_backfill_reports_a_recorded_meeting_with_no_media_row(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """Reported by name, never silently skipped.

    `has_recording` true with no `meeting_media` row is the meeting whose
    replay stays a permanent 404. An inner join answered "nothing to do" for
    exactly it, so the backfill could report clean and leave it broken.
    """
    truncate_evidence(test_pool)
    drop = make_drop(
        metadata=valid_metadata("no-media-row"), files=("recording.mp4",)
    )
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(conn, "no-media-row", drop)
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'no-media-row', 'real', '2026-08-05T12:00:19Z',"
            " 'second', true) RETURNING id",
            (job_id,),
        ).fetchone()[0]

        report = backfill_drop_paths(conn, drops_root)

    assert not report.ok, "a clean report here would hide a permanent 404"
    assert len(report.problems) == 1
    assert str(meeting_id) in report.problems[0]
    assert "no meeting_media row" in report.problems[0]


def test_backfill_converts_the_rows_under_an_already_anchored_job(
    test_pool: ConnectionPool,
    make_recording_drop: Callable[..., Path],
    drops_root: Path,
) -> None:
    """The realistic upgrade order: migrate, restart the api, backfill later.

    Intake anchors every new job the moment the api restarts, so a job can be
    anchored while the transcript and recording rows hanging off it still hold
    the pre-2.1a shapes. Skipping those rows because the *job* looked done is
    how they would never be converted at all.
    """
    truncate_evidence(test_pool)
    drop = make_recording_drop("already-anchored")
    (drop / "transcript.txt").write_text("[0:02] A: hi.\n", encoding="utf-8")
    recording = drop / "recording.mp4"
    transcript_digest, transcript_size = sha256_and_size(drop / "transcript.txt")
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus)"
            " VALUES ('already-anchored', %s, 'real') RETURNING id",
            (drop.name,),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'already-anchored', 'real', '2026-08-05T12:00:19Z',"
            " 'second', true) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        _insert_pre_migration_transcript(
            conn,
            meeting_id,
            "provided-text",
            "teams",
            "transcript.txt",
            transcript_digest,
            transcript_size,
        )
        conn.execute(
            "INSERT INTO meeting_media (meeting_id, size_bytes) VALUES (%s, %s)",
            (meeting_id, recording.stat().st_size),
        )

        report = backfill_drop_paths(conn, drops_root)

        transcript_path = conn.execute(
            "SELECT drop_relative_path FROM transcript_source WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()[0]
        media_path, media_sha = conn.execute(
            "SELECT drop_relative_path, sha256 FROM meeting_media WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()

    assert report.ok
    assert report.converted_jobs == [], "the job itself needed nothing"
    assert report.already_relative == 1
    assert (report.converted_transcripts, report.converted_media) == (1, 1)
    assert transcript_path == f"{drop.name}/transcript.txt"
    assert media_path == f"{drop.name}/recording.mp4"
    assert len(media_sha) == 64


def test_backfill_refuses_to_widen_a_transcript_the_current_drop_lacks(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    """A confidently wrong path recorded as success is the failure mode.

    A job re-armed onto a sibling drop may point at a drop that never carried
    this transcript form, and widening a bare filename against it would name a
    file that does not exist.
    """
    truncate_evidence(test_pool)
    drop = make_drop(
        metadata=valid_metadata("wrong-widen"), files=("transcript.txt",)
    )
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(conn, "wrong-widen", drop)
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, has_recording)"
            " VALUES (%s, 'wrong-widen', 'real', '2026-08-05T12:00:19Z',"
            " 'second', false) RETURNING id",
            (job_id,),
        ).fetchone()[0]
        # The drop carries transcript.txt and nothing else; this row claims a
        # VTT the drop it now points at never had.
        _insert_pre_migration_transcript(
            conn,
            meeting_id,
            "provided-vtt",
            "vtt",
            "transcript.vtt",
            "0" * 64,
            1,
        )

        report = backfill_drop_paths(conn, drops_root)

        stored = conn.execute(
            "SELECT drop_relative_path FROM transcript_source WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchone()[0]

    assert not report.ok
    assert report.converted_transcripts == 0
    assert "transcript.vtt" in report.problems[0]
    assert stored == "transcript.vtt", "the wrong value is not written"


def test_backfill_dry_run_writes_nothing(
    test_pool: ConnectionPool, make_drop: DropFactory, drops_root: Path
) -> None:
    truncate_evidence(test_pool)
    drop = make_drop(metadata=valid_metadata("dry"))
    with test_pool.connection() as conn:
        job_id = _seed_legacy_job(
            conn, "dry", drop, status="failed", error=UNBACKFILLED_DROP_PATH_ERROR
        )

        report = backfill_drop_paths(conn, drops_root, dry_run=True)

        status, absolute, relative = conn.execute(
            "SELECT status, drop_path, drop_relative_path FROM job WHERE id = %s",
            (job_id,),
        ).fetchone()

    assert report.converted_jobs == [(str(job_id), drop.name)]
    assert report.requeued_jobs == [str(job_id)], "it still reports what it would do"
    assert (status, absolute, relative) == ("failed", str(drop), None)


def test_backfill_main_exits_non_zero_on_an_unplaceable_row(
    test_pool: ConnectionPool,
    make_drop: DropFactory,
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The exit code is the contract a script reads.

    `report.ok` being false has to reach the process's status, or a partial
    backfill looks clean to everything that is not a human reading stderr.
    """
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        _seed_legacy_job(
            conn, "cli-ok", make_drop(metadata=valid_metadata("cli-ok"))
        )
        conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus)"
            " VALUES ('cli-elsewhere', '/somewhere/else/drop-9', 'real')"
        )

    monkeypatch.setattr(backfill, "_load_cli_config", lambda: _cli_config(app_config))

    assert backfill.main(["drop-paths"]) == 1

    captured = capsys.readouterr()
    assert "UNPLACEABLE" in captured.err
    assert "/somewhere/else/drop-9" in captured.err


def test_backfill_main_exits_zero_when_every_row_is_placeable(
    test_pool: ConnectionPool,
    make_drop: DropFactory,
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    truncate_evidence(test_pool)
    with test_pool.connection() as conn:
        _seed_legacy_job(
            conn, "cli-clean", make_drop(metadata=valid_metadata("cli-clean"))
        )

    monkeypatch.setattr(backfill, "_load_cli_config", lambda: _cli_config(app_config))

    assert backfill.main(["drop-paths"]) == 0


def test_backfill_main_passes_the_loaded_config_path_to_validation(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI backfill reads source-drop schema beside the configured config file."""
    config = _cli_config(app_config)
    observed: dict[str, Path | None] = {}

    def fake_backfill(
        _conn: Any,
        _root: Path,
        *,
        dry_run: bool,
        config_path: Path | None,
    ) -> backfill.Report:
        assert not dry_run
        observed["config_path"] = config_path
        return backfill.Report()

    monkeypatch.setattr(backfill, "_load_cli_config", lambda: config)
    monkeypatch.setattr(backfill, "require_drops_root", lambda _config: Path("/drops"))
    monkeypatch.setattr(backfill.db, "check_migrations_current", lambda _conn: None)
    monkeypatch.setattr(backfill.psycopg, "connect", lambda *_args, **_kwargs: nullcontext(object()))
    monkeypatch.setattr(backfill, "backfill_drop_paths", fake_backfill)

    assert backfill.main(["drop-paths"]) == 0
    assert observed == {"config_path": config.config_path}
