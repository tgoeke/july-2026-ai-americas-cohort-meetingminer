"""``prune``: delete meetings the corpus should no longer carry.

Nothing else in this system deletes a meeting. Ingestion is append-only, the
api exposes no delete route, and the obvious ``DELETE FROM meeting`` is
refused by Postgres: ``artifact`` references both ``meeting`` and ``moment``
with ``ON DELETE NO ACTION`` on purpose (migration 0009), so that deleting a
moment which yielded published evidence fails loudly instead of silently
taking the evidence with it. This module is the one place authorized to
unwind that guard, and it does so explicitly rather than by weakening the
constraint.

**The delete unit is the job row, not the meeting row.** ``meeting.job_id``
is ``ON DELETE CASCADE``, so deleting the job takes the meeting and, through
it, every table that cascades from a meeting: ``extraction_source``,
``frame``, ``frame_ocr``, ``meeting_crop``, ``meeting_media``,
``meeting_participant``, ``meeting_project``, ``meeting_projection``,
``meeting_series``, ``moment`` (and its ``moment_segment`` rows),
``screenshot``, ``transcript_segment`` and ``transcript_source``. Deleting
the meeting row alone would leave its job behind.

**Two tables are corpus-global and do not cascade.** ``screen`` carries no
meeting FK at all — it is the identity-keyed dedupe row several meetings'
screenshots point at — and ``participant`` is only linked through
``meeting_participant``. Both are swept, but only across the entities the
purge actually touched: a screen or participant that was already unreferenced
before this run is somebody else's row and is left alone. A participant still
named by a surviving ``transcript_segment`` is kept even with no
``meeting_participant`` row, because that FK is ``SET NULL`` and deleting the
row would quietly blank a kept meeting's speaker attribution.

Filesystem work never happens inside the transaction. The paths are collected
while the rows still exist, the transaction commits, and only then is
anything removed — a rolled-back purge must not leave a deleted directory
behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from psycopg import Connection

from meetingminer.config import AppConfig

#: Tables whose per-meeting row counts the report names. Ordered the way a
#: reader thinks about the bundle (the job and its meeting, then the evidence
#: that hangs off it), not the order they are deleted in.
COUNTED_TABLES: tuple[str, ...] = (
    "job",
    "meeting",
    "artifact",
    "moment",
    "moment_segment",
    "screenshot",
    "transcript_segment",
    "transcript_source",
    "frame",
    "frame_ocr",
    "meeting_participant",
    "meeting_media",
    "meeting_crop",
    "extraction_source",
)

#: How each counted table reaches its meeting. Every one of these is either
#: keyed by ``meeting_id`` directly or reached through exactly one join, and
#: the join is spelled out here so the count in the dry-run report and the
#: rows the delete actually removes can never drift apart.
_COUNT_SQL: dict[str, str] = {
    "job": "SELECT count(*) FROM job j"
           " WHERE EXISTS (SELECT 1 FROM meeting m WHERE m.job_id = j.id"
           "               AND m.id = ANY(%(ids)s))",
    "meeting": "SELECT count(*) FROM meeting WHERE id = ANY(%(ids)s)",
    "artifact": "SELECT count(*) FROM artifact WHERE meeting_id = ANY(%(ids)s)",
    "moment": "SELECT count(*) FROM moment WHERE meeting_id = ANY(%(ids)s)",
    "moment_segment": "SELECT count(*) FROM moment_segment ms"
                      " JOIN moment mo ON mo.id = ms.moment_id"
                      " WHERE mo.meeting_id = ANY(%(ids)s)",
    "screenshot": "SELECT count(*) FROM screenshot WHERE meeting_id = ANY(%(ids)s)",
    "transcript_segment": "SELECT count(*) FROM transcript_segment"
                          " WHERE meeting_id = ANY(%(ids)s)",
    "transcript_source": "SELECT count(*) FROM transcript_source"
                         " WHERE meeting_id = ANY(%(ids)s)",
    "frame": "SELECT count(*) FROM frame WHERE meeting_id = ANY(%(ids)s)",
    "frame_ocr": "SELECT count(*) FROM frame_ocr WHERE meeting_id = ANY(%(ids)s)",
    "meeting_participant": "SELECT count(*) FROM meeting_participant"
                           " WHERE meeting_id = ANY(%(ids)s)",
    "meeting_media": "SELECT count(*) FROM meeting_media WHERE meeting_id = ANY(%(ids)s)",
    "meeting_crop": "SELECT count(*) FROM meeting_crop WHERE meeting_id = ANY(%(ids)s)",
    "extraction_source": "SELECT count(*) FROM extraction_source"
                         " WHERE meeting_id = ANY(%(ids)s)",
}


class PruneError(RuntimeError):
    """A refusal the operator must resolve; printed as a named error."""


@dataclass(frozen=True)
class PublishedFile:
    """One published artifact's markdown file, relative to MM_PUBLISH_ROOT."""

    artifact_id: UUID
    relative_path: Path


