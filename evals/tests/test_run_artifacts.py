"""The run folder: created once, refused twice, and never carrying a secret.

Store-free: :class:`Run` takes a duck-typed config, so the immutability rules
and the redaction rule are exercised against a stub with a fabricated ``.env``
rather than against ``load_config``. That is deliberate — the store-free suite
must not depend on the real ``.env`` resolving, and a redaction test that
needed real secrets to run is a redaction test nobody runs.

Every run folder here is built under ``tmp_path``. ``make evals-test`` must
leave ``evals/runs/`` untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from evals.harness import checks
from evals.harness.checks import CheckResult
from evals.harness.run import (
    CONFIG_SNAPSHOT_NAME,
    MAX_NAME_LENGTH,
    REPORT_NAME,
    REQUIRED_CHECKS,
    VERDICT_NAME,
    Run,
    RunError,
    default_run_id,
    redact,
    resolved_settings,
    safe_name,
    scrub,
)

#: Values that only ever live in `.env`. The snapshot must contain none of
#: them, and the test greps for the literals rather than for key names.
SECRET_VALUES = {
    "postgres_password": "pg-secret-do-not-commit",
    "anthropic_api_key": "sk-ant-secret-do-not-commit",
    "meili_master_key": "meili-secret-do-not-commit",
}

RESOLVED_SETTINGS: dict[str, Any] = {
    "config_version": 1,
    "service": "meetingminer",
    "ocr": {"engine": "apple-vision", "fallback": "tesseract"},
    "llm": {"roles": {"extraction": {"model": "claude-sonnet-5"}}},
    "stores": {
        "postgres": {"host": "localhost", "port": 5433, "database": "meetingminer"}
    },
}


class StubSecrets:
    def __init__(self) -> None:
        for key, value in SECRET_VALUES.items():
            setattr(self, key, value)


class StubConfig:
    """The shape ``Run`` reads: settings, a config path, and secrets it must not touch."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = dict(settings if settings is not None else RESOLVED_SETTINGS)
        self.secrets = StubSecrets()
        self.config_path = Path("/repo/config.yaml")


class StubManifest:
    def __init__(self, manifest_id: str = "demo-001") -> None:
        self.id = manifest_id


class StubSubject:
    def __init__(self, manifest_id: str = "demo-001") -> None:
        self.manifest = StubManifest(manifest_id)
        self.source_id = f"source-{manifest_id}"
        self.meeting_id = f"meeting-{manifest_id}"
        self.job_id = f"job-{manifest_id}"
        self.title = "Scripted UI Demo"
        self.status = "succeeded"


def a_result(check: str = "2.1 capture recall", passed: bool = True, **kwargs: Any):
    return CheckResult(
        check=check,
        passed=passed,
        thresholds={"recall": 1.0},
        metrics={"recall": 1.0 if passed else 0.75},
        **kwargs,
    )


def make_run(tmp_path: Path, run_id: str = "2026-08-19-demo", **kwargs: Any) -> Run:
    return Run.create(run_id, config=StubConfig(), root=tmp_path, **kwargs)


REQUIRED_CHECK_ORDER = (
    checks.DURATION_AGREEMENT,
    checks.CAPTURE_RECALL,
    checks.OVER_CAPTURE,
    checks.VIEW_CLASSIFICATION,
    checks.DEDUP_QUALITY,
    checks.DOC_INDEX_SEARCH_RECALL,
    checks.PUBLISH_GATE_PROJECTION,
)


def record_completed_run(
    run: Run, subject: StubSubject, *, failed_check: str | None = None
) -> None:
    for check in REQUIRED_CHECK_ORDER:
        run.record(
            subject,
            a_result(
                check=check,
                passed=check != failed_check,
                blocking=check
                not in {checks.VIEW_CLASSIFICATION, checks.DEDUP_QUALITY},
            ),
        )


# --------------------------------------------------------------------------
# Folder creation and the two refusals
# --------------------------------------------------------------------------


def test_a_run_creates_its_folder_and_snapshots_the_configuration(
    tmp_path: Path,
) -> None:
    run = make_run(tmp_path, label="smoke")
    assert run.folder == tmp_path / "2026-08-19-demo"
    snapshot = yaml.safe_load((run.folder / CONFIG_SNAPSHOT_NAME).read_text())
    assert snapshot["settings"]["ocr"]["engine"] == "apple-vision"
    assert snapshot["run"]["label"] == "smoke"
    assert snapshot["config_path"] == "/repo/config.yaml"


