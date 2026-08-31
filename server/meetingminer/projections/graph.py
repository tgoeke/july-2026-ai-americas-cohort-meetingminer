"""The Neo4j projection: hand-written Cypher, one meeting at a time (AD-4, AD-7).

No library builds or owns graph structure (AD-7) — every node and edge below
is written by a parameterized statement in this file, which is what makes the
traversal templates Epic 3 writes testable against a shape somebody decided.

**Naming, which the architecture spine deferred to build (line 408).**

Nodes: ``Meeting``, ``Moment``, ``Screen``, ``Screenshot``, ``Participant``,
``Chunk``, ``Series``, ``Project``, ``Product``, ``Artifact``. Edges:

* ``(Meeting)-[:HAS_MOMENT]->(Moment)``
* ``(Artifact)-[:CITES]->(Moment)`` — a published artifact's evidence trail
  back to the moment that yielded it (story 4.4). ``Artifact`` nodes exist
  only for ``published`` rows — the publish gate refuses everything else —
  and they are meeting-scoped: a per-meeting pass deletes and re-creates
  them from Postgres, which is what keeps ``CITES`` intact across the
  ``DETACH DELETE`` of the ``Moment`` nodes it points at.
* ``(Moment)-[:SHOWS]->(Screenshot)`` — only when the moment names one
* ``(Screenshot)-[:OF_SCREEN]->(Screen)`` — ``Screen`` is cross-meeting, which
  is what makes screen lineage traversable
* ``(Screenshot)-[:SHOWN_DURING]->(Chunk)`` — the load-bearing join from
  `retrieval-prior-art.md` §2: *what was on screen when this was said*
* ``(Participant)-[:ATTENDED]->(Meeting)``, ``(Participant)-[:SPOKE_IN]->(Moment)``
* ``(Moment)-[:COVERS]->(Chunk)``
* ``(Meeting)-[:IN_SERIES]->(Series)``, ``(Project)-[:SCOPES]->(Meeting)``,
  ``(Product)-[:OWNS]->(Project)`` — the ERD's human-declared structure
  (story 2.5, AD-5); ``Series``/``Project``/``Product`` are cross-meeting
  nodes, upserted like ``Screen``/``Participant`` and never deleted by a
  per-meeting pass
* ``(Topic)-[:MENTIONS]->(Moment)`` — one edge per ``topic_mention`` row
  (story 10.1), carrying ``anchorMs``. ``Topic`` is meeting-scoped like
  ``Artifact``, so a per-meeting pass deletes and re-creates it, which is what
  keeps a re-extraction from leaving a superseded topic in the graph.
* ``(Thread)-[:INCLUDES]->(Topic)`` — the cross-meeting half (story 10.2).
  A ``Thread`` exists precisely because it spans meetings, so it is upserted
  like ``Screen`` and never deleted by a per-meeting pass. A meeting whose
  topics have not been threaded yet writes ``Topic`` nodes and no ``Thread``:
  extraction and thread derivation are two passes, and the second may not have
  run. Topics and threads are **navigation metadata outside the publish
  gate** — they are not artifacts, carry no lifecycle state, and so are never
  put through :func:`assert_publishable` (AD-4, as clarified for story 10.2).

Every node key is the Postgres-minted UUID, verbatim (AD-6) — never an
ordinal, never a composite the store mints. A ``Chunk`` has no Postgres row of
its own, so it keys on the UUID of its first ``transcript_segment``; see
``chunking.py`` for why that is stable.

**The asymmetry that makes per-meeting re-index safe.** Meeting-scoped labels
carry ``meetingId`` and are deleted and reinserted by it. ``Screen`` and
``Participant`` are cross-meeting and are only ever upserted: deleting a
``Screen`` would break lineage for every other meeting that showed it, and
deleting a ``Participant`` would break the cross-meeting traversal that is
half the point of the graph (AD-5). ``Series``/``Project``/``Product`` follow
the same rule: a cleared assignment loses its edge at the meeting's next
re-projection (the DETACH DELETE on ``Meeting`` takes it), and an entity node
with no remaining edges lingers until ``rebuild --all``.
"""

