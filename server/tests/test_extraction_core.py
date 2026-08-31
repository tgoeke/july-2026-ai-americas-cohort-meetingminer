"""The extraction decision core (story 4.1a): prompts, the markdown parser, AD-8.

Store-free on purpose — everything here is deterministic string work, so these
tests run with nothing up. The store-backed behavior (rows, adoption,
idempotence, the job reaching `done`) lives in `test_worker_extract.py`.

The parser tests are the `retrieval-prior-art.md` §8 regression: upstream's
indexer understood one of two markdown layouts, contributed zero decisions for
every meeting that used the other, and reported success. Every parser case
below is therefore asserted against **both** layouts of the same logical
content.
"""

from __future__ import annotations

import ast
import re
import sys
import types
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any
from uuid import UUID, uuid4

import pytest

from meetingminer.adapters.llm import (
    FallbackLlm,
    LlmError,
    LlmOptions,
    LlmUnavailableError,
    build_llm,
)
from meetingminer.adapters.llm.litellm import LiteLlmCompleter, resolve_api_base
from meetingminer.pipeline.extraction import (
    DOC_ACTION_ITEMS,
    DOC_ARCH_SUMMARY,
    DOC_RANKING_SIGNALS,
    DOC_TOPICS,
    KIND_ACTION_ITEM,
    KIND_ADR,
    KIND_SUMMARY,
    KNOWN_KINDS,
    LAYOUT_BULLET,
    LAYOUT_NONE,
    LAYOUT_TABLE,
    NO_DETAIL_BODY,
    PROMPT_VERSION,
    SUMMARY_TITLE,
    AnchorResolutionError,
    ArtifactParseError,
    build_actions_prompt,
    build_prompt,
    build_summary_prompt,
    parse_extraction_document,
    render_transcript,
    resolve_anchor,
)

from conftest import FakeLlm

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "meetingminer"
LLM_ADAPTER_ROOT = PACKAGE_ROOT / "adapters" / "llm"


@dataclass(frozen=True)
class _Turn:
    start_ms: int
    text: str
    speaker_label: str


@dataclass(frozen=True)
class _Moment:
    id: UUID
    start_ms: int
    end_ms: int


TURNS = (
    _Turn(2_000, "Everybody, good morning.", "Goeke, Timothy"),
    _Turn(62_000, "We will standardize on SFTP for the vendor feed.", "Goeke, Timothy"),
    _Turn(95_000, "Agreed, I will set up the credentials.", "Whitmore, Ellis"),
)


# --- render_transcript ------------------------------------------------------


def test_the_transcript_renders_as_the_timestamped_lines_both_prompts_declare() -> None:
    rendered = render_transcript(TURNS)
    assert rendered.splitlines() == [
        "[0:02] Goeke, Timothy: Everybody, good morning.",
        "[1:02] Goeke, Timothy: We will standardize on SFTP for the vendor feed.",
        "[1:35] Whitmore, Ellis: Agreed, I will set up the credentials.",
    ]


def test_a_turn_past_the_hour_renders_as_h_mm_ss() -> None:
    """90 minutes must read 1:30:15, never the nonsense timestamp 90:15."""
    rendered = render_transcript((_Turn(5_415_000, "Still going.", "Goeke, Timothy"),))
    assert rendered.startswith("[1:30:15] ")
    assert "90:15" not in rendered


def test_an_empty_turn_contributes_no_line_and_a_blank_label_reads_unknown() -> None:
    rendered = render_transcript(
        (
            _Turn(1_000, "   ", "Goeke, Timothy"),
            _Turn(2_000, "Said something.", "   "),
        )
    )
    assert rendered == "[0:02] Unknown: Said something."


# --- the two prompts (story 4.2: `template` is now config-owned, sourced --
# --- from the committed config.yaml via the `app_config` fixture) ---------


def test_both_prompts_embed_the_title_the_date_line_and_the_transcript(
    app_config,
) -> None:
    binding = app_config.settings.llm.roles.extraction
    transcript = render_transcript(TURNS)
    for prompt in (
        build_summary_prompt(
            transcript,
            template=binding.arch_summary_prompt,
            meeting_title="Data Hub Demo",
            meeting_date="6/10/2026",
        ),
        build_actions_prompt(
            transcript,
            template=binding.action_items_prompt,
            meeting_title="Data Hub Demo",
            meeting_date="6/10/2026",
        ),
    ):
        assert "Data Hub Demo" in prompt
        assert "This meeting took place on 6/10/2026." in prompt
        assert "[1:02] Goeke, Timothy: We will standardize on SFTP" in prompt
        # The grounding rules folded into the committed default template.
        assert "[m:ss]" in prompt
        assert "[Proposed]" in prompt
        assert "Do not invent facts" in prompt


def test_the_summary_prompt_pins_decisions_and_the_actions_prompt_pins_actions(
    app_config,
) -> None:
    binding = app_config.settings.llm.roles.extraction
    summary = build_summary_prompt("[0:02] A: hi", template=binding.arch_summary_prompt)
    actions = build_actions_prompt("[0:02] A: hi", template=binding.action_items_prompt)
    assert "## Decisions" in summary and "D1, D2, D3" in summary
    assert "## Action items" in actions and "A1, A2, A3" in actions
    assert "Committed, Assigned, or Tentative" in actions


def test_neither_prompt_frames_the_input_as_a_teams_meeting(app_config) -> None:
    # Story 6.7: a YouTube talk or a Zoom call goes through the same two
    # prompts, so the preamble names the input generically. Pinned so a later
    # edit cannot quietly re-introduce the Teams framing.
    binding = app_config.settings.llm.roles.extraction
    for template in (binding.arch_summary_prompt, binding.action_items_prompt):
        assert re.search(r"\bTeams\b", template) is None
        assert "one meeting or recorded session transcript" in template


def test_a_prompt_survives_a_missing_title_and_a_missing_date(app_config) -> None:
    binding = app_config.settings.llm.roles.extraction
    prompt = build_summary_prompt("[0:02] A: hi", template=binding.arch_summary_prompt)
    assert "untitled meeting" in prompt
    assert "This meeting took place" not in prompt


def test_build_prompt_routes_by_document_kind_and_refuses_an_unknown_one(
    app_config,
) -> None:
    binding = app_config.settings.llm.roles.extraction
    transcript = render_transcript(TURNS)
    assert build_prompt(
        DOC_ARCH_SUMMARY, transcript, template=binding.arch_summary_prompt
    ) == build_summary_prompt(transcript, template=binding.arch_summary_prompt)
    assert build_prompt(
        DOC_ACTION_ITEMS, transcript, template=binding.action_items_prompt
    ) == build_actions_prompt(transcript, template=binding.action_items_prompt)
    with pytest.raises(ValueError, match="unknown extraction document kind"):
        build_prompt("decisions", transcript, template=binding.arch_summary_prompt)


def test_prompt_version_is_a_recorded_constant() -> None:
    """Provenance depends on it existing and being stable within a build."""
    assert isinstance(PROMPT_VERSION, int)


