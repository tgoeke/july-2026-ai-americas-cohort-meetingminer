"""`moments` — cut the meeting timeline into the units everything else cites.

This is the stage that makes a citation target exist. It joins the two evidence
lanes the earlier stages produced — `screenshot` rows from `screens`,
`transcript_segment` rows from `align` — into one `moment` row per span,
carrying video-offset milliseconds, ISO 8601 UTC wall clock, the evidencing
screenshot (or, on a meeting with no replay at all, the drop's Stream URL as
UX-DR11's transitional deep link), provenance, and the transcript segments it
covers.

Its idempotence rule is the one exception in the pipeline, and the reason is
AD-6: a moment id is the citation currency, so deleting one breaks every answer
and published artifact that named it. Every other meeting-scoped stage replaces
its rows wholesale; this one **upserts by ``(meeting_id, identity_key)``**
("augmentation adds, never destroys", SPEC Constraints). The only rows it may
delete are ``derived_from = 'screen'`` moments the current run did not
recompute — such a moment exists only as the record of a screenshot that no
longer does.

Every decision lives in :mod:`meetingminer.pipeline.moments` with its
thresholds coming from ``config.yaml`` (AD-10); this module is the I/O around
them. No model call reads any of it (AD-13), and no file is written at all —
the drop directory stays read-only and the rows are the whole output.
"""

from __future__ import annotations

from datetime import timedelta
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from meetingminer.pipeline import moments as core
from meetingminer.pipeline.stage import StageContext, StageError

# Heartbeat cadence for the progress event on a boundary-dense meeting's
# upsert loop. One 34-minute recording in this corpus produced 580 screenshots,
# which is ~600 round-trips: without a heartbeat the stage looks hung.
PROGRESS_EVERY_MOMENTS = 50

_REMAP_PROVENANCE_KEY = "source_moment_remap"
_REMAP_RULE = "unique-live-moment-containing-source-instant"


class ArtifactMomentRemapError(StageError):
    """A published artifact has no unique live evidence-equivalent moment."""


_SELECT_SEGMENTS = """
SELECT id, ordinal, start_ms, end_ms
FROM transcript_segment
WHERE meeting_id = %s
ORDER BY start_ms, ordinal
"""

_SELECT_SCREENSHOTS = """
SELECT id, start_offset_ms, end_offset_ms
FROM screenshot
WHERE meeting_id = %s
ORDER BY start_offset_ms, ordinal
"""

_SELECT_MEETING = """
SELECT started_at, started_at_precision
FROM meeting
WHERE id = %s
"""

# The upsert that replaces delete-then-insert. `DO UPDATE` rather than
# `DO NOTHING`: a rerun over changed inputs must refresh a moment's span,
# screenshot and link, while its id — the thing citations name — stays put.
_UPSERT_MOMENT = """
INSERT INTO moment (
    meeting_id, identity_key, derived_from, start_ms, end_ms,
    started_at, started_at_precision, screenshot_id, source_deep_link,
    segment_count, provenance
) VALUES (
    %(meeting_id)s, %(identity_key)s, %(derived_from)s, %(start_ms)s, %(end_ms)s,
    %(started_at)s, %(started_at_precision)s, %(screenshot_id)s, %(source_deep_link)s,
    %(segment_count)s, %(provenance)s
)
ON CONFLICT (meeting_id, identity_key) DO UPDATE SET
    derived_from = EXCLUDED.derived_from,
    start_ms = EXCLUDED.start_ms,
    end_ms = EXCLUDED.end_ms,
    started_at = EXCLUDED.started_at,
    started_at_precision = EXCLUDED.started_at_precision,
    screenshot_id = EXCLUDED.screenshot_id,
    source_deep_link = EXCLUDED.source_deep_link,
    segment_count = EXCLUDED.segment_count,
    provenance = EXCLUDED.provenance
RETURNING id
"""

_INSERT_MOMENT_SEGMENT = """
INSERT INTO moment_segment (moment_id, transcript_segment_id) VALUES (%s, %s)
"""


def _load_segments(ctx: StageContext) -> list[core.SegmentFacts]:
    rows = ctx.conn.execute(_SELECT_SEGMENTS, (ctx.meeting_id,)).fetchall()
    return [
        core.SegmentFacts(
            segment_id=row[0],
            ordinal=int(row[1]),
            start_ms=int(row[2]),
            end_ms=int(row[3]),
        )
        for row in rows
    ]


