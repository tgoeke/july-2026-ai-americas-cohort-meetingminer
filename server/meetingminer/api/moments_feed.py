"""GET /moments/feed — the ranked front door (story 10.4, FR40).

The one screen that answers "what needs my attention" without a search. It is
a read over evidence (AD-5/AD-11): SELECTs only, no store clients, no writes,
and — the clause that shapes everything below — **no model call at request
time**. Every signal the order depends on was written by the worker and is
sitting in Postgres before the request arrives.

**The score is a pure function over plain facts.** :func:`score_candidate`
takes a :class:`FeedCandidate` — dataclasses of ints, strings and datetimes,
never a cursor or a connection — plus the config weights and a ``now``, and
returns a score and its reasons. That is what makes the ranking testable
without a database and reproducible from `config.yaml` plus the stored rows,
and it is why no ranking constant appears in this file: every number lives in
``ranking:`` in `config.yaml` with its recorded rationale (AD-10).

**Reason validation happens before pagination.** The order is not an
implementation detail, it is the acceptance criterion: candidates are scored,
each item's reasons are validated, an item with no valid reason is dropped and
logged, and only then are ``total``, ``offset`` and the page computed — from
the remaining rows alone. Validating after the slice would report a ``total``
counting rows the caller can never receive, and paging past the first screen
would skip rows rather than show them. :func:`rank_and_validate` does the two
steps in that order and returns both halves, so the route cannot get it
backwards and a test can assert the totals directly.

**Registration order.** ``/moments/feed`` is a literal path under
``/moments/{moment_id}``'s prefix, which is precisely the hazard
`api/registry.py` documents: registered after ``moments``, FastAPI would match
``feed`` as a ``moment_id`` and reject it as a malformed UUID. This module
therefore declares a ``ROUTER_ORDER`` below ``moments.py``'s, and
`tests/test_api_moments_feed.py` pins it. Story 2.2 owns ``moments.py`` and
nothing here edits it.

**Media stays ID-addressed (AD-17).** An item carries the opaque
``screenshotId`` and no path: the still is fetched through
``GET /media/files/{mediaId}``, never by joining a served string onto a root.
That is why ``screenshotPath`` — which ``GET /moments/{id}`` still serves for
2.2's renderer — is deliberately absent from the feed item.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal, Sequence, get_args
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.moments import PREVIEW_MAX_CHARS, ArtifactKind, ScreenViewType
from meetingminer.api.problems import ProblemDetails
from meetingminer.api.search import Corpus
from meetingminer.config import RankingConfig

router = APIRouter()
# Below `moments.py`'s 40 on purpose: see the module docstring.
ROUTER_ORDER = 35


# --- the wire vocabulary ----------------------------------------------------

# The six non-artifact reason kinds, exactly as the acceptance criteria spell
# them. A reason's `kind` is one of these or an `ArtifactKind` — the union
# below is the whole vocabulary, and a reason naming anything else is invalid
# and gets its item dropped.
SignalReasonKind = Literal["due", "risk", "question", "recency", "published", "thread"]
ReasonKind = ArtifactKind | SignalReasonKind

REASON_KINDS: tuple[str, ...] = get_args(ArtifactKind) + get_args(SignalReasonKind)

# The two `ranking_signal.kind` values, spelled as migration 0018's CHECK
# spells them. They are also reason kinds, which is not a coincidence: the
# stored row *is* the reason.
RISK = "risk"
QUESTION = "question"


class FeedReason(BaseModel):
    """Why this moment is on the feed, in the order that decided its score.

    ``ref`` is the id of the row the reason came from — an artifact, a ranking
    signal, a thread — so a card can link to its own evidence. ``at`` is the
    time the reason is about (a due date, a meeting start, a publication),
    never "now". Both are optional because not every reason has one.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    kind: ReasonKind
    label: str
    ref: str | None = None
    at: datetime | None = None


