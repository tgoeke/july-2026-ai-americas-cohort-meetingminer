"""The tier-1 check algorithms: pure functions over rows (eval-design §2.1-2.4).

Nothing here opens a connection or speaks HTTP. A check takes a
:class:`~evals.harness.groundtruth.Manifest` and a tuple of :class:`Capture`
records and returns a :class:`CheckResult`, so every algorithm is exercisable
with synthetic captures and no Docker store. ``corpus.py`` is the only module
that turns database rows into :class:`Capture` records, which is what keeps
that property true rather than merely intended.

Two numbers eval-design leaves open are pinned here, and both are written into
every run's report beside the result they produced (§6: thresholds are
provisional, and changing one invalidates prior verdicts):

* **The fuzzy comparison behind "token-set match >= 0.8".** §2.1 names no
  implementation and rapidfuzz is not a dependency, so it is defined as:
  fold both sides with ``normalize_anchor``; an anchor token is *present* when
  some OCR token scores at least :data:`TOKEN_SIMILARITY_THRESHOLD` against it
  under :class:`difflib.SequenceMatcher` (character-level OCR noise); the
  entry's score is present-anchor-tokens / total-anchor-tokens; the entry
  matches at :data:`ANCHOR_MATCH_THRESHOLD`.
* **"Distinct captures"** (§2.2) means ``screenshot`` rows for the meeting.
  A capture the pipeline emitted twice is two rows and counts twice; a capture
  whose OCR could not be read still counts, because dropping it would let a
  broken run slip under the guardrail.

The report is a serialization of these result objects, never a second
computation: a check that recorded a number the algorithm did not return would
be a verdict nothing produced.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import pairwise
from typing import Any

from evals.harness.groundtruth import Manifest, normalize_anchor

#: Check names, as they appear in the report and in assertion messages. The
#: eval-design section number leads, so a report line points at the algorithm
#: that produced it.
CAPTURE_RECALL = "2.1 capture recall"
OVER_CAPTURE = "2.2 over-capture guardrail"
VIEW_CLASSIFICATION = "2.3 view classification"
DEDUP_QUALITY = "2.4 dedup quality"
DOC_INDEX_SEARCH_RECALL = "2.10 doc-index search recall"
PUBLISH_GATE_PROJECTION = "2.11 publish-gate projection"
#: Not one of eval-design's numbered checks: a precondition on the ground
#: truth itself. A manifest whose duration disagrees with the recording is
#: describing a different meeting, and every check downstream of it is
#: measuring the wrong thing.
DURATION_AGREEMENT = "ground-truth duration agreement"

#: An anchor token counts as present when some OCR token scores at least this
#: under `difflib.SequenceMatcher`. Character-level tolerance: "Fulfillment"
#: read as "Fulfiliment" still counts.
TOKEN_SIMILARITY_THRESHOLD = 0.85
#: The share of an anchor's tokens that must be present for the entry to match
#: (eval-design §2.1's "fuzzy token-set match >= 0.8").
ANCHOR_MATCH_THRESHOLD = 0.8
#: eval-design §2.1: any miss fails the run.
CAPTURE_RECALL_THRESHOLD = 1.0
#: eval-design §2.4: sequential captures above this are duplicate candidates
#: for a human to rule on. Strictly above — the threshold itself is not a
#: candidate.
DEDUP_SIMILARITY_THRESHOLD = 0.9
#: How far a manifest's `duration_minutes` may sit from the probed recording
#: length before the ground truth is treated as describing another meeting.
DURATION_TOLERANCE_MINUTES = 1.0
#: eval-design §2.10: recall@5 = 1.0 on planted phrases. k = 5 is provisional
#: per §6; the phrases are verbatim plants, so the index has no excuse.
SEARCH_RECALL_K = 5
SEARCH_RECALL_THRESHOLD = 1.0

#: The two retrieval stores check 2.11 asserts membership in, named the way
#: the report and every failure message name them.
SEARCH_STORE = "meilisearch"
GRAPH_STORE = "neo4j"
PUBLISH_STORES = (SEARCH_STORE, GRAPH_STORE)
#: The one lifecycle state the publish gate lets into a store (AD-4).
PUBLISHED_STATE = "published"
#: The state `POST /moments/{id}/approve` consumes. Named so the "nothing left
#: to approve" report line can say which state ran out.
EXTRACTED_STATE = "extracted"
#: The only corpus tag check 2.11 may approve. Mirrors
#: ``subjects.EVAL_CORPUS`` — redeclared rather than imported so this module
#: stays free of the network module's import surface; both name the same wire
#: value (`meeting.corpus`), and the refusal tests pin the behavior.
SCRIPTED_CORPUS = "scripted"

#: The view label a manifest section implies (eval-design §2.3). The
#: participant-segment label is separate because segments are not one of the
#: two archetype sections.
VIEW_FOR_SECTION = {"screens": "ui-screen", "slides": "slide"}
PARTICIPANT_VIEW = "participant-gallery"

#: How a participant segment is named in a report. Segments carry no `id` of
#: their own — only `at` and an optional `label` — so the index is the id.
SEGMENT_SECTION = "participant_segments"


@dataclass(frozen=True)
class Capture:
    """One ``screenshot`` row, reduced to what the checks compare.

    ``ocr_text`` is ``None`` when the capture has no OCR text *at all* — no
    ``representative_frame_id``, or no ``frame_ocr`` row for the frame it
    names. That is a defect of the run, never a reason to drop the capture:
    it stays in the count check 2.2 measures and it stays in the sequence
    check 2.4 walks. An empty string is different and is not a defect — a
    camera gallery legitimately recognizes no text.
    """

    ordinal: int
    view_type: str
    ocr_text: str | None
    has_representative_frame: bool

    @property
    def has_ocr_text(self) -> bool:
        return self.ocr_text is not None

    @property
    def normalized_text(self) -> str:
        """The OCR text folded exactly the way anchors are folded (5.1)."""
        return normalize_anchor(self.ocr_text) if self.ocr_text is not None else ""


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict, in the shape the report serializes.

    One shape for every check on purpose: ``write_report`` walks results
    without knowing which algorithm produced them, so there is no per-check
    serializer to drift away from the algorithm it serializes.

    ``blocking`` is what separates a metric from a gate. Checks 2.3 and 2.4
    are reported and never fail a run (eval-design §2.3 reports accuracy;
    §2.4 lists candidates for a human), so their results carry
    ``blocking=False`` and the run's verdict ignores their ``passed``.
    """

    check: str
    passed: bool
    blocking: bool = True
    #: False when the check could not be applied at all — a scripted subject
    #: with no recording, say. Never a pass and never a skip: an inapplicable
    #: blocking check fails the run, because a capture check that measured
    #: nothing has not shown that anything was captured.
    applicable: bool = True
    thresholds: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    detail: tuple[Mapping[str, Any], ...] = ()
    problems: tuple[str, ...] = ()

    def summary(self) -> str:
        """A one-line verdict plus every problem — the assertion message."""
        state = "PASSED" if self.passed else "FAILED"
        if not self.applicable:
            state = "NOT APPLICABLE"
        metrics = ", ".join(f"{key}={value}" for key, value in self.metrics.items())
        head = f"{self.check}: {state}" + (f" ({metrics})" if metrics else "")
        if not self.problems:
            return head
        return head + "\n  - " + "\n  - ".join(self.problems)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "passed": self.passed,
            "blocking": self.blocking,
            "applicable": self.applicable,
            "thresholds": dict(self.thresholds),
            "metrics": dict(self.metrics),
            "detail": [dict(item) for item in self.detail],
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class EntryMatch:
    """One manifest entry and the capture (if any) that answered for it."""

    entry_id: str
    section: str
    anchor: str | None
    expected_view: str
    matched: bool
    score: float
    ordinal: int | None = None
    matched_view: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry_id,
            "section": self.section,
            "anchor": self.anchor,
            "expected_view": self.expected_view,
            "matched": self.matched,
            "score": round(self.score, 4),
            "capture_ordinal": self.ordinal,
            "capture_view": self.matched_view,
        }


