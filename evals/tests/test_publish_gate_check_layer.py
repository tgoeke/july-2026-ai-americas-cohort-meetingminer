"""Store-free safety tests for check 2.11's orchestration layer.

The glue's own guarantees, exercised with no store, no api and no probe:
the remote-target guard runs before any read; a non-scripted tag refuses
before any store handle exists (so no probe row can ever be minted into
the real corpus); unreachable stores are a named blocking not-applicable;
and the happy path wires the read-only membership plus the probe into the
pure assembly with the run's own id.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from evals.checks import gate_probe, test_publish_gate
from evals.checks.test_publish_gate import test_publish_gate_projection as run_gate
from evals.harness import checks
from evals.harness.checks import ApproveOutcome, CleanupReport, GateProbe, StorePresence
from evals.harness.stores import StoreAssertError

MEETING = "11111111-1111-7111-8111-111111111111"
PROBE_ID = "dddddddd-dddd-7ddd-8ddd-dddddddddddd"
MOMENT = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"


class RecordingRun:
    run_id = "2026-08-30-check-layer"

    def __init__(self) -> None:
        self.results: list[Any] = []
        self.notes: list[str] = []

    def record(self, subject: object, result: Any) -> Any:
        self.results.append(result)
        return result

    def note(self, problem: str) -> None:
        self.notes.append(problem)


def a_subject() -> SimpleNamespace:
    return SimpleNamespace(
        meeting_id=MEETING,
        manifest=SimpleNamespace(id="demo-001"),
        job_id="job-1",
        status="succeeded",
    )


class UnreadCorpus:
    def __init__(self) -> None:
        self.read = False

    def meeting_corpus(self, meeting_id: str) -> str:
        self.read = True
        raise AssertionError("the remote-target guard must run before corpus reads")


class RemoteConfig:
    def getoption(self, name: str) -> str:
        assert name == "--api-base-url"
        return "https://eval.example"


class LocalConfig:
    def getoption(self, name: str) -> str:
        assert name == "--api-base-url"
        return "http://127.0.0.1:8000"


def test_publish_gate_refuses_a_remote_api_before_reading_or_approving() -> None:
    run = RecordingRun()
    corpus = UnreadCorpus()

    with pytest.raises(AssertionError):
        run_gate(run, a_subject(), corpus, object(), RemoteConfig())

    assert corpus.read is False
    assert len(run.results) == 1
    assert run.results[0].passed is False
    assert "not a loopback API target" in run.results[0].problems[0]


def test_a_non_scripted_tag_builds_no_store_handle_and_mints_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 11.3 sharpening of the corpus refusal: with the probe in the
    sequence, the refusal must now also come before any store handle — a
    handle is the first step toward a minted row in the real corpus."""

    def handle_built(*args: object, **kwargs: object) -> object:
        raise AssertionError("the tag refusal must run before any store handle")

    monkeypatch.setattr(test_publish_gate.stores, "search_client", handle_built)
    monkeypatch.setattr(test_publish_gate.stores, "graph_driver", handle_built)
    monkeypatch.setattr(
        gate_probe,
        "run_gate_probe",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("the tag refusal must run before the probe")
        ),
    )

    corpus = SimpleNamespace(
        meeting_corpus=lambda meeting_id: "real",
        artifacts_for=lambda meeting_id: (),
    )
    run = RecordingRun()

    with pytest.raises(AssertionError):
        run_gate(run, a_subject(), corpus, object(), LocalConfig())

    assert len(run.results) == 1
    assert run.results[0].passed is False
    assert "never approved by a machine" in run.results[0].problems[0]


def test_an_unreachable_store_is_a_named_blocking_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        test_publish_gate.stores,
        "search_client",
        lambda config: (_ for _ in ()).throw(
            StoreAssertError("Meilisearch could not be reached")
        ),
    )

    corpus = SimpleNamespace(
        meeting_corpus=lambda meeting_id: "scripted",
        artifacts_for=lambda meeting_id: (),
    )
    run = RecordingRun()

    with pytest.raises(AssertionError):
        run_gate(run, a_subject(), corpus, object(), LocalConfig())

    assert len(run.results) == 1
    result = run.results[0]
    assert result.passed is False
    assert result.applicable is False
    assert "Meilisearch could not be reached" in result.problems[0]
    assert run.notes, "the diagnosis must land in the run problems too"