@dataclass(frozen=True)
class PurgePlan:
    """Everything a purge would remove, computed before anything is removed."""

    purge_ids: tuple[UUID, ...]
    keep_ids: tuple[UUID, ...]
    titles: dict[UUID, str]
    row_counts: dict[str, int]
    orphan_screen_ids: tuple[UUID, ...]
    orphan_participant_ids: tuple[UUID, ...]
    content_dirs: tuple[Path, ...]
    published_files: tuple[PublishedFile, ...]
    drop_paths: tuple[Path, ...]

    @property
    def total_rows(self) -> int:
        return (
            sum(self.row_counts.values())
            + len(self.orphan_screen_ids)
            + len(self.orphan_participant_ids)
        )


@dataclass
class PurgeReport:
    """What a committed purge actually removed."""

    plan: PurgePlan
    deleted_rows: dict[str, int] = field(default_factory=dict)
    removed_dirs: list[Path] = field(default_factory=list)
    absent_dirs: list[Path] = field(default_factory=list)
    removed_files: list[Path] = field(default_factory=list)
    absent_files: list[Path] = field(default_factory=list)
    commit_sha: str | None = None


def resolve_scope(
    conn: Connection, *, keep_ids: list[UUID], keep_corpus: list[str]
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    """Split the corpus into (kept, to purge), or refuse.

    A keep-set that names nothing is refused rather than treated as "keep
    nothing": the difference between an empty ``--keep-corpus scripted`` and a
    deliberate corpus-wide wipe is exactly the mistake this command must not
    make on someone's behalf.
    """
    rows = conn.execute("SELECT id, corpus FROM meeting").fetchall()
    if not rows:
        raise PruneError("the corpus holds no meetings; nothing to purge")

    known = {row[0] for row in rows}
    unknown = [str(value) for value in keep_ids if value not in known]
    if unknown:
        raise PruneError(
            "--keep names "
            + ("a meeting" if len(unknown) == 1 else "meetings")
            + " that the corpus does not hold: "
            + ", ".join(sorted(unknown))
        )

    corpora = {row[1] for row in rows}
    missing_corpora = sorted(set(keep_corpus) - corpora)
    if missing_corpora:
        raise PruneError(
            "--keep-corpus names no meeting in the corpus: "
            + ", ".join(missing_corpora)
            + f" (the corpus holds: {', '.join(sorted(corpora))})"
        )

    keep = {row[0] for row in rows if row[0] in set(keep_ids) or row[1] in set(keep_corpus)}
    if not keep:
        raise PruneError(
            "the keep-set resolves to zero meetings — refusing to empty the"
            " whole corpus; name what to keep with --keep or --keep-corpus"
        )

    purge = tuple(sorted(known - keep))
    if not purge:
        raise PruneError(
            "the keep-set covers every meeting in the corpus; nothing to purge"
        )
    return tuple(sorted(keep)), purge


def plan_purge(
    conn: Connection,
    config: AppConfig,
    purge_ids: tuple[UUID, ...],
    *,
    sweep_orphans: bool = False,
) -> PurgePlan:
    """Compute every row, directory and published file the purge would remove.

    ``sweep_orphans`` widens the two corpus-global sweeps to rows that were
    already unreferenced before this run — participant rows a merge left
    behind, screens whose meetings are long gone. Off by default because
    those rows are not this purge's to judge; on when the point of the
    purge is that no trace of the old corpus survives.
    """
    ids = list(purge_ids)
    params = {"ids": ids}

    titles = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT id, title FROM meeting WHERE id = ANY(%(ids)s)", params
        ).fetchall()
    }
    row_counts = {
        table: conn.execute(sql, params).fetchone()[0]
        for table, sql in ((name, _COUNT_SQL[name]) for name in COUNTED_TABLES)
    }

    published_files = tuple(
        PublishedFile(row[0], Path(row[1]) / f"{row[0]}.md")
        for row in conn.execute(
            "SELECT id, kind FROM artifact"
            " WHERE meeting_id = ANY(%(ids)s) AND state = 'published'"
            " ORDER BY kind, id",
            params,
        ).fetchall()
    )

    content_root = config.secrets.mm_content_root
    content_dirs = (
        tuple(content_root / "meetings" / str(meeting_id) for meeting_id in purge_ids)
        if content_root is not None
        else ()
    )

    return PurgePlan(
        purge_ids=purge_ids,
        keep_ids=(),
        titles=titles,
        row_counts=row_counts,
        orphan_screen_ids=_would_orphan_screens(conn, ids, sweep_orphans),
        orphan_participant_ids=_would_orphan_participants(conn, ids, sweep_orphans),
        content_dirs=content_dirs,
        published_files=published_files,
        drop_paths=_drop_paths(conn, ids),
    )