from __future__ import annotations

import json
from typing import Any

import neo4j

from meetingminer.projections.chunking import Chunk
from meetingminer.projections.evidence import MeetingEvidence
from meetingminer.projections.publish_gate import Artifact, assert_publishable
from meetingminer.projections.stores import MEETING_SCOPED_LABELS, ProjectionError

# Batch size for the UNWIND-driven writes. Large enough that a normal meeting
# is one round trip per statement, small enough that a pathological transcript
# does not send one statement the size of the corpus. Batches bound statement
# and round-trip size only — the *transaction* is per-meeting by design, so
# every batch of a meeting commits or rolls back together.
_BATCH = 500


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _batches(items: list[Any]) -> list[list[Any]]:
    return [items[i : i + _BATCH] for i in range(0, len(items), _BATCH)]


def delete_meeting(tx: neo4j.Transaction, meeting_id: str) -> None:
    """Remove one meeting's nodes and their edges, and nothing else.

    Scoped by ``meetingId`` on the meeting-owned labels only
    (`retrieval-prior-art.md` §3 rule 5). Cross-meeting ``Screen`` and
    ``Participant`` nodes survive; the edges *into* this meeting's nodes go
    with the nodes, because the delete is a DETACH DELETE.
    """
    for label in MEETING_SCOPED_LABELS:
        while True:
            summary = tx.run(
                f"MATCH (n:{label} {{meetingId: $meetingId}})"
                " WITH n LIMIT $batch DETACH DELETE n",
                meetingId=meeting_id,
                batch=_BATCH,
            ).consume()
            if summary.counters.nodes_deleted == 0:
                break


def _write_meeting(tx: neo4j.Transaction, evidence: MeetingEvidence) -> None:
    meeting_id = str(evidence.meeting_id)
    tx.run(
        "MERGE (m:Meeting {id: $id})"
        " SET m.meetingId = $id, m.sourceId = $sourceId, m.corpus = $corpus,"
        "     m.title = $title, m.startedAt = $startedAt,"
        "     m.startedAtPrecision = $startedAtPrecision,"
        "     m.hasRecording = $hasRecording",
        id=meeting_id,
        sourceId=evidence.source_id,
        corpus=evidence.corpus,
        title=evidence.title,
        startedAt=_iso(evidence.started_at),
        startedAtPrecision=evidence.started_at_precision,
        hasRecording=evidence.has_recording,
    ).consume()


