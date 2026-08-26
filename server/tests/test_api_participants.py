"""Contract tests for the participant curation routes (story 2.4;
Postgres only).

One test per row of the story's I/O matrix, plus the extra assertions the
Tasks section calls out: a retried merge is refused rather than duplicated, a
merge shows up in `GET /participants` as `mergedIntoParticipantId`, and a
rename never touches `identity_key`/`normalized_name`.

Fixtures use `projection_seed.seed_participant`/`seed_participant_alias`
directly — a full `seed_meeting` would drag in a job, transcript and moments
this router never touches.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from psycopg_pool import ConnectionPool

from projection_seed import seed_participant, seed_participant_alias

PARTICIPANT_FIELDS = {
    "id", "identityKey", "displayName", "normalizedName", "mergedIntoParticipantId",
    "createdAt", "updatedAt",
}


def _participant(pool: ConnectionPool, *, identity_key: str, display_name: str):
    with pool.connection() as conn:
        return seed_participant(conn, identity_key=identity_key, display_name=display_name)


def _alias(pool: ConnectionPool, *, alias_key: str, participant_id) -> None:
    with pool.connection() as conn:
        seed_participant_alias(conn, alias_key=alias_key, participant_id=participant_id)


def test_list_returns_every_row_with_merge_state(client, test_pool) -> None:
    survivor = _participant(
        test_pool, identity_key="mail:list-a@contoso.com", display_name="List A"
    )
    absorbed = _participant(test_pool, identity_key="name:list b", display_name="List B")
    _alias(test_pool, alias_key="name:list b", participant_id=survivor)

    response = client.get("/participants")
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["id"]: row for row in body}
    assert set(rows[str(survivor)]) == PARTICIPANT_FIELDS
    assert rows[str(survivor)]["mergedIntoParticipantId"] is None
    assert rows[str(absorbed)]["mergedIntoParticipantId"] == str(survivor)


def test_rename_updates_display_name_and_leaves_identity_alone(client, test_pool) -> None:
    participant_id = _participant(
        test_pool, identity_key="mail:rename@contoso.com", display_name="Old Name"
    )

    response = client.patch(
        f"/participants/{participant_id}", json={"displayName": "New Name"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["displayName"] == "New Name"
    assert body["identityKey"] == "mail:rename@contoso.com"
    assert body["normalizedName"] == "old name"

    listed = client.get("/participants").json()
    row = next(r for r in listed if r["id"] == str(participant_id))
    assert row["displayName"] == "New Name"


def test_rename_response_carries_created_at_and_advances_updated_at(
    client, test_pool
) -> None:
    participant_id = _participant(
        test_pool, identity_key="mail:timestamps@contoso.com", display_name="Old Name"
    )
    before = client.get("/participants").json()
    before_row = next(r for r in before if r["id"] == str(participant_id))

    response = client.patch(
        f"/participants/{participant_id}", json={"displayName": "New Name"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["createdAt"] == before_row["createdAt"]
    assert body["updatedAt"] > before_row["updatedAt"]


def test_rename_unknown_id_is_a_404(client) -> None:
    response = client.patch(f"/participants/{uuid4()}", json={"displayName": "X"})
    assert response.status_code == 404, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_rename_a_merged_away_id_is_a_409(client, test_pool) -> None:
    survivor = _participant(
        test_pool, identity_key="mail:rename-survivor@contoso.com", display_name="Survivor"
    )
    absorbed = _participant(
        test_pool, identity_key="name:rename absorbed", display_name="Absorbed"
    )
    _alias(test_pool, alias_key="name:rename absorbed", participant_id=survivor)

    response = client.patch(
        f"/participants/{absorbed}", json={"displayName": "New Name"}
    )
    assert response.status_code == 409, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:already-merged"


def test_rename_blank_name_is_a_422(client, test_pool) -> None:
    participant_id = _participant(
        test_pool, identity_key="mail:blank@contoso.com", display_name="Someone"
    )
    for blank in ("", "   "):
        response = client.patch(
            f"/participants/{participant_id}", json={"displayName": blank}
        )
        assert response.status_code == 422, response.text
        assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_rename_nul_name_is_a_422_problem(client, test_pool) -> None:
    participant_id = _participant(
        test_pool, identity_key="mail:nul@contoso.com", display_name="Someone"
    )

    response = client.patch(
        f"/participants/{participant_id}", json={"displayName": "Bad\u0000Name"}
    )

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_merge_writes_one_alias_row_and_list_reflects_it(client, test_pool) -> None:
    survivor = _participant(
        test_pool, identity_key="mail:merge-survivor@contoso.com", display_name="Survivor"
    )
    absorbed = _participant(
        test_pool, identity_key="name:merge absorbed", display_name="Absorbed"
    )

    response = client.post(
        f"/participants/{absorbed}/merge", json={"intoParticipantId": str(survivor)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["id"]: row for row in body}
    assert rows[str(absorbed)]["mergedIntoParticipantId"] == str(survivor)
    assert rows[str(survivor)]["mergedIntoParticipantId"] is None

    with test_pool.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM participant_alias WHERE alias_key = %s",
            ("name:merge absorbed",),
        ).fetchone()[0]
    assert count == 1


def test_merge_self_is_a_422(client, test_pool) -> None:
    participant_id = _participant(
        test_pool, identity_key="mail:self@contoso.com", display_name="Self"
    )
    response = client.post(
        f"/participants/{participant_id}/merge",
        json={"intoParticipantId": str(participant_id)},
    )
    assert response.status_code == 422, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_merge_unknown_id_is_a_404(client, test_pool) -> None:
    survivor = _participant(
        test_pool, identity_key="mail:merge-404@contoso.com", display_name="Survivor"
    )
    response = client.post(
        f"/participants/{uuid4()}/merge", json={"intoParticipantId": str(survivor)}
    )
    assert response.status_code == 404, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"

    response = client.post(
        f"/participants/{survivor}/merge", json={"intoParticipantId": str(uuid4())}
    )
    assert response.status_code == 404, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_merge_already_merged_source_is_a_409_and_not_a_duplicate_alias(
    client, test_pool
) -> None:
    survivor = _participant(
        test_pool, identity_key="mail:idempotent-survivor@contoso.com", display_name="Survivor"
    )
    other = _participant(
        test_pool, identity_key="mail:idempotent-other@contoso.com", display_name="Other"
    )
    absorbed = _participant(
        test_pool, identity_key="name:idempotent absorbed", display_name="Absorbed"
    )

    first = client.post(
        f"/participants/{absorbed}/merge", json={"intoParticipantId": str(survivor)}
    )
    assert first.status_code == 200, first.text

    # Retrying the same merge is refused, not silently duplicated.
    retry = client.post(
        f"/participants/{absorbed}/merge", json={"intoParticipantId": str(survivor)}
    )
    assert retry.status_code == 409, retry.text
    assert retry.json()["type"] == "urn:meetingminer:problem:already-merged"

    # Retrying onto a *different* survivor is refused the same way.
    onto_other = client.post(
        f"/participants/{absorbed}/merge", json={"intoParticipantId": str(other)}
    )
    assert onto_other.status_code == 409, onto_other.text
    assert onto_other.json()["type"] == "urn:meetingminer:problem:already-merged"

    with test_pool.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM participant_alias WHERE alias_key = %s",
            ("name:idempotent absorbed",),
        ).fetchone()[0]
    assert count == 1


def test_merge_onto_a_non_canonical_target_is_a_409(client, test_pool) -> None:
    root = _participant(
        test_pool, identity_key="mail:chain-root@contoso.com", display_name="Root"
    )
    middle = _participant(
        test_pool, identity_key="name:chain middle", display_name="Middle"
    )
    _alias(test_pool, alias_key="name:chain middle", participant_id=root)
    tail = _participant(test_pool, identity_key="name:chain tail", display_name="Tail")

    response = client.post(
        f"/participants/{tail}/merge", json={"intoParticipantId": str(middle)}
    )
    assert response.status_code == 409, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:merge-target-not-canonical"


def test_merge_refuses_to_absorb_a_survivor_that_would_create_a_chain(
    client, test_pool
) -> None:
    final_survivor = _participant(
        test_pool, identity_key="mail:chain-final@contoso.com", display_name="Final"
    )
    middle = _participant(
        test_pool, identity_key="mail:chain-middle@contoso.com", display_name="Middle"
    )
    initial_absorbed = _participant(
        test_pool, identity_key="name:chain initial", display_name="Initial"
    )

    first = client.post(
        f"/participants/{initial_absorbed}/merge",
        json={"intoParticipantId": str(middle)},
    )
    assert first.status_code == 200, first.text

    chained = client.post(
        f"/participants/{middle}/merge",
        json={"intoParticipantId": str(final_survivor)},
    )
    assert chained.status_code == 409, chained.text
    assert chained.json()["type"] == "urn:meetingminer:problem:already-merged"

    with test_pool.connection() as conn:
        rows = conn.execute(
            "SELECT alias_key, participant_id FROM participant_alias ORDER BY alias_key"
        ).fetchall()
    assert rows == [("name:chain initial", middle)]


def test_a_malformed_id_is_a_422_problem_on_every_route(client) -> None:
    for path, method in (
        ("/participants/not-a-uuid", "patch"),
        ("/participants/not-a-uuid/merge", "post"),
    ):
        kwargs = (
            {"json": {"displayName": "X"}}
            if method == "patch"
            else {"json": {"intoParticipantId": str(uuid4())}}
        )
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 422, response.text
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_participant_routes_document_the_runtime_422_problem_contract(client) -> None:
    schema = client.app.openapi()
    assert schema["paths"]["/participants/{participant_id}"]["patch"]["responses"][
        "422"
    ]["content"] == {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"}
        }
    }


def test_merge_route_documents_the_runtime_409_problem_contract(client) -> None:
    """The merge route's two 409 variants (`already-merged`,
    `merge-target-not-canonical`) share one response entry — pin its runtime
    shape the same way the 422 contract above is pinned."""
    schema = client.app.openapi()
    response = schema["paths"]["/participants/{participant_id}/merge"]["post"][
        "responses"
    ]["409"]
    assert response["content"] == {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"}
        }
    }


def test_two_truly_concurrent_merges_of_the_same_absorbed_id_never_500(
    client, test_pool
) -> None:
    """Two real requests, issued from two real threads with no `await`
    between them, racing to merge the *same* absorbed id.

    `TestClient` is thread-safe for concurrent requests (each acquires its
    own connection from the pool), so this exercises the actual row lock and
    the `UniqueViolation` catch against real Postgres contention rather than
    a simulated interleaving. A `threading.Barrier` holds both threads at the
    door so neither's `POST` starts before the other is ready to fire,
    maximizing genuine overlap instead of leaving it to scheduling luck.
    """
    survivor = _participant(
        test_pool, identity_key="mail:race-survivor@contoso.com", display_name="Survivor"
    )
    absorbed = _participant(
        test_pool, identity_key="name:race absorbed", display_name="Absorbed"
    )
    start = threading.Barrier(2, timeout=10)

    def fire():
        start.wait()
        return client.post(
            f"/participants/{absorbed}/merge",
            json={"intoParticipantId": str(survivor)},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(fire)
        second_future = pool.submit(fire)
        first = first_future.result(timeout=30)
        second = second_future.result(timeout=30)

    statuses = {first.status_code, second.status_code}
    assert statuses == {200, 409}, (first.status_code, first.text, second.status_code, second.text)
    loser = first if first.status_code == 409 else second
    assert loser.json()["type"] == "urn:meetingminer:problem:already-merged"

    with test_pool.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM participant_alias WHERE alias_key = %s",
            ("name:race absorbed",),
        ).fetchone()[0]
    assert count == 1
