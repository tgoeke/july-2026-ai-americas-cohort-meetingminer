"""infra/docker-compose.yml contract (story 1.10, findings 20-21), plus the
Makefile test recipes and pytest options the fast/full split rests on (11.1).

Static assertions over the compose file, the Makefile and pyproject — no
Docker needed. These exist because a single edit reverting a port, a digest,
a `-m ""`, or the default marker expression silently reopens what a story
closed.
"""

from __future__ import annotations

import ast
import math
import os
import shlex
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from repo_paths import REPO_ROOT

COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"
MAKEFILE_PATH = REPO_ROOT / "infra" / "Makefile"
PYPROJECT_PATH = REPO_ROOT / "server" / "pyproject.toml"
SERVER_DIR = REPO_ROOT / "server"
SERVER_TESTS = SERVER_DIR / "tests"
STORE_CHECK_NODE_ID = (
    f"{SERVER_TESTS / 'test_projections_search.py'}"
    "::test_configured_projection_stores_are_reachable"
)
COMPOSE: dict[str, Any] = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
SERVICES: dict[str, Any] = COMPOSE["services"]


def test_compose_defines_only_the_five_stores() -> None:
    """AD-9: three dev stores plus two test twins; app processes stay host-side."""
    assert set(SERVICES) == {
        "postgres",
        "neo4j",
        "meilisearch",
        "neo4j-test",
        "meilisearch-test",
    }


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_every_published_port_binds_loopback_only(service: str) -> None:
    """Store ports must never be reachable off-host (finding 20): the dev
    passwords are committed defaults and real transcripts land here."""
    for published in SERVICES[service].get("ports", []):
        assert isinstance(published, str), (
            f"{service}: long-form port mappings must also pin host_ip"
        )
        assert published.startswith("127.0.0.1:"), (
            f"{service}: port mapping {published!r} does not bind 127.0.0.1"
        )


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_every_image_is_digest_pinned(service: str) -> None:
    """A mutable tag can move under us; a digest cannot (finding 21)."""
    image = SERVICES[service]["image"]
    assert "@sha256:" in image, f"{service}: image {image!r} is not digest-pinned"


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_every_service_has_a_healthcheck(service: str) -> None:
    """`up -d --wait` is the gate host processes start behind, and it only
    waits for services that declare health."""
    assert "test" in SERVICES[service].get("healthcheck", {})


def _recipe(target: str) -> str:
    """`target:`'s rule and recipe lines, from the rule line to the first blank line."""
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    marker = f"\n{target}:"
    assert marker in makefile, f"infra/Makefile has no `{target}:` rule"
    return makefile.split(marker, maxsplit=1)[1].split("\n\n", maxsplit=1)[0]


def test_make_test_requires_the_effective_test_store_endpoints() -> None:
    """The full gate may not pass after pytest skips every store-backed test."""
    test_recipe = _recipe("test")
    assert "check-test-stores" in test_recipe
    assert "MM_REQUIRE_TEST_STORES=1" in test_recipe
    assert "test_configured_projection_stores_are_reachable" in MAKEFILE_PATH.read_text(
        encoding="utf-8"
    )


def _under_server_tests(word: str) -> bool:
    """A command word that is a path (or node id) at or under server/tests."""
    path = Path(word.split("::", maxsplit=1)[0])
    if not path.is_absolute():
        return False
    resolved = path.resolve()
    return resolved == SERVER_TESTS or SERVER_TESTS in resolved.parents


def _dry_run_pytest_commands(target: str) -> list[list[str]]:
    """Every server-suite pytest command `make -n -C infra <target>` would run, as words.

    `make -n` prints each recipe line expanded — prerequisites included — and
    executes none of them, so these are the effective commands without a
    pytest being spawned. A nested make must not inherit the outer one's
    flags, or running this under `make test` would change what is printed.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}}
    proc = subprocess.run(
        ["make", "-n", "-C", str(REPO_ROOT / "infra"), target],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    commands: list[list[str]] = []
    # A multi-line recipe is printed with its backslash-newline continuations;
    # join them so each command is one line before it is split.
    for line in proc.stdout.replace("\\\n", " ").splitlines():
        if "pytest" not in line:
            continue
        words = shlex.split(line)
        if "uv" in words and "pytest" in words and any(_under_server_tests(w) for w in words):
            commands.append(words)
    return commands


def _pytest_argv(words: list[str]) -> list[str]:
    """The `uv run … pytest …` part of a recipe command (after `cd … &&` and env assignments)."""
    return words[words.index("uv") :]


def _mark_expressions(argv: list[str]) -> list[str]:
    """Every marker expression pytest would see, in order — the last one is effective."""
    found: list[str] = []
    skip = False
    for i, word in enumerate(argv):
        if skip:
            skip = False
            continue
        if word in ("-m", "--markexpr"):
            found.append(argv[i + 1])
            skip = True
        elif word.startswith("--markexpr="):
            found.append(word.split("=", maxsplit=1)[1])
        elif word.startswith("-m") and not word.startswith("--"):
            found.append(word[2:])
    return found


def _reports_skips(argv: list[str]) -> bool:
    """`-rs` in any spelling pytest accepts: `-rs`, `-rsx`, `-r s`, `-r sx`."""
    for i, word in enumerate(argv):
        if word == "-r" and i + 1 < len(argv) and "s" in argv[i + 1]:
            return True
        if word.startswith("-r") and not word.startswith("--") and "s" in word[2:]:
            return True
    return False


def _resolved(word: str) -> str:
    """A path or node id with its file part resolved, for comparison with a resolved expectation."""
    head, sep, tail = word.partition("::")
    return f"{Path(head).resolve()}{sep}{tail}"


def _the_command_for(target: str, positional: Path | str) -> list[str]:
    """The one server-suite pytest command of `target` whose path word is `positional`."""
    wanted = str(positional)
    matches = [
        words
        for words in _dry_run_pytest_commands(target)
        if any(_under_server_tests(w) and _resolved(w) == wanted for w in words)
    ]
    assert len(matches) == 1, f"{target}: expected one pytest command over {wanted}, saw {matches}"
    return matches[0]


def test_make_test_runs_the_server_suite_with_the_marker_filter_cleared() -> None:
    """The gate's effective argv carries one clearing `-m ""` with no later expression, and requires the twins."""
    words = _the_command_for("test", SERVER_TESTS)
    expressions = _mark_expressions(_pytest_argv(words))
    assert expressions and expressions[-1] == "", expressions
    assert "MM_REQUIRE_TEST_STORES=1" in words


