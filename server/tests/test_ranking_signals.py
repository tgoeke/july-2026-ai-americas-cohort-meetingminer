"""The ranking decision core and the ranking-signals parser (story 10.4).

Two halves, both store-free and both fast:

* the ranking-signals document parser and the stage vocabulary it feeds —
  proving a risk and an open question are told apart by their item ID, that a
  blank label is refused rather than persisted, and that neither kind is ever
  an artifact kind;
* the pure ranker — `score_candidate`, `validate_reasons` and
  `rank_and_validate` — over plain dataclasses, with **no database**, which is
  the AC's "unit-testable as a pure function over plain facts".

The clause these tests exist to hold down is the ordering one: reason
validation happens BEFORE pagination, so `total` counts survivors only. It is
asserted directly, on `rank_and_validate`, rather than inferred from a page.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import yaml

from meetingminer.api.moments_feed import (
    REASON_KINDS,
    CandidateArtifact,
    CandidateSignal,
    CandidateThread,
    FeedCandidate,
    FeedReason,
    due_urgency,
    rank_and_validate,
    recency_factor,
    score_candidate,
    stated_due_date,
    stated_timing,
    validate_reasons,
)
from meetingminer.config import Settings
from meetingminer.pipeline import extraction as core
from repo_paths import REPO_ROOT

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def ranking():
    """The shipped `ranking:` block, read from the tracked config.yaml.

    Read rather than hand-built on purpose: every weight the score depends on
    is required to live in that file with its rationale, and a fixture that
    invented its own numbers would let the shipped ones drift to nonsense
    while these tests stayed green.
    """
    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    return Settings.model_validate(raw).ranking


# --- the ranking-signals document -------------------------------------------

SIGNALS_DOC = """
## Risks

| ID | Risk | Detail | Timestamp |
|----|------|--------|-----------|
| R1 | The vendor key may not arrive before the cutover | Blocks the SFTP move | [0:05] |
| R2 | Nobody owns the rollback | | [0:09] |

## Open questions

| ID | Question | Detail | Timestamp |
|----|----------|--------|-----------|
| Q1 | Who approves the purchase order? | Nobody claimed it | [0:44] |
"""


def test_the_signals_document_parses_risks_and_questions_by_item_id() -> None:
    parsed = core.parse_extraction_document(SIGNALS_DOC, core.DOC_RANKING_SIGNALS)

    assert [item.kind for item in parsed.artifacts] == ["risk", "risk", "question"]
    assert [item.item_id for item in parsed.artifacts] == ["R1", "R2", "Q1"]
    assert parsed.artifacts[0].title == (
        "The vendor key may not arrive before the cutover"
    )
    assert core.signal_detail(parsed.artifacts[0]) == "Blocks the SFTP move"
    # An absent detail is stored as the empty string, never as the
    # artifact-only "no detail" sentence.
    assert core.signal_detail(parsed.artifacts[1]) == ""
    assert parsed.artifacts[2].anchor_ms == 44_000


def test_a_commitment_that_strays_into_the_signals_document_is_not_a_signal() -> None:
    """An `A`-prefixed row is an action item: structure here, never a signal."""
    document = SIGNALS_DOC + (
        "| A9 | Send the vendor the file | a commitment, not a signal | [0:12] |\n"
    )

    parsed = core.parse_extraction_document(document, core.DOC_RANKING_SIGNALS)

    assert [item.item_id for item in parsed.artifacts] == ["R1", "R2", "Q1"]
    assert all(item.kind in core.RANKING_SIGNAL_KINDS for item in parsed.artifacts)


def test_a_signal_with_no_text_beyond_bookkeeping_is_refused() -> None:
    document = """
## Risks

| ID | Risk | Detail | Timestamp |
|----|------|--------|-----------|
| R1 |  |  | [0:05] |
"""
    with pytest.raises(core.ArtifactParseError) as raised:
        core.parse_extraction_document(document, core.DOC_RANKING_SIGNALS)

    assert "R1" in str(raised.value)


def test_ranking_signal_kinds_are_not_artifact_kinds() -> None:
    """The record's whole point: these rows never enter the publish lifecycle."""
    assert core.RANKING_SIGNAL_KINDS == {"risk", "question"}
    assert not core.RANKING_SIGNAL_KINDS & core.KNOWN_KINDS
    assert core.DOC_RANKING_SIGNALS not in core.DOCUMENT_KINDS
    assert core.DOC_RANKING_SIGNALS in core._PARSEABLE_DOCUMENT_KINDS


