"""Export a published artifact to disk and, for ADRs, commit it to git.

Story 4.3 (epics AC3): on the per-moment approve gesture, every artifact gets
a markdown file under ``MM_PUBLISH_ROOT``; `adr` artifacts additionally get
committed to a plain local git repository rooted there, `action-item`
artifacts never do. This module is the whole export/git surface — the api
route (`api/moments.py`) and `prune` (which removes what a purged meeting
published) are its only callers, and the route always calls these
functions *before* the Postgres ``UPDATE`` that marks a row `published`
(Design Notes: filesystem/git side effects precede the database write, so a
failure here never leaves an artifact wrongly marked published).

No GitPython: every dev/CI environment already has the system `git` binary
for the repo itself, so this shells out to it — always as a list of args,
never ``shell=True``.
"""

import fcntl
import hashlib
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager, suppress
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

# The local git identity `ensure_git_repo` sets, so a commit never fails on a
# missing global git identity in a fresh dev machine or CI container (Design
# Notes: "Please tell me who you are" would be a confusing first-publish
# error unrelated to anything this story is actually testing).
GIT_USER_NAME = "MeetingMiner"
GIT_USER_EMAIL = "meetingminer@localhost"

# A commit whose only problem is "nothing changed" is not a failure — a
# retried request re-exports identical content, and re-committing an
# unchanged file must be a no-op that still yields a usable sha (Design
# Notes, I/O matrix "retry after partial failure"). Matched against git's
# output under a forced `C` locale (`_GIT_ENV` below) so this string match
# cannot silently break under a developer's or CI's own `LC_ALL`/`LANG`.
_NOTHING_TO_COMMIT = "nothing to commit"

# Every git call here forces the `C` locale: git's own message text (this
# module greps `_NOTHING_TO_COMMIT` out of it) is locale-dependent, and a
# non-English `LC_ALL`/`LANG` in the environment would silently break the
# idempotent-retry detection without any test noticing (a dev machine or CI
# runner would need a non-English locale set to reproduce it).
# Git gives its ``GIT_*`` process variables precedence over discovery from
# ``cwd``.  Never inherit those controls: MM_PUBLISH_ROOT is the only
# repository this module is authorized to mutate.  Keeping the rest of the
# environment preserves PATH (and platform necessities such as HOME), while
# `_sanitized_git_env` defensively repeats the filtering for test/process
# overrides made after import.
_GIT_ENV = {
    key: value for key, value in os.environ.items() if not key.startswith("GIT_")
}
_GIT_ENV.update({"LC_ALL": "C", "LANG": "C"})

# How long any single git invocation may run before this module gives up on
# it. The route holds an open Postgres transaction with `FOR UPDATE` locks
# across every git call it makes, so a hung git process (a stuck pager, a
# stalled filesystem) must not block that transaction — and everything else
# contending for the same moment or a pool connection — forever.
_GIT_TIMEOUT_SECONDS = 30

# The process-global Git index needs cross-process serialization.  The lock is
# deliberately outside the configured repository: publishing must not create
# an untracked working-tree file, and normal repository cleanup cannot remove
# the mutex while another API process holds it.
_REPOSITORY_LOCK_DIR = Path(tempfile.gettempdir()) / "meetingminer-publish-locks"
_REPOSITORY_LOCK_TIMEOUT_SECONDS = 30


class GitExportError(RuntimeError):
    """A git operation failed for a reason other than "nothing to commit".

    Carries the artifact id (when the failing call is scoped to one — a
    repo-level call like `git init`/`git config` has none, and passes `None`)
    and a message describing what went wrong, so the api route can name both
    in the 500 problem it raises (I/O matrix: "git binary missing/fails on an
    ADR"). Raised for *every* git failure mode this module can hit: a
    non-zero exit, the binary missing from PATH (`FileNotFoundError`, a kind
    of `OSError`), any other `OSError` (e.g. a permission error), and a git
    call that ran past `_GIT_TIMEOUT_SECONDS` — never left to propagate as a
    bare, un-RFC-9457-shaped exception.
    """

    def __init__(self, artifact_id: UUID | None, stderr: str) -> None:
        self.artifact_id = artifact_id
        self.stderr = stderr
        scope = f"artifact {artifact_id}" if artifact_id is not None else "the publish repo"
        super().__init__(f"git export failed for {scope}: {stderr.strip()}")


