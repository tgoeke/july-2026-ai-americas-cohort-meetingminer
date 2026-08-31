"""The four levels of `GET /threads/{threadId}/timeline` (story 10.3).

Four things are proven here, and they are the four the story hangs on.

1. **Each level returns exactly its tier.** Asserted by comparing the whole
   top-level key set of each response, so a leaked tier fails rather than
   passing a spot check, and by comparing each item's whole key set at the
   moments tier — the one the acceptance criteria enumerate field by field.
2. **Never a storage path.** A screenshot is seeded with a distinctive stored
   path and the string is searched for in every level's raw body; the module's
   own SQL is separately asserted to select no path column.
3. **`occurredAt` is the server's derivation**, including the day-precision
   anchoring at `00:00:00Z` and the `meetingId`-then-`momentId` tie-break, and
   the SQL derivation is pinned against the pure Python one.
4. **The coarse levels are bounded aggregates that never scan `moment`.**
   Proven twice: statically, that no coarse statement names `moment` as a
   relation, and live, that `EXPLAIN` of each coarse statement contains no
   scan of `moment` while the fine level's does.

DB-backed against the per-run test database (a named skip when the compose
Postgres is down). Seeding helpers are imported from `test_api_threads.py`
rather than added to `conftest.py`: they are this story's fixtures, and the
wave rules keep new fixtures out of the shared module.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg_pool import ConnectionPool

from meetingminer.api import threads as threads_api
from meetingminer.domain.thread_timeline import (
    BUCKET_LADDER_MS,
    COARSE_LEVELS,
    LEVELS,
    TARGET_BUCKETS,
    bucket_index,
    format_rfc3339,
    occurred_at,
    plan_buckets,
    timeline_sort_key,
)

from conftest import truncate_evidence
from test_api_threads import (
    STARTED_AT,
    add_moment,
    add_thread,
    add_topic,
    seed_meeting,
)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


# --- the pure derivation ---------------------------------------------------


def test_occurred_at_is_the_meeting_start_plus_the_offset() -> None:
    assert occurred_at(STARTED_AT, "second", 30_000) == datetime(
        2026, 8, 5, 12, 0, 49, tzinfo=timezone.utc
    )


def test_a_day_precision_meeting_anchors_at_midnight_utc() -> None:
    """The stored time of day is discarded, not carried into the derivation.

    A drop that declared only a date still stores a full timestamp; whatever
    time of day happens to be in it was never observed, so anchoring on it
    would invent a wall clock the source never claimed.
    """
    assert occurred_at(STARTED_AT, "day", 30_000) == datetime(
        2026, 8, 5, 0, 0, 30, tzinfo=timezone.utc
    )


def test_rfc3339_is_utc_with_a_literal_z() -> None:
    assert format_rfc3339(STARTED_AT) == "2026-08-05T12:00:19Z"
    assert (
        format_rfc3339(STARTED_AT.astimezone(timezone(timedelta(hours=5))))
        == "2026-08-05T12:00:19Z"
    )
    assert format_rfc3339(occurred_at(STARTED_AT, "second", 1_500)) == (
        "2026-08-05T12:00:20.500Z"
    )


def test_ties_break_by_meeting_then_moment() -> None:
    instant = datetime(2026, 8, 5, tzinfo=timezone.utc)
    low_meeting = UUID(int=1)
    high_meeting = UUID(int=2)
    low_moment = UUID(int=10)
    high_moment = UUID(int=20)
    keys = [
        timeline_sort_key(instant, high_meeting, low_moment),
        timeline_sort_key(instant, low_meeting, high_moment),
        timeline_sort_key(instant, low_meeting, low_moment),
    ]
    assert sorted(keys) == [
        timeline_sort_key(instant, low_meeting, low_moment),
        timeline_sort_key(instant, low_meeting, high_moment),
        timeline_sort_key(instant, high_meeting, low_moment),
    ]


@pytest.mark.parametrize(
    "days",
    [1, 7, 30, 365, 3650, 36500],
)
def test_the_band_never_returns_more_buckets_than_the_target(days: int) -> None:
    """The bound is the point: a band's size comes from the ladder, not from
    how wide a window the caller named."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bucket_ms, bucket_count = plan_buckets(start, start + timedelta(days=days))
    assert bucket_count <= TARGET_BUCKETS
    assert bucket_ms > 0


