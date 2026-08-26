"""The AD-6 citation gate, exercised in isolation (story 3.3).

Store-free and model-free by construction: `api/citations.py` imports the
standard library and nothing else, so every rejection path in the story's
I/O matrix is reachable here without Postgres, without Meilisearch, and without
a completer. That is the point of the module boundary — the property "an uncited
answer cannot leave the API" is decided by pure code, so it can be proved by
pure tests.

`resolve` is a dict lookup here. What it stands for — a Postgres read in the
same request — is proved end to end in `test_api_chat.py`; what matters at this
level is that the gate calls it with exactly the cited ids and refuses when it
answers short.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence
from uuid import UUID, uuid4

import pytest

from meetingminer.api.citations import (
    MARKER_PATTERN,
    REJECTION_REASONS,
    MomentCitation,
    Rejection,
    ValidatedAnswer,
    parse_markers,
    split_claims,
    strip_markers,
    validate,
)

A = UUID("018f3f2a-0000-7000-8000-00000000000a")
B = UUID("018f3f2a-0000-7000-8000-00000000000b")
C = UUID("018f3f2a-0000-7000-8000-00000000000c")


def citation(moment_id: UUID, **overrides: object) -> MomentCitation:
    fields: dict[str, object] = {
        "moment_id": moment_id,
        "meeting_id": UUID("018f3f2a-0000-7000-8000-0000000000ff"),
        "start_ms": 2_000,
        "end_ms": 9_000,
        "screenshot_id": None,
        "source_deep_link": None,
    }
    fields.update(overrides)
    return MomentCitation(**fields)  # type: ignore[arg-type]


def resolver(*ids: UUID):
    """A `resolve` that holds exactly ``ids``, recording what it was asked for."""
    rows = {moment_id: citation(moment_id) for moment_id in ids}
    asked: list[tuple[UUID, ...]] = []

    def resolve(requested: Sequence[UUID]) -> Mapping[UUID, MomentCitation]:
        asked.append(tuple(requested))
        return {key: value for key, value in rows.items() if key in set(requested)}

    resolve.asked = asked  # type: ignore[attr-defined]
    return resolve


def marker(moment_id: UUID) -> str:
    return f"[[moment:{moment_id}]]"


# --- marker parsing -------------------------------------------------------


def test_markers_are_found_in_order_with_duplicates_kept() -> None:
    text = f"One {marker(A)}. Two {marker(B)}. Three {marker(A)}."
    assert parse_markers(text) == (str(A), str(B), str(A))


def test_a_marker_adjacent_to_punctuation_is_still_a_marker() -> None:
    """A model that writes the marker tight against the period, or inside the
    parentheses, has still cited — the gate must not be defeated by spacing."""
    assert parse_markers(f"The feed moved{marker(A)}.") == (str(A),)
    assert parse_markers(f"(see {marker(A)}), and so on.") == (str(A),)


def test_a_malformed_payload_is_recognized_as_an_attempted_citation() -> None:
    """`[[moment:not-a-uuid]]` is a marker, not prose.

    The distinction matters: read as prose the sentence would be reported as
    `uncited-claim`, which tells an operator the model forgot to cite. Read as a
    marker it is `unresolvable-marker`, which tells them the model cited
    something that does not exist. Those are different bugs.
    """
    assert parse_markers("The feed moved [[moment:not-a-uuid]].") == ("not-a-uuid",)


def test_an_uppercase_uuid_is_the_same_citation() -> None:
    text = f"The feed moved [[moment:{str(A).upper()}]]."
    outcome = validate(text, [A], resolver(A))
    assert isinstance(outcome, ValidatedAnswer)
    assert [row.moment_id for row in outcome.citations] == [A]


def test_prose_that_merely_mentions_the_syntax_is_not_a_marker() -> None:
    assert parse_markers("We discussed the [[moment]] convention.") == ()
    assert MARKER_PATTERN.search("[[ moment:x ]]") is None


# --- stripping ------------------------------------------------------------


def test_stripping_leaves_no_trace_of_where_a_marker_stood() -> None:
    text = f"The feed moved {marker(A)}. The PO needs approval. {marker(B)}"
    assert strip_markers(text) == "The feed moved. The PO needs approval."


def test_stripping_touches_only_the_gap_the_marker_left() -> None:
    """Interior spacing the model wrote on purpose is the model's, not noise.

    The gap a removed marker leaves is closed; two spaces after a colon, or a
    hand-aligned column, are left exactly as written."""
    text = f"Column A  holds  the total {marker(A)}.  Column B does not {marker(B)}."
    assert strip_markers(text) == "Column A  holds  the total.  Column B does not."


def test_a_marker_between_two_words_leaves_exactly_one_space() -> None:
    assert strip_markers(f"The feed {marker(A)} moved to SFTP.") == (
        "The feed moved to SFTP."
    )


def test_a_marker_opening_a_line_leaves_no_indent_behind() -> None:
    assert strip_markers(f"{marker(A)} The feed moved.") == "The feed moved."


def test_a_draft_cannot_forge_the_internal_marker_slot() -> None:
    """The substitution uses a private-use code point; one arriving in the
    draft is dropped rather than treated as a marker that was removed."""
    assert strip_markers(f"The \ue000feed moved {marker(A)}.") == "The feed moved."


def test_stripping_preserves_the_answers_own_line_structure() -> None:
    text = f"- SFTP {marker(A)}\n- Approval {marker(B)}\n"
    assert strip_markers(text) == "- SFTP\n- Approval"


# --- claim splitting ------------------------------------------------------


def test_a_marker_after_the_period_belongs_to_the_sentence_that_ended() -> None:
    """The pull-back rule. Without it, "Sentence. [[m]]" would report the first
    sentence as uncited and the second as citing a claim it does not make."""
    units = split_claims(f"The feed moved. {marker(A)} The PO needs approval. {marker(B)}")
    assert [unit.markers for unit in units] == [(str(A),), (str(B),)]
    assert units[0].prose.strip() == "The feed moved."


def test_a_marker_before_the_period_belongs_to_its_own_sentence_too() -> None:
    units = split_claims(f"The feed moved {marker(A)}. The PO needs approval {marker(B)}.")
    assert [unit.markers for unit in units] == [(str(A),), (str(B),)]


def test_each_line_of_a_list_is_its_own_unit() -> None:
    units = split_claims(f"- SFTP {marker(A)}\n- Approval {marker(B)}\n")
    assert len(units) == 2
    assert [unit.markers for unit in units] == [(str(A),), (str(B),)]


def test_a_terminator_inside_a_malformed_payload_does_not_split_a_unit() -> None:
    units = split_claims("The feed moved [[moment:a.b]].")
    assert len(units) == 1
    assert units[0].markers == ("a.b",)


def test_a_unit_with_no_alphanumeric_content_is_not_held_to_the_rule() -> None:
    units = split_claims(f"The feed moved {marker(A)}.\n---\n")
    assert [unit.is_claim for unit in units] == [True, False]


# --- the gate: the happy path ---------------------------------------------


def test_a_fully_cited_answer_passes_with_citations_in_first_appearance_order() -> None:
    draft = (
        f"The feed moved to SFTP {marker(B)}."
        f" The purchase order still needs approval {marker(A)}."
        f" Both came up in the same meeting {marker(B)}."
    )
    resolve = resolver(A, B)
    outcome = validate(draft, [A, B, C], resolve)
    assert isinstance(outcome, ValidatedAnswer)
    # First appearance, deduplicated — B was cited twice and appears once.
    assert [row.moment_id for row in outcome.citations] == [B, A]
    assert resolve.asked == [(B, A)]  # type: ignore[attr-defined]
    # The answer on the wire carries no marker: the array is the contract.
    assert "[[moment:" not in outcome.answer
    assert outcome.answer.startswith("The feed moved to SFTP.")


def test_every_citation_field_comes_from_the_resolver_not_the_draft() -> None:
    """AD-6: the model's text names *which* moment, never what it contains."""
    row = citation(A, start_ms=41_000, end_ms=46_000, source_deep_link="https://x")

    def resolve(requested: Sequence[UUID]) -> Mapping[UUID, MomentCitation]:
        return {A: row}

    outcome = validate(f"The feed moved {marker(A)}.", [A], resolve)
    assert isinstance(outcome, ValidatedAnswer)
    assert outcome.citations == (row,)


