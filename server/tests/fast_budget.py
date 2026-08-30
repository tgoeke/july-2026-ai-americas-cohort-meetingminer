"""The fast-set budget and the slow-set rules (story 11.1): a pytest plugin.

Loaded by ``server/tests/conftest.py`` through ``pytest_plugins``.
``server/pyproject.toml`` defaults every run to ``-m "not slow"``; this module
keeps that selection honest in three ways.

**The budget.** A test that passes, carries no ``slow`` mark, and spends
longer than ``mm_fast_test_budget_seconds`` in its call phase is reported
failed, naming the test, its duration, the key, and the remedies. Call phase
only: fixture setup (the per-run database, migrations, store wipes) amortises
across the run and is not what the budget guards. A failing test keeps its
own failure — the budget never replaces one — a ``slow``-marked test is exempt
whichever selection ran it, and a non-strict ``xfail`` that unexpectedly
passes is left alone. Every real run takes the value from pyproject, where
its rationale lives; the ``addini`` default below applies only to a run that
loads this plugin without ``server/pyproject.toml`` — the inner run
``test_fast_budget.py`` drives. Override it for one run with
``-o mm_fast_test_budget_seconds=<seconds>``. The value is validated once, in
``pytest_configure``: not a number, NaN, infinite, or non-positive is a usage
error naming the key and the value.

**Two structural rules**, checked at collection over every collected item
(before the marker expression deselects any) and reported as one usage error
listing every offending node id — never a silent mark: every ``slow`` mark
carries a non-empty ``reason=``, and a test with no ``slow`` mark may not
request ``projection_stores`` or ``stores_up`` — a twin-bound test belongs in
the slow set. The collection check reads each item's static fixture closure,
which a ``request.getfixturevalue("projection_stores")`` inside the test body
is not part of, so the twin rule is enforced twice more for that path. When
either fixture is set up, an unmarked requester fails before the fixture
function runs; the failure is cached the way pytest caches one and torn down
with that test, so a later ``slow`` test sets the fixture up normally. And
when an unmarked test's setup or call is reported, the twins its request
resolved are checked — the case the setup hook cannot see: ``stores_up`` is
session-scoped, and a request for it after a ``slow`` test set it up is
served from the cache without any setup. That check does not depend on the
outcome the test earned: a passed, skipped, xfailed or xpassed report
becomes a failure carrying the diagnostic and the outcome it replaces (an
error at setup, when one of the test's own fixtures asked), and a report
that already failed keeps its failure, with the diagnostic added as a
section unless it is that failure. The setup hook's refusal counts as a
resolved twin for the same reason: an ``xfail`` mark would otherwise absorb
it into a green XFAIL. The collection check stays because it names every
offender at once before anything runs; the other two are the backstops for
the dynamic path.

**The by-path hint.** The collection hook also records whether every
collected item carried ``slow`` — the case where the default expression alone
empties the run. When it did, no ``-k`` was given, the expression is the
default, and the session ends with nothing collected, one line says to pass
``-m ""``. A ``-k`` miss, or a path with nothing slow in it, gets no hint:
clearing the marker expression would not help there.
"""

from __future__ import annotations

import functools
import math
from typing import Generator, Iterable

import pytest

_FAST_TEST_BUDGET_KEY = "mm_fast_test_budget_seconds"
_BUDGET = pytest.StashKey[float]()
_ALL_SLOW = pytest.StashKey[bool]()
# Every collected node id that carried `slow` when the collection hook below
# ran (first, before deselection), however the mark got there — a decorator,
# a module or class `pytestmark`, `pytest.param(marks=...)` — for the
# contract in test_compose_contract.py that requires each to be pinned.
_SLOW_NODEIDS = pytest.StashKey[frozenset[str]]()
_TWIN_FIXTURES = frozenset({"projection_stores", "stores_up"})
# On an item: the setup hook refused a twin request from it — a resolved twin
# for the report-time check, which no outcome the test earns afterwards
# (an xfail mark absorbing the refusal, say) may hide.
_TWIN_REFUSED = pytest.StashKey[bool]()
# On an item: one of its reports already carries the twin diagnostic, so the
# later phases of the same item leave their reports alone.
_TWIN_REPORTED = pytest.StashKey[bool]()
_TWIN_SECTION = "fast_budget: the twin rule"
_AT_RUN_TIME = " (requested at run time)"
_DEFAULT_MARK_EXPRESSION = "not slow"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        _FAST_TEST_BUDGET_KEY,
        help="seconds an unmarked test's call phase may take before it is reported failed (story 11.1)",
        default="2.0",
    )


