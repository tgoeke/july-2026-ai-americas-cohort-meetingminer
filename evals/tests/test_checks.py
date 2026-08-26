"""The four check algorithms over synthetic captures — no store, no api.

This is where every row of story 5.2's edge-case matrix that does not need a
live corpus is pinned. The algorithms are pure functions over
:class:`Capture` records precisely so this file can exist: a threshold that
only a Docker stack could exercise is a threshold nobody re-checks.

Both named constants are tested at their boundary rather than near it. They
are provisional (eval-design §6) and expected to be recalibrated, so the tests
say what the number *does* — matches at exactly the threshold, misses just
below — instead of restating the number.
"""

from __future__ import annotations

from typing import Any

import pytest

from evals.harness import checks
from evals.harness.checks import (
    ANCHOR_MATCH_THRESHOLD,
    DEDUP_SIMILARITY_THRESHOLD,
    TOKEN_SIMILARITY_THRESHOLD,
    Capture,
    capture_recall,
    dedup_candidates,
    duration_agreement,
    not_applicable,
    ocr_defects,
    over_capture,
    token_containment,
    view_classification,
)
from evals.harness.groundtruth import Manifest
from evals.tests.conftest import meeting_of, valid_slide_deck, valid_ui_demo

# The shipped ui-demo builder: 2 screens + 2 participant segments = 4 expected
# captures, 12 minutes long.
SC1 = "Order Search Results"
SC2 = "Line Items and Tax Breakdown"


def manifest_of(**overrides: Any) -> Manifest:
    return Manifest(data=valid_ui_demo(**overrides))


def capture(
    ordinal: int,
    text: str | None = "",
    view_type: str = "ui-screen",
    *,
    frame: bool = True,
) -> Capture:
    """One capture. ``text=None`` is a capture with no OCR text at all."""
    return Capture(
        ordinal=ordinal,
        view_type=view_type,
        ocr_text=text,
        has_representative_frame=frame,
    )


def covering_captures() -> tuple[Capture, ...]:
    """Captures answering for every entry of the ui-demo manifest."""
    return (
        capture(1, "", "participant-gallery"),
        capture(2, f"Orders  {SC1}  page 1 of 4"),
        capture(3, f"{SC2} subtotal 41.20"),
        capture(4, "", "participant-gallery"),
    )


# --------------------------------------------------------------------------
# token_containment — the fuzzy comparison behind "token-set match >= 0.8"
# --------------------------------------------------------------------------


def test_an_anchor_present_verbatim_scores_one() -> None:
    assert token_containment(SC1, f"Orders {SC1} page 1 of 4") == 1.0


def test_containment_folds_both_sides_the_way_anchors_are_folded() -> None:
    """Case, punctuation and whitespace are folded by 5.1's `normalize_anchor`.

    Not a restatement of that function's own tests: if check 2.1 folded OCR
    text differently from the authoring-time uniqueness rule, rejecting
    colliding anchors at authoring time would mean nothing.
    """
    assert token_containment("Order-Search: Results!", "ORDER   SEARCH RESULTS") == 1.0


def test_character_level_ocr_noise_still_matches() -> None:
    """The mode the token threshold exists for: a misread letter per word."""
    noisy = "Fulfiliment Queue Pendlng Pick"
    assert token_containment("Fulfillment Queue Pending Pick", noisy) == 1.0


def test_an_absent_anchor_scores_zero() -> None:
    assert token_containment(SC1, "Tax Table Mapping Editor") == 0.0


@pytest.mark.parametrize(
    ("anchor", "text"),
    [("", "anything at all"), ("...", "anything at all"), (SC1, "")],
)
def test_nothing_to_find_or_nowhere_to_look_scores_zero(anchor: str, text: str) -> None:
    assert token_containment(anchor, text) == 0.0


def test_the_score_is_the_share_of_anchor_tokens_present() -> None:
    assert token_containment("alpha beta gamma delta", "alpha beta gamma") == 0.75


