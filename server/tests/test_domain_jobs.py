"""Truth table for ``domain.jobs.augmentation_in_flight`` (story 2.3).

Store-free on purpose: the predicate is a pure function over a stage-status
mapping, and the api test that consumes it (`test_api_moments.py`) only needs
to prove the wiring — the decision itself is pinned here, one snapshot per
shape the pipeline can actually produce.
"""

from __future__ import annotations

from meetingminer.domain.jobs import (
    AUGMENTATION_STAGES,
    PARTICIPANT_AUGMENTATION_STAGES,
    STAGE_NAMES,
    VIDEO_ONLY_STAGES,
    augmentation_in_flight,
)


def _snapshot(**overrides: str) -> dict[str, str]:
    """All stages ``done`` except the named overrides — the settled baseline."""
    statuses = {name: "done" for name in STAGE_NAMES}
    statuses.update(overrides)
    return statuses


def test_a_first_ingest_settling_in_order_is_not_augmenting() -> None:
    """Every prefix of an in-order first ingest reads as first ingest."""
    for boundary in range(len(STAGE_NAMES) + 1):
        statuses = {
            name: ("done" if index < boundary else "queued")
            for index, name in enumerate(STAGE_NAMES)
        }
        assert augmentation_in_flight(statuses) is False, statuses


def test_a_running_stage_mid_first_ingest_is_not_augmenting() -> None:
    assert augmentation_in_flight(_snapshot(moments="running", extract="queued")) is False


def test_a_transcript_only_first_ingest_with_its_skipped_prefix_is_not_augmenting() -> None:
    """The ``skipped`` video stages are an intake-time prefix, still in order."""
    statuses = {name: "skipped" for name in VIDEO_ONLY_STAGES}
    statuses.update({"align": "running", "moments": "queued", "extract": "queued"})
    assert augmentation_in_flight(statuses) is False


def test_a_recording_augmentation_snapshot_is_augmenting() -> None:
    """The re-queued video/align/moments stages sit beneath a settled extract."""
    statuses = _snapshot(**{name: "queued" for name in AUGMENTATION_STAGES})
    assert augmentation_in_flight(statuses) is True


def test_a_participant_augmentation_snapshot_is_augmenting() -> None:
    statuses = _snapshot(**{name: "queued" for name in PARTICIPANT_AUGMENTATION_STAGES})
    assert augmentation_in_flight(statuses) is True


def test_a_participant_augmentation_of_a_transcript_only_meeting_is_augmenting() -> None:
    """The video stages stay ``skipped`` — settled — while align/moments re-run."""
    statuses = {name: "skipped" for name in VIDEO_ONLY_STAGES}
    statuses.update({"align": "queued", "moments": "running", "extract": "done"})
    assert augmentation_in_flight(statuses) is True


def test_a_mid_augmentation_snapshot_with_some_stages_resettled_is_augmenting() -> None:
    """Halfway through the re-run the trailing evidence stages are still queued."""
    statuses = _snapshot(ocr="running", screens="queued", align="queued", moments="queued")
    assert augmentation_in_flight(statuses) is True


def test_an_all_settled_job_is_not_augmenting() -> None:
    assert augmentation_in_flight(_snapshot()) is False


def test_an_empty_mapping_is_not_augmenting() -> None:
    assert augmentation_in_flight({}) is False


def test_the_pre_41_unsettled_extract_blind_spot_reads_as_first_ingest() -> None:
    """A pre-4.1 job whose ``extract`` never settled offers no ordering signal
    once its evidence stages are re-queued — the predicate's documented blind
    spot, pinned as the conservative ``False``."""
    statuses = _snapshot(
        extract="queued", **{name: "queued" for name in PARTICIPANT_AUGMENTATION_STAGES}
    )
    assert augmentation_in_flight(statuses) is False


def test_a_partial_mapping_with_a_later_done_stage_reads_augmenting() -> None:
    """A stage missing from the mapping counts as unsettled — deliberate: the
    runner writes every stage row at claim time, so a partial mapping is
    already an anomaly, and a hole beneath a settled checkpoint is the
    out-of-order shape rather than something to paper over as settled."""
    assert augmentation_in_flight({"extract": "done"}) is True
    # A partial mapping whose only settled stage precedes the holes stays a
    # first ingest: nothing done follows the missing evidence.
    assert augmentation_in_flight({"probe": "done"}) is False