def test_the_snapshot_records_the_engine_the_numbers_were_produced_by(
    tmp_path: Path,
) -> None:
    """A recall figure is only interpretable beside the OCR engine that read
    the text it scored — that is why the snapshot exists at all."""
    run = make_run(tmp_path)
    snapshot = yaml.safe_load((run.folder / CONFIG_SNAPSHOT_NAME).read_text())
    assert snapshot["settings"]["ocr"] == {
        "engine": "apple-vision",
        "fallback": "tesseract",
    }


def test_a_folder_holding_a_verdict_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    closed = tmp_path / "2026-08-19-demo"
    closed.mkdir()
    (closed / VERDICT_NAME).write_text("PASS")
    with pytest.raises(RunError) as caught:
        make_run(tmp_path)
    assert str(closed) in str(caught.value)
    assert VERDICT_NAME in str(caught.value)
    assert not (closed / CONFIG_SNAPSHOT_NAME).exists()


def test_an_interrupted_run_folder_is_refused_too(tmp_path: Path) -> None:
    """A rerun gets its own folder; partial evidence is never mixed with a
    fresh attempt's."""
    (tmp_path / "2026-08-19-demo").mkdir()
    with pytest.raises(RunError) as caught:
        make_run(tmp_path)
    assert "a run gets its own folder" in str(caught.value)


def test_two_runs_on_one_day_get_different_default_ids() -> None:
    from datetime import datetime, timezone

    moment = datetime(2026, 8, 19, 14, 23, 5, tzinfo=timezone.utc)
    assert default_run_id("capture", now=moment) == "2026-08-19-capture"
    assert default_run_id(None, now=moment) == "2026-08-19-142305"


# --------------------------------------------------------------------------
# The report: written once, and a serialization of the results
# --------------------------------------------------------------------------


def test_the_report_is_a_serialization_of_the_recorded_results(
    tmp_path: Path,
) -> None:
    run = make_run(tmp_path)
    subject = StubSubject()
    record_completed_run(run, subject)
    report = yaml.safe_load(run.write_report().read_text())

    assert report["passed"] is True
    assert report["config_snapshot"] == CONFIG_SNAPSHOT_NAME
    entry = report["subjects"][0]
    assert entry["manifest"] == "demo-001"
    assert entry["meeting_id"] == "meeting-demo-001"
    assert [check["check"] for check in entry["checks"]] == [
        *REQUIRED_CHECK_ORDER,
    ]
    assert entry["checks"][0]["thresholds"] == {"recall": 1.0}


