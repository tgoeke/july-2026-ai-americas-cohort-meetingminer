"""Seed a finished evidence bundle straight into the test database.

The projection tests are about what `server/meetingminer/projections/` writes
into Neo4j and Meilisearch, not about how the bundle got into Postgres —
stories 1.3 to 1.6 already test that, and running the whole pipeline per case
would make every projection assertion cost an ffmpeg run. So these helpers
INSERT the rows the projections read, in exactly the shapes the migrations
declare, and let the constraints catch a fixture that drifts from the schema.

Both drop kinds are available, because the projection differs between them:
a recording meeting gets Screen/Screenshot nodes and `screenshotId` on its
moments, a transcript-only meeting gets neither and carries `sourceDeepLink`
in their place (UX-DR11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from meetingminer.domain.jobs import STAGE_NAMES, VIDEO_ONLY_STAGES

STARTED_AT = datetime(2026, 8, 5, 12, 0, 19, tzinfo=timezone.utc)
DEEP_LINK = "https://example-my.sharepoint.com/personal/u/_layouts/15/stream.aspx?id=x"


@dataclass(frozen=True)
class SeededTurn:
    ordinal: int
    start_ms: int
    text: str
    speaker_label: str
    participant_index: int | None = None
    speaker_resolution: str | None = None


DEFAULT_TURNS: tuple[SeededTurn, ...] = (
    SeededTurn(1, 2_000, "Everybody, good morning.", "Goeke, Timothy", 0),
    SeededTurn(2, 5_000, "Morning, all.", "Whitmore, Ellis", 1),
    SeededTurn(3, 9_000, "Let us walk the revenue slide.", "Goeke, Timothy", 0),
    SeededTurn(4, 40_000, "We moved that feed to SFTP last week.", "Speaker 8", None),
    SeededTurn(5, 44_000, "And the purchase order still needs approval.", "Whitmore, Ellis", 1),
)

DEFAULT_PARTICIPANTS: tuple[tuple[str, str], ...] = (
    ("mail:timothy.goeke@contoso.com", "Goeke, Timothy"),
    ("mail:ellis.whitmore@contoso.com", "Whitmore, Ellis"),
)


@dataclass(frozen=True)
class SeededMeeting:
    meeting_id: UUID
    job_id: UUID
    source_id: str
    participant_ids: tuple[UUID, ...]
    segment_ids: tuple[UUID, ...]
    moment_ids: tuple[UUID, ...]
    screen_ids: tuple[UUID, ...]
    screenshot_ids: tuple[UUID, ...]


def _normalized(display_name: str) -> str:
    if "," in display_name:
        last, first = (part.strip() for part in display_name.split(",", 1))
        display_name = f"{first} {last}"
    return display_name.casefold()


def seed_participant(
    conn: Connection, *, identity_key: str, display_name: str
) -> UUID:
    """Insert (or reuse) one bare `participant` row, with no meeting link.

    For story 2.4's merge-state fixtures, which need extra `participant` rows
    that are never attended a meeting — a full `seed_meeting` call would drag
    in a job, transcript and moments this test does not want.
    """
    return conn.execute(
        "INSERT INTO participant (identity_key, display_name, normalized_name)"
        " VALUES (%s, %s, %s)"
        " ON CONFLICT (identity_key) DO UPDATE SET display_name = EXCLUDED.display_name"
        " RETURNING id",
        (identity_key, display_name, _normalized(display_name)),
    ).fetchone()[0]


def seed_participant_alias(conn: Connection, *, alias_key: str, participant_id: UUID) -> None:
    """Insert one `participant_alias` row directly — the API-owned merge
    record (AD-5), for fixtures that need a pre-existing merge without going
    through `POST /participants/{id}/merge`."""
    conn.execute(
        "INSERT INTO participant_alias (alias_key, participant_id) VALUES (%s, %s)",
        (alias_key, participant_id),
    )


def seed_series(conn: Connection, *, name: str) -> UUID:
    """Insert one API-owned `series` row directly (story 2.5, AD-5) — the
    projection tests must not run the API to get structure into Postgres."""
    return conn.execute(
        "INSERT INTO series (name) VALUES (%s) RETURNING id", (name,)
    ).fetchone()[0]


def seed_product(conn: Connection, *, name: str) -> UUID:
    """Insert one API-owned `product` row directly (story 2.5, AD-5)."""
    return conn.execute(
        "INSERT INTO product (name) VALUES (%s) RETURNING id", (name,)
    ).fetchone()[0]


def seed_project(conn: Connection, *, name: str, product_id: UUID | None = None) -> UUID:
    """Insert one API-owned `project` row directly (story 2.5, AD-5)."""
    return conn.execute(
        "INSERT INTO project (name, product_id) VALUES (%s, %s) RETURNING id",
        (name, product_id),
    ).fetchone()[0]


def assign_project_product(
    conn: Connection, *, project_id: UUID, product_id: UUID | None
) -> None:
    """Update the project's one nullable `product_id` column (story 2.5) —
    the same write the API's PATCH performs, for reconciliation fixtures."""
    conn.execute(
        "UPDATE project SET product_id = %s WHERE id = %s", (product_id, project_id)
    )