def _write_structure(tx: neo4j.Transaction, evidence: MeetingEvidence) -> None:
    """The meeting's human-declared structure (story 2.5, AD-5).

    ``Series``/``Project``/``Product`` are cross-meeting: MERGE, never CREATE,
    never deleted per-meeting (the same rule as ``Screen``/``Participant``),
    carrying ``id`` + ``name`` and no ``meetingId``. A meeting with no
    assignments writes nothing. Runs after ``_write_meeting`` — every edge
    here matches the ``Meeting`` node it just wrote. One reconciliation on
    top of the upserts: the project's ``OWNS`` edges are made exactly its
    current product (see the inline note), because both ends are
    cross-meeting nodes no per-meeting delete ever cleans up.
    """
    structure = evidence.structure
    meeting_id = str(evidence.meeting_id)
    if structure.series_id is not None:
        tx.run(
            "MATCH (m:Meeting {id: $meetingId})"
            " MERGE (s:Series {id: $id})"
            " SET s.name = $name"
            " MERGE (m)-[:IN_SERIES]->(s)",
            meetingId=meeting_id,
            id=str(structure.series_id),
            name=structure.series_name,
        ).consume()
    if structure.project_id is not None:
        tx.run(
            "MATCH (m:Meeting {id: $meetingId})"
            " MERGE (p:Project {id: $id})"
            " SET p.name = $name"
            " MERGE (p)-[:SCOPES]->(m)",
            meetingId=meeting_id,
            id=str(structure.project_id),
            name=structure.project_name,
        ).consume()
        # OWNS connects two *cross-meeting* nodes, so no per-meeting delete
        # ever removes a stale one — under MERGE-only writing a project
        # reassigned to another product (PATCH /projects/{id}) would show two
        # owners until `rebuild --all`. Reconcile instead: make the project's
        # OWNS edges exactly its current state — delete every edge from a
        # product other than the current one, and all of them when the
        # project has none. Still inside the per-meeting transaction.
        if structure.product_id is not None:
            tx.run(
                "MATCH (p:Project {id: $projectId})"
                " MERGE (pd:Product {id: $id})"
                " SET pd.name = $name"
                " MERGE (pd)-[:OWNS]->(p)"
                " WITH p"
                " MATCH (other:Product)-[stale:OWNS]->(p)"
                " WHERE other.id <> $id"
                " DELETE stale",
                projectId=str(structure.project_id),
                id=str(structure.product_id),
                name=structure.product_name,
            ).consume()
        else:
            tx.run(
                "MATCH (:Product)-[stale:OWNS]->(:Project {id: $projectId})"
                " DELETE stale",
                projectId=str(structure.project_id),
            ).consume()


def _write_participants(tx: neo4j.Transaction, evidence: MeetingEvidence) -> None:
    if not evidence.participants:
        return
    rows = [
        {
            "id": str(p.id),
            "identityKey": p.identity_key,
            "displayName": p.display_name,
            "normalizedName": p.normalized_name,
            "isExternal": p.is_external,
            "isGuest": p.is_guest,
            "derivedFrom": p.derived_from,
            "title": p.title,
            "department": p.department,
            "org": p.org,
        }
        for p in evidence.participants
    ]
    for batch in _batches(rows):
        tx.run(
            "MATCH (m:Meeting {id: $meetingId})"
            " UNWIND $rows AS row"
            # MERGE, never CREATE: a Participant is cross-meeting and this
            # meeting is one of several that may already have written it.
            " MERGE (p:Participant {id: row.id})"
            " SET p.identityKey = row.identityKey,"
            "     p.displayName = row.displayName,"
            "     p.normalizedName = row.normalizedName"
            " MERGE (p)-[a:ATTENDED]->(m)"
            " SET a.isExternal = row.isExternal, a.isGuest = row.isGuest,"
            "     a.derivedFrom = row.derivedFrom, a.title = row.title,"
            "     a.department = row.department, a.org = row.org",
            meetingId=str(evidence.meeting_id),
            rows=batch,
        ).consume()


def _write_screens(tx: neo4j.Transaction, evidence: MeetingEvidence) -> None:
    if not evidence.screens:
        return
    rows = [
        {
            "id": str(s.id),
            "identityKey": s.identity_key,
            "label": s.label,
            "viewType": s.view_type,
        }
        for s in evidence.screens
    ]
    for batch in _batches(rows):
        tx.run(
            "UNWIND $rows AS row"
            # No meetingId on a Screen, deliberately: it belongs to every
            # meeting that showed it, which is what the lineage traversal
            # walks. It is never deleted by a per-meeting pass.
            " MERGE (s:Screen {id: row.id})"
            " SET s.identityKey = row.identityKey, s.label = row.label,"
            "     s.viewType = row.viewType",
            rows=batch,
        ).consume()


