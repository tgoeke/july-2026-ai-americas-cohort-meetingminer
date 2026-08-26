"""What a pipeline stage is handed, and how it reports failure.

Kept out of ``stages/__init__.py`` so the individual stage modules can import
it without importing the registry that imports them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from pathlib import Path
from uuid import UUID

from psycopg import Connection

from meetingminer.config import AppConfig
from meetingminer.domain.drops import DropContents
from meetingminer.logs import BoundLogger


class StageError(RuntimeError):
    """A stage could not complete.

    Raised with a message that names the actual cause (the tool's error, the
    missing input). The runner records it verbatim on ``job_stage.error`` and
    references the stage in ``job.error`` — never swallowed.
    """


@dataclass(frozen=True)
class StageContext:
    """Everything a stage may touch.

    The connection is the runner's: a stage runs inside the runner's open
    transaction and never commits — the runner checkpoints, so a stage that
    raises leaves no half-written rows behind.
    """

    conn: Connection
    config: AppConfig
    job_id: UUID
    meeting_id: UUID
    drop: DropContents
    # The two path anchors (`storage-layout.md` §4). `content_root` is where
    # this pipeline *writes*; `drops_root` is what a path to *arrived*
    # material is stored relative to. A stage records a path against one of
    # them and never an absolute one.
    content_root: Path
    drops_root: Path
    log: BoundLogger
    after_commit: list[Callable[[], None]] = field(default_factory=list)
    after_rollback: list[Callable[[], None]] = field(default_factory=list)

    def meeting_dir(self) -> Path:
        """This meeting's own subtree under the content root (AD-3).

        Every stage that writes media writes *only* below here, which is what
        makes "a rerun overwrites only rows keyed to that job's meeting" true
        on disk as well as in the database.
        """
        return self.content_root / "meetings" / str(self.meeting_id)

    def relative_path(self, path: Path) -> str:
        """A content-root-relative POSIX path for storage (AD-3).

        Raises :class:`StageError` rather than storing an absolute path if the
        argument somehow escaped the root.
        """
        try:
            return path.resolve().relative_to(self.content_root.resolve()).as_posix()
        except ValueError as exc:
            raise StageError(
                f"refusing to store a path outside MM_CONTENT_ROOT: {path}"
            ) from exc

    def drop_relative_path(self, path: Path) -> str:
        """A drops-root-relative POSIX path for storage (`storage-layout.md` §4).

        The twin of :meth:`relative_path` for material that *arrived*: the
        recording, and each provided transcript. Relative to the **root**, not
        to the drop's own folder — ``<drop-dir>/<filename>`` — so the stored
        path stays resolvable after an augmenting re-emit repoints the job at
        a sibling drop.
        """
        try:
            return path.resolve().relative_to(self.drops_root.resolve()).as_posix()
        except ValueError as exc:
            raise StageError(
                f"refusing to store a path outside MM_DROPS_ROOT: {path}"
            ) from exc