class FeedThread(BaseModel):
    """One thread chip on the card.

    ``color_ordinal`` is the server-owned immutable ordinal story 10.3
    allocates; the client maps it to a hue and never invents one. It is
    ``None`` on this branch, and only on this branch, because the column
    lands with story 10.3's migration 0017 — see the module the query lives
    in for how it is read without depending on the column's existence.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    thread_id: UUID
    name: str
    color_ordinal: int | None = None


class FeedItem(BaseModel):
    """One ranked moment, exactly the fields the story's AC enumerates.

    Deliberately no `score`: the acceptance criteria enumerate the card's
    fields, and a number the client cannot explain is not one of them. The
    ordered ``reasons`` are the explanation, and they are what story 10.5
    renders.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    moment_id: UUID
    meeting_id: UUID
    meeting_title: str | None = None
    started_at: datetime
    started_at_precision: str
    start_ms: int
    end_ms: int
    corpus: str
    has_recording: bool
    source_deep_link: str | None = None
    # Opaque, and opaque is the point (AD-17): resolved only through
    # `GET /media/files/{mediaId}`. No path is served here.
    screenshot_id: UUID | None = None
    view_type: ScreenViewType | None = None
    preview: str | None = None
    threads: list[FeedThread]
    # Non-empty by construction: an item whose reasons did not survive
    # validation was dropped before this model was built.
    reasons: list[FeedReason]


class MomentsFeedResponse(BaseModel):
    """The page, its filtered size, and its selected-corpus denominator.

    ``total`` counts the rows that survived reason validation — never the raw
    candidate scan — and all item filters. ``corpus_total`` counts the same
    validated selected corpus before the meeting, thread, and kind filters, so
    the client never derives that denominator or makes another HTTP request.

    Every request is a live ranking, not a snapshot shared with another page.
    The route clamps an offset beyond the filtered set to its end, so the
    in-response invariant `offset + len(items) <= total` always holds.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    items: list[FeedItem]
    total: int
    corpus_total: int
    limit: int
    offset: int


# --- the plain facts the score is computed over -----------------------------


@dataclass(frozen=True)
class CandidateArtifact:
    """One artifact of a candidate moment, as plain facts."""

    artifact_id: UUID
    kind: str
    state: str
    title: str
    body: str
    published_at: datetime | None = None


@dataclass(frozen=True)
class CandidateSignal:
    """One stored risk or open question."""

    signal_id: UUID
    kind: str
    label: str
    anchor_ms: int


@dataclass(frozen=True)
class CandidateThread:
    """One thread the candidate's moment belongs to."""

    thread_id: UUID
    name: str
    color_ordinal: int | None = None


@dataclass(frozen=True)
class FeedCandidate:
    """One moment and every stored signal about it — no cursor, no connection.

    This is the whole input to the scorer. ``moment_id`` and ``meeting_id``
    are ``None`` only for a row whose moment no longer resolves, which
    :func:`rank_and_validate` drops and logs rather than serializing.
    """

    moment_id: UUID | None
    meeting_id: UUID | None
    meeting_title: str | None
    corpus: str
    has_recording: bool
    started_at: datetime | None
    started_at_precision: str
    start_ms: int
    end_ms: int
    meeting_started_at: datetime | None
    source_deep_link: str | None = None
    screenshot_id: UUID | None = None
    view_type: str | None = None
    preview: str | None = None
    artifacts: tuple[CandidateArtifact, ...] = ()
    signals: tuple[CandidateSignal, ...] = ()
    threads: tuple[CandidateThread, ...] = ()


@dataclass(frozen=True)
class ScoredCandidate:
    """A candidate, its score, and the reasons that produced it."""

    candidate: FeedCandidate
    score: float
    reasons: tuple[FeedReason, ...]


@dataclass(frozen=True)
class DroppedCandidate:
    """A candidate that will not be served, and why — always logged."""

    moment_id: UUID | None
    reason: str
    detail: str = ""


def _card_threads(
    candidate: FeedCandidate, max_thread_reasons: int
) -> tuple[CandidateThread, ...]:
    """The valid, deterministic membership set used by score and wire alike."""
    return tuple(
        sorted(
            (thread for thread in candidate.threads if thread.name.strip()),
            key=lambda thread: (
                thread.name.strip().casefold(),
                thread.name.strip(),
                str(thread.thread_id),
            ),
        )[:max_thread_reasons]
    )