def _drop_paths(conn: Connection, ids: list[UUID]) -> tuple[Path, ...]:
    """Each purged meeting's source drop, relative to MM_DROPS_ROOT.

    Collected for every plan so the dry-run can name what ``--drops`` would
    additionally remove; nothing acts on it without that flag. A drop is
    write-once material the pipeline never produced, so naming it in the
    report is the point — an operator should see what they are about to make
    unrecoverable before they ask for it.
    """
    rows = conn.execute(
        "SELECT DISTINCT j.drop_relative_path FROM job j"
        " JOIN meeting m ON m.job_id = j.id"
        " WHERE m.id = ANY(%(ids)s) AND j.drop_relative_path IS NOT NULL"
        " ORDER BY 1",
        {"ids": ids},
    ).fetchall()
    return tuple(Path(row[0]) for row in rows)


def _would_orphan_screens(
    conn: Connection, ids: list[UUID], sweep_orphans: bool = False
) -> tuple[UUID, ...]:
    """Screens whose every screenshot belongs to a meeting being purged.

    Scoped to screens this purge actually touches, unless ``sweep_orphans``
    also claims the ones something else already orphaned.
    """
    touched = (
        ""
        if sweep_orphans
        else " AND EXISTS (SELECT 1 FROM screenshot ss"
             "             WHERE ss.screen_id = s.id"
             "               AND ss.meeting_id = ANY(%(ids)s))"
    )
    rows = conn.execute(
        "SELECT DISTINCT s.id FROM screen s"
        " WHERE NOT EXISTS (SELECT 1 FROM screenshot ss"
        "                   WHERE ss.screen_id = s.id"
        "                     AND NOT (ss.meeting_id = ANY(%(ids)s)))"
        + touched
        + " ORDER BY s.id",
        {"ids": ids},
    ).fetchall()
    return tuple(row[0] for row in rows)


