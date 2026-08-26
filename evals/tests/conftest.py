"""Valid-manifest builders for the eval suite, and its one standing guarantee.

Mirrors ``server/tests/conftest.valid_metadata``: one function per shape that
returns a *valid* instance and takes keyword overrides, so every negative test
differs from a passing one by exactly the thing under test. A test that built
its own dict from scratch could fail for a reason it did not name.

Also home to :func:`runs_folder_untouched`, which holds the whole store-free
suite to its advertised property: it creates no run folder.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from evals.harness.run import RUNS_ROOT

VALID_UI_DEMO: dict[str, Any] = {
    "meeting": {
        "id": "demo-fixture-ui",
        "source_id": "source-ui-1",
        "title": "Scripted UI Demo — Orders Module",
        "archetype": "ui-demo",
        "duration_minutes": 12,
        "participants": [{"name": "Tim Goeke", "role": "presenter"}],
    },
    "screens": [
        {
            "id": "SC1",
            "name": "Order List",
            "shown_at": "00:01:30",
            "ocr_anchor": "Order Search Results",
        },
        {
            "id": "SC2",
            "name": "Order Detail",
            "shown_at": "00:03:05",
            "ocr_anchor": "Line Items and Tax Breakdown",
        },
    ],
    "participant_segments": [
        {"at": "00:00:00", "label": "meeting start"},
        {"at": "00:08:10", "label": "sharing stops"},
    ],
    "planted": {
        "action_items": [
            {
                "id": "AI1",
                "text": "Update the tax table mapping by Friday",
                "speaker": "Tim Goeke",
                "at": "00:04:12",
            }
        ],
        "decisions": [
            {
                "id": "D1",
                "text": "Orders module keeps optimistic locking",
                "speaker": "Tim Goeke",
                "at": "00:06:02",
            }
        ],
        "phrases": [
            {
                "id": "P1",
                "text": "purple elephant deployment window",
                "speaker": "Tim Goeke",
                "at": "00:03:20",
            }
        ],
    },
    "qa": [
        {
            "id": "Q1",
            "question": "What did Tim decide about locking in the Orders module?",
            "expected_moment": "D1",
            "answer_must_contain": ["optimistic locking"],
        }
    ],
}

VALID_SLIDE_DECK: dict[str, Any] = {
    "meeting": {
        "id": "demo-fixture-deck",
        "source_id": "source-deck-1",
        "title": "Q3 Architecture Review",
        "archetype": "slide-deck",
        "duration_minutes": 18,
        "participants": [{"name": "Tim Goeke", "role": "presenter"}],
    },
    "slides": [
        {
            "id": "S1",
            "title": "Q3 Architecture Review",
            "shown_at": "00:00:45",
            "ocr_anchor": "Q3 Architecture Review",
        },
        {
            "id": "S2",
            "title": "Evidence Pipeline Today",
            "shown_at": "00:03:10",
            "ocr_anchor": "Evidence Pipeline Today",
        },
        {
            "id": "S3",
            "title": "Publish Gate",
            "shown_at": "00:10:05",
            "ocr_anchor": "Nothing Enters a Store Before Approval",
        },
    ],
    "participant_segments": [{"at": "00:00:00", "label": "meeting start"}],
    "planted": {
        "decisions": [
            {
                "id": "D1",
                "text": "The document index stays a separate store from the graph",
                "speaker": "Tim Goeke",
                "at": "00:07:15",
            }
        ]
    },
    "qa": [
        {
            "id": "Q1",
            "question": "Why is the document index a separate store?",
            "expected_moment": "D1",
            "answer_must_contain": ["document index"],
        }
    ],
}


def valid_ui_demo(**overrides: Any) -> dict[str, Any]:
    """A manifest that validates clean, with top-level keys replaceable.

    Deep-copied: a test that mutates a nested list must not leak into the
    next one.
    """
    manifest = copy.deepcopy(VALID_UI_DEMO)
    manifest.update(copy.deepcopy(overrides))
    return manifest


def valid_slide_deck(**overrides: Any) -> dict[str, Any]:
    manifest = copy.deepcopy(VALID_SLIDE_DECK)
    manifest.update(copy.deepcopy(overrides))
    return manifest


def meeting_of(manifest: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """The manifest's `meeting` block with fields replaced.

    Saves every caller from spelling out the whole block to change one field.
    """
    meeting = copy.deepcopy(manifest["meeting"])
    meeting.update(overrides)
    return meeting


def _runs_snapshot() -> frozenset[str] | None:
    """What ``evals/runs/`` holds right now, or ``None`` if it does not exist."""
    if not RUNS_ROOT.exists():
        return None
    return frozenset(path.name for path in RUNS_ROOT.iterdir())


@pytest.fixture(scope="session", autouse=True)
def runs_folder_untouched() -> Any:
    """``make evals-test`` must leave ``evals/runs/`` exactly as it found it.

    Advertised in AGENTS.md, in the Makefile comment and in this suite's own
    docstrings, and until now true only by the convention that every test
    passes ``root=tmp_path``. One test calling ``Run.create`` without it would
    create a folder under the *real* ``evals/runs/`` — which is committed as
    the audit record, so it would arrive in a commit as a run nobody ran.

    Compares names rather than asserting the folder is absent: real run folders
    are committed, so once the scripted meetings are recorded this directory is
    populated and "absent" stops being the right assertion. What must hold is
    that this suite changed nothing.
    """
    before = _runs_snapshot()
    yield
    after = _runs_snapshot()
    assert after == before, (
        "the store-free eval suite changed evals/runs/ — it must create no run"
        f" folder. Before: {sorted(before) if before else before}."
        f" After: {sorted(after) if after else after}."
        " A test calling Run.create() needs root=tmp_path."
    )