def _write_screenshots(tx: neo4j.Transaction, evidence: MeetingEvidence) -> None:
    if not evidence.screenshots:
        return
    rows = [
        {
            "id": str(s.id),
            "screenId": str(s.screen_id),
            "ordinal": s.ordinal,
            "startMs": s.start_offset_ms,
            "endMs": s.end_offset_ms,
            "path": s.path,
            "viewType": s.view_type,
            "captureCues": list(s.capture_cues),
            "classificationTags": list(s.classification_tags),
        }
        for s in evidence.screenshots
    ]
    for batch in _batches(rows):
        tx.run(
            "UNWIND $rows AS row"
            " MERGE (ss:Screenshot {id: row.id})"
            " SET ss.meetingId = $meetingId, ss.ordinal = row.ordinal,"
            "     ss.startMs = row.startMs, ss.endMs = row.endMs,"
            "     ss.path = row.path, ss.viewType = row.viewType,"
            "     ss.captureCues = row.captureCues,"
            "     ss.classificationTags = row.classificationTags"
            " WITH ss, row"
            " MATCH (s:Screen {id: row.screenId})"
            " MERGE (ss)-[:OF_SCREEN]->(s)",
            meetingId=str(evidence.meeting_id),
            rows=batch,
        ).consume()

    # A Cypher `MATCH` that finds nothing drops its row silently, so a missing
    # `Screen` node would cost an `OF_SCREEN` edge while the projection still
    # reported success. Screen lineage — *every discussion of this screen over
    # time* — is one of the two headline traversals, so an unlinked screenshot
    # is a named failure rather than a quiet gap.
    linked = tx.run(
        "MATCH (ss:Screenshot {meetingId: $meetingId})-[:OF_SCREEN]->(:Screen)"
        " RETURN count(DISTINCT ss) AS total",
        meetingId=str(evidence.meeting_id),
    ).single()["total"]
    if linked != len(rows):
        raise ProjectionError(
            f"meeting {evidence.meeting_id}: {len(rows) - linked} of {len(rows)}"
            " screenshots have no OF_SCREEN edge — the Screen nodes they name"
            " are missing from the graph and screen lineage would be broken."
            " Run 'rebuild --all' to regenerate both stores from Postgres."
        )


def _write_chunks(
    tx: neo4j.Transaction, evidence: MeetingEvidence, chunks: tuple[Chunk, ...]
) -> None:
    if not chunks:
        return
    rows = [
        {
            "id": str(c.id),
            "text": c.text,
            "startMs": c.start_ms,
            "endMs": c.end_ms,
            "speakers": list(c.speakers),
            "participantIds": [str(p) for p in c.participant_ids],
            # Neo4j node properties cannot contain maps. Keep the same
            # camelCase value-object shape as the search document as JSON so
            # each raw label stays paired with its own resolution.
            "speakerTurns": json.dumps(
                [
                    {
                        "speakerLabel": turn.speaker_label,
                        "speakerResolution": turn.speaker_resolution,
                    }
                    for turn in c.turns
                ]
            ),
            "turnCount": len(c.turns),
            "charCount": c.char_count,
        }
        for c in chunks
    ]
    for batch in _batches(rows):
        tx.run(
            "UNWIND $rows AS row"
            " MERGE (c:Chunk {id: row.id})"
            " SET c.meetingId = $meetingId, c.text = row.text,"
            "     c.startMs = row.startMs, c.endMs = row.endMs,"
            "     c.speakers = row.speakers,"
            "     c.participantIds = row.participantIds,"
            "     c.speakerTurns = row.speakerTurns,"
            "     c.turnCount = row.turnCount, c.charCount = row.charCount",
            meetingId=str(evidence.meeting_id),
            rows=batch,
        ).consume()


