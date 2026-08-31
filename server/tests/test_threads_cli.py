"""The production caller for the thread derivation (story 10.2's missing half).

Story 10.2 built `domain/threads.py` and migration 0015 and tested both
thoroughly — and nothing in the running system ever called `derive_threads`.
No pipeline stage, no api route, no console script. Topics accumulated per
meeting from the `extract` stage while `thread` and `topic_thread` stayed
empty, so every thread-shaped surface read a corpus with no threads in it. The
existing suites all passed, because each one called the derivation itself.

So the first test here is structural and is the point of the module: **the
derivation has a caller outside the test suite.** A unit test that invokes the
function under test can never catch a function nothing invokes; only a test
that asks "who calls this in the shipped package?" can. The rest pin the CLI's
own refusal surface.
"""

from __future__ import annotations

import ast
import tomllib
from importlib import import_module
from pathlib import Path

import pytest

from meetingminer.domain import threads_cli

SERVER_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = SERVER_ROOT / "meetingminer"


def _modules_naming(symbol: str) -> set[str]:
    """Every shipped module that references `symbol`, by import or by call.

    Walks the package's ASTs rather than grepping, so a name inside a string or
    a comment is not mistaken for a caller — which matters here, because the
    docstrings of several modules discuss `derive_threads` by name while not
    calling it, and those references are exactly what made the gap look wired.
    """
    found: set[str] = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            if symbol in names:
                found.add(str(path.relative_to(PACKAGE_ROOT)))
    return found


def test_the_thread_derivation_has_a_caller_in_the_shipped_package() -> None:
    """The regression this module exists for: logic built and never called."""
    callers = _modules_naming("derive_threads")
    # The definition itself does not count as a caller.
    callers.discard("domain/threads.py")
    assert callers, (
        "nothing in meetingminer/ calls derive_threads — the thread tables stay"
        " empty however many topics the extract stage writes, and every"
        " thread-shaped surface reads a corpus with no threads in it"
    )


def test_the_console_script_is_registered_and_resolves() -> None:
    """A caller that is not reachable as a command is not reachable at all."""
    manifest = tomllib.loads((SERVER_ROOT / "pyproject.toml").read_text())
    scripts = manifest["project"]["scripts"]
    assert "derive-threads" in scripts, (
        "derive-threads is not registered in [project.scripts], so"
        " `make threads` has no command to run"
    )
    module_path, _, attribute = scripts["derive-threads"].partition(":")
    assert callable(getattr(import_module(module_path), attribute))


def test_threading_is_not_folded_into_rebuild() -> None:
    """`rebuild` regenerates the stores *from* Postgres and writes no primary data.

    Pinned because folding the derivation into `rebuild` is the obvious-looking
    fix for the gap above, and it would make that command a Postgres writer —
    quietly breaking the promise that a rebuild changes no primary data.
    """
    rebuild_cli = (PACKAGE_ROOT / "projections" / "cli.py").read_text()
    assert "derive_threads" not in rebuild_cli


def test_dry_run_is_offered() -> None:
    assert threads_cli._parser().parse_args(["--dry-run"]).dry_run is True
    assert threads_cli._parser().parse_args([]).dry_run is False


def test_no_per_meeting_scope_is_offered() -> None:
    """A thread is a subject followed *across* meetings, so scope is the corpus."""
    with pytest.raises(SystemExit):
        threads_cli._parser().parse_args(["--meeting", "whatever"])
