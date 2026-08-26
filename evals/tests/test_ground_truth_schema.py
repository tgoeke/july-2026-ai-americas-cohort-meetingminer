"""evals/ground-truth.schema.json contract tests (no stores, no api).

Mirrors server/tests/test_drop_schema.py: one module-level validator, an
`errors()` helper, parametrized missing-field and invalid-value cases, plus
tests asserting the schema documents its own rules — a closed schema whose
description does not say *why* it is closed teaches nobody.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest

from evals.harness.groundtruth import SCHEMA_PATH
from evals.tests.conftest import meeting_of, valid_slide_deck, valid_ui_demo

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(
    SCHEMA, format_checker=jsonschema.FormatChecker()
)


def errors(instance: Any) -> list[str]:
    return [e.message for e in VALIDATOR.iter_errors(instance)]


def test_schema_is_valid_draft_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_valid_ui_demo_passes() -> None:
    assert errors(valid_ui_demo()) == []


def test_valid_slide_deck_passes() -> None:
    assert errors(valid_slide_deck()) == []


def test_optional_sections_may_be_omitted() -> None:
    """`planted` and `qa` are for checks a manifest may not exercise yet."""
    manifest = valid_ui_demo()
    del manifest["planted"]
    del manifest["qa"]
    assert errors(manifest) == []


# --- the archetype/section binding -----------------------------------------


def test_ui_demo_declaring_slides_fails_and_names_the_key() -> None:
    manifest = valid_ui_demo(slides=[{"id": "S1", "title": "T", "ocr_anchor": "A"}])
    messages = errors(manifest)
    assert messages
    assert any("slides" in message for message in messages)


def test_slide_deck_declaring_screens_fails_and_names_the_key() -> None:
    manifest = valid_slide_deck(
        screens=[{"id": "SC1", "name": "N", "ocr_anchor": "A"}]
    )
    messages = errors(manifest)
    assert messages
    assert any("screens" in message for message in messages)


def test_ui_demo_without_screens_fails() -> None:
    manifest = valid_ui_demo()
    del manifest["screens"]
    assert errors(manifest)


def test_slide_deck_without_slides_fails() -> None:
    manifest = valid_slide_deck()
    del manifest["slides"]
    assert errors(manifest)


# --- required-ness ----------------------------------------------------------


@pytest.mark.parametrize("field", ["meeting", "participant_segments"])
def test_missing_required_top_level_section_fails(field: str) -> None:
    manifest = valid_ui_demo()
    del manifest[field]
    assert errors(manifest), f"expected a violation when {field} is missing"


@pytest.mark.parametrize(
    "field", ["id", "source_id", "title", "archetype", "duration_minutes", "participants"]
)
def test_missing_required_meeting_field_fails(field: str) -> None:
    meeting = meeting_of(valid_ui_demo())
    del meeting[field]
    assert errors(valid_ui_demo(meeting=meeting))


@pytest.mark.parametrize("field", ["id", "name", "shown_at", "ocr_anchor"])
def test_missing_required_screen_field_fails(field: str) -> None:
    manifest = valid_ui_demo()
    del manifest["screens"][0][field]
    assert errors(manifest), f"expected a violation when screens[0].{field} is missing"


@pytest.mark.parametrize("field", ["id", "title", "ocr_anchor"])
def test_missing_required_slide_field_fails(field: str) -> None:
    manifest = valid_slide_deck()
    del manifest["slides"][0][field]
    assert errors(manifest), f"expected a violation when slides[0].{field} is missing"


def test_a_slide_may_be_placed_without_a_timestamp() -> None:
    """The asymmetry with `screens` is deliberate (eval-design §1).

    A deck is shown front to back, so a slide can be authored without knowing
    when it appears; a demo walks screens in an order only the script knows,
    and checks 2.3 and 2.5 need that timing.
    """
    manifest = valid_slide_deck()
    del manifest["slides"][0]["shown_at"]
    assert errors(manifest) == []


@pytest.mark.parametrize("field", ["id", "text", "speaker", "at"])
def test_missing_required_planted_field_fails(field: str) -> None:
    manifest = valid_ui_demo()
    del manifest["planted"]["decisions"][0][field]
    assert errors(manifest)


@pytest.mark.parametrize(
    "field", ["id", "question", "expected_moment", "answer_must_contain"]
)
def test_missing_required_qa_field_fails(field: str) -> None:
    manifest = valid_ui_demo()
    del manifest["qa"][0][field]
    assert errors(manifest)


# --- invalid values ---------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("archetype", "webinar"),  # the enum is closed
        ("archetype", "ui_demo"),  # spelling is part of the contract
        ("duration_minutes", 0),  # a zero-length meeting has no captures
        ("duration_minutes", -5),
        ("duration_minutes", "12"),
        ("id", ""),
        ("source_id", ""),
        ("title", ""),
        ("participants", []),  # somebody is in the meeting
        ("participants", [{"role": "presenter"}]),  # name is required
        ("participants", [{"name": "Tim", "email": "tim@example.com"}]),  # closed
    ],
)
def test_invalid_meeting_field_fails(field: str, value: Any) -> None:
    manifest = valid_ui_demo()
    manifest["meeting"] = meeting_of(manifest, **{field: value})
    assert errors(manifest), f"expected a violation for meeting.{field}={value!r}"


@pytest.mark.parametrize(
    "anchor", ["", None, 7],
)
def test_invalid_ocr_anchor_fails(anchor: Any) -> None:
    """The recall check has nothing to match on without a real anchor."""
    manifest = valid_ui_demo()
    manifest["screens"][0]["ocr_anchor"] = anchor
    assert errors(manifest)


@pytest.mark.parametrize(
    "timestamp",
    [
        "1:30",  # unpadded
        "00:01",  # no seconds
        "00:01:30.5",
        "90",
        "",
        90,
    ],
)
def test_malformed_timestamp_fails(timestamp: Any) -> None:
    manifest = valid_ui_demo()
    manifest["participant_segments"][0]["at"] = timestamp
    assert errors(manifest), f"expected a violation for at={timestamp!r}"


def test_impossible_clock_time_passes_the_schema_and_is_left_to_the_loader() -> None:
    """`00:99:00` has the right shape and is not a time.

    Pinned deliberately: it documents the seam between the two validation
    layers, so nobody later assumes the pattern already caught it.
    """
    manifest = valid_ui_demo()
    manifest["participant_segments"][0]["at"] = "00:99:00"
    assert errors(manifest) == []


def test_duplicate_anchors_pass_the_schema_and_are_left_to_the_loader() -> None:
    manifest = valid_ui_demo()
    manifest["screens"][1]["ocr_anchor"] = manifest["screens"][0]["ocr_anchor"]
    assert errors(manifest) == []


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda m: m.update({"notes": "extra"}), id="top-level"),
        pytest.param(lambda m: m["screens"][0].update({"url": "/orders"}), id="screen"),
        pytest.param(
            lambda m: m["participant_segments"][0].update({"until": "00:01:00"}),
            id="segment",
        ),
        pytest.param(lambda m: m["planted"].update({"risks": []}), id="planted"),
        pytest.param(
            lambda m: m["planted"]["decisions"][0].update({"confidence": 0.9}),
            id="planted-item",
        ),
        pytest.param(lambda m: m["qa"][0].update({"answer": "yes"}), id="qa"),
    ],
)
def test_unknown_key_fails_at_every_level(mutation: Any) -> None:
    manifest = valid_ui_demo()
    mutation(manifest)
    assert errors(manifest)


def test_empty_participant_segments_fails() -> None:
    """Meeting start is always an expected capture, so the list is never empty."""
    assert errors(valid_ui_demo(participant_segments=[]))


# --- the schema documents its own rules -------------------------------------


def _subschemas(node: Any) -> list[dict[str, Any]]:
    """Every mapping in the schema tree, including `$defs` bodies."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found += _subschemas(value)
    elif isinstance(node, list):
        for value in node:
            found += _subschemas(value)
    return found


