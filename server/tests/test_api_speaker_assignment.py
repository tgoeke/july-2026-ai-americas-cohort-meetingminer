"""Contract tests for `PUT /meetings/{meetingId}/speakers/{tag}` (story 7.3).

The write side of the speakers surface: a curator names a voice, an api-owned
`participant_alias` row is written in the `speaker:<meetingId>:<tag>` namespace
(AD-5), and the meeting's existing job is re-armed for `align → moments →
extract` only.

Two halves, deliberately split by cost. The module-level tests are the route's
contract — seeded rows, no pipeline — and stay in the fast set. `TestRerun`
carries the behavior that only a real rerun can show, and is `slow`: it
ingests a drop, runs the worker twice, and projects into the test twins.

The centre of the story is `TestRerun`'s first test. A rename must not break
anything already cited or published, so that test seeds an approved artifact,
a published artifact and a draft, renames a speaker, reruns, and asserts that
every pre-existing moment id still resolves and that only the draft moved.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID, uuid4

import pytest
from psycopg_pool import ConnectionPool

from meetingminer.config import AppConfig
from meetingminer.domain.jobs import SPEAKER_ASSIGNMENT_STAGES, STAGE_NAMES
from meetingminer.domain.speaker_assignments import (
    curated_identity_key,
    speaker_alias_key,
)
from meetingminer.pipeline import runner

from conftest import DropFactory, valid_metadata
from projection_seed import SeededMeeting, seed_meeting

# The tag a diarizer leaves behind and a curator has to name. `Speaker 8`
# is `pipeline/speakers._PLACEHOLDER_LABEL`'s shape, so `align` resolves it
# to `placeholder` with no participant until an alias says otherwise.
PLACEHOLDER_TAG = "Speaker 8"
# A source-attributed label, verbatim as `transcript_segment.speaker_label`
# stores it — comma and space included, which is also what exercises the
# route's path-parameter decoding.
NAMED_TAG = "Ironside, Indigo"

ASSIGNMENT_FIELDS = {
    "meetingId",
    "speakerLabel",
    "participantId",
    "displayName",
    "jobId",
    "rearmedStages",
}

# One transcript that carries both shapes and still cuts into three moments,
# so a rerun has artifacts to protect. Timings match
# `test_worker_extract.MULTI_MOMENT_TRANSCRIPT` so the moment boundaries are
# the ones that file already measured.
ASSIGNMENT_TRANSCRIPT = (
    "[0:02] Ironside, Indigo: We will standardize on SFTP for the vendor feed.\n"
    "[0:40] Speaker 8: I will set up the credentials this week.\n"
    "[1:30] Ironside, Indigo: Nothing else to report today.\n"
)


def _seed(pool: ConnectionPool, **kwargs: Any) -> SeededMeeting:
    with pool.connection() as conn:
        return seed_meeting(conn, **kwargs)


def _rows(pool: ConnectionPool, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def _settle_job(pool: ConnectionPool, job_id: UUID) -> None:
    """Leave the job the way a finished ingest leaves it.

    `projection_seed.seed_meeting` writes `job.status = 'running'` to model a
    job mid-extraction. The assignment route refuses to re-arm a running job
    (it would race the single worker's own final status write), so every test
    that is not *about* that refusal settles the job first.
    """
    with pool.connection() as conn:
        conn.execute("UPDATE job SET status = 'done' WHERE id = %s", (job_id,))


def _settle_rerun(pool: ConnectionPool, job_id: UUID) -> None:
    """Leave the job the way a *finished re-armed run* leaves it.

    An accepted assignment puts `align` and `moments` back to `queued`, which
    makes the meeting not viewable — correctly, and the UX design names that
    state. A second assignment therefore has to wait for the rerun, so a test
    that makes two of them settles the stages in between rather than
    pretending the first re-arm did not happen.
    """
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'done'"
            " WHERE job_id = %s AND name IN ('align', 'moments')",
            (job_id,),
        )
        conn.execute("UPDATE job SET status = 'done' WHERE id = %s", (job_id,))


def _seed_tagged_segments(
    pool: ConnectionPool, seeded: SeededMeeting, labels: Sequence[tuple[str, str]]
) -> None:
    """One `transcript_segment` per (label, resolution), in 0005's shape."""
    with pool.connection() as conn:
        source_id = conn.execute(
            "SELECT id FROM transcript_source WHERE meeting_id = %s",
            (seeded.meeting_id,),
        ).fetchone()[0]
        for ordinal, (label, resolution) in enumerate(labels, start=1):
            conn.execute(
                "INSERT INTO transcript_segment (meeting_id, ordinal, start_ms,"
                " end_ms, text, speaker_label, participant_id,"
                " speaker_resolution, label_source_id, timing_source_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, %s)",
                (
                    seeded.meeting_id,
                    ordinal,
                    ordinal * 1_000,
                    ordinal * 1_000 + 500,
                    f"segment {ordinal}",
                    label,
                    resolution,
                    source_id,
                    source_id,
                ),
            )


def _assignable_meeting(pool: ConnectionPool, source_id: str) -> SeededMeeting:
    """A settled meeting carrying one placeholder tag and one named tag."""
    seeded = _seed(pool, source_id=source_id, turns=(), has_recording=False)
    _seed_tagged_segments(
        pool, seeded, ((PLACEHOLDER_TAG, "placeholder"), (NAMED_TAG, "resolved"))
    )
    _settle_job(pool, seeded.job_id)
    return seeded


def _put(client: Any, meeting_id: Any, tag: str, body: dict[str, Any]) -> Any:
    return client.put(f"/meetings/{meeting_id}/speakers/{tag}", json=body)


def _alias_target(pool: ConnectionPool, meeting_id: UUID, tag: str) -> UUID | None:
    rows = _rows(
        pool,
        "SELECT participant_id FROM participant_alias WHERE alias_key = %s",
        speaker_alias_key(meeting_id, tag),
    )
    return rows[0][0] if rows else None


def _stage_statuses(pool: ConnectionPool, job_id: UUID) -> dict[str, str]:
    return {
        name: status
        for name, status in _rows(
            pool, "SELECT name, status FROM job_stage WHERE job_id = %s", job_id
        )
    }


class _GatedConnection:
    """Pause one route connection after its job-status read."""

    def __init__(self, conn: Any, entered: threading.Event, release: threading.Event):
        self._conn = conn
        self._entered = entered
        self._release = release

    def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
        import meetingminer.api.speakers as api_speakers

        if query == api_speakers._SPEAKER_TAG_EXISTS:
            self._entered.set()
            assert self._release.wait(timeout=10), "route gate was never released"
        return self._conn.execute(query, params, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class _GatedPool:
    def __init__(
        self,
        pool: ConnectionPool,
        entered: threading.Event,
        release: threading.Event,
    ):
        self._pool = pool
        self._entered = entered
        self._release = release

    @contextmanager
    def connection(self):
        with self._pool.connection() as conn:
            yield _GatedConnection(conn, self._entered, self._release)


# --- the alias write -------------------------------------------------------


def test_assigning_a_participant_writes_the_namespaced_alias(client, test_pool) -> None:
    """The matrix's first row: an api-owned alias row, in the AD-5 namespace."""
    seeded = _assignable_meeting(test_pool, "assign-participant")
    target = seeded.participant_ids[0]

    response = _put(
        client, seeded.meeting_id, PLACEHOLDER_TAG, {"participantId": str(target)}
    )

    assert response.status_code == 200
    assert _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG) == target
    # The key is namespaced, not bare — `mail:` and `name:` are the other two
    # spaces and a speaker assignment must never collide with either.
    assert speaker_alias_key(seeded.meeting_id, PLACEHOLDER_TAG) == (
        f"speaker:{seeded.meeting_id}:{PLACEHOLDER_TAG}"
    )


def test_the_response_carries_exactly_the_declared_fields(client, test_pool) -> None:
    seeded = _assignable_meeting(test_pool, "assign-fields")
    target = seeded.participant_ids[0]

    body = _put(
        client, seeded.meeting_id, PLACEHOLDER_TAG, {"participantId": str(target)}
    ).json()

    assert set(body) == ASSIGNMENT_FIELDS
    assert body["speakerLabel"] == PLACEHOLDER_TAG
    assert body["participantId"] == str(target)
    assert body["jobId"] == str(seeded.job_id)
    assert body["rearmedStages"] == list(SPEAKER_ASSIGNMENT_STAGES)


def test_a_new_display_name_mints_an_api_owned_participant(client, test_pool) -> None:
    """The curator typed a name no participant carries yet.

    The minted row is keyed in the api-owned `curated:` space, which cannot
    collide with a roster match key, so a curator's typed name can never
    silently merge two people (spec Change Log).
    """
    seeded = _assignable_meeting(test_pool, "assign-new-name")

    response = _put(
        client, seeded.meeting_id, PLACEHOLDER_TAG, {"displayName": "Alice Chen"}
    )

    assert response.status_code == 200
    minted = _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG)
    assert minted is not None
    assert _rows(
        test_pool,
        "SELECT identity_key, display_name FROM participant WHERE id = %s",
        minted,
    ) == [(curated_identity_key(seeded.meeting_id, PLACEHOLDER_TAG), "Alice Chen")]
    assert response.json()["displayName"] == "Alice Chen"