def test_the_template_is_used_verbatim_no_code_needs_to_change_to_swap_it() -> None:
    """The unit-level proof of "a prompt swap is a config edit" (AD-10).

    A distinct sentinel string, unrelated to anything the engine-free core
    knows about, round-trips into the composed prompt exactly as written —
    nothing here reformats, wraps, or otherwise depends on prompt content.
    """
    sentinel = "SENTINEL-TEMPLATE-4f3c2a: this text is not a real prompt at all."
    transcript = render_transcript(TURNS)
    prompt = build_summary_prompt(transcript, template=sentinel)
    assert prompt.startswith(sentinel)
    assert sentinel in build_actions_prompt(transcript, template=sentinel)
    assert sentinel in build_prompt(DOC_ARCH_SUMMARY, transcript, template=sentinel)


# --- the parser: both layouts of the architecture summary -------------------
#
# The same three decisions, one risk, and one restated reference, rendered once
# as a markdown table and once as a bullet list. Timestamps deliberately use
# U+2011 non-breaking hyphens, parentheses, italics and a comma list, because
# every one of those appears in the sampled real output.

SUMMARY_TABLE = """\
# 1️⃣ Executive Summary

Prose that is not an item and must not become one.

## 3. Decisions made

| ID | Decision | Context and consequences | Mark | Timestamp |
|----|----------|--------------------------|------|-----------|
| **D1** | Vendor feeds move to SFTP | Replaces the shared mailbox | Confirmed | [4:23‑5:12] |
| D2 | Adopt Fabrikam for the hub | Alternative was custom code | Assumed | *(4:51‑4:53)* |
| D3 | Ops owns key rotation | Named in the runbook | Confirmed | (4:26, 5:08, 6:04) |

## 7. Concerns / risks

| ID | Risk | Timestamp |
|----|------|-----------|
| R1 | Key rotation unowned | [9:02] |

## 13. Close with

- **D1** — see above, no new stamp [4:23]
"""

SUMMARY_BULLET = """\
# Architecture summary

Prose that is not an item and must not become one.

## Decisions

- **D1** – Vendor feeds move to SFTP – Replaces the shared mailbox – Confirmed – [4:23‑5:12]
- D2 — Adopt Fabrikam for the hub — Alternative was custom code — Assumed — *(4:51‑4:53)*
- D3: Ops owns key rotation – Named in the runbook – Confirmed – (4:26, 5:08, 6:04)

## Risks

- R1 – Key rotation unowned – [9:02]

## Close

- **D1** — see above, no new stamp [4:23]
"""


def _identity(document: Any) -> list[tuple[str, str, int, str]]:
    return [
        (item.kind, item.title, item.anchor_ms, item.item_id)
        for item in document.artifacts
    ]


def test_both_summary_layouts_yield_the_same_artifacts() -> None:
    """The §8 regression: one of two layouts must never be the silent one."""
    table = parse_extraction_document(SUMMARY_TABLE, DOC_ARCH_SUMMARY)
    bullet = parse_extraction_document(SUMMARY_BULLET, DOC_ARCH_SUMMARY)

    expected = [
        (KIND_ADR, "Vendor feeds move to SFTP", 263_000, "D1"),
        (KIND_ADR, "Adopt Fabrikam for the hub", 291_000, "D2"),
        (KIND_ADR, "Ops owns key rotation", 266_000, "D3"),
    ]
    assert _identity(table) == expected
    assert _identity(bullet) == expected
    assert table.layout == LAYOUT_TABLE
    assert bullet.layout == LAYOUT_BULLET
    # The bodies carry the same cells; only the table's header labels differ,
    # because only the table had a header row to label them with.
    for one, other in zip(table.artifacts, bullet.artifacts):
        for cell in other.body.splitlines():
            assert cell in one.body


def test_the_parser_never_depends_on_heading_numbering() -> None:
    """Sampled meetings number headings with digits, keycaps, or not at all."""
    for heading in ("## 3. Decisions made", "# 3️⃣ Decisions", "### Decisions"):
        document = parse_extraction_document(
            SUMMARY_TABLE.replace("## 3. Decisions made", heading), DOC_ARCH_SUMMARY
        )
        assert len(document.artifacts) == 3


def test_a_risk_is_recognized_but_is_not_an_artifact() -> None:
    """`artifact.kind` admits only adr and action-item; R/O/BR wait for 4.x."""
    document = parse_extraction_document(SUMMARY_TABLE, DOC_ARCH_SUMMARY)
    assert all(item.item_id != "R1" for item in document.artifacts)
    assert all(item.kind == KIND_ADR for item in document.artifacts)


def test_a_later_reference_to_an_id_is_not_a_second_artifact() -> None:
    """Both prompts say later sections reference IDs instead of restating them."""
    document = parse_extraction_document(SUMMARY_TABLE, DOC_ARCH_SUMMARY)
    assert [item.item_id for item in document.artifacts] == ["D1", "D2", "D3"]


def test_a_ragged_row_and_a_drifting_header_still_parse() -> None:
    """Column headers drift and rows go ragged; ID plus timestamp do not."""
    drifted = """\
## Decisions

| Ref | What was decided | When |
|-----|------------------|------|
| D1 | Vendor feeds move to SFTP | [4:23] |
| D2 | Adopt Fabrikam for the hub | [4:51] | Confirmed | extra cell |
"""
    document = parse_extraction_document(drifted, DOC_ARCH_SUMMARY)
    assert _identity(document) == [
        (KIND_ADR, "Vendor feeds move to SFTP", 263_000, "D1"),
        (KIND_ADR, "Adopt Fabrikam for the hub", 291_000, "D2"),
    ]


# --- the parser: both layouts of the action-items document ------------------

ACTIONS_TABLE = """\
# Action Items — Data Hub Demo (6/10/26)

**2 action items:** 1 committed, 0 assigned, 1 tentative.

## Whitmore, Ellis

| ID | Action | Details / dependency | Timing (as stated) | Timestamp | Status |
|----|--------|----------------------|--------------------|-----------|--------|
| LW1 | Set up the SFTP credentials | Needs the vendor key | this week | [5:12] | Committed |

## Unowned — needs an owner

| ID | Action | Details / dependency | Timing | Timestamp | Status |
|----|--------|----------------------|--------|-----------|--------|
| A9 | Confirm the retention window | none | not stated | (7:40, 8:02) | Tentative* (ownership inferred) |

## Reported done

| ID | Owner | What | Timestamp |
|----|-------|------|-----------|
| RD1 | Goeke, Timothy | Updated the runbook | [2:10] |

## Watch items

| ID | Item | Timestamp |
|----|------|-----------|
| W1 | Legal review pending | [11:00] |
"""