def test_a_narrow_window_uses_a_ladder_step() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bucket_ms, _ = plan_buckets(start, start + timedelta(hours=1))
    assert bucket_ms in BUCKET_LADDER_MS


def test_a_zero_length_window_is_one_bucket() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _, bucket_count = plan_buckets(start, start)
    assert bucket_count == 1


def test_an_inverted_window_is_refused_by_the_planner() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        plan_buckets(start, start - timedelta(days=1))


def test_an_item_on_the_windows_end_lands_in_the_last_bucket() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    bucket_ms, bucket_count = plan_buckets(start, end)
    assert bucket_index(end, start, bucket_ms, bucket_count) == bucket_count - 1
    assert bucket_index(start, start, bucket_ms, bucket_count) == 0


# --- query shape: the coarse levels never scan `moment` --------------------

# `FROM moment` / `JOIN moment` and nothing else. Written as a word-bounded
# pattern on purpose: `topic_mention` and `moment_segment` both contain the
# substring "moment", and a naive `"moment" in sql` check would call every
# coarse statement a violation and prove nothing.
_MOMENT_RELATION = re.compile(r"\b(?:FROM|JOIN)\s+moment\b", re.IGNORECASE)

# How `moment` appears in an `EXPLAIN` plan, whichever access method the
# planner chose: "Seq Scan on moment mo", "Index Scan using moment_pkey on
# moment mo", "Bitmap Heap Scan on moment mo". The word boundary keeps
# `moment_segment` and `topic_mention` out.
_MOMENT_SCAN = re.compile(r"\bon\s+moment\b", re.IGNORECASE)

_COARSE_STATEMENTS = {
    "bands": threads_api._BANDS,
    "meetings": threads_api._MEETINGS_LEVEL,
    "meeting-topics": threads_api._MEETING_TOPICS,
    "window-totals": threads_api._WINDOW_TOTALS,
    "thread-list": threads_api._THREAD_LIST,
    "thread-span": threads_api._THREAD_SPAN,
}


def test_the_coarse_statements_name_no_moment_relation() -> None:
    for name, statement in _COARSE_STATEMENTS.items():
        assert not _MOMENT_RELATION.search(statement), (
            f"the {name} statement joins `moment`; the coarse levels must"
            " aggregate over topic_mention, which already carries meeting_id"
            " and anchor_ms"
        )


def test_the_pattern_would_catch_a_moment_join() -> None:
    """The guard above is only worth having if it can fail."""
    assert _MOMENT_RELATION.search("SELECT 1 FROM moment mo")
    assert _MOMENT_RELATION.search("SELECT 1 FROM x JOIN moment mo ON true")
    assert not _MOMENT_RELATION.search("SELECT 1 FROM topic_mention tm")
    assert not _MOMENT_RELATION.search("SELECT 1 FROM moment_segment ms")


def test_no_statement_selects_a_stored_path() -> None:
    """AD-17: media is ID-addressed, so no query here may read a path column."""
    statements = {
        **_COARSE_STATEMENTS,
        "moments": threads_api._MOMENTS_LEVEL,
        "titles": threads_api._MOMENT_TITLES,
        "speakers": threads_api._MOMENT_SPEAKERS,
        "excerpts": threads_api._MOMENT_EXCERPTS,
        "artifacts": threads_api._MOMENT_ARTIFACTS,
    }
    for name, statement in statements.items():
        assert not re.search(r"\.path\b|drop_relative_path", statement), (
            f"the {name} statement reads a stored path; media travels as"
            " opaque ids (AD-17)"
        )


