"""`align` — reconcile the transcript lanes into derived rows, and derive participants.

This is the stage that makes "no citation, no answer" possible: it produces the
only transcript rows anything downstream reads, and it decides who said each of
them — or honestly records that it could not tell.

Two halves, both deterministic code (AD-13: evidence is never model-written):

* **Reconciliation.** The provided transcript is parsed in place — never
  rewritten, copied over, or deleted (the drop is read-only, AD-13) — and each
  turn becomes a *new* `transcript_segment` row naming its inputs: labels and
  text from the speaker-attributed ``.txt``, end timing from the VTT where a
  cue matched, and the STT lane as the verification anchor when a match landed
  inside the configured window. No file is picked wholesale and no two raw
  sources are merged into one raw source.
* **Participants.** The roster is the drop's participant graph when it carries
  one, and otherwise the transcript's own non-placeholder speaker labels. Every
  identity key is resolved through the API-owned `participant_alias` table
  before any insert, so an Epic-2 human merge survives re-ingest and reruns
  (AD-5).

Idempotence follows AD-11's split. Meeting-scoped rows (`transcript_segment`,
`meeting_participant`) are replaced wholesale by a rerun; the cross-meeting
`participant` rows they point at are upserted by identity key and never
deleted. Provided `transcript_source` rows are upserted rather than replaced so
their ids stay stable for the derived rows that name them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from psycopg.types.json import Jsonb

from meetingminer.config import AlignConfig
from meetingminer.pipeline import speakers, transcripts
from meetingminer.pipeline.alignment import (
    AlignmentMatch,
    TimedText,
    align_segments,
    merge_vtt_end_timings,
    resolve_end_times,
)
from meetingminer.pipeline.stage import StageContext, StageError
from meetingminer.pipeline.transcripts import strip_nuls

KIND_PROVIDED_TEXT = "provided-text"
KIND_PROVIDED_VTT = "provided-vtt"
KIND_STT = "stt"
PROVIDED_KINDS = (KIND_PROVIDED_TEXT, KIND_PROVIDED_VTT)

# Heartbeat cadence for the progress event on a long meeting's insert loop.
PROGRESS_EVERY_SEGMENTS = 500

_UPSERT_PROVIDED_SOURCE = """
INSERT INTO transcript_source (
    meeting_id, kind, format, drop_relative_path, content_path,
    sha256, byte_size, segment_count
) VALUES (
    %(meeting_id)s, %(kind)s, %(format)s, %(drop_relative_path)s, NULL,
    %(sha256)s, %(byte_size)s, %(segment_count)s
)
ON CONFLICT (meeting_id, kind) DO UPDATE SET
    format = EXCLUDED.format,
    drop_relative_path = EXCLUDED.drop_relative_path,
    sha256 = EXCLUDED.sha256,
    byte_size = EXCLUDED.byte_size,
    segment_count = EXCLUDED.segment_count
