"""GET /media contract tests (run against meetingminer_test; skip without Postgres).

Two things here break silently under a refactor and are therefore pinned row
by row: the containment guard, because a path that escapes the content root
still returns *some* bytes and looks like a working route; and the range
arithmetic, because an off-by-one in `Content-Range` makes a video player seek
to slightly the wrong place rather than fail. Both are exercised through the
real routes, and the two pure functions are also called directly so a failure
says which half is wrong.

The recording route's own hazard is registration order: `/media/{path:path}`
would swallow `/media/recordings/{meetingId}` if it were declared first, and
the failure would be a 404 rather than an error, so
`test_recordings_route_wins_over_the_catch_all` plants a decoy file to catch it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from meetingminer.api.media import (
    _UNSATISFIABLE,
    CHUNK_SIZE,
    _ByteRange,
    _parse_range,
    _resolve_under_root,
)
from meetingminer.api.problems import Problem

PROBLEM = "application/problem+json"

SHOT_RELATIVE = "meetings/m1/screenshots/shot-01.jpg"
# 10 KiB of non-repeating-enough bytes: long enough for a mid-file range and a
# 500-byte suffix to be distinguishable from the whole file.
SHOT_BYTES = bytes(range(256)) * 40

# Several times CHUNK_SIZE, so the streaming loop has to run more than once.
# Nothing else in this file is: turning `while remaining > 0` into a single
# `if` would truncate a real recording at 64 KiB while still advertising the
# full Content-Length, and every other test here would stay green.
LARGE_RELATIVE = "meetings/m1/frames/large.bin"
LARGE_BYTES = bytes(range(256)) * 800


def _slug(response) -> str:
    return response.json()["type"].removeprefix("urn:meetingminer:problem:")


def _assert_no_absolute_paths(response, *forbidden: Path) -> None:
    """No response the api emits may name a server-side absolute path."""
    body = response.text
    for path in forbidden:
        assert str(path) not in body, f"{path} leaked into {body}"
    # Belt and braces: nothing that even looks like a filesystem root.
    for token in ("/Users/", "/private/", "/var/folders", "/tmp/", "/etc/"):
        assert token not in body, f"{token!r} leaked into {body}"


# --- fixtures --------------------------------------------------------------


@pytest.fixture()
def media_root(client, content_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the api at an isolated MM_CONTENT_ROOT for one test.

    The api reaches its root through `app.state.config`, so the test swaps a
    copy of the loaded config rather than mutating the developer's own — and
    monkeypatch puts the real one back, because `app` is a module singleton
    every other test in the session shares.
    """
    import meetingminer.api.main as api_main

    root = content_root.resolve()
    config = api_main.app.state.config
    monkeypatch.setattr(
        api_main.app.state,
        "config",
        config.model_copy(
            update={"secrets": config.secrets.model_copy(update={"mm_content_root": root})}
        ),
    )
    return root


@pytest.fixture()
def screenshot_file(media_root: Path) -> Path:
    """A file at a root-relative path of the shape `screenshot.path` holds."""
    path = media_root / SHOT_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_bytes(SHOT_BYTES)
    return path


@pytest.fixture()
def large_file(media_root: Path) -> bytes:
    """A content-root file several chunks long, written without ffmpeg."""
    path = media_root / LARGE_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_bytes(LARGE_BYTES)
    return LARGE_BYTES


def _submit(client, drop: Path) -> str:
    response = client.post("/ingests", json={"dropPath": str(drop)})
    assert response.status_code == 201, response.text
    return response.json()["jobId"]


def _mint_meeting(pool, job_id: str, *, has_recording: bool) -> str:
    """Stand in for the worker's meeting mint (the api never writes this row)."""
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO meeting"
            " (job_id, source_id, corpus, started_at, started_at_precision,"
            "  title, has_recording)"
            " SELECT j.id, j.source_id, j.corpus, '2026-08-05T12:00:19Z', 'second',"
            "        'Replay Fixture', %s FROM job j WHERE j.id = %s"
            " RETURNING id",
            (has_recording, job_id),
        ).fetchone()
    return str(row[0])


