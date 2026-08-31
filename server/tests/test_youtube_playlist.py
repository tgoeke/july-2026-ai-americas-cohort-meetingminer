"""``youtube-drop --playlist``: playlist acquisition (story 6.2a).

Offline by construction, the way ``test_youtube.py`` is: ``_run`` and
``acquire`` are stubbed, enumeration is read from a recorded
``--flat-playlist`` listing, every drops root is a ``tmp_path`` directory, and
no store fixture is requested. Nothing here posts to a real api.

The story's load-bearing clause is that **a refused entry does not stop the
run**, so it is asserted from three directions: a refusal raised by
``acquire``, an entry the listing does not describe as a video, and an intake
failure after a successful mint.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from meetingminer import mintdrop, youtube

from repo_paths import REPO_ROOT

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "youtube"

PLAYLIST_ID = "PLmeetingminer0sandbox01"
PLAYLIST_URL = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"

#: The three video rows of `flat-playlist.json`, in listing order. The third
#: row of the fixture is a nested playlist and has no video id.
FIRST_ID = "aB3dEfGhIj0"
SECOND_ID = "bB3dEfGhIj1"
PRIVATE_ID = "cB3dEfGhIj2"


# --- helpers ---------------------------------------------------------------


def flat_listing() -> dict[str, Any]:
    return json.loads((FIXTURES / "flat-playlist.json").read_text(encoding="utf-8"))


def video_entries() -> list[youtube.PlaylistEntry]:
    """The fixture's four rows, as `enumerate_playlist` yields them."""
    return [
        youtube.PlaylistEntry(1, FIRST_ID, "Platform Sync — August"),
        youtube.PlaylistEntry(2, SECOND_ID, "Platform Sync — September"),
        youtube.PlaylistEntry(3, None, "Archive (nested playlist)"),
        youtube.PlaylistEntry(4, PRIVATE_ID, "[Private video]"),
    ]


def completed(stdout: str = "", stderr: str = "", code: int = 0):
    return subprocess.CompletedProcess(["yt-dlp"], code, stdout, stderr)


def mint_result(root: Path, video_id: str, *, status: str = "created"):
    return mintdrop.MintResult(
        status=status,
        path=root / f"drop-{video_id}",
        source_id=f"{youtube.YOUTUBE_SOURCE_ID_PREFIX}{video_id}",
        metadata={
            "startedAt": "2026-08-12T15:30:19Z",
            "startedAtPrecision": "second",
            "corpus": "real",
            "provenance": {"files": [{"dropFilename": "recording.mp4"}]},
        },
    )


def cli_config(root: Path, *, cap_minutes: int = 37) -> SimpleNamespace:
    return SimpleNamespace(
        config_path=REPO_ROOT / "config.yaml",
        secrets=SimpleNamespace(mm_drops_root=root),
        settings=SimpleNamespace(
            acquisition=SimpleNamespace(
                youtube=SimpleNamespace(max_duration_minutes=cap_minutes)
            )
        ),
    )


def _must_not_run(name: str):
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{name} must not be invoked")

    return _boom


