"""Augmentation end to end: evidence that reached an occurrence after its ingest.

Two shapes, one door. Story 1.12: a recording recovered after a transcript-only
ingest. Story 1.13: the source side's participant graph reaching a meeting whose
drop was emitted without one.

The whole chain in one pass, over the real Postgres: intake accepts a drop that
declares `augments`, re-arms the occurrence's existing job, and the worker runs
the stages that evidence invalidates against the *same* meeting — so every
moment id minted before it arrived is still there, still keyed the same way.

The pieces are each tested elsewhere (`test_ingests.py` for the intake matrix,
`test_worker_moments.py` for moment identity, `test_worker_runner.py` for the
stage loop). This file exists because nothing else runs them *in sequence*, and
the sequence is the story: an intake refusal, a stage that does not re-run, or a
`moments` checkpoint left `done` would each break augmentation while every one
of those suites stayed green.

DB-backed and ffmpeg-backed: skips with a named reason when either is absent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import pytest
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.config import AppConfig
from meetingminer.domain.jobs import (
    AUGMENTATION_STAGES,
    PARTICIPANT_AUGMENTATION_STAGES,
    STAGE_NAMES,
    VIDEO_ONLY_STAGES,
)
from meetingminer.pipeline import runner
from meetingminer.projections.stores import MOMENTS_INDEX

from conftest import (
    DropFactory,
    FakeEmbedder,
    FakeOcr,
    REAL_PROVENANCE_PULLED,
    requires_ffmpeg,
    valid_metadata,
)
from test_worker_moments import moment_rows
from test_worker_runner import SCREEN_A, meetings, stage_statuses

pytestmark = pytest.mark.slow(reason="runs the pipeline and projects into both test twins: 7 tests, 6.0s at e5510c7")

SOURCE_ID ="occ-recovered-recording"


def _augmenting_metadata(target_source_id: str = SOURCE_ID, **overrides: Any) -> dict:
    """A version 2 drop declaring the occurrence it augments."""
    return valid_metadata(
        target_source_id,
        schemaVersion=2,
        augments={"sourceId": target_source_id},
        **overrides,
    )


def _snapshot(drop: Path) -> dict[str, tuple[int, int]]:
    return {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(drop.iterdir())
    }


def _stages_that_ran(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """The stages this pass actually executed, from the runner's own log.

    `stage.started` is emitted immediately before a stage's implementation is
    called, so this is the direct witness that a stage ran — rather than the
    final checkpoint, which cannot tell a stage that re-ran from one that was
    already `done`.
    """
    records = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    return [record["stage"] for record in records if record["event"] == "stage.started"]


def _rows(pool: ConnectionPool, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


@requires_ffmpeg
def test_a_recovered_recording_augments_the_meeting_it_already_belongs_to(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    synthetic_recording: Path,
    fake_ocr: Callable[..., FakeOcr],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The story's acceptance evidence, in one sequence."""
    # --- 1. the occurrence as it exists today: transcript only -------------
    transcript_only = make_drop(
        metadata=valid_metadata(SOURCE_ID), files=("transcript.txt",)
    )
    opened = client.post("/ingests", json={"dropPath": str(transcript_only)})
    assert opened.status_code == 201
    job_id = UUID(opened.json()["jobId"])

    assert runner.run_once(test_pool, app_config, content_root) is True
    [meeting] = meetings(test_pool, job_id)
    meeting_id = meeting["id"]
    assert meeting["has_recording"] is False

    before = moment_rows(test_pool, meeting_id)
    assert before, "the transcript-only ingest must have produced moments to preserve"
    before_by_key = {row["identity_key"]: row["id"] for row in before}
    # UX-DR11: with no recording and no screenshot, the transitional deep link
    # is what stands where the replay button would be.
    assert {row["source_deep_link"] for row in before} == {REAL_PROVENANCE_PULLED["url"]}
    assert {row["screenshot_id"] for row in before} == {None}

    # The meeting was already projected. `projection_action` answers
    # ACTION_NONE while this row is current, so it is the thing that would
    # otherwise keep the augmented bundle out of both stores.
    with test_pool.connection() as conn:
        conn.execute(
            "INSERT INTO meeting_projection (meeting_id, structural_at, embedded_at,"
            " embedder_model, embedder_dimension, chunk_max_chars, chunk_overlap_turns)"
            " VALUES (%s, now(), now(), %s, %s, %s, %s)",
            (
                meeting_id,
                app_config.settings.embedder.model,
                app_config.settings.embedder.dimension,
                app_config.settings.projections.chunking.chunk_max_chars,
                app_config.settings.projections.chunking.chunk_overlap_turns,
            ),
        )

    # --- 2. the recording turns up, hand-built as an augmenting drop -------
    # The puller emits this shape under `--re-emit` (story 1.13): a changed
    # evidence set writes a new sibling drop at `<name>-002` declaring
    # `augments`. Built by hand here so the intake contract is tested directly.
    augmenting = make_drop(metadata=_augmenting_metadata(), files=("transcript.txt",))
    (augmenting / "recording.mp4").write_bytes(synthetic_recording.read_bytes())

    original_drop = _snapshot(transcript_only)
    accepted = client.post("/ingests", json={"dropPath": str(augmenting)})

    # AC 1: 200, not a `duplicate-source` conflict — and the same job.
    assert accepted.status_code == 200
    assert accepted.json() == {"jobId": str(job_id)}
    # AC 1, second half: the already-finalized drop is never touched (AD-1).
    assert _snapshot(transcript_only) == original_drop

    # --- 3. the worker runs the recovered recording against that meeting ---
    fake_ocr(default=SCREEN_A)
    capsys.readouterr()  # discard the transcript-only pass's log
    assert runner.run_once(test_pool, app_config, content_root) is True
    ran = _stages_that_ran(capsys)

    # AC 2: exactly the augmentation set re-runs, in pipeline order, once each.
    assert ran == list(AUGMENTATION_STAGES)
    statuses = stage_statuses(test_pool, job_id)
    assert {name: statuses[name] for name in AUGMENTATION_STAGES} == {
        name: "done" for name in AUGMENTATION_STAGES
    }
    # `extract` settled `done` on the first pass and is deliberately outside
    # the augmentation set: re-extraction is a manual re-queue, never an
    # intake behavior, so approved/published artifacts survive augmentation.
    assert statuses["extract"] == "done", "augmentation must not re-arm extract"
    assert set(statuses) == set(STAGE_NAMES)

    # One job, one meeting, one id — which is what keeps every citation valid.
    assert _rows(test_pool, "SELECT count(*) FROM job")[0][0] == 1
    [augmented] = meetings(test_pool, job_id)
    assert augmented["id"] == meeting_id
    # AC 3 (the mint half): the recording is now on the meeting row.
    assert augmented["has_recording"] is True

    after = moment_rows(test_pool, meeting_id)
    after_by_key = {row["identity_key"]: row["id"] for row in after}

    # AC 3: every moment id present beforehand is still present, under its
    # original identity key. Nothing deleted, renumbered, or re-keyed.
    for identity_key, moment_id in before_by_key.items():
        assert identity_key in after_by_key, f"{identity_key} was deleted or re-keyed"
        assert after_by_key[identity_key] == moment_id
    assert set(before_by_key.values()) <= {row["id"] for row in after}

    # AC 4: screens the recovered recording shows that no transcript-derived
    # moment covers become additional `screen:`-keyed moments alongside.
    new_screen_keys = {
        key for key in after_by_key if key.startswith("screen:")
    } - set(before_by_key)
    assert new_screen_keys, "the recovered recording added no screen-anchored moment"

    # AC 5: a moment that carried the transitional deep link now names a
    # screenshot and carries no link — the data-layer form of a true replay
    # button (Epic 2 owns the UI).
    preserved = [row for row in after if row["identity_key"] in before_by_key]
    assert preserved
    for row in preserved:
        assert row["source_deep_link"] is None, "the deep link was not retired"
        assert row["screenshot_id"] is not None, "no screenshot on display"

    # The projection state row was invalidated, so the terminal projection call
    # sees ACTION_FULL and the augmented bundle reaches both stores.
    assert _rows(test_pool, "SELECT count(*) FROM meeting_projection")[0][0] == 0

    # `_clear_replaced_video_evidence` is the *reverse* direction and must not
    # have fired: the media facts, the sampled frames and the screenshots the
    # video stages just wrote are all still there.
    assert _rows(
        test_pool, "SELECT count(*) FROM meeting_media WHERE meeting_id = %s", meeting_id
    )[0][0] == 1
    assert _rows(
        test_pool, "SELECT count(*) FROM frame WHERE meeting_id = %s", meeting_id
    )[0][0] > 0
    assert _rows(
        test_pool, "SELECT count(*) FROM screenshot WHERE meeting_id = %s", meeting_id
    )[0][0] > 0
    # AD-13: the provided transcript survived the whole thing — and the STT
    # lane's row is now beside it. Asserting the *set* of kinds is the
    # outcome-level witness that `transcribe` and `align` did work: a
    # `transcribe` that never ran leaves no 'stt' row, and an `align` that never
    # re-ran would have deleted it as a source no longer merged. Both stages are
    # otherwise only evidenced by their own re-armed checkpoints.
    assert _rows(
        test_pool,
        "SELECT kind, count(*) FROM transcript_source WHERE meeting_id = %s"
        " GROUP BY kind ORDER BY kind",
        meeting_id,
    ) == [("provided-text", 1), ("stt", 1)]