def test_a_token_matches_at_exactly_the_similarity_threshold() -> None:
    """2*17/40 = 0.85 — the boundary itself counts as present."""
    assert TOKEN_SIMILARITY_THRESHOLD == 0.85
    assert token_containment("a" * 20, "a" * 17 + "bbb") == 1.0


def test_a_token_just_under_the_similarity_threshold_is_absent() -> None:
    """2*16/40 = 0.80, under 0.85 — one more corrupted character than tolerated."""
    assert token_containment("a" * 20, "a" * 16 + "bbbb") == 0.0


# --------------------------------------------------------------------------
# Check 2.1 — capture recall
# --------------------------------------------------------------------------


def test_every_entry_matched_gives_recall_one_and_a_per_entry_line() -> None:
    result = capture_recall(manifest_of(), covering_captures())
    assert result.passed
    assert result.metrics["recall"] == 1.0
    assert result.metrics["expected"] == 4
    matched = {row["entry"]: row for row in result.detail}
    assert matched["SC1"]["capture_ordinal"] == 2
    assert matched["SC1"]["score"] == 1.0
    assert matched["SC2"]["capture_ordinal"] == 3
    assert len(result.detail) == 4


def test_one_unmatched_entry_fails_the_run_and_names_the_entry_and_anchor() -> None:
    captures = tuple(c for c in covering_captures() if c.ordinal != 3)
    result = capture_recall(manifest_of(), captures)
    assert not result.passed
    assert result.metrics["recall"] == 0.75
    problem = "\n".join(result.problems)
    assert "'SC2'" in problem
    assert "line items and tax breakdown" in problem


def test_a_missing_gallery_capture_leaves_a_participant_segment_unmatched() -> None:
    """Segments carry no anchor, so they are matched by gallery captures.

    Dropping them from the denominator instead would make a missing gallery
    capture invisible — the recall number would be perfect over the half of
    the manifest that happens to have anchors.
    """
    captures = tuple(c for c in covering_captures() if c.ordinal != 4)
    result = capture_recall(manifest_of(), captures)
    assert not result.passed
    assert result.metrics["expected"] == 4
    assert result.metrics["matched"] == 3
    assert "participant_segments[1]" in "\n".join(result.problems)


def test_the_denominator_comes_from_the_manifest_not_from_the_captures() -> None:
    """eval-design §2.1's independence rule, made mechanical.

    Twelve captures do not make the manifest expect twelve: a denominator
    derived from extractor output cannot contain a screen the extractor
    missed.
    """
    noise = tuple(capture(10 + i, "unrelated screen") for i in range(8))
    result = capture_recall(manifest_of(), covering_captures() + noise)
    assert result.metrics["expected"] == 4
    assert result.metrics["captures"] == 12


def test_an_entry_matches_at_exactly_the_anchor_threshold() -> None:
    """4 of 5 anchor tokens present = 0.8, the documented match line."""
    assert ANCHOR_MATCH_THRESHOLD == 0.8
    manifest = manifest_of(
        screens=[
            {
                "id": "SC1",
                "name": "Order List",
                "shown_at": "00:01:30",
                "ocr_anchor": "alpha beta gamma delta epsilon",
            }
        ],
        participant_segments=[],
    )
    result = capture_recall(manifest, (capture(1, "alpha beta gamma delta"),))
    assert result.detail[0]["score"] == 0.8
    assert result.passed


def test_an_entry_just_under_the_anchor_threshold_does_not_match() -> None:
    manifest = manifest_of(
        screens=[
            {
                "id": "SC1",
                "name": "Order List",
                "shown_at": "00:01:30",
                "ocr_anchor": "alpha beta gamma delta epsilon",
            }
        ],
        participant_segments=[],
    )
    result = capture_recall(manifest, (capture(1, "alpha beta gamma"),))
    assert result.detail[0]["score"] == 0.6
    assert not result.passed