def pytest_configure(config: pytest.Config) -> None:
    raw = config.getini(_FAST_TEST_BUDGET_KEY)
    try:
        budget = float(raw)
    except (TypeError, ValueError):
        budget = math.nan
    if not math.isfinite(budget) or budget <= 0:
        raise pytest.UsageError(
            f"{_FAST_TEST_BUDGET_KEY} must be a positive, finite number of seconds; got {raw!r}"
        )
    config.stash[_BUDGET] = budget


def _has_reason(mark: pytest.Mark) -> bool:
    reason = mark.kwargs.get("reason")
    return isinstance(reason, str) and bool(reason.strip())


def _twin_rule(nodeids: Iterable[str]) -> str:
    """The one diagnostic for the twin rule, whichever check raised it."""
    return (
        "a test that requests projection_stores or stores_up is bound by the test "
        "twins and belongs in the slow set; add @pytest.mark.slow(reason=...) to: "
        + ", ".join(nodeids)
    )


def _requesting_item(request: pytest.FixtureRequest) -> pytest.Item:
    """The test whose request is setting a fixture up.

    ``request.node`` is the node of the fixture's scope — the item for a
    function-scoped fixture, the session for ``stores_up`` — while the test
    that asked is ``_pyfuncitem`` on every request scope; pytest exposes no
    public name for it, and the pin in server/pyproject.toml is what makes
    the private one safe. Its absence is an error, never a silently skipped
    check.
    """
    item = getattr(request, "_pyfuncitem", None)
    if not isinstance(item, pytest.Item):
        raise RuntimeError(
            f"fast_budget: pytest {pytest.__version__} gives this request no _pyfuncitem, "
            "so the twin rule cannot find the requesting test; see _requesting_item"
        )
    return item


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    unreasoned: list[str] = []
    twin_bound: list[str] = []
    slow_nodeids: set[str] = set()
    for item in items:
        marks = list(item.iter_markers("slow"))
        if marks and not all(_has_reason(mark) for mark in marks):
            unreasoned.append(item.nodeid)
        if marks:
            slow_nodeids.add(item.nodeid)
        elif _TWIN_FIXTURES & set(getattr(item, "fixturenames", ())):
            twin_bound.append(item.nodeid)
    config.stash[_SLOW_NODEIDS] = frozenset(slow_nodeids)
    config.stash[_ALL_SLOW] = bool(items) and len(slow_nodeids) == len(items)
    problems: list[str] = []
    if unreasoned:
        problems.append(
            "every slow mark needs a non-empty reason= naming what outside the test "
            "process sets its duration, and the measured cost; missing on: "
            + ", ".join(unreasoned)
        )
    if twin_bound:
        problems.append(_twin_rule(twin_bound))
    if problems:
        raise pytest.UsageError("\n".join(problems))


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_setup(
    fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest
) -> None:
    """The twin rule again, as the fixture is set up: catches a request the
    static closure does not show (``request.getfixturevalue``). Runs before
    pytest's own setup implementation, so failing here means the fixture
    function never ran. Returns None otherwise so that implementation runs.

    The failure is recorded the way pytest's own implementation records one:
    ``FixtureDef.execute`` registers the post-finalizer before it calls this
    hook, and ``FixtureDef.finish`` returns early while ``cached_result`` is
    None — leaving that finalizer behind for the next requester to trip over
    — so the exception is cached, and the cache is torn down with the
    offending test rather than with the fixture's scope, so a later ``slow``
    test sets a session-scoped ``stores_up`` up afresh.
    """
    if fixturedef.argname not in _TWIN_FIXTURES:
        return
    item = _requesting_item(request)
    if item.get_closest_marker("slow") is not None:
        return
    # Named: the test, not the fixture — `projection_stores` resolves `stores_up`
    # first, so the fixture being set up need not be the one the test asked for.
    failure = pytest.fail.Exception(_twin_rule([item.nodeid]) + _AT_RUN_TIME, pytrace=False)
    fixturedef.cached_result = (None, fixturedef.cache_key(request), (failure, None))
    item.addfinalizer(functools.partial(fixturedef.finish, request=request))
    item.stash[_TWIN_REFUSED] = True
    raise failure