@requires_ffmpeg
def test_augmentation_reuses_the_job_rather_than_opening_a_second_one(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    synthetic_recording: Path,
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """AD-14's shape, stated as a constraint rather than as a count.

    `meeting.job_id` and `meeting.source_id` are UNIQUE and
    `job_source_id_live_key` forbids a second live job per sourceId, so a
    second job could never own this meeting. This asserts the invariant those
    three constraints exist to protect held after a full augmentation pass.
    """
    transcript_only = make_drop(
        metadata=valid_metadata("occ-one-job"), files=("transcript.txt",)
    )
    job_id = UUID(
        client.post("/ingests", json={"dropPath": str(transcript_only)}).json()["jobId"]
    )
    assert runner.run_once(test_pool, app_config, content_root) is True
    [meeting] = meetings(test_pool, job_id)

    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-one-job"), files=("transcript.txt",)
    )
    (augmenting / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
    assert (
        client.post("/ingests", json={"dropPath": str(augmenting)}).status_code == 200
    )
    fake_ocr(default=SCREEN_A)
    assert runner.run_once(test_pool, app_config, content_root) is True

    jobs = _rows(test_pool, "SELECT id, source_id, drop_relative_path FROM job")
    assert [(row[0], row[1]) for row in jobs] == [(job_id, "occ-one-job")]
    assert jobs[0][2] == augmenting.name, "the job now points at the augmenting drop"
    assert _rows(test_pool, "SELECT id, job_id FROM meeting") == [
        (meeting["id"], job_id)
    ]


@requires_ffmpeg
def test_an_augmenting_drop_may_restate_the_title_without_moving_a_moment(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    synthetic_recording: Path,
    fake_ocr: Callable[..., FakeOcr],
) -> None:
    """The descriptive half of the wall-clock guard, proven through the pipeline.

    Intake refuses an augmenting drop that restates `startedAt` or
    `startedAtPrecision` (`test_ingests.py`), because `mint_meeting` rewrites
    them and `moments` re-stamps every moment's absolute `started_at` from
    `meeting.started_at`. `title` and `provenance` are deliberately *not*
    pinned: the recovered recording is the better source for both. This is the
    proof that letting them through costs nothing — the title changes, and every
    moment that existed before keeps its id and its wall-clock start.
    """
    transcript_only = make_drop(
        metadata=valid_metadata("occ-retitled-e2e"), files=("transcript.txt",)
    )
    job_id = UUID(
        client.post("/ingests", json={"dropPath": str(transcript_only)}).json()["jobId"]
    )
    assert runner.run_once(test_pool, app_config, content_root) is True
    [meeting] = meetings(test_pool, job_id)
    assert meeting["title"] == REAL_PROVENANCE_PULLED["title"]
    before = {
        row["identity_key"]: (row["id"], row["started_at"])
        for row in moment_rows(test_pool, meeting["id"])
    }
    assert before

    recovered_title = f"{REAL_PROVENANCE_PULLED['title']} (recording recovered)"
    augmenting = make_drop(
        metadata=_augmenting_metadata(
            "occ-retitled-e2e",
            provenance={**REAL_PROVENANCE_PULLED, "title": recovered_title},
        ),
        files=("transcript.txt",),
    )
    (augmenting / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
    assert (
        client.post("/ingests", json={"dropPath": str(augmenting)}).status_code == 200
    )
    fake_ocr(default=SCREEN_A)
    assert runner.run_once(test_pool, app_config, content_root) is True

    [augmented] = meetings(test_pool, job_id)
    assert augmented["id"] == meeting["id"]
    # The recovered recording's label wins — that is the point of not pinning it.
    assert augmented["title"] == recovered_title
    assert augmented["provenance"]["title"] == recovered_title
    # And the clock the guard protects is exactly where it was.
    assert augmented["started_at"] == meeting["started_at"]
    assert augmented["started_at_precision"] == meeting["started_at_precision"]

    after = {
        row["identity_key"]: (row["id"], row["started_at"])
        for row in moment_rows(test_pool, meeting["id"])
    }
    for identity_key, id_and_start in before.items():
        assert identity_key in after, f"{identity_key} was deleted or re-keyed"
        assert after[identity_key] == id_and_start, "a preserved moment moved"


# --- the last acceptance criterion, over the real stores -------------------


def _search_moment_ids(meili: Any, meeting_id: UUID) -> list[str]:
    """One meeting's moment document ids in Meilisearch, duplicates included."""
    result = meili.index(MOMENTS_INDEX).get_documents({"limit": 1000})
    return [
        dict(document)["id"]
        for document in result.results
        if dict(document)["meetingId"] == str(meeting_id)
    ]


def _graph_moment_ids(driver: Any, meeting_id: UUID) -> list[str]:
    """One meeting's Moment node ids in Neo4j, duplicates included."""
    with driver.session() as session:
        return [
            record["id"]
            for record in session.run(
                "MATCH (:Meeting {id: $id})-[:HAS_MOMENT]->(mo:Moment)"
                " RETURN mo.id AS id",
                id=str(meeting_id),
            )
        ]


def _postgres_moment_ids(pool: ConnectionPool, meeting_id: UUID) -> set[str]:
    return {str(row["id"]) for row in moment_rows(pool, meeting_id)}


@requires_ffmpeg
def test_augmentation_replaces_the_meetings_documents_in_both_stores(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    synthetic_recording: Path,
    fake_ocr: Callable[..., FakeOcr],
    projection_trigger: None,
    projection_stores: Any,
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The story's last AC with nothing hand-fabricated in between.

    `test_projections_rebuild.py` proves the projection seam in isolation —
    invalidate, ACTION_FULL, scoped delete-and-reinsert — but it writes the
    augmentation's Postgres effects itself. The rest of this file drives the
    real pipeline but runs with the projection trigger stubbed out by conftest's
    autouse `_no_incidental_projection`, so its only projection evidence is that
    the `meeting_projection` row was deleted. Neither one runs the whole chain:
    real intake, real worker, real ingest-complete trigger, real stores.

    This does. A second meeting is ingested and projected alongside, so "only
    that meeting's documents were replaced" is checked against a bystander that
    went through the same path rather than against a seeded row.

    Store-backed: `projection_stores` skips with Neo4j's or Meilisearch's own
    reason when either is down.
    """
    driver, meili = projection_stores
    monkeypatch.setattr(projections, "build_embedder", lambda *_a, **_kw: fake_embedder)

    # --- two occurrences ingested transcript-only, both projected for real ---
    bystander_drop = make_drop(
        metadata=valid_metadata("occ-store-bystander"), files=("transcript.txt",)
    )
    bystander_job = UUID(
        client.post("/ingests", json={"dropPath": str(bystander_drop)}).json()["jobId"]
    )
    transcript_only = make_drop(
        metadata=valid_metadata("occ-store-augment"), files=("transcript.txt",)
    )
    job_id = UUID(
        client.post("/ingests", json={"dropPath": str(transcript_only)}).json()["jobId"]
    )
    assert runner.run_once(test_pool, app_config, content_root) is True
    assert runner.run_once(test_pool, app_config, content_root) is True
    assert runner.run_once(test_pool, app_config, content_root) is False

    [meeting] = meetings(test_pool, job_id)
    meeting_id = meeting["id"]
    [bystander] = meetings(test_pool, bystander_job)
    bystander_id = bystander["id"]

    # The premise: the trigger really fired for both, so ACTION_NONE is what
    # would otherwise keep the augmented bundle out of the stores.
    assert _rows(test_pool, "SELECT count(*) FROM meeting_projection")[0][0] == 2
    before_ids = set(_search_moment_ids(meili, meeting_id))
    assert before_ids == _postgres_moment_ids(test_pool, meeting_id)
    assert set(_graph_moment_ids(driver, meeting_id)) == before_ids
    bystander_search_before = sorted(_search_moment_ids(meili, bystander_id))
    bystander_graph_before = sorted(_graph_moment_ids(driver, bystander_id))
    assert bystander_search_before

    # --- the recording turns up ------------------------------------------
    augmenting = make_drop(
        metadata=_augmenting_metadata("occ-store-augment"), files=("transcript.txt",)
    )
    (augmenting / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
    assert (
        client.post("/ingests", json={"dropPath": str(augmenting)}).status_code == 200
    )
    fake_ocr(default=SCREEN_A)
    assert runner.run_once(test_pool, app_config, content_root) is True

    # The invalidation was recorded and the re-projection put the state back.
    projected = _rows(
        test_pool,
        "SELECT structural_at FROM meeting_projection WHERE meeting_id = %s",
        meeting_id,
    )
    assert projected and projected[0][0] is not None

    # --- both stores now describe the augmented meeting -------------------
    after = _postgres_moment_ids(test_pool, meeting_id)
    added = {
        str(row["id"])
        for row in moment_rows(test_pool, meeting_id)
        if row["identity_key"].startswith("screen:")
    } - before_ids
    assert added, "the recovered recording added no screen-anchored moment"

    search_ids = _search_moment_ids(meili, meeting_id)
    graph_ids = _graph_moment_ids(driver, meeting_id)
    # Delete-and-reinsert, not append: every moment the meeting has is there,
    # the new screen-derived one included, and none of them twice.
    assert set(search_ids) == after
    assert set(graph_ids) == after
    assert added <= set(search_ids) and added <= set(graph_ids)
    assert len(search_ids) == len(set(search_ids)), "a moment doubled in search"
    assert len(graph_ids) == len(set(graph_ids)), "a moment doubled in the graph"
    assert before_ids <= after, "a pre-augmentation moment id vanished"

    # --- and the other meeting was never opened ---------------------------
    assert sorted(_search_moment_ids(meili, bystander_id)) == bystander_search_before
    assert sorted(_graph_moment_ids(driver, bystander_id)) == bystander_graph_before


# --- story 1.13: the participant graph reaches a meeting that has none -----


GRAPH = [
    {
        "displayName": "Goeke, Timothy",
        "mail": "timothy.goeke@contoso.com",
        "title": "Senior Director",
        "department": "OPS 454D - 102",
        "deptCode": "01.102.000283.108",
        "org": "CONTOSO",
        "guest": False,
        "unresolved": False,
        "foundIn": ["recording permissions", "transcript"],
        "spokeTurns": 2,
        "spokeWords": 9,
        "managerChain": [
            {
                "name": "Uppingham, Zephyr",
                "title": "Chief Executive Officer",
                "mail": "zephyr.uppingham@contoso.com",
            }
        ],
    },
    {
        "displayName": "Whitmore, Ellis",
        "mail": "ellis.whitmore@contoso.com",
        "title": "Analyst",
        "org": "CONTOSO",
        "guest": False,
        "unresolved": False,
        "foundIn": ["transcript"],
        "spokeTurns": 1,
        "spokeWords": 2,
    },
    {
        # An external attendee the directory could not resolve. `guest` is
        # false on all 225 real rows, so `unresolved` is what decides.
        "displayName": "Vendor, Outside",
        "org": "Unknown",
        "guest": False,
        "unresolved": True,
        "foundIn": ["recording permissions"],
    },
]


def _participants(pool: ConnectionPool, meeting_id: UUID) -> list[tuple[Any, ...]]:
    return _rows(
        pool,
        "SELECT p.identity_key, p.display_name, mp.mail, mp.title, mp.org,"
        " mp.is_external, mp.source"
        " FROM meeting_participant mp JOIN participant p ON p.id = mp.participant_id"
        " WHERE mp.meeting_id = %s ORDER BY p.display_name",
        meeting_id,
    )


def test_a_participants_only_augmenting_drop_reaches_the_stores(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Story 1.13's acceptance chain, in one sequence.

    The occurrence as the corpus holds it today: a drop with no `participants`
    key, so `align` fell back to transcript speaker labels and keyed everyone on
    how their name was typed. The puller's `--re-emit` then produces a sibling
    drop carrying the graph, and this is what has to happen when it is POSTed:
    intake accepts it (no recording involved anywhere), re-arms only `align` and
    `moments`, and the worker rewrites the roster onto mail-keyed identities
    against the same meeting id.
    """
    # --- 1. ingested from a graph-less drop -------------------------------
    without_graph = make_drop(
        metadata=valid_metadata("occ-graph-e2e"), files=("transcript.txt",)
    )
    opened = client.post("/ingests", json={"dropPath": str(without_graph)})
    assert opened.status_code == 201
    job_id = UUID(opened.json()["jobId"])
    assert runner.run_once(test_pool, app_config, content_root) is True
    [meeting] = meetings(test_pool, job_id)
    meeting_id = meeting["id"]

    before = _participants(test_pool, meeting_id)
    # Name-keyed, and nothing the transcript could not see: no mail, no title.
    assert sorted(row[0] for row in before) == [
        "name:ellis whitmore",
        "name:timothy goeke",
    ]
    assert {row[2] for row in before} == {None}, "a transcript label carries no mail"
    before_moments = moment_rows(test_pool, meeting_id)
    assert before_moments, "the transcript-only ingest must have produced moments"
    before_by_key = {row["identity_key"]: row["id"] for row in before_moments}

    # The meeting was already projected: `projection_action` answers
    # ACTION_NONE while this row is current, so it is what would otherwise keep
    # the new roster out of both stores.
    with test_pool.connection() as conn:
        conn.execute(
            "INSERT INTO meeting_projection (meeting_id, structural_at, embedded_at,"
            " embedder_model, embedder_dimension, chunk_max_chars, chunk_overlap_turns)"
            " VALUES (%s, now(), now(), %s, %s, %s, %s)",
            (
                meeting_id,
                app_config.settings.embedder.model,
                app_config.settings.embedder.dimension,
                app_config.settings.projections.chunking.chunk_max_chars,
                app_config.settings.projections.chunking.chunk_overlap_turns,
            ),
        )

    # --- 2. the re-emitted drop, carrying the graph and nothing else new ---
    with_graph = make_drop(
        metadata=_augmenting_metadata("occ-graph-e2e", participants=GRAPH),
        files=("transcript.txt",),
    )
    original_drop = _snapshot(without_graph)
    accepted = client.post("/ingests", json={"dropPath": str(with_graph)})

    # AC: accepted, and it re-arms the occurrence's existing job.
    assert accepted.status_code == 200
    assert accepted.json() == {"jobId": str(job_id)}
    assert _snapshot(without_graph) == original_drop, "the finalized drop was touched"

    # --- 3. the worker re-derives the roster against the same meeting ------
    capsys.readouterr()  # discard the first pass's log
    assert runner.run_once(test_pool, app_config, content_root) is True
    ran = _stages_that_ran(capsys)

    # Only the two stages the graph invalidates: an unchanged (here absent)
    # recording is never re-sampled, re-OCR'd or re-screened.
    assert ran == list(PARTICIPANT_AUGMENTATION_STAGES)
    statuses = stage_statuses(test_pool, job_id)
    assert {name: statuses[name] for name in PARTICIPANT_AUGMENTATION_STAGES} == {
        "align": "done",
        "moments": "done",
    }
    assert [statuses[name] for name in sorted(VIDEO_ONLY_STAGES)] == ["skipped"] * len(
        VIDEO_ONLY_STAGES
    ), "the video stages never re-ran"

    # One job, one meeting, one id.
    assert _rows(test_pool, "SELECT count(*) FROM job")[0][0] == 1
    [augmented] = meetings(test_pool, job_id)
    assert augmented["id"] == meeting_id

    after = _participants(test_pool, meeting_id)
    keys = [row[0] for row in after]
    # AC: mail-keyed where the graph supplies a mail, normalized display name
    # only where it does not.
    assert sorted(keys) == sorted(
        [
            "mail:timothy.goeke@contoso.com",
            "mail:ellis.whitmore@contoso.com",
            "name:outside vendor",
        ]
    )
    by_key = {row[0]: row for row in after}
    assert by_key["mail:timothy.goeke@contoso.com"][3] == "Senior Director"
    assert by_key["mail:timothy.goeke@contoso.com"][4] == "CONTOSO"
    # The graph entry is stored whole, so the reporting chain arrives without a
    # new column.
    source = by_key["mail:timothy.goeke@contoso.com"][6]
    assert source["managerChain"][0]["mail"] == "zephyr.uppingham@contoso.com"
    # AC: `unresolved: true` is stored as external, without consulting `guest`.
    assert by_key["name:outside vendor"][5] is True
    assert by_key["name:outside vendor"][2] is None
    assert by_key["mail:timothy.goeke@contoso.com"][5] is False

    # The moments the meeting already had are still the moments it has.
    after_by_key = {row["identity_key"]: row["id"] for row in moment_rows(test_pool, meeting_id)}
    for identity_key, moment_id in before_by_key.items():
        assert identity_key in after_by_key, f"{identity_key} was deleted or re-keyed"
        assert after_by_key[identity_key] == moment_id

    # And the projection was invalidated, so the new roster reaches the stores.
    assert _rows(test_pool, "SELECT count(*) FROM meeting_projection")[0][0] == 0


def test_an_augmenting_drop_that_adds_nothing_is_refused_end_to_end(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
) -> None:
    """A second re-emit of an already-migrated occurrence changes nothing.

    The puller short-circuits this case itself (`--re-emit` reports `current`
    and writes no drop), so the refusal is the second line of defence: a
    hand-built repeat must not re-arm stages, re-derive an identical bundle and
    cost the meeting a re-projection.
    """
    with_graph = make_drop(
        metadata=valid_metadata("occ-already-migrated", participants=GRAPH),
        files=("transcript.txt",),
    )
    job_id = UUID(
        client.post("/ingests", json={"dropPath": str(with_graph)}).json()["jobId"]
    )
    assert runner.run_once(test_pool, app_config, content_root) is True
    [meeting] = meetings(test_pool, job_id)
    before = _participants(test_pool, meeting["id"])
    assert before

    repeat = make_drop(
        metadata=_augmenting_metadata("occ-already-migrated", participants=GRAPH),
        files=("transcript.txt",),
    )
    refused = client.post("/ingests", json={"dropPath": str(repeat)})

    assert refused.status_code == 409
    assert refused.json()["type"] == "urn:meetingminer:problem:augment-adds-nothing"
    # Nothing was re-armed, and the roster is exactly where it was.
    assert stage_statuses(test_pool, job_id)["align"] == "done"
    assert _rows(
        test_pool, "SELECT drop_relative_path FROM job WHERE id = %s", job_id
    ) == [(with_graph.name,)]
    assert _participants(test_pool, meeting["id"]) == before


def test_a_merge_made_before_the_graph_arrived_survives_the_re_ingest(
    client: Any,
    test_pool: ConnectionPool,
    app_config: AppConfig,
    content_root: Path,
    make_drop: DropFactory,
) -> None:
    """AD-5: the alias lookup runs first and unconditionally.

    A human merged two identities in Epic 2, which wrote
    `participant_alias(alias_key -> surviving participant)`. When the graph
    later supplies a mail for that person, `align` computes a *different*
    identity key — and must still land on the merged row, or every re-ingest
    would quietly undo the merge.
    """
    without_graph = make_drop(
        metadata=valid_metadata("occ-merged"), files=("transcript.txt",)
    )
    job_id = UUID(
        client.post("/ingests", json={"dropPath": str(without_graph)}).json()["jobId"]
    )
    assert runner.run_once(test_pool, app_config, content_root) is True
    [meeting] = meetings(test_pool, job_id)

    # The merge, as the API records it: the mail-keyed identity the graph is
    # about to produce resolves onto the name-keyed row that already exists.
    [(survivor,)] = _rows(
        test_pool,
        "SELECT id FROM participant WHERE identity_key = %s",
        "name:timothy goeke",
    )
    with test_pool.connection() as conn:
        conn.execute(
            "INSERT INTO participant_alias (alias_key, participant_id) VALUES (%s, %s)",
            ("mail:timothy.goeke@contoso.com", survivor),
        )

    with_graph = make_drop(
        metadata=_augmenting_metadata("occ-merged", participants=GRAPH),
        files=("transcript.txt",),
    )
    assert (
        client.post("/ingests", json={"dropPath": str(with_graph)}).status_code == 200
    )
    assert runner.run_once(test_pool, app_config, content_root) is True

    # The merged row is the one this meeting references, and no second row was
    # minted for the mail key.
    assert _rows(
        test_pool,
        "SELECT count(*) FROM participant WHERE identity_key = %s",
        "mail:timothy.goeke@contoso.com",
    )[0][0] == 0
    assert survivor in {
        row[0]
        for row in _rows(
            test_pool,
            "SELECT participant_id FROM meeting_participant WHERE meeting_id = %s",
            meeting["id"],
        )
    }
