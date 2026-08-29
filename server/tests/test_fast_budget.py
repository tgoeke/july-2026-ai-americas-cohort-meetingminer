"""The fast-set budget hook (story 11.1), driven through an inner pytest run.

``pytester`` runs a four-test file in a scratch directory with ``fast_budget``
loaded and the budget set to 0.01s, so 50ms sleepers are over budget while
each outer test's own call phase stays far inside the real 2.0s budget it
runs under.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
BUDGET_KEY = "mm_fast_test_budget_seconds"

PROBE = '''
import time

import pytest


def test_unmarked_sleeper():
    time.sleep(0.05)


def test_failing_sleeper():
    time.sleep(0.05)
    assert False, "the assertion, not the budget"


@pytest.mark.slow(reason="probe")
def test_slow_marked_sleeper():
    time.sleep(0.05)


def test_fast():
    assert True
'''


def _run_probe(pytester: pytest.Pytester) -> pytest.RunResult:
    """One inner run of the probe file; two of its four tests must fail."""
    pytester.syspathinsert(TESTS_DIR)
    pytester.makepyfile(test_budget_probe=PROBE)
    result = pytester.runpytest_inprocess(
        "-p", "fast_budget",
        "-p", "no:cacheprovider",
        "-o", f"{BUDGET_KEY}=0.01",
        "-o", "markers=slow: probe",
        "-v",
    )
    result.assert_outcomes(passed=2, failed=2)
    return result


def _failure_section(result: pytest.RunResult, test_name: str) -> str:
    """One test's block in FAILURES: from its underscored header to the next header or section rule."""
    lines = result.outlines
    header = next(
        i for i, line in enumerate(lines) if line.startswith("_") and f" {test_name} " in line
    )
    body: list[str] = []
    for line in lines[header + 1 :]:
        if line.startswith("_") or line.startswith("="):
            break
        body.append(line)
    return "\n".join(body)


def test_an_unmarked_test_over_budget_is_failed_naming_the_key(
    pytester: pytest.Pytester,
) -> None:
    """A passing 50ms sleeper against a 10ms budget is FAILED, naming the test, its duration, the key and both remedies."""
    result = _run_probe(pytester)
    result.stdout.fnmatch_lines(["*test_budget_probe.py::test_unmarked_sleeper FAILED*"])
    body = _failure_section(result, "test_unmarked_sleeper")
    assert "test_budget_probe.py::test_unmarked_sleeper passed, but its call phase took" in body
    assert BUDGET_KEY in body
    assert "mark it slow" in body
    assert "make the test itself faster" in body


def test_a_failing_test_over_budget_keeps_its_own_failure(
    pytester: pytest.Pytester,
) -> None:
    """The assertion is what is reported; the budget message never replaces a real failure."""
    result = _run_probe(pytester)
    result.stdout.fnmatch_lines(["*test_budget_probe.py::test_failing_sleeper FAILED*"])
    body = _failure_section(result, "test_failing_sleeper")
    assert "AssertionError: the assertion, not the budget" in body
    assert BUDGET_KEY not in body


def test_a_slow_marked_test_and_a_fast_test_pass(pytester: pytest.Pytester) -> None:
    """The mark exempts a sleeper from the budget, and a test inside the budget is untouched."""
    result = _run_probe(pytester)
    result.stdout.fnmatch_lines(
        [
            "*test_budget_probe.py::test_slow_marked_sleeper PASSED*",
            "*test_budget_probe.py::test_fast PASSED*",
        ]
    )
