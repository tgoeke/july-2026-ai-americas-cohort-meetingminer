"""Eval-subject selection over synthetic `GET /meetings` payloads.

Offline by construction: `select_subjects` is a pure function over rows, so
the matrix runs with no api, no store and no ingestion. `fetch_meetings` — the
one network call in the harness — is exercised here too, over an
`httpx.MockTransport`, so the request path and the response envelope are
pinned without anything listening on a port.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from evals.harness.groundtruth import Manifest
from evals.harness.subjects import (
    CorpusMismatch,
    CorpusReadError,
    Subject,
    UnmatchedManifest,
    fetch_meetings,
    select_subjects,
)
from evals.tests.conftest import meeting_of, valid_slide_deck, valid_ui_demo


def manifest_for(source_id: str, **overrides: Any) -> Manifest:
    data = valid_ui_demo(**overrides)
    data["meeting"] = meeting_of(data, source_id=source_id)
    return Manifest(data=data)


def row(source_id: str, corpus: str = "scripted", **overrides: Any) -> dict[str, Any]:
    """One `GET /meetings` item, camelCased exactly as the api returns it."""
    item: dict[str, Any] = {
        "jobId": f"job-{source_id}",
        "meetingId": f"meeting-{source_id}",
        "title": "Scripted UI Demo",
        "sourceId": source_id,
        "corpus": corpus,
        "status": "succeeded",
        "stages": [],
        "viewable": True,
    }
    item.update(overrides)
    return item


def test_a_scripted_row_matching_a_manifest_becomes_a_subject() -> None:
    manifest = manifest_for("drive-item-1")
    selection = select_subjects([row("drive-item-1")], [manifest])
    assert len(selection.subjects) == 1
    subject = selection.subjects[0]
    assert isinstance(subject, Subject)
    assert subject.manifest is manifest
    assert subject.source_id == "drive-item-1"
    assert subject.meeting_id == "meeting-drive-item-1"
    assert subject.job_id == "job-drive-item-1"
    assert subject.title == "Scripted UI Demo"
    assert subject.status == "succeeded"
    assert subject.viewable is True
    assert selection.unmatched == ()
    assert selection.corpus_mismatches == ()


def test_a_subject_carries_the_row_as_the_api_reported_it() -> None:
    """Not defaulted, not re-derived.

    `viewable` is the api's own `evidence_complete` verdict and `status` is
    what separates a leftover failed job from the re-ingest that replaced it.
    A check that assumed either would be asserting against its own guess.
    """
    manifest = manifest_for("drive-item-1")
    rows = [
        row(
            "drive-item-1",
            title="Half-ingested Demo",
            status="running",
            viewable=False,
            meetingId=None,
        )
    ]
    subject = select_subjects(rows, [manifest]).subjects[0]
    assert subject.title == "Half-ingested Demo"
    assert subject.status == "running"
    assert subject.viewable is False
    assert subject.meeting_id is None


def test_real_rows_are_dropped_from_a_mixed_corpus() -> None:
    """The demo corpus is ingested alongside the scripted meetings."""
    manifest = manifest_for("drive-item-1")
    rows = [
        row("drive-item-1"),
        row("northwind-weekly", corpus="real"),
        row("vendor-portal-kickoff", corpus="real"),
    ]
    selection = select_subjects(rows, [manifest])
    assert [subject.source_id for subject in selection.subjects] == ["drive-item-1"]
    assert selection.corpus_mismatches == ()


def test_a_manifest_naming_a_real_meeting_is_a_corpus_mismatch() -> None:
    """Never a subject, and never silently skipped either.

    A manifest pointing at a `real` meeting means the manifest names the wrong
    meeting or the drop was tagged wrong. Skipping it would shrink the
    denominator and report a run that measured less than it claimed.
    """
    manifest = manifest_for("northwind-weekly")
    selection = select_subjects([row("northwind-weekly", corpus="real")], [manifest])
    assert selection.subjects == ()
    assert len(selection.corpus_mismatches) == 1
    mismatch = selection.corpus_mismatches[0]
    assert isinstance(mismatch, CorpusMismatch)
    assert mismatch.corpus == "real"
    assert mismatch.source_id == "northwind-weekly"
    assert "northwind-weekly" in mismatch.describe()
    assert "scripted" in mismatch.describe()
    assert "'real'" in mismatch.describe()
    assert selection.unmatched == ()


def test_a_row_with_no_corpus_tag_reads_differently_from_a_mis_tagged_one() -> None:
    """"None" is not a corpus value anybody wrote.

    A row carrying no tag and a row tagged `real` are different failures — one
    predates the tag or did not come from a drop, the other is a mis-tagged
    drop — and triage goes to different places for each.
    """
    manifest = manifest_for("untagged")
    selection = select_subjects([row("untagged", corpus=None)], [manifest])
    mismatch = selection.corpus_mismatches[0]
    assert mismatch.corpus is None
    assert "no corpus tag" in mismatch.describe()
    assert "'None'" not in mismatch.describe()


def test_a_placeholder_source_id_is_reported_as_unmatched() -> None:
    """5.1 reports it; 5.2 decides whether it fails the run."""
    manifest = manifest_for("placeholder-demo-001-not-yet-recorded")
    selection = select_subjects([row("drive-item-1")], [manifest])
    assert selection.subjects == ()
    assert selection.corpus_mismatches == ()
    assert len(selection.unmatched) == 1
    unmatched = selection.unmatched[0]
    assert isinstance(unmatched, UnmatchedManifest)
    assert unmatched.manifest is manifest
    assert unmatched.source_id == "placeholder-demo-001-not-yet-recorded"
    assert "placeholder-demo-001-not-yet-recorded" in unmatched.describe()


def test_both_non_subject_buckets_can_describe_themselves() -> None:
    """5.2 reports the outcome; it should not have to invent phrasing for half of it."""
    selection = select_subjects(
        [row("northwind-weekly", corpus="real")],
        [manifest_for("northwind-weekly"), manifest_for("never-ingested")],
    )
    problems = selection.problems()
    assert len(problems) == 2
    assert any("northwind-weekly" in problem for problem in problems)
    assert any("never-ingested" in problem for problem in problems)


def test_an_empty_corpus_leaves_every_manifest_unmatched() -> None:
    manifests = [manifest_for("a"), manifest_for("b")]
    selection = select_subjects([], manifests)
    assert [item.manifest for item in selection.unmatched] == manifests


def test_ingested_meetings_without_a_manifest_are_simply_not_subjects() -> None:
    """A scripted drop nobody wrote ground truth for is not an eval subject.

    It is also not an error here: the harness measures what it has ground
    truth for. Deciding that a scripted meeting *should* have had a manifest
    is a corpus-completeness question, not a selection one.
    """
    selection = select_subjects([row("unwritten-script")], [])
    assert selection.subjects == ()
    assert selection.unmatched == ()
    assert selection.corpus_mismatches == ()


def test_selection_matches_by_source_id_not_by_title() -> None:
    manifest = manifest_for("drive-item-1")
    rows = [row("drive-item-2", title=manifest.title)]
    selection = select_subjects(rows, [manifest])
    assert selection.subjects == ()
    assert [item.manifest for item in selection.unmatched] == [manifest]


def test_several_manifests_match_their_own_rows() -> None:
    ui = manifest_for("drive-item-1")
    deck_data = valid_slide_deck()
    deck_data["meeting"] = meeting_of(deck_data, source_id="drive-item-2")
    deck = Manifest(data=deck_data)
    rows = [row("drive-item-2"), row("drive-item-1"), row("other", corpus="real")]
    selection = select_subjects(rows, [ui, deck])
    assert {s.source_id for s in selection.subjects} == {"drive-item-1", "drive-item-2"}
    assert {s.manifest.archetype for s in selection.subjects} == {"ui-demo", "slide-deck"}


def test_a_re_ingested_source_id_yields_a_subject_per_row() -> None:
    """A failed job leaves its row behind; a re-ingest adds a second.

    Both are surfaced rather than one being picked here — which one a run
    measures is story 5.2's call, and hiding the duplicate would take that
    decision away from it.
    """
    manifest = manifest_for("drive-item-1")
    rows = [
        row("drive-item-1", jobId="job-failed", meetingId=None, status="failed"),
        row("drive-item-1", jobId="job-retry"),
    ]
    selection = select_subjects(rows, [manifest])
    assert {subject.job_id for subject in selection.subjects} == {
        "job-failed",
        "job-retry",
    }
    assert {(subject.job_id, subject.status) for subject in selection.subjects} == {
        ("job-failed", "failed"),
        ("job-retry", "succeeded"),
    }


@pytest.mark.parametrize("corpus", ["real", "", None, "SCRIPTED"])
def test_only_the_exact_scripted_tag_admits_a_subject(corpus: Any) -> None:
    """The tag is an enum in docs/source-drop.schema.json — match it exactly."""
    manifest = manifest_for("drive-item-1")
    selection = select_subjects([row("drive-item-1", corpus=corpus)], [manifest])
    assert selection.subjects == ()
    assert len(selection.corpus_mismatches) == 1


# --- fetch_meetings: the one network call, exercised offline ----------------


def mock_api(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_fetch_meetings_gets_the_public_list_endpoint_and_unwraps_the_envelope() -> None:
    """Both halves matter and neither is observable from the harness's own types.

    A wrong path 404s only against a real api, and a wrong unwrap key yields an
    empty subject list that reads exactly like "nothing is ingested" — a run
    that measures nothing while reporting no error.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"meetings": [row("drive-item-1"), row("northwind", corpus="real")]}
        )

    rows = fetch_meetings("http://127.0.0.1:8000", transport=mock_api(handler))

    assert [str(request.url) for request in seen] == ["http://127.0.0.1:8000/meetings"]
    assert [item["sourceId"] for item in rows] == ["drive-item-1", "northwind"]
    # The rows are exactly the shape select_subjects consumes.
    selection = select_subjects(rows, [manifest_for("drive-item-1")])
    assert [subject.source_id for subject in selection.subjects] == ["drive-item-1"]