def _write_moments(
    tx: neo4j.Transaction, evidence: MeetingEvidence, chunks: tuple[Chunk, ...]
) -> None:
    if not evidence.moments:
        return
    # Which chunks a moment covers: they share at least one transcript
    # segment. Computed here rather than in Cypher because chunk membership is
    # a property of the packing, and the packing is a pure function that no
    # store should have to re-derive.
    chunk_ids_by_moment: dict[str, list[str]] = {}
    for chunk in chunks:
        for segment_id in chunk.segment_ids:
            moment_id = evidence.moment_by_segment.get(segment_id)
            if moment_id is None:
                continue
            bucket = chunk_ids_by_moment.setdefault(str(moment_id), [])
            if str(chunk.id) not in bucket:
                bucket.append(str(chunk.id))

    rows = [
        {
            "id": str(m.id),
            "identityKey": m.identity_key,
            "derivedFrom": m.derived_from,
            "startMs": m.start_ms,
            "endMs": m.end_ms,
            "startedAt": _iso(m.started_at),
            "startedAtPrecision": m.started_at_precision,
            "screenshotId": str(m.screenshot_id) if m.screenshot_id else None,
            "sourceDeepLink": m.source_deep_link,
            "segmentCount": m.segment_count,
            "text": m.text,
            "speakers": list(m.speakers),
            "participantIds": [str(p) for p in m.participant_ids],
            "chunkIds": chunk_ids_by_moment.get(str(m.id), []),
        }
        for m in evidence.moments
    ]
    for batch in _batches(rows):
        tx.run(
            "MATCH (meeting:Meeting {id: $meetingId})"
            " UNWIND $rows AS row"
            " MERGE (mo:Moment {id: row.id})"
            " SET mo.meetingId = $meetingId, mo.identityKey = row.identityKey,"
            "     mo.derivedFrom = row.derivedFrom, mo.startMs = row.startMs,"
            "     mo.endMs = row.endMs, mo.startedAt = row.startedAt,"
            "     mo.startedAtPrecision = row.startedAtPrecision,"
            "     mo.screenshotId = row.screenshotId,"
            "     mo.sourceDeepLink = row.sourceDeepLink,"
            "     mo.segmentCount = row.segmentCount, mo.text = row.text,"
            "     mo.speakers = row.speakers,"
            "     mo.participantIds = row.participantIds"
            " MERGE (meeting)-[:HAS_MOMENT]->(mo)",
            meetingId=str(evidence.meeting_id),
            rows=batch,
        ).consume()
        # `SHOWS` exists only when the moment names a screenshot. A
        # transcript-only meeting has none, and its `sourceDeepLink` property
        # is what stands in its place (UX-DR11) — no placeholder edge.
        tx.run(
            "UNWIND $rows AS row"
            " WITH row WHERE row.screenshotId IS NOT NULL"
            " MATCH (mo:Moment {id: row.id})"
            " MATCH (ss:Screenshot {id: row.screenshotId})"
            " MERGE (mo)-[:SHOWS]->(ss)",
            rows=batch,
        ).consume()
        tx.run(
            "UNWIND $rows AS row"
            " MATCH (mo:Moment {id: row.id})"
            " UNWIND row.chunkIds AS chunkId"
            " MATCH (c:Chunk {id: chunkId})"
            " MERGE (mo)-[:COVERS]->(c)",
            rows=batch,
        ).consume()
        tx.run(
            "UNWIND $rows AS row"
            " MATCH (mo:Moment {id: row.id})"
            " UNWIND row.participantIds AS participantId"
            " MATCH (p:Participant {id: participantId})"
            " MERGE (p)-[:SPOKE_IN]->(mo)",
            rows=batch,
        ).consume()


