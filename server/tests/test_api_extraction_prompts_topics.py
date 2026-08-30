"""`GET /extraction/prompts` serves the topics prompt beside the other two (story 10.1).

Field-set-literal pinning, the same style as `test_api_prompts.py` — which
stays frozen at two entries by the wave footprint; the three-kind contract
lives here.
"""

from __future__ import annotations

from meetingminer.config import AppConfig

RESPONSE_FIELDS = {"prompts"}
PROMPT_FIELDS = {"kind", "promptText"}


def test_extraction_prompts_returns_three_kinds_with_topic_verbatim(
    client, app_config: AppConfig
) -> None:
    binding = app_config.settings.llm.roles.extraction

    response = client.get("/extraction/prompts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == RESPONSE_FIELDS
    assert len(body["prompts"]) == 3
    for entry in body["prompts"]:
        assert set(entry) == PROMPT_FIELDS

    by_kind = {entry["kind"]: entry["promptText"] for entry in body["prompts"]}
    assert set(by_kind) == {"adr", "action-item", "topic"}
    # The committed config's text, verbatim — no store, no re-derivation.
    assert by_kind["topic"] == binding.topics_prompt
    # The load-bearing parser shape of the committed default.
    assert "## Topics" in by_kind["topic"]
    # The other two are unchanged by the third's arrival.
    assert by_kind["adr"] == binding.arch_summary_prompt
    assert by_kind["action-item"] == binding.action_items_prompt
