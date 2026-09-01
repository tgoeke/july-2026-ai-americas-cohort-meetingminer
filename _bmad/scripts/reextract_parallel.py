"""Re-run the `extract` stage over every meeting, in parallel.

**Why this exists.** The corpus was ingested before story 12.1 landed, so every
meeting's extraction documents were generated, parsed and discarded:
`extraction_source` holds 205 runs and **zero** retained document texts. The
markdown an owner actually wants — the ADR document, the action-items document —
does not exist for any meeting. Re-running `extract` is the only way to fill it,
because the document is a model output that nothing else reproduces.

**Why not the worker.** The worker holds a Postgres advisory lock for its
process lifetime, so a second one refuses to start by design, and it advances
one job at a time. Extraction is dominated by waiting on a remote model, so a
serial drain leaves the machine idle for most of an hour. This drives the same
stage function the worker drives — `pipeline.stages.extract.run` — over a thread
pool, one connection and one transaction per meeting.

**What it does not do.** It does not touch any other stage, does not re-probe,
re-frame, re-OCR or re-transcribe, and does not re-run projections beyond what
the stage itself performs. It writes only what `extract` writes.

Each meeting commits independently: a failure rolls back that meeting alone and
is reported at the end, so a partial run is a known partial rather than an
unknown one.

    uv run --project server python _bmad/scripts/reextract_parallel.py\n        [--workers N] [--limit N] [--meeting UUID ...]
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import UUID

import psycopg

from meetingminer import db
from meetingminer.config import load_config
from meetingminer.domain.drops import read_drop
from meetingminer.pipeline.stage import StageContext
from meetingminer.pipeline.stages import extract

_print_lock = threading.Lock()


def _say(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def _meetings(
    conn: psycopg.Connection, limit: int | None, only: tuple[UUID, ...] = ()
) -> list[tuple[UUID, UUID, str, str]]:
    """Every meeting whose job holds a readable drop, newest first.

    ``only`` narrows the run to named meetings — the case that arises when an
    earlier pass left a few meetings without retained text and re-running the
    other 56 would be paid work for nothing. A named meeting that has no
    readable drop is reported by the caller rather than silently skipped.
    """
    # `drop_relative_path`, not `drop_path`: story 2.1a anchored every stored
    # drop path to MM_DROPS_ROOT, and `drop_path` has been null on all 59 jobs
    # since. Resolved against the root by the caller.
    sql = (
        "SELECT m.id, j.id, j.drop_relative_path, m.title"
        " FROM meeting m JOIN job j ON j.id = m.job_id"
        " WHERE j.drop_relative_path IS NOT NULL"
    )
    params: list[object] = []
    if only:
        sql += " AND m.id = ANY(%s)"
        params.append(list(only))
    sql += " ORDER BY m.started_at DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, params).fetchall() if params else conn.execute(sql).fetchall()
    return [(r[0], r[1], r[2], r[3] or "(untitled)") for r in rows]


def _one(config, content_root: Path, drops_root: Path, row) -> tuple[str, str, str]:
    meeting_id, job_id, drop_path, title = row
    started = time.monotonic()

    def log(event: str, **fields: object) -> None:
        # The stage logs per document; keep only what says the run worked.
        if event in {"extract.document_stored", "extract.binding_resolved"}:
            _say(f"    {title[:38]:40} {event} {fields.get('kind', fields.get('binding', ''))}")

    try:
        with psycopg.connect(db.conninfo(config), connect_timeout=10) as conn:
            drop = read_drop(drops_root / drop_path, config_path=config.config_path)
            extract.run(
                StageContext(
                    conn=conn,
                    config=config,
                    job_id=job_id,
                    meeting_id=meeting_id,
                    drop=drop,
                    content_root=content_root,
                    drops_root=drops_root,
                    log=log,
                )
            )
        return ("ok", title, f"{time.monotonic() - started:.0f}s")
    except Exception as exc:  # noqa: BLE001 — every failure is reported, none swallowed
        return ("failed", title, f"{type(exc).__name__}: {exc}"[:160])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reextract-parallel")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--meeting",
        action="append",
        default=[],
        metavar="UUID",
        help="re-extract only this meeting; repeatable. Every call is paid, so"
        " scoping is the difference between three meetings and fifty-nine.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        only = tuple(UUID(value) for value in args.meeting)
    except ValueError as exc:
        parser.error(f"--meeting takes a UUID: {exc}")

    config = load_config()
    binding = config.settings.llm.roles.extraction
    content_root = Path(config.secrets.mm_content_root)
    drops_root = Path(config.secrets.mm_drops_root)

    with psycopg.connect(db.conninfo(config), connect_timeout=10) as conn:
        db.check_migrations_current(conn)
        rows = _meetings(conn, args.limit, only)

    # A named meeting that matched nothing is a typo or a meeting with no
    # readable drop. Refuse rather than quietly re-extracting a shorter list.
    if only:
        missing = set(only) - {row[0] for row in rows}
        if missing:
            print(
                "error: no meeting with a readable drop for "
                + ", ".join(str(value) for value in sorted(missing)),
                file=sys.stderr,
            )
            return 2

    print(f"model      : {binding.model}  (fallback {binding.fallback})")
    print(f"meetings   : {len(rows)}")
    print(f"workers    : {args.workers}")
    if args.dry_run:
        for _, _, _, title in rows:
            print(f"  would re-extract  {title[:60]}")
        return 0

    started = time.monotonic()
    ok, failed = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_one, config, content_root, drops_root, r): r for r in rows}
        for done in as_completed(futures):
            status, title, detail = done.result()
            (ok if status == "ok" else failed).append((title, detail))
            _say(f"  [{len(ok) + len(failed):>3}/{len(rows)}] {status:6} {title[:44]:46} {detail}")

    print(f"\n{len(ok)} ok, {len(failed)} failed in {(time.monotonic() - started) / 60:.1f} min")
    for title, detail in failed:
        print(f"  FAILED  {title[:44]:46} {detail}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
