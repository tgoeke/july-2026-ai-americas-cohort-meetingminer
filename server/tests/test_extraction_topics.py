"""Story 10.1: the topics document — parser, prompt, config, and the stage's third pass.

Parser tests are store-free string work over `pipeline/extraction.py`. The
stage tests are DB-backed (named skip when the compose Postgres is down) and
model-free by construction: the topics document is always *generated*, so the
scripted FakeLlm's replies queue is the topics reply — the two artifact
documents are adopted from the drop and make zero model calls, which keeps
each test's script unambiguous about which document it feeds.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable
from uuid import UUID

import pytest
from psycopg_pool import ConnectionPool

from meetingminer.config import AppConfig
from meetingminer.pipeline import extraction as core
from meetingminer.pipeline import runner

from conftest import EMPTY_EXTRACTION_DOCUMENT, DropFactory, FakeLlm, valid_metadata
from test_worker_runner import (
    enqueue,
    job_row,
    meetings,
    set_job_status,
    set_stage,
    stage_statuses,
    stage_error,
)


# --- the parser: the topics document kind ------------------------------------

TOPICS_TABLE_DOC = """\
# Topics — Data Hub Demo

## Topics

| ID | Topic | Gist | Timestamps |
|----|-------|------|------------|
| **T1** | Vendor feed transport | Moving the vendor feed to SFTP | [0:10], [0:45] |
| T2 | Credential ownership | Ellis owns the SFTP credentials | [1:35] |
"""

# The same two topics as bullets — the layouts must parse identically.
TOPICS_BULLET_DOC = """\
## Topics

