"""`meetingminer.digest.generator.render_digest` — store-free render tests.

`render_digest` takes the already-grouped `DigestMeeting` value objects, so
these tests build them directly rather than going through Postgres: owner
formatting, meeting ordering, and the empty-corpus message are all properties
of the render function alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from meetingminer.digest.generator import (
    DigestArtifact,
    DigestMeeting,
    _split_owner,
    read_published_artifacts,
    render_digest,
)


def _artifact(title: str = "Some artifact", body: str = "detail", owner: str | None = None) -> DigestArtifact:
    return DigestArtifact(id=uuid4(), title=title, body=body, owner=owner)


def _meeting(
    *,
    title: str | None = "Data Hub Demo",
    started_at: datetime = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
    decisions: tuple[DigestArtifact, ...] = (),
    action_items: tuple[DigestArtifact, ...] = (),
) -> DigestMeeting:
    return DigestMeeting(
        meeting_id=uuid4(),
        title=title,
        started_at=started_at,
        decisions=decisions,
        action_items=action_items,
    )


def test_no_meetings_states_that_nothing_is_published_yet() -> None:
    text = render_digest(())
    assert "No artifacts are published yet." in text
    assert "Morning Digest" in text


def test_owner_present_renders_the_assignee() -> None:
    action_item = _artifact(title="Approve the purchase order", owner="Ellis Whitmore")
    meeting = _meeting(decisions=(), action_items=(action_item,))
    text = render_digest((meeting,))
    assert "Approve the purchase order (Owner: Ellis Whitmore)" in text


def test_owner_absent_renders_unassigned() -> None:
    action_item = _artifact(title="Follow up with vendor", owner=None)
    meeting = _meeting(decisions=(), action_items=(action_item,))
    text = render_digest((meeting,))
    assert "Follow up with vendor (Owner: Unassigned)" in text
    assert "Owner: None" not in text


def test_decisions_and_action_items_render_under_separate_headings() -> None:
    adr = _artifact(title="Migrate the zylographic queue")
    action_item = _artifact(title="Approve the purchase order", owner="Ellis Whitmore")
    meeting = _meeting(decisions=(adr,), action_items=(action_item,))
    text = render_digest((meeting,))

    decisions_index = text.index("### Decisions")
    action_items_index = text.index("### Action Items")
    adr_index = text.index("Migrate the zylographic queue")
    action_index = text.index("Approve the purchase order")

    assert decisions_index < adr_index < action_items_index < action_index


def test_a_meeting_with_only_action_items_omits_the_decisions_heading() -> None:
    action_item = _artifact(title="Approve the purchase order")
    meeting = _meeting(decisions=(), action_items=(action_item,))
    text = render_digest((meeting,))
    assert "### Decisions" not in text
    assert "### Action Items" in text


def test_meetings_render_in_the_order_given_most_recent_first() -> None:
    """`render_digest` trusts caller ordering; `read_published_artifacts` is
    what actually sorts by `started_at DESC` (covered store-backed)."""
    newer = _meeting(title="Newer Meeting", started_at=datetime(2026, 8, 10, tzinfo=timezone.utc))
    older = _meeting(title="Older Meeting", started_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
    text = render_digest((newer, older))
    assert text.index("Newer Meeting") < text.index("Older Meeting")


def test_untitled_meeting_renders_a_placeholder_label() -> None:
    meeting = _meeting(title=None, decisions=(_artifact(),))
    text = render_digest((meeting,))
    assert "(untitled meeting)" in text


def test_a_multiline_body_indents_every_line_under_its_bullet() -> None:
    """`extraction.py` joins several table columns with `\n` into one body —
    every continuation line must stay indented under the bullet, not just
    the first."""
    action_item = _artifact(
        title="Approve the purchase order",
        owner="Ellis Whitmore",
        body="Get the PO signed off.\nEscalate to finance if not done by Friday.\nCc procurement.",
    )
    meeting = _meeting(decisions=(), action_items=(action_item,))
    text = render_digest((meeting,))

    body_lines = [
        "Get the PO signed off.",
        "Escalate to finance if not done by Friday.",
        "Cc procurement.",
    ]
    rendered_lines = text.splitlines()
    for body_line in body_lines:
        matches = [line for line in rendered_lines if line.strip() == body_line]
        assert matches, f"expected a rendered line for {body_line!r}"
        assert matches[0].startswith("  "), (
            f"line for {body_line!r} was not indented under its bullet: {matches[0]!r}"
        )


def test_owner_parser_preserves_blank_paragraphs_after_the_owner_line() -> None:
    owner, body = _split_owner("action-item", "Owner: Ellis Whitmore\n\nFollow up with finance.\n\n")
    assert owner == "Ellis Whitmore"
    assert body == "\nFollow up with finance.\n\n"


def test_blank_body_lines_stay_indented_under_the_artifact() -> None:
    action_item = _artifact(
        title="Approve the purchase order",
        owner="Ellis Whitmore",
        body="Get the PO signed off.\n\nEscalate to finance if not done by Friday.",
    )
    text = render_digest((_meeting(decisions=(), action_items=(action_item,)),))
    assert "  Get the PO signed off.\n  \n  Escalate to finance if not done by Friday." in text


def test_published_artifact_query_uses_a_unique_ordering_tiebreaker() -> None:
    class _Result:
        def fetchall(self) -> list[object]:
            return []

    class _RecordingConnection:
        query = ""

        def execute(self, query: str) -> _Result:
            self.query = query
            return _Result()

    connection = _RecordingConnection()
    assert read_published_artifacts(connection) == ()  # type: ignore[arg-type]
    assert "ORDER BY m.started_at DESC, m.id, a.kind, a.created_at, a.id" in connection.query