# --- stated timing ----------------------------------------------------------

# Which body label carries an action item's timing. The action-items prompt
# writes `Timing (as stated)`; real documents drift to `Due`, `Due date`,
# `When`, `By`. Matched as a whole word inside the label so `Owner` cannot
# match `by` and a `Details` column cannot match `date`.
_TIMING_LABEL = re.compile(
    r"(?:timing(?:\s*\(as stated\))?|due(?:\s+date)?|deadline|when|by)",
    re.IGNORECASE,
)

# What the prompt writes when the transcript stated no timing at all, plus the
# spellings a model reaches for anyway. Compared case-folded and stripped of
# punctuation: an item whose timing is one of these has no stated timing, and
# must not earn the weight of one.
_UNSTATED_TIMING = frozenset(
    {
        "not stated",
        "notstated",
        "none",
        "n/a",
        "na",
        "tbd",
        "tbc",
        "unknown",
        "unspecified",
        "",
    }
)

# The two calendar spellings a due date is read from. Anything else — "this
# week", "after the demo" — is *stated* timing that carries no date, which is
# a real distinction the AC depends on: it earns the stated-timing weight and
# no urgency, because the prompt is explicitly forbidden from converting a
# vague phrase into a calendar date and ranking on an invented one would be
# worse than not ranking on it.
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_US_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTH_NAME = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)"
)
_MONTH_FIRST_DATE = re.compile(
    rf"\b{_MONTH_NAME}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,\s*|\s+)(\d{{4}})\b",
    re.IGNORECASE,
)
_DAY_FIRST_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH_NAME}\.?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_MONTH_NUMBERS = {
    name: index
    for index, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}


def stated_timing(body: str) -> str | None:
    """The action item's stated timing text, or ``None`` when it stated none.

    Reads the labelled line the extraction parser wrote (``_title_and_body``
    renders every non-title cell as ``<header>: <cell>``), never the whole
    body: a due date mentioned inside a dependency sentence is prose, not the
    item's timing.
    """
    for line in body.splitlines():
        label, separator, value = line.partition(":")
        if not separator or _TIMING_LABEL.fullmatch(label.strip()) is None:
            continue
        text = value.strip()
        if text.casefold().strip(" .") in _UNSTATED_TIMING:
            continue
        if text:
            return text
    return None


def stated_due_date(timing: str) -> date | None:
    """The calendar date the timing text states, when it states one."""
    candidates: list[tuple[int, int, int, int]] = []
    candidates.extend(
        (match.start(), int(match.group(1)), int(match.group(2)), int(match.group(3)))
        for match in _ISO_DATE.finditer(timing)
    )
    candidates.extend(
        (match.start(), int(match.group(3)), int(match.group(1)), int(match.group(2)))
        for match in _US_DATE.finditer(timing)
    )
    candidates.extend(
        (
            match.start(),
            int(match.group(3)),
            _MONTH_NUMBERS[match.group(1)[:3].casefold()],
            int(match.group(2)),
        )
        for match in _MONTH_FIRST_DATE.finditer(timing)
    )
    candidates.extend(
        (
            match.start(),
            int(match.group(3)),
            _MONTH_NUMBERS[match.group(2)[:3].casefold()],
            int(match.group(1)),
        )
        for match in _DAY_FIRST_DATE.finditer(timing)
    )
    for _, year, month, day in sorted(candidates):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def due_urgency(due: date, now: datetime, horizon_days: float) -> float:
    """How urgent a stated due date is: 1.0 today or overdue, 0.0 at the horizon.

    Linear rather than exponential, unlike recency: a deadline does not decay,
    it arrives. Overdue clamps to 1.0 rather than growing without bound —
    something three months late is not thirty times more urgent than something
    due tomorrow, and letting it be would park one forgotten row at the top of
    the feed forever.
    """
    days_left = (due - now.astimezone(timezone.utc).date()).days
    if days_left <= 0:
        return 1.0
    if days_left >= horizon_days:
        return 0.0
    return 1.0 - days_left / horizon_days


