# Project record

What each epic delivered, the decisions a contributor must know before changing
it, and what was deliberately left undone. This replaces the per-story planning
files: those recorded how the work was dispatched, which stops mattering once it
has landed. What survives here is what constrains the next change.

Read [`architecture.md`](architecture.md) first — the decision ids referenced
below (AD-1 … AD-17) are defined there.

---

## Epic 1 — A recording becomes a precomputed evidence bundle

**Delivered**

- A one-command dev environment. Compose runs the three stores; api, worker, and
  the dev server run as host processes with pidfile lifecycle, polled readiness,
  and a migration gate. The generated TypeScript client is committed on purpose
  so a fresh clone builds without a live api.
- A single intake door that validates a drop against the versioned schema,
  inserts one job row plus eight pre-seeded stage checkpoints, and answers every
  error as `problem+json`.
- A restartable worker: claim with `FOR UPDATE SKIP LOCKED`, mint exactly one
  meeting, walk the eight stages, skip the video-only stages for transcript-only
  drops, and *pause* at the first unregistered stage rather than faking
  completion.
- The evidence stages: media probing and frame sampling; OCR behind an adapter
  port feeding screen segmentation with cross-meeting screen lineage, view
  classification, and screenshot capture; speech recognition reconciled against
  any provided transcript into derived speaker-attributed segments; and
  `moments`, the addressable citation unit joining transcript spans to
  screenshots.
- `projections` as the sole store writer, in a structural pass plus a separable
  embedding pass, with a `rebuild` CLI that regenerates both stores from
  Postgres and config alone.
- A drop-emitting acquisition seam that shares no server code, plus a schema-v2
  `augments` declaration letting late-arriving evidence re-arm an existing job.

**Know before you change it**

- `evidence_complete` is the readiness predicate, not `job.status = 'done'`.
  Because `extract` was unregistered until Epic 4, no job reached `done`; every
  consumer uses one shared predicate — all stages through `moments` settled.
- Stage semantics are resume, not restart. Settled stages are never re-executed;
  orphaned running jobs are requeued *without* resetting checkpoints.
- Moments are the one exception to delete-and-rewrite: a moment id is citation
  currency, so `moments` upserts and supersedes rather than deletes. Boundaries
  are the union of transcript-derived and screenshot-derived sets computed
  independently, so transcript boundaries — and therefore ids — are identical
  before and after a recording arrives.
- Speaker attribution never guesses. A label resolves only inside a meeting's
  roster; matching nothing is `unresolved`, matching several is `ambiguous`, a
  numbered placeholder is `placeholder`. None is ever merged into a resolved
  person.

**Left undone, deliberately**

No folder watcher, no broker, no scheduler, no auth, one worker on one machine —
the design leans on that instead of leases and heartbeats. Capture density
exceeds the over-capture guardrail on real meetings; the bias toward
over-capture was chosen and the tuning deferred to the eval corpus. A stage
rerun does not invalidate downstream checkpoints, reachable only by deliberate
operator action. Screen identity records nothing about which OCR engine produced
its signature, so engaging the fallback forks lineage.

---

## Epic 2 — The bundle becomes explorable and replayable

**Delivered**

- A read-only media surface: path-addressed streaming of content-root files and
  id-addressed streaming of a meeting's recording, both Range-correct, plus a
  player that opens at a given offset.
- Evidence path anchoring to two configured roots, a checksum and byte-size row
  for the recording, a backfill for legacy absolute paths, and database CHECKs
  that no stored path is absolute or contains a parent-directory segment.
- A mint command turning a local video into a schema-valid, atomically finalized
  drop keyed by content hash — one ingestion path, no tool-specific branch at
  intake.
- Moment view and meeting drill-down: screenshot series in stored ordinal order,
  full transcript with per-segment moment links, one inline replay at a time, a
  right rail typed for artifacts, and a degraded transcript-only mode.
- Human curation write paths — participant rename and merge, and series /
  project / product assignment — projected into the graph at the next rebuild.
- Two platform changes that removed chokepoints: per-run databases guarded by
  advisory locks plus a bounded cross-worktree lock for the shared stores; and
  auto-discovered route registration on both server and web, so adding an
  endpoint or a screen is adding a file rather than editing a shared block.

**Know before you change it**

- The viewability gate distinguishes "never ingested" (404) from "augmentation
  in flight" (409 with a named slug), derived from a pure predicate: an
  augmentation is in flight iff a settled stage follows an unsettled earlier one
  in canonical order. Both routes share the predicate the projection trigger
  uses, so they cannot disagree.
- Superseded moments are hidden from lists but still served in detail, flagged.
  Their ids are citations and must keep resolving.
- The moment-to-segment join is a table, never a timestamp `BETWEEN` — a covered
  segment may legitimately end after its moment does.
- Path containment is a guard, not a string check: resolve, assert relative to
  root, reject symlinked components. No absolute path appears in any response.
