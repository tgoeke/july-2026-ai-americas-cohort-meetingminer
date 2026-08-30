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
import re
import shlex
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from fast_budget import _SLOW_NODEIDS
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


def _dry_run(target: str, *flags: str) -> str:
    """What `make -n [flags] -C infra <target>` prints: every recipe command, one per line, plus whatever the flags add (`--debug=basic`: make's own trace).

    `make -n` prints each recipe line expanded — prerequisites included — and
    executes none of them, so this is the effective run without a pytest
    being spawned. A nested make must not inherit the outer one's flags, or
    running this under `make test` would change what is printed. A multi-line
    recipe is printed with its backslash-newline continuations; they are
    joined so each command is one line. `--no-print-directory`: `-C` turns
    `-w` on, and its "Entering directory" lines are not commands.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}}
    proc = subprocess.run(
        ["make", "-n", "--no-print-directory", *flags, "-C", str(REPO_ROOT / "infra"), target],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.replace("\\\n", " ")


def _server_pytest_words(line: str) -> list[str] | None:
    """A printed line that is a `uv … pytest …` over a path at or under server/tests, as words; else None."""
    if "pytest" not in line:
        return None
    words = shlex.split(line)
    if "uv" in words and "pytest" in words and any(_under_server_tests(w) for w in words):
        return words
    return None


def _dry_run_pytest_commands(target: str) -> list[list[str]]:
    """Every server-suite pytest command `make -n -C infra <target>` would run, as words."""
    found = (_server_pytest_words(line) for line in _dry_run(target).splitlines())
    return [words for words in found if words is not None]


# GNU make's `--debug=basic` announcement, printed before a target's recipe;
# 3.81 quotes the name `like this', 4.x 'like this'.
_REMAKE = re.compile(r"Must remake target [`']([^`']+)'\.")


def _dry_run_steps(target: str) -> list[tuple[str, list[str]]]:
    """`(target, lines printed while remaking it)` in the order make would run them.

    From `make -n --debug=basic`: make announces each target it must remake,
    prerequisites first, before printing that target's recipe, so which
    target runs first and which command belongs to which come from make's
    own decision, not from reading the rule line. The lines under a target
    still include make's other debug output; pick commands out of them with
    `_server_pytest_words`.
    """
    steps: list[tuple[str, list[str]]] = []
    output = _dry_run(target, "--debug=basic")
    for line in output.splitlines():
        announced = _REMAKE.search(line)
        if announced:
            steps.append((announced.group(1), []))
        elif steps:
            steps[-1][1].append(line)
    version = subprocess.run(["make", "--version"], capture_output=True, text=True, timeout=60)
    assert steps, (
        f"no remake announcement matched {_REMAKE.pattern!r} in `make -n --debug=basic` "
        f"output under {version.stdout.splitlines()[:1]}; first lines:\n"
        + "\n".join(output.splitlines()[:8])
    )
    return steps


# GNU make's `--debug=basic` trace, as it appears among a target's lines:
# indented file-status lines, the remake announcements, and the makefile
# and goal updates; its version banner precedes every announcement.
_MAKE_TRACE = re.compile(
    r"^(\s.*|Must remake target .*|Successfully remade target file .*"
    r"|Reading makefiles\.*|Updating goal targets\.*|Updating makefiles\.*)$"
)


def _direct_commands(target: str) -> list[str]:
    """The recipe commands `target` itself owns, in order, from make: the lines printed while remaking it (`_dry_run_steps`) that a plain `make -n` prints too.

    A prerequisite's commands sit under its own announcement, so only this
    target's lines are looked at; the plain run's lines — every target's,
    which is why its whole output is a safe reference — tell a recipe command
    from make's trace, `@`-prefixed lines included, which `-n` prints as
    well. A line under the target that is neither fails here rather than
    dropping out silently: a recipe that expands differently between the two
    runs (`$(shell date)`) would otherwise escape the contract.
    """
    steps = _dry_run_steps(target)
    lines = [printed for announced, printed in steps if announced == target]
    assert lines, f"make never announced remaking {target}; it remade {[t for t, _ in steps]}"
    assert len(lines) == 1, f"{target} was remade {len(lines)} times in {[t for t, _ in steps]}"
    plain = set(_dry_run(target).splitlines())
    unaccounted = [line for line in lines[0] if line not in plain and not _MAKE_TRACE.match(line)]
    assert not unaccounted, f"{target}: printed under it by --debug but not by a plain -n: {unaccounted}"
    return [line for line in lines[0] if line in plain]


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


# What `make test-fast` runs before the fast set, and all it may run: the
# client check and the three store-free suites. Anything more (an `infra-up`,
# a store check) would make the loop need Docker; anything less drops a suite
# from it with no failure. Adding or removing one is a deliberate edit of
# both places — the `test-fast:` rule line and this tuple. The recipe itself
# is one command, the fast set:
# test_make_test_fast_recipe_is_the_one_whole_server_pytest_command holds it
# to that, so nothing rides in the recipe past this list.
TEST_FAST_PREREQUISITES = ("check-client", "lint", "typecheck", "puller-test", "web-test", "evals-test")


def test_make_test_fast_runs_check_client_lint_typecheck_then_every_store_free_suite_before_the_fast_set() -> None:
    """The loop's effective sequence, from make itself: check-client first (a missing client fails with its named message, not as a Vite import error inside web-test), then lint, typecheck and the three store-free suites, and the one whole-server pytest command last, under test-fast. Dropping a prerequisite from the rule line, adding one, or moving check-client fails here."""
    steps = _dry_run_steps("test-fast")
    targets = [target for target, _ in steps]
    edit = "the `test-fast:` rule line and TEST_FAST_PREREQUISITES in test_compose_contract.py"
    required_prefix = list(TEST_FAST_PREREQUISITES[:3])
    assert targets[:3] == required_prefix, (
        f"check-client, lint and typecheck must run directly at the start; got {targets}"
    )
    assert targets[-1] == "test-fast", targets
    # The order among the three suites is deliberately unconstrained; the set
    # is exact, transitively — a prerequisite of a prerequisite would appear here too.
    assert set(targets[3:-1]) == set(TEST_FAST_PREREQUISITES[3:]), (
        f"test-fast ran {targets[3:-1]} after its fail-fast prefix, expected exactly "
        f"{list(TEST_FAST_PREREQUISITES[3:])}; edit both {edit}"
    )
    with_server_pytest = [
        target for target, lines in steps if any(_server_pytest_words(line) for line in lines)
    ]
    assert with_server_pytest == ["test-fast"], with_server_pytest