def _would_orphan_participants(
    conn: Connection, ids: list[UUID], sweep_orphans: bool = False
) -> tuple[UUID, ...]:
    """Participants left with no meeting once these meetings are gone.

    The ``transcript_segment`` clause is what keeps a kept meeting's speaker
    attribution intact: that FK is ``SET NULL``, so deleting a participant a
    surviving segment still names would blank the speaker rather than fail.
    """
    touched = (
        ""
        if sweep_orphans
        else " AND EXISTS (SELECT 1 FROM meeting_participant mp"
             "             WHERE mp.participant_id = p.id"
             "               AND mp.meeting_id = ANY(%(ids)s))"
    )
    rows = conn.execute(
        "SELECT DISTINCT p.id FROM participant p"
        " WHERE NOT EXISTS (SELECT 1 FROM meeting_participant mp"
        "                   WHERE mp.participant_id = p.id"
        "                     AND NOT (mp.meeting_id = ANY(%(ids)s)))"
        "   AND NOT EXISTS (SELECT 1 FROM transcript_segment ts"
        "                   WHERE ts.participant_id = p.id"
        "                     AND NOT (ts.meeting_id = ANY(%(ids)s)))"
        + touched
        + " ORDER BY p.id",
        {"ids": ids},
    ).fetchall()
    return tuple(row[0] for row in rows)


def stale_orphans(conn: Connection, purge_ids: tuple[UUID, ...]) -> int:
    """Count rows a scoped purge leaves behind because it did not orphan them.

    The difference between the scoped sweep and ``--sweep-orphans``, so the
    report can name it rather than leave the operator to notice that the
    participant count did not reach zero.
    """
    ids = list(purge_ids)
    scoped = len(_would_orphan_screens(conn, ids)) + len(
        _would_orphan_participants(conn, ids)
    )
    everything = len(_would_orphan_screens(conn, ids, True)) + len(
        _would_orphan_participants(conn, ids, True)
    )
    return everything - scoped


def execute_purge(conn: Connection, plan: PurgePlan) -> dict[str, int]:
    """Delete every planned row. The caller owns the transaction.

    Order is forced by the schema, not by preference: ``artifact`` first
    because its meeting and moment FKs are ``NO ACTION`` and would otherwise
    refuse the delete, then the ``job`` rows whose cascade does the bulk of
    the work, then the two corpus-global sweeps — which can only run once the
    screenshots and meeting_participant rows they test for are already gone.
    """
    ids = list(plan.purge_ids)
    params = {"ids": ids}
    deleted: dict[str, int] = {}

    deleted["artifact"] = conn.execute(
        "DELETE FROM artifact WHERE meeting_id = ANY(%(ids)s)", params
    ).rowcount
    deleted["job"] = conn.execute(
        "DELETE FROM job WHERE id IN"
        " (SELECT job_id FROM meeting WHERE id = ANY(%(ids)s))",
        params,
    ).rowcount

    deleted["screen"] = (
        conn.execute(
            "DELETE FROM screen WHERE id = ANY(%(screens)s)",
            {"screens": list(plan.orphan_screen_ids)},
        ).rowcount
        if plan.orphan_screen_ids
        else 0
    )
    deleted["participant"] = (
        conn.execute(
            "DELETE FROM participant WHERE id = ANY(%(people)s)",
            {"people": list(plan.orphan_participant_ids)},
        ).rowcount
        if plan.orphan_participant_ids
        else 0
    )

    remaining = conn.execute(
        "SELECT count(*) FROM meeting WHERE id = ANY(%(ids)s)", params
    ).fetchone()[0]
    if remaining:
        # Unreachable through the cascade above; asserted rather than assumed
        # because a future migration that drops meeting -> job CASCADE would
        # otherwise turn a purge into a silent no-op.
        raise PruneError(
            f"{remaining} of the {len(ids)} meetings survived the purge —"
            " the meeting -> job cascade did not fire; nothing was committed"
        )
    return deleted
