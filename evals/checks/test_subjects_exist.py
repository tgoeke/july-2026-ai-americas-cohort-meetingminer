"""A run with nothing to measure fails here, by name, before any check runs.

This is the *no silent zero* constraint made mechanical. Every check test is
parametrized per eval subject, and an empty parametrization produces skipped
tests — a green-looking run that measured nothing, which is exactly how a
harness comes to report 100% recall against an empty corpus. Ordering these
two tests first (``pytest_collection_modifyitems`` in ``evals/conftest.py``)
means a run in that state fails on the reason rather than on four empty checks.

**Today every run fails here**, and that is correct rather than a defect: both
shipped fixtures still carry placeholder ``source_id`` values, so nothing
ingested answers to them until the scripted meetings are recorded, pulled, and
the real ids replace the placeholders.
"""

from __future__ import annotations

from evals.conftest import EvalSubjects
from evals.harness.run import Run


def test_every_manifest_is_placed_against_the_ingested_corpus(
    run: Run, subjects: EvalSubjects
) -> None:
    """No unmatched manifest, no corpus mismatch, no ambiguous match.

    A manifest the run could not place is ground truth that measured nothing,
    so it fails the run rather than shrinking the denominator quietly. The
    problems are recorded into the report first: the terminal scrolls away,
    the run folder is the audit record.
    """
    for problem in subjects.problems:
        run.note(problem)
    assert not subjects.problems, (
        "the ground-truth corpus could not be placed against the ingested"
        " meetings:\n  - " + "\n  - ".join(subjects.problems)
    )


def test_the_run_has_at_least_one_eval_subject(
    run: Run, subjects: EvalSubjects
) -> None:
    """Zero subjects is a failure — never a pass, never a skip."""
    for problem in subjects.problems:
        run.note(problem)
    assert subjects.subjects, (
        "this run has no eval subjects, so every capture check below would"
        " have measured nothing. A check suite that finds nothing and reports"
        " success is the failure mode the eval design exists to forbid."
        + (
            "\n  - " + "\n  - ".join(subjects.problems)
            if subjects.problems
            else "\n  - no ground-truth manifests were loaded at all"
        )
    )
