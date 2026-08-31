"""Upload sessions (story 6.4a): the surface, its refusals, and its identity.

Offline by construction. No test here reaches a network, starts the real
detached child, or calls intake: ``post_ingest`` is replaced everywhere the
runner is exercised, and every drops root is a ``tmp_path``.

Three properties are asserted over and over, because they are what the story
*is*:

* **The api does no pipeline work.** ``POST /uploads`` writes bytes and a
  declaration; a must-not-run stub over ``mint`` proves the request handler
  never mints.
* **A refusal leaves nothing behind.** Every refusal row asserts the uploads
  root is empty afterwards — not merely that the response was a 4xx. A staging
  directory that survived a refusal is the failure mode this story exists to
  prevent.
* **One meeting, whichever door.** The identity test mints the same bytes
  through ``mint-drop``'s own call order and through the upload runner and
  requires the same ``sourceId`` and the same ``startedAt`` pair.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from fastapi.routing import APIRoute

import meetingminer.api.main as api_main
import meetingminer.api.uploads as api_uploads
from meetingminer import acquisitions, mintdrop, uploads
from meetingminer.config import AppConfig
from meetingminer.domain.drops import (
    EVIDENCE_FILENAMES,
    METADATA_FILENAME,
    read_drop,
    read_metadata,
)

from repo_paths import REPO_ROOT

SCHEMA_SOURCE = REPO_ROOT / "docs" / "source-drop.schema.json"
PROBLEM_MEDIA_TYPE = "application/problem+json"

STARTED_AT = "2026-08-05T12:00:19Z"
TITLE = "Platform Sync — August"

ZOOM_VTT = b"""WEBVTT

1
00:00:00.000 --> 00:00:02.400
Alice Chen: We should ship the migration first.

2
00:00:02.400 --> 00:00:05.000
Alice Chen: The rollback plan is written.

3
00:00:05.000 --> 00:00:08.000
Bob Stone: Agreed, I will take the runbook.
"""

LEGACY_TXT = b"""Alice Chen | 00:00
We should ship the migration first.

Bob Stone | 00:05
Agreed, I will take the runbook.
"""


# --- the isolated api -------------------------------------------------------


@dataclass(frozen=True)
class Env:
    """One test's api: its own repo-root anchor, drops root and upload caps."""

    config: AppConfig
    drops: Path
    uploads_root: Path
    acquisitions_root: Path

    def session_dirs(self) -> list[Path]:
        if not self.uploads_root.is_dir():
            return []
        return sorted(p for p in self.uploads_root.iterdir() if p.is_dir())

    def drop_dirs(self) -> list[Path]:
        return sorted(p for p in self.drops.iterdir() if p.is_dir() and not p.name.startswith("."))


@pytest.fixture()
def make_env(
    client: Any, app_config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Env]:
    """Point the running app at a throwaway repo root, drops root and caps.

    The same swap `test_api_acquisitions.py` makes, extended with the four
    upload boundaries so a cap can be made small enough to trip on purpose.
    """
    counter = 0

    def _make(
        *,
        max_recording_bytes: int = 8 * 1024 * 1024,
        max_transcript_bytes: int = 1024 * 1024,
        max_duration_minutes: int = 480,
        session_ttl_minutes: int = 1440,
    ) -> Env:
        nonlocal counter
        counter += 1
        home = tmp_path / f"host{counter}"
        (home / "docs").mkdir(parents=True)
        shutil.copy(SCHEMA_SOURCE, home / "docs" / SCHEMA_SOURCE.name)
        drops = tmp_path / f"drops{counter}"
        drops.mkdir()
        settings = app_config.settings
        acquisition = settings.acquisition
        config = app_config.model_copy(
            update={
                "config_path": home / "config.yaml",
                "secrets": app_config.secrets.model_copy(update={"mm_drops_root": drops}),
                "settings": settings.model_copy(
                    update={
                        "acquisition": acquisition.model_copy(
                            update={
                                "upload": acquisition.upload.model_copy(
                                    update={
                                        "max_recording_bytes": max_recording_bytes,
                                        "max_transcript_bytes": max_transcript_bytes,
                                        "max_duration_minutes": max_duration_minutes,
                                        "session_ttl_minutes": session_ttl_minutes,
                                    }
                                )
                            }
                        )
                    }
                ),
            }
        )
        monkeypatch.setattr(api_main.app.state, "config", config)
        return Env(
            config=config,
            drops=drops,
            uploads_root=uploads.sessions_root(config),
            acquisitions_root=acquisitions.acquisitions_root(config),
        )

    return _make


