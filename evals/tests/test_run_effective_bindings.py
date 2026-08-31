"""Story 8.2: a run's snapshot records the binding that answered, not only the file's.

A run is only reproducible if the snapshot says which model produced the
numbers. Once a selection can override `config.yaml` (story 8.2), the file's
`llm.roles.<role>.model` is no longer that answer, and a snapshot carrying only
the file would name a model the run may never have called.

The effective binding is read through `GET /settings/models` rather than from
Postgres. AD-16 makes the harness a client: the api already computes the
effective binding with the one shared rule, so reading it over HTTP keeps a
single implementation and needs no widening of the import guard in
`test_harness_boundary.py`.

No api is contacted here — every call goes through an injected transport, the
same way `harness/retrieval.py` is tested.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from evals.harness.run import (
    CONFIG_SNAPSHOT_NAME,
    Run,
    fetch_effective_bindings,
)


class StubConfig:
    """The shape `Run` reads: settings, a config path, and secrets it never touches.

    Defined here rather than imported from `test_run_artifacts`: this module
    needs three attributes, and importing another test module's helper would
    couple two suites that have no reason to move together.
    """

    def __init__(self) -> None:
        self.settings = {"ocr": {"engine": "apple-vision"}}
        self.secrets = object()
        self.config_path = Path("/repo/config.yaml")


SETTINGS_PAYLOAD: dict[str, Any] = {
    "roles": [
        {
            "role": "chat",
            "catalog": [
                {"binding": "openai/gpt-5.2", "label": "GPT-5.2", "provider": "openai"},
                {
                    "binding": "ollama/gpt-oss:120b",
                    "label": "GPT-OSS 120B (local)",
                    "provider": "ollama",
                },
            ],
            "default": "openai/gpt-5.2",
            "fileBinding": "openai/gpt-5.2",
            "selected": "ollama/gpt-oss:120b",
            "effectiveBinding": "ollama/gpt-oss:120b",
            "provider": "ollama",
            "source": "selection",
            "staleSelection": None,
            "staleReason": None,
        },
        {
            "role": "extraction",
            "catalog": [
                {
                    "binding": "ollama/gpt-oss:120b",
                    "label": "GPT-OSS 120B (local)",
                    "provider": "ollama",
                }
            ],
            "default": "ollama/gpt-oss:120b",
            "fileBinding": "ollama/gpt-oss:120b",
            "selected": None,
            "effectiveBinding": "ollama/gpt-oss:120b",
            "provider": "ollama",
            "source": "file-default",
            "staleSelection": None,
            "staleReason": None,
        },
    ]
}


def _serving(payload: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/settings/models", request.url.path
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _refusing(exc: Exception) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return httpx.MockTransport(handler)


def test_the_effective_binding_is_read_from_the_api() -> None:
    bindings = fetch_effective_bindings(
        "http://localhost:8765", transport=_serving(SETTINGS_PAYLOAD)
    )

    assert bindings["problem"] is None
    chat = bindings["roles"]["chat"]
    assert chat["effective"] == "ollama/gpt-oss:120b"
    assert chat["provider"] == "ollama"
    assert chat["selection_source"] == "selection"
    # The file's own values travel *beside* it, never replaced by it.
    assert chat["file_model"] == "openai/gpt-5.2"
    assert chat["file_default"] == "openai/gpt-5.2"


def test_a_role_nobody_has_chosen_for_records_the_file_default() -> None:
    bindings = fetch_effective_bindings(
        "http://localhost:8765", transport=_serving(SETTINGS_PAYLOAD)
    )

    extraction = bindings["roles"]["extraction"]
    assert extraction["effective"] == extraction["file_default"]
    assert extraction["selection_source"] == "file-default"
    assert extraction["selected"] is None


def test_an_unreachable_api_is_a_named_problem_rather_than_a_guess() -> None:
    """A snapshot that invented the file value would misreport a real run.

    The run still starts — the numbers are worth having — but the record says
    the effective binding could not be read, and names why.
    """
    bindings = fetch_effective_bindings(
        "http://localhost:8765",
        transport=_refusing(httpx.ConnectError("connection refused")),
    )

    assert bindings["roles"] == {}
    assert "connection refused" in bindings["problem"]
    assert "/settings/models" in bindings["problem"]


def test_a_malformed_payload_is_a_named_problem_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    bindings = fetch_effective_bindings(
        "http://localhost:8765", transport=httpx.MockTransport(handler)
    )

    assert bindings["roles"] == {}
    assert bindings["problem"]


def test_no_api_base_url_is_recorded_as_such(tmp_path: Path) -> None:
    """A run started without `--api-base-url` cannot read the selection."""
    bindings = fetch_effective_bindings(None)

    assert bindings["roles"] == {}
    assert "api" in bindings["problem"].lower()


# --- what lands in the snapshot ---------------------------------------------


def _snapshot(run: Run) -> dict[str, Any]:
    return yaml.safe_load((run.folder / CONFIG_SNAPSHOT_NAME).read_text())


def test_the_snapshot_records_the_effective_binding_beside_the_file_value(
    tmp_path: Path,
) -> None:
    run = Run.create(
        "2026-08-30-bindings",
        config=StubConfig(),
        root=tmp_path,
        effective_bindings=fetch_effective_bindings(
            "http://localhost:8765", transport=_serving(SETTINGS_PAYLOAD)
        ),
    )

    snapshot = _snapshot(run)
    chat = snapshot["llm_bindings"]["roles"]["chat"]
    assert chat["effective"] == "ollama/gpt-oss:120b"
    assert chat["file_model"] == "openai/gpt-5.2"
    assert snapshot["llm_bindings"]["problem"] is None
    # The resolved-configuration block is untouched beside it.
    assert "settings" in snapshot


def test_a_run_created_without_bindings_still_snapshots(tmp_path: Path) -> None:
    """The keyword is optional: no eval run may fail to start over this."""
    run = Run.create("2026-08-30-nobindings", config=StubConfig(), root=tmp_path)

    snapshot = _snapshot(run)
    assert snapshot["llm_bindings"]["roles"] == {}
    assert snapshot["llm_bindings"]["problem"]


def test_a_credential_in_the_api_url_is_scrubbed_from_the_bindings_block(
    tmp_path: Path,
) -> None:
    """The snapshot's secret rules apply to this block like any other."""
    run = Run.create(
        "2026-08-30-scrub",
        config=StubConfig(),
        root=tmp_path,
        effective_bindings={
            "problem": None,
            "source": "http://user:hunter2@localhost:8765/settings/models",
            "roles": {},
        },
    )

    text = json.dumps(_snapshot(run))
    assert "hunter2" not in text


