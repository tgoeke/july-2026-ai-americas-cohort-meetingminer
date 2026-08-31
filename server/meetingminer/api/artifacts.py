"""Meeting-scoped artifacts: the meeting summary, read and approved (story 12.2).

An artifact may be scoped to a meeting rather than to a moment. A meeting
summary analyses the whole transcript and has no single moment to hang from, so
its row carries no ``moment_id`` — migration 0022's ``artifact_scope_matches_kind``
CHECK is the single declaration of which kinds that applies to, and nothing in
this module carries a copy of it. Both statements below select on
``moment_id IS NULL``, the observable fact, so neither can drift from that
constraint.

**Reading a summary needs no citation.** ``GET /meetings/{id}/summary`` renders
stored artifact state; it is not an answer, and "no citation, no answer"
governs answers. What does *not* widen is the citation contract itself:
``meeting_id`` is an artifact's scope and provenance, never a citation, because
AD-15's citation carries a ``momentId`` with ``startMs``/``endMs`` and the
promise is that a citation opens the recording at the second. A summary's
content reaches an answer only through the moments its individual claims anchor
to, exactly as every other claim already does, and a claim the document does not
anchor is not citable at all (AD-6, AD-18). Nothing here emits a citation, and
the publish projection deliberately never writes a meeting-scoped artifact into
either store — see ``projections/publish_gate.py``.

**Publishing is not an exception either.** AD-6 makes human approval the gate
for every artifact, and a meeting-level one is not carved out of it. The approve
route below calls the very same
:func:`meetingminer.api.artifact_publish.publish_extracted` the per-moment
gesture calls, so the two are one implementation rather than two that resemble
each other. The per-moment path is unchanged.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import logs, projections
from meetingminer.api.artifact_publish import publish_extracted
from meetingminer.api.moments import ArtifactState, _require_viewable
from meetingminer.api.problems import Problem
from meetingminer.pipeline.extraction import KIND_SUMMARY

router = APIRouter()

_MEETING_EXISTS = "SELECT id FROM meeting WHERE id = %s"

# The meeting's summary. `moment_id IS NULL` is the scope test — not
# `kind = 'summary'` — so this read cannot disagree with the constraint that
# declares which kinds are meeting-scoped.
#
# `ORDER BY created_at, id LIMIT 1` rather than an assumption of uniqueness:
# nothing in the schema makes a meeting's summary unique, and a route that
# assumed it would fail in the one case worth surviving — a corpus that somehow
# holds two. The extract stage replaces its draft on every rerun and refuses to
# propose into a settled meeting scope, so a second row is not reachable
# through the pipeline; this ordering makes the route deterministic anyway.
_MEETING_SUMMARY = (
    "SELECT id, kind, state, title, body, created_at, published_at,"
    " publish_relative_path, publish_commit_sha FROM artifact"
    " WHERE meeting_id = %s AND moment_id IS NULL"
    " ORDER BY created_at, id LIMIT 1"
)

# The approve route's row lock: this meeting's still-`extracted`
# meeting-scoped artifacts, `FOR UPDATE` so two concurrent approvals of the
# same meeting cannot double-publish a row — the per-moment route's discipline,
# applied to the other scope.
_EXTRACTED_MEETING_SCOPED_FOR_UPDATE = (
    "SELECT id, kind, title, body FROM artifact"
    " WHERE meeting_id = %s AND moment_id IS NULL AND state = 'extracted'"
    " ORDER BY created_at, id FOR UPDATE"
)

_MEETING_SCOPED_ARTIFACTS = (
    "SELECT id, kind, state, title, body, created_at, published_at,"
    " publish_relative_path, publish_commit_sha FROM artifact"
    " WHERE meeting_id = %s AND moment_id IS NULL ORDER BY created_at, id"
)

def _problem(description: str) -> dict[str, object]:
    return {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": description,
    }


# The two routes advertise different failures, and they are kept apart on
# purpose. One shared map would have made the read's generated client carry a
# `500 publish-export-failed` it can never return and a 409 whose description
# named a condition only the write has — a published error contract that is not
# the route's own is a small lie a consumer writes a handler against.
_READ_PROBLEM_RESPONSES = {
    422: _problem("`invalid-request` — the route parameter is not a UUID."),
    404: _problem("`not-found` — no meeting with that id."),
    409: _problem(
        "`meeting-not-viewable` — the meeting exists but an evidence stage has"
        " not settled; the same gate every meeting-scoped read passes."
    ),
}

_APPROVE_PROBLEM_RESPONSES = {
    422: _problem("`invalid-request` — the route parameter is not a UUID."),
    404: _problem("`not-found` — no meeting with that id."),
    409: _problem(
        "`meeting-not-viewable` — an evidence stage has not settled; or"
        " `nothing-to-approve` — the meeting has no extracted meeting-scoped"
        " artifacts."
    ),
    500: _problem(
        "`publish-export-failed` — the artifact could not be written under"
        " MM_PUBLISH_ROOT; every row stays `extracted`."
    ),
}


class MeetingArtifact(BaseModel):
    """One artifact scoped to the meeting rather than to a moment.

    Deliberately carries **no** moment id and no replay offset. There is
    nothing to omit: the row has no moment, and a field that were present and
    null would invite a consumer to treat "meeting-scoped" as "citation not
    loaded yet" and go looking for one (AD-18).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    # `str`, not a `Literal`: migration 0022 says widening the kind CHECK is a
    # story, and enumerating today's kinds here would turn that migration into
    # a serialization failure. The kind's meaning to a client is the label it
    # renders, not a branch it takes on scope.
    kind: str
    state: ArtifactState
    title: str
    body: str
    created_at: datetime
    published_at: datetime | None = None
    publish_relative_path: str | None = None
    publish_commit_sha: str | None = None


class MeetingSummaryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    # Required-but-nullable: `null` says "this meeting has no summary", which
    # is an ordinary state — the extraction document carried no executive
    # summary, or extract has not run. An absent field would say nothing at
    # all, and a client could not tell the two apart from a client bug.
    summary: MeetingArtifact | None


class MeetingArtifactsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    artifacts: list[MeetingArtifact]


def _artifact(row: tuple) -> MeetingArtifact:
    return MeetingArtifact(
        id=row[0],
        kind=row[1],
        state=row[2],
        title=row[3],
        body=row[4],
        created_at=row[5],
        published_at=row[6],
        publish_relative_path=row[7],
        publish_commit_sha=row[8],
    )


@router.get(
    "/meetings/{meeting_id}/summary",
    operation_id="getMeetingSummary",
    response_model=MeetingSummaryResponse,
    responses=_READ_PROBLEM_RESPONSES,
)
def get_meeting_summary(meeting_id: UUID, request: Request) -> MeetingSummaryResponse:
    """The meeting's summary artifact, whatever its lifecycle state.

    Served regardless of `state`, drafts included, because this is a read of
    stored artifact state through the api's own Postgres read — the same door
    the moment view's right rail already opens onto unpublished artifacts
    (AD-4). It is not an answer and needs no citation to be shown.

    A meeting with no summary answers `200` with `summary: null` rather than
    `404`. "Not extracted yet", "the document carried no executive summary" and
    "no such meeting" are three different facts; the 404 is reserved for the
    third so a client never has to parse a message to tell them apart.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        # Header first (absence is the 404), then the viewability gate, then
        # the row — the split every meeting-scoped read uses, under REPEATABLE
        # READ so an extract rerun committing mid-read cannot be observed half
        # applied.
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if conn.execute(_MEETING_EXISTS, (meeting_id,)).fetchone() is None:
            raise Problem(404, "not-found", f"no meeting with id {meeting_id}")
        _require_viewable(conn, meeting_id)
        row = conn.execute(_MEETING_SUMMARY, (meeting_id,)).fetchone()
    return MeetingSummaryResponse(
        meeting_id=meeting_id, summary=_artifact(row) if row is not None else None
    )


@router.post(
    "/meetings/{meeting_id}/artifacts/approve",
    operation_id="approveMeetingArtifacts",
    response_model=MeetingArtifactsResponse,
    responses=_APPROVE_PROBLEM_RESPONSES,
)
def approve_meeting_artifacts(
    meeting_id: UUID, request: Request
) -> MeetingArtifactsResponse:
    """The meeting-scoped approval gesture — the per-moment one, other scope.

    One request advances every `extracted` meeting-scoped artifact of this
    meeting through both `approved` and `published`, through the same
    :func:`publish_extracted` the per-moment route calls: export to
    `MM_PUBLISH_ROOT` first, then the Postgres `UPDATE`, so a filesystem
    failure leaves every row `extracted` rather than half-published
    (AD-4/AD-5). A meeting-level artifact is not an exception to
    human-approved publishing (AD-6).

    The response re-reads the meeting's whole meeting-scoped set rather than
    only the rows this call published — story 4.3's rule, for its reason: a
    client that replaces its state with this response must not lose an artifact
    an earlier call published or a later rerun proposed.
    """
    pool = request.app.state.pool
    publish_root = request.app.state.publish_root
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if conn.execute(_MEETING_EXISTS, (meeting_id,)).fetchone() is None:
            raise Problem(404, "not-found", f"no meeting with id {meeting_id}")
        _require_viewable(conn, meeting_id)
        pending = conn.execute(
            _EXTRACTED_MEETING_SCOPED_FOR_UPDATE, (meeting_id,)
        ).fetchall()
        if not pending:
            raise Problem(
                409,
                "nothing-to-approve",
                f"meeting {meeting_id} has no extracted meeting-scoped"
                " artifacts to approve — either none were extracted yet, or"
                " every one is already approved or published",
            )
        publish_extracted(conn, publish_root, pending)
        refreshed = conn.execute(
            _MEETING_SCOPED_ARTIFACTS, (meeting_id,)
        ).fetchall()

    # After the transaction has committed, and never failing the gesture over a
    # store — the per-moment route's policy, for the same reason. The call is
    # made rather than skipped even though a meeting-scoped artifact has no
    # citable record to write: the decision about what is projectable belongs
    # to `projections`, which names its skip, and a route that quietly declined
    # to call it would be a second copy of that policy.
    published_ids = [row[0] for row in pending]
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
            meeting_id=meeting_id,
            artifact_ids=[str(artifact_id) for artifact_id in published_ids],
            error=f"{type(exc).__name__}: {exc}",
            recovery=f"rebuild --meeting {meeting_id}",
        )

    logs.log_event(
        "artifacts.meeting_scope_approved",
        meeting_id=meeting_id,
        published=len(published_ids),
        summaries=sum(1 for row in pending if row[1] == KIND_SUMMARY),
    )
    return MeetingArtifactsResponse(
        meeting_id=meeting_id, artifacts=[_artifact(row) for row in refreshed]
    )
