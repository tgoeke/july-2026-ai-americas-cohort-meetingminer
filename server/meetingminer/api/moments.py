"""GET /meetings/{meetingId}/moments, GET /moments/{momentId} (story 2.2),
and GET /meetings/{meetingId}/drilldown (story 2.3).

The read side of CAP-4: the moments list a meeting opens onto, the one
moment the web view renders — still screenshot, covering transcript, right
rail, replay offset — and the whole-meeting drill-down: the screenshot series
in capture order plus the full transcript, each segment naming the moment
covering it. Read-only over evidence (AD-5/AD-11): SELECTs only, no store
clients, no writes.

**The viewability gate (the deferred 1.9 obligation).** All three routes
answer for a meeting only once every evidence stage has settled, and the two
failure shapes are deliberately different statuses: an id with no meeting row
was never ingested and is a 404 ``not-found``; an existing meeting whose
evidence is still being prepared — first ingest or augmentation in flight —
is a 409 ``meeting-not-viewable``, because the resource exists and the
condition is transient. The predicate is
``projections.evidence.meeting_evidence_complete``
(a store-free module the api may import), not a re-implementation, so this
gate and the projection trigger can never disagree. The 409 additionally
carries ``augmenting`` and ``jobStatus`` extensions (AD-14): the web's empty
state has to tell an augmenting run from a first ingest, and
``domain.jobs.augmentation_in_flight`` derives that from the same stage rows
the gate already reads.

**Superseded moments are list-hidden, detail-served.** The ``moments`` stage
keeps a superseded row so its id — the citation currency (AD-6) — stays
resolvable, and marks it in provenance so no reader projects it as live
(``pipeline/stages/moments.py``). The list honors that mark; the detail route
serves the row flagged ``superseded: true`` so an existing citation renders as
"superseded" instead of breaking.

**Covering transcript is the ``moment_segment`` join**, never a
``BETWEEN start_ms AND end_ms`` filter: a covered segment may legitimately end
after its moment does, and it is still returned in full.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import logs, projections
from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.domain.jobs import augmentation_in_flight
from meetingminer.projections.evidence import meeting_evidence_complete
from meetingminer.projections.publish_gate import ARTIFACT_STATES, PUBLISHED_STATE
from meetingminer.publish import export

router = APIRouter()
ROUTER_ORDER = 40

# The header the moments list renders under, read before the gate so a missing
# row 404s and an unsettled one 409s — the required never-ingested versus
# augmentation-in-flight distinction.
_MEETING_HEADER = (
    "SELECT id, title, has_recording, corpus, started_at, started_at_precision"
    " FROM meeting WHERE id = %s"
)

# The most of a first segment's text the list ships per row. A preview is a
# one-line orientation, not the transcript — the detail route owns the full
# text — and a real meeting carries a hundred-plus moments, so an unbounded
# preview would ship whole monologues the row then clips anyway. The web
# truncates further with CSS; this cap bounds the wire.
PREVIEW_MAX_CHARS = 300

# One meeting's live moments, in citation order: `start_ms` with the id as the
# tiebreak (UUIDv7, so ties break in mint order). No ordinal is invented —
# augmentation inserts moments between existing ones, which is exactly what an
# ordinal cannot survive (migration 0006). The LATERAL picks the first covered
# segment's text (capped at PREVIEW_MAX_CHARS) as the row's preview —
# LEFT-joined, because a live moment may legitimately cover no segment at all
# (a screen-derived span nobody spoke in) and must still appear in the list;
# `moment_segment`, never a time filter. Superseded rows are excluded here and
# only here: the stage marked them so this list would not interleave ghosts
# with live moments.
_LIVE_MOMENTS = (
    "SELECT m.id, m.start_ms, m.end_ms, m.started_at, m.started_at_precision,"
    " ss.id, m.source_deep_link, m.segment_count, first_seg.text"
    " FROM moment m"
    " LEFT JOIN screenshot ss ON ss.id = m.screenshot_id"
    " AND ss.meeting_id = m.meeting_id"
    " LEFT JOIN LATERAL ("
    f"SELECT LEFT(ts.text, {PREVIEW_MAX_CHARS}) AS text FROM moment_segment ms"
    " JOIN transcript_segment ts ON ts.id = ms.transcript_segment_id"
    " WHERE ms.moment_id = m.id AND ts.meeting_id = m.meeting_id"
    " ORDER BY ts.ordinal LIMIT 1"
    ") first_seg ON true"
    " WHERE m.meeting_id = %s"
    " AND COALESCE(m.provenance->>'superseded', '') <> 'true'"
    " ORDER BY m.start_ms, m.id"
)

# One moment plus its meeting and — when it names one — its screenshot's
# stored content-root-relative path, which is all the web needs to render the
# still through `GET /media/{path}`: no root, no absolute path, no server-built
# URL leaves the server. LEFT JOIN because `screenshot_id` is NULL on a
# transcript-only meeting and on a moment past the last capture.
_MOMENT_WITH_MEETING = (
    "SELECT m.id, m.meeting_id, m.start_ms, m.end_ms, m.started_at,"
    " m.started_at_precision, ss.id, ss.path, m.source_deep_link,"
    " COALESCE(m.provenance->>'superseded', '') = 'true',"
    " mt.title, mt.has_recording, mt.corpus"
    " FROM moment m JOIN meeting mt ON mt.id = m.meeting_id"
    " LEFT JOIN screenshot ss ON ss.id = m.screenshot_id"
    " AND ss.meeting_id = m.meeting_id"
    " WHERE m.id = %s"
)

# The covering transcript, through the `moment_segment` join in the segments'
# own `ordinal` order — the same shape `projections/evidence.py:read_meeting`
# reads. A superseded moment has no links (the stage's rebuild left it at
# zero), so this legitimately answers empty for it.
_COVERING_SEGMENTS = (
    "SELECT ts.start_ms, ts.end_ms, ts.speaker_label, ts.speaker_resolution,"
    " ts.participant_id, ts.text"
    " FROM moment_segment ms"
    " JOIN moment m ON m.id = ms.moment_id"
    " JOIN transcript_segment ts ON ts.id = ms.transcript_segment_id"
    " WHERE ms.moment_id = %s AND ts.meeting_id = m.meeting_id"
    " ORDER BY ts.ordinal"
)

# The right rail's real read (story 4.3, replacing the hardcoded `[]`):
# every artifact this moment yielded, in mint order. `created_at, id` rather
# than a state-dependent order — the rail groups by kind category, not by
# lifecycle state, so insertion order is the only ordering that means
# anything here.
_MOMENT_ARTIFACTS = (
    "SELECT id, kind, state, title, body, published_at, publish_relative_path,"
    " publish_commit_sha FROM artifact WHERE moment_id = %s ORDER BY created_at, id"
)

# The approve route's row lock: only this moment's still-`extracted`
# artifacts, `FOR UPDATE` so a concurrent approve on the same moment cannot
# double-publish (or double-commit) the same row.
_EXTRACTED_ARTIFACTS_FOR_UPDATE = (
    "SELECT id, kind, title, body FROM artifact"
    " WHERE moment_id = %s AND state = 'extracted' ORDER BY created_at, id"
    " FOR UPDATE"
)

_PUBLISH_ARTIFACT = (
    "UPDATE artifact SET state = %s, approved_at = now(), published_at = now(),"
    " publish_relative_path = %s, publish_commit_sha = %s WHERE id = %s"
)

# The drill-down's header: the moments-list header plus the meeting-level
# `sourceDeepLink` — `provenance->>'url'` verbatim, raw and nullable. The drop
# metadata is unvalidated at meeting level (`domain/drops.py` validates only
# moment links), so the web renders it exclusively through `affordanceOf`/
# `safeHref` — the rule story 2.2 litigated for moment links.
_DRILLDOWN_HEADER = (
    "SELECT id, title, has_recording, corpus, started_at, started_at_precision,"
    " provenance->>'url'"
    " FROM meeting WHERE id = %s"
)

# The screenshot series, mirroring the projection's read
# (`projections/evidence.py`): JOIN screen for the human label, ORDER BY
# `ss.ordinal` — the capture order the UNIQUE (meeting_id, ordinal) constraint
# pins, never a timestamp sort. The LATERAL picks the live (non-superseded)
# moment carrying this `screenshot_id`, same-meeting guarded so a corrupt
# foreign FK cannot link another meeting's moment in — LEFT, because a
# screenshot past the last moment (or one only a superseded moment named) is
# still series evidence; LIMIT 1 with the list's own `start_ms, id` order,
# because nothing makes `moment.screenshot_id` unique and two live moments
# sharing a still must not duplicate the series row.
_SCREENSHOT_SERIES = (
    "SELECT ss.id, ss.ordinal, ss.start_offset_ms, ss.end_offset_ms, ss.path,"
    " ss.view_type, s.label, ss.classification_tags, live.id"
    " FROM screenshot ss JOIN screen s ON s.id = ss.screen_id"
    " LEFT JOIN LATERAL ("
    "SELECT m.id FROM moment m"
    " WHERE m.screenshot_id = ss.id AND m.meeting_id = ss.meeting_id"
    " AND COALESCE(m.provenance->>'superseded', '') <> 'true'"
    " ORDER BY m.start_ms, m.id LIMIT 1"
    ") live ON true"
    " WHERE ss.meeting_id = %s ORDER BY ss.ordinal"
)

# The full transcript in the segments' own `ordinal` order, each row naming
# the moment covering it through the `moment_segment` join —
# `UNIQUE (transcript_segment_id)` makes segment→moment a function, so the
# LEFT JOINs cannot fan out. LEFT on both hops: an uncovered segment is listed
# with a NULL moment, and the moment join is same-meeting guarded and
# superseded-filtered so neither a corrupt cross-meeting link nor a superseded
# row ever appears as a segment's moment.
_TRANSCRIPT_WITH_MOMENTS = (
    "SELECT ts.id, ts.ordinal, ts.start_ms, ts.end_ms, ts.speaker_label,"
    " ts.speaker_resolution, ts.participant_id, ts.text, m.id"
    " FROM transcript_segment ts"
    " LEFT JOIN moment_segment ms ON ms.transcript_segment_id = ts.id"
    " LEFT JOIN moment m ON m.id = ms.moment_id"
    " AND m.meeting_id = ts.meeting_id"
    " AND COALESCE(m.provenance->>'superseded', '') <> 'true'"
    " WHERE ts.meeting_id = %s ORDER BY ts.ordinal"
)

# What the enriched 409 reads: the job's own status plus every stage row, in
# one statement on the gate's connection (and therefore its snapshot).
_JOB_WITH_STAGE_STATUSES = (
    "SELECT j.status, s.name, s.status"
    " FROM meeting m JOIN job j ON j.id = m.job_id"
    " LEFT JOIN job_stage s ON s.job_id = j.id"
    " WHERE m.id = %s"
)

# The right rail's forward contract, pinned before Epic 4 delivers a single
# row: the seven categories are CAP-4's rail verbatim (action items, ADRs,
# decisions, stories, requirements, bug fixes, change requests) as wire slugs,
# and the states are `publish_gate.ARTIFACT_STATES` — asserted below so the
# two spellings cannot drift apart. Epic 4 adds rows; these fields do not
# change, so its arrival is data rather than a wire break.
ArtifactKind = Literal[
    "action-item",
    "adr",
    "decision",
    "story",
    "requirement",
    "bug-fix",
    "change-request",
]
ArtifactState = Literal["extracted", "approved", "published"]

# A hard check rather than an `assert`: `python -O` strips asserts, and the
# vocabulary lock has to hold in optimized runs too.
if get_args(ArtifactState) != ARTIFACT_STATES:
    raise RuntimeError(
        "the api's artifact-state vocabulary must be the publish gate's,"
        f" verbatim: {get_args(ArtifactState)!r} != {ARTIFACT_STATES!r}"
    )


class MomentArtifact(BaseModel):
    """One extracted artifact, as the right rail renders it.

    `id`/`kind`/`state`/`title`/`body` are 2.2's frozen wire fields, unchanged
    in name and meaning. The three publish fields are story 4.3's addition:
    all `None` for an `extracted` or `approved` row, all set together once a
    row becomes `published` — there is no state where only some are set.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    kind: ArtifactKind
    state: ArtifactState
    title: str
    body: str
    published_at: datetime | None = None
    # The exported file's path relative to MM_PUBLISH_ROOT — the outbound
    # link AC4 asks for, rendered as text since it names a local filesystem
    # location rather than a URL.
    publish_relative_path: str | None = None
    # The git commit sha, for a published `adr` only; NULL for a published
    # `action-item` (exported but never committed).
    publish_commit_sha: str | None = None


