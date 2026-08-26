"""Unit tests for `publish/export.py` (story 4.3): store-free, real `git`.

No Postgres, no mocked subprocess — `tmp_path` plus the real `git` binary on
PATH is local, offline tooling (AGENTS.md's docker-stack rule is about the
three store containers, not this), so exercising it for real is the right
call rather than faking a process that every dev/CI environment already has.
"""

from __future__ import annotations

import fcntl
import multiprocessing
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import meetingminer.publish.export as export_module
from meetingminer.publish.export import (
    GitExportError,
    commit_artifact,
    ensure_git_repo,
    export_artifact,
    publish_adr,
)


def _publish_adr_in_separate_process(
    publish_root: str,
    artifact_id: str,
    title: str,
    start: multiprocessing.synchronize.Barrier,
    results: multiprocessing.queues.Queue,
) -> None:
    """Publish one ADR after both API-process stand-ins are ready."""
    root = Path(publish_root)
    parsed_id = UUID(artifact_id)
    relative = export_artifact(root, parsed_id, "adr", title, "Body.")
    start.wait(timeout=10)
    results.put((artifact_id, publish_adr(root, relative, title, parsed_id)))


def test_export_artifact_writes_the_expected_path_and_content(tmp_path: Path) -> None:
    artifact_id = uuid4()
    relative = export_artifact(tmp_path, artifact_id, "adr", "Move to SFTP", "Body text.")

    assert relative == Path("adr") / f"{artifact_id}.md"
    written = (tmp_path / relative).read_text(encoding="utf-8")
    assert written == "# Move to SFTP\n\nBody text.\n"


def test_export_artifact_creates_the_kind_subdirectory(tmp_path: Path) -> None:
    artifact_id = uuid4()
    export_artifact(tmp_path, artifact_id, "action-item", "Follow up", "Do it.")
    assert (tmp_path / "action-item").is_dir()


def test_export_artifact_overwrites_identical_content_on_retry(tmp_path: Path) -> None:
    artifact_id = uuid4()
    first = export_artifact(tmp_path, artifact_id, "adr", "Title", "Body.")
    second = export_artifact(tmp_path, artifact_id, "adr", "Title", "Body.")
    assert first == second
    assert (tmp_path / first).read_text(encoding="utf-8") == "# Title\n\nBody.\n"


def test_ensure_git_repo_is_idempotent(tmp_path: Path) -> None:
    ensure_git_repo(tmp_path)
    assert (tmp_path / ".git").is_dir()
    # Calling again must not fail or reset the repo.
    ensure_git_repo(tmp_path)
    assert (tmp_path / ".git").is_dir()


def test_ensure_git_repo_sets_a_local_identity(tmp_path: Path) -> None:
    ensure_git_repo(tmp_path)
    name = subprocess.run(
        ["git", "config", "user.name"], cwd=tmp_path, capture_output=True, text=True
    )
    email = subprocess.run(
        ["git", "config", "user.email"], cwd=tmp_path, capture_output=True, text=True
    )
    assert name.stdout.strip() == "MeetingMiner"
    assert email.stdout.strip() == "meetingminer@localhost"


def test_commit_artifact_returns_a_real_sha(tmp_path: Path) -> None:
    ensure_git_repo(tmp_path)
    artifact_id = uuid4()
    relative = export_artifact(tmp_path, artifact_id, "adr", "Move to SFTP", "Body.")

    sha = commit_artifact(tmp_path, relative, "Move to SFTP", artifact_id)

    assert len(sha) == 40
    log = subprocess.run(
        ["git", "log", "-1", "--format=%H"], cwd=tmp_path, capture_output=True, text=True
    )
    assert log.stdout.strip() == sha


def test_commit_artifact_is_idempotent_on_an_unchanged_file(tmp_path: Path) -> None:
    ensure_git_repo(tmp_path)
    artifact_id = uuid4()
    relative = export_artifact(tmp_path, artifact_id, "adr", "Move to SFTP", "Body.")

    first_sha = commit_artifact(tmp_path, relative, "Move to SFTP", artifact_id)
    # Re-export identical content (a retried request), then commit again.
    export_artifact(tmp_path, artifact_id, "adr", "Move to SFTP", "Body.")
    second_sha = commit_artifact(tmp_path, relative, "Move to SFTP", artifact_id)

    assert second_sha == first_sha