def test_the_migration_declares_no_lifecycle_column() -> None:
    """A `state` column would be an approval path story 10.4 must not have."""
    sql = (
        REPO_ROOT
        / "server/meetingminer/migrations/0018_ranking_signals.sql"
    ).read_text()
    body = sql.split("CREATE TABLE ranking_signal", 1)[1].split(");", 1)[0]
    # Declarations only: the prose above each column legitimately says
    # "stated", and this assertion is about the schema, not the commentary.
    columns = [
        line.split()[0]
        for line in (raw.strip() for raw in body.splitlines())
        if line and not line.startswith("--") and not line.startswith(("FOREIGN", "("))
    ]

    assert "state" not in columns
    assert "'risk', 'question'" in body
    assert "ON DELETE CASCADE" in body


# --- stated timing ----------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        ("Timing (as stated): this week", "this week"),
        ("Owner: Ellis\nTiming (as stated): 2026-09-04", "2026-09-04"),
        ("Due date: 9/4/2026", "9/4/2026"),
        ("Timing (as stated): not stated", None),
        ("Timing (as stated): TBD", None),
        ("Timing (as stated):", None),
        ("Details and dependency: needs the vendor key first", None),
        ("", None),
    ],
)
def test_stated_timing_reads_the_labelled_line_only(body, expected) -> None:
    assert stated_timing(body) == expected


def test_a_date_inside_a_dependency_sentence_is_not_the_items_timing() -> None:
    """Prose is not a due date. Only the labelled timing line is read."""
    body = "Details and dependency: the vendor promised 2026-09-01 for the key"

    assert stated_timing(body) is None


@pytest.mark.parametrize(
    "timing,expected",
    [
        ("2026-09-04", (2026, 9, 4)),
        ("by 9/4/2026 at the latest", (2026, 9, 4)),
        ("this week", None),
        ("after the demo", None),
        ("2026-13-45", None),
    ],
)
def test_stated_due_date_reads_calendar_spellings_only(timing, expected) -> None:
    result = stated_due_date(timing)
    assert (result.timetuple()[:3] if result else None) == expected


def test_due_urgency_is_full_when_overdue_and_zero_at_the_horizon() -> None:
    today = NOW.date()
    assert due_urgency(today, NOW, 14.0) == 1.0
    assert due_urgency(today - timedelta(days=90), NOW, 14.0) == 1.0
    assert due_urgency(today + timedelta(days=14), NOW, 14.0) == 0.0
    assert due_urgency(today + timedelta(days=40), NOW, 14.0) == 0.0
    # Soonest first: a nearer date is always strictly more urgent.
    assert due_urgency(today + timedelta(days=2), NOW, 14.0) > due_urgency(
        today + timedelta(days=9), NOW, 14.0
    )


def test_recency_halves_at_one_half_life_and_never_exceeds_one() -> None:
    assert recency_factor(NOW, NOW, 14.0) == 1.0
    assert recency_factor(NOW - timedelta(days=14), NOW, 14.0) == pytest.approx(0.5)
    assert recency_factor(NOW - timedelta(days=28), NOW, 14.0) == pytest.approx(0.25)
    # A future timestamp is a clock, not a ranking: it clamps rather than
    # letting a wrong row outrank the present.
    assert recency_factor(NOW + timedelta(days=5), NOW, 14.0) == 1.0


# --- candidates -------------------------------------------------------------


def candidate(**overrides) -> FeedCandidate:
    """One candidate with every required plain fact filled in."""
    base = {
        "moment_id": uuid4(),
        "meeting_id": uuid4(),
        "meeting_title": "Data Hub Demo",
        "corpus": "real",
        "has_recording": True,
        "started_at": NOW - timedelta(days=60),
        "started_at_precision": "second",
        "start_ms": 2_000,
        "end_ms": 40_000,
        "meeting_started_at": NOW - timedelta(days=60),
    }
    base.update(overrides)
    return FeedCandidate(**base)  # type: ignore[arg-type]