def test_noise_on_a_matched_anchor_records_the_score_it_achieved() -> None:
    noisy = f"Orders  {SC1[:-1]}z  page 1 of 4"
    result = capture_recall(
        manifest_of(), (capture(1, noisy),) + covering_captures()[3:]
    )
    line = next(row for row in result.detail if row["entry"] == "SC1")
    assert line["matched"]
    assert line["score"] == 1.0


def test_a_capture_with_no_representative_frame_is_a_named_run_defect() -> None:
    captures = covering_captures() + (capture(5, None, frame=False),)
    result = capture_recall(manifest_of(), captures)
    assert not result.passed, "recall is 1.0, but the run still has a defect"
    assert result.metrics["recall"] == 1.0
    assert result.metrics["ocr_defects"] == 1
    assert "capture 5 has no representative_frame_id" in "\n".join(result.problems)


def test_a_capture_whose_frame_has_no_ocr_row_reads_differently() -> None:
    captures = covering_captures() + (capture(5, None, frame=True),)
    result = capture_recall(manifest_of(), captures)
    assert not result.passed
    assert "no frame_ocr row" in "\n".join(result.problems)


def test_a_defective_capture_is_never_dropped_from_the_count() -> None:
    """The over-capture guardrail counts it too — dropping it would hide a
    broken run behind a comfortable margin."""
    captures = covering_captures() + (capture(5, None, frame=False),)
    assert len(ocr_defects(captures)) == 1
    assert over_capture(manifest_of(), captures).metrics["captures"] == 5
    assert capture_recall(manifest_of(), captures).metrics["captures"] == 5


def test_an_empty_ocr_row_is_textless_but_not_a_defect() -> None:
    """A camera gallery legitimately recognizes no text; a missing row does not."""
    assert ocr_defects((capture(1, "", "participant-gallery"),)) == ()


def test_a_slide_deck_manifest_matches_on_its_slides_section() -> None:
    manifest = Manifest(data=valid_slide_deck())
    captures = (
        capture(1, "", "participant-gallery"),
        capture(2, "Q3 Architecture Review", "slide"),
        capture(3, "Evidence Pipeline Today", "slide"),
        capture(4, "Nothing Enters a Store Before Approval", "slide"),
    )
    result = capture_recall(manifest, captures)
    assert result.metrics["expected"] == 4
    assert result.metrics["matched"] == 4
    assert {row["section"] for row in result.detail} == {
        "slides",
        "participant_segments",
    }


# --------------------------------------------------------------------------
# Check 2.2 — over-capture guardrail
# --------------------------------------------------------------------------


def test_captures_within_the_budget_pass_and_record_both_numbers() -> None:
    result = over_capture(manifest_of(), tuple(capture(i) for i in range(1, 11)))
    assert result.passed
    assert result.metrics == {
        "captures": 10,
        "budget": 12,
        "duration_minutes": 12.0,
        "captures_per_minute": 0.833,
    }


def test_exactly_one_capture_per_minute_is_within_budget() -> None:
    assert over_capture(manifest_of(), tuple(capture(i) for i in range(1, 13))).passed


def test_over_budget_fails_and_records_captures_per_minute() -> None:
    result = over_capture(manifest_of(), tuple(capture(i) for i in range(1, 14)))
    assert not result.passed
    assert result.metrics["captures_per_minute"] == 1.083
    assert "exceeds the budget of 12" in result.problems[0]


def test_the_budget_rounds_a_fractional_duration_up() -> None:
    manifest = manifest_of(meeting=meeting_of(valid_ui_demo(), duration_minutes=11.2))
    result = over_capture(manifest, tuple(capture(i) for i in range(12)))
    assert result.passed
    assert result.metrics["budget"] == 12
    assert result.metrics["captures_per_minute"] == 1.071
    assert result.thresholds == {
        "max_captures": 12,
        "budget_formula": "max(ceil(duration_minutes), expected_screenshot_count)",
    }