def test_explain_shows_the_coarse_levels_never_scan_moment(
    pool: ConnectionPool,
) -> None:
    """The live half of the claim: the planner's own answer, not a guess.

    A static check on the SQL text cannot see through a view or a rewritten
    subquery, so the plan is read too — and the fine level is explained in the
    same test as the control, because a "no scan of moment" assertion that
    would also pass for a statement that does scan it proves nothing.
    """
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "m1")
        topic_id, _ = add_topic(conn, meeting_id, "Subject")
        thread_id = add_thread(conn, identity_key="subject", topic_ids=[topic_id])
        params = {
            "thread_id": thread_id,
            "window_from": STARTED_AT - timedelta(days=1),
            "window_to": STARTED_AT + timedelta(days=1),
            "bucket_ms": 86_400_000,
            "last_bucket": 1,
            "limit": 10,
        }
        for level in COARSE_LEVELS:
            statement = (
                threads_api._BANDS if level == "bands" else threads_api._MEETINGS_LEVEL
            )
            plan = _explain(conn, statement, params)
            assert not _MOMENT_SCAN.search(plan), (
                f"the {level} plan scans `moment`:\n{plan}"
            )
            # Bounded by the thread, not by the corpus: the thread id reaches
            # the plan as a predicate rather than being filtered afterwards.
            assert "topic_thread" in plan

        fine_plan = _explain(conn, threads_api._MOMENTS_LEVEL, params)
        assert _MOMENT_SCAN.search(fine_plan), (
            "the control failed: the moments level must read `moment`, so an"
            " assertion that no plan scans it would be vacuous"
        )


def _explain(conn: Connection, statement: str, params: dict) -> str:
    rows = conn.execute(f"EXPLAIN {statement}", params).fetchall()
    return "\n".join(row[0] for row in rows)


# --- the four levels over one seeded thread --------------------------------


@pytest.fixture()
def thread_fixture(pool: ConnectionPool) -> dict:
    """One thread over two meetings two days apart, with evidence on one moment.

    Deliberately small and explicit: every count asserted below is countable
    by hand from this seed.
    """
    with pool.connection() as conn:
        first = seed_meeting(conn, "first-meeting", has_recording=True)
        second = seed_meeting(conn, "second-meeting", offset_days=2)
        topic_a, moment_a = add_topic(conn, first, "SFTP Migration", start_ms=30_000)
        topic_b, moment_b = add_topic(conn, second, "SFTP Migration", start_ms=90_000)
        thread_id = add_thread(
            conn, identity_key="sftp migration", topic_ids=[topic_a, topic_b]
        )
        screenshot_id = _add_screenshot(conn, first, "meetings/first/shot-0001.jpg")
        conn.execute(
            "UPDATE moment SET screenshot_id = %s WHERE id = %s",
            (screenshot_id, moment_a),
        )
        _add_segment(conn, first, moment_a, "Ellis Whitmore", "resolved", 1)
        _add_segment(conn, first, moment_a, "Speaker 2", "placeholder", 2)
        artifact_id = conn.execute(
            "INSERT INTO artifact (moment_id, meeting_id, kind, state, title, body)"
            " VALUES (%s, %s, 'adr', 'extracted', %s, %s) RETURNING id",
            (moment_a, first, "Move the SFTP host", "We move it in September."),
        ).fetchone()[0]
    return {
        "thread_id": thread_id,
        "first_meeting": first,
        "second_meeting": second,
        "moment_a": moment_a,
        "moment_b": moment_b,
        "screenshot_id": screenshot_id,
        "artifact_id": artifact_id,
        "screenshot_path": "meetings/first/shot-0001.jpg",
    }


def _add_screenshot(conn: Connection, meeting_id: UUID, path: str) -> UUID:
    screen_id = conn.execute(
        "INSERT INTO screen (identity_key, signature, view_type)"
        " VALUES (%s, %s, 'slide')"
        " ON CONFLICT (identity_key) DO UPDATE SET signature = EXCLUDED.signature"
        " RETURNING id",
        (f"screen:{meeting_id}", f"signature for {meeting_id}"),
    ).fetchone()[0]
    return conn.execute(
        "INSERT INTO screenshot (meeting_id, screen_id, ordinal,"
        " start_offset_ms, end_offset_ms, frame_count, path, view_type)"
        " VALUES (%s, %s, 1, 0, 60000, 3, %s, 'slide') RETURNING id",
        (meeting_id, screen_id, path),
    ).fetchone()[0]


