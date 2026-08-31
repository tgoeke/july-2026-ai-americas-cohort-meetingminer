"""Reading published artifacts out of Postgres and rendering the example digest.

Split the way `meetingminer.projections.evidence` splits its store I/O from
its callers: :func:`read_published_artifacts` is the only SELECT in this
story, and :func:`render_digest` is deliberately store-free so the render
half is testable without Postgres. Read-only against `artifact`/`meeting`
(AD-2, AD-4) — no INSERT, no UPDATE, no new migration.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg import Connection

# Written by `pipeline/extraction.py` as the one canonical owner line,
# whichever shape the source document used: `f"Owner: {owner}\n{body}"`.
_OWNER_PREFIX = "Owner: "


@dataclass(frozen=True)
class DigestArtifact:
    """One published ADR or action item, as the digest will render it."""

    id: UUID
    title: str
    body: str
    # Parsed off a leading `Owner: <name>` line on `artifact.body`; None when
    # the line is absent. Never invented — an artifact with no `Owner:` line
    # renders unassigned rather than guessing a name.
    owner: str | None


@dataclass(frozen=True)
class DigestMeeting:
    """One meeting's published artifacts, grouped for the digest."""

    meeting_id: UUID
    title: str | None
    started_at: datetime
    decisions: tuple[DigestArtifact, ...]
    action_items: tuple[DigestArtifact, ...]


def _split_owner(kind: str, body: str) -> tuple[str | None, str]:
    """Parse a leading ``Owner: <name>`` line off an action item's body.

    Only action items carry an owner line (`extraction.py` writes it only for
    `DOC_ACTION_ITEMS`); an ADR's body is returned unchanged.
    """
    if kind != "action-item" or not body.startswith(_OWNER_PREFIX):
        return None, body
    first_line, _, rest = body.partition("\n")
    owner = first_line[len(_OWNER_PREFIX) :].strip()
    return (owner or None), rest


def read_published_artifacts(conn: Connection) -> tuple[DigestMeeting, ...]:
    """Every published ADR/action item, grouped by meeting, newest meeting first.

    One SELECT, ``artifact`` joined to ``meeting`` on the same
    ``artifact_meeting_state_idx (meeting_id, state)`` shape `evidence.py`
    uses elsewhere — ordered by ``m.started_at DESC`` so meetings group
    together in the pass below without a second lookup.
    """
    rows = conn.execute(
        "SELECT m.id, m.title, m.started_at, a.id, a.kind, a.title, a.body"
        " FROM artifact a"
        " JOIN meeting m ON m.id = a.meeting_id"
        # Moment-anchored rows only (story 12.2). The bucketing below is a
        # two-way split — `adr` or everything else — so a published
        # meeting-scoped artifact would silently be filed as an action item,
        # which it is not. This digest renders what its own docstring says it
        # renders; a meeting summary belongs to the meeting analysis panel
        # (story 12.3), not to a list of decisions and commitments. The filter
        # is on the observable scope, never on a kind name.
        " WHERE a.state = 'published' AND a.moment_id IS NOT NULL"
        " ORDER BY m.started_at DESC, m.id, a.kind, a.created_at, a.id",
    ).fetchall()

    meetings: dict[UUID, dict[str, object]] = {}
    order: list[UUID] = []
    for meeting_id, meeting_title, started_at, artifact_id, kind, title, body in rows:
        if meeting_id not in meetings:
            meetings[meeting_id] = {
                "title": meeting_title,
                "started_at": started_at,
                "decisions": [],
                "action_items": [],
            }
            order.append(meeting_id)
        owner, rendered_body = _split_owner(kind, body)
        entry = DigestArtifact(id=artifact_id, title=title, body=rendered_body, owner=owner)
        bucket = "decisions" if kind == "adr" else "action_items"
        meetings[meeting_id][bucket].append(entry)  # type: ignore[attr-defined]

    return tuple(
        DigestMeeting(
            meeting_id=meeting_id,
            title=meetings[meeting_id]["title"],  # type: ignore[arg-type]
            started_at=meetings[meeting_id]["started_at"],  # type: ignore[arg-type]
            decisions=tuple(meetings[meeting_id]["decisions"]),  # type: ignore[arg-type]
            action_items=tuple(meetings[meeting_id]["action_items"]),  # type: ignore[arg-type]
        )
        for meeting_id in order
    )


_NO_ARTIFACTS_MESSAGE = "No artifacts are published yet."


def _indent_body(body: str) -> str:
    """Indent every line of a (possibly multi-line) artifact body under its bullet.

    `extraction.py` joins several table columns with `\n` into one body, so a
    single `f"  {body}"` would indent only the first line and leave every
    continuation line flush-left, detached from its bullet.
    """
    return textwrap.indent(body, "  ", lambda _line: True)


def _render_meeting(meeting: DigestMeeting) -> str:
    label = meeting.title or "(untitled meeting)"
    date = meeting.started_at.date().isoformat()
    lines = [f"## {label} — {date}"]

    if meeting.decisions:
        lines.append("")
        lines.append("### Decisions")
        for artifact in meeting.decisions:
            lines.append(f"- {artifact.title}")
            if artifact.body:
                lines.append(_indent_body(artifact.body))

    if meeting.action_items:
        lines.append("")
        lines.append("### Action Items")
        for artifact in meeting.action_items:
            assignee = artifact.owner if artifact.owner else "Unassigned"
            lines.append(f"- {artifact.title} (Owner: {assignee})")
            if artifact.body:
                lines.append(_indent_body(artifact.body))

    return "\n".join(lines)


def render_digest(meetings: tuple[DigestMeeting, ...]) -> str:
    """Render the example email body — plain text/markdown, not MIME.

    Nothing in scope consumes a real `.eml`/MIME file (no delivery mechanism
    exists to read one), so a single readable text file demonstrating the
    digest content is the whole deliverable.
    """
    header = "MeetingMiner — Morning Digest (example)"
    if not meetings:
        return f"{header}\n\n{_NO_ARTIFACTS_MESSAGE}\n"

    body = "\n\n".join(_render_meeting(meeting) for meeting in meetings)
    return f"{header}\n\n{body}\n"
