"""The harness's one database connection — read-only, and mechanically so.

AD-16 lets the harness read Postgres directly and forbids it changing what it
audits. "Forbids" here is a Postgres setting rather than a convention: the
connection carries ``options="-c default_transaction_read_only=on"``, so an
``INSERT`` through it raises instead of relying on a reviewer noticing. The
publish-gate check (story 5.3) is meaningless if the harness can write the
state it is asserting about, and a rule enforced by review survives exactly as
long as reviewers do.

This is deliberately the *only* module in the harness that opens a database
connection, mirroring ``subjects.py`` being the only one that makes a network
call. Rows come in, :class:`~evals.harness.checks.Capture` dataclasses go out;
no algorithm lives here, which is what keeps ``checks.py`` runnable with no
store (``tests/test_harness_boundary.py`` is the mechanism, not the promise).

The conninfo is built here rather than imported from ``meetingminer.db``: that
module's job is opening write pools, so it stays forbidden even though its
``conninfo`` helper is the shape this mirrors.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import psycopg

from evals.harness.checks import Capture

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psycopg import Connection

#: One ``artifact`` row, the judge's extraction-item unit (story 5.4). Only
#: the columns the rubric-2.7 prompt needs: the moment it hangs off (to fetch
#: its covering transcript), and the extracted content itself.
ARTIFACT_COLUMNS = ("id", "moment_id", "kind", "state", "title", "body")

_ARTIFACTS = (
    "SELECT id, moment_id, kind, state, title, body"
    " FROM artifact"
    " WHERE meeting_id = %s::uuid"
    " ORDER BY created_at, id"
)

#: One ``moment_segment`` join row — the judge's faithfulness haystack.
#: Mirrors ``api/moments.py``'s ``_COVERING_SEGMENTS`` exactly (a covered
#: segment may end after its moment does, and is still returned in full), keyed
#: by moment rather than embedded in a route.
SEGMENT_COLUMNS = ("start_ms", "end_ms", "speaker_label", "text")

_SEGMENTS_FOR_MOMENT = (
    "SELECT ts.start_ms, ts.end_ms, ts.speaker_label, ts.text"
    " FROM moment_segment ms"
    " JOIN moment m ON m.id = ms.moment_id"
    " JOIN transcript_segment ts ON ts.id = ms.transcript_segment_id"
    " WHERE ms.moment_id = %s::uuid AND ts.meeting_id = m.meeting_id"
    " ORDER BY ts.ordinal"
)

#: What makes the connection read-only. A libpq `options` string, applied by
#: the server to every transaction on this session — including the implicit
#: one around a single autocommit statement.
READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"

#: ``%s::uuid`` on every meeting id, deliberately. The ids arrive as strings
#: from the api's JSON, and psycopg dumps a Python ``str`` as ``text`` — which
#: Postgres will not compare to a ``uuid`` column. The server's own queries
#: hand psycopg a ``UUID`` object and need no cast; the harness reads the api,
#: so it casts.
#:
#: One capture per row, ordinal-ordered. LEFT JOIN, not INNER: a capture whose
#: `representative_frame_id` is NULL (a `frames` rerun cleared it) or whose
#: frame has no `frame_ocr` row must still arrive, as a row with no text. An
#: INNER JOIN would drop it from the haystack *and* from the count, which is
#: exactly the silent exclusion check 2.1 reports as a defect.
#: The columns :data:`_CAPTURES` selects, in order. Named because the row
#: mapping below unpacks by position, and a swapped pair there would be a
#: silent corruption of every capture check — the SQL needs a store to
#: exercise, but the mapping does not (`tests/test_capture_rows.py`).
CAPTURE_COLUMNS = ("ordinal", "view_type", "representative_frame_id", "ocr_text")

_CAPTURES = (
    "SELECT s.ordinal, s.view_type, s.representative_frame_id, o.text"
    " FROM screenshot s"
    " LEFT JOIN frame_ocr o ON o.frame_id = s.representative_frame_id"
    " WHERE s.meeting_id = %s::uuid"
    " ORDER BY s.ordinal"
)

_MEDIA_DURATION = (
    "SELECT duration_ms FROM meeting_media WHERE meeting_id = %s::uuid"
)

_HAS_RECORDING = "SELECT has_recording FROM meeting WHERE id = %s::uuid"

_MEETING_CORPUS = "SELECT corpus FROM meeting WHERE id = %s::uuid"

#: One ``moment`` row, reduced to what probe eligibility reads (story 11.3):
#: the id the probe artifact will cite and the identity key that makes a
#: report line about it recognizable. Ordered by ``start_ms`` — the table
#: deliberately has no ordinal column (0006_moments.sql).
MOMENT_COLUMNS = ("id", "identity_key")

_MOMENTS = (
    "SELECT id, identity_key"
    " FROM moment"
    " WHERE meeting_id = %s::uuid"
    " ORDER BY start_ms, id"
)

#: One pipeline stage's checkpoint status for the meeting's job. The probe
#: rides a moment only after the ``extract`` stage has settled, so this read
#: joins ``job_stage`` through ``meeting.job_id`` rather than trusting the
#: api's coarser job status.
# Newest checkpoint first: a retry deletes and re-seeds its stage rows, so
# there is normally exactly one per (job, stage) — but `job_stage` carries no
# uniqueness constraint on that pair (0001_jobs.sql), and an answer that
# depended on planner order would be a guess. `id` is a uuidv7 tiebreak.
_STAGE_STATUS = (
    "SELECT js.status"
    " FROM job_stage js"
    " JOIN meeting m ON m.job_id = js.job_id"
    " WHERE m.id = %s::uuid AND js.name = %s"
    " ORDER BY js.created_at DESC, js.id DESC"
)


class CorpusQueryError(Exception):
    """A read against the corpus failed, or named a meeting that is not there.

    One error type for every way the read can fail, matching
    ``subjects.CorpusReadError``: a run that cannot read what it is measuring
    says so, rather than reporting zero captures.
    """


@dataclass(frozen=True)
class ArtifactRow:
    """One ``artifact`` row — the judge's extraction-item unit (story 5.4).

    ``moment_id`` is what :meth:`Corpus.segments_for_moment` reads with to
    build the faithfulness haystack; the FK from ``artifact`` to ``moment``
    (0009_artifacts.sql) is exactly why ``citation_present`` is mechanically
    true for an extraction item rather than judged — the row cannot exist
    without a moment.
    """

    id: str
    moment_id: str
    kind: str
    state: str
    title: str
    body: str


@dataclass(frozen=True)
class MomentRow:
    """One ``moment`` row — what the publish-gate probe chooses among.

    Only what eligibility needs: the id (the probe artifact's citation
    target, and what ``moment_in_graph`` is asked about) and the
    ``identity_key`` (so a report line about the chosen moment says which
    span of the meeting it was, not only a UUID).
    """

    id: str
    identity_key: str


@dataclass(frozen=True)
class TranscriptSegment:
    """One ``moment_segment``-covered ``transcript_segment`` row.

    Mirrors what ``api/moments.py`` serves as ``MomentSegment``, minus the
    fields the judge prompt has no use for (``speaker_resolution``,
    ``participant_id``): the judge reads text and timing, not identity.
    """

    start_ms: int
    end_ms: int
    speaker_label: str | None
    text: str


def artifact_from_row(row: Sequence[Any]) -> ArtifactRow:
    """One ``artifact`` row -> one :class:`ArtifactRow`, unpacked by name."""
    if len(row) != len(ARTIFACT_COLUMNS):
        raise CorpusQueryError(
            f"an artifact row arrived with {len(row)} columns, not"
            f" {len(ARTIFACT_COLUMNS)} ({', '.join(ARTIFACT_COLUMNS)}) — the"
            " query and this mapping have drifted apart"
        )
    id_, moment_id, kind, state, title, body = row
    return ArtifactRow(
        id=str(id_),
        moment_id=str(moment_id),
        kind=kind,
        state=state,
        title=title,
        body=body,
    )


def moment_from_row(row: Sequence[Any]) -> MomentRow:
    """One ``moment`` row -> one :class:`MomentRow`, unpacked by name."""
    if len(row) != len(MOMENT_COLUMNS):
        raise CorpusQueryError(
            f"a moment row arrived with {len(row)} columns, not"
            f" {len(MOMENT_COLUMNS)} ({', '.join(MOMENT_COLUMNS)}) — the"
            " query and this mapping have drifted apart"
        )
    id_, identity_key = row
    return MomentRow(id=str(id_), identity_key=identity_key)


def segment_from_row(row: Sequence[Any]) -> TranscriptSegment:
    """One covering-segment row -> one :class:`TranscriptSegment`."""
    if len(row) != len(SEGMENT_COLUMNS):
        raise CorpusQueryError(
            f"a transcript segment row arrived with {len(row)} columns, not"
            f" {len(SEGMENT_COLUMNS)} ({', '.join(SEGMENT_COLUMNS)}) — the"
            " query and this mapping have drifted apart"
        )
    start_ms, end_ms, speaker_label, text = row
    return TranscriptSegment(
        start_ms=start_ms, end_ms=end_ms, speaker_label=speaker_label, text=text
    )


def capture_from_row(row: Sequence[Any]) -> Capture:
    """One ``screenshot`` row -> one :class:`Capture`.

    Unpacked by name rather than indexed by position, so the mapping reads as
    the contract :data:`CAPTURE_COLUMNS` states and a swapped pair is visible
    on the page rather than hidden behind ``row[2]``/``row[3]``.

    The two nullable columns carry the distinction the checks act on:
    ``ocr_text`` stays ``None`` for a capture with no ``frame_ocr`` row (never
    coerced to ``""``, because an empty recognized text is a legitimately
    textless camera gallery and a missing row is a defect), and
    ``has_representative_frame`` separates "a `frames` rerun cleared the
    reference" from "the `ocr` stage did not cover the frame".
    """
    if len(row) != len(CAPTURE_COLUMNS):
        raise CorpusQueryError(
            f"a screenshot row arrived with {len(row)} columns, not"
            f" {len(CAPTURE_COLUMNS)} ({', '.join(CAPTURE_COLUMNS)}) — the"
            " query and this mapping have drifted apart"
        )
    ordinal, view_type, representative_frame_id, ocr_text = row
    return Capture(
        ordinal=ordinal,
        view_type=view_type,
        ocr_text=ocr_text,
        has_representative_frame=representative_frame_id is not None,
    )


def read_only_conninfo(config: Any) -> str:
    """The conninfo the harness connects with, from the resolved config.

    Mirrors ``meetingminer.db.conninfo`` — same host, port, database, user and
    ``.env`` password — plus the read-only option. ``config`` is duck-typed
    (anything exposing ``settings.stores.postgres`` and
    ``secrets.postgres_password``) so this is exercisable without loading the
    real config, which is what keeps the store-free suite off ``load_config``.
    """
    pg = config.settings.stores.postgres
    return psycopg.conninfo.make_conninfo(
        host=pg.host,
        port=pg.port,
        dbname=pg.database,
        user=pg.user,
        password=config.secrets.postgres_password,
        options=READ_ONLY_OPTIONS,
    )


class Corpus:
    """A lazily-opened read-only session over the ingested corpus.

    One connection for a whole run: the reads are a handful of indexed
    lookups per subject, and re-connecting per query would multiply the only
    thing here that can fail.
    """

    def __init__(self, conninfo: str) -> None:
        self.conninfo = conninfo
        self._connection: Connection | None = None

    @classmethod
    def from_config(cls, config: Any) -> Corpus:
        return cls(read_only_conninfo(config))

    @property
    def connection(self) -> Connection:
        if self._connection is None or self._connection.closed:
            try:
                self._connection = psycopg.connect(self.conninfo, autocommit=True)
            except psycopg.Error as exc:
                raise CorpusQueryError(
                    "the harness could not open its read-only connection to"
                    f" Postgres: {exc}"
                ) from exc
        return self._connection

    def close(self) -> None:
        if self._connection is not None and not self._connection.closed:
            self._connection.close()
        self._connection = None

    def _rows(self, sql: str, *params: Any) -> list[tuple[Any, ...]]:
        try:
            return self.connection.execute(sql, params).fetchall()
        except psycopg.Error as exc:
            described = ", ".join(str(param) for param in params)
            raise CorpusQueryError(f"reading {described} failed: {exc}") from exc

    def captures_for(self, meeting_id: str) -> tuple[Capture, ...]:
        """Every ``screenshot`` row for one meeting, ordinal-ordered.

        ``ocr_text`` is ``None`` for a capture with no readable text — the
        distinction the checks report as a run defect. It is never coerced to
        an empty string here, because an empty ``frame_ocr.text`` (a camera
        gallery) is a legitimately textless capture and a missing row is not.
        """
        return tuple(
            capture_from_row(row) for row in self._rows(_CAPTURES, meeting_id)
        )

    def media_duration_ms(self, meeting_id: str) -> int | None:
        """The probed recording length, or ``None`` when nothing probed it.

        ``None`` covers both "no ``meeting_media`` row" and "row with a NULL
        ``duration_ms``": neither gives the manifest cross-check anything to
        compare against, and both are reported by that check rather than here.
        """
        rows = self._rows(_MEDIA_DURATION, meeting_id)
        return rows[0][0] if rows else None

    def artifacts_for(self, meeting_id: str) -> tuple[ArtifactRow, ...]:
        """Every ``artifact`` row for one meeting, insertion-ordered.

        Read-only, direct from Postgres (AD-16 permits this; story 4.3's route
        that would add an API path is still backlog). One row per extraction
        proposal, regardless of ``state`` — the judge scores what was extracted,
        not only what is approved or published.
        """
        return tuple(
            artifact_from_row(row) for row in self._rows(_ARTIFACTS, meeting_id)
        )

    def segments_for_moment(self, moment_id: str) -> tuple[TranscriptSegment, ...]:
        """The transcript a moment covers, in transcript order.

        Mirrors ``api/moments.py``'s ``_COVERING_SEGMENTS`` join — the
        ``moment_segment`` table, never a ``BETWEEN start_ms AND end_ms``
        filter, because a covered segment may legitimately end after its
        moment does and must still be returned in full. This is the judge's
        faithfulness haystack for both a ``qa`` citation and an extracted
        artifact's own moment.
        """
        return tuple(
            segment_from_row(row) for row in self._rows(_SEGMENTS_FOR_MOMENT, moment_id)
        )

    def moments_for(self, meeting_id: str) -> tuple[MomentRow, ...]:
        """Every ``moment`` row for one meeting, timeline-ordered. Read-only.

        Probe eligibility (story 11.3) chooses from these: the publish-gate
        probe must cite an existing moment — ``graph.project_artifacts``
        rolls back on a missing ``Moment`` node, and only the worker/rebuild
        project meetings — so the candidates come from reads, never from
        anything the run seeded itself.
        """
        return tuple(moment_from_row(row) for row in self._rows(_MOMENTS, meeting_id))

    def stage_status(self, meeting_id: str, stage: str) -> str | None:
        """One pipeline stage's checkpoint status for this meeting's job.

        ``None`` when the meeting has no such stage row (or no meeting row)
        — which the probe layer treats as "not settled" and refuses by name,
        never as a green light. Read via ``meeting.job_id`` so the answer is
        about this meeting's own job, not a re-ingested sibling's.
        """
        rows = self._rows(_STAGE_STATUS, meeting_id, stage)
        return rows[0][0] if rows else None

    def meeting_corpus(self, meeting_id: str) -> str | None:
        """The meeting row's ``corpus`` tag, straight from Postgres.

        Check 2.11's refusal guard (story 5.3): the api's subject selection
        already filters to ``scripted``, but the approval mutates *this*
        database, so the tag is re-read here — from the store the mutation
        would hit — before any API call is made. ``None`` when the row is
        gone, which the guard treats as "not provably scripted" and refuses.
        """
        rows = self._rows(_MEETING_CORPUS, meeting_id)
        return rows[0][0] if rows else None

    def has_recording(self, meeting_id: str) -> bool:
        """Whether the drop carried a recording at all.

        A scripted subject with no recording cannot have been captured from,
        so the capture checks are not applicable to it — which is a named
        failure, never an empty pass.
        """
        rows = self._rows(_HAS_RECORDING, meeting_id)
        if not rows:
            raise CorpusQueryError(
                f"no meeting row for {meeting_id} — the api listed it, so either"
                " the row was deleted mid-run or the harness is pointed at a"
                " different database than the api"
            )
        return bool(rows[0][0])