def _add_segment(
    conn: Connection,
    meeting_id: UUID,
    moment_id: UUID,
    label: str,
    resolution: str,
    ordinal: int,
) -> None:
    source_id = conn.execute(
        "SELECT id FROM transcript_source WHERE meeting_id = %s LIMIT 1",
        (meeting_id,),
    ).fetchone()
    if source_id is None:
        source_id = conn.execute(
            "INSERT INTO transcript_source (meeting_id, kind, format,"
            " drop_relative_path, sha256, byte_size, segment_count)"
            " VALUES (%s, 'provided-text', 'teams', %s, %s, 1024, 2) RETURNING id",
            (meeting_id, f"{meeting_id}/transcript.txt", f"sha-{meeting_id}"),
        ).fetchone()
    segment_id = conn.execute(
        "INSERT INTO transcript_segment (meeting_id, label_source_id,"
        " timing_source_id, ordinal, start_ms, end_ms, speaker_label,"
        " speaker_resolution, text)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            meeting_id,
            source_id[0],
            source_id[0],
            ordinal,
            30_000 + ordinal * 1_000,
            31_000 + ordinal * 1_000,
            label,
            resolution,
            f"{label} says something at ordinal {ordinal}.",
        ),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO moment_segment (moment_id, transcript_segment_id)"
        " VALUES (%s, %s)",
        (moment_id, segment_id),
    )