def write_existing_youtube_drop(root: Path, video_id: str) -> Path:
    """A finalized, provenance-complete YouTube drop for `video_id`.

    A local copy rather than an import of `test_youtube.py`'s: the wave rules
    keep each story's fixtures inside its own module.
    """
    source_id = f"{youtube.YOUTUBE_SOURCE_ID_PREFIX}{video_id}"
    drop = root / mintdrop.drop_name(
        "2026-08-12T15:30:19Z", "Platform Sync — August", source_id
    )
    drop.mkdir()
    recording = drop / "recording.mp4"
    recording.write_bytes(b"existing youtube recording")
    digest, size = mintdrop.sha256_and_size(recording)
    metadata = {
        "schemaVersion": 1,
        "sourceId": source_id,
        "corpus": "real",
        "startedAt": "2026-08-12T15:30:19Z",
        "startedAtPrecision": "second",
        "provenance": {
            "tool": "youtube-drop",
            "title": "Platform Sync — August",
            "mintedAt": "2026-08-30T12:00:00Z",
            "suppliedBy": "test",
            "startedAtSource": "release_timestamp",
            "url": youtube.watch_url(video_id),
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
    return drop


@pytest.fixture()
def drops_root(tmp_path: Path) -> Path:
    root = tmp_path / "drops"
    root.mkdir()
    return root


def acquire_kwargs(root: Path, cap_minutes: int = 180) -> dict[str, Any]:
    return {
        "drops_root": root,
        "identity_root": root,
        "config_path": REPO_ROOT / "config.yaml",
        "max_duration_minutes": cap_minutes,
    }


# --- playlist URL classification (offline) ----------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/playlist?list={PLAYLIST_ID}",
        f"http://youtube.com/playlist?list={PLAYLIST_ID}",
        f"https://m.youtube.com/playlist?list={PLAYLIST_ID}",
        f"https://www.youtube.com/watch?v={FIRST_ID}&list={PLAYLIST_ID}",
        f"https://www.youtube.com/watch?v={FIRST_ID}&list={PLAYLIST_ID}&index=2",
    ],
)
def test_every_playlist_url_shape_yields_the_same_id(url: str) -> None:
    assert youtube.playlist_id_from_url(url) == PLAYLIST_ID


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={FIRST_ID}",
        f"https://youtu.be/{FIRST_ID}",
        f"https://www.youtube.com/shorts/{FIRST_ID}",
        f"https://vimeo.com/playlist?list={PLAYLIST_ID}",
        f"https://youtube.com.evil.example/playlist?list={PLAYLIST_ID}",
        f"ftp://www.youtube.com/playlist?list={PLAYLIST_ID}",
        "https://www.youtube.com/playlist",
        "https://www.youtube.com/playlist?list=",
        "https://www.youtube.com/playlist?list=bad*chars!!",
        f"https://www.youtube.com/playlist?list={PLAYLIST_ID}&list=OTHER",
        "not a url at all",
        "",
    ],
)
def test_a_url_that_names_no_playlist_is_refused_by_name(url: str) -> None:
    with pytest.raises(youtube.YoutubeError) as raised:
        youtube.playlist_id_from_url(url)
    assert "not a YouTube playlist URL" in str(raised.value)
    assert raised.value.rule == "not-a-playlist-url"


def test_the_canonical_playlist_url_is_what_enumeration_asks_for() -> None:
    assert youtube.playlist_url(PLAYLIST_ID) == PLAYLIST_URL


# --- enumeration -------------------------------------------------------------


