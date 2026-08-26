"""The filesystem half of a purge, run only after the transaction commits.

Two roots are touched and a third deliberately is not. ``MM_CONTENT_ROOT``
holds the material the pipeline *produced* for a meeting — frames,
screenshots, extracted audio, all under ``meetings/<meeting_id>/`` — and it is
reconstructible from the source drop, so it goes with the rows. The publish
root holds documents a human approved; those are removed as a normal git
commit, which keeps them recoverable from history. ``MM_DROPS_ROOT`` holds
what *arrived* and is nothing's output; a purge never touches it unless the
operator asks, because losing a drop is the one loss no rerun can undo.

Nothing here is transactional. Every function reports what it removed and
what was already gone, and treats already-gone as success — a purge re-run
after an interrupted one must converge rather than fail.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from meetingminer.prune import PurgePlan, PurgeReport
from meetingminer.publish.export import GitExportError, remove_published


def remove_content_dirs(plan: PurgePlan, report: PurgeReport) -> None:
    """Delete each purged meeting's produced-content directory."""
    for directory in plan.content_dirs:
        if directory.is_dir():
            shutil.rmtree(directory)
            report.removed_dirs.append(directory)
        else:
            report.absent_dirs.append(directory)


def remove_published_files(
    publish_root: Path | None, plan: PurgePlan, report: PurgeReport
) -> None:
    """Delete the purged meetings' published markdown and commit the removal.

    A missing publish root is not an error: an install that never published
    an artifact has none, and the purge has nothing to do here.
    """
    paths = [published.relative_path for published in plan.published_files]
    if not paths:
        return
    if publish_root is None or not publish_root.is_dir():
        report.absent_files.extend(paths)
        return

    present = [path for path in paths if (publish_root / path).exists()]
    report.absent_files.extend(path for path in paths if path not in set(present))
    if not present:
        return

    message = (
        f"Remove {len(present)} published artifact(s) for"
        f" {len(plan.purge_ids)} purged meeting(s)"
    )
    try:
        report.commit_sha = remove_published(publish_root, present, message=message)
    except GitExportError as exc:
        # The rows are already gone by the time this runs, so a git failure
        # must not read as "the purge failed" — it is a named, resumable
        # leftover. Re-running the removal converges.
        raise PublishRemovalError(str(exc)) from exc
    report.removed_files.extend(present)


class PublishRemovalError(RuntimeError):
    """The published files could not be removed after the rows were deleted."""


def remove_drops(drops_root: Path | None, drop_paths: list[Path], report: PurgeReport) -> None:
    """Delete opted-in source drops. Never reached without an explicit flag."""
    if drops_root is None:
        return
    for relative in drop_paths:
        directory = drops_root / relative
        if directory.is_dir():
            shutil.rmtree(directory)
            report.removed_dirs.append(directory)
        else:
            report.absent_dirs.append(directory)