- **T1** – Vendor feed transport – Moving the vendor feed to SFTP – [0:10], [0:45]
- T2 — Credential ownership — Ellis owns the SFTP credentials — [1:35]
"""


def test_the_table_layout_parses_topics_with_every_anchor() -> None:
    parsed = core.parse_extraction_document(TOPICS_TABLE_DOC, core.DOC_TOPICS)
    assert parsed.kind == core.DOC_TOPICS
    assert parsed.layout == "table"
    assert [a.kind for a in parsed.artifacts] == [core.KIND_TOPIC, core.KIND_TOPIC]
    assert [a.item_id for a in parsed.artifacts] == ["T1", "T2"]
    assert [a.title for a in parsed.artifacts] == [
        "Vendor feed transport",
        "Credential ownership",
    ]
    # Every stamp, in written order — topics need every place they were
    # discussed, not only the earliest.
    assert parsed.artifacts[0].anchors_ms == (10_000, 45_000)
    assert parsed.artifacts[0].anchor_ms == 10_000
    assert parsed.artifacts[1].anchors_ms == (95_000,)
    assert parsed.populated_target_sections == ("Topics",)


def test_the_bullet_layout_parses_the_same_topics() -> None:
    table = core.parse_extraction_document(TOPICS_TABLE_DOC, core.DOC_TOPICS)
    bullets = core.parse_extraction_document(TOPICS_BULLET_DOC, core.DOC_TOPICS)
    assert bullets.layout == "bullet"
    assert [(a.item_id, a.title, a.anchors_ms) for a in bullets.artifacts] == [
        (a.item_id, a.title, a.anchors_ms) for a in table.artifacts
    ]


@pytest.mark.parametrize(
    "document",
    [
        (
            "## Topics\n\n"
            "| ID | Topic | Gist | Timestamps |\n"
            "|----|-------|------|------------|\n"
            "| T1 | AI | Artificial intelligence planning | [0:10] |\n"
        ),
        "## Topics\n\n- T1 - AI - Artificial intelligence planning - [0:10]\n",
    ],
)
def test_a_short_topic_name_is_not_promoted_out_of_the_name_field(
    document: str,
) -> None:
    [topic] = core.parse_extraction_document(document, core.DOC_TOPICS).artifacts
    assert topic.title == "AI"
    assert core.topic_gist(topic) == "Artificial intelligence planning"


@pytest.mark.parametrize(
    ("document", "missing_field"),
    [
        (
            (
                "## Topics\n\n"
                "| ID | Topic | Gist | Timestamps |\n"
                "|----|-------|------|------------|\n"
                "| T1 | | Artificial intelligence planning | [0:10] |\n"
            ),
            "Topic",
        ),
        (
            (
                "## Topics\n\n"
                "| ID | Topic | Gist | Timestamps |\n"
                "|----|-------|------|------------|\n"
                "| T1 | AI | | [0:10] |\n"
            ),
            "Gist",
        ),
        (
            "## Topics\n\n- T1 -  - Artificial intelligence planning - [0:10]\n",
            "Topic",
        ),
        ("## Topics\n\n- T1 - AI -  - [0:10]\n", "Gist"),
    ],
)
def test_a_topic_requires_separate_name_and_gist_fields(
    document: str, missing_field: str
) -> None:
    with pytest.raises(core.ArtifactParseError, match=rf"T1.*{missing_field}"):
        core.parse_extraction_document(document, core.DOC_TOPICS)


def test_range_and_comma_stamps_all_land_in_anchors_ms() -> None:
    document = (
        "## Topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed transport | Moving to SFTP | (0:10‑0:45, 1:35) |\n"
    )
    [topic] = core.parse_extraction_document(document, core.DOC_TOPICS).artifacts
    assert topic.anchors_ms == (10_000, 45_000, 95_000)
    assert topic.anchor_ms == 10_000


def test_a_topic_without_a_timestamp_is_a_named_parse_error() -> None:
    document = (
        "## Topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed transport | Moving to SFTP | not stated |\n"
    )
    with pytest.raises(core.ArtifactParseError, match="T1"):
        core.parse_extraction_document(document, core.DOC_TOPICS)


@pytest.mark.parametrize(
    ("gist", "timestamps"),
    [
        ("Moving to SFTP", "[0:10], [99:99]"),
        ("Moving the 9:00 standup", "not stated"),
        ("Moving the 9:00 standup", ""),
    ],
)
def test_a_labelled_timestamp_field_is_authoritative_and_fully_validated(
    gist: str, timestamps: str
) -> None:
    document = (
        "## Topics\n\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        f"| T1 | Vendor feed transport | {gist} | {timestamps} |\n"
    )
    with pytest.raises(core.ArtifactParseError, match="T1.*Timestamps"):
        core.parse_extraction_document(document, core.DOC_TOPICS)


def test_a_document_with_no_structure_is_a_parse_error() -> None:
    with pytest.raises(core.ArtifactParseError):
        core.parse_extraction_document(
            "The meeting covered many topics in a free-flowing way.",
            core.DOC_TOPICS,
        )


def test_duplicate_topic_ids_are_a_named_parse_error() -> None:
    document = (
        "## Topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed transport | First definition | [0:10] |\n"
        "\n"
        "## More topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed restated | A restatement | [0:45] |\n"
        "| T2 | Credential ownership | Second topic | [1:35] |\n"
    )
    with pytest.raises(core.ArtifactParseError, match="duplicate topic ID T1"):
        core.parse_extraction_document(document, core.DOC_TOPICS)


def test_non_t_ids_are_structure_not_topics() -> None:
    # `R1` carries no timestamp: if it were mistaken for a topic this would be
    # a missing-anchor error, so a clean zero-topic parse proves non-T ids are
    # read as structure only.
    document = (
        "## Topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| R1 | Not a topic | A risk id | not stated |\n"
    )
    parsed = core.parse_extraction_document(document, core.DOC_TOPICS)
    assert parsed.artifacts == ()
    assert parsed.populated_target_sections == ("Topics",)


def test_a_semantic_heading_tolerates_topic_table_header_drift() -> None:
    # Real-world drift can affect the section and column names together. The
    # semantic heading is sufficient even without exact Topic/Gist headers.
    document = (
        "## Discussion themes\n"
        "\n"
        "| ID | Theme | Summary | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed transport | Moving to SFTP | [0:10] |\n"
    )
    parsed = core.parse_extraction_document(document, core.DOC_TOPICS)
    [topic] = parsed.artifacts
    assert topic.item_id == "T1"
    assert topic.title == "Vendor feed transport"
    assert topic.anchors_ms == (10_000,)
    assert core.topic_gist(topic) == "Moving to SFTP"


def test_canonical_topic_columns_are_sufficient_under_a_neutral_heading() -> None:
    document = (
        "## Notes\n\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed transport | Moving to SFTP | [0:10] |\n"
    )
    [topic] = core.parse_extraction_document(document, core.DOC_TOPICS).artifacts
    assert topic.title == "Vendor feed transport"
    assert core.topic_gist(topic) == "Moving to SFTP"


def test_auxiliary_topic_columns_do_not_become_part_of_the_gist() -> None:
    document = (
        "## Topics\n\n"
        "| ID | Topic | Gist | Confidence | Timestamps |\n"
        "|----|-------|------|------------|------------|\n"
        "| T1 | Vendor feed transport | Moving to SFTP | high | [0:10] |\n"
    )
    [topic] = core.parse_extraction_document(document, core.DOC_TOPICS).artifacts
    assert core.topic_gist(topic) == "Moving to SFTP"


@pytest.mark.parametrize(
    ("document", "item_id"),
    [
        (
            (
                "## Decisions\n\n"
                "| ID | Decision | Context | Timestamp |\n"
                "|----|----------|---------|-----------|\n"
                "| D1 | Rotate the vendor key | Required by policy | [0:10] |\n"
            ),
            "D1",
        ),
        (
            "## Notes\n\n- A1 - Rotate the vendor key - Required by policy - [0:10]\n",
            "A1",
        ),
        (
            "## Non-topic notes\n\n- T1 - Rotate key - Required by policy - [0:10]\n",
            "T1",
        ),
        (
            (
                "## Notes\n\n"
                "| ID | Topic Gist | Timestamp |\n"
                "|----|------------|-----------|\n"
                "| T1 | Rotate the vendor key | [0:10] |\n"
            ),
            "T1",
        ),
    ],
    ids=["decisions-table", "task-list", "negated-topic", "fused-header"],
)
def test_a_contentful_foreign_document_is_a_named_parse_error(
    document: str, item_id: str
) -> None:
    with pytest.raises(
        core.ArtifactParseError, match=rf"{item_id}.*topic semantics"
    ):
        core.parse_extraction_document(document, core.DOC_TOPICS)


def test_an_idless_contentful_foreign_table_is_a_named_parse_error() -> None:
    document = (
        "## Decisions\n\n"
        "| Decision | Context | Timestamp |\n"
        "|----------|---------|-----------|\n"
        "| Rotate the vendor key | Required by policy | [0:10] |\n"
    )
    with pytest.raises(
        core.ArtifactParseError,
        match="contentful row.*Decisions.*topic semantics",
    ):
        core.parse_extraction_document(document, core.DOC_TOPICS)


def test_the_shared_empty_document_parses_to_zero_topics() -> None:
    # The conftest default every worker test walks past: a Decisions-only
    # header must stay a successful zero-topic parse, or every existing
    # worker test fails the moment the stage grows its third pass.
    parsed = core.parse_extraction_document(EMPTY_EXTRACTION_DOCUMENT, core.DOC_TOPICS)
    assert parsed.artifacts == ()
    assert parsed.layout == core.LAYOUT_NONE
    assert parsed.populated_target_sections == ()


def test_proposed_artifact_anchors_ms_defaults_to_empty() -> None:
    proposal = core.ProposedArtifact(
        kind=core.KIND_ADR,
        title="t",
        body="b",
        anchor_ms=0,
        item_id="D1",
        layout=core.LAYOUT_TABLE,
    )
    assert proposal.anchors_ms == ()


def test_topic_gist_strips_timestamp_bookkeeping_in_both_layouts() -> None:
    for document in (TOPICS_TABLE_DOC, TOPICS_BULLET_DOC):
        parsed = core.parse_extraction_document(document, core.DOC_TOPICS)
        assert core.topic_gist(parsed.artifacts[0]) == "Moving the vendor feed to SFTP"
        assert core.topic_gist(parsed.artifacts[1]) == "Ellis owns the SFTP credentials"


def test_an_anchors_header_is_timestamp_bookkeeping_not_gist_text() -> None:
    document = (
        "## Topics\n\n"
        "| ID | Topic | Gist | Anchors |\n"
        "|----|-------|------|---------|\n"
        "| T1 | Vendor feed transport | Moving to SFTP | [0:10], [0:45] |\n"
    )
    [topic] = core.parse_extraction_document(document, core.DOC_TOPICS).artifacts
    assert topic.anchors_ms == (10_000, 45_000)
    assert core.topic_gist(topic) == "Moving to SFTP"


def test_a_topic_uses_the_exact_anchors_column_not_an_unrelated_time_header() -> None:
    document = (
        "## Topics\n\n"
        "| ID | Topic | Gist | Estimated time impact | Anchors |\n"
        "|----|-------|------|-----------------------|---------|\n"
        "| T1 | Vendor feed transport | Moving to SFTP | 9:00 | [0:10] |\n"
    )
    [topic] = core.parse_extraction_document(document, core.DOC_TOPICS).artifacts
    assert topic.anchors_ms == (10_000,)


def test_an_anchors_header_is_an_authoritative_topic_timestamp_field() -> None:
    document = (
        "## Topics\n\n"
        "| ID | Topic | Gist | Anchors |\n"
        "|----|-------|------|---------|\n"
        "| T1 | Vendor feed transport | Moving to SFTP | [0:10], [99:99] |\n"
    )
    with pytest.raises(core.ArtifactParseError, match="T1.*Timestamps"):
        core.parse_extraction_document(document, core.DOC_TOPICS)


# --- the prompt builder and the config binding -------------------------------


def test_build_topics_prompt_composes_the_template_verbatim() -> None:
    template = "TOPICS TEMPLATE TEXT"
    transcript = "[0:02] Goeke, Timothy: Everybody, good morning."
    prompt = core.build_prompt(
        core.DOC_TOPICS,
        transcript,
        template=template,
        meeting_title="Data Hub Demo",
        meeting_date="8/5/2026",
    )
    assert prompt.startswith(template)
    assert "Meeting: Data Hub Demo" in prompt
    assert "This meeting took place on 8/5/2026." in prompt
    assert "Raw transcript:\n\n" + transcript in prompt
    assert prompt == core.build_topics_prompt(
        transcript,
        template=template,
        meeting_title="Data Hub Demo",
        meeting_date="8/5/2026",
    )


def test_the_committed_topics_prompt_is_bound_and_parseable_in_shape(
    app_config: AppConfig,
) -> None:
    binding = app_config.settings.llm.roles.extraction
    text = binding.topics_prompt
    assert text.strip()
    # The load-bearing shape the parser keys on.
    assert "## Topics" in text
    assert "| ID | Topic | Gist | Timestamps |" in text
    assert "[m:ss]" in text
    assert "must not be written" in text
    # Story 6.7's generalisation: meetings and recorded sessions alike, and
    # never a source-tool name.
    assert "meeting or recorded session" in text
    assert "Teams" not in text


def test_a_missing_topics_prompt_key_is_refused_at_validation() -> None:
    """The I/O matrix's fail-fast row: no code-level default exists (AD-10).

    `NonEmptyText` is required, so a config lacking the key never loads —
    the same startup refusal the other two prompt fields already earn.
    """
    import pydantic

    from meetingminer.config import ExtractionRoleBinding

    with pytest.raises(pydantic.ValidationError, match="topics_prompt"):
        ExtractionRoleBinding.model_validate(
            {
                "model": "ollama/some-model",
                "arch_summary_prompt": "summary text",
                "action_items_prompt": "actions text",
            }
        )


# --- the stage's third pass (DB-backed) --------------------------------------

# Three turns spaced past the configured 20s moment gap: three moments, so
# anchors can land on different moments in one run.
MULTI_MOMENT_TRANSCRIPT = (
    "[0:02] Goeke, Timothy: We will standardize on SFTP for the vendor feed.\n"
    "[0:40] Whitmore, Ellis: I will set up the credentials this week.\n"
    "[1:30] Goeke, Timothy: Nothing else to report today.\n"
)

SUMMARY_DOC = """\
## Decisions