def test_enumeration_uses_flat_playlist_and_reads_the_recorded_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance: entries are enumerated with `--flat-playlist`."""
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any):
        seen["command"] = command
        seen["timeout"] = kwargs.get("timeout")
        return completed(stdout=json.dumps(flat_listing()))

    monkeypatch.setattr(youtube, "_run", fake_run)
    entries = youtube.enumerate_playlist(PLAYLIST_URL)

    assert seen["command"] == [
        youtube.YT_DLP,
        "-J",
        "--flat-playlist",
        PLAYLIST_URL,
    ]
    assert seen["timeout"] == youtube.PROBE_TIMEOUT_SECONDS
    assert entries == video_entries()


def test_enumeration_failure_carries_yt_dlps_own_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        youtube,
        "_run",
        lambda command, **kwargs: completed(
            stderr="ERROR: [youtube:tab] The playlist does not exist.", code=1
        ),
    )
    with pytest.raises(youtube.YoutubeError) as raised:
        youtube.enumerate_playlist(PLAYLIST_URL)
    assert "The playlist does not exist." in str(raised.value)
    assert raised.value.rule == "playlist-failed"


@pytest.mark.parametrize(
    "stdout",
    [
        "not json at all",
        "[]",
        '{"_type": "playlist"}',
        '{"entries": "not a list"}',
    ],
)
def test_unreadable_enumeration_output_is_refused_by_name(
    stdout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        youtube, "_run", lambda command, **kwargs: completed(stdout=stdout)
    )
    with pytest.raises(youtube.YoutubeError) as raised:
        youtube.enumerate_playlist(PLAYLIST_URL)
    assert raised.value.rule == "playlist-unreadable"


def test_an_empty_playlist_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        youtube,
        "_run",
        lambda command, **kwargs: completed(stdout='{"entries": []}'),
    )
    with pytest.raises(youtube.YoutubeError) as raised:
        youtube.enumerate_playlist(PLAYLIST_URL)
    assert raised.value.rule == "playlist-empty"


# --- the refusal rule vocabulary --------------------------------------------


def test_every_rule_the_source_raises_is_declared() -> None:
    """`refused:<rule>` is only stable if the vocabulary is closed."""
    source = (
        REPO_ROOT / "server" / "meetingminer" / "youtube.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    raised = [
        node.exc
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "YoutubeError"
    ]
    assert raised, "no YoutubeError raise sites found"
    for call in raised:
        rules = [keyword.value for keyword in call.keywords if keyword.arg == "rule"]
        assert len(rules) == 1, f"YoutubeError at line {call.lineno} needs one rule="
        rule = rules[0]
        assert isinstance(rule, ast.Constant) and isinstance(rule.value, str), (
            f"YoutubeError at line {call.lineno} needs a literal rule="
        )
        assert rule.value in youtube.REFUSAL_RULES
    assert "unclassified" in youtube.REFUSAL_RULES


def test_refusal_rule_names_the_source_of_every_refusal_kind() -> None:
    assert youtube.refusal_rule(youtube.YoutubeError("x", rule="duration-cap")) == (
        "duration-cap"
    )
    assert youtube.refusal_rule(youtube.YoutubeError("x")) == "unclassified"
    assert youtube.refusal_rule(mintdrop.MintError("x")) == "mint-refused"
    assert youtube.refusal_rule(youtube.ConfigError("x")) == "config"


def test_a_youtube_error_still_reads_as_its_message() -> None:
    """The rule is additive: story 6.2's operator-facing text is unchanged."""
    error = youtube.YoutubeError(
        "the video carries no video stream", rule="no-video-stream"
    )
    assert str(error) == "the video carries no video stream"


def test_a_youtube_error_rejects_a_rule_outside_the_closed_vocabulary() -> None:
    with pytest.raises(ValueError, match="unknown YouTube refusal rule: invented-token"):
        youtube.YoutubeError("x", rule="invented-token")


# --- the per-entry loop ------------------------------------------------------


