"""The judge bake-off (eval-design §7): pick the judge model empirically.

Three candidate pools — frontier API, local Ollama, hosted open-weight — each
score the same committed sample blind against each other, using
``judge.score_with_llm`` (the exact rubric-2.7 scorer the real judge run
uses). Primary grading is agreement with a human-authored gold verdict per
item; ties break on repeat-consistency, then pool order (cost/locality); an
unresolved tie is never broken arbitrarily.

Manual, RUNBOOK-invoked CLI, like ``judge.py`` — never collected by pytest,
never run under `make evals-test` / `make evals-run`. Every automated test
exercises the pure math (:func:`agreement`, :func:`consistency`,
:func:`_select_winner`) and candidate/sample loading against a fake `Llm`
(`evals/tests/test_bakeoff.py`); a real bake-off costs real money across three
providers by design (eval-design §7's whole point).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from evals.harness.judge import JudgeItem, RubricScore, _write_yaml_once, score_with_llm
from evals.harness.run import Run

REPORT_NAME = "bakeoff-report.yaml"

#: The three pools eval-design §7 names, in the order a cost/locality
#: tie-break prefers them: local first (free, on-machine), hosted open-weight
#: second, frontier API last (paid, off-machine).
POOLS: tuple[str, ...] = ("local-ollama", "hosted-open-weight", "frontier-api")
_POOL_PRIORITY = {pool: index for index, pool in enumerate(POOLS)}

_PROBE_PROMPT = "Reply with exactly one word: ready"


class BakeoffError(Exception):
    """The bake-off cannot proceed — a named refusal, never a vacuous winner."""


@dataclass(frozen=True)
class Candidate:
    """One judge candidate: which pool it represents, and its binding.

    ``binding`` is a real ``meetingminer.config.LlmRoleBinding`` (the
    structural protocol `adapters/llm/__init__.py`'s ``RoleBinding`` already
    matches field-for-field) — ad-hoc, built in memory from
    ``bakeoff-candidates.yaml``, never written into ``config.yaml``'s
    ``llm.roles`` (which `extra="forbid"`s a new key).
    """

    pool: Literal["local-ollama", "hosted-open-weight", "frontier-api"]
    label: str
    binding: Any


@dataclass(frozen=True)
class GoldVerdict:
    """One human-authored pass/fail for one sample item — the bake-off's gold."""

    item_id: str
    passed: bool


@dataclass(frozen=True)
class Sample:
    """The committed sample every candidate judges, plus its gold verdicts."""

    items: tuple[JudgeItem, ...]
    gold: dict[str, GoldVerdict]


def load_candidates(path: Path) -> tuple[Candidate, ...]:
    """Parse ``bakeoff-candidates.yaml``: a list of pool/label/binding entries.

    Refuses an empty list outright (the matrix's "empty candidate list ...
    named failure, never a vacuous winner") rather than letting the bake-off
    proceed with nothing to compare.
    """
    from meetingminer.config import LlmRoleBinding

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise BakeoffError(
            f"{path} names no candidates — the bake-off has nothing to compare"
        )
    candidates: list[Candidate] = []
    seen_labels: set[str] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise BakeoffError(f"{path} candidate {index} must be a mapping")
        pool = entry.get("pool")
        if pool not in POOLS:
            raise BakeoffError(
                f"{path} candidate {index} has pool {pool!r}, not one of {POOLS}"
            )
        label = entry.get("label")
        if not isinstance(label, str) or not label:
            raise BakeoffError(f"{path} candidate {index} needs a non-empty label")
        if label in seen_labels:
            raise BakeoffError(f"{path} has two candidates labeled {label!r}")
        seen_labels.add(label)
        binding_fields = {k: v for k, v in entry.items() if k not in ("pool", "label")}
        try:
            binding = LlmRoleBinding(**binding_fields)
        except Exception as exc:  # pydantic's ValidationError, not imported for its own sake
            raise BakeoffError(
                f"{path} candidate {label!r} is not a valid model binding: {exc}"
            ) from exc
        candidates.append(Candidate(pool=pool, label=label, binding=binding))
    return tuple(candidates)


