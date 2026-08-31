"""The rules behind tracing a subject, tested without a database (story 10.7).

`domain/thread_trace.py` exists so these three judgements are unit tests rather
than properties of a SQL string or of prose written at a call site. Each of them
is wrong in a way that is invisible from the outside: a suggestion list ranked
by the wrong key still looks like a suggestion list, and a completeness note
that says "every mention" about a capped result still reads as a sentence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from meetingminer.domain.thread_trace import (
    PER_MEETING_DEFAULT,
    SUGGESTION_MAX_MEETINGS,
    SUGGESTION_MIN_MEETINGS,
    completeness_note,
    drop_near_duplicates,
    duplicate_key,
    span_days,
)

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


# --- span ------------------------------------------------------------------


def test_span_days_counts_whole_days() -> None:
    assert span_days(NOW - timedelta(days=118), NOW) == 118


def test_span_days_of_one_instant_is_zero() -> None:
    assert span_days(NOW, NOW) == 0


def test_span_days_never_goes_negative() -> None:
    """A reversed pair is a caller bug, not a subject that ran backwards."""
    assert span_days(NOW, NOW - timedelta(days=5)) == 0


# --- near-duplicate dropping ----------------------------------------------


def test_duplicate_key_collapses_case_punctuation_and_a_plural() -> None:
    assert duplicate_key("Scorecard") == duplicate_key("Scorecards")
    assert duplicate_key("SFTP Migration") == duplicate_key("sftp  migration.")


def test_plural_twins_do_not_take_two_slots() -> None:
    kept = drop_near_duplicates(["Scorecard", "Scorecards", "Trail closure"], limit=6)
    assert [0, 2] == kept


def test_a_name_that_merely_extends_a_kept_one_is_dropped() -> None:
    """The containment test, which the key test alone lets through.

    "Lead" and "Division Lead" normalize differently, so nothing but
    containment catches that the second would send a reader to the same trace.
    """
    kept = drop_near_duplicates(["Lead", "Division Lead", "Budget"], limit=6)
    assert [0, 2] == kept


def test_dropping_preserves_the_ranking_order_it_was_given() -> None:
    """The sort is the caller's; this function only removes."""
    names = ["Cedar Lake Trail closure", "Budget", "Scorecard", "Scorecards"]
    assert [0, 1, 2] == drop_near_duplicates(names, limit=6)


def test_limit_bounds_what_is_kept() -> None:
    assert 2 == len(drop_near_duplicates(["one", "two", "three", "four"], limit=2))


def test_a_name_with_no_alphanumerics_is_not_offered() -> None:
    """Its key is empty, and an empty key would swallow every later name."""
    assert [1] == drop_near_duplicates(["—", "Budget"], limit=6)


# --- the completeness sentence --------------------------------------------


def test_an_exhaustive_uncapped_trace_says_every_mention() -> None:
    note = completeness_note(
        mode="exhaustive",
        stops=9,
        moments_quoted=31,
        mention_total=31,
        meetings_mentioning=9,
        per_meeting=PER_MEETING_DEFAULT,
    )
    assert "Every mention this corpus holds" in note
    assert "31" in note and "9 meetings" in note


def test_a_capped_trace_names_both_figures_and_never_claims_every() -> None:
    """The cap is per meeting, so the sentence must say the stops all survived.

    A note that reported only the quoted figure would read as though 54
    moments were all there were.
    """
    note = completeness_note(
        mode="exhaustive",
        stops=9,
        moments_quoted=54,
        mention_total=311,
        meetings_mentioning=9,
        per_meeting=6,
    )
    assert "54 of 311" in note
    assert "at most 6 per meeting" in note
    assert "all 9 meetings" in note
    assert "every" not in note.lower()


def test_a_sample_never_reads_as_a_full_history() -> None:
    note = completeness_note(
        mode="sample",
        stops=12,
        moments_quoted=40,
        mention_total=40,
        meetings_mentioning=12,
        per_meeting=6,
        ranking="hybrid",
    )
    assert "sample, not every mention" in note
    assert "hybrid" in note
    assert "Every mention" not in note


def test_a_sample_that_matched_nothing_offers_nothing() -> None:
    note = completeness_note(
        mode="sample",
        stops=0,
        moments_quoted=0,
        mention_total=0,
        meetings_mentioning=0,
        per_meeting=6,
    )
    assert "Nothing in the corpus matches this wording" in note
    assert "nearest guess" in note


def test_the_sample_note_states_its_ranking_when_it_degraded() -> None:
    """Keyword-only is a good answer, and one the reader is told about."""
    note = completeness_note(
        mode="sample",
        stops=3,
        moments_quoted=8,
        mention_total=8,
        meetings_mentioning=3,
        per_meeting=6,
        ranking="keyword",
    )
    assert "keyword ranking" in note


def test_the_band_excludes_one_meeting_rows_and_the_generic_ones() -> None:
    """The two bounds are what make a suggestion a subject rather than noise."""
    assert SUGGESTION_MIN_MEETINGS >= 2
    assert SUGGESTION_MAX_MEETINGS > SUGGESTION_MIN_MEETINGS