def _insert_screenshot(pool, meeting_id: str, path: str) -> str:
    """Stand in for the `screens` stage (the api never writes these rows).

    Returns the stored `screenshot.path`, so a test reads the value back out
    of the database rather than trusting the literal it passed in.
    """
    with pool.connection() as conn:
        screen_id = conn.execute(
            "INSERT INTO screen (identity_key, signature, view_type)"
            " VALUES (%s, %s, 'slide') RETURNING id",
            (f"meeting:{meeting_id}:1", "revenue slide"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO screenshot"
            " (meeting_id, screen_id, ordinal, start_offset_ms, end_offset_ms,"
            "  frame_count, path, view_type)"
            " VALUES (%s, %s, 1, 0, 2000, 3, %s, 'slide')",
            (meeting_id, screen_id, path),
        )
        stored = conn.execute(
            "SELECT path FROM screenshot WHERE meeting_id = %s", (meeting_id,)
        ).fetchone()[0]
    return stored


def _record_recording(pool, meeting_id: str, relative: str) -> None:
    """Stand in for the `probe` stage's provenance row (the api never writes it).

    The route resolves `meeting_media.drop_relative_path` against
    MM_DROPS_ROOT (story 2.1a), so this is what seeding a served recording
    means now — the drop on disk is no longer half the address.
    """
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO meeting_media (meeting_id, drop_relative_path, sha256,"
            " size_bytes) VALUES (%s, %s, %s, %s)",
            (meeting_id, relative, "0" * 64, 0),
        )


@pytest.fixture()
def recorded_meeting(client, test_pool, make_drop, synthetic_recording: Path) -> Any:
    """A meeting whose drop holds a real (tiny) mp4, plus that mp4's bytes.

    Returns `(meeting_id, drop_dir, recording_bytes)`. The drop is the thing
    served, so the recording is copied into it rather than referenced, and its
    drops-root-relative path is recorded the way `probe` records it.
    """
    drop = make_drop(files=("recording.mp4",))
    (drop / "recording.mp4").write_bytes(synthetic_recording.read_bytes())
    job_id = _submit(client, drop)
    meeting_id = _mint_meeting(test_pool, job_id, has_recording=True)
    _record_recording(test_pool, meeting_id, f"{drop.name}/recording.mp4")
    return meeting_id, drop, (drop / "recording.mp4").read_bytes()


# --- _parse_range (no store, no routes) -------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=1000-1999", _ByteRange(1000, 1999)),
        ("bytes=1000-", _ByteRange(1000, 9999)),
        ("bytes=-500", _ByteRange(9500, 9999)),
        ("bytes=0-0", _ByteRange(0, 0)),
        ("bytes=0-", _ByteRange(0, 9999)),
        # The last byte, addressed both ways.
        ("bytes=9999-9999", _ByteRange(9999, 9999)),
        ("bytes=-1", _ByteRange(9999, 9999)),
        # An end past EOF is clamped rather than refused: a player that asks
        # for more than exists gets what exists.
        ("bytes=9990-99999", _ByteRange(9990, 9999)),
        # A suffix longer than the file is the whole file.
        ("bytes=-99999", _ByteRange(0, 9999)),
        # Case-insensitive unit, and surrounding whitespace.
        ("Bytes= 100-199 ", _ByteRange(100, 199)),
    ],
)
def test_parse_range_accepts_every_rfc_9110_form(header: str, expected: _ByteRange) -> None:
    assert _parse_range(header, 10_000) == expected
    assert expected.length == expected.end - expected.start + 1


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "furlongs=1-2",
        "bytes=abc",
        "bytes=-",
        "bytes=1-2-3",
        "bytes=5-2",  # end before start: malformed, so the header is ignored
        "bytes=-1.5",
        "bytes=+5-9",
        "1000-1999",  # no unit at all
        "bytes=0-9,20-29",  # multi-range: answered whole, never multipart
    ],
)
def test_parse_range_ignores_anything_unusable(header: str | None) -> None:
    """RFC 9110 §14.2: an unusable Range is ignored and the whole file served."""
    assert _parse_range(header, 10_000) is None


