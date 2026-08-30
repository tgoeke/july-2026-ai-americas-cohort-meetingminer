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

from fast_budget import _BUDGET, _TWIN_FIXTURES, _TWIN_SECTION

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

# The twin fixtures requested at run time — outside every test's static
# fixture closure, so the collection rule cannot see them. The fakes have
# conftest's shape (`stores_up` per session, `projection_stores` per test and
# depending on it; `test_the_real_session_loads_fast_budget_from_conftest`
# pins those scopes) and record each run, so a probe can read how often the
# fixture it asked for actually ran.
TWIN_PROBE_CONFTEST = '''
import pytest

RAN = []


@pytest.fixture(scope="session")
def stores_up():
    RAN.append("stores_up")


@pytest.fixture()
def projection_stores(stores_up):
    RAN.append("projection_stores")
'''

# Unmarked requesters first: from the test body, and from a fixture of the
# test's own. Neither fixture has run when the middle test looks, and the
# marked requester afterwards sets it up normally.
UNMARKED_FIRST_PROBE = '''
import pytest

from conftest import RAN


def test_unmarked_dynamic_twin_user(request):
    request.getfixturevalue("FIXTURE")


@pytest.fixture()
def helper(request):
    request.getfixturevalue("FIXTURE")


def test_unmarked_via_its_own_fixture(helper):
    pass


def test_the_twin_fixture_never_ran():
    assert RAN == []


@pytest.mark.slow(reason="probe")
def test_marked_dynamic_twin_user(request):
    request.getfixturevalue("FIXTURE")
    assert RAN.count("FIXTURE") == 1
'''

# A slow module first, so a session-scoped fixture is cached when the
# unmarked test asks: that request never reaches fixture setup, and the
# report-time check is what fails it. The fixture ran once, for the slow test.
MARKED_FIRST_PROBE = '''
import pytest

from conftest import RAN

pytestmark = pytest.mark.slow(reason="probe")


def test_module_marked_dynamic_twin_user(request):
    request.getfixturevalue("FIXTURE")
    assert RAN.count("FIXTURE") == 1
'''

UNMARKED_AFTER_PROBE = '''
from conftest import RAN


def test_unmarked_dynamic_twin_user_after_a_slow_test(request):
    request.getfixturevalue("FIXTURE")


def test_the_twin_fixture_ran_once_for_the_slow_test():
    assert RAN.count("FIXTURE") == 1
'''

# After the slow module: unmarked requesters that earn no passing call
# report. One skips, one xfails and one xpasses after its request; two ask
# through a fixture of their own, so the request lands at setup, and one of
# those skips there; one fails its own assertion after the request. Under
# the session-scoped twin every request is served from the cache; under the
# function-scoped one each is refused by the setup hook.
UNMARKED_NON_PASSING_PROBE = '''
import pytest

from conftest import RAN


def test_unmarked_request_then_skip(request):
    request.getfixturevalue("FIXTURE")
    pytest.skip("probe: skipped after the request")


def test_unmarked_request_then_xfail(request):
    request.getfixturevalue("FIXTURE")
    pytest.xfail("probe: xfailed after the request")


@pytest.mark.xfail(reason="probe: declared failing, passes instead", strict=False)
def test_unmarked_request_then_xpass(request):
    request.getfixturevalue("FIXTURE")


@pytest.fixture()
def helper(request):
    request.getfixturevalue("FIXTURE")


def test_unmarked_request_from_its_own_fixture(helper):
    pass


@pytest.fixture()
def helper_then_skip(request):
    request.getfixturevalue("FIXTURE")
    pytest.skip("probe: skipped at setup")


def test_unmarked_request_from_its_own_fixture_then_skip(helper_then_skip):
    pass


def test_unmarked_request_then_assertion(request):
    request.getfixturevalue("FIXTURE")
    assert False, "the assertion, not the twin rule"


def test_the_twin_fixture_ran_once_for_the_slow_test():
    assert RAN.count("FIXTURE") == 1
'''

