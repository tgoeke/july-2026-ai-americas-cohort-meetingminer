"""Check 2.11's assembly, exercised over synthetic observations — no store.

``publish_gate`` is a pure function over what the test layer observed:
discovered subject artifacts with one read-only membership read apiece, and
the run-owned :class:`GateProbe` that carries the whole mutation sequence
(minted -> pre-absent -> approved -> post-present-cited -> erased). Every
I/O-matrix row that is not inherently store-backed lives here: the gate
violation headline, the probe's clean sequence, race tolerance, foreign-row
tolerance, cleanup loudness, probe refusals, the no-artifacts blocking
not-applicable, and the corpus-tag refusal.
"""

from __future__ import annotations

from dataclasses import dataclass

from evals.harness import checks
from evals.harness.checks import ApproveOutcome, CleanupReport, GateProbe, StorePresence

MEETING = "11111111-1111-7111-8111-111111111111"
MOMENT = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
ARTIFACT = "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb"
PROBE_MOMENT = "cccccccc-cccc-7ccc-8ccc-cccccccccccc"
PROBE_ARTIFACT = "dddddddd-dddd-7ddd-8ddd-dddddddddddd"


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


def clean_cleanup() -> CleanupReport:
    return CleanupReport(
        search_document_removed=True,
        graph_node_removed=True,
        export_file_removed=True,
        postgres_row_removed=True,
    )


def clean_probe(**overrides: object) -> GateProbe:
    fields: dict[str, object] = {
        "artifact_id": PROBE_ARTIFACT,
        "moment_id": PROBE_MOMENT,
        "pre": absent(),
        "post": present(PROBE_MOMENT),
        "approve": ApproveOutcome(
            attempted=True, ok=True, published_ids=(PROBE_ARTIFACT,)
        ),
        "cleanup": clean_cleanup(),
    }
    fields.update(overrides)
    return GateProbe(**fields)  # type: ignore[arg-type]


def gate(
    artifacts: list[FakeArtifact],
    membership: dict[str, dict[str, StorePresence]],
    probe: GateProbe,
) -> checks.CheckResult:
    return checks.publish_gate(MEETING, artifacts, membership, probe)


# --------------------------------------------------------------------------
# The clean sequence, and what the result records
# --------------------------------------------------------------------------


def test_the_clean_sequence_passes_and_reports_everything() -> None:
    """Subject rows read once and held to their state; the probe pre-absent,
    approved, post-present citing its moment, and erased verified."""
    extracted = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = gate([extracted], {ARTIFACT: absent()}, clean_probe())
    assert result.passed, result.summary()
    assert result.applicable
    assert result.metrics["approve_attempted"] is True
    assert result.metrics["cleanup_verified"] is True
    subject_record = result.detail[0]
    assert subject_record["artifact"] == ARTIFACT
    assert subject_record["membership"][checks.SEARCH_STORE]["present"] is False
    probe_record = result.detail[-1]
    assert probe_record["probe"] is True
    assert probe_record["artifact"] == PROBE_ARTIFACT
    assert probe_record["pre"][checks.SEARCH_STORE]["present"] is False
    assert probe_record["post"][checks.GRAPH_STORE]["cited_moment_ids"] == [
        PROBE_MOMENT
    ]
    assert probe_record["cleanup"]["postgres_row_removed"] is True


def test_unconsumed_extracted_subject_rows_are_only_held_to_absence() -> None:
    """The old contract approved the subject's extracted rows; this one never
    does. Extracted subject rows with no approval attempted against them are
    the expected steady state — absence asserted, no divergence, and they
    survive the run untouched (the run mutates only its probe)."""
    extracted = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = gate([extracted], {ARTIFACT: absent()}, clean_probe())
    assert result.passed, result.summary()
    assert not any("no approval was attempted" in p for p in result.problems)
    assert not any("nothing left to approve" in p for p in result.problems)


def test_published_subject_rows_are_held_to_presence_and_citation() -> None:
    published = FakeArtifact(ARTIFACT, MOMENT, "published")
    result = gate([published], {ARTIFACT: present(MOMENT)}, clean_probe())
    assert result.passed, result.summary()