def assign_meeting_series(conn: Connection, *, meeting_id: UUID, series_id: UUID) -> None:
    """Upsert the meeting's one `meeting_series` row (story 2.5) — the same
    at-most-one shape the API's PUT writes."""
    conn.execute(
        "INSERT INTO meeting_series (meeting_id, series_id) VALUES (%s, %s)"
        " ON CONFLICT (meeting_id) DO UPDATE SET series_id = EXCLUDED.series_id",
        (meeting_id, series_id),
    )


def assign_meeting_project(conn: Connection, *, meeting_id: UUID, project_id: UUID) -> None:
    """Upsert the meeting's one `meeting_project` row (story 2.5)."""
    conn.execute(
        "INSERT INTO meeting_project (meeting_id, project_id) VALUES (%s, %s)"
        " ON CONFLICT (meeting_id) DO UPDATE SET project_id = EXCLUDED.project_id",
        (meeting_id, project_id),
    )


def clear_meeting_series(conn: Connection, *, meeting_id: UUID) -> None:
    """Clear the meeting's series assignment the way the API's null PUT does."""
    conn.execute("DELETE FROM meeting_series WHERE meeting_id = %s", (meeting_id,))


def clear_meeting_project(conn: Connection, *, meeting_id: UUID) -> None:
    """Clear the meeting's project assignment the way the API's null PUT does."""
    conn.execute("DELETE FROM meeting_project WHERE meeting_id = %s", (meeting_id,))