- The recording is served from its drop, never copied. Copying would buy a
  fraction of the relocation guarantee for a permanent multi-gigabyte duplicate
  per meeting.
- The web home view is hidden, never unmounted. The verify-a-claim loop is
  search → moment → back → next hit; a route swap would blank the query and
  results on every Back.

**Left undone, deliberately**

No pagination or size cap on the read surface. No media caching validators. Merge
has no confirmation and no unmerge, and there is no duplicate-detection endpoint —
grouping is a client-side hint. No delete endpoints for structure entities;
orphans linger until a rebuild. No auth anywhere: the api is unauthenticated
loopback, and no scheme was invented mid-epic.

---

## Epic 3 — Search, and answers that cannot be uncited

**Delivered**

- Search over the moments index — typo-tolerant keyword blended with a vector
  lane, spanning transcript text, speakers, title, and screenshot OCR text, with
  highlights travelling as structured runs rather than markup.
- Two hand-written parameterized Cypher templates behind a named registry:
  screen history across meetings, and participant-topic moments.
- A chat route where a model classifies the question onto a template and/or
  search terms, deterministic code resolves anchors to database ids, the model
  synthesizes with citation markers, and a store-free validator either produces
  a citation array or rejects the whole answer.
- Server-sent replay of an already-validated answer, and a web chat panel with
  citation buttons and an explicit "no citable answer" state distinct from a
  transport failure.

**Know before you change it**

- The index ranks; Postgres cites. Every citation field on the wire is re-read
  from Postgres in the same request; a hit whose row is gone is dropped and
  logged, never returned.
- The citation gate is blunt on purpose: every sentence with alphanumeric content
  must carry a marker. A claim classifier would put a model back inside the gate.
- Validation runs *before* the representation is chosen, so a rejection is the
  same problem response on both paths and the stream never opens on a bad answer.
- Empty retrieval is refused before any model call — zero spend when the corpus
  can cite nothing.

**Left undone, deliberately**

OCR text is indexed for keyword matching but never embedded, so paraphrase cannot
reach on-screen content. Person-scoped questions union rather than intersect the
two legs, so an answer about one person can cite moments they were not in.
Classification itself is untested end to end; tests prove dispatch given a
classification. Citations stay moment-typed — there is no artifact citation
grammar.

---

## Epic 4 — Approved, published, citable knowledge

**Delivered**

- A checkpointed `extract` stage writing artifact rows in `extracted` state,
  anchored to the moment containing their timestamp.
- Whole-transcript extraction with adopt-when-present, generate-when-absent: a
  drop carrying the acquisition tool's markdown documents is parsed with zero
  model calls and recorded as arrived material; a missing document is generated
  through the port. One strict parser serves both paths.
- Both prompts live in config as literal text, are served by an endpoint, and are
  shown in the UI; every generated artifact records a hash of the exact template
  used.
- One per-moment approval gesture that advances every extracted artifact through
  approved to published, exports each to a publish root, and commits decision
  records to a local repository there.
- Publish-on-approve projection into a keyword-only artifact index and into the
  graph with a citation edge to the source moment.

**Know before you change it**

- Column ownership is split and the lifecycle is one-way. There is no unpublish
  path anywhere.
- A rerun replaces drafts only and never touches a moment carrying an approved or
  published artifact.
- Anchoring is containment, not similarity: moments tile the timeline, so an
  anchor resolves to the greatest start at or before it. An anchor outside the
  timeline fails the stage *by name* — dropping it would be a silent zero.
- The parser keys on item id plus timestamp, never on heading numbering. This is
  a recorded lesson: a prior parser understood one of two layouts, reported
  success, and lost most of the decisions.
- Side effects precede the database write, so a failure leaves rows extracted
  rather than marking something published that does not exist on disk.

**Left undone, deliberately**

Extraction can propose the same decision as both a decision record and an action
item; both publish. The adopt path is exercised against fixtures only. Screen and
OCR evidence no longer reach the extraction prompt after the move to
whole-transcript extraction, so a slide-only decision has nothing feeding it. A
partial multi-artifact approve can leave exports on disk while the database
correctly rolls back. The digest has no delivery, scheduling, or windowing.

---

## Epic 5 — A written, reproducible evaluation

**Delivered**

- A closed schema for ground-truth manifests plus a loader carrying the rules the
  schema cannot express, and the single implementation of the recall denominator.
- A subject selector admitting only the scripted corpus; a manifest naming a
  real-corpus meeting is reported as a mismatch, never silently skipped.
- Deterministic capture checks as pure functions over rows, immutable run folders
  with a secret-redacted config snapshot, and a write-once report.
- Retrieval recall through the public search route, and a publish-gate assertion
  that unpublished artifacts are absent from both stores before approval and
  present with resolving citations after.
- A rubric scorer and a blind three-pool bake-off that picks the judge model by
  measured agreement with human gold, both manual CLIs, never test-collected.
