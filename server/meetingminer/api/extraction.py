"""The extraction surface: the prompts that go out, and the documents that came back.

``GET /extraction/prompts`` is the visible half of story 4.2 (epics AC1);
``GET /meetings/{meeting_id}/extraction-documents`` is story 12.1's — each
extraction run's retained document text beside the kind, model, prompt hash and
item count that describe it.

Both are reads. ``extraction_source`` is worker-owned (AD-5): this module
selects from it and writes nothing, and no route here makes a model call.

Serves the three extraction prompt templates exactly as
``llm.roles.extraction`` holds them in the running config (AD-10): no store,
no cache, no re-derivation. The worker's ``extract`` stage
(``pipeline/stages/extract.py``) reads the same
``request.app.state.config.settings.llm.roles.extraction`` binding at call
time, so this route can never show text the pipeline would not actually
send — a config edit is visible here the moment a fresh process reads it,
with no separate "publish" step.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.moments import _require_viewable
from meetingminer.api.problems import Problem, ProblemDetails

router = APIRouter()

# The same `D`/`A` item-ID-prefix mapping the parser uses
# (`pipeline/extraction.py`), spelled as the wire kinds `api/moments.py`
# already pins: the architecture summary yields `adr` artifacts, the action
# document `action-item` ones. The topics document (story 10.1) is served as
# `topic` — not an artifact kind, but the same singular wire spelling.
ExtractionPromptKind = Literal["adr", "action-item", "topic"]


class ExtractionPrompt(BaseModel):
    """One document kind's active, complete prompt text."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    kind: ExtractionPromptKind
    prompt_text: str


class ExtractionPromptsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    prompts: list[ExtractionPrompt]


@router.get(
    "/extraction/prompts",
    operation_id="getExtractionPrompts",
    response_model=ExtractionPromptsResponse,
)
def get_extraction_prompts(request: Request) -> ExtractionPromptsResponse:
    binding = request.app.state.config.settings.llm.roles.extraction
    return ExtractionPromptsResponse(
        prompts=[
            ExtractionPrompt(kind="adr", prompt_text=binding.arch_summary_prompt),
            ExtractionPrompt(
                kind="action-item", prompt_text=binding.action_items_prompt
            ),
            ExtractionPrompt(kind="topic", prompt_text=binding.topics_prompt),
        ]
    )


# --- story 12.1: the retained documents -------------------------------------

# Ordered by `kind` rather than by insertion: the four rows describe four
# documents of one run, not a sequence, so a stable alphabetical order is a
# contract a test can hold and a client can render without inventing a ranking
# the data does not carry.
_MEETING_DOCUMENTS = """
SELECT kind, origin, drop_relative_path, sha256, byte_size, layout,
       item_count, artifact_count, model, prompt_version, prompt_hash,
       document_text, created_at, updated_at
FROM extraction_source
WHERE meeting_id = %s
ORDER BY kind
"""

_MEETING_EXISTS = "SELECT id FROM meeting WHERE id = %s"

_DOCUMENTS_PROBLEM_RESPONSES = {
    422: {
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
        "description": "`not-found` — no meeting with that id.",
    },
    409: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`meeting-not-viewable` — the meeting exists but an"
        " evidence stage has not settled; the same gate every meeting-scoped"
        " read passes.",
    },
}


class ExtractionDocument(BaseModel):
    """One extraction run: what produced it, what it yielded, and its text."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # `str`, not a `Literal` of today's four kinds: migration 0010 says
    # widening the kind CHECK is a story, and a response model that enumerated
    # them would turn that migration into a serialization failure here.
    kind: str
    origin: str
    # NULL for a generated document, which is not a drop file.
    drop_relative_path: str | None = None
    sha256: str
    byte_size: int
    layout: str
    item_count: int
    artifact_count: int
    # NULL for an adopted document: it was written by the puller's summariser,
    # whose model and prompt this side never observed.
    model: str | None = None
    prompt_version: int | None = None
    prompt_hash: str | None = None
    # The markdown as the model emitted it (or as the drop carried it) — never
    # re-rendered, re-wrapped or trimmed, so a reader sees everything the
    # parser ignored as well as everything it used.
    #
    # `null` means one specific thing: this run completed before story 12.1
    # retained documents, so there is no text to serve and a re-extraction is
    # what produces one. It does NOT mean the document was empty — an empty
    # document is `""` with `byteSize` 0. Collapsing the two would be exactly
    # the silent degradation AD-18 forbids, so they are distinct on the wire
    # and every renderer must keep them distinct.
    document_text: str | None = None
    created_at: datetime
    updated_at: datetime


class MeetingExtractionDocumentsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    documents: list[ExtractionDocument]


@router.get(
    "/meetings/{meeting_id}/extraction-documents",
    operation_id="listMeetingExtractionDocuments",
    response_model=MeetingExtractionDocumentsResponse,
    responses=_DOCUMENTS_PROBLEM_RESPONSES,
)
def list_meeting_extraction_documents(
    meeting_id: UUID, request: Request
) -> MeetingExtractionDocumentsResponse:
    """Every extraction run of one meeting, with the document it read (story 12.1).

    The document a run produced is the evidence for the artifacts it yielded,
    and it is the only thing to read at all when a run yielded nothing — which
    is the case this endpoint exists for. It is served as the markdown it is:
    no rendering, no summarising, no parse of it substituted for it.

    A meeting with no extraction rows returns an empty list rather than a 404 —
    that is a meeting whose extract stage has not run, which is a state, not a
    missing resource. The 404 is reserved for a meeting id that names nothing.
    """
    pool = request.app.state.pool
    # Header first (absence is the 404), the gate second, the rows last — the
    # same split and the same reasoning as `listMeetingMoments`, under
    # REPEATABLE READ so all three come from one snapshot and an extract
    # rerun committing mid-read cannot serve one document from before it and
    # another from after.
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if conn.execute(_MEETING_EXISTS, (meeting_id,)).fetchone() is None:
            raise Problem(404, "not-found", f"no meeting with id {meeting_id}")
        _require_viewable(conn, meeting_id)
        rows = conn.execute(_MEETING_DOCUMENTS, (meeting_id,)).fetchall()

    documents = [
        ExtractionDocument(
            kind=row[0],
            origin=row[1],
            drop_relative_path=row[2],
            sha256=row[3],
            byte_size=row[4],
            layout=row[5],
            item_count=row[6],
            artifact_count=row[7],
            model=row[8],
            prompt_version=row[9],
            prompt_hash=row[10],
            document_text=row[11],
            created_at=row[12],
            updated_at=row[13],
        )
        for row in rows
    ]
    logs.log_event(
        "extraction.documents_listed",
        meeting_id=meeting_id,
        documents=len(documents),
        # Named, not merely counted: a corpus still carrying pre-12.1 rows is
        # a re-extraction backlog, and it must be visible in the log rather
        # than inferred from empty panels.
        unretained=[d.kind for d in documents if d.document_text is None],
    )
    return MeetingExtractionDocumentsResponse(
        meeting_id=meeting_id, documents=documents
    )
