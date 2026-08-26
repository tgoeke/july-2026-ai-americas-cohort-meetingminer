"""Question classification, exercised in isolation (story 3.3, AD-7).

Store-free and model-free: `api/chat_router.py` is a pure parser over whatever
text a completer produced. The property under test is the one AD-7 depends on —
**the model classifies and code dispatches** — which means every reply the
registry cannot turn into a real dispatch has to degrade to search-only rather
than raise. A classifier that can crash a request is a model deciding whether
the api answers at all.
"""

from __future__ import annotations

import json

import pytest

from meetingminer.api.chat_router import (
    CLASSIFIER_VALUE_MAX_LENGTH,
    FALLBACK_REASONS,
    TEMPLATE_ANCHORS,
    build_classifier_prompt,
    parse_route,
)
from meetingminer.projections.traversals import TRAVERSAL_TEMPLATES

PARTICIPANT_TOPIC = {
    "template": "participant-topic-moments",
    "participant": "Clarence",
    "topic": "SFTP migration",
    "searchTerms": "SFTP migration Clarence",
}
SCREEN = {
    "template": "screen-history",
    "screen": "the vendor portal",
    "searchTerms": "vendor portal",
}


# --- the registry and the anchor map stay in step -------------------------


def test_every_registered_template_declares_its_anchors() -> None:
    """3.2 owns the registry; this router owns the natural-language anchors for
    it. A template added there without anchors here would be a template the
    classifier could name and the code could never dispatch — so it fails here
    rather than in a request."""
    assert set(TEMPLATE_ANCHORS) == set(TRAVERSAL_TEMPLATES)


def test_each_anchor_map_covers_exactly_its_templates_cypher_parameters() -> None:
    for name, anchors in TEMPLATE_ANCHORS.items():
        keywords = set(anchors.resolved.values()) | set(anchors.literal.values())
        assert keywords == set(TRAVERSAL_TEMPLATES[name].parameters), name


def test_the_prompt_names_every_registered_template_and_carries_the_question() -> None:
    prompt = build_classifier_prompt("  did I explain this to Clarence?  ")
    for name in TRAVERSAL_TEMPLATES:
        assert name in prompt
    assert "did I explain this to Clarence?" in prompt
    # The braces of the example JSON survived `str.format`.
    assert '{"template"' in prompt


# --- a decision code is willing to dispatch -------------------------------


def test_a_valid_participant_topic_decision_is_carried_through() -> None:
    decision = parse_route(json.dumps(PARTICIPANT_TOPIC))
    assert decision.template == "participant-topic-moments"
    assert decision.anchors == {"participant": "Clarence", "topic": "SFTP migration"}
    assert decision.search_terms == "SFTP migration Clarence"
    assert decision.fallback_reason is None


def test_a_valid_screen_history_decision_is_carried_through() -> None:
    decision = parse_route(json.dumps(SCREEN))
    assert decision.template == "screen-history"
    assert decision.anchors == {"screen": "the vendor portal"}


def test_anchors_are_stripped_but_never_otherwise_rewritten() -> None:
    """Name-to-id resolution is the orchestrator's job against Postgres; the
    router must not normalize a name into something a lookup cannot match."""
    decision = parse_route(json.dumps({**PARTICIPANT_TOPIC, "participant": "  Goeke, Timothy "}))
    assert decision.anchors["participant"] == "Goeke, Timothy"


def test_an_oversized_classifier_value_cannot_reach_a_dispatch() -> None:
    oversized = "x" * (CLASSIFIER_VALUE_MAX_LENGTH + 1)
    decision = parse_route(
        json.dumps(
            {
                "template": "participant-topic-moments",
                "participant": oversized,
                "topic": "purchase order",
                "searchTerms": oversized,
            }
        )
    )
    assert decision.template is None
    assert decision.fallback_reason == "missing-anchor"
    assert decision.search_terms is None


# --- every degradation path -----------------------------------------------


def test_a_fenced_reply_is_still_parsed() -> None:
    raw = "```json\n" + json.dumps(SCREEN) + "\n```"
    assert parse_route(raw).template == "screen-history"


def test_a_json_object_wrapped_in_prose_is_still_parsed() -> None:
    raw = f"Sure — here is the classification:\n{json.dumps(SCREEN)}\nHope that helps."
    assert parse_route(raw).template == "screen-history"


def test_the_first_object_in_a_prose_wrapped_multi_object_reply_is_parsed() -> None:
    raw = f"Classification: {json.dumps(SCREEN)}\nDiagnostic: {{\"retry\": false}}"
    decision = parse_route(raw)
    assert decision.template == "screen-history"
    assert decision.search_terms == "vendor portal"


def test_an_unregistered_template_degrades_to_search_only() -> None:
    decision = parse_route(json.dumps({"template": "moment-neighbours", "searchTerms": "sftp"}))
    assert decision.template is None
    assert decision.fallback_reason == "unregistered-template"
    # The search terms survive: a reply naming a template that does not exist
    # still told us what the question is about.
    assert decision.search_terms == "sftp"


@pytest.mark.parametrize(
    "payload",
    [
        {"template": "participant-topic-moments", "participant": "Clarence"},
        {"template": "participant-topic-moments", "topic": "SFTP"},
        {"template": "participant-topic-moments", "participant": "Clarence", "topic": "  "},
        {"template": "screen-history"},
        {"template": "screen-history", "screen": None},
    ],
)
def test_a_wrong_or_blank_parameter_set_degrades_to_search_only(payload: dict) -> None:
    """A blank topic would match the whole corpus and a missing anchor would
    raise inside `run_template`; neither is a routing decision."""
    decision = parse_route(json.dumps(payload))
    assert decision.template is None
    assert decision.fallback_reason == "missing-anchor"


def test_an_explicit_null_template_is_the_search_only_route() -> None:
    decision = parse_route(json.dumps({"template": None, "searchTerms": "revenue slide"}))
    assert decision.template is None
    assert decision.fallback_reason == "no-template"
    assert decision.search_terms == "revenue slide"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "I am sorry, I cannot help with that.",
        "{not json at all",
        "{'template': 'screen-history'}",  # python literal, not JSON
    ],
)
def test_junk_output_degrades_rather_than_raising(raw: str) -> None:
    decision = parse_route(raw)
    assert decision.template is None
    assert decision.fallback_reason == "unparsable"
    assert decision.search_terms is None


@pytest.mark.parametrize("raw", ["[]", '"screen-history"', "42", "null"])
def test_valid_json_that_is_not_an_object_degrades(raw: str) -> None:
    decision = parse_route(raw)
    assert decision.template is None
    assert decision.fallback_reason == "not-an-object"


def test_every_fallback_reason_the_parser_can_emit_is_declared() -> None:
    emitted = {
        parse_route(raw).fallback_reason
        for raw in (
            "junk",
            "[]",
            json.dumps({"template": None}),
            json.dumps({"template": "nope"}),
            json.dumps({"template": "screen-history"}),
        )
    }
    assert emitted == set(FALLBACK_REASONS)


def test_the_raw_reply_is_kept_for_the_log() -> None:
    assert parse_route("I cannot help").raw == "I cannot help"