def test_a_minted_participant_can_still_be_merged_away(client, test_pool) -> None:
    """The split this design accepts must stay recoverable.

    `api/participants.py` reads "merged away" as "this row's identity key is
    some row's alias key". If the minted row's identity key were the key its
    own assignment is stored under, its own assignment would read as a merge
    record and `POST /participants/{id}/merge` would refuse it forever — so
    the two key spaces are separate, and this is what says so.
    """
    seeded = _assignable_meeting(test_pool, "assign-mergeable")
    _put(client, seeded.meeting_id, PLACEHOLDER_TAG, {"displayName": "Alice Chen"})
    minted = _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG)

    listed = {row["id"]: row for row in client.get("/participants").json()}
    assert listed[str(minted)]["mergedIntoParticipantId"] is None

    merged = client.post(
        f"/participants/{minted}/merge",
        json={"intoParticipantId": str(seeded.participant_ids[0])},
    )

    assert merged.status_code == 200


def test_renaming_the_same_tag_reuses_the_one_minted_row(client, test_pool) -> None:
    """A correction is an update, not a second person."""
    seeded = _assignable_meeting(test_pool, "assign-rename")
    _put(client, seeded.meeting_id, PLACEHOLDER_TAG, {"displayName": "Alice Chen"})
    first = _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG)

    _settle_rerun(test_pool, seeded.job_id)
    assert _put(
        client, seeded.meeting_id, PLACEHOLDER_TAG, {"displayName": "Alicia Chen"}
    ).status_code == 200

    assert _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG) == first
    assert _rows(
        test_pool,
        "SELECT display_name FROM participant WHERE identity_key = %s",
        curated_identity_key(seeded.meeting_id, PLACEHOLDER_TAG),
    ) == [("Alicia Chen",)]


