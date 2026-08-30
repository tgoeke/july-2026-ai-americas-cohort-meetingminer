"""Check 2.11 — publish-gate projection assert — against the live system.

The sequence per subject (eval-design §2.11, reshaped by story 11.3):
discover the meeting's artifacts and their lifecycle state through the
read-only corpus connection; assert every non-``published`` artifact is in
**neither** retrieval store and every ``published`` one is in **both** with
citations resolving (direct read-only Meilisearch/Neo4j reads — absence has
no api surface, AD-4); then measure the approve→project *transition* on one
run-owned probe artifact (``gate_probe.py``): minted onto an eligible
projected subject moment, approved through the public
``POST /moments/{id}/approve`` — the harness's one sanctioned mutation
(AD-16) — asserted in both stores, and erased with the cleanup verified.
Assembly and verdict are the pure ``checks.publish_gate``; this file only
observes and delegates.

What story 11.3 changed: **subject artifacts are never approved.** The
shared corpus's ``extracted`` rows survive every run, so two eval runs no
longer consume each other's gate half, and the run's one write lands in a
namespace it owns (the probe's title carries the run id) and erases on the
way out. These tests read the shared dev stores read-only otherwise and are
safe to run while another eval run or any suite is running.

Two standing cautions:

* **Only ``corpus: scripted`` meetings ever host a probe.** The tag is
  re-read from Postgres before any store handle is built or row minted;
  anything else is a named refusal — the real corpus is never approved by a
  machine, and never probed either.
* **A run killed outright can strand its probe.** The erasure runs even
  when the sequence is interrupted, but a process killed mid-probe leaves
  the row, whose body text tells the finder exactly what to remove.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from evals.checks import gate_probe
from evals.harness import checks, retrieval, stores
from evals.harness.checks import CheckResult, GateProbe, StorePresence
from evals.harness.corpus import Corpus, CorpusQueryError
from evals.harness.run import Run
from evals.harness.stores import StoreAssertError
from evals.harness.subjects import Subject


def _record(
    run: Run,
    subject: Subject,
    name: str,
    compute: Callable[[], CheckResult],
) -> CheckResult:
    """Record what the algorithm returned, or why it blew up — never neither."""
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


def _not_applicable(
    run: Run, subject: Subject, name: str, reason: str
) -> CheckResult:
    """A named blocking not-applicable, kept in the run's problems too."""
    run.note(reason)
    return run.record(subject, checks.not_applicable(name, reason))


def test_publish_gate_projection(
    run: Run,
    subject: Subject,
    corpus: Corpus,
    app_config: object,
    pytestconfig: pytest.Config,
) -> None:
    """Check 2.11: unpublished in neither store; published in both; the gate
    transition measured on the run-owned probe and erased behind it."""
    name = checks.PUBLISH_GATE_PROJECTION
    if subject.meeting_id is None:
        result = _not_applicable(
            run,
            subject,
            name,
            f"manifest {subject.manifest.id!r} matches job {subject.job_id}"
            f" (status {subject.status}), which has no meeting row yet — there"
            " are no artifacts to gate",
        )
        assert result.passed, result.summary()
        return
    meeting_id = subject.meeting_id
    base_url = pytestconfig.getoption("--api-base-url")
    if not retrieval.is_local_api_base_url(base_url):
        result = _not_applicable(
            run,
            subject,
            name,
            f"REFUSED: publish-gate check 2.11 only runs against a local API"
            f" because its direct Postgres, Meilisearch, and Neo4j reads use"
            f" this checkout's configured stores; {base_url!r} is not a"
            " loopback API target, so no store read, approval call or probe"
            " row was made",
        )
        assert result.passed, result.summary()
        return

    # The refusal guard, before anything else: the corpus tag re-read from the
    # database the probe would be minted into. Named failure, no api call, no
    # store handle, no row.
    try:
        tag = corpus.meeting_corpus(meeting_id)
        artifacts = corpus.artifacts_for(meeting_id)
    except CorpusQueryError as exc:
        result = _not_applicable(
            run,
            subject,
            name,
            f"could not read artifacts for meeting {meeting_id}: {exc}",
        )
        assert result.passed, result.summary()
        return
    refusal = checks.publish_gate_refusal(meeting_id, tag)
    if refusal is not None:
        # The refusal decision is pure and pinned store-free
        # (`tests/test_publish_gate_algorithm.py`); this glue only records
        # what it returned — thresholds and metrics included, like every
        # other 2.11 outcome.
        result = run.record(subject, refusal)
        assert result.passed, result.summary()
        return

    # The read-only store handles — needed even for a meeting with no
    # artifacts, because the probe still measures the gate transition (and
    # the no-artifacts branch stays a named blocking not-applicable in the
    # pure assembly). Unreachable stores are a named blocking not-applicable
    # with the diagnosis kept in the run problems — and any *other*
    # construction exception is recorded the same way and re-raised, so no
    # path through construction can leave the check silently absent from the
    # report (the 5-2 record-and-reraise shape).
    graph = None
    try:
        search = stores.search_client(app_config)
        graph = stores.graph_driver(app_config)
    except StoreAssertError as exc:
        result = _not_applicable(
            run,
            subject,
            name,
            f"a retrieval store cannot be read for meeting {meeting_id}:"
            f" {exc}",
        )
        assert result.passed, result.summary()
        return
    except Exception as exc:
        failure = (
            f"{name}: building a store handle raised {type(exc).__name__}:"
            f" {exc} — the check measured nothing, so its verdict is unknown"
            " rather than passing"
        )
        run.record(subject, checks.not_applicable(name, failure))
        run.note(failure)
        if graph is not None:
            graph.close()
        raise

    try:
        # The subject halves: one membership read per artifact, no mutation.
        membership: dict[str, dict[str, StorePresence]] = {}
        membership_problem: str | None = None
        try:
            for artifact in artifacts:
                artifact_id = str(artifact.id)
                recorded = membership.setdefault(artifact_id, {})
                recorded[checks.SEARCH_STORE] = stores.artifact_in_search(
                    search, artifact_id
                )
                recorded[checks.GRAPH_STORE] = stores.artifact_in_graph(
                    graph, artifact_id
                )
        except StoreAssertError as exc:
            membership_problem = (
                f"the subject membership read failed for meeting"
                f" {meeting_id}: {exc}"
            )
            run.note(membership_problem)

        # The probe and the assembly, inside the record-and-reraise shape:
        # the probe layer names its own refusals and interruptions on the
        # GateProbe (and erases whatever it minted either way); anything
        # that still raises — a database the mint cannot reach — is
        # recorded as measured-nothing and re-raised.
        result = _record(
            run,
            subject,
            name,
            lambda: checks.publish_gate(
                meeting_id,
                artifacts,
                membership,
                (
                    GateProbe(problem=membership_problem)
                    if membership_problem is not None
                    else gate_probe.run_gate_probe(
                        run_id=run.run_id,
                        manifest_id=subject.manifest.id,
                        meeting_id=meeting_id,
                        base_url=base_url,
                        config=app_config,
                        corpus=corpus,
                        search=search,
                        graph=graph,
                    )
                ),
            ),
        )
    finally:
        graph.close()

    assert result.passed, result.summary()
