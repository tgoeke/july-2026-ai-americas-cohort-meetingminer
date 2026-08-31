"""GET /threads/suggestions and GET /threads/trace (story 10.7).

Threads stopped being a catalogue and became a query. What is asserted here is
the part of that which is invisible once it is wrong: a suggestion list ranked
by the wrong key still looks like a suggestion list, a capped trace still looks
like a whole one, and a sample still looks exhaustive.

Seeding helpers are imported from `test_api_threads.py` rather than added to
`conftest.py`, the rule `test_thread_timeline_levels.py` follows: they are this
epic's fixtures and the wave rules keep new fixtures out of the shared module.

Postgres-only and therefore fast. The sample leg is exercised with
`search_moments` and `meili_client` replaced at the module boundary: what is
under test is how this route assembles and *describes* a ranked list, not
whether Meilisearch ranks — that is `test_api_search.py`'s subject and it pays
the twin's cost for it.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg_pool import ConnectionPool

from meetingminer.adapters.embed import EmbedderError, EmbedderUnavailableError
from meetingminer.api import threads as threads_api
from meetingminer.projections.query import MomentHit, MomentSearchResult
from meetingminer.projections.stores import StoreUnavailableError

from conftest import truncate_evidence
from test_api_threads import (
    add_moment,
    add_thread,
    add_topic,
    seed_meeting,
)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


def add_mention(
    conn: Connection, topic_id: UUID, meeting_id: UUID, start_ms: int
) -> UUID:
    """One more moment of an existing topic, in the same meeting."""
    moment_id = add_moment(conn, meeting_id, start_ms)
    conn.execute(
        "INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)"
        " VALUES (%s, %s, %s, %s)",
        (topic_id, moment_id, meeting_id, start_ms),
    )
    return moment_id


def supersede(conn: Connection, moment_id: UUID) -> None:
    conn.execute(
        "UPDATE moment SET provenance = '{\"superseded\": \"true\"}'::jsonb"
        " WHERE id = %s",
        (moment_id,),
    )


def spread_thread(
    conn: Connection,
    *,
    name: str,
    meetings: int,
    day_step: int = 1,
    mentions_each: int = 1,
    first_day: int = 0,
    has_recording: bool = False,
) -> UUID:
    """One subject mentioned in `meetings` meetings, `day_step` days apart."""
    topic_ids = []
    for index in range(meetings):
        meeting_id = seed_meeting(
            conn,
            f"{name}-{index}-{uuid4().hex[:8]}",
            offset_days=first_day + index * day_step,
            has_recording=has_recording,
        )
        topic_id, _ = add_topic(conn, meeting_id, name, start_ms=1_000)
        for extra in range(1, mentions_each):
            add_mention(conn, topic_id, meeting_id, 1_000 + extra * 10_000)
        topic_ids.append(topic_id)
    return add_thread(conn, identity_key=name, topic_ids=topic_ids)


# --- GET /threads/suggestions ---------------------------------------------


def test_suggestions_rank_by_span_not_by_mention_count(
    client: TestClient, pool: ConnectionPool
) -> None:
    """The whole point of the band, and the thing that is wrong by default.

    `sprawling` is mentioned far less often than `chatty` but runs across four
    months rather than a fortnight, so it is the one with a history to fly
    along. A ranking on frequency would put `chatty` first and the reader
    would be offered the subject with no shape.
    """
    with pool.connection() as conn:
        spread_thread(conn, name="sprawling", meetings=4, day_step=40)
        spread_thread(conn, name="chatty", meetings=4, day_step=5, mentions_each=9)

    body = client.get("/threads/suggestions").json()
    names = [subject["name"] for subject in body["subjects"]]
    assert names[0] == "sprawling"
    assert body["subjects"][0]["reach"]["spanDays"] == 120
    assert body["subjects"][0]["reach"]["meetingCount"] == 4


def test_a_one_meeting_subject_is_never_offered(
    client: TestClient, pool: ConnectionPool
) -> None:
    """It is a durable identity kept as a reuse target, not a thread.

    976 of the corpus's 1,090 rows are this shape, which is exactly why the
    catalogue this story replaces was unusable.
    """
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "lonely")
        topic_id, _ = add_topic(conn, meeting_id, "lonely subject")
        add_thread(conn, identity_key="lonely subject", topic_ids=[topic_id])
        spread_thread(conn, name="recurring", meetings=3, day_step=30)

    names = [s["name"] for s in client.get("/threads/suggestions").json()["subjects"]]
    assert names == ["recurring"]


def test_a_subject_inside_a_fortnight_has_no_history_to_offer(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        spread_thread(conn, name="brief", meetings=3, day_step=2)

    assert client.get("/threads/suggestions").json()["subjects"] == []


def test_near_duplicates_do_not_take_two_slots(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        spread_thread(conn, name="scorecard", meetings=4, day_step=40)
        spread_thread(conn, name="scorecards", meetings=4, day_step=35)
        spread_thread(conn, name="budget", meetings=4, day_step=30)

    names = [s["name"] for s in client.get("/threads/suggestions").json()["subjects"]]
    assert names == ["scorecard", "budget"]


def test_the_band_travels_with_the_answer(
    client: TestClient, pool: ConnectionPool
) -> None:
    """An empty list means something specific, and a client must be able to say
    what — not render a blank."""
    body = client.get("/threads/suggestions").json()
    assert body["subjects"] == []
    assert body["minMeetings"] >= 2
    assert body["maxMeetings"] > body["minMeetings"]
    assert body["minSpanDays"] > 0


def test_the_offer_is_bounded_by_limit(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        for index in range(5):
            spread_thread(conn, name=f"subject{index}", meetings=3, day_step=30)

    body = client.get("/threads/suggestions", params={"limit": 2}).json()
    assert len(body["subjects"]) == 2


# --- GET /threads/trace: the exhaustive leg -------------------------------


def test_every_meeting_stays_a_stop_when_the_cap_bites(
    client: TestClient, pool: ConnectionPool
) -> None:
    """The story's sharpest rule: cap per meeting, never overall.

    An overall limit would spend its whole budget inside the first, busiest
    meeting and cut the last two months off the timeline entirely — showing
    the opening weeks as though they were the whole history.
    """
    with pool.connection() as conn:
        thread_id = spread_thread(
            conn, name="sftp migration", meetings=3, day_step=30, mentions_each=8
        )

    body = client.get(
        "/threads/trace", params={"threadId": str(thread_id), "perMeeting": 2}
    ).json()

    assert body["mode"] == "exhaustive"
    assert body["counts"]["stops"] == 3
    assert [stop["quotedCount"] for stop in body["stops"]] == [2, 2, 2]
    assert [stop["mentionCount"] for stop in body["stops"]] == [8, 8, 8]
    assert body["counts"]["momentsQuoted"] == 6
    assert body["counts"]["mentionTotal"] == 24
    assert body["complete"] is False
    assert "6 of 24" in body["completenessNote"]
    assert "all 3 meetings" in body["completenessNote"]


def test_stops_run_left_to_right_in_time_on_one_timeline(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        thread_id = spread_thread(conn, name="trail closure", meetings=4, day_step=17)

    body = client.get(
        "/threads/trace", params={"threadId": str(thread_id)}
    ).json()
    occurred = [stop["occurredAt"] for stop in body["stops"]]
    assert occurred == sorted(occurred)
    assert body["span"]["meetings"] == 4
    assert body["span"]["days"] == 51


def test_an_uncapped_trace_says_it_holds_every_mention(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        thread_id = spread_thread(conn, name="budget", meetings=3, day_step=20)

    body = client.get("/threads/trace", params={"threadId": str(thread_id)}).json()
    assert body["complete"] is True
    assert "Every mention this corpus holds" in body["completenessNote"]


def test_a_typed_phrase_that_names_a_subject_takes_the_exhaustive_leg(
    client: TestClient, pool: ConnectionPool
) -> None:
    """And says so, so the view is never quietly showing something else."""
    with pool.connection() as conn:
        thread_id = spread_thread(conn, name="sftp migration", meetings=3, day_step=20)

    body = client.get("/threads/trace", params={"q": "  SFTP Migration "}).json()
    assert body["mode"] == "exhaustive"
    assert body["threadId"] == str(thread_id)
    assert body["resolvedFrom"] == "SFTP Migration"
    assert body["ranking"] is None


def test_a_topic_name_resolves_even_when_it_is_not_the_thread_name(
    client: TestClient, pool: ConnectionPool
) -> None:
    """A reader types the subject as they heard it, which is a topic name."""
    with pool.connection() as conn:
        meeting_a = seed_meeting(conn, "a")
        meeting_b = seed_meeting(conn, "b", offset_days=30)
        topic_a, _ = add_topic(conn, meeting_a, "Cedar Lake Trail closure")
        topic_b, _ = add_topic(conn, meeting_b, "cedar lake trail closure.")
        thread_id = add_thread(
            conn, identity_key="cedar lake trail closure", topic_ids=[topic_a, topic_b]
        )

    body = client.get(
        "/threads/trace", params={"q": "Cedar Lake Trail closure"}
    ).json()
    assert body["mode"] == "exhaustive"
    assert body["threadId"] == str(thread_id)


def test_a_superseded_moment_is_neither_quoted_nor_counted(
    client: TestClient, pool: ConnectionPool
) -> None:
    """A timeline must not interleave ghosts with live moments, and the two
    figures beside the cap must count the same row set or the cap reads as
    data loss."""
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "one")
        topic_id, live = add_topic(conn, meeting_id, "subject", start_ms=1_000)
        second = seed_meeting(conn, "two", offset_days=30)
        topic_two, _ = add_topic(conn, second, "subject", start_ms=1_000)
        ghost = add_mention(conn, topic_id, meeting_id, 50_000)
        supersede(conn, ghost)
        thread_id = add_thread(
            conn, identity_key="subject", topic_ids=[topic_id, topic_two]
        )

    body = client.get("/threads/trace", params={"threadId": str(thread_id)}).json()
    quoted = [m["momentId"] for stop in body["stops"] for m in stop["moments"]]
    assert str(ghost) not in quoted
    assert str(live) in quoted
    assert body["counts"]["mentionTotal"] == 2
    assert body["complete"] is True


def test_a_stop_carries_the_facts_a_no_screen_reason_is_built_from(
    client: TestClient, pool: ConnectionPool
) -> None:
    """AD-18: a stop with no screens must state *why*, and the two reasons are
    different claims. Transcript-only is an established absence; a recorded
    meeting whose moments carry no still is an observed one. The route ships
    both facts rather than a rendered sentence, so a client cannot read the
    wrong claim out of prose."""
    with pool.connection() as conn:
        transcript_only = seed_meeting(conn, "silent", has_recording=False)
        recorded = seed_meeting(conn, "filmed", offset_days=30, has_recording=True)
        first, _ = add_topic(conn, transcript_only, "subject")
        second, _ = add_topic(conn, recorded, "subject")
        thread_id = add_thread(
            conn, identity_key="subject", topic_ids=[first, second]
        )

    stops = client.get(
        "/threads/trace", params={"threadId": str(thread_id)}
    ).json()["stops"]
    assert [stop["hasRecording"] for stop in stops] == [False, True]
    assert [stop["screenCount"] for stop in stops] == [0, 0]
    # Every quoted moment says its screenshot is absent rather than omitting
    # the key, so "no still here" and "this field was not served" stay apart.
    assert all(
        moment["screenshotId"] is None for stop in stops for moment in stop["moments"]
    )


def test_related_subjects_never_offer_the_one_already_open(
    client: TestClient, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "one")
        second = seed_meeting(conn, "two", offset_days=20)
        traced_a, moment_a = add_topic(conn, meeting_id, "subject", start_ms=1_000)
        traced_b, _ = add_topic(conn, second, "subject", start_ms=1_000)
        neighbour = conn.execute(
            "INSERT INTO topic (meeting_id, name, gist) VALUES (%s, %s, %s)"
            " RETURNING id",
            (meeting_id, "neighbour", "a gist"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)"
            " VALUES (%s, %s, %s, %s)",
            (neighbour, moment_a, meeting_id, 1_000),
        )
        thread_id = add_thread(
            conn, identity_key="subject", topic_ids=[traced_a, traced_b]
        )
        add_thread(conn, identity_key="neighbour", topic_ids=[neighbour])

    body = client.get("/threads/trace", params={"threadId": str(thread_id)}).json()
    offered = {s["name"] for s in body["relatedSubjects"]}
    assert offered == {"neighbour"}


def test_a_trace_with_neither_parameter_is_refused_by_name(
    client: TestClient, pool: ConnectionPool
) -> None:
    response = client.get("/threads/trace")
    assert response.status_code == 400
    assert response.json()["type"].endswith("invalid-request")


def test_an_unknown_thread_id_is_a_named_404(
    client: TestClient, pool: ConnectionPool
) -> None:
    response = client.get("/threads/trace", params={"threadId": str(uuid4())})
    assert response.status_code == 404
    assert response.json()["type"].endswith("not-found")


# --- GET /threads/trace: the sample leg -----------------------------------


class _Embedder:
    model = "stub-embed"
    dimension = 8

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def embed_query(self, text: str) -> list[float]:
        if self._error is not None:
            raise self._error
        return [0.1] * self.dimension


def _rank(monkeypatch: pytest.MonkeyPatch, moment_ids: list[UUID]) -> None:
    """Replace the index at this module's boundary, keeping the route's own
    assembly, ordering and wording under test."""
    monkeypatch.setattr(threads_api, "meili_client", lambda config: object())
    monkeypatch.setattr(
        threads_api,
        "search_moments",
        lambda client, config, **kwargs: MomentSearchResult(
            hits=tuple(
                MomentHit(moment_id=moment_id, snippet=(), score=1.0 - index / 100)
                for index, moment_id in enumerate(moment_ids)
            ),
            estimated_total=len(moment_ids),
            limit=kwargs.get("limit", 60),
            offset=0,
        ),
    )


def _with_embedder(client: TestClient, embedder: Any) -> None:
    client.app.state.embedder = embedder


def test_free_text_is_a_sample_and_says_so(
    client: TestClient, pool: ConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sample presented as a full history is the same unverified-absence
    failure as claiming no recording exists (AD-18)."""
    with pool.connection() as conn:
        first = seed_meeting(conn, "one")
        second = seed_meeting(conn, "two", offset_days=40)
        early = add_moment(conn, first, 1_000)
        late = add_moment(conn, second, 1_000)

    _with_embedder(client, _Embedder())
    # Ranked worst-first on purpose: relevance order must not survive into the
    # timeline, which is sorted by time and never by score.
    _rank(monkeypatch, [late, early])

    body = client.get("/threads/trace", params={"q": "something nobody named"}).json()
    assert body["mode"] == "sample"
    assert body["complete"] is False
    assert body["threadId"] is None
    assert "sample, not every mention" in body["completenessNote"]
    assert [stop["meetingId"] for stop in body["stops"]] == [str(first), str(second)]