def _timeline(client: TestClient, thread_id: UUID, level: str, **params) -> dict:
    response = client.get(
        f"/threads/{thread_id}/timeline", params={"level": level, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


_ENVELOPE_KEYS = {
    "threadId",
    "name",
    "colorOrdinal",
    "level",
    "windowFrom",
    "windowTo",
    "mentionCount",
    "meetingCount",
    "momentCount",
}


def test_every_level_returns_exactly_its_own_tier(
    client: TestClient, thread_fixture: dict
) -> None:
    """The keys, not a sample of them: a leaked tier has to fail here."""
    thread_id = thread_fixture["thread_id"]
    expected = {
        "bands": _ENVELOPE_KEYS | {"bucketMs", "bucketCount", "bands"},
        "meetings": _ENVELOPE_KEYS | {"meetings"},
        "moments": _ENVELOPE_KEYS | {"truncated", "moments"},
        "evidence": _ENVELOPE_KEYS | {"truncated", "evidence"},
    }
    for level in LEVELS:
        body = _timeline(client, thread_id, level)
        assert set(body) == expected[level], f"level {level} returned the wrong tier"


def test_the_moments_tier_carries_exactly_the_acceptance_criteria_fields(
    client: TestClient, thread_fixture: dict
) -> None:
    body = _timeline(client, thread_fixture["thread_id"], "moments")
    assert [m["momentId"] for m in body["moments"]] == [
        str(thread_fixture["moment_a"]),
        str(thread_fixture["moment_b"]),
    ]
    assert set(body["moments"][0]) == {
        "momentId",
        "meetingId",
        "title",
        "startMs",
        "occurredAt",
        "occurredAtPrecision",
        "speakers",
        "screenshotId",
    }
    first = body["moments"][0]
    assert first["title"] == "SFTP Migration"
    assert first["startMs"] == 30_000
    assert first["occurredAt"] == "2026-08-05T12:00:49Z"
    assert first["occurredAtPrecision"] == "second"
    assert first["screenshotId"] == str(thread_fixture["screenshot_id"])


def test_only_resolved_speakers_are_named(
    client: TestClient, thread_fixture: dict
) -> None:
    """`placeholder`, `unresolved` and `ambiguous` are not people's names."""
    body = _timeline(client, thread_fixture["thread_id"], "moments")
    assert body["moments"][0]["speakers"] == ["Ellis Whitmore"]
    assert body["moments"][1]["speakers"] == []


def test_the_evidence_tier_adds_what_backs_the_moment(
    client: TestClient, thread_fixture: dict
) -> None:
    body = _timeline(client, thread_fixture["thread_id"], "evidence")
    first = body["evidence"][0]
    assert set(first) == {
        "momentId",
        "meetingId",
        "title",
        "startMs",
        "occurredAt",
        "occurredAtPrecision",
        "speakers",
        "screenshotId",
        "excerpt",
        "artifacts",
        "hasRecording",
        "recordingMediaId",
    }
    assert first["excerpt"].startswith("Ellis Whitmore says something")
    assert first["artifacts"] == [
        {
            "artifactId": str(thread_fixture["artifact_id"]),
            "kind": "adr",
            "state": "extracted",
            "title": "Move the SFTP host",
        }
    ]
    assert first["hasRecording"] is True
    assert first["recordingMediaId"] == str(thread_fixture["first_meeting"])
    # The second meeting has no recording, so it offers no replay id.
    second = body["evidence"][1]
    assert second["hasRecording"] is False
    assert second["recordingMediaId"] is None


def test_no_level_ever_serves_a_storage_path(
    client: TestClient, thread_fixture: dict
) -> None:
    """AD-17 end to end: the stored path exists, and never crosses the wire."""
    for level in LEVELS:
        response = client.get(
            f"/threads/{thread_fixture['thread_id']}/timeline",
            params={"level": level},
        )
        assert thread_fixture["screenshot_path"] not in response.text
        assert "shot-0001" not in response.text


def test_the_bands_tier_is_a_density_strip_over_the_window(
    client: TestClient, thread_fixture: dict
) -> None:
    body = _timeline(client, thread_fixture["thread_id"], "bands")
    assert body["mentionCount"] == 2
    assert body["meetingCount"] == 2
    assert sum(band["mentionCount"] for band in body["bands"]) == 2
    assert body["bucketCount"] == len(body["bands"])
    assert body["bands"][0]["startAt"] == body["windowFrom"]
    # Every bucket is contiguous with the next: a band with a gap would render
    # as a hole the corpus does not have.
    for earlier, later in zip(body["bands"], body["bands"][1:]):
        assert earlier["endAt"] == later["startAt"]


def test_the_meetings_tier_carries_counts_and_topic_membership(
    client: TestClient, thread_fixture: dict
) -> None:
    body = _timeline(client, thread_fixture["thread_id"], "meetings")
    assert [m["meetingId"] for m in body["meetings"]] == [
        str(thread_fixture["first_meeting"]),
        str(thread_fixture["second_meeting"]),
    ]
    first = body["meetings"][0]
    assert first["mentionCount"] == 1
    assert first["momentCount"] == 1
    assert first["occurredAt"] == "2026-08-05T12:00:49Z"
    assert first["topics"] == [
        {
            "topicId": first["topics"][0]["topicId"],
            "name": "SFTP Migration",
            "linkedBy": "seed",
        }
    ]


def test_the_window_bounds_every_level_alike(
    client: TestClient, thread_fixture: dict
) -> None:
    """A window holding only the first meeting shows only it, at every level."""
    window = {
        "from": "2026-08-05T00:00:00Z",
        "to": "2026-08-06T00:00:00Z",
    }
    thread_id = thread_fixture["thread_id"]
    bands = _timeline(client, thread_id, "bands", **window)
    assert bands["mentionCount"] == 1
    assert bands["meetingCount"] == 1
    meetings = _timeline(client, thread_id, "meetings", **window)
    assert [m["meetingId"] for m in meetings["meetings"]] == [
        str(thread_fixture["first_meeting"])
    ]
    moments = _timeline(client, thread_id, "moments", **window)
    assert [m["momentId"] for m in moments["moments"]] == [
        str(thread_fixture["moment_a"])
    ]
    evidence = _timeline(client, thread_id, "evidence", **window)
    assert len(evidence["evidence"]) == 1


def test_a_window_before_every_mention_returns_an_empty_tier(
    client: TestClient, thread_fixture: dict
) -> None:
    body = _timeline(
        client,
        thread_fixture["thread_id"],
        "moments",
        **{"from": "2020-01-01T00:00:00Z", "to": "2020-01-02T00:00:00Z"},
    )
    assert body["moments"] == []
    assert body["mentionCount"] == 0
    assert body["windowFrom"] == "2020-01-01T00:00:00Z"


def test_the_sql_derivation_matches_the_python_one(
    client: TestClient, pool: ConnectionPool
) -> None:
    """The aggregate's wall clock and the pure function must not diverge.

    The api derives `occurredAt` in SQL for the coarse levels and reads it
    from the fine-level query for the others; both must equal what
    `domain.thread_timeline.occurred_at` says, or two zoom levels would place
    the same evidence at two instants.
    """
    day_start = datetime(2026, 8, 9, 17, 45, 3, tzinfo=timezone.utc)
    with pool.connection() as conn:
        meeting_id = seed_meeting(
            conn, "day-precision", precision="day", started_at=day_start
        )
        topic_id, _moment_id = add_topic(conn, meeting_id, "Daylong", start_ms=45_000)
        thread_id = add_thread(conn, identity_key="daylong", topic_ids=[topic_id])

    expected = format_rfc3339(occurred_at(day_start, "day", 45_000))
    assert expected == "2026-08-09T00:00:45Z"

    moments = _timeline(client, thread_id, "moments")
    assert moments["moments"][0]["occurredAt"] == expected
    assert moments["moments"][0]["occurredAtPrecision"] == "day"
    meetings = _timeline(client, thread_id, "meetings")
    assert meetings["meetings"][0]["occurredAt"] == expected
    assert meetings["meetings"][0]["occurredAtPrecision"] == "day"
    threads = client.get("/threads").json()["threads"]
    assert threads[0]["firstMentionAt"] == expected


def test_equal_anchors_order_by_meeting_then_moment(
    client: TestClient, pool: ConnectionPool
) -> None:
    """Two meetings starting at the same instant, one moment each at the same
    offset: the order is the declared tie-break, not insertion order."""
    with pool.connection() as conn:
        left = seed_meeting(conn, "left")
        right = seed_meeting(conn, "right")
        topic_left, moment_left = add_topic(conn, left, "Shared", start_ms=0)
        topic_right, moment_right = add_topic(conn, right, "Shared", start_ms=0)
        thread_id = add_thread(
            conn, identity_key="shared", topic_ids=[topic_left, topic_right]
        )

    body = _timeline(client, thread_id, "moments")
    served = [m["momentId"] for m in body["moments"]]
    instant = occurred_at(STARTED_AT, "second", 0)
    expected = [
        str(moment_id)
        for _, _, moment_id in sorted(
            [
                timeline_sort_key(instant, left, moment_left),
                timeline_sort_key(instant, right, moment_right),
            ]
        )
    ]
    assert served == expected


def test_a_superseded_moment_is_not_interleaved_with_live_ones(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "m1")
        topic_id, live_moment = add_topic(conn, meeting_id, "Subject")
        ghost = add_moment(conn, meeting_id, start_ms=5_000)
        conn.execute(
            "UPDATE moment SET provenance = '{\"superseded\": \"true\"}'::jsonb"
            " WHERE id = %s",
            (ghost,),
        )
        conn.execute(
            "INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)"
            " VALUES (%s, %s, %s, 5000)",
            (topic_id, ghost, meeting_id),
        )
        thread_id = add_thread(conn, identity_key="subject", topic_ids=[topic_id])

    body = _timeline(client, thread_id, "moments")
    assert [m["momentId"] for m in body["moments"]] == [str(live_moment)]


# --- refusals --------------------------------------------------------------


def test_an_unknown_thread_is_a_named_404(client: TestClient, pool: ConnectionPool) -> None:
    response = client.get(f"/threads/{UUID(int=7)}/timeline")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_an_unknown_level_is_refused_before_any_query(
    client: TestClient, thread_fixture: dict
) -> None:
    response = client.get(
        f"/threads/{thread_fixture['thread_id']}/timeline",
        params={"level": "galaxy"},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_a_malformed_thread_id_is_refused(client: TestClient) -> None:
    response = client.get("/threads/not-a-uuid/timeline")
    assert response.status_code == 422


def test_an_inverted_window_is_a_named_400(
    client: TestClient, thread_fixture: dict
) -> None:
    response = client.get(
        f"/threads/{thread_fixture['thread_id']}/timeline",
        params={"from": "2026-08-10T00:00:00Z", "to": "2026-08-01T00:00:00Z"},
    )
    assert response.status_code == 400
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-window"


def test_a_thread_with_no_mentions_serves_an_empty_timeline(
    client: TestClient, pool: ConnectionPool
) -> None:
    """0015 keeps such rows as reuse targets; they exist, so this is not a 404."""
    with pool.connection() as conn:
        thread_id = add_thread(conn, identity_key="emptied")

    body = _timeline(client, thread_id, "bands")
    assert body["windowFrom"] is None
    assert body["bands"] == []
    assert body["bucketCount"] == 0