TWIN_SCOPES = {"projection_stores": "function", "stores_up": "session"}
AT_RUN_TIME = "(requested at run time)"

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
    """conftest's pytest_plugins registers the plugin, the budget it configured is a valid number — whatever the ini or a `-o` override said — and the real twin fixtures have the scopes the probes mirror."""
    assert request.config.pluginmanager.hasplugin("fast_budget")
    configured = request.config.stash[_BUDGET]
    assert math.isfinite(configured) and configured > 0
    assert configured == float(request.config.getini(BUDGET_KEY))
    assert set(TWIN_SCOPES) == _TWIN_FIXTURES
    for name, scope in TWIN_SCOPES.items():
        fixturedefs = request.session._fixturemanager.getfixturedefs(name, request.node)
        assert fixturedefs, f"no fixture {name!r} visible from {request.node.nodeid}"
        assert fixturedefs[-1].scope == scope, (name, fixturedefs[-1].scope)


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


def _twin_probe_run(pytester: pytest.Pytester, fixture: str, **probe_files: str) -> pytest.RunResult:
    """One inner run over the probe files with FIXTURE substituted, the fake twins in its conftest."""
    pytester.makeconftest(TWIN_PROBE_CONFTEST)
    files = {name: text.replace("FIXTURE", fixture) for name, text in probe_files.items()}
    return _inner_run(pytester, **files)


@pytest.mark.parametrize("fixture", sorted(_TWIN_FIXTURES))
def test_an_unmarked_test_requesting_a_twin_at_run_time_is_stopped_before_it_runs(
    pytester: pytest.Pytester, fixture: str
) -> None:
    """`request.getfixturevalue` bypasses the closure the collection rule reads: the setup-time backstop fails the unmarked test (an error at setup when one of its own fixtures asked), naming it, the fixture never runs, and a slow-marked test may still request it the same way."""
    result = _twin_probe_run(pytester, fixture, test_dynamic_twin_probe=UNMARKED_FIRST_PROBE)
    result.stdout.fnmatch_lines(
        [
            "*test_dynamic_twin_probe.py::test_unmarked_dynamic_twin_user FAILED*",
            "*test_dynamic_twin_probe.py::test_unmarked_via_its_own_fixture ERROR*",
            "*test_dynamic_twin_probe.py::test_the_twin_fixture_never_ran PASSED*",
            "*test_dynamic_twin_probe.py::test_marked_dynamic_twin_user PASSED*",
        ]
    )
    result.assert_outcomes(passed=2, failed=1, errors=1)
    for test_name in ("test_unmarked_dynamic_twin_user", "test_unmarked_via_its_own_fixture"):
        body = _failure_section(result, test_name)
        assert f"test_dynamic_twin_probe.py::{test_name}" in body
        assert "@pytest.mark.slow(reason=...)" in body
        assert AT_RUN_TIME in body


@pytest.mark.parametrize("fixture", sorted(_TWIN_FIXTURES))
def test_an_unmarked_test_requesting_a_twin_a_slow_test_already_set_up_is_failed(
    pytester: pytest.Pytester, fixture: str
) -> None:
    """After a slow module set the fixture up, a session-scoped one is served from the cache with no setup for the setup hook to see: the unmarked test is failed when it is reported, with the same diagnostic. The fixture ran once, for the slow test."""
    result = _twin_probe_run(
        pytester,
        fixture,
        test_a_marked_module_probe=MARKED_FIRST_PROBE,
        test_b_unmarked_after_probe=UNMARKED_AFTER_PROBE,
    )
    result.stdout.fnmatch_lines(
        [
            "*test_a_marked_module_probe.py::test_module_marked_dynamic_twin_user PASSED*",
            "*test_b_unmarked_after_probe.py::test_unmarked_dynamic_twin_user_after_a_slow_test FAILED*",
            "*test_b_unmarked_after_probe.py::test_the_twin_fixture_ran_once_for_the_slow_test PASSED*",
        ]
    )
    result.assert_outcomes(passed=2, failed=1)
    body = _failure_section(result, "test_unmarked_dynamic_twin_user_after_a_slow_test")
    assert "test_b_unmarked_after_probe.py::test_unmarked_dynamic_twin_user_after_a_slow_test" in body
    assert AT_RUN_TIME in body


