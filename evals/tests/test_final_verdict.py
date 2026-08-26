"""Store-free tests for generated, auditable final eval verdicts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from evals.harness import checks
from evals.harness.run import (
    HUMAN_VERDICTS_NAME,
    REPORT_NAME,
    REQUIRED_CHECKS,
    VERDICT_NAME,
)
from evals.harness.verdict import (
    REQUIRED_WORKSHEETS,
    VerdictError,
    evaluate_final_verdict,
    finalize,
    main,
)

RUN_ID = "2026-08-20-final-verdict"


def report(
    folder: Path,
    *,
    failed: str | None = checks.CAPTURE_RECALL,
    problems: list[str] | None = None,
    inapplicable: str | None = None,
    reported_passed: bool | None = None,
) -> Path:
    records = []
    for name in sorted(REQUIRED_CHECKS):
        blocking = name not in {checks.VIEW_CLASSIFICATION, checks.DEDUP_QUALITY}
        records.append(
            {
                "check": name,
                "passed": name != failed,
                "blocking": blocking,
                "applicable": name != inapplicable,
                "thresholds": {},
                "metrics": {},
                "detail": [],
                "problems": [],
            }
        )
    path = folder / REPORT_NAME
    path.write_text(
        yaml.safe_dump(
            {
                "run": {"id": RUN_ID},
                "passed": (
                    failed is None and not problems and inapplicable is None
                    if reported_passed is None
                    else reported_passed
                ),
                "problems": problems or [],
                "subjects": [{"manifest": "demo-001", "checks": records}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def human(
    folder: Path,
    *,
    rulings: list[dict[str, str]] | None = None,
    advisory: list[dict[str, str]] | None = None,
    **overrides: Any,
) -> Path:
    worksheets: dict[str, list[dict[str, str]]] = {name: [] for name in REQUIRED_WORKSHEETS}
    worksheets["capture-recall-failures"] = rulings or []
    worksheets["dedup-candidates"] = advisory or []
    payload: dict[str, Any] = {
        "version": 1,
        "run": RUN_ID,
        "judge": "A. Operator",
        "completed_at": "2026-08-20T18:30:00+00:00",
        "worksheets": worksheets,
    }
    payload.update(overrides)
    path = folder / HUMAN_VERDICTS_NAME
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def ruling(
    *,
    check: str = checks.CAPTURE_RECALL,
    item: str = "check result",
    verdict: str = "pass",
    kind: str = "reconciliation",
) -> dict[str, str]:
    return {
        "manifest": "demo-001",
        "check": check,
        "item": item,
        "kind": kind,
        "verdict": verdict,
        "reason": "The source recording proves this measurement was wrong.",
    }


def test_a_complete_human_pass_override_generates_pass_without_changing_report(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report_path = report(folder)
    before = report_path.read_bytes()
    human_path = human(folder, rulings=[ruling()])

    result = finalize(folder)

    assert result.passed is True
    assert report_path.read_bytes() == before
    text = (folder / VERDICT_NAME).read_text()
    assert "# Final verdict: PASS" in text
    assert "demo-001` / `2.1 capture recall` / `check result`: **PASS**" in text
    assert ruling()["reason"] in text
    assert hashlib.sha256(before).hexdigest() in text
    assert hashlib.sha256(human_path.read_bytes()).hexdigest() in text


def test_an_unreconciled_blocking_failure_refuses_to_close_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(folder)

    with pytest.raises(VerdictError, match="do not reconcile"):
        finalize(folder)

    assert not (folder / VERDICT_NAME).exists()


def test_a_human_fail_reconciles_the_target_but_generates_fail(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(folder, rulings=[ruling(verdict="fail")])

    result = finalize(folder)

    assert result.passed is False
    assert "# Final verdict: FAIL" in (folder / VERDICT_NAME).read_text()


def test_invalid_or_mismatched_human_artifacts_refuse_before_writing(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    path = folder / HUMAN_VERDICTS_NAME
    path.write_text("run: [not a string", encoding="utf-8")

    with pytest.raises(VerdictError, match="not valid YAML"):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()

    human(folder, run="another-run")
    with pytest.raises(VerdictError, match="does not match"):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.pop("judge"), "judge"),
        (lambda payload: payload["worksheets"].pop("dedup-candidates"), "incomplete"),
        (
            lambda payload: payload["worksheets"]["capture-recall-failures"].append(
                {
                    "manifest": "demo-001",
                    "check": checks.CAPTURE_RECALL,
                    "item": "missing reason",
                    "kind": "reconciliation",
                    "verdict": "pass",
                }
            ),
            "reason",
        ),
    ],
)
def test_incomplete_human_metadata_or_records_refuse_before_writing(
    tmp_path: Path, mutate: Any, message: str
) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human_path = human(folder)
    payload = yaml.safe_load(human_path.read_text())
    mutate(payload)
    human_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(VerdictError, match=message):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()


@pytest.mark.parametrize("version", [True, 1.0])
def test_human_verdict_version_must_be_a_builtin_integer(tmp_path: Path, version: Any) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(folder, rulings=[ruling()], version=version)

    with pytest.raises(VerdictError, match="version"):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(completed_at="2026-08-20T18:30:00+01:00"), "UTC"),
        (
            lambda payload: payload["worksheets"]["capture-recall-failures"].append(
                {
                    **ruling(),
                    "reason": "First line\nsecond line",
                }
            ),
            "one line",
        ),
    ],
)
def test_human_timestamp_and_reason_are_auditable_one_line_utc_values(
    tmp_path: Path, mutate: Any, message: str
) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human_path = human(folder, rulings=[ruling()])
    payload = yaml.safe_load(human_path.read_text())
    mutate(payload)
    human_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(VerdictError, match=message):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()


@pytest.mark.parametrize(
    ("rulings", "message"),
    [
        ([ruling(), ruling(item="another row")], "duplicate reconciliation"),
        ([ruling(check=checks.VIEW_CLASSIFICATION)], "only failed applicable blocking"),
        ([ruling(check=checks.OVER_CAPTURE)], "only failed applicable blocking"),
    ],
)
def test_duplicate_or_nonfailed_reconciliation_targets_are_refused(
    tmp_path: Path, rulings: list[dict[str, str]], message: str
) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(folder, rulings=rulings)

    with pytest.raises(VerdictError, match=message):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()


def test_advisory_pass_on_an_actual_report_check_can_coexist_with_a_pass_override(
    tmp_path: Path,
) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(
        folder,
        rulings=[ruling()],
        advisory=[
            ruling(
                check=checks.DEDUP_QUALITY,
                item="captures 4+5",
                kind="advisory",
            )
        ],
    )

    result = finalize(folder)

    assert result.passed is True
    assert "**Advisory**" in (folder / VERDICT_NAME).read_text()


def test_an_advisory_fail_makes_the_generated_final_verdict_fail(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(
        folder,
        rulings=[ruling()],
        advisory=[
            ruling(
                check=checks.DEDUP_QUALITY,
                item="captures 4+5",
                kind="advisory",
                verdict="fail",
            )
        ],
    )

    result = finalize(folder)

    assert result.passed is False
    assert "# Final verdict: FAIL" in (folder / VERDICT_NAME).read_text()


def test_multiple_advisory_rows_for_the_same_check_are_auditable(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(
        folder,
        rulings=[ruling()],
        advisory=[
            ruling(check=checks.DEDUP_QUALITY, item="captures 4+5", kind="advisory"),
            ruling(check=checks.DEDUP_QUALITY, item="captures 8+9", kind="advisory"),
        ],
    )

    result = finalize(folder)

    assert result.passed is True
    text = (folder / VERDICT_NAME).read_text()
    assert "captures 4+5" in text
    assert "captures 8+9" in text


def test_advisory_rulings_cannot_invent_a_report_target(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(
        folder,
        rulings=[ruling()],
        advisory=[ruling(check="not a report check", item="invented", kind="advisory")],
    )

    with pytest.raises(VerdictError, match="actual deterministic report check"):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()


@pytest.mark.parametrize(
    ("problems", "inapplicable", "subject_count", "expected"),
    [
        (["unmatched manifest"], None, 1, "run-level problem"),
        ([], checks.CAPTURE_RECALL, 1, "inapplicable"),
        ([], None, 0, "zero subjects"),
    ],
)
def test_report_integrity_problems_cannot_be_overridden(
    tmp_path: Path,
    problems: list[str],
    inapplicable: str | None,
    subject_count: int,
    expected: str,
) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report_path = report(folder, problems=problems, inapplicable=inapplicable)
    if subject_count == 0:
        data = yaml.safe_load(report_path.read_text())
        data["subjects"] = []
        report_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    human(folder, rulings=[ruling()] if problems else [])

    result = finalize(folder)

    assert result.passed is False
    assert expected in (folder / VERDICT_NAME).read_text()


@pytest.mark.parametrize(
    ("failed", "reported_passed"),
    [(checks.CAPTURE_RECALL, True), (None, False)],
)
def test_report_passed_must_agree_with_report_contents_in_both_directions(
    tmp_path: Path, failed: str | None, reported_passed: bool
) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder, failed=failed, reported_passed=reported_passed)
    human(folder, rulings=[ruling()] if failed else [])

    result = finalize(folder)

    assert result.passed is False
    assert "does not agree" in (folder / VERDICT_NAME).read_text()


def test_each_failed_blocking_check_needs_its_own_reconciliation(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report_path = report(folder)
    payload = yaml.safe_load(report_path.read_text())
    for check in payload["subjects"][0]["checks"]:
        if check["check"] == checks.OVER_CAPTURE:
            check["passed"] = False
    report_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    human(folder, rulings=[ruling()])

    with pytest.raises(VerdictError, match="do not reconcile"):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()


def test_integrity_problem_does_not_remove_the_reconciliation_requirement(
    tmp_path: Path,
) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder, problems=["unmatched manifest"])
    human(folder)

    with pytest.raises(VerdictError, match="do not reconcile"):
        finalize(folder)
    assert not (folder / VERDICT_NAME).exists()


def test_missing_required_check_is_non_overridable_integrity_problem(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report_path = report(folder, failed=None)
    data = yaml.safe_load(report_path.read_text())
    data["subjects"][0]["checks"].pop()
    report_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    human(folder)

    result = evaluate_final_verdict(folder)

    assert result.passed is False
    assert any("missing required checks" in problem for problem in result.integrity_problems)


def test_a_final_verdict_cannot_be_overwritten(tmp_path: Path) -> None:
    folder = tmp_path / RUN_ID
    folder.mkdir()
    report(folder)
    human(folder, rulings=[ruling()])
    finalize(folder)

    with pytest.raises(VerdictError, match="already exists"):
        finalize(folder)
    assert not list(folder.glob(".verdict.md.*.tmp"))


def test_cli_returns_zero_for_generated_pass_and_one_for_generated_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    passing = tmp_path / RUN_ID
    passing.mkdir()
    report(passing)
    human(passing, rulings=[ruling()])
    assert main([str(passing)]) == 0
    assert "PASS" in capsys.readouterr().out

    failing = tmp_path / f"{RUN_ID}-fail"
    failing.mkdir()
    report_path = report(failing)
    report_payload = yaml.safe_load(report_path.read_text())
    report_payload["run"]["id"] = failing.name
    report_path.write_text(yaml.safe_dump(report_payload, sort_keys=False), encoding="utf-8")
    human_path = human(failing, rulings=[ruling(verdict="fail")])
    human_payload = yaml.safe_load(human_path.read_text())
    human_payload["run"] = failing.name
    human_path.write_text(yaml.safe_dump(human_payload, sort_keys=False), encoding="utf-8")
    assert main([str(failing)]) == 1
    assert "FAIL" in capsys.readouterr().out