def load_sample(path: Path) -> Sample:
    """Parse a committed sample file: mixed qa/artifact items plus human gold.

    Refuses an empty sample outright, mirroring :func:`load_candidates`.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    entries = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise BakeoffError(
            f"{path} names no sample items — the bake-off has nothing to score"
        )
    items: list[JudgeItem] = []
    gold: dict[str, GoldVerdict] = {}
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise BakeoffError(f"{path} item {index} must be a mapping")
        item_id = entry.get("id")
        kind = entry.get("kind")
        if not isinstance(item_id, str) or not item_id:
            raise BakeoffError(f"{path} item {index} needs a non-empty id")
        if item_id in seen_ids:
            raise BakeoffError(f"{path} has two items with id {item_id!r}")
        seen_ids.add(item_id)
        if kind not in ("qa", "artifact"):
            raise BakeoffError(f"{path} item {item_id!r} has kind {kind!r}, not qa/artifact")
        if "gold_passed" not in entry or not isinstance(entry["gold_passed"], bool):
            raise BakeoffError(
                f"{path} item {item_id!r} needs a boolean gold_passed — the human"
                " verdict every candidate is graded against"
            )
        meeting_id = entry.get("meeting_id", "sample")
        manifest_id = entry.get("manifest")
        candidate_text = entry.get("candidate_text", "")
        transcript = entry.get("transcript", "")
        citation_present = entry.get("citation_present", True)
        required_terms = entry.get("required_terms", ())
        if not isinstance(meeting_id, str):
            raise BakeoffError(f"{path} item {item_id!r} meeting_id must be a string")
        if manifest_id is not None and not isinstance(manifest_id, str):
            raise BakeoffError(f"{path} item {item_id!r} manifest must be a string or null")
        if not isinstance(candidate_text, str) or not isinstance(transcript, str):
            raise BakeoffError(f"{path} item {item_id!r} text fields must be strings")
        if not isinstance(citation_present, bool):
            raise BakeoffError(f"{path} item {item_id!r} citation_present must be boolean")
        if (
            not isinstance(required_terms, (list, tuple))
            or not all(isinstance(term, str) for term in required_terms)
        ):
            raise BakeoffError(f"{path} item {item_id!r} required_terms must be a list of strings")
        item = JudgeItem(
            kind=kind,
            item_id=item_id,
            meeting_id=meeting_id,
            manifest_id=manifest_id,
            candidate_text=candidate_text,
            transcript=transcript,
            citation_present=citation_present,
            required_terms=tuple(required_terms),
        )
        items.append(item)
        gold[item_id] = GoldVerdict(item_id=item_id, passed=entry["gold_passed"])
    return Sample(items=tuple(items), gold=gold)


def agreement(scores: dict[str, RubricScore], gold: dict[str, GoldVerdict]) -> float:
    """Fraction of gold items this candidate's ``passed`` verdict agrees with.

    Scored against every gold item, not only the ones a candidate actually
    answered: a candidate missing an item (excluded mid-round, say) does not
    get to shrink its own denominator.
    """
    if not gold:
        return 0.0
    matches = sum(
        1
        for item_id, verdict in gold.items()
        if item_id in scores and scores[item_id].passed == verdict.passed
    )
    return matches / len(gold)


def consistency(repeats: list[dict[str, RubricScore]]) -> float:
    """Fraction of items whose ``passed`` verdict was identical across repeats.

    ``--repeats == 1`` has nothing to compare, so callers only ask this when
    there is more than one repeat; a single repeat's "consistency" would be
    vacuously 1.0 and would say nothing about the model.
    """
    if not repeats:
        return 0.0
    item_ids = set(repeats[0])
    if not item_ids:
        return 0.0
    stable = sum(
        1
        for item_id in item_ids
        if len({r[item_id].passed for r in repeats if item_id in r}) == 1
    )
    return stable / len(item_ids)


def _select_winner(
    results: dict[str, dict[str, Any]], *, repeats: int
) -> tuple[str | None, str | None]:
    """eval-design §7's grading: agreement first, then consistency, then pool.

    Pool order is consulted only when ``repeats > 1`` gave consistency
    something to break the tie further with — at ``repeats == 1`` there is no
    second measured signal at all, and eval-design §7 lists pool order
    ("cost/locality") strictly *after* consistency, never as a standalone
    substitute for it. An agreement tie at ``repeats == 1`` is therefore never
    broken by which pool a candidate happens to sit in: it is named and left
    unresolved, exactly the acceptance criterion this function exists to meet.
    """
    if not results:
        return None, "no candidate could be scored — every candidate was excluded"
    best_agreement = max(result["agreement"] for result in results.values())
    tied = [label for label, result in results.items() if result["agreement"] == best_agreement]
    if len(tied) == 1:
        return tied[0], None

    if repeats > 1:
        best_consistency = max(results[label]["consistency"] for label in tied)
        by_consistency = [
            label for label in tied if results[label]["consistency"] == best_consistency
        ]
        if len(by_consistency) == 1:
            return by_consistency[0], None
        best_pool_rank = min(_POOL_PRIORITY[results[label]["pool"]] for label in by_consistency)
        by_pool = [
            label
            for label in by_consistency
            if _POOL_PRIORITY[results[label]["pool"]] == best_pool_rank
        ]
        if len(by_pool) == 1:
            return by_pool[0], None
        tied = by_pool

    tie_note = (
        f"{len(tied)} candidates tied on agreement ({best_agreement})"
        f"{' and consistency' if repeats > 1 else ''}: {', '.join(sorted(tied))}"
        " — no arbitrary pick"
    )
    return None, tie_note


def run_bakeoff(
    run_id: str,
    candidates: tuple[Candidate, ...],
    sample: Sample,
    config: Any,
    *,
    repeats: int = 1,
    root: Path | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Score every candidate blind against the sample and write the report.

    Every candidate's ``Llm`` is built with ``fallback=None`` — substitution
    would attribute a reply to the wrong exact model id, which is the one
    thing a bake-off exists to pin.
    """
    from meetingminer.adapters.llm import LlmError, build_llm
    from meetingminer.config import LlmRoleBinding

    if not candidates:
        raise BakeoffError("no candidates given — the bake-off has nothing to compare")
    if not sample.items:
        raise BakeoffError("the sample has no items — the bake-off has nothing to score")
    if repeats < 1:
        raise BakeoffError("repeats must be at least 1")

    run = Run.create(run_id, config=config, root=root, label=label)

    results: dict[str, dict[str, Any]] = {}
    excluded: dict[str, str] = {}
    for candidate in candidates:
        pinned = LlmRoleBinding(
            model=candidate.binding.model,
            fallback=None,
            base_url=candidate.binding.base_url,
            fallback_base_url=None,
            timeout_seconds=candidate.binding.timeout_seconds,
            num_ctx=candidate.binding.num_ctx,
        )
        llm = build_llm(pinned, config.settings.providers, log=None)
        try:
            probe = llm.complete(_PROBE_PROMPT)
            if not probe.text.strip():
                raise LlmError("probe reply was empty")
        except LlmError as exc:
            excluded[candidate.label] = str(exc)
            continue

        # `score_with_llm` catches `LlmError` internally for every call it
        # makes and always returns a `RubricScore` (never raises) — so this
        # loop cannot itself raise `LlmError`. No try/except needed here; the
        # reachability probe above is what actually excludes an unreachable
        # candidate before real, paid scoring calls are made.
        repeat_scores: list[dict[str, RubricScore]] = []
        candidate_error: str | None = None
        for _ in range(repeats):
            scores = {item.item_id: score_with_llm(llm, item) for item in sample.items}
            failed = next((score for score in scores.values() if score.call_failed), None)
            if failed is not None:
                candidate_error = failed.reason or "a scoring call failed"
                break
            repeat_scores.append(scores)
        if candidate_error is not None:
            excluded[candidate.label] = candidate_error
            continue

        #: eval-design §7's primary score is one measurement, not "whichever
        #: repeat happened to run last" — grading is always the first repeat;
        #: later repeats (when `--repeats > 1`) only ever feed the secondary
        #: `consistency` signal, never change which pass is graded.
        final_scores = repeat_scores[0]
        #: eval-design §7's "pinned by exact model id and version" — the set
        #: of `LlmReply.model` strings that actually answered this candidate's
        #: calls, not the configured binding's nominal model string. With
        #: `fallback=None` above, a healthy candidate answers every call with
        #: one consistent id; if the provider serves more than one, all are
        #: named rather than the first being picked silently.
        answering_models = sorted(
            {
                model
                for scores in repeat_scores
                for score in scores.values()
                for model in score.models
            }
            | {probe.model}
        )
        sample_items_by_id = {item.item_id: item for item in sample.items}
        results[candidate.label] = {
            "pool": candidate.pool,
            "configured_model": candidate.binding.model,
            "probe_model": probe.model,
            "model": answering_models[0] if len(answering_models) == 1 else answering_models,
            "agreement": round(agreement(final_scores, sample.gold), 4),
            "consistency": (
                round(consistency(repeat_scores), 4) if repeats > 1 else None
            ),
            "scores": {
                item_id: {**sample_items_by_id[item_id].to_dict(), **score.to_dict()}
                for item_id, score in final_scores.items()
            },
            "repeat_call_models": [
                {item_id: list(score.models) for item_id, score in scores.items()}
                for scores in repeat_scores
            ],
        }

    winner, tie = _select_winner(results, repeats=repeats)
    payload = {
        "story": "5.4 — LLM judge bake-off (eval-design §7)",
        "sample_size": len(sample.items),
        "repeats": repeats,
        "candidates": results,
        "excluded": excluded,
        "winner": winner,
        "tie": tie,
    }
    path = run.folder / REPORT_NAME
    _write_yaml_once(path, payload)
    return payload