def test_unresolved_deletes_the_alias_and_guesses_nothing(client, test_pool) -> None:
    """`unresolved` is a deletion: `participant_alias.participant_id` is NOT NULL.

    Removing the key restores `align`'s own answer, which for a placeholder
    tag is `placeholder` with no participant (AD-13).
    """
    seeded = _assignable_meeting(test_pool, "assign-unresolved")
    _put(
        client,
        seeded.meeting_id,
        PLACEHOLDER_TAG,
        {"participantId": str(seeded.participant_ids[0])},
    )
    assert _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG) is not None

    _settle_rerun(test_pool, seeded.job_id)
    response = _put(client, seeded.meeting_id, PLACEHOLDER_TAG, {"unresolved": True})

    assert response.status_code == 200
    assert _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG) is None
    assert response.json()["participantId"] is None
    assert response.json()["displayName"] is None


def test_unresolved_on_a_never_assigned_tag_is_accepted(client, test_pool) -> None:
    """Idempotent in both directions: nothing to delete is not an error."""
    seeded = _assignable_meeting(test_pool, "assign-unresolved-fresh")

    response = _put(client, seeded.meeting_id, PLACEHOLDER_TAG, {"unresolved": True})

    assert response.status_code == 200
    assert _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG) is None


def test_a_named_tag_is_assignable_through_the_same_path(client, test_pool) -> None:
    """Correcting a resolved label uses the assignment path (epic 7 context).

    The tag travels in the URL with its comma and space intact.
    """
    seeded = _assignable_meeting(test_pool, "assign-named-tag")
    target = seeded.participant_ids[1]

    response = _put(
        client, seeded.meeting_id, NAMED_TAG, {"participantId": str(target)}
    )

    assert response.status_code == 200
    assert response.json()["speakerLabel"] == NAMED_TAG
    assert _alias_target(test_pool, seeded.meeting_id, NAMED_TAG) == target