def test_a_short_take_budget_is_floored_at_the_expected_captures() -> None:
    """A take shorter than planned must not fail 2.2 for satisfying 2.1.

    Demo-001's take ran 247 s against a planned 12 minutes, so its manifest
    expects more captures (6) than the take has minutes — a pipeline that
    captured exactly the expected screens would then be over an
    unreachable budget. The manifest's own recall denominator floors it.
    """
    manifest = manifest_of(meeting=meeting_of(valid_ui_demo(), duration_minutes=2))
    expected = manifest.expected_screenshot_count
    result = over_capture(manifest, tuple(capture(i) for i in range(1, expected + 1)))
    assert result.passed
    assert result.metrics["budget"] == expected
    over = over_capture(manifest, tuple(capture(i) for i in range(1, expected + 2)))
    assert not over.passed


# --------------------------------------------------------------------------
# Check 2.3 — view classification (reported, never a gate)
# --------------------------------------------------------------------------


def test_classification_accuracy_is_reported_against_the_implied_label() -> None:
    result = view_classification(
        manifest_of(), capture_recall(manifest_of(), covering_captures()).matches
    )
    assert result.metrics == {"accuracy": 1.0, "correct": 4, "scored": 4}
    assert result.blocking is False


def test_a_misclassified_capture_is_named_but_does_not_gate_the_run() -> None:
    captures = (
        capture(1, "", "participant-gallery"),
        capture(2, f"Orders {SC1}", "slide"),
        capture(3, f"{SC2} subtotal"),
        capture(4, "", "participant-gallery"),
    )
    result = view_classification(
        manifest_of(), capture_recall(manifest_of(), captures).matches
    )
    assert result.metrics["accuracy"] == 0.75
    assert result.blocking is False, "the run's verdict must not depend on 2.3"
    assert "classified 'slide'" in result.problems[0]
    assert "'ui-screen'" in result.problems[0]


def test_nothing_matched_leaves_nothing_to_classify() -> None:
    result = view_classification(
        manifest_of(), capture_recall(manifest_of(), ()).matches
    )
    assert result.metrics["accuracy"] is None
    assert result.blocking is False


# --------------------------------------------------------------------------
# Check 2.4 — dedup candidates (listed, never collapsed)
# --------------------------------------------------------------------------


def test_sequential_near_duplicates_are_listed_with_their_scores() -> None:
    captures = (
        capture(1, "Order Search Results page 1 of 4"),
        capture(2, "Order Search Results page 1 of 4"),
        capture(3, "Tax Table Mapping Editor"),
    )
    result = dedup_candidates(captures)
    assert result.metrics["candidates"] == 1
    assert result.detail[0]["captures"] == [1, 2]
    assert result.detail[0]["similarity"] == 1.0


def test_dedup_never_fails_the_run_and_never_collapses_anything() -> None:
    """SPEC constraint: biased toward over-capture rather than evidence loss."""
    captures = (capture(1, "same text"), capture(2, "same text"))
    result = dedup_candidates(captures)
    assert result.passed and result.blocking is False
    assert result.metrics["captures"] == 2
    assert captures == (capture(1, "same text"), capture(2, "same text"))


def test_a_pair_at_exactly_the_dedup_threshold_is_not_a_candidate() -> None:
    """2*18/40 = 0.9 — candidates are strictly *above* the threshold."""
    assert DEDUP_SIMILARITY_THRESHOLD == 0.9
    captures = (capture(1, "a" * 18 + "bb"), capture(2, "a" * 18 + "cc"))
    assert dedup_candidates(captures).metrics["candidates"] == 0


def test_only_sequential_captures_are_paired() -> None:
    captures = (
        capture(1, "identical text here"),
        capture(2, "a completely different screen"),
        capture(3, "identical text here"),
    )
    assert dedup_candidates(captures).metrics["candidates"] == 0


