"""Replacing a stage's output directory without ever losing the previous one.

Two stages write a directory of media under this meeting's content-root
subtree — `frames` writes ``frames/``, `screens` writes ``screenshots/`` — and
both need the same durability property: a rerun that fails at any point leaves
the previous files *and* the database rows that name them intact, and a
successful rerun leaves no file from the previous run behind.

The sequence is: build into a staging directory beside the target, move the
target aside to a backup, ``os.replace`` the staging directory into place,
write the rows, and only discard the backup once the runner's transaction has
committed. A crash between the move and the commit is recovered on the next
attempt, which finds an orphaned backup and no target and puts it back.

Everything is guarded against escaping ``MM_CONTENT_ROOT``: a symlink anywhere
on the path from the root down to the target would let ``rmtree`` reach
another meeting's files, so it fails the stage instead of following it (AD-3,
AD-11).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from meetingminer.pipeline.stage import StageContext, StageError


def assert_private_meeting_subdir(content_root: Path, meeting_id: UUID, subdir: str) -> Path:
    """Return this meeting's ``subdir`` path, or raise :class:`StageError`.

    Rejects anything that could resolve outside the content root, including a
    symlink at ``meetings/``, at the meeting directory, or at ``subdir``
    itself: those are the three components a deletion would traverse.
    """
    root = content_root.resolve()
    target = content_root / "meetings" / str(meeting_id) / subdir
    if not target.is_relative_to(content_root):  # pragma: no cover - lexically impossible
        raise StageError(f"refusing to write {subdir} outside MM_CONTENT_ROOT: {target}")
    current = content_root
    for part in ("meetings", str(meeting_id), subdir):
        current = current / part
        if current.is_symlink():
            raise StageError(f"refusing symlinked {subdir} path: {current}")
    if not target.resolve().is_relative_to(root):
        raise StageError(f"refusing to write {subdir} outside MM_CONTENT_ROOT: {target}")
    if target.exists() and not target.is_dir():
        raise StageError(
            f"refusing to replace {target}: it exists but is not a directory"
        )
    return target


def remove_meeting_subdir(content_root: Path, meeting_id: UUID, subdir: str) -> None:
    """Delete one meeting's ``subdir`` subtree, refusing any unsafe path.

    Used by the runner when a failed recording job is replaced by a
    transcript-only drop: the video stages are skipped, so their output must
    not survive as misleading evidence.

    The swap's siblings go with it. A surviving ``.<subdir>-previous`` backup
    would be restored onto the empty target by the next
    :meth:`OutputDirSwap.open_staging`, resurrecting exactly the evidence this
    call was made to erase; a surviving staging directory is the same files
    under a different name.
    """
    target = assert_private_meeting_subdir(content_root, meeting_id, subdir)
    if target.exists():
        shutil.rmtree(target)
    meeting_dir = target.parent
    if not meeting_dir.is_dir() or meeting_dir.is_symlink():
        return
    prefix = f".{subdir}-"
    for entry in meeting_dir.iterdir():
        if not entry.name.startswith(prefix):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)


class OutputDirSwap:
    """One atomic replacement of ``meetings/<id>/<subdir>/``.

    Usage inside a stage::

        swap = OutputDirSwap(ctx, "screenshots")
        staging = swap.open_staging()
        ...write files into staging...            # swap.discard() on failure
        swap.publish()                            # staging becomes the target
        ...write the rows naming them...          # swap.restore() on failure
        swap.arm_hooks()                          # commit/rollback wiring
    """

    def __init__(self, ctx: StageContext, subdir: str) -> None:
        self._ctx = ctx
        self.subdir = subdir
        self.target = assert_private_meeting_subdir(ctx.content_root, ctx.meeting_id, subdir)
        self.meeting_dir = self.target.parent
        self.backup = self.meeting_dir / f".{subdir}-previous"
        self.staging: Path | None = None
        # True once publish() has swapped a directory in with nothing behind
        # it: on a first-ever run there is no backup to restore, so undoing
        # the publish means deleting what it put there.
        self._published_without_backup = False

    @property
    def _staging_prefix(self) -> str:
        return f".{self.subdir}-"

    def _sweep_leftover_staging(self) -> None:
        """Delete staging directories abandoned by a killed process.

        ``mkdtemp`` leaves a ``.<subdir>-XXXXXX`` directory behind if the
        process dies before publish or discard, and nothing else ever removes
        it. The backup is deliberately *not* swept — it is the previous output
        and the recovery path below depends on it.
        """
        if not self.meeting_dir.is_dir():
            return
        for entry in self.meeting_dir.iterdir():
            if entry == self.backup or not entry.name.startswith(self._staging_prefix):
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)

    def open_staging(self) -> Path:
        """Recover any orphaned backup, then hand back an empty staging directory."""
        try:
            # A process can die after moving the old directory aside but
            # before the database checkpoint commits. Restore it before doing
            # anything else.
            if self.backup.exists() and not self.target.exists():
                os.replace(self.backup, self.target)
            self._sweep_leftover_staging()
            self.meeting_dir.mkdir(parents=True, exist_ok=True)
            # Re-check after mkdir: the guard's answer is only as fresh as the
            # filesystem it was asked about.
            assert_private_meeting_subdir(
                self._ctx.content_root, self._ctx.meeting_id, self.subdir
            )
            staging = Path(tempfile.mkdtemp(prefix=self._staging_prefix, dir=self.meeting_dir))
        except OSError as exc:
            raise StageError(
                f"{self.subdir} directory {self.target} is unusable: {exc}"
            ) from exc
        self.staging = staging
        return staging

    def discard(self) -> None:
        """Throw the staging directory away; the previous output is untouched."""
        if self.staging is not None:
            shutil.rmtree(self.staging, ignore_errors=True)
            self.staging = None

    def restore(self) -> None:
        """Undo a :meth:`publish` whose database write did not survive.

        With a backup this puts the previous output back. Without one — a
        first-ever run — the published directory is what has to go: leaving it
        would strand a fully populated ``<subdir>/`` on disk that no surviving
        row names, which is exactly the orphan the swap exists to prevent.
        """
        if self.backup.exists():
            shutil.rmtree(self.target, ignore_errors=True)
            os.replace(self.backup, self.target)
            self._published_without_backup = False
            return
        if self._published_without_backup:
            shutil.rmtree(self.target, ignore_errors=True)
            self._published_without_backup = False

    def publish(self) -> None:
        """Swap the staging directory in, keeping the previous one as a backup.

        Durable output is never deleted before the new output exists, so a
        failed rerun leaves the previous files and rows intact. ``os.replace``
        gives the new directory one atomic name transition on the same
        filesystem.
        """
        staging = self.staging
        if staging is None:  # pragma: no cover - programming error
            raise StageError(f"{self.subdir} staging directory was never opened")
        try:
            if self.backup.exists():
                shutil.rmtree(self.backup)
            if self.target.exists():
                os.replace(self.target, self.backup)
            os.replace(staging, self.target)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if self.backup.exists() and not self.target.exists():
                os.replace(self.backup, self.target)
            raise StageError(
                f"could not replace {self.subdir} directory {self.target}: {exc}"
            ) from exc
        self._published_without_backup = not self.backup.exists()
        self.staging = None

    def arm_hooks(self) -> None:
        """Keep the backup until the runner's transaction settles.

        On commit the backup is discarded; on rollback it is put back, because
        only a durable database update may retire the files its rows named.
        """
        self._ctx.after_rollback.append(self.restore)
        self._ctx.after_commit.append(self._drop_backup)

    def _drop_backup(self) -> None:
        self._published_without_backup = False
        shutil.rmtree(self.backup, ignore_errors=True)
