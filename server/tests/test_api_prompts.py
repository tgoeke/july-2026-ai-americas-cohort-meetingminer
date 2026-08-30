"""Contract test for `GET /extraction/prompts` (story 4.2, epics AC1).

Field-set-literal pinning, the same style as `test_api_moments.py`. No
seeding needed: the route reads `request.app.state.config` directly, which
the `client` fixture (via `meetingminer.api.main.CONFIG`) loads from the
committed `config.yaml` — so this test is also the story's first acceptance
criterion, verbatim: "Given the committed config.yaml, when GET
/extraction/prompts is called, then it returns the full, current text of
both prompts, keyed adr/action-item."
"""

from __future__ import annotations

from meetingminer.config import AppConfig

RESPONSE_FIELDS = {"prompts"}
PROMPT_FIELDS = {"kind", "promptText"}


def test_extraction_prompts_returns_both_kinds_verbatim(
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
    # Story 10.1 adds `topic`; its text is pinned verbatim in
    # test_api_extraction_prompts_topics.py.
    assert set(by_kind) == {"adr", "action-item", "topic"}
    assert by_kind["adr"] == binding.arch_summary_prompt
    assert by_kind["action-item"] == binding.action_items_prompt
    # The committed default's load-bearing parser shape (AD-10 comment in
    # config.yaml) — a sanity check that this is real prompt text, not a
    # placeholder.
    assert "## Decisions" in by_kind["adr"]
    assert "## Action items" in by_kind["action-item"]