@pytest.fixture(autouse=True)
def no_minting(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request handler that started minting fails loudly rather than slowly.

    Lifted for the tests that drive the runner directly, which is the only
    place in this story allowed to mint.
    """

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the api request handler must not mint a drop")

    monkeypatch.setattr(uploads, "probe_media", _probe_ok)
    monkeypatch.setattr(mintdrop, "mint", _boom)


def _probe_ok(_path: Path) -> Any:
    """A video ffprobe would accept: one minute long, with a video stream."""

    @dataclass(frozen=True)
    class _Facts:
        duration_ms: int | None = 60_000
        container: str | None = "mov,mp4,m4a"
        video_codec: str | None = "h264"

        @property
        def has_video(self) -> bool:
            return self.video_codec is not None

    return _Facts()


@pytest.fixture()
def ffprobe_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """``shutil.which(FFPROBE)`` answers yes without needing the real tool."""
    monkeypatch.setattr(
        uploads.shutil, "which", lambda name: "/usr/bin/ffprobe" if name == "ffprobe" else None
    )


# --- helpers ----------------------------------------------------------------


def fields(**overrides: str | None) -> dict[str, str]:
    """The four text fields, with a key removed by passing it ``None``."""
    values: dict[str, str] = {
        "title": TITLE,
        "startedAt": STARTED_AT,
        "corpus": "real",
        "transcriptDialect": "zoom",
    }
    for key, value in overrides.items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    return values


def post_session(
    client: Any, *, data: dict[str, str], files: list[tuple[str, tuple[str, bytes, str]]]
) -> Any:
    return client.post("/uploads", data=data, files=files)


def vtt_part(name: str = "Migration Sync.vtt", body: bytes = ZOOM_VTT) -> tuple[str, tuple[str, bytes, str]]:
    return ("files", (name, body, "text/vtt"))


def txt_part(name: str = "Migration Sync.txt", body: bytes = LEGACY_TXT) -> tuple[str, tuple[str, bytes, str]]:
    return ("files", (name, body, "text/plain"))


def mp4_part(body: bytes, name: str = "Migration Sync.mp4") -> tuple[str, tuple[str, bytes, str]]:
    return ("files", (name, body, "video/mp4"))


def refusal(response: Any) -> tuple[str, str]:
    """The rule and remediation of an RFC 9457 refusal, asserted to be complete."""
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["type"].startswith("urn:meetingminer:problem:")
    for member in ("title", "status", "detail"):
        assert body[member], f"{member} is empty: {body}"
    assert body["rule"] in uploads.REFUSAL_RULES
    assert body["remediation"] == uploads.REMEDIATIONS[body["rule"]]
    return body["rule"], body["detail"]


# --- the closed vocabulary --------------------------------------------------


def test_every_rule_has_a_status_and_a_remedy() -> None:
    assert set(uploads.REMEDIATIONS) == set(uploads.REFUSAL_RULES)
    assert set(uploads.PROBLEM_STATUS) == set(uploads.REFUSAL_RULES)
    assert all(text.strip() for text in uploads.REMEDIATIONS.values())
    assert set(uploads.PROBLEM_STATUS.values()) == {400, 404, 413, 415, 422, 503}


def test_every_rule_raised_is_in_the_vocabulary() -> None:
    """Every ``rule=`` literal in the module is one the tables answer for.

    Read out of the source rather than exercised, so a rule added to a refusal
    that no test reaches still cannot escape the vocabulary.
    """
    source = Path(uploads.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    raised = {
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "UploadRefused"
        for keyword in node.keywords
        if keyword.arg == "rule" and isinstance(keyword.value, ast.Constant)
    }
    assert raised, "no rule literals found — the parser or the module moved"
    assert raised <= set(uploads.REFUSAL_RULES)


def test_upload_rules_stay_out_of_the_youtube_tables() -> None:
    """The two vocabularies meet only at ``refusal_for``/``problem_status``."""
    assert not set(uploads.REFUSAL_RULES) & set(acquisitions.REMEDIATIONS)
    assert acquisitions.problem_status("upload-too-large") == 413
    assert acquisitions.problem_status("duration-cap") == 422
    # A rule from neither table is this server's problem, not the client's.
    assert acquisitions.problem_status("no-such-rule") == 503


def test_refusal_for_classifies_an_upload_refusal() -> None:
    error = uploads.UploadRefused("nope", rule="upload-duration-cap")
    classified = acquisitions.refusal_for(error)
    assert classified.rule == "upload-duration-cap"
    assert classified.remediation == uploads.REMEDIATIONS["upload-duration-cap"]


# --- routes -----------------------------------------------------------------


def test_routes_are_registered_through_discovery(client: Any, make_env: Callable[..., Env]) -> None:
    """No edit to `api/main.py` was needed: the module is found by name.

    Asserted at both ends — discovery lists the module, and the registered app
    really dispatches to it — because a router that exists but is not reachable
    is the failure the registry's ordering rules exist to prevent.
    """
    from meetingminer.api.registry import discover_routers

    assert "uploads" in {name for name, _ in discover_routers()}

    declared = {
        (route.path, method)
        for route in api_uploads.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert ("/uploads", "POST") in declared
    assert ("/uploads/{upload_session_id}", "GET") in declared
    assert ("/uploads/{upload_session_id}", "DELETE") in declared

    make_env()
    reachable = client.get(f"/uploads/{uuid.uuid4()}")
    assert reachable.status_code == 404
    assert refusal(reachable)[0] == "upload-session-not-found"


# --- the happy paths --------------------------------------------------------


def test_transcript_only_session_is_first_class(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    response = post_session(client, data=fields(), files=[vtt_part()])
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["title"] == TITLE
    assert body["startedAt"] == STARTED_AT
    assert body["corpus"] == "real"
    assert body["transcriptDialect"] == "zoom"
    assert [f["canonical"] for f in body["files"]] == ["transcript.vtt"]
    assert body["files"][0]["originalFilename"] == "Migration Sync.vtt"
    assert body["files"][0]["byteSize"] == len(ZOOM_VTT)

    directories = env.session_dirs()
    assert [d.name for d in directories] == [body["uploadSessionId"]]
    assert (directories[0] / "transcript.vtt").read_bytes() == ZOOM_VTT
    # Nothing was minted, and nothing can read this directory as a drop.
    assert env.drop_dirs() == []
    assert not (directories[0] / METADATA_FILENAME).exists()


def test_recording_and_transcript_stage_together(
    client: Any, make_env: Callable[..., Env], ffprobe_present: None
) -> None:
    env = make_env()
    response = post_session(
        client, data=fields(), files=[mp4_part(b"pretend mp4 bytes"), vtt_part()]
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Canonical drop order, so the primary evidence file is first and identity
    # does not depend on the order the browser sent the parts in.
    assert [f["canonical"] for f in body["files"]] == ["recording.mp4", "transcript.vtt"]
    directory = env.uploads_root / body["uploadSessionId"]
    assert (directory / "recording.mp4").read_bytes() == b"pretend mp4 bytes"
    assert (directory / "transcript.vtt").read_bytes() == ZOOM_VTT


def test_a_plain_txt_needs_no_declared_dialect(client: Any, make_env: Callable[..., Env]) -> None:
    """The dialect is only load-bearing for a ``.vtt``; a ``.txt`` is a ``.txt``."""
    make_env()
    response = post_session(
        client, data=fields(transcriptDialect=None), files=[txt_part()]
    )
    assert response.status_code == 201, response.text
    assert response.json()["transcriptDialect"] == "plain"


def test_the_staging_directory_is_under_the_dot_staging_area(
    client: Any, make_env: Callable[..., Env]
) -> None:
    """Where the bytes land is the guarantee, so it is asserted as one."""
    env = make_env()
    response = post_session(client, data=fields(), files=[vtt_part()])
    directory = env.uploads_root / response.json()["uploadSessionId"]
    relative = directory.relative_to(env.drops)
    assert relative.parts[0] == mintdrop.STAGING_DIRNAME
    assert relative.parts[1] == uploads.UPLOADS_DIRNAME
    # `mint-drop`'s own scan for an already-minted drop prunes dot directories,
    # so a session can never be mistaken for one.
    assert mintdrop.find_existing_drop(env.drops, "sha256:whatever") is None


# --- the refusals -----------------------------------------------------------


@pytest.mark.parametrize("missing", ["title", "startedAt", "corpus"])
def test_missing_metadata_is_refused_by_name(
    client: Any, make_env: Callable[..., Env], missing: str
) -> None:
    env = make_env()
    response = post_session(client, data=fields(**{missing: None}), files=[vtt_part()])
    assert response.status_code == 400
    rule, detail = refusal(response)
    assert rule == "upload-metadata-missing"
    assert missing in detail
    assert env.session_dirs() == []


@pytest.mark.parametrize("value", ["2026-08-05", "2026-08-05T12:00:19", "not a time"])
def test_a_start_without_a_time_and_offset_is_refused(
    client: Any, make_env: Callable[..., Env], value: str
) -> None:
    """A date is not a start time, and a stamp without an offset is ambiguous."""
    env = make_env()
    response = post_session(client, data=fields(startedAt=value), files=[vtt_part()])
    assert response.status_code == 400
    assert refusal(response)[0] == "upload-started-at-invalid"
    assert env.session_dirs() == []


def test_an_offset_other_than_z_is_accepted_and_normalized(
    client: Any, make_env: Callable[..., Env]
) -> None:
    make_env()
    response = post_session(
        client, data=fields(startedAt="2026-08-05T08:00:19-04:00"), files=[vtt_part()]
    )
    assert response.status_code == 201, response.text
    # The same instant, spelled the way the drop schema spells it.
    assert response.json()["startedAt"] == STARTED_AT


def test_a_vtt_without_a_declared_dialect_is_refused(
    client: Any, make_env: Callable[..., Env]
) -> None:
    env = make_env()
    response = post_session(client, data=fields(transcriptDialect=None), files=[vtt_part()])
    assert response.status_code == 400
    assert refusal(response)[0] == "upload-dialect-undeclared"
    assert env.session_dirs() == []


def test_an_unknown_dialect_is_refused(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    response = post_session(client, data=fields(transcriptDialect="webex"), files=[vtt_part()])
    assert response.status_code == 400
    assert refusal(response)[0] == "upload-metadata-invalid"
    assert env.session_dirs() == []


def test_scripted_corpus_is_refused(client: Any, make_env: Callable[..., Env]) -> None:
    """An eval subject is minted on the host, not uploaded through a browser."""
    env = make_env()
    response = post_session(client, data=fields(corpus="scripted"), files=[vtt_part()])
    assert response.status_code == 400
    rule, detail = refusal(response)
    assert rule == "upload-metadata-invalid"
    assert "mint-drop" in detail
    assert env.session_dirs() == []


def test_an_unsupported_file_type_is_refused(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    response = post_session(
        client, data=fields(), files=[("files", ("agenda.pdf", b"%PDF-1.7", "application/pdf"))]
    )
    assert response.status_code == 415
    assert refusal(response)[0] == "upload-unsupported-type"
    assert env.session_dirs() == []


def test_two_files_for_one_role_are_refused(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    response = post_session(
        client,
        data=fields(transcriptDialect=None),
        files=[txt_part("one.txt"), txt_part("two.txt")],
    )
    assert response.status_code == 400
    assert refusal(response)[0] == "upload-duplicate-role"
    assert env.session_dirs() == []


def multipart_body(parts: list[tuple[str, str]], boundary: str = "mmboundary") -> bytes:
    """A hand-built multipart body of text fields only.

    Built by hand because an HTTP client with no files to send falls back to
    urlencoded, and "a complete set of metadata and no evidence" is exactly the
    shape this endpoint has to refuse.
    """
    chunks: list[bytes] = []
    for name, value in parts:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        chunks.append(value.encode("utf-8") + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks)


def test_a_session_with_no_evidence_is_refused(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    response = client.post(
        "/uploads",
        content=multipart_body(list(fields().items())),
        headers={"content-type": "multipart/form-data; boundary=mmboundary"},
    )
    assert response.status_code == 400
    assert refusal(response)[0] == "upload-no-evidence"
    assert env.session_dirs() == []


def test_an_empty_file_is_refused(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    response = post_session(client, data=fields(), files=[vtt_part(body=b"")])
    assert response.status_code == 400
    assert refusal(response)[0] == "upload-empty-file"
    assert env.session_dirs() == []


def test_an_unknown_field_is_refused_rather_than_ignored(
    client: Any, make_env: Callable[..., Env]
) -> None:
    """A misspelled field is reported as the typo it is, not as a missing one."""
    env = make_env()
    data = fields()
    data["titel"] = TITLE
    response = post_session(client, data=data, files=[vtt_part()])
    assert response.status_code == 400
    rule, detail = refusal(response)
    assert rule == "upload-unknown-field"
    assert "titel" in detail
    assert env.session_dirs() == []


def test_a_file_over_its_cap_is_refused_mid_stream(
    client: Any, make_env: Callable[..., Env]
) -> None:
    """The cap is enforced as the bytes arrive, not from Content-Length alone."""
    env = make_env(max_transcript_bytes=512)
    response = post_session(
        client, data=fields(transcriptDialect=None), files=[txt_part(body=b"x" * 4096)]
    )
    assert response.status_code == 413
    rule, detail = refusal(response)
    assert rule == "upload-too-large"
    assert "512" in detail
    assert env.session_dirs() == []


def test_a_declared_length_over_the_body_cap_is_refused_before_a_directory_exists(
    make_env: Callable[..., Env],
) -> None:
    """The Content-Length short-circuit costs no directory and reads no body."""
    env = make_env()
    limits = uploads.UploadLimits.from_config(env.config)

    async def _never() -> Any:
        raise AssertionError("the body must not be read")
        yield b""  # pragma: no cover - makes this an async generator

    import asyncio

    with pytest.raises(uploads.UploadRefused) as caught:
        asyncio.run(
            uploads.create_session(
                root=env.uploads_root,
                content_type="multipart/form-data; boundary=abc",
                content_length=limits.max_body_bytes + 1,
                body=_never(),
                limits=limits,
                now=datetime.now(timezone.utc),
            )
        )
    assert caught.value.rule == "upload-too-large"
    assert env.session_dirs() == []


def test_a_body_that_is_not_multipart_is_refused(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    response = client.post("/uploads", json={"title": TITLE})
    assert response.status_code == 400
    assert refusal(response)[0] == "upload-not-multipart"
    assert env.session_dirs() == []


def test_a_malformed_multipart_body_is_refused(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    response = client.post(
        "/uploads",
        content=b"--boundary\r\nnot a part at all",
        headers={"content-type": "multipart/form-data; boundary=boundary"},
    )
    assert response.status_code == 400
    assert refusal(response)[0] in {"upload-malformed", "upload-no-evidence"}
    assert env.session_dirs() == []


def test_a_recording_that_is_not_a_video_is_refused(
    client: Any, make_env: Callable[..., Env], ffprobe_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env()
    monkeypatch.setattr(
        uploads,
        "probe_media",
        lambda _path: (_ for _ in ()).throw(uploads.MediaToolError("moov atom not found")),
    )
    response = post_session(
        client, data=fields(transcriptDialect=None), files=[mp4_part(b"not really a video")]
    )
    assert response.status_code == 415
    assert refusal(response)[0] == "upload-not-a-video"
    assert env.session_dirs() == []


def test_a_recording_over_the_duration_cap_is_refused(
    client: Any, make_env: Callable[..., Env], ffprobe_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(max_duration_minutes=60)

    def _long(_path: Path) -> Any:
        facts = _probe_ok(_path)
        return type(facts)(duration_ms=61 * 60_000)

    monkeypatch.setattr(uploads, "probe_media", _long)
    response = post_session(
        client, data=fields(transcriptDialect=None), files=[mp4_part(b"long video")]
    )
    assert response.status_code == 422
    rule, detail = refusal(response)
    assert rule == "upload-duration-cap"
    assert "60-minute cap" in detail
    assert env.session_dirs() == []


def test_a_missing_ffprobe_names_the_tool_not_the_file(
    client: Any, make_env: Callable[..., Env], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env()
    monkeypatch.setattr(uploads.shutil, "which", lambda _name: None)
    response = post_session(
        client, data=fields(transcriptDialect=None), files=[mp4_part(b"video bytes")]
    )
    assert response.status_code == 503
    assert refusal(response)[0] == "upload-probe-unavailable"
    assert env.session_dirs() == []


# --- reading, discarding, sweeping ------------------------------------------


def test_a_session_can_be_read_back_and_discarded(client: Any, make_env: Callable[..., Env]) -> None:
    env = make_env()
    created = post_session(client, data=fields(), files=[vtt_part()]).json()
    session_id = created["uploadSessionId"]

    fetched = client.get(f"/uploads/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    deleted = client.delete(f"/uploads/{session_id}")
    assert deleted.status_code == 204
    assert env.session_dirs() == []

    gone = client.get(f"/uploads/{session_id}")
    assert gone.status_code == 404
    assert refusal(gone)[0] == "upload-session-not-found"
    assert client.delete(f"/uploads/{session_id}").status_code == 404


def test_an_unknown_session_id_is_a_named_404(client: Any, make_env: Callable[..., Env]) -> None:
    make_env()
    response = client.get(f"/uploads/{uuid.uuid4()}")
    assert response.status_code == 404
    assert refusal(response)[0] == "upload-session-not-found"


def test_a_malformed_session_id_never_reaches_the_filesystem(
    client: Any, make_env: Callable[..., Env]
) -> None:
    make_env()
    assert client.get("/uploads/../../etc").status_code in {404, 422}
    assert client.get("/uploads/not-a-uuid").status_code == 422


def test_an_expired_session_is_swept_by_the_next_upload(
    client: Any, make_env: Callable[..., Env]
) -> None:
    env = make_env(session_ttl_minutes=1)
    stale = post_session(client, data=fields(), files=[vtt_part()]).json()["uploadSessionId"]
    directory = env.uploads_root / stale

    # Age it by rewriting the one field the sweep reads.
    session = json.loads((directory / uploads.SESSION_FILENAME).read_text(encoding="utf-8"))
    session["expiresAt"] = "2020-01-01T00:00:00Z"
    (directory / uploads.SESSION_FILENAME).write_text(json.dumps(session), encoding="utf-8")

    fresh = post_session(client, data=fields(), files=[vtt_part()]).json()["uploadSessionId"]
    assert [d.name for d in env.session_dirs()] == [fresh]


def test_the_sweep_leaves_an_upload_in_flight_alone(make_env: Callable[..., Env]) -> None:
    """A directory with no session file yet is an upload still arriving."""
    env = make_env(session_ttl_minutes=60)
    limits = uploads.UploadLimits.from_config(env.config)
    in_flight = env.uploads_root / str(uuid.uuid4())
    in_flight.mkdir(parents=True)
    foreign = env.uploads_root / "not-a-session-id"
    foreign.mkdir()

    assert uploads.sweep_expired(env.uploads_root, limits, now=datetime.now(timezone.utc)) == []
    assert in_flight.is_dir()
    # And it only ever deletes what it can prove it made.
    assert foreign.is_dir()
    later = datetime.now(timezone.utc) + timedelta(minutes=61)
    assert uploads.sweep_expired(env.uploads_root, limits, now=later) == [in_flight.name]
    assert foreign.is_dir()


# --- the acquisition ---------------------------------------------------------


@pytest.fixture()
def no_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """The launch starts no process; the runner is driven directly instead."""

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no test here may start the detached child")

    monkeypatch.setattr(acquisitions.subprocess, "Popen", _boom)


@pytest.fixture()
def sleeping_child(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """A child that exists and does nothing, so a record has a live pid."""
    import subprocess

    started: list[Any] = []
    real_popen = subprocess.Popen

    def _popen(*args: Any, **kwargs: Any) -> Any:
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(
        acquisitions, "child_command", lambda *args, **kwargs: ["/bin/sleep", "30"]
    )
    monkeypatch.setattr(acquisitions.subprocess, "Popen", _popen)
    yield started
    for process in started:
        process.kill()
        process.wait()


def start_acquisition(client: Any, session_id: str) -> Any:
    return client.post("/acquisitions", json={"uploadSessionId": session_id})


def test_naming_both_sources_or_neither_is_refused(
    client: Any, make_env: Callable[..., Env], no_child: None
) -> None:
    make_env()
    both = client.post(
        "/acquisitions",
        json={"url": "https://youtu.be/aB3dEfGhIj0", "uploadSessionId": str(uuid.uuid4())},
    )
    assert both.status_code == 400
    assert both.json()["type"].endswith("acquisition-source-ambiguous")

    neither = client.post("/acquisitions", json={})
    assert neither.status_code == 400
    assert neither.json()["type"].endswith("acquisition-source-missing")


def test_an_unknown_session_cannot_be_acquired(
    client: Any, make_env: Callable[..., Env], no_child: None
) -> None:
    make_env()
    response = start_acquisition(client, str(uuid.uuid4()))
    assert response.status_code == 404
    assert refusal(response)[0] == "upload-session-not-found"


def test_launching_an_upload_acquisition_claims_the_session(
    client: Any, make_env: Callable[..., Env], sleeping_child: list[Any]
) -> None:
    env = make_env()
    session_id = post_session(client, data=fields(), files=[vtt_part()]).json()["uploadSessionId"]

    accepted = start_acquisition(client, session_id)
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["kind"] == "upload"
    assert body["sourceId"] == f"upload:{session_id}"
    assert body["status"] == "queued"

    status = client.get(f"/acquisitions/{body['acquisitionId']}")
    assert status.status_code == 200
    reported = status.json()
    assert reported["kind"] == "upload"
    assert reported["uploadSessionId"] == session_id
    assert reported["url"] == f"upload:{session_id}"

    # A second launch for the same session collides rather than consuming the
    # directory twice.
    again = start_acquisition(client, session_id)
    assert again.status_code == 409
    assert env.session_dirs()  # still staged; the runner has not run


def test_the_runner_mints_posts_and_removes_the_session(
    client: Any,
    make_env: Callable[..., Env],
    sleeping_child: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = make_env()
    session_id = post_session(client, data=fields(), files=[vtt_part()]).json()["uploadSessionId"]
    accepted = start_acquisition(client, session_id).json()

    monkeypatch.undo()  # the must-not-mint stub: the runner is the one place that may
    monkeypatch.setattr(api_main.app.state, "config", env.config)
    posted: list[Path] = []

    def _post_ingest(_api_url: str, drop_path: Path) -> tuple[str, int, str]:
        posted.append(drop_path)
        return ("created", 201, "0f7c3a52-6d41-4a0e-9b8e-2d5f1c9a7e30")

    monkeypatch.setattr(acquisitions, "post_ingest", _post_ingest)

    record = acquisitions.run_upload_acquisition(
        env.config, accepted["acquisitionId"], session_id, state_root=env.acquisitions_root
    )

    assert record.status == "posted"
    assert record.result == "created"
    assert record.job_id == "0f7c3a52-6d41-4a0e-9b8e-2d5f1c9a7e30"
    assert record.source_id.startswith("sha256:")
    assert record.tool == acquisitions.PROGRAM_UPLOAD_TOOL

    # One whole drop, valid against the contract intake validates against.
    drops = env.drop_dirs()
    assert len(drops) == 1
    assert posted == drops
    read_drop(drops[0], config_path=env.config.config_path)
    metadata = read_metadata(drops[0])
    assert metadata["corpus"] == "real"
    assert metadata["startedAt"] == STARTED_AT
    assert metadata["startedAtPrecision"] == "second"
    assert metadata["provenance"]["title"] == TITLE
    assert metadata["provenance"]["tool"] == acquisitions.PROGRAM_UPLOAD_TOOL
    # The zoom conversion happened on the way in, so the drop holds both files.
    assert (drops[0] / "transcript.txt").is_file()
    assert (drops[0] / "transcript.vtt").is_file()
    assert b"Alice Chen" in (drops[0] / "transcript.txt").read_bytes()
    # The person's own filename survives nowhere else: the staging path in
    # `provenance.files` is about to stop existing.
    uploaded = metadata["provenance"]["uploadSession"]["files"]
    assert [f["originalFilename"] for f in uploaded] == ["Migration Sync.vtt"]

    # And the session is gone.
    assert env.session_dirs() == []
    assert client.get(f"/uploads/{session_id}").status_code == 404


def test_a_failed_acquisition_still_removes_the_session(
    client: Any,
    make_env: Callable[..., Env],
    sleeping_child: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = make_env()
    session_id = post_session(client, data=fields(), files=[vtt_part()]).json()["uploadSessionId"]
    accepted = start_acquisition(client, session_id).json()

    monkeypatch.undo()
    monkeypatch.setattr(api_main.app.state, "config", env.config)
    monkeypatch.setattr(
        acquisitions,
        "mint",
        lambda **kwargs: (_ for _ in ()).throw(mintdrop.MintError("the drops root is full")),
    )

    record = acquisitions.run_upload_acquisition(
        env.config, accepted["acquisitionId"], session_id, state_root=env.acquisitions_root
    )

    assert record.status == "failed"
    assert record.refusal is not None
    assert record.refusal.rule == "mint-refused"
    assert "drops root is full" in record.refusal.detail
    assert record.refusal.remediation.strip()
    assert env.drop_dirs() == []
    assert env.session_dirs() == []


def test_an_intake_failure_keeps_the_drop_and_names_the_re_post(
    client: Any,
    make_env: Callable[..., Env],
    sleeping_child: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drop is finalized by then, so re-uploading would mint nothing new."""
    env = make_env()
    session_id = post_session(client, data=fields(), files=[vtt_part()]).json()["uploadSessionId"]
    accepted = start_acquisition(client, session_id).json()

    monkeypatch.undo()
    monkeypatch.setattr(api_main.app.state, "config", env.config)
    monkeypatch.setattr(
        acquisitions,
        "post_ingest",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            mintdrop.IntakeError("connection refused")
        ),
    )

    record = acquisitions.run_upload_acquisition(
        env.config, accepted["acquisitionId"], session_id, state_root=env.acquisitions_root
    )

    assert record.status == "failed"
    assert record.refusal is not None
    assert record.refusal.rule == "intake-failed"
    assert "curl" in record.refusal.remediation
    assert len(env.drop_dirs()) == 1
    assert env.session_dirs() == []