def test_every_object_schema_is_closed() -> None:
    """AD-1's convention, applied here: an unknown key is an authoring error.

    A manifest with a misspelled section would otherwise validate and silently
    contribute nothing to the recall denominator.
    """
    for subschema in _subschemas(SCHEMA):
        if subschema.get("type") == "object" and "properties" in subschema:
            assert subschema.get("additionalProperties") is False, (
                f"open object schema: {sorted(subschema['properties'])}"
            )


def test_schema_documents_the_independence_rule() -> None:
    description = SCHEMA["description"]
    assert "authored from the meeting script" in description
    assert "never derived from pipeline output" in description


def test_schema_documents_the_recall_denominator_formula() -> None:
    assert "slides (or screens) + participant_segments" in SCHEMA["description"]


def test_schema_documents_both_archetypes() -> None:
    archetype = SCHEMA["properties"]["meeting"]["properties"]["archetype"]
    assert archetype["enum"] == ["ui-demo", "slide-deck"]


def test_schema_documents_the_anchor_authoring_rule() -> None:
    anchor = SCHEMA["$defs"]["ocr_anchor"]["description"]
    assert "unique" in anchor
    assert "loader rule" in anchor


def test_schema_records_the_residual_anchor_collision_risk() -> None:
    """Exact-match uniqueness here vs fuzzy >= 0.8 matching in check 2.1.

    The gap is real and deliberately not closed by an invented threshold, so
    it is written down where the next story will read it rather than left to
    be rediscovered from a confusing recall failure.
    """
    anchor = SCHEMA["$defs"]["ocr_anchor"]["description"]
    assert "RESIDUAL RISK" in anchor
    assert "0.8" in anchor


def test_schema_documents_why_screens_are_timestamped_and_slides_need_not_be() -> None:
    assert SCHEMA["properties"]["screens"]["items"]["required"] == [
        "id",
        "name",
        "shown_at",
        "ocr_anchor",
    ]
    assert "shown_at" not in SCHEMA["properties"]["slides"]["items"]["required"]
    assert "`shown_at` is required here" in SCHEMA["properties"]["screens"]["description"]


def test_schema_documents_source_id_as_the_join_key() -> None:
    source_id = SCHEMA["properties"]["meeting"]["properties"]["source_id"]
    assert "sourceId" in source_id["description"]
    assert "placeholder" in source_id["description"]