# --- the gate: every rejection row of the matrix ---------------------------


def test_a_marker_naming_a_moment_nobody_retrieved_is_rejected_whole() -> None:
    """The poisoned-marker row: a real-looking uuid the retrieval never produced."""
    stranger = uuid4()
    outcome = validate(
        f"The feed moved {marker(A)}. And so did the ledger {marker(stranger)}.",
        [A],
        resolver(A, stranger),
    )
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "unresolvable-marker"
    assert str(stranger) in outcome.detail


def test_a_marker_whose_payload_is_not_a_uuid_is_rejected() -> None:
    outcome = validate("The feed moved [[moment:not-a-uuid]].", [A], resolver(A))
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "unresolvable-marker"


def test_a_nested_malformed_marker_is_rejected_without_leaking_syntax() -> None:
    outcome = validate(
        f"The feed moved [[moment:not-a-uuid [[moment:{A}]]",
        [A],
        resolver(A),
    )
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "unresolvable-marker"


@pytest.mark.parametrize("separator", ["\r", "\r\n", "\u2028", "\u2029"])
def test_every_line_separator_starts_a_new_claim_unit(separator: str) -> None:
    outcome = validate(
        f"The feed moved without a citation{separator}The PO was approved {marker(A)}.",
        [A],
        resolver(A),
    )
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "uncited-claim"


