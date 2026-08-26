"""Drop vocabulary: one definition of the canonical filenames, one reader.

The api and the worker must agree on what a drop is; these tests pin that
agreement (the api imports its constants from domain.drops) and the reader's
named-error contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from meetingminer.api import ingests
from meetingminer.domain import drops

from conftest import DropFactory, valid_metadata


def test_api_and_worker_share_one_filename_definition() -> None:
    assert ingests.METADATA_FILENAME is drops.METADATA_FILENAME
    assert ingests.EVIDENCE_FILENAMES is drops.EVIDENCE_FILENAMES
    assert drops.EVIDENCE_FILENAMES == (
        "recording.mp4",
        "transcript.vtt",
        "transcript.txt",
    )


def test_recording_drop_reports_a_recording(make_drop: DropFactory) -> None:
    drop = drops.read_drop(make_drop(files=("recording.mp4", "transcript.txt")))
    assert drop.has_recording is True
    assert drop.recording_path == drop.path / "recording.mp4"
    assert drop.transcript_paths == (drop.path / "transcript.txt",)


def test_transcript_only_drop_reports_no_recording(make_drop: DropFactory) -> None:
    drop = drops.read_drop(make_drop(files=("transcript.txt",)))
    assert drop.has_recording is False
    assert drop.recording_path is None


def test_metadata_fields_are_exposed_verbatim(make_drop: DropFactory) -> None:
    drop = drops.read_drop(make_drop(metadata=valid_metadata("source-42")))
    assert drop.source_id == "source-42"
    assert drop.corpus == "real"
    assert drop.started_at == datetime(2026, 8, 5, 12, 0, 19, tzinfo=timezone.utc)
    assert drop.started_at_precision == "second"
    assert drop.provenance["recordingName"].startswith("Daily Standup")
    # Best-effort title: the source side's provenance record, not a guess.
    assert drop.title == "Daily Standup"


def test_title_is_none_when_provenance_carries_no_title(make_drop: DropFactory) -> None:
    metadata = valid_metadata(provenance={"url": "https://example.invalid/x"})
    assert drops.read_drop(make_drop(metadata=metadata)).title is None


# `stream_url` is the one place that decides what counts as a usable source
# link (story 1.6, UX-DR11): whatever it returns is written onto every moment
# of a degraded-mode meeting and rendered as a link, so a scheme this project
# did not intend must never get past here.
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.invalid/stream.aspx?id=x", "https://example.invalid/stream.aspx?id=x"),
        ("http://example.invalid/x", "http://example.invalid/x"),
        # Scheme comparison is case-insensitive; the value itself is untouched.
        ("HTTPS://example.invalid/X", "HTTPS://example.invalid/X"),
        # Surrounding whitespace is stripped, and nothing else is changed.
        ("  https://example.invalid/x  ", "https://example.invalid/x"),
        ("javascript:alert(1)", None),
        ("mailto:someone@example.invalid", None),
        ("file:///etc/passwd", None),
        ("ftp://example.invalid/x", None),
        # HTTP(S) without an authority/host is not a usable deep link.
        ("https:", None),
        ("https:/path", None),
        ("https://", None),
        ("http:///path", None),
        ("https://example.invalid:not-a-port", None),
        ("https://example.invalid:99999", None),
        ("", None),
        ("   ", None),
        # Unparseable rather than merely wrong-schemed: an unterminated IPv6
        # bracket makes urlsplit raise, and one malformed field in a drop must
        # not fail the stage that reads it.
        ("http://[::1", None),
    ],
)
def test_stream_url_accepts_only_a_usable_http_link(
    make_drop: DropFactory, url: str, expected: str | None
) -> None:
    metadata = valid_metadata(provenance={"url": url, "title": "T"})
    assert drops.read_drop(make_drop(metadata=metadata)).stream_url == expected


@pytest.mark.parametrize("value", [None, 42, ["https://example.invalid/x"], {"href": "x"}])
def test_stream_url_is_none_when_the_url_field_is_not_a_string(
    make_drop: DropFactory, value: object
) -> None:
    metadata = valid_metadata(provenance={"url": value, "title": "T"})
    assert drops.read_drop(make_drop(metadata=metadata)).stream_url is None


def test_stream_url_is_none_when_provenance_carries_no_url(make_drop: DropFactory) -> None:
    metadata = valid_metadata(provenance={"title": "T"})
    assert drops.read_drop(make_drop(metadata=metadata)).stream_url is None


def test_day_precision_start_is_parsed(make_drop: DropFactory) -> None:
    metadata = valid_metadata(
        startedAt="2026-06-10T00:00:00Z", startedAtPrecision="day"
    )
    drop = drops.read_drop(make_drop(metadata=metadata))
    assert drop.started_at == datetime(2026, 6, 10, tzinfo=timezone.utc)
    assert drop.started_at_precision == "day"


def test_missing_directory_is_a_named_error(tmp_path: Path) -> None:
    with pytest.raises(drops.DropError, match="drop directory does not exist"):
        drops.read_drop(tmp_path / "absent")


def test_missing_metadata_is_a_named_error(make_drop: DropFactory) -> None:
    with pytest.raises(drops.DropError, match="missing metadata.json"):
        drops.read_drop(make_drop(omit_metadata=True))


def test_unparseable_metadata_is_a_named_error(make_drop: DropFactory) -> None:
    with pytest.raises(drops.DropError, match="not valid JSON"):
        drops.read_drop(make_drop(raw_metadata="{not json"))


def test_metadata_that_is_not_an_object_is_a_named_error(make_drop: DropFactory) -> None:
    with pytest.raises(drops.DropError, match="must be a JSON object"):
        drops.read_drop(make_drop(raw_metadata=json.dumps([1, 2, 3])))


def test_drop_without_evidence_is_a_named_error(make_drop: DropFactory) -> None:
    with pytest.raises(drops.DropError, match="neither a recording nor a transcript"):
        drops.read_drop(make_drop(files=()))


def test_missing_required_metadata_field_is_a_named_error(make_drop: DropFactory) -> None:
    metadata = valid_metadata()
    del metadata["corpus"]
    with pytest.raises(drops.DropError, match="missing required field 'corpus'"):
        drops.read_drop(make_drop(metadata=metadata))


def test_unknown_files_in_the_drop_are_ignored(make_drop: DropFactory) -> None:
    path = make_drop(files=("transcript.txt",))
    (path / "summary.md").write_text("generated by the puller", encoding="utf-8")
    drop = drops.read_drop(path)
    assert drop.transcript_paths == (path / "transcript.txt",)


def test_reading_a_drop_does_not_modify_it(make_drop: DropFactory) -> None:
    """AD-13: the drop directory is read-only after intake."""
    path = make_drop(files=("recording.mp4", "transcript.txt"))
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in path.iterdir()}
    drops.read_drop(path)
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in path.iterdir()}
    assert before == after