def _write_topics(tx: neo4j.Transaction, evidence: MeetingEvidence) -> None:
    """``Topic`` and ``Thread`` nodes with their ``MENTIONS``/``INCLUDES`` edges.

    Runs after ``_write_moments``, because every ``MENTIONS`` edge matches a
    ``Moment`` node written there. Three statements rather than one, for the
    same reason the moment writer splits: the ``Thread`` half is conditional
    on the meeting having been threaded, and folding a conditional MERGE into
    the node statement would make an un-threaded meeting silently skip its
    ``Topic`` nodes too.

    No publish gate. ``Artifact`` nodes go through :func:`assert_publishable`
    because a draft leaking into retrieval would put an unapproved claim in
    front of a reader; a topic is navigation metadata with no lifecycle state
    to gate on, so gating it would mean inventing one (AD-4, story 10.2).
    """
    if not evidence.topics:
        return
    meeting_id = str(evidence.meeting_id)
    rows = [
        {
            "id": str(topic.id),
            "name": topic.name,
            "gist": topic.gist,
            "threadId": str(topic.thread_id) if topic.thread_id is not None else None,
            "threadName": topic.thread_name,
            "mentions": [
                {"momentId": str(mention.moment_id), "anchorMs": mention.anchor_ms}
                for mention in topic.mentions
            ],
        }
        for topic in evidence.topics
    ]
    expected_edges = sum(
        len({mention["momentId"] for mention in row["mentions"]}) for row in rows
    )
    for batch in _batches(rows):
        tx.run(
            "UNWIND $rows AS row"
            " MERGE (t:Topic {id: row.id})"
            " SET t.meetingId = $meetingId, t.name = row.name, t.gist = row.gist",
            meetingId=meeting_id,
            rows=batch,
        ).consume()
        # A Thread is cross-meeting: MERGE, never CREATE, and never deleted by
        # a per-meeting pass. `threadId IS NOT NULL` is the un-threaded case —
        # the corpus-wide derivation has not run over this meeting's topics
        # yet, which is an ordering fact, not a missing node.
        tx.run(
            "UNWIND $rows AS row"
            " WITH row WHERE row.threadId IS NOT NULL"
            " MATCH (t:Topic {id: row.id})"
            " MERGE (th:Thread {id: row.threadId})"
            " SET th.name = row.threadName"
            " MERGE (th)-[:INCLUDES]->(t)",
            rows=batch,
        ).consume()
        tx.run(
            "UNWIND $rows AS row"
            " MATCH (t:Topic {id: row.id})"
            " UNWIND row.mentions AS mention"
            " MATCH (mo:Moment {id: mention.momentId})"
            " MERGE (t)-[m:MENTIONS]->(mo)"
            " SET m.anchorMs = mention.anchorMs",
            rows=batch,
        ).consume()

    # The same rule `OF_SCREEN` and `CITES` are held to: a Cypher `MATCH` that
    # finds nothing drops its row silently, so a missing `Moment` node would
    # cost a `MENTIONS` edge while the projection still reported success — and
    # a topic with no edge is navigation to nowhere, which is precisely what
    # migration 0014 refuses at the record.
    linked = tx.run(
        "MATCH (:Topic {meetingId: $meetingId})-[m:MENTIONS]->(:Moment)"
        " RETURN count(m) AS total",
        meetingId=meeting_id,
    ).single()["total"]
    if linked != expected_edges:
        raise ProjectionError(
            f"meeting {evidence.meeting_id}: {expected_edges - linked} of"
            f" {expected_edges} topic MENTIONS edges could not be written — a"
            " mentioned Moment node is missing from the graph, so the thread"
            " traversal would show a topic with no evidence. Run"
            f" 'rebuild --meeting {evidence.meeting_id}' to re-project the"
            " meeting and its topics together."
        )


def _delete_orphan_threads(tx: neo4j.Transaction) -> None:
    """Retire cross-meeting thread identities no projected topic still uses.

    A scoped meeting replacement must preserve a thread used by any other
    meeting, which is why :func:`delete_meeting` cannot delete `Thread` nodes.
    After current topics and `INCLUDES` edges are back, however, graph-wide
    orphanhood is decidable.  This is the point at which an absorbed thread's
    last edge has disappeared and its obsolete node can be removed without
    harming a survivor shared by another meeting.
    """
    tx.run(
        "MATCH (th:Thread)"
        " WHERE NOT (th)-[:INCLUDES]->(:Topic)"
        " DETACH DELETE th"
    ).consume()


