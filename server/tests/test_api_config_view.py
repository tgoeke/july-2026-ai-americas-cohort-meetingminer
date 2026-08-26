"""GET /config contract tests (story ui-1, SPEC-ui-reimagine CAP-3).

Two non-negotiables from the spec, pinned the same way ``/status``'s are
(`test_api_status.py`, the secret-discipline precedent):

* **Secrets never serialize.** Asserted against a config whose secrets are
  known fake strings: no key/password value — nor a prefix long enough to
  matter — appears anywhere in the serialized response. The endpoint reads
  no ``config.secrets`` field at all, and this test is what keeps it that way.
* **Allowlist, never a model dump.** The exact field set of every section is
  pinned below, so an implementation change that starts serializing a
  ``Settings`` sub-model wholesale — where a future field would ride along
  unreviewed — fails here the moment ``Settings`` gains any field.
"""

from __future__ import annotations

import pytest

import meetingminer.api.main as api_main
from meetingminer.config import AppConfig

# The same fake-secret vocabulary test_api_status.py uses, so the two
# secret-discipline pins stay one recognizable pattern.
FAKE_SECRETS = {
    "anthropic_api_key": "sk-ant-FAKE-SECRET-anthropic-0000",
    "openai_api_key": "sk-FAKE-SECRET-openai-1111",
    "openrouter_api_key": "sk-or-FAKE-SECRET-openrouter-2222",
    "postgres_password": "FAKE-SECRET-postgres-3333",
    "neo4j_password": "FAKE-SECRET-neo4j-4444",
    "meili_master_key": "FAKE-SECRET-meili-5555",
}

RESPONSE_FIELDS = {
    "service", "configVersion", "llmRoles", "providers", "embedder", "stt",
    "ocr", "diarizer", "pipeline", "projections", "api", "stores",
}
ROLE_FIELDS = {
    "role", "model", "fallback", "provider", "endpoint", "fallbackEndpoint",
    "timeoutSeconds", "numCtx", "archSummaryPrompt", "actionItemsPrompt",
}
PIPELINE_FIELDS = {"frames", "screens", "align", "moments"}
FRAMES_FIELDS = {"intervalSeconds", "jpegQuality"}
SCREENS_FIELDS = {
    "analysisWidth", "pixelDiffThreshold", "whitePixelLevel",
    "changeThreshold", "settleThreshold", "settleTextGrowthRatio",
    "settleTimeoutSeconds", "cropSurveyFrames", "cropColumnWhiteMax",
    "cropMinRegionWidth", "cropRowStaticRangeMax", "cropMaxBottomStrip",
    "cameraMaxWhiteFraction", "cameraMinSaturation", "lineageThreshold",
    "minSignatureTokens", "galleryMaxBlocks", "galleryMaxTextDensity",
    "slideMinBlockHeight", "slideMaxBlocks",
}
ALIGN_FIELDS = {"anchorWindowSeconds", "minMatchScore", "maxSegmentMs"}
MOMENTS_FIELDS = {"gapSeconds", "maxDurationMs"}
PROJECTIONS_FIELDS = {
    "chunking", "embedBatchSize", "momentsIndex", "chunksIndex", "synonyms",
}
INDEX_FIELDS = {
    "searchableAttributes", "filterableAttributes", "sortableAttributes",
    "rankingRules",
}
API_FIELDS = {"jobEventsPollSeconds", "jobEventsHeartbeatSeconds", "search", "chat"}
SEARCH_KNOB_FIELDS = {
    "defaultLimit", "maxLimit", "semanticRatio", "cropLength",
    "semanticScoreFloor",
}
CHAT_KNOB_FIELDS = {"retrievalLimit", "traversalRowLimit"}
STORES_FIELDS = {"postgres", "neo4j", "meilisearch"}
POSTGRES_FIELDS = {"host", "port", "database", "user"}
NEO4J_FIELDS = {"uri", "user"}
MEILISEARCH_FIELDS = {"url"}


