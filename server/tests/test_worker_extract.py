"""The `extract` stage through real worker runs: the story 4.1a I/O matrix.

DB-backed (skips with a named reason when the compose Postgres is down), and
model-free by construction: the autouse `_no_real_llm` fixture binds the stage
to a zero-artifact FakeLlm, and every test that wants proposals scripts its own
through `fake_llm` — no test here may reach a real provider or a real Ollama.

Extraction is whole-transcript and per *document*: the architecture summary and
the action items. A drop that carries a document has it adopted with **zero**
model calls; a document the drop lacks is generated. Both land artifacts
anchored by `[m:ss]` to the moment containing them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable
from uuid import UUID

import pytest
from psycopg_pool import ConnectionPool

from meetingminer import logs, projections
from meetingminer.adapters.llm import FallbackLlm, LlmUnavailableError
from meetingminer.config import AppConfig
from meetingminer.domain.drops import read_drop
from meetingminer.pipeline import runner
from meetingminer.pipeline.extraction import PROMPT_VERSION
from meetingminer.pipeline.stage import StageContext
from meetingminer.pipeline.stages import extract as extract_stage

from conftest import DROPS_ROOT, DropFactory, FakeEmbedder, FakeLlm, valid_metadata
from projection_seed import DEFAULT_TURNS, seed_meeting
from test_worker_runner import (
    enqueue,
    job_row,
    meetings,
    set_job_status,
    set_stage,
    stage_statuses,
)


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    from conftest import truncate_evidence

    truncate_evidence(test_pool)
    return test_pool


# Three turns spaced past the configured 20s gap, so the meeting cuts into
# three moments — enough to watch anchors land on *different* moments in one
# run, and to leave a moment with nothing anchored to it.
MULTI_MOMENT_TRANSCRIPT = (
    "[0:02] Goeke, Timothy: We will standardize on SFTP for the vendor feed.\n"
    "[0:40] Whitmore, Ellis: I will set up the credentials this week.\n"
    "[1:30] Goeke, Timothy: Nothing else to report today.\n"
)

# `[0:10]` falls in the first moment, `[0:45]` in the second, `[1:35]` in the
# third — the three moments the transcript above cuts into.
SUMMARY_DOC = """\
# Architecture summary — Data Hub Demo

## 3. Decisions made

| ID | Decision | Context and consequences | Mark | Timestamp |
|----|----------|--------------------------|------|-----------|
| **D1** | Standardize on SFTP | The vendor feed moves off the shared mailbox | Confirmed | [0:10] |
| D2 | Ops owns the credentials | Named during the walkthrough | Confirmed | *(0:45‑0:52)* |

## 7. Concerns / risks

| ID | Risk | Timestamp |
|----|------|-----------|
| R1 | Key rotation unowned | [0:50] |
"""

ACTIONS_DOC = """\
# Action Items — Data Hub Demo (6/10/26)

## Whitmore, Ellis

| ID | Action | Details / dependency | Timing (as stated) | Timestamp | Status |
|----|--------|----------------------|--------------------|-----------|--------|
| A1 | Set up the SFTP credentials | Needs the vendor key | this week | [1:35] | Committed |
"""

# The same two decisions rendered as bullets rather than a table — the
# `retrieval-prior-art.md` §8 regression, asserted end to end.
SUMMARY_DOC_BULLETS = """\
# Architecture summary — Data Hub Demo

## Decisions

- **D1** – Standardize on SFTP – The vendor feed moves off the shared mailbox – Confirmed – [0:10]
- D2 — Ops owns the credentials — Named during the walkthrough — Confirmed — *(0:45‑0:52)*
"""

# Parses cleanly, proposes nothing: a table header with no rows under it.
EMPTY_DOC = "## Decisions\n\n| ID | Decision | Timestamp |\n|----|----------|-----------|\n"

# Rows are plainly there and none of them is a decision — the no-silent-zero
# shape the stage must report by name.
ZERO_YIELD_DOC = """\
## Decisions and open questions

