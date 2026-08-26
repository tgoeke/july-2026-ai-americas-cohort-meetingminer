"""Reading the Neo4j projection — the graph query half of AD-7.

AD-7 says retrieval over the graph is hand-written, parameterized Cypher, and
the model's only jobs are classifying a question onto a template and
synthesizing the cited answer. This module is where that classification lands:
:data:`TRAVERSAL_TEMPLATES` is the complete registry of templates story 3.3's
router may dispatch onto, each entry carrying its Cypher text so "hand-written,
parameterized" is reviewable in one place rather than asserted in prose.

Two templates, matching the two demo traversals `spec-1-7` recorded when it
authored the graph shape:

* **screen-history** — ``Screen ← Screenshot ← Moment → Meeting``: every
  meeting and moment where a screen appeared, in time order. It walks
  ``SHOWS``, not ``SHOWN_DURING∘COVERS``, because the recorded design counts a
  moment as *showing* a screen only when that screen is its representative
  visual.
* **participant-topic-moments** — ``Participant → Meeting → Moment``: the
  "I already explained this to Clarence" query. Presence is ``ATTENDED``, not
  ``SPOKE_IN`` — Clarence was in the room, not necessarily speaking. There is
  no topic hop: Topic nodes do not exist until Epic 4, so "the topic was
  discussed" is a case-insensitive substring over ``Moment.text``.

Three rules every template obeys:

**Values travel as parameters, never in the statement text** (AD-7). The
Cypher strings below contain ``$``-parameters and no quote characters, so no
*string* literal can appear in them; a template test asserts both.

**Ids are Postgres-minted UUIDs, carried verbatim** (AD-6). Every returned id
is parsed to :class:`~uuid.UUID`; a node whose id does not parse is a named
:class:`ProjectionError`, mirroring ``projections/query.py``'s precedent for
the search store.

**No silent zero.** An anchor that matches no node (unknown screen or
participant) is a result whose anchor is ``None`` — distinguishable from an
anchor that exists but has no matching moments, which is a valid empty answer.
Malformed *input* is refused with :class:`ValueError` rather than resolved: an
anchor id that is not a UUID could never match a node, so sending it to the
store would collapse a caller bug into the unknown-anchor shape. Symmetrically,
a blank topic is refused — it would match the whole corpus, and a silent
*everything* is as wrong as a silent zero.

Rows carry what the graph holds (title, offsets, deep link) for ordering and
display context only — Neo4j ranks, Postgres cites. Story 3.3's citation
validator re-resolves every cited moment against Postgres before anything
reaches the wire. There is no result limit: the deferred retrieval eval
(`evals/designs/retrieval-eval.md` leg 2) compares exact sets, so a template
returns the complete result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping
from uuid import UUID

import neo4j
import neo4j.exceptions

from meetingminer.projections.stores import ProjectionError, StoreUnavailableError

# The registered template names — what story 3.3's router classifies onto.
SCREEN_HISTORY = "screen-history"
PARTICIPANT_TOPIC_MOMENTS = "participant-topic-moments"


# --- result shapes ---------------------------------------------------------


@dataclass(frozen=True)
class TraversalMoment:
    """One meeting-and-moment row a traversal returned, in traversal order.

    ``moment_id`` is the Postgres-minted UUID carried verbatim from the graph
    node (AD-6) — the citation currency. The rest is projection-read context
    for ordering and display; nothing here claims citation authority.
    """

    moment_id: UUID
    meeting_id: UUID
    meeting_title: str | None
    meeting_started_at: datetime
    start_ms: int
    end_ms: int
    screenshot_id: UUID | None
    source_deep_link: str | None


@dataclass(frozen=True)
class ScreenAnchor:
    """The resolved screen a screen-history traversal anchored on."""

    id: UUID
    identity_key: str
    label: str | None
    view_type: str | None


@dataclass(frozen=True)
class ParticipantAnchor:
    """The resolved participant a participant-topic traversal anchored on.

    ``identity_key`` is deliberately on the row's anchor: the retrieval eval's
    leg 2 compares participants by identity key, and story 3.3's answers name
    people by it.
    """

    id: UUID
    identity_key: str
    display_name: str


@dataclass(frozen=True)
class ScreenHistoryResult:
    """``screen is None`` means the anchor matched no node — an unknown
    screen, not an empty history. A resolved screen with no rows is the valid
    empty answer."""

    screen: ScreenAnchor | None
    rows: tuple[TraversalMoment, ...]


@dataclass(frozen=True)
class ParticipantTopicMomentsResult:
    """``participant is None`` means the anchor matched no node. A resolved
    participant with no rows means no attended meeting's moment text contains
    the topic — a valid empty answer."""

    participant: ParticipantAnchor | None
    rows: tuple[TraversalMoment, ...]


# --- the hand-written Cypher ----------------------------------------------

# Both statements share one shape: MATCH the anchor node by id, then OPTIONAL
# MATCH the traversal from it. Zero records means the anchor does not exist;
# one record with a NULL moment means it exists with no matching moments —
# which is how "unknown anchor" and "valid empty" stay distinguishable from a
# single round trip.
#
# Time order is explicit on every clause of the tie-break: `startedAt` is an
# ISO-8601 UTC string (lexical order is chronological), then `meeting.id`
# because distinct meetings can share a `startedAt` (day-precision drops all
# land on 00:00), then `startMs` within the meeting, then `moment.id` for
# simultaneous moments.

_SCREEN_HISTORY_CYPHER = (
    "MATCH (s:Screen {id: $screenId})"
    " OPTIONAL MATCH (s)<-[:OF_SCREEN]-(:Screenshot)<-[:SHOWS]-(mo:Moment)"
    "<-[:HAS_MOMENT]-(meeting:Meeting)"
    " RETURN s.id AS screenId, s.identityKey AS screenIdentityKey,"
    " s.label AS screenLabel, s.viewType AS screenViewType,"
    " mo.id AS momentId, meeting.id AS meetingId,"
    " meeting.title AS meetingTitle, meeting.startedAt AS meetingStartedAt,"
    " mo.startMs AS startMs, mo.endMs AS endMs,"
    " mo.screenshotId AS screenshotId, mo.sourceDeepLink AS sourceDeepLink"
    " ORDER BY meeting.startedAt, meeting.id, mo.startMs, mo.id"
)

# The WHERE belongs to the OPTIONAL MATCH, so a participant whose meetings
# never discuss the topic still yields their anchor row (with a NULL moment)
# rather than vanishing into the unknown-anchor case.
_PARTICIPANT_TOPIC_MOMENTS_CYPHER = (
    "MATCH (p:Participant {id: $participantId})"
    " OPTIONAL MATCH (p)-[:ATTENDED]->(meeting:Meeting)-[:HAS_MOMENT]->(mo:Moment)"
    " WHERE toLower(mo.text) CONTAINS toLower($topic)"
    " RETURN p.id AS anchorId, p.identityKey AS anchorIdentityKey,"
    " p.displayName AS anchorDisplayName,"
    " mo.id AS momentId, meeting.id AS meetingId,"
    " meeting.title AS meetingTitle, meeting.startedAt AS meetingStartedAt,"
    " mo.startMs AS startMs, mo.endMs AS endMs,"
    " mo.screenshotId AS screenshotId, mo.sourceDeepLink AS sourceDeepLink"
    " ORDER BY meeting.startedAt, meeting.id, mo.startMs, mo.id"
)


# --- input validation ------------------------------------------------------


def _input_uuid(value: Any, *, parameter: str) -> str:
    """Normalize one caller-supplied anchor id, or refuse by parameter name.

    An id that is not a UUID could never match a node, so sending it to the
    store would return the unknown-anchor shape for what is actually a caller
    bug. A :class:`ValueError` (mirroring the blank-topic refusal) keeps input
    errors and lookup misses distinguishable.
    """
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(
            f"{parameter} must be a UUID, got {value!r} — anchor resolution"
            " takes the Postgres-minted id; name-to-id resolution is the"
            " router's job (AD-6)"
        ) from exc


# --- record parsing --------------------------------------------------------


def _uuid_of(value: Any, *, node: str, template: str) -> UUID:
    """Parse one graph id, or refuse by name — never a partial silent result."""
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ProjectionError(
            f"the {template!r} traversal returned a {node} node whose id is"
            f" not a UUID: {value!r} — every graph node carries its"
            " Postgres-minted UUID verbatim (AD-6). Run 'rebuild --all' to"
            " regenerate the store from Postgres."
        ) from exc


def _string_of(value: Any, *, node: str, node_id: UUID, field: str, template: str) -> str:
    """A required node string property, or a named refusal when it is absent.

    Only for properties the projection always writes and a consumer keys on —
    ``identityKey`` is the retrieval eval's comparison key, so a ``None``
    slipping into it would corrupt every comparison downstream. Nullable
    display properties (``label``, ``title``) are carried as they are.
    """
    if not isinstance(value, str):
        raise ProjectionError(
            f"the {template!r} traversal returned {node} node {node_id} whose"
            f" {field} is missing or not a string: {value!r} — the projection"
            " always writes it. Run 'rebuild --all' to regenerate the store"
            " from Postgres."
        )
    return value


def _nullable_string_of(
    value: Any, *, node: str, node_id: UUID, field: str, template: str
) -> str | None:
    """A nullable graph string property, preserving ``None`` but refusing
    another value type at the typed traversal boundary."""
    if value is None:
        return None
    return _string_of(value, node=node, node_id=node_id, field=field, template=template)


def _int_of(value: Any, *, moment_id: UUID, field: str, template: str) -> int:
    """A required integer offset, or a named refusal — never a silent None."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProjectionError(
            f"the {template!r} traversal returned Moment {moment_id} whose"
            f" {field} is not an integer: {value!r} — offsets are written as"
            " integer milliseconds. Run 'rebuild --all' to regenerate the"
            " store from Postgres."
        )
    return value


