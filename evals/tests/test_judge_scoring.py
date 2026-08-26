"""``judge.py``'s rubric-2.7 scorer: prompt shape, JSON parsing, and the
mechanical/LLM criterion split (eval-design §2.7) — store-free, against a
fake `Llm`.

No test here makes a real model call: every scripted reply is a Python
string a fake `.complete()` returns, and `meetingminer.adapters.llm.LlmError`
is imported only to *raise* it from that fake, the same way
`server/tests/test_api_chat.py`'s `ChatLlm` stands in for `POST /chat`'s
completer. `test_harness_boundary.py::test_the_judge_and_bakeoff_modules_
never_reach_for_media_roots` and its import guards are what actually pin that
`judge.py` touches no recording path and no media-root environment variable;
this file is about the scoring logic those guards do not reach.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from evals.harness.judge import (
    JudgeItem,
    build_judge_prompt,
    contains_required_terms,
    score_with_llm,
)


@dataclass
class FakeReply:
    text: str
    model: str = "fake-judge-model"


@dataclass
class FakeLlm:
    """A scripted `Llm`: replies pop off a queue, or a callable computes one.

    Mirrors the shape `pipeline/stages/extract.py::run` calls (`.complete`
    with no options for these tests): the port's contract is exactly this
    method, nothing more.
    """

    replies: list[str] = field(default_factory=list)
    raises: BaseException | None = None
    calls: list[str] = field(default_factory=list)

    def complete(self, prompt: str, options: object | None = None) -> FakeReply:
        self.calls.append(prompt)
        if self.raises is not None:
            raise self.raises
        if not self.replies:
            raise AssertionError("FakeLlm ran out of scripted replies")
        return FakeReply(text=self.replies.pop(0))


def make_item(
    kind: str = "artifact",
    *,
    candidate_text: str = "The team decided to keep optimistic locking.",
    transcript: str = "[Tim Goeke] Orders module keeps optimistic locking.",
    citation_present: bool = True,
    required_terms: tuple[str, ...] = (),
) -> JudgeItem:
    return JudgeItem(
        kind=kind,
        item_id="item-1",
        meeting_id="meeting-1",
        manifest_id="demo-001",
        candidate_text=candidate_text,
        transcript=transcript,
        citation_present=citation_present,
        required_terms=required_terms,
    )


def valid_reply(*, faithful: bool = True, no_unsupported_claims: bool = True) -> str:
    return json.dumps(
        {
            "faithful": faithful,
            "no_unsupported_claims": no_unsupported_claims,
            "reason": "matches the transcript",
        }
    )


# --- contains_required_terms (mechanical criterion c) -----------------------


def test_no_required_terms_is_vacuously_satisfied() -> None:
    """An artifact item carries no `answer_must_contain` — nothing to check."""
    item = make_item(required_terms=())
    assert contains_required_terms(item) is True


def test_every_required_term_present_normalized() -> None:
    item = make_item(
        candidate_text="Optimistic-Locking stays in place for ORDERS.",
        required_terms=("optimistic locking",),
    )
    assert contains_required_terms(item) is True


def test_a_missing_required_term_fails() -> None:
    item = make_item(
        candidate_text="Tim owns the change and is working on it this week.",
        required_terms=("tax table", "Friday"),
    )
    assert contains_required_terms(item) is False


# --- build_judge_prompt ------------------------------------------------------


def test_the_prompt_carries_the_transcript_and_candidate_text_verbatim() -> None:
    item = make_item(
        candidate_text="UNIQUE CANDIDATE MARKER",
        transcript="UNIQUE TRANSCRIPT MARKER",
    )
    prompt = build_judge_prompt(item)
    assert "UNIQUE CANDIDATE MARKER" in prompt
    assert "UNIQUE TRANSCRIPT MARKER" in prompt


def test_the_prompt_never_asks_the_model_to_judge_the_mechanical_criteria() -> None:
    """Rubric 2.7's two mechanical criteria are decided before the model is
    ever asked — the prompt must not invite it to second-guess them."""
    prompt = build_judge_prompt(make_item())
    assert "citation_present" not in prompt
    assert "contains_required_terms" not in prompt


def test_an_empty_transcript_reads_as_no_evidence_rather_than_a_blank() -> None:
    prompt = build_judge_prompt(make_item(transcript=""))
    assert "no transcript text is available" in prompt


# --- score_with_llm: parses on the first try --------------------------------


def test_a_valid_reply_parses_into_a_rubric_score() -> None:
    llm = FakeLlm(replies=[valid_reply(faithful=True, no_unsupported_claims=True)])
    score = score_with_llm(llm, make_item(citation_present=True))
    assert score.applicable is True
    assert score.faithful is True
    assert score.no_unsupported_claims is True
    assert score.citation_present is True
    assert score.contains_required_terms is True
    assert score.passed is True
    assert len(llm.calls) == 1


def test_the_recorded_model_is_the_replys_not_a_nominal_binding_string() -> None:
    """`RubricScore.model` must be the exact `LlmReply.model` that answered —
    the spec's `Always` rule ("not the configured role's nominal model").
    `FakeLlm` never sees a binding at all, so there is nothing to fall back to
    here except the reply itself."""
    llm = FakeLlm(replies=[valid_reply(faithful=True, no_unsupported_claims=True)])
    score = score_with_llm(llm, make_item())
    assert score.model == "fake-judge-model"


def test_the_retrys_model_wins_when_the_retry_is_what_parsed() -> None:
    class TwoModelLlm:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def complete(self, prompt: str, options: object | None = None):
            self.calls.append(prompt)
            if len(self.calls) == 1:
                return FakeReply(text="not json", model="first-model")
            return FakeReply(text=valid_reply(), model="second-model")

    score = score_with_llm(TwoModelLlm(), make_item())
    assert score.applicable is True
    assert score.model == "second-model"
    assert score.models == ("first-model", "second-model")


def test_passed_is_the_and_of_all_four_criteria() -> None:
    """A faithful, unsupported-claim-free reply still fails if a mechanical
    criterion is false — `passed` is the AND of all four, not just the two
    the model answered. Uses a required-terms mismatch rather than a missing
    citation, since a missing citation now skips the judge call entirely
    (see the "never calls the model" tests below)."""
    llm = FakeLlm(replies=[valid_reply(faithful=True, no_unsupported_claims=True)])
    score = score_with_llm(
        llm, make_item(citation_present=True, required_terms=("pessimistic locking",))
    )
    assert score.faithful is True
    assert score.no_unsupported_claims is True
    assert score.contains_required_terms is False
    assert score.passed is False


def test_a_missing_citation_never_calls_the_model() -> None:
    """`passed` is already decided by a missing citation — the judge call is
    skipped entirely, not just discounted after the fact. `_score_qa_items`
    used to special-case this; the check now lives in `score_with_llm` itself
    so every caller (including `run_bakeoff`, which calls `score_with_llm`
    directly) gets it for free."""
    llm = FakeLlm(replies=[])  # would raise AssertionError if ever called
    score = score_with_llm(llm, make_item(citation_present=False))
    assert score.passed is False
    assert score.citation_present is False
    assert score.faithful is None
    assert score.no_unsupported_claims is None
    assert score.applicable is True
    assert score.model is None
    assert llm.calls == []


def test_a_missing_citation_still_reports_the_mechanical_required_terms_result() -> None:
    """The skip only bypasses the judge call, not the other mechanical
    criterion — `contains_required_terms` is still computed and recorded."""
    llm = FakeLlm(replies=[])
    score = score_with_llm(
        llm,
        make_item(
            citation_present=False,
            candidate_text="no mention of the required phrase",
            required_terms=("optimistic locking",),
        ),
    )
    assert score.contains_required_terms is False
    assert score.passed is False
    assert llm.calls == []


def test_the_judge_can_fail_an_item_on_faithfulness_alone() -> None:
    llm = FakeLlm(replies=[valid_reply(faithful=False, no_unsupported_claims=True)])
    score = score_with_llm(llm, make_item())
    assert score.faithful is False
    assert score.passed is False


# --- score_with_llm: the one-retry-then-not-applicable path -----------------


def test_an_unparsable_reply_is_retried_once_with_a_stricter_prompt() -> None:
    llm = FakeLlm(replies=["not json at all", valid_reply()])
    score = score_with_llm(llm, make_item())
    assert len(llm.calls) == 2
    assert "previous reply could not be parsed" in llm.calls[1]
    assert "not json at all" in llm.calls[1]
    assert score.applicable is True
    assert score.passed is True


def test_two_unparsable_replies_are_recorded_not_applicable_never_passed() -> None:
    llm = FakeLlm(replies=["still not json", "still not json either"])
    score = score_with_llm(llm, make_item())
    assert len(llm.calls) == 2
    assert score.applicable is False
    assert score.passed is False
    assert score.faithful is None
    assert score.no_unsupported_claims is None
    assert score.raw_reply == "still not json either"
    assert score.reason is not None


@pytest.mark.parametrize(
    "bad_reply",
    [
        '{"faithful": true}',  # missing no_unsupported_claims
        '{"faithful": true, "no_unsupported_claims": true}',  # missing reason
        '{"faithful": "yes", "no_unsupported_claims": true}',  # wrong type
        "[]",  # not an object
        "",  # empty
    ],
)
def test_every_shape_of_unparsable_reply_is_recorded_not_applicable(bad_reply: str) -> None:
    llm = FakeLlm(replies=[bad_reply, bad_reply])
    score = score_with_llm(llm, make_item())
    assert score.applicable is False
    assert score.passed is False


# --- score_with_llm: a call that raises never crashes the scorer -----------


def test_a_call_that_raises_llm_error_is_recorded_not_applicable_not_a_crash() -> None:
    from meetingminer.adapters.llm import LlmError

    llm = FakeLlm(raises=LlmError("the model host is not answering"))
    score = score_with_llm(llm, make_item())
    assert score.applicable is False
    assert score.passed is False
    assert "not answering" in (score.reason or "")
    assert score.call_failed is True


def test_llm_unavailable_error_is_also_recorded_not_a_crash() -> None:
    """`LlmUnavailableError` is an `LlmError` subclass — the same recorded-defect
    path, not a second one, mirroring `extract.py`'s single `except LlmError`."""
    from meetingminer.adapters.llm import LlmUnavailableError

    llm = FakeLlm(raises=LlmUnavailableError("host unreachable"))
    score = score_with_llm(llm, make_item())
    assert score.applicable is False
    assert score.passed is False


def test_a_retry_call_that_then_raises_is_also_recorded_not_a_crash() -> None:
    from meetingminer.adapters.llm import LlmError

    calls: list[str] = []

    class FlakyLlm:
        def complete(self, prompt: str, options: object | None = None) -> FakeReply:
            calls.append(prompt)
            if len(calls) == 1:
                return FakeReply(text="not json")
            raise LlmError("second call failed too")

    score = score_with_llm(FlakyLlm(), make_item())
    assert len(calls) == 2
    assert score.applicable is False
    assert score.passed is False
