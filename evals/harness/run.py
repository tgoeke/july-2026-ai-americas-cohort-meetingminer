"""The run folder: created once, written once, never edited.

A verdict that cannot be reproduced or invalidated is not evidence, so every
run gets ``evals/runs/<run-id>/`` holding what was measured and the resolved
configuration it was measured against (eval-design §4). The immutability rule
is §4.6-4.7: nothing is edited after a verdict, and any pipeline or judge
change invalidates the verdict and demands a fresh folder.

Two rules follow from that, and both are enforced here rather than trusted:

* **A run gets its own folder.** ``Run.create`` refuses an existing folder —
  emphatically so when it already holds a ``verdict.md``, because that folder
  is a closed audit record. Reusing one would silently rewrite the evidence
  behind a verdict somebody already recorded.
* **The configuration snapshot is secret-free.** Run folders are committed as
  the audit record, so a snapshot carrying ``.env`` values would commit them.
  Only the resolved ``config.yaml`` is written — ``AppConfig.secrets`` is
  never read — and the dump is walked once more for anything secret-shaped, so
  a future key added to ``config.yaml`` cannot leak by being new.

The snapshot matters as much as the numbers: a recall figure is only
interpretable beside the OCR engine that produced the text it scored.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from evals.harness.checks import (
    CAPTURE_RECALL,
    DEDUP_QUALITY,
    DOC_INDEX_SEARCH_RECALL,
    DURATION_AGREEMENT,
    OVER_CAPTURE,
    PUBLISH_GATE_PROJECTION,
    VIEW_CLASSIFICATION,
    CheckResult,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from evals.harness.subjects import Subject

EVALS_ROOT = Path(__file__).resolve().parents[1]
#: Run folders live in the repository and are committed: they are the audit
#: record, not scratch output.
RUNS_ROOT = EVALS_ROOT / "runs"

REPORT_NAME = "deterministic-report.yaml"
CONFIG_SNAPSHOT_NAME = "config-snapshot.yaml"
HUMAN_VERDICTS_NAME = "human-verdicts.yaml"
#: Story 5.5 writes this; its presence is what marks a folder closed.
VERDICT_NAME = "verdict.md"

#: Substrings that make a configuration key secret-shaped — the whole value
#: goes. Defensive: nothing in today's `config.yaml` matches, and that is the
#: point, because the snapshot must stay secret-free when somebody adds a key
#: to it without reading this file.
#:
#: Deliberately not a bare "key": `identity_key` and `api_key` are different
#: kinds of thing, and redacting the first would hide real configuration.
#: `dsn` and `conninfo` are here because neither ever holds anything but a
#: credential-carrying string.
SECRET_KEY_HINTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "master_key",
    "private_key",
    "privatekey",
    "authorization",
    "credential",
    "dsn",
    "conninfo",
)

#: `url`/`uri` are deliberately NOT in the list above. The endpoint a run was
#: configured against is exactly what makes the snapshot interpretable — a
#: judge score is only readable beside the provider it was produced by — so
#: blanking `providers.anthropic.base_url` would destroy audit value to defend
#: against a credential that may not be there. The credential *inside* such a
#: value is removed instead, by the scrubbers below, which apply to every
#: string in the dump and so also catch a credential URL parked under a key
#: nobody thought to list.
#:
#: Three shapes, because a credential reaches a config file three ways:
#: `scheme://user:pw@host` (the URL form), `?apiKey=...` (the query-string
#: form), and libpq's `host=... password=...` keyword form.
_URL_CREDENTIALS = re.compile(r"(?i)(?<=://)[^/\s@]+(?=@)")
_QUERY_CREDENTIALS = re.compile(
    r"(?i)([?&](?:api[-_]?key|access[-_]?token|token|key|password|secret|auth(?:orization)?)=)[^&\s]+"
)
# `[^\s&]+`, not `\S+`: a keyword credential ends at whitespace, and one that
# came from a query string ends at the next `&` — without that bound, scrubbing
# `?apiKey=x&limit=5` would swallow `&limit=5` along with the key.
_KEYWORD_CREDENTIALS = re.compile(
    r"(?i)\b((?:password|passwd|pgpassword|secret|api[-_]?key|token|private[-_]?key|authorization|auth)\s*=\s*)[^\s&]+"
)

REDACTED = "[redacted]"

#: What a run id (and the label that can become one) may contain. A run id is
#: joined onto `evals/runs/`, so anything that could climb out of that folder —
#: a separator, a `..`, a leading dot — has to be refused rather than
#: sanitized: silently rewriting an operator's `--run-id` would file the audit
#: record somewhere they did not ask for and will not look.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_NAME_LENGTH = 96

# A report is a completed tier-1 run only after every check has contributed a
# result for every selected subject. Checks 2.3 and 2.4 are not verdict gates,
# but omitting them still makes an artifact incomplete rather than successful.
REQUIRED_CHECKS = frozenset(
    {
        DURATION_AGREEMENT,
        CAPTURE_RECALL,
        OVER_CAPTURE,
        VIEW_CLASSIFICATION,
        DEDUP_QUALITY,
        DOC_INDEX_SEARCH_RECALL,
        PUBLISH_GATE_PROJECTION,
    }
)


class RunError(Exception):
    """The run folder could not be created, or would have been written twice."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(value: str, *, field: str) -> str:
    """A run id or label, or a named error. Never a sanitized substitute.

    ``Run.create`` joins the run id onto :data:`RUNS_ROOT`, so ``../..`` or an
    absolute-looking value would write the audit record outside `evals/runs/`
    — or over something else entirely.
    """
    if not isinstance(value, str) or not _SAFE_NAME.match(value):
        raise RunError(
            f"{field} {value!r} is not usable as a folder name: it must start"
            " with a letter or digit and contain only letters, digits, '.',"
            " '-' and '_'. A run id names a folder under evals/runs/, so a"
            " path separator or a '..' in it would write the audit record"
            " somewhere else."
        )
    if len(value) > MAX_NAME_LENGTH:
        raise RunError(
            f"{field} is {len(value)} characters, past the {MAX_NAME_LENGTH}"
            " allowed for a folder name"
        )
    return value


