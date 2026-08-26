"""docs/source-drop.schema.json contract tests (no database needed)."""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest

from conftest import REPO_ROOT
from conftest import REAL_PROVENANCE_MIGRATED, REAL_PROVENANCE_PULLED, valid_metadata

SCHEMA_PATH = REPO_ROOT / "docs" / "source-drop.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(
    SCHEMA, format_checker=jsonschema.FormatChecker()
)


def errors(instance: Any) -> list[str]:
    return [e.message for e in VALIDATOR.iter_errors(instance)]


def test_schema_is_valid_draft_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_valid_metadata_with_pulled_provenance_passes() -> None:
    metadata = valid_metadata(provenance=dict(REAL_PROVENANCE_PULLED))
    assert errors(metadata) == []


def test_valid_metadata_with_migrated_provenance_passes() -> None:
    metadata = valid_metadata(provenance=dict(REAL_PROVENANCE_MIGRATED))
    assert errors(metadata) == []


def test_day_precision_and_participants_pass() -> None:
    metadata = valid_metadata(
        startedAt="2026-08-05T00:00:00Z",
        startedAtPrecision="day",
        participants=[
            {"displayName": "Peyton Fenwick", "aadObjectId": "00000000-0000-0000-0000-000000000001"},
            {"displayName": "Priya Holloway"},
        ],
    )
    assert errors(metadata) == []


@pytest.mark.parametrize(
    "field", ["schemaVersion", "sourceId", "corpus", "startedAt", "startedAtPrecision", "provenance"]
)
def test_missing_required_field_fails(field: str) -> None:
    metadata = valid_metadata()
    del metadata[field]
    assert errors(metadata), f"expected a violation when {field} is missing"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemaVersion", 4),  # 1-3 exist; a fourth needs a schema change
        ("schemaVersion", "2"),  # the enum is numeric, not a version string
        ("sourceId", ""),
        ("corpus", "synthetic"),
        ("startedAt", "8.5.26"),
        ("startedAt", "2026-08-05T12:00:19"),  # no UTC designator
        ("startedAt", "2026-08-05T12:00:19-05:00"),  # non-UTC offset
        ("startedAt", "2026-13-45T99:99:99Z"),  # impossible date-time (FormatChecker)
        ("startedAtPrecision", "hour"),
        ("provenance", "pulled by hand"),  # must be an object
        ("participants", [{"aadObjectId": "no-display-name"}]),
    ],
)
def test_invalid_field_value_fails(field: str, value: Any) -> None:
    metadata = valid_metadata(**{field: value})
    assert errors(metadata), f"expected a violation for {field}={value!r}"


def test_format_checker_asserts_date_time() -> None:
    """Guards against the format extras going missing: 'date-time' must be
    an actively checked format, not silently skipped."""
    assert "date-time" in VALIDATOR.format_checker.checkers


def test_day_precision_requires_midnight_time() -> None:
    metadata = valid_metadata(
        startedAt="2026-08-05T12:00:19Z", startedAtPrecision="day"
    )
    assert errors(metadata)


def test_unknown_top_level_field_fails() -> None:
    metadata = valid_metadata(groundTruthId="gt-1")
    assert errors(metadata)


# --- story 1.12: schemaVersion 2 and the `augments` declaration -------------


def test_version_1_without_augments_still_validates() -> None:
    """The back-compat half: all 28 existing drops carry version 1."""
    assert errors(valid_metadata()) == []


def test_version_2_without_augments_validates() -> None:
    """Version 2 is a superset: `augments` is optional, not required by it."""
    assert errors(valid_metadata(schemaVersion=2)) == []


def test_version_2_with_augments_validates() -> None:
    metadata = valid_metadata(
        schemaVersion=2, augments={"sourceId": "the-transcript-only-occurrence"}
    )
    assert errors(metadata) == []


def test_augments_may_name_a_different_source_than_the_drop_itself() -> None:
    """AD-1 admits both identity forms, so the two ids are allowed to differ.

    A recording recovered from the recorder's personal drive carries its own
    drive-item id; the *declaration* is the link, not the drop's own identity.
    """
    metadata = valid_metadata(
        "drive-item-recovered-later",
        schemaVersion=2,
        augments={"sourceId": "stream-url-of-the-original-recap"},
    )
    assert errors(metadata) == []


def test_version_1_with_augments_fails() -> None:
    """Fail-closed in the other direction.

    A version 1 consumer ignores an unknown field, and ignoring `augments`
    would ingest the recovered recording as a brand-new meeting and orphan
    every existing citation. So `augments` must imply version 2.
    """
    metadata = valid_metadata(augments={"sourceId": "target-1"})
    assert errors(metadata)