| ID | Item | Timestamp |
|----|------|-----------|
| O1 | Who owns key rotation | [0:12] |
| R1 | Vendor key expiry unknown | [0:44] |
"""


@pytest.fixture()
def make_transcript_drop(make_drop: DropFactory) -> Callable[..., Any]:
    """A transcript-only drop, optionally carrying the extraction documents.

    Story-local rather than folded into the shared `make_drop`: the shared
    conftest block is a known cross-story conflict point, and only extraction
    cares about these two files.
    """

    def _make(
        source_id: str, *, summary: str | None = None, actions: str | None = None
    ) -> Any:
        drop = make_drop(metadata=valid_metadata(source_id), files=())
        (drop / "transcript.txt").write_text(MULTI_MOMENT_TRANSCRIPT, encoding="utf-8")
        if summary is not None:
            (drop / "extraction-summary.md").write_text(summary, encoding="utf-8")
        if actions is not None:
            (drop / "extraction-action-items.md").write_text(actions, encoding="utf-8")
        return drop

    return _make


def moment_ids(pool: ConnectionPool, meeting_id: UUID) -> list[UUID]:
    with pool.connection() as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT id FROM moment WHERE meeting_id = %s ORDER BY start_ms, id",
                (meeting_id,),
            ).fetchall()
        ]


def artifact_rows(pool: ConnectionPool, meeting_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, moment_id, kind, state, title, body, provenance"
            " FROM artifact WHERE meeting_id = %s ORDER BY created_at, id",
            (meeting_id,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "moment_id": row[1],
            "kind": row[2],
            "state": row[3],
            "title": row[4],
            "body": row[5],
            "provenance": row[6],
        }
        for row in rows
    ]


def extraction_sources(pool: ConnectionPool, meeting_id: UUID) -> dict[str, dict[str, Any]]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT kind, origin, drop_relative_path, sha256, byte_size, layout,"
            " item_count, artifact_count, model, prompt_version, prompt_hash"
            " FROM extraction_source WHERE meeting_id = %s",
            (meeting_id,),
        ).fetchall()
    return {
        row[0]: {
            "origin": row[1],
            "drop_relative_path": row[2],
            "sha256": row[3],
            "byte_size": row[4],
            "layout": row[5],
            "item_count": row[6],
            "artifact_count": row[7],
            "model": row[8],
            "prompt_version": row[9],
            "prompt_hash": row[10],
        }
        for row in rows
    }


def log_events(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]


def summary_event(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    [record] = [
        record
        for record in log_events(capsys)
        if record["event"] == "stage.extract.summary"
    ]
    return record


def requeue_extract(pool: ConnectionPool, job_id: UUID) -> None:
    set_stage(pool, job_id, "extract", "queued")
    set_job_status(pool, job_id, "queued")


# The evidence tables the stage must never touch (NFR5): row counts across an
# extract run are the invariant.
EVIDENCE_COUNT_TABLES = (
    "moment",
    "transcript_segment",
    "screenshot",
    "frame",
    "meeting_participant",
)


def evidence_counts(pool: ConnectionPool, meeting_id: UUID) -> dict[str, int]:
    with pool.connection() as conn:
        return {
            table: conn.execute(
                f"SELECT count(*) FROM {table} WHERE meeting_id = %s", (meeting_id,)
            ).fetchone()[0]
            for table in EVIDENCE_COUNT_TABLES
        }


# --- adopt: the drop already carries what a model would have produced -------


def test_adopting_both_documents_makes_no_model_call_and_records_both_sources(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """AC 1: zero calls, artifacts anchored to their moments, AD-17 source rows.

    A transcript-only drop on purpose (AD-1): extraction behaves identically
    with the video stages `skipped`, and that is the shape the real corpus is
    in.
    """
    engine = fake_llm()
    drop = make_transcript_drop("source-adopt", summary=SUMMARY_DOC, actions=ACTIONS_DOC)
    job_id = enqueue(pool, drop, "source-adopt")

    assert runner.run_once(pool, app_config, content_root) is True

    statuses = stage_statuses(pool, job_id)
    assert statuses["moments"] == "done"
    assert statuses["extract"] == "done"
    assert job_row(pool, job_id) == ("done", None)
    # The whole point of adoption: a derivative document already exists, so
    # nothing is asked of a model for it. The topics document (story 10.1)
    # has no adoption path, so exactly one call went out — the topics one.
    [topics_call] = engine.calls
    assert "## Topics" in topics_call

    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])
    assert len(moments) == 3

    rows = artifact_rows(pool, meeting["id"])
    # `[0:10]` is in moment 0, `[0:45]` in moment 1, `[1:35]` in moment 2.
    assert [(row["kind"], row["title"], row["moment_id"]) for row in rows] == [
        ("adr", "Standardize on SFTP", moments[0]),
        ("adr", "Ops owns the credentials", moments[1]),
        ("action-item", "Set up the SFTP credentials", moments[2]),
    ]
    for row in rows:
        assert row["state"] == "extracted"
        assert row["provenance"]["source"] == "adopted"
        assert row["provenance"]["model"] is None
        assert row["provenance"]["prompt_version"] is None
        assert row["provenance"]["prompt_hash"] is None
        assert row["provenance"]["layout"] == "table"
    assert rows[0]["provenance"]["anchor_ms"] == 10_000
    assert rows[0]["provenance"]["document_kind"] == "arch-summary"
    assert rows[2]["provenance"]["document_kind"] == "action-items"

    sources = extraction_sources(pool, meeting["id"])
    assert set(sources) == {"arch-summary", "action-items", "topics"}
    assert sources["topics"]["origin"] == "generated"
    assert sources["arch-summary"] == {
        "origin": "adopted",
        "drop_relative_path": f"{drop.name}/extraction-summary.md",
        "sha256": hashlib.sha256(SUMMARY_DOC.encode()).hexdigest(),
        "byte_size": len(SUMMARY_DOC.encode()),
        "layout": "table",
        "item_count": 2,
        "artifact_count": 2,
        "model": None,
        "prompt_version": None,
        "prompt_hash": None,
    }
    assert sources["action-items"]["drop_relative_path"] == (
        f"{drop.name}/extraction-action-items.md"
    )
    assert sources["action-items"]["artifact_count"] == 1


def test_the_bullet_layout_adopts_to_the_same_artifacts_as_the_table_layout(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """AC 3 end to end — the `retrieval-prior-art.md` §8 regression."""
    fake_llm()
    job_id = enqueue(
        pool,
        make_transcript_drop(
            "source-bullets", summary=SUMMARY_DOC_BULLETS, actions=ACTIONS_DOC
        ),
        "source-bullets",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])
    rows = artifact_rows(pool, meeting["id"])
    assert [(row["kind"], row["title"], row["moment_id"]) for row in rows] == [
        ("adr", "Standardize on SFTP", moments[0]),
        ("adr", "Ops owns the credentials", moments[1]),
        ("action-item", "Set up the SFTP credentials", moments[2]),
    ]
    assert extraction_sources(pool, meeting["id"])["arch-summary"]["layout"] == "bullet"


# --- generate: the drop carries neither, or only one ------------------------


def test_generating_both_documents_makes_one_call_per_document_kind(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """AC 2: the whole timestamped transcript goes out once per document kind."""
    engine = fake_llm(replies=(SUMMARY_DOC, ACTIONS_DOC))
    job_id = enqueue(pool, make_transcript_drop("source-generate"), "source-generate")

    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    assert len(engine.calls) == 3
    for call in engine.calls:
        # The *whole* transcript, not one moment's slice.
        assert "[0:02] Goeke, Timothy: We will standardize on SFTP" in call
        assert "[1:30] Goeke, Timothy: Nothing else to report today." in call
    assert "## Decisions" in engine.calls[0]
    assert "## Action items" in engine.calls[1]
    assert "## Topics" in engine.calls[2]
    # The grounding both prompts depend on. Without the date line, models
    # invent calendar due dates for vague commitments like "next week"; a
    # `_meeting_date` that returned "" or reformatted would ship silently
    # mis-grounded prompts with every test still green.
    for call in engine.calls:
        assert "Meeting: Daily Standup" in call
        assert "This meeting took place on 8/5/2026." in call
    # The role's context window reached the port (config.yaml `num_ctx`),
    # because Ollama's default would silently truncate a long transcript.
    binding = app_config.settings.llm.roles.extraction
    for options in engine.options:
        assert options is not None
        assert options.num_ctx == binding.num_ctx
        assert options.timeout_seconds == binding.timeout_seconds

    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])
    rows = artifact_rows(pool, meeting["id"])
    # Indistinguishable in shape from the adopted ones: same kinds, same
    # titles, same moments.
    assert [(row["kind"], row["title"], row["moment_id"]) for row in rows] == [
        ("adr", "Standardize on SFTP", moments[0]),
        ("adr", "Ops owns the credentials", moments[1]),
        ("action-item", "Set up the SFTP credentials", moments[2]),
    ]
    arch_summary_hash = hashlib.sha256(binding.arch_summary_prompt.encode()).hexdigest()[:16]
    action_items_hash = hashlib.sha256(binding.action_items_prompt.encode()).hexdigest()[:16]
    for row in rows:
        assert row["provenance"]["source"] == "generated"
        assert row["provenance"]["model"] == "fake-llm"
        assert row["provenance"]["prompt_version"] == PROMPT_VERSION
        expected_hash = (
            arch_summary_hash
            if row["provenance"]["document_kind"] == "arch-summary"
            else action_items_hash
        )
        assert row["provenance"]["prompt_hash"] == expected_hash

    sources = extraction_sources(pool, meeting["id"])
    for kind, text, prompt_hash in (
        ("arch-summary", SUMMARY_DOC, arch_summary_hash),
        ("action-items", ACTIONS_DOC, action_items_hash),
    ):
        assert sources[kind]["origin"] == "generated"
        # No drop file, so no path — but the bytes that were parsed are still
        # identified, so a rerun can prove whether the input changed.
        assert sources[kind]["drop_relative_path"] is None
        assert sources[kind]["sha256"] == hashlib.sha256(text.encode()).hexdigest()
        assert sources[kind]["model"] == "fake-llm"
        assert sources[kind]["prompt_version"] == PROMPT_VERSION
        assert sources[kind]["prompt_hash"] == prompt_hash


def test_a_different_configured_prompt_changes_the_hash_not_the_prompt_version(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """Story 4.2: a config-only prompt edit is not a code change and must not
    bump `PROMPT_VERSION` — but it must change `prompt_hash`, since that is
    the field that lets an eval harness or a reviewer tell two prompt-config
    edits apart."""
    fake_llm(replies=(SUMMARY_DOC, ACTIONS_DOC))
    edited = app_config.model_copy(deep=True)
    edited.settings.llm.roles.extraction.arch_summary_prompt += (
        "\n\nEdited for this test only."
    )
    job_id = enqueue(
        pool, make_transcript_drop("source-edited-prompt"), "source-edited-prompt"
    )
    assert runner.run_once(pool, edited, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    [meeting] = meetings(pool, job_id)
    sources = extraction_sources(pool, meeting["id"])
    edited_binding = edited.settings.llm.roles.extraction
    expected_hash = hashlib.sha256(
        edited_binding.arch_summary_prompt.encode()
    ).hexdigest()[:16]
    default_hash = hashlib.sha256(
        app_config.settings.llm.roles.extraction.arch_summary_prompt.encode()
    ).hexdigest()[:16]
    assert sources["arch-summary"]["prompt_hash"] == expected_hash
    assert sources["arch-summary"]["prompt_hash"] != default_hash
    # The parser-contract version is unaffected by a text-only prompt edit.
    assert sources["arch-summary"]["prompt_version"] == PROMPT_VERSION

    # Symmetric proof for the other document: editing `action_items_prompt`
    # alone (a fresh copy, `arch_summary_prompt` back at its committed
    # default) changes only the action-items hash, leaves the untouched
    # arch-summary document's hash at its own default value, and bumps
    # neither document's `prompt_version`.
    fake_llm(replies=(SUMMARY_DOC, ACTIONS_DOC))
    edited_actions = app_config.model_copy(deep=True)
    edited_actions.settings.llm.roles.extraction.action_items_prompt += (
        "\n\nEdited for this test only, actions side."
    )
    actions_job_id = enqueue(
        pool,
        make_transcript_drop("source-edited-actions-prompt"),
        "source-edited-actions-prompt",
    )
    assert runner.run_once(pool, edited_actions, content_root) is True
    assert job_row(pool, actions_job_id) == ("done", None)

    [actions_meeting] = meetings(pool, actions_job_id)
    actions_sources = extraction_sources(pool, actions_meeting["id"])
    edited_actions_binding = edited_actions.settings.llm.roles.extraction
    expected_actions_hash = hashlib.sha256(
        edited_actions_binding.action_items_prompt.encode()
    ).hexdigest()[:16]
    default_actions_hash = hashlib.sha256(
        app_config.settings.llm.roles.extraction.action_items_prompt.encode()
    ).hexdigest()[:16]
    assert actions_sources["action-items"]["prompt_hash"] == expected_actions_hash
    assert actions_sources["action-items"]["prompt_hash"] != default_actions_hash
    # The untouched document's hash still matches the committed default —
    # editing one document's prompt never perturbs the other's.
    assert actions_sources["arch-summary"]["prompt_hash"] == default_hash
    assert actions_sources["arch-summary"]["prompt_version"] == PROMPT_VERSION
    assert actions_sources["action-items"]["prompt_version"] == PROMPT_VERSION


def test_a_drop_carrying_one_document_adopts_it_and_generates_the_other(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """Adoption is decided per document kind, not per drop."""
    engine = fake_llm(replies=(SUMMARY_DOC,))
    job_id = enqueue(
        pool,
        make_transcript_drop("source-mixed", actions=ACTIONS_DOC),
        "source-mixed",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    # Two calls: the summary, and the topics document (story 10.1, always
    # generated). The action items arrived in the drop.
    assert len(engine.calls) == 2
    assert "## Decisions" in engine.calls[0]
    assert "## Topics" in engine.calls[1]

    [meeting] = meetings(pool, job_id)
    sources = extraction_sources(pool, meeting["id"])
    assert sources["arch-summary"]["origin"] == "generated"
    assert sources["action-items"]["origin"] == "adopted"
    by_kind = {row["kind"]: row for row in artifact_rows(pool, meeting["id"])}
    # Provenance records each artifact's own source, not the meeting's.
    assert by_kind["adr"]["provenance"]["source"] == "generated"
    assert by_kind["action-item"]["provenance"]["source"] == "adopted"


# --- anchoring --------------------------------------------------------------


def test_an_anchor_outside_the_timeline_fails_the_job_naming_the_artifact(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """AC 5: never silently dropped — a fabricated timestamp fails the meeting."""
    fake_llm()
    stray = SUMMARY_DOC.replace("[0:10]", "[59:59]")
    job_id = enqueue(
        pool,
        make_transcript_drop("source-anchor", summary=stray, actions=ACTIONS_DOC),
        "source-anchor",
    )

    assert runner.run_once(pool, app_config, content_root) is True

    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "stage extract failed" in error
    assert "D1" in error and "Standardize on SFTP" in error
    assert "59:59" in error and "falls outside" in error
    assert stage_statuses(pool, job_id)["extract"] == "failed"
    [meeting] = meetings(pool, job_id)
    # The failed stage's transaction rolled back: no half-meeting of drafts.
    assert artifact_rows(pool, meeting["id"]) == []
    assert extraction_sources(pool, meeting["id"]) == {}


# --- the no-silent-zero signal ----------------------------------------------


def test_a_document_whose_populated_section_yields_nothing_is_named(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC 4: a zero over plainly populated input is a signal, not a plain success."""
    fake_llm()
    job_id = enqueue(
        pool,
        make_transcript_drop(
            "source-zero", summary=ZERO_YIELD_DOC, actions=EMPTY_DOC
        ),
        "source-zero",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    [meeting] = meetings(pool, job_id)
    assert artifact_rows(pool, meeting["id"]) == []
    records = log_events(capsys)
    zeros = [r for r in records if r["event"] == "stage.extract.zero_artifacts"]
    # The summary carried rows and produced nothing — named. The action
    # document carried a bare header and nothing else, which is an honest
    # "nothing here" rather than a silent zero, so it is not named.
    assert [r["document"] for r in zeros] == ["arch-summary"]
    assert zeros[0]["populated_sections"] == ["Decisions and open questions"]
    assert zeros[0]["origin"] == "adopted"
    [summary] = [r for r in records if r["event"] == "stage.extract.summary"]
    assert summary["artifacts"] == {"action-item": 0, "adr": 0}
    assert summary["adopted"] == 2, "both artifact documents came from the drop"
    assert summary["generated"] == 1, "the topics document is always generated"


# --- idempotence (AD-11): drafts are replaced, approval is untouchable ------


def test_a_rerun_replaces_drafts_and_leaves_the_approved_moment_alone(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC 7: an approved moment's whole artifact set survives — drafts included.

    The first moment ends the rerun in the mixed state that matters: one
    `approved` artifact plus one still-`extracted` sibling draft on the same
    moment. Both must come through untouched — a draft delete scoped only by
    meeting would destroy the sibling permanently, because nothing is then
    proposed onto an approved moment to replace it.
    """
    two_on_the_first_moment = SUMMARY_DOC.replace("*(0:45‑0:52)*", "[0:12]")
    fake_llm()
    job_id = enqueue(
        pool,
        make_transcript_drop(
            "source-rerun", summary=two_on_the_first_moment, actions=ACTIONS_DOC
        ),
        "source-rerun",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])
    first = artifact_rows(pool, meeting["id"])
    assert [(row["kind"], row["moment_id"]) for row in first] == [
        ("adr", moments[0]),
        ("adr", moments[0]),
        ("action-item", moments[2]),
    ]

    # A human approved the first moment's first ADR through what will be the
    # story 4.3 endpoint, leaving its sibling still a pending draft. Test
    # isolation writes the state column directly; the *stage* never does.
    approved_id = first[0]["id"]
    with pool.connection() as conn:
        conn.execute(
            "UPDATE artifact SET state = 'approved' WHERE id = %s", (approved_id,)
        )
    sibling_draft = first[1]

    capsys.readouterr()
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True

    assert job_row(pool, job_id) == ("done", None)
    after = artifact_rows(pool, meeting["id"])
    # The approved row survives verbatim...
    assert [row["id"] for row in after if row["state"] == "approved"] == [approved_id]
    # ...and so does its sibling draft: same id, still a draft, neither deleted
    # nor re-proposed.
    assert [
        row for row in after if row["moment_id"] == moments[0] and row["id"] != approved_id
    ] == [sibling_draft]
    # The third moment's draft was replaced by a new row.
    replaced = [row for row in after if row["moment_id"] == moments[2]]
    assert len(replaced) == 1
    assert replaced[0]["id"] != first[2]["id"]

    summary = summary_event(capsys)
    assert summary["skipped_approved"] == 2, "both anchors on the approved moment"
    assert summary["drafts_replaced"] == 1, "only the unapproved moment's draft"


def test_the_stage_writes_only_artifact_and_extraction_source_rows(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """NFR5: an extract rerun leaves every evidence table's count where it was."""
    fake_llm()
    job_id = enqueue(
        pool,
        make_transcript_drop("source-nfr5", summary=SUMMARY_DOC, actions=ACTIONS_DOC),
        "source-nfr5",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)

    before = evidence_counts(pool, meeting["id"])
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True
    assert evidence_counts(pool, meeting["id"]) == before
    # The source rows are upserted, never accumulated — three kinds now that
    # the topics document (story 10.1) writes its own.
    assert len(extraction_sources(pool, meeting["id"])) == 3


# --- malformed documents: retry on generate, never on adopt -----------------


def test_a_generated_document_that_will_not_parse_is_retried_once(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    engine = fake_llm(replies=("no table and no bullets anywhere", SUMMARY_DOC, ACTIONS_DOC))
    job_id = enqueue(pool, make_transcript_drop("source-retry"), "source-retry")

    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    # Four calls over three documents: the summary took two.
    assert len(engine.calls) == 4
    assert engine.calls[0] == engine.calls[1], "the retry re-sends the same prompt"
    [meeting] = meetings(pool, job_id)
    assert len(artifact_rows(pool, meeting["id"])) == 3


def test_a_generated_unrelated_table_is_retried_once(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    unrelated = """\
# Notes

| Topic | Detail |
|-------|--------|
| Hosting | The plan is documented elsewhere |
"""
    engine = fake_llm(replies=(unrelated, SUMMARY_DOC, ACTIONS_DOC))
    job_id = enqueue(pool, make_transcript_drop("source-unrelated-generated"), "source-unrelated-generated")

    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    assert len(engine.calls) == 4
    assert engine.calls[0] == engine.calls[1]


def test_a_second_unusable_reply_fails_the_job_naming_extract_and_the_document(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    fake_llm(replies=("nothing parseable here", "still nothing parseable"))
    job_id = enqueue(pool, make_transcript_drop("source-badllm"), "source-badllm")

    assert runner.run_once(pool, app_config, content_root) is True

    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "stage extract failed" in error
    assert "arch-summary" in error
    assert "unusable after a retry" in error
    assert stage_statuses(pool, job_id)["extract"] == "failed"
    [meeting] = meetings(pool, job_id)
    assert artifact_rows(pool, meeting["id"]) == []


def test_an_adopted_document_that_will_not_parse_fails_without_a_retry(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """Re-reading the same bytes cannot parse differently, so there is no retry."""
    engine = fake_llm()
    unanchored = SUMMARY_DOC.replace("[0:10]", "no timestamp at all")
    job_id = enqueue(
        pool,
        make_transcript_drop("source-badfile", summary=unanchored, actions=ACTIONS_DOC),
        "source-badfile",
    )

    assert runner.run_once(pool, app_config, content_root) is True

    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None
    assert "extraction-summary.md" in error
    assert "D1" in error and "no [m:ss] anchor" in error
    # Nothing was asked of a model — not even a retry.
    assert engine.calls == []


def test_an_adopted_unrelated_table_fails_without_a_model_call(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    unrelated = """\
# Notes

| Topic | Detail |
|-------|--------|
| Hosting | The plan is documented elsewhere |
"""
    engine = fake_llm()
    job_id = enqueue(
        pool,
        make_transcript_drop("source-unrelated-adopted", summary=unrelated, actions=ACTIONS_DOC),
        "source-unrelated-adopted",
    )

    assert runner.run_once(pool, app_config, content_root) is True

    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "recognized target section" in error
    assert engine.calls == []


def test_a_declared_document_the_drop_does_not_carry_fails_by_name(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_drop: DropFactory,
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """The schema's fail-closed version gate has to buy something.

    Deciding adoption on file presence alone meant a drop that *declares* a
    document whose file is missing quietly took the generate path and spent a
    model pass re-deriving work the drop said it had already done — while
    looking, in every log line, exactly like a drop that never had one.
    """
    engine = fake_llm()
    metadata = valid_metadata(
        "source-declared",
        schemaVersion=3,
        extractions={
            "archSummary": "extraction-summary.md",
            "actionItems": "extraction-action-items.md",
        },
    )
    drop = make_drop(metadata=metadata, files=())
    (drop / "transcript.txt").write_text(MULTI_MOMENT_TRANSCRIPT, encoding="utf-8")
    # Only one of the two declared documents is actually there.
    (drop / "extraction-action-items.md").write_text(ACTIONS_DOC, encoding="utf-8")
    job_id = enqueue(pool, drop, "source-declared")

    assert runner.run_once(pool, app_config, content_root) is True

    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None
    assert "metadata.extractions.archSummary" in error
    assert "extraction-summary.md" in error
    assert engine.calls == [], "and no model pass was spent discovering it"


def test_a_drop_that_carries_a_document_without_declaring_it_is_still_adopted(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """The pre-declaration shape: every drop emitted before `extractions` existed."""
    engine = fake_llm()
    job_id = enqueue(
        pool,
        make_transcript_drop(
            "source-undeclared", summary=SUMMARY_DOC, actions=ACTIONS_DOC
        ),
        "source-undeclared",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    # Both artifact documents adopted; the one call is the topics pass.
    [topics_call] = engine.calls
    assert "## Topics" in topics_call


def test_an_extraction_document_that_is_not_utf8_is_a_named_refusal(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    """A lossy decode would put U+FFFD into titles under a correct checksum."""
    fake_llm()
    drop = make_transcript_drop("source-badbytes", actions=ACTIONS_DOC)
    (drop / "extraction-summary.md").write_bytes(
        b"## Decisions\n\n| D1 | Vendor feeds move to \xff\xfe SFTP | [0:10] |\n"
    )
    job_id = enqueue(pool, drop, "source-badbytes")

    assert runner.run_once(pool, app_config, content_root) is True

    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None
    assert "extraction-summary.md" in error and "not valid UTF-8" in error


def test_a_document_that_parsed_items_but_inserted_none_says_both_numbers(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`artifact_count` alone could not tell a discard from a parse failure.

    Both decisions anchor onto the first moment, a human approves one artifact
    there, and the rerun parses two items and inserts neither — which must not
    read as "this document parsed nothing".
    """
    both_on_the_first_moment = SUMMARY_DOC.replace("*(0:45‑0:52)*", "[0:12]")
    fake_llm()
    job_id = enqueue(
        pool,
        make_transcript_drop(
            "source-counts", summary=both_on_the_first_moment, actions=ACTIONS_DOC
        ),
        "source-counts",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    first = artifact_rows(pool, meeting["id"])
    with pool.connection() as conn:
        conn.execute(
            "UPDATE artifact SET state = 'approved' WHERE id = %s", (first[0]["id"],)
        )

    capsys.readouterr()
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True

    summary_source = extraction_sources(pool, meeting["id"])["arch-summary"]
    assert summary_source["item_count"] == 2, "the parser found both decisions"
    assert summary_source["artifact_count"] == 0, "and neither became a row"

    # And each discard is named, not merely counted: an operator deciding
    # whether to re-open a moment needs to know which item, not how many.
    records = log_events(capsys)
    discarded = [
        r for r in records if r["event"] == "stage.extract.artifact_discarded"
    ]
    assert {r["item_id"] for r in discarded} == {"D1", "D2"}
    assert {r["reason"] for r in discarded} == {"approved-moment"}
    assert all(r["document"] == "arch-summary" for r in discarded)


# --- fallback (AD-8): engaged at call time, recorded in provenance ----------


def test_an_unavailable_primary_engages_the_fallback_for_the_whole_meeting(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = FakeLlm(
        replies=(LlmUnavailableError("the local host is not answering (test)"),),
        model="primary-model",
    )
    fallback = FakeLlm(replies=(SUMMARY_DOC, ACTIONS_DOC), model="fallback-model")

    def _build(_binding: Any, _providers: Any, log: Any = None) -> FallbackLlm:
        return FallbackLlm(primary, fallback, log=log)

    monkeypatch.setattr(extract_stage, "build_llm", _build)
    job_id = enqueue(pool, make_transcript_drop("source-fallback"), "source-fallback")

    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    # The primary was asked once; the fallback served every document after.
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 3
    [meeting] = meetings(pool, job_id)
    rows = artifact_rows(pool, meeting["id"])
    assert len(rows) == 3
    for row in rows:
        assert row["provenance"]["fallback_engaged"] is True
        assert row["provenance"]["model"] == "fallback-model"


def test_both_models_unavailable_fails_the_job_naming_both_errors(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _build(_binding: Any, _providers: Any, log: Any = None) -> FallbackLlm:
        return FallbackLlm(
            FakeLlm(replies=(LlmUnavailableError("primary unreachable (test)"),)),
            FakeLlm(replies=(LlmUnavailableError("fallback unreachable (test)"),)),
            log=log,
        )

    monkeypatch.setattr(extract_stage, "build_llm", _build)
    job_id = enqueue(pool, make_transcript_drop("source-alldown"), "source-alldown")

    assert runner.run_once(pool, app_config, content_root) is True

    status, error = job_row(pool, job_id)
    assert status == "failed"
    assert error is not None and "stage extract failed" in error
    assert "primary unreachable (test)" in error
    assert "fallback unreachable (test)" in error
    # Retryable by re-queue: the stage is `failed`, not poisoned.
    requeue_extract(pool, job_id)
    monkeypatch.setattr(extract_stage, "build_llm", lambda *_a, **_kw: FakeLlm())
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)


# --- superseded moments -----------------------------------------------------


def test_an_artifact_anchored_to_a_superseded_moment_is_counted_not_inserted(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A superseded moment is a ghost no right rail shows — so is a reported outcome."""
    fake_llm()
    job_id = enqueue(
        pool,
        make_transcript_drop("source-super", summary=SUMMARY_DOC, actions=ACTIONS_DOC),
        "source-super",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])

    with pool.connection() as conn:
        conn.execute(
            "UPDATE moment SET provenance = provenance ||"
            " '{\"superseded\": true}'::jsonb WHERE id = %s",
            (moments[0],),
        )

    capsys.readouterr()
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    rows = artifact_rows(pool, meeting["id"])
    assert all(row["moment_id"] != moments[0] for row in rows)
    records = log_events(capsys)
    [summary] = [r for r in records if r["event"] == "stage.extract.summary"]
    assert summary["skipped_superseded"] == 1
    [discarded] = [
        r for r in records if r["event"] == "stage.extract.artifact_discarded"
    ]
    assert discarded["item_id"] == "D1"
    assert discarded["reason"] == "superseded-moment"
    assert discarded["moment_id"] == str(moments[0])


# --- a meeting with nothing to extract from ---------------------------------


def _run_extract_only(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    drop_path: Any,
    job_id: UUID,
    meeting_id: UUID,
) -> None:
    """Run just the `extract` stage over an already-seeded meeting.

    Deliberately not through `runner.run_once`: the meetings below have no
    transcript segments or no moments, and `align` refuses a drop whose
    transcript will not parse — the pipeline would fail two stages earlier and
    `extract` would never be reached. Seeding the end state directly is the
    only way to put the stage in front of the input this matrix row describes.
    """
    drop = read_drop(drop_path, config_path=app_config.config_path)
    with pool.connection() as conn:
        extract_stage.run(
            StageContext(
                conn=conn,
                config=app_config,
                job_id=job_id,
                meeting_id=meeting_id,
                drop=drop,
                content_root=content_root,
                drops_root=DROPS_ROOT,
                log=logs.bind(job_id=job_id, stage="extract"),
            )
        )
        conn.commit()


@pytest.mark.parametrize(
    "turns, with_moments, reason",
    [
        # No transcript segments at all: nothing to send and nothing to read.
        ((), False, "no transcript text"),
        # Turns exist but the timeline was never cut into moments, so there is
        # nowhere for an `[m:ss]` anchor to resolve to. Extracting anyway would
        # have to either invent a citation target or drop every artifact.
        (DEFAULT_TURNS, False, "no moments"),
    ],
    ids=["no-transcript-text", "no-moments"],
)
def test_a_meeting_with_nothing_to_extract_from_completes_without_a_call(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
    capsys: pytest.CaptureFixture[str],
    turns: Any,
    with_moments: bool,
    reason: str,
) -> None:
    """The stage completes, spends nothing, writes nothing, and says why."""
    engine = fake_llm()
    source_id = f"source-empty-{reason.replace(' ', '-')}"
    drop = make_transcript_drop(source_id)
    with pool.connection() as conn:
        seeded = seed_meeting(
            conn,
            source_id=source_id,
            has_recording=False,
            turns=turns,
            with_moments=with_moments,
        )
        conn.commit()

    capsys.readouterr()
    # No exception: "stage completes" is the whole of this row's happy path.
    _run_extract_only(
        pool, app_config, content_root, drop, seeded.job_id, seeded.meeting_id
    )

    # No calls: a meeting with nothing to read must not spend a model pass on
    # discovering that, and must not reach a real provider either.
    assert engine.calls == []
    assert artifact_rows(pool, seeded.meeting_id) == []
    assert extraction_sources(pool, seeded.meeting_id) == {}

    # Read the captured stream once: `log_events` drains it, so a second call
    # would assert against an empty buffer and pass for the wrong reason.
    records = log_events(capsys)
    [summary] = [r for r in records if r["event"] == "stage.extract.summary"]
    assert summary["skipped_reason"] == reason
    assert summary["documents"] == {}
    assert summary["artifacts"] == {"action-item": 0, "adr": 0}
    assert summary["models"] == []
    # The skip is a counted outcome, not a quiet return: the summary says how
    # much evidence it found before deciding there was nothing to extract.
    assert summary["moments"] == 0
    assert summary["turns"] == len(turns)
    # Not a zero-artifact signal either — no source document was read, so
    # there is no populated section to have been silent about.
    assert not [r for r in records if r["event"] == "stage.extract.zero_artifacts"]


# --- NFR7 / AD-4: extract writes no store, so search never sees a draft -----


@pytest.mark.slow(reason="reads the projected evidence back through both test twins under the projection lock: 1.5s at e5510c7")
def test_search_never_returns_an_extracted_artifacts_content(
    pool: ConnectionPool,
    client: Any,
    app_config: AppConfig,
    content_root: Any,
    make_transcript_drop: Callable[..., Any],
    fake_llm: Callable[..., FakeLlm],
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
) -> None:
    """After extract settles and the meeting's evidence is projected, querying
    `GET /search` for an extracted artifact's title text surfaces no artifact
    content in any hit — the stores were never written by extract.

    Store-backed: `projection_stores` wipes both stores under the
    cross-worktree lock, so a hit here could only come from this test's own
    projection.
    """
    fake_llm()
    zorblatt = SUMMARY_DOC.replace("Standardize on SFTP", "Adopt the Zorblatt gateway")
    job_id = enqueue(
        pool,
        make_transcript_drop("source-gate", summary=zorblatt, actions=ACTIONS_DOC),
        "source-gate",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    [meeting] = meetings(pool, job_id)
    assert any(
        "Zorblatt" in row["title"] for row in artifact_rows(pool, meeting["id"])
    ), "the draft must exist in Postgres for its absence from search to mean anything"

    # Project the meeting's evidence exactly as the ingest-complete trigger
    # would have (the worker tests run with the trigger stubbed out).
    with pool.connection() as conn:
        projections.project_meeting(
            conn, app_config, meeting["id"], embedder_factory=lambda: fake_embedder
        )

    import meetingminer.api.main as api_main

    original = api_main.app.state.embedder
    api_main.app.state.embedder = fake_embedder
    try:
        response = client.get("/search", params={"q": "Zorblatt gateway"})
    finally:
        api_main.app.state.embedder = original
    assert response.status_code == 200, response.text
    # Not merely "no hits": the vector lane legitimately dredges up nearest
    # moments for any query, so hits may exist — but no hit may carry the
    # draft's title or body text anywhere in its fields.
    hits = response.json()["hits"]
    assert "Zorblatt" not in json.dumps(hits)
