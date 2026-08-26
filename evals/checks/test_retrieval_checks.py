"""Check 2.10 — doc-index search recall@5 — against the live api (story 5.3).

The thin layer, same split as the capture checks: the queries go through the
public ``GET /search`` (`harness/retrieval.py` — never a raw Meilisearch
query, since the route is the surface under test), and the scoring is the
pure ``checks.search_recall`` over what came back. Nothing is computed here.

Store-backed and api-backed, read-only: one unfiltered search per planted
phrase, ``limit=5`` — the index gets no help. **These tests hold the shared
Docker stores — one agent at a time (AGENTS.md).**
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from evals.harness import checks, retrieval
from evals.harness.checks import CheckResult, PhraseSearch
from evals.harness.retrieval import RetrievalReadError
from evals.harness.run import Run
from evals.harness.subjects import Subject


def _record(
    run: Run,
    subject: Subject,
    name: str,
    compute: Callable[[], CheckResult],
) -> CheckResult:
    """Run a check, or record why the algorithm blew up, and report either way.

    The same shape as the capture checks' ``_record``, minus the capture
    ``Evidence`` gate: retrieval measurability is not capture measurability —
    a transcript-only subject has no captures but its planted phrases must
    still be findable, so ``has_recording`` never blocks this check. The
    retrieval-specific unmeasurable states (api refused, no meeting row) are
    recorded by the caller as named not-applicable results instead.
    """
    try:
        result = compute()
    except Exception as exc:
        failure = (
            f"{name} raised {type(exc).__name__}: {exc} — the check measured"
            " nothing, so its verdict is unknown rather than passing"
        )
        run.record(subject, checks.not_applicable(name, failure))
        run.note(failure)
        raise
    return run.record(subject, result)


def test_doc_index_search_recall(
    run: Run, subject: Subject, pytestconfig: pytest.Config
) -> None:
    """Check 2.10, threshold recall@5 = 1.0: every planted phrase must surface
    its containing meeting through the public search — verbatim plants, so the
    index has no excuse (eval-design §2.10)."""
    name = checks.DOC_INDEX_SEARCH_RECALL
    if subject.meeting_id is None:
        result = run.record(
            subject,
            checks.not_applicable(
                name,
                f"manifest {subject.manifest.id!r} matches job"
                f" {subject.job_id} (status {subject.status}), which has no"
                " meeting row yet — there is no meeting id for a hit to"
                " resolve to",
            ),
        )
        assert result.passed, result.summary()
        return

    base_url = pytestconfig.getoption("--api-base-url")
    phrases = tuple(subject.manifest.planted.get("phrases") or ())
    outcomes: dict[str, PhraseSearch] = {}
    unqueried: dict[str, str] = {}
    for index, phrase in enumerate(phrases):
        phrase_id = str(phrase.get("id", f"phrases[{index}]"))
        try:
            outcomes[phrase_id] = retrieval.search_hits(
                base_url, str(phrase.get("text", ""))
            )
        except RetrievalReadError as exc:
            # The api refused or could not answer this query (503
            # search-store-unavailable, embedder-unusable, a shape drift).
            # Captured per phrase, never loop-aborting: a refusal on phrase
            # three must not discard what phrases one and two measured.
            unqueried[phrase_id] = str(exc)
            run.note(
                f"check 2.10, manifest {subject.manifest.id!r}: phrase"
                f" {phrase_id!r} could not be queried: {exc}"
            )

    if phrases and not outcomes:
        # Nothing at all was measurable — the blocking not-applicable naming
        # every failing phrase; the diagnosis is already in the run problems
        # (the notes above).
        reason = (
            f"no planted phrase could be queried through {base_url} — the"
            " check measured nothing. Failures: "
            + "; ".join(f"{pid!r}: {why}" for pid, why in unqueried.items())
        )
        result = run.record(subject, checks.not_applicable(name, reason))
        assert result.passed, result.summary()
        return

    meeting_id = subject.meeting_id
    result = _record(
        run,
        subject,
        name,
        lambda: checks.search_recall(
            subject.manifest, meeting_id, outcomes, unqueried=unqueried
        ),
    )
    assert result.passed, result.summary()
