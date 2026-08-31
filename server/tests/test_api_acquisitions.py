"""The acquisition launch surface (story 6.4).

Offline by construction, like ``test_youtube.py``: ``yt-dlp`` is never on the
PATH these tests see, ``youtube.probe`` answers from the recorded
``info.json`` fixtures, and the only child process any test starts is
``/bin/sleep`` — enough to give a status record a live pid, and incapable of
reaching a network.

Two properties are asserted everywhere rather than in one place, because they
are what the story *is*:

* **The api does no acquisition work.** Every request-handler test installs
  must-not-run stubs over ``yt-dlp``, ``download()`` and ``mint()``, so a
  handler that started doing the work fails loudly rather than slowly.
* **A refusal is fields, not prose.** The ``failed`` rows assert
  ``refusal.rule`` / ``detail`` / ``remediation`` with the log file empty or
  absent, which is the clause a web client depends on.

Every drop these tests touch lives in a ``tmp_path`` drops root, and every
``.logs/acquisitions`` directory is anchored on a ``tmp_path`` stand-in for
the repo root — the api's config is swapped per test, so the real ``.logs/``
is never written.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from fastapi.routing import APIRoute
from psycopg_pool import ConnectionPool

import meetingminer.api.acquisitions as api_acquisitions
import meetingminer.api.main as api_main
from meetingminer import acquisitions, mintdrop, youtube
from meetingminer.config import AppConfig

from repo_paths import REPO_ROOT

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "youtube"
SCHEMA_SOURCE = REPO_ROOT / "docs" / "source-drop.schema.json"

VALID_ID = "aB3dEfGhIj0"
WATCH_URL = f"https://www.youtube.com/watch?v={VALID_ID}"
SOURCE_ID = f"youtube:{VALID_ID}"

OTHER_ID = "Zz9YxWvUtS1"
OTHER_URL = f"https://youtu.be/{OTHER_ID}"

PROBLEM_MEDIA_TYPE = "application/problem+json"


# --- helpers ---------------------------------------------------------------


def info_fixture(name: str, **overrides: Any) -> dict[str, Any]:
    info = json.loads((FIXTURES / f"{name}.info.json").read_text(encoding="utf-8"))
    info.update(overrides)
    return info


def _must_not_run(name: str) -> Callable[..., Any]:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{name} must not be invoked")

    return _boom


def dead_pid() -> int:
    """A pid that certainly names nothing: a child started and fully reaped."""
    process = subprocess.Popen(["/bin/echo"], stdout=subprocess.DEVNULL)
    process.wait()
    return process.pid


# Copied, not imported, from `test_youtube.py`: this story owns its fixtures,
# so a later edit there cannot silently change what `exists` means here.
def write_existing_youtube_drop(root: Path) -> tuple[Path, dict[str, Any]]:
    drop = root / mintdrop.drop_name(
        "2026-08-12T15:30:19Z", "Platform Sync — August", SOURCE_ID
    )
    drop.mkdir()
    recording = drop / "recording.mp4"
    recording.write_bytes(b"existing youtube recording")
    digest, size = mintdrop.sha256_and_size(recording)
    metadata = {
        "schemaVersion": 1,
        "sourceId": SOURCE_ID,
        "corpus": "real",
        "startedAt": "2026-08-12T15:30:19Z",
        "startedAtPrecision": "second",
        "provenance": {
            "tool": "youtube-drop",
            "title": "Platform Sync — August",
            "mintedAt": "2026-08-30T12:00:00Z",
            "suppliedBy": "test",
            "startedAtSource": "release_timestamp",
            "url": WATCH_URL,
            "channel": "MeetingMiner Sandbox",
            "durationSeconds": 1830,
            "ytDlpVersion": "2026.07.04",
            "formatId": "137+140",
            "files": [
                {
                    "dropFilename": "recording.mp4",
                    "sourcePath": "/private/tmp/source.mp4",
                    "sha256": digest,
                    "byteSize": size,
                }
            ],
        },
    }
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return drop, metadata


def mint_result(drop: Path, *, status: str = "created") -> mintdrop.MintResult:
    return mintdrop.MintResult(
        status=status,
        path=drop,
        source_id=SOURCE_ID,
        metadata={
            "sourceId": SOURCE_ID,
            "corpus": "real",
            "startedAt": "2026-08-12T15:30:19Z",
            "startedAtPrecision": "second",
            "provenance": {
                "tool": "youtube-drop",
                "ytDlpVersion": "2026.07.04",
                "files": [{"dropFilename": "recording.mp4"}],
            },
        },
    )


@dataclass(frozen=True)
class Env:
    """One test's isolated api: its own `.logs/` anchor and drops root."""

    config: AppConfig
    root: Path
    drops: Path

    def record(self, **overrides: Any) -> acquisitions.AcquisitionRecord:
        """Write a status record straight to the file, as the child would."""
        fields: dict[str, Any] = {
            "acquisition_id": str(uuid.uuid4()),
            "source_id": SOURCE_ID,
            "url": WATCH_URL,
            "status": "queued",
            "created_at": "2026-08-30T12:00:00Z",
            "updated_at": "2026-08-30T12:00:00Z",
        }
        fields.update(overrides)
        record = acquisitions.AcquisitionRecord(**fields)
        acquisitions.write_record(self.root, record)
        return record