ACTIONS_BULLET = """\
# Action Items — Data Hub Demo (6/10/26)

## Whitmore, Ellis

- LW1 – Set up the SFTP credentials – Needs the vendor key – this week – [5:12] – Committed

## Unowned — needs an owner

- A9 – Confirm the retention window – none – not stated – (7:40, 8:02) – Tentative* (ownership inferred)

## Reported done

- RD1 – Goeke, Timothy – Updated the runbook – [2:10]

## Watch items

- W1 – Legal review pending – [11:00]
"""


def test_both_action_layouts_yield_the_same_artifacts() -> None:
    table = parse_extraction_document(ACTIONS_TABLE, DOC_ACTION_ITEMS)
    bullet = parse_extraction_document(ACTIONS_BULLET, DOC_ACTION_ITEMS)
    expected = [
        (KIND_ACTION_ITEM, "Set up the SFTP credentials", 312_000, "LW1"),
        (KIND_ACTION_ITEM, "Confirm the retention window", 460_000, "A9"),
    ]
    assert _identity(table) == expected
    assert _identity(bullet) == expected


def test_reported_done_and_watch_items_are_not_action_items() -> None:
    """Their own prompt says so: finished work and pending decisions are not actions."""
    for document in (
        parse_extraction_document(ACTIONS_TABLE, DOC_ACTION_ITEMS),
        parse_extraction_document(ACTIONS_BULLET, DOC_ACTION_ITEMS),
    ):
        assert {item.item_id for item in document.artifacts} == {"LW1", "A9"}


def test_a_status_cell_matched_by_prefix_never_becomes_the_title() -> None:
    """`Tentative* (ownership inferred)` is a status, exactly as addActionCounts reads it."""
    document = parse_extraction_document(ACTIONS_TABLE, DOC_ACTION_ITEMS)
    unowned = next(item for item in document.artifacts if item.item_id == "A9")
    assert unowned.title == "Confirm the retention window"
    assert "Tentative* (ownership inferred)" in unowned.body


def test_the_summary_contributes_decisions_only_so_actions_are_never_doubled() -> None:
    """A summary's own action table is the same commitments the action doc lists."""
    summary_with_actions = SUMMARY_TABLE + """
## 5. Action items

| ID | Owner | Action | Timestamp |
|----|-------|--------|-----------|
| A1 | Whitmore, Ellis | Set up the SFTP credentials | [5:12] |
"""
    document = parse_extraction_document(summary_with_actions, DOC_ARCH_SUMMARY)
    assert [item.item_id for item in document.artifacts] == ["D1", "D2", "D3"]


# --- timestamps -------------------------------------------------------------


@pytest.mark.parametrize(
    "stamp, anchor_ms",
    [
        ("[4:23]", 263_000),
        ("4:23", 263_000),
        ("(4:23)", 263_000),
        ("*(4:23‑5:12)*", 263_000),  # U+2011 range, italicised
        ("[4:23–5:12]", 263_000),  # en dash
        ("[4:23—5:12]", 263_000),  # em dash
        ("(5:08, 4:26, 6:04)", 266_000),  # comma list: earliest wins
        ("Confirmed – [7:47‑8:24]", 467_000),  # fused into a status cell
        ("[1:04:23]", 3_863_000),  # h:mm:ss
    ],
)
def test_every_observed_timestamp_form_normalizes_to_the_earliest_anchor(
    stamp: str, anchor_ms: int
) -> None:
    document = parse_extraction_document(
        f"## Decisions\n\n| D1 | Vendor feeds move to SFTP | {stamp} |\n",
        DOC_ARCH_SUMMARY,
    )
    [item] = document.artifacts
    assert item.anchor_ms == anchor_ms


# --- the anchor comes from the item's own timestamp, not from anywhere on the row


def test_the_anchor_is_taken_from_the_labelled_timestamp_column() -> None:
    """A stamp mentioned in prose must never outrank the item's own column.

    "as agreed at [2:10]" in a Details cell is earlier than the real anchor,
    resolves to a real moment, and would produce a confidently wrong citation.
    """
    document = parse_extraction_document(
        """\
## Decisions

| ID | Decision | Context and consequences | Timestamp |
|----|----------|--------------------------|-----------|
| D1 | Vendor feeds move to SFTP | Confirms what was agreed at [2:10] | [4:23] |
""",
        DOC_ARCH_SUMMARY,
    )
    [item] = document.artifacts
    assert item.anchor_ms == 263_000, "the Timestamp column, not the earliest stamp"


def test_the_anchor_is_taken_from_a_stamp_only_cell_when_no_header_names_one() -> None:
    document = parse_extraction_document(
        """\
## Decisions

| D1 | Vendor feeds move to SFTP | Follows the 9:00 standup decision | [4:23] |
""",
        DOC_ARCH_SUMMARY,
    )
    [item] = document.artifacts
    assert item.anchor_ms == 263_000, "the stamp-only cell, not the 9:00 in prose"


def test_the_whole_row_is_the_anchor_of_last_resort() -> None:
    """A prose bullet has no separable stamp cell, and still has to anchor."""
    document = parse_extraction_document(
        "## Decisions\n\n- **D1** Vendor feeds move to SFTP, agreed at [4:23].\n",
        DOC_ARCH_SUMMARY,
    )
    [item] = document.artifacts
    assert item.anchor_ms == 263_000


# --- a decision that starts with a status word is still a decision -----------


@pytest.mark.parametrize(
    "decision",
    [
        "Open the firewall port for SFTP",
        "Risk register moves to Jira",
        "Assigned owners are tracked in the runbook",
    ],
)
def test_a_decision_opening_with_a_status_word_keeps_its_own_title(
    decision: str,
) -> None:
    """A bare prefix match stole these titles and used the context cell instead."""
    document = parse_extraction_document(
        f"## Decisions\n\n| D1 | {decision} | Agreed in the walkthrough | Confirmed | [4:23] |\n",
        DOC_ARCH_SUMMARY,
    )
    [item] = document.artifacts
    assert item.title == decision


def test_a_real_status_cell_is_still_excluded_from_the_title() -> None:
    document = parse_extraction_document(
        "## Action items\n\n| A1 | Tentative* (ownership inferred) | Ship the runbook | [4:23] |\n",
        DOC_ACTION_ITEMS,
    )
    [item] = document.artifacts
    assert item.title == "Ship the runbook"


# --- the owner reaches the artifact on both paths ---------------------------


def test_an_owner_in_the_heading_and_an_owner_in_a_column_both_reach_the_body() -> None:
    """The convergence requirement: adoption and generation must agree.

    The real summariser puts the owner in the `## <Owner>` heading; the
    generated prompt puts it in an Owner column. Reading only one would mean an
    adopted item arrives with no owner and a generated one has it.
    """
    from_heading = parse_extraction_document(
        """\
## Whitmore, Ellis

| ID | Action | Timestamp |
|----|--------|-----------|
| A1 | Set up the SFTP credentials | [5:12] |
""",
        DOC_ACTION_ITEMS,
    )
    from_column = parse_extraction_document(
        """\
## Action items

| ID | Action | Owner | Timestamp |
|----|--------|-------|-----------|
| A1 | Set up the SFTP credentials | Whitmore, Ellis | [5:12] |
""",
        DOC_ACTION_ITEMS,
    )
    for document in (from_heading, from_column):
        [item] = document.artifacts
        assert item.owner == "Whitmore, Ellis"
        assert item.body.startswith("Owner: Whitmore, Ellis")
    # And the owner is rendered exactly once, not once per shape it arrived in.
    [column_item] = from_column.artifacts
    assert column_item.body.count("Whitmore, Ellis") == 1