# --------------------------------------------------------------------------
# Violations — the headline, and the positive-half regressions
# --------------------------------------------------------------------------


def test_an_unpublished_subject_in_a_store_is_the_headline_violation() -> None:
    extracted = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    membership = {
        ARTIFACT: {
            checks.SEARCH_STORE: StorePresence(present=True),
            checks.GRAPH_STORE: StorePresence(present=False),
        }
    }
    result = gate([extracted], membership, clean_probe())
    assert not result.passed
    violation = next(p for p in result.problems if "GATE VIOLATION" in p)
    assert checks.SEARCH_STORE in violation
    assert ARTIFACT in violation
    assert "'extracted'" in violation


def test_an_approved_state_row_is_held_to_the_negative_half() -> None:
    """`approved` is not `published`: the gate holds until the final state."""
    approved = FakeArtifact(ARTIFACT, MOMENT, "approved")
    membership = {
        ARTIFACT: {
            checks.SEARCH_STORE: StorePresence(present=True),
            checks.GRAPH_STORE: StorePresence(present=False),
        }
    }
    result = gate([approved], membership, clean_probe())
    assert not result.passed
    assert result.applicable, "a violation must never soften into not-applicable"
    assert any("GATE VIOLATION" in p for p in result.problems)


def test_a_probe_present_before_approval_is_the_headline_violation_too() -> None:
    """The probe is the measured gate transition: its freshly minted
    `extracted` row in a store is the same AD-4 break as any other."""
    probe = clean_probe(
        pre={
            checks.SEARCH_STORE: StorePresence(present=False),
            checks.GRAPH_STORE: StorePresence(present=True),
        }
    )
    result = gate([], {}, probe)
    assert not result.passed
    assert result.applicable
    violation = next(p for p in result.problems if "GATE VIOLATION" in p)
    assert PROBE_ARTIFACT in violation
    assert checks.GRAPH_STORE in violation


def test_a_published_subject_absent_from_one_store_fails_naming_it() -> None:
    published = FakeArtifact(ARTIFACT, MOMENT, "published")
    membership = {
        ARTIFACT: {
            checks.SEARCH_STORE: StorePresence(
                present=True, cited_moment_ids=(MOMENT,)
            ),
            checks.GRAPH_STORE: StorePresence(present=False),
        }
    }
    result = gate([published], membership, clean_probe())
    assert not result.passed
    problem = next(p for p in result.problems if "absent" in p)
    assert checks.GRAPH_STORE in problem
    assert "regressed" in problem


def test_a_probe_absent_from_a_store_after_approval_is_a_regression() -> None:
    probe = clean_probe(
        post={
            checks.SEARCH_STORE: StorePresence(
                present=True, cited_moment_ids=(PROBE_MOMENT,)
            ),
            checks.GRAPH_STORE: StorePresence(present=False),
        }
    )
    result = gate([], {}, probe)
    assert not result.passed
    problem = next(p for p in result.problems if "absent" in p)
    assert PROBE_ARTIFACT in problem
    assert checks.GRAPH_STORE in problem
    assert "regressed" in problem


def test_a_probe_whose_citation_does_not_resolve_fails() -> None:
    other = "eeeeeeee-eeee-7eee-8eee-eeeeeeeeeeee"
    probe = clean_probe(post=present(other))
    result = gate([], {}, probe)
    assert not result.passed
    problem = next(p for p in result.problems if "citation" in p)
    assert PROBE_ARTIFACT in problem and PROBE_MOMENT in problem


def test_a_published_subject_citation_mismatch_fails() -> None:
    other = "eeeeeeee-eeee-7eee-8eee-eeeeeeeeeeee"
    published = FakeArtifact(ARTIFACT, MOMENT, "published")
    result = gate([published], {ARTIFACT: present(other)}, clean_probe())
    assert not result.passed
    problem = next(p for p in result.problems if "citation" in p)
    assert ARTIFACT in problem and MOMENT in problem


# --------------------------------------------------------------------------
# The approve outcome — failure, race tolerance, divergence
# --------------------------------------------------------------------------