def test_a_capture_with_no_ocr_text_is_not_scored_for_similarity() -> None:
    """Its own reported defect; inventing a similarity from unread text would
    put a pair in front of a human that nothing measured."""
    captures = (capture(1, "some text"), capture(2, None), capture(3, "some text"))
    assert dedup_candidates(captures).metrics["candidates"] == 0


def test_captures_are_paired_in_ordinal_order_not_row_order() -> None:
    captures = (capture(3, "b" * 40), capture(1, "a" * 40), capture(2, "a" * 40))
    result = dedup_candidates(captures)
    assert result.detail[0]["captures"] == [1, 2]


# --------------------------------------------------------------------------
# Ground-truth duration agreement
# --------------------------------------------------------------------------


def test_a_manifest_agreeing_with_the_recording_passes() -> None:
    result = duration_agreement(manifest_of(), 12 * 60_000)
    assert result.passed
    assert result.metrics["delta_minutes"] == 0.0


def test_a_manifest_within_the_tolerance_passes() -> None:
    assert duration_agreement(manifest_of(), int(12.9 * 60_000)).passed


def test_a_manifest_past_the_tolerance_fails_as_a_ground_truth_error() -> None:
    result = duration_agreement(manifest_of(), 20 * 60_000)
    assert not result.passed
    assert "describing a different meeting" in result.problems[0]
    assert result.metrics["recording_minutes"] == 20.0


def test_a_recording_with_no_probed_duration_cannot_be_cross_checked() -> None:
    result = duration_agreement(manifest_of(), None)
    assert not result.passed
    assert result.metrics["recording_minutes"] is None


# --------------------------------------------------------------------------
# Not-applicable, and the report shape every check obeys
# --------------------------------------------------------------------------


def test_a_check_that_could_not_run_is_a_failure_not_a_skip() -> None:
    result = not_applicable(checks.CAPTURE_RECALL, "the meeting has no recording")
    assert result.applicable is False
    assert result.passed is False
    assert result.blocking is True
    assert result.problems == ("the meeting has no recording",)
    assert "NOT APPLICABLE" in result.summary()


@pytest.mark.parametrize(
    "result",
    [
        capture_recall(manifest_of(), covering_captures()),
        over_capture(manifest_of(), covering_captures()),
        dedup_candidates(covering_captures()),
        duration_agreement(manifest_of(), 12 * 60_000),
    ],
    ids=lambda result: result.check,
)
def test_every_threshold_a_check_applied_is_carried_with_its_result(
    result: checks.CheckResult,
) -> None:
    """eval-design §6: a threshold change invalidates prior verdicts, so the
    number in force has to travel with the number it produced."""
    serialized = result.to_dict()
    assert serialized["thresholds"], f"{result.check} recorded no threshold"
    assert set(serialized) == {
        "check",
        "passed",
        "blocking",
        "applicable",
        "thresholds",
        "metrics",
        "detail",
        "problems",
    }


# --------------------------------------------------------------------------
# Check 2.1 — the two ways recall can be wrong while looking right
# --------------------------------------------------------------------------


def two_anchor_manifest() -> Manifest:
    """Two anchors that 5.1 accepts as unique and check 2.1 cannot tell apart.

    Uniqueness is exact-match-after-folding; matching is fuzzy at 0.8. Anchors
    differing by one word out of five clear the first and collide under the
    second — the residual risk `evals/README.md` documents.
    """
    return manifest_of(
        screens=[
            {
                "id": "SC1",
                "name": "Order Search",
                "shown_at": "00:01:30",
                "ocr_anchor": "Order Search Results Page Header",
            },
            {
                "id": "SC2",
                "name": "Order Sidebar",
                "shown_at": "00:03:05",
                "ocr_anchor": "Order Search Results Page Sidebar",
            },
        ],
        participant_segments=[],
    )


