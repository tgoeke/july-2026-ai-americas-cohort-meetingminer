"""Reading one meeting's finished evidence bundle out of Postgres.

Postgres is the database of record (AD-2); both retrieval stores are
disposable projections of what is read here. So this module is the projection
module's whole input surface, and it is read-only — every SELECT, no INSERT,
no UPDATE (`meeting_projection` is written by ``__init__``, and it is the one
row this module's package owns).

Deliberately store-free: nothing here imports ``neo4j`` or ``meilisearch``, so
the graph and search projections take a plain value object rather than each
re-deriving the bundle from SQL. Two writers reading the corpus two different
ways is exactly the divergence AD-4 exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg import Connection

from meetingminer.domain.jobs import evidence_complete
from meetingminer.projections.chunking import Turn


@dataclass(frozen=True)
class ScreenRow:
    """A cross-meeting screen (AD-5). Upserted, never deleted per meeting."""

    id: UUID
    identity_key: str
    label: str | None
    view_type: str


@dataclass(frozen=True)
class ScreenshotRow:
    """One capture inside one meeting — meeting-scoped, replaced on re-index.

    ``ocr_text`` is the recognized text of the frame this capture was copied
    from (``screenshot.representative_frame_id`` → ``frame_ocr.text``). It is
    ``None`` when the screenshot has no representative frame — a `frames`
    rerun sets that column NULL rather than cascading (migration 0003) — and
    when the `ocr` stage has not written a row for it. Absent OCR text is not
    an error; it is a moment whose screen contributes nothing to the full-text
    index.
    """

    id: UUID
    screen_id: UUID
    ordinal: int
    start_offset_ms: int
    end_offset_ms: int
    path: str
    view_type: str
    capture_cues: tuple[str, ...]
    classification_tags: tuple[str, ...]
    ocr_text: str | None = None


@dataclass(frozen=True)
class StructureRow:
    """The meeting's human-declared structure (story 2.5, AD-5).

    Series membership and project/product assignment are API-written rows the
    worker never touches; they are read here — the projection's only input
    surface — so the graph can write the cross-meeting ``Series``/``Project``/
    ``Product`` nodes. Every field is optional: a meeting may have a series
    and no project, a project with no product, or nothing at all.
    """

    series_id: UUID | None = None
    series_name: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    product_id: UUID | None = None
    product_name: str | None = None


@dataclass(frozen=True)
class ParticipantRow:
    """A person plus how they attended this meeting."""

    id: UUID
    identity_key: str
    display_name: str
    normalized_name: str
    is_external: bool
    is_guest: bool
    derived_from: str
    title: str | None
    department: str | None
    org: str | None


@dataclass(frozen=True)
class MomentRow:
    """One moment and the evidence it names.

    ``id`` is the citation currency (AD-6) and is carried verbatim into both
    stores. ``screenshot_id`` is NULL on a transcript-only meeting, where
    ``source_deep_link`` stands in its place (UX-DR11).
    """

    id: UUID
    identity_key: str
    derived_from: str
    start_ms: int
    end_ms: int
    started_at: datetime
    started_at_precision: str
    screenshot_id: UUID | None
    source_deep_link: str | None
    segment_count: int
    segment_ids: tuple[UUID, ...]
    text: str
    speakers: tuple[str, ...]
    participant_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class MeetingEvidence:
    """Everything the projections write for one meeting."""

    meeting_id: UUID
    source_id: str
    corpus: str
    title: str | None
    started_at: datetime
    started_at_precision: str
    has_recording: bool
    moments: tuple[MomentRow, ...]
    screenshots: tuple[ScreenshotRow, ...]
    screens: tuple[ScreenRow, ...]
    participants: tuple[ParticipantRow, ...]
    turns: tuple[Turn, ...]
    # transcript_segment id -> the moment covering it. `moment_segment` carries
    # `UNIQUE (transcript_segment_id)`, so a segment belongs to exactly one
    # moment and this mapping cannot be ambiguous.
    moment_by_segment: dict[UUID, UUID]
    # Human-declared series/project/product (story 2.5); all-None when the
    # meeting has no assignments, and the graph then writes nothing for it.
    structure: StructureRow = StructureRow()


def projectable_meeting_ids(conn: Connection) -> list[UUID]:
    """Every meeting whose evidence is complete, oldest first.

    Evidence-complete, not ``job.status = 'done'``: ``extract`` produces
    artifacts, not evidence, and AD-4 projects artifacts only on publish — a
    meeting whose extraction failed (or that predates story 4.1 and sits
    paused at ``extract``) is still fully projectable evidence, and gating on
    ``done`` would leave it out of `rebuild --all`.
    """
    rows = conn.execute(
        "SELECT m.id, s.name, s.status"
        " FROM meeting m"
        " JOIN job_stage s ON s.job_id = m.job_id"
        " ORDER BY m.started_at, m.id"
    ).fetchall()
    statuses: dict[UUID, dict[str, str]] = {}
    order: list[UUID] = []
    for meeting_id, name, status in rows:
        if meeting_id not in statuses:
            statuses[meeting_id] = {}
            order.append(meeting_id)
        statuses[meeting_id][name] = status
    return [mid for mid in order if evidence_complete(statuses[mid])]


def meeting_evidence_complete(conn: Connection, meeting_id: UUID) -> bool:
    """Whether one meeting's evidence stages have all settled."""
    rows = conn.execute(
        "SELECT s.name, s.status FROM meeting m"
        " JOIN job_stage s ON s.job_id = m.job_id WHERE m.id = %s",
        (meeting_id,),
    ).fetchall()
    return bool(rows) and evidence_complete({name: status for name, status in rows})


