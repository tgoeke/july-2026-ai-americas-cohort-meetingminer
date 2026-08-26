"""Check 2.11's assembly, exercised over synthetic observations — no store.

``publish_gate`` is a pure function over what the test layer observed:
discovered artifacts, per-store membership before and after, and the approve
outcome. Every I/O-matrix row that is not inherently store-backed lives here:
the pre-approval gate violation (the headline), post-approval absence per
store, citation mismatch, the consumed one-way lifecycle, refusal outcomes,
and the no-artifacts blocking not-applicable.
"""

from __future__ import annotations

from dataclasses import dataclass

from evals.harness import checks
from evals.harness.checks import ApproveOutcome, StorePresence

MEETING = "11111111-1111-7111-8111-111111111111"
MOMENT = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
ARTIFACT = "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb"


@dataclass(frozen=True)
class FakeArtifact:
    """The attribute shape ``publish_gate`` reads (``corpus.ArtifactRow`` has it)."""

    id: str
    moment_id: str
    state: str
    kind: str = "adr"


def absent() -> dict[str, StorePresence]:
    return {
        checks.SEARCH_STORE: StorePresence(present=False),
        checks.GRAPH_STORE: StorePresence(present=False),
    }


def present(*moments: str) -> dict[str, StorePresence]:
    return {
        checks.SEARCH_STORE: StorePresence(present=True, cited_moment_ids=moments),
        checks.GRAPH_STORE: StorePresence(present=True, cited_moment_ids=moments),
    }


def approved_ok(*published: str) -> ApproveOutcome:
    return ApproveOutcome(attempted=True, ok=True, published_ids=published)


def test_the_clean_sequence_passes_and_reports_everything() -> None:
    """Absent before, approved, present in both after, citing its moment."""
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: absent()},
        approved_ok(ARTIFACT),
        {ARTIFACT: present(MOMENT)},
    )
    assert result.passed, result.summary()
    assert result.metrics["approve_attempted"] is True
    assert result.metrics["published_asserted"] == 1
    record = result.detail[0]
    assert record["asserted_published"] is True
    assert record["pre"][checks.SEARCH_STORE]["present"] is False
    assert record["post"][checks.GRAPH_STORE]["cited_moment_ids"] == [MOMENT]


def test_an_unpublished_artifact_in_a_store_is_the_headline_violation() -> None:
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {
            ARTIFACT: {
                checks.SEARCH_STORE: StorePresence(present=True),
                checks.GRAPH_STORE: StorePresence(present=False),
            }
        },
        approved_ok(ARTIFACT),
        {ARTIFACT: present(MOMENT)},
    )
    assert not result.passed
    violation = next(p for p in result.problems if "GATE VIOLATION" in p)
    assert checks.SEARCH_STORE in violation
    assert ARTIFACT in violation
    assert "'extracted'" in violation


def test_a_published_artifact_absent_from_one_store_fails_naming_it() -> None:
    """Projection-on-publish landed with story 4-4, so absence from either
    store after approval is a regression — the check defending the contract,
    never to be weakened to green."""
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: absent()},
        approved_ok(ARTIFACT),
        {
            ARTIFACT: {
                checks.SEARCH_STORE: StorePresence(
                    present=True, cited_moment_ids=(MOMENT,)
                ),
                checks.GRAPH_STORE: StorePresence(present=False),
            }
        },
    )
    assert not result.passed
    problem = next(p for p in result.problems if "absent" in p)
    assert checks.GRAPH_STORE in problem
    assert "regressed" in problem


def test_a_present_artifact_whose_citation_does_not_resolve_fails() -> None:
    other_moment = "cccccccc-cccc-7ccc-8ccc-cccccccccccc"
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: absent()},
        approved_ok(ARTIFACT),
        {ARTIFACT: present(other_moment)},
    )
    assert not result.passed
    problem = next(p for p in result.problems if "citation" in p)
    assert ARTIFACT in problem and MOMENT in problem


def test_already_published_rows_are_asserted_even_with_nothing_to_approve() -> None:
    """The consumed lifecycle: gate half unmeasurable, named with the state
    distribution; the positive half still runs over the published rows."""
    artifact = FakeArtifact(ARTIFACT, MOMENT, "published")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {},
        ApproveOutcome(attempted=False),
        {ARTIFACT: present(MOMENT)},
    )
    assert not result.passed
    assert not result.applicable
    consumed = next(p for p in result.problems if "nothing left to approve" in p)
    assert "published: 1" in consumed
    assert "one-way lifecycle" in consumed
    # The positive half found nothing wrong, so it contributed no problem.
    assert len(result.problems) == 1


def test_a_consumed_lifecycle_with_a_missing_published_row_reports_both() -> None:
    artifact = FakeArtifact(ARTIFACT, MOMENT, "published")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {},
        ApproveOutcome(attempted=False),
        {
            ARTIFACT: {
                checks.SEARCH_STORE: StorePresence(present=False),
                checks.GRAPH_STORE: StorePresence(present=False),
            }
        },
    )
    assert not result.passed
    assert any("nothing left to approve" in p for p in result.problems)
    assert sum("absent" in p for p in result.problems) == 2