@dataclass(frozen=True)
class RecallResult(CheckResult):
    """Check 2.1's result, plus the per-entry matching check 2.3 reads.

    Check 2.3 scores the *matched* captures against the label their manifest
    section implies, so it needs the matching rather than a second pass over
    the captures. Handing it these records is what stops the two checks from
    disagreeing about which capture answered for which entry.
    """

    matches: tuple[EntryMatch, ...] = ()


def not_applicable(check: str, reason: str, *, blocking: bool = True) -> CheckResult:
    """A check that could not run, recorded as a failure rather than a skip.

    The *no silent zero* constraint's whole point: a suite that finds nothing
    to measure and reports success is how a harness comes to claim 100% while
    measuring nothing.
    """
    return CheckResult(
        check=check,
        passed=False,
        blocking=blocking,
        applicable=False,
        problems=(reason,),
    )


def token_containment(anchor: str, text: str) -> float:
    """Share of the anchor's tokens present in ``text``, OCR noise tolerated.

    Both sides are folded with 5.1's ``normalize_anchor`` — the same folding
    that rejects colliding anchors at authoring time. Folding them differently
    would make authoring-time collision rejection meaningless.

    Returns 0.0 when either side folds to nothing: an anchor with no tokens
    cannot be found (5.1 rejects those at authoring time), and a capture with
    no recognized text contains nothing.
    """
    anchor_tokens = normalize_anchor(anchor).split()
    if not anchor_tokens:
        return 0.0
    haystack = set(normalize_anchor(text).split())
    if not haystack:
        return 0.0
    present = sum(1 for token in anchor_tokens if _token_present(token, haystack))
    return present / len(anchor_tokens)


def _token_present(token: str, haystack: Iterable[str]) -> bool:
    if token in haystack:
        return True
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(token)
    for candidate in haystack:
        matcher.set_seq1(candidate)
        # The two cheap upper bounds first: `difflib`'s own documented way to
        # skip candidates that cannot reach the threshold.
        if (
            matcher.real_quick_ratio() >= TOKEN_SIMILARITY_THRESHOLD
            and matcher.quick_ratio() >= TOKEN_SIMILARITY_THRESHOLD
            and matcher.ratio() >= TOKEN_SIMILARITY_THRESHOLD
        ):
            return True
    return False


def ocr_defects(captures: Sequence[Capture]) -> tuple[str, ...]:
    """Captures that can produce no OCR text, named by ordinal.

    Reported rather than filtered. A capture with no text cannot match an
    anchor, so silently dropping it would shrink the haystack *and* the count
    at once — hiding a broken `frames`/`ocr` rerun behind a clean recall
    number and a comfortable over-capture margin.
    """
    problems: list[str] = []
    for capture in captures:
        if capture.has_ocr_text:
            continue
        if not capture.has_representative_frame:
            problems.append(
                f"capture {capture.ordinal} has no representative_frame_id, so it"
                " can produce no OCR text — a `frames` rerun cleared the reference"
                " and the `screens` stage has not run since"
            )
        else:
            problems.append(
                f"capture {capture.ordinal} names a representative frame with no"
                " frame_ocr row — the `ocr` stage did not cover the frame the"
                " `screens` stage chose"
            )
    return tuple(problems)


def _best_match(
    anchor: str, captures: Sequence[Capture]
) -> tuple[float, Capture | None]:
    """The highest-scoring capture for one anchor; ties go to the lower ordinal.

    Entries are matched independently, so two near-identical anchors can both
    resolve to the same capture. The matching is deliberately left that way —
    picking a winner greedily would turn a ground-truth authoring problem into
    what looks like a pipeline miss — but the outcome is not left unsaid:
    :func:`_double_assigned` finds it and :func:`capture_recall` reports it as
    a problem, so recall cannot read 1.0 over a screen nothing captured.
    """
    best_score = 0.0
    best: Capture | None = None
    for capture in sorted(captures, key=lambda item: item.ordinal):
        score = token_containment(anchor, capture.ocr_text or "")
        if score > best_score:
            best_score, best = score, capture
    return best_score, best


