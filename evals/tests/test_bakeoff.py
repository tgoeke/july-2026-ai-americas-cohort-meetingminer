"""``bakeoff.py``: candidate/sample loading, the agreement/consistency math,
and the tie-break order (eval-design §7) — store-free, against fake `Llm`s.

Like `test_judge_scoring.py`, no test here makes a real model call.
`run_bakeoff` itself calls `meetingminer.adapters.llm.build_llm` through a
function-local import, so the end-to-end tests monkeypatch that module
attribute directly with a fake completer factory — the same substitution
`server/tests/test_api_chat.py`'s `chat_llm` fixture does for `POST /chat`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from evals.harness.bakeoff import (
    BakeoffError,
    Candidate,
    GoldVerdict,
    Sample,
    _select_winner,
    agreement,
    consistency,
    load_candidates,
    load_sample,
    main,
    run_bakeoff,
)
from evals.harness.judge import JudgeItem, RubricScore

# --- fakes -------------------------------------------------------------------


@dataclass
class FakeReply:
    text: str
    model: str = "fake-model"


@dataclass
class FakeLlm:
    #: each entry is either a bare reply string (wrapped with the default
    #: `FakeReply.model`) or a pre-built `FakeReply` naming its own model —
    #: the latter is how a test pins the exact answering model per call.
    replies: list[str | FakeReply] = field(default_factory=list)
    raises: BaseException | None = None
    calls: int = 0

    def complete(self, prompt: str, options: object | None = None) -> FakeReply:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        if not self.replies:
            raise AssertionError("FakeLlm ran out of scripted replies")
        reply = self.replies.pop(0)
        return reply if isinstance(reply, FakeReply) else FakeReply(text=reply)


def verdict_reply(passed: bool) -> str:
    """A judge reply that makes `score_with_llm` compute `passed == passed`,
    for an item whose `citation_present` and `required_terms` already hold."""
    return json.dumps({"faithful": passed, "no_unsupported_claims": passed, "reason": "x"})


def score(passed: bool) -> RubricScore:
    return RubricScore(
        passed=passed,
        citation_present=True,
        contains_required_terms=True,
        faithful=passed,
        no_unsupported_claims=passed,
        raw_reply=None,
    )


def item(item_id: str) -> JudgeItem:
    return JudgeItem(
        kind="artifact",
        item_id=item_id,
        meeting_id="m1",
        manifest_id="demo-001",
        candidate_text="x",
        transcript="y",
        citation_present=True,
    )


# --- agreement / consistency -------------------------------------------------


def test_agreement_is_the_fraction_matching_gold() -> None:
    gold = {"a": GoldVerdict("a", True), "b": GoldVerdict("b", False)}
    scores = {"a": score(True), "b": score(True)}  # disagrees on b
    assert agreement(scores, gold) == 0.5


def test_agreement_with_no_gold_is_zero_not_a_division_error() -> None:
    assert agreement({}, {}) == 0.0


def test_a_missing_score_counts_as_a_disagreement_not_a_shrunk_denominator() -> None:
    """A candidate excluded mid-round does not get to answer fewer gold items
    than everyone else — a missing score is scored against, not skipped."""
    gold = {"a": GoldVerdict("a", True), "b": GoldVerdict("b", True)}
    scores = {"a": score(True)}
    assert agreement(scores, gold) == 0.5


def test_consistency_is_the_fraction_stable_across_repeats() -> None:
    repeats = [
        {"a": score(True), "b": score(True)},
        {"a": score(True), "b": score(False)},
    ]
    assert consistency(repeats) == 0.5


def test_consistency_with_no_repeats_is_zero() -> None:
    assert consistency([]) == 0.0


def test_consistency_is_one_when_every_item_agrees_every_repeat() -> None:
    repeats = [{"a": score(True)}, {"a": score(True)}, {"a": score(True)}]
    assert consistency(repeats) == 1.0


# --- _select_winner: the tie-break order -------------------------------------


def result(agreement_: float, *, pool: str, consistency_: float | None = None) -> dict[str, Any]:
    return {"pool": pool, "agreement": agreement_, "consistency": consistency_, "scores": {}}


def test_a_unique_top_agreement_wins_outright() -> None:
    results = {"a": result(1.0, pool="frontier-api"), "b": result(0.5, pool="local-ollama")}
    winner, tie = _select_winner(results, repeats=1)
    assert winner == "a"
    assert tie is None


def test_a_tie_at_repeats_one_is_never_broken_by_pool_and_is_named() -> None:
    """The acceptance criterion, verbatim: two candidates tied on agreement
    with --repeats=1 -> winner null, tie named — never an arbitrary pick, and
    never resolved by which pool a candidate happens to sit in."""
    results = {
        "local": result(0.8, pool="local-ollama"),
        "frontier": result(0.8, pool="frontier-api"),
    }
    winner, tie = _select_winner(results, repeats=1)
    assert winner is None
    assert tie is not None
    assert "local" in tie and "frontier" in tie


def test_a_tie_broken_by_consistency_when_repeats_exceeds_one() -> None:
    results = {
        "a": result(0.8, pool="frontier-api", consistency_=0.9),
        "b": result(0.8, pool="local-ollama", consistency_=0.6),
    }
    winner, tie = _select_winner(results, repeats=3)
    assert winner == "a"
    assert tie is None


def test_a_tie_on_agreement_and_consistency_falls_back_to_pool_order() -> None:
    results = {
        "frontier": result(0.8, pool="frontier-api", consistency_=0.9),
        "local": result(0.8, pool="local-ollama", consistency_=0.9),
        "hosted": result(0.8, pool="hosted-open-weight", consistency_=0.9),
    }
    winner, tie = _select_winner(results, repeats=3)
    assert winner == "local"
    assert tie is None


def test_a_tie_unbroken_even_after_pool_order_is_named_not_picked() -> None:
    """Two candidates in the *same* pool, tied on agreement and consistency:
    pool order cannot distinguish them either, so it is still a named tie."""
    results = {
        "local-a": result(0.8, pool="local-ollama", consistency_=0.9),
        "local-b": result(0.8, pool="local-ollama", consistency_=0.9),
    }
    winner, tie = _select_winner(results, repeats=3)
    assert winner is None
    assert tie is not None


def test_no_surviving_candidate_is_a_named_failure_not_a_null_without_reason() -> None:
    winner, tie = _select_winner({}, repeats=1)
    assert winner is None
    assert tie is not None and "excluded" in tie


# --- load_candidates ----------------------------------------------------------


def test_load_candidates_parses_a_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "candidates.yaml"
    path.write_text(
        yaml.safe_dump(
            [
                {"pool": "frontier-api", "label": "claude", "model": "claude-sonnet-5"},
                {"pool": "local-ollama", "label": "qwen", "model": "ollama/qwen3:30b"},
            ]
        )
    )
    candidates = load_candidates(path)
    assert [c.label for c in candidates] == ["claude", "qwen"]
    assert candidates[0].binding.model == "claude-sonnet-5"


def test_the_committed_default_candidates_cover_every_required_pool() -> None:
    path = Path(__file__).parents[2] / "evals/bakeoff-candidates.yaml"
    assert {candidate.pool for candidate in load_candidates(path)} == {
        "frontier-api", "local-ollama", "hosted-open-weight"
    }


def test_load_candidates_refuses_an_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "candidates.yaml"
    path.write_text(yaml.safe_dump([]))
    with pytest.raises(BakeoffError, match="no candidates"):
        load_candidates(path)


def test_load_candidates_refuses_an_unknown_pool(tmp_path: Path) -> None:
    path = tmp_path / "candidates.yaml"
    path.write_text(yaml.safe_dump([{"pool": "carrier-pigeon", "label": "x", "model": "m"}]))
    with pytest.raises(BakeoffError, match="pool"):
        load_candidates(path)


def test_load_candidates_refuses_duplicate_labels(tmp_path: Path) -> None:
    path = tmp_path / "candidates.yaml"
    path.write_text(
        yaml.safe_dump(
            [
                {"pool": "frontier-api", "label": "dupe", "model": "a"},
                {"pool": "local-ollama", "label": "dupe", "model": "b"},
            ]
        )
    )
    with pytest.raises(BakeoffError, match="dupe"):
        load_candidates(path)


def test_load_candidates_refuses_an_invalid_binding(tmp_path: Path) -> None:
    path = tmp_path / "candidates.yaml"
    path.write_text(
        yaml.safe_dump([{"pool": "frontier-api", "label": "x", "not_a_field": "boom"}])
    )
    with pytest.raises(BakeoffError):
        load_candidates(path)


# --- load_sample ---------------------------------------------------------------


def _sample_yaml(*items: dict[str, Any]) -> dict[str, Any]:
    return {"items": list(items)}


def test_load_sample_parses_a_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump(
            _sample_yaml(
                {"id": "i1", "kind": "qa", "candidate_text": "x", "gold_passed": True},
                {"id": "i2", "kind": "artifact", "candidate_text": "y", "gold_passed": False},
            )
        )
    )
    sample = load_sample(path)
    assert len(sample.items) == 2
    assert sample.gold["i1"].passed is True
    assert sample.gold["i2"].passed is False


def test_load_sample_refuses_an_empty_sample(tmp_path: Path) -> None:
    path = tmp_path / "sample.yaml"
    path.write_text(yaml.safe_dump(_sample_yaml()))
    with pytest.raises(BakeoffError, match="no sample items"):
        load_sample(path)


def test_load_sample_refuses_a_missing_gold_verdict(tmp_path: Path) -> None:
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump(_sample_yaml({"id": "i1", "kind": "qa", "candidate_text": "x"}))
    )
    with pytest.raises(BakeoffError, match="gold_passed"):
        load_sample(path)


def test_load_sample_refuses_a_bad_kind(tmp_path: Path) -> None:
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump(
            _sample_yaml({"id": "i1", "kind": "essay", "candidate_text": "x", "gold_passed": True})
        )
    )
    with pytest.raises(BakeoffError, match="kind"):
        load_sample(path)


def test_load_sample_refuses_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump(
            _sample_yaml(
                {"id": "dupe", "kind": "qa", "candidate_text": "x", "gold_passed": True},
                {"id": "dupe", "kind": "qa", "candidate_text": "y", "gold_passed": False},
            )
        )
    )
    with pytest.raises(BakeoffError, match="dupe"):
        load_sample(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("citation_present", "false"),
        ("candidate_text", 42),
        ("required_terms", "not-a-list"),
    ],
)
def test_load_sample_refuses_malformed_optional_fields(
    tmp_path: Path, field: str, value: Any
) -> None:
    path = tmp_path / "sample.yaml"
    entry = {"id": "i1", "kind": "qa", "gold_passed": True, field: value}
    path.write_text(yaml.safe_dump(_sample_yaml(entry)))
    with pytest.raises(BakeoffError):
        load_sample(path)


# --- run_bakeoff: end to end against fakes, never a real model -------------


class FakeConfig:
    class settings:
        providers: dict[str, Any] = {}  # noqa: RUF012 - a fixed-shape stand-in, never mutated

        @staticmethod
        def model_dump(mode: str = "json") -> dict[str, Any]:
            return {"providers": {}}

    config_path = "fake-config.yaml"


@pytest.fixture()
def two_candidates() -> tuple[Candidate, ...]:
    from meetingminer.config import LlmRoleBinding

    return (
        Candidate(pool="local-ollama", label="local", binding=LlmRoleBinding(model="ollama/local")),
        Candidate(pool="frontier-api", label="frontier", binding=LlmRoleBinding(model="claude-x")),
    )


@pytest.fixture()
def one_item_sample() -> Sample:
    return Sample(items=(item("i1"),), gold={"i1": GoldVerdict("i1", True)})


def test_run_bakeoff_refuses_no_candidates(one_item_sample: Sample, tmp_path: Path) -> None:
    with pytest.raises(BakeoffError, match="no candidates"):
        run_bakeoff("run-1", (), one_item_sample, FakeConfig(), root=tmp_path)


def test_run_bakeoff_refuses_an_empty_sample(
    two_candidates: tuple[Candidate, ...], tmp_path: Path
) -> None:
    empty = Sample(items=(), gold={})
    with pytest.raises(BakeoffError, match="no items"):
        run_bakeoff("run-1", two_candidates, empty, FakeConfig(), root=tmp_path)


def test_run_bakeoff_refuses_invalid_repeats_before_creating_a_run(
    two_candidates: tuple[Candidate, ...], one_item_sample: Sample, tmp_path: Path
) -> None:
    with pytest.raises(BakeoffError, match="repeats"):
        run_bakeoff("run-zero", two_candidates, one_item_sample, FakeConfig(), root=tmp_path, repeats=0)
    assert not (tmp_path / "run-zero").exists()


def test_run_bakeoff_picks_the_agreeing_candidate_and_excludes_the_unreachable_one(
    two_candidates: tuple[Candidate, ...], one_item_sample: Sample, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meetingminer.adapters.llm import LlmUnavailableError

    def fake_build_llm(role_binding: Any, providers: Any, log: Any = None) -> Any:
        if role_binding.model == "ollama/local":
            return FakeLlm(raises=LlmUnavailableError("host down"))
        # One reply for the reachability probe, one for the item score. The
        # answering model is deliberately not `role_binding.model` ("claude-x")
        # so the report can only be right by reading `LlmReply.model`.
        return FakeLlm(
            replies=[
                FakeReply(text="ready", model="claude-x-20260101"),
                FakeReply(text=verdict_reply(True), model="claude-x-20260101"),
            ]
        )

    monkeypatch.setattr("meetingminer.adapters.llm.build_llm", fake_build_llm)

    payload = run_bakeoff(
        "run-unreachable", two_candidates, one_item_sample, FakeConfig(), root=tmp_path
    )
    assert "local" in payload["excluded"]
    assert "host down" in payload["excluded"]["local"]
    assert payload["candidates"]["frontier"]["agreement"] == 1.0
    assert payload["candidates"]["frontier"]["configured_model"] == "claude-x"
    assert payload["candidates"]["frontier"]["model"] == "claude-x-20260101"
    assert payload["winner"] == "frontier"
    assert (tmp_path / "run-unreachable" / "bakeoff-report.yaml").exists()


def test_run_bakeoff_excludes_a_candidate_whose_probe_reply_is_empty(
    one_item_sample: Sample, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A misconfigured candidate (wrong model id, wrong `base_url` hitting an
    unrelated service) can answer the probe without raising — garbage or
    empty text instead of an error. An empty reply must still exclude the
    candidate rather than being read as "reachable" and proceeding into real,
    paid scoring calls."""
    from meetingminer.config import LlmRoleBinding

    candidate = Candidate(
        pool="frontier-api", label="empty-probe", binding=LlmRoleBinding(model="claude-x")
    )
    fake = FakeLlm(replies=[""])  # the probe reply itself is empty

    monkeypatch.setattr(
        "meetingminer.adapters.llm.build_llm", lambda role_binding, providers, log=None: fake
    )

    payload = run_bakeoff(
        "run-empty-probe", (candidate,), one_item_sample, FakeConfig(), root=tmp_path
    )

    assert "empty-probe" in payload["excluded"]
    assert payload["candidates"] == {}
    # No scoring call was made past the probe.
    assert fake.calls == 1


