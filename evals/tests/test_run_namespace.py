"""``Run.create`` owns its folder even when it loses the ``mkdir`` race.

``Run.create`` checks ``folder.exists()`` and then calls ``mkdir`` — a TOCTOU
window. Two concurrent runs resolving the same ``--run-id`` can both see
"no folder" and race the ``mkdir``; the loser must get the same ownership
refusal an up-front collision gets ("a run gets its own folder"), never the
generic "could not create the run folder" wrapper, because the generic wording
sends the operator after permissions and disk space when the actual finding is
that another run owns the namespace.

The race is simulated rather than raced: ``Path.exists`` is patched to answer
``False`` for the run folder alone (everything else — the ``verdict.md``
probe included — answers truthfully), while the folder really exists, so
``mkdir`` collides exactly as it would when a sibling run wins the window.

Store-free, and every folder is under ``tmp_path``: ``make evals-test`` must
leave ``evals/runs/`` untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evals.harness.run import CONFIG_SNAPSHOT_NAME, VERDICT_NAME, Run, RunError


class StubSecrets:
    postgres_password = "pw-not-read-here"


class StubConfig:
    """The duck-typed shape ``Run`` reads (mirrors ``test_run_artifacts.py``)."""

    settings: dict[str, Any] = {"service": "meetingminer"}
    secrets = StubSecrets()
    config_path = Path("/repo/config.yaml")


def lose_the_mkdir_race(
    monkeypatch: pytest.MonkeyPatch, folder: Path
) -> None:
    """Make ``folder.exists()`` lie the way the race window does.

    Only the run folder itself answers ``False``; every other path — the
    ``verdict.md`` probe inside the refusal — keeps its real answer, because
    the race is about the folder's creation, not about the filesystem at
    large.
    """
    real_exists = Path.exists

    def raced(self: Path, **kwargs: Any) -> bool:
        if self == folder:
            return False
        return real_exists(self, **kwargs)

    monkeypatch.setattr(Path, "exists", raced)


def test_a_lost_mkdir_race_gets_the_ownership_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loser's error names the namespace rule, not a filesystem mishap."""
    folder = tmp_path / "2026-08-30-left"
    folder.mkdir()
    lose_the_mkdir_race(monkeypatch, folder)

    with pytest.raises(RunError) as caught:
        Run.create("2026-08-30-left", config=StubConfig(), root=tmp_path)

    message = str(caught.value)
    assert "a run gets its own folder" in message
    assert str(folder) in message
    assert "could not create" not in message


def test_a_lost_race_onto_a_closed_folder_still_names_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verdict-holding folder is a closed audit record, and the race wording
    must not soften that: colliding with one names ``verdict.md``
    distinctly, exactly as the up-front refusal does."""
    folder = tmp_path / "2026-08-30-left"
    folder.mkdir()
    (folder / VERDICT_NAME).write_text("PASS")
    lose_the_mkdir_race(monkeypatch, folder)

    with pytest.raises(RunError) as caught:
        Run.create("2026-08-30-left", config=StubConfig(), root=tmp_path)

    message = str(caught.value)
    assert VERDICT_NAME in message
    assert str(folder) in message
    assert "could not create" not in message


def test_the_losing_run_writes_nothing_into_the_folder_it_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The winner's evidence stays untouched: no snapshot, no partial file."""
    folder = tmp_path / "2026-08-30-left"
    folder.mkdir()
    lose_the_mkdir_race(monkeypatch, folder)

    with pytest.raises(RunError):
        Run.create("2026-08-30-left", config=StubConfig(), root=tmp_path)

    assert list(folder.iterdir()) == []
    assert not (folder / CONFIG_SNAPSHOT_NAME).is_file()


def test_an_ordinary_create_error_keeps_its_own_wording(tmp_path: Path) -> None:
    """The generic wrapper survives for what it is for: a real filesystem
    refusal (here: the parent is a file, so ``mkdir(parents=True)`` fails
    with NotADirectoryError, not FileExistsError)."""
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("a file where the runs root should be")

    with pytest.raises(RunError) as caught:
        Run.create("2026-08-30-left", config=StubConfig(), root=blocked_root)

    assert "could not create" in str(caught.value)
