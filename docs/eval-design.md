# Eval Design

Companion to `SPEC.md` (CAP-7, CAP-8). Operationalizes `eval-strategy.md`: ground-truth schema, per-check algorithms, judging procedures, and the eval runbook. Covers the DOCUMENT-only items too, so the design is complete even where the capstone doesn't implement.

## 1. Ground-truth script schema (YAML)

One file per scripted meeting under `evals/ground-truth/`. Everything the pipeline should detect is declared up front.

```yaml
meeting:
  id: demo-001
  title: "Scripted UI Demo — Orders Module"
  archetype: ui-demo          # ui-demo | slide-deck
  duration_minutes: 12
  participants:
    - name: Tim Goeke
      role: presenter

slides:                        # slide-deck archetype: full manifest (deck shows ALL slides)
  - id: S1
    title: "Q3 Architecture Review"
    ocr_anchor: "Q3 Architecture Review"   # distinctive on-screen text a capture must contain

screens:                       # ui-demo archetype
  - id: SC1
    name: "Order List"
    shown_at: "00:01:30"
    ocr_anchor: "Order Search Results"

participant_segments:          # expected captures beyond slides/screens
  - at: "00:00:00"             # meeting start
  - at: "00:08:10"             # sharing stops

planted:
  action_items:
    - id: AI1
      text: "Update the tax table mapping by Friday"
      speaker: Tim Goeke
      at: "00:04:12"
  decisions:
    - id: D1
      text: "Orders module keeps optimistic locking"
      speaker: Tim Goeke
      at: "00:06:02"
  phrases:                     # planted verbatim phrases for transcript/timestamp checks
    - id: P1
      text: "purple elephant deployment window"
      speaker: Tim Goeke
      at: "00:03:20"

qa:                            # questions the corpus must answer with citations
  - id: Q1
    question: "What did Tim decide about locking in the Orders module?"
    expected_moment: D1
    answer_must_contain: ["optimistic locking"]
```

Expected screenshot count per meeting = slides (or screens) + participant_segments — the manifest is the recall denominator.

**Authoring rule (resolved 2026-08-17):** every slide and screen entry MUST carry a unique, distinctive `ocr_anchor` — plant one on the slide/screen if it doesn't occur naturally. Ground truth is by construction, so this rule makes OCR-anchor matching sufficient for the lab corpus; image-based matching (perceptual hashing) is product-later for unscripted recordings.

**Schema note (added 2026-08-19, story 5.1).** The example above predates the machine-readable schema at `evals/ground-truth.schema.json`, and differs from it in the ways below. Follow the schema; it is what validation enforces.

- The example is **illustrative of both archetypes at once**. It declares `slides:` and `screens:` in one file, which no single manifest may do: `meeting.archetype` selects exactly one of them and declaring the other fails validation. A `ui-demo` file carries `screens:` only; a `slide-deck` file carries `slides:` only.
- `meeting.source_id` is **required** and does not appear above. It holds the ingested drop's `sourceId` (`docs/source-drop.schema.json`) and is how a manifest is matched to a meeting — `meeting.id` stays the manifest's own human-facing label. The `sourceId` is not knowable until the scripted meeting is recorded and pulled, so a manifest ships with a placeholder and the subject selector reports it as unmatched until the real id replaces it.
- Two smaller shape rules the example leaves implicit: `shown_at` is required on every `screens` entry (checks 2.3 and 2.5 need entry timing; a deck is shown front to back, so `slides` may omit it), and every `participant_segments` entry needs a distinct `at` — one moment is one expected capture, so a repeated timestamp inflates the recall denominator and puts 100% out of reach.

Everything else in §1 stands unchanged, including the expected-screenshot-count formula and the authoring rule above it.

## 2. Checks

Each check states: tier, algorithm, threshold, capstone status (BUILD / DOCUMENT).

### 2.1 Capture recall — primary metric (BUILD)
- **Tier:** deterministic, then human judge over failures.
- **Algorithm:** OCR every captured PNG; normalize text (lowercase, collapse whitespace, strip punctuation); a capture matches a manifest entry when its OCR text contains the entry's `ocr_anchor` (fuzzy token-set match ≥ 0.8 to tolerate OCR noise). Recall = matched manifest entries / total manifest entries.
- **Threshold:** 1.0 (100%). Any miss fails the run.
- **Independence (required):** the manifest is authored from the meeting script, never from the extractor's output. A denominator derived from what the extractor emitted cannot contain a screen it missed, so it reports 100% while measuring nothing.
- **Resolved (2026-08-17):** anchor matching is sufficient under the §1 authoring rule (unique distinctive anchor per slide/screen). OCR engine: Apple Vision framework primary (macOS demo machine), Tesseract as portable fallback, both behind the same swappable interface. Image hashing: product-later.

