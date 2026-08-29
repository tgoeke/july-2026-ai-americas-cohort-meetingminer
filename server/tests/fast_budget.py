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
the slow set.

**The by-path hint.** When the default ``-m "not slow"`` deselects every
collected test (a ``slow`` module run by path), the session still exits 5,
and one line says to pass ``-m ""``.
"""

from __future__ import annotations

import math
from typing import Generator

import pytest

_FAST_TEST_BUDGET_KEY = "mm_fast_test_budget_seconds"
_BUDGET = pytest.StashKey[float]()
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


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    unreasoned: list[str] = []
    twin_bound: list[str] = []
    for item in items:
        marks = list(item.iter_markers("slow"))
        if marks and not all(_has_reason(mark) for mark in marks):
            unreasoned.append(item.nodeid)
        if not marks and _TWIN_FIXTURES & set(getattr(item, "fixturenames", ())):
            twin_bound.append(item.nodeid)
    problems: list[str] = []
    if unreasoned:
        problems.append(
            "every slow mark needs a non-empty reason= naming what outside the test "
            "process sets its duration, and the measured cost; missing on: "
            + ", ".join(unreasoned)
        )
    if twin_bound:
        problems.append(
            "a test that requests projection_stores or stores_up is bound by the test "
            "twins and belongs in the slow set; add @pytest.mark.slow(reason=...) to: "
            + ", ".join(twin_bound)
        )
    if problems:
        raise pytest.UsageError("\n".join(problems))


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
    if exitstatus != pytest.ExitCode.NO_TESTS_COLLECTED:
        return
    if session.config.option.markexpr != _DEFAULT_MARK_EXPRESSION:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None or not reporter.stats.get("deselected"):
        return
    reporter.write_line(
        'every collected test was deselected by the default -m "not slow" (addopts '
        'in server/pyproject.toml); a slow module run by path needs -m "" on the '
        "command line.",
        yellow=True,
    )
