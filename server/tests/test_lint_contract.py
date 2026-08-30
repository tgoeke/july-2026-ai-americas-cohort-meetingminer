"""`make lint` / `make typecheck` and their committed baseline (story 11.4, B-4).

Static assertions over the Makefile — via `make -n`, which prints every
recipe command and executes none — and over server/pyproject.toml. No
stores, no Docker, no venv beyond the test's own, so the file belongs to
the fast set. These exist because a single edit deleting a target, dropping
one from the `test-fast:` rule line, or quietly widening the dated ruff/mypy
baseline would reopen backlog B-4 with no failure anywhere.

The baseline is pinned shrink-only: retiring an entry (deleting a per-file
line or one of its codes) stays green, while adding a path, a code, a
config key that exempts by another route (`extend-exclude`,
`ignore_errors`), or a select/extend key fails here by name.

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
SPRINT_NOTES_PATH = REPO_ROOT / "_bmad-output" / "implementation-artifacts" / "sprint-notes.md"

BASELINE_SUMMARY = "49 file-code pairs across 38 per-file entries"

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

# The dated global ignore (2026-08-30): seven mechanical codes, exempt
# tree-wide — new files included — until retired. Removing one is retirement
# (fix the modules, then shrink both this set and pyproject's); adding one
# is a widening of the baseline and must be as deliberate.
BASELINE_GLOBAL_IGNORE = frozenset(
    {"I001", "PLW1510", "RUF100", "SIM117", "UP017", "UP035", "UP037"}
)

# The dated per-file baseline (2026-08-30), mirroring pyproject's
# per-file-ignores at its widest. The containment assertion below makes the
# table shrink-only: pyproject may retire any entry or code without touching
# this mapping, but a new path or a new code fails until it is added here
# deliberately.
BASELINE_PER_FILE: dict[str, frozenset[str]] = {
    path: frozenset(codes)
    for path, codes in {
        "meetingminer/adapters/diarize/__init__.py": ("RUF022",),
        "meetingminer/adapters/embed/ollama.py": ("UP041",),
        "meetingminer/api/chat_router.py": ("RUF022",),
        "meetingminer/api/citations.py": ("RUF022",),
        "meetingminer/api/status.py": ("BLE001",),
        "meetingminer/domain/drops.py": ("B018",),
        "meetingminer/mintdrop.py": ("B018",),
        "meetingminer/pipeline/extraction.py": ("FURB167", "FURB188", "SIM102"),
        "meetingminer/pipeline/frameimage.py": ("RUF023",),
        "meetingminer/pipeline/runner.py": ("BLE001", "S110"),
        "meetingminer/pipeline/screens.py": ("RUF023",),
        "meetingminer/pipeline/stages/transcribe.py": ("F401",),
        "meetingminer/projections/locks.py": ("SIM115",),
        "meetingminer/projections/traversals.py": ("TRY004",),
        "meetingminer/prune/cli.py": ("SIM102",),
        "meetingminer/worker/main.py": ("F401",),
        "tests/conftest.py": ("BLE001", "ISC004", "S110"),
        "tests/fast_budget.py": ("TRY004",),
        "tests/test_api_chat.py": ("FURB188",),
        "tests/test_api_registry.py": ("PLR0402",),
        "tests/test_digest.py": ("F401",),
        "tests/test_drops_root.py": ("F401",),
        "tests/test_extraction_core.py": ("SIM102",),
        "tests/test_fast_budget.py": ("PIE810",),
        "tests/test_frame_image.py": ("C408",),
        "tests/test_makefile_procs.py": ("FURB167",),
        "tests/test_mint_drop.py": ("PYI034", "PYI036"),
        "tests/test_ocr_adapter.py": ("FLY002",),
        "tests/test_parallel_store_safety.py": ("PYI034", "S102"),
        "tests/test_projections_chunking.py": ("RUF007",),
        "tests/test_projections_query.py": ("F401",),
        "tests/test_projections_rebuild.py": ("RUF059",),
        "tests/test_projections_single_writer.py": ("SIM102",),
        "tests/test_projections_traversals.py": ("PYI034", "PYI036"),
        "tests/test_prune.py": ("B017", "F401", "RUF059"),
        "tests/test_screens_core.py": ("C408", "RUF059"),
        "tests/test_screens_with_real_pixels.py": ("C408",),
        "tests/test_worker_transcripts.py": ("RUF012",),
    }.items()
}

RULE_CODE = re.compile(r"[A-Z][A-Z0-9]*[0-9]+")


def test_baseline_prose_distinguishes_pairs_from_per_file_entries() -> None:
    """The measured debt has two units: rule pairs and TOML path entries."""
    for path in (PYPROJECT_PATH, SPRINT_NOTES_PATH):
        assert BASELINE_SUMMARY in path.read_text(), (
            f"{path.relative_to(REPO_ROOT)} must describe the dated baseline as "
            f"{BASELINE_SUMMARY!r}"
        )


def _dry_run(target: str) -> str:
    """Every command `make -C infra <target>` would run, one per line, none executed.

    A nested make must not inherit an outer one's flags, or running this
    under `make test` would change what is printed; `--no-print-directory`
    drops the "Entering directory" noise `-C` turns on.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS"}
    }
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
            assert "--project" in words, (
                f"a {tool} command must run under `uv run --project <server>` so the dev-group "
                f"pins and pyproject config apply; got {words}"
            )
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
    pytest_lines = [i for i, line in enumerate(lines) if "pytest" in _words(line)]
    assert pytest_lines, (
        f"`make -n test-fast` printed no pytest command at all — the loop lost its fast set; "
        f"see {EDIT_SITES}"
    )
    first_pytest = min(pytest_lines)
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
    against the versions it was measured with, so a floor alone is drift —
    and ruff's `required-version` must be the same range as its pin, or the
    two drift apart and a stray global ruff rewrites the baseline math."""
    dev = _pyproject()["dependency-groups"]["dev"]
    for tool in ("ruff", "mypy"):
        pins = [d for d in dev if isinstance(d, str) and re.match(rf"{tool}\s*[><=]", d)]
        assert len(pins) == 1, f"dev group must pin {tool} exactly once, got {pins}"
        assert ">=" in pins[0] and "<" in pins[0], f"{tool} needs a floor and a ceiling: {pins[0]}"
    ruff_pin = next(d for d in dev if isinstance(d, str) and re.match(r"ruff\s*[><=]", d))
    pinned_range = ruff_pin.removeprefix("ruff").replace(" ", "")
    required = _pyproject()["tool"]["ruff"].get("required-version")
    assert required is not None, (
        "[tool.ruff] required-version keeps a stray global ruff from rewriting the baseline math"
    )
    assert required.replace(" ", "") == pinned_range, (
        f"[tool.ruff] required-version ({required!r}) must equal the dev-group ruff pin's range "
        f"({pinned_range!r}); ranges that drift apart re-open the door required-version closes"
    )


def test_pyproject_carries_the_dated_ruff_baseline_and_nothing_looser() -> None:
    """The ruff tables hold exactly the dated baseline and its version guard:
    no `extend-exclude` or other `[tool.ruff]` key that exempts whole trees
    (demonstrated to stay green under every other assertion here), no
    select/extend key that changes the rule set — the version pin's job —
    and per-file entries only shrink: retiring a line or a code stays green,
    while a new path or code fails until BASELINE_PER_FILE grows it
    deliberately."""
    ruff = _pyproject()["tool"]["ruff"]
    assert set(ruff) == {"required-version", "lint"}, (
        f"[tool.ruff] may hold only required-version and lint; another key (extend-exclude, "
        f"exclude, src) can exempt whole trees while every other check stays green — got "
        f"{sorted(ruff)}"
    )
    lint = ruff["lint"]
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
        assert path in BASELINE_PER_FILE, (
            f"per-file-ignores gained a new path {path!r}; the 2026-08-30 baseline is "
            "shrink-only — a new exemption is a widening, an edit of pyproject AND "
            "BASELINE_PER_FILE in test_lint_contract.py"
        )
        unknown = set(codes) - BASELINE_PER_FILE[path]
        assert not unknown, (
            f"per-file-ignores for {path} gained {sorted(unknown)}; the 2026-08-30 baseline "
            "is shrink-only — a new exemption is a widening, an edit of pyproject AND "
            "BASELINE_PER_FILE in test_lint_contract.py"
        )


def test_pyproject_pins_the_mypy_scope_to_the_decision_cores() -> None:
    """`[tool.mypy]` is exactly scope + strictness floor + the one override:
    another key can hollow the target out while it still prints success —
    `ignore_errors = true` was demonstrated to leave `make typecheck`
    reporting "no issues found in 13 source files" — so the key set itself
    is pinned, as is each override's."""
    mypy_config = _pyproject()["tool"]["mypy"]
    assert set(mypy_config) == {"files", "check_untyped_defs", "overrides"}, (
        f"[tool.mypy] may hold only files, check_untyped_defs and overrides; another key "
        f"(ignore_errors, follow_imports=skip, exclude) can blank the check while it still "
        f"reports success — got {sorted(mypy_config)}"
    )
    assert tuple(mypy_config["files"]) == DECISION_CORE_FILES, (
        "[tool.mypy] files must be exactly the decision-core modules; changing the scope "
        "edits pyproject AND DECISION_CORE_FILES in test_lint_contract.py"
    )
    for path in DECISION_CORE_FILES:
        assert (SERVER_DIR / path).is_file(), f"decision-core module missing on disk: {path}"
    check_untyped = mypy_config.get("check_untyped_defs")
    assert check_untyped is True, (
        f"check_untyped_defs must be true — it is the scope's one strictness floor; got "
        f"{check_untyped!r}"
    )
    overrides = mypy_config.get("overrides")
    assert overrides, "the jsonschema override is part of the committed baseline"
    for override in overrides:
        assert set(override) == {"module", "ignore_missing_imports"}, (
            f"an override may hold only module + ignore_missing_imports; another key "
            f"(ignore_errors) hollows the check for those modules — got {sorted(override)}"
        )
        modules = override["module"]
        modules = [modules] if isinstance(modules, str) else modules
        assert all(m == "jsonschema" or m.startswith("jsonschema.") for m in modules), (
            f"a new ignore_missing_imports override widens the dated baseline: {modules}"
        )
