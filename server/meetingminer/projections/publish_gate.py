"""The publish gate: no *artifact* outside `published` state is projected (AD-4).

AD-4 puts this gate *inside* the projection module rather than in the API. The
`artifact` table exists (story 4.1) and story 4.4 wired the production callers:
:func:`published_artifacts` is the one Postgres read that feeds artifact
projection, and it selects ``WHERE state = 'published'`` — so even a caller
that skipped :func:`assert_publishable` could not hand a draft to a store.
The gate still runs on every artifact projected (defense in depth).

The artifact lifecycle is one-way (``extracted → approved → published``) and
there is no unpublish in the capstone, so the gate is a single-state check
rather than a state machine.

The consequence AD-4 draws from this: search and chat operate over evidence
plus *published* artifacts only. An unpublished artifact is visible solely in
the moment view's right rail, through API reads of Postgres — never through a
projected store.

**One deliberate exception, and this docstring names it so the gate's account
of itself stays true.** Extraction documents are projected *without* passing
this gate — every one of them, as soon as it is stored, approved or not (owner
ruling 2026-08-31, recorded in AD-4). The reasoning is story 12.1's motivation
turned around: the run whose text somebody needs to read is exactly the run
that yielded nothing worth approving, so gating documents behind approval would
withhold them in precisely the case they exist for. The exception is narrow in
two ways that this module's rule keeps intact, and both are enforced in
:mod:`meetingminer.projections.documents` rather than asserted here:

* It is an exception to **reach**, never to legibility. A document carries its
  unreviewed, machine-written status in the indexed record itself, and every
  surface that renders one labels it (AD-18).
* It is **never a citation target**. A document is a claim *about* evidence,
  so citing it would establish that the model said something rather than that
  the meeting did — the circularity this gate exists to prevent. Its content
  reaches an answer only through the moments its individual claims anchor to,
  which is the published-artifact path above, gated exactly as before (AD-6).

So the sentence this gate can still stand behind is: nothing uncitable becomes
citable, and no unpublished *artifact* is ever projected. What changed is that
"projected" no longer implies "published" for every kind of thing in the
stores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence
from uuid import UUID

from psycopg import Connection

# The one-way lifecycle from AD-4/AD-5, in order. Listed so a refusal message
# can say where the artifact actually is rather than only that it is wrong.
ARTIFACT_STATES: tuple[str, ...] = ("extracted", "approved", "published")
PUBLISHED_STATE = "published"

# The Meilisearch index published artifacts will land in (Epic 4). Named here
# so the gate and the index it guards are declared together.
ARTIFACTS_INDEX = "artifacts"


class PublishGateRefused(RuntimeError):
    """An artifact was offered for projection in a state that forbids it.

    A named refusal, not a bug: the projection module is *supposed* to say no,
    and the message names the state it saw and the state it requires.
    """


def refusal_reason(state: str | None) -> str | None:
    """Why this state may not be projected, or ``None`` when it may.

    Split out from :func:`assert_publishable` so a caller that wants to report
    a refusal (a CLI summary, a log line) does not have to raise and catch to
    find out. An unknown state is refused too — a value outside the lifecycle
    means something upstream is broken, and guessing would be worse.
    """
    if state == PUBLISHED_STATE:
        return None
    if state is None:
        return (
            "artifact has no lifecycle state; the projection module refuses"
            f" anything that is not {PUBLISHED_STATE!r} (AD-4)"
        )
    if state not in ARTIFACT_STATES:
        return (
            f"artifact state {state!r} is not one of"
            f" {', '.join(ARTIFACT_STATES)} — refusing to project it (AD-4)"
        )
    return (
        f"artifact is {state!r}, not {PUBLISHED_STATE!r} — the publish gate"
        " refuses it; unpublished artifacts are visible only through API reads"
        " of Postgres, never in a projected store (AD-4)"
    )


def is_publishable(state: str | None) -> bool:
    """Whether this lifecycle state may be projected."""
    return refusal_reason(state) is None


def assert_publishable(state: str | None) -> None:
    """Raise :class:`PublishGateRefused` unless ``state`` is ``published``."""
    reason = refusal_reason(state)
    if reason is not None:
        raise PublishGateRefused(reason)


@dataclass(frozen=True)
class Artifact:
    """A published artifact, as the projection will read it (Epic 4).

    Defined now so the shape the gate guards is stated rather than implied.
    ``moment_ids`` is not optional: an artifact with no evidence edge would be
    an uncited claim reaching retrieval, which AD-6 forbids.
    """

    id: UUID
    meeting_id: UUID
    corpus: str
    kind: str
    state: str
    title: str
    body: str
    moment_ids: tuple[UUID, ...]


def artifact_document(artifact: Artifact) -> dict[str, Any]:
    """The Meilisearch document for a published artifact.

    Keyed on the Postgres-minted artifact UUID and carrying ``meetingId`` and
    ``corpus`` like every other projected document, so the same per-meeting
    delete-and-reinsert and the same corpus scoping apply to it.
    """
    assert_publishable(artifact.state)
    if not artifact.moment_ids:
        raise PublishGateRefused(
            f"artifact {artifact.id} is published but cites no moment —"
            " refusing to project an uncited artifact (AD-6)"
        )
    return {
        "id": str(artifact.id),
        "meetingId": str(artifact.meeting_id),
        "corpus": artifact.corpus,
        "kind": artifact.kind,
        "state": artifact.state,
        "title": artifact.title,
        "text": artifact.body,
        "momentIds": [str(moment_id) for moment_id in artifact.moment_ids],
    }


# The projection read. `corpus` lives on `meeting`, so it joins in; the state
# filter is structural rather than advisory — a caller cannot ask this
# statement for a draft. `moment_id` is a single column today and maps 1:1
# onto the dataclass's `moment_ids` tuple.
_PUBLISHED_ARTIFACTS = (
    "SELECT a.id, a.meeting_id, mt.corpus, a.kind, a.state, a.title, a.body,"
    " a.moment_id"
    " FROM artifact a JOIN meeting mt ON mt.id = a.meeting_id"
    " WHERE a.state = %s"
)
_ORDERED = " ORDER BY a.created_at, a.id"


def published_artifacts(
    conn: Connection,
    *,
    meeting_id: UUID | None = None,
    artifact_ids: Sequence[UUID] | None = None,
) -> tuple[Artifact, ...]:
    """Read the published artifacts a projection may write, and only those.

    Scoped either to one meeting (the per-meeting structural pass, `rebuild`)
    or to specific artifact ids (the approve route's post-commit call). The
    ``WHERE state = 'published'`` filter is in the statement itself, so an
    ``extracted`` or ``approved`` id simply does not come back — the caller's
    :func:`assert_publishable` on each returned row is defense in depth, not
    the only line (AD-4).
    """
    if (meeting_id is None) == (artifact_ids is None):
        raise ValueError(
            "published_artifacts takes exactly one scope: meeting_id or artifact_ids"
        )
    if meeting_id is not None:
        rows = conn.execute(
            _PUBLISHED_ARTIFACTS + " AND a.meeting_id = %s" + _ORDERED,
            (PUBLISHED_STATE, meeting_id),
        ).fetchall()
    else:
        if not artifact_ids:
            return ()
        rows = conn.execute(
            _PUBLISHED_ARTIFACTS + " AND a.id = ANY(%s)" + _ORDERED,
            (PUBLISHED_STATE, list(artifact_ids)),
        ).fetchall()
    return tuple(
        Artifact(
            id=row[0],
            meeting_id=row[1],
            corpus=row[2],
            kind=row[3],
            state=row[4],
            title=row[5],
            body=row[6],
            moment_ids=(row[7],),
        )
        for row in rows
    )