def test_publish_adr_uses_an_existing_configured_repository_and_preserves_history(
    tmp_path: Path,
) -> None:
    """Configuration authorizes an operator-created repo at MM_PUBLISH_ROOT.
    Publishing must add its ADR without rewriting or discarding prior history.
    """
    publish_root = tmp_path / "operator-repo"
    publish_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=publish_root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Operator"], cwd=publish_root, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "operator@example.com"],
        cwd=publish_root,
        check=True,
    )
    (publish_root / "seed.txt").write_text("operator history\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=publish_root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=publish_root, check=True)

    artifact_id = uuid4()
    relative = export_artifact(publish_root, artifact_id, "adr", "Adopt SFTP", "Body.")
    sha = publish_adr(publish_root, relative, "Adopt SFTP", artifact_id)

    log = subprocess.run(
        ["git", "log", "--format=%H %s"], cwd=publish_root, capture_output=True, text=True
    )
    assert sha in log.stdout
    assert "Publish ADR: Adopt SFTP" in log.stdout
    assert "seed" in log.stdout
    assert (publish_root / relative).is_file()
    author = subprocess.run(
        ["git", "show", "-s", "--format=%an <%ae>", sha],
        cwd=publish_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert author.stdout.strip() == "Operator <operator@example.com>"


def test_retry_after_a_later_adr_commit_returns_the_original_path_sha(tmp_path: Path) -> None:
    """A no-op retry identifies the last commit that changed its own path,
    rather than the repository's newer HEAD from another ADR.
    """
    ensure_git_repo(tmp_path)
    first_id = uuid4()
    first_path = export_artifact(tmp_path, first_id, "adr", "First", "Body.")
    first_sha = publish_adr(tmp_path, first_path, "First", first_id)
    second_id = uuid4()
    second_path = export_artifact(tmp_path, second_id, "adr", "Second", "Body.")
    second_sha = publish_adr(tmp_path, second_path, "Second", second_id)

    export_artifact(tmp_path, first_id, "adr", "First", "Body.")
    retry_sha = publish_adr(tmp_path, first_path, "First", first_id)

    assert retry_sha == first_sha
    assert retry_sha != second_sha


def test_ensure_git_repo_is_unaffected_by_a_foreign_repo_one_level_up(
    tmp_path: Path,
) -> None:
    """A publish root merely *nested inside* a foreign repo, with no `.git`
    of its own, is not the hazard: `git init` creates an independent repo at
    `publish_root` itself, and git always resolves to the nearest `.git` —
    the outer repo is never touched."""
    outer = tmp_path / "outer-repo"
    outer.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    subprocess.run(["git", "config", "user.name", "Outer"], cwd=outer, check=True)
    subprocess.run(["git", "config", "user.email", "outer@example.com"], cwd=outer, check=True)
    (outer / "seed.txt").write_text("outer repo content\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=outer, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=outer, check=True)

    publish_root = outer / "publish"
    publish_root.mkdir()

    ensure_git_repo(publish_root)  # must not raise

    assert (publish_root / ".git").is_dir()
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=outer, capture_output=True, text=True
    )
    assert log.stdout.strip() == "seed"


def test_ensure_git_repo_accepts_a_publish_root_it_previously_initialized(
    tmp_path: Path,
) -> None:
    """The guard must not false-positive on the ordinary, intended shape:
    a `publish_root` this function itself `git init`-ed stays accepted on
    every later call (the steady-state, one-per-approve-request shape)."""
    ensure_git_repo(tmp_path)
    assert (tmp_path / ".git").is_dir()
    ensure_git_repo(tmp_path)  # must not raise


def test_repository_lock_times_out_without_creating_a_publish_root_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = export_module._repository_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as held_lock:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX)
        monkeypatch.setattr(export_module, "_REPOSITORY_LOCK_TIMEOUT_SECONDS", 0.1)
        with pytest.raises(GitExportError, match="timed out waiting for the publish repository lock"):
            ensure_git_repo(tmp_path)
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_UN)

    assert not (tmp_path / ".meetingminer-publish.lock").exists()