RETURNING id
"""

_INSERT_SEGMENT = """
INSERT INTO transcript_segment (
    meeting_id, ordinal, start_ms, end_ms, text, speaker_label, participant_id,
    speaker_resolution, label_source_id, timing_source_id, stt_source_id,
    stt_start_ms, alignment_delta_ms, match_score
) VALUES (
    %(meeting_id)s, %(ordinal)s, %(start_ms)s, %(end_ms)s, %(text)s,
    %(speaker_label)s, %(participant_id)s, %(speaker_resolution)s,
    %(label_source_id)s, %(timing_source_id)s, %(stt_source_id)s,
    %(stt_start_ms)s, %(alignment_delta_ms)s, %(match_score)s
)
"""

_INSERT_MEETING_PARTICIPANT = """
INSERT INTO meeting_participant (
    meeting_id, participant_id, mail, title, department, dept_code,
    line_of_business, office, org, is_guest, is_external, spoke_turns,
    spoke_words, found_in, derived_from, source
) VALUES (
    %(meeting_id)s, %(participant_id)s, %(mail)s, %(title)s, %(department)s,
    %(dept_code)s, %(line_of_business)s, %(office)s, %(org)s, %(is_guest)s,
    %(is_external)s, %(spoke_turns)s, %(spoke_words)s, %(found_in)s,
    %(derived_from)s, %(source)s
)
"""


@dataclass(frozen=True)
class LoadedSource:
    """One recorded `transcript_source` row plus what it parsed to."""

    id: UUID
    kind: str
    format: str
    parsed: transcripts.ParsedTranscript

    @property
    def segments(self) -> tuple[transcripts.ParsedSegment, ...]:
        return self.parsed.segments


@dataclass
class RosterEntry:
    """One candidate person for this meeting, before identity resolution.

    Two keys, deliberately: ``match_key`` is the normalized display name a
    transcript label is matched against *inside this meeting*, and
    ``identity_key`` is what the person is upserted by *across* meetings —
    their mail when the graph supplies one. Conflating them is what makes two
    same-named humans collapse onto one participant row.
    """

    identity_key: str
    match_key: str
    display_name: str
    graph: dict[str, Any] | None = None
    spoke: bool = False
    participant_id: UUID | None = None

    @property
    def derived_from(self) -> str:
        if self.graph is None:
            return "transcript"
        return "both" if self.spoke else "drop-graph"


def _strip_nuls_deep(value: Any) -> Any:
    """``strip_nuls`` applied through a nested structure, keys included.

    The participant graph is stored whole as jsonb, and Postgres refuses
    U+0000 there exactly as it does in ``text``. Sanitizing only the scalars
    lifted onto their own columns would still fail the INSERT on the payload.
    """
    if isinstance(value, str):
        return strip_nuls(value)
    if isinstance(value, dict):
        return {_strip_nuls_deep(k): _strip_nuls_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nuls_deep(item) for item in value]
    return value


def _read_drop_file(path: Path) -> tuple[str, str, int]:
    """Text, sha256 of the raw bytes, and byte size. The drop is only read."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StageError(f"provided transcript {path.name} could not be read: {exc}") from exc
    # Digest the bytes, not the decoded text: the hash answers "did this input
    # change", which is a question about the file, not about our decoder.
    digest = hashlib.sha256(raw).hexdigest()
    return raw.decode("utf-8", errors="replace"), digest, len(raw)


def _record_provided_sources(ctx: StageContext) -> dict[str, LoadedSource]:
    """Parse and record every transcript the drop provided.

    A ``.txt`` that matches neither lineage fails the stage naming the file: a
    provided transcript that is silently ignored is exactly the evidence loss
    AD-13 exists to prevent. A ``.vtt`` that will not parse is recorded with
    zero segments instead — it only ever contributes end timings, and losing
    those must not cost the meeting its speaker-attributed text.
    """
    loaded: dict[str, LoadedSource] = {}
    candidates = (
        (KIND_PROVIDED_TEXT, ctx.drop.transcript_text_path),
        (KIND_PROVIDED_VTT, ctx.drop.transcript_vtt_path),
    )
    for kind, path in candidates:
        if path is None:
            continue
        text, digest, byte_size = _read_drop_file(path)
        if kind == KIND_PROVIDED_VTT:
            parsed = transcripts.parse_vtt(text)
        else:
            try:
                parsed = transcripts.parse_text_transcript(text)
            except transcripts.TranscriptParseError as exc:
                raise StageError(f"provided transcript {path.name}: {exc}") from exc
        source_id = ctx.conn.execute(
            _UPSERT_PROVIDED_SOURCE,
            {
                "meeting_id": ctx.meeting_id,
                "kind": kind,
                "format": parsed.format,
                # Relative to MM_DROPS_ROOT, not to the drop's own folder
                # (story 2.1a, `storage-layout.md` §4-5): a bare filename is
                # not resolvable without knowing which drop the job currently
                # points at, and that changes under an augmenting re-emit.
                "drop_relative_path": ctx.drop_relative_path(path),
                "sha256": digest,
                "byte_size": byte_size,
                "segment_count": parsed.segment_count,
            },
        ).fetchone()[0]
        loaded[kind] = LoadedSource(
            id=source_id, kind=kind, format=parsed.format, parsed=parsed
        )

    # A drop that lost a transcript form between runs must not keep the row
    # describing it. The cascade takes the derived rows naming it; they are
    # rewritten below.
    stale = [kind for kind in PROVIDED_KINDS if kind not in loaded]
    if stale:
        ctx.conn.execute(
            "DELETE FROM transcript_source WHERE meeting_id = %s AND kind = ANY(%s)",
            (ctx.meeting_id, stale),
        )
    return loaded


