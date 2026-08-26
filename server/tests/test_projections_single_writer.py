"""AD-4's "exactly one writer", made falsifiable.

AD-4 says every Neo4j and Meilisearch write lives in
``server/meetingminer/projections/``. As prose that is unfalsifiable — a
contributor who has not read the architecture spine can open a driver anywhere
and nothing complains. This file is the mechanism that complains: it walks the
whole server package's source and fails if either client is imported outside
the projection module.

Deliberately import inspection over convention. It costs nothing, it runs in
the normal suite with no stores up, and it is the only check that survives
somebody who never read AD-4.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "meetingminer"
PROJECTIONS_ROOT = PACKAGE_ROOT / "projections"

# The two store clients. Nothing outside `projections/` may import either.
FORBIDDEN_ROOTS = {"neo4j", "meilisearch"}


def python_files() -> list[Path]:
    return sorted(p for p in PACKAGE_ROOT.rglob("*.py"))


def imported_roots(path: Path) -> set[str]:
    """Top-level package names imported by one module, however they are spelled.

    Covers ``import x``, ``import x.y``, ``from x import y`` and
    ``from x.y import z``. A relative import has no module root to leak
    through, so it is ignored.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_the_package_actually_has_modules_to_inspect() -> None:
    """A guard on the guard: an empty walk would make the next test vacuous.

    Named modules rather than a count. A threshold like "more than twenty
    files" passes for the wrong reason the moment the package grows, and stops
    saying anything about whether the walk reached the code that matters.
    """
    walked = {path.relative_to(PACKAGE_ROOT).as_posix() for path in python_files()}
    # One module per place a store client could plausibly be reached for:
    # the worker's pipeline, the api, and the projection module itself.
    for expected in (
        "pipeline/runner.py",
        "api/main.py",
        "projections/__init__.py",
        "projections/stores.py",
    ):
        assert expected in walked, f"the import walk never reached {expected}"


def test_neo4j_and_meilisearch_are_imported_only_under_projections() -> None:
    offenders: list[tuple[str, str]] = []
    for path in python_files():
        if path.is_relative_to(PROJECTIONS_ROOT):
            continue
        for root in imported_roots(path) & FORBIDDEN_ROOTS:
            offenders.append((str(path.relative_to(PACKAGE_ROOT)), root))
    assert not offenders, (
        "AD-4: every Neo4j and Meilisearch write goes through"
        " meetingminer/projections/. These modules import a store client"
        f" directly: {offenders}"
    )


def test_the_projection_module_does_import_both_clients() -> None:
    """The negative test above is only meaningful if the positive one holds."""
    roots: set[str] = set()
    for path in PROJECTIONS_ROOT.rglob("*.py"):
        roots |= imported_roots(path)
    assert FORBIDDEN_ROOTS <= roots


@pytest.mark.parametrize("client_root", sorted(FORBIDDEN_ROOTS))
def test_the_check_would_catch_a_violation(tmp_path: Path, client_root: str) -> None:
    """Prove the inspection detects what it claims to, not just that it passes."""
    offender = tmp_path / "rogue.py"
    offender.write_text(f"from {client_root}.errors import Whatever\n", encoding="utf-8")
    assert client_root in imported_roots(offender)


def test_the_api_package_never_reaches_a_store() -> None:
    """AD-4's consequence, checked where a reviewer will look for it.

    The API reads Postgres and nothing else; search and chat land in Epic 3
    *through* this module, never around it.
    """
    api_root = PACKAGE_ROOT / "api"
    for path in api_root.rglob("*.py"):
        assert not (imported_roots(path) & FORBIDDEN_ROOTS), path