def test_adjacent_candidates_are_offered_rather_than_one_guessed(
    client: TestClient, pool: ConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"trail closures" must surface both neighbours, not pick one."""
    with pool.connection() as conn:
        spread_thread(conn, name="Cedar Lake Trail closure", meetings=3, day_step=20)
        spread_thread(conn, name="Trail closure outlook", meetings=2, day_step=20)

    _with_embedder(client, _Embedder())
    _rank(monkeypatch, [])

    body = client.get("/threads/trace", params={"q": "trail closure"}).json()
    assert body["mode"] == "sample"
    offered = {candidate["name"] for candidate in body["candidates"]}
    assert offered == {"Cedar Lake Trail closure", "Trail closure outlook"}
    assert all(c["meetingCount"] >= 2 for c in body["candidates"])


def test_a_wording_that_matches_nothing_offers_nothing_it_cannot_back(
    client: TestClient, pool: ConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_embedder(client, _Embedder())
    _rank(monkeypatch, [])

    body = client.get("/threads/trace", params={"q": "no such thing"}).json()
    assert body["stops"] == []
    assert body["candidates"] == []
    assert body["span"] is None
    assert "Nothing in the corpus matches this wording" in body["completenessNote"]


def test_the_sample_is_capped_per_meeting_too(
    client: TestClient, pool: ConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pool.connection() as conn:
        meeting_id = seed_meeting(conn, "busy")
        ranked = [add_moment(conn, meeting_id, 1_000 * (index + 1)) for index in range(6)]

    _with_embedder(client, _Embedder())
    _rank(monkeypatch, ranked)

    body = client.get(
        "/threads/trace", params={"q": "busy", "perMeeting": 2}
    ).json()
    assert body["counts"]["stops"] == 1
    assert body["stops"][0]["quotedCount"] == 2
    assert body["stops"][0]["mentionCount"] == 6


def test_an_unavailable_embedder_degrades_to_keyword_and_reports_it(
    client: TestClient, pool: ConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keyword-only is a good answer. An answer that hid which half it lost
    would not be (AD-18)."""
    _with_embedder(client, _Embedder(EmbedderUnavailableError("host is down")))
    _rank(monkeypatch, [])

    body = client.get("/threads/trace", params={"q": "anything"}).json()
    assert body["ranking"] == "keyword"


def test_a_misconfigured_embedder_is_refused_rather_than_degraded(
    client: TestClient, pool: ConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model answering wrongly is a config error no retry fixes, and it must
    not masquerade as an outage."""
    _with_embedder(client, _Embedder(EmbedderError("wrong dimension")))
    _rank(monkeypatch, [])

    response = client.get("/threads/trace", params={"q": "anything"})
    assert response.status_code == 503
    assert response.json()["type"].endswith("embedder-unusable")


def test_an_unreachable_index_is_a_named_refusal(
    client: TestClient, pool: ConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(config: Any) -> Any:
        raise StoreUnavailableError("meilisearch is not listening")

    _with_embedder(client, _Embedder())
    monkeypatch.setattr(threads_api, "meili_client", refuse)

    response = client.get("/threads/trace", params={"q": "anything"})
    assert response.status_code == 503
    assert response.json()["type"].endswith("thread-trace-store-unavailable")


# --- AD-17 -----------------------------------------------------------------


def test_no_statement_in_the_module_selects_a_stored_path() -> None:
    """Media is id-addressed, so no query here may read a path column.

    Written over every SQL constant the module holds rather than a listed few,
    so a statement added later is covered without this test being edited —
    which is the failure mode a hand-listed set has.
    """
    statements = {
        name: value
        for name, value in vars(threads_api).items()
        # SQL constants only, by the module's own naming: an upper-case name.
        # `__doc__` quotes the very column names this forbids, in prose that
        # explains why they are forbidden.
        if re.fullmatch(r"_?[A-Z][A-Z0-9_]*", name)
        and isinstance(value, str)
        and "SELECT" in value
    }
    assert len(statements) >= 12
    for name, statement in statements.items():
        assert ".path" not in statement and "drop_relative_path" not in statement, (
            f"{name} reads a stored path; media travels as opaque ids (AD-17)"
        )
