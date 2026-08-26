"""Check 2.10's scoring and its api call, exercised with no store and no api.

``search_recall`` is a pure function over synthetic :class:`PhraseSearch`
outcomes — every I/O-matrix row that is not store-backed lives here: the rank
boundary at k, a missed phrase naming the hits it got instead, phrase-less
manifests as a blocking not-applicable, ``indexMissing`` as its own failure,
and a degraded ``keyword`` ranking recorded without failing.

``search_hits``/``approve_moment`` are exercised through ``httpx.MockTransport``
— the same seam ``fetch_meetings`` uses — so the problem-slug extraction and
the shape guards run under ``make evals-test``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from evals.harness import checks
from evals.harness.checks import PhraseSearch, SearchHit
from evals.harness.groundtruth import Manifest
from evals.harness.retrieval import (
    ApproveError,
    RetrievalReadError,
    approve_moment,
    is_local_api_base_url,
    search_hits,
)

MEETING = "11111111-1111-7111-8111-111111111111"
OTHER_MEETING = "22222222-2222-7222-8222-222222222222"


def manifest_with_phrases(*phrases: dict[str, Any]) -> Manifest:
    return Manifest(
        data={
            "meeting": {"id": "demo-001"},
            "planted": {"phrases": list(phrases)},
        }
    )


def a_phrase(phrase_id: str = "P1", text: str = "purple elephant") -> dict[str, Any]:
    return {"id": phrase_id, "text": text}


def hit(meeting_id: str = MEETING, moment: str = "m-1", score: float = 0.9) -> SearchHit:
    return SearchHit(moment_id=moment, meeting_id=meeting_id, score=score)


def outcome(
    *hits: SearchHit, ranking: str = "hybrid", index_missing: bool = False
) -> PhraseSearch:
    return PhraseSearch(hits=hits, ranking=ranking, index_missing=index_missing)


# --------------------------------------------------------------------------
# search_recall — the pure scoring
# --------------------------------------------------------------------------


def test_a_phrase_found_at_rank_one_passes_and_records_the_rank() -> None:
    result = checks.search_recall(
        manifest_with_phrases(a_phrase()), MEETING, {"P1": outcome(hit())}
    )
    assert result.passed, result.summary()
    assert result.metrics["recall_at_k"] == 1.0
    assert result.detail[0]["rank"] == 1
    assert result.detail[0]["ranking"] == "hybrid"
    assert result.thresholds == {"k": 5, "recall": 1.0}


def test_a_hit_at_the_rank_boundary_still_counts() -> None:
    """k = 5: the fifth hit is inside the window, per eval-design §2.10."""
    others = [hit(OTHER_MEETING, moment=f"m-{i}") for i in range(4)]
    result = checks.search_recall(
        manifest_with_phrases(a_phrase()),
        MEETING,
        {"P1": outcome(*others, hit(moment="m-target"))},
    )
    assert result.passed, result.summary()
    assert result.detail[0]["rank"] == 5


def test_a_missed_phrase_fails_naming_the_phrase_and_the_hits_it_got() -> None:
    result = checks.search_recall(
        manifest_with_phrases(a_phrase("P1", "purple elephant deployment")),
        MEETING,
        {"P1": outcome(hit(OTHER_MEETING, moment="m-x", score=0.42))},
    )
    assert not result.passed
    assert result.metrics["recall_at_k"] == 0.0
    problem = result.problems[0]
    assert "'P1'" in problem
    assert "purple elephant deployment" in problem
    assert "m-x" in problem and OTHER_MEETING in problem and "0.42" in problem


def test_one_missed_phrase_fails_even_when_the_others_are_found() -> None:
    result = checks.search_recall(
        manifest_with_phrases(a_phrase("P1"), a_phrase("P2", "second plant")),
        MEETING,
        {"P1": outcome(hit()), "P2": outcome(hit(OTHER_MEETING))},
    )
    assert not result.passed
    assert result.metrics["found"] == 1
    assert result.metrics["phrases"] == 2


def test_a_manifest_with_no_phrases_is_a_blocking_not_applicable() -> None:
    """Never a vacuous pass: recall over zero phrases measured nothing."""
    result = checks.search_recall(
        Manifest(data={"meeting": {"id": "demo-002"}}), MEETING, {}
    )
    assert not result.passed
    assert not result.applicable
    assert result.blocking
    assert "'demo-002'" in result.problems[0]
    assert "plants no phrases" in result.problems[0]


def test_a_missing_index_is_its_own_failure_naming_the_cause() -> None:
    result = checks.search_recall(
        manifest_with_phrases(a_phrase()),
        MEETING,
        {"P1": outcome(ranking="keyword", index_missing=True)},
    )
    assert not result.passed
    assert "indexMissing" in result.problems[0]
    assert result.detail[0]["index_missing"] is True


def test_keyword_ranking_is_recorded_but_is_not_itself_a_failure() -> None:
    """Verbatim plants must survive keyword ranking; failing on embedder
    downtime would misattribute the miss."""
    result = checks.search_recall(
        manifest_with_phrases(a_phrase()),
        MEETING,
        {"P1": outcome(hit(), ranking="keyword")},
    )
    assert result.passed, result.summary()
    assert result.detail[0]["ranking"] == "keyword"


def test_a_phrase_with_no_recorded_outcome_is_a_divergence_failure() -> None:
    """The queries issued and the manifest walked must be the same set, or the
    ratio is not recall — same rule as capture recall's denominator guard."""
    result = checks.search_recall(manifest_with_phrases(a_phrase()), MEETING, {})
    assert not result.passed
    assert "diverged" in result.problems[0]


