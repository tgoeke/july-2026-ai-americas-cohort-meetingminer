"""``judge.py``'s `run_judge` orchestration and its CLI's `--meeting-id`
deduplication — store-free, against fakes for every collaborator (`Corpus`,
`ask_chat`, `subjects.fetch_meetings`/`select_subjects`, `build_llm`).

No test here makes a real Postgres connection, a real `POST /chat` call, or a
real model call — every one of `run_judge`'s collaborators is monkeypatched to
a fake, the same substitution discipline `test_judge_scoring.py` and
`test_bakeoff.py` already use for the `Llm` port.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml

from evals.harness import judge as judge_module
from evals.harness.corpus import ArtifactRow, TranscriptSegment, artifact_from_row
from evals.harness.groundtruth import Manifest
from evals.harness.judge import JudgeError, _write_yaml_once, main, run_judge
from evals.harness.subjects import Selection, Subject


@dataclass
class FakeReply:
    text: str
    model: str = "fake-judge-model"


@dataclass
class FakeLlm:
    replies: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def complete(self, prompt: str, options: object | None = None) -> FakeReply:
        self.calls.append(prompt)
        if not self.replies:
            raise AssertionError("FakeLlm ran out of scripted replies")
        return FakeReply(text=self.replies.pop(0))


def verdict_reply(*, faithful: bool = True, no_unsupported_claims: bool = True) -> str:
    return json.dumps(
        {
            "faithful": faithful,
            "no_unsupported_claims": no_unsupported_claims,
            "reason": "matches the transcript",
        }
    )


def make_manifest(*, manifest_id: str = "demo-001", qa: list[dict[str, Any]] | None = None) -> Manifest:
    return Manifest(
        data={
            "meeting": {
                "id": manifest_id,
                "source_id": "src-1",
                "title": "Orders Demo",
                "archetype": "ui-demo",
                "duration_minutes": 5,
            },
            "qa": qa or [],
        }
    )


def make_subject(meeting_id: str, manifest: Manifest) -> Subject:
    return Subject(
        manifest=manifest,
        source_id=manifest.source_id,
        job_id="job-1",
        meeting_id=meeting_id,
        title=manifest.title,
        status="succeeded",
        viewable=True,
    )


@dataclass
class FakeCorpus:
    artifacts: dict[str, tuple[ArtifactRow, ...]] = field(default_factory=dict)
    segments_by_moment: dict[str, tuple[TranscriptSegment, ...]] = field(default_factory=dict)
    closed: bool = False

    @classmethod
    def from_config(cls, config: Any) -> FakeCorpus:
        # Overwritten per-test by `install_fakes` to return the specific
        # pre-built instance a test wants `run_judge` to read from, rather
        # than a fresh empty one.
        return cls()

    def artifacts_for(self, meeting_id: str) -> tuple[ArtifactRow, ...]:
        return self.artifacts.get(meeting_id, ())

    def segments_for_moment(self, moment_id: str) -> tuple[TranscriptSegment, ...]:
        return self.segments_by_moment.get(moment_id, ())

    def close(self) -> None:
        self.closed = True


class FakeConfig:
    class settings:
        class llm:
            class roles:
                class judge:
                    model = "claude-sonnet-5"
                    fallback = None

        providers: dict[str, Any] = {}  # noqa: RUF012 - fixed-shape stand-in


def install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    subjects: tuple[Subject, ...],
    llm: FakeLlm,
    corpus: FakeCorpus,
    chat_bodies: dict[str, dict[str, Any]] | None = None,
    built_bindings: list[Any] | None = None,
) -> None:
    monkeypatch.setattr(
        "evals.harness.subjects.fetch_meetings", lambda api_base_url: ()
    )
    monkeypatch.setattr(
        "evals.harness.subjects.select_subjects",
        lambda meetings, manifests: Selection(subjects=subjects, unmatched=(), corpus_mismatches=()),
    )
    def fake_build_llm(binding: Any, *_args: Any, **_kwargs: Any) -> FakeLlm:
        if built_bindings is not None:
            built_bindings.append(binding)
        return llm

    monkeypatch.setattr("meetingminer.adapters.llm.build_llm", fake_build_llm)

    class _CorpusFactory:
        @staticmethod
        def from_config(config: Any) -> FakeCorpus:
            return corpus

    monkeypatch.setattr(judge_module, "Corpus", _CorpusFactory)

    bodies = chat_bodies or {}

    def fake_ask_chat(base_url: str, question: str, *, timeout: float = 120.0) -> dict[str, Any]:
        return bodies[question]

    monkeypatch.setattr(judge_module, "ask_chat", fake_ask_chat)


# --- refusals, before any collaborator is touched ---------------------------


def test_run_judge_refuses_a_missing_run_folder(tmp_path: Path) -> None:
    with pytest.raises(JudgeError, match="does not exist"):
        run_judge(
            tmp_path / "no-such-folder",
            ["m1"],
            manifests=[],
            api_base_url="http://fake",
            config=FakeConfig(),
        )


def test_run_judge_refuses_a_folder_that_already_has_a_report(tmp_path: Path) -> None:
    (tmp_path / "llm-judge-report.yaml").write_text("already: written\n")
    with pytest.raises(JudgeError, match="already exists"):
        run_judge(
            tmp_path,
            ["m1"],
            manifests=[],
            api_base_url="http://fake",
            config=FakeConfig(),
        )


def test_run_judge_refuses_a_meeting_id_matching_no_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fakes(monkeypatch, subjects=(), llm=FakeLlm(), corpus=FakeCorpus())
    with pytest.raises(JudgeError, match="no-such-meeting"):
        run_judge(
            tmp_path,
            ["no-such-meeting"],
            manifests=[],
            api_base_url="http://fake",
            config=FakeConfig(),
        )


# --- the happy path: one artifact item, one qa item -------------------------


def test_run_judge_writes_a_correctly_shaped_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = make_manifest(
        qa=[{"id": "Q1", "question": "What was decided?", "answer_must_contain": ["optimistic locking"]}]
    )
    subject = make_subject("meeting-1", manifest)
    corpus = FakeCorpus(
        artifacts={
            "meeting-1": (
                ArtifactRow(
                    id="artifact-1",
                    moment_id="moment-1",
                    kind="decision",
                    state="proposed",
                    title="Keep optimistic locking",
                    body="The team decided to keep optimistic locking.",
                ),
            )
        },
        segments_by_moment={
            "moment-1": (
                TranscriptSegment(
                    start_ms=0, end_ms=1000, speaker_label="Tim Goeke",
                    text="Orders module keeps optimistic locking.",
                ),
            )
        },
    )
    llm = FakeLlm(
        replies=[
            verdict_reply(),  # scores the artifact
            verdict_reply(),  # scores the qa answer
        ]
    )
    built_bindings: list[Any] = []
    install_fakes(
        monkeypatch,
        subjects=(subject,),
        llm=llm,
        corpus=corpus,
        chat_bodies={
            "What was decided?": {
                "answer": "The team kept optimistic locking.",
                "citations": [{"momentId": "moment-1"}],
            }
        },
        built_bindings=built_bindings,
    )

    payload = run_judge(
        tmp_path,
        ["meeting-1"],
        manifests=[manifest],
        api_base_url="http://fake",
        config=FakeConfig(),
    )

    assert corpus.closed is True
    assert built_bindings == [FakeConfig.settings.llm.roles.judge]
    assert len(payload["items"]) == 2
    kinds = {item["kind"] for item in payload["items"]}
    assert kinds == {"artifact", "qa"}
    for item in payload["items"]:
        assert item["passed"] is True
        assert item["citation_present"] is True
        assert item["model"] == "fake-judge-model"

    report_path = tmp_path / "llm-judge-report.yaml"
    assert report_path.exists()
    on_disk = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert on_disk == payload
    assert on_disk["judge_answering_models"] == ["fake-judge-model"]
    # never touches the deterministic report or Run.passed
    assert not (tmp_path / "deterministic-report.yaml").exists()


def test_run_judge_serializes_an_artifact_row_read_from_postgres(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_id = UUID("12345678-1234-5678-1234-567812345678")
    moment_id = UUID("87654321-4321-8765-4321-876543218765")
    artifact = artifact_from_row((artifact_id, moment_id, "adr", "proposed", "Title", "Body"))
    manifest = make_manifest()
    corpus = FakeCorpus(artifacts={"meeting-1": (artifact,)})
    install_fakes(
        monkeypatch,
        subjects=(make_subject("meeting-1", manifest),),
        llm=FakeLlm(replies=[verdict_reply()]),
        corpus=corpus,
    )

    payload = run_judge(
        tmp_path, ["meeting-1"], manifests=[manifest], api_base_url="http://fake", config=FakeConfig()
    )

    assert payload["items"][0]["item"] == str(artifact_id)
    assert yaml.safe_load((tmp_path / "llm-judge-report.yaml").read_text()) == payload


def test_a_failed_report_serialization_does_not_claim_the_final_path(tmp_path: Path) -> None:
    path = tmp_path / "llm-judge-report.yaml"
    with pytest.raises(yaml.representer.RepresenterError):
        _write_yaml_once(path, {"id": UUID("12345678-1234-5678-1234-567812345678")})
    assert not path.exists()


def test_run_judge_skips_the_model_call_for_an_uncited_qa_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = make_manifest(qa=[{"id": "Q1", "question": "Uncited?"}])
    subject = make_subject("meeting-1", manifest)
    corpus = FakeCorpus()
    llm = FakeLlm(replies=[])  # would raise if the judge call were made
    install_fakes(
        monkeypatch,
        subjects=(subject,),
        llm=llm,
        corpus=corpus,
        chat_bodies={"Uncited?": {"answer": "no citation here", "citations": []}},
    )

    payload = run_judge(
        tmp_path,
        ["meeting-1"],
        manifests=[manifest],
        api_base_url="http://fake",
        config=FakeConfig(),
    )

    (item,) = payload["items"]
    assert item["passed"] is False
    assert item["citation_present"] is False
    assert llm.calls == []


# --- main(): duplicate --meeting-id is deduped before any real call --------


def test_main_dedupes_duplicate_meeting_ids_before_calling_run_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repeated `--meeting-id` must not double a real `POST /chat` call and
    a real judge call — a silent, real-money duplicate spend."""
    captured: dict[str, Any] = {}

    def fake_run_judge(run_folder: Path, meeting_ids: list[str], **kwargs: Any) -> dict[str, Any]:
        captured["meeting_ids"] = meeting_ids
        return {}

    monkeypatch.setattr(judge_module, "run_judge", fake_run_judge)
    monkeypatch.setattr("meetingminer.config.load_config", lambda: FakeConfig())
    monkeypatch.setattr("evals.harness.groundtruth.load_all", list)

    exit_code = main(
        [
            str(tmp_path),
            "--meeting-id", "meeting-1",
            "--meeting-id", "meeting-1",
            "--meeting-id", "meeting-2",
        ]
    )

    assert exit_code == 0
    assert captured["meeting_ids"] == ["meeting-1", "meeting-2"]


def test_main_reports_an_unexpected_error_as_a_clean_cli_error_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def raises_unexpectedly(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(judge_module, "run_judge", raises_unexpectedly)
    monkeypatch.setattr("meetingminer.config.load_config", lambda: FakeConfig())
    monkeypatch.setattr("evals.harness.groundtruth.load_all", list)

    with pytest.raises(SystemExit) as excinfo:
        main([str(tmp_path), "--meeting-id", "meeting-1"])

    assert excinfo.value.code == 2
    assert "boom" in capsys.readouterr().err