def _moment_of(data: Mapping[str, Any], *, template: str) -> TraversalMoment:
    """One traversal record → one row, ids parsed, corruption named."""
    moment_id = _uuid_of(data.get("momentId"), node="Moment", template=template)
    meeting_id = _uuid_of(data.get("meetingId"), node="Meeting", template=template)
    raw_screenshot = data.get("screenshotId")
    screenshot_id = (
        _uuid_of(raw_screenshot, node="Screenshot", template=template)
        if raw_screenshot is not None
        else None
    )
    raw_started = data.get("meetingStartedAt")
    try:
        started_at = datetime.fromisoformat(raw_started)
    except (TypeError, ValueError) as exc:
        raise ProjectionError(
            f"the {template!r} traversal returned Meeting {meeting_id} with a"
            f" startedAt that is not ISO-8601: {raw_started!r} — the"
            " projection writes it and time order depends on it. Run"
            " 'rebuild --all' to regenerate the store from Postgres."
        ) from exc
    if started_at.tzinfo is None or started_at.utcoffset() != timedelta(0):
        # The lexical-order premise of the Cypher ORDER BY holds only for
        # offset-aware UTC values; a naive one means the projection did not
        # write this node.
        raise ProjectionError(
            f"the {template!r} traversal returned Meeting {meeting_id} with a"
            f" non-UTC startedAt: {raw_started!r} — the projection writes"
            " offset-aware UTC, and time order depends on it. Run"
            " 'rebuild --all' to regenerate the store from Postgres."
        )
    start_ms = _int_of(data.get("startMs"), moment_id=moment_id, field="startMs", template=template)
    end_ms = _int_of(data.get("endMs"), moment_id=moment_id, field="endMs", template=template)
    if start_ms < 0 or end_ms < start_ms:
        raise ProjectionError(
            f"the {template!r} traversal returned Moment {moment_id} with"
            f" invalid offsets startMs={start_ms}, endMs={end_ms} — offsets"
            " must be non-negative and endMs must not precede startMs. Run"
            " 'rebuild --all' to regenerate the store from Postgres."
        )
    return TraversalMoment(
        moment_id=moment_id,
        meeting_id=meeting_id,
        meeting_title=_nullable_string_of(
            data.get("meetingTitle"),
            node="Meeting",
            node_id=meeting_id,
            field="title",
            template=template,
        ),
        meeting_started_at=started_at,
        start_ms=start_ms,
        end_ms=end_ms,
        screenshot_id=screenshot_id,
        source_deep_link=_nullable_string_of(
            data.get("sourceDeepLink"),
            node="Moment",
            node_id=moment_id,
            field="sourceDeepLink",
            template=template,
        ),
    )