def test_an_unqueried_phrase_fails_by_its_own_reason_not_as_a_divergence() -> None:
    """A phrase whose query the api refused is a named failure carrying the
    refusal — a different finding from the test layer losing track of it,
    and the queried phrases' measurements survive beside it."""
    result = checks.search_recall(
        manifest_with_phrases(a_phrase("P1"), a_phrase("P2", "second plant")),
        MEETING,
        {"P2": outcome(hit())},
        unqueried={"P1": "the api answered 503 search-store-unavailable"},
    )
    assert not result.passed
    assert result.metrics["found"] == 1, "the queried phrase still counted"
    failed = next(p for p in result.problems if "'P1'" in p)
    assert "could not be queried" in failed
    assert "search-store-unavailable" in failed
    assert "diverged" not in failed
    unqueried_detail = next(d for d in result.detail if d["phrase"] == "P1")
    assert unqueried_detail["queried"] is False
    assert "search-store-unavailable" in unqueried_detail["reason"]


def test_an_over_long_hit_list_cannot_widen_the_recall_window() -> None:
    """Defensive slice: the query asks for `limit=5`, and a response that
    ignored it must not turn recall@5 into recall@6."""
    others = [hit(OTHER_MEETING, moment=f"m-{i}") for i in range(5)]
    result = checks.search_recall(
        manifest_with_phrases(a_phrase()),
        MEETING,
        {"P1": outcome(*others, hit(moment="m-sixth"))},
    )
    assert not result.passed, "a hit at rank 6 is outside the window"
    assert result.detail[0]["rank"] is None
    assert len(result.detail[0]["hits"]) == 5


def test_an_outcome_naming_no_manifest_phrase_is_a_divergence_failure() -> None:
    """The reverse direction of the missing-outcome guard: extra keys mean
    the queries issued and the denominator walked are different sets."""
    result = checks.search_recall(
        manifest_with_phrases(a_phrase()),
        MEETING,
        {"P1": outcome(hit()), "P-stray": outcome(hit())},
    )
    assert not result.passed
    stray = next(p for p in result.problems if "P-stray" in p)
    assert "diverged" in stray


def test_an_unqueried_name_outside_the_manifest_is_a_divergence_failure() -> None:
    result = checks.search_recall(
        manifest_with_phrases(a_phrase()),
        MEETING,
        {"P1": outcome(hit())},
        unqueried={"P-stray": "the api answered 503 search-store-unavailable"},
    )
    assert not result.passed
    stray = next(problem for problem in result.problems if "P-stray" in problem)
    assert "diverged" in stray


# --------------------------------------------------------------------------
# search_hits — the api call, offline
# --------------------------------------------------------------------------


def search_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": "purple elephant",
        "ranking": "hybrid",
        "hits": [
            {"momentId": "m-1", "meetingId": MEETING, "score": 0.87},
            {"momentId": "m-2", "meetingId": OTHER_MEETING, "score": None},
        ],
        "estimatedTotal": 2,
        "limit": 5,
        "offset": 0,
        "indexMissing": False,
    }
    payload.update(overrides)
    return payload


def transport_returning(payload: Any, status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(status, json=payload)
    )


def test_search_hits_parses_hits_ranking_and_index_missing() -> None:
    result = search_hits(
        "http://api", "purple elephant", transport=transport_returning(search_payload())
    )
    assert result.ranking == "hybrid"
    assert result.index_missing is False
    assert result.hits[0] == SearchHit(moment_id="m-1", meeting_id=MEETING, score=0.87)
    assert result.hits[1].score is None


def test_search_hits_sends_an_unfiltered_query_at_the_default_k() -> None:
    """No corpus filter and no meetingId — the index gets no help."""
    seen: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(httpx.QueryParams(request.url.query))
        return httpx.Response(200, json=search_payload())

    search_hits("http://api", "purple elephant", transport=httpx.MockTransport(capture))
    assert seen["params"] == {"q": "purple elephant", "limit": "5"}