def artifact(**overrides) -> CandidateArtifact:
    base = {
        "artifact_id": uuid4(),
        "kind": "adr",
        "state": "extracted",
        "title": "Move the feed to SFTP",
        "body": "",
        "published_at": None,
    }
    base.update(overrides)
    return CandidateArtifact(**base)  # type: ignore[arg-type]


def signal(**overrides) -> CandidateSignal:
    base = {
        "signal_id": uuid4(),
        "kind": "risk",
        "label": "The vendor key may not arrive",
        "anchor_ms": 5_000,
    }
    base.update(overrides)
    return CandidateSignal(**base)  # type: ignore[arg-type]


# --- the score --------------------------------------------------------------


def test_every_ac_signal_produces_its_own_reason_kind(ranking) -> None:
    """One candidate carrying all six signal shapes yields all six kinds."""
    row = candidate(
        meeting_started_at=NOW - timedelta(days=1),
        artifacts=(
            artifact(kind="adr", title="Adopt SFTP"),
            artifact(kind="decision", title="Ship on Friday"),
            artifact(
                kind="action-item",
                title="Set up the credentials",
                body="Timing (as stated): 2026-09-02",
            ),
            artifact(
                kind="adr",
                title="Published record",
                state="published",
                published_at=NOW - timedelta(days=2),
            ),
        ),
        signals=(
            signal(kind="risk", label="The vendor key may not arrive"),
            signal(kind="question", label="Who approves the PO?", anchor_ms=44_000),
        ),
        threads=(CandidateThread(thread_id=uuid4(), name="data hub"),),
    )

    score, reasons = score_candidate(row, ranking, NOW)

    assert {reason.kind for reason in reasons} == {
        "adr", "decision", "action-item", "due", "risk", "question", "recency",
        "published", "thread",
    }
    assert all(reason.kind in REASON_KINDS for reason in reasons)
    assert score > 0
    # Ordered by individual contribution: splitting the categorical action
    # term from urgency leaves the ADR as the largest single explanation.
    assert reasons[0].kind == "adr"


def test_the_score_is_deterministic_over_the_same_facts(ranking) -> None:
    row = candidate(
        artifacts=(artifact(kind="adr", title="Adopt SFTP"),),
        signals=(signal(), signal(kind="question", label="Who?", anchor_ms=9_000)),
    )

    first = score_candidate(row, ranking, NOW)
    second = score_candidate(row, ranking, NOW)

    assert first == second


def test_an_adr_outranks_a_decision_which_outranks_a_question(ranking) -> None:
    """The relative order of the config's weights, asserted as behaviour."""
    old = NOW - timedelta(days=365)

    def score_of(**kwargs) -> float:
        return score_candidate(
            candidate(meeting_started_at=old, started_at=old, **kwargs), ranking, NOW
        )[0]

    adr = score_of(artifacts=(artifact(kind="adr", title="A"),))
    decision = score_of(artifacts=(artifact(kind="decision", title="A"),))
    risk = score_of(signals=(signal(kind="risk", label="A"),))
    question = score_of(signals=(signal(kind="question", label="A"),))
    thread = score_of(threads=(CandidateThread(thread_id=uuid4(), name="t"),))

    assert adr > decision > risk > question > thread > 0


def test_a_sooner_action_item_outranks_a_later_one(ranking) -> None:
    """"Soonest first" — the AC's parenthesis, as an ordering assertion."""
    old = NOW - timedelta(days=365)

    def score_of(timing: str) -> float:
        return score_candidate(
            candidate(
                meeting_started_at=old,
                started_at=old,
                artifacts=(
                    artifact(
                        kind="action-item",
                        title="Set up the credentials",
                        body=f"Timing (as stated): {timing}",
                    ),
                ),
            ),
            ranking,
            NOW,
        )[0]

    tomorrow = (NOW + timedelta(days=1)).date().isoformat()
    next_week = (NOW + timedelta(days=7)).date().isoformat()
    far = (NOW + timedelta(days=60)).date().isoformat()

    assert score_of(tomorrow) > score_of(next_week) > score_of(far)
    # A vague but stated timing earns the stated-timing weight and no urgency,
    # so it ties with a date past the horizon rather than being ranked on an
    # invented calendar day.
    assert score_of("some time after the demo") == score_of(far)
    # An action item whose timing nobody stated earns nothing beyond the
    # always-decaying meeting-recency term.
    baseline = score_candidate(
        candidate(meeting_started_at=old, started_at=old), ranking, NOW
    )[0]
    assert score_of("not stated") == baseline