def export_artifact(
    publish_root: Path, artifact_id: UUID, kind: str, title: str, body: str
) -> Path:
    """Write ``{publish_root}/{kind}/{artifact_id}.md``; return its relative path.

    The artifact's own UUID is the filename (Design Notes): titles are free
    LLM text, not guaranteed filesystem-safe or unique, while the id is
    already the citation key everywhere else in the system (AD-6). Writing
    identical content twice (a retried request) is a no-op overwrite, not an
    error.
    """
    kind_dir = publish_root / kind
    kind_dir.mkdir(parents=True, exist_ok=True)
    relative_path = Path(kind) / f"{artifact_id}.md"
    (publish_root / relative_path).write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return relative_path


def ensure_git_repo(publish_root: Path) -> None:
    """Make ``publish_root`` a git working tree, idempotently.

    Called from the approve route on first ADR publish, never from startup
    validation (Design Notes): an install that never publishes an ADR never
    gets a `.git` directory it didn't ask for. A local `user.name`/
    `user.email` is set every time this runs (cheap, and safe to repeat) so a
    commit never fails on a missing global git identity.

    A pre-existing repository at the configured root is operator-authorized:
    configuration itself grants that authority.  Initialise only when Git
    metadata is absent, preserving existing history and local setup otherwise.
    """
    with _repository_lock(publish_root, artifact_id=None):
        _ensure_git_repo(publish_root)


def publish_adr(
    publish_root: Path, relative_path: Path, title: str, artifact_id: UUID
) -> str:
    """Atomically initialise, commit, and identify one ADR.

    This is the API-facing operation.  Its single repository lock covers
    every Git mutation and SHA lookup so different moments cannot race a
    shared index or accidentally record each other's commit.
    """
    with _repository_lock(publish_root, artifact_id=artifact_id):
        _ensure_git_repo(publish_root)
        return _commit_artifact(publish_root, relative_path, title, artifact_id)


def _ensure_git_repo(publish_root: Path) -> None:
    initialized_here = not (publish_root / ".git").exists()
    if initialized_here:
        init = _run(["git", "init"], publish_root, artifact_id=None)
        if init.returncode != 0:
            raise GitExportError(None, init.stderr)
    _ensure_local_identity(publish_root, "user.name", GIT_USER_NAME, initialized_here)
    _ensure_local_identity(publish_root, "user.email", GIT_USER_EMAIL, initialized_here)


def _ensure_local_identity(
    publish_root: Path, key: str, value: str, initialized_here: bool
) -> None:
    """Set MeetingMiner identity only for a new or locally-unset repository."""
    if not initialized_here:
        current = _run(
            ["git", "config", "--local", "--get", key], publish_root, artifact_id=None
        )
        if current.returncode == 0:
            return
        if current.returncode != 1:
            raise GitExportError(None, current.stderr)
    configured = _run(
        ["git", "config", "--local", key, value], publish_root, artifact_id=None
    )
    if configured.returncode != 0:
        raise GitExportError(None, configured.stderr)


def commit_artifact(
    publish_root: Path, relative_path: Path, title: str, artifact_id: UUID
) -> str:
    """`git add` + `git commit` one exported ADR; return the resulting sha.

    A commit that fails only because there is nothing to commit (an
    unchanged re-export) is not an error: this returns the current
    ``git rev-parse HEAD`` instead, so a retried request stays idempotent.
    Any other git failure raises :class:`GitExportError` naming the artifact
    id and git's stderr.
    """
    with _repository_lock(publish_root, artifact_id=artifact_id):
        return _commit_artifact(publish_root, relative_path, title, artifact_id)