### 2.2 Over-capture guardrail (BUILD)
- **Tier:** deterministic only.
- **Algorithm:** count distinct captures; fail if count > ceil(`duration_minutes`) — one slide-or-screen per minute of meeting.
- **Measured headroom (2026-08-18):** a tuned extractor produced 0.86 captures/min on a real 61-minute recording — 14% under the line. The shipped story 1.4 path produced 188 captures on a 57-minute meeting = 3.3/min, failing by 3.3x. See `capture-measurements.md` §5.

### 2.3 View classification (BUILD, first pass)
- **Tier:** deterministic against script labels.
- **Algorithm:** every capture's classified view (slide | ui-screen | participant/gallery) compared to the label implied by the manifest section it matched; report accuracy. Classification accuracy is itself a tracked metric.

### 2.4 Dedup quality (BUILD)
- **Tier:** deterministic candidate detection + human judge.
- **Algorithm:** OCR text similarity on sequential captures; pairs above 0.9 similarity are duplicate candidates; human judge rules keep/collapse. Bias per SPEC constraint: prefer over-capture to loss.

### 2.4a Implementation notes on checks 2.1-2.4 (added 2026-08-19, story 5.2)

Its own subsection rather than a trailing paragraph under §2.4: the notes below
concern §2.1 and §2.2, and a reader skimming a frozen contract would otherwise
take them for part of the dedup check. **§2.2-§2.4 stand unchanged, and so do
§2.1's recall formula, its 1.0 threshold and its independence rule.** §2.1's
algorithm line is amended on one point below — where the OCR text comes from.
Three decisions were made when the checks were built, and are recorded here so
a later reader does not have to recover them from code:

- **§2.1's "OCR every captured PNG" is not what the check does, and must not
  be.** The haystack is the pipeline's own stored OCR: for each `screenshot`
  row, the `frame_ocr` text of the frame the `screens` stage chose as
  representative, read by a LEFT JOIN so a capture with no text still arrives
  and still counts. The harness runs no OCR of its own. This does not weaken
  §2.1's independence rule, which binds the *denominator* — the manifest stays
  authored from the meeting script, and a screen that was never captured has
  no row and no text no matter which engine reads it, so every failure
  direction of a shared engine fails the run. What it trades away is a capture
  legible to some second engine but not to the configured one; that is a real
  finding about the configured engine rather than a harness defect, which is
  why the engine is part of every run's recorded config snapshot. A harness
  re-OCR would instead measure a second engine the product does not ship, and
  could report recall the shipped pipeline cannot reproduce.
- **"fuzzy token-set match ≥ 0.8" (§2.1) is stdlib `difflib`, not rapidfuzz.**
  §2.1 names no implementation and rapidfuzz is not a dependency of this
  project. The comparison is: fold both the anchor and the OCR text with the
  authoring-time normalization (`evals/harness/groundtruth.normalize_anchor`);
  an anchor token counts as *present* when some OCR token scores ≥ **0.85**
  against it under `difflib.SequenceMatcher`, which is the character-level
  tolerance for OCR noise; the entry's score is present anchor tokens / total
  anchor tokens; the entry matches at ≥ 0.8. Both numbers are provisional under
  §6 and both are written into every run's report beside the result they
  produced. The rejected alternative — adding rapidfuzz for `token_set_ratio` —
  buys a well-known implementation at the cost of a dependency whose exact
  semantics would then be the undocumented contract of a check §6 says will be
  recalibrated anyway.
- **"count distinct captures" (§2.2) means `screenshot` rows for the meeting.**
  §2.2 says "distinct" without saying distinct by what. It is one row per
  capture: a capture the pipeline emitted twice is two rows and counts twice,
  and a capture whose OCR could not be read still counts — dropping it would
  shrink the guardrail's numerator at exactly the moment a run is broken.

One consequence of the §1 formula worth stating, because §2.1's "matched
manifest entries" reads as anchors alone: the recall denominator is slides (or
screens) **plus participant segments**, and segments carry no `ocr_anchor`. A
segment is matched by a `participant-gallery` capture, one apiece in ordinal
order. Dropping segments from the denominator instead would make a missing
gallery capture unnoticeable, which the §1 formula exists to prevent.

