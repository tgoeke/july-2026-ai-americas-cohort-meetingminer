"""The eval-run plugin: options, subject selection, and the run folder.

Sits at ``evals/`` rather than in ``evals/checks/`` so its options are
registered for either suite, and creates *nothing* unless a test asks for it.
That is what keeps ``evals/tests/`` store-free and folder-free: session
fixtures are built on first request, so ``make evals-test`` — which requests
none of them — opens no connection, makes no HTTP call, and leaves
``evals/runs/`` untouched.

Two things happen here that a plain fixture could not do:

* **Subjects are selected at collection time** (:func:`pytest_generate_tests`),
  because the check tests are parametrized one-per-eval-subject. Selection is
  cached, so the one ``GET /meetings`` call happens once per session.
* **The zero-subject test runs first** (:func:`pytest_collection_modifyitems`).
  An empty parametrization produces skipped tests, which is precisely the
  silent zero the eval design forbids; ordering the existence test ahead of
  the checks means a run with nothing to measure fails on *that*, by name,
  rather than on four checks that quietly had no work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from evals.harness.checks import Capture
from evals.harness.corpus import Corpus, CorpusQueryError
from evals.harness.groundtruth import GroundTruthError, load_all
from evals.harness.run import Run, default_run_id, fetch_effective_bindings
from evals.harness.subjects import (
    CorpusReadError,
    Selection,
    Subject,
    fetch_meetings,
    select_subjects,
)

#: Where the harness reads the corpus from. The api runs as a host process on
#: this address (infra/Makefile API_HOST/API_PORT); an eval run against another
#: machine passes `--api-base-url`.
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"

#: The module whose tests must be collected first, whatever the file order.
SUBJECTS_EXIST_MODULE = "test_subjects_exist"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("evals", "MeetingMiner eval harness")
    group.addoption(
        "--run-id",
        default=None,
        help=(
            "Folder name under evals/runs/ for this run. Defaults to"
            " <date>-<label> (eval-design §4). A run gets its own folder:"
            " an existing one is refused, never reused."
        ),
    )
    group.addoption(
        "--run-label",
        default=None,
        help="Short label for the run, used in the default run id and recorded in the report.",
    )
    group.addoption(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help=f"Base url of the running api (default {DEFAULT_API_BASE_URL}).",
    )


@dataclass(frozen=True)
class EvalSubjects:
    """What a run may measure, and everything it may not — never a bare list.

    ``problems`` carries the manifests that could not be placed *and* the
    ones this module refuses to measure. A run that dropped either silently
    would report perfect recall over whatever happened to be ingested.
    """

    subjects: tuple[Subject, ...]
    problems: tuple[str, ...]
    selection: Selection | None


def _ambiguity_problem(manifest_id: str, rows: list[Subject]) -> str:
    where = ", ".join(
        f"job {subject.job_id} (meeting {subject.meeting_id}, status {subject.status})"
        for subject in rows
    )
    return (
        f"manifest {manifest_id!r} matches {len(rows)} ingested scripted"
        f" meetings — {where}. A re-ingest leaves the earlier job's row behind,"
        " and the run cannot tell which one the ground truth describes, so it"
        " measures neither. Remove the stale ingestion and rerun."
    )


def _split(selection: Selection) -> EvalSubjects:
    """Subjects a run may measure, with ambiguous manifests moved to problems."""
    by_manifest: dict[str, list[Subject]] = {}
    for subject in selection.subjects:
        by_manifest.setdefault(subject.manifest.id, []).append(subject)
    subjects = tuple(rows[0] for rows in by_manifest.values() if len(rows) == 1)
    problems = list(selection.problems())
    problems += [
        _ambiguity_problem(manifest_id, rows)
        for manifest_id, rows in sorted(by_manifest.items())
        if len(rows) > 1
    ]
    return EvalSubjects(
        subjects=subjects, problems=tuple(problems), selection=selection
    )


_CACHE: dict[str, EvalSubjects] = {}


def eval_subjects(config: pytest.Config) -> EvalSubjects:
    """Select this session's eval subjects, once.

    Every way the selection can fail — unreadable ground truth, an api that is
    not answering — becomes a *problem* rather than an exception, so the
    failure is reported by the ordered-first existence test (and lands in the
    run's report) instead of aborting collection with a traceback.
    """
    base_url = config.getoption("--api-base-url")
    cached = _CACHE.get(base_url)
    if cached is not None:
        return cached

    try:
        manifests = load_all()
    except GroundTruthError as exc:
        result = EvalSubjects(subjects=(), problems=(str(exc),), selection=None)
        _CACHE[base_url] = result
        return result

    try:
        rows = fetch_meetings(base_url)
    except CorpusReadError as exc:
        result = EvalSubjects(subjects=(), problems=(str(exc),), selection=None)
        _CACHE[base_url] = result
        return result

    result = _split(select_subjects(rows, manifests))
    _CACHE[base_url] = result
    return result


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize the check tests one-per-eval-subject.

    Only fires for a test that asks for ``subject``; nothing in
    ``evals/tests/`` does, so the store-free suite never triggers selection.
    """
    if "subject" not in metafunc.fixturenames:
        return
    selected = eval_subjects(metafunc.config)
    metafunc.parametrize(
        "subject",
        selected.subjects,
        ids=[subject.manifest.id for subject in selected.subjects],
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Run the zero-subject test before any check test."""
    items.sort(key=lambda item: 0 if SUBJECTS_EXIST_MODULE in item.nodeid else 1)


@pytest.fixture(scope="session")
def app_config() -> Any:
    """The resolved ``config.yaml`` + ``.env``, via the one allowed server import.

    ``meetingminer.config`` is the single named allowance in the AD-16 import
    guard: it parses two files and mutates nothing. The import is inside the
    fixture rather than at module scope so the store-free suite — which never
    requests this fixture — does not even import the server package, and so a
    new required key in ``.env`` cannot break ``make evals-test``.
    """
    from meetingminer.config import load_config

    return load_config()


@pytest.fixture(scope="session")
def run(request: pytest.FixtureRequest, app_config: Any) -> Any:
    """The run folder, created on first request and reported on at the end.

    The report is written in teardown whether the run passed or failed: the
    report *is* the record of a failure, and triage classifies from it
    (runbook step 2).
    """
    label = request.config.getoption("--run-label")
    run_id = request.config.getoption("--run-id") or default_run_id(label)
    api_base_url = request.config.getoption("--api-base-url")
    created = Run.create(
        run_id,
        config=app_config,
        label=label,
        api_base_url=api_base_url,
        # Story 8.2: which binding each role will actually be served by, read
        # from the running api rather than re-derived here (AD-16 keeps this
        # harness a client). Recorded beside the file's own values, so a run
        # whose selection differs from `config.yaml` is still reproducible.
        effective_bindings=fetch_effective_bindings(api_base_url),
    )
    yield created
    created.write_report()


@pytest.fixture(scope="session")
def corpus(app_config: Any) -> Any:
    """The read-only Postgres session (AD-16), closed at the end of the run."""
    reader = Corpus.from_config(app_config)
    yield reader
    reader.close()


@pytest.fixture(scope="session")
def subjects(pytestconfig: pytest.Config) -> EvalSubjects:
    """This session's eval subjects and every problem selecting them found."""
    return eval_subjects(pytestconfig)


@dataclass(frozen=True)
class Evidence:
    """One subject's captures, or the named reason there are none to measure."""

    captures: tuple[Capture, ...]
    media_duration_ms: int | None
    has_recording: bool
    problem: str | None = None

    @property
    def measurable(self) -> bool:
        return self.problem is None


@pytest.fixture(scope="session")
def evidence_for(corpus: Corpus) -> Callable[[Subject], Evidence]:
    """Read one subject's captures once, however many checks ask for them."""
    cache: dict[str, Evidence] = {}

    def read(subject: Subject) -> Evidence:
        if subject.meeting_id is None:
            return Evidence(
                captures=(),
                media_duration_ms=None,
                has_recording=False,
                problem=(
                    f"manifest {subject.manifest.id!r} matches job"
                    f" {subject.job_id} (status {subject.status}), which has no"
                    " meeting row yet — the worker has not claimed it, so there"
                    " is nothing captured to measure"
                ),
            )
        cached = cache.get(subject.meeting_id)
        if cached is not None:
            return cached
        evidence = read_evidence(corpus, subject)
        cache[subject.meeting_id] = evidence
        return evidence

    return read


def read_evidence(corpus: Corpus, subject: Subject) -> Evidence:
    """Read a subject's corpus evidence, preserving database failures in-band.

    This function deliberately returns an unmeasurable :class:`Evidence` when
    the read-only corpus connection fails. The check layer can then record each
    check as not applicable and write the database diagnostic into the run
    artifact, instead of fixture setup aborting before any report line exists.
    """
    if subject.meeting_id is None:
        return Evidence(
            captures=(),
            media_duration_ms=None,
            has_recording=False,
            problem=(
                f"manifest {subject.manifest.id!r} matches job"
                f" {subject.job_id} (status {subject.status}), which has no"
                " meeting row yet — the worker has not claimed it, so there"
                " is nothing captured to measure"
            ),
        )
    try:
        has_recording = corpus.has_recording(subject.meeting_id)
        return Evidence(
            # Read even when there is no recording: a transcript-only meeting
            # with screenshot rows is itself worth seeing in the report.
            captures=corpus.captures_for(subject.meeting_id),
            media_duration_ms=corpus.media_duration_ms(subject.meeting_id),
            has_recording=has_recording,
            problem=(
                None
                if has_recording
                else (
                    f"meeting {subject.meeting_id} was ingested with"
                    " has_recording = false, so the capture checks are not"
                    " applicable — a scripted eval subject with no recording"
                    " cannot measure capture"
                )
            ),
        )
    except CorpusQueryError as exc:
        return Evidence(
            captures=(),
            media_duration_ms=None,
            has_recording=False,
            problem=(
                f"could not read corpus evidence for meeting {subject.meeting_id}:"
                f" {exc}"
            ),
        )


@pytest.fixture()
def evidence(subject: Subject, evidence_for: Callable[[Subject], Evidence]) -> Evidence:
    return evidence_for(subject)