def recency_factor(then: datetime, now: datetime, half_life_days: float) -> float:
    """Exponential decay: 1.0 now, 0.5 one half-life ago, never negative.

    A future timestamp — a clock skew, a meeting recorded with tomorrow's date
    — clamps to 1.0 rather than exceeding it, so no row can outrank the
    present by being wrong about it.
    """
    age_days = (now - then).total_seconds() / 86_400.0
    if age_days <= 0:
        return 1.0
    return float(0.5 ** (age_days / half_life_days))


# --- scoring ----------------------------------------------------------------


def _days_ago_label(then: datetime, now: datetime) -> str:
    days = int((now - then).total_seconds() // 86_400)
    if days <= 0:
        return "Met today"
    if days == 1:
        return "Met yesterday"
    return f"Met {days} days ago"


@dataclass
class _Term:
    """One scored contribution and the reason that explains it."""

    score: float
    reason: FeedReason


def score_candidate(
    candidate: FeedCandidate, ranking: RankingConfig, now: datetime
) -> tuple[float, tuple[FeedReason, ...]]:
    """The deterministic score and its ordered reasons — pure, no I/O.

    Reasons are ordered by the size of the contribution that produced them,
    highest first, so the first reason on a card is always the one that put it
    there. Ties break on the reason vocabulary's own order and then on the
    label, so two runs over identical rows produce byte-identical output.
    """
    weights = ranking.weights
    terms: list[_Term] = []
    hidden_score = 0.0

    # --- artifacts ---------------------------------------------------------
    # Once per kind, never once per row: a moment carrying two ADRs is not
    # twice as pressing as one carrying a single ADR, and a per-row sum would
    # let a verbose extraction pass outrank a decisive meeting.
    artifact_weight = {"adr": weights.adr, "decision": weights.decision}
    seen_kinds: set[str] = set()
    for artifact in candidate.artifacts:
        if artifact.kind in seen_kinds or artifact.kind == "action-item":
            continue
        if not artifact.title.strip():
            # A titleless artifact cannot produce a label, and a reason with
            # no label is invalid. Skipped here so it cannot contribute a
            # score it has no reason for; `validate_reasons` is what decides
            # whether the item survives at all.
            continue
        seen_kinds.add(artifact.kind)
        terms.append(
            _Term(
                artifact_weight.get(artifact.kind, 0.0),
                FeedReason(
                    kind=artifact.kind,
                    label=artifact.title.strip(),
                    ref=str(artifact.artifact_id),
                ),
            )
        )

    # --- action items with stated timing, soonest first --------------------
    # Both configured weights are categorical: a moment earns each at most
    # once, however many action rows the extraction produced. Pick the most
    # urgent action deterministically and let its two reasons explain the two
    # separate contributions (`action-item` for stated timing, `due` for the
    # calendar urgency). This also keeps the artifact-kind filter truthful.
    action_items = [
        artifact
        for artifact in candidate.artifacts
        if artifact.kind == "action-item" and artifact.title.strip()
    ]
    timed_actions: list[tuple[float, date | None, CandidateArtifact, str]] = []
    for artifact in action_items:
        timing = stated_timing(artifact.body)
        if timing is None:
            continue
        due = stated_due_date(timing)
        urgency = (
            due_urgency(due, now, ranking.due_horizon_days) if due is not None else 0.0
        )
        timed_actions.append((urgency, due, artifact, timing))

    if timed_actions:
        urgency, due, artifact, timing = min(
            timed_actions,
            key=lambda item: (
                -item[0],
                item[1] is None,
                item[1] or date.max,
                str(item[2].artifact_id),
            ),
        )
        label = f"{artifact.title.strip()} — {timing}"
        terms.append(
            _Term(
                weights.action_item_stated_timing,
                FeedReason(
                    kind="action-item",
                    label=label,
                    ref=str(artifact.artifact_id),
                ),
            )
        )
        if due is not None:
            terms.append(
                _Term(
                    weights.due_urgency * urgency,
                    FeedReason(
                        kind="due",
                        label=label,
                        ref=str(artifact.artifact_id),
                        at=datetime(
                            due.year, due.month, due.day, tzinfo=timezone.utc
                        ),
                    ),
                )
            )
    elif action_items:
        artifact = min(action_items, key=lambda item: str(item.artifact_id))
        # An action whose timing nobody stated is still worth saying on the
        # card, but earns no weight: the AC ranks only stated timing.
        terms.append(
            _Term(
                0.0,
                FeedReason(
                    kind="action-item",
                    label=artifact.title.strip(),
                    ref=str(artifact.artifact_id),
                ),
            )
        )

    # --- risks and open questions ------------------------------------------
    # Earned once per kind (see `max_signal_reasons` in config.yaml), while
    # the reasons themselves are capped separately so a card stays a card.
    for kind, weight in ((RISK, weights.risk), (QUESTION, weights.question)):
        matching = [signal for signal in candidate.signals if signal.kind == kind]
        if not matching:
            continue
        # Anchor order, so the reasons read down the meeting the way it
        # happened rather than in whatever order the aggregate returned them.
        matching.sort(key=lambda signal: (signal.anchor_ms, str(signal.signal_id)))
        for position, signal in enumerate(matching[: ranking.max_signal_reasons]):
            terms.append(
                _Term(
                    # The whole weight lands on the first of its kind; the
                    # rest are reasons a reader sees, not score.
                    weight if position == 0 else 0.0,
                    FeedReason(
                        kind=kind,
                        label=signal.label,
                        ref=str(signal.signal_id),
                    ),
                )
            )

    # --- recency ------------------------------------------------------------
    # The term is always in the score; the *reason* is only emitted while the
    # meeting is within one half-life. Beyond that, saying "recent" on the
    # card would be saying something untrue about a two-month-old meeting.
    if candidate.meeting_started_at is not None:
        factor = recency_factor(
            candidate.meeting_started_at, now, ranking.recency_half_life_days
        )
        contribution = weights.meeting_recency * factor
        if factor >= 0.5:
            terms.append(
                _Term(
                    contribution,
                    FeedReason(
                        kind="recency",
                        label=_days_ago_label(candidate.meeting_started_at, now),
                        at=candidate.meeting_started_at,
                    ),
                )
            )
        else:
            hidden_score += contribution

    # --- publication --------------------------------------------------------
    published = [
        artifact
        for artifact in candidate.artifacts
        if artifact.published_at is not None and artifact.title.strip()
    ]
    if published:
        newest = max(published, key=lambda artifact: artifact.published_at)  # type: ignore[arg-type,return-value]
        assert newest.published_at is not None
        factor = recency_factor(
            newest.published_at, now, ranking.recency_half_life_days
        )
        contribution = weights.publication_recency * factor
        if factor >= 0.5:
            terms.append(
                _Term(
                    contribution,
                    FeedReason(
                        kind="published",
                        label=newest.title.strip(),
                        ref=str(newest.artifact_id),
                        at=newest.published_at,
                    ),
                )
            )
        else:
            hidden_score += contribution

    # --- thread membership --------------------------------------------------
    chips = _card_threads(candidate, ranking.max_thread_reasons)
    if chips:
        for position, thread in enumerate(chips):
            terms.append(
                _Term(
                    weights.thread_membership if position == 0 else 0.0,
                    FeedReason(
                        kind="thread",
                        label=thread.name.strip(),
                        ref=str(thread.thread_id),
                    ),
                )
            )

    order = {kind: index for index, kind in enumerate(REASON_KINDS)}
    terms.sort(key=lambda term: (-term.score, order[term.reason.kind], term.reason.label))
    return hidden_score + sum(term.score for term in terms), tuple(
        term.reason for term in terms
    )


# --- validation, then pagination --------------------------------------------


def validate_reasons(reasons: Sequence[FeedReason]) -> tuple[FeedReason, ...]:
    """Keep the reasons a client can render; discard the rest.

    A reason is valid when its ``kind`` is in the vocabulary and its ``label``
    is not blank. Both are things a card is built out of: an unknown kind has
    no chip and no icon, and a blank label is an empty row. Neither is an
    error worth failing a request over — it is one bad row out of a corpus —
    so the reason is discarded, and an item left with none of them is dropped
    and named.
    """
    return tuple(
        reason
        for reason in reasons
        if reason.kind in REASON_KINDS and reason.label.strip()
    )


def rank_and_validate(
    candidates: Sequence[FeedCandidate], ranking: RankingConfig, now: datetime
) -> tuple[list[ScoredCandidate], list[DroppedCandidate]]:
    """Score, validate, and sort — everything that must happen *before* a page.

    Returns the surviving rows in served order and every dropped row with its
    named reason. The caller counts ``total`` from the first list and slices
    it; nothing here knows about ``limit`` or ``offset``, which is what makes
    it impossible for this project to compute a total over rows it then
    refuses to serve.
    """
    kept: list[ScoredCandidate] = []
    dropped: list[DroppedCandidate] = []
    for candidate in candidates:
        if (
            candidate.moment_id is None
            or candidate.meeting_id is None
            or candidate.started_at is None
        ):
            # The moment no longer resolves — deleted, or never joined. It is
            # dropped and named, never returned half-built.
            dropped.append(
                DroppedCandidate(
                    candidate.moment_id, "unresolved-moment", "no moment row joined"
                )
            )
            continue
        score, reasons = score_candidate(candidate, ranking, now)
        valid = validate_reasons(reasons)
        if not valid:
            dropped.append(
                DroppedCandidate(
                    candidate.moment_id,
                    "no-valid-reason",
                    f"{len(reasons)} reason(s) produced, none serializable",
                )
            )
            continue
        kept.append(ScoredCandidate(candidate, score, valid))

    kept.sort(
        key=lambda scored: (
            -scored.score,
            # The AC's tie-break, and story 10.3's: meeting, then moment. The
            # ids are stable, so an equal-scoring page never reshuffles
            # between two requests over unchanged rows.
            str(scored.candidate.meeting_id),
            str(scored.candidate.moment_id),
        )
    )
    return kept, dropped


def to_item(scored: ScoredCandidate, max_thread_reasons: int) -> FeedItem:
    """One surviving candidate as the wire model. Never called for a dropped row."""
    candidate = scored.candidate
    assert candidate.moment_id is not None
    assert candidate.meeting_id is not None
    assert candidate.started_at is not None
    return FeedItem(
        moment_id=candidate.moment_id,
        meeting_id=candidate.meeting_id,
        meeting_title=candidate.meeting_title,
        started_at=candidate.started_at,
        started_at_precision=candidate.started_at_precision,
        start_ms=candidate.start_ms,
        end_ms=candidate.end_ms,
        corpus=candidate.corpus,
        has_recording=candidate.has_recording,
        source_deep_link=candidate.source_deep_link,
        screenshot_id=candidate.screenshot_id,
        view_type=candidate.view_type,  # type: ignore[arg-type]
        preview=candidate.preview,
        threads=[
            FeedThread(
                thread_id=thread.thread_id,
                name=thread.name.strip(),
                color_ordinal=thread.color_ordinal,
            )
            for thread in _card_threads(candidate, max_thread_reasons)
        ],
        reasons=list(scored.reasons),
    )


# --- the read ---------------------------------------------------------------

# The candidate scan. A moment is a candidate when something is stored about
# it — an artifact, a ranking signal, a thread membership — or when its
# meeting is recent enough that the recency reason alone is honest. Anything
# else has nothing to put on a card and is not scanned, which is also what
# keeps this bounded on a corpus of hundreds of meetings.
#
# Superseded moments are excluded here, the same way `GET /meetings/{id}/
# moments` excludes them: the id still resolves as a citation, but a ghost is
# not evidence a front door presents as live.
#
# `thread.color_ordinal` is read as `to_jsonb(t) ->> 'color_ordinal'` rather
# than as a column, and that is deliberate, not a trick: story 10.3 adds the
# column in migration 0017 and is building in parallel: naming the column
# directly would make this query a syntax error until that story lands, and
# duplicating its DDL here would put two definitions of one corpus sequence in
# the tree. `to_jsonb` of the row yields no key when the column does not
# exist, so this serves `null` today and the real ordinal the moment 0017 is
# applied — with no edit here.
_FEED_CANDIDATES = f"""
SELECT
    m.id,
    m.meeting_id,
    mt.title,
    mt.corpus,
    mt.has_recording,
    m.started_at,
    m.started_at_precision,
    m.start_ms,
    m.end_ms,
    mt.started_at,
    m.source_deep_link,
    ss.id,
    ss.view_type,
    first_seg.text,
    COALESCE(arts.rows, '[]'::jsonb),
    COALESCE(sigs.rows, '[]'::jsonb),
    COALESCE(thr.rows, '[]'::jsonb)
FROM moment m
JOIN meeting mt ON mt.id = m.meeting_id
LEFT JOIN screenshot ss
       ON ss.id = m.screenshot_id AND ss.meeting_id = m.meeting_id
LEFT JOIN LATERAL (
    SELECT LEFT(ts.text, {PREVIEW_MAX_CHARS}) AS text
    FROM moment_segment ms
    JOIN transcript_segment ts ON ts.id = ms.transcript_segment_id
    WHERE ms.moment_id = m.id AND ts.meeting_id = m.meeting_id
    ORDER BY ts.ordinal LIMIT 1
) first_seg ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
        'id', a.id, 'kind', a.kind, 'state', a.state, 'title', a.title,
        'body', a.body, 'published_at', a.published_at
    ) ORDER BY a.created_at, a.id) AS rows
    FROM artifact a WHERE a.moment_id = m.id
) arts ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
        'id', rs.id, 'kind', rs.kind, 'label', rs.label,
        'anchor_ms', rs.anchor_ms
    ) ORDER BY rs.anchor_ms, rs.id) AS rows
    FROM ranking_signal rs WHERE rs.moment_id = m.id
) sigs ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(DISTINCT jsonb_build_object(
        'id', t.id, 'name', t.name,
        'color_ordinal', (to_jsonb(t) ->> 'color_ordinal')
    )) AS rows
    FROM topic_mention tm
    JOIN topic_thread tt ON tt.topic_id = tm.topic_id
    JOIN thread t ON t.id = tt.thread_id
    WHERE tm.moment_id = m.id
) thr ON true
WHERE COALESCE(m.provenance->>'superseded', '') <> 'true'
  AND (%(corpus)s::text IS NULL OR mt.corpus = %(corpus)s::text)
  AND (
        EXISTS (SELECT 1 FROM artifact a2 WHERE a2.moment_id = m.id)
     OR EXISTS (SELECT 1 FROM ranking_signal rs2 WHERE rs2.moment_id = m.id)
     OR EXISTS (
            SELECT 1 FROM topic_mention tm3
            JOIN topic_thread tt3 ON tt3.topic_id = tm3.topic_id
            WHERE tm3.moment_id = m.id
        )
     OR mt.started_at >= %(recency_floor)s
  )
"""


def _thread_of(row: dict) -> CandidateThread:
    ordinal = row.get("color_ordinal")
    return CandidateThread(
        thread_id=UUID(row["id"]),
        name=row["name"],
        color_ordinal=int(ordinal) if ordinal is not None else None,
    )


def _candidates(conn, params: dict) -> list[FeedCandidate]:
    rows = conn.execute(_FEED_CANDIDATES, params).fetchall()
    candidates: list[FeedCandidate] = []
    for row in rows:
        candidates.append(
            FeedCandidate(
                moment_id=row[0],
                meeting_id=row[1],
                meeting_title=row[2],
                corpus=row[3],
                has_recording=row[4],
                started_at=row[5],
                started_at_precision=row[6],
                start_ms=row[7],
                end_ms=row[8],
                meeting_started_at=row[9],
                source_deep_link=row[10],
                screenshot_id=row[11],
                view_type=row[12],
                preview=row[13],
                artifacts=tuple(
                    CandidateArtifact(
                        artifact_id=UUID(item["id"]),
                        kind=item["kind"],
                        state=item["state"],
                        title=item["title"] or "",
                        body=item["body"] or "",
                        published_at=(
                            datetime.fromisoformat(item["published_at"])
                            if item.get("published_at")
                            else None
                        ),
                    )
                    for item in row[14]
                ),
                signals=tuple(
                    CandidateSignal(
                        signal_id=UUID(item["id"]),
                        kind=item["kind"],
                        label=item["label"] or "",
                        anchor_ms=int(item["anchor_ms"]),
                    )
                    for item in row[15]
                ),
                threads=tuple(_thread_of(item) for item in row[16]),
            )
        )
    return candidates


_PROBLEM_RESPONSES = {
    422: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`invalid-request` — a filter is not the declared type.",
    },
    500: {
        "model": ProblemDetails,
        "content": {"application/problem+json": {}},
        "description": "`internal-error` — unexpected failure.",
    },
}