### 2.5 Citation timestamp window (DOCUMENT)
- **Tier:** deterministic (documented); human judge stands in for the capstone.
- **Algorithm:** for every citation resolving to a planted item, assert |cited timestamp − scripted `at`| ≤ 15s.

### 2.6 Action-item extraction (DOCUMENT the fuzzy match; LLM + human judge for capstone)
- **Algorithm:** fuzzy set-match extracted items against `planted.action_items` (normalized-text similarity ≥ 0.75) → found / missing / extra. LLM judge scores semantic equivalence on non-exact matches; human judge is final.

### 2.7 ADR/decision extraction and cited Q&A quality (BUILD nice-to-have: LLM judge harness)
- **Tier:** LLM judge + human judge.
- **Rubric (LLM judge, per answer/artifact):** (a) faithful to the cited moment's transcript, (b) citation present — no citation is an automatic fail per the SPEC's core constraint, (c) `answer_must_contain` terms present, (d) nothing asserted beyond evidence. Judge model runs behind the standard adapter interface.

### 2.8 Retrieval right-moment-cited (DOCUMENT)
- Human judge for the capstone: for each `qa` entry, does the top citation resolve to `expected_moment`? The documented deterministic replacement is the timestamp-window check (2.5).

### 2.9 Retrieval eval design (DOCUMENT only — full designs promised to instructors)
- Topic/mention search: recall@k against planted phrases and topics (does the meeting containing the plant appear in the top k?). The doc-index slice of this is promoted to BUILD as check 2.10.
- Graph traversal: the participants → meetings → topics → moments query (Clarence demo) has a fully known expected result set from the scripts; exact-set comparison.
- Cited Q&A: rubric 2.7 plus right-moment-cited 2.8.

### 2.10 Doc-index search recall (BUILD — CAP-9)
- **Tier:** deterministic only.
- **Algorithm:** for each `planted.phrases` entry, query the full-text document index; pass if a moment from the containing meeting appears in the top k results. k = 5, provisional per §6.
- **Threshold:** recall@5 = 1.0 on planted phrases (they are verbatim plants; the index has no excuse).

### 2.11 Publish-gate projection (BUILD — CAP-9)
- **Tier:** deterministic only.
- **Algorithm:** for a scripted artifact, assert before approval that it appears in NEITHER retrieval store (doc index, graph); approve it; assert it appears in BOTH, with citations resolving to its source moment. Any violation fails the run — this check defends the SPEC's publish-gate constraint.

### 2.11a Implementation notes on checks 2.10-2.11 (added 2026-08-21, story 5.3)

Additive, same discipline as §2.4a and §7.1: §2.10's algorithm and threshold
and §2.11's sequence stand unchanged; the decisions the build made precise are
recorded here so a later reader does not have to recover them from code.

- **§2.10's "query the full-text document index" is asserted through the
  public `GET /search`, never a raw Meilisearch query.**
  `evals/designs/retrieval-eval.md` leg 1 says "through the public api
  (AD-16)" explicitly, and the surface users hit is what the promise is
  about — a raw index query could pass while the route is broken. Queries are
  **unfiltered** (no `corpus`, no `meetingId` parameter, `limit=5`): the
  index gets no help. A degraded `ranking: "keyword"` response (embedder
  down) is recorded per phrase, not failed — verbatim plants must survive
  keyword ranking, and failing on embedder downtime would misattribute the
  miss. `indexMissing: true` is its own blocking failure naming the missing
  index, distinct from "the plant was outranked".
- **§2.11's "before approval" means every non-`published` row.** The
  lifecycle is `extracted → approved → published` (AD-4/AD-5), and the gate
  admits only the final state, so `approved` rows are held to the absence
  assert exactly like `extracted` ones.
- **§2.11's store membership is a direct read-only store read, by necessity
  and by license.** AD-4 makes unpublished artifacts visible *only* through
  Postgres api reads — absence from the retrieval stores has no api surface,
  and `/search` deliberately excludes the `artifacts` index — so "appears in
  NEITHER store" cannot be an api read. AD-16 sanctions "read-only store
  queries" for exactly this; `evals/harness/stores.py` is that sanction's
  whole footprint (one module, pinned read-only by boundary test, Neo4j
  session opened `default_access_mode=READ`). Where
  `retrieval-eval.md`'s looser sentence ("api-visible behavior plus the
  corpus connection") cannot implement this section's literal store assert,
  this section — the contract of record — wins.
