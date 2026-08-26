"""The claim-and-advance loop the worker runs (AD-11).

One pass = claim one `queued` job, mint its Meeting row, then walk
``STAGE_NAMES`` in order:

* a stage already `done`/`skipped` is not re-executed — resume, not restart;
* a video-only stage on a transcript-only drop is recorded `skipped` (AD-1);
* a registered stage runs, and its outcome is checkpointed in Postgres before
  the next stage starts;
* an *unregistered* stage pauses the job: the stage stays `queued`, the job
  stays `running`, and a paused event is logged. Unbuilt work is never marked
  `done` or `skipped`.

Failure is recorded on both rows — ``job_stage.status='failed'`` with the
stage's error, ``job.status='failed'`` with an error naming the stage — and
never swallowed. ``updated_at`` on both is maintained by a database trigger
(migration 0002), so no UPDATE here has to remember it.

AD-9 pins exactly one worker on one Mac, so ``FOR UPDATE SKIP LOCKED`` is
belt-and-braces rather than the basis of correctness; no lease or heartbeat
machinery exists or is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from meetingminer import logs, projections
from meetingminer.config import AppConfig, ConfigError, require_drops_root
from meetingminer.domain.drops import (
    DropContents,
    DropError,
    DropPathError,
    read_drop,
    resolve_drop_path,
)
from meetingminer.domain.jobs import (
    STAGE_NAMES,
    UNBACKFILLED_DROP_PATH_ERROR,
    VIDEO_ONLY_STAGES,
    evidence_complete,
)
from meetingminer.pipeline.outputs import remove_meeting_subdir
from meetingminer.pipeline.stage import StageContext, StageError
from meetingminer.pipeline.stages import stage_implementation

# Stage checkpoints that mean "already accounted for, do not re-execute".
_SETTLED_STAGE_STATUSES = frozenset({"done", "skipped"})


@dataclass(frozen=True)
class ClaimedJob:
    """One claimed row. ``drop_relative_path`` is anchored to MM_DROPS_ROOT.

    The claim hands back the *stored* path and the runner resolves it once,
    against the configured root, before reading the drop — so relocating the
    drops volume is an environment change and every stage below is unaffected.
    ``None`` is a row the 2.1a backfill has not converted yet.
    """

    id: UUID
    source_id: str
    drop_relative_path: str | None
    corpus: str


def requeue_orphaned_jobs(conn: Connection) -> list[UUID]:
    """Return jobs left `running` by a crash to `queued`; report which.

    Stage checkpoints are deliberately *not* reset: a job whose `probe` is
    already `done` re-runs only what is unfinished, so a restart never re-runs
    ffmpeg over an already-sampled recording. Safe without leases because
    AD-9 fixes exactly one worker (the Makefile enforces it with a pidfile).
    """
    rows = conn.execute(
        "UPDATE job SET status = 'queued', error = NULL"
        " WHERE status = 'running' RETURNING id"
    ).fetchall()
    conn.commit()
    return [row[0] for row in rows]


def claim_job(conn: Connection) -> ClaimedJob | None:
    """Claim the oldest `queued` job, or return ``None`` when the queue is empty."""
    row = conn.execute(
        "UPDATE job SET status = 'running', error = NULL"
        " WHERE id = ("
        "   SELECT id FROM job WHERE status = 'queued'"
        "   ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
        " )"
        " RETURNING id, source_id, drop_relative_path, corpus"
    ).fetchone()
    conn.commit()
    if row is None:
        return None
    return ClaimedJob(
        id=row[0], source_id=row[1], drop_relative_path=row[2], corpus=row[3]
    )


def mint_meeting(conn: Connection, job: ClaimedJob, drop: DropContents) -> UUID:
    """Mint (or refresh) the one Meeting row for this job (AD-5, AD-14).

    Minted at claim time rather than inside `probe`, because `probe` is
    skipped for transcript-only drops (AD-1) and those jobs must still have a
    meeting. ``ON CONFLICT (job_id)`` makes a re-claim update the existing row
    instead of creating a second one, so "exactly one Meeting row linked to
    the job" holds after every claim.

    ``source_id`` and ``corpus`` come from the job row (what intake accepted);
    the wall clock and provenance come from the drop's metadata.json, never
    re-derived from media metadata.
    """
    row = conn.execute(
        "INSERT INTO meeting ("
        "  job_id, source_id, corpus, started_at, started_at_precision,"
        "  title, has_recording, provenance"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (job_id) DO UPDATE SET"
        "   source_id = EXCLUDED.source_id,"
        "   corpus = EXCLUDED.corpus,"
        "   started_at = EXCLUDED.started_at,"
        "   started_at_precision = EXCLUDED.started_at_precision,"
        "   title = EXCLUDED.title,"
        "   has_recording = EXCLUDED.has_recording,"
        "   provenance = EXCLUDED.provenance"
        " RETURNING id",
        (
            job.id,
            job.source_id,
            job.corpus,
            drop.started_at,
            drop.started_at_precision,
            drop.title,
            drop.has_recording,
            Jsonb(drop.provenance),
        ),
    ).fetchone()
    conn.commit()
    return row[0]


def _stage_statuses(conn: Connection, job_id: UUID) -> dict[str, str]:
    rows = conn.execute(
        "SELECT name, status FROM job_stage WHERE job_id = %s", (job_id,)
    ).fetchall()
    return {name: status for name, status in rows}


# Media subtrees the video stages write under `meetings/<meeting_id>/`.
_VIDEO_OUTPUT_SUBDIRS = ("screenshots", "frames", "audio")


def _clear_replaced_video_evidence(
    conn: Connection, job_id: UUID, meeting_id: UUID, content_root: Path
) -> None:
    """Remove evidence from a failed recording retry now made transcript-only.

    A failed job is intentionally re-used for the same source id. If its new
    drop has no recording, old frame/OCR/screenshot/media evidence would
    otherwise survive despite every video stage being skipped. The deletion is
    tightly scoped to this meeting's rows and its own media subtrees.

    Screenshots go first: they reference the frames, and their files are the
    ones a viewer would otherwise still be served. The `meeting_crop` row goes
    with them — it describes the share region those screenshots were decided
    against, so it is meaningless once they are gone. `frame_ocr` needs no
    statement of its own — it cascades from `frame`. Cross-meeting `screen`
    rows are never deleted here (AD-5); a screen that now has no screenshot in
    this meeting still belongs to whatever other meetings showed it. The
    directory removal takes each subtree's swap backup and staging siblings
    with it, so nothing can be restored onto the emptied target later.

    The STT verification lane goes the same way: `transcribe` is now a skipped
    stage, so its `transcript_source` row and the extracted audio it names must
    not survive as evidence of a recording this meeting no longer has. Deleting
    that row cascades to the derived `transcript_segment` rows anchored to it,
    so `align` is put back to `queued` — otherwise a checkpoint reading `done`
    would sit over a meeting whose transcript rows had just been removed.
    `moments` is put back for the same reason and by either deletion: it names
    the screenshots and the transcript segments that just went away.
    """
    cleared_screenshots = conn.execute(
        "DELETE FROM screenshot WHERE meeting_id = %s RETURNING id", (meeting_id,)
    ).fetchall()
    conn.execute("DELETE FROM meeting_crop WHERE meeting_id = %s", (meeting_id,))
    conn.execute("DELETE FROM frame WHERE meeting_id = %s", (meeting_id,))
    conn.execute("DELETE FROM meeting_media WHERE meeting_id = %s", (meeting_id,))
    cleared = conn.execute(
        "DELETE FROM transcript_source WHERE meeting_id = %s AND kind = 'stt'"
        " RETURNING id",
        (meeting_id,),
    ).fetchall()
    if cleared:
        conn.execute(
            "UPDATE job_stage SET status = 'queued', error = NULL"
            " WHERE job_id = %s AND name = 'align'",
            (job_id,),
        )
    if cleared or cleared_screenshots:
        # `moments` names both of those: the screenshot each moment evidences
        # and the transcript segments it covers. Either deletion leaves a
        # `done` checkpoint sitting over moments that describe evidence this
        # meeting no longer has, so the stage is put back to `queued` and
        # re-derives the transcript-only layout — which, per the SPEC, keeps
        # every transcript-anchored moment's id and drops only the
        # screen-anchored ones.
        conn.execute(
            "UPDATE job_stage SET status = 'queued', error = NULL"
            " WHERE job_id = %s AND name = 'moments'",
            (job_id,),
        )
    # A retry can replace the recording drop after its video-only checkpoints
    # were already marked done. Those outputs were just deleted, so preserve
    # the transcript-only contract in the checkpoints as well as on disk.
    conn.execute(
        "UPDATE job_stage SET status = 'skipped', error = NULL"
        " WHERE job_id = %s AND name = ANY(%s)",
        (job_id, list(VIDEO_ONLY_STAGES)),
    )
    for subdir in _VIDEO_OUTPUT_SUBDIRS:
        remove_meeting_subdir(content_root, meeting_id, subdir)


def _persisted_has_recording(conn: Connection, job_id: UUID) -> bool | None:
    """This job's meeting's recorded ``has_recording``, or ``None`` when unminted."""
    row = conn.execute(
        "SELECT has_recording FROM meeting WHERE job_id = %s", (job_id,)
    ).fetchone()
    return None if row is None else bool(row[0])


def _invalidate_augmented_projection(
    conn: Connection, meeting_id: UUID, log: logs.BoundLogger
) -> None:
    """Make the augmented meeting re-project (stories 1.12 and 1.13, AD-4).

    An augmenting drop is one the api accepted against a meeting that already
    exists: stages are about to re-run against this same meeting id, so
    whatever is in Neo4j and Meilisearch now describes evidence that is being
    superseded. `projection_action` answers `ACTION_NONE` while a current
    `meeting_projection` row exists, so without dropping that row the terminal
    projection call would decline and the new evidence would never reach either
    store.

    Every augmentation invalidates, not only one that first supplies a
    recording: a drop that brings the participant graph re-runs `align` and
    `moments`, which is exactly what rewrites the meeting's participants and the
    speaker attribution on every moment document — the fields the graph exists
    to correct — and none of that would reach either store otherwise.

    Not a store write and not `unproject_meeting`: only the state row goes, so
    the meeting stays searchable from its transcript for the length of the
    re-run and `project_meeting`'s per-meeting delete-and-reinsert replaces its
    documents in one pass at the end.

    Failure is logged and the run continues, for the same reason
    `_maybe_project` swallows: the evidence is what the job exists to produce,
    and a projection that did not happen is what `rebuild` is for.
    """
    log("job.augmenting", meeting_id=meeting_id)
    try:
        projections.invalidate_meeting_projection(conn, meeting_id, log=log)
    except Exception as exc:  # noqa: BLE001 - never fail an ingest over projections
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - a broken connection must not escape
            pass
        log.error(
            "projection.invalidate_failed",
            meeting_id=meeting_id,
            error=f"{type(exc).__name__}: {exc}",
            recovery=f"run 'rebuild --meeting {meeting_id}' once the ingest finishes",
        )


def _run_hooks(
    hooks: list[Callable[[], None]], log: logs.BoundLogger, phase: str
) -> None:
    """Run a stage's commit/rollback hooks, surviving a hook that raises.

    These hooks only tidy files (retire a backup, put one back). One that
    fails must not abort the rest, and — for the commit phase — must not
    escape into the failure path, because the rows it belongs to are already
    durable. Every failure is logged as its own event rather than swallowed.
    """
    for action in hooks:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask the outcome
            log.error(
                "stage.hook_failed",
                phase=phase,
                error=f"{type(exc).__name__}: {exc}",
            )


def _set_stage(
    conn: Connection, job_id: UUID, name: str, status: str, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE job_stage SET status = %s, error = %s WHERE job_id = %s AND name = %s",
        (status, error, job_id, name),
    )
    conn.commit()


def _fail_job(
    conn: Connection, job_id: UUID, error: str, stage: str | None = None
) -> None:
    """Record a failure on the job row (and its stage, when one is implicated)."""
    conn.rollback()  # discard whatever the failed stage had written
    if stage is not None:
        conn.execute(
            "UPDATE job_stage SET status = 'failed', error = %s"
            " WHERE job_id = %s AND name = %s",
            (error, job_id, stage),
        )
    message = f"stage {stage} failed: {error}" if stage else error
    conn.execute("UPDATE job SET status = 'failed', error = %s WHERE id = %s", (message, job_id))
    conn.commit()


def _drops_root_or_fail(
    conn: Connection, job: ClaimedJob, log: logs.BoundLogger, config: AppConfig
) -> Path | None:
    """The configured drops root, or fail the job naming the misconfiguration.

    The worker gates on ``require_drops_root`` at startup, so reaching this
    with an unusable root means the environment changed under a running
    process. That is a job failure with a named error, never a claim advanced
    against an unanchored path.
    """
    try:
        return require_drops_root(config)
    except ConfigError as exc:
        error = f"drops root unusable: {exc}"
        _fail_job(conn, job.id, error)
        log.error("job.failed", error=error)
        return None


def _resolve_drop_or_fail(
    conn: Connection, job: ClaimedJob, log: logs.BoundLogger, drops_root: Path
) -> Path | None:
    """Turn the claimed job's stored relative path into a directory.

    The one place a stored drop path becomes a filesystem path in the worker.
    A row the 2.1a backfill has not converted has no relative path at all, and
    says so by name rather than failing later as a missing directory.
    """
    if job.drop_relative_path is None:
        # Recorded verbatim from the shared constant, because the backfill
        # matches on this exact string to re-queue the jobs it repairs. A
        # worker started before the backfill therefore costs an operator a
        # re-run of the backfill, not the jobs themselves.
        _fail_job(conn, job.id, UNBACKFILLED_DROP_PATH_ERROR)
        log.error("job.failed", error=UNBACKFILLED_DROP_PATH_ERROR)
        return None
    try:
        return resolve_drop_path(drops_root, job.drop_relative_path)
    except (DropPathError, OSError, ValueError) as exc:
        error = f"drop path is not usable under MM_DROPS_ROOT: {exc}"
        _fail_job(conn, job.id, error)
        log.error("job.failed", error=error)
        return None


def _read_drop_or_fail(
    conn: Connection,
    job: ClaimedJob,
    log: logs.BoundLogger,
    config: AppConfig,
    drop_dir: Path,
) -> DropContents | None:
    try:
        return read_drop(drop_dir, config_path=config.config_path)
    except DropError as exc:
        # Not a stage failure: the drop was validated at intake, so it changed
        # or vanished afterwards. Still recorded, never swallowed.
        error = f"source drop unreadable: {exc}"
        _fail_job(conn, job.id, error)
        log.error("job.failed", error=error)
        return None


def _maybe_project(
    conn: Connection,
    config: AppConfig,
    meeting_id: UUID,
    statuses: dict[str, str],
    log: logs.BoundLogger,
    attempted: set[UUID] | None = None,
) -> None:
    """Project this meeting into the retrieval stores once its evidence is complete.

    **The ingest-complete trigger (AD-4).** AD-4 says evidence projects "at
    ingest-complete", but no job can reach ``done``: ``extract`` is in
    ``STAGE_NAMES``, has no implementation, and the runner deliberately pauses
    there rather than marking unbuilt work done. AD-4 itself splits the two
    triggers — evidence projects at ingest-complete, *artifacts* project on
    publish — and ``extract`` produces artifacts only, so it is not an input to
    the evidence projection. ``evidence_complete()`` is therefore the honest
    trigger, and it stays correct unchanged once Epic 4 registers ``extract``
    and jobs start reaching ``done``.

    **Called from inside the stage loop, never after it.** Every job in the
    system today returns at the ``extract`` pause, so the code after the loop
    is unreachable and a projection call placed there would silently never run.
    This is called at each point a stage settles instead, which is what makes
    it fire on the paused-at-``extract`` path.

    **Projection failure never fails the job.** The evidence is computed,
    durable, and correct; a store being down is an operational problem
    ``rebuild`` fixes, and failing the ingest would force a re-run of hours of
    pipeline work to recover from it. Guarding on the recorded
    ``meeting_projection`` state makes calling this at three settle points per
    stage harmless and the whole thing idempotent across restarts, and
    ``attempted`` keeps a *failing* projection from repeating once per settled
    stage.
    """
    if not evidence_complete(statuses):
        return
    if attempted is not None:
        # One attempt per meeting per pass. The recorded `meeting_projection`
        # row already makes a *successful* projection a no-op at the remaining
        # settle points; this makes a *failing* one quiet too, instead of
        # retrying a down store once per settled stage and burying the real
        # error in six identical log lines.
        if meeting_id in attempted:
            return
        attempted.add(meeting_id)
    try:
        action = projections.projection_action(conn, config, meeting_id)
        if action == projections.ACTION_NONE:
            return
        if action == projections.ACTION_FULL:
            outcome = projections.project_meeting(conn, config, meeting_id, log=log)
        else:
            outcome = projections.project_meeting_embeddings(
                conn, config, meeting_id, log=log
            )
    except Exception as exc:  # noqa: BLE001 - never fail an ingest over a store
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - a broken connection must not escape
            # "Projection failure never fails the job" has to survive the
            # cleanup too: a connection broken by whatever just failed would
            # otherwise raise here and take down an ingest whose evidence is
            # already computed, durable, and correct.
            pass
        log.error(
            "projection.failed",
            meeting_id=meeting_id,
            error=f"{type(exc).__name__}: {exc}",
            recovery="run 'rebuild --meeting <id>' once the store is back",
        )
        return
    log(
        "projection.done",
        meeting_id=meeting_id,
        structural=outcome.structural,
        embedded=outcome.embedded,
        moments=outcome.moment_documents,
        chunks=outcome.chunk_documents,
        warning=outcome.warning,
    )


def run_job(
    conn: Connection,
    job: ClaimedJob,
    config: AppConfig,
    content_root: Path,
) -> None:
    """Advance one claimed job as far as the built stages allow."""
    # Claim/mint are pipeline events too. Bind a stage up front so every
    # worker/pipeline log record satisfies the job_id + stage contract.
    log = logs.bind(job_id=job.id, stage="claim")
    log(
        "job.claimed",
        source_id=job.source_id,
        drop_relative_path=job.drop_relative_path,
    )

    drops_root = _drops_root_or_fail(conn, job, log, config)
    if drops_root is None:
        return
    drop_dir = _resolve_drop_or_fail(conn, job, log, drops_root)
    if drop_dir is None:
        return
    drop = _read_drop_or_fail(conn, job, log, config, drop_dir)
    if drop is None:
        return

    # Read before minting, because `mint_meeting`'s ON CONFLICT overwrites it:
    # this is the only moment the *previous* recording state is still on the
    # row. `None` means no meeting yet — a first claim, not an augmentation.
    had_recording = _persisted_has_recording(conn, job.id)

    try:
        meeting_id = mint_meeting(conn, job, drop)
    except Exception as exc:  # malformed metadata can surface only on retry
        error = f"meeting mint failed: {type(exc).__name__}: {exc}"
        _fail_job(conn, job.id, error)
        log.error("job.failed", error=error)
        return
    log(
        "job.meeting_minted",
        meeting_id=meeting_id,
        has_recording=drop.has_recording,
    )

    # A declared augmentation (the drop carries `augments`) or the recovery of a
    # recording for a meeting persisted as having none. The second case is kept
    # beside the first because a plain re-queue of a failed job can also bring a
    # recording, and it carries no declaration.
    if drop.metadata.get("augments") is not None or (
        drop.has_recording and had_recording is False
    ):
        _invalidate_augmented_projection(conn, meeting_id, log)

    if not drop.has_recording:
        try:
            _clear_replaced_video_evidence(conn, job.id, meeting_id, content_root)
            conn.commit()
        except Exception as exc:  # deletion must not leave misleading evidence
            error = f"video evidence cleanup failed: {type(exc).__name__}: {exc}"
            _fail_job(conn, job.id, error)
            log.error("job.failed", error=error)
            return

    statuses = _stage_statuses(conn, job.id)
    # Meetings this pass already offered to the projection module (see
    # `_maybe_project`). Per-pass, not per-process: a later claim retries.
    projection_attempted: set[UUID] = set()
    for name in STAGE_NAMES:
        stage_log = log.bind(stage=name)
        if statuses.get(name) in _SETTLED_STAGE_STATUSES:
            stage_log("stage.resumed", status=statuses[name])
            # Covers a re-claimed job whose evidence completed in an earlier
            # claim: nothing settles in this pass, so without a check here the
            # projection would never fire for it.
            _maybe_project(conn, config, meeting_id, statuses, stage_log, projection_attempted)
            continue

        if not drop.has_recording and name in VIDEO_ONLY_STAGES:
            _set_stage(conn, job.id, name, "skipped")
            statuses[name] = "skipped"
            stage_log("stage.skipped", reason="drop has no recording")
            _maybe_project(conn, config, meeting_id, statuses, stage_log, projection_attempted)
            continue

        implementation = stage_implementation(name)
        if implementation is None:
            # Honest pause: the job stays `running` with this stage `queued`
            # until the story that builds it registers an implementation.
            stage_log("job.paused", reason="stage not implemented yet")
            return

        _set_stage(conn, job.id, name, "running")
        stage_log("stage.started")
        ctx = StageContext(
            conn=conn,
            config=config,
            job_id=job.id,
            meeting_id=meeting_id,
            drop=drop,
            content_root=content_root,
            drops_root=drops_root,
            log=stage_log,
        )
        try:
            implementation(ctx)
            if name in {"screens", "align"}:
                # Both stages replace evidence `moments` owns: `screens`
                # deletes screenshot rows (whose FK only clears the reference)
                # and `align` replaces transcript segments (cascading their
                # links). Queue the dependent stage in this transaction, so a
                # producer failure rolls the invalidation back with its work.
                # `statuses` was read once before this loop, therefore it must
                # change too or this same claim would resume an old `done`
                # checkpoint and never rebuild the bundle.
                conn.execute(
                    "UPDATE job_stage SET status = 'queued', error = NULL"
                    " WHERE job_id = %s AND name = 'moments'",
                    (job.id,),
                )
                statuses["moments"] = "queued"
            conn.commit()
        except StageError as exc:
            _run_hooks(ctx.after_rollback, stage_log, "rollback")
            _fail_job(conn, job.id, str(exc), stage=name)
            stage_log.error("stage.failed", error=str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - a bug must not be swallowed either
            _run_hooks(ctx.after_rollback, stage_log, "rollback")
            error = f"unexpected {type(exc).__name__}: {exc}"
            _fail_job(conn, job.id, error, stage=name)
            stage_log.error("stage.failed", error=error)
            return

        # Outside the try on purpose. The rows are durable now, so a failing
        # commit hook must never reach the rollback path — running
        # `swap.restore()` here would revert the directory those committed
        # rows name. A hook failure is reported and the job continues.
        _run_hooks(ctx.after_commit, stage_log, "commit")

        _set_stage(conn, job.id, name, "done")
        statuses[name] = "done"
        stage_log("stage.done")
        # The settle point that actually fires for a normal run: `moments`
        # finishing is what completes the evidence bundle.
        _maybe_project(conn, config, meeting_id, statuses, stage_log, projection_attempted)

    # Reached only once every stage in STAGE_NAMES is built; today every job
    # pauses at `extract`, whichever kind of drop it carries.
    conn.execute("UPDATE job SET status = 'done', error = NULL WHERE id = %s", (job.id,))
    conn.commit()
    log("job.done")


def run_once(pool: ConnectionPool, config: AppConfig, content_root: Path) -> bool:
    """Claim and advance at most one job. Returns whether one was claimed.

    ``False`` means the queue was empty — the worker then idles at its poll
    interval rather than logging anything (no log spam on an idle queue).
    """
    with pool.connection() as conn:
        job = claim_job(conn)
        if job is None:
            return False
        try:
            run_job(conn, job, config, content_root)
        except psycopg.Error:
            # If the connection recovered enough to accept this rollback and
            # update, put the claimed job back immediately. Waiting for a full
            # process restart would otherwise strand it after a transient DB
            # outage. If the database is still unavailable, re-raise: the next
            # successful poll/startup recovery remains the fallback.
            try:
                conn.rollback()
                conn.execute(
                    "UPDATE job SET status = 'queued' WHERE id = %s AND status = 'running'",
                    (job.id,),
                )
                conn.commit()
            except psycopg.Error:
                conn.rollback()
                raise
    return True
