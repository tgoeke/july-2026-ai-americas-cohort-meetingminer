"""Contract tests for `GET /meetings/{meeting_id}/extraction-documents` (story 12.1).

One test per clause of the story's fourth acceptance criterion, plus the
distinction the criterion's whole point rests on: a run that yielded nothing is
still served, and a run that was never retained is served as something a reader
can tell apart from an empty document.

Rows are inserted raw rather than through the `extract` stage, for the reason
`test_api_moments_feed` inserts ranking signals raw: the worker owns these
columns in production, and going through the stage here would be testing the
extraction pass rather than the route. `test_worker_extract` covers the stage.

Postgres only — no store, no api process, and no model call anywhere: the route
reads rows the worker wrote before the request arrived.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

from psycopg_pool import ConnectionPool

from projection_seed import SeededMeeting, seed_meeting

DOCUMENT_FIELDS = {
    "kind", "origin", "dropRelativePath", "sha256", "byteSize", "layout",
    "itemCount", "artifactCount", "model", "promptVersion", "promptHash",
    "documentText", "createdAt", "updatedAt",
}

# Markdown a renderer would be tempted to normalize: a table, trailing
# whitespace, a hard tab, an unclosed emphasis, and prose the parser ignored.
# Served back byte-identical or the route re-rendered the document.
AWKWARD_MARKDOWN = (
    "# Architecture summary — Data Hub Demo\n"
    "\n"
    "The tone was more settled than last week. *Nothing below captures that\n"
    "\n"
    "## 3. Decisions made\n"
    "\n"
    "| ID | Decision | Timestamp |\n"
    "|----|----------|-----------|\t\n"
    "| D1 | Standardize on SFTP | [0:10] |   \n"
)


def _seed(pool: ConnectionPool, **kwargs: Any) -> SeededMeeting:
    with pool.connection() as conn:
        return seed_meeting(conn, **kwargs)


def _document(
    pool: ConnectionPool,
    meeting_id: UUID,
    *,
    kind: str = "arch-summary",
    origin: str = "generated",
    drop_relative_path: str | None = None,
    text: str | None = AWKWARD_MARKDOWN,
    layout: str = "table",
    item_count: int = 1,
    artifact_count: int = 1,
    model: str | None = "fake-llm",
    prompt_version: int | None = 3,
    prompt_hash: str | None = "0123456789abcdef",
) -> None:
    """One `extraction_source` row, in the shape migrations 0010–0019 declare.

    ``text=None`` writes the pre-story-12.1 row: a run that completed before
    documents were retained. Migration 0019 CHECKs that a retained text's
    length equals `byte_size`, so the checksum columns are derived from the
    text here rather than passed in — a test cannot accidentally record a
    checksum that describes different bytes.
    """
    raw = b"" if text is None else text.encode("utf-8")
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO extraction_source (meeting_id, kind, origin,"
            " drop_relative_path, sha256, byte_size, layout, item_count,"
            " artifact_count, model, prompt_version, prompt_hash, document_text)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                meeting_id, kind, origin, drop_relative_path,
                hashlib.sha256(raw).hexdigest(), len(raw), layout, item_count,
                artifact_count, model, prompt_version, prompt_hash, text,
            ),
        )


def test_a_runs_document_is_served_with_what_produced_it(client, test_pool) -> None:
    """AC 4: text, kind, model, prompt hash and item count, in one read."""
    seeded = _seed(test_pool, source_id="doc-served")
    _document(test_pool, seeded.meeting_id)

    response = client.get(f"/meetings/{seeded.meeting_id}/extraction-documents")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meetingId"] == str(seeded.meeting_id)
    [document] = body["documents"]
    assert set(document) == DOCUMENT_FIELDS
    assert document["kind"] == "arch-summary"
    assert document["model"] == "fake-llm"
    assert document["promptHash"] == "0123456789abcdef"
    assert document["itemCount"] == 1
    assert document["documentText"] == AWKWARD_MARKDOWN


def test_the_document_is_served_as_the_markdown_it_is(client, test_pool) -> None:
    """AC 4: not re-rendered, so the reader sees what the parser ignored.

    Byte-identical, which is the assertion that catches a route that
    normalized whitespace, stripped a trailing space, or — worst — served the
    parse of the document in place of the document.
    """
    seeded = _seed(test_pool, source_id="doc-verbatim")
    _document(test_pool, seeded.meeting_id)

    [document] = client.get(
        f"/meetings/{seeded.meeting_id}/extraction-documents"
    ).json()["documents"]

    served = document["documentText"]
    assert served == AWKWARD_MARKDOWN
    assert served.encode("utf-8") == AWKWARD_MARKDOWN.encode("utf-8")
    # The two things a parse would have dropped are both there.
    assert "The tone was more settled" in served
    assert "|----|----------|-----------|\t\n" in served
    # And the checksum the row carries verifies against what was served, so a
    # reader can prove the served document is the document that was parsed.
    assert (
        hashlib.sha256(served.encode("utf-8")).hexdigest() == document["sha256"]
    )
    assert len(served.encode("utf-8")) == document["byteSize"]


def test_a_run_that_yielded_nothing_is_still_served(client, test_pool) -> None:
    """The case the story exists for: zero items, and text to read anyway."""
    seeded = _seed(test_pool, source_id="doc-zero")
    _document(
        test_pool,
        seeded.meeting_id,
        layout="none",
        item_count=0,
        artifact_count=0,
    )

    [document] = client.get(
        f"/meetings/{seeded.meeting_id}/extraction-documents"
    ).json()["documents"]

    assert document["itemCount"] == 0 and document["artifactCount"] == 0
    assert document["documentText"] == AWKWARD_MARKDOWN


def test_an_unretained_run_is_distinguishable_from_an_empty_document(
    client, test_pool
) -> None:
    """AD-18: `null` and `""` mean different things and stay different.

    A run from before story 12.1 has no text and needs re-extracting; a run
    whose document really was empty has been retained and needs nothing.
    Collapsing them would be a silent degradation — the reader would be told
    "nothing here" in a case where the truth is "nothing was kept".
    """
    seeded = _seed(test_pool, source_id="doc-null-vs-empty")
    _document(test_pool, seeded.meeting_id, kind="arch-summary", text=None)
    _document(test_pool, seeded.meeting_id, kind="action-items", text="")

    documents = {
        d["kind"]: d
        for d in client.get(
            f"/meetings/{seeded.meeting_id}/extraction-documents"
        ).json()["documents"]
    }

    assert documents["arch-summary"]["documentText"] is None
    assert documents["arch-summary"]["byteSize"] == 0
    assert documents["action-items"]["documentText"] == ""
    assert documents["action-items"]["byteSize"] == 0
    assert (
        documents["arch-summary"]["documentText"]
        != documents["action-items"]["documentText"]
    )


def test_every_kind_of_the_run_is_listed_in_a_stable_order(client, test_pool) -> None:
    """All four documents a run writes, ordered by kind so a client can rely on it."""
    seeded = _seed(test_pool, source_id="doc-all-kinds")
    for kind in ("topics", "arch-summary", "ranking-signals", "action-items"):
        _document(test_pool, seeded.meeting_id, kind=kind)

    body = client.get(
        f"/meetings/{seeded.meeting_id}/extraction-documents"
    ).json()

    assert [d["kind"] for d in body["documents"]] == [
        "action-items", "arch-summary", "ranking-signals", "topics",
    ]


def test_an_adopted_documents_drop_path_survives_the_copy(client, test_pool) -> None:
    """The retained text is a second copy, not a replacement for provenance."""
    seeded = _seed(test_pool, source_id="doc-adopted")
    _document(
        test_pool,
        seeded.meeting_id,
        origin="adopted",
        drop_relative_path="doc-adopted/extraction-summary.md",
        model=None,
        prompt_version=None,
        prompt_hash=None,
    )

    [document] = client.get(
        f"/meetings/{seeded.meeting_id}/extraction-documents"
    ).json()["documents"]

    assert document["origin"] == "adopted"
    assert document["dropRelativePath"] == "doc-adopted/extraction-summary.md"
    assert document["documentText"] == AWKWARD_MARKDOWN
    # An adopted document was written by the puller's summariser, whose model
    # this side never observed and must not guess at.
    assert document["model"] is None and document["promptHash"] is None


def test_a_meeting_with_no_extraction_rows_is_an_empty_list(client, test_pool) -> None:
    """Not a 404: a meeting whose extract stage has not run is a state."""
    seeded = _seed(test_pool, source_id="doc-none")

    response = client.get(f"/meetings/{seeded.meeting_id}/extraction-documents")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "meetingId": str(seeded.meeting_id), "documents": []
    }


def test_an_unknown_meeting_is_a_404_problem(client, test_pool) -> None:
    response = client.get(f"/meetings/{uuid4()}/extraction-documents")

    assert response.status_code == 404, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:meetingminer:problem:not-found"


def test_a_malformed_meeting_id_is_a_422_problem(client, test_pool) -> None:
    response = client.get("/meetings/not-a-uuid/extraction-documents")

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"


def test_an_unsettled_meeting_is_a_409(client, test_pool) -> None:
    """The same gate every meeting-scoped read passes, not a new policy."""
    seeded = _seed(
        test_pool,
        source_id="doc-unsettled",
        stage_overrides={"moments": "running"},
    )
    _document(test_pool, seeded.meeting_id)

    response = client.get(f"/meetings/{seeded.meeting_id}/extraction-documents")

    assert response.status_code == 409, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert (
        response.json()["type"] == "urn:meetingminer:problem:meeting-not-viewable"
    )
