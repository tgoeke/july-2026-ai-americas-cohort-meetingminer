"""What a run does with a manifest that matches more than one meeting.

Story 5.1 delivered `select_subjects` with three buckets and explicitly left
one decision to 5.2: a `sourceId` can yield several rows, because a failed job
leaves its row behind and a re-ingest adds another, and 5.1 made every matching
scripted row a subject rather than picking one.

5.2's answer is that the run refuses to guess. It cannot tell which ingestion
the ground truth describes, so it measures neither and says so — the same
discipline as the zero-subject failure, one step further in. That decision
lives in `evals/conftest.py:_split`, which is the plugin the store-backed suite
runs under, so this file is the only thing that exercises it without a live
api. Styled after `test_subject_selection.py`, over synthetic rows.
"""

from __future__ import annotations

from typing import Any

from evals.conftest import _split
from evals.harness.groundtruth import Manifest
from evals.harness.subjects import Selection, Subject, select_subjects
from evals.tests.conftest import meeting_of, valid_ui_demo


def manifest_for(manifest_id: str, source_id: str) -> Manifest:
    data = valid_ui_demo()
    data["meeting"] = meeting_of(data, id=manifest_id, source_id=source_id)
    return Manifest(data=data)


def row(source_id: str, job: str, status: str = "succeeded", **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "jobId": job,
        "meetingId": f"meeting-{job}",
        "title": "Scripted UI Demo",
        "sourceId": source_id,
        "corpus": "scripted",
        "status": status,
        "stages": [],
        "viewable": True,
    }
    item.update(overrides)
    return item


def split_of(rows: list[dict[str, Any]], manifests: list[Manifest]):
    return _split(select_subjects(rows, manifests))


def test_one_row_per_manifest_is_a_subject_and_no_problem() -> None:
    manifest = manifest_for("demo-001", "drive-1")
    selected = split_of([row("drive-1", "job-a")], [manifest])
    assert [subject.manifest.id for subject in selected.subjects] == ["demo-001"]
    assert selected.problems == ()


def test_a_manifest_matching_two_ingestions_is_measured_by_neither() -> None:
    """A stale failed job beside its re-ingest. Measuring the wrong one would
    report a capture miss that is really a leftover row."""
    manifest = manifest_for("demo-001", "drive-1")
    selected = split_of(
        [row("drive-1", "job-old", status="failed"), row("drive-1", "job-new")],
        [manifest],
    )
    assert selected.subjects == ()
    assert len(selected.problems) == 1


def test_the_ambiguity_problem_names_both_ingestions_and_their_statuses() -> None:
    """Named, because the fix is an operator deleting one of them — a message
    that said only "ambiguous" would leave them hunting."""
    manifest = manifest_for("demo-001", "drive-1")
    selected = split_of(
        [row("drive-1", "job-old", status="failed"), row("drive-1", "job-new")],
        [manifest],
    )
    problem = selected.problems[0]
    assert "'demo-001'" in problem
    for expected in ("job-old", "job-new", "failed", "succeeded", "meeting-job-new"):
        assert expected in problem, f"the problem does not name {expected!r}"
    assert "Remove the stale ingestion" in problem


def test_an_ambiguous_manifest_does_not_take_an_unambiguous_one_down_with_it() -> None:
    ambiguous = manifest_for("demo-001", "drive-1")
    clean = manifest_for("demo-002", "drive-2")
    selected = split_of(
        [row("drive-1", "job-a"), row("drive-1", "job-b"), row("drive-2", "job-c")],
        [ambiguous, clean],
    )
    assert [subject.manifest.id for subject in selected.subjects] == ["demo-002"]
    assert len(selected.problems) == 1


def test_the_selection_problems_survive_the_split() -> None:
    """Unmatched manifests and corpus mismatches are 5.1's buckets; the split
    adds to them rather than replacing them."""
    placeholder = manifest_for("demo-001", "placeholder-not-yet-recorded")
    mistagged = manifest_for("demo-002", "drive-2")
    selected = split_of([row("drive-2", "job-c", corpus="real")], [placeholder, mistagged])
    assert selected.subjects == ()
    assert len(selected.problems) == 2
    joined = "\n".join(selected.problems)
    assert "placeholder-not-yet-recorded" in joined
    assert "corpus 'real'" in joined


def test_the_split_carries_the_selection_through_for_the_report() -> None:
    manifest = manifest_for("demo-001", "drive-1")
    selected = split_of([row("drive-1", "job-a")], [manifest])
    assert isinstance(selected.selection, Selection)
    assert isinstance(selected.subjects[0], Subject)
