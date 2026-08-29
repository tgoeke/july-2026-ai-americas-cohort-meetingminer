"""The fast_budget plugin (story 11.1), driven through inner pytest runs.

``pytester`` runs probe files in a scratch directory that carries its own
empty ``[pytest]`` ini — so the inner rootdir can never climb to
``server/pyproject.toml`` — with ``fast_budget`` loaded and the budget set to
0.05s: 0.2s sleepers are four times over it, and each outer test's own call
phase stays several times under the real 2.0s budget it runs under.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from fast_budget import _BUDGET

TESTS_DIR = Path(__file__).resolve().parent
BUDGET_KEY = "mm_fast_test_budget_seconds"
DEFAULT_ADDOPTS = ("-o", "addopts=-m 'not slow'")
HINT = 'deselected by the default -m "not slow"'

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

XPASS_PROBE = '''
import time

import pytest


@pytest.mark.xfail(reason="probe: declared failing, passes instead", strict=False)
def test_xpass_sleeper():
    time.sleep(0.2)
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

SLOW_ONLY_PROBE = '''
import pytest


@pytest.mark.slow(reason="probe")
def test_only_slow():
    pass
'''

TRIVIAL_PROBE = '''
def test_trivial():
    assert True
'''


def _inner_run(
    pytester: pytest.Pytester, *extra_args: str, budget: str = "0.05", **probe_files: str
) -> pytest.RunResult:
    """One in-process pytest over the probe files, fast_budget loaded, the budget given."""
    pytester.makeini("[pytest]")
    pytester.syspathinsert(TESTS_DIR)
    pytester.makepyfile(**probe_files)
    return pytester.runpytest_inprocess(
        "-p", "fast_budget",
        "-p", "no:cacheprovider",
        "-o", f"{BUDGET_KEY}={budget}",
        "-o", "markers=slow: probe",
        "-v",
        *extra_args,
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
    """conftest's pytest_plugins registers the plugin, and the budget it configured is a valid number — whatever the ini or a `-o` override said."""
    assert request.config.pluginmanager.hasplugin("fast_budget")
    configured = request.config.stash[_BUDGET]
    assert math.isfinite(configured) and configured > 0
    assert configured == float(request.config.getini(BUDGET_KEY))


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


def test_a_non_strict_xfail_that_passes_over_budget_keeps_its_xpass(
    pytester: pytest.Pytester,
) -> None:
    """An unexpected pass on a non-strict xfail is reported as XPASS, never flipped into a budget failure."""
    result = _inner_run(pytester, test_xpass_probe=XPASS_PROBE)
    result.assert_outcomes(xpassed=1)
    assert BUDGET_KEY not in result.stdout.str()


@pytest.mark.parametrize("value", ["abc", "nan", "inf", "0", "-1"])
def test_an_invalid_budget_is_a_usage_error_naming_the_key_and_value(
    pytester: pytest.Pytester, value: str
) -> None:
    """Not a number, NaN, infinite, zero or negative: the run stops at configure time with the key and the offending value."""
    result = _inner_run(pytester, budget=value, test_trivial_probe=TRIVIAL_PROBE)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    stderr = result.stderr.str()
    assert BUDGET_KEY in stderr
    assert repr(value) in stderr


def test_a_valid_non_default_budget_is_accepted(pytester: pytest.Pytester) -> None:
    """The documented `-o` override with any positive finite value configures the run."""
    result = _inner_run(pytester, budget="3.5", test_trivial_probe=TRIVIAL_PROBE)
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("selection", [("-m", "not slow"), DEFAULT_ADDOPTS], ids=["cli", "addopts"])
def test_a_slow_mark_without_a_reason_stops_collection(
    pytester: pytest.Pytester, selection: tuple[str, str]
) -> None:
    """A bare `@pytest.mark.slow` is a usage error naming the node id, also when the default `not slow` expression would have deselected it first."""
    result = _inner_run(pytester, *selection, test_no_reason_probe=NO_REASON_PROBE)
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


def test_a_slow_only_path_under_the_default_selection_prints_the_hint(
    pytester: pytest.Pytester,
) -> None:
    """Every collected test carried `slow`, the default expression removed them all: exit 5 and the `-m ""` hint."""
    result = _inner_run(pytester, *DEFAULT_ADDOPTS, test_slow_only_probe=SLOW_ONLY_PROBE)
    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    result.stdout.fnmatch_lines([f"*{HINT}*"])


def test_a_keyword_miss_on_a_fast_file_exits_5_without_the_hint(
    pytester: pytest.Pytester,
) -> None:
    """`-k` emptied a fast file, not the marker expression: exit 5, and no hint that clearing `-m` would help."""
    result = _inner_run(
        pytester, *DEFAULT_ADDOPTS, "-k", "nomatch", test_trivial_probe=TRIVIAL_PROBE
    )
    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    assert HINT not in result.stdout.str()