@pytest.fixture()
def make_env(
    client: Any, app_config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Env]:
    """Point the running app at a throwaway repo root and drops root.

    `.logs/acquisitions` is anchored on `config.config_path.parent` (story
    1.10, finding 17), so swapping the config is all it takes to keep every
    status file inside `tmp_path`. `docs/source-drop.schema.json` is copied
    beside it because `read_drop` resolves the schema the same way.
    """
    counter = 0

    def _make(*, cap_minutes: int = 180) -> Env:
        nonlocal counter
        counter += 1
        home = tmp_path / f"host{counter}"
        (home / "docs").mkdir(parents=True)
        shutil.copy(SCHEMA_SOURCE, home / "docs" / SCHEMA_SOURCE.name)
        drops = tmp_path / f"drops{counter}"
        drops.mkdir()
        settings = app_config.settings
        config = app_config.model_copy(
            update={
                "config_path": home / "config.yaml",
                "secrets": app_config.secrets.model_copy(
                    update={"mm_drops_root": drops}
                ),
                "settings": settings.model_copy(
                    update={
                        "acquisition": settings.acquisition.model_copy(
                            update={
                                "youtube": settings.acquisition.youtube.model_copy(
                                    update={"max_duration_minutes": cap_minutes}
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
            root=acquisitions.acquisitions_root(config),
            drops=drops,
        )

    return _make


@pytest.fixture()
def env(make_env: Callable[..., Env]) -> Env:
    return make_env()


@pytest.fixture(autouse=True)
def no_acquisition_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-11, as a stub: nothing here may run a tool, download, or mint.

    Autouse, so a route that starts doing acquisition work in-process fails in
    every test rather than in the one that remembered to check.
    """
    monkeypatch.setattr(youtube, "_run", _must_not_run("yt-dlp"))
    monkeypatch.setattr(youtube, "download", _must_not_run("yt-dlp download"))
    monkeypatch.setattr(youtube, "mint", _must_not_run("mint()"))
    monkeypatch.setattr(mintdrop, "mint", _must_not_run("mint()"))


@pytest.fixture()
def tools_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both CLI tools 'installed', without touching the real PATH."""
    monkeypatch.setattr(shutil, "which", lambda name: f"/stub/bin/{name}")


@pytest.fixture()
def no_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)


@pytest.fixture()
def sleeping_children(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[subprocess.Popen[bytes]]]:
    """Replace the child's argv with `/bin/sleep`, and reap what starts.

    The launch path itself is real — the same `Popen`, the same detached
    session, the same log file — so the pid a status record carries is a pid
    that is genuinely alive. Only the program is swapped, which is what keeps
    the suite off the network.
    """
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def _popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(
        acquisitions,
        "child_command",
        lambda _id, _url, _root: ["/bin/sleep", "30"],
    )
    monkeypatch.setattr(acquisitions.subprocess, "Popen", _popen)
    yield started
    for process in started:
        process.kill()
        process.wait()


@pytest.fixture()
def no_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """No request may start a process at all (the probe, and every refusal)."""
    monkeypatch.setattr(
        acquisitions.subprocess, "Popen", _must_not_run("a child process")
    )


def seed_job_and_meeting(pool: ConnectionPool, source_id: str) -> tuple[str, str]:
    """One `job` row and the `meeting` the worker would mint for it."""
    with pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_relative_path, corpus, status)"
            " VALUES (%s, %s, 'real', 'running') RETURNING id",
            (source_id, source_id),
        ).fetchone()[0]
        meeting_id = conn.execute(
            "INSERT INTO meeting (job_id, source_id, corpus, started_at,"
            " started_at_precision, title, has_recording)"
            " VALUES (%s, %s, 'real', '2026-08-12T15:30:19Z', 'second',"
            " 'Platform Sync', true) RETURNING id",
            (job_id, source_id),
        ).fetchone()[0]
    return str(job_id), str(meeting_id)


# --- POST /acquisitions: the launch ----------------------------------------


def test_a_launch_answers_202_and_starts_a_detached_child(
    client: Any, env: Env, sleeping_children: list[Any]
) -> None:
    """The whole contract of the accept: an id, a status file, and a real
    detached process whose stdout is that acquisition's log."""
    response = client.post("/acquisitions", json={"url": WATCH_URL})
    assert response.status_code == 202, response.text
    body = response.json()
    # `kind` joined the accept in story 6.4a, when an acquisition could be
    # started from an upload session as well as from a URL.
    assert set(body) == {"acquisitionId", "sourceId", "status", "kind"}
    assert body["kind"] == "youtube"
    assert body["sourceId"] == SOURCE_ID
    assert body["status"] == "queued"
    acquisition_id = body["acquisitionId"]
    assert str(uuid.UUID(acquisition_id)) == acquisition_id

    record = acquisitions.read_record(env.root, acquisition_id)
    assert record.status == "queued"
    assert record.source_id == SOURCE_ID
    # The canonical watch URL, whatever shape the caller pasted.
    assert record.url == WATCH_URL
    assert acquisitions.pid_is_live(record.pid)
    assert len(sleeping_children) == 1
    assert record.pid == sleeping_children[0].pid
    assert acquisitions.log_path(env.root, acquisition_id).is_file()


def test_the_child_is_detached_with_the_log_open_and_no_stdin(
    client: Any, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detached is asserted at the call, not inferred: an api restart must not
    take a multi-gigabyte download with it."""
    seen: dict[str, Any] = {}
    real_popen = subprocess.Popen

    def _popen(argv: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        seen["log_name"] = kwargs["stdout"].name
        # The status file exists before the child does: a runner that starts
        # first could write a transition into a record nothing has created.
        seen["record_before_start"] = acquisitions.read_record(
            env.root, argv[argv.index("--acquisition-id") + 1]
        ).status
        return real_popen(["/bin/sleep", "30"], **kwargs)

    monkeypatch.setattr(acquisitions.subprocess, "Popen", _popen)
    response = client.post("/acquisitions", json={"url": WATCH_URL})
    assert response.status_code == 202, response.text
    acquisition_id = response.json()["acquisitionId"]
    process = acquisitions.read_record(env.root, acquisition_id).pid
    assert process is not None
    os.kill(process, 9)
    os.waitpid(process, 0)

    assert seen["record_before_start"] == "queued"
    assert seen["kwargs"]["start_new_session"] is True
    assert seen["kwargs"]["stdin"] is subprocess.DEVNULL
    assert seen["kwargs"]["stderr"] is subprocess.STDOUT
    assert seen["log_name"] == str(acquisitions.log_path(env.root, acquisition_id))
    # The runner is reached as a module, never as a path a request could bend.
    assert seen["argv"][:4] == [sys.executable, "-m", "meetingminer.acquisitions", "--run"]
    assert WATCH_URL in seen["argv"]
    assert seen["argv"][seen["argv"].index("--state-root") + 1] == str(env.root)


def test_the_runner_waits_for_the_launch_claim_before_advancing_state(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: the parent owns the first post-Popen write.

    A real child may begin running before ``Popen`` returns in the parent. Its
    first status transition must therefore wait for the parent's claim lock;
    otherwise a fast terminal child write can be overwritten by stale
    ``queued+pid`` state.
    """
    record = env.record()
    acquisition_started = threading.Event()
    finished: list[acquisitions.AcquisitionRecord] = []
    drop = env.drops / "drop"
    drop.mkdir()

    def _acquire(url: str, **kwargs: Any) -> mintdrop.MintResult:
        acquisition_started.set()
        return mint_result(drop, status="exists")

    monkeypatch.setattr(youtube, "acquire", _acquire)
    monkeypatch.setattr(
        acquisitions,
        "post_ingest",
        lambda api_url, path: (
            "duplicate",
            409,
            "00000000-0000-0000-0000-000000000001",
        ),
    )

    runner = threading.Thread(
        target=lambda: finished.append(
            acquisitions.run_acquisition(
                env.config, record.acquisition_id, record.url
            )
        )
    )
    with acquisitions.claim_lock(env.root):
        runner.start()
        assert not acquisition_started.wait(timeout=0.1)
        assert acquisitions.read_record(env.root, record.acquisition_id).status == (
            "queued"
        )
    runner.join(timeout=2)

    assert not runner.is_alive()
    assert finished[0].status == "posted"
    assert acquisitions.read_record(env.root, record.acquisition_id).status == (
        "posted"
    )


def test_a_second_launch_for_the_same_source_is_refused_by_conflict(
    client: Any, env: Env, sleeping_children: list[Any]
) -> None:
    """A live acquisition owns its source id; a different one is unaffected."""
    first = client.post("/acquisitions", json={"url": WATCH_URL})
    assert first.status_code == 202, first.text

    conflict = client.post(
        # A different URL shape for the same video: the claim is on the source
        # id, not on the string the caller pasted.
        "/acquisitions",
        json={"url": f"https://youtu.be/{VALID_ID}"},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = conflict.json()
    assert body["type"] == "urn:meetingminer:problem:acquisition-in-progress"
    assert body["rule"] == "acquisition-in-progress"
    assert "poll" in body["remediation"].lower()
    assert "upload session" not in body["remediation"].lower()
    assert body["acquisitionId"] == first.json()["acquisitionId"]
    assert body["sourceId"] == SOURCE_ID

    other = client.post("/acquisitions", json={"url": OTHER_URL})
    assert other.status_code == 202, other.text
    assert other.json()["sourceId"] == f"youtube:{OTHER_ID}"


@pytest.mark.parametrize("finished", ["posted", "failed"])
def test_a_finished_record_does_not_block_a_new_launch(
    client: Any, env: Env, sleeping_children: list[Any], finished: str
) -> None:
    """`posted` and `failed` are terminal: re-acquiring the same video is
    allowed, and gets a new acquisition id."""
    prior = env.record(status=finished, pid=os.getpid())
    response = client.post("/acquisitions", json={"url": WATCH_URL})
    assert response.status_code == 202, response.text
    assert response.json()["acquisitionId"] != prior.acquisition_id


@pytest.mark.parametrize("pid_kind", ["dead", "unset"])
def test_an_abandoned_record_does_not_block_a_new_launch(
    client: Any, env: Env, sleeping_children: list[Any], pid_kind: str
) -> None:
    """A `queued` record whose pid is dead — or never recorded, which can only
    mean the api died mid-claim — is not live."""
    pid = dead_pid() if pid_kind == "dead" else None
    env.record(status="queued", pid=pid)
    response = client.post("/acquisitions", json={"url": WATCH_URL})
    assert response.status_code == 202, response.text


def test_a_bad_url_is_refused_before_any_state_or_process_exists(
    client: Any, env: Env, no_child: None
) -> None:
    """URL classification is offline and wins the ordering race: nothing is
    written and nothing is started for a URL that is not one YouTube video."""
    response = client.post("/acquisitions", json={"url": "https://vimeo.com/1"})
    assert response.status_code == 400, response.text
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["rule"] == "not-a-video-url"
    assert body["remediation"] == acquisitions.REMEDIATIONS["not-a-video-url"]
    assert "vimeo" in body["detail"]
    assert not env.root.exists()


# --- POST /acquisitions/probe ----------------------------------------------


def test_a_probe_answers_exactly_the_four_declared_fields(
    client: Any, env: Env, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(youtube, "probe", lambda url: info_fixture("full"))
    response = client.post("/acquisitions/probe", json={"url": WATCH_URL})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "title": "Platform Sync — August",
        "durationMs": 1_830_000,
        "captions": {"kind": "manual", "language": "en"},
        "sourceId": SOURCE_ID,
    }


def test_a_probe_reports_no_captions_rather_than_refusing(
    client: Any, env: Env, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A video with no English track still mints a recording-only drop, so the
    pre-submit check says so instead of refusing."""
    info = info_fixture("no-english")
    monkeypatch.setattr(youtube, "probe", lambda url: info)
    url = f"https://www.youtube.com/watch?v={info['id']}"
    response = client.post("/acquisitions/probe", json={"url": url})
    assert response.status_code == 200, response.text
    assert response.json()["captions"] is None


def test_a_probe_falls_back_to_the_video_id_when_the_title_is_blank(
    client: Any, env: Env, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same fallback `acquire()` applies, so the preview names the drop
    the acquisition would actually mint."""
    monkeypatch.setattr(youtube, "probe", lambda url: info_fixture("full", title="  "))
    response = client.post("/acquisitions/probe", json={"url": WATCH_URL})
    assert response.status_code == 200, response.text
    assert response.json()["title"] == VALID_ID


@pytest.mark.parametrize("missing", ["publication-time", "publisher"])
def test_a_probe_does_not_require_acquisition_provenance_fields(
    client: Any,
    env: Env,
    tools_present: None,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    """F3: the frozen probe boundary stops before provenance validation."""
    info = info_fixture("full")
    if missing == "publication-time":
        info.pop("release_timestamp", None)
        info.pop("upload_date", None)
    else:
        info.pop("channel", None)
        info.pop("uploader", None)
    monkeypatch.setattr(youtube, "probe", lambda url: info)

    response = client.post("/acquisitions/probe", json={"url": WATCH_URL})

    assert response.status_code == 200, response.text
    assert response.json()["sourceId"] == SOURCE_ID


def test_a_probe_over_the_duration_cap_names_the_config_key(
    client: Any,
    make_env: Callable[..., Env],
    tools_present: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_env(cap_minutes=10)
    monkeypatch.setattr(youtube, "probe", lambda url: info_fixture("full"))
    response = client.post("/acquisitions/probe", json={"url": WATCH_URL})
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["rule"] == "duration-cap"
    assert "10-minute cap" in body["detail"]
    assert youtube.MAX_DURATION_CONFIG_KEY in body["remediation"]


def test_a_probe_on_a_host_without_yt_dlp_is_unavailable_not_invalid(
    client: Any, env: Env, no_tools: None
) -> None:
    """A host-side rule says nothing about the URL, so it is 503, not 4xx."""
    response = client.post("/acquisitions/probe", json={"url": WATCH_URL})
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["rule"] == "tool-missing"
    assert body["title"] == "Service Unavailable"
    assert body["remediation"] == acquisitions.REMEDIATIONS["tool-missing"]


def test_a_probe_on_an_audio_only_video_is_refused_by_name(
    client: Any, env: Env, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = info_fixture("audio-only")
    monkeypatch.setattr(youtube, "probe", lambda url: info)
    url = f"https://www.youtube.com/watch?v={info['id']}"
    response = client.post("/acquisitions/probe", json={"url": url})
    assert response.status_code == 422, response.text
    assert response.json()["rule"] == "no-video-stream"


def test_a_probe_leaves_no_state_no_drop_and_no_process(
    client: Any,
    env: Env,
    tools_present: None,
    no_child: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The clause that makes the probe safe to call on every keystroke."""
    monkeypatch.setattr(youtube, "probe", lambda url: info_fixture("full"))
    assert client.post("/acquisitions/probe", json={"url": WATCH_URL}).status_code == 200
    # And a refusing probe is just as inert.
    assert client.post("/acquisitions/probe", json={"url": "https://vimeo.com/1"}).status_code == 400
    assert not env.root.exists()
    assert list(env.drops.iterdir()) == []


def test_a_bad_probe_url_is_refused_with_the_same_vocabulary(
    client: Any, env: Env, no_child: None
) -> None:
    response = client.post("/acquisitions/probe", json={"url": "not a url"})
    assert response.status_code == 400, response.text
    assert response.json()["rule"] == "not-a-video-url"


# --- GET /acquisitions/{id} -------------------------------------------------


def test_an_unknown_acquisition_id_is_a_problem_json_404(
    client: Any, env: Env
) -> None:
    unknown = uuid.uuid4()
    response = client.get(f"/acquisitions/{unknown}")
    assert response.status_code == 404, response.text
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert str(unknown) in response.json()["detail"]


@pytest.mark.parametrize(
    ("raw_id", "expected"),
    [
        # A well-formed segment that is not a UUID: refused by the typed path
        # parameter, which is what keeps a request from naming a file.
        ("not-a-uuid", 422),
        # A traversal attempt is refused one step earlier still: the decoded
        # path carries separators, so the `{acquisition_id}` segment pattern
        # matches nothing and no route is reached at all.
        ("..%2F..%2Fetc%2Fpasswd", 404),
        ("%2E%2E%2F%2E%2E%2Fetc%2Fpasswd", 404),
    ],
)
def test_a_path_that_is_not_a_uuid_never_becomes_a_filename(
    client: Any,
    env: Env,
    raw_id: str,
    expected: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every path segment that would become a filename is a typed `UUID`, so
    the refusal happens before anything on disk is touched."""
    monkeypatch.setattr(
        acquisitions, "read_record", _must_not_run("a status-file read")
    )
    response = client.get(f"/acquisitions/{raw_id}")
    assert response.status_code == expected, response.text
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)


def test_a_status_file_may_not_lend_its_contents_to_another_id(
    client: Any, env: Env
) -> None:
    """The only string that becomes a path here is the validated path
    parameter. A file whose own `acquisitionId` disagrees with the id it was
    found under is refused rather than served — and it certainly does not get
    to name the log the tail is read from."""
    record = env.record(status="failed")
    path = acquisitions.status_path(env.root, record.acquisition_id)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["acquisitionId"] = "../../etc/passwd"
    path.write_text(json.dumps(body), encoding="utf-8")

    response = client.get(f"/acquisitions/{record.acquisition_id}")
    assert response.status_code == 500, response.text
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json()["type"] == (
        "urn:meetingminer:problem:acquisition-state-unreadable"
    )


def test_a_posted_acquisition_resolves_its_meeting_id_from_postgres(
    client: Any,
    env: Env,
    test_pool: ConnectionPool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner writes the job id; the meeting id is resolved per read,
    because the worker mints that row after intake."""
    job_id, meeting_id = seed_job_and_meeting(test_pool, SOURCE_ID)
    record = env.record()
    drop = env.drops / "drop"
    drop.mkdir()
    monkeypatch.setattr(
        youtube, "acquire", lambda url, **kwargs: mint_result(drop, status="created")
    )
    monkeypatch.setattr(
        acquisitions, "post_ingest", lambda api_url, path: ("created", 201, job_id)
    )
    final = acquisitions.run_acquisition(env.config, record.acquisition_id, WATCH_URL)
    assert final.status == "posted"
    assert final.result == "created"

    body = client.get(f"/acquisitions/{record.acquisition_id}").json()
    assert body["status"] == "posted"
    assert body["result"] == "created"
    assert body["jobId"] == job_id
    assert body["meetingId"] == meeting_id
    assert body["source"] == {
        "sourceId": SOURCE_ID,
        "tool": "youtube-drop",
        "toolVersion": "2026.07.04",
    }
    assert body["refusal"] is None


def test_a_meeting_row_the_worker_has_not_minted_yet_reads_as_null(
    client: Any, env: Env
) -> None:
    """`meetingId` appearing on a later poll is the design, not a bug: the
    status file never carries it."""
    record = env.record(status="posted", result="created", job_id=str(uuid.uuid4()))
    body = client.get(f"/acquisitions/{record.acquisition_id}").json()
    assert body["jobId"] == record.job_id
    assert body["meetingId"] is None


def test_an_already_minted_drop_reaches_posted_exists_with_no_yt_dlp_call(
    client: Any,
    env: Env,
    test_pool: ConnectionPool,
    no_tools: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.2's `exists` short-circuit, end to end through the runner: it
    answers from the drops root, so no tool is checked, no probe is run, and
    not one media byte moves."""
    write_existing_youtube_drop(env.drops)
    job_id, meeting_id = seed_job_and_meeting(test_pool, SOURCE_ID)
    posted: list[Path] = []

    def _post_ingest(api_url: str, path: Path) -> tuple[str, int, str]:
        posted.append(path)
        return "created", 201, job_id

    monkeypatch.setattr(acquisitions, "post_ingest", _post_ingest)
    record = env.record()
    final = acquisitions.run_acquisition(env.config, record.acquisition_id, WATCH_URL)
    assert final.status == "posted"
    assert final.result == "exists"
    # `no_tools` makes `ensure_tools()` a refusal and `no_acquisition_work`
    # makes every yt-dlp invocation an error: reaching `posted` proves neither
    # ran. The drop was still handed to the one intake door.
    assert len(posted) == 1

    body = client.get(f"/acquisitions/{record.acquisition_id}").json()
    assert body["status"] == "posted"
    assert body["result"] == "exists"
    assert body["jobId"] == job_id
    assert body["meetingId"] == meeting_id
    assert body["source"]["toolVersion"] == "2026.07.04"


def test_a_failed_acquisition_explains_itself_without_any_log(
    client: Any, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clause a web client depends on: `rule`, `detail` and `remediation`
    are all present and correct with the log file empty."""
    refusal = youtube.YoutubeError(
        "the video is 30.5 minutes long — over the 10-minute cap",
        rule="duration-cap",
    )

    def _refuse(url: str, **kwargs: Any) -> Any:
        raise refusal

    monkeypatch.setattr(youtube, "acquire", _refuse)
    monkeypatch.setattr(acquisitions, "post_ingest", _must_not_run("POST /ingests"))
    record = env.record()
    final = acquisitions.run_acquisition(env.config, record.acquisition_id, WATCH_URL)
    assert final.status == "failed"

    acquisitions.log_path(env.root, record.acquisition_id).write_bytes(b"")
    body = client.get(f"/acquisitions/{record.acquisition_id}").json()
    assert body["status"] == "failed"
    assert body["logTail"] == []
    assert body["refusal"] == {
        "rule": "duration-cap",
        "detail": "the video is 30.5 minutes long — over the 10-minute cap",
        "remediation": acquisitions.REMEDIATIONS["duration-cap"],
    }
    assert body["result"] is None
    assert body["source"] is None


def test_a_failed_acquisition_explains_itself_with_no_log_file_at_all(
    client: Any, env: Env
) -> None:
    """A missing log is an empty tail, never a 500 and never a missing reason."""
    record = env.record(
        status="failed",
        refusal=acquisitions.Refusal(
            rule="probe-failed",
            detail="yt-dlp refused: ERROR: Private video",
            remediation=acquisitions.REMEDIATIONS["probe-failed"],
        ),
    )
    assert not acquisitions.log_path(env.root, record.acquisition_id).exists()
    body = client.get(f"/acquisitions/{record.acquisition_id}").json()
    assert body["logTail"] == []
    assert body["refusal"]["rule"] == "probe-failed"


def test_an_intake_failure_is_failed_and_names_the_repost_command(
    client: Any, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The drop is finalized and re-running the acquisition would be the wrong
    advice, so the remediation is the exact re-POST for this drop."""
    drop = env.drops / "drop"
    drop.mkdir()
    monkeypatch.setattr(youtube, "acquire", lambda url, **kwargs: mint_result(drop))

    def _unreachable(api_url: str, path: Path) -> tuple[str, int, str]:
        raise mintdrop.IntakeError(
            f"POST {api_url}/ingests failed (is the api running?): refused"
        )

    monkeypatch.setattr(acquisitions, "post_ingest", _unreachable)
    record = env.record()
    final = acquisitions.run_acquisition(env.config, record.acquisition_id, WATCH_URL)
    assert final.status == "failed"

    body = client.get(f"/acquisitions/{record.acquisition_id}").json()
    assert body["refusal"]["rule"] == "intake-failed"
    assert "is the api running?" in body["refusal"]["detail"]
    remediation = body["refusal"]["remediation"]
    assert "/ingests" in remediation
    assert str(drop) in remediation
    assert "re-POST" in remediation


def test_child_config_failure_writes_a_structured_failed_record(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: even failure before config load is fields, never log-only prose."""
    record = env.record(pid=os.getpid())
    monkeypatch.setattr(
        acquisitions,
        "_load_cli_config",
        lambda: (_ for _ in ()).throw(acquisitions.ConfigError("broken config")),
    )

    code = acquisitions.main(
        [
            "--run",
            "--acquisition-id",
            record.acquisition_id,
            "--url",
            record.url,
            "--state-root",
            str(env.root),
        ]
    )

    assert code == 1
    stored = acquisitions.read_record(env.root, record.acquisition_id)
    assert stored.status == "failed"
    assert stored.refusal == acquisitions.Refusal(
        rule="config",
        detail="broken config",
        remediation=acquisitions.REMEDIATIONS["config"],
    )


def test_the_log_tail_is_bounded_and_reports_the_end_of_the_run(
    client: Any, env: Env
) -> None:
    record = env.record(status="running", pid=os.getpid())
    line = "x" * 200
    acquisitions.log_path(env.root, record.acquisition_id).write_text(
        "\n".join(f"{index:05d} {line}" for index in range(5000)) + "\n",
        encoding="utf-8",
    )
    tail = client.get(f"/acquisitions/{record.acquisition_id}").json()["logTail"]
    assert 0 < len(tail) <= acquisitions.LOG_TAIL_MAX_LINES
    assert sum(len(entry) for entry in tail) <= acquisitions.LOG_TAIL_MAX_BYTES
    assert tail[-1].startswith("04999")


def test_log_tail_drops_the_partial_first_line(tmp_path: Path) -> None:
    """A byte-bounded read starts mid-line; reporting half a line would be a
    lie about what the tool printed."""
    path = tmp_path / "acq.log"
    path.write_text("first\nsecond\nthird\n", encoding="utf-8")
    # 10 bytes off the end starts inside "second"; the fragment is dropped
    # rather than reported as a line the tool printed.
    assert acquisitions.log_tail(path, max_bytes=10) == ["third"]
    assert acquisitions.log_tail(path, max_bytes=4096) == ["first", "second", "third"]
    assert acquisitions.log_tail(tmp_path / "missing.log") == []
    assert acquisitions.log_tail(path, max_bytes=4096, max_lines=2) == [
        "second",
        "third",
    ]


# --- the tables and the route table -----------------------------------------


def test_both_refusal_tables_cover_exactly_the_closed_vocabulary() -> None:
    """One vocabulary, two total functions over it. A rule added to
    `REFUSAL_RULES` later fails here rather than acquiring a silent default,
    which is why neither table is a comprehension."""
    assert set(acquisitions.REMEDIATIONS) == set(youtube.REFUSAL_RULES)
    assert set(acquisitions.PROBLEM_STATUS) == set(youtube.REFUSAL_RULES)
    assert all(text.strip() for text in acquisitions.REMEDIATIONS.values())
    assert set(acquisitions.PROBLEM_STATUS.values()) == {400, 422, 503}


def test_the_status_buckets_pin_the_complete_rule_partition() -> None:
    """F5/F6: every rule's category is contract, not only table membership."""
    host_rules = {
        "tool-missing",
        "tool-unrunnable",
        "tool-timeout",
        "version-failed",
        "version-empty",
        "probe-unreadable",
        "format-id-missing",
        "identity-mismatch",
        "download-failed",
        "download-incomplete",
        "captions-missing-vtt",
        "captions-changed",
        "tool-version-missing",
        "drops-root-changed",
        "existing-drop-incomplete",
        "playlist-unreadable",
        "mint-refused",
        "intake-failed",
        "config",
        "unclassified",
    }
    expected = {rule: 422 for rule in youtube.REFUSAL_RULES}
    expected["not-a-video-url"] = 400
    expected.update(dict.fromkeys(host_rules, 503))
    assert acquisitions.PROBLEM_STATUS == expected


def test_every_remediation_keeps_its_rule_specific_action() -> None:
    """F5: non-empty text alone cannot detect two remediations being swapped."""
    anchors = {
        "not-a-video-url": "one YouTube video",
        "tool-missing": "Install the missing tool",
        "tool-unrunnable": "permissions",
        "tool-timeout": "network",
        "version-failed": "--version' failed",
        "version-empty": "printed nothing",
        "probe-failed": "publicly playable",
        "probe-unreadable": "output this server could not parse",
        "duration-unknown": "no usable duration",
        "duration-cap": youtube.MAX_DURATION_CONFIG_KEY,
        "no-video-stream": "recording.mp4",
        "channel-missing": "publisher",
        "format-id-missing": "format it downloaded",
        "identity-mismatch": "different video",
        "started-at-unknown": "--started-at",
        "download-failed": "while downloading",
        "download-incomplete": "no usable media",
        "captions-missing-vtt": "no VTT",
        "captions-changed": "availability changed",
        "tool-version-missing": "version could not be recorded",
        "drops-root-changed": "MM_DROPS_ROOT",
        "existing-drop-incomplete": "Quarantine",
        "not-a-playlist-url": "Playlists are not acquired",
        "playlist-failed": "could not list",
        "playlist-unreadable": "playlist listing",
        "playlist-empty": "no entries",
        "entry-not-a-video": "no YouTube video",
        "mint-refused": "could not be assembled",
        "intake-failed": "finalized drop",
        "config": "configuration refused",
        "unclassified": "cannot classify",
    }
    assert set(anchors) == set(youtube.REFUSAL_RULES)
    for rule, anchor in anchors.items():
        assert anchor in acquisitions.REMEDIATIONS[rule], rule


def test_every_refusal_rule_maps_to_a_titled_problem_status() -> None:
    """No refusal may fall through to problems.py's untitled "Error"."""
    for status in set(acquisitions.PROBLEM_STATUS.values()):
        assert api_acquisitions._REFUSAL_TITLES[status]


def test_probe_is_declared_ahead_of_the_parameterized_status_route() -> None:
    """registry.py's rule, applied inside the router the media.py way: the
    literal path must be declared first or the parameterized sibling swallows
    it and rejects `probe` as a malformed UUID."""
    paths = [
        route.path
        for route in api_acquisitions.router.routes
        if isinstance(route, APIRoute)
    ]
    assert paths.index("/acquisitions/probe") < paths.index(
        "/acquisitions/{acquisition_id}"
    )


def test_the_probe_route_is_reachable_on_the_registered_app(
    client: Any, env: Env, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And the discovery-registered app really dispatches there — no edit to
    api/main.py was needed to reach any of this."""
    monkeypatch.setattr(youtube, "probe", lambda url: info_fixture("full"))
    response = client.post("/acquisitions/probe", json={"url": WATCH_URL})
    assert response.status_code == 200, response.text
    assert response.json()["sourceId"] == SOURCE_ID


def test_the_runner_module_imports_neither_the_api_nor_fastapi() -> None:
    """The child runs without FastAPI: `python -m meetingminer.acquisitions`
    must not depend on the web framework it exists to keep the work out of.
    Read from the import statements themselves, so the prose that explains the
    rule cannot be mistaken for a violation of it."""
    tree = ast.parse(Path(acquisitions.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert imported, "no imports found — did the parse target move?"
    for name in imported:
        assert not name.startswith("meetingminer.api"), name
        assert not name.split(".")[0] in {"fastapi", "starlette", "pydantic"}, name