def _run_cypher(
    driver: neo4j.Driver,
    *,
    template: str,
    cypher: str,
    parameters: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run one template statement, wrapping the driver's failure taxonomy.

    Callers outside this package never see a raw ``neo4j`` exception: a store
    that cannot be reached is :class:`StoreUnavailableError`, a store that
    answered and refused is :class:`ProjectionError` — the same split
    ``projections/query.py`` applies to Meilisearch.
    """
    try:
        with driver.session() as session:
            return [record.data() for record in session.run(cypher, parameters)]
    except (
        neo4j.exceptions.ServiceUnavailable,
        neo4j.exceptions.SessionExpired,
        OSError,
    ) as exc:
        raise StoreUnavailableError(
            f"Neo4j became unreachable during the {template!r} traversal"
            f" ({type(exc).__name__}: {exc}) — start it with 'make infra-up'"
        ) from exc
    except (neo4j.exceptions.Neo4jError, neo4j.exceptions.DriverError) as exc:
        raise ProjectionError(
            f"Neo4j failed the {template!r} traversal"
            f" ({type(exc).__name__}: {exc})"
        ) from exc


# --- the templates ---------------------------------------------------------


def screen_history(driver: neo4j.Driver, *, screen_id: UUID | str) -> ScreenHistoryResult:
    """Every meeting and moment where the screen appeared, in time order.

    ``Screen ← Screenshot ← Moment → Meeting`` (spec-1-7's recorded shape),
    ordered by (``meeting.startedAt``, ``meeting.id``, ``moment.startMs``).
    """
    records = _run_cypher(
        driver,
        template=SCREEN_HISTORY,
        cypher=_SCREEN_HISTORY_CYPHER,
        parameters={"screenId": _input_uuid(screen_id, parameter="screen_id")},
    )
    if not records:
        return ScreenHistoryResult(screen=None, rows=())
    first = records[0]
    screen_uuid = _uuid_of(first.get("screenId"), node="Screen", template=SCREEN_HISTORY)
    anchor = ScreenAnchor(
        id=screen_uuid,
        identity_key=_string_of(
            first.get("screenIdentityKey"),
            node="Screen",
            node_id=screen_uuid,
            field="identityKey",
            template=SCREEN_HISTORY,
        ),
        label=_nullable_string_of(
            first.get("screenLabel"),
            node="Screen",
            node_id=screen_uuid,
            field="label",
            template=SCREEN_HISTORY,
        ),
        view_type=_nullable_string_of(
            first.get("screenViewType"),
            node="Screen",
            node_id=screen_uuid,
            field="viewType",
            template=SCREEN_HISTORY,
        ),
    )
    rows = tuple(
        _moment_of(record, template=SCREEN_HISTORY)
        for record in records
        if record.get("momentId") is not None
    )
    return ScreenHistoryResult(screen=anchor, rows=rows)


def participant_topic_moments(
    driver: neo4j.Driver, *, participant_id: UUID | str, topic: str
) -> ParticipantTopicMomentsResult:
    """Moments discussing the topic in meetings the participant attended.

    ``Participant → Meeting → Moment`` with a case-insensitive substring match
    over ``Moment.text`` — no Topic nodes exist until Epic 4, and spec-1-7
    records that Epic 3 templates must not assume them.
    """
    if not isinstance(topic, str):
        # `str(None)` is the non-blank string "None", so a type check has to
        # come before the blank check or a None topic would query for the
        # literal word.
        raise ValueError(f"topic must be a string, got {type(topic).__name__}")
    if not topic.strip():
        raise ValueError(
            "topic must not be blank — a blank topic would match every moment"
            " in the corpus, and a silent everything is as wrong as a silent"
            " zero"
        )
    records = _run_cypher(
        driver,
        template=PARTICIPANT_TOPIC_MOMENTS,
        cypher=_PARTICIPANT_TOPIC_MOMENTS_CYPHER,
        parameters={
            "participantId": _input_uuid(participant_id, parameter="participant_id"),
            # Stripped: `Moment.text` never carries the caller's padding, so
            # a padded topic would be a literal-whitespace match — a false
            # empty over an intent the caller plainly stated.
            "topic": topic.strip(),
        },
    )
    if not records:
        return ParticipantTopicMomentsResult(participant=None, rows=())
    first = records[0]
    participant_uuid = _uuid_of(
        first.get("anchorId"), node="Participant", template=PARTICIPANT_TOPIC_MOMENTS
    )
    anchor = ParticipantAnchor(
        id=participant_uuid,
        identity_key=_string_of(
            first.get("anchorIdentityKey"),
            node="Participant",
            node_id=participant_uuid,
            field="identityKey",
            template=PARTICIPANT_TOPIC_MOMENTS,
        ),
        display_name=_string_of(
            first.get("anchorDisplayName"),
            node="Participant",
            node_id=participant_uuid,
            field="displayName",
            template=PARTICIPANT_TOPIC_MOMENTS,
        ),
    )
    rows = tuple(
        _moment_of(record, template=PARTICIPANT_TOPIC_MOMENTS)
        for record in records
        if record.get("momentId") is not None
    )
    return ParticipantTopicMomentsResult(participant=anchor, rows=rows)


# --- the registry ----------------------------------------------------------


@dataclass(frozen=True)
class TraversalTemplate:
    """One registered traversal: its name, its keyword parameters, the
    hand-written Cypher it runs, and the function that runs it.

    Carrying the Cypher text on the registration is what makes AD-7's
    "hand-written, parameterized" reviewable and testable in one place — a
    template whose statement interpolated a value would fail the registry
    test, not just a review.
    """

    name: str
    parameters: tuple[str, ...]
    cypher: str
    run: Callable[..., ScreenHistoryResult | ParticipantTopicMomentsResult]


# The complete set of traversals story 3.3's router may classify onto. A
# mapping precisely so a later deterministic template (a name-resolver, say)
# is an addition, not a rework.
TRAVERSAL_TEMPLATES: Mapping[str, TraversalTemplate] = {
    SCREEN_HISTORY: TraversalTemplate(
        name=SCREEN_HISTORY,
        parameters=("screen_id",),
        cypher=_SCREEN_HISTORY_CYPHER,
        run=screen_history,
    ),
    PARTICIPANT_TOPIC_MOMENTS: TraversalTemplate(
        name=PARTICIPANT_TOPIC_MOMENTS,
        parameters=("participant_id", "topic"),
        cypher=_PARTICIPANT_TOPIC_MOMENTS_CYPHER,
        run=participant_topic_moments,
    ),
}


def run_template(
    driver: neo4j.Driver, name: str, **params: Any
) -> ScreenHistoryResult | ParticipantTopicMomentsResult:
    """Dispatch one traversal by its registered name — the router's only door."""
    template = TRAVERSAL_TEMPLATES.get(name)
    if template is None:
        registered = ", ".join(sorted(TRAVERSAL_TEMPLATES))
        raise ProjectionError(
            f"no traversal template named {name!r} — registered templates:"
            f" {registered}"
        )
    if set(params) != set(template.parameters):
        # Checked here rather than left to Python's TypeError: the router
        # calls through this door with model-classified parameters, and a
        # misspelled one must surface as the named taxonomy, not a raw
        # TypeError.
        declared = ", ".join(template.parameters)
        passed = ", ".join(sorted(params)) or "none"
        raise ProjectionError(
            f"the {name!r} template takes exactly ({declared}) — got ({passed})"
        )
    return template.run(driver, **params)