def read_meeting(conn: Connection, meeting_id: UUID) -> MeetingEvidence:
    """Read one meeting's whole bundle. Raises ``LookupError`` if absent."""
    row = conn.execute(
        "SELECT id, source_id, corpus, started_at, started_at_precision, title,"
        " has_recording FROM meeting WHERE id = %s",
        (meeting_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"no meeting {meeting_id}")

    turns = tuple(
        Turn(
            id=r[0],
            ordinal=r[1],
            start_ms=r[2],
            end_ms=r[3],
            text=r[4],
            speaker_label=r[5],
            participant_id=r[6],
            speaker_resolution=r[7],
        )
        for r in conn.execute(
            "SELECT id, ordinal, start_ms, end_ms, text, speaker_label,"
            " participant_id, speaker_resolution FROM transcript_segment"
            " WHERE meeting_id = %s ORDER BY ordinal",
            (meeting_id,),
        ).fetchall()
    )
    turn_by_id = {turn.id: turn for turn in turns}

    # `moment_segment` is joined through `transcript_segment` rather than
    # through `moment`, because the segment is what carries `meeting_id`.
    moment_segments: dict[UUID, list[UUID]] = {}
    moment_by_segment: dict[UUID, UUID] = {}
    for moment_id, segment_id in conn.execute(
        "SELECT ms.moment_id, ms.transcript_segment_id FROM moment_segment ms"
        " JOIN transcript_segment ts ON ts.id = ms.transcript_segment_id"
        " WHERE ts.meeting_id = %s"
        " ORDER BY ts.ordinal",
        (meeting_id,),
    ).fetchall():
        moment_segments.setdefault(moment_id, []).append(segment_id)
        moment_by_segment[segment_id] = moment_id

    moments: list[MomentRow] = []
    for r in conn.execute(
        "SELECT id, identity_key, derived_from, start_ms, end_ms, started_at,"
        " started_at_precision, screenshot_id, source_deep_link, segment_count"
        " FROM moment WHERE meeting_id = %s ORDER BY start_ms, id",
        (meeting_id,),
    ).fetchall():
        segment_ids = tuple(moment_segments.get(r[0], ()))
        covered = [turn_by_id[sid] for sid in segment_ids if sid in turn_by_id]
        speakers: list[str] = []
        participants: list[UUID] = []
        for turn in covered:
            label = turn.speaker_label.strip() or "Unknown"
            if label not in speakers:
                speakers.append(label)
            # An unresolved or ambiguous speaker contributes no participant —
            # a wrong attribution is worse than an absent one, so no
            # `SPOKE_IN` edge is invented for it.
            if turn.participant_id is not None and turn.participant_id not in participants:
                participants.append(turn.participant_id)
        moments.append(
            MomentRow(
                id=r[0],
                identity_key=r[1],
                derived_from=r[2],
                start_ms=r[3],
                end_ms=r[4],
                started_at=r[5],
                started_at_precision=r[6],
                screenshot_id=r[7],
                source_deep_link=r[8],
                segment_count=r[9],
                segment_ids=segment_ids,
                text="\n".join(
                    f"{turn.speaker_label.strip() or 'Unknown'}: {turn.text.strip()}"
                    for turn in covered
                ),
                speakers=tuple(speakers),
                participant_ids=tuple(participants),
            )
        )

    screenshots: list[ScreenshotRow] = []
    screens: dict[UUID, ScreenRow] = {}
    # LEFT JOIN on both hops: `representative_frame_id` is nullable by design
    # (a `frames` rerun sets it NULL rather than deleting screenshot
    # evidence), and a frame may have no `frame_ocr` row when the `ocr` stage
    # has not run. An INNER JOIN here would silently drop screenshots from the
    # projection — the moment would lose its `screenshotId` for want of OCR
    # text it never needed.
    for r in conn.execute(
        "SELECT ss.id, ss.screen_id, ss.ordinal, ss.start_offset_ms,"
        " ss.end_offset_ms, ss.path, ss.view_type, ss.capture_cues,"
        " ss.classification_tags, s.identity_key, s.label, s.view_type,"
        " fo.text"
        " FROM screenshot ss JOIN screen s ON s.id = ss.screen_id"
        " LEFT JOIN frame_ocr fo ON fo.frame_id = ss.representative_frame_id"
        " WHERE ss.meeting_id = %s ORDER BY ss.ordinal",
        (meeting_id,),
    ).fetchall():
        screenshots.append(
            ScreenshotRow(
                id=r[0],
                screen_id=r[1],
                ordinal=r[2],
                start_offset_ms=r[3],
                end_offset_ms=r[4],
                path=r[5],
                view_type=r[6],
                capture_cues=tuple(r[7] or ()),
                classification_tags=tuple(r[8] or ()),
                ocr_text=r[12],
            )
        )
        screens.setdefault(
            r[1], ScreenRow(id=r[1], identity_key=r[9], label=r[10], view_type=r[11])
        )

    participants_rows = tuple(
        ParticipantRow(
            id=r[0],
            identity_key=r[1],
            display_name=r[2],
            normalized_name=r[3],
            is_external=r[4],
            is_guest=r[5],
            derived_from=r[6],
            title=r[7],
            department=r[8],
            org=r[9],
        )
        for r in conn.execute(
            "SELECT p.id, p.identity_key, p.display_name, p.normalized_name,"
            " mp.is_external, mp.is_guest, mp.derived_from, mp.title,"
            " mp.department, mp.org"
            " FROM meeting_participant mp"
            " JOIN participant p ON p.id = mp.participant_id"
            " WHERE mp.meeting_id = %s ORDER BY p.normalized_name, p.id",
            (meeting_id,),
        ).fetchall()
    )

    # Exactly one row: anchored on the meeting, LEFT JOINs through the two
    # one-row-per-meeting assignment tables (their `meeting_id` PRIMARY KEYs
    # make fan-out impossible). These are API-owned tables (AD-5) read here
    # exactly like every worker-owned one — SELECTs only.
    structure_row = conn.execute(
        "SELECT se.id, se.name, pr.id, pr.name, pd.id, pd.name"
        " FROM meeting m"
        " LEFT JOIN meeting_series ms ON ms.meeting_id = m.id"
        " LEFT JOIN series se ON se.id = ms.series_id"
        " LEFT JOIN meeting_project mp ON mp.meeting_id = m.id"
        " LEFT JOIN project pr ON pr.id = mp.project_id"
        " LEFT JOIN product pd ON pd.id = pr.product_id"
        " WHERE m.id = %s",
        (meeting_id,),
    ).fetchone()
    if structure_row is None:
        # The meeting answered the first SELECT above but not this one —
        # deleted mid-read. Same failure mode, same named error.
        raise LookupError(f"no meeting {meeting_id}")
    structure = StructureRow(
        series_id=structure_row[0],
        series_name=structure_row[1],
        project_id=structure_row[2],
        project_name=structure_row[3],
        product_id=structure_row[4],
        product_name=structure_row[5],
    )

    return MeetingEvidence(
        meeting_id=row[0],
        source_id=row[1],
        corpus=row[2],
        started_at=row[3],
        started_at_precision=row[4],
        title=row[5],
        has_recording=row[6],
        moments=tuple(moments),
        screenshots=tuple(screenshots),
        screens=tuple(screens.values()),
        participants=participants_rows,
        turns=turns,
        moment_by_segment=moment_by_segment,
        structure=structure,
    )