# --- the re-arm ------------------------------------------------------------


def test_acceptance_rearms_exactly_align_moments_and_extract(client, test_pool) -> None:
    """The AC names three stages, and no video stage may re-run."""
    seeded = _assignable_meeting(test_pool, "assign-rearm")
    before = _stage_statuses(test_pool, seeded.job_id)

    _put(
        client,
        seeded.meeting_id,
        PLACEHOLDER_TAG,
        {"participantId": str(seeded.participant_ids[0])},
    )

    after = _stage_statuses(test_pool, seeded.job_id)
    assert SPEAKER_ASSIGNMENT_STAGES == ("align", "moments", "extract")
    assert [name for name in STAGE_NAMES if after[name] == "queued"] == list(
        SPEAKER_ASSIGNMENT_STAGES
    )
    # Every other stage keeps the checkpoint it had — the runner resumes.
    for name in STAGE_NAMES:
        if name not in SPEAKER_ASSIGNMENT_STAGES:
            assert after[name] == before[name]
    assert _rows(test_pool, "SELECT status FROM job WHERE id = %s", seeded.job_id) == [
        ("queued",)
    ]


def test_the_rearm_does_not_disturb_the_jobs_drop_path(client, test_pool) -> None:
    """Unlike an augmenting drop, an assignment brings no new evidence."""
    seeded = _assignable_meeting(test_pool, "assign-drop-path")
    [(before,)] = _rows(
        test_pool, "SELECT drop_relative_path FROM job WHERE id = %s", seeded.job_id
    )

    _put(
        client,
        seeded.meeting_id,
        PLACEHOLDER_TAG,
        {"participantId": str(seeded.participant_ids[0])},
    )

    assert _rows(
        test_pool, "SELECT drop_relative_path FROM job WHERE id = %s", seeded.job_id
    ) == [(before,)]


# --- refusals --------------------------------------------------------------


def test_an_unknown_tag_is_refused(client, test_pool) -> None:
    """A typo must not write an alias no segment will ever match."""
    seeded = _assignable_meeting(test_pool, "assign-unknown-tag")

    response = _put(
        client,
        seeded.meeting_id,
        "SPEAKER_99",
        {"participantId": str(seeded.participant_ids[0])},
    )

    assert response.status_code == 404
    assert response.json()["type"] == "urn:meetingminer:problem:unknown-speaker-tag"
    assert response.headers["content-type"].startswith("application/problem+json")


def test_an_unknown_participant_is_refused(client, test_pool) -> None:
    seeded = _assignable_meeting(test_pool, "assign-unknown-participant")

    response = _put(
        client, seeded.meeting_id, PLACEHOLDER_TAG, {"participantId": str(uuid4())}
    )

    assert response.status_code == 404
    assert response.json()["type"] == "urn:meetingminer:problem:unknown-participant"
    assert _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG) is None