def test_an_unowned_section_and_an_unowned_cell_both_mean_no_owner() -> None:
    for document_text in (
        "## Unowned — needs an owner\n\n| A1 | Confirm the retention window | [5:12] |\n",
        "## Action items\n\n| ID | Action | Owner | Timestamp |\n| A1 | Confirm it | unowned | [5:12] |\n",
    ):
        [item] = parse_extraction_document(document_text, DOC_ACTION_ITEMS).artifacts
        assert item.owner is None
        assert "Owner:" not in item.body


def test_a_decision_never_carries_an_owner() -> None:
    [item] = parse_extraction_document(SUMMARY_TABLE, DOC_ARCH_SUMMARY).artifacts[:1]
    assert item.owner is None


# --- per-owner ID reuse -----------------------------------------------------


def test_two_owners_may_each_carry_an_a1() -> None:
    """Real action documents number per owner; a global key dropped the second."""
    document = parse_extraction_document(
        """\
## Whitmore, Ellis

| ID | Action | Timestamp |
|----|--------|-----------|
| A1 | Set up the SFTP credentials | [5:12] |

## Goeke, Timothy

| ID | Action | Timestamp |
|----|--------|-----------|
| A1 | Circulate the migration note | [6:40] |
""",
        DOC_ACTION_ITEMS,
    )
    assert [(item.item_id, item.owner) for item in document.artifacts] == [
        ("A1", "Whitmore, Ellis"),
        ("A1", "Goeke, Timothy"),
    ]


def test_the_summary_still_dedups_a_restated_id_across_sections() -> None:
    """Decisions are numbered once for the whole document, so D1 is D1."""
    document = parse_extraction_document(SUMMARY_TABLE, DOC_ARCH_SUMMARY)
    assert [item.item_id for item in document.artifacts] == ["D1", "D2", "D3"]


# --- ragged rows, lowercase IDs, and an absent body -------------------------


def test_an_id_behind_a_ragged_leading_cell_is_still_found() -> None:
    """`|  | D4 | ... |` was dropped with no trace — the §8 shape per row."""
    document = parse_extraction_document(
        "## Decisions\n\n|  | D4 | Vendor feeds move to SFTP | [4:23] |\n",
        DOC_ARCH_SUMMARY,
    )
    assert [(item.item_id, item.title) for item in document.artifacts] == [
        ("D4", "Vendor feeds move to SFTP")
    ]


@pytest.mark.parametrize("spelling", ["d1", "D1", "d 1"])
def test_item_ids_are_read_case_insensitively(spelling: str) -> None:
    """A document writing `d1` writes the same ID; reading it as prose is a zero."""
    document = parse_extraction_document(
        f"## Decisions\n\n| {spelling} | Vendor feeds move to SFTP | [4:23] |\n",
        DOC_ARCH_SUMMARY,
    )
    assert [item.item_id for item in document.artifacts] == ["D1"]


def test_an_item_with_no_detail_says_so_rather_than_repeating_its_title() -> None:
    """4.3's reviewer must tell "nothing was recorded" from "the title again"."""
    document = parse_extraction_document(
        "## Decisions\n\n- **D1** Vendor feeds move to SFTP [4:23]\n",
        DOC_ARCH_SUMMARY,
    )
    [item] = document.artifacts
    assert item.title == "Vendor feeds move to SFTP [4:23]"
    assert item.body == NO_DETAIL_BODY


# --- refusals: every one keeps its own complaint -----------------------------


def test_an_unanchored_item_is_a_named_parse_error() -> None:
    """Documents from the pre-7/16/26 prompt lineage carry no anchors at all."""
    unanchored = """\
## Decisions

| ID | Decision | Mark |
|----|----------|------|
| D1 | Vendor feeds move to SFTP | Confirmed |
"""
    with pytest.raises(ArtifactParseError) as excinfo:
        parse_extraction_document(unanchored, DOC_ARCH_SUMMARY)
    assert "D1" in str(excinfo.value)
    assert "no [m:ss] anchor" in str(excinfo.value)


def test_an_unrelated_table_is_not_a_recognized_architecture_summary() -> None:
    """A table outside target sections cannot become a successful empty parse."""
    document = """\
# Notes

| Topic | Detail |
|-------|--------|
| Hosting | The plan is documented elsewhere |
"""
    with pytest.raises(ArtifactParseError, match="recognized target section"):
        parse_extraction_document(document, DOC_ARCH_SUMMARY)


@pytest.mark.parametrize(
    "document, complaint",
    [
        ("", "is empty"),
        ("   \n\n  ", "is empty"),
        (
            "# Architecture summary\n\nNothing but prose, no table and no bullets.\n",
            "neither known layout matched",
        ),
        (
            "## Decisions\n\n| D1 |  | [4:23] |\n",
            "no text beyond its ID",
        ),
    ],
)
def test_every_malformed_document_is_a_named_refusal(
    document: str, complaint: str
) -> None:
    """No silent zero: an unusable document is refused by name, never as ()."""
    with pytest.raises(ArtifactParseError) as excinfo:
        parse_extraction_document(document, DOC_ARCH_SUMMARY)
    assert complaint in str(excinfo.value)


def test_an_unknown_document_kind_is_a_programming_error_not_a_parse_error() -> None:
    with pytest.raises(ValueError, match="unknown extraction document kind"):
        parse_extraction_document("## Decisions\n\n| D1 | x | [0:01] |\n", "decisions")


# --- the no-silent-zero signal ----------------------------------------------


def test_a_header_only_table_is_an_honest_nothing_not_a_populated_section() -> None:
    document = parse_extraction_document(
        "## Decisions\n\n| ID | Decision | Timestamp |\n|----|----------|-----------|\n",
        DOC_ARCH_SUMMARY,
    )
    assert document.artifacts == ()
    assert document.populated_target_sections == ()
    assert document.layout == LAYOUT_NONE


def test_a_populated_target_section_that_yields_nothing_is_reported_by_name() -> None:
    """The §8 shape: rows are plainly there and no artifact came out of them."""
    only_risks = """\
## Decisions and open questions

| ID | Item | Timestamp |
|----|------|-----------|
| O1 | Who owns key rotation | [9:02] |
| R1 | Vendor key expiry unknown | [9:40] |
"""
    document = parse_extraction_document(only_risks, DOC_ARCH_SUMMARY)
    assert document.artifacts == ()
    assert document.populated_target_sections == ("Decisions and open questions",)


# --- anchor resolution ------------------------------------------------------