def run_with_stubbed_acquire(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    outcomes: dict[str, Any],
    no_post: bool = False,
    post: Any = None,
) -> tuple[int, list[str], dict[str, Any]]:
    """Drive `run_playlist` over the recorded listing with a scripted `acquire`.

    `outcomes` maps a video id to either a `MintResult` or an exception to
    raise. Returns the exit code, the acquired URLs in order, and the posts.
    """
    seen: dict[str, Any] = {"urls": [], "posts": []}

    monkeypatch.setattr(youtube, "ensure_playlist_tool", lambda: None)
    monkeypatch.setattr(
        youtube,
        "_run",
        lambda command, **kwargs: completed(stdout=json.dumps(flat_listing())),
    )

    def fake_acquire(url: str, **kwargs: Any):
        seen["urls"].append(url)
        video_id = youtube.video_id_from_url(url)
        outcome = outcomes[video_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def fake_post(api_url: str, drop_path: Path) -> tuple[str, int, str | None]:
        seen["posts"].append(drop_path)
        if post is not None:
            return post(api_url, drop_path)
        return "created", 201, "job-1"

    monkeypatch.setattr(youtube, "acquire", fake_acquire)
    monkeypatch.setattr(youtube, "post_ingest", fake_post)

    code = youtube.run_playlist(
        PLAYLIST_URL,
        api_url="http://api.test",
        no_post=no_post,
        acquire_kwargs=acquire_kwargs(tmp_path),
    )
    return code, seen["urls"], seen


def test_every_entry_is_minted_and_posted_sequentially_in_listing_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance: one drop and one `POST /ingests` per entry, sequentially."""
    outcomes = {
        FIRST_ID: mint_result(tmp_path, FIRST_ID),
        SECOND_ID: mint_result(tmp_path, SECOND_ID),
        PRIVATE_ID: mint_result(tmp_path, PRIVATE_ID),
    }
    code, urls, seen = run_with_stubbed_acquire(
        monkeypatch, tmp_path, outcomes=outcomes
    )
    out = capsys.readouterr().out

    assert urls == [
        youtube.watch_url(FIRST_ID),
        youtube.watch_url(SECOND_ID),
        youtube.watch_url(PRIVATE_ID),
    ]
    assert seen["posts"] == [
        outcomes[key].path for key in (FIRST_ID, SECOND_ID, PRIVATE_ID)
    ]
    assert code == 1  # the nested-playlist row is still a refusal
    assert "3 minted, 0 exists, 1 refused" in out


def test_a_refused_entry_does_not_stop_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance: the clause most likely to be got wrong."""
    outcomes = {
        FIRST_ID: youtube.YoutubeError(
            "the video is 210.0 minutes long — over the 180-minute cap",
            rule="duration-cap",
        ),
        SECOND_ID: mint_result(tmp_path, SECOND_ID),
        PRIVATE_ID: mint_result(tmp_path, PRIVATE_ID),
    }
    code, urls, seen = run_with_stubbed_acquire(
        monkeypatch, tmp_path, outcomes=outcomes
    )
    captured = capsys.readouterr()

    # The refusal did not end the run: both later videos were still acquired.
    assert urls == [
        youtube.watch_url(FIRST_ID),
        youtube.watch_url(SECOND_ID),
        youtube.watch_url(PRIVATE_ID),
    ]
    assert len(seen["posts"]) == 2
    assert code == 1
    assert "refused:duration-cap" in captured.out
    assert "over the 180-minute cap" in captured.err
    assert "2 minted, 0 exists, 2 refused" in captured.out


def test_a_mint_refusal_on_one_entry_is_also_survived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outcomes = {
        FIRST_ID: mintdrop.MintError("drops root vanished mid-run"),
        SECOND_ID: mint_result(tmp_path, SECOND_ID),
        PRIVATE_ID: mint_result(tmp_path, PRIVATE_ID),
    }
    code, urls, _ = run_with_stubbed_acquire(monkeypatch, tmp_path, outcomes=outcomes)
    assert len(urls) == 3
    assert code == 1
    assert "refused:mint-refused" in capsys.readouterr().out


def test_an_entry_that_is_not_a_video_is_refused_without_acquiring_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fixture's third row is a nested playlist — no video id to mint."""
    outcomes = {
        FIRST_ID: mint_result(tmp_path, FIRST_ID),
        SECOND_ID: mint_result(tmp_path, SECOND_ID),
        PRIVATE_ID: mint_result(tmp_path, PRIVATE_ID),
    }
    _, urls, _ = run_with_stubbed_acquire(monkeypatch, tmp_path, outcomes=outcomes)
    out = capsys.readouterr().out

    assert len(urls) == 3  # never four: the nested row reached no subprocess
    assert "refused:entry-not-a-video" in out
    assert "Archive (nested playlist)" in out


def test_an_intake_failure_on_one_entry_does_not_stop_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = mint_result(tmp_path, FIRST_ID)
    outcomes = {
        FIRST_ID: first,
        SECOND_ID: mint_result(tmp_path, SECOND_ID),
        PRIVATE_ID: mint_result(tmp_path, PRIVATE_ID),
    }

    def post(api_url: str, drop_path: Path) -> tuple[str, int, str | None]:
        if drop_path == first.path:
            raise mintdrop.IntakeError("connection refused")
        return "created", 201, "job-2"

    code, urls, seen = run_with_stubbed_acquire(
        monkeypatch, tmp_path, outcomes=outcomes, post=post
    )
    captured = capsys.readouterr()

    assert len(urls) == 3
    assert len(seen["posts"]) == 3  # every entry was still offered to intake
    assert code == 1
    assert "intake FAILED" in captured.out
    # story 6.2's recovery guidance, per entry, on the failing one only
    assert "re-POST this exact drop" in captured.err


def test_no_post_mints_every_entry_and_posts_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outcomes = {
        FIRST_ID: mint_result(tmp_path, FIRST_ID),
        SECOND_ID: mint_result(tmp_path, SECOND_ID),
        PRIVATE_ID: mint_result(tmp_path, PRIVATE_ID),
    }
    code, urls, seen = run_with_stubbed_acquire(
        monkeypatch, tmp_path, outcomes=outcomes, no_post=True
    )
    assert len(urls) == 3
    assert seen["posts"] == []
    assert code == 1  # the nested row still refuses
    assert "not posted" in capsys.readouterr().out


def test_a_playlist_of_only_good_entries_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(youtube, "ensure_playlist_tool", lambda: None)
    listing = {
        "_type": "playlist",
        "id": PLAYLIST_ID,
        "entries": [{"_type": "url", "id": FIRST_ID, "title": "Only entry"}],
    }
    monkeypatch.setattr(
        youtube, "_run", lambda command, **kwargs: completed(stdout=json.dumps(listing))
    )
    monkeypatch.setattr(
        youtube, "acquire", lambda url, **kwargs: mint_result(tmp_path, FIRST_ID)
    )
    monkeypatch.setattr(
        youtube, "post_ingest", lambda api_url, path: ("created", 201, "job-1")
    )
    assert (
        youtube.run_playlist(
            PLAYLIST_URL,
            api_url="http://api.test",
            no_post=False,
            acquire_kwargs=acquire_kwargs(tmp_path),
        )
        == 0
    )


# --- the exists short-circuit, per entry -------------------------------------


def test_the_exists_short_circuit_applies_per_entry_with_no_media_download(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance: story 6.2's `exists` path runs per entry, and the entry that
    is already minted reaches neither the probe nor the downloader."""
    write_existing_youtube_drop(drops_root, FIRST_ID)
    listing = {
        "_type": "playlist",
        "id": PLAYLIST_ID,
        "entries": [
            {"_type": "url", "id": FIRST_ID, "title": "Platform Sync — August"}
        ],
    }
    monkeypatch.setattr(
        youtube.shutil,
        "which",
        lambda tool: "/fake/yt-dlp" if tool == youtube.YT_DLP else None,
    )
    monkeypatch.setattr(youtube, "probe", _must_not_run("probe"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    monkeypatch.setattr(youtube, "yt_dlp_version", _must_not_run("yt_dlp_version"))
    posted: list[Path] = []

    def fake_run(command: list[str], **kwargs: Any):
        # Only the enumeration may reach yt-dlp; anything else is a media call.
        assert command[:3] == [youtube.YT_DLP, "-J", "--flat-playlist"]
        return completed(stdout=json.dumps(listing))

    def fake_post(api_url: str, path: Path) -> tuple[str, int, str | None]:
        posted.append(path)
        return "duplicate", 409, None

    monkeypatch.setattr(youtube, "_run", fake_run)
    monkeypatch.setattr(youtube, "post_ingest", fake_post)

    code = youtube.run_playlist(
        PLAYLIST_URL,
        api_url="http://api.test",
        no_post=False,
        acquire_kwargs=acquire_kwargs(drops_root),
    )
    out = capsys.readouterr().out

    assert code == 0
    assert len(posted) == 1  # the exists path still POSTs
    assert "exists" in out
    assert "0 minted, 1 exists, 0 refused" in out


# --- the summary table -------------------------------------------------------


def test_the_summary_table_names_every_entrys_outcome() -> None:
    rows = [
        youtube.EntryOutcome(
            youtube.PlaylistEntry(1, FIRST_ID, "Platform Sync — August"),
            "minted",
            "created",
            failed=False,
        ),
        youtube.EntryOutcome(
            youtube.PlaylistEntry(2, SECOND_ID, "Platform Sync — September"),
            "exists",
            "already ingested",
            failed=False,
        ),
        youtube.EntryOutcome(
            youtube.PlaylistEntry(3, None, "Archive (nested playlist)"),
            "refused:entry-not-a-video",
            "the listing row names no YouTube video",
            failed=True,
        ),
    ]
    lines = youtube.format_outcome_table(PLAYLIST_ID, rows)

    assert lines[0] == (
        f"playlist {PLAYLIST_ID} — 3 entries: 1 minted, 1 exists, 1 refused"
    )
    assert [" ".join(line.split()) for line in lines[1:]] == [
        f"1. {FIRST_ID} minted Platform Sync — August — created",
        f"2. {SECOND_ID} exists Platform Sync — September — already ingested",
        (
            "3. — refused:entry-not-a-video Archive (nested playlist)"
            " — the listing row names no YouTube video"
        ),
    ]
    # The outcome column is aligned, so a table of twenty entries stays legible.
    starts = {
        line.index(row.outcome)
        for line, row in zip(lines[1:], rows, strict=True)
    }
    assert len(starts) == 1


def test_one_entry_is_reported_in_the_singular() -> None:
    rows = [
        youtube.EntryOutcome(
            youtube.PlaylistEntry(1, FIRST_ID, None), "minted", "created", failed=False
        )
    ]
    assert youtube.format_outcome_table(PLAYLIST_ID, rows)[0].endswith(
        "— 1 entry: 1 minted, 0 exists, 0 refused"
    )


# --- the CLI -----------------------------------------------------------------


def test_the_single_video_path_is_untouched_when_playlist_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story 6.2's path must behave identically without `--playlist`."""
    root = tmp_path / "drops"
    root.mkdir()
    result = mint_result(tmp_path, FIRST_ID)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))
    monkeypatch.setattr(youtube, "resolve_api_url", lambda explicit: "http://api.test")
    monkeypatch.setattr(youtube, "resolve_drops_root", lambda explicit, config: root)
    monkeypatch.setattr(
        youtube, "enumerate_playlist", _must_not_run("enumerate_playlist")
    )
    monkeypatch.setattr(youtube, "run_playlist", _must_not_run("run_playlist"))

    def fake_acquire(url: str, **kwargs: Any):
        seen["url"] = url
        kwargs.pop("prepare_drops_root")
        seen["kwargs"] = kwargs
        return result

    monkeypatch.setattr(youtube, "acquire", fake_acquire)
    monkeypatch.setattr(youtube, "_report", lambda value, files: None)
    monkeypatch.setattr(
        youtube, "post_ingest", lambda api_url, path: ("created", 201, "job-1")
    )

    assert youtube.main([youtube.watch_url(FIRST_ID)]) == 0
    assert seen["url"] == youtube.watch_url(FIRST_ID)
    assert seen["kwargs"] == {
        "drops_root": root,
        "identity_root": root,
        "config_path": REPO_ROOT / "config.yaml",
        "max_duration_minutes": 37,
    }