def test_an_unknown_meeting_is_refused(client) -> None:
    response = _put(client, uuid4(), PLACEHOLDER_TAG, {"unresolved": True})

    assert response.status_code == 404
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_a_meeting_whose_evidence_is_unsettled_is_refused(client, test_pool) -> None:
    """The sibling reads' 409, reused rather than restated."""
    seeded = _seed(
        test_pool,
        source_id="assign-unsettled",
        turns=(),
        has_recording=False,
        stage_overrides={"align": "queued"},
    )
    _seed_tagged_segments(test_pool, seeded, ((PLACEHOLDER_TAG, "placeholder"),))
    _settle_job(test_pool, seeded.job_id)

    response = _put(client, seeded.meeting_id, PLACEHOLDER_TAG, {"unresolved": True})

    assert response.status_code == 409
    assert response.json()["type"] == "urn:meetingminer:problem:meeting-not-viewable"


def test_a_running_job_is_refused(client, test_pool) -> None:
    """Re-arming a claimed job would race the single worker (AD-9)."""
    seeded = _seed(
        test_pool, source_id="assign-running", turns=(), has_recording=False
    )
    _seed_tagged_segments(test_pool, seeded, ((PLACEHOLDER_TAG, "placeholder"),))
    # `seed_meeting` already leaves the job `running`; asserted, not assumed.
    assert _rows(
        test_pool, "SELECT status FROM job WHERE id = %s", seeded.job_id
    ) == [("running",)]

    response = _put(client, seeded.meeting_id, PLACEHOLDER_TAG, {"unresolved": True})

    assert response.status_code == 409
    assert response.json()["type"] == "urn:meetingminer:problem:assignment-target-busy"
    assert response.json()["jobStatus"] == "running"
    assert _stage_statuses(test_pool, seeded.job_id)["align"] == "done"


def test_a_worker_cannot_claim_between_the_status_check_and_rearm(
    client, test_pool, monkeypatch
) -> None:
    """The job status check must lock the row through the route's writes."""
    seeded = _assignable_meeting(test_pool, "assign-claim-race")
    entered = threading.Event()
    release = threading.Event()
    claimed = threading.Event()
    monkeypatch.setattr(
        client.app.state, "pool", _GatedPool(test_pool, entered, release)
    )

    def claim_after_competing_rearm() -> None:
        with test_pool.connection() as conn:
            conn.execute(
                "UPDATE job SET status = 'queued' WHERE id = %s", (seeded.job_id,)
            )
            conn.commit()
            job = runner.claim_job(conn)
            assert job is not None and job.id == seeded.job_id
        claimed.set()

    with ThreadPoolExecutor(max_workers=2) as workers:
        request = workers.submit(
            _put,
            client,
            seeded.meeting_id,
            PLACEHOLDER_TAG,
            {"participantId": str(seeded.participant_ids[0])},
        )
        assert entered.wait(timeout=10), "assignment never reached the race gate"
        competitor = workers.submit(claim_after_competing_rearm)
        claimed_before_assignment_committed = claimed.wait(timeout=0.5)
        release.set()
        response = request.result(timeout=10)
        competitor.result(timeout=10)

    assert response.status_code == 200
    assert claimed_before_assignment_committed is False
    assert _rows(
        test_pool, "SELECT status FROM job WHERE id = %s", seeded.job_id
    ) == [("running",)]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="none-of-the-three"),
        pytest.param(
            {"participantId": str(uuid4()), "unresolved": True}, id="two-at-once"
        ),
        pytest.param({"displayName": "  "}, id="blank-name"),
        pytest.param({"displayName": "a\x00b"}, id="nul-in-name"),
        pytest.param({"unresolved": False}, id="unresolved-false-selects-nothing"),
    ],
)
def test_a_body_that_names_no_single_choice_is_refused(
    client, test_pool, body
) -> None:
    seeded = _assignable_meeting(test_pool, f"assign-invalid-{abs(hash(str(body)))}")

    response = _put(client, seeded.meeting_id, PLACEHOLDER_TAG, body)

    assert response.status_code == 422
    assert response.json()["type"] == "urn:meetingminer:problem:invalid-request"
    assert _alias_target(test_pool, seeded.meeting_id, PLACEHOLDER_TAG) is None


