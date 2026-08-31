"""POST /chat end to end: retrieval → synthesis → the citation gate → the wire.

Store-backed, like `test_api_search.py`, and for the same reason: the property
under test is that a citation leaving this api came out of *Postgres* after real
retrieval ranked it, and nothing short of the real stores proves that.

**No model is ever reached.** Every test here binds a fake completer over
`meetingminer.api.chat.build_llm` — the conftest autouse guard already does it,
and these tests replace it with a scripted one. The `Llm` calls a request makes
are, in order, classification and synthesis, so a scripted fake reads as the
route reads.

**The synthesis fake writes its answer from the prompt it was given.** That is
deliberate rather than convenient: a test cannot know the seeded moment ids
before the route retrieves them, and a fake that cites what it was actually
shown is the honest stand-in for a compliant model. The dishonest ones — a
stranger's uuid, an uncited sentence, plain prose — are scripted literally,
because those are exactly the drafts the gate exists to refuse.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
from uuid import UUID, uuid4

import pytest
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.api.chat import (
    ARTIFACTS_PER_MOMENT_MAX_CHARS,
    CHAT_QUESTION_MAX_LENGTH,
    MOMENT_TEXT_MAX_CHARS,
    RetrievedArtifact,
    RetrievedMoment,
    build_synthesis_prompt,
)
from meetingminer.api.citations import MomentCitation, Rejection, validate
from meetingminer.config import AppConfig
from meetingminer.projections.stores import ProjectionError, StoreUnavailableError

from conftest import truncate_evidence
from projection_seed import SeededTurn, seed_meeting
from projection_seed import insert_artifact as seed_artifact

# One definition of the near-orthogonal embedder, shared rather than re-derived:
# `conftest.FakeEmbedder`'s vectors are almost parallel, which makes the
# semantic floor meaningless and every query return the whole corpus — and this
# file needs "nothing matched" to be reachable.
from test_api_search import SpreadEmbedder, bind_embedder

pytestmark = pytest.mark.slow(reason="/chat retrieves through the Neo4j and Meilisearch test twins: 54 tests, 96.6s at e5510c7")

MARKER = re.compile(r"\[\[moment:([0-9a-fA-F-]{36})\]\]")

# The classifier replies, written the way the prompt asks for them.
SEARCH_ONLY = json.dumps({"template": None, "searchTerms": "purchase order"})


def participant_topic(
    participant: str, topic: str, search_terms: str | None = None
) -> str:
    return json.dumps(
        {
            "template": "participant-topic-moments",
            "participant": participant,
            "topic": topic,
            "searchTerms": search_terms if search_terms is not None else topic,
        }
    )


def screen_history(screen: str, search_terms: str = "vendor portal") -> str:
    return json.dumps(
        {"template": "screen-history", "screen": screen, "searchTerms": search_terms}
    )


def supersede(pool: ConnectionPool, moment_id: UUID) -> None:
    """Mark one moment the way the `moments` stage does.

    The same UPDATE `test_api_moments.py::_supersede` uses (provenance merged,
    count squared to zero, links dropped), so "superseded" means one thing
    across the suite rather than two.
    """
    with pool.connection() as conn:
        conn.execute(
            "UPDATE moment SET"
            "   provenance = provenance || '{\"superseded\": true}'::jsonb,"
            "   segment_count = 0"
            " WHERE id = %s",
            (moment_id,),
        )
        conn.execute("DELETE FROM moment_segment WHERE moment_id = %s", (moment_id,))
        conn.commit()


def label_screen(pool: ConnectionPool, screen_id: UUID, label: str) -> None:
    """Give a screen the human-editable name a question would call it by."""
    with pool.connection() as conn:
        conn.execute("UPDATE screen SET label = %s WHERE id = %s", (label, screen_id))
        conn.commit()


class ChatLlm:
    """A scripted `Llm` for the two calls `POST /chat` makes.

    ``route`` answers the classification call. ``draft`` answers synthesis: a
    string is returned verbatim, a callable is handed the moment ids the
    synthesis prompt actually showed and returns the draft to test with.
    """

    def __init__(
        self,
        route: str = SEARCH_ONLY,
        draft: str | Callable[[list[str]], str] | None = None,
    ) -> None:
        self.route = route
        self.draft = draft if draft is not None else cite_every_moment
        self.calls: list[str] = []

    def complete(self, prompt: str) -> Any:
        from meetingminer.adapters.llm import LlmReply

        self.calls.append(prompt)
        if len(self.calls) == 1:
            text = self.route
        elif callable(self.draft):
            text = self.draft(MARKER.findall(prompt))
        else:
            text = self.draft
        return LlmReply(text=text, model="fake-chat", fallback_engaged=False)

    @property
    def synthesis_prompt(self) -> str:
        assert len(self.calls) >= 2, "synthesis was never called"
        return self.calls[1]


def cite_every_moment(moment_ids: list[str]) -> str:
    """One cited sentence per retrieved moment — the compliant model."""
    return " ".join(
        f"Point {index} came from the corpus [[moment:{moment_id}]]."
        for index, moment_id in enumerate(moment_ids, start=1)
    )


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    truncate_evidence(test_pool)
    return test_pool


@pytest.fixture()
def embedder(app_config: AppConfig) -> SpreadEmbedder:
    return SpreadEmbedder(dimension=app_config.settings.embedder.dimension)


@pytest.fixture()
def chat_client(client: Any, embedder: SpreadEmbedder) -> Iterator[Any]:
    """The TestClient with a stand-in embedder bound, restored afterwards."""
    import meetingminer.api.main as api_main

    original = api_main.app.state.embedder
    api_main.app.state.embedder = embedder
    try:
        yield client
    finally:
        api_main.app.state.embedder = original


@pytest.fixture()
def chat_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[..., ChatLlm]:
    """Bind `POST /chat` to a scripted completer for the rest of one test."""
    import meetingminer.api.chat as chat_module

    def _install(**kwargs: Any) -> ChatLlm:
        engine = ChatLlm(**kwargs)
        monkeypatch.setattr(chat_module, "build_llm", lambda *_a, **_kw: engine)
        return engine

    return _install


def bind_chat_config(monkeypatch: pytest.MonkeyPatch, **knobs: int) -> None:
    """Retune `api.chat` for the rest of one test.

    Against `app.state.config`, not the session-scoped `app_config` fixture:
    `api/main` loads its own AppConfig at import, so those are two instances and
    only the app's is the one a request reads."""
    import meetingminer.api.main as api_main

    chat = api_main.app.state.config.settings.api.chat
    for key, value in knobs.items():
        monkeypatch.setattr(chat, key, value)


def project(
    pool: ConnectionPool, config: AppConfig, meeting_id: UUID, embedder: Any
) -> None:
    with pool.connection() as conn:
        projections.project_meeting(
            conn, config, meeting_id, embedder_factory=lambda: embedder
        )