class MomentListItem(BaseModel):
    """One live moment, as the meeting's moments list renders it.

    Field names and types reuse the `SearchHit` vocabulary (`api/search.py`)
    wherever the two describe the same column, so the generated TS client
    keeps one spelling per column.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    moment_id: UUID
    start_ms: int
    end_ms: int
    started_at: datetime
    started_at_precision: str
    screenshot_id: UUID | None = None
    source_deep_link: str | None = None
    segment_count: int
    # The first covered segment's text, capped at PREVIEW_MAX_CHARS — the list
    # row's one-line preview, not the transcript (the detail route owns that).
    # NULL when the moment covers no segment at all.
    preview: str | None = None


class MeetingMomentsResponse(BaseModel):
    """The meeting header plus its live moments, in `start_ms, id` order."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    title: str | None = None
    has_recording: bool
    corpus: str
    started_at: datetime
    started_at_precision: str
    moments: list[MomentListItem]


class MomentSegment(BaseModel):
    """One covered transcript segment, exactly as stored — an overhanging
    `end_ms` is the segment's own reading, not an error to clip."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    start_ms: int
    end_ms: int
    speaker_label: str
    speaker_resolution: str | None = None
    participant_id: UUID | None = None
    text: str


class MomentDetail(BaseModel):
    """One moment: the evidence CAP-4's view renders."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    moment_id: UUID
    meeting_id: UUID
    meeting_title: str | None = None
    corpus: str
    has_recording: bool
    start_ms: int
    end_ms: int
    started_at: datetime
    started_at_precision: str
    screenshot_id: UUID | None = None
    # The stored content-root-relative `screenshot.path` verbatim, for
    # `GET /media/{path}` — beside the id because the id is citation parity
    # and the path is what an `<img>` needs (`SearchHit` carries only the id;
    # its consumer never renders the image).
    screenshot_path: str | None = None
    # `moment.source_deep_link` verbatim: no time parameter appended, no
    # re-derivation from meeting provenance (UX-DR11).
    source_deep_link: str | None = None
    # True when a later run re-cut this span onto a different row. The id
    # still resolves — it is a citation — but a renderer must be able to say
    # "superseded" instead of presenting it as live.
    superseded: bool
    segments: list[MomentSegment]
    artifacts: list[MomentArtifact]