def _default_bakeoff_run_id(label: str | None) -> str:
    """``bakeoff-<UTC date>[-<label>]`` — eval-design §7's own folder naming."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"bakeoff-{date}-{label}" if label else f"bakeoff-{date}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the judge bake-off (eval-design §7): score a committed sample"
            " with every candidate in bakeoff-candidates.yaml, blind, and pick"
            " the winner by agreement with human gold. Manual: this calls real"
            " frontier and hosted-open-weight providers, which cost money."
        )
    )
    parser.add_argument("--run-id", default=None, help="folder name under evals/runs/")
    parser.add_argument("--run-label", default=None, help="short label, used in the default run id")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("evals/bakeoff-candidates.yaml"),
        help="path to the candidates file (default %(default)s)",
    )
    parser.add_argument(
        "--sample", type=Path, required=True, help="path to a committed sample file"
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="times to re-score the sample per candidate, for a consistency tie-break",
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    from meetingminer.config import load_config

    config = load_config()
    run_id = args.run_id or _default_bakeoff_run_id(args.run_label)
    try:
        candidates = load_candidates(args.candidates)
        sample = load_sample(args.sample)
        payload = run_bakeoff(
            run_id,
            candidates,
            sample,
            config,
            repeats=args.repeats,
            label=args.run_label,
        )
    except BakeoffError as exc:
        parser.error(str(exc))
    except Exception as exc:  # noqa: BLE001 - operator-facing CLI, never a raw traceback
        parser.error(str(exc))
    print(f"evals/runs/{run_id}/{REPORT_NAME}: winner={payload['winner']!r}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())
