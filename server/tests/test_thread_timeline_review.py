"""Review regressions for Story 10.3's pure timeline decisions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from meetingminer.api.threads import router
from meetingminer.domain.thread_timeline import (
    BUCKET_LADDER_MS,
    LEVELS,
    TARGET_BUCKETS,
    plan_buckets,
)

from conftest import truncate_evidence
from test_api_threads import STARTED_AT, add_thread, add_topic, seed_meeting


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


def test_exact_target_boundary_keeps_the_finer_bucket_step() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exact_end = start + timedelta(
        milliseconds=TARGET_BUCKETS * BUCKET_LADDER_MS[0]
    )

    assert plan_buckets(start, exact_end) == (
        BUCKET_LADDER_MS[0],
        TARGET_BUCKETS,
    )

    one_millisecond_over = exact_end + timedelta(milliseconds=1)
    over_bucket_ms, over_bucket_count = plan_buckets(start, one_millisecond_over)
    assert over_bucket_ms == BUCKET_LADDER_MS[1]
    assert over_bucket_count <= TARGET_BUCKETS


def test_openapi_requires_the_discriminator_in_every_timeline_tier() -> None:
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    response_schema = schema["paths"]["/threads/{thread_id}/timeline"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]

    assert response_schema["discriminator"] == {
        "propertyName": "level",
        "mapping": {
            "bands": "#/components/schemas/BandsTimeline",
            "meetings": "#/components/schemas/MeetingsTimeline",
            "moments": "#/components/schemas/MomentsTimeline",
            "evidence": "#/components/schemas/EvidenceTimeline",
        },
    }
    for name in (
        "BandsTimeline",
        "MeetingsTimeline",
        "MomentsTimeline",
        "EvidenceTimeline",
    ):
        assert "level" in schema["components"]["schemas"][name]["required"]


def test_mention_anchor_owns_window_membership_at_every_level(
    client: TestClient, pool: ConnectionPool
) -> None:
    """A fine row follows its mention even when its evidence starts earlier."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "anchor-boundary")
        topic_id, moment_id = add_topic(
            conn, meeting_id, "Boundary", start_ms=59_000
        )
        conn.execute(
            "UPDATE topic_mention SET anchor_ms = 61000 WHERE topic_id = %s",
            (topic_id,),
        )
        thread_id = add_thread(
            conn, identity_key="anchor boundary", topic_ids=[topic_id]
        )

    windows = (
        (
            {
                "from": (STARTED_AT + timedelta(seconds=60)).isoformat(),
                "to": (STARTED_AT + timedelta(seconds=62)).isoformat(),
            },
            1,
        ),
        (
            {
                "from": (STARTED_AT + timedelta(seconds=58)).isoformat(),
                "to": (STARTED_AT + timedelta(seconds=60)).isoformat(),
            },
            0,
        ),
    )
    tier_key = {
        "bands": "bands",
        "meetings": "meetings",
        "moments": "moments",
        "evidence": "evidence",
    }

    for window, expected_count in windows:
        for level in LEVELS:
            response = client.get(
                f"/threads/{thread_id}/timeline",
                params={"level": level, **window},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["mentionCount"] == expected_count
            assert body["meetingCount"] == expected_count
            assert body["momentCount"] == expected_count
            rows = body[tier_key[level]]
            if level == "bands":
                assert sum(row["mentionCount"] for row in rows) == expected_count
            else:
                assert len(rows) == expected_count

    included = client.get(
        f"/threads/{thread_id}/timeline",
        params={"level": "moments", **windows[0][0]},
    ).json()
    assert included["moments"][0]["momentId"] == str(moment_id)
    assert included["moments"][0]["occurredAt"] == (
        STARTED_AT + timedelta(seconds=59)
    ).isoformat().replace("+00:00", "Z")
    assert included["moments"][0]["occurredAt"] < included["windowFrom"]


def test_openapi_says_fine_occurred_at_may_fall_outside_the_window() -> None:
    app = FastAPI()
    app.include_router(router)
    occurred_at = app.openapi()["components"]["schemas"]["TimelineMoment"][
        "properties"
    ]["occurredAt"]

    assert "may fall outside" in occurred_at["description"]
    assert "mention anchor" in occurred_at["description"]