def _commit_artifact(
    publish_root: Path, relative_path: Path, title: str, artifact_id: UUID
) -> str:
    add = _run(
        ["git", "add", "--", str(relative_path)], publish_root, artifact_id=artifact_id
    )
    if add.returncode != 0:
        raise GitExportError(artifact_id, add.stderr)

    # `git commit --only` reports a no-op differently across Git versions;
    # query just this path in the index before committing.  Unrelated staged
    # files deliberately do not affect this result.
    staged = _run(
        ["git", "diff", "--cached", "--quiet", "--", str(relative_path)],
        publish_root,
        artifact_id=artifact_id,
    )
    if staged.returncode == 0:
        return _artifact_commit_sha(publish_root, relative_path, artifact_id)
    if staged.returncode != 1:
        raise GitExportError(artifact_id, staged.stderr)

    commit = _run(
        [
            "git",
            "commit",
            "--only",
            "-m",
            f"Publish ADR: {title} ({artifact_id})",
            "--",
            str(relative_path),
        ],
        publish_root,
        artifact_id=artifact_id,
    )
    if commit.returncode != 0:
        if _NOTHING_TO_COMMIT in commit.stderr.lower() or _NOTHING_TO_COMMIT in (
            commit.stdout or ""
        ).lower():
            return _artifact_commit_sha(publish_root, relative_path, artifact_id)
        raise GitExportError(artifact_id, commit.stderr)

    return _artifact_commit_sha(publish_root, relative_path, artifact_id)


def _artifact_commit_sha(
    publish_root: Path, relative_path: Path, artifact_id: UUID
) -> str:
    sha = _run(
        ["git", "log", "-1", "--format=%H", "--", str(relative_path)],
        publish_root,
        artifact_id=artifact_id,
    )
    if sha.returncode != 0:
        raise GitExportError(artifact_id, sha.stderr)
    if not sha.stdout.strip():
        raise GitExportError(artifact_id, f"no git commit found for {relative_path}")
    return sha.stdout.strip()


@contextmanager
def _repository_lock(publish_root: Path, *, artifact_id: UUID | None):
    """Acquire the configured repository's bounded cross-process lock."""
    lock_file = None
    acquired = False
    try:
        try:
            lock_path = _repository_lock_path(publish_root)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open("a+", encoding="utf-8")
            deadline = time.monotonic() + _REPOSITORY_LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise GitExportError(
                            artifact_id,
                            "timed out waiting for the publish repository lock",
                        )
                    time.sleep(0.05)
        except OSError as exc:
            raise GitExportError(
                artifact_id, f"could not lock publish repository: {exc}"
            ) from exc
        yield
    finally:
        if lock_file is not None:
            if acquired:
                with suppress(OSError):
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            with suppress(OSError):
                lock_file.close()


def _repository_lock_path(publish_root: Path) -> Path:
    """Stable system-temp lock path for one resolved publish repository."""
    identity = hashlib.sha256(str(publish_root.resolve()).encode("utf-8")).hexdigest()
    return _REPOSITORY_LOCK_DIR / f"{identity}.lock"


def _run(
    args: list[str], cwd: Path, *, artifact_id: UUID | None
) -> subprocess.CompletedProcess[str]:
    """Run one git invocation, translating every non-exit-code failure mode
    into :class:`GitExportError` rather than letting it propagate raw.

    A non-zero exit is left to the caller (some callers — `commit_artifact`'s
    "nothing to commit" path — treat a specific non-zero exit as expected,
    not a failure). Everything that never gets as far as an exit code is not
    left to the caller: the git binary missing from ``PATH`` raises
    `FileNotFoundError` (a kind of `OSError`), a permission error raises
    `OSError`, and a call that outlives `_GIT_TIMEOUT_SECONDS` raises
    `subprocess.TimeoutExpired` — all three are caught here and re-raised as
    the one named exception the api route already knows how to turn into an
    RFC 9457 `Problem`, instead of surfacing as an unhandled 500.
    """
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=_sanitized_git_env(_GIT_ENV),
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except OSError as exc:
        raise GitExportError(artifact_id, f"{' '.join(args)}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitExportError(
            artifact_id,
            f"{' '.join(args)}: timed out after {_GIT_TIMEOUT_SECONDS}s",
        ) from exc