def test_check_test_stores_runs_its_node_id_with_the_marker_filter_cleared() -> None:
    """Its node id sits in a `slow` module: the effective argv must end with `-m ""` or pytest collects nothing."""
    words = _the_command_for("check-test-stores", STORE_CHECK_NODE_ID)
    expressions = _mark_expressions(_pytest_argv(words))
    assert expressions and expressions[-1] == "", expressions
    assert "MM_REQUIRE_TEST_STORES=1" in words


def test_make_test_fast_runs_the_whole_server_fast_set() -> None:
    """The loop's effective argv: this project, the complete server/tests root, skips printed, and no `-m` so pyproject's default selects the fast set."""
    words = _the_command_for("test-fast", SERVER_TESTS)
    argv = _pytest_argv(words)
    assert Path(argv[argv.index("--project") + 1]).resolve() == SERVER_DIR
    paths = [Path(w).resolve() for w in argv if _under_server_tests(w)]
    assert paths == [SERVER_TESTS], paths
    assert _reports_skips(argv), argv
    assert _mark_expressions(argv) == [], argv
    assert "MM_REQUIRE_TEST_STORES=1" not in words


def test_a_cli_empty_marker_expression_clears_the_addopts_default(
    pytester: pytest.Pytester,
) -> None:
    """The semantics `make test` relies on: with addopts `-m 'not slow'`, a later `-m ""` collects a slow-marked sentinel that the default alone deselects."""
    pytester.makeini("[pytest]")
    pytester.makepyfile(
        test_sentinel='''
import pytest


@pytest.mark.slow(reason="sentinel")
def test_slow_sentinel():
    pass
'''
    )
    common = ("-p", "no:cacheprovider", "-o", "markers=slow: sentinel", "-o", "addopts=-m 'not slow'")
    deselected = pytester.runpytest_inprocess(*common)
    assert deselected.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    cleared = pytester.runpytest_inprocess(*common, "-m", "")
    cleared.assert_outcomes(passed=1)


def _pytest_options() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["tool"]["pytest"][
        "ini_options"
    ]


def test_pyproject_selects_the_fast_set_by_default_with_strict_markers() -> None:
    """The default selection is configuration — the expression `-m ""` clears — and a misspelled mark is an error."""
    args = shlex.split(_pytest_options()["addopts"])
    assert "-m" in args, args
    assert args[args.index("-m") + 1] == "not slow"
    assert "--strict-markers" in args


def test_pyproject_registers_the_slow_marker() -> None:
    """With `--strict-markers` an unregistered `slow` would stop collection."""
    assert any(marker.startswith("slow:") for marker in _pytest_options()["markers"])


def test_pyproject_sets_a_positive_finite_fast_test_budget() -> None:
    """The budget the fast_budget plugin reads is a configured positive, finite number of seconds."""
    budget = float(_pytest_options()["mm_fast_test_budget_seconds"])
    assert math.isfinite(budget) and budget > 0


# The measured slow set (story 11.1): the twelve modules that held 471 of the
# full run's 527 test-seconds at e5510c7. Adding a module to the slow set or
# removing one is a deliberate edit of both places — its `pytestmark` line
# and this list.
SLOW_MODULES = (
    "test_api_chat",
    "test_api_search",
    "test_augmentation",
    "test_failfast",
    "test_makefile_procs",
    "test_migrations",
    "test_parallel_store_safety",
    "test_projections_graph",
    "test_projections_locks",
    "test_projections_rebuild",
    "test_projections_search",
    "test_projections_traversals",
)


def _is_slow_mark(node: ast.expr) -> bool:
    """`pytest.mark.slow` or `pytest.mark.slow(...)`."""
    if isinstance(node, ast.Call):
        node = node.func
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "slow"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _has_module_level_slow_mark(path: Path) -> bool:
    """A real module-level `pytestmark = pytest.mark.slow(...)`, alone or inside a list — the same text inside a string is not a mark."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            continue
        marks = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        if any(_is_slow_mark(mark) for mark in marks):
            return True
    return False


def test_the_module_level_slow_set_is_exactly_the_measured_twelve() -> None:
    """Derived from the syntax of every test module and compared both ways: an extra marked module would shrink the fast set silently, a missing mark would re-admit a twin-bound module, and a mark inside a string is no mark."""
    marked = {p.stem for p in SERVER_TESTS.glob("test_*.py") if _has_module_level_slow_mark(p)}
    expected = set(SLOW_MODULES)
    assert marked == expected, (
        f"extra: {sorted(marked - expected)}; missing: {sorted(expected - marked)}"
    )
