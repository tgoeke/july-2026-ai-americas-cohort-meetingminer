# Design: Action-Item Fuzzy Set-Match (check 2.6)

**Status: documented only — not implemented.** Deferred per
`docs/architecture.md` ("design everything, build the
slice"). The contract of record is `eval-design.md` §2.6; this file expands
that sketch to an implementable design. Until it is built, the
`action-item-matches` worksheet in `evals/RUNBOOK.md` step 5 covers it: the
human compares the app's extracted action items against
`planted.action_items` by hand.

## What it checks

That extraction found every planted action item, invented none, and — because
extraction paraphrases — that "found" tolerates rewording without tolerating a
different item.

## Algorithm

A set-match between two sets of normalized strings:

- **Expected set** — `planted.action_items[].text` from the manifest. The
  authoring validator rejects duplicate normalized expected texts; otherwise
  one expected task could manufacture an ambiguous denominator.
- **Extracted multiset** — the action items the pipeline extracted for the
  meeting, read through the public api (AD-16). Equal normalized values remain
  distinct records, keyed by their stable API item ids; unassigned duplicates
  are separate `extra` results rather than silently coalesced.

Procedure:

1. **Normalize both sides** with the shipped folding —
   `evals/harness/groundtruth.normalize_anchor` (lowercase, strip `[^\w\s]`,
   collapse whitespace). One folding across the whole harness, for the same
   reason check 2.1's matching shares it with story 5.1's authoring-time
   uniqueness rules: two conventions would let authoring accept what matching
   cannot see.
2. **Score every expected×extracted pair** with normalized-text similarity.
   Following the shipped convention (eval-design §2.4a: stdlib `difflib`, not
   rapidfuzz), similarity is `difflib.SequenceMatcher.ratio()` over the two
   folded strings — the same comparison check 2.4 uses for dedup candidates.
   Token-containment (`evals/harness/checks.token_containment`) is the wrong
   tool here: it is asymmetric and anchor-oriented, while two action-item
   texts are peers.
3. **Build the threshold-qualified bipartite graph**, with an edge for every
   expected×extracted pair scoring at least 0.75, then choose a one-to-one
   matching in this order: maximum cardinality first; among those, maximum
   total similarity; among equal-score matchings, the lexicographically least
   sequence of `(expected manifest id, extracted stable API id)` pairs. This is a
   deterministic maximum-weight maximum-cardinality matching, not a greedy
   walk: it cannot consume the only qualifying extracted item for a later
   expected item when a lower-score pairing would find both. Unlike check 2.1
   — where independent matching deliberately exposes a double-assigned
   capture — one-to-one assignment is correct here: two planted items are
   distinct tasks by construction, and one extracted item must not satisfy
   both.
4. **Classify** into three buckets:
   - `found` — assigned pairs at similarity ≥ **0.75**;
   - `missing` — expected items left unassigned;
   - `extra` — extracted items left unassigned.

Threshold **0.75** per eval-design §6 (provisional; a change is recorded in
the run's `verdict.md` and invalidates prior verdicts). It sits deliberately
below 2.1's 0.8: extraction paraphrases where OCR only misreads characters.

## Escalation (eval-design §3)

- **Exact matches** (similarity 1.0 after folding) are settled
  deterministically; nobody reviews them.
- **Non-exact `found` pairs, and every `missing`/`extra` item, escalate to the
  LLM judge** (story 5.4, when built) to score semantic equivalence: is
  "Update the tax table mapping by Friday" the same task as "Tim to fix the
  tax mapping table before end of week"? Judge scores are advisory.
- **The human judge is final**, via the `action-item-matches` worksheet;
  verdicts land per item in `human-verdicts.yaml` with a one-line reason, and
  the human verdict wins any disagreement with the deterministic bucket or the
  judge score.

## Data sources

- **Ground truth:** `planted.action_items` in the manifest — `id`, `text`,
  `speaker`, `at` (`evals/ground-truth.schema.json`).
- **System under test:** the extracted action items for the subject meeting,
  read through the public api. Speaker and timestamp are *not* part of the
  set-match — they are what the citation checks (2.5) and rubric §2.7 assert —
  so this check cannot fail an item that was extracted correctly but
  attributed wrongly; that failure belongs to the check that owns attribution.

## Failure modes

| Failure | What it means | Triage class |
|---------|---------------|--------------|
| `missing` item, human confirms | Extraction never surfaced a planted task | genuine miss (extraction quality) |
| `extra` item, human confirms | Extraction invented or split a task | pipeline bug (extraction quality) |
| Non-exact pair ruled non-equivalent by the human | The 0.75 threshold matched two different tasks | recalibration candidate for §6 — record in `verdict.md` |
| Planted text unrecognizable in the transcript | The script was not followed when recorded | ground-truth script error |

## What implementing requires

1. An api read of the extracted action items for a meeting (exists once the
   extraction surface ships; the harness side is a client call plus row
   shaping, as `subjects.fetch_meetings` does for `GET /meetings`).
2. A new check module under `evals/checks/` returning the shipped
   `CheckResult` shape — thresholds in the report beside the results,
   `found`/`missing`/`extra` in `detail`, one `problems` line per
   `missing`/`extra`.
3. The escalation hand-off: non-exact pairs written into the report in a form
   the LLM-judge step (story 5.4) and the human worksheet can consume without
   recomputing the assignment.
4. An authoring guard beside story 5.1's loader rules: **reject duplicate
   normalized `planted.action_items` texts and reject (or at least flag) two
   whose folded texts score at or above the 0.75 match threshold.** Under
   one-to-one assignment, two near-identical planted tasks guarantee that one
   reads as `missing` even when extraction found both — a false miss
   manufactured by the ground truth. This is the action-item analogue of the
   near-identical-anchor risk `evals/README.md` documents for check 2.1, but
   here the guard is cheap and threshold-derived rather than guessed, so it
   belongs at authoring time.

## Why deferred

The deterministic half is small, but on its own it can only bucket — the
check's verdict is genuinely three-tiered (deterministic → LLM judge → human),
and the middle tier is story 5.4, itself a nice-to-have. Building the bucketer
ahead of the surfaces it feeds would ship a number nobody can act on, so the
whole check is documented and the human worksheet carries it for the capstone.