@pytest.mark.parametrize(
    "header",
    [
        # `str.isdigit` is true for these and `int()` refuses them, which is an
        # unhandled 500 on a header the matrix says to ignore. A Range header
        # is decoded latin-1, so a raw 0xB2 byte reaches the parser as exactly
        # this string — httpx will not transmit one (it re-encodes as UTF-8),
        # which is why the non-ASCII spellings are pinned here and only the
        # long-digit one is also exercised through the route below.
        "bytes=\u00b2-5",
        "bytes=5-\u00b2",
        "bytes=-\u00b2",
        # `str.isdigit` is true and `int()` *succeeds*, for a value no HTTP
        # client meant to send: Arabic-Indic five.
        "bytes=\u0665-9",
        # Past the interpreter's own int-conversion limit.
        "bytes=" + "9" * 5000 + "-",
        "bytes=0-" + "9" * 5000,
        "bytes=-" + "9" * 5000,
    ],
)
def test_parse_range_ignores_digits_int_cannot_take(header: str) -> None:
    """Whatever `_parse_range` accepts, `int()` has to accept too."""
    assert _parse_range(header, 10_000) is None


@pytest.mark.parametrize(
    ("header", "size"),
    [
        ("bytes=10000-", 10_000),  # first byte is exactly EOF
        ("bytes=10000-10005", 10_000),
        ("bytes=-0", 10_000),  # a zero-length suffix names nothing
        ("bytes=0-", 0),  # an empty file satisfies no range at all
        ("bytes=-1", 0),
    ],
)
def test_parse_range_reports_unsatisfiable(header: str, size: int) -> None:
    assert _parse_range(header, size) is _UNSATISFIABLE


# --- _resolve_under_root (no store, no routes) -----------------------------


def test_resolve_under_root_accepts_a_nested_relative_path(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    (root / "meetings" / "m1").mkdir(parents=True)
    assert _resolve_under_root(root, "meetings/m1/a.jpg") == root / "meetings/m1/a.jpg"


@pytest.mark.parametrize(
    "relative",
    [
        "../secret.txt",
        "meetings/../../secret.txt",
        "/etc/passwd",
        "/",
        "a\x00b",
    ],
)
def test_resolve_under_root_refuses_escapes(tmp_path: Path, relative: str) -> None:
    root = tmp_path / "content"
    root.mkdir()
    with pytest.raises(Problem) as caught:
        _resolve_under_root(root.resolve(), relative)
    assert caught.value.status == 400
    assert caught.value.slug == "media-path-invalid"


def test_resolve_under_root_refuses_any_symlinked_component(tmp_path: Path) -> None:
    """Every symlink is refused, not only one that leaves the root.

    Nothing the worker writes under the content root is a symlink, so there is
    no legitimate traffic to lose — and "does this link still land inside the
    root" is a question with a different answer at every moment.
    """
    root = (tmp_path / "content").resolve()
    root.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"not yours")
    real = root / "real.jpg"
    real.write_bytes(b"mine")
    (root / "escape.jpg").symlink_to(outside)
    (root / "inside.jpg").symlink_to(real)
    (root / "escape-dir").symlink_to(tmp_path, target_is_directory=True)

    for relative in ("escape.jpg", "inside.jpg", "escape-dir/outside.jpg"):
        with pytest.raises(Problem) as caught:
            _resolve_under_root(root, relative)
        assert caught.value.slug == "media-path-invalid", relative


# --- the path-addressed route ----------------------------------------------


def test_screenshot_streams_with_its_content_type(client, screenshot_file: Path) -> None:
    response = client.get(f"/media/{SHOT_RELATIVE}")
    assert response.status_code == 200
    assert response.content == SHOT_BYTES
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(SHOT_BYTES))
    # The declared type is the whole type: nothing served here is ever sniffed.
    assert response.headers["x-content-type-options"] == "nosniff"


def test_screenshot_honours_a_range(client, screenshot_file: Path) -> None:
    response = client.get(
        f"/media/{SHOT_RELATIVE}", headers={"Range": "bytes=1000-1999"}
    )
    assert response.status_code == 206
    assert response.content == SHOT_BYTES[1000:2000]
    assert response.headers["content-range"] == f"bytes 1000-1999/{len(SHOT_BYTES)}"


def test_a_file_larger_than_one_chunk_streams_whole(client, large_file: bytes) -> None:
    """The streaming loop has to iterate; a single-shot read truncates here."""
    assert len(large_file) > CHUNK_SIZE * 2, "fixture must span several chunks"

    response = client.get(f"/media/{LARGE_RELATIVE}")

    assert response.status_code == 200
    assert len(response.content) == len(large_file)
    assert response.content == large_file
    assert response.headers["content-length"] == str(len(large_file))