class ClosableDriver:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_the_happy_path_wires_membership_and_the_probe_with_the_runs_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring, not behavior: membership keyed per subject artifact from the
    read-only helpers, the probe launched with this run's id and this
    subject's manifest, the driver closed, and a clean assembly passing."""
    driver = ClosableDriver()
    monkeypatch.setattr(
        test_publish_gate.stores, "search_client", lambda config: object()
    )
    monkeypatch.setattr(
        test_publish_gate.stores, "graph_driver", lambda config: driver
    )
    monkeypatch.setattr(
        test_publish_gate.stores,
        "artifact_in_search",
        lambda client, artifact_id: StorePresence(present=False),
    )
    monkeypatch.setattr(
        test_publish_gate.stores,
        "artifact_in_graph",
        lambda client, artifact_id: StorePresence(present=False),
    )

    probe_calls: list[dict[str, Any]] = []

    def canned_probe(**kwargs: Any) -> GateProbe:
        probe_calls.append(kwargs)
        absent = {
            checks.SEARCH_STORE: StorePresence(present=False),
            checks.GRAPH_STORE: StorePresence(present=False),
        }
        present = {
            checks.SEARCH_STORE: StorePresence(
                present=True, cited_moment_ids=(MOMENT,)
            ),
            checks.GRAPH_STORE: StorePresence(
                present=True, cited_moment_ids=(MOMENT,)
            ),
        }
        return GateProbe(
            artifact_id=PROBE_ID,
            moment_id=MOMENT,
            pre=absent,
            post=present,
            approve=ApproveOutcome(
                attempted=True, ok=True, published_ids=(PROBE_ID,)
            ),
            cleanup=CleanupReport(
                search_document_removed=True,
                graph_node_removed=True,
                export_file_removed=True,
                postgres_row_removed=True,
            ),
        )

    monkeypatch.setattr(gate_probe, "run_gate_probe", canned_probe)

    subject_artifact = SimpleNamespace(
        id="22222222-2222-7222-8222-222222222222",
        moment_id=MOMENT,
        state="extracted",
    )
    corpus = SimpleNamespace(
        meeting_corpus=lambda meeting_id: "scripted",
        artifacts_for=lambda meeting_id: (subject_artifact,),
    )
    run = RecordingRun()

    run_gate(run, a_subject(), corpus, object(), LocalConfig())

    assert len(run.results) == 1
    result = run.results[0]
    assert result.passed is True, result.problems
    assert result.metrics["artifacts"] == 1
    assert result.metrics["cleanup_verified"] is True
    assert driver.closed is True
    assert probe_calls and probe_calls[0]["run_id"] == RecordingRun.run_id
    assert probe_calls[0]["manifest_id"] == "demo-001"
    assert probe_calls[0]["meeting_id"] == MEETING


def test_a_later_subject_store_error_preserves_the_first_defect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F7: subject observations and their read error reach assembly together."""
    driver = ClosableDriver()
    monkeypatch.setattr(
        test_publish_gate.stores, "search_client", lambda config: object()
    )
    monkeypatch.setattr(
        test_publish_gate.stores, "graph_driver", lambda config: driver
    )
    monkeypatch.setattr(
        test_publish_gate.stores,
        "artifact_in_search",
        lambda client, artifact_id: StorePresence(present=False),
    )
    monkeypatch.setattr(
        test_publish_gate.stores,
        "artifact_in_graph",
        lambda client, artifact_id: (_ for _ in ()).throw(
            StoreAssertError("Neo4j failed after Meilisearch answered")
        ),
    )
    monkeypatch.setattr(
        gate_probe,
        "run_gate_probe",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("a partial subject read must not mint a probe")
        ),
    )
    subject_artifact = SimpleNamespace(
        id="22222222-2222-7222-8222-222222222222",
        moment_id=MOMENT,
        state="published",
    )
    corpus = SimpleNamespace(
        meeting_corpus=lambda meeting_id: "scripted",
        artifacts_for=lambda meeting_id: (subject_artifact,),
    )
    run = RecordingRun()

    with pytest.raises(AssertionError):
        run_gate(run, a_subject(), corpus, object(), LocalConfig())

    result = run.results[0]
    assert result.applicable
    assert any("absent from meilisearch" in problem for problem in result.problems)
    assert any("Neo4j failed after" in problem for problem in result.problems)
    assert driver.closed