- **"citations resolving to its source moment" means:** the projected
  Meilisearch document's `momentIds` contains the artifact's `moment_id`
  (`projections/publish_gate.py`'s `artifact_document` shape), and in the
  graph some node whose `id` property equals the artifact UUID relates to
  the `Moment` node with that id. The graph match is deliberately
  label-agnostic — story 4-4's label choice cannot quietly evade the assert.
- **The positive half's assert set is every artifact `published` after the
  approval call** — the rows this run's approval advanced plus any row
  already `published` before it. §2.11's "assert it appears in BOTH" binds
  the published *state*, not the transition this run happened to drive, so a
  previously published row missing from a store is the same defect as a
  newly published one missing.
- **The check consumes state.** Approval is one-way with no unpublish, so a
  run that approves leaves the next run with nothing `extracted`: the gate
  half then records a blocking not-applicable naming the state distribution.
  Inherent to verifying a one-way gate against a shared corpus; documented in
  `evals/RUNBOOK.md` rather than papered over with a store write the harness
  must never make. And until story 4-4 wires projection-on-publish, the
  post-approval presence half FAILS against real subjects — that failure is
  the check defending the gate, never to be weakened or greened.

## 3. Judging tiers and escalation

1. **Deterministic asserts** always run first; their report is the input to everything downstream.
2. **LLM judge** (if harness is built) scores what determinism can't decide; scores are advisory. The judge model is selected by the bake-off (§7) and pinned.
3. **Human judge** is the final arbiter over both, operated via the runbook below. Disagreement resolution: human verdict wins and is recorded with a one-line reason.

Thesis parallel holds: deterministic core, probabilistic contributors, humans approve.

## 4. Eval runbook (CAP-8)

The operator procedure for one full eval run. Success test: an operator without tribal knowledge completes a run using only this section.

**Operationalization note (added 2026-08-20, story 5.5).** This section is operationalized at `evals/RUNBOOK.md` — the self-contained operator procedure, with every command, artifact format (`human-verdicts.yaml`, `verdict.md`), refusal behavior and worksheet stated in full against the shipped story-5.1/5.2 harness. The DOCUMENT-only sketches are expanded into full standalone designs under `evals/designs/`: §2.5 at `citation-timestamp-window.md`, §2.6 at `action-item-fuzzy-match.md`, §2.8/§2.9 at `retrieval-eval.md`, and §5 at `eval-cadence.md`. This section and those sections remain the contract of record and their text here is unchanged; the runbook and designs cite back here, and where a design sharpens a sketch it says so explicitly in its own text (e.g. `citation-timestamp-window.md` measures §2.5's window to the nearest edge of the cited moment's span, stated and justified there, provisional under §6).

**Preconditions**
1. Ground-truth YAML files exist under `evals/ground-truth/` and validate against the schema (§1).
2. Every scripted meeting is ingested; ingestion completed (bundles precomputed).
3. Run folder created: `evals/runs/<run-id>/` (run-id = date + short label).

**Procedure**
1. **Deterministic suite.** Run all BUILD checks (2.1–2.4) against every scripted meeting. Write `deterministic-report.yaml` (per-check pass/fail, per-manifest-entry match detail) into the run folder.
2. **Triage failures.** For each deterministic failure classify: pipeline bug | ground-truth script error | genuine capture miss. Script errors are fixed in the YAML and noted; the suite reruns. Pipeline bugs and misses stay in the report.
3. **LLM judge** (if harness built). Score extraction and Q&A per rubric 2.7; write `llm-judge-report.yaml`, recording the exact judge model id and version in the run metadata.
4. **Human judging.** Walk the human-judged checks (capture-recall failures, dedup candidates, action-item non-exact matches, ADR/decision quality, Q&A right-moment-cited) using one worksheet per check; record verdict + one-line reason per item in `human-verdicts.yaml`.
5. **Final verdict.** Run passes only if: capture recall = 100%, over-capture guardrail holds, and no human verdict is a fail. Record PASS/FAIL with summary in `verdict.md`.
6. **Archive.** The run folder is immutable after verdict; nothing is edited retroactively.
7. **Rerun rule.** Any pipeline change — or a judge-model change — after a run invalidates its verdict; rerun from step 1 in a new run folder.

## 5. Cadence

- **Capstone (implemented):** ONE full run before the demo, after the eval harness is complete and before demo-script work begins (sequencing rule). The judge bake-off (§7) runs before that full run so the winning judge is pinned going in.
- **Documented only:** change-triggered runs on any prompt or screenshot-algorithm change; a full go-to-production gate run before any delivery.

## 6. Threshold policy and open decisions

**Thresholds are provisional baselines** (accepted 2026-08-16): anchor match ≥ 0.8, dedup candidate ≥ 0.9, action-item fuzzy match ≥ 0.75, doc-index recall@k with k = 5 (accepted 2026-08-17). They are expected to be recalibrated against observed results during eval runs; any change is recorded in the run's `verdict.md` and invalidates prior verdicts per the rerun rule (§4.7).

**Formerly open, resolved 2026-08-17:**

- OCR engine → Apple Vision framework primary, Tesseract portable fallback (§2.1).
- PNG-to-slide matching → unique-anchor authoring rule (§1); image hashing product-later.
- LLM judge model → selected by bake-off (§7), then pinned.

## 7. Judge bake-off

Selects the LLM judge empirically instead of by fiat. Runs once, before the first full eval run (§5).

- **Candidates**, three pools, all behind the standard adapter interface (configuration, not code):
  1. Frontier API models — Anthropic and OpenAI, via the endpoint allowlist.
  2. Local models via Ollama on the dev machine (M4 Max, 128 GB unified RAM — large open-weight models run comfortably).
  3. Hosted open-weight frontier models (e.g. Kimi and peers), also allowlisted.
- **Egress rule:** cloud candidates receive derived data only (transcript snippets, extracted artifacts) — never recordings — per the SPEC's locality constraint.
- **Method:** every candidate judges the same sample of scripted-corpus extraction and Q&A outputs using rubric 2.7, blind to each other. A human judges the same sample first; the human verdicts are gold.
- **Grading:** primary score is agreement with human verdicts. Ties break on verdict consistency across repeated runs, then cost/locality (local preferred at equal quality).
- **Outcome:** the winner is pinned by exact model id and version, recorded in every run's metadata (§4.3); changing it later triggers the rerun rule (§4.7). Bake-off results land in `evals/runs/bakeoff-<date>/` under the same immutability rule.

### 7.1 Implementation notes on §2.7 and §7 (added 2026-08-20, story 5.4)

Additive, same discipline as §2.4a: §2.7's rubric and §7's bake-off contract stand unchanged; three decisions the build made precise are recorded here.

- **The judge JSON schema.** A judge model answers exactly two of rubric 2.7's four criteria — `faithful` and `no_unsupported_claims` — as `{"faithful": bool, "no_unsupported_claims": bool, "reason": str}`. One retry on an unparsable reply, with a stricter prompt naming the bad reply; a second unparsable reply is recorded not-applicable, naming the raw reply, and `passed` is `false` — never a crash, never a silent pass.
- **The mechanical-vs-LLM split.** `citation_present` and `contains_required_terms` (rubric 2.7(b)/(c)) are computed, not judged: `citation_present` is a citations array non-empty for a `qa` answer, or mechanically `true` for an extracted artifact (an `artifact` row cannot exist without its `moment_id` FK, `0009_artifacts.sql`); `contains_required_terms` is a normalized substring match of every `qa.answer_must_contain` term against the candidate text, vacuously `true` when there are none (an artifact carries no required-terms field). `passed` is the conjunction of all four. An uncited `qa` answer skips the judge call entirely — `citation_present=false` already forces `passed=false`, so nothing the model says can change the verdict, and no call is worth its cost.
- **The bake-off tie-break order.** Primary score is agreement with the sample's human gold verdicts. Pool order (`local-ollama`, `hosted-open-weight`, `frontier-api` — cost/locality, §7's own preference) is consulted strictly *after* `--repeats`-based consistency (fraction of items scored identically across repeats), never as a standalone substitute for it: when `--repeats > 1`, a tie breaks by consistency first, then by pool order if it still ties; at `--repeats == 1` there is no consistency signal at all, so the tie is never broken by pool order either — `winner` is written `null` and the tied candidates are named immediately. A tie that survives both consistency and pool order (same pool, same consistency) is likewise never broken arbitrarily. Every per-candidate `Llm` is built with `fallback: null` regardless of what `bakeoff-candidates.yaml` declares, so a substitution can never attribute a reply to the wrong exact model id.