def test_multiple_timed_actions_earn_each_weight_once(ranking) -> None:
    """F2: a talkative moment must not multiply a categorical contribution."""
    old = NOW - timedelta(days=365)
    soon = (NOW + timedelta(days=1)).date().isoformat()
    one = candidate(
        meeting_started_at=old,
        artifacts=(
            artifact(kind="action-item", title="First", body=f"Timing: {soon}"),
        ),
    )
    two = candidate(
        meeting_started_at=old,
        artifacts=(
            artifact(kind="action-item", title="First", body=f"Timing: {soon}"),
            artifact(kind="action-item", title="Second", body=f"Timing: {soon}"),
        ),
    )

    one_score, one_reasons = score_candidate(one, ranking, NOW)
    two_score, two_reasons = score_candidate(two, ranking, NOW)

    assert two_score == one_score
    assert [reason.kind for reason in one_reasons] == ["due", "action-item"]
    assert [reason.kind for reason in two_reasons] == ["due", "action-item"]


def test_repeated_signals_do_not_multiply_the_score(ranking) -> None:
    """A talkative meeting must not be able to hold the whole front door."""
    old = NOW - timedelta(days=365)
    one = candidate(
        meeting_started_at=old, started_at=old, signals=(signal(label="a"),)
    )
    nine = candidate(
        meeting_started_at=old,
        started_at=old,
        signals=tuple(
            signal(label=f"risk {index}", anchor_ms=index * 1_000)
            for index in range(9)
        ),
    )

    one_score, one_reasons = score_candidate(one, ranking, NOW)
    nine_score, nine_reasons = score_candidate(nine, ranking, NOW)

    assert nine_score == one_score
    assert len(one_reasons) == 1
    # The reasons are capped by `max_signal_reasons`, so the card stays a card.
    assert len(nine_reasons) == ranking.max_signal_reasons


def test_a_recency_reason_is_only_claimed_while_it_is_true(ranking) -> None:
    fresh = candidate(meeting_started_at=NOW - timedelta(days=3))
    stale = candidate(meeting_started_at=NOW - timedelta(days=90))

    fresh_kinds = {r.kind for r in score_candidate(fresh, ranking, NOW)[1]}
    stale_kinds = {r.kind for r in score_candidate(stale, ranking, NOW)[1]}

    assert "recency" in fresh_kinds
    assert "recency" not in stale_kinds


def test_recency_terms_keep_decaying_after_the_reason_window(ranking) -> None:
    """F1: hiding a stale label must not turn exponential decay into a cliff."""
    old = NOW - timedelta(days=28)
    older = NOW - timedelta(days=56)

    old_score, old_reasons = score_candidate(
        candidate(meeting_started_at=old), ranking, NOW
    )
    older_score, older_reasons = score_candidate(
        candidate(meeting_started_at=older), ranking, NOW
    )

    assert old_score == pytest.approx(ranking.weights.meeting_recency * 0.25)
    assert old_score > older_score > 0
    assert "recency" not in {reason.kind for reason in old_reasons + older_reasons}

    published = artifact(
        kind="adr", title="Published record", state="published", published_at=old
    )
    publication_score, publication_reasons = score_candidate(
        candidate(meeting_started_at=older, artifacts=(published,)), ranking, NOW
    )
    assert publication_score == pytest.approx(
        ranking.weights.adr
        + ranking.weights.meeting_recency * 0.0625
        + ranking.weights.publication_recency * 0.25
    )
    assert "published" not in {reason.kind for reason in publication_reasons}