def scrub(value: str) -> str:
    """Remove a credential embedded in an otherwise-informative string.

    Applied to every string in the dump, not only to values under a listed
    key: the risk this closes is a credential parked somewhere nobody thought
    to list, and a key-name rule by definition cannot see those.
    """
    scrubbed = _URL_CREDENTIALS.sub(REDACTED, value)
    scrubbed = _QUERY_CREDENTIALS.sub(rf"\1{REDACTED}", scrubbed)
    return _KEYWORD_CREDENTIALS.sub(rf"\1{REDACTED}", scrubbed)


def redact(value: Any) -> Any:
    """Copy a resolved-config dump with every secret removed.

    Two rules, because a secret arrives two ways. A secret-shaped *key* loses
    its whole value; every *string* is scrubbed for a credential embedded in
    it, whatever key it sits under.
    """
    if isinstance(value, Mapping):
        return {
            key: REDACTED
            if any(hint in str(key).lower() for hint in SECRET_KEY_HINTS)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return scrub(value)
    return value


def resolved_settings(config: Any) -> dict[str, Any]:
    """The resolved ``config.yaml``, redacted. ``config.secrets`` is not read.

    ``config`` is duck-typed on purpose: a pydantic ``Settings`` is dumped via
    ``model_dump``, and a plain mapping is taken as-is, so the snapshot is
    testable without ``load_config`` (which the store-free suite must not
    call).
    """
    settings = config.settings
    dump = getattr(settings, "model_dump", None)
    data = dump(mode="json") if callable(dump) else dict(settings)
    return redact(data)


class Run:
    """One eval run's folder and the results recorded into it."""

    def __init__(self, run_id: str, folder: Path, label: str | None = None) -> None:
        self.run_id = run_id
        self.folder = folder
        self.label = label
        self.started_at = _now()
        self._subjects: dict[str, dict[str, Any]] = {}
        self._problems: list[str] = []
        self._report_path: Path | None = None

    @classmethod
    def create(
        cls,
        run_id: str,
        *,
        config: Any,
        root: Path | None = None,
        label: str | None = None,
        api_base_url: str | None = None,
    ) -> Run:
        """Make the folder and write the configuration snapshot into it.

        Refuses an existing folder either way, with different wording for the
        two cases: a folder holding a verdict is a closed record, while one
        without is an interrupted run whose partial evidence must not be mixed
        with a fresh attempt's.
        """
        safe_name(run_id, field="--run-id")
        if label is not None:
            safe_name(label, field="--run-label")
        folder = (Path(root) if root is not None else RUNS_ROOT) / run_id
        if folder.exists():
            if (folder / VERDICT_NAME).exists():
                raise RunError(
                    f"{folder} already holds {VERDICT_NAME}: a run folder is"
                    " immutable once a verdict is recorded (eval-design §4.6)."
                    " Start a new run with a different --run-id."
                )
            raise RunError(
                f"{folder} already exists: a run gets its own folder, so an"
                " interrupted run is rerun under a new --run-id rather than"
                " written over."
            )
        try:
            folder.mkdir(parents=True)
        except OSError as exc:
            raise RunError(f"could not create the run folder {folder}: {exc}") from exc

        run = cls(run_id=run_id, folder=folder, label=label)
        run._write_yaml(
            CONFIG_SNAPSHOT_NAME,
            {
                "run": run._identity(),
                "config_path": str(getattr(config, "config_path", "")),
                "settings": resolved_settings(config),
                "api_base_url": redact(api_base_url) if api_base_url else None,
            },
        )
        return run

    def _identity(self) -> dict[str, Any]:
        return {"id": self.run_id, "label": self.label, "started_at": self.started_at}

    def _write_yaml(self, name: str, payload: Mapping[str, Any]) -> Path:
        path = self.folder / name
        path.write_text(
            yaml.safe_dump(dict(payload), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    def note(self, problem: str) -> None:
        """Record a run-level problem — an unmatched manifest, a corpus mismatch.

        Kept beside the checks rather than only in pytest output: the report is
        the artifact triage reads, and a run that measured nothing has to say
        why in the file, not only on a terminal that has scrolled away.
        """
        if problem not in self._problems:
            self._problems.append(problem)

    def describe_subject(self, subject: Subject) -> dict[str, Any]:
        """Register a subject in the report, returning its record."""
        key = subject.manifest.id
        record = self._subjects.get(key)
        if record is None:
            record = {
                "manifest": key,
                "source_id": subject.source_id,
                "meeting_id": subject.meeting_id,
                "job_id": subject.job_id,
                "title": subject.title,
                "status": subject.status,
                "checks": [],
            }
            self._subjects[key] = record
        return record

    def record(self, subject: Subject, result: CheckResult) -> CheckResult:
        """Attach one check's result to its subject. Returned for chaining."""
        self.describe_subject(subject)["checks"].append(result.to_dict())
        return result

    def _completeness_problems(self) -> tuple[str, ...]:
        """Name every subject whose report is missing a required check.

        Pytest selection flags and interruptions may deliberately produce a
        partial artifact, but that artifact must never look like a completed
        passing run. Keep the reason in the report instead of relying on an
        operator to reconstruct it from a terminal command.
        """
        problems: list[str] = []
        for manifest, record in self._subjects.items():
            recorded = {check["check"] for check in record["checks"]}
            missing = sorted(REQUIRED_CHECKS - recorded)
            if missing:
                problems.append(
                    f"manifest {manifest!r} is missing required checks:"
                    f" {', '.join(missing)}"
                )
        return tuple(problems)

    @property
    def passed(self) -> bool:
        """The run's verdict: no run-level problem, every blocking check passed."""
        if self._problems or self._completeness_problems():
            return False
        return all(
            check["passed"]
            for record in self._subjects.values()
            for check in record["checks"]
            if check["blocking"]
        ) and bool(self._subjects)

    def write_report(self) -> Path:
        """Write ``deterministic-report.yaml`` — once, or raise.

        Written even when the run failed: the report *is* the record of the
        failure, and triage (runbook step 2) classifies from it.
        """
        if self._report_path is not None:
            raise RunError(
                f"{self._report_path} has already been written: a run folder is"
                " written once and never edited (eval-design §4.6)."
            )
        completeness_problems = self._completeness_problems()
        payload = {
            "run": {**self._identity(), "finished_at": _now()},
            "story": (
                "5.2 + 5.3 — deterministic capture, retrieval and publish-gate"
                " checks (eval-design §2.1-2.4, §2.10-2.11)"
            ),
            "config_snapshot": CONFIG_SNAPSHOT_NAME,
            "passed": self.passed,
            "problems": [*self._problems, *completeness_problems],
            "subjects": [self._subjects[key] for key in sorted(self._subjects)],
        }
        self._report_path = self._write_yaml(REPORT_NAME, payload)
        return self._report_path


def default_run_id(label: str | None = None, *, now: datetime | None = None) -> str:
    """``<date>-<label>`` per eval-design §4: a run-id is a date plus a label.

    Without a label the time of day stands in, so two runs on one day cannot
    collide onto a folder ``Run.create`` would then refuse.

    UTC, like every timestamp in the report: a folder name that disagreed with
    the ``started_at`` inside it would make two runs orderable two ways.
    """
    moment = now or datetime.now(timezone.utc)
    if label is not None:
        safe_name(label, field="--run-label")
    return f"{moment:%Y-%m-%d}-{label or format(moment, '%H%M%S')}"
