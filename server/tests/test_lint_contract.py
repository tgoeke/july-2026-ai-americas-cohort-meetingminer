"""`make lint` / `make typecheck` and their committed baseline (story 11.4, B-4).

Static assertions over the Makefile — via `make -n`, which prints every
recipe command and executes none — and over server/pyproject.toml. No
stores, no Docker, no venv beyond the test's own, so the file belongs to
the fast set. These exist because a single edit deleting a target, dropping
one from the `test-fast:` rule line, or quietly widening the dated ruff/mypy
baseline would reopen backlog B-4 with no failure anywhere.

Deliberately self-contained: nothing is imported from test_compose_contract,
so each contract file fails on its own terms whatever happens to the other's
helpers.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tomllib
from pathlib import Path

from repo_paths import REPO_ROOT

MAKEFILE_DIR = REPO_ROOT / "infra"
PYPROJECT_PATH = REPO_ROOT / "server" / "pyproject.toml"
SERVER_DIR = REPO_ROOT / "server"

# Dropping lint or typecheck from the loop is a deliberate edit of both
# places, and the assertions below name them:
EDIT_SITES = (
    "the `test-fast:` rule line in infra/Makefile and TEST_FAST_PREREQUISITES "
    "in test_compose_contract.py"
)

# The typecheck scope: the architecture's decision cores ("Segmentation,
# classification, identity, chunking, and highlighting are database-free,
# model-free", docs/architecture.md) mapped to concrete modules. Widening or
# shrinking `[tool.mypy] files` is an edit of pyproject and this tuple.
DECISION_CORE_FILES = (
    "meetingminer/domain/__init__.py",
    "meetingminer/domain/drops.py",
    "meetingminer/domain/jobs.py",
    "meetingminer/pipeline/alignment.py",
    "meetingminer/pipeline/extraction.py",
    "meetingminer/pipeline/moments.py",
    "meetingminer/pipeline/outputs.py",
    "meetingminer/pipeline/screens.py",
    "meetingminer/pipeline/speakers.py",
    "meetingminer/pipeline/transcripts.py",
    "meetingminer/projections/chunking.py",
    "meetingminer/projections/publish_gate.py",
    "meetingminer/projections/query.py",
)

# The dated global ignore (2026-08-30): seven mechanical codes. Removing one
# is retirement (fix the modules, then shrink both this set and pyproject's);
# adding one is a widening of the baseline and must be as deliberate.
BASELINE_GLOBAL_IGNORE = frozenset(
    {"I001", "PLW1510", "RUF100", "SIM117", "UP017", "UP035", "UP037"}
)

RULE_CODE = re.compile(r"[A-Z][A-Z0-9]*[0-9]+")


def _dry_run(target: str) -> str:
    """Every command `make -C infra <target>` would run, one per line, none executed.

    A nested make must not inherit an outer one's flags, or running this
    under `make test` would change what is printed; `--no-print-directory`
    drops the "Entering directory" noise `-C` turns on.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}}
    proc = subprocess.run(
        ["make", "-n", "--no-print-directory", "-C", str(MAKEFILE_DIR), target],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.replace("\\\n", " ")


def _words(line: str) -> list[str]:
    """`line` as shell words; a make-printed line that is not shell-splittable
    (an unbalanced quote inside an echo) is nobody's tool command."""
    try:
        return shlex.split(line)
    except ValueError:
        return []


def _tool_commands(printed: str, tool: str) -> list[list[str]]:
    """The printed commands invoking `tool` under `uv run --project <server>`, as words."""
    commands: list[list[str]] = []
    for line in printed.splitlines():
        if tool not in line:
            continue
        words = _words(line)
        if tool in words and "uv" in words:
            project = Path(words[words.index("--project") + 1]).resolve()
            assert project == SERVER_DIR, (
                f"{tool} must run under the server project (its config and pins), got {project}"
            )
            commands.append(words)
    return commands


def test_make_lint_runs_ruff_check_over_the_whole_server_tree() -> None:
    """One command, `ruff check` on server/ — sources and tests — so the rule
    set the committed baseline was measured against is what actually runs."""
    commands = _tool_commands(_dry_run("lint"), "ruff")
    assert len(commands) == 1, f"`make lint` must run exactly one ruff command, got {commands}"
    words = commands[0]
    assert words[words.index("ruff") + 1] == "check", words
    checked = [Path(w).resolve() for w in words[words.index("check") + 1 :] if not w.startswith("-")]
    assert checked == [SERVER_DIR], (
        f"`make lint` checks {checked}, expected exactly the whole server tree {SERVER_DIR}"
    )


def test_make_typecheck_runs_mypy_bare_from_server() -> None:
    """One command, `python -m mypy` with no arguments, run from server/: the
    scope lives in `[tool.mypy] files`, so this target and any bare mypy run
    from server/ agree on it by construction."""
    commands = _tool_commands(_dry_run("typecheck"), "mypy")
    assert len(commands) == 1, f"`make typecheck` must run exactly one mypy command, got {commands}"
    words = commands[0]
    assert words[0] == "cd" and Path(words[1]).resolve() == SERVER_DIR, (
        f"mypy must run from server/ so it discovers pyproject's [tool.mypy]; got {words}"
    )
    assert words[words.index("-m") + 1] == "mypy", words
    assert words[-1] == "mypy", (
        f"the recipe must stay bare — scope belongs in `[tool.mypy] files`, not argv: {words}"
    )


def test_make_test_fast_runs_lint_and_typecheck_before_the_fast_set() -> None:
    """The loop runs both tools, and both before its pytest command, so a lint
    or type error fails the loop before any test does."""
    printed = _dry_run("test-fast")
    ruff_commands = _tool_commands(printed, "ruff")
    mypy_commands = _tool_commands(printed, "mypy")
    assert ruff_commands and mypy_commands, (
        f"`make test-fast` must run lint and typecheck; dropping either is an edit of both "
        f"{EDIT_SITES} — it ran ruff={ruff_commands} mypy={mypy_commands}"
    )
    lines = printed.splitlines()
    first_pytest = min(i for i, line in enumerate(lines) if "pytest" in _words(line))
    for tool in ("ruff", "mypy"):
        positions = [i for i, line in enumerate(lines) if tool in _words(line)]
        assert positions and max(positions) < first_pytest, (
            f"{tool} must run before the fast set's pytest command; see {EDIT_SITES}"
        )


def _pyproject() -> dict:
    with PYPROJECT_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_pins_ruff_and_mypy_in_the_dev_group() -> None:
    """Both tools pinned above and below: the committed baseline is only green
    against the versions it was measured with, so a floor alone is drift."""
    dev = _pyproject()["dependency-groups"]["dev"]
    for tool in ("ruff", "mypy"):
        pins = [d for d in dev if isinstance(d, str) and re.match(rf"{tool}\s*[><=]", d)]
        assert len(pins) == 1, f"dev group must pin {tool} exactly once, got {pins}"
        assert ">=" in pins[0] and "<" in pins[0], f"{tool} needs a floor and a ceiling: {pins[0]}"
    assert "required-version" in _pyproject()["tool"]["ruff"], (
        "[tool.ruff] required-version keeps a stray global ruff from rewriting the baseline math"
    )


def test_pyproject_carries_the_dated_ruff_baseline_and_nothing_looser() -> None:
    """The global ignore is exactly the seven measured mechanical codes, the
    per-file entries name real files with real rule codes, and no select/
    extend key widens or narrows the default rule set — that is the version
    pin's job."""
    lint = _pyproject()["tool"]["ruff"]["lint"]
    assert set(lint) == {"ignore", "per-file-ignores"}, (
        f"[tool.ruff.lint] may hold only the dated baseline (ignore, per-file-ignores); "
        f"a select/extend key changes the rule set silently — got {sorted(lint)}"
    )
    assert set(lint["ignore"]) == BASELINE_GLOBAL_IGNORE, (
        "the global ignore is the dated 2026-08-30 baseline; growing it is a config sweep, "
        "shrinking it is retirement — either edits pyproject AND BASELINE_GLOBAL_IGNORE in "
        "test_lint_contract.py, with the deferred-work.md item updated"
    )
    per_file = lint["per-file-ignores"]
    assert per_file, "the per-file baseline may be retired entry-by-entry, not dropped wholesale"
    for path, codes in per_file.items():
        assert not Path(path).is_absolute(), f"baseline paths are relative to server/: {path}"
        assert (SERVER_DIR / path).is_file(), (
            f"baseline names a file that no longer exists: {path} — retire its entry"
        )
        assert codes and all(RULE_CODE.fullmatch(code) for code in codes), (
            f"baseline entry for {path} must be a non-empty list of rule codes, got {codes}"
        )


def test_pyproject_pins_the_mypy_scope_to_the_decision_cores() -> None:
    """`[tool.mypy] files` is the decision-core list, checked with
    check_untyped_defs; the only missing-import forgiveness is jsonschema's."""
    mypy_config = _pyproject()["tool"]["mypy"]
    assert tuple(mypy_config["files"]) == DECISION_CORE_FILES, (
        "[tool.mypy] files must be exactly the decision-core modules; changing the scope "
        "edits pyproject AND DECISION_CORE_FILES in test_lint_contract.py"
    )
    for path in DECISION_CORE_FILES:
        assert (SERVER_DIR / path).is_file(), f"decision-core module missing on disk: {path}"
    assert mypy_config["check_untyped_defs"] is True
    overrides = mypy_config["overrides"]
    assert overrides, "the jsonschema override is part of the committed baseline"
    for override in overrides:
        modules = override["module"]
        modules = [modules] if isinstance(modules, str) else modules
        assert all(m == "jsonschema" or m.startswith("jsonschema.") for m in modules), (
            f"a new ignore_missing_imports override widens the dated baseline: {modules}"
        )