- An operator runbook and a store-free finalizer producing a hash-audited verdict
  from the machine report plus versioned, reasoned human overrides.

**Know before you change it**

- Zero eval subjects is a failure — never a pass, never a skip. A harness
  reporting success while measuring nothing is the exact failure mode this epic
  defends against.
- The denominator comes from the manifest, authored from the meeting script,
  never from pipeline output.
- The presence of a verdict closes a run folder. Every threshold applied is
  written beside the result it produced, so changing a threshold invalidates
  prior verdicts.
- Only genuinely subjective criteria reach a model. Citation-present and
  required-terms are mechanical; a missing citation skips the judge call.
- No automated suite can trigger a real model call — judge and bake-off are
  explicit CLIs the runbook invokes.

**Left undone, deliberately**

The end-to-end procedure has never run against a fully real scripted subject, and
both shipped fixtures still carry placeholder source ids, so a run today fails on
that gate by design. Four check designs are specified but unimplemented. The
bake-off has no minimum-agreement floor.

---

## Epic 11 — A test loop measured in seconds (in progress: 11.1 landed)

**Delivered**

- A fast set and a full gate. `server/pyproject.toml` defaults every pytest run
  to `-m 'not slow' --strict-markers`; `slow` marks the tests whose duration
  something outside the test process sets — the Neo4j/Meilisearch test twins,
  spawned processes, the projection file lock, timers — each with a `reason=`
  and its measured cost. `make test-fast` runs `check-client`, the store-free
  suites, and the fast set against Postgres alone; `make test` passes `-m ""`
  and runs everything against all three stores.
- A per-test budget (`server/tests/fast_budget.py`, 2.0s on the call phase
  only) that fails an unmarked passing test which outgrows the fast set, so the
  default run cannot regrow silently.
- Two collection-time rules: a `slow` mark must carry a reason, and an unmarked
  test may not request the twin-bound fixtures (`projection_stores`,
  `stores_up`) — checked statically, again at fixture setup, and again when the
  test is reported, so a `request.getfixturevalue` cannot slip past.

**Know before you change it**

- The split rests on a measurement, not the estimate that preceded it: at
  `e5510c7` (2026-08-29) the full server run was 1,683 tests in 9m17s, with 471
  of 527 test-seconds in twelve twin-, process-, lock-, or timer-bound modules.
  Re-measure with `--durations=25 -m ""` before moving a mark.
- The slow set is pinned in `server/tests/test_compose_contract.py`
  (`SLOW_MODULES`, `SLOW_TESTS`), as are `test-fast`'s prerequisites and its
  one pytest command. Adding a mark, a prerequisite, or a recipe line is an
  edit of both places.
- A `slow` module run by path without `-m ""` collects nothing and exits 5 with
  a hint; an empty expression on the command line replaces the `addopts` one.
- Plugins are registered through `pytest_plugins` in `server/tests/conftest.py`,
  so pytest needs a path under `server/tests` or a cwd of `server/`.
  `REPO_ROOT` lives in `server/tests/repo_paths.py`, not the conftest.
- Contention is not a reason to mark: a test that is slow only while another
  suite, a rebuild, or the worker runs is re-run alone before it is marked.

**Left undone, deliberately**

The fast set is ~50s of pytest, not seconds: ~1,000 Postgres-backed api and
worker tests at 20–50ms each, a fixture cost the marks do not touch (backlog
residue, filed in the process record). Per-run store isolation for the twins
(11.2), eval-run namespacing (11.3), and lint/type tooling in the fast loop
(11.4) are the rest of the epic and have not started.

---

## Retrieval and evaluation posture

Retrieval is two lanes over one authoritative store. The search and graph stores
decide ordering and membership; Postgres decides truth. Every id leaving either
store is re-resolved against Postgres in the same request, so a stale index entry
becomes a dropped-and-logged hit rather than a citation resolving nowhere.

Cited answering is a deterministic pipeline with exactly two model calls in it —
classification and synthesis. Everything load-bearing around them is code. The
classifier's output is validated against the template registry and degrades to
search-only when unrecognized. The synthesis output passes a store-free validator
requiring every sentence to carry a marker and every marker to name a moment that
was retrieved for this question *and* still resolves live. Failure is total and
typed: no repair, no partial emission.

The harness sits outside all of that as a client, and its tiers correspond to how
much the verdict can be trusted. Deterministic checks gate. Classification
accuracy and dedup candidates are reported but never gate, and dedup never
collapses anything — the system is deliberately biased toward over-capture rather
than loss. The publish-gate check is the only place the harness writes, and it
writes through the approval route only. Above that sits a judge whose model was
chosen by blind bake-off against human gold, whose output is advisory and cannot
move the deterministic report. At the top a human may overturn a failed blocking
check with a targeted, reasoned, versioned override — but never a report-integrity
problem such as zero subjects or a missing required check. Those cannot be
overridden by anyone.