def _load_stt_source(ctx: StageContext) -> LoadedSource | None:
    """The verification lane `transcribe` recorded, or ``None``.

    ``None`` is the transcript-only case: the drop carried no recording, so
    `transcribe` was recorded as skipped and every derived row's
    ``stt_source_id`` stays NULL.
    """
    row = ctx.conn.execute(
        "SELECT id, segments FROM transcript_source"
        " WHERE meeting_id = %s AND kind = 'stt'",
        (ctx.meeting_id,),
    ).fetchone()
    if row is None:
        return None
    source_id, payload = row

    def _decoded(index: int, entry: dict[str, Any]) -> transcripts.ParsedSegment:
        # `or 0` would turn a missing or unparseable start into offset zero — a
        # fabricated timestamp, which is the one thing the whole verification
        # lane exists to avoid. A payload this stage wrote and cannot now read
        # is a bug, so it fails the stage by name instead.
        start = _as_int(entry.get("start_ms"))
        if start is None:
            raise StageError(
                f"stt transcript_source segment {index} has no usable start_ms:"
                f" {entry.get('start_ms')!r}"
            )
        end = _as_int(entry.get("end_ms")) if entry.get("end_ms") is not None else None
        return transcripts.ParsedSegment(
            ordinal=index,
            start_ms=start,
            end_ms=end,
            speaker_label=entry.get("speaker"),
            text=str(entry.get("text") or ""),
        )

    segments = tuple(
        _decoded(index, entry)
        for index, entry in enumerate(payload or [], start=1)
        if isinstance(entry, dict)
    )
    return LoadedSource(
        id=source_id,
        kind=KIND_STT,
        format=transcripts.FORMAT_STT,
        parsed=transcripts.ParsedTranscript(
            format=transcripts.FORMAT_STT, segments=segments
        ),
    )


def _graph_roster(ctx: StageContext) -> list[RosterEntry] | None:
    """The drop's participant graph as roster entries, or ``None`` when absent.

    The Teams puller fills the key from its per-occurrence ``org chart.json``
    (story 1.13), so this is the path that runs for a drop emitted since; the
    transcript-derived path below still runs for one emitted before, and for
    any source that has no graph to give. An entry without a ``displayName``
    fails the stage naming its index — a nameless participant is not something
    to guess around.
    """
    raw = ctx.drop.metadata.get("participants")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise StageError(
            f"metadata.participants must be an array, got {type(raw).__name__}"
        )
    if not raw:
        # An empty array says "the source looked and found nobody". Falling
        # back to transcript labels here would invent a roster the drop
        # explicitly declined to assert.
        return []
    entries: dict[str, RosterEntry] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise StageError(
                f"metadata.participants[{index}] is not an object:"
                f" {type(item).__name__}"
            )
        display = item.get("displayName")
        if not isinstance(display, str) or not display.strip():
            raise StageError(
                f"metadata.participants[{index}] has no usable displayName"
            )
        match_key = speakers.normalize_display_name(display)
        if not match_key:  # pragma: no cover - a non-blank name always normalizes
            raise StageError(
                f"metadata.participants[{index}] displayName {display!r}"
                " normalizes to nothing"
            )
        key = speakers.identity_key_for(display, _as_text(item.get("mail")))
        existing = entries.get(key)
        if existing is None:
            entries[key] = RosterEntry(
                identity_key=key,
                match_key=match_key,
                display_name=strip_nuls(display.strip()),
                graph=item,
            )
        else:
            # Two graph entries folding onto one *identity* key is a merge the
            # source already made in effect. Later entries win field by field,
            # which is what "the last thing the source said about this person"
            # means; the display name stays the one first seen.
            # Two people who merely share a name keep separate entries and one
            # shared match key, which makes that label honestly ambiguous
            # rather than silently attributing it to whichever came first.
            existing.graph = {**(existing.graph or {}), **item}
    return list(entries.values())


def _label_roster(labels: Iterable[str | None]) -> list[RosterEntry]:
    """A roster built from the transcript's own non-placeholder labels."""
    entries: dict[str, RosterEntry] = {}
    for label in labels:
        if label is None or not label.strip() or speakers.is_placeholder_label(label):
            continue
        # No graph, so no mail: the name is both the match key and, through
        # `identity_key_for`, the namespaced identity key.
        key = speakers.identity_key_for(label)
        if key and key not in entries:
            entries[key] = RosterEntry(
                identity_key=key,
                match_key=speakers.normalize_display_name(label),
                display_name=strip_nuls(label.strip()),
            )
    return list(entries.values())


