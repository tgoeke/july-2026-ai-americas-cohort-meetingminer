"""The fast-set budget (story 11.1): a pytest plugin, loaded by conftest.

``server/pyproject.toml`` defaults every run to ``-m "not slow"``; this hook
keeps that selection fast. A test that passes, carries no ``slow`` mark, and
spends longer than ``mm_fast_test_budget_seconds`` in its call phase is
reported failed, naming the test, its duration, the key, and the two
remedies. The value and its rationale live in pyproject; this module reads
it and nothing else.

Call phase only: fixture setup (the per-run database, migrations, store
wipes) amortises across the run and is not what the budget guards. A failing
test keeps its own failure — the budget never replaces one — and a
``slow``-marked test is exempt whichever selection ran it.
"""

from __future__ import annotations

from typing import Generator

import pytest

_FAST_TEST_BUDGET_KEY = "mm_fast_test_budget_seconds"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        _FAST_TEST_BUDGET_KEY,
        help="seconds an unmarked test's call phase may take before it is reported failed (story 11.1)",
        default="2.0",
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if call.when != "call" or not report.passed or item.get_closest_marker("slow"):
        return report
    budget = float(item.config.getini(_FAST_TEST_BUDGET_KEY))
    if call.duration <= budget:
        return report
    report.outcome = "failed"
    report.longrepr = (
        f"{item.nodeid} passed, but its call phase took {call.duration:.2f}s "
        f"against the {budget:.1f}s fast-set budget ({_FAST_TEST_BUDGET_KEY} in "
        "server/pyproject.toml). Either mark it slow with a reason — "
        "`@pytest.mark.slow(reason=...)`, or a module-level `pytestmark` when the "
        "whole file is bound by a store, a spawned process, or a timer — so the "
        "default run deselects it, or make the test itself faster."
    )
    return report
