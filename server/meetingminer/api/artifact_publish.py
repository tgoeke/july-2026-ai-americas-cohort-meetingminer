"""The one publish gesture, shared by every scope an artifact can have (AD-6).

Story 4.3 built approval as a per-moment gesture and put the export → git →
``UPDATE`` sequence inline in ``approve_moment_artifacts``. Story 12.2 added a
second scope — an artifact anchored to the *meeting* rather than to a moment —
and AD-6 is explicit that a meeting-level artifact is **not an exception to
human-approved publishing**. Two routes that each did their own export and
their own state write would be two gestures that merely resembled each other,
and the one that drifted would be the one nobody was looking at.

So the sequence lives here once and both routes call it. What that pins:

* Export to ``MM_PUBLISH_ROOT`` and, for ``adr`` rows, the git commit happen
  **before** the Postgres ``UPDATE``, so a filesystem or git failure leaves
  every affected row ``extracted`` rather than half-published (AD-4/AD-5).
* ``state``, ``approved_at``, ``published_at`` and the two publish columns are
  written together in one statement. There is no resting ``approved`` state a
  human ever sees; one gesture crosses both transitions.
* A failure is a :class:`Problem` naming the artifact, never a partial success.

This module writes only the lifecycle and publish columns the api owns; the
extraction-content columns stay worker-owned (AD-5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence
from uuid import UUID

from psycopg import Connection

from meetingminer.api.problems import Problem
from meetingminer.projections.publish_gate import PUBLISHED_STATE
from meetingminer.publish import export

# The api's half of the disjoint column split (AD-5), written as one statement
# so no row can be left with a state and no export path, or the reverse.
_PUBLISH_ARTIFACT = (
    "UPDATE artifact SET state = %s, approved_at = now(), published_at = now(),"
    " publish_relative_path = %s, publish_commit_sha = %s WHERE id = %s"
)

# Which kind is git-committed as well as exported. `publish_commit_sha` is NULL
# for every other kind — an action item and a meeting summary are exported for
# a human to read, while an ADR is a decision record whose home is a git
# history. Story 4.3's rule, unchanged here; this module only stopped it from
# being written twice.
_GIT_COMMITTED_KIND = "adr"


def publish_extracted(
    conn: Connection,
    publish_root: Path,
    pending: Sequence[tuple[UUID, str, str, str]],
) -> None:
    """Export, commit where the kind calls for it, then advance every row.

    ``pending`` is ``(artifact_id, kind, title, body)`` per row, already locked
    ``FOR UPDATE`` by the caller — this function does not choose which rows
    publish, only what publishing one *is*. The caller's transaction is still
    open on return, so nothing here is durable until it commits and no store is
    touched from inside it.
    """
    for artifact_id, kind, title, body in pending:
        try:
            relative_path = export.export_artifact(
                publish_root, artifact_id, kind, title, body
            )
        except OSError as exc:
            raise Problem(
                500,
                "publish-export-failed",
                f"artifact {artifact_id} could not be exported: {exc}",
                artifactId=str(artifact_id),
            ) from exc
        commit_sha: str | None = None
        if kind == _GIT_COMMITTED_KIND:
            try:
                commit_sha = export.publish_adr(
                    publish_root, relative_path, title, artifact_id
                )
            except export.GitExportError as exc:
                raise Problem(
                    500,
                    "publish-git-failed",
                    f"artifact {artifact_id} could not be committed to"
                    f" the publish git repo: {exc.stderr.strip()}",
                    artifactId=str(artifact_id),
                ) from exc
        conn.execute(
            _PUBLISH_ARTIFACT,
            (PUBLISHED_STATE, str(relative_path), commit_sha, artifact_id),
        )
