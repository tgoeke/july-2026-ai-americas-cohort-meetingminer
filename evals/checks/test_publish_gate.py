"""Check 2.11 — publish-gate projection assert — against the live system.

The sequence per subject (eval-design §2.11, made precise in §2.11a): discover
the meeting's artifacts and their lifecycle state through the read-only corpus
connection; assert every non-``published`` artifact is in **neither** retrieval
store (direct read-only Meilisearch/Neo4j reads — absence has no api surface,
AD-4); approve through the public ``POST /moments/{id}/approve`` — the
harness's one sanctioned mutation (AD-16); assert every ``published`` artifact
is in **both** stores with citations resolving to its source moment. Assembly
and verdict are the pure ``checks.publish_gate``; this file only observes.

Two standing cautions:

* **This check mutates the shared corpus.** Approval is one-way — there is no
  unpublish — so a run consumes the subject's ``extracted`` artifacts and the
  next run records the gate half unmeasurable (RUNBOOK step 2 notes).
* **Only ``corpus: scripted`` meetings are ever approved.** The tag is re-read
  from Postgres before any api call; anything else is a named refusal — the
  real corpus is never approved by a machine.

**These tests hold the shared Docker stores — one agent at a time (AGENTS.md).**
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from evals.harness import checks, retrieval, stores
from evals.harness.checks import ApproveOutcome, CheckResult, StorePresence
from evals.harness.corpus import Corpus, CorpusQueryError
from evals.harness.retrieval import ApproveError
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
    """Check 2.11: unpublished in neither store; published in both, cited."""
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
            " loopback API target, so no store read or approval call was made",
        )
        assert result.passed, result.summary()
        return

    # The refusal guard, before anything else: the corpus tag re-read from the
    # database the approval would mutate. Named failure, no api call.
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

    if not artifacts:
        # `publish_gate` renders this as the blocking not-applicable naming
        # the meeting; no store connection is worth opening for it.
        result = _record(
            run,
            subject,
            name,
            lambda: checks.publish_gate(
                meeting_id, artifacts, {}, ApproveOutcome(attempted=False), {}
            ),
        )
        assert result.passed, result.summary()
        return

    # The read-only store handles. Unreachable stores are a named blocking
    # not-applicable with the diagnosis kept in the run problems — and any
    # *other* construction exception (a malformed URL, a driver surprise) is
    # recorded the same way and re-raised, so no path through construction
    # can leave the check silently absent from the report (the 5-2
    # record-and-reraise shape).
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

    def membership(artifact_id: str) -> dict[str, StorePresence]:
        return {
            checks.SEARCH_STORE: stores.artifact_in_search(search, artifact_id),
            checks.GRAPH_STORE: stores.artifact_in_graph(graph, artifact_id),
        }

    try:
        try:
            pre = {str(a.id): membership(str(a.id)) for a in artifacts}
        except StoreAssertError as exc:
            result = _not_applicable(
                run,
                subject,
                name,
                f"the pre-approval membership read failed for meeting"
                f" {meeting_id}: {exc}",
            )
            assert result.passed, result.summary()
            return

        # Approve: one call per moment that still holds an `extracted`
        # artifact, in discovery order. The harness's only mutation.
        moments_to_approve: list[str] = []
        for artifact in artifacts:
            moment_id = str(artifact.moment_id)
            if (
                artifact.state == checks.EXTRACTED_STATE
                and moment_id not in moments_to_approve
            ):
                moments_to_approve.append(moment_id)
        published_ids: list[str] = []
        if moments_to_approve:
            outcome_detail: str | None = None
            ok = True
            try:
                for moment_id in moments_to_approve:
                    returned = retrieval.approve_moment(base_url, moment_id)
                    published_ids.extend(
                        str(item["id"])
                        for item in returned
                        if item.get("state") == checks.PUBLISHED_STATE
                    )
            except ApproveError as exc:
                ok = False
                outcome_detail = str(exc)
            outcome = ApproveOutcome(
                attempted=True,
                ok=ok,
                detail=outcome_detail,
                published_ids=tuple(published_ids),
            )
        else:
            outcome = ApproveOutcome(attempted=False)

        post_ids = sorted(
            set(outcome.published_ids)
            | {
                str(a.id)
                for a in artifacts
                if a.state == checks.PUBLISHED_STATE
            }
        )
        try:
            post = {artifact_id: membership(artifact_id) for artifact_id in post_ids}
        except StoreAssertError as exc:
            result = _not_applicable(
                run,
                subject,
                name,
                f"the post-approval membership read failed for meeting"
                f" {meeting_id}: {exc} — the approval WAS attempted"
                f" ({outcome.attempted}), so rerun implications apply"
                " (RUNBOOK: the lifecycle is one-way)",
            )
            assert result.passed, result.summary()
            return
    finally:
        graph.close()

    result = _record(
        run,
        subject,
        name,
        lambda: checks.publish_gate(meeting_id, artifacts, pre, outcome, post),
    )
    assert result.passed, result.summary()
