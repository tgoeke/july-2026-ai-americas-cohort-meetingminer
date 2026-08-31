"""Contract tests for `GET /moments/feed` (story 10.4; Postgres only).

One test per clause of the story's acceptance criteria, seeded through
`projection_seed.seed_meeting` so the rows are the exact shapes the migrations
declare. The field-set literals below are the wire contract story 10.5 is
building its cards against; they are pinned here so a rename is a test
failure rather than a silent break in another lane.

The route makes no model call — there is no fake completer anywhere in this
file, and that is the point: everything the ranking reads was written by the
worker before the request arrived.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

import meetingminer.api.moments as moments_api
import meetingminer.api.moments_feed as feed_api
from meetingminer.api.registry import discover_routers
from projection_seed import SeededMeeting, insert_artifact, seed_meeting

FEED_FIELDS = {"items", "total", "corpusTotal", "limit", "offset"}
ITEM_FIELDS = {
    "momentId", "meetingId", "meetingTitle", "startedAt", "startedAtPrecision",
    "startMs", "endMs", "corpus", "hasRecording", "sourceDeepLink",
    "screenshotId", "viewType", "preview", "threads", "reasons",
}
REASON_FIELDS = {"kind", "label", "ref", "at"}
THREAD_FIELDS = {"threadId", "name", "colorOrdinal"}

NOW = datetime.now(timezone.utc)


def _seed(pool: ConnectionPool, **kwargs) -> SeededMeeting:
    with pool.connection() as conn:
        return seed_meeting(conn, **kwargs)


def _signal(
    pool: ConnectionPool,
    seeded: SeededMeeting,
    *,
    moment_index: int = 0,
    kind: str = "risk",
    label: str = "The vendor key may not arrive before the cutover",
    detail: str = "",
    anchor_ms: int = 5_000,
    item_id: str = "R1",
) -> UUID:
    """One ranking-signal row, in the shape migration 0018 declares.

    Written raw here for the reason `projection_seed.insert_artifact` writes
    artifacts raw: the worker owns these columns in production, and a test
    that went through the stage would be testing the extraction pass rather
    than the feed.
    """
    with pool.connection() as conn:
        return conn.execute(
            "INSERT INTO ranking_signal"
            " (meeting_id, moment_id, kind, label, detail, anchor_ms, item_id,"
            "  provenance)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                seeded.meeting_id,
                seeded.moment_ids[moment_index],
                kind,
                label,
                detail,
                anchor_ms,
                item_id,
                Jsonb({"role": "extraction", "document_kind": "ranking-signals"}),
            ),
        ).fetchone()[0]


def _thread(
    pool: ConnectionPool,
    seeded: SeededMeeting,
    *,
    name: str = "data hub",
    moment_index: int = 0,
    color_ordinal: int | None = None,
) -> UUID:
    """A topic on one moment, unioned into one thread — the 10.1/10.2 chain."""
    with pool.connection() as conn:
        topic_id = conn.execute(
            "INSERT INTO topic (meeting_id, name, gist) VALUES (%s, %s, %s)"
            " RETURNING id",
            (seeded.meeting_id, name, f"Gist: {name}"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)"
            " VALUES (%s, %s, %s, %s)",
            (topic_id, seeded.moment_ids[moment_index], seeded.meeting_id, 2_000),
        )
        thread_id = conn.execute(
            "INSERT INTO thread (identity_key, name, link_rule, color_ordinal)"
            " VALUES (%s, %s, 'normalized-name-or-embedding-similarity', %s)"
            " RETURNING id",
            (f"{name}:{uuid4()}", name, color_ordinal),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO topic_thread (topic_id, thread_id, linked_by)"
            " VALUES (%s, %s, 'seed')",
            (topic_id, thread_id),
        )
        return thread_id


# --- registration ------------------------------------------------------------


def test_the_feed_registers_before_the_parameterized_moment_route() -> None:
    """`/moments/feed` under `/moments/{moment_id}` is registry.py's hazard.

    Registered after `moments`, FastAPI would match `feed` as a `moment_id`
    and reject it as a malformed UUID. The order is a matching contract, so
    it is asserted rather than assumed.
    """
    order = [name for name, _ in discover_routers()]

    assert order.index("moments_feed") < order.index("moments")
    assert feed_api.ROUTER_ORDER < moments_api.ROUTER_ORDER


def test_the_literal_route_is_not_swallowed(client) -> None:
    """The behaviour the ordering exists for, not just the ordering."""
    response = client.get("/moments/feed")

    assert response.status_code == 200, response.text
    assert set(response.json()) == FEED_FIELDS


def test_openapi_discloses_that_offset_pages_are_ranked_live(client) -> None:
    """F9: the cross-request relaxation is part of the served contract."""
    operation = client.app.openapi()["paths"]["/moments/feed"]["get"]
    description = operation["description"].lower()

    assert "ranked at request time" in description
    assert "not stable across requests" in description
    assert "repeat" in description
    assert "skipped" in description


# --- the page ----------------------------------------------------------------


def test_the_feed_returns_the_declared_envelope_and_card_fields(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="feed-shape", started_at=NOW)
    with test_pool.connection() as conn:
        insert_artifact(
            conn, seeded.moment_ids[0], seeded.meeting_id, kind="adr",
            state="extracted", title="Adopt SFTP for the vendor feed",
        )
    _signal(test_pool, seeded)
    _thread(test_pool, seeded)

    response = client.get("/moments/feed")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == FEED_FIELDS
    assert body["offset"] == 0
    assert body["limit"] == 20
    assert body["total"] >= 1
    item = body["items"][0]
    assert set(item) == ITEM_FIELDS
    assert item["momentId"] == str(seeded.moment_ids[0])
    assert item["meetingId"] == str(seeded.meeting_id)
    assert item["meetingTitle"] == "Data Hub Demo"
    assert item["corpus"] == "real"
    assert item["hasRecording"] is True
    assert item["startMs"] == 2_000
    assert item["preview"] == "Everybody, good morning."
    assert item["viewType"] in {"slide", "ui-screen", "participant-gallery"}
    for reason in item["reasons"]:
        assert set(reason) == REASON_FIELDS
    for thread in item["threads"]:
        assert set(thread) == THREAD_FIELDS


def test_the_card_carries_an_opaque_screenshot_id_and_never_a_path(
    client, test_pool
) -> None:
    """AD-17: the still is fetched by id through `GET /media/files/{mediaId}`.

    `GET /moments/{id}` still serves `screenshotPath` for story 2.2's
    renderer; the feed deliberately does not, so no served string can be
    joined onto a root.
    """
    seeded = _seed(test_pool, source_id="feed-media", started_at=NOW)
    _signal(test_pool, seeded)

    item = client.get("/moments/feed").json()["items"][0]

    assert item["screenshotId"] == str(seeded.screenshot_ids[0])
    assert "screenshotPath" not in item
    assert "path" not in item
    body = client.get("/moments/feed").text
    assert "meetings/" not in body


def test_every_item_carries_a_non_empty_ordered_reasons_list(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="feed-reasons", started_at=NOW)
    with test_pool.connection() as conn:
        insert_artifact(
            conn, seeded.moment_ids[0], seeded.meeting_id, kind="action-item",
            state="extracted", title="Set up the SFTP credentials",
            body="Owner: Ellis\nTiming (as stated): "
            + (NOW + timedelta(days=1)).date().isoformat(),
        )
    _signal(test_pool, seeded, kind="question", label="Who approves the PO?")

    body = client.get("/moments/feed").json()

    assert body["items"]
    for item in body["items"]:
        assert item["reasons"], item
        assert all(reason["label"].strip() for reason in item["reasons"])
        assert all(reason["kind"] in feed_api.REASON_KINDS for reason in item["reasons"])
    # The urgent commitment leads, and its reason is the `due` kind.
    top = body["items"][0]
    assert top["reasons"][0]["kind"] == "due"
    assert top["reasons"][0]["at"] is not None
    assert top["reasons"][0]["ref"] is not None


def test_a_published_artifact_produces_a_published_reason_with_its_timestamp(
    client, test_pool
) -> None:
    """The one path that parses a timestamp back out of the aggregate's JSON.

    `published_at` reaches the scorer as a string inside `jsonb_agg`, not as a
    psycopg `datetime`, so this asserts the round trip against a real Postgres
    rather than against a hand-built candidate — the pure tests cannot catch a
    rendering the parser does not accept.
    """
    stale = NOW - timedelta(days=200)
    seeded = _seed(test_pool, source_id="feed-published", started_at=stale)
    published_at = NOW - timedelta(days=2)
    with test_pool.connection() as conn:
        artifact_id = insert_artifact(
            conn, seeded.moment_ids[0], seeded.meeting_id, kind="adr",
            state="published", title="Adopt SFTP",
        )
        conn.execute(
            "UPDATE artifact SET published_at = %s WHERE id = %s",
            (published_at, artifact_id),
        )

    item = client.get("/moments/feed").json()["items"][0]

    [reason] = [r for r in item["reasons"] if r["kind"] == "published"]
    assert reason["label"] == "Adopt SFTP"
    assert reason["ref"] == str(artifact_id)
    assert reason["at"] is not None
    assert reason["at"].startswith(published_at.date().isoformat())


def test_a_decision_outranks_a_bare_recent_moment(client, test_pool) -> None:
    decided = _seed(test_pool, source_id="feed-rank-decided", started_at=NOW)
    with test_pool.connection() as conn:
        insert_artifact(
            conn, decided.moment_ids[1], decided.meeting_id, kind="adr",
            state="extracted", title="Adopt SFTP",
        )

    items = client.get("/moments/feed").json()["items"]

    assert items[0]["momentId"] == str(decided.moment_ids[1])
    assert items[0]["reasons"][0]["kind"] == "adr"


# --- validation before pagination -------------------------------------------


def test_an_item_with_no_valid_reason_is_dropped_from_items_and_total(
    client, test_pool, capsys
) -> None:
    """The clause that is easy to get backwards, asserted end to end.

    The reasonless moment belongs to a meeting old enough to earn no recency
    reason, and its only artifact has a blank title — so it produces no
    renderable reason at all. It must not appear in `items`, must not be
    counted in `total`, and must be named in the log rather than vanishing.
    """
    stale = NOW - timedelta(days=200)
    good = _seed(test_pool, source_id="feed-valid", started_at=stale)
    bad = _seed(test_pool, source_id="feed-invalid", started_at=stale)
    with test_pool.connection() as conn:
        insert_artifact(
            conn, good.moment_ids[0], good.meeting_id, kind="adr",
            state="extracted", title="A decision worth showing",
        )
        insert_artifact(
            conn, bad.moment_ids[0], bad.meeting_id, kind="adr",
            state="extracted", title="   ",
        )

    body = client.get("/moments/feed").json()

    served = {item["momentId"] for item in body["items"]}
    assert str(good.moment_ids[0]) in served
    assert str(bad.moment_ids[0]) not in served
    assert body["total"] == len(body["items"]) == 1
    assert "moments.feed.item_dropped" in capsys.readouterr().out


def test_total_and_offsets_count_only_serializable_rows(client, test_pool) -> None:
    """Paging is over survivors, so no page is ever short for an unseen reason.

    Four scorable moments and one reasonless one are seeded. Every page taken
    two at a time must sum to `total`, and `total` must be four — the count
    after validation, never the count the candidate scan produced.
    """
    stale = NOW - timedelta(days=200)
    seeded = [
        _seed(test_pool, source_id=f"feed-page-{index}", started_at=stale)
        for index in range(2)
    ]
    reasonless = _seed(test_pool, source_id="feed-page-bad", started_at=stale)
    with test_pool.connection() as conn:
        for index, meeting in enumerate(seeded):
            for moment_index in range(2):
                insert_artifact(
                    conn, meeting.moment_ids[moment_index], meeting.meeting_id,
                    kind="adr", state="extracted",
                    title=f"Decision {index}-{moment_index}",
                )
        insert_artifact(
            conn, reasonless.moment_ids[0], reasonless.meeting_id, kind="adr",
            state="extracted", title="",
        )

    first = client.get("/moments/feed?limit=2&offset=0").json()
    second = client.get("/moments/feed?limit=2&offset=2").json()
    past_the_end = client.get("/moments/feed?limit=2&offset=4").json()
    well_past_the_end = client.get("/moments/feed?limit=2&offset=99").json()

    assert first["total"] == second["total"] == past_the_end["total"] == 4
    assert len(first["items"]) == 2
    assert len(second["items"]) == 2
    assert past_the_end["items"] == []
    assert well_past_the_end["items"] == []
    assert first["offset"] == 0 and second["offset"] == 2
    assert well_past_the_end["offset"] == 4
    for response in (first, second, past_the_end, well_past_the_end):
        assert response["offset"] + len(response["items"]) <= response["total"]
    # This unchanged, score-tied fixture remains stable; the endpoint contract
    # deliberately makes no such promise once ranking moves between requests.
    ids = [item["momentId"] for item in first["items"] + second["items"]]
    assert len(set(ids)) == 4
    assert str(reasonless.moment_ids[0]) not in ids


def test_the_page_size_is_bounded_by_the_configured_maximum(client) -> None:
    body = client.get("/moments/feed?limit=100000").json()

    assert body["limit"] == 100


# --- filters ------------------------------------------------------------------


def test_the_corpus_filter_selects_only_that_corpus(client, test_pool) -> None:
    real = _seed(test_pool, source_id="feed-corpus-real", started_at=NOW)
    scripted = _seed(
        test_pool, source_id="feed-corpus-scripted", corpus="scripted",
        started_at=NOW,
    )
    _signal(test_pool, real)
    _signal(test_pool, scripted)

    body = client.get("/moments/feed?corpus=scripted").json()

    assert body["items"]
    assert {item["corpus"] for item in body["items"]} == {"scripted"}
    assert body["total"] == len(body["items"])


def test_corpus_total_ignores_item_filters_but_respects_corpus_scope(
    client, test_pool
) -> None:
    """Story 10.5 gets its denominator without another HTTP request."""
    stale = NOW - timedelta(days=200)
    risky = _seed(test_pool, source_id="feed-total-risk", started_at=stale)
    decided = _seed(test_pool, source_id="feed-total-adr", started_at=stale)
    scripted = _seed(
        test_pool,
        source_id="feed-total-scripted",
        corpus="scripted",
        started_at=stale,
    )
    _signal(test_pool, risky, kind="risk", label="A selected risk")
    _signal(test_pool, scripted, kind="risk", label="A scripted risk")
    with test_pool.connection() as conn:
        insert_artifact(
            conn,
            decided.moment_ids[0],
            decided.meeting_id,
            kind="adr",
            state="extracted",
            title="A second real-corpus candidate",
        )

    body = client.get(
        "/moments/feed",
        params={"corpus": "real", "meeting": risky.meeting_id, "kind": "risk"},
    ).json()

    assert body["total"] == len(body["items"]) == 1
    assert body["corpusTotal"] == 2


def test_the_meeting_filter_selects_only_that_meeting(client, test_pool) -> None:
    wanted = _seed(test_pool, source_id="feed-meeting-a", started_at=NOW)
    _seed(test_pool, source_id="feed-meeting-b", started_at=NOW)
    _signal(test_pool, wanted)

    body = client.get(f"/moments/feed?meeting={wanted.meeting_id}").json()

    assert body["items"]
    assert {item["meetingId"] for item in body["items"]} == {str(wanted.meeting_id)}


def test_the_thread_filter_selects_only_members_of_that_thread(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="feed-thread", started_at=NOW)
    other = _seed(test_pool, source_id="feed-thread-other", started_at=NOW)
    ordinal = 2**40 + 17
    thread_id = _thread(
        test_pool, seeded, name="data hub", color_ordinal=ordinal
    )
    _signal(test_pool, other)

    body = client.get(f"/moments/feed?thread={thread_id}").json()

    assert body["items"]
    assert {item["momentId"] for item in body["items"]} == {
        str(seeded.moment_ids[0])
    }
    chips = body["items"][0]["threads"]
    assert [chip["threadId"] for chip in chips] == [str(thread_id)]
    assert chips[0]["name"] == "data hub"
    # Migration 0017's bigint survives Postgres -> JSON text -> Python int ->
    # the camelCase wire without narrowing to 32 bits.
    assert chips[0]["colorOrdinal"] == ordinal


def test_thread_chips_are_bounded_by_the_ranking_config(client, test_pool) -> None:
    """F3: the card and its reasons use the same configured membership cap."""
    seeded = _seed(test_pool, source_id="feed-thread-cap", started_at=NOW)
    for index in range(5):
        _thread(test_pool, seeded, name=f"thread-{index}")

    item = client.get("/moments/feed").json()["items"][0]
    thread_reasons = [
        reason for reason in item["reasons"] if reason["kind"] == "thread"
    ]

    assert len(item["threads"]) == 3
    assert len(thread_reasons) == 3
    assert [thread["threadId"] for thread in item["threads"]] == [
        reason["ref"] for reason in thread_reasons
    ]


def test_the_kind_filter_keeps_only_items_carrying_that_reason(
    client, test_pool
) -> None:
    stale = NOW - timedelta(days=200)
    risky = _seed(test_pool, source_id="feed-kind-risk", started_at=stale)
    decided = _seed(test_pool, source_id="feed-kind-adr", started_at=stale)
    _signal(test_pool, risky, kind="risk", label="A stated risk")
    with test_pool.connection() as conn:
        insert_artifact(
            conn, decided.moment_ids[0], decided.meeting_id, kind="adr",
            state="extracted", title="A decision",
        )

    body = client.get("/moments/feed?kind=risk").json()

    assert body["total"] == len(body["items"]) == 1
    assert body["items"][0]["momentId"] == str(risky.moment_ids[0])
    assert any(reason["kind"] == "risk" for reason in body["items"][0]["reasons"])


def test_an_unknown_kind_filter_serves_an_empty_page_not_an_error(
    client, test_pool
) -> None:
    """A filter nothing matches is an empty feed, never a 500."""
    seeded = _seed(test_pool, source_id="feed-kind-none", started_at=NOW)
    _signal(test_pool, seeded)

    body = client.get("/moments/feed?kind=astrology").json()

    assert body["items"] == []
    assert body["total"] == 0


def test_action_item_filter_keeps_a_timed_action(client, test_pool) -> None:
    """F4: timing adds a due reason; it must not erase the artifact kind."""
    stale = NOW - timedelta(days=200)
    seeded = _seed(test_pool, source_id="feed-kind-action", started_at=stale)
    with test_pool.connection() as conn:
        insert_artifact(
            conn,
            seeded.moment_ids[0],
            seeded.meeting_id,
            kind="action-item",
            state="extracted",
            title="Set up credentials",
            body="Timing (as stated): 2026-09-01",
        )

    body = client.get("/moments/feed?kind=action-item").json()

    assert body["total"] == len(body["items"]) == 1
    assert body["items"][0]["momentId"] == str(seeded.moment_ids[0])
    assert {reason["kind"] for reason in body["items"][0]["reasons"]} >= {
        "action-item",
        "due",
    }


# --- what never reaches the feed ---------------------------------------------


def test_a_superseded_moment_is_never_served(client, test_pool) -> None:
    """The id still resolves as a citation; a ghost is not a front-door card."""
    seeded = _seed(test_pool, source_id="feed-superseded", started_at=NOW)
    _signal(test_pool, seeded)
    with test_pool.connection() as conn:
        conn.execute(
            "UPDATE moment SET provenance = provenance ||"
            " '{\"superseded\": true}'::jsonb WHERE id = %s",
            (seeded.moment_ids[0],),
        )

    served = {
        item["momentId"] for item in client.get("/moments/feed").json()["items"]
    }

    assert str(seeded.moment_ids[0]) not in served


def test_an_old_moment_with_nothing_stored_about_it_is_not_a_candidate(
    client, test_pool
) -> None:
    """The feed is what needs attention, not everything that ever happened."""
    _seed(test_pool, source_id="feed-quiet", started_at=NOW - timedelta(days=200))

    body = client.get("/moments/feed").json()

    assert body["items"] == []
    assert body["total"] == 0


def test_a_ranking_signal_never_enters_the_artifact_lifecycle(
    client, test_pool
) -> None:
    """The record has no `state` to move, and the rail never shows one."""
    seeded = _seed(test_pool, source_id="feed-lifecycle", started_at=NOW)
    _signal(test_pool, seeded)

    with test_pool.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'ranking_signal' AND column_name = 'state'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM artifact WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()[0] == 0

    detail = client.get(f"/moments/{seeded.moment_ids[0]}").json()
    assert detail["artifacts"] == []


def test_the_feed_makes_no_model_call(client, test_pool, monkeypatch) -> None:
    """A request-time model call is the failure this test exists to catch."""
    seeded = _seed(test_pool, source_id="feed-no-llm", started_at=NOW)
    _signal(test_pool, seeded)

    import meetingminer.adapters.llm as llm_module

    def refuse(*args, **kwargs):
        raise AssertionError("the feed must not build an Llm at request time")

    monkeypatch.setattr(llm_module, "build_llm", refuse)

    assert client.get("/moments/feed").status_code == 200
