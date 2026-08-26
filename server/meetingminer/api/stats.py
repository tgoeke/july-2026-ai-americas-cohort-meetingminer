"""GET /corpus/stats — corpus-scale counts for the home screen (SPEC-ui-reimagine CAP-1).

Every number is a count or sum over the database of record — nothing here is
estimated, cached, or decorated, because the home screen's contract is that
"how much evidence does this corpus hold" is answered with real counts only.

Read-only throughout (spec constraint "New backend is read-only"): the module
reads meeting, meeting_media, transcript_segment, moment, screen, screenshot,
artifact, and participant, and writes none of them. Cheap aggregates over the
existing schema — no new pipeline stage, no migration (spec Assumptions).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

router = APIRouter()

# One statement, therefore one snapshot — the same reason api/meetings.py runs
# a single query: two counts read at different instants could disagree about a
# meeting a worker commit lands between them.
#
# Evidence duration per meeting is the probed recording duration when a
# recording exists, else the last transcript segment's end — a transcript-only
# meeting still holds that much evidence, and reporting it as zero would make
# the home screen lie about the corpus (reference-ui.md: honest absence beats
# decoration, but this is presence, not absence).
_CORPUS_COUNTS = """
SELECT
    (SELECT count(*) FROM meeting) AS meetings,
    (SELECT COALESCE(sum(COALESCE(mm.duration_ms, ts.max_end_ms, 0)), 0)
       FROM meeting m
       LEFT JOIN meeting_media mm ON mm.meeting_id = m.id
       LEFT JOIN (SELECT meeting_id, max(end_ms) AS max_end_ms
                    FROM transcript_segment GROUP BY meeting_id) ts
              ON ts.meeting_id = m.id) AS total_duration_ms,
    (SELECT count(*) FROM moment) AS moments,
    (SELECT count(*) FROM screen) AS screens,
    (SELECT count(*) FROM screenshot) AS screenshots,
    (SELECT count(*) FROM artifact) AS artifacts,
    (SELECT count(*) FROM participant) AS participants,
    (SELECT count(*) FROM artifact WHERE state = 'published') AS published_documents
"""

_ARTIFACTS_BY_KIND = "SELECT kind, count(*) FROM artifact GROUP BY kind"
_ARTIFACTS_BY_STATE = "SELECT state, count(*) FROM artifact GROUP BY state"


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ArtifactCounts(_CamelModel):
    """Extracted artifacts, total and split two ways.

    Both splits are dynamic dicts rather than fixed fields so a kind or state
    the CHECK constraint gains later is counted without an api change — the
    values come straight from GROUP BY, never from a hardcoded list.
    """

    total: int
    by_kind: dict[str, int]
    by_state: dict[str, int]


class CorpusStats(_CamelModel):
    """The corpus's scale, as the home screen states it (CAP-1)."""

    meetings: int
    # Recording duration where probed, last transcript end where not.
    total_duration_ms: int
    moments: int
    # Distinct screens (cross-meeting identity) vs. captures of them.
    screens: int
    screenshots: int
    artifacts: ArtifactCounts
    participants: int
    # Artifacts in state 'published' — the only rows that read as knowledge.
    published_documents: int


@router.get(
    "/corpus/stats",
    operation_id="getCorpusStats",
    response_model=CorpusStats,
)
def get_corpus_stats(request: Request) -> CorpusStats:
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = conn.execute(_CORPUS_COUNTS).fetchone()
        by_kind = {r[0]: r[1] for r in conn.execute(_ARTIFACTS_BY_KIND).fetchall()}
        by_state = {r[0]: r[1] for r in conn.execute(_ARTIFACTS_BY_STATE).fetchall()}
    return CorpusStats(
        meetings=row[0],
        total_duration_ms=row[1],
        moments=row[2],
        screens=row[3],
        screenshots=row[4],
        artifacts=ArtifactCounts(total=row[5], by_kind=by_kind, by_state=by_state),
        participants=row[6],
        published_documents=row[7],
    )