@pytest.mark.parametrize(
    "base_url",
    ["http://localhost:8000", "http://127.0.0.1:8765", "http://[::1]:8000"],
)
def test_loopback_api_targets_are_safe_for_publish_gate(base_url: str) -> None:
    assert is_local_api_base_url(base_url)


@pytest.mark.parametrize(
    "base_url",
    ["https://eval.example", "http://10.0.0.2:8000", "not a url"],
)
def test_non_loopback_api_targets_are_refused_for_publish_gate(base_url: str) -> None:
    assert not is_local_api_base_url(base_url)


def test_a_refusal_carries_the_problem_slug() -> None:
    problem = {
        "type": "urn:meetingminer:problem:search-store-unavailable",
        "title": "Service Unavailable",
        "status": 503,
        "detail": "Meilisearch unreachable at http://localhost:7700",
    }
    with pytest.raises(RetrievalReadError) as caught:
        search_hits(
            "http://api", "x", transport=transport_returning(problem, status=503)
        )
    assert "search-store-unavailable" in str(caught.value)
    assert "Meilisearch unreachable" in str(caught.value)


def test_a_connection_failure_is_the_same_named_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(RetrievalReadError):
        search_hits("http://api", "x", transport=httpx.MockTransport(refuse))


def test_a_redirect_is_a_named_refusal_not_a_shape_mystery() -> None:
    """Anything but 200 is refused by status — a 307 must read as "the api
    answered 307", never as a JSON error from a redirect body."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(307, headers={"location": "http://elsewhere"})
    )
    with pytest.raises(RetrievalReadError) as caught:
        search_hits("http://api", "x", transport=transport)
    assert "307" in str(caught.value)
    with pytest.raises(ApproveError) as approve_caught:
        approve_moment("http://api", "m-1", transport=transport)
    assert "307" in str(approve_caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"no": "hits"},
        {"hits": "not-a-list"},
        {"hits": [{"momentId": 7, "meetingId": MEETING}]},
    ],
)
def test_a_shape_drift_is_refused_by_name(payload: Any) -> None:
    with pytest.raises(RetrievalReadError):
        search_hits("http://api", "x", transport=transport_returning(payload))


@pytest.mark.parametrize(
    "payload",
    [search_payload(ranking=None), search_payload(indexMissing="false")],
)
def test_missing_or_malformed_search_metadata_is_refused(payload: Any) -> None:
    with pytest.raises(RetrievalReadError) as caught:
        search_hits("http://api", "x", transport=transport_returning(payload))
    assert "ranking" in str(caught.value)
    assert "indexMissing" in str(caught.value)


def test_a_non_json_answer_is_refused() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html>proxy error</html>")
    )
    with pytest.raises(RetrievalReadError):
        search_hits("http://api", "x", transport=transport)


# --------------------------------------------------------------------------
# approve_moment — the one sanctioned mutation, offline
# --------------------------------------------------------------------------


def test_approve_moment_posts_and_returns_the_artifact_states() -> None:
    seen: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = request.read()
        return httpx.Response(
            200,
            json=[
                {"id": "a-1", "kind": "adr", "state": "published"},
                {"id": "a-2", "kind": "action-item", "state": "published"},
            ],
        )

    returned = approve_moment(
        "http://api", "m-1", transport=httpx.MockTransport(capture)
    )
    assert seen["method"] == "POST"
    assert seen["path"] == "/moments/m-1/approve"
    assert seen["body"] == b"", "the route takes no body"
    assert [item["state"] for item in returned] == ["published", "published"]


@pytest.mark.parametrize(
    ("status", "slug"),
    [
        (409, "nothing-to-approve"),
        (409, "meeting-not-viewable"),
        (404, "not-found"),
    ],
)
def test_an_approve_refusal_carries_the_problem_slug(status: int, slug: str) -> None:
    problem = {
        "type": f"urn:meetingminer:problem:{slug}",
        "title": "Conflict",
        "status": status,
        "detail": "refused",
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json=problem)
    )
    with pytest.raises(ApproveError) as caught:
        approve_moment("http://api", "m-1", transport=transport)
    assert slug in str(caught.value)


def test_an_approve_answer_that_is_not_an_artifact_list_is_refused() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"approved": True})
    )
    with pytest.raises(ApproveError):
        approve_moment("http://api", "m-1", transport=transport)


def test_the_error_types_survive_json_reencoding() -> None:
    """The slug lives in the message, so a report line renders it verbatim."""
    problem = {
        "type": "urn:meetingminer:problem:embedder-unusable",
        "title": "Service Unavailable",
        "status": 503,
        "detail": "wrong dimension",
    }
    with pytest.raises(RetrievalReadError) as caught:
        search_hits(
            "http://api", "x", transport=transport_returning(problem, status=503)
        )
    assert "embedder-unusable" in json.dumps(str(caught.value))