def test_separate_processes_serialize_scoped_commits_without_touching_staged_action(
    tmp_path: Path,
) -> None:
    """Two API-process stand-ins share one real repo and system-temp lock."""
    ensure_git_repo(tmp_path)
    staged_action = tmp_path / "action-item" / "human-staged.md"
    staged_action.parent.mkdir()
    staged_action.write_text("do not commit me\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "action-item/human-staged.md"], cwd=tmp_path, check=True)

    first_id, second_id = uuid4(), uuid4()
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_publish_adr_in_separate_process,
            args=(str(tmp_path), str(first_id), "First ADR", start, results),
        ),
        context.Process(
            target=_publish_adr_in_separate_process,
            args=(str(tmp_path), str(second_id), "Second ADR", start, results),
        ),
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    shas = dict(results.get(timeout=5) for _ in processes)
    assert set(shas) == {str(first_id), str(second_id)}
    assert shas[str(first_id)] != shas[str(second_id)]
    for artifact_id, sha in shas.items():
        committed = subprocess.run(
            ["git", "show", "--format=", "--name-only", sha],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert committed.stdout.splitlines() == [f"adr/{artifact_id}.md"]
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert staged.stdout.splitlines() == ["action-item/human-staged.md"]


def test_git_environment_overrides_cannot_redirect_a_publish(
    tmp_path: Path, monkeypatch
) -> None:
    """GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE are untrusted even when inherited.
    The configured root, not a decoy repo named by the environment, receives
    the ADR commit.
    """
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=decoy, check=True)
    publish_root = tmp_path / "publish"
    publish_root.mkdir()
    monkeypatch.setattr(
        export_module,
        "_GIT_ENV",
        {
            **export_module._GIT_ENV,
            "GIT_DIR": str(decoy / ".git"),
            "GIT_WORK_TREE": str(decoy),
            "GIT_INDEX_FILE": str(tmp_path / "decoy.index"),
        },
    )

    artifact_id = uuid4()
    relative = export_artifact(publish_root, artifact_id, "adr", "Target", "Body.")
    sha = publish_adr(publish_root, relative, "Target", artifact_id)

    assert (publish_root / ".git").exists()
    assert len(sha) == 40
    assert not (decoy / relative).exists()
    decoy_log = subprocess.run(
        ["git", "log", "--format=%H"], cwd=decoy, capture_output=True, text=True
    )
    assert decoy_log.stdout == ""


@pytest.mark.parametrize("config_key", ["user.name", "user.email"])
def test_ensure_git_repo_names_local_identity_configuration_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_key: str
) -> None:
    original_run = export_module._run

    def fail_config(args, cwd, *, artifact_id):
        if args[:4] == ["git", "config", "--local", config_key]:
            return subprocess.CompletedProcess(args, 1, "", f"cannot set {config_key}")
        return original_run(args, cwd, artifact_id=artifact_id)

    monkeypatch.setattr(export_module, "_run", fail_config)
    with pytest.raises(GitExportError, match=f"cannot set {config_key}"):
        ensure_git_repo(tmp_path)


def test_commit_artifact_raises_a_named_error_outside_a_repo(tmp_path: Path) -> None:
    artifact_id = uuid4()
    relative = export_artifact(tmp_path, artifact_id, "adr", "Title", "Body.")

    with pytest.raises(GitExportError) as excinfo:
        commit_artifact(tmp_path, relative, "Title", artifact_id)

    assert excinfo.value.artifact_id == artifact_id
    assert str(artifact_id) in str(excinfo.value)


# --- P1/P2/P3: every non-exit-code git failure mode is a named GitExportError ---


def test_a_missing_git_binary_raises_a_named_error_not_a_bare_filenotfounderror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_run` must catch `FileNotFoundError` (a kind of `OSError`) itself,
    not let it propagate raw past `commit_artifact`/`ensure_git_repo`. Real
    `subprocess.run`, no mocking: `_GIT_ENV`'s `PATH` is pointed at an empty
    directory so the git binary genuinely cannot be found."""
    empty_path_dir = tmp_path / "empty-path"
    empty_path_dir.mkdir()
    monkeypatch.setattr(
        export_module, "_GIT_ENV", {**export_module._GIT_ENV, "PATH": str(empty_path_dir)}
    )

    publish_root = tmp_path / "publish"
    publish_root.mkdir()
    with pytest.raises(GitExportError) as excinfo:
        ensure_git_repo(publish_root)

    assert excinfo.value.artifact_id is None
    assert not (publish_root / ".git").exists()


def test_a_hung_git_process_raises_a_named_error_after_the_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_run` must map `subprocess.TimeoutExpired` to `GitExportError` too —
    real `subprocess.run` against a fake `git` shell script that never exits,
    with the timeout shortened so the test does not actually wait 30s."""
    monkeypatch.setattr(export_module, "_GIT_TIMEOUT_SECONDS", 0.2)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nwhile :; do :; done\n", encoding="utf-8")
    fake_git.chmod(0o755)
    monkeypatch.setattr(
        export_module, "_GIT_ENV", {**export_module._GIT_ENV, "PATH": str(fake_bin)}
    )

    publish_root = tmp_path / "publish"
    publish_root.mkdir()
    with pytest.raises(GitExportError, match="timed out"):
        ensure_git_repo(publish_root)


def test_git_calls_force_the_c_locale_so_the_nothing_to_commit_match_is_stable() -> None:
    """P3: a non-English `LC_ALL`/`LANG` in the ambient environment must not
    reach git — `_GIT_ENV` always forces `C`, regardless of what this test
    process itself was started with."""
    assert export_module._GIT_ENV["LC_ALL"] == "C"
    assert export_module._GIT_ENV["LANG"] == "C"