def _disambiguate(
    resolution: speakers.LabelResolution, shared_names: set[str]
) -> speakers.LabelResolution:
    """Refuse a match onto a name two different identities both write.

    Never-guess applies to the roster as much as to the label: if the graph
    says two people are called `Kingsley, Kendall`, a turn labelled that names
    both of them, and naming one anyway would be exactly the wrong attribution
    the constraint exists to prevent.
    """
    if resolution.status != speakers.RESOLVED:
        return resolution
    if resolution.match_key not in shared_names:
        return resolution
    return speakers.LabelResolution(
        status=speakers.AMBIGUOUS, candidates=resolution.candidates
    )


def _resolve_participants(ctx: StageContext, roster: list[RosterEntry]) -> None:
    """Give every roster entry a `participant` id, through the alias table.

    The alias lookup comes first and unconditionally (AD-5): if a human merged
    this identity away in Epic 2, the surviving participant is the one this
    meeting must reference, and re-creating the merged-away row would undo the
    merge on every re-ingest.
    """
    for entry in roster:
        alias = ctx.conn.execute(
            "SELECT participant_id FROM participant_alias WHERE alias_key = %s",
            (entry.identity_key,),
        ).fetchone()
        if alias is not None:
            entry.participant_id = alias[0]
            continue
        # A genuine upsert: `identity_key` is UNIQUE and this row may already
        # exist from another meeting, which a bare INSERT would abort on.
        # `display_name` is deliberately not refreshed — the API owns human
        # edits to it (AD-5) and a re-ingest must not undo one.
        entry.participant_id = ctx.conn.execute(
            "INSERT INTO participant (identity_key, display_name, normalized_name)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (identity_key) DO UPDATE SET"
            "   normalized_name = EXCLUDED.normalized_name"
            " RETURNING id",
            (entry.identity_key, entry.display_name, entry.match_key),
        ).fetchone()[0]


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = strip_nuls(str(value)).strip()
    return text or None


