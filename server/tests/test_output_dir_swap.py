"""The output-directory swap both media stages share.

Pure filesystem behavior, so these need neither Postgres nor ffmpeg: the
context is built by hand and only its content root, meeting id, and hook lists
are ever touched. What is under test is the guarantee the `frames` and
`screens` stages both rest on — a rerun that fails at any point leaves no
directory that the surviving database rows do not name.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from meetingminer import logs
from meetingminer.pipeline.outputs import (
    OutputDirSwap,
    assert_private_meeting_subdir,
    remove_meeting_subdir,
)
from meetingminer.pipeline.stage import StageContext, StageError

SUBDIR = "screenshots"


@pytest.fixture()
def meeting_id() -> UUID:
    return uuid4()


@pytest.fixture()
def ctx(content_root: Path, meeting_id: UUID) -> StageContext:
    # conn/config/drop are never read by OutputDirSwap; the stage contract is
    # what supplies them in production.
    return StageContext(
        conn=None,  # type: ignore[arg-type]
        config=None,  # type: ignore[arg-type]
        job_id=uuid4(),
        meeting_id=meeting_id,
        drop=None,  # type: ignore[arg-type]
        content_root=content_root,
        drops_root=content_root,  # never read here; the swap writes only content
        log=logs.bind(job_id="test", stage=SUBDIR),
    )


def write(directory: Path, name: str, content: bytes = b"x") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content)
    return path


def names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


# --- the happy path --------------------------------------------------------


def test_publish_then_commit_replaces_the_directory(ctx: StageContext) -> None:
    swap = OutputDirSwap(ctx, SUBDIR)
    write(swap.target, "old.jpg", b"previous")

    staging = swap.open_staging()
    write(staging, "new.jpg", b"current")
    swap.publish()
    swap.arm_hooks()
    for action in ctx.after_commit:
        action()

    assert names(swap.target) == ["new.jpg"]
    assert (swap.target / "new.jpg").read_bytes() == b"current"
    assert not swap.backup.exists(), "the backup is retired once the rows are durable"


def test_rollback_after_publish_restores_the_previous_directory(ctx: StageContext) -> None:
    swap = OutputDirSwap(ctx, SUBDIR)
    write(swap.target, "old.jpg", b"previous")

    staging = swap.open_staging()
    write(staging, "new.jpg", b"current")
    swap.publish()
    swap.arm_hooks()
    for action in ctx.after_rollback:
        action()

    assert names(swap.target) == ["old.jpg"]
    assert (swap.target / "old.jpg").read_bytes() == b"previous"


# --- the first-ever run has nothing to fall back to ------------------------


def test_rollback_of_a_first_ever_publish_removes_the_orphan(ctx: StageContext) -> None:
    """No backup exists, so restoring means deleting what publish put there.

    Otherwise a failure after publish leaves a fully populated directory on
    disk that no surviving row names.
    """
    swap = OutputDirSwap(ctx, SUBDIR)
    assert not swap.target.exists()

    staging = swap.open_staging()
    write(staging, "new.jpg")
    swap.publish()
    assert swap.target.is_dir()

    swap.restore()

    assert not swap.target.exists()


def test_a_committed_first_run_is_not_removed_by_a_later_restore(ctx: StageContext) -> None:
    """Once the rows are durable the directory stays, whatever runs afterwards."""
    swap = OutputDirSwap(ctx, SUBDIR)
    staging = swap.open_staging()
    write(staging, "new.jpg")
    swap.publish()
    swap.arm_hooks()
    for action in ctx.after_commit:
        action()

    swap.restore()

    assert names(swap.target) == ["new.jpg"]


def test_discard_before_publish_leaves_the_previous_output(ctx: StageContext) -> None:
    swap = OutputDirSwap(ctx, SUBDIR)
    write(swap.target, "old.jpg", b"previous")
    staging = swap.open_staging()
    write(staging, "new.jpg")

    swap.discard()

    assert names(swap.target) == ["old.jpg"]
    assert not staging.exists()


# --- crash recovery --------------------------------------------------------


def test_an_orphaned_backup_is_restored_on_the_next_run(ctx: StageContext) -> None:
    """State left by a process killed between the move and the commit."""
    swap = OutputDirSwap(ctx, SUBDIR)
    write(swap.backup, "old.jpg", b"previous")
    assert not swap.target.exists()

    swap.open_staging()

    assert names(swap.target) == ["old.jpg"]


def test_a_leaking_staging_directory_is_swept_on_the_next_run(ctx: StageContext) -> None:
    """mkdtemp leaves a directory behind on SIGKILL and nothing else sweeps it."""
    swap = OutputDirSwap(ctx, SUBDIR)
    write(swap.target, "old.jpg", b"previous")
    leaked = write(swap.meeting_dir / f".{SUBDIR}-abc123", "half-written.jpg").parent
    survivor = write(swap.meeting_dir / "frames", "frame-000001.jpg").parent

    staging = swap.open_staging()

    assert not leaked.exists()
    assert survivor.is_dir(), "another stage's output is not a staging directory"
    assert staging.is_dir() and staging != leaked


def test_the_sweep_never_touches_the_backup(ctx: StageContext) -> None:
    """The backup shares the staging prefix; deleting it would lose the rerun."""
    swap = OutputDirSwap(ctx, SUBDIR)
    write(swap.backup, "old.jpg", b"previous")
    write(swap.target, "current.jpg")

    swap.open_staging()

    assert swap.backup.is_dir()
    assert names(swap.backup) == ["old.jpg"]


def test_a_failing_orphan_recovery_is_a_named_stage_error(
    ctx: StageContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OSError here must not escape as an 'unexpected OSError'."""
    swap = OutputDirSwap(ctx, SUBDIR)
    write(swap.backup, "old.jpg")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(StageError, match="is unusable"):
        swap.open_staging()


