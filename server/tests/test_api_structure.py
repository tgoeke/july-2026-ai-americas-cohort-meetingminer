"""Contract tests for the series/project/product routes (story 2.5;
Postgres only).

One test per row of the story's I/O matrix, plus the extras the Tasks section
calls out: a series reassignment replaces the single `meeting_series` row
rather than accumulating a second, and an assignment survives being read back
through `GET /series` `meetingIds`.

Meetings come from `projection_seed.seed_meeting` — the router only checks the
meeting exists, so the full bundle is inert but harmless; everything else is
created through the API itself, because this router is AD-5's write path.
"""

from __future__ import annotations

from uuid import uuid4

from psycopg_pool import ConnectionPool

from projection_seed import seed_meeting

ENTITY_FIELDS = {"id", "name", "createdAt", "updatedAt"}


def _meeting(pool: ConnectionPool, *, source_id: str):
    with pool.connection() as conn:
        return seed_meeting(conn, source_id=source_id).meeting_id


def _series_rows(pool: ConnectionPool, meeting_id):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT series_id FROM meeting_series WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchall()


# --- create ---------------------------------------------------------------


def test_create_series_returns_the_row(client) -> None:
    response = client.post("/series", json={"name": "Weekly Data Hub Sync"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == ENTITY_FIELDS
    assert body["name"] == "Weekly Data Hub Sync"


def test_create_duplicate_name_is_a_409_per_entity_type(client) -> None:
    for path in ("/series", "/products", "/projects"):
        assert client.post(path, json={"name": "Dup"}).status_code == 201
        response = client.post(path, json={"name": "Dup"})
        assert response.status_code == 409, (path, response.text)
        assert response.json()["type"] == "urn:meetingminer:problem:name-taken"


def test_the_same_name_is_allowed_across_entity_types(client) -> None:
    """`UNIQUE` is per table: a product and a project may share a name."""
    for path in ("/series", "/products", "/projects"):
        response = client.post(path, json={"name": "Data Hub"})
        assert response.status_code == 201, (path, response.text)


def test_blank_name_is_a_422(client) -> None:
    for path in ("/series", "/products", "/projects"):
        for bad in ("", "   ", "with\x00nul"):
            response = client.post(path, json={"name": bad})
            assert response.status_code == 422, (path, bad, response.text)
            assert (
                response.json()["type"] == "urn:meetingminer:problem:invalid-request"
            )


def test_create_project_with_and_without_product(client) -> None:
    product_id = client.post("/products", json={"name": "Data Hub"}).json()["id"]

    response = client.post(
        "/projects", json={"name": "Feed Migration", "productId": product_id}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == ENTITY_FIELDS | {"productId"}
    assert body["productId"] == product_id

    bare = client.post("/projects", json={"name": "Unhomed"})
    assert bare.status_code == 201, bare.text
    assert bare.json()["productId"] is None


def test_create_project_with_unknown_product_is_a_404(client) -> None:
    response = client.post(
        "/projects", json={"name": "Orphan", "productId": str(uuid4())}
    )
    assert response.status_code == 404, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


# --- project -> product assignment ---------------------------------------


def test_assign_project_to_product(client) -> None:
    project_id = client.post("/projects", json={"name": "Feed"}).json()["id"]
    product_id = client.post("/products", json={"name": "Hub"}).json()["id"]

    response = client.patch(
        f"/projects/{project_id}", json={"productId": product_id}
    )
    assert response.status_code == 200, response.text
    assert response.json()["productId"] == product_id


def test_assign_project_unknown_ids_are_404s(client) -> None:
    product_id = client.post("/products", json={"name": "Hub"}).json()["id"]
    project_id = client.post("/projects", json={"name": "Feed"}).json()["id"]

    response = client.patch(f"/projects/{uuid4()}", json={"productId": product_id})
    assert response.status_code == 404, response.text
    response = client.patch(
        f"/projects/{project_id}", json={"productId": str(uuid4())}
    )
    assert response.status_code == 404, response.text


def test_clear_projects_product(client) -> None:
    product_id = client.post("/products", json={"name": "Hub"}).json()["id"]
    project_id = client.post(
        "/projects", json={"name": "Feed", "productId": product_id}
    ).json()["id"]

    response = client.patch(f"/projects/{project_id}", json={"productId": None})
    assert response.status_code == 200, response.text
    assert response.json()["productId"] is None


# --- meeting -> series assignment -----------------------------------------


def test_assign_meeting_to_series(client, test_pool) -> None:
    meeting_id = _meeting(test_pool, source_id="structure-series")
    series_id = client.post("/series", json={"name": "Sync"}).json()["id"]

    response = client.put(
        f"/meetings/{meeting_id}/series", json={"seriesId": series_id}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"meetingId": str(meeting_id), "seriesId": series_id}


def test_series_reassignment_replaces_the_single_row(client, test_pool) -> None:
    meeting_id = _meeting(test_pool, source_id="structure-reassign")
    first = client.post("/series", json={"name": "First"}).json()["id"]
    second = client.post("/series", json={"name": "Second"}).json()["id"]

    client.put(f"/meetings/{meeting_id}/series", json={"seriesId": first})
    response = client.put(
        f"/meetings/{meeting_id}/series", json={"seriesId": second}
    )
    assert response.status_code == 200, response.text
    rows = _series_rows(test_pool, meeting_id)
    assert [str(row[0]) for row in rows] == [second]


def test_assign_meeting_series_unknown_ids_are_404s(client, test_pool) -> None:
    meeting_id = _meeting(test_pool, source_id="structure-404s")
    series_id = client.post("/series", json={"name": "Sync"}).json()["id"]

    response = client.put(f"/meetings/{uuid4()}/series", json={"seriesId": series_id})
    assert response.status_code == 404, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"
    response = client.put(
        f"/meetings/{meeting_id}/series", json={"seriesId": str(uuid4())}
    )
    assert response.status_code == 404, response.text


def test_clear_meeting_series_deletes_the_row(client, test_pool) -> None:
    meeting_id = _meeting(test_pool, source_id="structure-clear")
    series_id = client.post("/series", json={"name": "Sync"}).json()["id"]
    client.put(f"/meetings/{meeting_id}/series", json={"seriesId": series_id})

    response = client.put(f"/meetings/{meeting_id}/series", json={"seriesId": None})
    assert response.status_code == 200, response.text
    assert response.json() == {"meetingId": str(meeting_id), "seriesId": None}
    assert _series_rows(test_pool, meeting_id) == []


# --- meeting -> project assignment ----------------------------------------


def test_assign_and_clear_meeting_project(client, test_pool) -> None:
    meeting_id = _meeting(test_pool, source_id="structure-project")
    project_id = client.post("/projects", json={"name": "Feed"}).json()["id"]

    response = client.put(
        f"/meetings/{meeting_id}/project", json={"projectId": project_id}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"meetingId": str(meeting_id), "projectId": project_id}

    response = client.put(f"/meetings/{meeting_id}/project", json={"projectId": None})
    assert response.status_code == 200, response.text
    assert response.json() == {"meetingId": str(meeting_id), "projectId": None}


def test_assign_meeting_project_unknown_ids_are_404s(client, test_pool) -> None:
    meeting_id = _meeting(test_pool, source_id="structure-project-404s")
    project_id = client.post("/projects", json={"name": "Feed"}).json()["id"]

    response = client.put(
        f"/meetings/{uuid4()}/project", json={"projectId": project_id}
    )
    assert response.status_code == 404, response.text
    response = client.put(
        f"/meetings/{meeting_id}/project", json={"projectId": str(uuid4())}
    )
    assert response.status_code == 404, response.text


# --- lists ----------------------------------------------------------------


def test_lists_carry_all_rows_product_ids_and_ordered_meeting_ids(
    client, test_pool
) -> None:
    """`GET /series|/projects|/products` return every row; projects carry
    `productId`; series and project rows carry `meetingIds` ordered by when
    the meeting happened — the read-back that proves an assignment persisted."""
    from datetime import datetime, timezone

    with test_pool.connection() as conn:
        later = seed_meeting(
            conn,
            source_id="structure-list-later",
            started_at=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        ).meeting_id
        earlier = seed_meeting(
            conn,
            source_id="structure-list-earlier",
            started_at=datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc),
        ).meeting_id

    series_id = client.post("/series", json={"name": "Sync"}).json()["id"]
    product_id = client.post("/products", json={"name": "Hub"}).json()["id"]
    project_id = client.post(
        "/projects", json={"name": "Feed", "productId": product_id}
    ).json()["id"]
    # Assigned later-first, listed in meeting time order regardless.
    for meeting_id in (later, earlier):
        client.put(f"/meetings/{meeting_id}/series", json={"seriesId": series_id})
        client.put(f"/meetings/{meeting_id}/project", json={"projectId": project_id})

    series = client.get("/series").json()
    assert [row["name"] for row in series] == ["Sync"]
    assert series[0]["meetingIds"] == [str(earlier), str(later)]

    projects = client.get("/projects").json()
    assert [row["name"] for row in projects] == ["Feed"]
    assert projects[0]["productId"] == product_id
    assert projects[0]["meetingIds"] == [str(earlier), str(later)]

    products = client.get("/products").json()
    assert [row["name"] for row in products] == ["Hub"]
    assert set(products[0]) == ENTITY_FIELDS


def test_an_unassigned_series_lists_empty_meeting_ids(client) -> None:
    client.post("/series", json={"name": "Empty"})
    series = client.get("/series").json()
    assert series[0]["meetingIds"] == []


# --- malformed ids --------------------------------------------------------


def test_malformed_uuid_path_params_are_422s(client) -> None:
    for method, path, body in (
        ("patch", "/projects/not-a-uuid", {"productId": None}),
        ("put", "/meetings/not-a-uuid/series", {"seriesId": None}),
        ("put", "/meetings/not-a-uuid/project", {"projectId": None}),
    ):
        response = getattr(client, method)(path, json=body)
        assert response.status_code == 422, (path, response.text)
        assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_a_missing_key_is_a_422_not_a_clear(client, test_pool) -> None:
    """Required-but-nullable: `{}` (key absent) must be rejected, never read
    as `null` — an accidental empty body must not clear an assignment."""
    meeting_id = _meeting(test_pool, source_id="structure-missing-key")
    project_id = client.post("/projects", json={"name": "Missing Key"}).json()["id"]

    for method, path in (
        ("put", f"/meetings/{meeting_id}/series"),
        ("put", f"/meetings/{meeting_id}/project"),
        ("patch", f"/projects/{project_id}"),
    ):
        response = getattr(client, method)(path, json={})
        assert response.status_code == 422, (path, response.text)
        assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_clearing_an_unassigned_meeting_is_a_200_with_null(client, test_pool) -> None:
    """The DELETE-of-nothing path: null-clear on a meeting with no assignment
    row succeeds idempotently."""
    meeting_id = _meeting(test_pool, source_id="structure-clear-nothing")

    response = client.put(f"/meetings/{meeting_id}/series", json={"seriesId": None})
    assert response.status_code == 200, response.text
    assert response.json() == {"meetingId": str(meeting_id), "seriesId": None}

    response = client.put(f"/meetings/{meeting_id}/project", json={"projectId": None})
    assert response.status_code == 200, response.text
    assert response.json() == {"meetingId": str(meeting_id), "projectId": None}


def test_a_non_uuid_body_id_is_a_422(client, test_pool) -> None:
    meeting_id = _meeting(test_pool, source_id="structure-bad-body-id")
    project_id = client.post("/projects", json={"name": "Bad Body Id"}).json()["id"]

    for method, path, body in (
        ("put", f"/meetings/{meeting_id}/series", {"seriesId": "not-a-uuid"}),
        ("put", f"/meetings/{meeting_id}/project", {"projectId": "not-a-uuid"}),
        ("patch", f"/projects/{project_id}", {"productId": "not-a-uuid"}),
        ("post", "/projects", {"name": "Bad Product Ref", "productId": "not-a-uuid"}),
    ):
        response = getattr(client, method)(path, json=body)
        assert response.status_code == 422, (path, response.text)
        assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_patch_response_carries_created_at_and_advances_updated_at(client) -> None:
    """Pins migration 0013's `set_updated_at` trigger — the only observation
    of it in the suite (same idiom as the participants rename test)."""
    product_id = client.post("/products", json={"name": "Trigger Hub"}).json()["id"]
    before = client.post("/projects", json={"name": "Trigger Feed"}).json()

    response = client.patch(f"/projects/{before['id']}", json={"productId": product_id})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["createdAt"] == before["createdAt"]
    assert body["updatedAt"] > before["updatedAt"]
