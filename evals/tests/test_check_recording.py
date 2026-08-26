"""Every path through a check test lands a line in the report.

`_record` lives in the store-backed module `evals/checks/test_capture_checks.py`
because that is where it is used, but nothing about it needs a store: it is a
pure dispatcher over a `Run`, an `Evidence` and a callable. Exercising it here
is the only way it is covered at all — `evals/checks/` runs only during a real
eval run, holding the shared stores, which is not a place to discover that an
inapplicable dedup check was recorded as a gate that failed.

What it must never do is leave a check out. A check silently absent from a
report reads as a check that passed, and the run's verdict is computed over
whatever was recorded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.checks.test_capture_checks import _record
from evals.conftest import Evidence, read_evidence
from evals.harness import checks
from evals.harness.checks import CheckResult
from evals.harness.corpus import CorpusQueryError
from evals.harness.run import Run
from evals.tests.test_run_artifacts import StubConfig, StubSubject


def a_run(tmp_path: Path) -> Run:
    return Run.create("2026-08-19-record", config=StubConfig(), root=tmp_path)


def measurable() -> Evidence:
    return Evidence(captures=(), media_duration_ms=720_000, has_recording=True)


def unmeasurable() -> Evidence:
    return Evidence(
        captures=(),
        media_duration_ms=None,
        has_recording=False,
        problem="the meeting was ingested with has_recording = false",
    )


def recorded(run: Run) -> list[dict]:
    return run.describe_subject(StubSubject())["checks"]


def test_a_measurable_subject_records_what_the_algorithm_returned(
    tmp_path: Path,
) -> None:
    run = a_run(tmp_path)
    expected = CheckResult(check=checks.OVER_CAPTURE, passed=True)
    result = _record(
        run, StubSubject(), measurable(), checks.OVER_CAPTURE, lambda: expected
    )
    assert result is expected
    assert [check["check"] for check in recorded(run)] == [checks.OVER_CAPTURE]


def test_an_unmeasurable_subject_records_not_applicable_with_the_reason(
    tmp_path: Path,
) -> None:
    run = a_run(tmp_path)
    result = _record(
        run,
        StubSubject(),
        unmeasurable(),
        checks.CAPTURE_RECALL,
        lambda: pytest.fail("ran"),
    )
    assert result.applicable is False
    assert result.passed is False
    assert "has_recording = false" in result.problems[0]


@pytest.mark.parametrize("blocking", [True, False])
def test_an_inapplicable_check_keeps_its_own_blocking_ness(
    tmp_path: Path, blocking: bool
) -> None:
    """The defect this test exists for: recording an inapplicable check 2.4 as
    `blocking=True` tells story 5.5's triage that dedup is a gate and that it
    failed — the opposite of what the contract says about it."""
    run = a_run(tmp_path)
    result = _record(
        run,
        StubSubject(),
        unmeasurable(),
        checks.DEDUP_QUALITY,
        lambda: pytest.fail("ran"),
        blocking=blocking,
    )
    assert result.blocking is blocking
    assert recorded(run)[0]["blocking"] is blocking


def test_a_non_blocking_check_that_could_not_run_does_not_fail_the_run(
    tmp_path: Path,
) -> None:
    run = a_run(tmp_path)
    _record(
        run,
        StubSubject(),
        measurable(),
        checks.CAPTURE_RECALL,
        lambda: CheckResult(check=checks.CAPTURE_RECALL, passed=True),
    )
    _record(
        run,
        StubSubject(),
        unmeasurable(),
        checks.DEDUP_QUALITY,
        lambda: pytest.fail("ran"),
        blocking=False,
    )
    for check in (
        checks.DURATION_AGREEMENT,
        checks.OVER_CAPTURE,
        checks.VIEW_CLASSIFICATION,
        # Story 5.3: completeness now requires the retrieval and publish-gate
        # checks per subject too, so a passing run records all seven.
        checks.DOC_INDEX_SEARCH_RECALL,
        checks.PUBLISH_GATE_PROJECTION,
    ):
        _record(
            run,
            StubSubject(),
            measurable(),
            check,
            lambda check=check: CheckResult(
                check=check,
                passed=True,
                blocking=check != checks.VIEW_CLASSIFICATION,
            ),
            blocking=check != checks.VIEW_CLASSIFICATION,
        )
    assert run.passed is True


def test_a_blocking_check_that_could_not_run_does_fail_the_run(
    tmp_path: Path,
) -> None:
    run = a_run(tmp_path)
    _record(
        run,
        StubSubject(),
        unmeasurable(),
        checks.CAPTURE_RECALL,
        lambda: pytest.fail("ran"),
    )
    assert run.passed is False


def test_a_check_that_raised_is_recorded_rather_than_lost(tmp_path: Path) -> None:
    """Without this the exception propagates, the check is never recorded, and
    `Run.passed` is computed over whichever checks happened to survive."""
    run = a_run(tmp_path)

    def explode() -> CheckResult:
        raise ZeroDivisionError("division by zero")

    with pytest.raises(ZeroDivisionError):
        _record(run, StubSubject(), measurable(), checks.OVER_CAPTURE, explode)

    entry = recorded(run)[0]
    assert entry["check"] == checks.OVER_CAPTURE
    assert entry["applicable"] is False
    assert "ZeroDivisionError" in entry["problems"][0]
    assert "division by zero" in entry["problems"][0]


def test_a_check_that_raised_fails_the_run_even_when_it_never_gates_one(
    tmp_path: Path,
) -> None:
    """`blocking=False` means "a real result of this check does not fail the
    run", never "this check may go unrun"."""
    run = a_run(tmp_path)

    def explode() -> CheckResult:
        raise RuntimeError("the corpus went away")

    with pytest.raises(RuntimeError):
        _record(
            run,
            StubSubject(),
            measurable(),
            checks.DEDUP_QUALITY,
            explode,
            blocking=False,
        )

    assert recorded(run)[0]["blocking"] is False, "the check is still not a gate"
    assert run.passed is False, "but a crashed check is a defect, not a measurement"
    report = run.write_report().read_text()
    assert "the corpus went away" in report