def _sanitized_git_env(environment: dict[str, str]) -> dict[str, str]:
    """Strip Git controls even if a caller inherited or injected them."""
    sanitized = {
        key: value for key, value in environment.items() if not key.startswith("GIT_")
    }
    sanitized.update({"LC_ALL": "C", "LANG": "C"})
    return sanitized


def remove_published(
    publish_root: Path, relative_paths: Sequence[Path], *, message: str
) -> str | None:
    """Delete exported artifact files and commit the removal; return the sha.

    The second caller of this module (the first is the approve route). When
    `prune` deletes a meeting, the markdown it published becomes a file whose
    artifact row no longer exists — no longer citable evidence, just an
    orphan. Removing it is a normal git commit, never a history rewrite: the
    published document is still recoverable from the repository's history,
    which is the whole reason the publish root is a git repository.

    Only the named paths are staged — never `git add -A`, which would sweep
    in whatever else an operator keeps in that directory. Paths already
    absent from the working tree are skipped rather than failing the run, so
    a re-run after a partial removal converges. Returns ``None`` when there
    was nothing to remove or nothing staged ended up differing from HEAD.
    """
    present = [path for path in relative_paths if (publish_root / path).exists()]
    if not present:
        return None

    with _repository_lock(publish_root, artifact_id=None):
        _ensure_git_repo(publish_root)

        # Only `adr` artifacts were ever committed (`publish_adr`);
        # `action-item` files are written to the working tree and left
        # untracked on purpose. `git add` on a path it does not track and
        # that no longer exists is a fatal pathspec error, so the tracked
        # subset is resolved *before* anything is unlinked. Untracked files
        # are simply deleted — there is no history for them to leave.
        tracked = _tracked_subset(publish_root, present)
        for path in present:
            (publish_root / path).unlink()
        if not tracked:
            return None

        args = ["git", "add", "--"] + [str(path) for path in tracked]
        added = _run(args, publish_root, artifact_id=None)
        if added.returncode != 0:
            raise GitExportError(None, added.stderr)

        staged = _run(["git", "diff", "--cached", "--quiet"], publish_root, artifact_id=None)
        if staged.returncode == 0:
            return None
        if staged.returncode != 1:
            raise GitExportError(None, staged.stderr)

        commit = _run(
            ["git", "commit", "-m", message], publish_root, artifact_id=None
        )
        if commit.returncode != 0:
            if _NOTHING_TO_COMMIT in commit.stderr.lower() or _NOTHING_TO_COMMIT in (
                commit.stdout or ""
            ).lower():
                return None
            raise GitExportError(None, commit.stderr)

        head = _run(["git", "rev-parse", "HEAD"], publish_root, artifact_id=None)
        if head.returncode != 0:
            raise GitExportError(None, head.stderr)
        return head.stdout.strip()


def _tracked_subset(publish_root: Path, paths: Sequence[Path]) -> list[Path]:
    """Which of these paths git actually tracks, in the order given."""
    listed = _run(
        ["git", "ls-files", "--"] + [str(path) for path in paths],
        publish_root,
        artifact_id=None,
    )
    if listed.returncode != 0:
        raise GitExportError(None, listed.stderr)
    known = {line.strip() for line in listed.stdout.splitlines() if line.strip()}
    return [path for path in paths if str(path) in known]