def test_a_range_spanning_a_chunk_boundary_streams_whole(
    client, large_file: bytes
) -> None:
    """A ranged read is chunked too, and 206 is the branch a player takes."""
    start, end = 60_000, 140_000
    assert start < CHUNK_SIZE < end, "the range must cross a chunk boundary"

    response = client.get(
        f"/media/{LARGE_RELATIVE}", headers={"Range": f"bytes={start}-{end}"}
    )

    assert response.status_code == 206
    assert len(response.content) == end - start + 1
    assert response.content == large_file[start : end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/{len(large_file)}"
    # Asserted on this branch too: the 206 header dict is a separate literal
    # from the 200 one, so the 200-only assertion pins nothing here.
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "header", ["bytes=" + "9" * 5000 + "-", "bytes=0-" + "9" * 5000]
)
def test_a_range_python_cannot_parse_is_ignored_by_the_route(
    client, screenshot_file: Path, header: str
) -> None:
    """`int()` refuses a digit run this long; the route must still answer 200."""
    response = client.get(f"/media/{SHOT_RELATIVE}", headers={"Range": header})

    assert response.status_code == 200
    assert response.content == SHOT_BYTES


def test_missing_file_under_the_root_is_a_404_problem(client, media_root: Path) -> None:
    response = client.get("/media/meetings/m1/screenshots/nope.jpg")
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    assert _slug(response) == "media-not-found"
    _assert_no_absolute_paths(response, media_root)


def test_directory_is_a_404_problem(client, screenshot_file: Path, media_root: Path) -> None:
    response = client.get("/media/meetings/m1/screenshots")
    assert response.status_code == 404
    assert _slug(response) == "media-not-found"
    _assert_no_absolute_paths(response, media_root)


def test_empty_path_is_a_404_problem(client, media_root: Path) -> None:
    """`/media/` names the root itself, which is a directory, not a file."""
    response = client.get("/media/")
    assert response.status_code == 404
    assert _slug(response) == "media-not-found"


@pytest.mark.parametrize(
    "spelling",
    [
        # Percent-encoded separators, the forms that actually survive a client:
        # a literal `../..` is collapsed by every conforming client, proxy and
        # server before routing (see the test below), so these are the shapes a
        # traversal attempt really arrives in.
        "..%2F..%2Fetc%2Fpasswd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "%2E%2E/%2E%2E/etc/passwd",
        "meetings/..%2F..%2Fetc%2Fpasswd",
        # `/media//etc/passwd` reaches the route as the absolute `/etc/passwd`.
        "/etc/passwd",
    ],
)
def test_traversal_is_a_400_problem_and_serves_no_bytes(
    client, media_root: Path, spelling: str
) -> None:
    response = client.get(f"/media/{spelling}")
    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM
    assert _slug(response) == "media-path-invalid"
    assert b"root:" not in response.content
    _assert_no_absolute_paths(response, media_root)


def test_literal_dot_dot_never_reaches_the_media_prefix(client, media_root: Path) -> None:
    """The un-encoded form is normalised away, so it can only ever 404.

    Pinned so the guard's coverage is not mistaken for the client's: this row
    of the matrix serves no bytes because the request stops being a `/media`
    request at all, and the encoded forms above are what the guard answers.
    """
    response = client.get("/media/../../etc/passwd")
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    assert b"root:" not in response.content


def test_symlink_escape_is_a_400_problem(client, media_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"not yours")
    (media_root / "escape.jpg").symlink_to(outside)

    response = client.get("/media/escape.jpg")
    assert response.status_code == 400
    assert _slug(response) == "media-path-invalid"
    assert response.content != b"not yours"
    _assert_no_absolute_paths(response, media_root, outside)


def test_unconfigured_content_root_is_a_500_problem(client, monkeypatch) -> None:
    import meetingminer.api.main as api_main

    config = api_main.app.state.config
    monkeypatch.setattr(
        api_main.app.state,
        "config",
        config.model_copy(
            update={"secrets": config.secrets.model_copy(update={"mm_content_root": None})}
        ),
    )
    response = client.get(f"/media/{SHOT_RELATIVE}")
    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM
    assert _slug(response) == "media-root-unconfigured"
    assert "MM_CONTENT_ROOT" in response.json()["detail"]


