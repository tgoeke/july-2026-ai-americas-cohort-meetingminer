"""Loader rules: everything JSON Schema cannot express (no stores, no api).

Anchor uniqueness, id uniqueness, `qa.expected_moment` resolution, timestamps
inside the meeting, and the cross-file rules that only make sense over a whole
ground-truth directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from evals.harness.groundtruth import (
    GroundTruthError,
    Manifest,
    load_all,
    load_manifest,
    manifest_paths,
    normalize_anchor,
    parse_timestamp,
    validate_manifest,
)
from evals.tests.conftest import meeting_of, valid_slide_deck, valid_ui_demo


def write(directory: Path, name: str, manifest: dict[str, Any]) -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return path


# --- parse_timestamp --------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("00:00:00", 0), ("00:01:30", 90), ("01:00:00", 3600), ("02:03:04", 7384)],
)
def test_parse_timestamp_returns_offset_seconds(value: str, seconds: int) -> None:
    assert parse_timestamp(value) == seconds


@pytest.mark.parametrize(
    "value",
    [
        "00:99:00",  # right shape, not a time
        "00:00:99",
        "1:30",
        "00:01",
        "",
        None,
        90,
    ],
)
def test_parse_timestamp_rejects_non_timestamps(value: Any) -> None:
    with pytest.raises(GroundTruthError):
        parse_timestamp(value)


def test_parse_timestamp_names_the_field_it_was_given() -> None:
    with pytest.raises(GroundTruthError) as exc:
        parse_timestamp("00:99:00", field="screens[2].shown_at")
    assert "screens[2].shown_at" in str(exc.value)
    assert "00:99:00" in str(exc.value)


# --- normalize_anchor -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Order Search Results", "order search results"),
        ("  ORDER   search\tResults ", "order search results"),
        ("Order-Search: Results!", "order search results"),
        ("Q3 Architecture Review", "q3 architecture review"),
        # `[^\w\s]` — an underscore IS a word character, so it survives.
        # Pinned because the docstring says "strips punctuation" and a reader
        # would reasonably expect otherwise; check 2.1 must fold OCR text the
        # same way or the comparison means nothing.
        ("order_search_results", "order_search_results"),
        ("Order_Search Results", "order_search results"),
        ("Straße", "straße"),
        # Non-ASCII punctuation folds like the ASCII kind; non-ASCII *letters*
        # are word characters and survive.
        ("Café — Menu", "café menu"),
        ("\u201cOrder Search\u201d \u2192 Results", "order search results"),
    ],
)
def test_normalize_anchor_matches_the_check_that_will_consume_it(
    raw: str, expected: str
) -> None:
    """Same folding as eval-design §2.1 — lowercase, no punctuation, one space."""
    assert normalize_anchor(raw) == expected


# --- the count --------------------------------------------------------------


def test_expected_screenshot_count_is_screens_plus_segments() -> None:
    manifest = Manifest(data=valid_ui_demo())
    assert len(manifest.entries) == 2
    assert len(manifest.participant_segments) == 2
    assert manifest.expected_screenshot_count == 4


def test_expected_screenshot_count_uses_slides_for_a_deck() -> None:
    manifest = Manifest(data=valid_slide_deck())
    assert manifest.section == "slides"
    assert manifest.expected_screenshot_count == 3 + 1


def test_anchors_are_exposed_normalized() -> None:
    manifest = Manifest(data=valid_ui_demo())
    assert manifest.anchors == ("order search results", "line items and tax breakdown")


# --- anchors ----------------------------------------------------------------


def test_duplicate_anchor_fails_and_names_both_entries() -> None:
    manifest = valid_ui_demo()
    manifest["screens"][1]["ocr_anchor"] = "order   SEARCH results!"
    problems = validate_manifest(manifest)
    assert problems
    joined = " ".join(problems)
    assert "SC1" in joined and "SC2" in joined
    assert "ocr_anchor" in joined


def test_missing_anchor_fails_and_names_the_entry() -> None:
    manifest = valid_ui_demo()
    del manifest["screens"][1]["ocr_anchor"]
    problems = validate_manifest(manifest)
    assert problems
    assert any("screens[1]" in problem and "ocr_anchor" in problem for problem in problems)


@pytest.mark.parametrize("anchor", ["---", "...", "   ", "!?!", "\u2014\u2014"])
def test_an_anchor_that_normalizes_to_nothing_fails(anchor: str) -> None:
    """It clears `minLength: 1` and is still permanently unmatchable.

    Capture recall compares *normalized* OCR text against the anchor, so an
    anchor made only of punctuation gives the check nothing to find: the entry
    could never be recalled, and the run would fail against the ground truth
    rather than against the pipeline.
    """
    manifest = valid_ui_demo()
    manifest["screens"][0]["ocr_anchor"] = anchor
    problems = validate_manifest(manifest)
    assert any(
        "normalizes to nothing" in problem and "SC1" in problem for problem in problems
    )


def test_distinct_anchors_are_accepted_without_a_similarity_threshold() -> None:
    """Non-empty and unique is the whole rule (story acceptance).

    Two anchors that merely share words are legal; inventing a
    "distinctiveness" threshold here would reject valid ground truth.
    """
    manifest = valid_ui_demo()
    manifest["screens"][0]["ocr_anchor"] = "Order Search Results"
    manifest["screens"][1]["ocr_anchor"] = "Order Search Filters"
    assert validate_manifest(manifest) == []


def test_duplicate_participant_segment_timestamps_fail_and_name_both() -> None:
    """One moment is one expected capture.

    A repeated `at` demands two captures of a single instant, so the recall
    denominator is inflated by one and 100% becomes unreachable — a run that
    fails against its own ground truth rather than against the pipeline.
    """
    manifest = valid_ui_demo()
    manifest["participant_segments"][1]["at"] = manifest["participant_segments"][0]["at"]
    problems = validate_manifest(manifest)
    assert any(
        "duplicate participant_segments" in problem
        and "participant_segments[0]" in problem
        and "participant_segments[1]" in problem
        for problem in problems
    )


def test_distinct_participant_segment_timestamps_are_accepted() -> None:
    assert validate_manifest(valid_ui_demo()) == []


# --- ids and references -----------------------------------------------------


def test_duplicate_entry_id_fails_and_names_the_id() -> None:
    manifest = valid_ui_demo()
    manifest["screens"][1]["id"] = "SC1"
    problems = validate_manifest(manifest)
    assert any("duplicate id 'SC1'" in problem for problem in problems)


def test_duplicate_planted_id_fails() -> None:
    manifest = valid_ui_demo()
    manifest["planted"]["phrases"][0]["id"] = "D1"
    problems = validate_manifest(manifest)
    assert any("duplicate id 'D1'" in problem for problem in problems)


def test_duplicate_qa_id_fails() -> None:
    manifest = valid_ui_demo()
    manifest["qa"].append(dict(manifest["qa"][0]))
    problems = validate_manifest(manifest)
    assert any("duplicate id 'Q1'" in problem for problem in problems)


def test_dangling_expected_moment_fails_and_names_the_reference() -> None:
    manifest = valid_ui_demo()
    manifest["qa"][0]["expected_moment"] = "D9"
    problems = validate_manifest(manifest)
    assert any("'D9'" in problem for problem in problems)


@pytest.mark.parametrize("moment", ["AI1", "D1", "P1"])
def test_expected_moment_may_name_any_planted_kind(moment: str) -> None:
    manifest = valid_ui_demo()
    manifest["qa"][0]["expected_moment"] = moment
    assert validate_manifest(manifest) == []


# --- timestamps -------------------------------------------------------------


def test_impossible_clock_time_fails_and_names_field_and_value() -> None:
    manifest = valid_ui_demo()
    manifest["screens"][0]["shown_at"] = "00:99:00"
    problems = validate_manifest(manifest)
    assert any(
        "screens[0].shown_at" in problem and "00:99:00" in problem for problem in problems
    )


def test_timestamp_past_the_meeting_fails_and_names_field_and_value() -> None:
    manifest = valid_ui_demo()  # duration_minutes: 12
    manifest["planted"]["decisions"][0]["at"] = "00:13:00"
    problems = validate_manifest(manifest)
    assert any(
        "planted.decisions[0].at" in problem and "00:13:00" in problem
        for problem in problems
    )


@pytest.mark.parametrize("duration", [float("inf"), float("nan")])
def test_non_finite_duration_fails_validation_without_crashing(duration: float) -> None:
    manifest = valid_ui_demo()
    manifest["meeting"]["duration_minutes"] = duration
    problems = validate_manifest(manifest)
    assert any("duration_minutes" in problem and "finite" in problem for problem in problems)


def test_a_timestamp_exactly_at_the_end_is_accepted() -> None:
    manifest = valid_ui_demo()
    manifest["participant_segments"][1]["at"] = "00:12:00"
    assert validate_manifest(manifest) == []


def _set_at(manifest: dict[str, Any], path: str, value: str) -> None:
    """Set the timestamp named by a dotted report path, e.g. `screens[0].shown_at`."""
    section, _, field = path.rpartition(".")
    name, _, index = section.partition("[")
    target: Any = manifest
    for part in name.split("."):
        target = target[part]
    target[int(index.rstrip("]"))][field] = value


@pytest.mark.parametrize(
    "path",
    [
        "screens[0].shown_at",
        "participant_segments[1].at",
        "planted.action_items[0].at",
        "planted.decisions[0].at",
        "planted.phrases[0].at",
    ],
)
def test_every_timestamped_section_is_range_checked(path: str) -> None:
    """Named after every place a manifest carries a time, and covering them.

    All three planted kinds are listed, not just one: they are walked by a
    shared tuple, and a loop narrowed to a single kind would otherwise pass
    this test while leaving two kinds unchecked.
    """
    manifest = valid_ui_demo()
    _set_at(manifest, path, "00:59:59")
    problems = validate_manifest(manifest)
    assert any(path in problem for problem in problems), problems


@pytest.mark.parametrize(
    "path",
    [
        "screens[0].shown_at",
        "participant_segments[1].at",
        "planted.action_items[0].at",
        "planted.decisions[0].at",
        "planted.phrases[0].at",
    ],
)
def test_every_timestamped_section_is_shape_checked(path: str) -> None:
    manifest = valid_ui_demo()
    _set_at(manifest, path, "00:99:00")
    problems = validate_manifest(manifest)
    assert any(path in problem and "00:99:00" in problem for problem in problems)


# --- the section the archetype did not declare -------------------------------


def test_problems_in_the_wrong_section_are_reported_in_the_same_pass() -> None:
    """The one-pass promise, applied to a mis-declared section.

    A ui-demo carrying `slides` is already a schema error. If the loader rules
    only walked `screens`, fixing the archetype would hand the author a second
    round of duplicate ids and anchors they were never told about.
    """
    manifest = valid_ui_demo(
        slides=[
            {"id": "SC1", "title": "One", "ocr_anchor": "Order Search Results"},
            {"id": "SC1", "title": "Two", "ocr_anchor": "Order Search Results"},
        ]
    )
    problems = validate_manifest(manifest)
    joined = " ".join(problems)
    assert "'slides'" in joined  # the schema half
    assert "duplicate id 'SC1'" in joined  # the loader half, in the other section
    assert "duplicate ocr_anchor" in joined


def test_a_stray_section_is_still_timestamp_checked() -> None:
    manifest = valid_slide_deck(
        screens=[
            {
                "id": "SC9",
                "name": "Stray",
                "shown_at": "00:99:00",
                "ocr_anchor": "Stray Screen",
            }
        ]
    )
    problems = validate_manifest(manifest)
    assert any("screens[0].shown_at" in problem for problem in problems)


# --- load_manifest ----------------------------------------------------------


def test_load_manifest_reads_and_validates(tmp_path: Path) -> None:
    path = write(tmp_path, "ok.yaml", valid_ui_demo())
    manifest = load_manifest(path)
    assert manifest.id == "demo-fixture-ui"
    assert manifest.source_id == "source-ui-1"
    assert manifest.path == path
    assert manifest.expected_screenshot_count == 4


def test_load_manifest_reports_every_problem_at_once(tmp_path: Path) -> None:
    """Both layers report through one list, so an author fixes one pass."""
    manifest = valid_ui_demo()
    manifest["screens"][1]["ocr_anchor"] = "Order Search Results"  # loader rule
    manifest["meeting"] = meeting_of(manifest, archetype="webinar")  # schema rule
    path = write(tmp_path, "broken.yaml", manifest)
    with pytest.raises(GroundTruthError) as exc:
        load_manifest(path)
    message = str(exc.value)
    assert "broken.yaml" in message
    assert "webinar" in message
    assert "duplicate ocr_anchor" in message


def test_load_manifest_rejects_unparseable_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("meeting: [unclosed\n", encoding="utf-8")
    with pytest.raises(GroundTruthError) as exc:
        load_manifest(path)
    assert "bad.yaml" in str(exc.value)


def test_load_manifest_reports_a_missing_file_as_a_ground_truth_error(
    tmp_path: Path,
) -> None:
    """One error type for every way ground truth can fail to arrive.

    A caller walking a directory should not need a second `except` clause for
    a broken symlink or a file that vanished between listing and reading.
    """
    with pytest.raises(GroundTruthError) as exc:
        load_manifest(tmp_path / "gone.yaml")
    assert "gone.yaml" in str(exc.value)


def test_load_manifest_reports_a_non_utf8_file_as_a_ground_truth_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "latin1.yaml"
    path.write_bytes("meeting:\n  title: caf\xe9\n".encode("latin-1"))
    with pytest.raises(GroundTruthError) as exc:
        load_manifest(path)
    assert "latin1.yaml" in str(exc.value)


def test_load_manifest_reports_a_directory_as_a_ground_truth_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "a-directory.yaml").mkdir()
    with pytest.raises(GroundTruthError):
        load_manifest(tmp_path / "a-directory.yaml")


# --- manifest_paths ---------------------------------------------------------


def test_manifest_paths_reports_a_missing_directory_as_a_ground_truth_error(
    tmp_path: Path,
) -> None:
    """A renamed ground-truth directory must not escape as FileNotFoundError.

    Every caller is written to catch GroundTruthError; a bare OSError here
    would surface as a crash rather than "the ground truth is not where the
    harness looks".
    """
    with pytest.raises(GroundTruthError) as exc:
        manifest_paths(tmp_path / "not-here")
    assert "not-here" in str(exc.value)


def test_manifest_paths_matches_the_suffix_case_insensitively(tmp_path: Path) -> None:
    """A skipped manifest is a silently shrunken recall denominator."""
    write(tmp_path, "lower.yaml", valid_ui_demo())
    (tmp_path / "UPPER.YAML").write_text("{}", encoding="utf-8")
    (tmp_path / "short.YML").write_text("{}", encoding="utf-8")
    assert {path.name for path in manifest_paths(tmp_path)} == {
        "lower.yaml",
        "UPPER.YAML",
        "short.YML",
    }


def test_manifest_paths_does_not_recurse(tmp_path: Path) -> None:
    """Manifests are one flat set; a subdirectory is a filing decision nobody made."""
    write(tmp_path, "top.yaml", valid_ui_demo())
    nested = tmp_path / "archive"
    nested.mkdir()
    write(nested, "old.yaml", valid_slide_deck())
    assert [path.name for path in manifest_paths(tmp_path)] == ["top.yaml"]


def test_load_all_reports_a_broken_manifest_symlink(tmp_path: Path) -> None:
    """A broken YAML fixture is invalid ground truth, never an omitted fixture."""
    (tmp_path / "broken.yaml").symlink_to(tmp_path / "missing.yaml")
    with pytest.raises(GroundTruthError) as exc:
        load_all(tmp_path)
    assert "broken.yaml" in str(exc.value)


# --- load_all: the corpus-level rules ---------------------------------------


def test_load_all_loads_every_manifest(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", valid_ui_demo())
    write(tmp_path, "b.yaml", valid_slide_deck())
    manifests = load_all(tmp_path)
    assert [m.id for m in manifests] == ["demo-fixture-ui", "demo-fixture-deck"]


def test_load_all_ignores_non_manifest_files(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", valid_ui_demo())
    (tmp_path / "README.md").write_text("notes", encoding="utf-8")
    assert len(load_all(tmp_path)) == 1


def test_load_all_rejects_a_duplicate_source_id(tmp_path: Path) -> None:
    """Two manifests claiming one drop would both match the same meeting."""
    write(tmp_path, "a.yaml", valid_ui_demo())
    second = valid_slide_deck()
    second["meeting"] = meeting_of(second, source_id="source-ui-1")
    write(tmp_path, "b.yaml", second)
    with pytest.raises(GroundTruthError) as exc:
        load_all(tmp_path)
    message = str(exc.value)
    assert "duplicate source_id 'source-ui-1'" in message
    assert "a.yaml" in message and "b.yaml" in message


def test_load_all_rejects_a_duplicate_meeting_id(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", valid_ui_demo())
    second = valid_slide_deck()
    second["meeting"] = meeting_of(second, id="demo-fixture-ui")
    write(tmp_path, "b.yaml", second)
    with pytest.raises(GroundTruthError) as exc:
        load_all(tmp_path)
    assert "duplicate meeting.id 'demo-fixture-ui'" in str(exc.value)


def test_load_all_reports_a_broken_file_by_name(tmp_path: Path) -> None:
    write(tmp_path, "good.yaml", valid_ui_demo())
    broken = valid_slide_deck()
    del broken["slides"][0]["ocr_anchor"]
    write(tmp_path, "broken.yaml", broken)
    with pytest.raises(GroundTruthError) as exc:
        load_all(tmp_path)
    assert "broken.yaml" in str(exc.value)
    assert "good.yaml" not in str(exc.value)