def test_a_refused_approval_fails_carrying_the_problem_detail() -> None:
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: absent()},
        ApproveOutcome(
            attempted=True,
            ok=False,
            detail="the api answered 409 meeting-not-viewable: evidence pending",
        ),
        {},
    )
    assert not result.passed
    assert result.applicable
    problem = next(p for p in result.problems if "approval" in p)
    assert "meeting-not-viewable" in problem


def test_no_artifacts_at_all_is_a_blocking_not_applicable_naming_the_meeting() -> None:
    result = checks.publish_gate(
        MEETING, [], {}, ApproveOutcome(attempted=False), {}
    )
    assert not result.passed
    assert not result.applicable
    assert result.blocking
    assert MEETING in result.problems[0]
    assert "no artifacts at all" in result.problems[0]


def test_an_extracted_artifact_never_approved_is_a_divergence_failure() -> None:
    """The check and the test layer disagreeing about what to approve must be
    loud — a silently skipped approval would leave the gate untested."""
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: absent()},
        ApproveOutcome(attempted=False),
        {},
    )
    assert not result.passed
    assert any("no approval was attempted" in p for p in result.problems)


def test_a_membership_read_that_was_never_recorded_is_a_divergence() -> None:
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {},
        approved_ok(ARTIFACT),
        {},
    )
    assert not result.passed
    assert any(
        "no pre-approval" in p and checks.SEARCH_STORE in p for p in result.problems
    )
    assert any("no post-approval" in p for p in result.problems)


def test_an_approved_state_row_is_held_to_the_negative_half() -> None:
    """`approved` is not `published`: the gate holds until the final state."""
    artifact = FakeArtifact(ARTIFACT, MOMENT, "approved")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: {
            checks.SEARCH_STORE: StorePresence(present=True),
            checks.GRAPH_STORE: StorePresence(present=False),
        }},
        ApproveOutcome(attempted=False),
        {},
    )
    assert not result.passed
    assert result.applicable, "a violation must never soften into not-applicable"
    assert any("GATE VIOLATION" in p for p in result.problems)


def test_the_gate_rule_travels_with_the_result() -> None:
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: absent()},
        approved_ok(ARTIFACT),
        {ARTIFACT: present(MOMENT)},
    )
    assert "gate" in result.thresholds
    assert checks.SEARCH_STORE in result.thresholds["gate"]
    assert checks.GRAPH_STORE in result.thresholds["gate"]


def test_a_published_id_discovery_never_saw_is_a_loud_divergence() -> None:
    """Every other observation/discovery mismatch is loud; an approval
    publishing an id the corpus read never returned must be too — its
    citation cannot be verified, and silence would read as verified."""
    ghost = "dddddddd-dddd-7ddd-8ddd-dddddddddddd"
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: absent()},
        approved_ok(ARTIFACT, ghost),
        {ARTIFACT: present(MOMENT), ghost: present(MOMENT)},
    )
    assert not result.passed
    problem = next(p for p in result.problems if ghost in p)
    assert "discovery never saw" in problem
    assert "unverified" in problem


def test_a_successful_approval_that_published_nothing_is_a_divergence() -> None:
    """`ok` with an empty publish set would let the positive half pass having
    verified zero artifacts — the endpoint's own contract (409 on nothing to
    approve, at least one row on success) says that state is a divergence."""
    artifact = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = checks.publish_gate(
        MEETING,
        [artifact],
        {ARTIFACT: absent()},
        ApproveOutcome(attempted=True, ok=True, published_ids=()),
        {},
    )
    assert not result.passed
    assert any("verified nothing" in p for p in result.problems)


# --------------------------------------------------------------------------
# The scripted-corpus refusal — pure, so deleting the guard fails a test
# --------------------------------------------------------------------------


def test_a_scripted_tag_is_no_refusal() -> None:
    assert checks.publish_gate_refusal(MEETING, checks.SCRIPTED_CORPUS) is None


def test_a_non_scripted_tag_is_refused_with_no_approval_call() -> None:
    result = checks.publish_gate_refusal(MEETING, "real")
    assert result is not None
    assert not result.passed
    assert result.blocking
    problem = result.problems[0]
    assert "REFUSED" in problem
    assert "'real'" in problem
    assert "never approved by a machine" in problem
    assert "no approval call was made" in problem
    # Thresholds travel with the refusal like with every other 2.11 result.
    assert result.thresholds == checks.PUBLISH_GATE_THRESHOLDS
    assert result.metrics["approve_attempted"] is False


def test_a_vanished_meeting_row_is_its_own_refusal_not_corpus_none() -> None:
    """`None` means the row is gone, which is a different finding from a
    mis-tagged drop — rendering it as "corpus None" would send triage after
    a tag nobody ever wrote."""
    result = checks.publish_gate_refusal(MEETING, None)
    assert result is not None
    assert not result.passed
    problem = result.problems[0]
    assert "no meeting row" in problem
    assert "None" not in problem
    assert "no approval call was made" in problem