@router.get(
    "/moments/feed",
    response_model=MomentsFeedResponse,
    operation_id="getMomentsFeed",
    responses=_PROBLEM_RESPONSES,
    summary="The ranked moments feed — what needs attention first.",
)
def moments_feed(
    request: Request,
    corpus: Annotated[
        Corpus | None, Query(description="Scope the feed to one corpus.")
    ] = None,
    thread: Annotated[
        UUID | None, Query(description="Only moments belonging to this thread.")
    ] = None,
    meeting: Annotated[
        UUID | None, Query(description="Only moments of this meeting.")
    ] = None,
    kind: Annotated[
        str | None,
        Query(
            description=(
                "Keep only items carrying a valid reason of this kind — an"
                " artifact kind or one of due/risk/question/recency/"
                "published/thread. Applied with reason validation, before"
                " pagination."
            )
        ),
    ] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MomentsFeedResponse:
    """Rank stored signals, validate reasons, then page — in that order.

    Pages are ranked at request time against the corpus as it exists then.
    Ordering is not stable across requests: as ranking moves, a candidate may
    repeat or be skipped across an offset boundary. This is a live feed, not a
    stable paging snapshot shared by separate requests.
    """
    ranking: RankingConfig = request.app.state.config.settings.ranking
    # One `now` for the whole request: two calls would let a candidate scored
    # at the top of the loop be compared against a different present than one
    # scored at the bottom, which is a non-deterministic order by another
    # name.
    now = datetime.now(timezone.utc)
    page_size = min(limit or ranking.default_limit, ranking.max_limit)
    # The candidate scan's cheap floor: a meeting older than one half-life
    # cannot earn a recency *reason*, so it is only a candidate if something
    # is stored about it. Scoring still uses the full decay.
    recency_floor = now - timedelta(days=ranking.recency_half_life_days)

    with request.app.state.pool.connection() as conn:
        candidates = _candidates(
            conn,
            {
                "corpus": corpus,
                "recency_floor": recency_floor,
            },
        )

    # Validate the selected corpus once, before every item filter. The same
    # survivor set supplies both counts, so corpusTotal and total cannot see
    # different database snapshots inside one request.
    corpus_kept, dropped = rank_and_validate(candidates, ranking, now)
    corpus_total = len(corpus_kept)
    for drop in dropped:
        # Named, never merely counted: a moment silently missing from the
        # front door is the failure this log line exists to make visible.
        logs.log_event(
            "moments.feed.item_dropped",
            moment_id=str(drop.moment_id) if drop.moment_id else None,
            reason=drop.reason,
            detail=drop.detail,
        )
    kept = [
        scored
        for scored in corpus_kept
        if (meeting is None or scored.candidate.meeting_id == meeting)
        and (
            thread is None
            or any(
                membership.thread_id == thread
                for membership in scored.candidate.threads
            )
        )
    ]
    if kind is not None:
        # Applied here — after validation, before the slice — so a filtered
        # `total` counts exactly the rows a caller can page through.
        kept = [
            scored
            for scored in kept
            if any(reason.kind == kind for reason in scored.reasons)
        ]

    total = len(kept)
    effective_offset = min(offset, total)
    page = kept[effective_offset : effective_offset + page_size]
    logs.log_event(
        "moments.feed.served",
        total=total,
        corpus_total=corpus_total,
        returned=len(page),
        dropped=len(dropped),
        limit=page_size,
        offset=effective_offset,
        corpus=corpus,
        kind=kind,
    )
    return MomentsFeedResponse(
        items=[to_item(scored, ranking.max_thread_reasons) for scored in page],
        total=total,
        corpus_total=corpus_total,
        limit=page_size,
        offset=effective_offset,
    )