def test_the_problem_is_recorded_in_the_snapshot_not_as_a_run_failure(
    tmp_path: Path,
) -> None:
    """An unreadable effective binding is a provenance gap, not a failed run.

    Whether it should invalidate a verdict is a question about the verdict.
    The snapshot names it; the checks decide whether the run passed.
    """
    run = Run.create(
        "2026-08-30-noted",
        config=StubConfig(),
        root=tmp_path,
        effective_bindings=fetch_effective_bindings(
            "http://localhost:8765",
            transport=_refusing(httpx.ConnectError("connection refused")),
        ),
    )

    assert "connection refused" in _snapshot(run)["llm_bindings"]["problem"]
    # Not pushed onto the run's problem list, which is what fails a run: an
    # empty run is already not "passed" for its own reasons, so the assertion
    # is that this problem is not among the reasons.
    report = yaml.safe_load(Path(run.write_report()).read_text())
    assert not any("settings/models" in problem for problem in report["problems"])


@pytest.mark.parametrize("role", ["chat", "extraction"])
def test_every_role_the_api_reports_reaches_the_snapshot(
    tmp_path: Path, role: str
) -> None:
    run = Run.create(
        f"2026-08-30-roles-{role}",
        config=StubConfig(),
        root=tmp_path,
        effective_bindings=fetch_effective_bindings(
            "http://localhost:8765", transport=_serving(SETTINGS_PAYLOAD)
        ),
    )

    assert role in _snapshot(run)["llm_bindings"]["roles"]