def ask(client: Any, question: str, **kwargs: Any) -> Any:
    return client.post("/chat", json={"question": question}, **kwargs)


def answered(client: Any, question: str) -> dict[str, Any]:
    response = ask(client, question)
    assert response.status_code == 200, response.text
    return response.json()


def refused(client: Any, question: str, reason: str, **kwargs: Any) -> dict[str, Any]:
    response = ask(client, question, **kwargs)
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:no-citable-answer"
    assert body["reason"] == reason
    # Nothing partial ever leaves: not a sentence, not a citation.
    assert "answer" not in body and "citations" not in body
    return body


def moment_rows(pool: ConnectionPool, meeting_id: UUID) -> dict[str, tuple[Any, ...]]:
    with pool.connection() as conn:
        return {
            str(row[0]): row
            for row in conn.execute(
                "SELECT id, meeting_id, start_ms, end_ms, screenshot_id,"
                " source_deep_link FROM moment WHERE meeting_id = %s",
                (meeting_id,),
            ).fetchall()
        }


# --- the cited answer, both legs ------------------------------------------


def test_a_search_led_question_answers_with_postgres_resolved_citations(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """AC2: every citation field equals that moment's row, and the answer text
    carries no marker."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-search")
    project(pool, app_config, seeded.meeting_id, embedder)
    llm = chat_llm(route=SEARCH_ONLY)

    body = answered(chat_client, "what happened with the purchase order?")

    assert body["route"]["template"] is None
    assert body["route"]["fallbackReason"] == "no-template"
    assert body["route"]["searchHits"] >= 1
    assert body["citations"], body
    assert "[[moment:" not in body["answer"]

    rows = moment_rows(pool, seeded.meeting_id)
    for citation in body["citations"]:
        row = rows[citation["momentId"]]
        assert citation["meetingId"] == str(row[1])
        assert citation["startMs"] == row[2]
        assert citation["endMs"] == row[3]
        assert citation["screenshotId"] == (str(row[4]) if row[4] else None)
        assert citation["sourceDeepLink"] == row[5]
    # Classification then synthesis, and nothing else.
    assert len(llm.calls) == 2

    # The evidence really is in the prompt. Without this the transcript join
    # could break — every moment arriving with empty text — and the suite would
    # stay green, because the fakes build their draft from the marker headers
    # alone: an endpoint answering from prompts that contain no evidence at all,
    # gate satisfied.
    prompt = llm.synthesis_prompt
    assert "Whitmore, Ellis: And the purchase order still needs approval." in prompt
    # And the block header names the meeting and the date it happened, so two
    # occurrences of a recurring meeting are distinguishable.
    assert "Data Hub Demo — 2026-08-05 at" in prompt


def test_search_uses_classifier_terms_when_the_question_has_no_indexed_phrase(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """Classifier normalization is the search leg's contract, not a prompt hint."""
    _driver, _meili = projection_stores
    seeded_corpus(pool, app_config, embedder, "chat-api-classifier-terms")
    chat_llm(route=SEARCH_ONLY)

    body = answered(chat_client, "What did we decide?")

    assert body["route"]["searchHits"] >= 1
    assert body["citations"]


def test_a_transcript_only_citation_serializes_its_source_deep_link(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(
            conn, source_id="chat-api-transcript-deep-link", has_recording=False
        )
    project(pool, app_config, seeded.meeting_id, embedder)
    chat_llm(route=SEARCH_ONLY)

    body = answered(chat_client, "what happened with the purchase order?")
    rows = moment_rows(pool, seeded.meeting_id)
    assert body["citations"]
    for citation in body["citations"]:
        assert citation["screenshotId"] is None
        assert citation["sourceDeepLink"] == rows[citation["momentId"]][5]


def test_prompt_dropped_moments_are_not_eligible_citations() -> None:
    """The prompt's evidence set and the gate's allowed IDs must stay identical."""
    moments = tuple(
        RetrievedMoment(
            citation=MomentCitation(
                moment_id=uuid4(),
                meeting_id=uuid4(),
                start_ms=index * 1_000,
                end_ms=(index + 1) * 1_000,
            ),
            meeting_title="Long meeting",
            meeting_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            text="x" * MOMENT_TEXT_MAX_CHARS,
        )
        for index in range(25)
    )
    prompt, prompted_ids = build_synthesis_prompt("What happened?", moments)
    dropped = next(
        moment.citation.moment_id
        for moment in moments
        if moment.citation.moment_id not in prompted_ids
    )

    assert prompted_ids
    assert f"[[moment:{dropped}]]" not in prompt
    outcome = validate(
        f"The hidden moment says so [[moment:{dropped}]].",
        prompted_ids,
        lambda _ids: {},
    )
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "unresolvable-marker"


def test_many_artifacts_on_one_moment_share_a_bounded_budget() -> None:
    """A moment's block must not grow unboundedly with the number of
    published artifacts citing it: N artifacts each up to a full moment's
    worth of text would let one heavily-annotated moment dwarf every other
    block despite the overall prompt cap. The artifacts collectively share
    one budget, cropped as a whole rather than per artifact."""
    moment_id = uuid4()
    moment = RetrievedMoment(
        citation=MomentCitation(
            moment_id=moment_id, meeting_id=uuid4(), start_ms=0, end_ms=1_000
        ),
        meeting_title="Data Hub Demo",
        meeting_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        text="A short transcript.",
    )
    artifacts = {
        moment_id: tuple(
            RetrievedArtifact(
                moment_id=moment_id,
                kind="adr",
                title=f"Decision {index}",
                body="x" * MOMENT_TEXT_MAX_CHARS,
            )
            for index in range(10)
        )
    }
    prompt, prompted_ids = build_synthesis_prompt(
        "What did we decide?", (moment,), artifacts
    )
    assert prompted_ids == (moment_id,)
    marker = f"[[moment:{moment_id}]]"
    block = prompt.split(marker, 1)[1]
    # The transcript plus the shared artifact budget, with slack for the
    # header line and the "Published ... from this moment" labels — nowhere
    # near what 10 uncapped artifacts (10 * MOMENT_TEXT_MAX_CHARS) would cost.
    assert len(block) < MOMENT_TEXT_MAX_CHARS + ARTIFACTS_PER_MOMENT_MAX_CHARS + 500


def test_citations_are_read_from_postgres_and_not_from_the_index(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """AD-6, proved by making the two disagree — the same move
    `test_api_search.py` makes for `/search`."""
    from meetingminer.projections.stores import MOMENTS_INDEX, await_task

    _driver, meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-poisoned-index")
    project(pool, app_config, seeded.meeting_id, embedder)
    poisoned = str(uuid4())
    await_task(
        meili,
        meili.index(MOMENTS_INDEX).update_documents(
            [
                {"id": str(moment_id), "startMs": 999_999, "meetingId": poisoned}
                for moment_id in seeded.moment_ids
            ]
        ),
    )
    chat_llm(route=SEARCH_ONLY)

    body = answered(chat_client, "what happened with the purchase order?")
    rows = moment_rows(pool, seeded.meeting_id)
    assert body["citations"]
    for citation in body["citations"]:
        assert citation["startMs"] == rows[citation["momentId"]][2] != 999_999
        assert citation["meetingId"] == str(seeded.meeting_id) != poisoned


def test_a_traversal_led_question_cites_the_templates_moments(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """The demo traversal: two meetings one participant attended, and the answer
    cites moments the 3.2 template produced, re-read from Postgres."""
    from datetime import datetime, timezone

    _driver, _meili = projection_stores
    with pool.connection() as conn:
        first = seed_meeting(
            conn,
            source_id="chat-api-traversal-1",
            started_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            screen_identity_keys=("sha256:chat-screen-a",),
        )
        second = seed_meeting(
            conn,
            source_id="chat-api-traversal-2",
            started_at=datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc),
            screen_identity_keys=("sha256:chat-screen-b",),
        )
    project(pool, app_config, first.meeting_id, embedder)
    project(pool, app_config, second.meeting_id, embedder)
    chat_llm(route=participant_topic("Goeke, Timothy", "purchase order"))

    body = answered(
        chat_client, "did I already explain the purchase order to Timothy Goeke?"
    )

    assert body["route"]["template"] == "participant-topic-moments"
    assert body["route"]["anchorResolved"] is True
    # One matching moment per meeting: the template spans both, which is the
    # whole point of the "I already explained this" question.
    assert body["route"]["traversalRows"] >= 2

    seeded_ids = {str(m) for m in (*first.moment_ids, *second.moment_ids)}
    cited = {citation["momentId"] for citation in body["citations"]}
    assert cited <= seeded_ids
    all_rows = {
        **moment_rows(pool, first.meeting_id),
        **moment_rows(pool, second.meeting_id),
    }
    for citation in body["citations"]:
        row = all_rows[citation["momentId"]]
        assert (citation["startMs"], citation["endMs"]) == (row[2], row[3])


def test_a_participant_the_corpus_does_not_know_resolves_to_no_anchor(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No silent zero: the traversal reports its anchor unresolved, the search
    leg still runs, and when it also finds nothing the answer is `no-evidence`
    rather than an empty success."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-unknown-anchor")
    project(pool, app_config, seeded.meeting_id, embedder)
    llm = chat_llm(route=participant_topic("Zephaniah Quillfeather", "zylographic"))

    body = refused(
        chat_client,
        "did I explain zylographic reconciliation to Zephaniah Quillfeather?",
        "no-evidence",
    )
    # The distinction is on the wire, not only in a log line: without it this
    # body would be byte-identical to a question that simply matched nothing.
    assert body["route"]["anchorResolved"] is False
    assert body["route"]["traversalOutcome"] == "anchor-unknown"
    assert body["route"]["template"] == "participant-topic-moments"
    # And in the log, where an operator looks for the name that failed.
    assert "chat.anchor_unresolved" in capsys.readouterr().out
    # The classifier ran; synthesis did not — nothing was retrieved to cite.
    assert len(llm.calls) == 1


# --- every rejection row of the matrix ------------------------------------


def test_a_marker_naming_a_moment_nobody_retrieved_is_refused(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-poisoned-marker")
    project(pool, app_config, seeded.meeting_id, embedder)
    stranger = uuid4()
    chat_llm(
        route=SEARCH_ONLY, draft=f"The ledger was reconciled [[moment:{stranger}]]."
    )

    refused(
        chat_client, "what happened with the purchase order?", "unresolvable-marker"
    )


def test_a_moment_deleted_between_retrieval_and_validation_is_refused(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """AD-6's read-back is inside the request, not a cache of retrieval: a row
    that disappears while the model is thinking must still be caught."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-deleted-moment")
    project(pool, app_config, seeded.meeting_id, embedder)

    def delete_then_cite(moment_ids: list[str]) -> str:
        assert moment_ids, "the fake needs a retrieved moment to delete"
        with pool.connection() as conn:
            conn.execute(
                "DELETE FROM moment WHERE id = ANY(%s)",
                ([UUID(m) for m in moment_ids],),
            )
            conn.commit()
        return cite_every_moment(moment_ids)

    chat_llm(route=SEARCH_ONLY, draft=delete_then_cite)

    refused(
        chat_client, "what happened with the purchase order?", "unresolvable-marker"
    )


def test_one_uncited_sentence_refuses_the_whole_answer(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-uncited")
    project(pool, app_config, seeded.meeting_id, embedder)

    def one_cited_one_not(moment_ids: list[str]) -> str:
        return (
            f"The purchase order still needs approval [[moment:{moment_ids[0]}]]."
            " It was approved the following Tuesday."
        )

    chat_llm(route=SEARCH_ONLY, draft=one_cited_one_not)
    refused(chat_client, "what happened with the purchase order?", "uncited-claim")


def test_plain_prose_is_refused_as_no_citations(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    fake_chat_llm: Callable[..., Any],
    embedder: SpreadEmbedder,
) -> None:
    """Through the conftest fixture, so the shared money guard is exercised by
    the same path a future chat test will reach for."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-no-citations")
    project(pool, app_config, seeded.meeting_id, embedder)
    fake_chat_llm(replies=(SEARCH_ONLY, "The purchase order still needs approval."))

    refused(chat_client, "what happened with the purchase order?", "no-citations")


def test_an_empty_corpus_is_refused_without_spending_a_single_model_call(
    pool: ConnectionPool,
    projection_stores: Any,
    chat_client: Any,
    fake_chat_llm: Callable[..., Any],
) -> None:
    """Nothing in the corpus can be cited, so nothing this endpoint could emit
    would pass the gate — and no provider is contacted to discover that."""
    _driver, _meili = projection_stores
    fake = fake_chat_llm()

    refused(chat_client, "what happened with the purchase order?", "no-evidence")
    assert fake.calls == []


def test_a_question_that_matches_nothing_is_refused_before_synthesis(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """A populated corpus that holds no answer: the classifier ran, retrieval
    came back empty, and synthesis never happened."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-no-match")
    project(pool, app_config, seeded.meeting_id, embedder)
    llm = chat_llm(route=json.dumps({"template": None, "searchTerms": "zylographic"}))

    body = refused(
        chat_client, "what did we decide about zylographic bathymetry?", "no-evidence"
    )
    # The same reason, a different route: no template was dispatched at all, so
    # `anchorResolved` is null rather than false. This is the pair the
    # unknown-anchor test above is distinguishable *from*.
    assert body["route"]["anchorResolved"] is None
    assert body["route"]["traversalOutcome"] == "not-dispatched"
    assert len(llm.calls) == 1


# --- the SSE surface ------------------------------------------------------


def sse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE body into (event name, payload) pairs, comments ignored."""
    events: list[tuple[str, dict[str, Any]]] = []
    name: str | None = None
    data: list[str] = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line.startswith(":"):
            continue
        if line == "":
            if name is not None and data:
                events.append((name, json.loads("\n".join(data))))
            name, data = None, []
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            name = value
        elif field == "data":
            data.append(value)
    if name is not None and data:
        events.append((name, json.loads("\n".join(data))))
    return events


def test_the_stream_replays_the_validated_answer_in_the_pinned_order(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """AC4: `chat.token`+ then `chat.citations` then `chat.done`, every token a
    chunk of the answer the gate already passed."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-sse")
    project(pool, app_config, seeded.meeting_id, embedder)

    chat_llm(route=SEARCH_ONLY)
    reference = answered(chat_client, "what happened with the purchase order?")

    chat_llm(route=SEARCH_ONLY)
    response = ask(
        chat_client,
        "what happened with the purchase order?",
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")

    events = sse_events(response.text)
    names = [name for name, _ in events]
    assert names[-2:] == ["chat.citations", "chat.done"]
    assert set(names[:-2]) == {"chat.token"}
    assert names.count("chat.token") >= 1

    streamed = "".join(
        payload["text"] for name, payload in events if name == "chat.token"
    )
    assert streamed == reference["answer"]
    citations = dict(events)["chat.citations"]["citations"]
    assert citations == reference["citations"]
    assert dict(events)["chat.done"]["route"] == reference["route"]
    # Every payload names its own event, so a captured stream is self-describing
    # (the same contract `api/events.py` states for job events).
    for name, payload in events:
        assert payload["event"] == name


def test_a_rejected_answer_never_opens_the_stream(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """AC5: the SSE caller gets the problem body and zero `chat.token` events —
    distinguishable from a transport error, which is the whole reason the gate
    runs before the response type is chosen."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-sse-rejected")
    project(pool, app_config, seeded.meeting_id, embedder)
    chat_llm(route=SEARCH_ONLY, draft="The purchase order still needs approval.")

    body = refused(
        chat_client,
        "what happened with the purchase order?",
        "no-citations",
        headers={"Accept": "text/event-stream"},
    )
    assert body["status"] == 422
    assert "chat.token" not in json.dumps(body)


def test_an_explicitly_unacceptable_sse_representation_falls_back_to_json(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    seeded_corpus(pool, app_config, embedder, "chat-api-sse-q-zero")
    chat_llm(route=SEARCH_ONLY)

    response = ask(
        chat_client,
        "what happened with the purchase order?",
        headers={"Accept": "application/json, text/event-stream; q=0"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["citations"]


# --- the door and the dependencies ----------------------------------------


@pytest.mark.parametrize("question", ["", "   ", "\n\t "])
def test_a_blank_question_is_refused_at_the_door(
    chat_client: Any, question: str
) -> None:
    response = ask(chat_client, question)
    assert response.status_code == 422
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_a_question_past_the_length_bound_is_refused_at_the_door(
    chat_client: Any,
) -> None:
    response = ask(chat_client, "a" * (CHAT_QUESTION_MAX_LENGTH + 1))
    assert response.status_code == 422
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"


def test_an_unreachable_search_store_is_a_named_503(
    pool: ConnectionPool,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Named, not a 500: the slug says which process to restart.

    Seeded but unprojected on purpose — the corpus guard reads Postgres, so the
    request reaches the search leg, which is where the outage is."""
    import meetingminer.api.chat as chat_module

    with pool.connection() as conn:
        seed_meeting(conn, source_id="chat-api-search-down")
    chat_llm(route=SEARCH_ONLY)

    def down(_config: Any) -> Any:
        raise StoreUnavailableError("Meilisearch unreachable at http://localhost:7700")

    monkeypatch.setattr(chat_module, "meili_client", down)
    response = ask(chat_client, "what happened with the purchase order?")
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:chat-search-store-unavailable"
    assert body["store"] == "meilisearch"


def test_an_unreachable_graph_store_is_a_named_503(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meetingminer.api.chat as chat_module

    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-graph-down")
    project(pool, app_config, seeded.meeting_id, embedder)
    chat_llm(route=participant_topic("Goeke, Timothy", "purchase order"))

    def down(_config: Any) -> Any:
        raise StoreUnavailableError("Neo4j unreachable at bolt://localhost:7687")

    monkeypatch.setattr(chat_module, "neo4j_driver", down)
    response = ask(chat_client, "did I explain the purchase order to Timothy Goeke?")
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:chat-graph-store-unavailable"
    assert body["store"] == "neo4j"


def test_an_unusable_search_store_is_a_named_503(
    pool: ConnectionPool,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meetingminer.api.chat as chat_module

    with pool.connection() as conn:
        seed_meeting(conn, source_id="chat-api-search-unusable")
    chat_llm(route=SEARCH_ONLY)
    monkeypatch.setattr(
        chat_module,
        "meili_client",
        lambda _config: (_ for _ in ()).throw(ProjectionError("index malformed")),
    )

    response = ask(chat_client, "what happened with the purchase order?")
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:chat-search-store-unusable"
    assert body["store"] == "meilisearch"


def test_an_unusable_graph_store_is_a_named_503(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meetingminer.api.chat as chat_module

    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-graph-unusable")
    project(pool, app_config, seeded.meeting_id, embedder)
    chat_llm(route=participant_topic("Goeke, Timothy", "purchase order"))
    monkeypatch.setattr(
        chat_module,
        "neo4j_driver",
        lambda _config: (_ for _ in ()).throw(ProjectionError("graph malformed")),
    )

    response = ask(chat_client, "did I explain the purchase order to Timothy Goeke?")
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:chat-graph-store-unusable"
    assert body["store"] == "neo4j"


# --- NFR7: no artifact text reaches synthesis -----------------------------


def test_no_unpublished_artifact_text_reaches_the_synthesis_prompt(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """Retrieval draws from evidence moments only. An `extracted` artifact lives
    in the database of record and surfaces in a moment's right rail; it must not
    reach the model that writes the answer."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-api-nfr7")
        seed_artifact(
            conn,
            seeded.moment_ids[0],
            seeded.meeting_id,
            state="extracted",
            title="Zylographic reconciliation decision",
            body="We will migrate the zylographic queue in Q4.",
        )
        conn.commit()
    project(pool, app_config, seeded.meeting_id, embedder)
    llm = chat_llm(route=SEARCH_ONLY)

    body = answered(chat_client, "what happened with the purchase order?")
    assert body["citations"]
    assert "zylographic" not in llm.synthesis_prompt.casefold()


# --- anchor resolution refuses rather than guesses -------------------------


def seeded_corpus(
    pool: ConnectionPool,
    app_config: AppConfig,
    embedder: SpreadEmbedder,
    source_id: str,
    **kwargs: Any,
) -> Any:
    """One seeded, projected meeting — the setup most cases below share."""
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id=source_id, **kwargs)
    project(pool, app_config, seeded.meeting_id, embedder)
    return seeded


@pytest.mark.parametrize(
    ("anchor", "why"),
    [
        # An unescaped `%` is a pattern matching every row; behind LIMIT 2 it
        # would hand the traversal an arbitrary participant.
        ("%", "a bare wildcard"),
        ("%Goeke%", "wildcards around a real name"),
        # `_` matches any single character: unescaped, "timothy g_eke" finds
        # "timothy goeke" — a near miss silently promoted to a match.
        ("timothy g_eke", "a single-character wildcard"),
        # Normalizes to the empty needle, which would become LIKE '%%'.
        (",", "bare punctuation"),
    ],
)
def test_a_wildcard_or_empty_anchor_resolves_to_nobody(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    anchor: str,
    why: str,
) -> None:
    """Anchor text is model-written data, never a pattern.

    The question still answers from the search leg — the assertion is that the
    traversal reports an unknown anchor rather than dispatching onto whichever
    row the wildcard happened to reach first."""
    _driver, _meili = projection_stores
    seeded_corpus(pool, app_config, embedder, f"chat-api-wildcard-{abs(hash(anchor))}")
    chat_llm(route=participant_topic(anchor, "purchase order", "purchase order"))

    body = answered(chat_client, "what happened with the purchase order?")
    assert body["route"]["anchorResolved"] is False, why
    assert body["route"]["traversalRows"] == 0
    assert body["route"]["traversalOutcome"] == "anchor-unknown"


def test_two_equally_exact_candidates_resolve_to_nobody(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two people whose names normalize identically are not one person.

    Resolving to the first row would dispatch the traversal on a guess and then
    return citations that all resolve — the most convincing wrong answer this
    endpoint can produce."""
    _driver, _meili = projection_stores
    seeded_corpus(
        pool,
        app_config,
        embedder,
        "chat-api-ambiguous",
        participants=(
            ("mail:timothy.goeke@contoso.com", "Goeke, Timothy"),
            ("mail:t.goeke@contractor.example", "Goeke, Timothy"),
        ),
    )
    chat_llm(
        route=participant_topic("Timothy Goeke", "purchase order", "purchase order")
    )

    body = answered(chat_client, "what happened with the purchase order?")
    assert body["route"]["anchorResolved"] is False
    out = capsys.readouterr().out
    assert "chat.anchor_ambiguous" in out
    assert '"exact": true' in out


def test_an_exact_match_beside_a_substring_match_is_not_ambiguous(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """The other half of the guard: exactness breaks the tie, so a name that is
    also a prefix of somebody else's still resolves."""
    _driver, _meili = projection_stores
    seeded_corpus(
        pool,
        app_config,
        embedder,
        "chat-api-exact-wins",
        participants=(
            ("mail:ellis@contoso.com", "Whitmore, Ellis"),
            ("mail:ellis.hollis@contoso.com", "Whitmore, Ellis Hollis"),
        ),
    )
    chat_llm(
        route=participant_topic("Ellis Whitmore", "purchase order", "purchase order")
    )

    body = answered(chat_client, "what happened with the purchase order?")
    assert body["route"]["anchorResolved"] is True
    assert body["route"]["traversalOutcome"] == "resolved"


# --- what retrieval drops, and why ----------------------------------------


def test_a_hit_the_database_of_record_no_longer_holds_is_dropped_and_logged(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stale index document is never a citation and never silently discarded:
    the id is logged so `make rebuild` is a diagnosable fix."""
    _driver, _meili = projection_stores
    seeded = seeded_corpus(pool, app_config, embedder, "chat-api-stale-hit")
    with pool.connection() as conn:
        # A second, unprojected meeting, so the corpus is not empty and the
        # request reaches retrieval rather than the pre-synthesis guard.
        seed_meeting(conn, source_id="chat-api-stale-hit-other")
        conn.execute("DELETE FROM moment WHERE meeting_id = %s", (seeded.meeting_id,))
        conn.commit()
    chat_llm(route=SEARCH_ONLY)

    refused(chat_client, "what happened with the purchase order?", "no-evidence")
    out = capsys.readouterr().out
    assert "chat.stale_hit" in out
    assert str(seeded.moment_ids[1]) in out


def test_a_superseded_moment_is_dropped_from_retrieval_and_logged(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Its id stays resolvable so existing citations survive, but no *new*
    answer may be sent to it — `api/moments.py` renders it as superseded."""
    _driver, _meili = projection_stores
    seeded = seeded_corpus(pool, app_config, embedder, "chat-api-superseded")
    superseded_id = seeded.moment_ids[1]
    supersede(pool, superseded_id)
    llm = chat_llm(route=SEARCH_ONLY)

    refused(chat_client, "what happened with the purchase order?", "no-evidence")
    out = capsys.readouterr().out
    assert "chat.superseded_moment" in out
    # Never offered to the model either: only the classification call happened,
    # and the id appears in no prompt.
    assert len(llm.calls) == 1
    assert str(superseded_id) not in llm.calls[0]


def test_a_corpus_of_only_superseded_moments_costs_no_model_call(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    fake_chat_llm: Callable[..., Any],
    embedder: SpreadEmbedder,
) -> None:
    """The pre-synthesis guard asks what Postgres can *cite*, not what it holds:
    a corpus of ghosts can cite nothing, so it bills nothing."""
    _driver, _meili = projection_stores
    seeded = seeded_corpus(pool, app_config, embedder, "chat-api-all-superseded")
    for moment_id in seeded.moment_ids:
        supersede(pool, moment_id)
    fake = fake_chat_llm()

    refused(chat_client, "what happened with the purchase order?", "no-evidence")
    assert fake.calls == []


def test_a_moment_superseded_between_retrieval_and_validation_is_refused(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """The gate's own read-back carries the live-moment clause, not just the
    context read: a moment superseded while the model was thinking must not be
    emitted as a citation."""
    _driver, _meili = projection_stores
    seeded_corpus(pool, app_config, embedder, "chat-api-superseded-midflight")

    def supersede_then_cite(moment_ids: list[str]) -> str:
        assert moment_ids, "the fake needs a retrieved moment to supersede"
        for moment_id in moment_ids:
            supersede(pool, UUID(moment_id))
        return cite_every_moment(moment_ids)

    chat_llm(route=SEARCH_ONLY, draft=supersede_then_cite)
    refused(
        chat_client, "what happened with the purchase order?", "unresolvable-marker"
    )


# --- the other half of the AD-7 dispatch surface --------------------------


def test_a_screen_history_question_cites_the_templates_moments(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """The mirror of the participant traversal, and the half of `TEMPLATE_ANCHORS`
    nothing else exercises end to end: swap the two anchor arms, or mistype a
    column in the screen lookup, and every screen question would degrade
    silently to search-only."""
    from datetime import datetime, timezone

    _driver, _meili = projection_stores
    shared = ("sha256:chat-shared-screen",)
    with pool.connection() as conn:
        earlier = seed_meeting(
            conn,
            source_id="chat-api-screen-earlier",
            title="Portal Review",
            screen_identity_keys=shared,
            started_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )
        later = seed_meeting(
            conn,
            source_id="chat-api-screen-later",
            title="Portal Review",
            screen_identity_keys=shared,
            started_at=datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc),
        )
    assert earlier.screen_ids == later.screen_ids, "fixture must reuse the screen row"
    label_screen(pool, earlier.screen_ids[0], "Vendor Portal")
    project(pool, app_config, earlier.meeting_id, embedder)
    project(pool, app_config, later.meeting_id, embedder)
    chat_llm(route=screen_history("vendor portal"))

    body = answered(chat_client, "every time the vendor portal came up")

    assert body["route"]["template"] == "screen-history"
    assert body["route"]["anchorResolved"] is True
    assert body["route"]["traversalOutcome"] == "resolved"
    assert body["route"]["traversalRows"] >= 2
    seeded_ids = {str(m) for m in (*earlier.moment_ids, *later.moment_ids)}
    assert {citation["momentId"] for citation in body["citations"]} <= seeded_ids


def test_a_template_the_router_filled_wrongly_is_its_own_outcome(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`run_template` refuses malformed parameters. That is a routing miss, not
    a statement about the corpus, so it must not read as "the corpus does not
    know that anchor" on the wire."""
    import meetingminer.api.chat as chat_module

    _driver, _meili = projection_stores
    seeded_corpus(pool, app_config, embedder, "chat-api-input-refused")

    def refuse(_driver_arg: Any, _name: str, **_params: Any) -> Any:
        raise ValueError("topic must not be blank")

    monkeypatch.setattr(chat_module, "run_template", refuse)
    chat_llm(
        route=participant_topic("Goeke, Timothy", "purchase order", "purchase order")
    )

    body = answered(chat_client, "what happened with the purchase order?")
    assert body["route"]["traversalOutcome"] == "input-refused"
    # Not `false`: anchor resolution succeeded, so claiming the anchor was
    # unknown would be a different — and wrong — sentence.
    assert body["route"]["anchorResolved"] is None
    assert body["route"]["traversalRows"] == 0


# --- the configured knobs actually bound something ------------------------


LEDGER_TURNS = (
    SeededTurn(1, 2_000, "The ledger opened clean this week.", "Goeke, Timothy", 0),
    SeededTurn(2, 5_000, "Good to hear.", "Whitmore, Ellis", 1),
    SeededTurn(3, 40_000, "The ledger closed late again.", "Goeke, Timothy", 0),
    SeededTurn(4, 44_000, "We will watch it.", "Whitmore, Ellis", 1),
)


def test_the_configured_retrieval_limit_bounds_the_search_leg(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-10: the knob is only a knob if turning it changes the answer.

    Both seeded moments say "ledger", so the unbounded leg retrieves two; with
    the configured breadth at one it retrieves one."""
    _driver, _meili = projection_stores
    seeded_corpus(
        pool, app_config, embedder, "chat-api-retrieval-limit", turns=LEDGER_TURNS
    )
    route = json.dumps({"template": None, "searchTerms": "ledger"})

    chat_llm(route=route)
    assert (
        answered(chat_client, "what happened with the ledger?")["route"]["searchHits"]
        == 2
    )

    bind_chat_config(monkeypatch, retrieval_limit=1)
    chat_llm(route=route)
    bounded = answered(chat_client, "what happened with the ledger?")
    assert bounded["route"]["searchHits"] == 1
    assert bounded["route"]["retrieved"] == 1


def test_the_traversal_row_limit_keeps_the_most_recent_rows_and_says_so(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two properties in one: the cap keeps the *recent* appearances, because
    these templates answer recency questions, and it announces that it dropped
    something — silent truncation is the sibling of the silent zero."""
    from datetime import datetime, timezone

    _driver, _meili = projection_stores
    with pool.connection() as conn:
        earlier = seed_meeting(
            conn,
            source_id="chat-api-cap-earlier",
            started_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            screen_identity_keys=("sha256:chat-cap-a",),
        )
        later = seed_meeting(
            conn,
            source_id="chat-api-cap-later",
            started_at=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
            screen_identity_keys=("sha256:chat-cap-b",),
        )
    project(pool, app_config, earlier.meeting_id, embedder)
    project(pool, app_config, later.meeting_id, embedder)
    route = participant_topic("Goeke, Timothy", "purchase order", "purchase order")

    chat_llm(route=route)
    full = answered(chat_client, "did I explain the purchase order to Timothy Goeke?")
    assert full["route"]["traversalRows"] == 2
    assert full["route"]["traversalTruncated"] is False

    bind_chat_config(monkeypatch, traversal_row_limit=1)
    chat_llm(route=route)
    capped = answered(chat_client, "did I explain the purchase order to Timothy Goeke?")
    assert capped["route"]["traversalRows"] == 1
    assert capped["route"]["traversalTruncated"] is True
    # And the row it kept is the recent one — the appearance the question is
    # about. (The search leg also runs, so the assertion is on the traversal's
    # own contribution: the later meeting's moment leads the citation order.)
    assert capped["citations"][0]["meetingId"] == str(later.meeting_id)


# --- the two embedder failures, and the two model failures ----------------


def test_an_unreachable_embedder_degrades_to_keyword_retrieval(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """The one embedder failure this system is required to survive. Reorder the
    two `except` clauses and every question becomes a 503 instead."""
    from conftest import DownEmbedder

    _driver, _meili = projection_stores
    seeded_corpus(pool, app_config, embedder, "chat-api-embedder-down")
    bind_embedder(chat_client, DownEmbedder())
    chat_llm(route=SEARCH_ONLY)

    body = answered(chat_client, "what happened with the purchase order?")
    assert body["citations"]


def test_a_misconfigured_embedder_refuses_with_a_named_503(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """A model that answers *wrongly* is a config error no retry fixes, and it
    must not masquerade as the outage above."""
    from conftest import BrokenEmbedder

    _driver, _meili = projection_stores
    seeded_corpus(pool, app_config, embedder, "chat-api-embedder-broken")
    bind_embedder(chat_client, BrokenEmbedder(model="wrong-model", dimension=7))
    chat_llm(route=SEARCH_ONLY)

    response = ask(chat_client, "what happened with the purchase order?")
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:embedder-unusable"
    assert body["model"] == "wrong-model"
    assert body["dimension"] == 7


@pytest.mark.parametrize("call", ["classification", "synthesis"])
@pytest.mark.parametrize(
    ("error", "slug"),
    [
        ("LlmUnavailableError", "chat-model-unavailable"),
        ("LlmError", "chat-model-unusable"),
    ],
)
def test_a_failing_chat_model_is_a_named_503_not_an_opaque_500(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    fake_chat_llm: Callable[..., Any],
    embedder: SpreadEmbedder,
    call: str,
    error: str,
    slug: str,
) -> None:
    """Both models down names a dependency an operator restarts, and it has to
    stay distinguishable from a rejected answer — which is a 422 and means the
    system worked."""
    import meetingminer.adapters.llm as llm_module

    _driver, _meili = projection_stores
    seeded_corpus(pool, app_config, embedder, f"chat-api-model-{call}-{slug}")
    raised = getattr(llm_module, error)("the model host said no")
    replies = (raised,) if call == "classification" else (SEARCH_ONLY, raised)
    fake_chat_llm(replies=replies)

    response = ask(chat_client, "what happened with the purchase order?")
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == f"urn:meetingminer:problem:{slug}"
    assert body["purpose"] == call


def test_no_fallback_primary_failure_is_a_prompt_503_naming_the_binding(
    pool: ConnectionPool,
    chat_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC CAP-4: with no fallback configured, a primary model failure reaches
    the caller as a named 503 — through the *real* `FallbackLlm` composition, so
    the no-fallback re-raise path is the thing under test, not a fake of it.

    The detail must name the `llm.roles.chat` binding and the configured model,
    because the reader of this sentence is deciding what to fix; and the primary
    must have been called exactly once — no retry, no substitute (the silent
    fallback this break-fix removed must stay removed).
    """
    import meetingminer.api.chat as chat_module
    import meetingminer.api.main as api_main
    from meetingminer.adapters.llm import FallbackLlm, LlmUnavailableError

    # A moment row so the no-evidence guard lets the request reach the model.
    # Never projected: classification fails before either store is queried.
    with pool.connection() as conn:
        seed_meeting(conn, source_id="chat-api-no-fallback-503")

    binding = api_main.app.state.config.settings.llm.roles.chat
    assert binding.fallback is None, (
        "config.yaml's chat role grew a fallback — this test exercises the"
        " no-fallback decision of record and needs updating alongside it"
    )

    class DownPrimary:
        model = binding.model
        calls = 0

        def complete(self, prompt: str, options: Any = None) -> Any:
            DownPrimary.calls += 1
            raise LlmUnavailableError("Incorrect API key provided")

    engine = FallbackLlm(DownPrimary(), None)
    monkeypatch.setattr(chat_module, "build_llm", lambda *_a, **_kw: engine)

    response = ask(chat_client, "what happened with the purchase order?")
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:chat-model-unavailable"
    assert body["binding"] == "llm.roles.chat"
    assert body["model"] == binding.model
    assert "llm.roles.chat" in body["detail"]
    assert binding.model in body["detail"]
    assert "no fallback configured" in body["detail"]
    # Exactly one model call: the failure was surfaced, not retried and never
    # handed to a substitute.
    assert DownPrimary.calls == 1


# --- the money guard guards itself ----------------------------------------


def test_every_production_build_llm_call_site_is_named_in_the_money_guard() -> None:
    """`LLM_CALL_SITES` states its own failure mode; this is what enforces it.

    The autouse `_no_real_llm` fixture patches exactly the call sites that list
    names. A new role — a judge binding, a second chat surface — that calls
    `build_llm` without being added there is a call site that reaches a real
    provider the first time any test walks past it, and spends real money doing
    it. An AST walk over the package is the same machinery
    `test_projections_single_writer.py` uses to keep AD-4 falsifiable.
    """
    import ast
    from pathlib import Path

    from conftest import LLM_CALL_SITES

    package_root = Path(__file__).resolve().parents[1] / "meetingminer"
    named = {module for module, _attribute in LLM_CALL_SITES}

    callers: set[str] = set()
    for path in sorted(package_root.rglob("*.py")):
        module = (
            "meetingminer." + path.relative_to(package_root).with_suffix("").as_posix()
        ).replace("/", ".")
        if module.startswith("meetingminer.adapters.llm"):
            continue  # the port's own package defines build_llm; it never calls it
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else None
                )
                if name == "build_llm":
                    callers.add(module)

    assert callers, "the walk found no build_llm call site at all — it is vacuous"
    unguarded = callers - named
    assert not unguarded, (
        "these modules call build_llm but are not in conftest.LLM_CALL_SITES, so"
        " the autouse no-real-model guard does not cover them and a test walking"
        f" past one would spend real API money: {sorted(unguarded)}"
    )


# --- published artifacts fold into retrieval (story 4.4) ------------------


ARTIFACT_TERMS = json.dumps({"template": None, "searchTerms": "Quorlix"})


def _insert_artifact(
    pool: ConnectionPool,
    moment_id: UUID,
    meeting_id: UUID,
    *,
    kind: str = "adr",
    state: str = "published",
    title: str = "Adopt the Quorlix feed",
    body: str = "We standardize on the Quorlix reconciliation feed.",
) -> UUID:
    # A pool adapter over the one canonical INSERT (projection_seed).
    with pool.connection() as conn:
        return seed_artifact(
            conn, moment_id, meeting_id, kind=kind, state=state, title=title, body=body
        )


def test_an_artifact_hit_contributes_its_source_moment_citation(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """Epics AC3: the question is answered *by the artifact* — its term
    appears in no transcript — yet the citation is the source moment's,
    through the unchanged six-field gate, and the context block labels the
    artifact as published knowledge inside that moment's block."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-artifact")
    _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    project(pool, app_config, seeded.meeting_id, embedder)
    llm = chat_llm(route=ARTIFACT_TERMS)

    body = answered(chat_client, "what did we decide about Quorlix?")

    assert body["citations"], body
    cited = {citation["momentId"] for citation in body["citations"]}
    assert cited == {str(seeded.moment_ids[0])}
    assert body["route"]["searchHits"] == 1
    # The citation is exactly AD-15's six fields — no artifact field leaked
    # into the frozen contract.
    assert set(body["citations"][0]) == {
        "momentId",
        "meetingId",
        "startMs",
        "endMs",
        "screenshotId",
        "sourceDeepLink",
    }
    # The artifact's title/body entered the source moment's context block,
    # labelled as published, ahead of the model's synthesis call.
    prompt = llm.synthesis_prompt
    assert "Published adr from this moment: Adopt the Quorlix feed" in prompt
    assert "We standardize on the Quorlix reconciliation feed." in prompt
    # And it sits inside the moment's block, under that moment's marker.
    marker = f"[[moment:{seeded.moment_ids[0]}]]"
    block = prompt.split(marker, 1)[1]
    assert "Published adr from this moment" in block.split("[[moment:", 1)[0]


def test_artifact_rank_survives_postgres_readback(
    pool: ConnectionPool,
) -> None:
    import meetingminer.api.chat as chat_module

    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-artifact-rank")
        older = seed_artifact(
            conn,
            seeded.moment_ids[0],
            seeded.meeting_id,
            title="Older lower-ranked artifact",
        )
        newer = seed_artifact(
            conn,
            seeded.moment_ids[0],
            seeded.meeting_id,
            title="Newer higher-ranked artifact",
        )

    grouped = chat_module._read_artifact_context(pool, (newer, older))
    assert [artifact.title for artifact in grouped[seeded.moment_ids[0]]] == [
        "Newer higher-ranked artifact",
        "Older lower-ranked artifact",
    ]


def test_a_stale_summary_index_hit_is_dropped_as_non_citable(
    pool: ConnectionPool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A NULL-scoped artifact can never enter moment-keyed chat context."""
    import meetingminer.api.chat as chat_module

    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-stale-summary")
        summary_id = seed_artifact(
            conn,
            None,  # type: ignore[arg-type] -- migration 0022's meeting scope
            seeded.meeting_id,
            kind="summary",
            title="Executive summary",
            body="Whole-meeting analysis with no replayable anchor.",
        )

    capsys.readouterr()
    assert chat_module._read_artifact_context(pool, (summary_id,)) == {}
    assert "chat.stale_artifact_hit" in capsys.readouterr().out


def test_route_search_hits_does_not_double_count_a_shared_source_moment(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-artifact-mixed-route")
    _insert_artifact(
        pool,
        seeded.moment_ids[1],
        seeded.meeting_id,
        title="Purchase order approval",
        body="The purchase order still needs approval.",
    )
    project(pool, app_config, seeded.meeting_id, embedder)
    chat_llm(route=SEARCH_ONLY)

    body = answered(chat_client, "what happened with the purchase order?")

    assert body["route"]["searchHits"] == 1
    assert {citation["momentId"] for citation in body["citations"]} == {
        str(seeded.moment_ids[1])
    }


def test_full_ordinary_retrieval_cannot_crop_the_ranked_artifact_source(
    pool: ConnectionPool,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-vacuous regression for the 32k prompt-cap failure.

    Twenty-four maximum-size ordinary candidates precede one artifact source
    in the reviewed implementation, which drops the artifact block. The
    remediated ordering reserves its capacity and keeps its relevance lead.
    """
    import meetingminer.api.chat as chat_module

    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-artifact-prompt-cap")

    artifact_moment = seeded.moment_ids[0]
    ordinary_ids = tuple(uuid4() for _ in range(24))
    artifact_id = uuid4()
    all_ids = (*ordinary_ids, artifact_moment)
    contexts = {
        moment_id: RetrievedMoment(
            citation=MomentCitation(
                moment_id=moment_id,
                meeting_id=seeded.meeting_id,
                start_ms=index * 1_000,
                end_ms=(index + 1) * 1_000,
            ),
            meeting_title="Capacity test",
            meeting_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            text="x" * MOMENT_TEXT_MAX_CHARS,
        )
        for index, moment_id in enumerate(all_ids)
    }
    artifact = RetrievedArtifact(
        moment_id=artifact_moment,
        kind="adr",
        title="Highest-ranked published decision",
        body="This artifact must survive the full ordinary candidate budget.",
    )
    monkeypatch.setattr(chat_module, "_search_leg", lambda *_a, **_kw: ordinary_ids)
    monkeypatch.setattr(chat_module, "_artifact_leg", lambda *_a, **_kw: (artifact_id,))
    monkeypatch.setattr(
        chat_module,
        "_read_artifact_context",
        lambda *_a, **_kw: {artifact_moment: (artifact,)},
    )
    traversal_id = ordinary_ids[-1]
    monkeypatch.setattr(
        chat_module,
        "_traversal_leg",
        lambda *_a, **_kw: chat_module.TraversalLeg(ids=(traversal_id,)),
    )
    monkeypatch.setattr(chat_module, "_read_context", lambda *_a, **_kw: contexts)
    monkeypatch.setattr(
        chat_module,
        "_resolver",
        lambda _pool: (
            lambda ids: {moment_id: contexts[moment_id].citation for moment_id in ids}
        ),
    )
    llm = chat_llm(route=ARTIFACT_TERMS)

    body = answered(chat_client, "what did we decide about Quorlix?")

    marker = f"[[moment:{artifact_moment}]]"
    assert marker in llm.synthesis_prompt
    # Capacity selection prioritizes the artifact, while presentation keeps
    # traversal first and then ordinary search order rather than moving the
    # artifact ahead of either route.
    traversal_marker = f"[[moment:{traversal_id}]]"
    ordinary_marker = f"[[moment:{ordinary_ids[0]}]]"
    assert llm.synthesis_prompt.index(traversal_marker) < llm.synthesis_prompt.index(
        ordinary_marker
    )
    assert llm.synthesis_prompt.index(ordinary_marker) < llm.synthesis_prompt.index(
        marker
    )
    assert "Highest-ranked published decision" in llm.synthesis_prompt
    assert body["route"]["searchHits"] == 25
    assert any(
        citation["momentId"] == str(artifact_moment) for citation in body["citations"]
    )


def test_an_unpublished_artifact_contributes_nothing_to_chat(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
) -> None:
    """The structural half of AC2 through chat: a draft is in neither store,
    so a question only the draft could answer retrieves nothing and is
    refused — never answered from unpublished AI output."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-artifact-draft")
    _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id, state="extracted")
    project(pool, app_config, seeded.meeting_id, embedder)
    chat_llm(route=ARTIFACT_TERMS)

    body = refused(chat_client, "what did we decide about Quorlix?", "no-evidence")
    assert body["route"]["searchHits"] == 0


def test_a_stale_artifact_hit_never_reaches_the_synthesis_prompt(
    pool: ConnectionPool,
    app_config: AppConfig,
    projection_stores: Any,
    chat_client: Any,
    chat_llm: Callable[..., ChatLlm],
    embedder: SpreadEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A document the artifacts index still holds for a row that is no
    longer `published` (raw state surgery standing in for any index/Postgres
    skew, since there is no unpublish route) must never fold into the
    synthesis prompt — the chat sibling of `search.stale_artifact_hit`. This
    is the AC2/NFR7 boundary: unpublished AI output re-entering synthesis is
    exactly what the publish gate exists to prevent."""
    _driver, _meili = projection_stores
    with pool.connection() as conn:
        seeded = seed_meeting(conn, source_id="chat-artifact-stale")
    artifact_id = _insert_artifact(pool, seeded.moment_ids[0], seeded.meeting_id)
    project(pool, app_config, seeded.meeting_id, embedder)

    # The row's state moves out from under the index — no unpublish route.
    with pool.connection() as conn:
        conn.execute(
            "UPDATE artifact SET state = 'extracted' WHERE id = %s", (artifact_id,)
        )
        conn.commit()

    chat_llm(route=ARTIFACT_TERMS)
    body = refused(chat_client, "what did we decide about Quorlix?", "no-evidence")
    assert body["route"]["searchHits"] == 0
    assert "chat.stale_artifact_hit" in capsys.readouterr().out