def test_a_titleless_artifact_contributes_no_reason(ranking) -> None:
    """A reason with no label is one a card cannot render."""
    old = NOW - timedelta(days=365)
    row = candidate(
        meeting_started_at=old,
        started_at=old,
        artifacts=(artifact(kind="adr", title="   "),),
    )

    score, reasons = score_candidate(row, ranking, NOW)

    assert reasons == ()
    assert score == 0.0


# --- validation before pagination -------------------------------------------


def test_validate_reasons_discards_unknown_kinds_and_blank_labels() -> None:
    reasons = [
        FeedReason.model_construct(kind="risk", label="a real one"),
        FeedReason.model_construct(kind="risk", label="   "),
        FeedReason.model_construct(kind="astrology", label="not a kind"),
    ]

    assert [r.label for r in validate_reasons(reasons)] == ["a real one"]


def test_totals_are_computed_from_survivors_not_from_the_scan(ranking) -> None:
    """The clause: validation happens BEFORE pagination.

    Three candidates go in, one of which can produce no valid reason. The
    ranker must hand back two survivors and one named drop — so a caller
    computing `total` from its output can never report a row it will not
    serve.
    """
    old = NOW - timedelta(days=365)
    good_one = candidate(
        meeting_started_at=old, started_at=old,
        artifacts=(artifact(kind="adr", title="Adopt SFTP"),),
    )
    good_two = candidate(
        meeting_started_at=old, started_at=old, signals=(signal(label="a risk"),)
    )
    reasonless = candidate(
        meeting_started_at=old, started_at=old,
        artifacts=(artifact(kind="adr", title=""),),
    )

    kept, dropped = rank_and_validate([good_one, reasonless, good_two], ranking, NOW)

    assert len(kept) == 2
    assert len(dropped) == 1
    assert dropped[0].moment_id == reasonless.moment_id
    assert dropped[0].reason == "no-valid-reason"
    assert all(scored.reasons for scored in kept)


def test_a_candidate_whose_moment_does_not_resolve_is_dropped_and_named(
    ranking,
) -> None:
    """"An item whose moment no longer resolves is dropped and logged."""
    ghost = candidate(moment_id=None, started_at=None)

    kept, dropped = rank_and_validate([ghost], ranking, NOW)

    assert kept == []
    assert [drop.reason for drop in dropped] == ["unresolved-moment"]


def test_ranking_order_is_score_then_meeting_then_moment(ranking) -> None:
    """Ties break deterministically, so an unchanged corpus never reshuffles."""
    old = NOW - timedelta(days=365)
    meeting_a = UUID("00000000-0000-4000-8000-00000000000a")
    meeting_b = UUID("00000000-0000-4000-8000-00000000000b")
    moment_one = UUID("00000000-0000-4000-8000-000000000001")
    moment_two = UUID("00000000-0000-4000-8000-000000000002")

    rows = [
        candidate(
            moment_id=moment_two, meeting_id=meeting_b, meeting_started_at=old,
            started_at=old, signals=(signal(label="tie"),),
        ),
        candidate(
            moment_id=moment_one, meeting_id=meeting_a, meeting_started_at=old,
            started_at=old, signals=(signal(label="tie"),),
        ),
        candidate(
            moment_id=moment_one, meeting_id=meeting_a, meeting_started_at=old,
            started_at=old, artifacts=(artifact(kind="adr", title="wins"),),
        ),
    ]

    kept, _ = rank_and_validate(rows, ranking, NOW)

    assert [scored.reasons[0].kind for scored in kept] == ["adr", "risk", "risk"]
    assert kept[1].candidate.meeting_id == meeting_a
    assert kept[2].candidate.meeting_id == meeting_b


def test_ranking_is_stable_across_repeated_runs(ranking) -> None:
    old = NOW - timedelta(days=365)
    rows = [
        candidate(
            meeting_started_at=old, started_at=old,
            signals=(signal(label=f"risk {index}"),),
        )
        for index in range(8)
    ]

    first = [scored.candidate.moment_id for scored in rank_and_validate(rows, ranking, NOW)[0]]
    second = [scored.candidate.moment_id for scored in rank_and_validate(rows, ranking, NOW)[0]]

    assert first == second
