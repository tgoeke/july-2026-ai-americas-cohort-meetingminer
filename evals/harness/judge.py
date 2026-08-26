"""Rubric 2.7's LLM-judge scorer, behind the `Llm` port (AD-8), and its CLI.

Rubric 2.7 (eval-design §2.7) names four criteria per answer/artifact:
faithful to the cited moment, a citation present, `answer_must_contain` terms
present, nothing asserted beyond evidence. Two are computed, not judged —
``citation_present`` (an array non-empty, or FK-backed for an extraction item)
and ``contains_required_terms`` (a normalized substring match) are exactly the
kind of fact a three-line function answers more reliably than a model. Only
``faithful`` and ``no_unsupported_claims`` are asked of the judge model.

This module is a manual, RUNBOOK-invoked CLI, never collected by pytest and
never run under `make evals-test` / `make evals-run` — the judge role can be a
paid frontier API, and a real call must never fire unattended. Every automated
test exercises :func:`score_with_llm` against a fake `Llm`
(`evals/tests/test_judge_scoring.py`); nothing here imports a provider SDK.

**AD-12's judge-scoped egress rule**, made mechanical rather than trusted: a
`JudgeItem`'s `transcript` and `candidate_text` are built exclusively from
Postgres columns already read read-only (`evals/harness/corpus.py`) or a
`POST /chat` response (the public API) — never a recording path, a frame, or
any bytes under either evidence-root environment variable a running
MeetingMiner reads for drop material and pipeline-produced media. This module
references neither of those two variable names anywhere, by name or by value,
and imports no `meetingminer.pipeline`/`.projections`/`.worker` module
(`evals/tests/test_harness_boundary.py` pins both).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
import yaml

from evals.harness.corpus import ArtifactRow, Corpus, TranscriptSegment
from evals.harness.groundtruth import Manifest, normalize_anchor

#: eval-design §2.7's report name, written once into an already-existing run
#: folder (created earlier by `evals-run`, story 5.2). This module never calls
#: `Run.create` — that would refuse a folder that already holds
#: `deterministic-report.yaml` — and it never touches that report or
#: `Run.passed` (eval-design §4.3: the LLM judge tier is advisory).
REPORT_NAME = "llm-judge-report.yaml"

RUBRIC = "2.7 ADR/decision extraction and cited Q&A quality"

FAITHFUL = "faithful"
CITATION_PRESENT = "citation_present"
CONTAINS_REQUIRED_TERMS = "contains_required_terms"
NO_UNSUPPORTED_CLAIMS = "no_unsupported_claims"

#: The two JSON keys a judge reply must carry as booleans to parse at all.
_REQUIRED_JSON_KEYS = (FAITHFUL, NO_UNSUPPORTED_CLAIMS)

_JudgeItemKind = Literal["qa", "artifact"]


class JudgeError(Exception):
    """The judge CLI could not proceed — a named refusal, never a silent skip."""


@dataclass(frozen=True)
class JudgeItem:
    """One rubric-2.7 subject: a real `qa` answer or a real extracted artifact.

    ``transcript`` is the faithfulness haystack — the cited moment's covering
    segments, joined in transcript order. ``candidate_text`` is what is being
    judged: a `POST /chat` answer for a ``qa`` item, or `title` + `body` for an
    artifact. ``required_terms`` is ``qa.answer_must_contain``; empty for an
    artifact, which the ground-truth schema gives no required-terms field —
    :func:`contains_required_terms` returns ``True`` vacuously in that case,
    the same "nothing to check" reading `checks.py` gives an empty haystack.
    ``citation_present`` is supplied by the caller because the two kinds
    compute it two different ways (a citations array vs. an FK), not by this
    dataclass.
    """

    kind: _JudgeItemKind
    item_id: str
    meeting_id: str
    manifest_id: str | None
    candidate_text: str
    transcript: str
    citation_present: bool
    required_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "item": self.item_id,
            "meeting_id": self.meeting_id,
            "manifest": self.manifest_id,
        }


@dataclass(frozen=True)
class RubricScore:
    """Rubric 2.7's verdict for one item, in the shape the report serializes.

    ``faithful`` and ``no_unsupported_claims`` are ``None`` when the judge
    reply could not be parsed even after a retry — never coerced to ``False``,
    which would read as a measured judgment rather than a defect of the judge
    call. ``passed`` is always a real boolean: an unparsable reply, or a
    failed judge call, makes ``passed=False`` and ``applicable=False`` (the
    matrix's "never silently passed").
    """

    passed: bool
    citation_present: bool
    contains_required_terms: bool
    faithful: bool | None
    no_unsupported_claims: bool | None
    raw_reply: str | None
    applicable: bool = True
    reason: str | None = None
    #: The exact `LlmReply.model` string that answered this call — never the
    #: configured role's nominal model (a spec `Always` rule). `None` only
    #: when no call ever returned a reply (the judge call itself raised
    #: `LlmError`/`LlmUnavailableError` before any `LlmReply` existed, or the
    #: item's judge call was skipped entirely because `citation_present` was
    #: already `False`).
    model: str | None = None
    #: Exact models returned by every completed LLM call for this item. A
    #: retry therefore keeps the first response's provenance as well as the
    #: final response that supplied the verdict.
    models: tuple[str, ...] = ()
    #: Unlike an unparsable model reply, an adapter error means no verdict was
    #: produced at all. Bake-off uses this to exclude the candidate as required.
    call_failed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "applicable": self.applicable,
            "citation_present": self.citation_present,
            "contains_required_terms": self.contains_required_terms,
            "faithful": self.faithful,
            "no_unsupported_claims": self.no_unsupported_claims,
            "raw_reply": self.raw_reply,
            "reason": self.reason,
            "model": self.model,
            "models": list(self.models),
            "call_failed": self.call_failed,
        }


def contains_required_terms(item: JudgeItem) -> bool:
    """Mechanical criterion (c): every required term as a normalized substring.

    Folded with the same ``normalize_anchor`` check 2.1 folds OCR text with —
    one definition of "the same words, modulo case/punctuation/whitespace"
    across the whole harness. No required terms (an artifact item) is
    vacuously satisfied: there is nothing to check, not a failure to find it.
    """
    if not item.required_terms:
        return True
    haystack = normalize_anchor(item.candidate_text)
    return all(normalize_anchor(term) in haystack for term in item.required_terms)


def build_judge_prompt(item: JudgeItem) -> str:
    """The rubric-2.7 prompt: transcript, candidate text, the JSON contract.

    Deliberately asks for exactly the two criteria a model must judge — never
    ``citation_present`` or ``contains_required_terms``, which are already
    decided before this prompt is built. Handing the model a criterion code
    already answers would invite it to disagree with a mechanical fact.
    """
    kind_label = "a cited Q&A answer" if item.kind == "qa" else "an extracted artifact"
    return (
        "You are scoring one item against a strict rubric. Judge only the two"
        " criteria named below; do not judge anything else.\n\n"
        f"ITEM TYPE: {kind_label}\n\n"
        "TRANSCRIPT (the only evidence this item may draw on):\n"
        f"{item.transcript or '(no transcript text is available for this moment)'}\n\n"
        "CANDIDATE TEXT (what you are judging):\n"
        f"{item.candidate_text}\n\n"
        "Answer exactly these two questions:\n"
        "1. faithful: is every claim in the candidate text supported by the"
        " transcript above?\n"
        "2. no_unsupported_claims: does the candidate text assert nothing"
        " beyond what the transcript supports (no invented facts, dates, or"
        " names)?\n\n"
        "Reply with ONLY a JSON object, no other text, in exactly this shape:\n"
        '{"faithful": true or false, "no_unsupported_claims": true or false,'
        ' "reason": "one sentence"}'
    )


def _stricter_prompt(item: JudgeItem, bad_reply: str) -> str:
    """The one retry the matrix allows, naming what the first reply got wrong."""
    return (
        build_judge_prompt(item)
        + "\n\nYour previous reply could not be parsed as the required JSON"
        f" object. It was:\n{bad_reply}\n\nReply again with ONLY the JSON"
        ' object: {"faithful": true or false, "no_unsupported_claims": true or'
        ' false, "reason": "one sentence"}'
    )


def _parse_judge_reply(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not all(isinstance(data.get(key), bool) for key in _REQUIRED_JSON_KEYS):
        return None
    if not isinstance(data.get("reason"), str):
        return None
    return data


def score_with_llm(llm: Any, item: JudgeItem) -> RubricScore:
    """Score one item: two criteria computed, two asked of the judge model.

    One retry on an unparsable reply, with a stricter prompt naming the bad
    reply — mirroring `pipeline/stages/extract.py`'s `_generate` shape. A
    judge call that raises `LlmError`, or a second unparsable reply, is
    recorded not-applicable with the raw reply (or the error) preserved —
    never silently passed and never a crash (the matrix's "recorded defect,
    not a crash").
    """
    from meetingminer.adapters.llm import LlmError

    citation_present = item.citation_present
    required_ok = contains_required_terms(item)
    if not citation_present:
        # `passed` is the AND of all four criteria, so a missing citation
        # already decides the verdict — no judge call is worth its cost on an
        # item that cannot pass regardless of what the model says.
        return RubricScore(
            passed=False,
            citation_present=False,
            contains_required_terms=required_ok,
            faithful=None,
            no_unsupported_claims=None,
            raw_reply=None,
            applicable=True,
            reason="citation absent — automatic fail, judge call skipped",
            model=None,
        )
    prompt = build_judge_prompt(item)
    try:
        reply = llm.complete(prompt)
    except LlmError as exc:
        return RubricScore(
            passed=False,
            citation_present=citation_present,
            contains_required_terms=required_ok,
            faithful=None,
            no_unsupported_claims=None,
            raw_reply=None,
            applicable=False,
            reason=f"the judge model could not answer: {exc}",
            model=None,
            call_failed=True,
        )
    parsed = _parse_judge_reply(reply.text)
    raw_reply = reply.text
    model = reply.model
    if parsed is None:
        try:
            retry = llm.complete(_stricter_prompt(item, reply.text))
        except LlmError as exc:
            return RubricScore(
                passed=False,
                citation_present=citation_present,
                contains_required_terms=required_ok,
                faithful=None,
                no_unsupported_claims=None,
                raw_reply=raw_reply,
                applicable=False,
                reason=(
                    "the judge reply was not valid JSON, and the retry call"
                    f" failed: {exc}"
                ),
                model=model,
                models=(model,),
                call_failed=True,
            )
        raw_reply = retry.text
        model = retry.model
        parsed = _parse_judge_reply(retry.text)
        if parsed is None:
            return RubricScore(
                passed=False,
                citation_present=citation_present,
                contains_required_terms=required_ok,
                faithful=None,
                no_unsupported_claims=None,
                raw_reply=raw_reply,
                applicable=False,
                reason="the judge reply was not valid JSON after one retry",
                model=model,
                models=(reply.model, model),
            )
    faithful = bool(parsed[FAITHFUL])
    no_unsupported = bool(parsed[NO_UNSUPPORTED_CLAIMS])
    passed = citation_present and required_ok and faithful and no_unsupported
    return RubricScore(
        passed=passed,
        citation_present=citation_present,
        contains_required_terms=required_ok,
        faithful=faithful,
        no_unsupported_claims=no_unsupported,
        raw_reply=raw_reply,
        reason=parsed["reason"],
        model=model,
        models=(reply.model, model) if "retry" in locals() else (model,),
    )


# --- building real items from the corpus and the public API ----------------


def _joined_transcript(segments: tuple[TranscriptSegment, ...]) -> str:
    return "\n".join(
        f"[{segment.speaker_label or 'Unknown'}] {segment.text}" for segment in segments
    )


def artifact_item(
    manifest_id: str | None,
    meeting_id: str,
    artifact: ArtifactRow,
    segments: tuple[TranscriptSegment, ...],
) -> JudgeItem:
    """One extraction item. ``citation_present`` is mechanically true: an
    `artifact` row cannot exist without a `moment_id` FK (0009_artifacts.sql)."""
    return JudgeItem(
        kind="artifact",
        item_id=artifact.id,
        meeting_id=meeting_id,
        manifest_id=manifest_id,
        candidate_text=f"{artifact.title}\n\n{artifact.body}",
        transcript=_joined_transcript(segments),
        citation_present=True,
    )


def qa_item(
    manifest_id: str,
    meeting_id: str,
    qa_entry: dict[str, Any],
    *,
    answer: str,
    citations_present: bool,
    segments: tuple[TranscriptSegment, ...],
) -> JudgeItem:
    """One cited-Q&A item, from a real `POST /chat` answer for the planted
    question. ``citation_present`` is the answer's citations array non-empty —
    the matrix's "no citation is an automatic fail", computed, never judged."""
    return JudgeItem(
        kind="qa",
        item_id=str(qa_entry.get("id", qa_entry.get("question", "qa"))),
        meeting_id=meeting_id,
        manifest_id=manifest_id,
        candidate_text=answer,
        transcript=_joined_transcript(segments),
        citation_present=citations_present,
        required_terms=tuple(qa_entry.get("answer_must_contain", ())),
    )


def ask_chat(base_url: str, question: str, *, timeout: float = 120.0) -> dict[str, Any]:
    """`POST /chat` for one planted question, returning the parsed JSON body.

    The same public-api read `subjects.fetch_meetings` uses for `GET
    /meetings` — no server module imported, an httpx call the only way this
    module reaches the running system.
    """
    url = f"{base_url.rstrip('/')}/chat"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url,
                json={"question": question},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise JudgeError(f"POST {url} failed for {question!r}: {exc}") from exc


def _write_yaml_once(path: Path, payload: dict[str, Any]) -> None:
    """Write once, refusing an existing file — atomically, not check-then-act.

    Serialization finishes in a temporary file before the final name is
    claimed. Linking the completed file into place fails atomically when a
    report already exists, so neither a serialization error nor a competing
    writer can leave an empty or partial immutable report behind.
    """
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise JudgeError(
                f"{path} already exists: a run folder is written once and never edited"
                " (eval-design §4.6)."
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _score_qa_items(
    llm: Any,
    corpus: Corpus,
    manifest_id: str,
    meeting_id: str,
    manifest: Manifest,
    *,
    api_base_url: str,
) -> list[tuple[JudgeItem, RubricScore]]:
    """One real `POST /chat` round trip and one score per manifest `qa` entry.

    A citation-free answer's judge call is skipped inside `score_with_llm`
    itself now — `citation_present=False` already forces `passed=False` (the
    AND of all four criteria), so nothing the model says can change the
    verdict. That check lives in exactly one place; this function just calls
    `score_with_llm` unconditionally.
    """
    results: list[tuple[JudgeItem, RubricScore]] = []
    for qa_entry in manifest.qa:
        body = ask_chat(api_base_url, str(qa_entry["question"]))
        citations = body.get("citations") or []
        answer = str(body.get("answer", ""))
        segments: tuple[TranscriptSegment, ...] = ()
        if citations:
            top_moment_id = citations[0].get("momentId")
            if top_moment_id:
                segments = corpus.segments_for_moment(str(top_moment_id))
        item = qa_item(
            manifest_id,
            meeting_id,
            qa_entry,
            answer=answer,
            citations_present=bool(citations),
            segments=segments,
        )
        results.append((item, score_with_llm(llm, item)))
    return results


def run_judge(
    run_folder: Path,
    meeting_ids: list[str],
    *,
    manifests: list[Manifest],
    api_base_url: str,
    config: Any,
) -> dict[str, Any]:
    """Score every requested meeting's qa/artifact items and write the report.

    Raises :class:`JudgeError` before writing anything if the run folder does
    not already exist (it is created earlier, by `evals-run`) or already
    carries `llm-judge-report.yaml`, or a requested meeting id matches no
    scripted subject (so there is no manifest to pull `qa` from).
    """
    from meetingminer.adapters.llm import build_llm

    from evals.harness.subjects import fetch_meetings, select_subjects

    folder = Path(run_folder)
    if not folder.is_dir():
        raise JudgeError(
            f"{folder} does not exist — run `evals-run` first to create the"
            " run folder this step judges into (eval-design §4.3)"
        )
    report_path = folder / REPORT_NAME
    if report_path.exists():
        raise JudgeError(f"{report_path} already exists: written once, never twice")

    selection = select_subjects(fetch_meetings(api_base_url), manifests)
    subject_by_meeting = {
        subject.meeting_id: subject
        for subject in selection.subjects
        if subject.meeting_id is not None
    }
    missing = [mid for mid in meeting_ids if mid not in subject_by_meeting]
    if missing:
        raise JudgeError(
            "the following --meeting-id values match no scripted eval subject,"
            f" so no manifest names their qa entries: {', '.join(missing)}"
        )

    binding = config.settings.llm.roles.judge
    llm = build_llm(binding, config.settings.providers, log=None)

    corpus = Corpus.from_config(config)
    scored: list[tuple[JudgeItem, RubricScore]] = []
    try:
        for meeting_id in meeting_ids:
            subject = subject_by_meeting[meeting_id]
            manifest = subject.manifest
            for artifact in corpus.artifacts_for(meeting_id):
                segments = corpus.segments_for_moment(artifact.moment_id)
                item = artifact_item(manifest.id, meeting_id, artifact, segments)
                scored.append((item, score_with_llm(llm, item)))
            scored.extend(
                _score_qa_items(
                    llm, corpus, manifest.id, meeting_id, manifest,
                    api_base_url=api_base_url,
                )
            )
    finally:
        corpus.close()

    #: The `Always` rule is "record the exact `LlmReply.model` string per
    #: call, not the configured role's nominal model" — each item's `model`
    #: (from `RubricScore.to_dict()`) already satisfies that. This is a
    #: run-level summary derived from those same per-call values, not a
    #: second, competing source of truth: the configured binding, for
    #: comparison, plus the distinct set of models that actually answered.
    answering_models = sorted(
        {model for _item, score in scored for model in score.models}
    )
    payload = {
        "story": "5.4 — LLM judge harness (eval-design §2.7)",
        "rubric": RUBRIC,
        "judge_configured_binding": {"model": binding.model, "fallback": binding.fallback},
        "judge_answering_models": answering_models,
        "items": [
            {**item.to_dict(), **score.to_dict()} for item, score in scored
        ],
    }
    _write_yaml_once(report_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score a real run's extracted artifacts and Q&A answers against"
            " rubric 2.7 (eval-design §2.7), writing llm-judge-report.yaml"
            " into an existing run folder. Manual, RUNBOOK-invoked: this"
            " calls the pinned config.settings.llm.roles.judge model, which"
            " may be a paid provider."
        )
    )
    parser.add_argument("run_folder", type=Path, help="an existing evals/runs/<run-id> folder")
    parser.add_argument(
        "--meeting-id",
        dest="meeting_ids",
        action="append",
        required=True,
        help="an ingested, scripted meeting id to score (repeatable)",
    )
    parser.add_argument(
        "--api-base-url",
        default="http://127.0.0.1:8000",
        help="where GET /meetings and POST /chat are read (default %(default)s)",
    )
    args = parser.parse_args(argv)

    from meetingminer.config import load_config

    from evals.harness.groundtruth import load_all

    config = load_config()
    manifests = load_all()
    # `--meeting-id` is repeatable; a duplicate id would trigger a duplicate
    # real `POST /chat` call and a duplicate scored item — a silent, real-money
    # duplicate spend. `dict.fromkeys` dedupes while preserving order.
    meeting_ids = list(dict.fromkeys(args.meeting_ids))
    try:
        run_judge(
            args.run_folder,
            meeting_ids,
            manifests=manifests,
            api_base_url=args.api_base_url,
            config=config,
        )
    except JudgeError as exc:
        parser.error(str(exc))
    except Exception as exc:  # noqa: BLE001 - operator-facing CLI, never a raw traceback
        parser.error(str(exc))
    print(f"{args.run_folder / REPORT_NAME}: written")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())