def _found_in(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [strip_nuls(str(item)) for item in value if item is not None]
    return []


def _meeting_participant_rows(
    meeting_id: UUID, roster: list[RosterEntry]
) -> list[dict[str, Any]]:
    """One row per *participant*, merging roster entries the alias table joined.

    Two roster entries can resolve to one participant id — that is exactly what
    a human merge does — and `meeting_participant` is keyed on
    ``(meeting_id, participant_id)``, so they are folded here rather than left
    to collide on insert.
    """
    merged: dict[UUID, dict[str, Any]] = {}
    for entry in roster:
        if entry.participant_id is None:  # pragma: no cover - always resolved first
            continue
        graph = entry.graph or {}
        row = merged.get(entry.participant_id)
        candidate = {
            "meeting_id": meeting_id,
            "participant_id": entry.participant_id,
            "mail": _as_text(graph.get("mail")),
            "title": _as_text(graph.get("title")),
            "department": _as_text(graph.get("department")),
            "dept_code": _as_text(graph.get("deptCode")),
            "line_of_business": _as_text(graph.get("lineOfBusiness")),
            "office": _as_text(graph.get("office")),
            "org": _as_text(graph.get("org")),
            "is_guest": bool(graph.get("guest", False)),
            # The graph's `unresolved: true` marks an *external* attendee who
            # is not in the tenant directory. They are kept as external, never
            # dropped and never merged into a resolved person — and this is a
            # different fact from a speaker label that matched nobody.
            "is_external": bool(graph.get("unresolved", False)),
            "spoke_turns": _as_int(graph.get("spokeTurns")),
            "spoke_words": _as_int(graph.get("spokeWords")),
            "found_in": _found_in(graph.get("foundIn")),
            "derived_from": entry.derived_from,
            # The scalars above are sanitized individually, but this stores the
            # graph entry whole. Postgres refuses U+0000 in jsonb exactly as it
            # does in text, so one bad byte anywhere in the drop's graph would
            # otherwise fail the entire stage.
            "source": Jsonb(_strip_nuls_deep(graph)),
        }
        if row is None:
            merged[entry.participant_id] = candidate
            continue
        for key, value in candidate.items():
            if key in ("meeting_id", "participant_id", "derived_from"):
                continue
            if not row.get(key) and value:
                row[key] = value
        if row["derived_from"] != candidate["derived_from"]:
            row["derived_from"] = "both"
    return list(merged.values())


@dataclass
class DerivedSegment:
    """One row about to be written, before it is handed to the INSERT."""

    ordinal: int
    start_ms: int
    end_ms: int
    text: str
    speaker_label: str
    resolution: str
    participant_id: UUID | None
    label_source_id: UUID
    timing_source_id: UUID
    match: AlignmentMatch = field(default_factory=AlignmentMatch)


def _timed(segments: Iterable[transcripts.ParsedSegment]) -> tuple[TimedText, ...]:
    return tuple(
        TimedText(start_ms=s.start_ms, end_ms=s.end_ms, text=s.text) for s in segments
    )


def run(ctx: StageContext) -> None:
    config: AlignConfig = ctx.config.settings.pipeline.align
    provided = _record_provided_sources(ctx)
    stt = _load_stt_source(ctx)

    text_source = provided.get(KIND_PROVIDED_TEXT)
    vtt_source = provided.get(KIND_PROVIDED_VTT)

    # Labels come from the speaker-attributed export (AD-13). A drop carrying
    # only a VTT falls back to its cues, which carry no speakers at all — the
    # rows then say `Unknown`/`placeholder` rather than borrowing a name.
    if text_source is not None and text_source.segments:
        label_source = text_source
    elif vtt_source is not None and vtt_source.segments:
        label_source = vtt_source
    else:
        label_source = None

    if label_source is None and stt is None:
        # A silent recording has lawful visual evidence but no lawful words,
        # timing, or speakers to derive.  A declared participant graph remains
        # source evidence independent of speech, so preserve it; absent (or an
        # explicitly empty) graph means no participants.  Settle at zero text
        # rows so `moments` can build its screen-only timeline; a rerun also
        # removes rows that described an earlier transcript-bearing drop.
        roster = _graph_roster(ctx)
        from_graph = roster is not None
        if roster is None:
            roster = []
        _resolve_participants(ctx, roster)
        ctx.conn.execute(
            "DELETE FROM transcript_segment WHERE meeting_id = %s", (ctx.meeting_id,)
        )
        ctx.conn.execute(
            "DELETE FROM meeting_participant WHERE meeting_id = %s", (ctx.meeting_id,)
        )
        participant_rows = _meeting_participant_rows(ctx.meeting_id, roster)
        if participant_rows:
            with ctx.conn.cursor() as cursor:
                cursor.executemany(_INSERT_MEETING_PARTICIPANT, participant_rows)
        ctx.log(
            "stage.align.derived",
            meeting_id=ctx.meeting_id,
            segment_count=0,
            label_source=None,
            label_format=None,
            vtt_end_timings=0,
            stt_anchored=0,
            stt_segments=0,
            roster_source="drop-graph" if from_graph else "none",
            participant_count=len(participant_rows),
            resolved=0,
            unresolved=0,
            ambiguous=0,
            placeholder=0,
        )
        return

    if label_source is not None:
        label_source_id = label_source.id
        base = label_source.segments
        vtt_ends: tuple[int | None, ...]
        if vtt_source is not None and vtt_source is not label_source and vtt_source.segments:
            vtt_ends = merge_vtt_end_timings(
                _timed(base), _timed(vtt_source.segments), config
            )
        else:
            vtt_ends = tuple(None for _ in base)
        timing_ids = tuple(
            vtt_source.id if (end is not None and vtt_source is not None) else label_source.id
            for end in vtt_ends
        )
    elif stt is not None:
        # No provided transcript at all: the derived segments *are* the STT
        # segments, every speaker label the `Unknown` placeholder (AD-13).
        label_source_id = stt.id
        base = stt.segments
        vtt_ends = tuple(None for _ in base)
        timing_ids = tuple(stt.id for _ in base)
    else:  # pragma: no cover - the zero-segment branch above already returned
        raise StageError("align reached its derivation with no source at all")

    timed = _timed(base)
    ends = resolve_end_times(timed, vtt_ends, config)
    for position, (segment, end_ms) in enumerate(zip(timed, ends)):
        following = timed[position + 1] if position + 1 < len(timed) else None
        if (
            end_ms == segment.start_ms
            and vtt_ends[position] is None
            and segment.end_ms is None
            and following is not None
            and following.start_ms <= segment.start_ms
        ):
            ctx.log(
                "stage.align.zero-duration-fallback",
                severity="warning",
                meeting_id=ctx.meeting_id,
                turn_ordinal=position + 1,
                turn_start_ms=segment.start_ms,
                following_turn_start_ms=following.start_ms,
            )
    matches: tuple[AlignmentMatch, ...]
    if stt is not None and label_source is not None and stt.segments:
        matches = align_segments(timed, _timed(stt.segments), config)
    else:
        # Either there is no verification lane at all (a transcript-only drop),
        # or the lane *is* the transcript. An STT segment aligned to itself is
        # not evidence of anything, so those rows name the STT source as their
        # label and timing source and leave the anchor columns NULL.
        matches = tuple(AlignmentMatch() for _ in base)

    roster = _graph_roster(ctx)
    from_graph = roster is not None
    if roster is None:
        roster = _label_roster(segment.speaker_label for segment in base)
    # Labels are matched against the *match* keys — normalized display names —
    # because a transcript never carries a mail address.
    roster_keys = tuple(entry.match_key for entry in roster)
    by_key: dict[str, RosterEntry] = {}
    shared_names: set[str] = set()
    for entry in roster:
        if entry.match_key in by_key:
            # Two distinct identities writing the same name. `resolve_label`
            # compares against a *set* of keys, so on its own it would see one
            # candidate and resolve — attributing every turn to whichever the
            # roster happened to list first. The multiplicity is only knowable
            # here, so the ambiguity is applied here.
            shared_names.add(entry.match_key)
            continue
        by_key[entry.match_key] = entry

    resolutions = [
        _disambiguate(
            speakers.resolve_label(segment.speaker_label, roster_keys), shared_names
        )
        for segment in base
    ]
    for resolution in resolutions:
        if resolution.status == speakers.RESOLVED and resolution.match_key in by_key:
            by_key[resolution.match_key].spoke = True

    _resolve_participants(ctx, roster)

    # Meeting-scoped rows are replaced wholesale, including on the empty path
    # so a rerun over a meeting whose transcript vanished clears what described
    # it. `participant` is never deleted here — it is cross-meeting (AD-11).
    ctx.conn.execute(
        "DELETE FROM transcript_segment WHERE meeting_id = %s", (ctx.meeting_id,)
    )
    ctx.conn.execute(
        "DELETE FROM meeting_participant WHERE meeting_id = %s", (ctx.meeting_id,)
    )

    participant_rows = _meeting_participant_rows(ctx.meeting_id, roster)
    if participant_rows:
        with ctx.conn.cursor() as cursor:
            cursor.executemany(_INSERT_MEETING_PARTICIPANT, participant_rows)

    counts = {name: 0 for name in speakers.RESOLUTIONS}
    anchored = 0
    total = len(base)
    for index, segment in enumerate(base):
        resolution = resolutions[index]
        counts[resolution.status] += 1
        entry = (
            by_key.get(resolution.match_key)
            if resolution.status == speakers.RESOLVED
            else None
        )
        match = matches[index]
        if match.matched:
            anchored += 1
        ctx.conn.execute(
            _INSERT_SEGMENT,
            {
                "meeting_id": ctx.meeting_id,
                "ordinal": index + 1,
                "start_ms": segment.start_ms,
                "end_ms": ends[index],
                "text": strip_nuls(segment.text),
                "speaker_label": strip_nuls(
                    (segment.speaker_label or "").strip() or transcripts.UNKNOWN_SPEAKER
                ),
                "participant_id": entry.participant_id if entry is not None else None,
                "speaker_resolution": resolution.status,
                "label_source_id": label_source_id,
                "timing_source_id": timing_ids[index],
                "stt_source_id": stt.id if (match.matched and stt is not None) else None,
                "stt_start_ms": match.stt_start_ms,
                "alignment_delta_ms": match.delta_ms,
                "match_score": match.match_score,
            },
        )
        if (index + 1) % PROGRESS_EVERY_SEGMENTS == 0 and index + 1 != total:
            ctx.log(
                "stage.align.progress",
                meeting_id=ctx.meeting_id,
                segments_done=index + 1,
                segment_count=total,
            )

    ctx.log(
        "stage.align.derived",
        meeting_id=ctx.meeting_id,
        segment_count=total,
        label_source=label_source.kind if label_source is not None else KIND_STT,
        label_format=label_source.format if label_source is not None else transcripts.FORMAT_STT,
        vtt_end_timings=sum(1 for end in vtt_ends if end is not None),
        stt_anchored=anchored,
        stt_segments=len(stt.segments) if stt is not None else 0,
        roster_source="drop-graph" if from_graph else "transcript",
        participant_count=len(participant_rows),
        resolved=counts[speakers.RESOLVED],
        unresolved=counts[speakers.UNRESOLVED],
        ambiguous=counts[speakers.AMBIGUOUS],
        placeholder=counts[speakers.PLACEHOLDER],
    )
