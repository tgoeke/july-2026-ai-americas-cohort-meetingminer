"""/health contract: exact JSON keys and values against the repo's known config."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest


def test_health_returns_exact_contract() -> None:
    # Imported here so a config problem surfaces as this test's failure,
    # not as a collection error for the whole module.
    import meetingminer.api.main as api_main

    client = TestClient(api_main.app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "meetingminer-api",
        "configVersion": 1,
    }


def test_openapi_schema_types_health_response() -> None:
    import meetingminer.api.main as api_main

    client = TestClient(api_main.app)
    schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/health"]["get"]
    assert operation["operationId"] == "getHealth"

    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    model = schema["components"]["schemas"][ref.rsplit("/", 1)[1]]
    assert set(model["properties"]) == {"status", "service", "configVersion"}


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_health_allows_the_configured_vite_origins(origin: str) -> None:
    import meetingminer.api.main as api_main

    client = TestClient(api_main.app)
    response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