| ID | Decision | Context and consequences | Mark | Timestamp |
|----|----------|--------------------------|------|-----------|
| D1 | Standardize on SFTP | Replaces the shared mailbox | Confirmed | [0:10] |
"""

ACTIONS_DOC = """\
## Action items

| ID | Action | Details and dependency | Owner | Timing (as stated) | Status | Timestamp |
|----|--------|------------------------|-------|---------------------|--------|-----------|
| A1 | Set up the SFTP credentials | Needs the vendor key | Whitmore, Ellis | this week | Committed | [1:35] |
"""

# `[0:10]` is in moment 0, `[0:45]` in moment 1, `[1:35]` in moment 2.
TOPICS_DOC = """\
## Topics

| ID | Topic | Gist | Timestamps |
|----|-------|------|------------|
| T1 | Vendor feed transport | Moving the vendor feed to SFTP | [0:10], [0:45] |
| T2 | Credential ownership | Ellis owns the SFTP credentials | [1:35] |
"""

SIGNALS_DOC = """\
## Risks

| ID | Risk | Detail | Timestamp |
|----|------|--------|-----------|
| R1 | The vendor key may be late | Blocks cutover | [0:10] |

## Open questions

| ID | Question | Detail | Timestamp |
|----|----------|--------|-----------|
| Q1 | Who approves the purchase order? | Nobody claimed it | [0:45] |
"""


@pytest.fixture()
def pool(test_pool: ConnectionPool) -> ConnectionPool:
    from conftest import truncate_evidence

    truncate_evidence(test_pool)
    return test_pool


@pytest.fixture()
def make_extraction_drop(make_drop: DropFactory) -> Callable[[str], Any]:
    """A transcript drop that carries BOTH artifact documents.

    Adopting them makes the artifact passes call-free, so the FakeLlm's
    scripted replies queue is read by exactly one caller: the topics pass.
    """

    def _make(source_id: str) -> Any:
        drop = make_drop(metadata=valid_metadata(source_id), files=())
        (drop / "transcript.txt").write_text(MULTI_MOMENT_TRANSCRIPT, encoding="utf-8")
        (drop / "extraction-summary.md").write_text(SUMMARY_DOC, encoding="utf-8")
        (drop / "extraction-action-items.md").write_text(ACTIONS_DOC, encoding="utf-8")
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


def topic_rows(pool: ConnectionPool, meeting_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, name, gist, provenance FROM topic"
            " WHERE meeting_id = %s ORDER BY created_at, id",
            (meeting_id,),
        ).fetchall()
    return [
        {"id": row[0], "name": row[1], "gist": row[2], "provenance": row[3]}
        for row in rows
    ]


def signal_rows(pool: ConnectionPool, meeting_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT moment_id, kind, label, detail, anchor_ms, item_id, provenance"
            " FROM ranking_signal WHERE meeting_id = %s ORDER BY anchor_ms, item_id",
            (meeting_id,),
        ).fetchall()
    return [
        {
            "moment_id": row[0],
            "kind": row[1],
            "label": row[2],
            "detail": row[3],
            "anchor_ms": row[4],
            "item_id": row[5],
            "provenance": row[6],
        }
        for row in rows
    ]


def signals_source(pool: ConnectionPool, meeting_id: UUID) -> tuple[int, int] | None:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT item_count, artifact_count FROM extraction_source"
            " WHERE meeting_id = %s AND kind = 'ranking-signals'",
            (meeting_id,),
        ).fetchone()
    return (row[0], row[1]) if row is not None else None


def mention_rows(pool: ConnectionPool, topic_id: UUID) -> list[tuple[UUID, int]]:
    with pool.connection() as conn:
        return [
            (row[0], row[1])
            for row in conn.execute(
                "SELECT moment_id, anchor_ms FROM topic_mention"
                " WHERE topic_id = %s ORDER BY anchor_ms",
                (topic_id,),
            ).fetchall()
        ]


def topics_source(pool: ConnectionPool, meeting_id: UUID) -> dict[str, Any] | None:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT origin, drop_relative_path, sha256, byte_size, layout,"
            " item_count, artifact_count, model, prompt_version, prompt_hash"
            " FROM extraction_source WHERE meeting_id = %s AND kind = 'topics'",
            (meeting_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "origin": row[0],
        "drop_relative_path": row[1],
        "sha256": row[2],
        "byte_size": row[3],
        "layout": row[4],
        "item_count": row[5],
        "artifact_count": row[6],
        "model": row[7],
        "prompt_version": row[8],
        "prompt_hash": row[9],
    }


def log_events(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]


def requeue_extract(pool: ConnectionPool, job_id: UUID) -> None:
    set_stage(pool, job_id, "extract", "queued")
    set_job_status(pool, job_id, "queued")


def test_topics_land_as_rows_with_a_mention_per_containing_moment(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    engine = fake_llm(replies=(TOPICS_DOC,))
    job_id = enqueue(pool, make_extraction_drop("source-topics"), "source-topics")

    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    # Both artifact documents were adopted, so the only calls are the two
    # passes with no adoption path: topics, then story 10.4's ranking
    # signals. The topics call is the first, over the whole transcript,
    # carrying the committed template.
    assert len(engine.calls) == 2
    binding = app_config.settings.llm.roles.extraction
    assert engine.calls[0].startswith(binding.topics_prompt)
    assert engine.calls[1].startswith(binding.ranking_signals_prompt)
    assert "[1:30] Goeke, Timothy: Nothing else to report today." in engine.calls[0]

    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])
    assert len(moments) == 3

    topics = topic_rows(pool, meeting["id"])
    assert [(topic["name"], topic["gist"]) for topic in topics] == [
        ("Vendor feed transport", "Moving the vendor feed to SFTP"),
        ("Credential ownership", "Ellis owns the SFTP credentials"),
    ]
    prompt_hash = hashlib.sha256(binding.topics_prompt.encode()).hexdigest()[:16]
    for topic in topics:
        assert topic["provenance"]["source"] == "generated"
        assert topic["provenance"]["model"] == "fake-llm"
        assert topic["provenance"]["prompt_version"] == core.PROMPT_VERSION
        assert topic["provenance"]["prompt_hash"] == prompt_hash
        assert topic["provenance"]["document_kind"] == "topics"
    assert topics[0]["provenance"]["item_id"] == "T1"

    # T1's two stamps land in two different moments; T2's one in the third.
    assert mention_rows(pool, topics[0]["id"]) == [
        (moments[0], 10_000),
        (moments[1], 45_000),
    ]
    assert mention_rows(pool, topics[1]["id"]) == [(moments[2], 95_000)]

    source = topics_source(pool, meeting["id"])
    assert source == {
        "origin": "generated",
        "drop_relative_path": None,
        "sha256": hashlib.sha256(TOPICS_DOC.encode()).hexdigest(),
        "byte_size": len(TOPICS_DOC.encode()),
        "layout": "table",
        "item_count": 2,
        "artifact_count": 2,
        "model": "fake-llm",
        "prompt_version": core.PROMPT_VERSION,
        "prompt_hash": prompt_hash,
    }

    # Topics are not artifacts: nothing entered the lifecycle table for them.
    with pool.connection() as conn:
        kinds = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT kind FROM artifact WHERE meeting_id = %s",
                (meeting["id"],),
            ).fetchall()
        }
    assert kinds == {"adr", "action-item"}


def test_two_stamps_inside_one_moment_collapse_to_the_earliest(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    document = (
        "## Topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed transport | Discussed twice in one moment | [0:10], [0:05] |\n"
    )
    fake_llm(replies=(document,))
    job_id = enqueue(pool, make_extraction_drop("source-collapse"), "source-collapse")
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])
    [topic] = topic_rows(pool, meeting["id"])
    # One mention for the moment, anchored at the earliest stamp.
    assert mention_rows(pool, topic["id"]) == [(moments[0], 5_000)]


def test_a_rerun_replaces_the_topic_rows(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    fake_llm(replies=(TOPICS_DOC,))
    job_id = enqueue(pool, make_extraction_drop("source-rerun"), "source-rerun")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    first = topic_rows(pool, meeting["id"])
    assert len(first) == 2

    replacement = (
        "## Topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Key rotation | Who rotates the vendor key | [0:45] |\n"
    )
    fake_llm(replies=(replacement,))
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    topics = topic_rows(pool, meeting["id"])
    assert [topic["name"] for topic in topics] == ["Key rotation"]
    assert not {topic["id"] for topic in topics} & {topic["id"] for topic in first}
    # One `topics` source row, upserted, describing the latest pass.
    source = topics_source(pool, meeting["id"])
    assert source is not None and source["item_count"] == 1
    # The artifact lifecycle stayed an artifact concern: still only drafts of
    # the two artifact kinds, no `topic` kind anywhere.
    with pool.connection() as conn:
        states = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT state FROM artifact WHERE meeting_id = %s",
                (meeting["id"],),
            ).fetchall()
        }
    assert states == {"extracted"}


def test_an_early_exit_rerun_removes_existing_topics_and_mentions(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = fake_llm(replies=(TOPICS_DOC,))
    job_id = enqueue(pool, make_extraction_drop("source-rerun-empty"), "source-rerun-empty")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    topics = topic_rows(pool, meeting["id"])
    assert len(topics) == 2
    assert sum(len(mention_rows(pool, topic["id"])) for topic in topics) == 3

    with pool.connection() as conn:
        conn.execute(
            "DELETE FROM transcript_segment WHERE meeting_id = %s",
            (meeting["id"],),
        )

    capsys.readouterr()
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    assert len(engine.calls) == 2, "the empty rerun must exit before another model call"
    assert topic_rows(pool, meeting["id"]) == []
    assert topics_source(pool, meeting["id"]) is None

    [summary] = [
        event
        for event in log_events(capsys)
        if event["event"] == "stage.extract.summary"
    ]
    assert summary["skipped_reason"] == "no transcript text"
    assert summary["topics_replaced"] == 2
    assert summary["topics"] == 0
    assert summary["topic_mentions"] == 0


def test_topics_attach_to_moments_with_approved_artifacts(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    fake_llm(replies=(TOPICS_DOC,))
    job_id = enqueue(pool, make_extraction_drop("source-approved"), "source-approved")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])

    with pool.connection() as conn:
        updated = conn.execute(
            "UPDATE artifact SET state = 'approved'"
            " WHERE meeting_id = %s AND moment_id = %s AND kind = 'adr'",
            (meeting["id"], moments[0]),
        ).rowcount
    assert updated == 1

    document = (
        "## Topics\n\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed transport | Still navigable after approval | [0:10] |\n"
    )
    fake_llm(replies=(document,))
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True

    [topic] = topic_rows(pool, meeting["id"])
    assert mention_rows(pool, topic["id"]) == [(moments[0], 10_000)]


def test_a_moment_only_augmentation_deletes_a_topic_left_without_mentions(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    engine = fake_llm(replies=(TOPICS_DOC,))
    job_id = enqueue(
        pool,
        make_extraction_drop("source-orphan-augmentation"),
        "source-orphan-augmentation",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    assert stage_statuses(pool, job_id)["extract"] == "done"

    with pool.connection() as conn:
        conn.execute("DELETE FROM topic WHERE meeting_id = %s", (meeting["id"],))
        screen_moment = conn.execute(
            "INSERT INTO moment (meeting_id, identity_key, derived_from, start_ms,"
            " end_ms, started_at, started_at_precision, provenance)"
            " SELECT id, 'screen:10000000', 'screen', 10000000, 10010000,"
            " started_at + interval '10000 seconds', started_at_precision,"
            " '{}'::jsonb FROM meeting WHERE id = %s RETURNING id",
            (meeting["id"],),
        ).fetchone()[0]
        topic_id = conn.execute(
            "INSERT INTO topic (meeting_id, name, gist)"
            " VALUES (%s, 'Temporary screen topic', 'Only on removed evidence')"
            " RETURNING id",
            (meeting["id"],),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO topic_mention (topic_id, moment_id, meeting_id, anchor_ms)"
            " VALUES (%s, %s, %s, 10000000)",
            (topic_id, screen_moment, meeting["id"]),
        )

    # This is the augmentation checkpoint shape: moments re-runs while extract
    # remains settled, so only the database invariant can remove the orphan.
    set_stage(pool, job_id, "moments", "queued")
    set_job_status(pool, job_id, "queued")
    assert runner.run_once(pool, app_config, content_root) is True
    assert stage_statuses(pool, job_id)["extract"] == "done"
    assert len(engine.calls) == 2, "augmentation must leave extract settled"

    with pool.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM moment WHERE id = %s", (screen_moment,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM topic_mention WHERE topic_id = %s", (topic_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM topic WHERE id = %s", (topic_id,)
        ).fetchone()[0] == 0


def test_superseded_mentions_are_skipped_and_an_unmentioned_topic_dropped(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_llm(replies=(TOPICS_DOC,))
    job_id = enqueue(pool, make_extraction_drop("source-super"), "source-super")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])

    with pool.connection() as conn:
        conn.execute(
            "UPDATE moment SET provenance = provenance ||"
            " '{\"superseded\": true}'::jsonb WHERE id = %s",
            (moments[0],),
        )

    # T1 anchors only inside the superseded moment → the whole topic drops.
    # T2 anchors there and in a live moment → one mention survives.
    document = (
        "## Topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Vendor feed transport | Only in the superseded span | [0:10] |\n"
        "| T2 | Credential ownership | Also discussed later | [0:05], [1:35] |\n"
    )
    capsys.readouterr()
    fake_llm(replies=(document,))
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    [topic] = topic_rows(pool, meeting["id"])
    assert topic["name"] == "Credential ownership"
    assert mention_rows(pool, topic["id"]) == [(moments[2], 95_000)]

    records = log_events(capsys)
    discarded_mentions = [
        r for r in records if r["event"] == "stage.extract.topic_mention_discarded"
    ]
    assert {(r["item_id"], r["reason"]) for r in discarded_mentions} == {
        ("T1", "superseded-moment"),
        ("T2", "superseded-moment"),
    }
    [dropped] = [r for r in records if r["event"] == "stage.extract.topic_discarded"]
    assert dropped["item_id"] == "T1"
    assert dropped["reason"] == "no-surviving-mention"


def test_zero_topics_on_a_contentful_meeting_is_a_named_signal_not_an_error(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The default reply is the shared zero-artifact document: a well-formed
    # parse that yields no topics on a meeting that has transcript and moments.
    fake_llm()
    job_id = enqueue(pool, make_extraction_drop("source-zero"), "source-zero")
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)

    [meeting] = meetings(pool, job_id)
    assert topic_rows(pool, meeting["id"]) == []
    source = topics_source(pool, meeting["id"])
    assert source is not None and source["item_count"] == 0

    [signal] = [
        r for r in log_events(capsys) if r["event"] == "stage.extract.zero_topics"
    ]
    assert signal["meeting_id"] == str(meeting["id"])


def test_an_anchor_outside_the_timeline_fails_the_stage_naming_the_topic(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    document = (
        "## Topics\n"
        "\n"
        "| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|------------|\n"
        "| T1 | Invented span | The model made this stamp up | [59:00] |\n"
    )
    fake_llm(replies=(document,))
    job_id = enqueue(pool, make_extraction_drop("source-outside"), "source-outside")
    assert runner.run_once(pool, app_config, content_root) is True

    status, _error = job_row(pool, job_id)
    assert status == "failed"
    error = stage_error(pool, job_id, "extract")
    assert error is not None
    assert "T1" in error
    assert "topics" in error

    # Nothing half-landed: the failed transaction rolled back every topic row.
    [meeting] = meetings(pool, job_id)
    assert topic_rows(pool, meeting["id"]) == []


def test_an_unparseable_topics_reply_earns_one_retry(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    engine = fake_llm(replies=("prose with no structure at all", TOPICS_DOC))
    job_id = enqueue(pool, make_extraction_drop("source-retry"), "source-retry")
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    # Two topics calls (the refusal and its retry) plus story 10.4's
    # ranking-signals pass, which runs after topics settle.
    assert len(engine.calls) == 3
    [meeting] = meetings(pool, job_id)
    assert len(topic_rows(pool, meeting["id"])) == 2


def test_a_contentful_foreign_topics_reply_earns_one_retry(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    foreign = (
        "## Decisions\n\n"
        "| ID | Decision | Context | Timestamp |\n"
        "|----|----------|---------|-----------|\n"
        "| T1 | Rotate the vendor key | Required by policy | [0:10] |\n"
    )
    engine = fake_llm(replies=(foreign, TOPICS_DOC))
    job_id = enqueue(pool, make_extraction_drop("source-foreign-retry"), "source-foreign-retry")
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    # Two topics calls (the refusal and its retry) plus story 10.4's
    # ranking-signals pass, which runs after topics settle.
    assert len(engine.calls) == 3
    [meeting] = meetings(pool, job_id)
    assert len(topic_rows(pool, meeting["id"])) == 2


def test_an_idless_contentful_foreign_topics_reply_earns_one_retry(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    foreign = (
        "## Decisions\n\n"
        "| Decision | Context | Timestamp |\n"
        "|----------|---------|-----------|\n"
        "| Rotate the vendor key | Required by policy | [0:10] |\n"
    )
    engine = fake_llm(replies=(foreign, TOPICS_DOC))
    job_id = enqueue(
        pool,
        make_extraction_drop("source-idless-foreign-retry"),
        "source-idless-foreign-retry",
    )
    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    # Two topics calls (the refusal and its retry) plus story 10.4's
    # ranking-signals pass, which runs after topics settle.
    assert len(engine.calls) == 3
    [meeting] = meetings(pool, job_id)
    assert len(topic_rows(pool, meeting["id"])) == 2


def test_two_unusable_topics_replies_fail_the_stage_naming_the_document(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    fake_llm(replies=("prose, not a document", "still prose"))
    job_id = enqueue(pool, make_extraction_drop("source-unusable"), "source-unusable")
    assert runner.run_once(pool, app_config, content_root) is True

    status, _error = job_row(pool, job_id)
    assert status == "failed"
    error = stage_error(pool, job_id, "extract")
    assert error is not None
    assert "topics" in error
    assert "retry" in error


# --- story 10.4's fourth pass (F6 review coverage) --------------------------


def test_ranking_signals_land_with_provenance_and_reach_the_feed(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
    client,
) -> None:
    engine = fake_llm(replies=(TOPICS_DOC, SIGNALS_DOC))
    job_id = enqueue(pool, make_extraction_drop("source-signals"), "source-signals")

    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    assert len(engine.calls) == 2

    [meeting] = meetings(pool, job_id)
    moments = moment_ids(pool, meeting["id"])
    rows = signal_rows(pool, meeting["id"])
    assert [
        (row["moment_id"], row["kind"], row["label"], row["detail"], row["anchor_ms"], row["item_id"])
        for row in rows
    ] == [
        (moments[0], "risk", "The vendor key may be late", "Blocks cutover", 10_000, "R1"),
        (moments[1], "question", "Who approves the purchase order?", "Nobody claimed it", 45_000, "Q1"),
    ]
    assert signals_source(pool, meeting["id"]) == (2, 2)
    for row in rows:
        assert row["provenance"] | {
            "role": "extraction",
            "document_kind": core.DOC_RANKING_SIGNALS,
            "item_id": row["item_id"],
        } == row["provenance"]

    feed = client.get("/moments/feed?kind=risk").json()
    assert feed["total"] == len(feed["items"]) == 1
    assert feed["items"][0]["momentId"] == str(moments[0])
    assert any(reason["kind"] == "risk" for reason in feed["items"][0]["reasons"])


def test_ranking_signal_rerun_replaces_then_early_exit_clears_rows(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    fake_llm(replies=(TOPICS_DOC, SIGNALS_DOC))
    job_id = enqueue(pool, make_extraction_drop("source-signals-rerun"), "source-signals-rerun")
    assert runner.run_once(pool, app_config, content_root) is True
    [meeting] = meetings(pool, job_id)
    assert {row["item_id"] for row in signal_rows(pool, meeting["id"])} == {"R1", "Q1"}

    replacement = """\
