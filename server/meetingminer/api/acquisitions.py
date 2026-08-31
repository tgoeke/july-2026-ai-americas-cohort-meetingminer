"""The acquisition surface: start one, check a URL first, poll one (story 6.4).

Three routes, and none of them does any acquisition work:

* ``POST /acquisitions`` classifies the URL offline, claims its source id, and
  starts :mod:`meetingminer.acquisitions` as a detached host process. It
  answers 202 — accepted, not done. The request handler invokes no ``yt-dlp``
  and mints nothing (AD-11), and the child it starts reaches intake only
  through ``POST /ingests`` (AD-14).
* ``POST /acquisitions/probe`` runs story 6.2's URL, tool, availability,
  stream and duration checks and stops there: no media bytes, no drop, no
  process, no status file.
* ``GET /acquisitions/{acquisitionId}`` reads the status file the child
  writes, resolves the meeting id from Postgres by job id, and appends a
  bounded log tail.

**Refusals are fields, never prose.** Every refusal — from either the probe or
a finished acquisition — carries story 6.2a's ``rule`` token, the tool's own
``detail``, and a ``remediation``. The web client never parses the log tail to
learn why something failed. The rule → HTTP status and rule → remediation
tables live in :mod:`meetingminer.acquisitions`, keyed on that one closed
vocabulary.

Registration is auto-discovery (story 2.8): this file declares no
``ROUTER_ORDER``, so it sorts at ``DEFAULT_ROUTER_ORDER`` and — being first by
name among the default-order modules — registers right after ``media``.
``/acquisitions/probe`` is declared **before** ``/acquisitions/{id}`` inside
this router, which is ``registry.py``'s documented rule for a literal path
under a parameterized sibling.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import acquisitions, uploads, youtube
from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.api.uploads import (
    refusal_problem as upload_refusal_problem,
    state_problem as upload_state_problem,
)
from meetingminer.config import AppConfig, ConfigError
from meetingminer.transcripts import dialects

router = APIRouter()

#: Titles for the three statuses a refusal maps to. `problems.Problem` knows
#: the first two; 503 is this module's own, and an untitled problem body would
#: be the one place the api says "Error".
_REFUSAL_TITLES = {
    400: "Bad Request",
    409: "Conflict",
    422: "Unprocessable Content",
    503: "Service Unavailable",
}

#: `meeting.job_id` is NOT NULL UNIQUE (migration 0002), so this is the whole
#: meeting-id resolution: at most one row, and no ordering to think about.
#: Deliberately not stored in the status file — the worker creates the meeting
#: row after intake, so a later poll is what makes the id appear.
_MEETING_FOR_JOB = "SELECT id FROM meeting WHERE job_id = %s"

_PROBLEM_RESPONSE = {"model": ProblemDetails, "content": {"application/problem+json": {}}}


class AcquisitionRequest(BaseModel):
    """One source, named exactly one way.

    ``url`` for a published video, ``uploadSessionId`` for files already handed
    to ``POST /uploads``. Both, or neither, is a refusal rather than a
    precedence rule: a client that sent both does not know which one it meant,
    and guessing would acquire the wrong meeting.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    url: str | None = None
    upload_session_id: UUID | None = None


