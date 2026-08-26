"""App-wide problem+json handlers: no api error may emit {"detail": ...}.

These tests need no database — handlers fire before any pool access.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

PROBLEM = "application/problem+json"


def _client() -> TestClient:
    import meetingminer.api.main as api_main

    # No lifespan: handler paths under test never touch the pool.
    return TestClient(api_main.app, raise_server_exceptions=False)


def test_unknown_path_is_404_problem_not_detail() -> None:
    response = _client().get("/nonexistent")
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:not-found"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert "detail" in body and body["detail"] != ""
    assert set(body) == {"type", "title", "status", "detail"}


def test_invalid_request_body_is_422_problem_not_detail() -> None:
    response = _client().post("/ingests", json={"wrongField": 1})
    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:invalid-request"
    assert body["status"] == 422
    assert "dropPath" in body["detail"]
    assert isinstance(body["errors"], list) and body["errors"]
    assert not isinstance(body.get("detail"), list)  # never FastAPI's default shape


def test_method_not_allowed_is_problem_json_with_allow_header() -> None:
    response = _client().delete("/health")
    assert response.status_code == 405
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "urn:meetingminer:problem:http-error"
    assert "GET" in response.headers["allow"]


def test_unexpected_exception_is_500_problem() -> None:
    import meetingminer.api.main as api_main

    # Throwaway route (kept out of the OpenAPI schema) to hit the catch-all.
    if not any(getattr(r, "path", None) == "/__boom" for r in api_main.app.routes):

        @api_main.app.get("/__boom", include_in_schema=False)
        def _boom() -> None:
            raise RuntimeError("kaboom")

    response = _client().get("/__boom")
    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:internal-error"
    assert body["status"] == 500
    assert "kaboom" not in body["detail"]  # internals never leak to clients


def test_openapi_declares_new_operations() -> None:
    schema = _client().get("/openapi.json").json()
    assert schema["paths"]["/ingests"]["post"]["operationId"] == "createIngest"
    assert schema["paths"]["/jobs/{job_id}"]["get"]["operationId"] == "getJob"
    post = schema["paths"]["/ingests"]["post"]
    assert "201" in post["responses"] and "200" in post["responses"]
