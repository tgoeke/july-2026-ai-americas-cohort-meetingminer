"""GET /extraction/prompts — the visible half of story 4.2 (epics AC1).

Serves the two extraction prompt templates exactly as
``llm.roles.extraction`` holds them in the running config (AD-10): no store,
no cache, no re-derivation. The worker's ``extract`` stage
(``pipeline/stages/extract.py``) reads the same
``request.app.state.config.settings.llm.roles.extraction`` binding at call
time, so this route can never show text the pipeline would not actually
send — a config edit is visible here the moment a fresh process reads it,
with no separate "publish" step.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

router = APIRouter()

# The same `D`/`A` item-ID-prefix mapping the parser uses
# (`pipeline/extraction.py`), spelled as the wire kinds `api/moments.py`
# already pins: the architecture summary yields `adr` artifacts, the action
# document `action-item` ones.
ExtractionPromptKind = Literal["adr", "action-item"]


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
        ]
    )
