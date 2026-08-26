"""Job-domain vocabulary shared by api and worker.

Lives in ``domain`` because both the api (which never imports ``pipeline``)
and the worker need the canonical stage list; ``domain`` depends on nothing
above it.
"""

from __future__ import annotations

from collections.abc import Mapping

# Ingest pipeline stages in execution order (architecture spine, AD-11).
STAGE_NAMES: tuple[str, ...] = (
    "probe",
    "frames",
    "ocr",
    "screens",
    "transcribe",
    "align",
    "moments",
    "extract",
)

# Stages that only make sense when the drop carries a recording (AD-1).
# A transcript-only drop records exactly these as ``skipped`` and proceeds to
# ``align``; ``moments`` then falls back to transcript segmentation.
VIDEO_ONLY_STAGES: frozenset[str] = frozenset(
    {"probe", "frames", "ocr", "screens", "transcribe"}
)

# The stages an augmenting drop re-runs when a recording is recovered after the
# occurrence was already ingested transcript-only (story 1.12, FR32). Exactly
# the video stages that ingest recorded as ``skipped``, plus:
#
# * ``align`` — the STT verification lane exists only once ``transcribe`` has
#   run, so the merged transcript has to be re-derived against it (AD-13);
# * ``moments`` — the acceptance criterion. `moments` is the stage that attaches
#   the screenshot to a moment and, by the same upsert, clears the transitional
#   deep link (UX-DR11, `pipeline/stages/moments.py`), which is what turns a
#   moment into a true replay target. A ``done`` checkpoint here would leave the
#   recovered recording invisible to every moment in the meeting.
#
# ``extract`` is deliberately outside the set: it reads the transcript rather
# than the video, it produces artifacts rather than evidence, and its output
# carries human approval (`approved`/`published` artifact rows) that an intake
# behavior must never silently re-propose. Re-extraction after augmentation is
# a deliberate manual re-queue, not something a drop triggers.
#
# Derived in ``STAGE_NAMES`` order so the re-armed job walks them in pipeline
# order. Intake is the only consumer: ``api/ingests.py`` is what puts exactly
# these stages back to ``queued``. The worker never imports this list — it walks
# ``STAGE_NAMES`` and skips whatever is already settled, so it re-runs precisely
# what intake re-queued. It lives in ``domain`` so the api can import it without
# reaching into ``pipeline``.
AUGMENTATION_STAGES: tuple[str, ...] = tuple(
    name
    for name in STAGE_NAMES
    if name in VIDEO_ONLY_STAGES or name in {"align", "moments"}
)

# The stages an augmenting drop re-runs when it adds no recording — a drop that
# brings the occurrence's participant graph to a meeting whose drop carried none
# (story 1.13), or any later evidence that is metadata rather than media.
#
# ``align`` is the stage that reads ``metadata.participants``: it builds the
# roster from the graph, resolves each entry through ``participant_alias``
# (AD-5) and writes ``meeting_participant``. ``moments`` follows because a
# moment's speaker attribution comes from the aligned transcript, so a ``done``
# checkpoint there would leave moments describing the roster the meeting had
# before the graph arrived.
#
# The video stages are deliberately outside the set: the recording is unchanged
# (or absent), so re-running ``frames``/``ocr``/``screens`` over it would
# re-derive identical evidence at real cost. Intake chooses between this tuple
# and ``AUGMENTATION_STAGES`` on exactly one question — does this drop bring a
# recording the meeting did not have?
PARTICIPANT_AUGMENTATION_STAGES: tuple[str, ...] = tuple(
    name for name in STAGE_NAMES if name in {"align", "moments"}
)

# Stages whose completion means the evidence bundle is built: everything up to
# and including ``moments``. ``extract`` is deliberately outside — it produces
# artifacts (Epic 4), not evidence, and AD-4 projects evidence at
# ingest-complete while artifacts project only on publish. A meeting is "safe
# to open" the moment its evidence settles, whatever the extraction stage is
# still doing (or however a pre-4.1 job was left paused there).
EVIDENCE_STAGES: tuple[str, ...] = STAGE_NAMES[: STAGE_NAMES.index("moments") + 1]

# The exact ``job.error`` the runner writes when it claims a job whose
# ``drop_relative_path`` is still NULL — a row the story 2.1a backfill has not
# reached (pipeline/runner.py).
#
# It lives here, as a constant, because two components have to agree on it
# *character for character*: the runner writes it, and the backfill matches on
# it to re-queue exactly the jobs it just repaired. Matching on ``status =
# 'failed'`` instead would resurrect unrelated failures — a job that failed
# because ffprobe rejected its recording must stay failed — so the match is
# equality against this string and nothing looser. Editing it in one place and
# not the other silently strands every affected job in ``failed``.
UNBACKFILLED_DROP_PATH_ERROR = (
    "job has no drops-root-relative path — it predates story 2.1a; run"
    " 'make backfill-drop-paths' to convert it, which also re-queues this job"
)


def augmentation_in_flight(stage_statuses: Mapping[str, str]) -> bool:
    """True when an augmentation — not a first ingest — is rebuilding evidence.

    The signal is out-of-order settlement: some stage with status ``done``
    follows, in ``STAGE_NAMES`` order, an earlier evidence stage that is not
    settled (``done``/``skipped``). That is sound because a first ingest
    settles stages strictly in pipeline order (a transcript-only drop's
    ``skipped`` video stages are an intake-time prefix, still in order), so a
    first ingest never has a ``done`` checkpoint after an unsettled evidence
    stage. Both augmentation tuples (``AUGMENTATION_STAGES``,
    ``PARTICIPANT_AUGMENTATION_STAGES``) deliberately exclude ``extract``, so
    an augmenting job always re-queues evidence stages beneath a settled
    ``extract`` — exactly the out-of-order shape a first ingest cannot reach.

    Known blind spot: a pre-4.1 job whose ``extract`` never settled leaves no
    ``done`` stage after the re-queued evidence stages, so an augmentation of
    it reads as ``False`` — "first ingest" is the honest conservative answer
    when the ordering signal is absent.

    A stage *missing* from the mapping counts as unsettled — deliberate. The
    runner inserts every stage row at claim time, so a partial mapping is
    already an anomaly; if one nonetheless carries a later ``done`` stage,
    that hole before a settled checkpoint is exactly the out-of-order shape,
    and inventing "settled" for evidence that is not there would hide it.
    """
    unsettled_evidence_seen = False
    for name in STAGE_NAMES:
        status = stage_statuses.get(name)
        if unsettled_evidence_seen and status == "done":
            return True
        if name in EVIDENCE_STAGES and status not in {"done", "skipped"}:
            unsettled_evidence_seen = True
    return False


def evidence_complete(stage_statuses: Mapping[str, str]) -> bool:
    """True when every evidence stage has settled (``done`` or ``skipped``).

    One definition of "safe to open", shared by the api's meetings list and the
    projection trigger. ``skipped`` counts as settled because that is exactly
    what a transcript-only drop records for its video stages (AD-1) — such a
    meeting is complete, not degraded.
    """
    return all(stage_statuses.get(name) in {"done", "skipped"} for name in EVIDENCE_STAGES)
