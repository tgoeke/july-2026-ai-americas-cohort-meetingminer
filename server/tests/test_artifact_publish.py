"""Contract tests for story 4.3: the right rail's real artifact read, and the
per-moment `POST /moments/{moment_id}/approve` gesture.

Seeds through `projection_seed.seed_meeting` for the moment/meeting shape
(same as `test_api_moments.py`), plus a local `insert_artifact` raw-SQL
helper — no shared artifact factory exists yet (`test_worker_extract.py`'s
`artifact_rows` reads rows; this only needs to write them). `client`'s
`app.state.publish_root` is an isolated `tmp_path` folder per test
(`conftest.py`), so every test's exports and git repo are its own.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg_pool import ConnectionPool

from meetingminer import projections
from meetingminer.projections import publish_gate
from meetingminer.publish import export
from projection_seed import SeededMeeting, seed_meeting
from projection_seed import insert_artifact as seed_artifact


def _seed(pool: ConnectionPool, **kwargs) -> SeededMeeting:
    with pool.connection() as conn:
        return seed_meeting(conn, **kwargs)


def insert_artifact(
    pool: ConnectionPool,
    moment_id: UUID,
    meeting_id: UUID,
    kind: str,
    *,
    state: str = "extracted",
    title: str = "Move the feed to SFTP",
    body: str = "Decided during the demo.",
) -> UUID:
    # A pool adapter over the one canonical INSERT (projection_seed); this
    # file's gesture tests start from `extracted`, hence the local default.
    with pool.connection() as conn:
        return seed_artifact(
            conn, moment_id, meeting_id, kind=kind, state=state, title=title, body=body
        )


def artifact_row(pool: ConnectionPool, artifact_id: UUID) -> dict[str, Any]:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT state, approved_at, published_at, publish_relative_path,"
            " publish_commit_sha FROM artifact WHERE id = %s",
            (artifact_id,),
        ).fetchone()
    return {
        "state": row[0],
        "approved_at": row[1],
        "published_at": row[2],
        "publish_relative_path": row[3],
        "publish_commit_sha": row[4],
    }


# --- GET /moments/{moment_id} reads real artifacts --------------------------


def test_get_moment_returns_real_extracted_artifacts(client, test_pool) -> None:
    seeded = _seed(test_pool, source_id="source-artifact-read")
    insert_artifact(test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr")
    insert_artifact(
        test_pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        "action-item",
        title="Follow up with vendor",
        body="Owner: Ellis.",
    )

    response = client.get(f"/moments/{seeded.moment_ids[0]}")
    assert response.status_code == 200, response.text
    artifacts = response.json()["artifacts"]
    assert len(artifacts) == 2
    for artifact in artifacts:
        assert artifact["state"] == "extracted"
        assert artifact["publishedAt"] is None
        assert artifact["publishRelativePath"] is None
        assert artifact["publishCommitSha"] is None
    assert {a["kind"] for a in artifacts} == {"adr", "action-item"}


# --- POST /moments/{moment_id}/approve --------------------------------------


def test_approve_publishes_mixed_kinds_exports_and_commits_only_the_adr(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="source-approve-happy")
    adr_id = insert_artifact(
        test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr", title="Adopt SFTP"
    )
    action_id = insert_artifact(
        test_pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        "action-item",
        title="Notify vendor",
    )

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {a["id"] for a in body} == {str(adr_id), str(action_id)}
    for artifact in body:
        assert artifact["state"] == "published"
        assert artifact["publishedAt"] is not None
        assert artifact["publishRelativePath"] is not None

    by_id = {a["id"]: a for a in body}
    assert by_id[str(adr_id)]["publishRelativePath"] == f"adr/{adr_id}.md"
    assert by_id[str(adr_id)]["publishCommitSha"] is not None
    assert len(by_id[str(adr_id)]["publishCommitSha"]) == 40
    assert by_id[str(action_id)]["publishRelativePath"] == f"action-item/{action_id}.md"
    assert by_id[str(action_id)]["publishCommitSha"] is None

    publish_root: Path = client.app.state.publish_root
    adr_file = publish_root / "adr" / f"{adr_id}.md"
    action_file = publish_root / "action-item" / f"{action_id}.md"
    assert adr_file.read_text(encoding="utf-8") == "# Adopt SFTP\n\nDecided during the demo.\n"
    assert action_file.is_file()

    # Only the ADR is committed to git.
    log = subprocess.run(
        ["git", "log", "--name-only", "--format="],
        cwd=publish_root,
        capture_output=True,
        text=True,
    )
    assert f"adr/{adr_id}.md" in log.stdout
    assert f"action-item/{action_id}.md" not in log.stdout

    adr_row = artifact_row(test_pool, adr_id)
    assert adr_row["state"] == "published"
    assert adr_row["approved_at"] is not None
    assert adr_row["published_at"] is not None
    assert adr_row["publish_commit_sha"] is not None
    action_row = artifact_row(test_pool, action_id)
    assert action_row["state"] == "published"
    assert action_row["publish_commit_sha"] is None


def test_approve_is_409_when_nothing_is_extracted(client, test_pool) -> None:
    seeded = _seed(test_pool, source_id="source-approve-nothing")
    already_published = insert_artifact(
        test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr", state="published"
    )

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:nothing-to-approve"

    # No writes at all — the already-published row is untouched.
    row = artifact_row(test_pool, already_published)
    assert row["state"] == "published"


def test_approve_is_409_on_a_moment_with_no_artifacts_at_all(client, test_pool) -> None:
    seeded = _seed(test_pool, source_id="source-approve-empty")

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 409, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:nothing-to-approve"


def test_approve_is_404_for_an_unknown_moment(client) -> None:
    response = client.post(f"/moments/{uuid4()}/approve")
    assert response.status_code == 404, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_approve_is_409_meeting_not_viewable_when_evidence_is_unsettled(
    client, test_pool
) -> None:
    seeded = _seed(
        test_pool,
        source_id="source-approve-unsettled",
        stage_overrides={"moments": "running"},
    )
    insert_artifact(test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr")

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 409, response.text
    assert response.json()["type"] == "urn:meetingminer:problem:meeting-not-viewable"


def test_approve_retried_after_first_success_finds_nothing_left(
    client, test_pool
) -> None:
    """The idempotent-retry row of the matrix, exercised end to end: once the
    first call publishes every extracted artifact, a second call on the same
    moment has nothing left and answers 409, not a re-publish."""
    seeded = _seed(test_pool, source_id="source-approve-retry")
    insert_artifact(test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr")

    first = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert first.status_code == 200, first.text

    second = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert second.status_code == 409, second.text
    assert second.json()["type"] == "urn:meetingminer:problem:nothing-to-approve"


def test_approve_is_500_and_rolls_back_everything_when_git_commit_fails(
    client, test_pool, monkeypatch
) -> None:
    """I/O matrix: 'git binary missing/fails on an ADR' — no artifact in the
    moment becomes `published`, not even the action-item that never touches
    git, because file/git side effects run before the one Postgres UPDATE
    that commits the whole batch (Design Notes)."""
    seeded = _seed(test_pool, source_id="source-approve-git-failure")
    adr_id = insert_artifact(
        test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr", title="Adopt SFTP"
    )
    action_id = insert_artifact(
        test_pool, seeded.moment_ids[0], seeded.meeting_id, "action-item"
    )

    def _boom(*_args, **_kwargs):
        raise export.GitExportError(adr_id, "simulated git failure: disk full")

    monkeypatch.setattr(export, "publish_adr", _boom)

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 500, response.text
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:publish-git-failed"
    assert str(adr_id) in body["detail"]
    assert body["artifactId"] == str(adr_id)

    # Nothing became published — the action-item's row is untouched too,
    # even though it never calls git.
    adr_row = artifact_row(test_pool, adr_id)
    assert adr_row["state"] == "extracted"
    assert adr_row["publish_relative_path"] is None
    action_row = artifact_row(test_pool, action_id)
    assert action_row["state"] == "extracted"
    assert action_row["publish_relative_path"] is None


def test_concurrent_approvals_commit_only_their_own_adrs_and_keep_staged_files(
    client, test_pool
) -> None:
    """Different moments share one publish repo, not one Git index.

    Both requests run concurrently.  Each response must record the commit
    that touched its ADR alone, while a human/action-item staged before either
    request remains staged rather than leaking into either commit.
    """
    first = _seed(test_pool, source_id="source-concurrent-publish-first")
    second = _seed(test_pool, source_id="source-concurrent-publish-second")
    first_adr = insert_artifact(
        test_pool, first.moment_ids[0], first.meeting_id, "adr", title="First ADR"
    )
    second_adr = insert_artifact(
        test_pool, second.moment_ids[0], second.meeting_id, "adr", title="Second ADR"
    )
    publish_root: Path = client.app.state.publish_root
    export.ensure_git_repo(publish_root)
    staged_action = publish_root / "action-item" / "human-staged.md"
    staged_action.parent.mkdir()
    staged_action.write_text("do not commit me\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "--", str(staged_action.relative_to(publish_root))],
        cwd=publish_root,
        check=True,
    )

    def approve(moment_id: UUID):
        return client.post(f"/moments/{moment_id}/approve")

    with ThreadPoolExecutor(max_workers=2) as workers:
        first_response, second_response = tuple(
            workers.map(approve, (first.moment_ids[0], second.moment_ids[0]))
        )

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 200, second_response.text
    first_sha = artifact_row(test_pool, first_adr)["publish_commit_sha"]
    second_sha = artifact_row(test_pool, second_adr)["publish_commit_sha"]
    assert first_sha is not None and second_sha is not None and first_sha != second_sha
    for sha, artifact_id in ((first_sha, first_adr), (second_sha, second_adr)):
        committed = subprocess.run(
            ["git", "show", "--format=", "--name-only", sha],
            cwd=publish_root,
            capture_output=True,
            text=True,
            check=True,
        )
        assert committed.stdout.splitlines() == [f"adr/{artifact_id}.md"]
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=publish_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert staged.stdout.splitlines() == ["action-item/human-staged.md"]


def test_commit_artifact_no_op_retry_returns_the_same_sha_directly(tmp_path: Path) -> None:
    """The git-specific half of the idempotent-retry row, exercised directly
    against `export.commit_artifact` rather than through the api: a second
    commit of unchanged content must not raise, and must return the same
    sha the first commit produced (I/O matrix: 'git commit for an unchanged
    file yields "nothing to commit"')."""
    artifact_id = uuid4()
    export.ensure_git_repo(tmp_path)
    relative_path = export.export_artifact(tmp_path, artifact_id, "adr", "Title", "Body.")

    first_sha = export.commit_artifact(tmp_path, relative_path, "Title", artifact_id)
    second_sha = export.commit_artifact(tmp_path, relative_path, "Title", artifact_id)

    assert second_sha == first_sha


# --- projection on publish (story 4.4) ------------------------------------

# The approve route now projects after its commit. For every test above, that
# call is replaced with a recording no-op: those tests are about the gesture's
# Postgres/filesystem/git contract, and reaching the real stores from each of
# them would drag the shared projection stack (and its cross-worktree lock)
# into tests that assert nothing about it. The stores-backed truth lives in
# `test_approve_projects_into_both_stores`, which opts out via its marker.


@pytest.fixture(autouse=True)
def _stub_projection(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if "real_projection" in request.keywords:
        yield None
        return
    calls: list[dict[str, Any]] = []

    def record(conn: Any, config: Any, *, artifact_ids=None, meeting_id=None, log=None):
        # Observed at call time: the rows the route hands over are already
        # durably published — the projection runs after the commit.
        states: list[str] = []
        if artifact_ids:
            states = [
                row[0]
                for row in conn.execute(
                    "SELECT state FROM artifact WHERE id = ANY(%s)",
                    (list(artifact_ids),),
                ).fetchall()
            ]
        calls.append({"artifact_ids": list(artifact_ids or ()), "states": states})
        return len(artifact_ids or ())

    monkeypatch.setattr(
        projections, "project_published_artifacts", record
    )
    yield calls


def test_approve_hands_the_published_ids_to_projection_after_commit(
    client: Any, test_pool: ConnectionPool, _stub_projection: list[dict[str, Any]]
) -> None:
    seeded = _seed(test_pool, source_id="publish-projects")
    artifact_id = insert_artifact(
        test_pool, seeded.moment_ids[0], seeded.meeting_id, "action-item"
    )

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 200, response.text

    assert _stub_projection == [
        {"artifact_ids": [artifact_id], "states": ["published"]}
    ]


def test_approve_returns_200_and_logs_recovery_when_projection_fails(
    client: Any,
    test_pool: ConnectionPool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    """The gesture never fails over a store: rows stay published, the response
    is the normal 200, and the log carries the `rebuild --meeting` hint."""

    def explode(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("meilisearch fell over mid-publish")

    monkeypatch.setattr(projections, "project_published_artifacts", explode)
    seeded = _seed(test_pool, source_id="publish-projection-fails")
    artifact_id = insert_artifact(
        test_pool, seeded.moment_ids[0], seeded.meeting_id, "action-item"
    )

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 200, response.text
    assert response.json()[0]["state"] == "published"
    assert artifact_row(test_pool, artifact_id)["state"] == "published"

    out = capsys.readouterr().out
    assert "artifacts.projection.failed" in out
    assert f"rebuild --meeting {seeded.meeting_id}" in out
    assert "meilisearch fell over mid-publish" in out


@pytest.mark.real_projection
@pytest.mark.slow(reason="the one real projection into both test twins, under the projection lock: 1.6s at e5510c7")
def test_approve_projects_into_both_stores(
    client: Any,
    test_pool: ConnectionPool,
    app_config: Any,
    projection_stores: Any,
    fake_embedder: Any,
) -> None:
    """Epics AC1, end to end: the human gesture lands the artifact in the
    Meilisearch artifacts index and in Neo4j citing its source moment, through
    the projections module under both locks."""
    from meetingminer.projections.publish_gate import ARTIFACTS_INDEX

    driver, meili = projection_stores
    seeded = _seed(test_pool, source_id="publish-projects-real")
    with test_pool.connection() as conn:
        projections.project_meeting(
            conn, app_config, seeded.meeting_id, embedder_factory=lambda: fake_embedder
        )
    artifact_id = insert_artifact(
        test_pool, seeded.moment_ids[0], seeded.meeting_id, "action-item"
    )

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 200, response.text

    document = dict(meili.index(ARTIFACTS_INDEX).get_document(str(artifact_id)))
    assert document["momentIds"] == [str(seeded.moment_ids[0])]
    assert document["state"] == "published"
    with driver.session() as session:
        rows = [
            record.data()
            for record in session.run(
                "MATCH (a:Artifact {id: $id})-[:CITES]->(m:Moment)"
                " RETURN m.id AS moment",
                id=str(artifact_id),
            )
        ]
    assert rows == [{"moment": str(seeded.moment_ids[0])}]


# --- story 12.2: the meeting-scoped gesture ---------------------------------
#
# The same lifecycle, the same export, the same function — the other scope.
# `insert_artifact` takes `moment_id` positionally, so `None` seeds a
# meeting-scoped row through the one canonical INSERT; migration 0022's CHECK
# is what makes `None` legal for `summary` and illegal for the other kinds.

SUMMARY_BODY = "- Vendor feeds move to SFTP [4:23]\n- Key rotation is unowned [9:02]"


def insert_summary(
    pool: ConnectionPool,
    meeting_id: UUID,
    *,
    state: str = "extracted",
    body: str = SUMMARY_BODY,
) -> UUID:
    return insert_artifact(
        pool,
        None,
        meeting_id,
        "summary",
        state=state,
        title="Executive summary",
        body=body,
    )


def test_get_meeting_summary_returns_a_draft_without_a_citation(
    client, test_pool
) -> None:
    """A summary renders freely: this is a read of stored artifact state, not
    an answer, so "no citation, no answer" does not reach it. Served while
    still `extracted`, the same door the moment rail already opens onto
    unpublished artifacts."""
    seeded = _seed(test_pool, source_id="source-summary-get")
    summary_id = insert_summary(test_pool, seeded.meeting_id)

    response = client.get(f"/meetings/{seeded.meeting_id}/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meetingId"] == str(seeded.meeting_id)
    assert body["summary"]["id"] == str(summary_id)
    assert body["summary"]["kind"] == "summary"
    assert body["summary"]["state"] == "extracted"
    assert body["summary"]["body"] == SUMMARY_BODY
    # No moment id and no replay offset anywhere on the wire — not even null.
    # A null one would read as "citation not loaded yet" and send a consumer
    # looking for a replay link that does not exist (AD-15, AD-18).
    assert "momentId" not in body["summary"]
    assert "startMs" not in body["summary"]


def test_get_meeting_summary_is_null_when_the_meeting_has_none(
    client, test_pool
) -> None:
    """`200` with `summary: null`, not `404`. "Not extracted yet" and "no such
    meeting" are different facts and a client must not have to parse a message
    to tell them apart."""
    seeded = _seed(test_pool, source_id="source-summary-absent")
    response = client.get(f"/meetings/{seeded.meeting_id}/summary")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "meetingId": str(seeded.meeting_id),
        "summary": None,
    }


def test_get_meeting_summary_ignores_moment_anchored_artifacts(
    client, test_pool
) -> None:
    """The read is scoped by `moment_id IS NULL`, so a meeting full of ADRs and
    action items still reports no summary rather than returning one of them."""
    seeded = _seed(test_pool, source_id="source-summary-only-scope")
    insert_artifact(test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr")
    insert_artifact(test_pool, seeded.moment_ids[0], seeded.meeting_id, "action-item")

    response = client.get(f"/meetings/{seeded.meeting_id}/summary")
    assert response.status_code == 200, response.text
    assert response.json()["summary"] is None


def test_get_meeting_summary_is_404_for_an_unknown_meeting(client) -> None:
    response = client.get(f"/meetings/{uuid4()}/summary")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("not-found")


def test_get_meeting_summary_is_422_for_a_malformed_id(client) -> None:
    response = client.get("/meetings/not-a-uuid/summary")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_approving_a_meeting_scoped_artifact_publishes_it(client, test_pool) -> None:
    """A meeting-level artifact is not an exception to human-approved
    publishing (AD-6): one gesture, both transitions, exported like any other.
    It is not git-committed — that is the ADR rule, unchanged."""
    seeded = _seed(test_pool, source_id="source-summary-approve")
    summary_id = insert_summary(test_pool, seeded.meeting_id)

    response = client.post(f"/meetings/{seeded.meeting_id}/artifacts/approve")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meetingId"] == str(seeded.meeting_id)
    [artifact] = body["artifacts"]
    assert artifact["id"] == str(summary_id)
    assert artifact["state"] == "published"
    assert artifact["publishedAt"] is not None
    assert artifact["publishRelativePath"] == f"summary/{summary_id}.md"
    assert artifact["publishCommitSha"] is None

    publish_root: Path = client.app.state.publish_root
    exported = publish_root / "summary" / f"{summary_id}.md"
    assert exported.read_text(encoding="utf-8") == (
        f"# Executive summary\n\n{SUMMARY_BODY}\n"
    )
    log = subprocess.run(
        ["git", "log", "--name-only", "--format="],
        cwd=publish_root,
        capture_output=True,
        text=True,
    )
    assert f"summary/{summary_id}.md" not in log.stdout

    row = artifact_row(test_pool, summary_id)
    assert row["state"] == "published"
    assert row["approved_at"] is not None
    assert row["published_at"] is not None


def test_the_meeting_scope_approve_leaves_moment_drafts_alone(
    client, test_pool
) -> None:
    """The two gestures are scoped, not overlapping. Approving the meeting
    scope must not publish a moment's drafts behind the reader's back — the
    per-moment approval is a separate human decision."""
    seeded = _seed(test_pool, source_id="source-summary-scope-split")
    summary_id = insert_summary(test_pool, seeded.meeting_id)
    adr_id = insert_artifact(
        test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr"
    )

    response = client.post(f"/meetings/{seeded.meeting_id}/artifacts/approve")
    assert response.status_code == 200, response.text
    assert [a["id"] for a in response.json()["artifacts"]] == [str(summary_id)]
    assert artifact_row(test_pool, adr_id)["state"] == "extracted"


def test_the_per_moment_approve_leaves_the_meeting_scope_alone(
    client, test_pool
) -> None:
    """And the other way round: the per-moment path keeps working exactly as it
    did, and its `WHERE moment_id = %s` never reaches a NULL-moment row."""
    seeded = _seed(test_pool, source_id="source-summary-moment-untouched")
    summary_id = insert_summary(test_pool, seeded.meeting_id)
    adr_id = insert_artifact(test_pool, seeded.moment_ids[0], seeded.meeting_id, "adr")

    response = client.post(f"/moments/{seeded.moment_ids[0]}/approve")
    assert response.status_code == 200, response.text
    assert [a["id"] for a in response.json()] == [str(adr_id)]
    assert artifact_row(test_pool, summary_id)["state"] == "extracted"


def test_meeting_scope_approve_is_409_when_nothing_is_extracted(
    client, test_pool
) -> None:
    seeded = _seed(test_pool, source_id="source-summary-nothing")
    insert_summary(test_pool, seeded.meeting_id, state="published")

    response = client.post(f"/meetings/{seeded.meeting_id}/artifacts/approve")
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("nothing-to-approve")


def test_meeting_scope_approve_is_404_for_an_unknown_meeting(client) -> None:
    response = client.post(f"/meetings/{uuid4()}/artifacts/approve")
    assert response.status_code == 404
    assert response.json()["type"].endswith("not-found")


def test_a_published_meeting_scoped_artifact_is_never_projected(
    client, test_pool
) -> None:
    """The citation contract does not widen, asserted where it would break.

    `published_artifacts` is the one Postgres read feeding both store writers,
    and both records are citation-bearing. Before this filter it would have
    built `moment_ids=(None,)` — Meilisearch would have carried
    `momentIds: ["None"]`, a citation that cannot open the recording at the
    second, and Neo4j would have expected a `CITES` edge it could not write and
    failed `rebuild --meeting` for the whole meeting.

    Store-free: `published_artifacts` and `meeting_scoped_published` are
    Postgres reads, so this asserts the exclusion itself rather than the
    absence of a document in an index.
    """
    seeded = _seed(test_pool, source_id="source-summary-not-projected")
    summary_id = insert_summary(test_pool, seeded.meeting_id, state="published")
    adr_id = insert_artifact(
        test_pool,
        seeded.moment_ids[0],
        seeded.meeting_id,
        "adr",
        state="published",
    )

    with test_pool.connection() as conn:
        projectable = publish_gate.published_artifacts(
            conn, meeting_id=seeded.meeting_id
        )
        scoped = publish_gate.meeting_scoped_published(
            conn, [summary_id, adr_id]
        )

    assert [artifact.id for artifact in projectable] == [adr_id]
    # Never `(None,)` — the tuple is a real moment id or the row is not here.
    assert projectable[0].moment_ids == (seeded.moment_ids[0],)
    assert all(None not in artifact.moment_ids for artifact in projectable)
    assert scoped == frozenset({summary_id})


@pytest.mark.real_projection
def test_the_projection_names_why_it_skipped_a_meeting_scoped_artifact(
    client, test_pool, app_config
) -> None:
    """AD-18: the skip is deliberate, so it must not report itself as an error
    that did not happen.

    Reporting "not found in state 'published'" would be untrue — the row is
    published — and would send an operator looking for a missing row.

    Opts out of this module's projection stub because the real function's own
    reporting is the behaviour under test; the stub returns a count and logs
    nothing. It still opens **no store**: with nothing projectable the call
    takes its two locks, reads nothing, emits the skips and returns 0 before
    `_open_stores` is reached — which is also why it needs no `slow` mark.
    """
    seeded = _seed(test_pool, source_id="source-summary-skip-named")
    summary_id = insert_summary(test_pool, seeded.meeting_id, state="published")
    missing_id = uuid4()

    events: list[dict[str, Any]] = []
    with test_pool.connection() as conn:
        projected = projections.project_published_artifacts(
            conn,
            app_config,
            artifact_ids=[summary_id, missing_id],
            log=lambda event, **fields: events.append({"event": event, **fields}),
        )

    assert projected == 0
    skips = {
        event["artifact_id"]: event["reason"]
        for event in events
        if event["event"] == "projection.artifact_skipped"
    }
    assert "meeting-scoped" in skips[summary_id]
    assert "AD-6" in skips[summary_id]
    # The genuinely absent id still reports the other reason, so the two cases
    # stay distinguishable.
    assert skips[missing_id] == "not found in state 'published'"