@pytest.fixture()
def fake_secret_config(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> AppConfig:
    """The committed config with every secret replaced by a known fake string,
    installed as the app's config for the duration of one test."""
    config = app_config.model_copy(
        update={"secrets": app_config.secrets.model_copy(update=FAKE_SECRETS)}
    )
    monkeypatch.setattr(api_main.app.state, "config", config)
    return config


def test_no_secret_material_serializes(client, fake_secret_config: AppConfig) -> None:
    response = client.get("/config")
    assert response.status_code == 200, response.text
    for secret in FAKE_SECRETS.values():
        assert secret not in response.text
        assert secret[:12] not in response.text


def test_every_section_is_the_pinned_allowlist(
    client, fake_secret_config: AppConfig
) -> None:
    """Exact field sets at every level: a wholesale Settings serialization —
    the shape a future secret-bearing field would leak through — cannot pass."""
    body = client.get("/config").json()
    assert set(body) == RESPONSE_FIELDS
    for role in body["llmRoles"]:
        assert set(role) == ROLE_FIELDS
    assert set(body["embedder"]) == {"model", "dimension"}
    assert set(body["stt"]) == {"engine", "model"}
    assert set(body["ocr"]) == {"engine", "fallback"}
    assert set(body["diarizer"]) == {"engine"}
    assert set(body["pipeline"]) == PIPELINE_FIELDS
    assert set(body["pipeline"]["frames"]) == FRAMES_FIELDS
    assert set(body["pipeline"]["screens"]) == SCREENS_FIELDS
    assert set(body["pipeline"]["align"]) == ALIGN_FIELDS
    assert set(body["pipeline"]["moments"]) == MOMENTS_FIELDS
    assert set(body["projections"]) == PROJECTIONS_FIELDS
    assert set(body["projections"]["chunking"]) == {
        "chunkMaxChars", "chunkOverlapTurns",
    }
    assert set(body["projections"]["momentsIndex"]) == INDEX_FIELDS
    assert set(body["projections"]["chunksIndex"]) == INDEX_FIELDS
    assert set(body["api"]) == API_FIELDS
    assert set(body["api"]["search"]) == SEARCH_KNOB_FIELDS
    assert set(body["api"]["chat"]) == CHAT_KNOB_FIELDS
    assert set(body["stores"]) == STORES_FIELDS
    assert set(body["stores"]["postgres"]) == POSTGRES_FIELDS
    assert set(body["stores"]["neo4j"]) == NEO4J_FIELDS
    assert set(body["stores"]["meilisearch"]) == MEILISEARCH_FIELDS


def test_values_come_from_the_live_settings(
    client, fake_secret_config: AppConfig
) -> None:
    """Spot-check that the projection carries the loaded config's own values —
    the page renders the live stack, not a copy of defaults."""
    settings = fake_secret_config.settings
    body = client.get("/config").json()

    assert body["service"] == settings.service
    assert body["configVersion"] == settings.config_version
    assert body["embedder"]["model"] == settings.embedder.model
    assert body["embedder"]["dimension"] == settings.embedder.dimension
    assert body["stt"] == {"engine": settings.stt.engine, "model": settings.stt.model}
    assert body["providers"] == {
        name: endpoint.base_url for name, endpoint in settings.providers.items()
    }
    assert (
        body["pipeline"]["screens"]["changeThreshold"]
        == settings.pipeline.screens.change_threshold
    )
    assert (
        body["api"]["search"]["semanticRatio"] == settings.api.search.semantic_ratio
    )
    assert body["stores"]["postgres"]["host"] == settings.stores.postgres.host
    assert body["stores"]["postgres"]["port"] == settings.stores.postgres.port
    assert body["stores"]["neo4j"]["uri"] == settings.stores.neo4j.uri
    assert body["stores"]["meilisearch"]["url"] == settings.stores.meilisearch.url


def test_llm_roles_carry_prompts_and_resolved_endpoints(
    client, fake_secret_config: AppConfig
) -> None:
    """CAP-3: the three bindings, the extraction prompts in full, and the
    effective endpoint each primary model's calls go to."""
    settings = fake_secret_config.settings
    roles = settings.llm.roles
    body = client.get("/config").json()

    by_role = {row["role"]: row for row in body["llmRoles"]}
    assert set(by_role) == {"extraction", "chat", "judge"}

    extraction = by_role["extraction"]
    assert extraction["model"] == roles.extraction.model
    # The complete prompt templates (parent CAP-5's visibility mandate) —
    # what a config reader sees is literally what gets sent.
    assert extraction["archSummaryPrompt"] == roles.extraction.arch_summary_prompt
    assert extraction["actionItemsPrompt"] == roles.extraction.action_items_prompt

    for name, binding in (("chat", roles.chat), ("judge", roles.judge)):
        row = by_role[name]
        assert row["model"] == binding.model
        assert row["fallback"] == binding.fallback
        # Prompts belong to extraction only.
        assert row["archSummaryPrompt"] is None
        assert row["actionItemsPrompt"] is None
        # The resolved endpoint: the role's own override when set, else the
        # provider's entry; a role whose provider has no entry resolves None.
        if binding.base_url:
            assert row["endpoint"] == binding.base_url
        elif row["provider"] in settings.providers:
            assert row["endpoint"] == settings.providers[row["provider"]].base_url