def _write_shown_during(
    tx: neo4j.Transaction, evidence: MeetingEvidence, chunks: tuple[Chunk, ...]
) -> None:
    """``(Screenshot)-[:SHOWN_DURING]->(Chunk)`` by timeline overlap.

    The load-bearing edge (`retrieval-prior-art.md` §2): it answers *what was
    on screen when this was said*. Its precision is bounded by the chunk
    boundary, which is exactly why chunk size is a config value with recorded
    rationale rather than a constant.
    """
    if not evidence.screenshots or not chunks:
        return
    rows: list[dict[str, Any]] = []
    for screenshot in evidence.screenshots:
        for chunk in chunks:
            # Half-open overlap on both sides, so a chunk that merely abuts a
            # capture is not claimed as having been said over it.
            if screenshot.start_offset_ms < chunk.end_ms and chunk.start_ms < screenshot.end_offset_ms:
                rows.append({"screenshotId": str(screenshot.id), "chunkId": str(chunk.id)})
    for batch in _batches(rows):
        tx.run(
            "UNWIND $rows AS row"
            " MATCH (ss:Screenshot {id: row.screenshotId})"
            " MATCH (c:Chunk {id: row.chunkId})"
            " MERGE (ss)-[:SHOWN_DURING]->(c)",
            rows=batch,
        ).consume()


def _write_artifacts(tx: neo4j.Transaction, artifacts: tuple[Artifact, ...]) -> None:
    """``Artifact`` nodes plus their ``CITES`` edges (story 4.4).

    The gate runs per artifact even though every caller reads through
    ``publish_gate.published_artifacts`` (whose statement already filters on
    ``state = 'published'``) — defense in depth is the point of a gate (AD-4).
    The ``CITES`` edge count is verified the way ``OF_SCREEN`` is: a Cypher
    ``MATCH`` that finds no ``Moment`` drops its row silently, and an artifact
    with no evidence edge would be an uncited claim reaching retrieval (AD-6).
    """
    if not artifacts:
        return
    rows = []
    expected_edges = 0
    for artifact in artifacts:
        assert_publishable(artifact.state)
        # Deduplicated: MERGE writes one edge per distinct (artifact, moment)
        # pair, so the expectation the count below is held to must be the
        # distinct pairs too — a repeated moment id in the tuple is one edge,
        # never a false ProjectionError.
        moment_ids = list(
            dict.fromkeys(str(moment_id) for moment_id in artifact.moment_ids)
        )
        expected_edges += len(moment_ids)
        rows.append(
            {
                "id": str(artifact.id),
                "meetingId": str(artifact.meeting_id),
                "corpus": artifact.corpus,
                "kind": artifact.kind,
                "state": artifact.state,
                "title": artifact.title,
                "momentIds": moment_ids,
            }
        )
    artifact_ids = [row["id"] for row in rows]
    # Delete-then-merge, like every other re-projection in this file: a
    # republished artifact whose source moment changed must not keep the old
    # CITES edge beside the new one. Scoped to this batch's artifacts and run
    # inside the caller's transaction, so a failure below rolls it back too.
    tx.run(
        "MATCH (a:Artifact)-[c:CITES]->() WHERE a.id IN $ids DELETE c",
        ids=artifact_ids,
    ).consume()
    for batch in _batches(rows):
        tx.run(
            "UNWIND $rows AS row"
            " MERGE (a:Artifact {id: row.id})"
            " SET a.meetingId = row.meetingId, a.corpus = row.corpus,"
            "     a.kind = row.kind, a.state = row.state, a.title = row.title"
            " WITH a, row"
            " UNWIND row.momentIds AS momentId"
            " MATCH (mo:Moment {id: momentId})"
            " MERGE (a)-[:CITES]->(mo)",
            rows=batch,
        ).consume()
    linked = tx.run(
        "MATCH (a:Artifact)-[:CITES]->(:Moment)"
        " WHERE a.id IN $ids RETURN count(*) AS total",
        ids=artifact_ids,
    ).single()["total"]
    if linked != expected_edges:
        raise ProjectionError(
            f"{expected_edges - linked} of {expected_edges} artifact citation"
            " edges could not be written — a cited Moment node is missing from"
            " the graph, so the evidence trail would be broken. Run"
            f" 'rebuild --meeting {artifacts[0].meeting_id}' to re-project the"
            " meeting and its published artifacts together."
        )