MOMENT_A = _Moment(uuid4(), 0, 30_000)
MOMENT_B = _Moment(uuid4(), 30_000, 90_000)
MOMENT_C = _Moment(uuid4(), 90_000, 120_000)
MOMENTS = (MOMENT_A, MOMENT_B, MOMENT_C)


@pytest.mark.parametrize(
    "anchor_ms, expected",
    [
        (0, MOMENT_A),  # exactly the first start
        (17_000, MOMENT_A),  # inside
        (29_999, MOMENT_A),  # the instant before the boundary
        (30_000, MOMENT_B),  # the boundary belongs to the moment it opens
        (89_999, MOMENT_B),
        (90_000, MOMENT_C),
        (120_000, MOMENT_C),  # exactly the last end
    ],
)
def test_an_anchor_resolves_to_the_moment_containing_it(
    anchor_ms: int, expected: _Moment
) -> None:
    """Greatest start_ms <= t, half-open [start, next_start) — plan_moments' own rule."""
    assert resolve_anchor(anchor_ms, MOMENTS) == expected.id


@pytest.mark.parametrize("anchor_ms", [-1, 120_001, 900_000])
def test_an_anchor_outside_the_timeline_is_a_named_error_never_a_snap(
    anchor_ms: int,
) -> None:
    """Snapping would manufacture a citation the timeline does not contain."""
    with pytest.raises(AnchorResolutionError) as excinfo:
        resolve_anchor(anchor_ms, MOMENTS)
    message = str(excinfo.value)
    assert "0:00-2:00" in message
    assert str(anchor_ms) in message


def test_an_anchor_falling_in_a_gap_between_moments_is_a_named_error() -> None:
    """Greatest `start_ms <= t` is the containing moment only *because* moments
    tile. If the tiling ever develops a hole, picking the moment before the
    hole would cite an instant that moment does not cover."""
    holed = (_Moment(uuid4(), 0, 10_000), _Moment(uuid4(), 30_000, 60_000))
    with pytest.raises(AnchorResolutionError) as excinfo:
        resolve_anchor(20_000, holed)
    assert "falls in a gap between moments" in str(excinfo.value)
    assert "does not contain it" in str(excinfo.value)


def test_an_anchor_against_a_meeting_with_no_moments_is_a_named_error() -> None:
    with pytest.raises(AnchorResolutionError, match="no moments"):
        resolve_anchor(1_000, ())


def test_moment_order_in_the_bundle_does_not_change_resolution() -> None:
    shuffled = (MOMENT_C, MOMENT_A, MOMENT_B)
    assert resolve_anchor(17_000, shuffled) == MOMENT_A.id
    assert resolve_anchor(95_000, shuffled) == MOMENT_C.id


# --- the fallback composer and the config binding (AD-8, AD-10) -------------


class _Binding:
    """A role binding's whole shape, including story 4.1a's three call knobs."""

    def __init__(self, **overrides: Any) -> None:
        self.model = "claude-imaginary-9"
        self.fallback = "ollama/some-other:7b"
        self.base_url: str | None = None
        self.fallback_base_url: str | None = None
        self.timeout_seconds: float | None = None
        self.num_ctx: int | None = None
        for key, value in overrides.items():
            setattr(self, key, value)


class _Provider:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


_PROVIDERS = {
    "anthropic": _Provider("https://api.anthropic.com"),
    "openai": _Provider("https://openai.example/v1"),
    "ollama": _Provider("http://localhost:11434"),
}


def test_build_llm_constructs_the_adapter_with_the_configured_model_strings() -> None:
    """A config edit is the whole swap: the model strings pass through verbatim."""
    composed = build_llm(_Binding(), _PROVIDERS)
    assert isinstance(composed, FallbackLlm)
    assert composed.primary.model == "claude-imaginary-9"
    assert composed.primary.api_base == "https://api.anthropic.com"
    assert composed.fallback is not None
    assert composed.fallback.model == "ollama/some-other:7b"
    assert composed.fallback.api_base == "http://localhost:11434"


def test_the_roles_request_knobs_reach_the_primary_and_the_fallback_alike() -> None:
    """A fallback answering with a truncated context would be a second binding."""
    composed = build_llm(
        _Binding(
            model="ollama/gpt-oss:120b",
            fallback="ollama/qwen3:32b",
            timeout_seconds=900.0,
            num_ctx=65536,
        ),
        _PROVIDERS,
    )
    for completer in (composed.primary, composed.fallback):
        assert completer is not None
        assert completer.timeout_seconds == 900.0
        assert completer.num_ctx == 65536


def test_the_roles_endpoint_reaches_the_primary_and_not_the_fallback() -> None:
    """The fallback is a different model; assuming the primary's host serves it
    is how a fallback goes silently dead, leaving "both models failed" as the
    only outcome the first time the primary misses. Absent an explicit
    `fallback_base_url` it resolves through `providers`, exactly as it did
    before this role had an endpoint at all."""
    composed = build_llm(
        _Binding(
            model="ollama/gpt-oss:120b",
            fallback="ollama/qwen3:32b",
            base_url="http://a-different-host.invalid:11434",
        ),
        _PROVIDERS,
    )
    assert composed.primary.api_base == "http://a-different-host.invalid:11434"
    assert composed.fallback is not None
    assert composed.fallback.api_base == "http://localhost:11434"


def test_a_role_may_declare_its_fallbacks_endpoint_explicitly() -> None:
    composed = build_llm(
        _Binding(
            model="ollama/gpt-oss:120b",
            fallback="ollama/qwen3:32b",
            base_url="http://primary.invalid:11434",
            fallback_base_url="http://secondary.invalid:11434",
        ),
        _PROVIDERS,
    )
    assert composed.primary.api_base == "http://primary.invalid:11434"
    assert composed.fallback is not None
    assert composed.fallback.api_base == "http://secondary.invalid:11434"


def test_an_ignored_num_ctx_is_named_rather_than_silently_dropped() -> None:
    """It exists to prevent a silent truncation; dropping it silently is the
    same loss one layer down."""
    events: list[dict[str, Any]] = []
    build_llm(
        _Binding(model="claude-imaginary-9", fallback=None, num_ctx=65536),
        _PROVIDERS,
        log=lambda event, **fields: events.append({"event": event, **fields}),
    )
    [ignored] = [e for e in events if e["event"] == "llm.num_ctx_ignored"]
    assert ignored["model"] == "claude-imaginary-9"
    assert ignored["num_ctx"] == 65536

    events.clear()
    build_llm(
        _Binding(model="ollama/gpt-oss:120b", fallback=None, num_ctx=65536),
        _PROVIDERS,
        log=lambda event, **fields: events.append({"event": event, **fields}),
    )
    assert not [e for e in events if e["event"] == "llm.num_ctx_ignored"]


def test_a_role_that_declares_no_timeout_keeps_the_adapter_default() -> None:
    from meetingminer.adapters.llm.litellm import DEFAULT_TIMEOUT_SECONDS

    composed = build_llm(_Binding(), _PROVIDERS)
    assert composed.primary.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert composed.primary.num_ctx is None