def test_a_refusal_never_rearms_the_job(client, test_pool) -> None:
    """A rejected assignment must leave the pipeline exactly where it was."""
    seeded = _assignable_meeting(test_pool, "assign-refusal-no-rearm")
    before = _stage_statuses(test_pool, seeded.job_id)

    assert _put(client, seeded.meeting_id, "SPEAKER_99", {"unresolved": True}).status_code == 404

    assert _stage_statuses(test_pool, seeded.job_id) == before


def test_the_read_route_still_serves_the_meeting(client, test_pool) -> None:
    """7.2's one-shape criterion is untouched by adding the write side."""
    seeded = _assignable_meeting(test_pool, "assign-read-unaffected")

    body = client.get(f"/meetings/{seeded.meeting_id}/speakers").json()

    assert {row["speakerLabel"] for row in body["speakers"]} == {
        PLACEHOLDER_TAG,
        NAMED_TAG,
    }


# --- what only a real rerun can show ---------------------------------------


class TestRerun:
    """The assignment carried through `align → moments → extract`."""

    pytestmark = pytest.mark.slow(
        reason="ingests a drop and runs the worker twice, projecting into both test twins: 5 tests, ~9s"
    )

    @staticmethod
    def _ingest(
        client: Any,
        test_pool: ConnectionPool,
        app_config: AppConfig,
        content_root: Path,
        make_drop: DropFactory,
        source_id: str,
    ) -> tuple[UUID, UUID]:
        """Ingest the assignment transcript and run it to completion."""
        drop = make_drop(
            metadata=valid_metadata(source_id), files=("transcript.txt",)
        )
        (drop / "transcript.txt").write_text(ASSIGNMENT_TRANSCRIPT, encoding="utf-8")
        job_id = UUID(
            client.post("/ingests", json={"dropPath": str(drop)}).json()["jobId"]
        )
        assert runner.run_once(test_pool, app_config, content_root) is True
        [(meeting_id,)] = _rows(
            test_pool, "SELECT id FROM meeting WHERE job_id = %s", job_id
        )
        return job_id, meeting_id

    @staticmethod
    def _moments(pool: ConnectionPool, meeting_id: UUID) -> list[tuple[Any, ...]]:
        return _rows(
            pool,
            "SELECT id, identity_key, start_ms FROM moment WHERE meeting_id = %s"
            " ORDER BY start_ms",
            meeting_id,
        )

    @staticmethod
    def _segments(pool: ConnectionPool, meeting_id: UUID) -> list[tuple[Any, ...]]:
        return _rows(
            pool,
            "SELECT speaker_label, speaker_resolution, participant_id"
            " FROM transcript_segment WHERE meeting_id = %s ORDER BY ordinal",
            meeting_id,
        )

    def test_a_rename_breaks_no_moment_id_citation_or_published_artifact(
        self, client, test_pool, app_config, content_root, make_drop
    ) -> None:
        """The clause that matters most, pinned.

        Someone corrects a speaker's name months after a meeting was
        published. Every pre-existing moment id must still resolve, the
        approved and published artifacts must be untouched, and extraction
        must replace drafts only.
        """
        _job_id, meeting_id = self._ingest(
            client, test_pool, app_config, content_root, make_drop, "assign-citation"
        )
        moments_before = self._moments(test_pool, meeting_id)
        assert len(moments_before) >= 3, "need distinct moments to protect"

        # The human record this meeting already carries: one approved
        # artifact with a sibling draft, one published artifact, and one
        # plain draft on a moment nobody has acted on.
        with test_pool.connection() as conn:
            for moment_id, state, title in (
                (moments_before[0][0], "approved", "approved adr"),
                (moments_before[0][0], "extracted", "sibling of an approved moment"),
                (moments_before[1][0], "published", "published adr"),
                (moments_before[2][0], "extracted", "a plain draft"),
            ):
                conn.execute(
                    "INSERT INTO artifact (moment_id, meeting_id, kind, state,"
                    " title, body) VALUES (%s, %s, 'adr', %s, %s, 'body')",
                    (moment_id, meeting_id, state, title),
                )
        artifacts_before = _rows(
            test_pool,
            "SELECT id, moment_id, state, title, body FROM artifact"
            " WHERE meeting_id = %s ORDER BY id",
            meeting_id,
        )
        protected = [row for row in artifacts_before if row[2] != "extracted"]
        sibling = [
            row
            for row in artifacts_before
            if row[2] == "extracted" and row[1] == moments_before[0][0]
        ]
        plain_draft = [
            row
            for row in artifacts_before
            if row[2] == "extracted" and row[1] == moments_before[2][0]
        ]
        assert len(protected) == 2 and len(sibling) == 1 and len(plain_draft) == 1

        response = _put(
            client, meeting_id, PLACEHOLDER_TAG, {"displayName": "Alice Chen"}
        )
        assert response.status_code == 200
        assert runner.run_once(test_pool, app_config, content_root) is True

        # 1. Every pre-existing moment id still resolves, unmoved and unrekeyed.
        assert self._moments(test_pool, meeting_id) == moments_before

        # 2. The approved and published rows are exactly as the human left
        #    them, and so is the draft sitting beside the approved one.
        after = {
            row[0]: row
            for row in _rows(
                test_pool,
                "SELECT id, moment_id, state, title, body FROM artifact"
                " WHERE meeting_id = %s",
                meeting_id,
            )
        }
        for row in protected + sibling:
            assert after.get(row[0]) == row, f"artifact {row[3]!r} was disturbed"

        # 3. Extraction replaced drafts only: the one draft on a moment no
        #    human had acted on is the only row that went.
        assert plain_draft[0][0] not in after

        # 4. And the rename actually took effect, or none of the above is a test.
        assert ("Speaker 8", "resolved") in {
            (label, resolution)
            for label, resolution, _ in self._segments(test_pool, meeting_id)
        }

    def test_the_assignment_reattributes_the_transcript(
        self, client, test_pool, app_config, content_root, make_drop
    ) -> None:
        """The tag is kept verbatim; only the attribution changes."""
        _job_id, meeting_id = self._ingest(
            client, test_pool, app_config, content_root, make_drop, "assign-reattribute"
        )
        before = self._segments(test_pool, meeting_id)
        assert (PLACEHOLDER_TAG, "placeholder", None) in before

        _put(client, meeting_id, PLACEHOLDER_TAG, {"displayName": "Alice Chen"})
        assert runner.run_once(test_pool, app_config, content_root) is True

        after = self._segments(test_pool, meeting_id)
        assigned = [row for row in after if row[0] == PLACEHOLDER_TAG]
        assert assigned, "the tag must survive the assignment verbatim"
        for label, resolution, participant_id in assigned:
            assert label == PLACEHOLDER_TAG
            assert resolution == "resolved"
            assert participant_id is not None

    def test_unresolved_returns_the_tag_to_placeholder(
        self, client, test_pool, app_config, content_root, make_drop
    ) -> None:
        """The third AC: the tag is kept and no name is guessed."""
        _job_id, meeting_id = self._ingest(
            client, test_pool, app_config, content_root, make_drop, "assign-back"
        )
        _put(client, meeting_id, PLACEHOLDER_TAG, {"displayName": "Alice Chen"})
        assert runner.run_once(test_pool, app_config, content_root) is True

        _put(client, meeting_id, PLACEHOLDER_TAG, {"unresolved": True})
        assert runner.run_once(test_pool, app_config, content_root) is True

        assigned = [
            row for row in self._segments(test_pool, meeting_id) if row[0] == PLACEHOLDER_TAG
        ]
        assert assigned
        for label, resolution, participant_id in assigned:
            assert (label, resolution, participant_id) == (
                PLACEHOLDER_TAG,
                "placeholder",
                None,
            )

    def test_an_assigned_participant_becomes_a_meeting_participant(
        self, client, test_pool, app_config, content_root, make_drop
    ) -> None:
        """Without attendance the graph silently drops the `SPOKE_IN` edge.

        `projections/graph.py` MATCHes the `Participant` node built from
        `meeting_participant`, so an assignment that wrote no attendance row
        would re-attribute the transcript and leave the graph unchanged.
        """
        _job_id, meeting_id = self._ingest(
            client, test_pool, app_config, content_root, make_drop, "assign-attendance"
        )
        _put(client, meeting_id, PLACEHOLDER_TAG, {"displayName": "Alice Chen"})
        assert runner.run_once(test_pool, app_config, content_root) is True

        assigned = _alias_target(test_pool, meeting_id, PLACEHOLDER_TAG)
        attendance = {
            row[0]
            for row in _rows(
                test_pool,
                "SELECT participant_id FROM meeting_participant WHERE meeting_id = %s",
                meeting_id,
            )
        }
        assert assigned in attendance

    def test_an_assignment_onto_a_merged_away_participant_follows_the_merge(
        self, client, test_pool, app_config, content_root, make_drop
    ) -> None:
        """AD-5: the alias lookup runs first and unconditionally.

        A curator assigns a tag, then merges that person into someone else.
        The transcript must name the survivor, or the merge would be undone
        for this meeting on every rerun.
        """
        _job_id, meeting_id = self._ingest(
            client, test_pool, app_config, content_root, make_drop, "assign-merged"
        )
        _put(client, meeting_id, PLACEHOLDER_TAG, {"displayName": "Alice Chen"})
        absorbed = _alias_target(test_pool, meeting_id, PLACEHOLDER_TAG)
        [(survivor,)] = _rows(
            test_pool,
            "SELECT id FROM participant WHERE id <> %s ORDER BY created_at LIMIT 1",
            absorbed,
        )
        [(absorbed_key,)] = _rows(
            test_pool, "SELECT identity_key FROM participant WHERE id = %s", absorbed
        )
        with test_pool.connection() as conn:
            conn.execute(
                "INSERT INTO participant_alias (alias_key, participant_id)"
                " VALUES (%s, %s)",
                (absorbed_key, survivor),
            )

        assert runner.run_once(test_pool, app_config, content_root) is True

        assigned = [
            row for row in self._segments(test_pool, meeting_id) if row[0] == PLACEHOLDER_TAG
        ]
        assert assigned
        for _label, _resolution, participant_id in assigned:
            assert participant_id == survivor

    def test_correcting_a_source_named_tag_moves_transcript_provenance(
        self, client, test_pool, app_config, content_root, make_drop
    ) -> None:
        """The corrected person, not the source's old match, spoke in transcript.

        A source participant remains an attendee after a correction, but its
        attendance provenance must return to ``drop-graph``. The participant
        named by the human assignment is the row derived from the transcript.
        """
        drop = make_drop(
            metadata=valid_metadata(
                "assign-source-correction",
                participants=[
                    {
                        "displayName": NAMED_TAG,
                        "mail": "indigo.ironside@example.com",
                    }
                ],
            ),
            files=("transcript.txt",),
        )
        (drop / "transcript.txt").write_text(
            ASSIGNMENT_TRANSCRIPT, encoding="utf-8"
        )
        job_id = UUID(
            client.post("/ingests", json={"dropPath": str(drop)}).json()["jobId"]
        )
        assert runner.run_once(test_pool, app_config, content_root) is True
        [(meeting_id,)] = _rows(
            test_pool, "SELECT id FROM meeting WHERE job_id = %s", job_id
        )
        [(source_participant,)] = _rows(
            test_pool,
            "SELECT id FROM participant WHERE identity_key = %s",
            "mail:indigo.ironside@example.com",
        )

        response = _put(
            client, meeting_id, NAMED_TAG, {"displayName": "Corrected Speaker"}
        )
        assert response.status_code == 200
        corrected_participant = UUID(response.json()["participantId"])
        assert runner.run_once(test_pool, app_config, content_root) is True

        provenance = dict(
            _rows(
                test_pool,
                "SELECT participant_id, derived_from FROM meeting_participant"
                " WHERE meeting_id = %s",
                meeting_id,
            )
        )
        assert provenance[source_participant] == "drop-graph"
        assert provenance[corrected_participant] == "transcript"