def _double_assigned(
    matches: Sequence[EntryMatch],
) -> tuple[tuple[int, tuple[str, ...]], ...]:
    """Captures that answered for more than one manifest entry.

    Entries are matched independently (see :func:`_best_match`), which is what
    lets two near-identical anchors — legal ground truth, since 5.1's
    uniqueness rule is exact-match-after-folding while this check matches
    fuzzily — both resolve to the same capture. Recall would then read 1.0
    while a scripted screen was never captured at all.

    Detected and reported rather than repaired. Assigning greedily instead
    would silently pick a winner and leave the loser unmatched, turning a
    ground-truth authoring problem into what looks like a pipeline miss; the
    runbook's triage step wants to see it for what it is.
    """
    claimed: dict[int, list[str]] = {}
    for match in matches:
        if match.matched and match.ordinal is not None:
            claimed.setdefault(match.ordinal, []).append(match.entry_id)
    return tuple(
        (ordinal, tuple(entries))
        for ordinal, entries in sorted(claimed.items())
        if len(entries) > 1
    )


def capture_recall(manifest: Manifest, captures: Sequence[Capture]) -> RecallResult:
    """Check 2.1: matched manifest entries / expected captures (threshold 1.0).

    The denominator is ``Manifest.expected_screenshot_count`` — slides (or
    screens) plus participant segments — and nothing here re-derives it
    (eval-design §1, the independence rule). The two halves of that
    denominator are matched differently because only one of them has anchors:

    * A slide or screen matches the capture whose OCR text best contains its
      ``ocr_anchor``, at :data:`ANCHOR_MATCH_THRESHOLD`.
    * A participant segment has no anchor — the manifest says only that the
      gallery should have been captured at that moment — so segments are
      matched by count against the ``participant-gallery`` captures, one
      apiece in ordinal order. That is the only signal the schema offers, and
      dropping segments from the denominator instead would make a missing
      gallery capture unnoticeable.
    """
    matches: list[EntryMatch] = []
    section = manifest.section
    expected_view = VIEW_FOR_SECTION[section]
    for index, entry in enumerate(manifest.entries):
        anchor = str(entry.get("ocr_anchor", ""))
        score, capture = _best_match(anchor, captures)
        matched = score >= ANCHOR_MATCH_THRESHOLD and capture is not None
        matches.append(
            EntryMatch(
                entry_id=str(entry.get("id", f"{section}[{index}]")),
                section=section,
                anchor=normalize_anchor(anchor),
                expected_view=expected_view,
                matched=matched,
                score=score,
                ordinal=capture.ordinal if matched and capture else None,
                matched_view=capture.view_type if matched and capture else None,
            )
        )

    gallery = sorted(
        (c for c in captures if c.view_type == PARTICIPANT_VIEW),
        key=lambda item: item.ordinal,
    )
    for index, segment in enumerate(manifest.participant_segments):
        capture = gallery[index] if index < len(gallery) else None
        matches.append(
            EntryMatch(
                entry_id=f"{SEGMENT_SECTION}[{index}] at {segment.get('at')}",
                section=SEGMENT_SECTION,
                anchor=None,
                expected_view=PARTICIPANT_VIEW,
                matched=capture is not None,
                score=1.0 if capture is not None else 0.0,
                ordinal=capture.ordinal if capture else None,
                matched_view=capture.view_type if capture else None,
            )
        )

    expected = manifest.expected_screenshot_count
    matched_count = sum(1 for match in matches if match.matched)
    recall = matched_count / expected if expected else 0.0

    problems = [
        (
            f"manifest entry {match.entry_id!r} is unmatched:"
            + (
                f" no capture's OCR text contains its anchor"
                f" {match.anchor!r} at {ANCHOR_MATCH_THRESHOLD}"
                f" (best score {round(match.score, 4)})"
                if match.anchor is not None
                else " no participant-gallery capture is left to answer for it"
            )
        )
        for match in matches
        if not match.matched
    ]
    if not expected:
        problems.append(
            f"manifest {manifest.id!r} expects no captures at all, so recall"
            " measures nothing"
        )
    if len(matches) != expected:
        # The denominator and the entries walked have to be the same set. If
        # they ever diverge, `matched / expected` stops being recall — and it
        # can exceed 1.0, which would read as better than perfect rather than
        # as broken.
        problems.append(
            f"the check built {len(matches)} entry records for a manifest whose"
            f" expected_screenshot_count is {expected}: the recall denominator"
            " and the entries actually walked have diverged, so this ratio is"
            " not recall"
        )
    shared = _double_assigned(matches)
    problems.extend(
        f"capture {ordinal} answers for {len(entries)} manifest entries"
        f" ({', '.join(entries)}) — one capture cannot be two screens, so"
        " recall is counting at least one entry whose screen may never have"
        " been captured. Triage as a ground-truth script error first: the"
        " cheap fix is to make those anchors share fewer words"
        for ordinal, entries in shared
    )
    defects = ocr_defects(captures)
    problems.extend(defects)

    return RecallResult(
        check=CAPTURE_RECALL,
        # Every way this check can be wrong is already a problem, and a run
        # with no problems has recall 1.0 by construction — so the verdict is
        # "nothing to report", not a second list of conditions that could
        # drift away from the first.
        passed=bool(expected) and recall >= CAPTURE_RECALL_THRESHOLD and not problems,
        thresholds={
            "recall": CAPTURE_RECALL_THRESHOLD,
            "anchor_match": ANCHOR_MATCH_THRESHOLD,
            "token_similarity": TOKEN_SIMILARITY_THRESHOLD,
        },
        metrics={
            "recall": round(recall, 4),
            "matched": matched_count,
            "expected": expected,
            "captures": len(captures),
            "ocr_defects": len(defects),
            "double_assigned_captures": len(shared),
        },
        detail=tuple(match.to_dict() for match in matches),
        problems=tuple(problems),
        matches=tuple(matches),
    )


def over_capture(manifest: Manifest, captures: Sequence[Capture]) -> CheckResult:
    """Check 2.2: ``screenshot`` rows must not exceed the capture budget.

    The budget is ``max(ceil(duration_minutes), expected_screenshot_count)``.
    The one-per-minute arm is eval-design §2.2's guardrail; the second arm
    exists because a scripted take can run shorter than planned (demo-001 ran
    247 s against a planned 12 minutes), leaving the manifest demanding more
    captures than the take has minutes — a budget below the manifest's own
    recall denominator would fail a pipeline for doing exactly what check 2.1
    requires of it.

    Every row counts — including a capture with no readable OCR text. The
    guardrail is about how much the extractor emitted, and text the pipeline
    failed to read does not make a capture stop existing.
    """
    count = len(captures)
    duration = float(manifest.duration_minutes)
    budget = max(math.ceil(duration), manifest.expected_screenshot_count)
    per_minute = round(count / duration, 3) if duration > 0 else None
    passed = count <= budget
    over_budget = (
        f"{count} captures for {duration} minutes exceeds the budget of"
        f" {budget} (max of one per minute and the manifest's"
        f" {manifest.expected_screenshot_count} expected captures):"
        f" {per_minute} captures/min"
    )
    return CheckResult(
        check=OVER_CAPTURE,
        passed=passed,
        thresholds={
            "max_captures": budget,
            "budget_formula": "max(ceil(duration_minutes), expected_screenshot_count)",
        },
        metrics={
            "captures": count,
            "budget": budget,
            "duration_minutes": duration,
            "captures_per_minute": per_minute,
        },
        problems=() if passed else (over_budget,),
    )


