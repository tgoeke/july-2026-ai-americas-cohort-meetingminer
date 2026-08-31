"""The upload surface: hand the api files it can later mint a drop from (story 6.4a).

Three routes, and none of them touches the pipeline:

* ``POST /uploads`` streams one multipart session into its own staging
  directory under ``MM_DROPS_ROOT/.staging/uploads/`` and answers 201. It mints
  nothing, converts nothing and ingests nothing — the session is inert bytes
  plus a declaration until ``POST /acquisitions`` names it.
* ``GET /uploads/{uploadSessionId}`` reports what a session holds, so a client
  that lost the create response can still find its own upload before it expires.
* ``DELETE /uploads/{uploadSessionId}`` discards one. A person who changed their
  mind should not have to wait for the TTL to get their bytes off the evidence
  volume.

**Refusals are fields, never prose**, exactly as ``api/acquisitions.py``
reports them: every refusal is RFC 9457 with :mod:`meetingminer.uploads`'s
``rule`` token, the refusal's own ``detail``, and a ``remediation`` (AD-18).
The rule → status and rule → remediation tables live in that module, keyed on
one closed vocabulary.

**Why the request stream and not ``UploadFile``.** FastAPI would spool every
part through ``TMPDIR`` on the boot volume before this handler ran, and only
then could the bytes be copied to the evidence volume — two writes of a
multi-gigabyte recording, and a size cap checked after the fact.
:func:`meetingminer.uploads.create_session` reads ``request.stream()`` directly,
so each part is written once and the cap refuses mid-transfer.

Registration is auto-discovery (story 2.8): no ``ROUTER_ORDER``, because
``/uploads`` has no literal sibling under its parameterized route.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import acquisitions, uploads
from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.config import AppConfig

#: Spelled once, so the declared schema and the check cannot disagree.
UPLOAD_CORPUS_VALUE = uploads.UPLOAD_CORPUS

router = APIRouter()

#: Titles for the statuses an upload refusal maps to. `problems.Problem` knows
#: 400, 404 and 422; the other three are this module's own, and an untitled
#: problem body would be the one place the api says "Error".
_REFUSAL_TITLES = {
    400: "Bad Request",
    404: "Not Found",
    413: "Content Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Content",
    503: "Service Unavailable",
}

_PROBLEM_RESPONSE = {"model": ProblemDetails, "content": {"application/problem+json": {}}}

#: The request body, declared rather than derived. The handler takes the raw
#: `Request` so it can stream the parts itself, which means FastAPI has no
#: parameter model to generate a schema from — and a generated client with no
#: body type is one story 6.5a would have to hand-write around. `openapi_extra`
#: puts the shape back in the document without giving the parser the body.
#: It is the same contract the module enforces: three required fields, an
#: optional dialect and supplier, and the files themselves.
_MULTIPART_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "title": "UploadSessionRequest",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The meeting's human label, shown in the app.",
                        },
                        "startedAt": {
                            "type": "string",
                            "description": (
                                "When the meeting started: RFC 3339 with an"
                                " offset (2026-08-05T12:00:19Z). A date alone is"
                                " refused — an upload never records day precision."
                            ),
                        },
                        "corpus": {
                            "type": "string",
                            "enum": [UPLOAD_CORPUS_VALUE],
                            "description": (
                                "Always 'real'. Scripted meetings are eval"
                                " subjects and are minted on the api host."
                            ),
                        },
                        "transcriptDialect": {
                            "type": "string",
                            "enum": list(uploads.dialects.DIALECTS),
                            "description": (
                                "Which export the transcript is. Required"
                                " whenever a .vtt is attached; declared, never"
                                " detected."
                            ),
                        },
                        "suppliedBy": {
                            "type": "string",
                            "description": "Who supplied the files, recorded in provenance.",
                        },
                        "files": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "description": (
                                "The recording and/or transcript. The role is"
                                " decided by the file extension: .mp4 becomes"
                                " recording.mp4, .vtt transcript.vtt, .txt"
                                " transcript.txt."
                            ),
                        },
                    },
                    "required": ["title", "startedAt", "corpus", "files"],
                }
            }
        },
    }
}


class UploadedFileView(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    #: The drop filename these bytes will become — decided by the uploaded
    #: file's extension, the same rule `mint-drop` applies to an operator's argv.
    canonical: str
    #: What the client called it. The only record of the user's own filename:
    #: the staged copy is named for its role and the drop's provenance describes
    #: the bytes, not the browser's path.
    original_filename: str
    sha256: str
    byte_size: int


class UploadSessionView(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    upload_session_id: UUID
    title: str
    #: Full ISO 8601 UTC at second precision — what the drop will carry. An
    #: upload never records day precision.
    started_at: str
    corpus: str
    transcript_dialect: str
    supplied_by: str
    created_at: str
    #: When an unclaimed session is swept. Not a promise that it survives until
    #: then: `DELETE` and a successful acquisition both remove it earlier.
    expires_at: str
    files: list[UploadedFileView]


def _config(request: Request) -> AppConfig:
    """The api process's config, reached through app state.

    Never by importing ``api.main`` — that is circular — and answered as a 500
    rather than assumed, the way ``api/acquisitions.py`` does it: the
    alternative is anchoring the staging area on nothing.
    """
    config = getattr(request.app.state, "config", None)
    if not isinstance(config, AppConfig):
        raise Problem(
            500,
            "config-unavailable",
            "the api process has no loaded configuration, so an upload cannot be"
            " staged; restart the api",
        )
    return config


def refusal_problem(error: uploads.UploadRefused) -> Problem:
    """One refusal, as RFC 9457 with ``rule`` and ``remediation`` extensions.

    ``rule`` and ``remediation`` ride as extension members because RFC 9457's
    four members are reserved (``problems.problem_response`` enforces that).
    """
    status = uploads.PROBLEM_STATUS[error.rule]
    return Problem(
        status,
        "upload-refused",
        " ".join(str(error).split()),
        title=_REFUSAL_TITLES.get(status),
        rule=error.rule,
        remediation=uploads.REMEDIATIONS[error.rule],
    )


def _view(session: uploads.UploadSession) -> UploadSessionView:
    return UploadSessionView(
        upload_session_id=UUID(session.session_id),
        title=session.title,
        started_at=session.started_at,
        corpus=session.corpus,
        transcript_dialect=session.transcript_dialect,
        supplied_by=session.supplied_by,
        created_at=session.created_at,
        expires_at=session.expires_at,
        files=[
            UploadedFileView(
                canonical=staged.canonical,
                original_filename=staged.original_filename,
                sha256=staged.sha256,
                byte_size=staged.byte_size,
            )
            for staged in session.files
        ],
    )


def _root(request: Request) -> tuple[AppConfig, uploads.UploadLimits, Path]:
    config = _config(request)
    return config, uploads.UploadLimits.from_config(config), uploads.sessions_root(config)


@router.post(
    "/uploads",
    operation_id="createUploadSession",
    status_code=201,
    response_model=UploadSessionView,
    description=(
        "Receive one multipart/form-data session: the text fields "
        + ", ".join(sorted(uploads.TEXT_FIELDS))
        + ", plus a recording and/or a transcript, whose roles are decided by"
        " their file extensions (.mp4, .vtt, .txt). Nothing is minted or"
        " ingested here."
    ),
    responses={
        400: _PROBLEM_RESPONSE,
        413: _PROBLEM_RESPONSE,
        415: _PROBLEM_RESPONSE,
        422: _PROBLEM_RESPONSE,
        500: _PROBLEM_RESPONSE,
        503: _PROBLEM_RESPONSE,
    },
    openapi_extra=_MULTIPART_BODY,
)
async def create_upload_session(request: Request) -> UploadSessionView:
    try:
        config, limits, root = _root(request)
    except uploads.UploadRefused as exc:
        raise refusal_problem(exc) from exc

    # Cheap, bounded, and the only thing that reclaims an abandoned session's
    # bytes: story 6.4's spec recorded that nothing reaped staged state.
    state_root = acquisitions.acquisitions_root(config)
    with acquisitions.claim_lock(state_root):
        uploads.sweep_expired(
            root,
            limits,
            now=datetime.now(timezone.utc),
            protected_session_ids=acquisitions.live_upload_sessions(state_root),
        )

    declared = request.headers.get("content-length")
    try:
        content_length = int(declared) if declared is not None else None
    except ValueError:
        content_length = None

    try:
        session = await uploads.create_session(
            root=root,
            content_type=request.headers.get("content-type"),
            content_length=content_length,
            body=request.stream(),
            limits=limits,
            # The TTL starts when a complete session is published, not before a
            # slow request begins streaming.
            now=lambda: datetime.now(timezone.utc),
        )
    except uploads.UploadRefused as exc:
        raise refusal_problem(exc) from exc
    except uploads.UploadStateError as exc:
        raise Problem(500, "upload-state-unwritable", str(exc)) from exc
    return _view(session)


@router.get(
    "/uploads/{upload_session_id}",
    operation_id="getUploadSession",
    response_model=UploadSessionView,
    responses={
        404: _PROBLEM_RESPONSE,
        422: _PROBLEM_RESPONSE,
        500: _PROBLEM_RESPONSE,
        503: _PROBLEM_RESPONSE,
    },
)
def get_upload_session(upload_session_id: UUID, request: Request) -> UploadSessionView:
    # A `UUID` path parameter, not a string: every segment that becomes a
    # directory name is typed, so no request can name a path. A malformed id is
    # a 422 from path validation and nothing is read.
    try:
        _, _, root = _root(request)
        session = uploads.read_session(root, str(upload_session_id))
    except uploads.UploadSessionNotFound as exc:
        raise _not_found(upload_session_id) from exc
    except uploads.UploadRefused as exc:
        raise refusal_problem(exc) from exc
    except uploads.UploadStateError as exc:
        raise Problem(500, "upload-state-unreadable", str(exc)) from exc
    return _view(session)


@router.delete(
    "/uploads/{upload_session_id}",
    operation_id="deleteUploadSession",
    status_code=204,
    description=(
        "Discard one upload session and its staged bytes. Idempotent in effect"
        " but not in status: a session that is already gone answers 404, because"
        " a client that thinks it deleted something it never had is a client"
        " with a bug."
    ),
    responses={
        404: _PROBLEM_RESPONSE,
        409: _PROBLEM_RESPONSE,
        422: _PROBLEM_RESPONSE,
        500: _PROBLEM_RESPONSE,
        503: _PROBLEM_RESPONSE,
    },
)
def delete_upload_session(upload_session_id: UUID, request: Request) -> Response:
    try:
        config, _, root = _root(request)
        state_root = acquisitions.acquisitions_root(config)
        with acquisitions.claim_lock(state_root):
            live = acquisitions.live_upload_sessions(state_root).get(
                str(upload_session_id)
            )
            if live is not None:
                rule = "acquisition-in-progress"
                raise Problem(
                    uploads.PROBLEM_STATUS[rule],
                    "acquisition-in-progress",
                    f"acquisition {live.acquisition_id} is already"
                    f" {live.status} for upload session {upload_session_id}",
                    rule=rule,
                    remediation=uploads.REMEDIATIONS[rule],
                    acquisitionId=live.acquisition_id,
                    sourceId=live.source_id,
                )
            removed = uploads.discard_session(root, str(upload_session_id))
    except uploads.UploadRefused as exc:
        raise refusal_problem(exc) from exc
    except uploads.UploadStateError as exc:
        raise Problem(500, "upload-state-unreadable", str(exc)) from exc
    if not removed:
        raise _not_found(upload_session_id)
    return Response(status_code=204)


def _not_found(upload_session_id: UUID) -> Problem:
    """The one 404 this router raises, carrying the same three fields.

    A missing session is a refusal like any other — expired, discarded, or
    already turned into a drop — so a client renders it with the same code path
    it renders every other one.
    """
    rule = "upload-session-not-found"
    return Problem(
        uploads.PROBLEM_STATUS[rule],
        "upload-refused",
        f"no upload session with id {upload_session_id}",
        title=_REFUSAL_TITLES[404],
        rule=rule,
        remediation=uploads.REMEDIATIONS[rule],
    )
