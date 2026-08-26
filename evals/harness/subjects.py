"""Which ingested meetings an eval run is allowed to measure.

Eval subjects are meetings tagged ``corpus: scripted``, matched to their
manifest by ``sourceId``. Real pulled meetings are demo corpus: they have no
ground truth, so measuring them would be measuring nothing (scope.md §Corpus).

A manifest whose ``source_id`` matches a ``corpus: real`` row is *not* quietly
skipped. That pairing means someone wrote a ground-truth manifest against a
meeting that was never scripted, or the drop was tagged wrong — an authoring
error either way, and it is reported as one.

AD-16: the corpus is read through the public API. :func:`fetch_meetings` is
the only network call in the harness and the only impure function in this
module; selection is a pure function over rows so the matrix is unit-testable
with no api, no store and no ingestion.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from evals.harness.groundtruth import Manifest

#: The only corpus tag an eval run may measure.
EVAL_CORPUS = "scripted"


class CorpusReadError(Exception):
    """The ingestion list could not be read, or did not answer in the shape promised.

    One error type for every way the read can fail, so a caller does not need
    to know whether the api was down, answered with an error status, returned
    something that was not JSON, or returned JSON without the documented
    envelope. A run that cannot read the corpus has no subjects, and that is a
    named failure rather than an empty list.
    """


@dataclass(frozen=True)
class Subject:
    """One scripted meeting paired with the manifest that describes it."""

    manifest: Manifest
    source_id: str
    job_id: str | None
    meeting_id: str | None
    title: str | None
    #: The job's lifecycle status. Carried because it is the only field that
    #: distinguishes a leftover failed job from the re-ingest that replaced it
    #: when one `sourceId` yields several rows — the decision this module
    #: deliberately leaves to story 5.2.
    status: str | None
    #: The api's own "safe to open" verdict (`evidence_complete`). Carried
    #: rather than re-derived: one definition of viewable, server-side.
    viewable: bool


@dataclass(frozen=True)
class CorpusMismatch:
    """A manifest naming a meeting that is not tagged ``scripted``."""

    manifest: Manifest
    source_id: str
    #: The row's corpus tag, or ``None`` when the row carried none at all.
    #: The two are different failures — a mis-tagged drop versus a row that
    #: predates the tag or came from something that is not a drop — and a
    #: report that renders the second as the string "None" sends triage after
    #: a corpus value nobody ever wrote.
    corpus: str | None
    job_id: str | None
    meeting_id: str | None

    def describe(self) -> str:
        tagged = (
            f"which is ingested as corpus {self.corpus!r}"
            if self.corpus
            else "which is ingested with no corpus tag at all"
        )
        return (
            f"manifest {self.manifest.id!r} names source_id {self.source_id!r},"
            f" {tagged} — only {EVAL_CORPUS!r} meetings are eval subjects, so"
            " either the manifest names the wrong meeting or the drop was"
            " tagged wrong"
        )


@dataclass(frozen=True)
class UnmatchedManifest:
    """Ground truth with no ingested meeting answering to its ``source_id``."""

    manifest: Manifest
    source_id: str

    def describe(self) -> str:
        return (
            f"manifest {self.manifest.id!r} names source_id {self.source_id!r},"
            " which nothing ingested answers to — either the scripted meeting"
            " has not been ingested yet, or the manifest still carries the"
            " placeholder id it shipped with"
        )


@dataclass(frozen=True)
class Selection:
    """The outcome of matching manifests against the ingested corpus.

    Three buckets rather than a filtered list: a run that silently dropped the
    manifests it could not place would report perfect recall over whatever
    happened to be ingested. What could not be placed is part of the result,
    and both non-subject buckets can describe themselves so 5.2 does not have
    to invent phrasing for half the outcome.
    """

    subjects: tuple[Subject, ...]
    unmatched: tuple[UnmatchedManifest, ...]
    corpus_mismatches: tuple[CorpusMismatch, ...]

    def problems(self) -> tuple[str, ...]:
        """Every non-subject outcome, rendered for a report."""
        return tuple(
            item.describe() for item in (*self.corpus_mismatches, *self.unmatched)
        )


def _rows_by_source_id(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    index: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        source_id = row.get("sourceId")
        if isinstance(source_id, str) and source_id:
            index.setdefault(source_id, []).append(row)
    return index


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def select_subjects(
    meeting_rows: Sequence[Mapping[str, Any]], manifests: Sequence[Manifest]
) -> Selection:
    """Pair manifests with ``GET /meetings`` rows.

    Rows are the camelCased items of the ``meetings`` array exactly as the api
    returns them. A manifest may legitimately match more than one row — a
    failed job leaves its row behind and a re-ingest adds another — so every
    matching scripted row becomes a subject, carrying its ``status``, and
    story 5.2 decides what a duplicate means for a run.
    """
    index = _rows_by_source_id(meeting_rows)
    subjects: list[Subject] = []
    unmatched: list[UnmatchedManifest] = []
    mismatches: list[CorpusMismatch] = []

    for manifest in manifests:
        matches = index.get(manifest.source_id, [])
        if not matches:
            unmatched.append(
                UnmatchedManifest(manifest=manifest, source_id=manifest.source_id)
            )
            continue
        for row in matches:
            if row.get("corpus") == EVAL_CORPUS:
                subjects.append(
                    Subject(
                        manifest=manifest,
                        source_id=manifest.source_id,
                        job_id=_text(row.get("jobId")),
                        meeting_id=_text(row.get("meetingId")),
                        title=_text(row.get("title")),
                        status=_text(row.get("status")),
                        viewable=bool(row.get("viewable")),
                    )
                )
            else:
                mismatches.append(
                    CorpusMismatch(
                        manifest=manifest,
                        source_id=manifest.source_id,
                        corpus=_text(row.get("corpus")),
                        job_id=_text(row.get("jobId")),
                        meeting_id=_text(row.get("meetingId")),
                    )
                )

    return Selection(
        subjects=tuple(subjects),
        unmatched=tuple(unmatched),
        corpus_mismatches=tuple(mismatches),
    )


def fetch_meetings(
    base_url: str,
    *,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Read the ingestion list through the public api (AD-16).

    A plain ``GET /meetings``: the harness reads the corpus the same way the
    browser does, and imports no server module to do it. The response envelope
    is unwrapped here so every caller works on the row list ``select_subjects``
    expects.

    ``transport`` is an injection seam, not a feature. It is the only reason
    the one network call in the harness can be exercised offline, which is what
    keeps the whole eval suite store-free and api-free.
    """
    url = f"{base_url.rstrip('/')}/meetings"
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise CorpusReadError(f"could not read the corpus from {url}: {exc}") from exc
    except ValueError as exc:
        raise CorpusReadError(f"{url} did not answer with JSON: {exc}") from exc

    if not isinstance(payload, Mapping) or not isinstance(payload.get("meetings"), list):
        shape = (
            f"an object with keys {sorted(payload)}"
            if isinstance(payload, Mapping)
            else type(payload).__name__
        )
        raise CorpusReadError(
            f"{url} did not answer with a `meetings` array — got {shape}."
            " Either the api is not MeetingMiner, or GET /meetings changed shape"
            " and the harness has to change with it"
        )
    if not all(isinstance(row, Mapping) for row in payload["meetings"]):
        raise CorpusReadError(
            f"{url} returned a `meetings` entry that is not an object."
            " GET /meetings changed shape and the harness has to change with it"
        )
    return list(payload["meetings"])