def test_make_test_fast_recipe_is_the_one_whole_server_pytest_command() -> None:
    """The commands the `test-fast` recipe owns, from make: exactly one, the whole-server pytest command — so it is last, and nothing before or after it (a `docker compose`, a store check, a second suite) rides in the recipe past the prerequisite contract above — and that command is exactly `cd <root> && uv run --project <server> pytest -q -rs <server/tests>`. Exact argv rejects a command that merely mentions pytest, a non-execution or narrower-selection option, shell backgrounding, and anything chained onto either side. Everything else the loop runs is a prerequisite target; adding one is an edit of TEST_FAST_PREREQUISITES."""
    commands = _direct_commands("test-fast")
    server = [command for command in commands if _server_pytest_words(command)]
    assert len(server) == 1, f"test-fast's recipe has {len(server)} whole-server pytest commands: {commands}"
    assert commands == server, (
        f"test-fast's recipe runs {commands}; it may own only its whole-server pytest command — "
        "anything more belongs in a prerequisite target, an edit of both the `test-fast:` rule "
        "line and TEST_FAST_PREREQUISITES in test_compose_contract.py"
    )
    words = shlex.split(server[0])
    assert words[0] == "cd" and Path(words[1]).resolve() == REPO_ROOT and words[2] == "&&", words[:3]
    invocation = words[3:]
    expected = [
        "uv",
        "run",
        "--project",
        str(SERVER_DIR),
        "pytest",
        "-q",
        "-rs",
        str(SERVER_TESTS),
    ]
    assert invocation == expected, (
        f"test-fast's recipe must run exactly {expected} after `cd <root> &&`; got {invocation}. "
        "Anything else is a different or second command and belongs in a prerequisite target"
    )


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


def _slow_pytestmark_in(body: list[ast.stmt]) -> bool:
    """A real `pytestmark = pytest.mark.slow(...)` among these statements, alone or inside a list — the same text inside a string is not a mark."""
    for node in body:
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