def test_a_refused_probe_approval_fails_carrying_the_problem_detail() -> None:
    probe = clean_probe(
        approve=ApproveOutcome(
            attempted=True,
            ok=False,
            detail="the api answered 409 meeting-not-viewable: evidence pending",
        ),
        post=None,
    )
    extracted = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = gate([extracted], {ARTIFACT: absent()}, probe)
    assert not result.passed
    assert result.applicable
    problem = next(p for p in result.problems if "approv" in p)
    assert "meeting-not-viewable" in problem


def test_a_concurrent_approval_is_tolerated_and_named_in_the_detail() -> None:
    """The race row: a sibling run's approve won, this run's 409 resolved by
    re-reading its own row as published. The gate was still exercised
    through the public api, so the result passes — with the race on the
    record, never silently."""
    race = (
        "a concurrent approval published probe artifact"
        f" {PROBE_ARTIFACT} first (409 nothing-to-approve, row re-read"
        " 'published') — the gate was still exercised through the public api"
    )
    probe = clean_probe(
        approve=ApproveOutcome(
            attempted=True, ok=True, detail=race, published_ids=(PROBE_ARTIFACT,)
        )
    )
    extracted = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = gate([extracted], {ARTIFACT: absent()}, probe)
    assert result.passed, result.summary()
    probe_record = result.detail[-1]
    assert "concurrent approval" in probe_record["approve"]["detail"]


def test_foreign_rows_in_the_approve_response_are_recorded_never_a_problem() -> None:
    """The route returns every artifact under the moment by design; rows the
    run did not mint are ignored for ownership asserts and land in the
    detail only."""
    foreign = "ffffffff-ffff-7fff-8fff-ffffffffffff"
    probe = clean_probe(foreign_ids=(foreign,))
    extracted = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = gate([extracted], {ARTIFACT: absent()}, probe)
    assert result.passed, result.summary()
    assert not any(foreign in p for p in result.problems)
    assert result.detail[-1]["foreign_rows"] == [foreign]


def test_an_ok_approval_that_left_the_probe_unpublished_is_a_divergence() -> None:
    probe = clean_probe(
        approve=ApproveOutcome(attempted=True, ok=True, published_ids=())
    )
    result = gate([], {}, probe)
    assert not result.passed
    assert any("verified nothing" in p for p in result.problems)


def test_a_minted_probe_with_no_approval_attempt_is_a_divergence() -> None:
    probe = clean_probe(approve=ApproveOutcome(attempted=False), post=None)
    result = gate([], {}, probe)
    assert not result.passed
    assert any("no approval was attempted" in p for p in result.problems)


# --------------------------------------------------------------------------
# Cleanup is loud — a leftover is a named failure, never a shrug
# --------------------------------------------------------------------------


def test_a_cleanup_leftover_fails_naming_the_id_and_the_store() -> None:
    leftover = (
        f"the meilisearch document for probe artifact {PROBE_ARTIFACT} survived"
        " its erasure — remove it from the 'artifacts' index by hand"
    )
    probe = clean_probe(
        cleanup=CleanupReport(
            search_document_removed=False,
            graph_node_removed=True,
            export_file_removed=True,
            postgres_row_removed=True,
            problems=(leftover,),
        )
    )
    result = gate([], {}, probe)
    assert not result.passed
    assert leftover in result.problems
    assert result.metrics["cleanup_verified"] is False


def test_a_silent_cleanup_leftover_still_fails_by_target_name() -> None:
    """A boolean saying 'not removed' with no problem line must not slip
    through as a pass — the assembly names the target itself."""
    probe = clean_probe(
        cleanup=CleanupReport(
            search_document_removed=True,
            graph_node_removed=False,
            export_file_removed=True,
            postgres_row_removed=True,
        )
    )
    result = gate([], {}, probe)
    assert not result.passed
    problem = next(p for p in result.problems if "graph_node_removed" in p)
    assert PROBE_ARTIFACT in problem


def test_a_minted_probe_with_no_cleanup_record_fails() -> None:
    probe = clean_probe(cleanup=None)
    result = gate([], {}, probe)
    assert not result.passed
    assert any(
        "cleanup" in p and PROBE_ARTIFACT in p for p in result.problems
    )


# --------------------------------------------------------------------------
# Probe refusals — blocking not-applicables that name state and remedy
# --------------------------------------------------------------------------