def test_content_root_that_is_not_a_directory_is_a_500_problem(
    client, content_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator error, not a missing file — so 500, not a 404 per request."""
    import meetingminer.api.main as api_main

    config = api_main.app.state.config
    monkeypatch.setattr(
        api_main.app.state,
        "config",
        config.model_copy(
            update={
                "secrets": config.secrets.model_copy(
                    update={"mm_content_root": content_root / "does-not-exist"}
                )
            }
        ),
    )
    response = client.get(f"/media/{SHOT_RELATIVE}")
    assert response.status_code == 500
    assert _slug(response) == "media-root-unconfigured"
    _assert_no_absolute_paths(response, content_root)


# --- the recording route ---------------------------------------------------


def test_recording_streams_whole_without_a_range(client, recorded_meeting) -> None:
    meeting_id, _drop, recording = recorded_meeting
    response = client.get(f"/media/recordings/{meeting_id}")
    assert response.status_code == 200
    assert response.content == recording
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["content-length"] == str(len(recording))


def test_recording_serves_an_exact_byte_range(client, recorded_meeting) -> None:
    """The seek an HTML5 <video> actually issues."""
    meeting_id, _drop, recording = recorded_meeting
    assert len(recording) > 2000, "the synthetic recording is too small to range over"
    response = client.get(
        f"/media/recordings/{meeting_id}", headers={"Range": "bytes=1000-1999"}
    )
    assert response.status_code == 206
    assert response.content == recording[1000:2000]
    assert len(response.content) == 1000
    assert response.headers["content-range"] == f"bytes 1000-1999/{len(recording)}"
    assert response.headers["content-length"] == "1000"
    assert response.headers["accept-ranges"] == "bytes"


def test_recording_serves_an_open_ended_range(client, recorded_meeting) -> None:
    meeting_id, _drop, recording = recorded_meeting
    size = len(recording)
    response = client.get(
        f"/media/recordings/{meeting_id}", headers={"Range": "bytes=1000-"}
    )
    assert response.status_code == 206
    assert response.content == recording[1000:]
    assert response.headers["content-range"] == f"bytes 1000-{size - 1}/{size}"


def test_recording_serves_a_suffix_range(client, recorded_meeting) -> None:
    """`bytes=-500` — how a player finds the moov atom at the end of an mp4."""
    meeting_id, _drop, recording = recorded_meeting
    size = len(recording)
    response = client.get(
        f"/media/recordings/{meeting_id}", headers={"Range": "bytes=-500"}
    )
    assert response.status_code == 206
    assert response.content == recording[-500:]
    assert response.headers["content-range"] == f"bytes {size - 500}-{size - 1}/{size}"


def test_recording_refuses_an_unsatisfiable_range(client, recorded_meeting) -> None:
    meeting_id, _drop, recording = recorded_meeting
    size = len(recording)
    response = client.get(
        f"/media/recordings/{meeting_id}", headers={"Range": f"bytes={size}-"}
    )
    assert response.status_code == 416
    assert response.headers["content-type"] == PROBLEM
    assert response.headers["content-range"] == f"bytes */{size}"
    assert _slug(response) == "media-range-unsatisfiable"
    assert response.json()["title"] == "Range Not Satisfiable"


def test_recording_ignores_a_malformed_range(client, recorded_meeting) -> None:
    meeting_id, _drop, recording = recorded_meeting
    response = client.get(
        f"/media/recordings/{meeting_id}", headers={"Range": "furlongs=1-2"}
    )
    assert response.status_code == 200
    assert response.content == recording


def test_unknown_meeting_is_a_404_problem(client, media_root: Path) -> None:
    response = client.get(f"/media/recordings/{uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    assert _slug(response) == "media-not-found"


def test_transcript_only_meeting_names_that_it_has_no_recording(
    client, test_pool, make_drop
) -> None:
    job_id = _submit(client, make_drop(files=("transcript.txt",)))
    meeting_id = _mint_meeting(test_pool, job_id, has_recording=False)

    response = client.get(f"/media/recordings/{meeting_id}")
    assert response.status_code == 404
    assert _slug(response) == "media-no-recording"
    assert "no recording" in response.json()["detail"]


def test_recording_missing_on_disk_is_a_404_problem(client, recorded_meeting) -> None:
    """`has_recording` is true but the drop's file is gone — never a 500."""
    meeting_id, drop, _recording = recorded_meeting
    (drop / "recording.mp4").unlink()

    response = client.get(f"/media/recordings/{meeting_id}")
    assert response.status_code == 404
    assert _slug(response) == "media-not-found"
    _assert_no_absolute_paths(response, drop)


def test_recordings_route_wins_over_the_catch_all(
    client, media_root: Path, recorded_meeting
) -> None:
    """Registration order, pinned: the catch-all must not shadow recordings.

    If `/media/{path:path}` were declared first it would try to resolve
    `recordings/<uuid>` as a content-root file — which is why a decoy is
    planted exactly there. The bytes that come back have to be the drop's.
    """
    meeting_id, _drop, recording = recorded_meeting
    decoy = media_root / "recordings" / meeting_id
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b"decoy")

    response = client.get(f"/media/recordings/{meeting_id}")
    assert response.status_code == 200
    assert response.content == recording
    assert response.content != b"decoy"