# --- one meeting, whichever door --------------------------------------------


def test_an_upload_and_a_hand_mint_produce_one_identity(
    client: Any,
    make_env: Callable[..., Env],
    sleeping_child: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The story's real requirement: the same bytes are the same meeting.

    One transcript is minted the way ``mint-drop`` mints it — the CLI's own call
    order, ``convert_supplied`` then ``mint`` — and the other is uploaded and
    acquired. Identical ``sourceId`` and identical ``startedAt`` pair, and the
    second reaches ``exists`` rather than minting a second write-once drop.
    """
    env = make_env()
    session_id = post_session(client, data=fields(), files=[vtt_part()]).json()["uploadSessionId"]
    accepted = start_acquisition(client, session_id).json()

    monkeypatch.undo()
    monkeypatch.setattr(api_main.app.state, "config", env.config)
    monkeypatch.setattr(acquisitions, "post_ingest", lambda *a, **k: ("created", 201, None))

    # The hand mint, from the operator's own copy of the same bytes.
    hand = tmp_path / "operator" / "Migration Sync.vtt"
    hand.parent.mkdir(parents=True, exist_ok=True)
    hand.write_bytes(ZOOM_VTT)
    with uploads.dialects.workspace() as workspace:
        conversion = uploads.dialects.convert_supplied(
            [str(hand)], dialect="zoom", into=workspace
        )
        minted = mintdrop.mint(
            supplied=conversion.supplied,
            corpus="real",
            drops_root=env.drops,
            config_path=env.config.config_path,
            title=TITLE,
            started_at_argument=STARTED_AT,
            identity_root=env.drops,
            provenance_extra=conversion.provenance_extra,
        )
    assert minted.status == "created"

    uploaded = acquisitions.run_upload_acquisition(
        env.config, accepted["acquisitionId"], session_id, state_root=env.acquisitions_root
    )

    assert uploaded.source_id == minted.source_id
    # The content decided, so the second run found the first drop instead of
    # writing a second one for the same meeting.
    assert uploaded.result == "exists"
    assert len(env.drop_dirs()) == 1

    metadata = read_metadata(minted.path)
    assert metadata["startedAt"] == STARTED_AT
    assert metadata["startedAtPrecision"] == "second"
    assert env.session_dirs() == []


def test_the_source_id_is_the_digest_of_the_bytes_that_enter_the_drop(
    client: Any,
    make_env: Callable[..., Env],
    sleeping_child: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not the digest of what was uploaded — the two differ for ``zoom``.

    The conversion produces the transcript the drop holds, so identity follows
    the converted bytes. Asserted directly because getting it backwards is the
    mistake that makes one meeting into two.
    """
    env = make_env()
    created = post_session(client, data=fields(), files=[vtt_part()]).json()
    session_id = created["uploadSessionId"]
    uploaded_digest = created["files"][0]["sha256"]
    accepted = start_acquisition(client, session_id).json()

    monkeypatch.undo()
    monkeypatch.setattr(api_main.app.state, "config", env.config)
    monkeypatch.setattr(acquisitions, "post_ingest", lambda *a, **k: ("created", 201, None))

    record = acquisitions.run_upload_acquisition(
        env.config, accepted["acquisitionId"], session_id, state_root=env.acquisitions_root
    )

    drop = env.drop_dirs()[0]
    # The primary file is the first canonical name the drop holds, which for a
    # converted Zoom transcript is the produced `transcript.vtt` — not the
    # `.txt` beside it, and not the file that was uploaded.
    primary = next(name for name in EVIDENCE_FILENAMES if (drop / name).is_file())
    assert primary == "transcript.vtt"
    primary_digest, _ = mintdrop.sha256_and_size(drop / primary)
    assert record.source_id == f"sha256:{primary_digest}"
    assert record.source_id != f"sha256:{uploaded_digest}"


def test_a_plain_upload_keeps_the_uploaded_digest(
    client: Any,
    make_env: Callable[..., Env],
    sleeping_child: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no conversion, the bytes that arrived are the bytes that enter."""
    env = make_env()
    created = post_session(
        client, data=fields(transcriptDialect=None), files=[txt_part()]
    ).json()
    session_id = created["uploadSessionId"]
    accepted = start_acquisition(client, session_id).json()

    monkeypatch.undo()
    monkeypatch.setattr(api_main.app.state, "config", env.config)
    monkeypatch.setattr(acquisitions, "post_ingest", lambda *a, **k: ("created", 201, None))

    record = acquisitions.run_upload_acquisition(
        env.config, accepted["acquisitionId"], session_id, state_root=env.acquisitions_root
    )
    assert record.source_id == f"sha256:{created['files'][0]['sha256']}"


@pytest.mark.slow(reason="builds a real mp4 with ffmpeg and probes it; ~2s of tool time")
def test_a_real_recording_passes_the_video_and_duration_checks(
    client: Any,
    make_env: Callable[..., Env],
    monkeypatch: pytest.MonkeyPatch,
    synthetic_recording: Path,
) -> None:
    """The one row that uses the real ffprobe rather than a stubbed one."""
    env = make_env()
    monkeypatch.undo()  # restore the real probe_media and shutil.which
    monkeypatch.setattr(api_main.app.state, "config", env.config)
    response = post_session(
        client,
        data=fields(transcriptDialect=None),
        files=[mp4_part(synthetic_recording.read_bytes())],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert [f["canonical"] for f in body["files"]] == ["recording.mp4"]
    staged = env.uploads_root / body["uploadSessionId"] / "recording.mp4"
    assert staged.read_bytes() == synthetic_recording.read_bytes()


def test_a_staged_session_is_not_a_drop_intake_will_take(
    client: Any, make_env: Callable[..., Env]
) -> None:
    """The last line of the guarantee, asserted at the intake door itself."""
    env = make_env()
    session_id = post_session(client, data=fields(), files=[vtt_part()]).json()["uploadSessionId"]
    directory = env.uploads_root / session_id

    response = client.post("/ingests", json={"dropPath": str(directory)})
    assert response.status_code >= 400
    assert re.search(r"metadata|drop", response.text, re.IGNORECASE)