def view_classification(
    manifest: Manifest, matches: Sequence[EntryMatch]
) -> CheckResult:
    """Check 2.3: classified view vs the label the matched section implies.

    Reported, never a gate (``blocking=False``): eval-design §2.3 calls
    accuracy a tracked metric, and a misclassified capture is still evidence
    that was captured. Only matched entries are scored — an unmatched entry
    has no capture to classify, and it has already failed check 2.1.
    """
    scored = [match for match in matches if match.matched]
    correct = sum(1 for match in scored if match.matched_view == match.expected_view)
    accuracy = correct / len(scored) if scored else None
    wrong = [
        f"capture {match.ordinal} answering for {match.entry_id!r} is classified"
        f" {match.matched_view!r}, but its manifest section implies"
        f" {match.expected_view!r}"
        for match in scored
        if match.matched_view != match.expected_view
    ]
    if not scored:
        wrong.append(
            f"manifest {manifest.id!r} matched no captures, so there is no"
            " classification to score"
        )
    return CheckResult(
        check=VIEW_CLASSIFICATION,
        passed=accuracy == 1.0 if scored else False,
        blocking=False,
        thresholds={},
        metrics={
            "accuracy": round(accuracy, 4) if accuracy is not None else None,
            "correct": correct,
            "scored": len(scored),
        },
        detail=tuple(
            match.to_dict()
            for match in scored
            if match.matched_view != match.expected_view
        ),
        problems=tuple(wrong),
    )


def dedup_candidates(captures: Sequence[Capture]) -> CheckResult:
    """Check 2.4: sequential captures whose folded OCR text is too alike.

    Candidates only. Nothing is collapsed and nothing fails
    (``blocking=False``): the SPEC biases toward over-capture rather than
    loss, so a human rules keep-or-collapse per pair (runbook step 4).

    Similarity is ``difflib.SequenceMatcher`` over the folded text of the two
    captures — character-level, so a page that gained one field reads as a
    near-duplicate while a different screen does not. Two captures that both
    recognize no text score 1.0 and are listed: several textless gallery shots
    in a row genuinely are candidates for a human to rule on.
    """
    ordered = sorted(captures, key=lambda item: item.ordinal)
    pairs: list[dict[str, Any]] = []
    for earlier, later in pairwise(ordered):
        if not (earlier.has_ocr_text and later.has_ocr_text):
            # Its own reported defect (check 2.1); scoring it here would
            # invent a similarity from text that was never read.
            continue
        score = SequenceMatcher(
            None, earlier.normalized_text, later.normalized_text, autojunk=False
        ).ratio()
        if score > DEDUP_SIMILARITY_THRESHOLD:
            pairs.append(
                {
                    "captures": [earlier.ordinal, later.ordinal],
                    "similarity": round(score, 4),
                    "views": [earlier.view_type, later.view_type],
                }
            )
    return CheckResult(
        check=DEDUP_QUALITY,
        passed=True,
        blocking=False,
        thresholds={"similarity": DEDUP_SIMILARITY_THRESHOLD},
        metrics={"candidates": len(pairs), "captures": len(captures)},
        detail=tuple(pairs),
        problems=tuple(
            f"captures {pair['captures'][0]} and {pair['captures'][1]} are"
            f" {pair['similarity']} similar — a human rules keep or collapse"
            for pair in pairs
        ),
    )


def duration_agreement(
    manifest: Manifest, media_duration_ms: int | None
) -> CheckResult:
    """The manifest and the recording must describe the same meeting.

    ``duration_minutes`` is the over-capture budget *and* the range every
    manifest timestamp is validated against, so a manifest that is a minute or
    more away from the probed recording is ground truth for something else.
    Failing here rather than inside check 2.2 is what lets triage classify it
    as a script error instead of a pipeline bug (runbook step 2).
    """
    declared = float(manifest.duration_minutes)
    if media_duration_ms is None:
        unprobed = (
            "the meeting has no probed media duration (no meeting_media row, or"
            " duration_ms is NULL), so the manifest's duration_minutes of"
            f" {declared} cannot be cross-checked"
        )
        return CheckResult(
            check=DURATION_AGREEMENT,
            passed=False,
            thresholds={"tolerance_minutes": DURATION_TOLERANCE_MINUTES},
            metrics={"manifest_minutes": declared, "recording_minutes": None},
            problems=(unprobed,),
        )
    probed = media_duration_ms / 60000
    delta = abs(declared - probed)
    passed = delta <= DURATION_TOLERANCE_MINUTES
    disagreement = (
        f"the manifest declares {declared} minutes but the recording is"
        f" {round(probed, 3)} — a gap of {round(delta, 3)} minutes, past the"
        f" {DURATION_TOLERANCE_MINUTES}-minute tolerance. The manifest may be"
        " describing a different meeting."
    )
    return CheckResult(
        check=DURATION_AGREEMENT,
        passed=passed,
        thresholds={"tolerance_minutes": DURATION_TOLERANCE_MINUTES},
        metrics={
            "manifest_minutes": declared,
            "recording_minutes": round(probed, 3),
            "delta_minutes": round(delta, 3),
        },
        problems=() if passed else (disagreement,),
    )