def _load_screenshots(ctx: StageContext) -> list[core.ScreenshotFacts]:
    rows = ctx.conn.execute(_SELECT_SCREENSHOTS, (ctx.meeting_id,)).fetchall()
    return [
        core.ScreenshotFacts(
            screenshot_id=row[0],
            start_offset_ms=int(row[1]),
            end_offset_ms=int(row[2]),
        )
        for row in rows
    ]


def _remap_published_artifacts(
    ctx: StageContext,
    planned_with_ids: list[tuple[core.PlannedMoment, UUID]],
    recomputed: list[UUID],
) -> int:
    """Move artifacts off moments this run is about to supersede.

    The source instant is the first/original moment's start, retained across
    every later transition. Exactly one newly planned live span must contain
    it (inclusive start, exclusive end); zero or more than one is a named
    stage failure, so the surrounding transaction rolls back instead of
    committing an uncitable or guessed artifact edge.

    All artifact rows are locked and moved, not only rows already published.
    That serializes against the approval route's ``FOR UPDATE`` and prevents
    an extracted row selected before this stage from becoming published on a
    source this transaction then supersedes.
    """
    rows = ctx.conn.execute(
        "SELECT a.id, a.moment_id, m.start_ms, a.provenance"
        " FROM artifact a JOIN moment m"
        "   ON m.id = a.moment_id AND m.meeting_id = a.meeting_id"
        " WHERE a.meeting_id = %s"
        "   AND NOT (m.id = ANY(%s::uuid[]))"
        " ORDER BY a.id FOR UPDATE OF a",
        (ctx.meeting_id, recomputed),
    ).fetchall()
    for artifact_id, old_moment_id, current_start_ms, provenance in rows:
        artifact_provenance = _artifact_provenance(
            artifact_id, old_moment_id, current_start_ms, provenance
        )
        remap = artifact_provenance.get(_REMAP_PROVENANCE_KEY)
        if remap is None:
            original_moment_id = old_moment_id
            source_instant_ms = int(current_start_ms)
            transitions: list[dict[str, Any]] = []
        else:
            original_moment_id, source_instant_ms, transitions = (
                _validated_remap_history(artifact_id, old_moment_id, remap)
            )
        replacements = [
            replacement_id
            for moment, replacement_id in planned_with_ids
            if moment.start_ms <= source_instant_ms < moment.end_ms
        ]
        if len(replacements) != 1:
            raise ArtifactMomentRemapError(
                f"artifact {artifact_id} cites moment {old_moment_id}"
                f" at {source_instant_ms}ms, but augmentation found"
                f" {len(replacements)} live moments containing that instant;"
                " refusing to supersede its source without one unique"
                " evidence-equivalent replacement"
            )
        replacement_id = replacements[0]
        transitions.append(
            {
                "from_moment_id": str(old_moment_id),
                "to_moment_id": str(replacement_id),
                "source_instant_ms": int(source_instant_ms),
                "rule": _REMAP_RULE,
            }
        )
        artifact_provenance[_REMAP_PROVENANCE_KEY] = {
            "original_moment_id": str(original_moment_id),
            "original_source_instant_ms": source_instant_ms,
            "transitions": transitions,
        }
        ctx.conn.execute(
            "UPDATE artifact SET moment_id = %s, provenance = %s WHERE id = %s",
            (replacement_id, Jsonb(artifact_provenance), artifact_id),
        )
    return len(rows)


def _artifact_provenance(
    artifact_id: UUID,
    old_moment_id: UUID,
    current_start_ms: int,
    provenance: Any,
) -> dict[str, Any]:
    if provenance is None:
        return {}
    if not isinstance(provenance, Mapping):
        raise ArtifactMomentRemapError(
            f"artifact {artifact_id} on moment {old_moment_id} has malformed"
            f" provenance {provenance!r}; refusing to rewrite its source"
            f" from {current_start_ms}ms"
        )
    return dict(provenance)


