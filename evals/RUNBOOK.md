# Eval Runbook

The operator procedure for one full eval run, start to verdict (CAP-8,
eval-design §4). Success test: an operator without tribal knowledge completes a
run and records a defensible verdict using only this file. Every command you
must type, file you must inspect, and record you must write is stated here;
links into [`README.md`](README.md) and
[`eval-design.md`](../docs/eval-design.md) are
for depth, never for missing steps.

**What is runnable today.** The deterministic suite is stories 5.1/5.2/5.3:
the capture checks (eval-design §2.1–2.4), the ground-truth
duration-agreement precondition, doc-index search recall@5 (§2.10) and the
publish-gate projection assert (§2.11) — all in one `make evals-run` pass,
one report. The LLM judge harness and bake-off (§2.7) are story 5.4, a
nice-to-have, and are built: step 4 below is the real procedure, both CLIs
manual and never run under `make evals-test` / `make evals-run`.

The procedure, in order:

1. [Preconditions](#step-1--preconditions)
2. [Deterministic suite](#step-2--deterministic-suite)
3. [Failure triage](#step-3--failure-triage)
4. [Optional LLM judging](#step-4--optional-llm-judging)
5. [Human judging](#step-5--human-judging)
6. [Final verdict](#step-6--final-verdict)
7. [Archive](#step-7--archive)
8. [Rerun rule](#step-8--rerun-rule)

---

## Step 1 — Preconditions

What has to exist before a run can measure anything. `make evals-run` guards
most of these itself (`check-env`, `infra-up`, `check-stores`, `check-api`),
but checking them first turns its refusals into things you expected.

1. **The stack is up.** From the repo root:

   ```bash
   make up
   ```

   brings up the Docker stores, runs migrations, and starts the api, worker
   and web app. The eval run reads Postgres directly (read-only) and lists the
   corpus through `GET /meetings`, so it needs both the stores and the api.

2. **`.env` exists and carries usable storage roots.** `MM_DROPS_ROOT` and
   `MM_CONTENT_ROOT` must both be absolute, writable directories. `check-env`
   refuses a missing drops-root setting; the api and worker's configuration
   loader validates both roots when `make up` starts them. If `.env` is
   missing, `make bootstrap` creates it from `.env.example`; then set, for
   example, `MM_DROPS_ROOT=/absolute/path/to/drops` and
   `MM_CONTENT_ROOT=/absolute/path/to/content`. Do not parse `.env` with a
   shell substitution to check quoted values: start the stack and let the
   loader perform the quote-safe validation.

3. **The ground truth validates.**

   ```bash
   make evals-test
   ```

   must be green. It is store-free and api-free — it validates every manifest
   under `evals/ground-truth/` against the schema and the loader rules, and it
   creates nothing under `evals/runs/`. A red `evals-test` is a manifest
   problem to fix before any run, using the authoring rules in
   [`README.md`](README.md#authoring-rules).

4. **Every manifest carries a real `source_id` and its meeting is ingested.**
   A manifest is matched to an ingested meeting by `sourceId`, and only
   meetings tagged `corpus: scripted` are eval subjects.

   **Today this precondition is unmet, and the run tells you so.** Both
   shipped fixtures still carry placeholder `source_id` values
   (`placeholder-<meeting-id>-not-yet-recorded`), so `make evals-run` exits
   non-zero at the zero-subject gate — `evals/checks/test_subjects_exist.py`,
   ordered first on purpose — naming each unmatched manifest. That exit is an
   **unmet precondition, not a FAIL verdict**: nothing was measured, so there
   is nothing to record a verdict about. Do not write a `verdict.md` for such
   a run. The replacement procedure is in
   [`README.md` — "`source_id` is a placeholder until the meeting is
   pulled"](README.md#source_id-is-a-placeholder-until-the-meeting-is-pulled);
   the recordings that will replace the placeholders are the two NDA demo
   recordings tracked in
   `docs/backlog.md` (the story-2.1b
   entry).

   **A partially met precondition behaves the same way.** If one manifest
   matches an ingested meeting while another still carries a placeholder, the
   checks do run over the matched subject and their results land in the
   report — but the unmatched manifest is recorded as a run-level problem,
   the zero-subject gate's placement test fails naming it, and the run exits
   non-zero with the report's overall `passed: false`. Such a run is usable
   for triage of the matched subject, never for a PASS verdict: ground truth
   that measured nothing must fail the run rather than quietly shrink it.

5. **Runs overlap safely (story 11.3).** `make evals-run` reads the shared
   Docker stores read-only; its one write is check 2.11's run-owned probe,
   minted through the public api and erased on the way out. Two runs, or a
   run beside any test suite, do not contend — each run owns its folder and
   its probe namespace. What can still briefly serialize is the approve
   route's post-commit projection, which takes the same store file lock and
   Postgres advisory lock as every dev-store writer (AGENTS.md, stores
   section): a concurrent holder means a bounded wait, and a timeout is a
   named error the route logs — `rebuild --meeting <id>` closes the gap
   while the route itself still answers.

## Step 2 — Deterministic suite

One pass of every built deterministic check over every eval subject, producing
the run folder.

### The command

```bash
make evals-run EVAL_ARGS='--run-label <label>'
```

This runs the whole `evals/checks/` pytest package against the shared Docker
stores — not only the capture checks. `evals/checks/test_corpus_artifacts.py`
(story 5.4) rides along in the same pass: it is the query coverage for
`corpus.py`'s `artifacts_for`/`segments_for_moment` (what `judge.py` reads),
seeds and cleans its own rows, makes no LLM call, and does not touch the run
folder or `deterministic-report.yaml` — expect it in the test output, not as
a surprise.

**One check in this pass mutates state — deliberately, and only what the run
owns (story 11.3).** Check 2.11 never approves a subject's `extracted`
artifacts: it asserts subject membership read-only, then measures the
approve→project transition on one probe artifact the run mints onto an
eligible projected subject moment, approves through the public
`POST /moments/{id}/approve` (the harness's one sanctioned mutation, AD-16),
and erases with per-target verification — the Postgres row, the publish-root
export, the Meilisearch document, the Neo4j node. The probe is minted only
after re-reading the meeting's `corpus: scripted` tag from Postgres — a
non-scripted meeting is a named refusal with no store handle and no row —
and its title carries the run id, so a row stranded by a killed process
names the run that owes its erasure (delete it, its search document, its
graph node and its export file by that artifact id). Reruns keep their gate
half: nothing is consumed. One residual window is accepted and detected
after the fact: a subject `extracted` row landing on the chosen moment
between the eligibility read and the approval (an operator approving or
re-extracting mid-run) is consumed by the probe's approval — the report
then fails the check naming the consumed ids; record it beside the run and
re-extract before the next gate measurement.

`<label>` is a short slug for what this run is (e.g. `pre-demo`,
`capture-fix`). Both `--run-label` and `--run-id` must start with a letter or
digit, contain only letters, digits, `.`, `-` and `_`, and be at most 96
characters — anything else is a named refusal, never silently sanitized. The
harness options, all passed through `EVAL_ARGS`:

| Option | Default | What it does |
|--------|---------|--------------|
| `--run-id` | `<UTC date>-<label or HHMMSS>` | Names the folder under `evals/runs/` outright |
| `--run-label` | none | Supplies the label half of the default run id; recorded in the report |
| `--api-base-url` | `http://127.0.0.1:8000` | Where `GET /meetings` is read from; `make evals-run` passes the Makefile's `$(CLIENT_URL)` explicitly |

Always pass `--run-label`: a run started without one gets the
`<UTC date>-<HHMMSS>` default, which tells the next reader nothing about what
the run was for. If you do end up with a defaulted id, it is discoverable as
the newest folder under `evals/runs/` and as `run.id` inside that folder's
`deterministic-report.yaml`.

### What lands in the folder

```
evals/runs/<run-id>/
  config-snapshot.yaml       the resolved config.yaml the run measured against
  deterministic-report.yaml  per-check pass/fail, per-manifest-entry detail
```

The snapshot is written first and is secret-free (nothing from `.env`; every
secret-shaped value redacted). The report is written at the end of the session
**whether the run passed or failed** — the report is the record of a failure,
and step 3 triages from it.

### When it refuses

- **The target folder already exists.** A run gets its own folder; an
  interrupted run is rerun under a new `--run-id`, never written over. Reusing
  a label on the same day hard-fails for the same reason — the default run id
  is that day's date plus the label. Pick a new label or pass `--run-id`.
- **The folder already holds `verdict.md`.** That folder is a closed audit
  record, immutable once a verdict is recorded (eval-design §4.6). Start a new
  run with a different `--run-id`.
- **No eval subjects** (the zero-subject gate, step 1.4), an api that is not
  answering or does not identify as the MeetingMiner api, or one manifest
  matching more than one ingested scripted meeting — the run cannot tell which
  one the ground truth describes, so it measures neither and says so; remove
  the stale ingestion and rerun.

### Reading `deterministic-report.yaml`

The report's top level carries the run identity (`id`, `label`, `started_at`,
`finished_at`, all UTC), an overall `passed`, run-level `problems` (unmatched
manifests, corpus mismatches, subjects missing a required check), and one
record per subject. Each subject record lists its `checks`; every check result
has the same shape:

| Field | Meaning |
|-------|---------|
| `check` | which check, named by its eval-design section (e.g. `2.1 capture recall`) |
| `passed` | this check's own verdict |
| `blocking` | whether a failure fails the run — `false` for 2.3 and 2.4, which are reported only |
| `applicable` | `false` when the check could not run at all (e.g. subject with no recording); an inapplicable **blocking** check fails the run — never a skip |
| `thresholds` | the numbers in force when this result was produced (§6 makes them provisional, so they travel with the result) |
| `metrics` | the measured numbers |
| `detail` | per-manifest-entry records (which capture answered for which entry, at what score) |
| `problems` | one line per defect, in triage-ready wording |

The seven checks every completed run must report per subject:

| Check | Threshold in force | Gate? |
|-------|--------------------|-------|
| `2.1 capture recall` | recall 1.0; anchor match ≥ 0.8; token similarity ≥ 0.85 | fails the run |
| `2.2 over-capture guardrail` | captures ≤ ceil(`duration_minutes`) | fails the run |
| `2.3 view classification` | accuracy reported | reported only |
| `2.4 dedup quality` | pairs strictly above 0.9 similarity listed | reported only |
| `2.10 doc-index search recall` | recall@5 = 1.0 on planted phrases, unfiltered public `GET /search` | fails the run |
| `2.11 publish-gate projection` | subjects read-only (non-`published` in neither store; `published` in both, citing its moment); the gate transition on a run-owned probe, erased afterward | fails the run |
| `ground-truth duration agreement` | ±1.0 minute vs the probed recording | fails the run |

A subject missing any of the seven fails the run on completeness. 2.10 records
each phrase's rank, the `ranking` mode (`hybrid`, or `keyword` when the
embedder was down — recorded, never itself a failure) and `indexMissing`;
2.11 records every subject artifact's membership per store, and the probe's
whole sequence: pre/post membership, the approve outcome (a refusal carries
its problem slug; a concurrent run's win is named as the race it is), the
foreign response rows it set aside, and the cleanup verdict per target.

What to do with check 2.3's number: view-classification accuracy is a tracked
metric, not a gate and not a worksheet. Read it each run; a notable drop from
the previous run's accuracy goes into `verdict.md`'s Notes (step 6) so the
trend is on the audit record, and a persistent drop is a pipeline finding to
raise outside the run.

## Step 3 — Failure triage

Triage works over the report's `problems` lines, not over whole checks: one
failed check can carry several lines with different classes (check 2.1 can
report `ocr_defects` and `double_assigned_captures` in the same result).
Classify **each `problems` line** as exactly one of three classes, using the
report's own signatures:

**1. Pipeline bug** — the pipeline mis-produced evidence.
- `ocr_defects` above zero in check 2.1's metrics: a capture exists but can
  produce no OCR text. The `problems` line names which kind — no
  `representative_frame_id` (a `frames` rerun cleared the reference and the
  `screens` stage has not run since) or no `frame_ocr` row for the frame the
  `screens` stage chose (the `ocr` stage did not cover it). The stage names
  are the diagnosis, not a command: **no operator command re-runs a single
  stage today.** The one operator-level requeue that exists is for a *failed*
  job — re-POSTing its drop to `POST /ingests` (re-running the same
  `make mint-drop` command does this: it reports `exists` and POSTs the drop
  again) re-queues the job in place and re-runs the full stage set: the retry
  deletes and re-seeds its stage checkpoints. Anything beyond that is
  developer work outside this runbook — record the defect and leave it in the
  report.
- A `2.2 over-capture guardrail` failure with plausible ground truth: the
  extractor emitted more captures than one per minute.
- Note: `recall: 1.0` next to `passed: false` on check 2.1 is not a bug in the
  check — recall is only one of three things 2.1 asserts. Read `problems` for
  which of the other two fired (`ocr_defects` → pipeline bug;
  `double_assigned_captures` → script error, below).
- A **verbatim-phrase miss on check 2.10**: the phrases are planted verbatim,
  so the index has no excuse — always a pipeline bug (projection, indexing,
  or the search route), never a recalibration candidate. The `problems` line
  carries the top-5 the query got instead; the recorded `ranking` mode tells
  you whether the embedder was even involved — a `keyword` degradation is
  context, not the cause of a verbatim miss. An `indexMissing` failure means
  nothing was ever projected: ingest and project before rerunning.
- A **pre-approval `GATE VIOLATION` on check 2.11** — an unpublished artifact
  present in a retrieval store — is the headline pipeline bug: something
  projected past the publish gate (AD-4). It is never a script error.
- A **post-approval absence on check 2.11** — the probe (or an already
  `published` subject row) missing from a store — is a regression of
  projection-on-publish (story 4-4, landed): the approve route must land the
  artifact in both stores. A citation-resolution failure (present but not
  citing the source moment) triages the same way.

**2. Ground-truth script error** — the manifest is wrong, not the pipeline.
- A `ground-truth duration agreement` failure: the manifest is describing a
  different meeting.
- `double_assigned_captures` above zero: one capture answered for two manifest
  entries, so two anchors are too alike. The cheap fix is to make them share
  fewer words.
- A capture-recall failure whose matched entries look interchangeable
  (the near-identical-anchor risk,
  [`README.md`](README.md#known-residual-risk-near-identical-anchors)).

**3. Genuine capture miss** — the manifest is right and the pipeline captured
nothing for the entry: an unmatched entry in 2.1's `detail` with a low best
score and no script-error signature.

Two 2.11 lines belong to none of the three classes. A **probe refusal** —
every moment holds an unconsumed `extracted` row, the `extract` stage is not
settled, the meeting was never projected, or there are no moments — is the
gate half unmeasured, still failing the run (a blocking not-applicable is
never a pass); each names its remedy in the line. A **cleanup leftover**
names the exact ids still standing and where: the run owes an erasure —
remove the named row, document, node or file by that artifact id and rerun
under a new run id.

**What to do with each class:**

- **Script errors are fixed in the YAML and noted.** Correct the manifest,
  re-run `make evals-test` to validate the fix, then rerun the deterministic
  suite (step 2) under a **new run id** — the old folder is never edited, and
  the eventual `verdict.md` (step 6) notes the correction and names the
  superseded run folder.
- **Pipeline bugs and genuine misses stay in the report.** They are what the
  run found. Capture-recall failures go to the human-judging worksheet in
  step 5; a bug you fix afterwards triggers the rerun rule (step 8).

## Step 4 — Optional LLM judging

Built (story 5.4), nice-to-have, and manual: neither CLI below runs under
`make evals-test` or `make evals-run`, and neither is invoked from
`infra/Makefile`. Both call real model providers, so run them by hand and
never unattended — the frontier and hosted-open-weight pools cost money per
call. Skipping this step entirely is always valid; the human judge (step 5)
covers everything the judge would have scored, and `adr-decision-quality`'s
worksheet just stays without an LLM-judge column to read from.

### 4.1 — Bake-off first, once, before the first full eval run

The judge model is selected empirically (eval-design §7), never by fiat:

```bash
uv run --project server python -m evals.harness.bakeoff \
  --sample evals/bakeoff-samples/sample-001.yaml \
  --run-label pre-demo
```

- `--candidates` defaults to `evals/bakeoff-candidates.yaml` — one entry per
  pool (frontier API, local Ollama, hosted open-weight), each an
  `LlmRoleBinding`-shaped mapping plus `pool`/`label`. Edit that file to swap
  a candidate; no code changes.
- `--sample` is a committed fixture of qa/artifact items with authored human
  gold verdicts (`evals/bakeoff-samples/sample-001.yaml` ships one). Every
  candidate scores the same sample, blind to the others.
- `--repeats N` re-scores the sample N times per candidate, to break an
  agreement tie by verdict consistency (see below).
- The result lands in `evals/runs/bakeoff-<UTC date>[-<label>]/` — a fresh
  `Run.create` folder, `config-snapshot.yaml` plus `bakeoff-report.yaml` —
  under the same immutability rule as every other run folder (never rerun
  against the same `--run-id`).
- Each candidate's `Llm` is built with its `fallback` forced to `None`,
  regardless of what `bakeoff-candidates.yaml` says: a substitution would
  attribute a reply to the wrong exact model id, the one thing a bake-off
  exists to pin.
- A candidate that cannot be reached (`LlmUnavailableError`/`LlmError`) is
  recorded under `excluded` with its error — never silently dropped from the
  report and never silently substituted.
- **Reading `winner`:** the primary score is agreement with the sample's gold
  verdicts. A tie breaks by `--repeats`-based consistency when
  `--repeats > 1`, then by pool order (`local-ollama`, `hosted-open-weight`,
  `frontier-api` — cost/locality preference). An agreement tie at
  `--repeats == 1`, or one that survives both tie-breaks, is never broken
  arbitrarily: `winner` is `null` and `tie` names the tied candidates. Re-run
  with `--repeats` raised, or extend the sample, rather than picking by hand.
- **Pin the winner.** The bake-off never writes `config.yaml` (`AD-10`
  bindings are a human edit). Once `winner` is non-null, edit
  `config.yaml`'s `llm.roles.judge` to the winning candidate's exact
  `model`/`base_url`/etc. by hand, and record which bake-off run justified it
  in the commit that changes it.

### 4.2 — Score a real run

Once the judge role is pinned, score a real run's extracted artifacts and
Q&A answers against rubric 2.7:

```bash
uv run --project server python -m evals.harness.judge \
  evals/runs/<run-id> \
  --meeting-id <meeting-id> [--meeting-id <meeting-id> ...]
```

- `<run-id>` is an **existing** folder from step 2 (this command does not
  create one) — it writes `llm-judge-report.yaml` into it, once; a folder
  that already carries that file is refused.
- `--meeting-id` names an ingested, scripted meeting to score (repeatable);
  each must match a manifest the subject selector placed (step 1.4) — a
  meeting id naming no scripted subject is refused, naming which.
- For every `artifact` row on that meeting, the judge scores `faithful`/
  `no_unsupported_claims` against the artifact's own moment's covering
  transcript; `citation_present` is mechanically `true` (an `artifact` row
  cannot exist without its moment FK).
- For every manifest `qa` entry, the judge asks a real `POST /chat` for the
  planted question, then scores the answer the same way against the top
  citation's covering transcript. `citation_present` is the answer's
  citations array non-empty — an uncited answer is an automatic fail and
  skips the model call entirely (nothing left for it to decide).
- `contains_required_terms` (`qa.answer_must_contain`) and `citation_present`
  are computed, never judged; only `faithful` and `no_unsupported_claims` are
  asked of the model, with one retry on an unparsable reply before the item
  is recorded not-applicable (never silently passed).
- `llm-judge-report.yaml` never touches `deterministic-report.yaml` or its
  `passed` field (eval-design §4.3: this tier is advisory).

### 4.3 — Scores are advisory

They feed the `adr-decision-quality` worksheet in step 5; they gate nothing
on their own, and the human verdict wins every disagreement.

Changing the pinned judge model later invalidates prior verdicts (step 8).

## Step 5 — Human judging

The human judge is the final arbiter over both the deterministic results and
any LLM-judge scores (eval-design §3). Walk one worksheet per human-judged
check, then record every ruling in the run folder.

### The worksheets

Five, one per human-judged check. For each, list every item the reports put in
front of you. A worksheet is empty only when its surface is not built and so
produces no candidates; a surfaced candidate whose evidence cannot be
inspected is an advisory `fail`, never an omission.

The current web app has no meeting drill-down or replay view. Use the report
first; for evidence that is currently inspectable, use the app's existing
search surface or a current replay/search endpoint when it is available. If a
worksheet needs a capture, transcript, or citation drill-down that the current
app cannot expose, record that item as `fail` with a reason naming the
unavailable evidence. It must not disappear from the worksheet. Worksheets
3–5 judge surfaces that are not all built yet — each row below says what
exists today.

| # | Worksheet | What you judge | Items come from |
|---|-----------|----------------|-----------------|
| 1 | `capture-recall-failures` | Is each unmatched manifest entry a genuine miss? | check 2.1 `problems`/`detail`; inspect only through a currently available replay/search route; otherwise record unavailable evidence as fail |
| 2 | `dedup-candidates` | Keep or collapse each near-duplicate pair | check 2.4 `detail`; no current capture drill-down means an unresolved candidate is fail |
| 3 | `action-item-matches` | Are non-exact extracted action items semantically the planted ones? | `designs/action-item-fuzzy-match.md`. **[arrives with epic 4 — stories 4.1/4.2]** No extraction surface exists yet, so there is nothing to compare against `planted.action_items`; record this worksheet empty until then |
| 4 | `adr-decision-quality` | Is each extracted decision/ADR faithful to its cited moment, per rubric §2.7? | LLM-judge report when built (story 5.4); current drill-down evidence is unavailable. **[arrives with epic 4 — story 4.1]** No extracted artifacts exist yet; record this worksheet empty until then |
| 5 | `qa-right-moment-cited` | For each manifest `qa` entry, does the top citation resolve to `expected_moment`? | eval-design §2.8. **[arrives with stories 3.3/3.4]** The cited-Q&A ask surface is not built yet (corpus search, story 3.1, is — but it is not Q&A); record this worksheet empty until then |

Use this template per worksheet. For an override of a failed deterministic
blocking check, carry its exact `manifest`, `check`, and `item` into the YAML
below; the finalizer reconciles the check target against the report. Advisory
items use the same evidence target but remain item-level records.

```
Worksheet: <name>                Run: <run-id>    Judge: <name>
| item | machine result | human verdict | one-line reason |
|------|----------------|---------------|-----------------|
```

### Recording: `human-verdicts.yaml`

Write the rulings to `evals/runs/<run-id>/human-verdicts.yaml`, in exactly
this versioned shape:

```yaml
version: 1
run: 2026-09-02-pre-demo          # the run id — must equal the folder name
judge: Tim Goeke
completed_at: "2026-09-02T16:40:00+00:00"   # ISO 8601, UTC — when judging finished
worksheets:
  capture-recall-failures:
    - manifest: demo-001
      check: "2.1 capture recall"
      item: "SC3"
      kind: reconciliation          # reconciliation | advisory
      machine: "unmatched, best score 0.31"   # optional: the result being ruled on
      verdict: fail               # pass | fail
      reason: "The order-filter screen truly never appears in any capture."
  dedup-candidates:
    - manifest: demo-001
      check: "2.4 dedup quality"
      item: "captures 4+5"
      kind: advisory
      machine: "similarity 0.9412"
      verdict: pass
      reason: "Same screen but the confirm modal is open in 5 — both stay."
  action-item-matches: []         # nothing to judge this run — recorded, not omitted
  adr-decision-quality: []
  qa-right-moment-cited: []
```

Rules:

- Every record has `manifest`, `check`, `item`, `kind`, `verdict` (`pass` |
  `fail`), and a one-line `reason`; `machine` is optional but useful. The
  `(manifest, check)` target must name an actual report check, and
  `(manifest, check, item)` must be unique. This allows several auditable
  advisory items for one check, such as multiple dedup pairs.
- **Reconcile every failed applicable blocking result exactly once.** A
  `kind: reconciliation` row is a check-level override and must name a failed
  applicable blocking result. Its `item` identifies the report evidence the
  judge considered, while its reason must account for that check's failed
  evidence as a whole. Its `pass` is the only human action that can overrule
  the deterministic failure; its `fail` yields generated FAIL. A duplicate,
  passing, or nonblocking reconciliation target makes finalization refuse, as
  does an omitted failed-blocking reconciliation.
- A `kind: advisory` row records an individual item for any actual report
  check. It cannot overrule a deterministic result, but its `fail` makes the
  generated final verdict FAIL. Do not omit unavailable evidence: record it
  as an advisory `fail` with the reason.
- **All five worksheet keys are always present**, empty lists where nothing
  was judged.
- No human ruling can overrule a report-integrity problem (run-level problem,
  zero subjects, missing required check, or inapplicable blocking result).
- **`pass` and `fail` are the only verdict values.** An item you cannot rule
  on — ambiguous or unavailable evidence — must be resolved before step 6, or
  ruled `fail` with the `reason` naming the uncertainty. There is no third
  value: an unresolved item left out of the file would make the verdict
  vacuously clean.
- `python -m evals.harness.verdict evals/runs/<run-id>` validates this artifact
  before writing anything. It requires all five worksheet keys, nonempty
  `judge` and `completed_at`, `version: 1`, one-line nonempty reasons, actual
  report targets, and complete reconciliation; it never rewrites the
  deterministic report. It validates record shape and targets, not whether an
  advisory item or a reason is substantively correct.

## Step 6 — Final verdict

Generate, do not hand-author, the immutable final verdict:

```bash
python -m evals.harness.verdict evals/runs/<run-id>
```

The command writes `verdict.md` once and includes SHA-256 hashes of both
source artifacts plus every targeted ruling and reason. Deterministic
`passed` remains factual and unchanged. Generated PASS requires no
report-integrity problem, no human `fail`, and exactly one human `pass`
reconciliation for every failed applicable blocking result. Advisory `pass`
items do not change deterministic results; an advisory `fail` generates FAIL.
Malformed, mismatched, duplicate, invented-target, or incomplete human
evidence refuses before closing the folder. An existing `verdict.md` is never
overwritten. A generated PASS exits 0; a generated FAIL is still written and
then exits 1, so an operator can archive its evidence while automation detects
the failed gate.

**Threshold changes** remain a rerun trigger: record any calibration decision
in the issue or commit that changes the threshold, invalidate prior verdicts,
and run a fresh folder. The generated verdict is the immutable audit summary,
not a place to amend measured evidence.

## Step 7 — Archive

The run folder is immutable once `verdict.md` exists. Nothing in it is edited
retroactively — not to fix a typo, not to append a late ruling. The harness
enforces the half it can see: `Run.create` refuses a folder holding
`verdict.md` as a closed audit record, refuses any existing folder, and raises
on a second `deterministic-report.yaml` write. The other half is yours: treat
the folder as read-only from this point.

Run folders are committed — they are the audit record. Stage the folder
explicitly (never `git add -A`) and push:

```bash
git add evals/runs/<run-id>
git commit -m "eval: record <run-id> verdict (<PASS|FAIL>)"
git push
```

Anything you want to change after this point is a new run.

**End state of the environment.** `make evals-run` held nothing exclusive
(story 11.3): it read the stores, and its probe namespace was erased before
it exited — steps 3 through 7 (triage, human judging, verdict, archive) read
files and the app, holding nothing either. The stack may stay up for the next
task or come down with `make down`, which stops the web app, worker, api and
the store containers; nothing about a recorded run depends on either choice.

## Step 8 — Rerun rule

Any of the following, after a run, **invalidates that run's verdict**
(eval-design §4.7):

- a pipeline change (any stage: capture, OCR, screens, transcripts, moments,
  extraction, projections),
- a `config.yaml` change — pipeline configuration is part of the pipeline,
  which is why every run snapshots the resolved config it measured against,
- an embedder change (the embedding model is a recorded property of the
  retrieval store),
- a judge-model change (the §7 pin moved),
- a threshold change (step 6),
- a ground-truth manifest edit — an edited manifest invalidates every verdict
  it grounded, because the denominator behind those verdicts is no longer the
  one on record.

The response is always the same: a fresh run folder, from step 1 — new
`--run-id` (or new label), full preconditions, full deterministic suite. Never
re-open, append to, or amend the invalidated folder; it stays as the record of
what was true before the change.