def _has_module_level_slow_mark(path: Path) -> bool:
    """A module-level `pytestmark` carrying `slow`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _slow_pytestmark_in(tree.body)


def _both_ways(marked: set[str], expected: tuple[str, ...], pin: str) -> None:
    """Exact-set comparison with a message that says what to edit."""
    assert marked == set(expected), (
        f"extra: {sorted(marked - set(expected))}; missing: {sorted(set(expected) - marked)} "
        f"— a slow mark is a deliberate edit of both places: the mark and {pin} in "
        "server/tests/test_compose_contract.py"
    )


def test_the_module_level_slow_set_is_exactly_the_measured_twelve() -> None:
    """Derived from the syntax of every test module and compared both ways: an extra marked module would shrink the fast set silently, a missing mark would re-admit a twin-bound module, and a mark inside a string is no mark."""
    marked = {p.stem for p in SERVER_TESTS.glob("test_*.py") if _has_module_level_slow_mark(p)}
    _both_ways(marked, SLOW_MODULES, "SLOW_MODULES")


# The measured per-test slow set (story 11.1): the four tests in otherwise
# fast modules bound by a timer or the twins, as `module::test`. A test in a
# class would be `module::Class::test`; a mark on the class itself — a
# decorator or a class-body `pytestmark` — is `module::Class` and pins every
# test collected under it, nested classes included. Adding a per-test mark or
# removing one is a deliberate edit of both places — the decorator and this
# list.
SLOW_TESTS = (
    "test_api_events::test_a_slow_configured_heartbeat_is_not_overridden_by_a_faster_default",
    "test_api_events::test_configured_poll_cadence_is_honored",
    "test_artifact_publish::test_approve_projects_into_both_stores",
    "test_worker_extract::test_search_never_returns_an_extracted_artifacts_content",
)


def _decorated_slow_definitions(path: Path) -> set[str]:
    """Every `def`, `async def` or `class` a real `pytest.mark.slow` reaches through syntax, as `module::name`.

    Definitions at module level or inside a class, including ones under a
    module-level `if`/`try`/`with`, which pytest collects too. A mark counts
    anywhere inside a decorator expression — `pytest.param(marks=...)` in a
    `parametrize` as well as the decorator itself — and a class-body
    `pytestmark` counts for the class. The same text inside a string (a
    pytester probe) is not a mark.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()

    def walk(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}::{node.name}"
                decorated = any(
                    _is_slow_mark(inner)
                    for decorator in node.decorator_list
                    for inner in ast.walk(decorator)
                )
                if decorated or (isinstance(node, ast.ClassDef) and _slow_pytestmark_in(node.body)):
                    found.add(name)
                if isinstance(node, ast.ClassDef):
                    walk(node.body, name)
                continue
            for field in ("body", "orelse", "finalbody"):
                block = getattr(node, field, None)
                if isinstance(block, list):
                    walk(block, prefix)
            for handler in getattr(node, "handlers", []):
                walk(handler.body, prefix)

    walk(tree.body, path.stem)
    return found


def test_the_per_test_slow_set_is_exactly_the_measured_four() -> None:
    """Derived from the syntax of every test module and compared both ways: a fifth decorator would remove a fast test from the default run with every other contract green, a missing one would re-admit a timer- or twin-bound test, and a mark inside a probe string is no mark."""
    marked: set[str] = set()
    for path in SERVER_TESTS.glob("test_*.py"):
        marked |= _decorated_slow_definitions(path)
    _both_ways(marked, SLOW_TESTS, "SLOW_TESTS")


def _pinned(
    nodeid: str,
    slow_modules: tuple[str, ...] = SLOW_MODULES,
    slow_tests: tuple[str, ...] = SLOW_TESTS,
) -> bool:
    """Whether a slow-marked node id is accounted for: its module is in `slow_modules`, or `slow_tests` holds its `module::[Class::]test` (parametrization stripped) or the `module::Class` of a class enclosing it — the syntax inventory's name for a class-level mark, which pins every test collected under the class."""
    path, _, rest = nodeid.partition("::")
    stem = Path(path).stem
    if stem in slow_modules:
        return True
    parts = rest.partition("[")[0].split("::")
    return any(f"{stem}::{'::'.join(parts[:depth])}" in slow_tests for depth in range(len(parts), 0, -1))


