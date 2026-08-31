"""Story 8.2: the api surface that persists and serves a per-role model selection.

`GET /settings/models` is the surface story 8.1 deliberately did not build — the
catalog was declared in `config.yaml` and visible nowhere in a running system.
`PUT /settings/roles/{role}` is what makes a picker real rather than decorative.

Nothing here hardcodes a model tag beside `config.yaml`. Story 8.1's review
found exactly that: assertions that read as meaningful while actually restating
the file. Every binding used below is read from the loaded configuration, so a
config edit changes what these tests exercise rather than what they claim.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from meetingminer.config import AppConfig
from meetingminer.domain import model_selection
from meetingminer.domain.model_providers import provider_for_model

PROBLEM_JSON = "application/problem+json"


@pytest.fixture(autouse=True)
def clear_settings(test_pool: ConnectionPool) -> Iterator[None]:
    """`app_setting` is not evidence, so conftest's TRUNCATE does not reach it.

    Cleared here rather than by widening `EVIDENCE_TABLES`: that tuple is a
    statement about which tables hold a meeting's evidence, and a settings row
    is neither evidence nor another story's to add.
    """
    with test_pool.connection() as conn:
        conn.execute("DELETE FROM app_setting")
    yield
    with test_pool.connection() as conn:
        conn.execute("DELETE FROM app_setting")


def _roles(app_config: AppConfig) -> Any:
    return app_config.settings.llm.roles


def _alternative(app_config: AppConfig, role: str) -> str:
    """A catalog binding for ``role`` that is *not* its default.

    Read from the file so the test exercises a real second choice; if a role
    ever declares a one-entry catalog the test skips with that reason rather
    than asserting against an invented tag.
    """
    binding = getattr(_roles(app_config), role)
    others = [
        entry.binding
        for entry in binding.catalog
        if entry.binding != (binding.default or binding.model)
    ]
    if not others:
        pytest.skip(f"`llm.roles.{role}` declares a one-entry catalog in config.yaml")
    return others[0]


def _role_view(payload: dict[str, Any], role: str) -> dict[str, Any]:
    matches = [row for row in payload["roles"] if row["role"] == role]
    assert matches, f"{role!r} missing from {[r['role'] for r in payload['roles']]}"
    return matches[0]


# --- GET /settings/models ---------------------------------------------------


def test_the_catalog_is_served_with_the_active_selection(
    client: TestClient, app_config: AppConfig
) -> None:
    response = client.get("/settings/models")

    assert response.status_code == 200
    payload = response.json()
    assert {row["role"] for row in payload["roles"]} == {
        "extraction",
        "chat",
        "judge",
    }

    chat = _role_view(payload, "chat")
    configured = _roles(app_config).chat
    assert [entry["binding"] for entry in chat["catalog"]] == [
        entry.binding for entry in configured.catalog
    ]
    assert chat["catalog"][0]["provider"] == provider_for_model(
        configured.catalog[0].binding
    )
    assert chat["catalog"][0]["label"] == configured.catalog[0].label


def test_with_nothing_chosen_every_role_reports_the_files_default(
    client: TestClient, app_config: AppConfig
) -> None:
    payload = client.get("/settings/models").json()

    for role in ("extraction", "chat", "judge"):
        view = _role_view(payload, role)
        configured = getattr(_roles(app_config), role)
        assert view["selected"] is None
        assert view["effectiveBinding"] == configured.default
        assert view["source"] == "file-default"
        assert view["fileModel"] == configured.model
        assert view["staleSelection"] is None


# --- PUT /settings/roles/{role} ---------------------------------------------


def test_a_selection_persists_and_is_what_the_role_resolves_to(
    client: TestClient, app_config: AppConfig, test_pool: ConnectionPool
) -> None:
    chosen = _alternative(app_config, "chat")

    put = client.put("/settings/roles/chat", json={"binding": chosen})

    assert put.status_code == 200
    assert put.json()["effectiveBinding"] == chosen
    assert put.json()["source"] == "selection"

    # Served on the next read, and durable in the store rather than in process
    # memory — a restart must not lose the choice.
    assert _role_view(client.get("/settings/models").json(), "chat")[
        "effectiveBinding"
    ] == chosen
    with test_pool.connection() as conn:
        assert model_selection.read_selection(conn, "chat") == chosen


def test_choosing_again_replaces_rather_than_accumulates(
    client: TestClient, app_config: AppConfig, test_pool: ConnectionPool
) -> None:
    chosen = _alternative(app_config, "chat")
    default = _roles(app_config).chat.default

    client.put("/settings/roles/chat", json={"binding": chosen})
    second = client.put("/settings/roles/chat", json={"binding": default})

    assert second.json()["effectiveBinding"] == default
    with test_pool.connection() as conn:
        rows = conn.execute(
            "SELECT count(*) FROM app_setting WHERE key = %s",
            (model_selection.selection_key("chat"),),
        ).fetchone()
    assert rows[0] == 1


def test_one_roles_selection_does_not_move_another(
    client: TestClient, app_config: AppConfig
) -> None:
    client.put(
        "/settings/roles/chat", json={"binding": _alternative(app_config, "chat")}
    )

    payload = client.get("/settings/models").json()

    assert _role_view(payload, "extraction")["source"] == "file-default"
    assert (
        _role_view(payload, "extraction")["effectiveBinding"]
        == _roles(app_config).extraction.default
    )


# --- refusals ---------------------------------------------------------------


def test_a_binding_outside_the_catalog_is_refused_and_nothing_is_written(
    client: TestClient, app_config: AppConfig, test_pool: ConnectionPool
) -> None:
    response = client.put(
        "/settings/roles/chat", json={"binding": "openai/not-in-any-catalog"}
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:binding-not-in-catalog"
    assert "openai/not-in-any-catalog" in body["detail"]
    assert "chat" in body["detail"]
    # The refusal says what *is* legal, so the caller does not have to guess.
    for entry in _roles(app_config).chat.catalog:
        assert entry.binding in body["detail"]

    with test_pool.connection() as conn:
        assert model_selection.read_selection(conn, "chat") is None


def test_an_unknown_role_is_refused_by_name(client: TestClient) -> None:
    response = client.put("/settings/roles/nonesuch", json={"binding": "anything"})

    assert response.status_code == 404
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:unknown-role"
    for role in ("extraction", "chat", "judge"):
        assert role in body["detail"]


def test_a_blank_binding_is_refused(client: TestClient) -> None:
    response = client.put("/settings/roles/chat", json={"binding": "   "})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_JSON)


# --- the catalog changing under a stored selection --------------------------


def test_a_stored_selection_the_catalog_dropped_is_reported_not_applied(
    client: TestClient, app_config: AppConfig, test_pool: ConnectionPool
) -> None:
    """`config.yaml` is edited independently of the store.

    Written straight to the table, because the write path refuses exactly this
    value — which is the point: the row can only reach this state by the
    catalog changing after it was written.
    """
    with test_pool.connection() as conn:
        model_selection.write_selection(conn, "chat", "openai/withdrawn-model")

    view = _role_view(client.get("/settings/models").json(), "chat")

    assert view["effectiveBinding"] == _roles(app_config).chat.default
    assert view["source"] == "file-default"
    assert view["selected"] == "openai/withdrawn-model"
    assert view["staleSelection"] == "openai/withdrawn-model"
    assert "openai/withdrawn-model" in view["staleReason"]
