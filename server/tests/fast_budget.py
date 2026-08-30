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
is not part of, so the twin rule is enforced a second time when either
fixture is set up: an unmarked requester fails there, before the fixture
function runs and before anything is cached, so a later ``slow`` test sets the
fixture up normally. The collection check stays because it names every
offender at once before anything runs; the setup check is the backstop for
the dynamic path. ``stores_up`` is session-scoped, so its setup check fires
for the first request of the session — a cached ``stores_up`` is a skip gate
that already passed, not the wiping fixture, which is ``projection_stores``,
per test.

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
_TWIN_FIXTURES = frozenset({"projection_stores", "stores_up"})
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


def _requesting_item(request: pytest.FixtureRequest) -> pytest.Item | None:
    """The test whose request is setting a fixture up.

    ``request.node`` is the node of the fixture's scope — the item for a
    function-scoped fixture, the session for ``stores_up`` — while the test
    that asked is ``_pyfuncitem`` on every request scope; pytest exposes no
    public name for it. A request with neither is not a test's (nothing to
    check).
    """
    item = getattr(request, "_pyfuncitem", None)
    if isinstance(item, pytest.Item):
        return item
    node = request.node
    return node if isinstance(node, pytest.Item) else None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    unreasoned: list[str] = []
    twin_bound: list[str] = []
    unmarked_seen = False
    for item in items:
        marks = list(item.iter_markers("slow"))
        if marks and not all(_has_reason(mark) for mark in marks):
            unreasoned.append(item.nodeid)
        if not marks:
            unmarked_seen = True
            if _TWIN_FIXTURES & set(getattr(item, "fixturenames", ())):
                twin_bound.append(item.nodeid)
    config.stash[_ALL_SLOW] = bool(items) and not unmarked_seen
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
    if item is None or item.get_closest_marker("slow") is not None:
        return
    failure = pytest.fail.Exception(
        _twin_rule([item.nodeid]) + f" (requested {fixturedef.argname} at run time)",
        pytrace=False,
    )
    fixturedef.cached_result = (None, fixturedef.cache_key(request), (failure, None))
    item.addfinalizer(functools.partial(fixturedef.finish, request=request))
    raise failure


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if call.when != "call" or not report.passed or hasattr(report, "wasxfail"):
        return report
    if item.get_closest_marker("slow") is not None:
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