def _twins_resolved_for(item: pytest.Item) -> set[str]:
    """The twin fixtures this test's request resolved, statically or at run time.

    ``Function._request`` is the item's request and ``_fixture_defs`` every
    fixture it resolved — including one ``getfixturevalue`` found already
    cached, which the setup hook never saw. Both names are private; pytest
    keeps no public record of run-time requests.
    """
    request = getattr(item, "_request", None)
    resolved = getattr(request, "_fixture_defs", None)
    return _TWIN_FIXTURES & set(resolved or ())


def _twin_bound(item: pytest.Item) -> bool:
    """Whether this test's request reached a twin: resolved one, or was refused one by the setup hook."""
    return item.stash.get(_TWIN_REFUSED, False) or bool(_twins_resolved_for(item))


def _earned_outcome(report: pytest.TestReport) -> str:
    """The outcome pytest gave this report, in the terminal's words."""
    if hasattr(report, "wasxfail"):
        return "xfailed" if report.skipped else "xpassed"
    return report.outcome


def _twin_failure(item: pytest.Item, report: pytest.TestReport) -> pytest.TestReport:
    """The report of an unmarked twin-bound test, made a failure whatever it was.

    A failure the test earned on its own is kept, with the diagnostic added
    as a section — unless the failure is the setup hook's refusal, which
    already reads the same. Every other outcome, including a skip, an xfail
    and an xpass, is replaced by the diagnostic, which names the outcome it
    replaces; ``wasxfail`` goes with it, or the terminal would still print
    the report as XFAIL.
    """
    diagnosis = _twin_rule([item.nodeid]) + _AT_RUN_TIME
    if report.failed:
        if _AT_RUN_TIME not in str(report.longrepr):
            report.sections.append((_TWIN_SECTION, diagnosis))
        return report
    earned = _earned_outcome(report)
    if hasattr(report, "wasxfail"):
        del report.wasxfail
    report.outcome = "failed"
    report.longrepr = f"{diagnosis}; this replaces the test's own {report.when} outcome ({earned})"
    return report


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if call.when == "teardown" or item.get_closest_marker("slow") is not None:
        return report
    if item.stash.get(_TWIN_REPORTED, False):
        return report
    if _twin_bound(item):
        item.stash[_TWIN_REPORTED] = True
        return _twin_failure(item, report)
    if call.when != "call" or not report.passed or hasattr(report, "wasxfail"):
        return report
    budget = item.config.stash[_BUDGET]
    if call.duration <= budget:
        return report
    report.outcome = "failed"
    report.longrepr = (
        f"{item.nodeid} passed, but its call phase took {call.duration:.2f}s "
        f"against the {budget:.2f}s fast-set budget ({_FAST_TEST_BUDGET_KEY} in "
        "server/pyproject.toml). Either mark it slow with a reason — "
        "`@pytest.mark.slow(reason=...)`, or a module-level `pytestmark` when the "
        "whole file is bound by a store, a spawned process, or a timer — so the "
        "default run deselects it, or make the test itself faster. If it only "
        "exceeds the budget while another suite, a rebuild, or the worker is "
        "running, re-run it alone before marking it slow: contention is not a "
        "reason to mark."
    )
    return report


def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    config = session.config
    if exitstatus != pytest.ExitCode.NO_TESTS_COLLECTED:
        return
    if config.option.markexpr != _DEFAULT_MARK_EXPRESSION or config.option.keyword:
        return
    if not config.stash.get(_ALL_SLOW, False):
        return
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    reporter.write_line(
        'every collected test was deselected by the default -m "not slow" (addopts '
        'in server/pyproject.toml); a slow module run by path needs -m "" on the '
        "command line.",
        yellow=True,
    )