def test_recording_response_never_names_the_drop(client, recorded_meeting) -> None:
    """The drop is absolute and server-side; the client only knows the meeting."""
    meeting_id, drop, _recording = recorded_meeting
    response = client.get(f"/media/recordings/{meeting_id}")
    assert str(drop) not in str(dict(response.headers))


def test_a_symlinked_recording_is_refused(
    client, recorded_meeting, tmp_path: Path
) -> None:
    """A recorded path is data, so the file it names is guarded too.

    Intake refuses a symlinked `recording.mp4` before a job row exists, so
    this is the drop that *became* a link afterwards. Resolving the stored
    path would otherwise stream whatever it points at — the same escape the
    path-addressed route refuses, reached through the database instead of the
    url.
    """
    meeting_id, drop, _recording = recorded_meeting
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not yours")
    (drop / "recording.mp4").unlink()
    (drop / "recording.mp4").symlink_to(outside)

    response = client.get(f"/media/recordings/{meeting_id}")

    assert response.status_code == 404
    assert _slug(response) == "media-not-found"
    assert b"not yours" not in response.content
    _assert_no_absolute_paths(response, drop, outside)


def test_a_drop_directory_that_became_a_symlink_is_refused(
    client, test_pool, recorded_meeting, tmp_path: Path
) -> None:
    """The other half of the same escape: the drop itself is the symlink.

    Intake refuses a symlinked drop directory outright (story 2.1a, covered in
    `test_ingests.py`), so the only way to reach this state is for the
    directory to be replaced by a link after the job row existed. Resolution
    refuses it rather than following it out of the root.
    """
    meeting_id, drop, _recording = recorded_meeting
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "recording.mp4").write_bytes(b"not yours")
    shutil.rmtree(drop)
    # `try/finally`, because the drops root is session-scoped and shared: a
    # symlink left behind here is a booby trap for every later test that walks
    # or resolves under the root.
    drop.symlink_to(elsewhere, target_is_directory=True)
    try:
        response = client.get(f"/media/recordings/{meeting_id}")
    finally:
        drop.unlink()

    assert response.status_code == 404
    assert _slug(response) == "media-not-found"
    assert b"not yours" not in response.content


# --- the database's own paths ----------------------------------------------


def test_a_stored_screenshot_path_resolves_through_the_media_route(
    client, test_pool, make_drop, media_root: Path
) -> None:
    """The whole chain: `screenshot.path` -> url -> bytes.

    Every other path test here writes a literal it invented. This one takes
    the value back out of the database and asks for exactly that, which is
    what the acceptance criterion is actually about — a root-relative path the
    `screens` stage wrote has to be serveable as-is, with no rewriting in
    between.
    """
    # Its own meeting rather than `recorded_meeting`: a screenshot path has
    # nothing to do with a recording, and that fixture needs ffmpeg.
    job_id = _submit(client, make_drop(files=("transcript.txt",)))
    meeting_id = _mint_meeting(test_pool, job_id, has_recording=False)
    relative = f"meetings/{meeting_id}/screenshots/shot-01.jpg"
    on_disk = media_root / relative
    on_disk.parent.mkdir(parents=True)
    on_disk.write_bytes(SHOT_BYTES)

    stored = _insert_screenshot(test_pool, meeting_id, relative)
    assert stored == relative, "the column must round-trip the path unchanged"

    response = client.get(f"/media/{stored}")

    assert response.status_code == 200
    assert response.content == SHOT_BYTES
    assert response.headers["content-type"] == "image/jpeg"
