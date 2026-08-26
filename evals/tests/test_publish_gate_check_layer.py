"""Store-free safety tests for check 2.11's orchestration layer."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from evals.checks.test_publish_gate import test_publish_gate_projection as run_gate


class RecordingRun:
    def __init__(self) -> None:
        self.results: list[Any] = []
        self.notes: list[str] = []

    def record(self, subject: object, result: Any) -> Any:
        self.results.append(result)
        return result

    def note(self, problem: str) -> None:
        self.notes.append(problem)


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


def test_publish_gate_refuses_a_remote_api_before_reading_or_approving() -> None:
    run = RecordingRun()
    corpus = UnreadCorpus()
    subject = SimpleNamespace(
        meeting_id="11111111-1111-7111-8111-111111111111",
        manifest=SimpleNamespace(id="demo-001"),
        job_id="job-1",
        status="succeeded",
    )

    with pytest.raises(AssertionError):
        run_gate(run, subject, corpus, object(), RemoteConfig())

    assert corpus.read is False
    assert len(run.results) == 1
    assert run.results[0].passed is False
    assert "not a loopback API target" in run.results[0].problems[0]
