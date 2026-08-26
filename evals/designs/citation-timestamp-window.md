# Design: Citation Timestamp Window (check 2.5)

**Status: documented only — not implemented.** Deferred per
`docs/architecture.md` ("Document (not implement):
the retrieval eval strategy… Produce designs for ALL retrieval items" — the
capstone strategy is design everything, build the slice). The contract of
record is `eval-design.md` §2.5; this file is that sketch expanded to an
implementable design. Until it is built, the human judge stands in: the
`qa-right-moment-cited` worksheet in `evals/RUNBOOK.md` step 5 covers the same
ground by hand.

## What it checks

That a citation does not merely point at the right planted item but points at
the right **moment in time**: a citation that resolves to the planted decision
but drops the viewer three minutes early has failed the "verification takes
seconds, not a rewatch" promise even though the retrieval was nominally
correct.

## Algorithm

For **each manifest `qa` entry**, evaluate exactly its first API-returned
citation (the top citation). The expected plant is the entry's
`expected_moment`. A missing top citation, a top citation that cannot resolve
to one planted item, or a top citation resolving to a plant other than
`expected_moment` is a hard failure; none is silently dropped from the result
population.

For a top citation resolving to its expected planted item:

```
planted_at_ms    = planted.*.at as milliseconds from recording start
start_ms, end_ms = the cited moment's span

nearest_ms = min(max(planted_at_ms, start_ms), end_ms)
nearest_edge_delta_ms = nearest_ms - planted_at_ms

assert abs(nearest_edge_delta_ms) ≤ 15_000
```

- `planted_at_ms` — the manifest's scripted timestamp: `planted.*.at`
  (`HH:MM:SS`, wall time from meeting start), converted to milliseconds from
  recording start. **Conversion assumption:** this equates recording start
  with meeting start — the same assumption manifest authoring makes when it
  writes `at` from the script. A recording that starts late shifts *every*
  delta by the same amount, and the duration-agreement precondition does not
  bound that shift (two equal durations can still disagree on their origin).
  Implementing this check must treat a systematic same-direction bias across
  all of one meeting's plants as its own named problem — an origin offset to
  report as such, not N independent window misses.
- `start_ms`/`end_ms` — the cited moment's span. A moment row carries both as
  integer milliseconds from recording start (the project-wide convention,
  `moment` table, migration 0006), and the api's citation arrays are built
  from those rows (AD-6: the moment id is the citation currency).
- `nearest_edge_delta_ms` is signed: negative means the cited span ends before
  the plant, positive means the cited span starts after it, and zero means the
  plant lies inside the span. The window is **±15 000 ms**, symmetric.
  Provisional per eval-design §6:
  a change is recorded in the run's `verdict.md` and invalidates prior
  verdicts.
- **The nearest-edge distance deliberately refines eval-design §2.5**, whose
  sentence reads as point distance (`|cited timestamp − scripted at| ≤ 15s`).
  Moments are cut at transcript/screenshot boundaries, not at plants, so a
  plant routinely falls *inside* the cited moment's span — and a moment that
  contains the scripted instant is exactly right, which a point-to-start
  distance would fail on the size of the span. The refinement is lenient in
  one direction only (it never fails a citation the point form would pass),
  it is stated here rather than left implicit in code, and it is provisional
  under §6 like the window itself. §2.5 stays the contract of record for what
  the check is for.

Per-Q&A result records `qa_id`, `expected_moment`, top-citation identifier,
`state` (`within_window`, `outside_window`, `no_citation`,
`wrong_citation`, `ambiguous_citation`, `missing_span`, `malformed_span`,
`reversed_span`, or `out_of_recording_span`), and `nearest_edge_delta_ms` only
for the two window states. Every span state other than the window states is a
hard failure. This gives every Q&A item one deterministic result.

## Data sources

- **Ground truth:** the manifest's `planted.action_items[].at`,
  `planted.decisions[].at`, `planted.phrases[].at`
  (`evals/ground-truth.schema.json`), and `qa[].expected_moment` naming the
  planted item a question's top citation must resolve to.
- **System under test:** the structured citation array the api returns for a
  Q&A answer, read through the public api per AD-16 (the harness is a client,
  never a housemate) — each citation resolving to a moment whose
  `start_ms`/`end_ms` the api reports. The harness performs no direct store
  read for this check beyond its existing read-only corpus connection.

## Failure modes

| Failure | What it means | Triage class |
|---------|---------------|--------------|
| `outside_window` | Retrieval found the expected item but cites a mis-cut or neighboring moment | pipeline bug (moment segmentation or citation building) |
| `wrong_citation` | The top citation resolves unambiguously to a planted item other than `expected_moment` | pipeline bug (retrieval ranking), unless the manifest expectation is wrong |
| `ambiguous_citation` | The top citation cannot be joined uniquely to one planted item | join/moment-cutting defect; hard fail, never a guessed match |
| `no_citation` | Automatic fail per the SPEC's core constraint (every claim cites) — rubric §2.7(b) territory, not a window miss | pipeline bug (citation gate) |
| `missing_span` | The citation names a moment but exposes no `start_ms`/`end_ms` span | API/citation contract defect; hard fail |
| `malformed_span` | Either span endpoint is not an integer millisecond offset | API/citation contract defect; hard fail |
| `reversed_span` | `end_ms < start_ms` | moment data defect; hard fail |
| `out_of_recording_span` | Either endpoint is outside `[0, recording_duration_ms]` | moment data or recording-identity defect; hard fail |
| Scripted `at` outside the probed recording length | The manifest describes a different meeting; the duration-agreement precondition should have caught it first | ground-truth script error |

## What implementing requires

1. **The planted-item↔citation join** — the missing piece and the reason this
   is a design rather than a check. The manifest knows a plant's id and `at`;
   a citation knows a moment id and span. Joining them needs a deterministic
   mapping from planted item to moment. Two workable routes, in preference
   order:
   - *Via `qa.expected_moment`:* for Q&A citations, the manifest already names
     the planted item the top citation must resolve to, so the join is
     "the moment whose span contains (or is nearest to) `planted.*.at` for
     that item" — computable from the manifest and the moment table alone.
   - *Via verbatim text:* `planted.phrases` are spoken verbatim, so the
     containing moment is findable by transcript-segment text match, the same
     normalization conventions as `normalize_anchor`.

   Either route needs a **deterministic tiebreak**, because a plant can sit
   exactly on a boundary two moments share, and screen-derived and
   transcript-derived moments can overlap: containment wins and is asserted
   unique among moments of the same `derived_from`; on a containment tie, or
   between equally-near non-containing moments, the earliest `start_ms` wins;
   any tie that rule cannot break is recorded as `ambiguous_citation` rather
   than resolved silently — an ambiguous join is a finding about moment
   cutting, not a coin to flip.
2. **A Q&A driver:** something that issues each manifest `qa.question` through
   the public api and captures the structured answer + citations — this does
   not exist in the harness today and is shared with the §2.8/§2.9 designs
   (see `retrieval-eval.md`).
3. **Report plumbing:** a new check module under `evals/checks/` following the
   shipped `CheckResult` shape, thresholds written into the report beside the
   results per §6.

## Why deferred

The check is deterministic and cheap once the join and the Q&A driver exist,
but both sit on the retrieval surface story 5.3 builds and the capstone scope
line draws the boundary at documenting retrieval evals rather than building
them. eval-design §2.5 also names its capstone stand-in explicitly: the human
judge, via the runbook worksheet.