@pytest.mark.parametrize("fixture", sorted(_TWIN_FIXTURES))
def test_an_unmarked_twin_request_is_failed_whatever_outcome_the_test_earned(
    pytester: pytest.Pytester, fixture: str
) -> None:
    """The report-time check must not wait for a passing call. Session-scoped twin, served from the cache with no setup hook to see it: an unmarked test that skips, xfails or xpasses after its request is FAILED with the diagnostic, the outcome it earned and that outcome's reason; a request from one of its own fixtures is an ERROR at setup, whether the fixture then passed or skipped, so the body never runs; a test that then fails its own assertion keeps that failure, with the diagnostic printed once beside it. Function-scoped twin, set up afresh and refused by the setup hook: the refusal is the failure, printed once with nothing added — and under the xfail mark, which absorbed the refusal into a green XFAIL before the refusal counted as a resolved twin, the report says so. The fixture ran once, for the slow test."""
    result = _twin_probe_run(
        pytester,
        fixture,
        test_a_marked_module_probe=MARKED_FIRST_PROBE,
        test_b_non_passing_probe=UNMARKED_NON_PASSING_PROBE,
    )
    result.stdout.fnmatch_lines(
        [
            "*test_a_marked_module_probe.py::test_module_marked_dynamic_twin_user PASSED*",
            "*test_b_non_passing_probe.py::test_unmarked_request_then_skip FAILED*",
            "*test_b_non_passing_probe.py::test_unmarked_request_then_xfail FAILED*",
            "*test_b_non_passing_probe.py::test_unmarked_request_then_xpass FAILED*",
            "*test_b_non_passing_probe.py::test_unmarked_request_from_its_own_fixture ERROR*",
            "*test_b_non_passing_probe.py::test_unmarked_request_from_its_own_fixture_then_skip ERROR*",
            "*test_b_non_passing_probe.py::test_unmarked_request_then_assertion FAILED*",
            "*test_b_non_passing_probe.py::test_the_twin_fixture_ran_once_for_the_slow_test PASSED*",
        ]
    )
    result.assert_outcomes(passed=2, failed=4, errors=2)
    cached = TWIN_SCOPES[fixture] == "session"
    replaced = {
        "test_unmarked_request_then_skip": (
            "this replaces the test's own call outcome (skipped: Skipped: probe: skipped after the request)"
        ),
        "test_unmarked_request_then_xfail": (
            "this replaces the test's own call outcome (xfailed: probe: xfailed after the request)"
        ),
        "test_unmarked_request_then_xpass": (
            "this replaces the test's own call outcome (xpassed: probe: declared failing, passes instead)"
        ),
        "test_unmarked_request_from_its_own_fixture": "this replaces the test's own setup outcome (passed)",
        "test_unmarked_request_from_its_own_fixture_then_skip": (
            "this replaces the test's own setup outcome (skipped: Skipped: probe: skipped at setup)"
        ),
    }
    absorbed = (
        "the refusal was absorbed into the test's own call outcome "
        "(xfailed: probe: declared failing, passes instead)"
    )
    for test_name, replacement in replaced.items():
        body = _failure_section(result, test_name)
        assert f"test_b_non_passing_probe.py::{test_name}" in body
        assert body.count(AT_RUN_TIME) == 1, body
        if cached:
            assert replacement in body
        elif test_name.endswith("xpass"):
            assert absorbed in body
        else:
            assert "this replaces" not in body and "absorbed" not in body
        assert _TWIN_SECTION not in body
    body = _failure_section(result, "test_unmarked_request_then_assertion")
    assert body.count(AT_RUN_TIME) == 1, body
    if cached:
        assert "AssertionError: the assertion, not the twin rule" in body
        assert _TWIN_SECTION in body
    else:
        assert _TWIN_SECTION not in body


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