# --------------------------------------------------------------------------
# Check 2.10 — doc-index search recall (story 5.3)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """One ``GET /search`` hit, reduced to what check 2.10 scores.

    ``meeting_id`` is the membership signal — a phrase passes when a hit from
    its containing meeting appears in the top k — and ``moment_id``/``score``
    are what a miss reports, so triage can see what outranked the plant.
    """

    moment_id: str
    meeting_id: str
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "moment_id": self.moment_id,
            "meeting_id": self.meeting_id,
            "score": self.score,
        }


@dataclass(frozen=True)
class PhraseSearch:
    """One ``GET /search`` response for one planted phrase.

    ``ranking`` and ``index_missing`` are the response's own announcements
    (`SearchResponse.ranking` / `.indexMissing`). Both are recorded per
    phrase: a degraded ``keyword`` ranking is context a triager needs, and a
    missing index is a failure in its own right — "nothing was ever
    projected" is not "the plant was outranked".
    """

    hits: tuple[SearchHit, ...]
    ranking: str
    index_missing: bool = False


def search_recall(
    manifest: Manifest,
    meeting_id: str,
    hits_by_phrase: Mapping[str, PhraseSearch],
    *,
    unqueried: Mapping[str, str] | None = None,
) -> CheckResult:
    """Check 2.10: recall@k on planted phrases through the public ``/search``.

    One query per ``planted.phrases`` entry, ``limit=k``, no corpus filter —
    the index gets no help. A phrase passes iff some hit's ``meeting_id``
    equals the subject's meeting id within the top :data:`SEARCH_RECALL_K`
    hits (the list is sliced to k here, so an over-long response cannot widen
    the window); recall@5 must be 1.0 (the phrases are verbatim plants,
    eval-design §2.10) or the run fails.

    ``unqueried`` maps phrase id → why its query could not be issued (the api
    refused, carrying the problem slug). Those phrases fail by name; a phrase
    absent from *both* mappings is a divergence between the queries issued
    and the manifest — as is a key in ``hits_by_phrase`` naming no manifest
    phrase, since a ratio over a different set than the denominator's is not
    recall.

    A manifest that plants no phrases is a blocking *not applicable*, never a
    vacuous pass: a recall over zero phrases has measured nothing. A
    ``keyword`` ranking (embedder down) is recorded, not failed — verbatim
    plants must survive keyword ranking, and failing on embedder downtime
    would misattribute the miss.
    """
    unqueried = unqueried or {}
    thresholds = {"k": SEARCH_RECALL_K, "recall": SEARCH_RECALL_THRESHOLD}
    phrases = tuple(manifest.planted.get("phrases") or ())
    if not phrases:
        return CheckResult(
            check=DOC_INDEX_SEARCH_RECALL,
            passed=False,
            applicable=False,
            thresholds=thresholds,
            metrics={"phrases": 0},
            problems=(
                (
                    f"manifest {manifest.id!r} plants no phrases"
                    " (planted.phrases is absent or empty), so doc-index"
                    " recall has nothing to measure — never a vacuous pass"
                ),
            ),
        )

    detail: list[dict[str, Any]] = []
    problems: list[str] = []
    found = 0
    walked: set[str] = set()
    for index, phrase in enumerate(phrases):
        phrase_id = str(phrase.get("id", f"phrases[{index}]"))
        text = str(phrase.get("text", ""))
        walked.add(phrase_id)
        outcome = hits_by_phrase.get(phrase_id)
        if outcome is None:
            reason = unqueried.get(phrase_id)
            if reason is not None:
                problems.append(
                    f"phrase {phrase_id!r} ({text!r}) could not be queried:"
                    f" {reason}"
                )
            else:
                problems.append(
                    f"phrase {phrase_id!r} has no recorded search outcome —"
                    " the queries issued and the manifest's phrase list have"
                    " diverged, so this recall is not recall"
                )
            detail.append(
                {
                    "phrase": phrase_id,
                    "text": text,
                    "queried": False,
                    "reason": reason,
                }
            )
            continue
        # Sliced to k defensively: the query asks for `limit=k`, but an
        # over-long response must not quietly widen recall@5 into recall@N.
        top = outcome.hits[:SEARCH_RECALL_K]
        rank = next(
            (
                position
                for position, hit in enumerate(top, start=1)
                if hit.meeting_id == meeting_id
            ),
            None,
        )
        detail.append(
            {
                "phrase": phrase_id,
                "text": text,
                "rank": rank,
                "ranking": outcome.ranking,
                "index_missing": outcome.index_missing,
                "hits": [hit.to_dict() for hit in top],
            }
        )
        if outcome.index_missing:
            problems.append(
                f"phrase {phrase_id!r}: the search index does not exist"
                " (indexMissing) — nothing was ever projected, so the plant"
                " was never findable"
            )
            continue
        if rank is None:
            got = (
                "; ".join(
                    f"rank {position}: moment {hit.moment_id}"
                    f" (meeting {hit.meeting_id}, score {hit.score})"
                    for position, hit in enumerate(top, start=1)
                )
                or "no hits at all"
            )
            problems.append(
                f"phrase {phrase_id!r} ({text!r}) surfaced no hit from meeting"
                f" {meeting_id} in the top {SEARCH_RECALL_K} — got: {got}"
            )
            continue
        found += 1

    strays = sorted((set(hits_by_phrase) | set(unqueried)) - walked)
    if strays:
        problems.append(
            f"search outcomes or failed queries were recorded for"
            f" {', '.join(repr(s) for s in strays)}, which name no manifest"
            " phrase — the queries issued and the"
            " manifest's phrase list have diverged, so this recall is not"
            " recall"
        )

    recall = found / len(phrases)
    return CheckResult(
        check=DOC_INDEX_SEARCH_RECALL,
        passed=recall >= SEARCH_RECALL_THRESHOLD and not problems,
        thresholds=thresholds,
        metrics={
            "recall_at_k": round(recall, 4),
            "found": found,
            "phrases": len(phrases),
        },
        detail=tuple(detail),
        problems=tuple(problems),
    )


# --------------------------------------------------------------------------
# Check 2.11 — publish-gate projection (story 5.3)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StorePresence:
    """One artifact's membership in one retrieval store, read-only.

    ``cited_moment_ids`` carries how the store relates the artifact to
    moments — the projected document's ``momentIds`` for Meilisearch, the
    ``Moment`` nodes the artifact's node relates to for Neo4j — so citation
    resolution is asserted from the same read that established presence.
    """

    present: bool
    cited_moment_ids: tuple[str, ...] = ()
    #: Anything anomalous the read noticed that is not by itself a gate
    #: verdict — e.g. several graph nodes sharing the artifact's id. Kept on
    #: the presence so it lands in the report's detail beside the read that
    #: saw it.
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "cited_moment_ids": list(self.cited_moment_ids),
            "note": self.note,
        }


@dataclass(frozen=True)
class ApproveOutcome:
    """What happened at ``POST /moments/{id}/approve`` — the one mutation.

    Since story 11.3 the approval is only ever the run-owned probe's:
    ``attempted=False`` on a minted probe means the probe layer and the check
    have diverged, and the check says so rather than passing over it.
    ``detail`` carries the problem slug when the api refused — or the named
    race, when a concurrent run's approval published the probe first (the
    409 resolved by re-reading the probe's own row; the gate was still
    exercised through the public api, so ``ok`` is ``True`` and the race is
    on the record).
    """

    attempted: bool
    ok: bool = False
    detail: str | None = None
    #: The run-minted artifact ids the approval advanced to ``published``,
    #: read off the endpoint's own post-call response after the ownership
    #: filter — the positive half's assert set.
    published_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CleanupReport:
    """What the probe erased on its way out, verified per target.

    Four booleans because the probe lands in four places: the Postgres row
    the run minted, the Meilisearch document and Neo4j node the api
    projected for it, and the export file the api wrote under the publish
    root. Each is ``True`` only when the erasure was *verified* — the target
    read back absent afterward — never merely attempted. ``problems`` names
    every leftover with the exact ids and the manual remedy; a leftover is a
    named failure of the check, loud by design.
    """

    search_document_removed: bool
    graph_node_removed: bool
    export_file_removed: bool
    postgres_row_removed: bool
    problems: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return (
            self.search_document_removed
            and self.graph_node_removed
            and self.export_file_removed
            and self.postgres_row_removed
            and not self.problems
        )

    def leftovers(self) -> tuple[str, ...]:
        """The targets whose erasure did not verify, by field name."""
        return tuple(
            name
            for name, removed in (
                ("search_document_removed", self.search_document_removed),
                ("graph_node_removed", self.graph_node_removed),
                ("export_file_removed", self.export_file_removed),
                ("postgres_row_removed", self.postgres_row_removed),
            )
            if not removed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "search_document_removed": self.search_document_removed,
            "graph_node_removed": self.graph_node_removed,
            "export_file_removed": self.export_file_removed,
            "postgres_row_removed": self.postgres_row_removed,
            "verified": self.verified,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class GateProbe:
    """The run-owned probe artifact: the one mutation sequence 2.11 measures.

    The probe layer (``evals/checks/gate_probe.py``) mints one ``extracted``
    artifact onto an eligible projected subject moment, reads its membership
    in both stores, approves it through the public api, reads again, and
    erases everything it left behind. This record carries that whole
    sequence into the pure assembly.

    ``problem`` set means the sequence did not complete: either nothing was
    minted at all (no eligible moment, unprojected meeting, unsettled
    extract stage — ``artifact_id`` is then ``None``), or a store read
    failed mid-probe (``artifact_id`` is set, and the cleanup verdict is
    still enforced). Either way the gate transition went unmeasured, which
    is a blocking not-applicable — never a pass, and never allowed to
    soften a violation the reads did establish.
    """

    artifact_id: str | None = None
    moment_id: str | None = None
    pre: Mapping[str, StorePresence] | None = None
    post: Mapping[str, StorePresence] | None = None
    approve: ApproveOutcome = ApproveOutcome(attempted=False)
    cleanup: CleanupReport | None = None
    problem: str | None = None
    #: A concurrent run's approval published this probe before (or instead
    #: of) this run's own approve call — detected at the pre-read or at the
    #: 409. The pre-read may then legitimately show presence (the row was
    #: already ``published`` when it was read), so the pre-absence half is
    #: not asserted; the positive half and the cleanup verdict still are.
    raced: bool = False
    #: Approve-response rows for artifacts the run did not mint. The route
    #: returns every artifact under the moment by design, so these are
    #: recorded in the detail and ignored for ownership asserts — never a
    #: divergence.
    foreign_ids: tuple[str, ...] = ()
    #: Foreign rows this approval could have advanced: rows returned as
    #: ``published`` that were ``extracted`` at discovery, plus response ids
    #: absent from discovery (the late-arrival window). Kept separate from
    #: already-published context rows so an independent settled row is never
    #: blamed on this run.
    consumed_foreign_ids: tuple[str, ...] = ()


def _membership_of(
    membership: Mapping[str, Mapping[str, StorePresence]],
    artifact_id: str,
) -> dict[str, StorePresence | None]:
    recorded = membership.get(artifact_id, {})
    return {store: recorded.get(store) for store in PUBLISH_STORES}


#: The rule in force for every 2.11 result, whatever branch produced it —
#: eval-design §6's "thresholds travel with the result they produced" applies
#: to the refusal exactly as to a measurement.
PUBLISH_GATE_THRESHOLDS: Mapping[str, Any] = {
    "gate": (
        f"non-{PUBLISHED_STATE} artifacts appear in neither store;"
        f" {PUBLISHED_STATE} artifacts appear in both"
        f" ({', '.join(PUBLISH_STORES)}) citing their source moment"
    ),
    "probe": (
        "the gate transition is measured on one run-owned probe artifact —"
        " minted, approved and erased by the run, with cleanup verified;"
        " subject artifacts are read-only and never approved"
    ),
    "approvable_corpus": SCRIPTED_CORPUS,
}


def publish_gate_refusal(
    meeting_id: str, corpus_tag: str | None
) -> CheckResult | None:
    """Why 2.11 must not touch this meeting, as a result — or ``None``.

    Pure and store-free, so the guard is pinned by the algorithm suite rather
    than living only in check glue no test reaches (the live selector already
    pre-filters to scripted subjects, which is exactly why this second check
    against the *database's* tag needs its own falsifiable seam). Two
    refusals, worded apart because they are different findings:

    * a tag that is not ``scripted`` — the manifest names the wrong meeting
      or the drop was tagged wrong; the real corpus is never approved by a
      machine;
    * no tag at all, meaning the meeting row is gone — the api listed it and
      Postgres no longer has it, so the harness is mid-rerun or pointed at a
      different database. Never rendered as "corpus None": that would send
      triage after a tag nobody ever wrote.

    Either way: a blocking failure, and **no api call is made**.
    """
    if corpus_tag == SCRIPTED_CORPUS:
        return None
    if corpus_tag is None:
        problem = (
            f"REFUSED: meeting {meeting_id} has no meeting row in Postgres"
            " any more — the api listed it, so either the row was deleted"
            " mid-run or the harness is pointed at a different database than"
            " the api; nothing provably scripted is here to approve, so no"
            " approval call was made"
        )
    else:
        problem = (
            f"REFUSED: meeting {meeting_id} is corpus {corpus_tag!r}, not"
            f" {SCRIPTED_CORPUS!r} — the real corpus is never approved by a"
            " machine, so no approval call was made"
        )
    return CheckResult(
        check=PUBLISH_GATE_PROJECTION,
        passed=False,
        thresholds=PUBLISH_GATE_THRESHOLDS,
        metrics={"corpus": corpus_tag, "approve_attempted": False},
        problems=(problem,),
    )


def _probe_sequence_problems(probe: GateProbe) -> list[str]:
    """Every defect in the probe's minted-approved-asserted sequence.

    Only called for a probe that was minted *and* not interrupted: an
    interruption already carries its own named diagnosis, and piling the
    pre/post divergence lines on top of it would bury the cause under its
    consequences.
    """
    problems: list[str] = []
    artifact_id = str(probe.artifact_id)
    moment_id = str(probe.moment_id) if probe.moment_id is not None else None
    if moment_id is None:
        problems.append(
            f"probe artifact {artifact_id} recorded no moment id — its"
            " citation resolution cannot be verified; the probe layer and"
            " the check have diverged"
        )

    # The negative half of the measured transition: the freshly minted
    # `extracted` probe must be in neither store. Not asserted for a raced
    # probe: a sibling run's approval published the row before this run's
    # pre-read, so presence there is the gate working, not a violation.
    if not probe.raced:
        for store in PUBLISH_STORES:
            presence = (probe.pre or {}).get(store)
            if presence is None:
                problems.append(
                    f"no pre-approval {store} membership was recorded for probe"
                    f" artifact {artifact_id} — the probe layer and the check"
                    " have diverged"
                )
            elif presence.present:
                problems.append(
                    f"GATE VIOLATION: probe artifact {artifact_id} (state"
                    f" {EXTRACTED_STATE!r}) is present in {store} before approval"
                    " — an unpublished artifact reached a retrieval store (AD-4)"
                )

    # The mutation — the run's own approval, or the named reason it failed.
    if not probe.approve.attempted:
        problems.append(
            f"probe artifact {artifact_id} was minted but no approval was"
            " attempted — the probe layer and the check have diverged"
        )
    elif not probe.approve.ok:
        problems.append(
            "approving the probe through the public api failed:"
            f" {probe.approve.detail or 'no detail recorded'}"
        )
    elif artifact_id not in probe.approve.published_ids:
        problems.append(
            "the approval reported success but probe artifact"
            f" {artifact_id} is not among the published rows it returned —"
            " the approve outcome and the probe have diverged, so the"
            " positive half verified nothing"
        )
    else:
        # The positive half: the published probe is in both stores, citing
        # the subject moment it was minted onto.
        for store in PUBLISH_STORES:
            presence = (probe.post or {}).get(store)
            if presence is None:
                problems.append(
                    f"no post-approval {store} membership was recorded for"
                    f" probe artifact {artifact_id} — the probe layer and"
                    " the check have diverged"
                )
            elif not presence.present:
                problems.append(
                    f"published probe artifact {artifact_id} is absent from"
                    f" {store} after approval — projection-on-publish"
                    " (story 4-4) has regressed: the approve route must land"
                    " the artifact in both stores"
                )
            elif (
                moment_id is not None
                and moment_id not in presence.cited_moment_ids
            ):
                cited = ", ".join(presence.cited_moment_ids) or "nothing"
                problems.append(
                    f"probe artifact {artifact_id} is present in {store} but"
                    " its citation does not resolve to its source moment"
                    f" {moment_id} — the store cites {cited}"
                )
    return problems


def _probe_cleanup_problems(probe: GateProbe) -> list[str]:
    """The cleanup verdict, enforced for every minted probe — loud always."""
    artifact_id = str(probe.artifact_id)
    if probe.cleanup is None:
        return [
            f"no cleanup was recorded for probe artifact {artifact_id} — the"
            " run-minted row and whatever the api projected for it may be"
            " left behind; remove them by that id"
        ]
    problems = list(probe.cleanup.problems)
    # `cleanup_probe` writes prose ("Meilisearch still holds artifact …"),
    # not field names, so the unexplained-leftover backstop matches on the
    # store vocabulary the real messages carry — pinned by the algorithm
    # suite against the verbatim wording, so the two layers cannot drift
    # back into the field-name mismatch this replaced (a real leftover used
    # to earn a second, false "no recorded reason" line).
    keywords: dict[str, tuple[str, ...]] = {
        "search_document_removed": ("meilisearch",),
        "graph_node_removed": ("neo4j",),
        "export_file_removed": ("export file", "mm_publish_root"),
        "postgres_row_removed": ("postgres",),
    }
    lowered = [problem.lower() for problem in problems]
    unexplained = [
        name
        for name in probe.cleanup.leftovers()
        if not any(
            keyword in problem
            for keyword in keywords[name]
            for problem in lowered
        )
    ]
    if unexplained:
        problems.append(
            f"probe cleanup left {', '.join(unexplained)} unverified for"
            f" artifact {artifact_id} with no recorded reason — remove the"
            " leftover by that id and fix the cleanup reporting"
        )
    return problems


def publish_gate(
    meeting_id: str,
    artifacts: Sequence[Any],
    membership: Mapping[str, Mapping[str, StorePresence]],
    probe: GateProbe,
) -> CheckResult:
    """Check 2.11: unpublished absent from both stores; published in both.

    Pure assembly over observations the test layer gathered (discovery via
    the read-only corpus connection, membership via read-only store reads,
    the probe via ``evals/checks/gate_probe.py``). ``artifacts`` items carry
    ``id``, ``moment_id`` and ``state`` (``corpus.ArtifactRow`` does).

    Subject artifacts are asserted **read-only**, one membership read apiece:
    every non-``published`` row absent from both stores, every ``published``
    row present in both with its citation resolving. The run never approves
    a subject row — the shared corpus's ``extracted`` rows survive every run
    — so an unconsumed extracted row is the expected steady state, not a
    divergence, and there is no consumed-lifecycle branch any more.

    The gate *transition* is measured on the run-owned probe: minted
    ``extracted``, absent from both stores, approved through the public api,
    present in both citing its subject moment, and erased with the cleanup
    verified. Any violation fails the run; an unpublished artifact in a
    store — subject or probe — is the headline: the SPEC's publish-gate
    constraint broken (AD-4).
    """
    thresholds = PUBLISH_GATE_THRESHOLDS
    states: dict[str, int] = {}
    for artifact in artifacts:
        states[artifact.state] = states.get(artifact.state, 0) + 1

    problems: list[str] = []

    # The subject halves: one read per artifact, no mutation anywhere.
    for artifact in artifacts:
        artifact_id = str(artifact.id)
        moment_id = str(artifact.moment_id)
        for store, presence in _membership_of(membership, artifact_id).items():
            if presence is None:
                problems.append(
                    f"no {store} membership was recorded for artifact"
                    f" {artifact_id} (state {artifact.state!r}) — the"
                    " observations and the discovery have diverged"
                )
            elif artifact.state == PUBLISHED_STATE:
                if not presence.present:
                    problems.append(
                        f"published artifact {artifact_id} is absent from"
                        f" {store} — projection-on-publish (story 4-4) has"
                        " regressed: the approve route must land the artifact"
                        " in both stores"
                    )
                elif moment_id not in presence.cited_moment_ids:
                    cited = ", ".join(presence.cited_moment_ids) or "nothing"
                    problems.append(
                        f"artifact {artifact_id} is present in {store} but"
                        " its citation does not resolve to its source moment"
                        f" {moment_id} — the store cites {cited}"
                    )
            elif presence.present:
                problems.append(
                    f"GATE VIOLATION: artifact {artifact_id} (state"
                    f" {artifact.state!r}) is present in {store} — an"
                    " unpublished artifact reached a retrieval store (AD-4)"
                )

    # The probe: the measured gate transition, or the named reason it went
    # unmeasured. A minted probe's cleanup verdict is enforced either way.
    probe_measured = False
    probe_problems: list[str] = []
    if probe.problem is not None:
        probe_problems.append(probe.problem)
    if probe.artifact_id is None:
        if probe.problem is None:
            probe_problems.append(
                f"the probe for meeting {meeting_id} recorded neither an"
                " artifact nor a problem — the probe layer and the check"
                " have diverged"
            )
    else:
        if probe.problem is None:
            probe_measured = True
            probe_problems.extend(_probe_sequence_problems(probe))
        elif not probe.raced:
            # An interruption does not un-see a violation: a pre-read that
            # recorded the extracted probe present in a store stands on its
            # own, whatever stopped the sequence afterwards.
            for store in PUBLISH_STORES:
                presence = (probe.pre or {}).get(store)
                if presence is not None and presence.present:
                    probe_problems.append(
                        f"GATE VIOLATION: probe artifact {probe.artifact_id}"
                        f" (state {EXTRACTED_STATE!r}) is present in {store}"
                        " before approval — an unpublished artifact reached a"
                        " retrieval store (AD-4); recorded before the probe"
                        " was interrupted"
                    )
        probe_problems.extend(_probe_cleanup_problems(probe))
    # A foreign published row the discovery saw as `extracted` is a subject
    # row this run's approval consumed — a row landed on the chosen moment
    # between the eligibility read and the approval (the accepted residual
    # window, named in gate_probe.py and the RUNBOOK). The remaining foreign
    # rows — already published before this run — stay recorded-only.
    consumed = sorted(probe.consumed_foreign_ids)
    if consumed:
        probe_problems.append(
            "the probe's approval consumed subject rows the discovery saw as"
            f" {EXTRACTED_STATE!r}: {', '.join(consumed)} — the lifecycle is"
            " one-way, so record this beside the run and re-extract the"
            " subject before the next gate measurement"
        )
    problems.extend(probe_problems)

    if not artifacts:
        problems.append(
            f"meeting {meeting_id} has no artifacts at all — the extract"
            " stage never ran for it, so the subject halves of the publish"
            " gate have nothing to hold to; never a vacuous pass"
        )

    def presence_dicts(
        recorded: Mapping[str, StorePresence] | None,
    ) -> dict[str, dict[str, Any] | None]:
        return {
            store: (
                presence.to_dict()
                if (presence := (recorded or {}).get(store)) is not None
                else None
            )
            for store in PUBLISH_STORES
        }

    detail = tuple(
        {
            "artifact": str(artifact.id),
            "moment": str(artifact.moment_id),
            "state": artifact.state,
            "membership": presence_dicts(membership.get(str(artifact.id))),
        }
        for artifact in artifacts
    ) + (
        {
            "probe": True,
            "artifact": probe.artifact_id,
            "moment": probe.moment_id,
            "problem": probe.problem,
            "approve": {
                "attempted": probe.approve.attempted,
                "ok": probe.approve.ok,
                "detail": probe.approve.detail,
                "published_ids": list(probe.approve.published_ids),
            },
            "foreign_rows": list(probe.foreign_ids),
            "consumed_foreign_rows": list(probe.consumed_foreign_ids),
            "pre": presence_dicts(probe.pre),
            "post": presence_dicts(probe.post),
            "cleanup": (
                probe.cleanup.to_dict() if probe.cleanup is not None else None
            ),
        },
    )

    violation_found = any("GATE VIOLATION" in problem for problem in problems)
    return CheckResult(
        check=PUBLISH_GATE_PROJECTION,
        passed=not problems,
        # `applicable=False` only when the gate transition went unmeasured
        # (or there was no subject artifact to hold to the gate at all) *and*
        # nothing that was measured was violated: a real violation must read
        # as a failure, never soften into "could not be measured". A measured
        # probe's own defects — a post-approval absence, a citation miss, a
        # cleanup leftover — are measurements too, so they keep the result
        # applicable even on a meeting with no subject artifacts.
        applicable=(bool(artifacts) and probe_measured)
        or violation_found
        or bool(probe_measured and probe_problems),
        thresholds=thresholds,
        metrics={
            "artifacts": len(artifacts),
            "states": states,
            "probe_minted": probe.artifact_id is not None,
            "approve_attempted": probe.approve.attempted,
            "cleanup_verified": (
                probe.cleanup is not None and probe.cleanup.verified
            ),
        },
        detail=detail,
        problems=tuple(problems),
    )