class ProbeRequest(BaseModel):
    """``POST /acquisitions/probe`` takes a URL and only a URL."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    url: str


class AcquisitionAccepted(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    acquisition_id: UUID
    #: For an upload this is ``upload:<sessionId>`` until the drop is minted;
    #: the content-derived id appears on ``GET`` once the status is ``posted``.
    source_id: str
    status: str
    #: Which source this acquisition was started from — ``youtube`` or ``upload``.
    kind: str


class ProbeCaptions(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    kind: str
    language: str


class ProbeResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    title: str
    duration_ms: int
    #: ``None`` when the video publishes no English track. Not a refusal: a
    #: recording-only drop is valid, and the UI says so before submit.
    captions: ProbeCaptions | None
    source_id: str


class AcquisitionRefusal(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    rule: str
    detail: str
    remediation: str


class AcquisitionSource(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_id: str
    tool: str | None = None
    tool_version: str | None = None


class AcquisitionStatus(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    acquisition_id: UUID
    source_id: str
    #: A watch URL for a YouTube acquisition; ``upload:<sessionId>`` for an
    #: upload, which has no page. Read ``kind`` before rendering it as a link.
    url: str
    status: str
    #: One of ``youtube`` / ``upload``.
    kind: str
    #: Present exactly when ``kind`` is ``upload``. The session is gone by the
    #: time the status is terminal — it is removed as soon as the drop is
    #: finalized or the acquisition fails — so this identifies it, it does not
    #: locate it.
    upload_session_id: UUID | None = None
    created_at: str
    updated_at: str
    #: ``created`` or ``exists``, on ``posted`` only.
    result: str | None = None
    job_id: UUID | None = None
    #: Resolved per read from ``meeting.job_id``; ``None`` until the worker
    #: has claimed the job and minted the meeting row.
    meeting_id: UUID | None = None
    source: AcquisitionSource | None = None
    #: Present exactly when ``status`` is ``failed``, and complete on its own:
    #: nothing here is read from the log.
    refusal: AcquisitionRefusal | None = None
    #: Diagnostic only, bounded by bytes and by lines. Always present — an
    #: empty list is "nothing logged yet", which is a different statement from
    #: a missing field, and the failure fields never depend on it.
    log_tail: list[str]


def _config(request: Request) -> AppConfig:
    """The api process's config, reached through app state.

    Never by importing ``api.main`` — that is circular — and answered as a 500
    rather than assumed, the way ``ingests.drops_root`` answers an unusable
    drops root: the alternative is anchoring ``.logs/`` on nothing.
    """
    config = getattr(request.app.state, "config", None)
    if not isinstance(config, AppConfig):
        raise Problem(
            500,
            "config-unavailable",
            "the api process has no loaded configuration, so acquisition state"
            " cannot be anchored; restart the api",
        )
    return config


def _refusal_problem(error: Exception) -> Problem:
    """One refusal, as RFC 9457 with ``rule`` and ``remediation`` extensions.

    The status comes from :data:`acquisitions.PROBLEM_STATUS`, keyed on story
    6.2a's rule — three buckets over one vocabulary, never a second one.
    ``rule`` and ``remediation`` ride as extension members because RFC 9457's
    four members are reserved (``problems.problem_response`` enforces that).
    """
    refusal = acquisitions.refusal_for(error)
    status = acquisitions.problem_status(refusal.rule)
    return Problem(
        status,
        "acquisition-refused",
        refusal.detail,
        title=_REFUSAL_TITLES.get(status),
        rule=refusal.rule,
        remediation=refusal.remediation,
    )


@router.post(
    "/acquisitions",
    operation_id="startAcquisition",
    status_code=202,
    response_model=AcquisitionAccepted,
    responses={
        400: _PROBLEM_RESPONSE,
        409: _PROBLEM_RESPONSE,
        422: _PROBLEM_RESPONSE,
        500: _PROBLEM_RESPONSE,
        503: _PROBLEM_RESPONSE,
    },
)
def start_acquisition(
    body: AcquisitionRequest, request: Request
) -> AcquisitionAccepted:
    config = _config(request)
    if body.url is not None and body.upload_session_id is not None:
        rule = "acquisition-source-ambiguous"
        raise Problem(
            400,
            "acquisition-source-ambiguous",
            "name either url or uploadSessionId, not both — an acquisition has"
            " one source, and this server will not choose which one you meant",
            rule=rule,
            remediation=uploads.REMEDIATIONS[rule],
        )
    if body.url is None and body.upload_session_id is None:
        rule = "acquisition-source-missing"
        raise Problem(
            400,
            "acquisition-source-missing",
            "name a source: url for a published video, or uploadSessionId for"
            " files already sent to POST /uploads",
            rule=rule,
            remediation=uploads.REMEDIATIONS[rule],
        )
    try:
        if body.upload_session_id is not None:
            record = acquisitions.launch_upload(config, str(body.upload_session_id))
        else:
            record = acquisitions.launch(config, body.url or "")
    except uploads.UploadSessionNotFound as exc:
        rule = "upload-session-not-found"
        raise Problem(
            uploads.PROBLEM_STATUS[rule],
            "upload-refused",
            f"no upload session with id {body.upload_session_id}",
            rule=rule,
            remediation=uploads.REMEDIATIONS[rule],
        ) from exc
    except uploads.UploadRefused as exc:
        raise upload_refusal_problem(exc) from exc
    except uploads.UploadStateError as exc:
        raise _refusal_problem(exc) from exc
    except dialects.DialectError as exc:
        raise _refusal_problem(exc) from exc
    except youtube.YoutubeError as exc:
        raise _refusal_problem(exc) from exc
    except acquisitions.AcquisitionInProgress as exc:
        rule = "acquisition-in-progress"
        remediation = (
            uploads.REMEDIATIONS[rule]
            if exc.record.kind == acquisitions.KIND_UPLOAD
            else acquisitions.YOUTUBE_IN_PROGRESS_REMEDIATION
        )
        raise Problem(
            409,
            "acquisition-in-progress",
            f"acquisition {exc.record.acquisition_id} is already"
            f" {exc.record.status} for {exc.record.source_id}; poll it rather"
            " than starting a second one",
            rule=rule,
            remediation=remediation,
            acquisitionId=exc.record.acquisition_id,
            sourceId=exc.record.source_id,
        ) from exc
    except acquisitions.AcquisitionStateError as exc:
        if body.upload_session_id is not None:
            raise upload_state_problem(
                exc, rule="acquisition-state-unwritable"
            ) from exc
        raise Problem(500, "acquisition-state-unwritable", str(exc)) from exc
    return AcquisitionAccepted(
        acquisition_id=UUID(record.acquisition_id),
        source_id=record.source_id,
        status=record.status,
        kind=record.kind,
    )


# Declared BEFORE `/acquisitions/{acquisition_id}`: a literal path under a
# parameterized sibling must register first, or the parameterized route
# swallows it (registry.py's documented rule, and `media.py`'s pattern).
@router.post(
    "/acquisitions/probe",
    operation_id="probeAcquisition",
    response_model=ProbeResult,
    responses={
        400: _PROBLEM_RESPONSE,
        422: _PROBLEM_RESPONSE,
        500: _PROBLEM_RESPONSE,
        503: _PROBLEM_RESPONSE,
    },
)
def probe_acquisition(body: ProbeRequest, request: Request) -> ProbeResult:
    config = _config(request)
    try:
        report = youtube.probe_only(
            body.url,
            max_duration_minutes=(
                config.settings.acquisition.youtube.max_duration_minutes
            ),
        )
    except (youtube.YoutubeError, ConfigError) as exc:
        raise _refusal_problem(exc) from exc
    captions = None
    if report.captions is not None:
        language, kind = report.captions
        captions = ProbeCaptions(kind=kind, language=language)
    return ProbeResult(
        title=report.title,
        duration_ms=report.duration_ms,
        captions=captions,
        source_id=report.source_id,
    )


@router.get(
    "/acquisitions/{acquisition_id}",
    operation_id="getAcquisition",
    response_model=AcquisitionStatus,
    description=(
        "One acquisition's state — "
        + " | ".join(acquisitions.STATUSES)
        + " — read from the status file its detached runner writes."
    ),
    responses={
        404: _PROBLEM_RESPONSE,
        422: _PROBLEM_RESPONSE,
        500: _PROBLEM_RESPONSE,
    },
)
def get_acquisition(acquisition_id: UUID, request: Request) -> AcquisitionStatus:
    # A `UUID` path parameter, not a string: every segment that becomes a
    # filename is typed, so no request can name a file. A malformed id is a
    # 422 from path validation and nothing is read.
    config = _config(request)
    root = acquisitions.acquisitions_root(config)
    try:
        record = acquisitions.read_record(root, str(acquisition_id))
    except acquisitions.AcquisitionNotFound as exc:
        raise Problem(
            404, "not-found", f"no acquisition with id {acquisition_id}"
        ) from exc
    except acquisitions.AcquisitionStateError as exc:
        raise Problem(500, "acquisition-state-unreadable", str(exc)) from exc

    job_id: UUID | None = None
    if record.job_id:
        try:
            job_id = UUID(record.job_id)
        except ValueError:
            # A job id the api cannot parse is reported as absent rather than
            # 500'd: the acquisition's own state is still worth showing.
            job_id = None

    meeting_id: UUID | None = None
    if job_id is not None:
        with request.app.state.pool.connection() as conn:
            row = conn.execute(_MEETING_FOR_JOB, (job_id,)).fetchone()
        meeting_id = row[0] if row else None

    source = None
    if record.status == "posted":
        source = AcquisitionSource(
            source_id=record.source_id,
            tool=record.tool,
            tool_version=record.tool_version,
        )
    refusal = None
    if record.refusal is not None:
        refusal = AcquisitionRefusal(
            rule=record.refusal.rule,
            detail=record.refusal.detail,
            remediation=record.refusal.remediation,
        )

    upload_session_id: UUID | None = None
    if record.upload_session_id:
        try:
            upload_session_id = UUID(record.upload_session_id)
        except ValueError:
            # Reported as absent rather than 500'd, for the same reason a
            # malformed job id is: the acquisition's own state is still worth
            # showing.
            upload_session_id = None

    return AcquisitionStatus(
        # The validated path parameter, never the id inside the file: the log
        # path is built from it, and only a typed UUID may reach a filename.
        acquisition_id=acquisition_id,
        source_id=record.source_id,
        url=record.url,
        status=record.status,
        kind=record.kind,
        upload_session_id=upload_session_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        result=record.result,
        job_id=job_id,
        meeting_id=meeting_id,
        source=source,
        refusal=refusal,
        log_tail=acquisitions.log_tail(
            acquisitions.log_path(root, str(acquisition_id))
        ),
    )