def test_run_bakeoff_excludes_a_candidate_that_fails_after_its_probe(
    one_item_sample: Sample, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meetingminer.adapters.llm import LlmError
    from meetingminer.config import LlmRoleBinding

    candidate = Candidate(pool="frontier-api", label="drops-later", binding=LlmRoleBinding(model="x"))

    class DropsAfterProbe:
        calls = 0

        def complete(self, prompt: str, options: object | None = None) -> FakeReply:
            self.calls += 1
            if self.calls == 1:
                return FakeReply("ready", model="x-v1")
            raise LlmError("provider dropped during scoring")

    monkeypatch.setattr(
        "meetingminer.adapters.llm.build_llm", lambda role_binding, providers, log=None: DropsAfterProbe()
    )
    payload = run_bakeoff("run-drops", (candidate,), one_item_sample, FakeConfig(), root=tmp_path)
    assert payload["candidates"] == {}
    assert "provider dropped" in payload["excluded"]["drops-later"]


def test_run_bakeoff_forces_fallback_none_on_every_candidate(
    one_item_sample: Sample, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate carrying its own `fallback` in `bakeoff-candidates.yaml`
    must still be called with `fallback=None` — substitution would attribute
    a reply to the wrong exact model id."""
    from meetingminer.config import LlmRoleBinding

    candidate = Candidate(
        pool="frontier-api",
        label="x",
        binding=LlmRoleBinding(model="claude-x", fallback="ollama/qwen3:30b"),
    )
    seen_bindings: list[Any] = []
    fake = FakeLlm(replies=["ready", verdict_reply(True)])

    def fake_build_llm(role_binding: Any, providers: Any, log: Any = None) -> Any:
        seen_bindings.append(role_binding)
        return fake

    monkeypatch.setattr("meetingminer.adapters.llm.build_llm", fake_build_llm)

    run_bakeoff("run-fallback", (candidate,), one_item_sample, FakeConfig(), root=tmp_path)

    # `build_llm` is called once per candidate; the binding it receives must
    # already carry `fallback=None`, whatever bakeoff-candidates.yaml said.
    assert len(seen_bindings) == 1
    assert seen_bindings[0].fallback is None
    # Both calls this candidate makes (the probe, then the item score) went
    # to the one Llm built from that pinned binding.
    assert fake.calls == 2


def test_run_bakeoff_breaks_an_agreement_tie_by_consistency_end_to_end(
    one_item_sample: Sample, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end `run_bakeoff(..., repeats=3)`: two candidates tie on
    agreement (both get the single item right on the first repeat, which is
    what `agreement` is graded against), but one candidate's judge answer
    flips across repeats while the other's does not. The tie must be broken
    by `consistency`, and `payload["candidates"][label]["consistency"]` must
    reflect the actual per-repeat accumulation, not a hand-built input — no
    other test in this file exercises `run_bakeoff` with `repeats > 1`."""
    from meetingminer.config import LlmRoleBinding

    flaky = Candidate(
        pool="hosted-open-weight", label="flaky", binding=LlmRoleBinding(model="flaky-model")
    )
    stable = Candidate(
        pool="frontier-api", label="stable", binding=LlmRoleBinding(model="stable-model")
    )

    def fake_build_llm(role_binding: Any, providers: Any, log: Any = None) -> Any:
        if role_binding.model == "flaky-model":
            # probe, then repeat 1 (True), repeat 2 (False), repeat 3 (True):
            # the first repeat agrees with gold, so agreement ties with
            # `stable`, but the verdict is not the same across repeats.
            return FakeLlm(
                replies=["ready", verdict_reply(True), verdict_reply(False), verdict_reply(True)]
            )
        # probe, then the same verdict every repeat.
        return FakeLlm(replies=["ready", verdict_reply(True), verdict_reply(True), verdict_reply(True)])

    monkeypatch.setattr("meetingminer.adapters.llm.build_llm", fake_build_llm)

    payload = run_bakeoff(
        "run-repeats", (flaky, stable), one_item_sample, FakeConfig(), root=tmp_path, repeats=3
    )

    assert payload["candidates"]["flaky"]["agreement"] == 1.0
    assert payload["candidates"]["stable"]["agreement"] == 1.0
    assert payload["candidates"]["flaky"]["consistency"] == 0.0
    assert payload["candidates"]["stable"]["consistency"] == 1.0
    assert payload["winner"] == "stable"
    assert payload["tie"] is None
    # The scores dict carries the item's own metadata (kind/manifest), not
    # only the rubric score — the same shape `judge.py`'s report uses.
    item_scores = payload["candidates"]["stable"]["scores"]["i1"]
    assert item_scores["kind"] == "artifact"
    assert item_scores["manifest"] == "demo-001"
    assert item_scores["passed"] is True
    assert payload["candidates"]["stable"]["repeat_call_models"] == [
        {"i1": ["fake-model"]},
        {"i1": ["fake-model"]},
        {"i1": ["fake-model"]},
    ]


def test_run_bakeoff_writes_the_report_once_via_run_create(
    two_candidates: tuple[Candidate, ...],
    one_item_sample: Sample,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "meetingminer.adapters.llm.build_llm",
        lambda role_binding, providers, log=None: FakeLlm(replies=[verdict_reply(True)] * 4),
    )
    run_bakeoff("run-once", two_candidates, one_item_sample, FakeConfig(), root=tmp_path)
    folder = tmp_path / "run-once"
    assert (folder / "config-snapshot.yaml").exists()
    assert (folder / "bakeoff-report.yaml").exists()
    # A second run against the same run-id is refused (Run.create's own rule,
    # exercised here rather than re-tested from scratch).
    from evals.harness.run import RunError

    with pytest.raises(RunError):
        run_bakeoff("run-once", two_candidates, one_item_sample, FakeConfig(), root=tmp_path)


def test_main_reports_an_unexpected_error_as_a_clean_cli_error_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def raises_unexpectedly(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    import evals.harness.bakeoff as bakeoff_module

    monkeypatch.setattr(bakeoff_module, "run_bakeoff", raises_unexpectedly)
    monkeypatch.setattr("meetingminer.config.load_config", lambda: FakeConfig())

    sample_path = tmp_path / "sample.yaml"
    sample_path.write_text(yaml.safe_dump(_sample_yaml({"id": "i1", "kind": "artifact", "gold_passed": True})))
    candidates_path = tmp_path / "candidates.yaml"
    candidates_path.write_text(
        yaml.safe_dump([{"pool": "frontier-api", "label": "x", "model": "claude-x"}])
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--candidates", str(candidates_path), "--sample", str(sample_path)])

    assert excinfo.value.code == 2
    assert "boom" in capsys.readouterr().err