def test_the_committed_extraction_binding_reaches_no_paid_provider(
    app_config: Any,
) -> None:
    """AC 6, asserted against the real `config.yaml` rather than a fixture.

    Story 4.1 defaulted extraction to `claude-sonnet-5` and the backfill cost
    358 paid calls over 5 of 28 meetings before it was stopped. Whole-transcript
    extraction is a local-model job, and *no configuration path in the committed
    file reaches a paid provider* — primary, fallback, and endpoint alike.
    """
    binding = app_config.settings.llm.roles.extraction
    # Both models are Ollama-served. Asserted as a property rather than as
    # literal host strings: the extraction host is a deployment detail that
    # will move, and a suite that goes red on a clone behind a different
    # network is a suite people learn to ignore.
    assert binding.model.startswith("ollama/")
    assert binding.fallback is not None and binding.fallback.startswith("ollama/")
    # Correctness settings, not tuning: without `num_ctx` Ollama silently
    # truncates a long transcript, and 120s is short for a whole-meeting pass.
    assert binding.num_ctx is not None and binding.num_ctx >= 32768
    assert binding.timeout_seconds is not None and binding.timeout_seconds >= 300

    composed = build_llm(binding, app_config.settings.providers)
    paid_hosts = {
        _host_of(provider.base_url)
        for name, provider in app_config.settings.providers.items()
        if name in ("anthropic", "openai", "openrouter")
    }
    for completer in (composed.primary, composed.fallback):
        assert completer is not None
        assert completer.model.startswith("ollama/")
        host = _host_of(completer.api_base)
        assert host not in paid_hosts, "no configuration path reaches a paid provider"
        assert _is_private_host(host), f"{host} is not a private or local host"


def _host_of(url: str | None) -> str:
    return urlsplit(url or "").hostname or ""


def _is_private_host(host: str) -> bool:
    """Whether the host is loopback, a private address, or a local name."""
    if host in ("localhost", "") or host.endswith(".local"):
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def test_resolve_api_base_covers_prefixed_bare_and_unknown_models() -> None:
    assert resolve_api_base("ollama/qwen3:32b", _PROVIDERS) == "http://localhost:11434"
    assert resolve_api_base("claude-sonnet-5", _PROVIDERS) == "https://api.anthropic.com"
    assert resolve_api_base("gpt-4o", _PROVIDERS) == "https://openai.example/v1"
    # An unknown prefix (or a non-claude bare id) is LiteLLM's routing problem,
    # not a config error this adapter invents.
    assert resolve_api_base("openrouter/some/model", _PROVIDERS) is None
    assert resolve_api_base("gpt-oss", _PROVIDERS) is None


def test_fallback_engages_at_call_time_and_serves_the_rest_of_the_meeting() -> None:
    primary = FakeLlm(
        replies=(LlmUnavailableError("anthropic is not answering"),),
        model="primary-model",
    )
    fallback = FakeLlm(model="fallback-model")
    events: list[str] = []
    composed = FallbackLlm(primary, fallback, log=lambda event, **_kw: events.append(event))

    first = composed.complete("prompt one")
    second = composed.complete("prompt two")

    assert first.model == "fallback-model" and first.fallback_engaged is True
    assert second.fallback_engaged is True
    # Once engaged, the primary is not retried mid-meeting...
    assert primary.calls == ["prompt one"]
    assert fallback.calls == ["prompt one", "prompt two"]
    # ...and the substitution was logged exactly once.
    assert events.count("llm.fallback_engaged") == 1


def test_the_composer_forwards_per_call_options_to_whichever_model_answers() -> None:
    primary = FakeLlm(replies=(LlmUnavailableError("down"),), model="primary-model")
    fallback = FakeLlm(model="fallback-model")
    options = LlmOptions(num_ctx=65536, timeout_seconds=900.0)
    FallbackLlm(primary, fallback).complete("prompt", options)
    assert primary.options == [options]
    assert fallback.options == [options]


def test_both_models_failing_raises_with_both_errors_named() -> None:
    composed = FallbackLlm(
        FakeLlm(replies=(LlmUnavailableError("primary down"),)),
        FakeLlm(replies=(LlmUnavailableError("fallback down"),)),
    )
    with pytest.raises(LlmError) as excinfo:
        composed.complete("prompt")
    assert "primary down" in str(excinfo.value)
    assert "fallback down" in str(excinfo.value)


def test_a_primary_without_a_fallback_raises_the_primary_error() -> None:
    composed = FallbackLlm(FakeLlm(replies=(LlmUnavailableError("down"),)), None)
    with pytest.raises(LlmUnavailableError, match="down"):
        composed.complete("prompt")


def test_a_plain_llm_error_from_the_primary_also_engages_the_fallback() -> None:
    """The catch is the base `LlmError`, not only the unavailable subclass —
    a primary that answered unusably still cannot answer, and narrowing the
    catch to `LlmUnavailableError` must fail this test."""
    primary = FakeLlm(replies=(LlmError("model answered with no usable text"),))
    fallback = FakeLlm(model="fallback-model")
    reply = FallbackLlm(primary, fallback).complete("prompt")
    assert reply.model == "fallback-model"
    assert reply.fallback_engaged is True


def test_a_healthy_primary_never_reports_fallback_engaged() -> None:
    composed = FallbackLlm(FakeLlm(model="primary-model"), FakeLlm(model="unused"))
    reply = composed.complete("prompt")
    assert reply.model == "primary-model"
    assert reply.fallback_engaged is False


# --- the LiteLLM completer, against a stubbed SDK ---------------------------
#
# `LiteLlmCompleter.complete` imports `litellm` lazily, so inserting a stub
# module into `sys.modules` is enough to execute the real adapter code —
# passthrough, exception mapping, and reply handling — with no provider, no
# network, and no multi-second SDK import.

_MAPPED_EXCEPTION_NAMES = (
    "APIConnectionError",
    "Timeout",
    "ServiceUnavailableError",
    "InternalServerError",
    "RateLimitError",
    "AuthenticationError",
    "PermissionDeniedError",
)

_OK_DOCUMENT = "## Decisions\n\n| ID | Decision | Timestamp |\n"


def _response(content: Any, **extra: Any) -> types.SimpleNamespace:
    message = types.SimpleNamespace(content=content)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=message)], **extra
    )