# A class-level `slow` mark in both syntactic forms, over methods pytest
# collects as `module::Class::test[param]` and under a nested class; a
# decorated method beside them keeps a pin of its own, and an unmarked one
# needs none.
CLASS_MARKED_SOURCE = '''
import pytest


class TestGroup:
    pytestmark = pytest.mark.slow(reason="probe: class body")

    def test_one(self):
        pass

    @pytest.mark.parametrize("n", [1, 2])
    def test_two(self, n):
        pass

    class TestNested:
        def test_three(self):
            pass


@pytest.mark.slow(reason="probe: class decorator")
class TestDecorated:
    def test_four(self):
        pass


class TestPlain:
    @pytest.mark.slow(reason="probe: one method")
    def test_five(self):
        pass

    def test_six(self):
        pass
'''


def test_a_class_level_slow_mark_pins_the_class_by_syntax_and_by_collection(
    pytester: pytest.Pytester,
) -> None:
    """One representation for a class-level mark, `module::Class`: the name the syntax inventory already gave a class decorator and a class-body `pytestmark` (neither is a module-level mark), now accepted by the collected-node guard for every test pytest collects under the class — parametrized, nested — while a decorated method keeps its own `module::Class::test` pin and an unmarked method is pinned by neither. Without its pin, the class's tests are named as unpinned."""
    pytester.makeini("[pytest]")
    path = pytester.makepyfile(test_slow_class_source=CLASS_MARKED_SOURCE)
    assert not _has_module_level_slow_mark(path)
    pins = _decorated_slow_definitions(path)
    assert pins == {
        "test_slow_class_source::TestGroup",
        "test_slow_class_source::TestDecorated",
        "test_slow_class_source::TestPlain::test_five",
    }
    items, recorder = pytester.inline_genitems(
        "-p", "fast_budget", "-p", "no:cacheprovider", "-o", "markers=slow: probe", str(path)
    )
    collected = {item.nodeid for item in items}
    assert collected == {
        "test_slow_class_source.py::TestGroup::test_one",
        "test_slow_class_source.py::TestGroup::test_two[1]",
        "test_slow_class_source.py::TestGroup::test_two[2]",
        "test_slow_class_source.py::TestGroup::TestNested::test_three",
        "test_slow_class_source.py::TestDecorated::test_four",
        "test_slow_class_source.py::TestPlain::test_five",
        "test_slow_class_source.py::TestPlain::test_six",
    }
    # What the plugin recorded for the pinned-set guard: every collected item
    # but the unmarked method.
    (modifyitems,) = recorder.getcalls("pytest_collection_modifyitems")
    recorded = modifyitems.config.stash[_SLOW_NODEIDS]
    assert recorded == collected - {"test_slow_class_source.py::TestPlain::test_six"}
    unpinned = sorted(n for n in recorded if not _pinned(n, slow_modules=(), slow_tests=tuple(pins)))
    assert unpinned == [], unpinned
    assert not _pinned("test_slow_class_source.py::TestPlain::test_six", (), tuple(pins))
    without_the_class = tuple(pins - {"test_slow_class_source::TestGroup"})
    assert sorted(n for n in recorded if not _pinned(n, (), without_the_class)) == [
        "test_slow_class_source.py::TestGroup::TestNested::test_three",
        "test_slow_class_source.py::TestGroup::test_one",
        "test_slow_class_source.py::TestGroup::test_two[1]",
        "test_slow_class_source.py::TestGroup::test_two[2]",
    ]


def test_every_slow_marked_item_this_session_collected_is_pinned(
    request: pytest.FixtureRequest,
) -> None:
    """The syntax inventories see marks in source; this sees the marks pytest applied — whatever form they took — because the fast_budget plugin records every collected item that carried `slow` when its collection hook ran, before deselection, and each must be in SLOW_MODULES or SLOW_TESTS. Exact in a whole-suite run; vacuous when only this module was collected."""
    slow = request.config.stash[_SLOW_NODEIDS]
    unpinned = sorted(nodeid for nodeid in slow if not _pinned(nodeid))
    assert not unpinned, (
        f"slow-marked but in neither SLOW_MODULES nor SLOW_TESTS "
        f"(server/tests/test_compose_contract.py): {unpinned}"
    )
