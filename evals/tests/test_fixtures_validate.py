"""The shipped ground truth validates (no stores, no api).

The fixtures are the thing every Epic 5 check consumes. If they drift out of
the schema — or out of the count formula — every downstream measurement is
measuring the wrong denominator, so they are asserted here rather than trusted.

Loading is deliberately lazy. A module that loaded the corpus at import time
would turn a broken fixture into a *collection* error, which takes down the
guard tests along with everything else — including the one that exists to say
"the ground-truth directory is empty", in exactly the situation it exists for.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pytest

from evals.harness.groundtruth import (
    GROUND_TRUTH_DIR,
    Manifest,
    load_all,
    load_manifest,
    manifest_paths,
    normalize_anchor,
)

#: The fixtures this repository ships, pinned by name and archetype.
#:
#: Named explicitly rather than discovered: a test that compares discovery
#: against discovery cannot fail. This is what notices a fixture that was
#: renamed, deleted, or saved with a suffix the loader does not pick up.
EXPECTED_FIXTURES = {
    "demo-001-orders-ui-demo.yaml": "ui-demo",
    "demo-002-q3-architecture-review.yaml": "slide-deck",
}


@functools.lru_cache(maxsize=1)
def corpus() -> tuple[Manifest, ...]:
    """The whole ground-truth corpus, loaded once per session.

    Not cached across a failure: `lru_cache` does not memoize exceptions, so a
    broken fixture fails every test that asks for the corpus rather than one
    arbitrary first caller.
    """
    return tuple(load_all(GROUND_TRUTH_DIR))


def fixture(name: str) -> Manifest:
    return load_manifest(GROUND_TRUTH_DIR / name)


def test_the_ground_truth_directory_is_not_empty() -> None:
    """A guard on the guards: an empty directory makes every test below vacuous."""
    assert manifest_paths(GROUND_TRUTH_DIR), f"no manifests under {GROUND_TRUTH_DIR}"


def test_the_shipped_fixtures_are_exactly_the_expected_files() -> None:
    found = {path.name for path in manifest_paths(GROUND_TRUTH_DIR)}
    assert found == set(EXPECTED_FIXTURES), (
        "the ground-truth directory does not hold the fixtures this suite"
        " asserts over — add the new file to EXPECTED_FIXTURES (with its"
        " archetype) or restore the missing one"
    )


def test_every_fixture_loads_and_validates() -> None:
    """load_all raises on any problem, so getting a manifest each is the assertion."""
    assert {manifest.path.name for manifest in corpus() if manifest.path} == set(
        EXPECTED_FIXTURES
    )


@pytest.mark.parametrize("archetype", ["ui-demo", "slide-deck"])
def test_both_archetypes_are_represented(archetype: str) -> None:
    """The schema's conditional half is only exercised if both shapes ship."""
    assert any(manifest.archetype == archetype for manifest in corpus())


@pytest.mark.parametrize(("name", "archetype"), sorted(EXPECTED_FIXTURES.items()))
def test_each_fixture_declares_the_archetype_it_is_named_for(
    name: str, archetype: str
) -> None:
    assert fixture(name).archetype == archetype


@pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES))
def test_expected_screenshot_count_matches_the_formula(name: str) -> None:
    manifest = fixture(name)
    section = manifest.data[manifest.section]
    assert manifest.expected_screenshot_count == len(section) + len(
        manifest.data["participant_segments"]
    )
    assert manifest.expected_screenshot_count > 0


@pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES))
def test_every_entry_has_a_unique_non_empty_anchor(name: str) -> None:
    manifest = fixture(name)
    anchors = manifest.anchors
    assert len(anchors) == len(manifest.entries)
    assert all(anchor for anchor in anchors)
    assert len(set(anchors)) == len(anchors)


@pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES))
def test_anchors_are_authored_as_clean_on_screen_text(name: str) -> None:
    """The raw anchor carries no stray or doubled whitespace.

    Normalization would forgive it, but the anchor is meant to be the literal
    text a human planted on the slide; a trailing space in the YAML is an
    authoring slip, not a deliberate anchor.
    """
    for entry in fixture(name).entries:
        raw = entry["ocr_anchor"]
        assert raw == " ".join(raw.split()), f"{entry['id']}: {raw!r}"
        assert normalize_anchor(raw), f"{entry['id']}: anchor normalizes to nothing"


@pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES))
def test_fixture_file_name_carries_the_meeting_id(name: str) -> None:
    """So a failing report line points at a findable file."""
    assert name.startswith(fixture(name).id)


def test_the_ground_truth_directory_is_where_the_harness_looks() -> None:
    assert GROUND_TRUTH_DIR == Path(__file__).resolve().parents[1] / "ground-truth"