def _validated_remap_history(
    artifact_id: UUID, current_moment_id: UUID, raw: Any
) -> tuple[UUID, int, list[dict[str, Any]]]:
    """Validate the reserved provenance key before extending its chain."""

    def refuse(reason: str) -> ArtifactMomentRemapError:
        return ArtifactMomentRemapError(
            f"artifact {artifact_id} has malformed {_REMAP_PROVENANCE_KEY}"
            f" provenance ({reason}); refusing to rewrite moment"
            f" {current_moment_id}"
        )

    if not isinstance(raw, Mapping):
        raise refuse("expected an object")
    try:
        original_moment_id = UUID(str(raw["original_moment_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise refuse("invalid original_moment_id") from exc
    raw_transitions = raw.get("transitions")
    if not isinstance(raw_transitions, list) or not raw_transitions:
        raise refuse("transitions must be a non-empty array")

    explicit_instant = raw.get("original_source_instant_ms")
    if explicit_instant is None and isinstance(raw_transitions[0], Mapping):
        # Accept the valid first-version history already written by this story
        # and normalize it on the next transition.
        explicit_instant = raw_transitions[0].get("source_instant_ms")
    if isinstance(explicit_instant, bool) or not isinstance(explicit_instant, int):
        raise refuse("invalid original_source_instant_ms")
    source_instant_ms = explicit_instant

    transitions: list[dict[str, Any]] = []
    expected_from = original_moment_id
    for position, item in enumerate(raw_transitions):
        if not isinstance(item, Mapping):
            raise refuse(f"transition {position} is not an object")
        try:
            from_id = UUID(str(item["from_moment_id"]))
            to_id = UUID(str(item["to_moment_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise refuse(f"transition {position} has an invalid moment id") from exc
        instant = item.get("source_instant_ms")
        if (
            isinstance(instant, bool)
            or not isinstance(instant, int)
            or instant != source_instant_ms
        ):
            raise refuse(f"transition {position} changed the original source instant")
        if item.get("rule") != _REMAP_RULE:
            raise refuse(f"transition {position} has an unknown rule")
        if from_id != expected_from:
            raise refuse(f"transition {position} breaks the remap chain")
        expected_from = to_id
        transitions.append(
            {
                "from_moment_id": str(from_id),
                "to_moment_id": str(to_id),
                "source_instant_ms": source_instant_ms,
                "rule": _REMAP_RULE,
            }
        )
    if expected_from != current_moment_id:
        raise refuse("history does not end at the artifact's current moment")
    return original_moment_id, source_instant_ms, transitions


def run(ctx: StageContext) -> None:
    config = ctx.config.settings.pipeline.moments
    segments = _load_segments(ctx)
    screenshots = _load_screenshots(ctx)
    planned = core.plan_moments(segments, screenshots, config)

    meeting = ctx.conn.execute(_SELECT_MEETING, (ctx.meeting_id,)).fetchone()
    if meeting is None:  # pragma: no cover - the runner mints it before any stage
        raise StageError(f"meeting {ctx.meeting_id} disappeared before `moments` ran")
    started_at, started_at_precision = meeting

    # UX-DR11: the deep link stands in for a replay affordance, so it is written
    # only on a meeting that has neither — no recording in the drop and no
    # screenshot evidence. When either arrives, the link is cleared by the same
    # upsert that attaches the screenshot, which is how "the deep link is
    # retired" happens with no extra mechanism. `drop.stream_url` is the one
    # place that decides what counts as a usable link (non-empty http/https).
    has_replay = ctx.drop.has_recording or bool(screenshots)
    deep_link = None if has_replay else ctx.drop.stream_url
    config_used = {
        "gap_seconds": config.gap_seconds,
        "max_duration_ms": config.max_duration_ms,
    }

    # Rebuilt, never assumed durable: `align` replaces this meeting's
    # `transcript_segment` rows wholesale on a rerun, which cascades these links
    # away. Cleared before the upserts so `UNIQUE (transcript_segment_id)`
    # cannot collide with a link this run is about to re-make.
    ctx.conn.execute(
        "DELETE FROM moment_segment WHERE moment_id IN"
        " (SELECT id FROM moment WHERE meeting_id = %s)",
        (ctx.meeting_id,),
    )

    recomputed: list[UUID] = []
    planned_with_ids: list[tuple[core.PlannedMoment, UUID]] = []
    recomputed_starts: set[int] = set()
    links: list[tuple[UUID, UUID]] = []
    for moment in planned:
        payload: dict[str, Any] = {
            "meeting_id": ctx.meeting_id,
            "identity_key": moment.identity_key,
            "derived_from": moment.derived_from,
            "start_ms": moment.start_ms,
            "end_ms": moment.end_ms,
            "started_at": started_at + timedelta(milliseconds=moment.start_ms),
            "started_at_precision": started_at_precision,
            "screenshot_id": moment.screenshot_id,
            "source_deep_link": deep_link,
            "segment_count": moment.segment_count,
            "provenance": Jsonb(
                {
                    "boundary": moment.boundary,
                    "derived_from": moment.derived_from,
                    "config": config_used,
                }
            ),
        }
        moment_id = ctx.conn.execute(_UPSERT_MOMENT, payload).fetchone()[0]
        recomputed.append(moment_id)
        planned_with_ids.append((moment, moment_id))
        recomputed_starts.add(moment.start_ms)
        links.extend((moment_id, segment_id) for segment_id in moment.segment_ids)
        done = len(recomputed)
        if done % PROGRESS_EVERY_MOMENTS == 0 and done != len(planned):
            ctx.log(
                "stage.moments.progress",
                meeting_id=ctx.meeting_id,
                moments_done=done,
                moment_count=len(planned),
            )

    if links:
        with ctx.conn.cursor() as cursor:
            cursor.executemany(_INSERT_MOMENT_SEGMENT, links)

    remapped_artifacts = _remap_published_artifacts(ctx, planned_with_ids, recomputed)

    # The one deletion this stage is allowed. A screen-anchored moment exists
    # only because a screenshot did, so one this run did not recompute is the
    # record of evidence that is gone. Transcript-anchored moments are never
    # deleted here, whatever the current transcript says.
    #
    # The `start_ms` guard closes a re-key hole. If `align` later derives a
    # transcript boundary that lands exactly where a `screen:X` moment already
    # starts, the span becomes `both` and keys as `transcript:X` — a *different*
    # row. Deleting the old `screen:X` would then re-key that instant onto a new
    # UUID and break every citation naming it, which is precisely what this
    # stage exists to prevent. The screenshot is still there, so the row is not
    # evidence of anything gone; it is superseded, and it is kept and marked.
    #
    # The casts are not decoration: an empty `recomputed` (the empty-meeting
    # path) would otherwise be an array of unknown type and abort the statement.
    removed = ctx.conn.execute(
        "DELETE FROM moment WHERE meeting_id = %s AND derived_from = 'screen'"
        " AND NOT (id = ANY(%s::uuid[]))"
        " AND NOT (start_ms = ANY(%s::bigint[])) RETURNING id",
        (ctx.meeting_id, recomputed, sorted(recomputed_starts)),
    ).fetchall()

    # What is left un-recomputed and un-deleted is *superseded*: a moment whose
    # boundary moved when `align` re-derived the transcript, or a screen-anchored
    # row a transcript boundary has just taken over. It keeps its id so every
    # citation still resolves (AD-6), but a reader ordering this meeting by
    # `start_ms` must be able to tell it from a live one — otherwise Epic 2
    # projects ghost moments interleaved with real ones. So it is marked in
    # provenance (merged, never overwriting what is already recorded there) and
    # its coverage count is squared with the links it actually has, which the
    # rebuild above left at zero. A superseded moment that comes back on a later
    # run is un-marked by the upsert, which rewrites `provenance` wholesale.
    superseded = ctx.conn.execute(
        "UPDATE moment SET"
        "   provenance = provenance || '{\"superseded\": true}'::jsonb,"
        "   segment_count = 0,"
        "   source_deep_link = CASE WHEN %s THEN NULL ELSE source_deep_link END"
        " WHERE meeting_id = %s AND NOT (id = ANY(%s::uuid[]))"
        " RETURNING id, derived_from",
        (has_replay, ctx.meeting_id, recomputed),
    ).fetchall()

    moments_without_link = 0 if (has_replay or deep_link) else len(planned)

    ctx.log(
        "stage.moments.identified",
        meeting_id=ctx.meeting_id,
        moment_count=len(planned),
        transcript_anchored=sum(
            1 for m in planned if m.derived_from != core.DERIVED_SCREEN
        ),
        screen_anchored=sum(
            1 for m in planned if m.derived_from == core.DERIVED_SCREEN
        ),
        with_screenshot=sum(1 for m in planned if m.screenshot_id is not None),
        # Exactly: moments on a meeting rendering in UX-DR11's *degraded* mode
        # (no recording, no screenshots) that got no deep link either, so they
        # offer neither replay nor a way back to the source. Zero whenever the
        # meeting has replay evidence — those moments want no link at all — and
        # zero when the drop supplied a usable one.
        moments_without_link=moments_without_link,
        degraded_moments_without_link=moments_without_link,
        segments_covered=sum(m.segment_count for m in planned),
        retained_stale=sum(
            1
            for _moment_id, derived_from in superseded
            if derived_from != core.DERIVED_SCREEN
        ),
        removed_screen_anchored=len(removed),
        remapped_artifacts=remapped_artifacts,
        boundaries=core.boundary_counts(planned),
        config=config_used,
    )