def test_a_probe_that_could_not_be_minted_is_a_blocking_not_applicable() -> None:
    reason = (
        f"no probe was minted for meeting {MEETING}: every one of its 3"
        " moments holds an 'extracted' artifact — approve or re-extract the"
        " subject by hand, then rerun"
    )
    result = gate(
        [FakeArtifact(ARTIFACT, MOMENT, "extracted")],
        {ARTIFACT: absent()},
        GateProbe(problem=reason),
    )
    assert not result.passed
    assert not result.applicable
    assert result.blocking
    assert reason in result.problems


def test_a_probe_refusal_never_softens_a_real_violation() -> None:
    membership = {
        ARTIFACT: {
            checks.SEARCH_STORE: StorePresence(present=True),
            checks.GRAPH_STORE: StorePresence(present=False),
        }
    }
    result = gate(
        [FakeArtifact(ARTIFACT, MOMENT, "extracted")],
        membership,
        GateProbe(problem="no probe was minted: the meeting was never projected"),
    )
    assert not result.passed
    assert result.applicable, "a violation must never soften into not-applicable"
    assert any("GATE VIOLATION" in p for p in result.problems)


def test_an_interrupted_probe_keeps_its_diagnosis_and_its_cleanup() -> None:
    """A store read failing mid-probe leaves a minted row behind it: the
    named interruption lands as the problem, the pre/post divergence noise
    is not piled on top, and the cleanup verdict is still enforced."""
    interruption = (
        "the pre-approval membership read failed for probe artifact"
        f" {PROBE_ARTIFACT}: Meilisearch could not be reached"
    )
    probe = GateProbe(
        artifact_id=PROBE_ARTIFACT,
        moment_id=PROBE_MOMENT,
        approve=ApproveOutcome(attempted=False),
        cleanup=clean_cleanup(),
        problem=interruption,
    )
    result = gate([], {}, probe)
    assert not result.passed
    assert not result.applicable
    assert interruption in result.problems
    assert not any("no pre-approval" in p for p in result.problems)
    assert not any("no approval was attempted" in p for p in result.problems)


def test_a_probe_reporting_neither_artifact_nor_problem_is_a_divergence() -> None:
    result = gate([], {}, GateProbe())
    assert not result.passed
    assert any("diverged" in p for p in result.problems)


# --------------------------------------------------------------------------
# Divergences between observations and discovery
# --------------------------------------------------------------------------


def test_a_subject_membership_read_that_was_never_recorded_is_a_divergence() -> None:
    extracted = FakeArtifact(ARTIFACT, MOMENT, "extracted")
    result = gate([extracted], {}, clean_probe())
    assert not result.passed
    assert any(
        "membership was recorded" in p and checks.SEARCH_STORE in p
        for p in result.problems
    )


def test_a_missing_probe_membership_read_is_a_divergence() -> None:
    probe = clean_probe(pre=None, post=None)
    result = gate([], {}, probe)
    assert not result.passed
    assert any("no pre-approval" in p for p in result.problems)
    assert any("no post-approval" in p for p in result.problems)


# --------------------------------------------------------------------------
# The no-artifacts branch, and what travels with every result
# --------------------------------------------------------------------------


def test_no_artifacts_at_all_is_a_blocking_not_applicable_with_probe_detail() -> None:
    """Unchanged §2.11 semantics — never a vacuous pass — and the probe's
    outcome is still on the record for triage."""
    result = gate([], {}, clean_probe())
    assert not result.passed
    assert not result.applicable
    assert result.blocking
    no_artifacts = next(p for p in result.problems if "no artifacts at all" in p)
    assert MEETING in no_artifacts
    assert result.detail[-1]["artifact"] == PROBE_ARTIFACT


def test_the_gate_rule_and_the_probe_rule_travel_with_the_result() -> None:
    result = gate(
        [FakeArtifact(ARTIFACT, MOMENT, "extracted")],
        {ARTIFACT: absent()},
        clean_probe(),
    )
    assert checks.SEARCH_STORE in result.thresholds["gate"]
    assert checks.GRAPH_STORE in result.thresholds["gate"]
    assert "probe" in result.thresholds
    assert "run-owned" in result.thresholds["probe"]


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
