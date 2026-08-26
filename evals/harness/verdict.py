"""Generate an auditable final verdict without rewriting deterministic evidence.

The deterministic report remains the factual record of what the harness
measured.  This module is deliberately a post-suite step: it may record a
human ruling about an applicable failed blocking result, but it never changes
``deterministic-report.yaml`` or its ``passed`` field.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from evals.harness.run import (
    HUMAN_VERDICTS_NAME,
    REPORT_NAME,
    REQUIRED_CHECKS,
    VERDICT_NAME,
)

HUMAN_VERDICTS_VERSION = 1
REQUIRED_WORKSHEETS = (
    "capture-recall-failures",
    "dedup-candidates",
    "action-item-matches",
    "adr-decision-quality",
    "qa-right-moment-cited",
)


class VerdictError(Exception):
    """The run artifacts cannot safely be closed with a verdict."""


@dataclass(frozen=True)
class _LoadedYaml:
    """One immutable-in-memory read used for both parsing and hashing."""

    path: Path
    payload: dict[str, Any]
    sha256: str


@dataclass(frozen=True)
class HumanRuling:
    """One reconciliatory or advisory human ruling tied to report evidence."""

    manifest: str
    check: str
    item: str
    verdict: str
    reason: str
    worksheet: str
    kind: str

    @property
    def target(self) -> tuple[str, str]:
        return (self.manifest, self.check)

    @property
    def identity(self) -> tuple[str, str, str]:
        return (*self.target, self.item)


@dataclass(frozen=True)
class HumanVerdicts:
    """The validated, versioned human artifact."""

    run: str
    judge: str
    completed_at: str
    rulings: tuple[HumanRuling, ...]
    path: Path
    sha256: str


@dataclass(frozen=True)
class FinalVerdict:
    """A generated verdict and the evidence used to make it."""

    passed: bool
    run_id: str
    report_hash: str
    human_hash: str
    integrity_problems: tuple[str, ...]
    failed_targets: tuple[tuple[str, str], ...]
    rulings: tuple[HumanRuling, ...]


def _load_yaml(path: Path, *, label: str) -> _LoadedYaml:
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise VerdictError(f"could not read {label} {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise VerdictError(f"{label} {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise VerdictError(f"{label} {path} must be a YAML mapping")
    return _LoadedYaml(path=path, payload=raw, sha256=hashlib.sha256(source).hexdigest())


def _nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerdictError(f"human verdicts {field} must be a non-empty string")
    return value.strip()


def _completed_at(value: Any) -> str:
    timestamp = _nonempty_string(value, field="completed_at")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerdictError(
            "human verdicts completed_at must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise VerdictError("human verdicts completed_at must be an actual UTC timestamp")
    return timestamp


def _parse_human_verdicts(source: _LoadedYaml, *, run_id: str) -> HumanVerdicts:
    """Load the human artifact and reject omissions before closing the folder.

    A row is either a check-level ``reconciliation`` or an item-level
    ``advisory`` ruling. Both name report evidence; only a reconciliation may
    overturn a failed applicable blocking check.
    """
    raw = source.payload
    version = raw.get("version")
    if type(version) is not int or version != HUMAN_VERDICTS_VERSION:
        raise VerdictError(
            f"human verdicts version must be {HUMAN_VERDICTS_VERSION!r}"
        )
    recorded_run = _nonempty_string(raw.get("run"), field="run")
    if recorded_run != run_id:
        raise VerdictError(
            f"human verdicts run {recorded_run!r} does not match folder {run_id!r}"
        )
    judge = _nonempty_string(raw.get("judge"), field="judge")
    completed_at = _completed_at(raw.get("completed_at"))
    worksheets = raw.get("worksheets")
    if not isinstance(worksheets, dict):
        raise VerdictError("human verdicts worksheets must be a mapping")
    actual_worksheets = set(worksheets)
    expected_worksheets = set(REQUIRED_WORKSHEETS)
    if actual_worksheets != expected_worksheets:
        missing = sorted(expected_worksheets - actual_worksheets)
        unknown = sorted(actual_worksheets - expected_worksheets)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise VerdictError("human verdicts worksheets are incomplete: " + "; ".join(details))

    rulings: list[HumanRuling] = []
    identities: set[tuple[str, str, str]] = set()
    for worksheet in REQUIRED_WORKSHEETS:
        rows = worksheets[worksheet]
        if not isinstance(rows, list):
            raise VerdictError(f"worksheet {worksheet!r} must be a list")
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise VerdictError(f"worksheet {worksheet!r} item {index} must be a mapping")
            manifest = _nonempty_string(row.get("manifest"), field="manifest")
            check = _nonempty_string(row.get("check"), field="check")
            item = _nonempty_string(row.get("item"), field="item")
            kind = row.get("kind")
            if kind not in {"reconciliation", "advisory"}:
                raise VerdictError(
                    f"worksheet {worksheet!r} item {index} kind must be "
                    "'reconciliation' or 'advisory'"
                )
            verdict = row.get("verdict")
            if verdict not in {"pass", "fail"}:
                raise VerdictError(
                    f"worksheet {worksheet!r} item {index} verdict must be 'pass' or 'fail'"
                )
            raw_reason = row.get("reason")
            if isinstance(raw_reason, str) and ("\r" in raw_reason or "\n" in raw_reason):
                raise VerdictError(
                    f"worksheet {worksheet!r} item {index} reason must be one line"
                )
            reason = _nonempty_string(raw_reason, field="reason")
            identity = (manifest, check, item)
            if identity in identities:
                raise VerdictError(
                    "human verdicts contain duplicate item ruling for "
                    f"manifest {manifest!r}, check {check!r}, item {item!r}"
                )
            identities.add(identity)
            rulings.append(
                HumanRuling(manifest, check, item, verdict, reason, worksheet, kind)
            )
    return HumanVerdicts(
        recorded_run,
        judge,
        completed_at,
        tuple(rulings),
        source.path,
        source.sha256,
    )


def load_human_verdicts(path: Path, *, run_id: str) -> HumanVerdicts:
    """Load a versioned human artifact for callers that do not need a report."""
    return _parse_human_verdicts(_load_yaml(path, label="human verdicts"), run_id=run_id)


def _report_facts(
    report: dict[str, Any], *, run_id: str
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...], frozenset[tuple[str, str]]]:
    """Return non-overridable integrity problems and failed blocking targets."""
    problems: list[str] = []
    failed: list[tuple[str, str]] = []
    targets: set[tuple[str, str]] = set()
    run = report.get("run")
    if not isinstance(run, dict) or run.get("id") != run_id:
        raise VerdictError("deterministic report run.id does not match the run folder")
    report_problems = report.get("problems")
    if not isinstance(report_problems, list) or not all(
        isinstance(problem, str) for problem in report_problems
    ):
        raise VerdictError("deterministic report problems must be a list of strings")
    if report_problems:
        problems.extend(f"run-level problem: {problem}" for problem in report_problems)
    reported_passed = report.get("passed")
    if not isinstance(reported_passed, bool):
        raise VerdictError("deterministic report passed must be a boolean")
    subjects = report.get("subjects")
    if not isinstance(subjects, list):
        raise VerdictError("deterministic report subjects must be a list")
    if not subjects:
        problems.append("the deterministic report contains zero subjects")
    seen_manifests: set[str] = set()
    for subject_index, subject in enumerate(subjects, start=1):
        if not isinstance(subject, dict):
            raise VerdictError(f"deterministic report subject {subject_index} must be a mapping")
        manifest = subject.get("manifest")
        if not isinstance(manifest, str) or not manifest:
            raise VerdictError(f"deterministic report subject {subject_index} has no manifest")
        if manifest in seen_manifests:
            problems.append(f"manifest {manifest!r} appears more than once")
        seen_manifests.add(manifest)
        checks = subject.get("checks")
        if not isinstance(checks, list):
            raise VerdictError(f"manifest {manifest!r} checks must be a list")
        by_name: dict[str, dict[str, Any]] = {}
        for check_index, check in enumerate(checks, start=1):
            if not isinstance(check, dict):
                raise VerdictError(
                    f"manifest {manifest!r} check {check_index} must be a mapping"
                )
            name = check.get("check")
            if not isinstance(name, str) or not name:
                raise VerdictError(f"manifest {manifest!r} has a check without a name")
            if name in by_name:
                problems.append(f"manifest {manifest!r} records check {name!r} more than once")
                continue
            if not all(isinstance(check.get(field), bool) for field in ("passed", "blocking", "applicable")):
                raise VerdictError(
                    f"manifest {manifest!r}, check {name!r} must carry boolean "
                    "passed, blocking, and applicable fields"
                )
            by_name[name] = check
            targets.add((manifest, name))
            if check["blocking"] and not check["applicable"]:
                problems.append(
                    f"manifest {manifest!r}, blocking check {name!r} is inapplicable"
                )
            elif check["blocking"] and not check["passed"]:
                failed.append((manifest, name))
        missing = sorted(REQUIRED_CHECKS - set(by_name))
        if missing:
            problems.append(
                f"manifest {manifest!r} is missing required checks: {', '.join(missing)}"
            )
    recomputed_passed = not problems and not failed
    if reported_passed != recomputed_passed:
        problems.append(
            "deterministic report passed does not agree with its recorded "
            "subjects, checks, and run-level problems"
        )
    return tuple(problems), tuple(failed), frozenset(targets)


def evaluate_final_verdict(run_folder: Path) -> FinalVerdict:
    """Evaluate immutable report + human evidence without writing a file."""
    folder = Path(run_folder)
    run_id = folder.name
    report_path = folder / REPORT_NAME
    human_path = folder / HUMAN_VERDICTS_NAME
    report_source = _load_yaml(report_path, label="deterministic report")
    integrity_problems, failed_targets, report_targets = _report_facts(
        report_source.payload, run_id=run_id
    )
    human = _parse_human_verdicts(
        _load_yaml(human_path, label="human verdicts"), run_id=run_id
    )
    failed_set = set(failed_targets)
    ruling_targets = {ruling.target for ruling in human.rulings}
    invalid_targets = ruling_targets - report_targets
    if invalid_targets:
        rendered = ", ".join(
            f"({manifest!r}, {check!r})" for manifest, check in sorted(invalid_targets)
        )
        raise VerdictError(
            "human rulings must target an actual deterministic report check: " + rendered
        )
    reconciliations = tuple(
        ruling for ruling in human.rulings if ruling.kind == "reconciliation"
    )
    reconciliation_targets = {ruling.target for ruling in reconciliations}
    invalid_reconciliations = reconciliation_targets - failed_set
    if invalid_reconciliations:
        rendered = ", ".join(
            f"({manifest!r}, {check!r})"
            for manifest, check in sorted(invalid_reconciliations)
        )
        raise VerdictError(
            "human reconciliations may target only failed applicable blocking results: "
            + rendered
        )
    if len(reconciliations) != len(reconciliation_targets):
        raise VerdictError(
            "human verdicts contain duplicate reconciliation for a failed blocking result"
        )
    missing = failed_set - reconciliation_targets
    if missing:
        rendered = ", ".join(
            f"({manifest!r}, {check!r})" for manifest, check in sorted(missing)
        )
        raise VerdictError("human verdicts do not reconcile failed blocking results: " + rendered)
    passed = (
        not integrity_problems
        and all(ruling.verdict == "pass" for ruling in human.rulings)
        and reconciliation_targets == failed_set
    )
    return FinalVerdict(
        passed=passed,
        run_id=run_id,
        report_hash=report_source.sha256,
        human_hash=human.sha256,
        integrity_problems=integrity_problems,
        failed_targets=failed_targets,
        rulings=human.rulings,
    )


def _render(verdict: FinalVerdict) -> str:
    state = "PASS" if verdict.passed else "FAIL"
    lines = [
        f"# Final verdict: {state}",
        "",
        f"- **Run:** {verdict.run_id}",
        "- **Evaluator:** evals.harness.verdict",
        f"- **Deterministic report SHA-256:** `{verdict.report_hash}`",
        f"- **Human verdicts SHA-256:** `{verdict.human_hash}`",
        "",
        "## Deterministic evidence",
        "",
        "- `deterministic-report.yaml` is unchanged; its `passed` field remains the deterministic result.",
    ]
    if verdict.integrity_problems:
        lines.extend(["", "## Non-overridable report-integrity problems", ""])
        lines.extend(f"- {problem}" for problem in verdict.integrity_problems)
    if verdict.rulings:
        lines.extend(["", "## Human rulings", ""])
        for ruling in verdict.rulings:
            lines.append(
                f"- **{ruling.kind.title()}** — `{ruling.manifest}` / "
                f"`{ruling.check}` / `{ruling.item}`: **{ruling.verdict.upper()}** "
                f"— {ruling.reason} (worksheet: `{ruling.worksheet}`)"
            )
    else:
        lines.extend(["", "## Human rulings", "", "- No human ruling was required."])
    return "\n".join(lines) + "\n"


def finalize(run_folder: Path) -> FinalVerdict:
    """Write the generated final verdict once, or refuse a closed run folder."""
    folder = Path(run_folder)
    verdict_path = folder / VERDICT_NAME
    if verdict_path.exists():
        raise VerdictError(
            f"{verdict_path} already exists: final verdicts are immutable; start a new run"
        )
    verdict = evaluate_final_verdict(folder)
    rendered = _render(verdict)
    temporary_path = verdict_path.with_name(
        f".{VERDICT_NAME}.{uuid4().hex}.tmp"
    )
    temporary_created = False
    try:
        descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        temporary_created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(rendered)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_path, verdict_path)
        except FileExistsError as exc:
            raise VerdictError(
                f"{verdict_path} already exists: final verdicts are immutable; start a new run"
            ) from exc
    except FileExistsError as exc:
        raise VerdictError(
            f"could not create temporary final verdict {temporary_path}: {exc}"
        ) from exc
    except OSError as exc:
        raise VerdictError(f"could not publish final verdict {verdict_path}: {exc}") from exc
    finally:
        if temporary_created:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an immutable eval final verdict")
    parser.add_argument("run_folder", type=Path, help="evals/runs/<run-id> folder")
    args = parser.parse_args(argv)
    try:
        verdict = finalize(args.run_folder)
    except VerdictError as exc:
        parser.error(str(exc))
    print(f"{args.run_folder / VERDICT_NAME}: {'PASS' if verdict.passed else 'FAIL'}")
    return 0 if verdict.passed else 1


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())
