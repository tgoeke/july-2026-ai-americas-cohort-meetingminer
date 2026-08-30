"""The retrieval-check api calls: ``GET /search`` and the one sanctioned mutation.

Check 2.10 rides the public ``GET /search``, never a raw Meilisearch query —
the surface users hit is what the promise is about, and a raw index query
would pass while the route is broken (`evals/designs/retrieval-eval.md` leg 1,
AD-16). Check 2.11's approval, the harness's *only* mutation of the system,
goes through ``POST /moments/{moment_id}/approve`` for the same reason: the
gate under test is the one the public api exercises.

This module joins ``subjects.py`` and ``judge.py`` as the harness's httpx
users (``tests/test_harness_boundary.py`` pins the set). Like
``fetch_meetings``, every call takes an injectable ``transport`` so the whole
shape is exercisable offline, which is what keeps ``make evals-test``
store-free and api-free.

An api refusal arrives as a named error carrying the RFC 9457 problem slug
(``urn:meetingminer:problem:<slug>``), so a 503 ``search-store-unavailable``
or a 409 ``nothing-to-approve`` lands in the report as its diagnosis rather
than as a bare status code.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from evals.harness.checks import SEARCH_RECALL_K, PhraseSearch, SearchHit

DEFAULT_TIMEOUT = 10.0

#: The prefix every problem body's `type` carries (`api/problems.py`).
_PROBLEM_TYPE_PREFIX = "urn:meetingminer:problem:"


def is_local_api_base_url(base_url: str) -> bool:
    """Whether ``base_url`` names a loopback API process.

    Check 2.11 combines public API calls with direct reads from the configured
    local Postgres, Meilisearch, and Neo4j stores. It must never approve a
    remote API based on those local observations. The read-only retrieval
    checks may still use any reachable API; this predicate is specifically the
    publish-gate safety guard.
    """
    try:
        host = urlsplit(base_url).hostname
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1"}


class RetrievalReadError(Exception):
    """``GET /search`` could not be read, or answered in an unpromised shape.

    One error type for every way the read can fail, matching
    ``subjects.CorpusReadError``: a check that cannot query the surface under
    test records a named not-applicable rather than an empty result set.
    """


class ApproveError(Exception):
    """``POST /moments/{id}/approve`` was refused or could not be reached.

    The message carries the problem slug when the api sent one (404
    ``not-found``, 409 ``meeting-not-viewable`` / ``nothing-to-approve``), so
    the report names the refusal rather than a status code — and ``slug``
    carries it structurally, so a caller distinguishing one refusal from
    another (the probe layer's 409 race resolution) matches the RFC 9457
    type, never a substring of prose that may be reworded.
    """

    def __init__(self, message: str, *, slug: str | None = None) -> None:
        super().__init__(message)
        self.slug = slug


def _problem_slug(response: httpx.Response) -> str | None:
    """The RFC 9457 slug in a problem body, or ``None`` when there is none."""
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, Mapping):
        return None
    kind = payload.get("type")
    if isinstance(kind, str) and kind.startswith(_PROBLEM_TYPE_PREFIX):
        return kind[len(_PROBLEM_TYPE_PREFIX) :]
    return None


def _describe_refusal(response: httpx.Response) -> str:
    slug = _problem_slug(response)
    detail = None
    try:
        payload = response.json()
        if isinstance(payload, Mapping):
            detail = payload.get("detail")
    except ValueError:
        pass
    described = f"the api answered {response.status_code}"
    if slug:
        described += f" {slug}"
    if isinstance(detail, str) and detail:
        described += f": {detail}"
    return described


def search_hits(
    base_url: str,
    phrase: str,
    *,
    limit: int = SEARCH_RECALL_K,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> PhraseSearch:
    """One unfiltered ``GET /search`` for one planted phrase.

    ``limit`` defaults to check 2.10's k. No ``corpus`` and no ``meetingId``
    parameter, deliberately: the index gets no help — the plant has to
    surface against the whole corpus, exactly as a user's query would.
    """
    url = f"{base_url.rstrip('/')}/search"
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(url, params={"q": phrase, "limit": limit})
    except httpx.HTTPError as exc:
        raise RetrievalReadError(
            f"could not query {url} for {phrase!r}: {exc}"
        ) from exc
    # `!= 200`, not `>= 400`: 200 is the route's only success shape, so a
    # redirect surfaces as "the api answered 307" — a diagnosis — instead of
    # a JSON shape error from a body nobody promised.
    if response.status_code != 200:
        raise RetrievalReadError(
            f"searching {url} for {phrase!r} was refused —"
            f" {_describe_refusal(response)}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RetrievalReadError(f"{url} did not answer with JSON: {exc}") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("hits"), list):
        raise RetrievalReadError(
            f"{url} did not answer with a `hits` array — GET /search changed"
            " shape and the harness has to change with it"
        )
    hits: list[SearchHit] = []
    for hit in payload["hits"]:
        if (
            not isinstance(hit, Mapping)
            or not isinstance(hit.get("momentId"), str)
            or not isinstance(hit.get("meetingId"), str)
        ):
            raise RetrievalReadError(
                f"{url} returned a hit without string momentId/meetingId —"
                " GET /search changed shape and the harness has to change"
                " with it"
            )
        score = hit.get("score")
        hits.append(
            SearchHit(
                moment_id=hit["momentId"],
                meeting_id=hit["meetingId"],
                score=float(score) if isinstance(score, (int, float)) else None,
            )
        )
    ranking = payload.get("ranking")
    index_missing = payload.get("indexMissing")
    if not isinstance(ranking, str) or not isinstance(index_missing, bool):
        raise RetrievalReadError(
            f"{url} did not answer with string `ranking` and boolean"
            " `indexMissing` — GET /search changed shape and the harness has"
            " to change with it"
        )
    return PhraseSearch(
        hits=tuple(hits),
        ranking=ranking,
        index_missing=index_missing,
    )


def approve_moment(
    base_url: str,
    moment_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> tuple[dict[str, Any], ...]:
    """``POST /moments/{moment_id}/approve`` — the one sanctioned mutation.

    No body; returns every artifact the moment now carries, as plain dicts
    with at least ``id`` and ``state`` — the newly ``published`` rows among
    them are check 2.11's positive-half assert set. Any refusal raises
    :class:`ApproveError` carrying the problem slug.
    """
    url = f"{base_url.rstrip('/')}/moments/{moment_id}/approve"
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.post(url)
    except httpx.HTTPError as exc:
        raise ApproveError(f"could not reach {url}: {exc}") from exc
    # Same `!= 200` rule as `search_hits`: anything else — a 3xx included —
    # is a named refusal rather than a shape error downstream.
    if response.status_code != 200:
        raise ApproveError(
            f"approving moment {moment_id} was refused —"
            f" {_describe_refusal(response)}",
            slug=_problem_slug(response),
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApproveError(f"{url} did not answer with JSON: {exc}") from exc
    if not isinstance(payload, list) or not all(
        isinstance(item, Mapping)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("state"), str)
        for item in payload
    ):
        raise ApproveError(
            f"{url} did not answer with the promised artifact list — the"
            " route changed shape and the harness has to change with it"
        )
    return tuple(dict(item) for item in payload)