## Open questions

| ID | Question | Detail | Timestamp |
|----|----------|--------|-----------|
| Q9 | Is key rotation automated? | Still unanswered | [1:35] |
"""
    engine = fake_llm(replies=(TOPICS_DOC, replacement))
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True
    assert [row["item_id"] for row in signal_rows(pool, meeting["id"])] == ["Q9"]
    assert signals_source(pool, meeting["id"]) == (1, 1)

    with pool.connection() as conn:
        conn.execute(
            "DELETE FROM transcript_segment WHERE meeting_id = %s",
            (meeting["id"],),
        )
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True
    assert len(engine.calls) == 2, "the early exit must not call the model"
    assert signal_rows(pool, meeting["id"]) == []
    assert signals_source(pool, meeting["id"]) is None


def test_ranking_signal_on_a_superseded_moment_is_named_and_skipped(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_llm(replies=(TOPICS_DOC, SIGNALS_DOC))
    job_id = enqueue(pool, make_extraction_drop("source-signals-super"), "source-signals-super")
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
    fake_llm(replies=(TOPICS_DOC, SIGNALS_DOC))
    requeue_extract(pool, job_id)
    assert runner.run_once(pool, app_config, content_root) is True

    rows = signal_rows(pool, meeting["id"])
    assert [row["item_id"] for row in rows] == ["Q1"]
    [discard] = [
        event
        for event in log_events(capsys)
        if event["event"] == "stage.extract.ranking_signal_discarded"
    ]
    assert (discard["item_id"], discard["reason"], discard["moment_id"]) == (
        "R1",
        "superseded-moment",
        str(moments[0]),
    )


def test_unusable_ranking_signals_reply_gets_exactly_one_retry(
    pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Any,
    make_extraction_drop: Callable[[str], Any],
    fake_llm: Callable[..., FakeLlm],
) -> None:
    duplicate = """\
## Risks
| ID | Risk | Detail | Timestamp |
|----|------|--------|-----------|
| R1 | First | one | [0:05] |
| R1 | Conflicting | two | [0:09] |
"""
    engine = fake_llm(replies=(TOPICS_DOC, duplicate, SIGNALS_DOC))
    job_id = enqueue(pool, make_extraction_drop("source-signals-retry"), "source-signals-retry")

    assert runner.run_once(pool, app_config, content_root) is True
    assert job_row(pool, job_id) == ("done", None)
    assert len(engine.calls) == 3
    assert engine.calls[1] == engine.calls[2]
    [meeting] = meetings(pool, job_id)
    assert {row["item_id"] for row in signal_rows(pool, meeting["id"])} == {"R1", "Q1"}