def test_a_retrieved_moment_whose_row_has_gone_is_rejected() -> None:
    """The deleted-moment row: retrieved, cited, and no longer in Postgres."""
    outcome = validate(f"The feed moved {marker(A)}.", [A], resolver())
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "unresolvable-marker"
    assert str(A) in outcome.detail


def test_one_uncited_sentence_rejects_the_whole_answer() -> None:
    outcome = validate(
        f"The feed moved to SFTP {marker(A)}. The purchase order was approved.",
        [A],
        resolver(A),
    )
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "uncited-claim"
    assert "purchase order was approved" in outcome.detail


def test_an_uncited_connective_sentence_is_rejected_too() -> None:
    """Deliberately blunt (Design Notes): a claim classifier would put a model
    back inside the gate, which is what AD-6 forbids."""
    outcome = validate(
        f"Here is what the corpus shows. The feed moved {marker(A)}.", [A], resolver(A)
    )
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "uncited-claim"


def test_plain_prose_with_no_markers_at_all_is_no_citations() -> None:
    outcome = validate(
        "The feed moved to SFTP last week and the PO still needs approval.",
        [A, B],
        resolver(A, B),
    )
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "no-citations"


def test_markers_with_no_prose_are_an_empty_answer() -> None:
    outcome = validate(f"{marker(A)} {marker(B)}", [A, B], resolver(A, B))
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "empty-answer"


@pytest.mark.parametrize("draft", ["", "   ", "\n\n", "...", "—"])
def test_a_draft_with_nothing_to_cite_is_an_empty_answer(draft: str) -> None:
    outcome = validate(draft, [A], resolver(A))
    assert isinstance(outcome, Rejection)
    assert outcome.reason == "empty-answer"


def test_no_postgres_read_happens_when_a_marker_already_failed() -> None:
    """Ordering, made falsifiable: a draft citing a stranger is refused before
    the resolver is called, so a rejected answer costs no database read."""
    resolve = resolver(A)
    outcome = validate(f"The ledger moved {marker(uuid4())}.", [A], resolve)
    assert isinstance(outcome, Rejection)
    assert resolve.asked == []  # type: ignore[attr-defined]


# --- the reason vocabulary ------------------------------------------------


def test_every_rejection_reason_is_kebab_case_and_the_set_is_closed() -> None:
    """3.4 renders one state and branches on this set; a typo would render
    nothing at all, so the set is enforced rather than described."""
    assert REJECTION_REASONS == (
        "no-evidence",
        "no-citations",
        "uncited-claim",
        "unresolvable-marker",
        "empty-answer",
    )
    # Kebab-case, checked rather than assumed: a future `noEvidence` would pass
    # the tuple comparison above only by being added to it, and this is what
    # would object. Problem *extensions* are camelCase; the values inside them
    # are slugs, like every other slug this api emits.
    for reason in REJECTION_REASONS:
        assert re.fullmatch(r"[a-z]+(?:-[a-z]+)*", reason), reason
    with pytest.raises(ValueError):
        Rejection("not-a-reason", "detail")