def test_the_flag_routes_to_the_playlist_run_with_the_same_acquire_kwargs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "drops"
    root.mkdir()
    seen: dict[str, Any] = {}
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))
    monkeypatch.setattr(youtube, "resolve_api_url", lambda explicit: "http://api.test")
    monkeypatch.setattr(youtube, "resolve_drops_root", lambda explicit, config: root)
    monkeypatch.setattr(youtube, "acquire", _must_not_run("acquire"))

    def fake_run_playlist(url: str, **kwargs: Any) -> int:
        seen["url"] = url
        seen["api_url"] = kwargs["api_url"]
        seen["no_post"] = kwargs["no_post"]
        kwargs["acquire_kwargs"].pop("prepare_drops_root")
        seen["acquire_kwargs"] = kwargs["acquire_kwargs"]
        return 0

    monkeypatch.setattr(youtube, "run_playlist", fake_run_playlist)

    assert youtube.main([PLAYLIST_URL, "--playlist", "--no-post"]) == 0
    assert seen["url"] == PLAYLIST_URL
    assert seen["api_url"] == "http://api.test"
    assert seen["no_post"] is True
    assert seen["acquire_kwargs"] == {
        "drops_root": root,
        "identity_root": root,
        "config_path": REPO_ROOT / "config.yaml",
        "max_duration_minutes": 37,
    }


