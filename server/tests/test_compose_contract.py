"""infra/docker-compose.yml contract (story 1.10, findings 20-21), plus the
Makefile test recipes and pytest options the fast/full split rests on (11.1).

Static assertions over the compose file, the Makefile and pyproject — no
Docker needed. These exist because a single edit reverting a port, a digest,
a `-m ""`, or the default marker expression silently reopens what a story
closed.
"""

from __future__ import annotations

import math
import shlex
import tomllib
from typing import Any

import pytest
import yaml

from repo_paths import REPO_ROOT

COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"
MAKEFILE_PATH = REPO_ROOT / "infra" / "Makefile"
PYPROJECT_PATH = REPO_ROOT / "server" / "pyproject.toml"
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


def test_make_test_clears_the_default_marker_selection() -> None:
    """pyproject deselects `slow` by default; the gate must pass `-m ""` or the slow modules never run."""
    assert '-m ""' in _recipe("test")


def test_check_test_stores_clears_the_default_marker_selection() -> None:
    """Its node id sits in a `slow` module: without `-m ""` pytest collects nothing and exits 5."""
    assert '-m ""' in _recipe("check-test-stores")


def test_make_test_fast_prints_skips_and_never_requires_the_stores() -> None:
    """The iteration loop names every skipped store-backed test and does not gate on the twins."""
    recipe = _recipe("test-fast")
    assert "-rs" in recipe
    assert "MM_REQUIRE_TEST_STORES" not in recipe


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
# full run's 527 test-seconds at e5510c7. Removing a module from the slow set
# is a deliberate edit of both places — its `pytestmark` line and this list.
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


@pytest.mark.parametrize("module", SLOW_MODULES)
def test_each_measured_slow_module_is_marked_at_module_level(module: str) -> None:
    """The list above is the measured set; a module leaves it only by editing both this list and its own mark."""
    source = (REPO_ROOT / "server" / "tests" / f"{module}.py").read_text(encoding="utf-8")
    assert any(
        line.startswith("pytestmark = pytest.mark.slow(") for line in source.splitlines()
    ), f"{module}.py has no module-level `pytestmark = pytest.mark.slow(` line"