def test_one_capture_answering_for_two_entries_never_reads_as_full_recall() -> None:
    """The failure mode this detection exists for: SC2's screen was never
    captured, and without the check recall would say 1.0 anyway."""
    result = capture_recall(
        two_anchor_manifest(), (capture(1, "Order Search Results Page Header 1 of 4"),)
    )
    assert result.metrics["recall"] == 1.0, "both entries did match the one capture"
    assert not result.passed, "so the check must fail on the double assignment"
    assert result.metrics["double_assigned_captures"] == 1


def test_the_double_assignment_problem_names_the_capture_and_both_entries() -> None:
    result = capture_recall(
        two_anchor_manifest(), (capture(1, "Order Search Results Page Header 1 of 4"),)
    )
    problem = next(p for p in result.problems if "answers for" in p)
    assert "capture 1" in problem
    assert "SC1" in problem and "SC2" in problem
    assert "ground-truth script error" in problem


def test_nothing_is_reassigned_or_collapsed_by_the_detection() -> None:
    """Detected, not repaired. Greedily picking a winner would leave the loser
    unmatched and make an authoring problem look like a pipeline miss."""
    result = capture_recall(
        two_anchor_manifest(), (capture(1, "Order Search Results Page Header 1 of 4"),)
    )
    assert [row["capture_ordinal"] for row in result.detail] == [1, 1]
    assert all(row["matched"] for row in result.detail)


def test_distinct_captures_for_distinct_entries_are_not_double_assigned() -> None:
    result = capture_recall(
        two_anchor_manifest(),
        (
            capture(1, "Order Search Results Page Header 1 of 4"),
            capture(2, "Order Search Results Page Sidebar tray"),
        ),
    )
    assert result.metrics["double_assigned_captures"] == 0
    assert result.passed


def test_an_anchored_entry_and_a_segment_cannot_share_one_capture() -> None:
    """The gallery capture answers for the segment; an anchored entry whose
    text also matched it would be the same double count."""
    manifest = manifest_of(
        screens=[
            {
                "id": "SC1",
                "name": "Gallery",
                "shown_at": "00:01:30",
                "ocr_anchor": "Speaker View Grid",
            }
        ],
        participant_segments=[{"at": "00:00:00", "label": "meeting start"}],
    )
    result = capture_recall(
        manifest, (capture(1, "Speaker View Grid", "participant-gallery"),)
    )
    assert result.metrics["recall"] == 1.0
    assert not result.passed
    assert result.metrics["double_assigned_captures"] == 1


def test_the_entries_walked_are_reconciled_against_the_denominator() -> None:
    """A divergence would make `matched / expected` stop being recall — and it
    could exceed 1.0, reading as better than perfect rather than as broken."""
    manifest = manifest_of()
    assert manifest.expected_screenshot_count == 4
    result = capture_recall(manifest, covering_captures())
    assert len(result.detail) == manifest.expected_screenshot_count
    assert result.metrics["expected"] == len(result.matches)


class DriftedManifest(Manifest):
    """A manifest whose denominator disagrees with the entries it declares.

    Standing in for the only way `len(matches) != expected` can happen: a
    second implementation of the recall denominator somewhere. eval-design
    §2.1's independence rule is why `expected_screenshot_count` is the one
    implementation, and this is what notices if that ever stops being true.
    """

    @property
    def expected_screenshot_count(self) -> int:
        return 2


def test_a_second_denominator_cannot_push_recall_past_one() -> None:
    manifest = DriftedManifest(data=valid_ui_demo())
    result = capture_recall(manifest, covering_captures())
    assert len(result.matches) == 4, "four entries were actually walked"
    assert result.metrics["recall"] == 2.0, "against a denominator of two"
    assert not result.passed, "a ratio above 1.0 is broken, not better than perfect"
    assert "have diverged" in "\n".join(result.problems)