# The three view classifications, exactly the CHECK on `screenshot.view_type`
# (migration 0003) — typed as a Literal so the generated TS client carries the
# vocabulary instead of a bare string (the `ArtifactKind` precedent).
ScreenViewType = Literal["slide", "ui-screen", "participant-gallery"]


class DrilldownScreenshot(BaseModel):
    """One capture in the meeting's screenshot series, in `ordinal` order.

    `view_type` is the stored `screenshot.view_type` (slide / ui-screen /
    participant-gallery) and `screen_label` the human-edited `screen.label`
    when set. `moment_id` is the live moment carrying this `screenshot_id` —
    NULL when only a superseded moment (or none at all) names it.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    screenshot_id: UUID
    ordinal: int
    start_offset_ms: int
    end_offset_ms: int
    # The stored content-root-relative path verbatim, for `GET /media/{path}`.
    path: str
    view_type: ScreenViewType
    screen_label: str | None = None
    classification_tags: list[str]
    moment_id: UUID | None = None


class DrilldownSegment(BaseModel):
    """One transcript segment of the whole meeting, in `ordinal` order.

    The segment fields spell exactly what `MomentSegment` spells; `moment_id`
    is the live moment covering it through `moment_segment` — NULL for an
    uncovered segment.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    segment_id: UUID
    ordinal: int
    start_ms: int
    end_ms: int
    speaker_label: str
    speaker_resolution: str | None = None
    participant_id: UUID | None = None
    text: str
    moment_id: UUID | None = None