def test_augments_without_a_source_id_fails() -> None:
    metadata = valid_metadata(schemaVersion=2, augments={})
    assert errors(metadata)


def test_augments_with_an_empty_source_id_fails() -> None:
    metadata = valid_metadata(schemaVersion=2, augments={"sourceId": ""})
    assert errors(metadata)


def test_augments_with_an_extra_key_fails() -> None:
    """Closed like the top level: a second locator needs a schema change."""
    metadata = valid_metadata(
        schemaVersion=2, augments={"sourceId": "target-1", "meetingId": "guessed"}
    )
    assert errors(metadata)


def test_schema_documents_the_augments_declaration() -> None:
    assert "augments" in SCHEMA["description"]
    assert SCHEMA["properties"]["augments"]["required"] == ["sourceId"]
    assert SCHEMA["properties"]["schemaVersion"]["enum"] == [1, 2, 3]


def test_schema_documents_canonical_filenames() -> None:
    description = SCHEMA["description"]
    for name in (
        "metadata.json",
        "recording.mp4",
        "transcript.vtt",
        "transcript.txt",
        "extraction-summary.md",
        "extraction-action-items.md",
    ):
        assert name in description


# --- story 4.1a: schemaVersion 3 and the `extractions` declaration ----------


def test_version_3_without_extractions_validates() -> None:
    """Version 3 is a superset: `extractions` is optional, not required by it."""
    assert errors(valid_metadata(schemaVersion=3)) == []


def test_version_3_with_both_extraction_documents_validates() -> None:
    metadata = valid_metadata(
        schemaVersion=3,
        extractions={
            "archSummary": "extraction-summary.md",
            "actionItems": "extraction-action-items.md",
        },
    )
    assert errors(metadata) == []


def test_version_3_with_one_extraction_document_validates() -> None:
    """Adoption is per document kind, so a drop may carry only one of them."""
    metadata = valid_metadata(
        schemaVersion=3, extractions={"actionItems": "extraction-action-items.md"}
    )
    assert errors(metadata) == []


@pytest.mark.parametrize("version", [1, 2])
def test_an_older_version_carrying_extractions_fails(version: int) -> None:
    """Fail closed, the same way `augments` does.

    A consumer pinned to version 2 ignores an unknown field, and ignoring
    `extractions` would send a whole transcript to a model to re-derive
    documents the drop already carries.
    """
    metadata = valid_metadata(
        schemaVersion=version, extractions={"archSummary": "extraction-summary.md"}
    )
    assert errors(metadata)


def test_an_empty_extractions_object_fails() -> None:
    """The key is omitted, never emitted empty — `readParticipantGraph`'s rule."""
    assert errors(valid_metadata(schemaVersion=3, extractions={}))


def test_an_extractions_document_must_name_its_canonical_filename() -> None:
    metadata = valid_metadata(
        schemaVersion=3, extractions={"archSummary": "6.10.26 Some Meeting.md"}
    )
    assert errors(metadata)


def test_an_unknown_extractions_key_fails() -> None:
    """Closed like the top level: a third document needs a schema change."""
    metadata = valid_metadata(
        schemaVersion=3, extractions={"transcriptSummary": "extraction-summary.md"}
    )
    assert errors(metadata)


def test_an_augmenting_drop_that_also_carries_extractions_validates() -> None:
    """AC 8, and the reason the `augments` gate is a minimum rather than a const.

    Pinned to `schemaVersion: 2`, this drop would be unsatisfiable: `augments`
    would demand exactly 2 and `extractions` at least 3.
    """
    metadata = valid_metadata(
        schemaVersion=3,
        augments={"sourceId": "the-transcript-only-occurrence"},
        extractions={
            "archSummary": "extraction-summary.md",
            "actionItems": "extraction-action-items.md",
        },
    )
    assert errors(metadata) == []


def test_an_augmenting_drop_at_version_3_without_extractions_still_validates() -> None:
    metadata = valid_metadata(schemaVersion=3, augments={"sourceId": "target-1"})
    assert errors(metadata) == []


def test_schema_documents_the_extractions_declaration() -> None:
    assert "extractions" in SCHEMA["description"]
    assert SCHEMA["properties"]["extractions"]["minProperties"] == 1
    assert SCHEMA["properties"]["extractions"]["additionalProperties"] is False