def seed_meeting(
    conn: Connection,
    *,
    source_id: str,
    has_recording: bool = True,
    title: str = "Data Hub Demo",
    corpus: str = "real",
    turns: Sequence[SeededTurn] = DEFAULT_TURNS,
    participants: Sequence[tuple[str, str]] = DEFAULT_PARTICIPANTS,
    screen_identity_keys: Sequence[str] = ("sha256:screen-a", "sha256:screen-b"),
    screen_view_types: tuple[str, ...] | None = None,
    with_moments: bool = True,
    started_at: datetime = STARTED_AT,
    stage_overrides: dict[str, str] | None = None,
) -> SeededMeeting:
    """Insert one meeting's whole evidence bundle and return its ids.

    ``started_at`` sets both ``meeting.started_at`` and each moment's
    ``started_at`` — every seeded meeting otherwise shares :data:`STARTED_AT`,
    which makes cross-meeting time-order assertions (the traversal templates,
    story 3.3's tests) impossible without it. Its exact definition is pinned
    in `spec-3-2-graph-traversal-templates.md` (AGENTS.md's shared-addition
    convention) so no second definition appears.

    Stage rows are settled the way the runner would settle them: everything
    through `moments` `done`, the video stages `skipped` on a transcript-only
    drop, and `extract` left `queued` — a job mid-extraction, or one left at
    the pre-4.1 pause, which is exactly why the projection trigger cannot key
    on `job.status = 'done'`.
    """
    # A naive datetime would be read in the session timezone by Postgres and
    # silently skew every cross-meeting time-order assertion.
    assert started_at.tzinfo is not None, "started_at must be timezone-aware"
    job_id = conn.execute(
        "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
        " VALUES (%s, %s, %s, 'running') RETURNING id",
        (source_id, source_id, corpus),
    ).fetchone()[0]
    for name in STAGE_NAMES:
        if stage_overrides and name in stage_overrides:
            status = stage_overrides[name]
        elif name == "extract":
            status = "queued"  # extraction still ahead: not part of evidence
        elif not has_recording and name in VIDEO_ONLY_STAGES:
            status = "skipped"
        else:
            status = "done"
        conn.execute(
            "INSERT INTO job_stage (job_id, name, status) VALUES (%s, %s, %s)",
            (job_id, name, status),
        )

    meeting_id = conn.execute(
        "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
        " started_at_precision, title, has_recording, provenance)"
        " VALUES (%s, %s, %s, %s, 'second', %s, %s, %s) RETURNING id",
        (
            job_id,
            source_id,
            corpus,
            started_at,
            title,
            has_recording,
            Jsonb({"url": DEEP_LINK}),
        ),
    ).fetchone()[0]

    participant_ids: list[UUID] = []
    for identity_key, display_name in participants:
        participant_id = conn.execute(
            "INSERT INTO participant (identity_key, display_name, normalized_name)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (identity_key) DO UPDATE SET display_name = EXCLUDED.display_name"
            " RETURNING id",
            (identity_key, display_name, _normalized(display_name)),
        ).fetchone()[0]
        participant_ids.append(participant_id)
        conn.execute(
            "INSERT INTO meeting_participant (meeting_id, participant_id, derived_from)"
            " VALUES (%s, %s, 'transcript')",
            (meeting_id, participant_id),
        )

    screen_ids: list[UUID] = []
    screenshot_ids: list[UUID] = []
    if has_recording:
        # One view type per screen, zipped with the identity keys; the default
        # keeps the pre-2.3 shape — every seeded screen an 'ui-screen'. An
        # `is not None` check, not truthiness: an explicitly-passed empty
        # tuple must reach the strict zip and fail loudly there, not silently
        # become the default.
        view_types = (
            screen_view_types
            if screen_view_types is not None
            else tuple("ui-screen" for _ in screen_identity_keys)
        )
        for index, (identity_key, view_type) in enumerate(
            zip(screen_identity_keys, view_types, strict=True)
        ):
            screen_id = conn.execute(
                "INSERT INTO screen (identity_key, signature, view_type)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (identity_key) DO UPDATE SET signature = EXCLUDED.signature"
                " RETURNING id",
                (identity_key, f"signature for {identity_key}", view_type),
            ).fetchone()[0]
            screen_ids.append(screen_id)
            screenshot_ids.append(
                conn.execute(
                    "INSERT INTO screenshot (meeting_id, screen_id, ordinal,"
                    " start_offset_ms, end_offset_ms, frame_count, path, view_type,"
                    " capture_cues) VALUES (%s, %s, %s, %s, %s, 3, %s, %s,"
                    " ARRAY['region-change']) RETURNING id",
                    (
                        meeting_id,
                        screen_id,
                        index + 1,
                        index * 30_000,
                        (index + 1) * 30_000,
                        f"meetings/{meeting_id}/screenshots/{index + 1}.jpg",
                        view_type,
                    ),
                ).fetchone()[0]
            )

    source_id_row = conn.execute(
        "INSERT INTO transcript_source (meeting_id, kind, format,"
        " drop_relative_path, sha256, byte_size, segment_count)"
        " VALUES (%s, 'provided-text', 'teams', %s, %s, %s, %s)"
        " RETURNING id",
        (
            meeting_id,
            f"{source_id}/transcript.txt",
            f"sha-{source_id}",
            1024,
            len(turns),
        ),
    ).fetchone()[0]

    segment_ids: list[UUID] = []
    for spec in turns:
        participant_id = (
            participant_ids[spec.participant_index]
            if spec.participant_index is not None
            else None
        )
        segment_ids.append(
            conn.execute(
                "INSERT INTO transcript_segment (meeting_id, ordinal, start_ms, end_ms,"
                " text, speaker_label, participant_id, speaker_resolution,"
                " label_source_id, timing_source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    meeting_id,
                    spec.ordinal,
                    spec.start_ms,
                    spec.start_ms + 2_000,
                    spec.text,
                    spec.speaker_label,
                    participant_id,
                    spec.speaker_resolution
                    or ("resolved" if participant_id else "unresolved"),
                    source_id_row,
                    source_id_row,
                ),
            ).fetchone()[0]
        )

    moment_ids: list[UUID] = []
    if with_moments and turns:
        # Two moments, cut at the 30-second gap the seeded turns contain —
        # the same shape the `moments` stage produces at the configured gap.
        groups = [
            [i for i, spec in enumerate(turns) if spec.start_ms < 30_000],
            [i for i, spec in enumerate(turns) if spec.start_ms >= 30_000],
        ]
        for group_index, group in enumerate(g for g in groups if g):
            start_ms = turns[group[0]].start_ms
            end_ms = turns[group[-1]].start_ms + 2_000
            screenshot_id = (
                screenshot_ids[min(group_index, len(screenshot_ids) - 1)]
                if screenshot_ids
                else None
            )
            moment_id = conn.execute(
                "INSERT INTO moment (meeting_id, identity_key, derived_from,"
                " start_ms, end_ms, started_at, started_at_precision, screenshot_id,"
                " source_deep_link, segment_count, provenance)"
                " VALUES (%s, %s, 'transcript', %s, %s, %s, 'second', %s, %s, %s, %s)"
                " RETURNING id",
                (
                    meeting_id,
                    f"transcript:{start_ms}",
                    start_ms,
                    end_ms,
                    started_at,
                    screenshot_id,
                    # UX-DR11: the transitional deep link stands where the
                    # replay button would be, and only when there is no video.
                    None if has_recording else DEEP_LINK,
                    len(group),
                    Jsonb({"reason": "seeded"}),
                ),
            ).fetchone()[0]
            moment_ids.append(moment_id)
            for turn_index in group:
                conn.execute(
                    "INSERT INTO moment_segment (moment_id, transcript_segment_id)"
                    " VALUES (%s, %s)",
                    (moment_id, segment_ids[turn_index]),
                )

    conn.commit()
    return SeededMeeting(
        meeting_id=meeting_id,
        job_id=job_id,
        source_id=source_id,
        participant_ids=tuple(participant_ids),
        segment_ids=tuple(segment_ids),
        moment_ids=tuple(moment_ids),
        screen_ids=tuple(screen_ids),
        screenshot_ids=tuple(screenshot_ids),
    )


def insert_artifact(
    conn: Connection,
    moment_id: UUID,
    meeting_id: UUID,
    *,
    kind: str = "adr",
    state: str = "published",
    title: str = "Move the feed to SFTP",
    body: str = "Decided during the demo.",
) -> UUID:
    """One artifact row, in the shape migration 0009 declares (story 4.4).

    The single definition every suite seeds artifacts through — the worker
    owns these columns in production, so tests write them raw here rather
    than each file repeating the INSERT.
    """
    return conn.execute(
        "INSERT INTO artifact (moment_id, meeting_id, kind, state, title, body)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (moment_id, meeting_id, kind, state, title, body),
    ).fetchone()[0]