def test_main_refuses_a_video_url_under_playlist_before_touching_the_drops_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Story 6.2's ordering rule: classification wins the race with the
    resolver that write-probes `.staging`."""
    root = tmp_path / "drops"
    root.mkdir()
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))

    def mutating_resolver(explicit: str | None, config: object) -> Path:
        (root / ".staging").mkdir()
        return root

    monkeypatch.setattr(youtube, "resolve_drops_root", mutating_resolver)
    monkeypatch.setattr(youtube, "run_playlist", _must_not_run("run_playlist"))

    assert youtube.main([youtube.watch_url(FIRST_ID), "--playlist"]) == 1
    assert list(root.iterdir()) == []
    assert "not a YouTube playlist URL" in capsys.readouterr().err


def test_a_run_level_playlist_refusal_is_fatal_and_named(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "drops"
    root.mkdir()
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))
    monkeypatch.setattr(youtube, "resolve_api_url", lambda explicit: "http://api.test")
    monkeypatch.setattr(youtube, "resolve_drops_root", lambda explicit, config: root)
    monkeypatch.setattr(
        youtube,
        "run_playlist",
        lambda url, **kwargs: (_ for _ in ()).throw(
            youtube.YoutubeError("the playlist has no entries", rule="playlist-empty")
        ),
    )

    assert youtube.main([PLAYLIST_URL, "--playlist"]) == 1
    assert "fatal: youtube-drop refused: the playlist has no entries" in (
        capsys.readouterr().err
    )


# --- the Makefile door -------------------------------------------------------


def test_makefile_passes_the_playlist_flag_as_one_argument(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    fake_python = venv / "bin" / "python"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$MM_TEST_CAPTURE\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env_file = tmp_path / ".env"
    env_file.write_text("MM_DROPS_ROOT=/tmp/drops\n", encoding="utf-8")
    capture = tmp_path / "args.txt"

    completed_make = subprocess.run(
        [
            "make",
            "-f",
            str(REPO_ROOT / "infra" / "Makefile"),
            "youtube-drop",
            f"URL={PLAYLIST_URL}",
            "PLAYLIST=1",
            f"ROOT={REPO_ROOT}",
            f"VENV={venv}",
            f"ENVFILE={env_file}",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=dict(os.environ, MM_TEST_CAPTURE=str(capture)),
        check=False,
    )

    assert completed_make.returncode == 0, completed_make.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "meetingminer.youtube",
        PLAYLIST_URL,
        "--playlist",
    ]


def test_the_url_guard_still_names_url_and_now_names_playlist() -> None:
    makefile = (REPO_ROOT / "infra" / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nyoutube-drop: check-env\n", 1)[1].split("\n\n", 1)[0]
    assert "error: URL is required" in recipe
    assert "PLAYLIST=1" in recipe
    assert "$(if $(PLAYLIST),--playlist)" in recipe


# --- the docs ----------------------------------------------------------------


def test_readme_documents_playlist_acquisition() -> None:
    readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Ingesting a YouTube video", 1)[1].split("\n## ", 1)[0]
    assert "PLAYLIST=1" in section
    assert "--flat-playlist" in section
    assert "a refused entry does not stop the run" in section
    # The two statements story 6.2 wrote are corrected, not left contradicting.
    assert "playlists are not supported" not in section
    assert "a playlist-only URL is refused" not in section
