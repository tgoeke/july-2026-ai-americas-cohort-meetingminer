"""The four BUILD capture checks against a live corpus (eval-design §2.1-2.4).

The thin layer: each test feeds real rows to a pure function from
``evals/harness/checks.py``, records the result into the run folder, and
asserts on it. Nothing is computed here — a number in the report that no
algorithm returned would be a verdict nothing produced.

Store-backed, and read-only twice over: the captures arrive through the
harness's ``default_transaction_read_only`` connection (AD-16), and the
corpus is listed through the public api. **These tests read the shared dev
stores read-only — safe beside another eval run or any suite (story 11.3).**
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest

from evals.conftest import Evidence
from evals.harness import checks
from evals.harness.checks import CheckResult
from evals.harness.corpus import Corpus
from evals.harness.run import Run
from evals.harness.subjects import Subject


def _record(
    run: Run,
    subject: Subject,
    evidence: Evidence,
    name: str,
    compute: Callable[[], CheckResult],
    *,
    blocking: bool = True,
) -> CheckResult:
    """Run a check, or record why it could not be run, and report either way.

    Every path through here lands a line in the report, because a check
    silently absent from a report reads as a check that passed. There are
    three:

    * the subject is measurable and the algorithm returns — its result;
    * the subject cannot be measured (no recording, no meeting row) — a *not
      applicable* result carrying the reason;
    * the algorithm raised — a *not applicable* result naming the exception,
      a run-level problem so the report's verdict cannot come out ``true``,
      and the original traceback re-raised so pytest fails on the real fault.

    ``blocking`` is threaded through rather than left at
    :func:`checks.not_applicable`'s default, because it is a property of the
    *check*, not of the outcome. Checks 2.3 and 2.4 never gate a run, so
    recording an inapplicable 2.4 as ``blocking=True`` would tell story 5.5's
    triage that dedup is a gate and that it failed — which is the opposite of
    what the contract says about it.
    """
    if not evidence.measurable:
        return run.record(
            subject,
            checks.not_applicable(
                name,
                evidence.problem or "the subject cannot be measured",
                blocking=blocking,
            ),
        )
    try:
        result = compute()
    except Exception as exc:
        failure = (
            f"{name} raised {type(exc).__name__}: {exc} — the check measured"
            " nothing, so its verdict is unknown rather than passing"
        )
        run.record(subject, checks.not_applicable(name, failure, blocking=blocking))
        # A crashed check is a harness defect, not a measurement. Noting it at
        # run level is what makes `Run.passed` false even for a check that
        # never gates a run: `blocking=False` means "a real result of this
        # check does not fail the run", never "this check may go unrun".
        run.note(failure)
        raise
    return run.record(subject, result)


#: One matching per subject, shared by checks 2.1 and 2.3. Check 2.3 scores
#: the captures 2.1 matched, so the two must be looking at the same matching —
#: memoized rather than recomputed so that is a fact about the run, not a
#: property of the algorithm that a later edit could quietly break.
_MATCHING: dict[str, checks.RecallResult] = {}


def _recall(subject: Subject, evidence: Evidence) -> checks.RecallResult:
    key = subject.manifest.id
    if key not in _MATCHING:
        _MATCHING[key] = checks.capture_recall(subject.manifest, evidence.captures)
    return _MATCHING[key]


def test_the_manifest_duration_agrees_with_the_recording(
    run: Run, subject: Subject, evidence: Evidence
) -> None:
    """A manifest more than a minute off the recording is ground truth for
    another meeting — a script error, not a pipeline bug (runbook step 2)."""
    result = _record(
        run,
        subject,
        evidence,
        checks.DURATION_AGREEMENT,
        lambda: checks.duration_agreement(
            subject.manifest, evidence.media_duration_ms
        ),
    )
    assert result.passed, result.summary()


def test_capture_recall(run: Run, subject: Subject, evidence: Evidence) -> None:
    """Check 2.1, threshold 1.0: any unmatched manifest entry fails the run."""
    result = _record(
        run,
        subject,
        evidence,
        checks.CAPTURE_RECALL,
        lambda: _recall(subject, evidence),
    )
    assert result.passed, result.summary()


def test_over_capture_guardrail(
    run: Run, subject: Subject, evidence: Evidence
) -> None:
    """Check 2.2: ``screenshot`` rows must not exceed one per minute."""
    result = _record(
        run,
        subject,
        evidence,
        checks.OVER_CAPTURE,
        lambda: checks.over_capture(subject.manifest, evidence.captures),
    )
    assert result.passed, result.summary()


def test_view_classification(
    run: Run, subject: Subject, evidence: Evidence
) -> None:
    """Check 2.3: accuracy is reported; the run's verdict does not depend on it.

    Deliberately assertion-free on the score. A misclassified capture is still
    evidence that was captured, and eval-design §2.3 calls this a tracked
    metric rather than a gate — so it lands in the report and nowhere else.
    """
    _record(
        run,
        subject,
        evidence,
        checks.VIEW_CLASSIFICATION,
        lambda: checks.view_classification(
            subject.manifest, _recall(subject, evidence).matches
        ),
        blocking=False,
    )


def test_dedup_candidates(run: Run, subject: Subject, evidence: Evidence) -> None:
    """Check 2.4: near-duplicate pairs are listed for a human, never collapsed.

    Also assertion-free, and for a stronger reason than 2.3: the SPEC biases
    toward over-capture rather than loss, so a candidate pair is a question
    for the runbook's human-judging step, not a failure.
    """
    _record(
        run,
        subject,
        evidence,
        checks.DEDUP_QUALITY,
        lambda: checks.dedup_candidates(evidence.captures),
        blocking=False,
    )


#: The probe row's `identity_key`. Named so the assertion below can look for
#: it, and distinctive so a human finding one in the corpus knows where it came
#: from.
WRITE_PROBE_KEY = "eval-harness-write-probe"


def test_the_harness_connection_refuses_a_write(corpus: Corpus) -> None:
    """AD-16, enforced by Postgres rather than by reviewer vigilance.

    The publish-gate check (story 5.3) is meaningless if the harness can write
    the state it audits, so ``default_transaction_read_only=on`` is on the
    connection itself. This is the test that says so out loud: the table named
    is real, and the statement would otherwise succeed.

    Which is exactly why the probe runs inside ``force_rollback`` rather than
    on the autocommit connection. The one Postgres every agent shares is the
    dev database, not a disposable fixture, and this test's whole premise is
    that the statement *would* succeed if the guarantee regressed — so on the
    day it regresses, an unwrapped probe leaves a permanent junk `screen` row
    behind and every agent inherits it. The rollback holds whichever way the
    statement goes: the write is undone if it landed, and the transaction is
    aborted if it raised.
    """
    connection = corpus.connection
    with (
        connection.transaction(force_rollback=True),
        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
    ):
        connection.execute(
            "INSERT INTO screen (identity_key, signature, view_type)"
            f" VALUES ('{WRITE_PROBE_KEY}', 'probe', 'ui-screen')"
        )

    # Belt to the rollback's braces, and read-only itself so it always runs:
    # if the row somehow survived, say so here rather than leaving it for the
    # next agent to find in a corpus they are trying to measure.
    survivors = corpus.connection.execute(
        "SELECT count(*) FROM screen WHERE identity_key = %s", (WRITE_PROBE_KEY,)
    ).fetchone()
    assert survivors is not None and survivors[0] == 0, (
        f"the write probe left a {WRITE_PROBE_KEY!r} row in the shared corpus —"
        " the read-only guarantee regressed AND the rollback did not hold;"
        " delete the row before running anything else against this database"
    )
