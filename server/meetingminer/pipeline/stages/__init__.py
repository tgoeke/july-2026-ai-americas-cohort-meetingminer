"""The stage registry: stage name -> implementation.

An *unregistered* name is the pause signal, not an error and not a no-op: the
runner stops advancing the job, leaves the stage `queued` and the job
`running`, and logs a paused event. Nothing is ever marked `done` or `skipped`
on behalf of work that does not exist yet. With every name in ``STAGE_NAMES``
registered — `extract` landed with story 4.1 — a job that settles every stage
reaches `done`; the pause mechanism stays, waiting for whatever stage a later
epic appends.
"""

from __future__ import annotations

from typing import Callable, Mapping

from meetingminer.pipeline.stage import StageContext
from meetingminer.pipeline.stages import align as align_stage
from meetingminer.pipeline.stages import extract as extract_stage
from meetingminer.pipeline.stages import frames as frames_stage
from meetingminer.pipeline.stages import moments as moments_stage
from meetingminer.pipeline.stages import ocr as ocr_stage
from meetingminer.pipeline.stages import probe as probe_stage
from meetingminer.pipeline.stages import screens as screens_stage
from meetingminer.pipeline.stages import transcribe as transcribe_stage

StageFn = Callable[[StageContext], None]

STAGE_IMPLEMENTATIONS: Mapping[str, StageFn] = {
    "probe": probe_stage.run,
    "frames": frames_stage.run,
    "ocr": ocr_stage.run,
    "screens": screens_stage.run,
    "transcribe": transcribe_stage.run,
    "align": align_stage.run,
    "moments": moments_stage.run,
    "extract": extract_stage.run,
}


def stage_implementation(name: str) -> StageFn | None:
    """The implementation for ``name``, or ``None`` when it is not built yet."""
    return STAGE_IMPLEMENTATIONS.get(name)
