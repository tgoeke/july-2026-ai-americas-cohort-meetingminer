"""GET /meetings — the ingestion list the UI seeds from (story 1.9).

One row per *job*, not per meeting: a drop that has been accepted but not yet
claimed has no `meeting` row, and the list has to show it advancing anyway.
`meeting.job_id` is UNIQUE (migration 0002), so the join stays one-to-one and
the meeting-side columns are simply NULL until the worker mints the row.

The api reads job, job_stage, and meeting here and writes none of them
(AD-5/AD-11); it starts no pipeline work and blocks on nothing.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.jobs import JobStage, stage_sort_key
from meetingminer.domain.jobs import evidence_complete

router = APIRouter()
ROUTER_ORDER = 30

# One statement, therefore one snapshot — the same reason `_JOB_WITH_STAGES`
# in api/jobs.py is a single query. Reading the jobs, their meetings, and
# their checkpoints separately would let a worker commit land between the
# reads and hand the caller a job paired with stages it never had.
#
# `created_at DESC` is newest-first; the id is the tiebreak, and because ids
# are UUIDv7 it breaks ties in insertion order rather than arbitrarily.
#
# The evidence-card roll-ups (SPEC-ui-reimagine CAP-1, story ui-1) ride the
# same statement as scalar subqueries on `m.id`, so a card's counts come from
# the same snapshot as its stages. All are cheap aggregates over existing
# tables — no new pipeline stage, no migration:
#
# * duration is the probed recording duration when one exists, else the last
#   transcript segment's end (a transcript-only meeting still holds evidence);
# * the poster is the meeting's first non-gallery screenshot — a slide or a
#   ui-screen fronts the card better than webcam tiles — falling back to the
#   first capture of any kind. Its stored content-root-relative `path` rides
#   along because that is what an `<img>` via `GET /media/{path}` needs
#   (the api/moments.py precedent: id for identity, path for rendering).
_MEETINGS_WITH_STAGES = (
    "SELECT j.id, j.status, j.source_id, j.corpus, j.error, j.created_at,"
    " m.id, m.title, m.started_at, m.started_at_precision, m.has_recording,"
    " s.name, s.status, s.error,"
    " COALESCE(mm.duration_ms,"
    "          (SELECT max(t.end_ms) FROM transcript_segment t"
    "            WHERE t.meeting_id = m.id)),"
    " poster.id, poster.path,"
    " (SELECT count(*) FROM moment mo WHERE mo.meeting_id = m.id),"
    " (SELECT count(*) FROM screenshot sc WHERE sc.meeting_id = m.id),"
    " (SELECT count(*) FROM artifact a WHERE a.meeting_id = m.id),"
    " (SELECT count(*) FROM meeting_participant mp WHERE mp.meeting_id = m.id)"
    " FROM job j"
    " LEFT JOIN meeting m ON m.job_id = j.id"
    " LEFT JOIN job_stage s ON s.job_id = j.id"
    " LEFT JOIN meeting_media mm ON mm.meeting_id = m.id"
    " LEFT JOIN LATERAL ("
    "   SELECT ps.id, ps.path FROM screenshot ps"
    "    WHERE ps.meeting_id = m.id"
    "    ORDER BY (ps.view_type = 'participant-gallery') ASC, ps.ordinal ASC"
    "    LIMIT 1"
    " ) poster ON true"
    " ORDER BY j.created_at DESC, j.id DESC"
)


class MeetingListItem(BaseModel):
    """One ingestion, as the meetings view renders it."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: UUID
    # NULL until the worker claims the job and mints the meeting.
    meeting_id: UUID | None = None
    title: str | None = None
    source_id: str
    corpus: str
    started_at: datetime | None = None
    started_at_precision: str | None = None
    has_recording: bool | None = None
    status: str
    error: str | None = None
    stages: list[JobStage]
    # Computed server-side from `evidence_complete` so "safe to open" has one
    # definition instead of being re-derived (and eventually mis-derived) in
    # the browser.
    viewable: bool
    # --- evidence-card roll-ups (story ui-1, CAP-1) ----------------------
    # Recording duration where probed, last transcript end where not; NULL
    # until either exists — never a fabricated zero.
    duration_ms: int | None = None
    # First non-gallery screenshot (else first of any kind); NULL until the
    # screens stage has emitted one. The path is content-root-relative, for
    # `GET /media/{path}`.
    poster_screenshot_id: UUID | None = None
    poster_screenshot_path: str | None = None
    # Cheap per-meeting aggregates; 0 (not NULL) before the meeting exists,
    # because a card with no evidence yet honestly holds zero of each.
    moment_count: int = 0
    screenshot_count: int = 0
    artifact_count: int = 0
    participant_count: int = 0


class MeetingsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meetings: list[MeetingListItem]


def _to_item(job: tuple, stage_rows: list[tuple]) -> MeetingListItem:
    stages = sorted(
        (JobStage(name=row[11], status=row[12], error=row[13]) for row in stage_rows),
        key=lambda stage: stage_sort_key(stage.name),
    )
    return MeetingListItem(
        job_id=job[0],
        status=job[1],
        source_id=job[2],
        corpus=job[3],
        error=job[4],
        meeting_id=job[6],
        title=job[7],
        started_at=job[8],
        started_at_precision=job[9],
        has_recording=job[10],
        stages=stages,
        viewable=evidence_complete({stage.name: stage.status for stage in stages}),
        duration_ms=job[14],
        poster_screenshot_id=job[15],
        poster_screenshot_path=job[16],
        moment_count=job[17],
        screenshot_count=job[18],
        artifact_count=job[19],
        participant_count=job[20],
    )


@router.get(
    "/meetings",
    operation_id="listMeetings",
    response_model=MeetingsResponse,
)
def list_meetings(request: Request) -> MeetingsResponse:
    pool = request.app.state.pool
    with pool.connection() as conn:
        rows = conn.execute(_MEETINGS_WITH_STAGES).fetchall()

    # Rows arrive grouped by job (the ORDER BY is on job columns only), so a
    # plain grouped walk preserves newest-first without a second sort. A job
    # with no checkpoint rows still yields one row, with NULL stage columns.
    items: list[MeetingListItem] = []
    current: tuple | None = None
    stage_rows: list[tuple] = []
    for row in rows:
        if current is None or row[0] != current[0]:
            if current is not None:
                items.append(_to_item(current, stage_rows))
            current, stage_rows = row, []
        if row[11] is not None:
            stage_rows.append(row)
    if current is not None:
        items.append(_to_item(current, stage_rows))

    # `meetings.` rather than anything resembling a wire event name: log events
    # and the SSE contract are separate vocabularies (FR8).
    logs.log_event(
        "meetings.listed",
        meetings=len(items),
        viewable=sum(1 for item in items if item.viewable),
    )
    return MeetingsResponse(meetings=items)