def test_fetch_meetings_tolerates_a_trailing_slash_on_the_base_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"meetings": []})

    assert fetch_meetings("http://127.0.0.1:8000/", transport=mock_api(handler)) == []
    assert seen == ["http://127.0.0.1:8000/meetings"]


def test_fetch_meetings_wraps_a_transport_failure_in_a_named_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(CorpusReadError) as exc:
        fetch_meetings("http://127.0.0.1:8000", transport=mock_api(handler))
    assert "http://127.0.0.1:8000/meetings" in str(exc.value)


def test_fetch_meetings_wraps_an_error_status_in_a_named_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(CorpusReadError):
        fetch_meetings("http://127.0.0.1:8000", transport=mock_api(handler))


def test_fetch_meetings_wraps_a_non_json_body_in_a_named_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not the api</html>")

    with pytest.raises(CorpusReadError):
        fetch_meetings("http://127.0.0.1:8000", transport=mock_api(handler))


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},  # a plausible-but-wrong envelope key
        {"meetings": {"drive-item-1": {}}},  # an object, not an array
        {"meetings": ["not a meeting row"]},
        {},
        [],
    ],
)
def test_fetch_meetings_rejects_a_missing_or_malformed_envelope(payload: Any) -> None:
    """A KeyError here would surface as a crash, not as "the api changed shape"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(CorpusReadError) as exc:
        fetch_meetings("http://127.0.0.1:8000", transport=mock_api(handler))
    assert "meetings" in str(exc.value)
