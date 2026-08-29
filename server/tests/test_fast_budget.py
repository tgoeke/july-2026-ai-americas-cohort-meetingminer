"""The fast_budget plugin (story 11.1), driven through inner pytest runs.

``pytester`` runs probe files in a scratch directory that carries its own
empty ``[pytest]`` ini — so the inner rootdir can never climb to
``server/pyproject.toml`` — with ``fast_budget`` loaded and the budget set to
0.05s: 0.2s sleepers are four times over it, and each outer test's own call
phase stays several times under the real 2.0s budget it runs under.
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
    time.sleep(0.2)


def test_failing_sleeper():
    time.sleep(0.2)
    assert False, "the assertion, not the budget"


@pytest.mark.slow(reason="probe")
def test_slow_marked_sleeper():
    time.sleep(0.2)


def test_fast():
    assert True
'''

NO_REASON_PROBE = '''
import pytest


@pytest.mark.slow
def test_bare_slow_mark():
    pass
'''

TWIN_PROBE = '''
import pytest


@pytest.fixture()
def projection_stores():
    return None


def test_unmarked_twin_user(projection_stores):
    pass
'''


def _inner_run(pytester: pytest.Pytester, **probe_files: str) -> pytest.RunResult:
    """One in-process pytest over the probe files, fast_budget loaded, budget 0.05s."""
    pytester.makeini("[pytest]")
    pytester.syspathinsert(TESTS_DIR)
    pytester.makepyfile(**probe_files)
    return pytester.runpytest_inprocess(
        "-p", "fast_budget",
        "-p", "no:cacheprovider",
        "-o", f"{BUDGET_KEY}=0.05",
        "-o", "markers=slow: probe",
        "-v",
    )


def _run_probe(pytester: pytest.Pytester) -> pytest.RunResult:
    """The four-test probe; two of its tests must fail."""
    result = _inner_run(pytester, test_budget_probe=PROBE)
    result.assert_outcomes(passed=2, failed=2)
    return result


def _failure_section(result: pytest.RunResult, test_name: str) -> str:
    """One test's block in FAILURES: from its underscored header to the next header or section rule."""
    lines = result.outlines
    header = next(
        (i for i, line in enumerate(lines) if line.startswith("_") and f" {test_name} " in line),
        None,
    )
    assert header is not None, f"no FAILURES block for {test_name} in:\n" + "\n".join(lines)
    body: list[str] = []
    for line in lines[header + 1 :]:
        if line.startswith("_") or line.startswith("="):
            break
        body.append(line)
    return "\n".join(body)


def test_the_real_session_loads_fast_budget_from_conftest(
    request: pytest.FixtureRequest,
) -> None:
    """conftest's pytest_plugins registers the plugin and pyproject supplies the 2.0s budget."""
    assert request.config.pluginmanager.hasplugin("fast_budget")
    assert float(request.config.getini(BUDGET_KEY)) == 2.0


def test_an_unmarked_test_over_budget_is_failed_naming_the_key(
    pytester: pytest.Pytester,
) -> None:
    """A passing 0.2s sleeper against a 0.05s budget is FAILED, naming the test, its duration, the key and the remedies."""
    result = _run_probe(pytester)
    result.stdout.fnmatch_lines(["*test_budget_probe.py::test_unmarked_sleeper FAILED*"])
    body = _failure_section(result, "test_unmarked_sleeper")
    assert "test_budget_probe.py::test_unmarked_sleeper passed, but its call phase took" in body
    assert BUDGET_KEY in body
    assert "mark it slow" in body
    assert "make the test itself faster" in body
    assert "re-run it alone" in body


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


def test_a_slow_mark_without_a_reason_stops_collection(pytester: pytest.Pytester) -> None:
    """A bare `@pytest.mark.slow` is a usage error naming the node id; nothing is marked silently."""
    result = _inner_run(pytester, test_no_reason_probe=NO_REASON_PROBE)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*reason=*test_no_reason_probe.py::test_bare_slow_mark*"])


def test_an_unmarked_test_requesting_the_twins_stops_collection(
    pytester: pytest.Pytester,
) -> None:
    """A test whose fixture closure names projection_stores must carry a slow mark."""
    result = _inner_run(pytester, test_twin_probe=TWIN_PROBE)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(
        ["*projection_stores*test_twin_probe.py::test_unmarked_twin_user*"]
    )
