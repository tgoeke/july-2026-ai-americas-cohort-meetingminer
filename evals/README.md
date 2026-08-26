# evals

The eval harness: ground-truth manifests, tiered checks, and immutable run
artifacts. Design lives in
`docs/eval-design.md`; this file is the
operating half — what a manifest declares, how to author one, and how to run
the suite.

**AD-16 — the harness is a client, never a housemate.** It mutates the system
only through the public API and asserts through API reads, read-only store
queries, and run artifacts. That rule is what makes the publish-gate check
meaningful, so it is enforced by an AST walk in
`tests/test_harness_boundary.py` rather than left to convention.

It imports exactly **two** server modules: `meetingminer.config` (from
`conftest.py`, `harness/judge.py` and `harness/bakeoff.py`), so a run's
configuration snapshot is the resolved configuration rather than the
harness's own re-parse of `config.yaml` and `.env`, and
`meetingminer.adapters.llm` (the judge's model port, story 5.4). Neither
mutates any store. Everything else under `meetingminer` is refused —
including `meetingminer.db`, whose `conninfo` helper is the shape
`harness/corpus.py` mirrors, because that module's job is opening write
pools. The guard tests pin the allowances to those exact modules and
importers, so widening them is a deliberate act rather than a drift. The
same suite pins the store drivers: `httpx` to `subjects.py`/`judge.py`/
`retrieval.py`, `psycopg` to `corpus.py`, and `meilisearch`/`neo4j` to
`stores.py` — which is additionally pinned to read-only usage (no store
write-method reference survives the guard).

Shipped so far: the ground-truth schema, its validating loader, eval-subject
selection and one fixture per archetype (story 5.1); the four deterministic
capture checks, the run folder and the deterministic report (story 5.2); the
retrieval and publish-gate checks — doc-index search recall@5 through the
public `GET /search` and the publish-gate projection assert (story 5.3); the
LLM judge harness and bake-off (story 5.4); and the operating procedure —
**[`RUNBOOK.md`](RUNBOOK.md)**, the step-by-step operator path from
preconditions through triage, human judging, `human-verdicts.yaml` and
`verdict.md` (story 5.5). This file is the reference half; the runbook is the
procedure half. The documented-only check designs (citation timestamp window,
action-item fuzzy match, eval cadence, the full retrieval eval) live under
**[`designs/`](designs/)**, each pointing back to its `eval-design.md`
section.

## Layout

```
evals/
  __init__.py                makes `evals` a package, so `evals.harness`
                             imports with no sys.path hack
  ground-truth.schema.json   JSON Schema (draft 2020-12) for one manifest
  ground-truth/              one YAML manifest per scripted meeting
  conftest.py                the run plugin: --run-id / --run-label /
                             --api-base-url, subject selection at collection
                             time, and the session fixtures the checks request
  harness/__init__.py
  harness/groundtruth.py     loader + the rules JSON Schema cannot express
  harness/subjects.py        manifest <-> ingested-meeting matching, and the
                             harness's one network call
  harness/checks.py          the check algorithms — pure functions over rows
  harness/corpus.py          the harness's one database connection, read-only
  harness/retrieval.py       GET /search and the one sanctioned mutation
                             (POST /moments/{id}/approve), httpx
  harness/stores.py          read-only Meilisearch/Neo4j membership reads —
                             the only module importing either driver
  harness/run.py             the run folder, the config snapshot, the report
  checks/                    the store-backed tier-1 checks — one eval run
  runs/<run-id>/             one run's immutable artifacts (committed)
  tests/__init__.py
  tests/conftest.py          valid-manifest builders every negative test
                             mutates by exactly one field
  tests/                     the suite (store-free, api-free)
```

## What a manifest declares

One YAML file per scripted meeting, authored **from the meeting script**:

- `meeting` — `id` (the manifest's own label, e.g. `demo-001`), `source_id`
  (the ingested drop's `sourceId`), `title`, `archetype`, `duration_minutes`,
  `participants`.
- `screens` (archetype `ui-demo`) **or** `slides` (archetype `slide-deck`) —
  every application screen, or the full deck. Declaring the other section is a
  validation error. A `screens` entry must carry `shown_at`; a `slides` entry
  need not — a demo walks screens in an order only the script knows and checks
  2.3/2.5 need that timing, while a deck is shown front to back.
- `participant_segments` — the moments where nothing is shared and a capture
  should hold the gallery view (meeting start, the moment sharing stops).
- `planted` — `action_items`, `decisions`, `phrases` spoken verbatim in the
  script, each with a speaker and a timestamp.
- `qa` — questions the corpus must answer, each naming the planted item its
  top citation must resolve to.

**Expected screenshot count = slides (or screens) + participant_segments.**
That count is the recall denominator, and it exists in exactly one place:
`Manifest.expected_screenshot_count`. Nothing re-derives it.

## Authoring rules

1. **The manifest is never derived from pipeline output.** A denominator built
   from what the extractor emitted cannot contain a screen it missed, so it
   reports 100% recall while measuring nothing. Write the manifest from the
   script, before the recording is processed.
2. **Every slide and screen carries an `ocr_anchor`** — distinctive on-screen
   text a capture of it must contain. Plant the text on the slide if it does
   not occur naturally.
3. **Anchors are unique within a manifest after normalization** (lowercase,
   punctuation stripped, whitespace collapsed — the same folding capture-recall
   matching uses). Two anchors the check could not tell apart are rejected here
   instead of colliding silently during a run.
4. **An anchor must survive normalization.** `"---"` or `"   "` clears the
   schema's `minLength: 1` and still leaves the check nothing to find, so the
   entry could never be recalled.
5. **Ids are unique across the whole manifest** and `qa.expected_moment` must
   name a planted item that exists.
6. **Timestamps are `HH:MM:SS`**, real clock times, inside `duration_minutes`,
   and no two `participant_segments` share an `at` — one moment is one
   expected capture, so repeating it inflates the denominator and puts 100%
   out of reach.
7. **`source_id` is unique across the directory**, as is `meeting.id`.

Nothing beyond non-empty and unique is asserted about an anchor. There is no
similarity or "distinctiveness" threshold: inventing one would reject valid
ground truth.

### Known residual risk: near-identical anchors

Uniqueness here is **exact match after folding**. Check 2.1 matches **fuzzily**,
at token-set similarity ≥ 0.8. So two anchors that differ by a single word —
`"Order Search Results"` and `"Order Search Filters"` — are legal ground truth
and may still be conflated at run time, matching the same capture.

That gap is deliberately left open rather than closed by a guessed threshold,
which would reject ground truth that is perfectly fine. The consequence for
whoever runs a check: **a capture-recall failure whose matched entries look
interchangeable should be triaged as a ground-truth script error before it is
treated as a pipeline bug** (runbook step 2). The cheap fix is to make the two
anchors share fewer words.

## `source_id` is a placeholder until the meeting is pulled

A manifest is matched to an ingested meeting by `sourceId`, and that id does
not exist until the scripted meeting is recorded and pulled. The shipped
fixtures therefore carry `placeholder-<meeting-id>-not-yet-recorded`.

When the recordings land: read the real `sourceId` off `GET /meetings` (or the
drop's `metadata.json`), replace the placeholder, and delete
`test_shipped_source_ids_are_still_placeholders` from
`tests/test_fixtures_validate.py`. Until then the subject selector reports the
manifest under `unmatched` — visibly, rather than as a silently empty subject
list.

## Eval subjects

`select_subjects(meeting_rows, manifests)` pairs manifests with the items of
`GET /meetings` and returns three buckets:

- `subjects` — `corpus: scripted` rows whose `sourceId` matches a manifest.
  The only meetings an eval run may measure. Each carries the row's `jobId`,
  `meetingId`, `title`, `status` and `viewable` as the api reported them. A
  failed job may be re-posted in place; retry resets and re-seeds its stage
  rows, so it does not create a second subject merely by retrying.
- `corpus_mismatches` — a manifest matching a row that is not tagged
  `scripted`. Real pulled meetings are demo corpus and have no ground truth,
  so this pairing means the manifest names the wrong meeting or the drop was
  tagged wrong. Reported, not skipped. A row carrying no tag at all reads
  differently from one tagged `real`.
- `unmatched` — a manifest nothing ingested answers to (a placeholder
  `source_id`, or a meeting not yet ingested). It fails the run (below).

Both non-subject buckets describe themselves: `.describe()` on either record,
or `Selection.problems()` for all of them, so a report does not have to invent
phrasing.

`fetch_meetings(base_url)` is the only network call — a `GET /meetings` read.
Every way it can fail (connection, error status, non-JSON body, a missing or
malformed `meetings` envelope) arrives as one `CorpusReadError`, so a run that
cannot read the corpus says so instead of reporting zero subjects.

## Adding a fixture

1. Write the meeting script first. The manifest follows the script.
2. Copy an existing file in `ground-truth/` — `demo-001-orders-ui-demo.yaml`
   for `ui-demo`, `demo-002-q3-architecture-review.yaml` for `slide-deck`.
3. Name the file `<meeting-id>-<slug>.yaml`; the suite asserts the file name
   starts with `meeting.id` so a failing report line points at a findable file.
4. Give `meeting.id` and `meeting.source_id` values no other manifest uses.
5. Add the file name and its archetype to `EXPECTED_FIXTURES` in
   `tests/test_fixtures_validate.py`. The shipped set is pinned by name on
   purpose — a test that discovered the fixtures and then asserted over what it
   discovered could not notice one that was renamed or deleted.
6. Run `make evals-test`. Every rule above reports as a named message; the
   loader lists all of them at once rather than one per run.

## Running the store-free suite

```bash
make evals-test                              # or:
uv run --project server pytest evals/tests -q
```

No Docker store, no api, no ingestion, and no run folder: the loader reads
files, `select_subjects` is a pure function over rows, and every check
algorithm is exercised over synthetic captures. `make evals-test` is part of
`make test`, in the store-free group that runs before the containers come up.

## The checks

Six deterministic checks (eval-design §2.1-2.4, §2.10-2.11), plus one
precondition on the ground truth itself. Every threshold each applies is
written into the report beside the result it produced — §6 makes thresholds
provisional, so a changed number invalidates prior verdicts and the number in
force has to travel with the number it produced.

| Check | What it measures | Gate? |
|-------|------------------|-------|
| 2.1 capture recall | matched manifest entries / `expected_screenshot_count`, threshold **1.0** | fails the run |
| 2.2 over-capture guardrail | `screenshot` rows vs `ceil(duration_minutes)` | fails the run |
| 2.3 view classification | classified view vs the label the matched section implies | reported only |
| 2.4 dedup quality | sequential captures above 0.9 similarity, listed for a human | reported only |
| 2.10 doc-index search recall | each planted phrase through the public `GET /search`, unfiltered, `limit=5`: a hit from the containing meeting in the top 5; recall@5 = **1.0** | fails the run |
| 2.11 publish-gate projection | non-`published` artifacts in **neither** store (read-only Meilisearch/Neo4j reads); approve via `POST /moments/{id}/approve`; `published` artifacts in **both**, citations resolving to their source moment | fails the run |
| duration agreement | `duration_minutes` vs the probed recording, ±1 minute | fails the run |

Two gate semantics on the new rows worth stating:

- **2.10 never fails on a degraded ranking.** `ranking: "keyword"` (embedder
  down) is recorded per phrase — verbatim plants must still be found. An
  `indexMissing` response, a manifest with no planted phrases, or a search
  api refusal are each a named blocking failure, never a skip or a vacuous
  pass.
- **2.11 consumes state and only ever mutates `scripted` meetings.** Approval
  is one-way (no unpublish), so a run that approves leaves the next run with
  nothing `extracted`: the gate half then records a blocking not-applicable
  naming the state distribution — a full gate measurement needs an unconsumed
  `extracted` artifact. The meeting's `corpus` tag is re-read from Postgres
  before any api call, and anything not `scripted` is a named refusal: the
  real corpus is never approved by a machine.

Two things eval-design leaves open are pinned in `harness/checks.py`:

- **"fuzzy token-set match ≥ 0.8"** is stdlib `difflib`, not rapidfuzz. Both
  sides are folded with `normalize_anchor`; an anchor token is *present* when
  some OCR token scores ≥ 0.85 against it under `SequenceMatcher`
  (character-level OCR noise); the entry's score is present tokens / total
  tokens; the entry matches at ≥ 0.8.
- **"distinct captures"** means `screenshot` rows for the meeting. A capture
  whose OCR could not be read still counts — dropping it would shrink the
  haystack *and* the count, hiding a broken run behind a clean recall number.

Two rules worth knowing before triaging a failure:

- **Participant segments are matched by count**, one per `participant-gallery`
  capture in ordinal order. They carry no anchor, and dropping them from the
  denominator instead would make a missing gallery capture invisible.
- **A capture with no OCR text is a reported defect**, named by ordinal, never
  filtered out — no `representative_frame_id` (a `frames` rerun cleared it) or
  no `frame_ocr` row for the frame the `screens` stage chose.
- **One capture answering for two entries is a reported problem**, not a
  repair. Entries match independently, so two near-identical anchors can both
  resolve to the same capture and recall would read 1.0 over a screen nothing
  captured. Assigning greedily instead would silently pick a winner and leave
  the loser looking like a pipeline miss, which is the wrong triage.

The haystack is the pipeline's own OCR text rather than a second OCR pass. The
independence rule constrains the *denominator*, which is authored from the
script; and the failure direction is safe, because a capture that was never
taken has no row and no text. What that trades away is a capture legible to a
second engine but not to the configured one — which is a real finding about the
configured engine, and is why the run's config snapshot records it.

## Running one eval run

```bash
make evals-run                                   # or, with options:
make evals-run EVAL_ARGS='--run-label capture'
```

**Store-backed and api-backed.** It reads Postgres directly (read-only) and
lists the corpus through `GET /meetings`, so it needs `make up` and it holds
the shared Docker stores while it runs — one agent at a time (AGENTS.md).

### What a run is, and what lands in the folder

A run is one pass of the deterministic checks over every eval subject, plus the
folder that makes its result reproducible:

```
evals/runs/<run-id>/
  config-snapshot.yaml       the resolved config.yaml the run measured against
  deterministic-report.yaml  per-check pass/fail, per-manifest-entry detail
```

`<run-id>` is a date plus a short label (`2026-08-19-capture`). The harness
takes three options, all passed through `EVAL_ARGS`:

| Option | Default | What it does |
|--------|---------|--------------|
| `--run-id` | `<UTC date>-<label or HHMMSS>` | Names the folder under `evals/runs/` outright |
| `--run-label` | none | Supplies just the label half, and is recorded in the report |
| `--api-base-url` | `http://127.0.0.1:8000` | Where `GET /meetings` is read from. `make evals-run` passes `$(CLIENT_URL)` explicitly, so the address the run measures is the one `check-api` validated |

Both `--run-id` and `--run-label` name a folder, so both are constrained to
letters, digits, `.`, `-` and `_`, starting with a letter or digit. A value
that could climb out of `evals/runs/` is a named error, never quietly
sanitized — an audit record filed somewhere the operator did not ask for is
one they will not look in.

**Reusing a label on the same day hard-fails**, because the default run id is
that day's date plus the label and a run gets its own folder. That is the
intended behaviour, not an inconvenience: the second run would otherwise be
written into the first one's evidence. Pick a new label, or pass `--run-id`.

The snapshot matters as much as the numbers: a recall figure is only
interpretable beside the OCR engine that read the text it scored. It holds the
resolved `config.yaml` and **nothing from `.env`** — run folders are committed
as the audit record, so a leak here is a committed secret. `AppConfig.secrets`
is never read, and the dump is walked once more for anything secret-shaped so a
key added to `config.yaml` later cannot leak by being new.

### The folder is immutable

Nothing in a run folder is edited after the fact (eval-design §4.6). `Run`
enforces it rather than trusting it:

- an existing folder is **refused** — a rerun of an interrupted run gets its own
  `--run-id`, so partial evidence is never mixed with a fresh attempt's;
- a folder already holding `verdict.md` (story 5.5) is refused with its own
  message: that folder is a closed audit record;
- `deterministic-report.yaml` is written once, and a second write raises.

Any pipeline change — or a judge-model change — invalidates a run's verdict and
demands a fresh folder (§4.7).

### A run with no subjects fails, by design

**Today that is every run.** Both shipped fixtures still carry placeholder
`source_id` values, so nothing ingested answers to them and `make evals-run`
exits non-zero on `checks/test_subjects_exist.py`, naming each unmatched
manifest and each corpus mismatch.

That is the correct state, not a defect. The alternative — skipping, or passing
vacuously over an empty subject list — is exactly how a harness comes to report
100% recall while measuring nothing. The same rule applies further in: a
scripted subject with no recording, or one whose job has no meeting row yet,
records each capture check as *not applicable* and fails, rather than reporting
an empty pass.

A run also refuses to guess when one manifest matches **more than one** ingested
scripted meeting (a failed job leaves its row behind and a re-ingest adds
another). It cannot tell which one the ground truth describes, so it measures
neither and says so; remove the stale ingestion and rerun.

### Triaging a failure

Runbook step 2 classifies each failure as a pipeline bug, a ground-truth script
error, or a genuine capture miss. Shortcuts from the report:

- **`recall: 1.0` next to `passed: false` on check 2.1** is the report's most
  confusing line, and it is not a bug in the check. Recall is one of three
  things 2.1 asserts; read `problems` for which of the other two fired:
  - `ocr_defects` above zero — a capture exists but can produce no OCR text
    (no `representative_frame_id`, or no `frame_ocr` row for the frame the
    `screens` stage chose). A **pipeline bug**: rerun the `ocr` stage, or the
    `screens` stage after a `frames` rerun cleared the references.
  - `double_assigned_captures` above zero — one capture answered for two
    manifest entries, so recall counted a screen that may never have been
    captured. A **script error** (below).
- a `duration agreement` failure is a **script error** — the manifest is
  describing a different meeting;
- a capture-recall failure whose matched entries look interchangeable is a
  script error too (see the near-identical-anchor risk above), not a pipeline
  bug. The cheap fix is to make the two anchors share fewer words.
- a **verbatim-phrase miss on check 2.10 is a pipeline bug** — the phrases
  are planted verbatim, so the index has no excuse; the report carries the
  top-5 it got instead, and the `ranking` mode says whether the embedder was
  even involved.
- a **post-approval absence on check 2.11** is, today, **the missing story
  4-4 wiring**: nothing projects artifacts on publish yet, so once real
  subjects exist the positive half fails until 4-4 lands — that failure is
  the check defending the gate; never weaken or green it. After 4-4 lands, a
  post-approval absence is a **regression** of projection-on-publish. A
  *pre*-approval presence is the headline **GATE VIOLATION** either way: an
  unpublished artifact reached a retrieval store.
- a 2.11 "nothing left to approve" not-applicable names the artifact state
  distribution: a previous run's approval consumed the `extracted` rows
  (one-way lifecycle). Re-measuring the gate half needs a fresh extraction —
  a rerun alone cannot bring it back.