class MeetingDrilldownResponse(BaseModel):
    """The whole meeting's evidence: header, series, full transcript."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    title: str | None = None
    has_recording: bool
    corpus: str
    started_at: datetime
    started_at_precision: str
    # `meeting.provenance->>'url'` verbatim — raw drop metadata, nullable,
    # rendered only through the web's affordance helpers.
    source_deep_link: str | None = None
    screenshots: list[DrilldownScreenshot]
    segments: list[DrilldownSegment]


_PROBLEM_RESPONSES = {
    422: {
        # `model` would make FastAPI add an application/json alternative.
        # The app-wide validation handler only emits RFC 9457 problem+json, so
        # name the already-registered component directly to document that
        # exact runtime contract and no fictional media type.
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`invalid-request` — the route parameter is not a UUID.",
    },
    404: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`not-found` — no such row; the meeting was never"
        " ingested (or the moment never minted).",
    },
    409: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`meeting-not-viewable` — the meeting exists but an"
        " evidence stage has not settled; first ingest or augmentation is in"
        " flight. Transient: retry once ingestion settles. Carries two"
        " additive extensions beside `meetingId` (story 2.3, AD-14):"
        " `augmenting` (bool — an augmentation re-run, not a first ingest)"
        " and `jobStatus` (str — the job row's own status, e.g. `running`"
        " or `failed`).",
    },
}


def _require_viewable(conn, meeting_id: UUID) -> None:
    """409 unless every evidence stage of this meeting is done/skipped.

    The refusal carries two additive extensions beyond 2.2's pinned
    ``meetingId``: ``augmenting`` (is this an augmentation re-run rather than
    a first ingest — `domain.jobs.augmentation_in_flight` over the same stage
    rows, read on the same connection and therefore the gate's snapshot) and
    ``jobStatus`` (the job row's own status, so a ``failed`` ingest is
    distinguishable from one still ``running``).
    """
    if not meeting_evidence_complete(conn, meeting_id):
        rows = conn.execute(_JOB_WITH_STAGE_STATUSES, (meeting_id,)).fetchall()
        # `meeting.job_id` is NOT NULL with an FK (migration 0002), so a
        # meeting the gate just read always joins to a job and `rows` cannot
        # be empty — the "unknown" arm is schema-unreachable, kept only so a
        # future schema change degrades to an honest word instead of an
        # IndexError inside the error path.
        job_status = rows[0][0] if rows else "unknown"
        stage_statuses = {name: status for _, name, status in rows if name is not None}
        raise Problem(
            409,
            "meeting-not-viewable",
            f"meeting {meeting_id} exists but its evidence is still being"
            " prepared — an ingest or augmentation stage has not settled yet;"
            " it will become viewable when every evidence stage is done or"
            " skipped",
            meetingId=str(meeting_id),
            augmenting=augmentation_in_flight(stage_statuses),
            jobStatus=job_status,
        )


@router.get(
    "/meetings/{meeting_id}/moments",
    operation_id="listMeetingMoments",
    response_model=MeetingMomentsResponse,
    responses=_PROBLEM_RESPONSES,
)
def list_meeting_moments(meeting_id: UUID, request: Request) -> MeetingMomentsResponse:
    pool = request.app.state.pool
    # Three reads on one connection, split like `read_meeting`: header first
    # (absence is the 404), the gate second (existence without settled
    # evidence is the 409), the moments last. The transaction is REPEATABLE
    # READ so all three come from one snapshot — the house "one statement,
    # one snapshot" invariant extended to a read that cannot be one statement.
    # Under the default Read Committed, an augmentation committing between the
    # gate and the list would pass the gate on the pre-augmentation stages and
    # then serve mid-rebuild rows as viewable.
    with pool.connection() as conn:
        # First statement of the (implicit) transaction, so it governs every
        # read below; it expires with the transaction, leaving nothing set on
        # the pooled connection.
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        header = conn.execute(_MEETING_HEADER, (meeting_id,)).fetchone()
        if header is None:
            raise Problem(404, "not-found", f"no meeting with id {meeting_id}")
        _require_viewable(conn, meeting_id)
        rows = conn.execute(_LIVE_MOMENTS, (meeting_id,)).fetchall()

    moments = [
        MomentListItem(
            moment_id=row[0],
            start_ms=row[1],
            end_ms=row[2],
            started_at=row[3],
            started_at_precision=row[4],
            screenshot_id=row[5],
            source_deep_link=row[6],
            segment_count=row[7],
            preview=row[8],
        )
        for row in rows
    ]
    logs.log_event("moments.listed", meeting_id=meeting_id, moments=len(moments))
    return MeetingMomentsResponse(
        meeting_id=header[0],
        title=header[1],
        has_recording=header[2],
        corpus=header[3],
        started_at=header[4],
        started_at_precision=header[5],
        moments=moments,
    )


@router.get(
    "/moments/{moment_id}",
    operation_id="getMoment",
    response_model=MomentDetail,
    responses=_PROBLEM_RESPONSES,
)
def get_moment(moment_id: UUID, request: Request) -> MomentDetail:
    pool = request.app.state.pool
    # Same split, same reasoning as the list route: the moment+meeting join
    # first (absence is the 404), the gate second, the covering segments last
    # — and the same REPEATABLE READ, so the gate's verdict and the segments
    # it vouches for come from one snapshot rather than straddling an
    # augmentation commit.
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        row = conn.execute(_MOMENT_WITH_MEETING, (moment_id,)).fetchone()
        if row is None:
            raise Problem(404, "not-found", f"no moment with id {moment_id}")
        _require_viewable(conn, row[1])
        segment_rows = conn.execute(_COVERING_SEGMENTS, (moment_id,)).fetchall()
        artifact_rows = conn.execute(_MOMENT_ARTIFACTS, (moment_id,)).fetchall()

    logs.log_event(
        "moments.viewed",
        moment_id=moment_id,
        meeting_id=row[1],
        segments=len(segment_rows),
        superseded=row[9],
    )
    return MomentDetail(
        moment_id=row[0],
        meeting_id=row[1],
        start_ms=row[2],
        end_ms=row[3],
        started_at=row[4],
        started_at_precision=row[5],
        screenshot_id=row[6],
        screenshot_path=row[7],
        source_deep_link=row[8],
        superseded=row[9],
        meeting_title=row[10],
        has_recording=row[11],
        corpus=row[12],
        segments=[
            MomentSegment(
                start_ms=segment[0],
                end_ms=segment[1],
                speaker_label=segment[2],
                speaker_resolution=segment[3],
                participant_id=segment[4],
                text=segment[5],
            )
            for segment in segment_rows
        ],
        # The rail's real read (story 4.3): unpublished artifacts surface
        # here and only here (AD-4) — this route never filters by state.
        artifacts=[
            MomentArtifact(
                id=artifact[0],
                kind=artifact[1],
                state=artifact[2],
                title=artifact[3],
                body=artifact[4],
                published_at=artifact[5],
                publish_relative_path=artifact[6],
                publish_commit_sha=artifact[7],
            )
            for artifact in artifact_rows
        ],
    )


@router.post(
    "/moments/{moment_id}/approve",
    operation_id="approveMomentArtifacts",
    response_model=list[MomentArtifact],
    responses=_PROBLEM_RESPONSES,
)
def approve_moment_artifacts(moment_id: UUID, request: Request) -> list[MomentArtifact]:
    """The per-moment approval gesture (story 4.3, epics AC1/AC2/AC3).

    One request advances every `extracted` artifact under this moment through
    both `approved` and `published` — there is no separate human gesture for
    the middle state (Design Notes). Each row is exported to
    `MM_PUBLISH_ROOT` and, for `adr` rows, git-committed there *before* the
    Postgres `UPDATE`: a filesystem or git failure must leave every affected
    row `extracted`, never half-published (AD-4/AD-5).
    """
    pool = request.app.state.pool
    publish_root = request.app.state.publish_root
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        row = conn.execute(_MOMENT_WITH_MEETING, (moment_id,)).fetchone()
        if row is None:
            raise Problem(404, "not-found", f"no moment with id {moment_id}")
        _require_viewable(conn, row[1])
        pending = conn.execute(_EXTRACTED_ARTIFACTS_FOR_UPDATE, (moment_id,)).fetchall()
        if not pending:
            raise Problem(
                409,
                "nothing-to-approve",
                f"moment {moment_id} has no extracted artifacts to approve"
                " — either none were extracted yet, or every artifact under"
                " it is already approved or published",
            )

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
            if kind == "adr":
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

        # Re-read *every* artifact this moment has — not just the rows this
        # call just published — on the same connection/transaction, so the
        # response carries exactly what Postgres now holds (including
        # `now()`'s actual value for the newly-published rows). The web
        # replaces its whole `detail.artifacts` state with this response
        # (`MomentView.tsx`), so answering with only the just-published rows
        # would silently drop any artifact published by an earlier call, or
        # extracted by a later rerun, from the rail until the next reload.
        refreshed = conn.execute(_MOMENT_ARTIFACTS, (moment_id,)).fetchall()

    # Projection runs *after* the transaction above has committed — the rows
    # are durably `published` before any store is touched (story 4.4 Design
    # Notes: never hold FOR UPDATE locks across two store writes and a
    # cross-process file lock). And the gesture never fails over a store
    # (mirrors the worker's policy): any store, lock or unexpected failure is
    # logged with the recovery hint and the route still returns the published
    # rows. The gap window — `published` in Postgres, absent from the stores —
    # is closed by `rebuild --meeting <id>`.
    published_ids = [pending_row[0] for pending_row in pending]
    try:
        with pool.connection() as conn:
            projections.project_published_artifacts(
                conn,
                request.app.state.config,
                artifact_ids=published_ids,
                log=logs.log_event,
            )
    except Exception as exc:  # noqa: BLE001 — the gesture must not 5xx over a store
        logs.log_event(
            "artifacts.projection.failed",
            moment_id=moment_id,
            meeting_id=row[1],
            artifact_ids=[str(artifact_id) for artifact_id in published_ids],
            error=f"{type(exc).__name__}: {exc}",
            recovery=f"rebuild --meeting {row[1]}",
        )

    result = [
        MomentArtifact(
            id=artifact[0],
            kind=artifact[1],
            state=artifact[2],
            title=artifact[3],
            body=artifact[4],
            published_at=artifact[5],
            publish_relative_path=artifact[6],
            publish_commit_sha=artifact[7],
        )
        for artifact in refreshed
    ]
    logs.log_event(
        "moments.approved",
        moment_id=moment_id,
        meeting_id=row[1],
        artifacts=len(result),
    )
    return result


@router.get(
    "/meetings/{meeting_id}/drilldown",
    operation_id="getMeetingDrilldown",
    response_model=MeetingDrilldownResponse,
    responses=_PROBLEM_RESPONSES,
)
def get_meeting_drilldown(meeting_id: UUID, request: Request) -> MeetingDrilldownResponse:
    """One meeting's whole evidence surface (story 2.3, UX-DR5).

    The header with the meeting-level `sourceDeepLink`, the screenshot series
    in `ordinal` order — each capture labeled with its stored classification
    and carrying the live moment that names it — and the full transcript,
    each segment naming the moment covering it through `moment_segment`.
    Uncovered segments and unclaimed screenshots appear with a NULL
    `momentId`; superseded moments appear in neither mapping.
    """
    pool = request.app.state.pool
    # Same split, same reasoning as the moments list: header first (absence is
    # the 404), the gate second (existence without settled evidence is the
    # 409), the evidence last — all under REPEATABLE READ so the series and
    # transcript come from the snapshot the gate vouched for rather than
    # straddling an augmentation commit.
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        header = conn.execute(_DRILLDOWN_HEADER, (meeting_id,)).fetchone()
        if header is None:
            raise Problem(404, "not-found", f"no meeting with id {meeting_id}")
        _require_viewable(conn, meeting_id)
        screenshot_rows = conn.execute(_SCREENSHOT_SERIES, (meeting_id,)).fetchall()
        segment_rows = conn.execute(_TRANSCRIPT_WITH_MOMENTS, (meeting_id,)).fetchall()

    screenshots = [
        DrilldownScreenshot(
            screenshot_id=row[0],
            ordinal=row[1],
            start_offset_ms=row[2],
            end_offset_ms=row[3],
            path=row[4],
            view_type=row[5],
            screen_label=row[6],
            classification_tags=list(row[7] or ()),
            moment_id=row[8],
        )
        for row in screenshot_rows
    ]
    segments = [
        DrilldownSegment(
            segment_id=row[0],
            ordinal=row[1],
            start_ms=row[2],
            end_ms=row[3],
            speaker_label=row[4],
            speaker_resolution=row[5],
            participant_id=row[6],
            text=row[7],
            moment_id=row[8],
        )
        for row in segment_rows
    ]
    logs.log_event(
        "moments.drilldown",
        meeting_id=meeting_id,
        screenshots=len(screenshots),
        segments=len(segments),
    )
    return MeetingDrilldownResponse(
        meeting_id=header[0],
        title=header[1],
        has_recording=header[2],
        corpus=header[3],
        started_at=header[4],
        started_at_precision=header[5],
        source_deep_link=header[6],
        screenshots=screenshots,
        segments=segments,
    )