@pytest.fixture()
def stub_litellm(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A `litellm` stand-in the adapter's lazy import resolves to.

    Configure `stub.result` (returned) or `stub.error` (raised) per test;
    every call's kwargs are recorded on `stub.calls`. `stub.exceptions`
    carries real exception classes under the SDK's names — including two the
    adapter deliberately does *not* map to unavailability: `BadRequestError`,
    and `NotFoundError`, which since story 8.2 is the model-the-provider-does
    -not-serve refusal that must never engage the fallback (backlog B-38).

    Every name the adapter references must appear here, or the lazy
    `import litellm` inside `complete` resolves to a stub without it and the
    `except` clause raises `AttributeError` instead of mapping the failure.
    """
    stub = types.ModuleType("litellm")
    stub.exceptions = types.SimpleNamespace(
        **{
            name: type(name, (Exception,), {})
            for name in (*_MAPPED_EXCEPTION_NAMES, "BadRequestError", "NotFoundError")
        }
    )
    stub.calls = []
    stub.result = _response(_OK_DOCUMENT)
    stub.error = None

    def completion(**kwargs: Any) -> Any:
        stub.calls.append(kwargs)
        if stub.error is not None:
            raise stub.error
        return stub.result

    stub.completion = completion
    monkeypatch.setitem(sys.modules, "litellm", stub)
    return stub


def test_the_completer_passes_the_binding_through_to_the_sdk(
    stub_litellm: Any,
) -> None:
    completer = LiteLlmCompleter("ollama/qwen3:32b", _PROVIDERS, timeout_seconds=42.0)
    stub_litellm.result = _response(_OK_DOCUMENT, model="qwen3:32b-served")

    reply = completer.complete("the prompt")

    [call] = stub_litellm.calls
    assert call == {
        "model": "ollama/qwen3:32b",
        "messages": [{"role": "user", "content": "the prompt"}],
        "api_base": "http://localhost:11434",
        "timeout": 42.0,
    }
    assert reply.text == _OK_DOCUMENT
    # Provenance records the model that actually answered when the SDK
    # reports one...
    assert reply.model == "qwen3:32b-served"
    assert reply.fallback_engaged is False


def test_the_completer_falls_back_to_the_configured_model_string(
    stub_litellm: Any,
) -> None:
    """...and the configured string when the response names none."""
    completer = LiteLlmCompleter("claude-sonnet-5", _PROVIDERS)
    stub_litellm.result = _response(_OK_DOCUMENT)  # no `model` attribute
    assert completer.complete("p").model == "claude-sonnet-5"
    assert stub_litellm.calls[0]["api_base"] == "https://api.anthropic.com"


def test_num_ctx_reaches_the_sdk_for_an_ollama_model(stub_litellm: Any) -> None:
    """A correctness setting: without it Ollama silently truncates the transcript."""
    completer = LiteLlmCompleter("ollama/gpt-oss:120b", _PROVIDERS, num_ctx=65536)
    completer.complete("p")
    assert stub_litellm.calls[0]["num_ctx"] == 65536


def test_num_ctx_is_absent_for_every_other_provider(stub_litellm: Any) -> None:
    """It is an Ollama request parameter; another provider would refuse it."""
    LiteLlmCompleter("claude-sonnet-5", _PROVIDERS, num_ctx=65536).complete("p")
    assert "num_ctx" not in stub_litellm.calls[0]


def test_per_call_options_override_the_binding(stub_litellm: Any) -> None:
    completer = LiteLlmCompleter(
        "ollama/gpt-oss:120b", _PROVIDERS, timeout_seconds=120.0, num_ctx=8192
    )
    completer.complete("p", LlmOptions(num_ctx=65536, timeout_seconds=900.0))
    assert stub_litellm.calls[0]["num_ctx"] == 65536
    assert stub_litellm.calls[0]["timeout"] == 900.0
    # An options value left None means "whatever the binding configured".
    completer.complete("p", LlmOptions())
    assert stub_litellm.calls[1]["num_ctx"] == 8192
    assert stub_litellm.calls[1]["timeout"] == 120.0


def test_the_roles_base_url_wins_over_the_shared_provider_endpoint(
    stub_litellm: Any,
) -> None:
    completer = LiteLlmCompleter(
        "ollama/gpt-oss:120b", _PROVIDERS, base_url="http://10.77.0.52:11434"
    )
    completer.complete("p")
    assert stub_litellm.calls[0]["api_base"] == "http://10.77.0.52:11434"


@pytest.mark.parametrize("name", _MAPPED_EXCEPTION_NAMES)
def test_each_mapped_sdk_exception_surfaces_as_unavailable(
    stub_litellm: Any, name: str
) -> None:
    completer = LiteLlmCompleter("claude-sonnet-5", _PROVIDERS)
    stub_litellm.error = getattr(stub_litellm.exceptions, name)("provider said no")
    with pytest.raises(LlmUnavailableError) as excinfo:
        completer.complete("p")
    assert "claude-sonnet-5" in str(excinfo.value)
    assert name in str(excinfo.value)


def test_an_unmapped_sdk_exception_surfaces_as_the_base_error(
    stub_litellm: Any,
) -> None:
    """A refused *request* is not an unavailable host: no fallback fixes it."""
    completer = LiteLlmCompleter("claude-sonnet-5", _PROVIDERS)
    stub_litellm.error = stub_litellm.exceptions.BadRequestError("prompt too long")
    with pytest.raises(LlmError) as excinfo:
        completer.complete("p")
    assert not isinstance(excinfo.value, LlmUnavailableError)
    assert "prompt too long" in str(excinfo.value)


@pytest.mark.parametrize(
    "response",
    [
        _response(""),  # empty text
        _response("   \n"),  # whitespace-only text
        _response(None),  # missing content
        _response([{"type": "text", "text": "blocks"}]),  # content blocks
        types.SimpleNamespace(choices=[]),  # no completion at all
        types.SimpleNamespace(choices=None),  # degenerate: TypeError shape
        types.SimpleNamespace(choices=[{"message": {}}]),  # dict-shaped choice
    ],
)
def test_degenerate_responses_surface_as_the_base_error(
    stub_litellm: Any, response: Any
) -> None:
    completer = LiteLlmCompleter("claude-sonnet-5", _PROVIDERS)
    stub_litellm.result = response
    with pytest.raises(LlmError) as excinfo:
        completer.complete("p")
    assert not isinstance(excinfo.value, LlmUnavailableError)


def test_a_broken_litellm_install_is_a_named_port_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `None` in sys.modules makes `import litellm` raise ImportError — the
    # "package not installed / install broken" shape.
    monkeypatch.setitem(sys.modules, "litellm", None)
    completer = LiteLlmCompleter("claude-sonnet-5", _PROVIDERS)
    with pytest.raises(LlmError, match="not importable") as excinfo:
        completer.complete("p")
    assert not isinstance(excinfo.value, LlmUnavailableError)


# --- AD-8: litellm is imported only under adapters/llm/ ---------------------


def _imported_roots(path: Path) -> set[str]:
    """Top-level imports, wherever they appear — module or function scope.

    `ast.walk` reaches nested nodes, so the adapter's deliberate lazy import
    inside `complete()` is still counted for the positive check below.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_litellm_is_imported_only_under_the_llm_adapter() -> None:
    """AD-8: feature code sees the `Llm` port; only the adapter sees the SDK."""
    offenders = [
        str(path.relative_to(PACKAGE_ROOT))
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if not path.is_relative_to(LLM_ADAPTER_ROOT)
        and "litellm" in _imported_roots(path)
    ]
    assert not offenders, (
        "AD-8: `litellm` may be imported only under meetingminer/adapters/llm/."
        f" These modules import it directly: {offenders}"
    )


def test_the_llm_adapter_does_import_litellm() -> None:
    """The negative test above is only meaningful if the positive one holds."""
    roots: set[str] = set()
    for path in LLM_ADAPTER_ROOT.rglob("*.py"):
        roots |= _imported_roots(path)
    assert "litellm" in roots


# --- story 12.2: the executive summary is kept, not dropped -----------------
#
# The architecture summary is a whole-meeting analysis and until now only the
# rows under its decisions heading survived parsing. These cases pin the prose,
# the three heading spellings sampled from real output, and — just as
# important — that capturing it changed nothing about what the document already
# produced.

# The three spellings sampled from real puller output. Numbering, emoji and
# heading level all vary; the two-word phrase is what they share, which is why
# it is what the parser keys on.
_EXEC_SUMMARY_HEADINGS = (
    "# 1️⃣ Executive Summary",
    "## 1. Header & Executive Summary",
    "# 1 Executive Summary",
)


def _summary_document(heading: str, prose: str) -> str:
    """One architecture summary: an executive-summary section, then decisions.

    The decisions heading is deliberately a *deeper* level than the first
    heading in two of the three spellings, because that is what real documents
    do and it is the case a "run to the next same-or-shallower heading" rule
    would get wrong by swallowing the table.
    """
    return (
        f"{heading}\n"
        f"\n"
        f"{prose}\n"
        f"\n"
        f"## 3. Decisions made\n"
        f"\n"
        f"| ID | Decision | Mark | Timestamp |\n"
        f"|----|----------|------|-----------|\n"
        f"| D1 | Vendor feeds move to SFTP | Confirmed | [4:23] |\n"
    )


@pytest.mark.parametrize("heading", _EXEC_SUMMARY_HEADINGS)
def test_every_sampled_executive_summary_heading_is_recognized(heading: str) -> None:
    """Matched on heading text, never on numbering — the parser's standing rule."""
    prose = "- Vendor feeds move to SFTP [4:23]\n- Key rotation is unowned [9:02]"
    document = parse_extraction_document(
        _summary_document(heading, prose), DOC_ARCH_SUMMARY
    )
    assert document.summary == prose


def test_the_summary_stops_at_the_next_heading_of_any_level() -> None:
    """The decisions table is not swallowed into the summary body.

    `# 1️⃣ Executive Summary` is level 1 and `## 3. Decisions made` is level 2,
    so a rule that ran to the next same-or-shallower heading would take the
    whole table with it. This is the case that chose the rule.
    """
    prose = "A one-line executive summary."
    document = parse_extraction_document(
        _summary_document("# 1️⃣ Executive Summary", prose), DOC_ARCH_SUMMARY
    )
    assert document.summary == prose
    assert "D1" not in (document.summary or "")
    assert "Vendor feeds move to SFTP" not in (document.summary or "")


def test_capturing_the_summary_changes_nothing_else_about_the_parse() -> None:
    """The whole safety argument for this story's parser change, asserted.

    The executive-summary section is already a *target* section
    (`_ARCH_TARGET_HEADINGS` contains "summary"), so its lines already feed the
    populated-section signal and a stray `D`-row inside it already becomes an
    ADR. The prose is therefore collected *in addition to* the existing
    per-line handling, never instead of it — and this is what "in addition to"
    means observably.
    """
    prose = "Prose that is not an item and must not become one."
    with_summary = parse_extraction_document(SUMMARY_TABLE, DOC_ARCH_SUMMARY)
    assert with_summary.summary == prose
    # Byte-for-byte the outcomes the pre-12.2 parser produced for this fixture.
    assert _identity(with_summary) == [
        (KIND_ADR, "Vendor feeds move to SFTP", 263_000, "D1"),
        (KIND_ADR, "Adopt Fabrikam for the hub", 291_000, "D2"),
        (KIND_ADR, "Ops owns key rotation", 266_000, "D3"),
    ]
    assert with_summary.layout == LAYOUT_TABLE
    assert with_summary.populated_target_sections == ("3. Decisions made",)


def test_a_document_with_no_executive_summary_yields_none() -> None:
    """No fabrication. The bullet fixture's heading is `# Architecture summary`,
    which is not an executive summary, and the generated prompt emits no such
    section at all — so the generate path produces no summary artifact."""
    assert parse_extraction_document(SUMMARY_BULLET, DOC_ARCH_SUMMARY).summary is None


def test_an_empty_executive_summary_section_yields_none_not_empty_string() -> None:
    """A section that is present but carries nothing is "no summary", not an
    empty summary worth storing: there is nothing for a reader to read either
    way, and a stored empty artifact would occupy the meeting's summary slot."""
    document = parse_extraction_document(
        _summary_document("# 1 Executive Summary", "   \n\n\t"), DOC_ARCH_SUMMARY
    )
    assert document.summary is None


def test_the_summary_keeps_its_own_paragraph_breaks() -> None:
    """Stripped at the ends only. The prose is stored as the model wrote it —
    the same rule story 12.1 applied to the document as a whole."""
    prose = "First line.\n\n- A bullet [4:23]\n- Another bullet [9:02]"
    document = parse_extraction_document(
        _summary_document("# 1 Executive Summary", prose), DOC_ARCH_SUMMARY
    )
    assert document.summary == prose


def test_only_the_architecture_summary_carries_a_summary() -> None:
    """Every other document kind parses to `summary=None`, including one whose
    own text contains the phrase: the field belongs to the architecture
    summary's section, not to any occurrence of the words."""
    actions = parse_extraction_document(ACTIONS_TABLE, DOC_ACTION_ITEMS)
    assert actions.summary is None

    topics = parse_extraction_document(
        "# Topics\n\n| ID | Topic | Gist | Timestamps |\n"
        "|----|-------|------|-----------|\n"
        "| T1 | Vendor feeds | Moving to SFTP | [4:23] |\n",
        DOC_TOPICS,
    )
    assert topics.summary is None

    signals = parse_extraction_document(
        "# 1 Executive Summary\n\nProse that must not be captured here.\n\n"
        "## Risks\n\n| ID | Risk | Timestamp |\n|----|------|-----------|\n"
        "| R1 | Key rotation unowned | [9:02] |\n",
        DOC_RANKING_SIGNALS,
    )
    assert signals.summary is None


def test_the_summary_kind_is_an_artifact_kind_with_no_anchor_of_its_own() -> None:
    """`summary` counts as an artifact kind (it enters the same lifecycle), and
    the summary is deliberately not a `ProposedArtifact`: every one of those
    carries an `anchor_ms`, and a summary has no anchor. Giving it one would be
    a fabricated citation."""
    assert KIND_SUMMARY in KNOWN_KINDS
    document = parse_extraction_document(
        _summary_document("# 1 Executive Summary", "Prose."), DOC_ARCH_SUMMARY
    )
    assert all(item.kind != KIND_SUMMARY for item in document.artifacts)
    assert SUMMARY_TITLE