# --- the escape guards -----------------------------------------------------


@pytest.mark.parametrize("component", ("meetings", "meeting", "subdir"))
def test_a_symlinked_output_path_component_is_refused(
    content_root: Path, meeting_id: UUID, component: str
) -> None:
    meeting_dir = content_root / "meetings" / str(meeting_id)
    elsewhere = content_root / "elsewhere" / str(meeting_id)
    elsewhere.mkdir(parents=True)
    if component == "meetings":
        (content_root / "meetings").symlink_to(content_root / "elsewhere", target_is_directory=True)
    elif component == "meeting":
        meeting_dir.parent.mkdir(parents=True)
        meeting_dir.symlink_to(elsewhere, target_is_directory=True)
    else:
        meeting_dir.mkdir(parents=True)
        (meeting_dir / SUBDIR).symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(StageError, match=f"refusing symlinked {SUBDIR} path"):
        assert_private_meeting_subdir(content_root, meeting_id, SUBDIR)


def test_a_target_that_is_not_a_directory_is_refused(
    content_root: Path, meeting_id: UUID
) -> None:
    meeting_dir = content_root / "meetings" / str(meeting_id)
    meeting_dir.mkdir(parents=True)
    (meeting_dir / SUBDIR).write_bytes(b"not a directory")

    with pytest.raises(StageError, match="exists but is not a directory"):
        assert_private_meeting_subdir(content_root, meeting_id, SUBDIR)


# --- cleanup ---------------------------------------------------------------


def test_remove_takes_the_backup_and_staging_siblings_with_it(
    ctx: StageContext, content_root: Path, meeting_id: UUID
) -> None:
    """A surviving backup would be restored onto the emptied target later."""
    swap = OutputDirSwap(ctx, SUBDIR)
    write(swap.target, "current.jpg")
    write(swap.backup, "old.jpg")
    leaked = write(swap.meeting_dir / f".{SUBDIR}-tmp999", "half.jpg").parent
    other = write(swap.meeting_dir / "frames", "frame-000001.jpg").parent

    remove_meeting_subdir(content_root, meeting_id, SUBDIR)

    assert not swap.target.exists()
    assert not swap.backup.exists()
    assert not leaked.exists()
    assert other.is_dir(), "only the named subdir's own tree is removed"

    # A swap opened afterwards must find nothing to recover.
    assert names(OutputDirSwap(ctx, SUBDIR).open_staging()) == []
    assert not swap.target.exists()


def test_remove_of_an_absent_subdir_is_a_no_op(
    content_root: Path, meeting_id: UUID
) -> None:
    remove_meeting_subdir(content_root, meeting_id, SUBDIR)