def test_the_original_traceback_survives(tmp_path: Path) -> None:
    """Re-raised rather than swallowed: pytest should fail on the real fault,
    not on a summary of it."""
    run = a_run(tmp_path)

    def explode() -> CheckResult:
        raise KeyError("representative_frame_id")

    with pytest.raises(KeyError, match="representative_frame_id"):
        _record(run, StubSubject(), measurable(), checks.CAPTURE_RECALL, explode)


def test_a_corpus_read_failure_becomes_recorded_unmeasurable_evidence(
    tmp_path: Path,
) -> None:
    class BrokenCorpus:
        def has_recording(self, meeting_id: str) -> bool:
            raise CorpusQueryError(f"read failed for {meeting_id}")

    evidence = read_evidence(BrokenCorpus(), StubSubject())
    assert evidence.measurable is False
    assert "read failed" in (evidence.problem or "")

    run = a_run(tmp_path)
    for check in (
        checks.DURATION_AGREEMENT,
        checks.CAPTURE_RECALL,
        checks.OVER_CAPTURE,
        checks.VIEW_CLASSIFICATION,
        checks.DEDUP_QUALITY,
    ):
        _record(
            run,
            StubSubject(),
            evidence,
            check,
            lambda: pytest.fail("the corpus failure must stop computation"),
            blocking=check not in {checks.VIEW_CLASSIFICATION, checks.DEDUP_QUALITY},
        )

    checks_in_report = recorded(run)
    assert [result["check"] for result in checks_in_report] == [
        checks.DURATION_AGREEMENT,
        checks.CAPTURE_RECALL,
        checks.OVER_CAPTURE,
        checks.VIEW_CLASSIFICATION,
        checks.DEDUP_QUALITY,
    ]
    assert all(result["applicable"] is False for result in checks_in_report)
    assert "read failed" in run.write_report().read_text()
    assert run.passed is False