def test_a_failed_blocking_check_makes_the_run_fail(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    run.record(StubSubject(), a_result(passed=False))
    assert yaml.safe_load(run.write_report().read_text())["passed"] is False


def test_a_failed_non_blocking_check_does_not(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    record_completed_run(run, StubSubject(), failed_check=checks.VIEW_CLASSIFICATION)
    assert yaml.safe_load(run.write_report().read_text())["passed"] is True


def test_a_run_that_measured_nothing_never_reports_a_pass(tmp_path: Path) -> None:
    """The *no silent zero* rule at the report level: no subjects is not a pass."""
    run = make_run(tmp_path)
    report = yaml.safe_load(run.write_report().read_text())
    assert report["passed"] is False
    assert report["subjects"] == []


def test_a_partial_subject_report_is_incomplete_and_never_passes(
    tmp_path: Path,
) -> None:
    """`-k` or an interrupt may select one check, never a passing full run."""
    assert set(REQUIRED_CHECK_ORDER) == REQUIRED_CHECKS
    run = make_run(tmp_path)
    run.record(
        StubSubject(),
        a_result(
            check=checks.VIEW_CLASSIFICATION,
            blocking=False,
        ),
    )
    report = yaml.safe_load(run.write_report().read_text())
    assert report["passed"] is False
    assert "missing required checks" in report["problems"][0]
    assert checks.CAPTURE_RECALL in report["problems"][0]
    assert checks.OVER_CAPTURE in report["problems"][0]
    # Story 5.3: the retrieval and publish-gate checks are required per
    # subject too — a report without them is incomplete, never passing.
    assert checks.DOC_INDEX_SEARCH_RECALL in report["problems"][0]
    assert checks.PUBLISH_GATE_PROJECTION in report["problems"][0]


def test_run_level_problems_land_in_the_report_and_fail_the_run(
    tmp_path: Path,
) -> None:
    run = make_run(tmp_path)
    run.note(
        "manifest 'demo-001' names source_id 'placeholder', which nothing answers to"
    )
    run.note(
        "manifest 'demo-001' names source_id 'placeholder', which nothing answers to"
    )
    record_completed_run(run, StubSubject())
    report = yaml.safe_load(run.write_report().read_text())
    assert report["passed"] is False
    assert len(report["problems"]) == 1, "a problem noted twice is one problem"


def test_the_report_is_written_once_and_never_edited(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    run.record(StubSubject(), a_result())
    run.write_report()
    with pytest.raises(RunError) as caught:
        run.write_report()
    assert "written once" in str(caught.value)


def test_the_finished_folder_holds_the_report_and_the_snapshot(
    tmp_path: Path,
) -> None:
    run = make_run(tmp_path)
    run.record(StubSubject(), a_result())
    run.write_report()
    assert sorted(path.name for path in run.folder.iterdir()) == [
        CONFIG_SNAPSHOT_NAME,
        REPORT_NAME,
    ]


# --------------------------------------------------------------------------
# The snapshot is secret-free
# --------------------------------------------------------------------------


def test_no_env_value_reaches_the_configuration_snapshot(tmp_path: Path) -> None:
    """Run folders are committed as the audit record, so a leak here is a
    committed secret."""
    run = make_run(tmp_path)
    text = (run.folder / CONFIG_SNAPSHOT_NAME).read_text()
    for value in SECRET_VALUES.values():
        assert value not in text


def test_the_configuration_snapshot_records_the_effective_api_endpoint(
    tmp_path: Path,
) -> None:
    run = Run.create(
        "2026-08-19-demo",
        config=StubConfig(),
        root=tmp_path,
        api_base_url="http://localhost:8765",
    )
    snapshot = yaml.safe_load((run.folder / CONFIG_SNAPSHOT_NAME).read_text())
    assert snapshot["api_base_url"] == "http://localhost:8765"


def test_no_env_value_reaches_the_report_either(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    run.record(StubSubject(), a_result())
    text = run.write_report().read_text()
    for value in SECRET_VALUES.values():
        assert value not in text


def test_a_secret_shaped_key_added_to_config_yaml_is_redacted(
    tmp_path: Path,
) -> None:
    """Defence against the next key, not against today's `config.yaml`.

    Nothing in the shipped config is secret-shaped; the snapshot stays
    secret-free when somebody adds a key to it without reading `run.py`.
    """
    settings = {
        **RESOLVED_SETTINGS,
        "providers": {
            "anthropic": {"base_url": "https://api.anthropic.com", "api_key": "sk-leak"}
        },
        "stores": {
            "meilisearch": {"url": "http://localhost:7700", "master_key": "leak"}
        },
    }
    run = Run.create("2026-08-19-demo", config=StubConfig(settings), root=tmp_path)
    snapshot = yaml.safe_load((run.folder / CONFIG_SNAPSHOT_NAME).read_text())
    assert snapshot["settings"]["providers"]["anthropic"]["api_key"] == "[redacted]"
    assert snapshot["settings"]["stores"]["meilisearch"]["master_key"] == "[redacted]"
    assert (
        snapshot["settings"]["providers"]["anthropic"]["base_url"]
        == "https://api.anthropic.com"
    )


def test_private_key_and_authorization_settings_are_redacted(tmp_path: Path) -> None:
    settings = {
        **RESOLVED_SETTINGS,
        "integration": {
            "private_key": "private-key-leak",
            "authorization": "Bearer authorization-leak",
            "endpoint": "https://token-url-leak@host.example",
        },
    }
    run = Run.create("2026-08-19-demo", config=StubConfig(settings), root=tmp_path)
    text = (run.folder / CONFIG_SNAPSHOT_NAME).read_text()
    for secret in ("private-key-leak", "authorization-leak", "token-url-leak"):
        assert secret not in text
    assert "host.example" in text


def test_redaction_walks_lists_as_well_as_mappings() -> None:
    assert redact({"roles": [{"model": "x", "api_key": "leak"}]}) == {
        "roles": [{"model": "x", "api_key": "[redacted]"}]
    }


def test_a_key_that_merely_ends_in_key_is_not_redacted() -> None:
    """`identity_key` is configuration, not a credential — redacting it would
    hide a real setting from the audit record."""
    assert redact({"identity_key": "sha256:abc"}) == {"identity_key": "sha256:abc"}


def test_resolved_settings_dumps_a_pydantic_model_without_touching_secrets() -> None:
    class Model:
        def model_dump(self, mode: str | None = None) -> dict[str, Any]:
            return {"ocr": {"engine": "tesseract"}}

    class Config:
        settings = Model()

        @property
        def secrets(self) -> Any:  # pragma: no cover - reading it is the failure
            raise AssertionError("the snapshot must never read .env secrets")

    assert resolved_settings(Config()) == {"ocr": {"engine": "tesseract"}}


# --------------------------------------------------------------------------
# A run id names a folder, so it may not name a path
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["..", "../../etc", "evil/../..", "runs/nested", "/absolute", ".hidden", "", "a b"],
)
def test_a_run_id_that_could_climb_out_of_the_runs_folder_is_refused(
    name: str, tmp_path: Path
) -> None:
    """`--run-id` is joined onto `evals/runs/`. Without this, `--run-id ../..`
    writes the audit record over whatever is up there."""
    with pytest.raises(RunError):
        Run.create(name, config=StubConfig(), root=tmp_path)


def test_a_refused_run_id_creates_nothing(tmp_path: Path) -> None:
    with pytest.raises(RunError):
        Run.create("../escape", config=StubConfig(), root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_an_unsafe_label_is_refused_too(tmp_path: Path) -> None:
    """The label becomes the second half of a default run id, so it reaches the
    same join by another route."""
    with pytest.raises(RunError):
        Run.create("2026-08-19-demo", config=StubConfig(), root=tmp_path, label="../x")
    with pytest.raises(RunError):
        default_run_id("../x")


def test_an_over_long_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RunError) as caught:
        Run.create("a" * (MAX_NAME_LENGTH + 1), config=StubConfig(), root=tmp_path)
    assert str(MAX_NAME_LENGTH) in str(caught.value)


@pytest.mark.parametrize("name", ["2026-08-19-capture", "bakeoff-2026-08-19", "r1.2_3"])
def test_the_run_ids_an_operator_actually_types_are_accepted(name: str) -> None:
    assert safe_name(name, field="--run-id") == name


def test_the_error_says_why_rather_than_silently_renaming(tmp_path: Path) -> None:
    """Sanitizing an operator's `--run-id` would file the audit record
    somewhere they did not ask for and will not look."""
    with pytest.raises(RunError) as caught:
        Run.create("../escape", config=StubConfig(), root=tmp_path)
    assert "--run-id" in str(caught.value)
    assert "path separator" in str(caught.value)


# --------------------------------------------------------------------------
# A credential inside an otherwise-informative value
# --------------------------------------------------------------------------


def test_a_credential_in_a_url_is_scrubbed_without_losing_the_endpoint() -> None:
    """Key-name redaction cannot see this one: `uri` is a benign key and the
    endpoint is exactly what makes the snapshot interpretable."""
    assert (
        scrub("bolt://neo4j:hunter2@localhost:7687")
        == "bolt://[redacted]@localhost:7687"
    )


def test_a_credential_in_a_query_string_is_scrubbed() -> None:
    assert scrub("http://localhost:7700/indexes?apiKey=abc123&limit=5") == (
        "http://localhost:7700/indexes?apiKey=[redacted]&limit=5"
    )


def test_authorization_in_a_query_string_is_scrubbed() -> None:
    assert scrub("https://host.example?authorization=secret&limit=5") == (
        "https://host.example?authorization=[redacted]&limit=5"
    )


def test_a_libpq_keyword_credential_is_scrubbed() -> None:
    """The shape a `conninfo` takes when it is not a URL."""
    assert scrub("host=localhost port=5433 password=hunter2 dbname=mm") == (
        "host=localhost port=5433 password=[redacted] dbname=mm"
    )


def test_an_ordinary_endpoint_survives_untouched() -> None:
    for value in (
        "https://api.anthropic.com",
        "http://localhost:11434",
        "bolt://localhost:7687",
    ):
        assert scrub(value) == value


def test_a_credential_url_reaches_the_snapshot_scrubbed(tmp_path: Path) -> None:
    settings = {
        **RESOLVED_SETTINGS,
        "stores": {
            "neo4j": {"uri": "bolt://neo4j:pg-secret-do-not-commit@localhost:7687"}
        },
    }
    run = Run.create("2026-08-19-demo", config=StubConfig(settings), root=tmp_path)
    text = (run.folder / CONFIG_SNAPSHOT_NAME).read_text()
    assert "pg-secret-do-not-commit" not in text
    assert "localhost:7687" in text, "the endpoint is the audit record's point"


def test_url_shaped_keys_are_not_blanked_wholesale() -> None:
    """`base_url` stays readable on purpose: a judge score is only
    interpretable beside the provider it was produced by."""
    dumped = redact(
        {"providers": {"anthropic": {"base_url": "https://api.anthropic.com"}}}
    )
    assert dumped["providers"]["anthropic"]["base_url"] == "https://api.anthropic.com"


def test_a_dsn_or_conninfo_key_loses_its_whole_value() -> None:
    """Neither ever holds anything but a credential-carrying string, so there
    is nothing to preserve."""
    assert redact({"dsn": "postgres://u:p@h/db", "conninfo": "host=h password=p"}) == {
        "dsn": "[redacted]",
        "conninfo": "[redacted]",
    }


def test_scrubbing_reaches_values_nested_in_lists() -> None:
    assert redact({"fallbacks": ["https://ok.example", "bolt://u:p@h:7687"]}) == {
        "fallbacks": ["https://ok.example", "bolt://[redacted]@h:7687"]
    }