def project_artifacts(driver: neo4j.Driver, artifacts: tuple[Artifact, ...]) -> None:
    """Upsert published artifacts without re-projecting their meetings.

    The approve route's path (via ``projections.project_published_artifacts``):
    the meeting's graph already stands, so this only MERGEs the ``Artifact``
    nodes and their ``CITES`` edges. One transaction, so a missing ``Moment``
    (a meeting that was never projected) rolls the whole write back and the
    caller's ``rebuild --meeting`` hint is the recovery.
    """
    if not artifacts:
        return
    with driver.session() as session:
        with session.begin_transaction() as tx:
            _write_artifacts(tx, artifacts)
            tx.commit()


def project_meeting(
    driver: neo4j.Driver,
    evidence: MeetingEvidence,
    chunks: tuple[Chunk, ...],
    artifacts: tuple[Artifact, ...] = (),
) -> None:
    """Delete and reinsert one meeting's graph. Idempotent by construction.

    Order matters: screens before screenshots (``OF_SCREEN`` matches an
    existing ``Screen``), chunks before moments (``COVERS``), screenshots
    before moments (``SHOWS``), moments before topics (``MENTIONS``).
    """
    meeting_id = str(evidence.meeting_id)
    with driver.session() as session:
        # One explicit transaction for the whole delete+write sequence: a
        # crash, a raced write, or a raised check mid-sequence rolls the
        # meeting back to its prior state instead of leaving a half-written
        # graph. The `_BATCH`-sized statements stay batched *within* it.
        with session.begin_transaction() as tx:
            delete_meeting(tx, meeting_id)
            _write_meeting(tx, evidence)
            _write_structure(tx, evidence)
            _write_participants(tx, evidence)
            _write_screens(tx, evidence)
            _write_screenshots(tx, evidence)
            _write_chunks(tx, evidence, chunks)
            _write_moments(tx, evidence, chunks)
            # Topics after moments: every `MENTIONS` edge matches a `Moment`
            # node written just above, and the count check depends on it.
            _write_topics(tx, evidence)
            _delete_orphan_threads(tx)
            _write_shown_during(tx, evidence, chunks)
            # Artifacts last: `CITES` matches the Moment nodes written above.
            # Inside the same transaction, so the meeting and its published
            # artifacts land (or roll back) together — the delete at the top
            # removed the old Artifact nodes along with everything else.
            _write_artifacts(tx, artifacts)
            tx.commit()


def unproject_meeting(driver: neo4j.Driver, meeting_id: str) -> None:
    """Remove one meeting from the graph, leaving cross-meeting nodes intact."""
    with driver.session() as session:
        # Same atomicity as `project_meeting`: the batched delete loop runs
        # to completion inside one transaction or not at all.
        with session.begin_transaction() as tx:
            delete_meeting(tx, meeting_id)
            tx.commit()


def counts(driver: neo4j.Driver) -> dict[str, int]:
    """Node counts per label plus edge counts per type, for the rebuild check.

    Used by the `rebuild` equivalence assertion — comparing these across a
    wipe-and-regenerate is how "content equivalent to the originals" is
    actually checked rather than asserted.
    """
    result: dict[str, int] = {}
    with driver.session() as session:
        for record in session.run(
            "MATCH (n) UNWIND labels(n) AS label"
            " RETURN label, count(*) AS total ORDER BY label"
        ):
            result[f"node:{record['label']}"] = record["total"]
        for record in session.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS total ORDER BY type"
        ):
            result[f"edge:{record['type']}"] = record["total"]
    return result
