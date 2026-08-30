---
title: 'Story 5.1: Ground-Truth Schema & Scripted Fixtures'
type: 'feature'
created: '2026-08-19'
status: 'done'
baseline_revision: '5336aec3d5ce93304306da2c7da9d648a367b40a'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/specs/spec-meetingminer/eval-design.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The ground-truth manifest carries no schemaVersion, though the drop schema
      it mirrors carries one and the manifest $id already embeds a version segment.
    evidence: |-
      docs/source-drop.schema.json versions its contract so a consumer pinned to
      version 1 fails closed on a version 2 drop. Every shipped manifest is
      unversioned, so the first breaking schema change has no way to fail loudly on
      files written against the old shape. Not patched because manifests and the
      harness that reads them live in one repository and version together in git,
      which is a materially weaker case than the puller/server split the drop
      schema's versioning exists for - so the design call is genuinely arguable
      rather than an oversight.
    location: >-
      evals/ground-truth.schema.json
    severity: medium
  - summary: >-
      The AD-16 import guard is both stricter and looser than AD-16 itself.
    evidence: |-
      ARCHITECTURE-SPINE.md AD-16 bans imports that change state and explicitly
      permits direct read-only queries of Postgres and the stores. The guard bans
      the bare `meetingminer` root outright, which will force stories 5.2/5.3 to
      duplicate any shared read-only constant. In the other direction nothing
      forbids importing psycopg, neo4j or meilisearch, so a future check can write
      the very stores it audits without importing a server module at all, and a
      dynamic importlib.import_module("meetingminer.db") passes the AST walk
      untouched.
    location: >-
      evals/tests/test_harness_boundary.py
    severity: medium
  - summary: >-
      No meeting script exists for either fixture to have been transcribed from.
    evidence: |-
      eval-design.md §1 and §2.1 state the independence rule positively: the
      manifest is authored from the meeting script. No meeting script exists
      anywhere in the repository. demo-001 is §1's YAML example carried over and
      extended with invented screens; demo-002 is extrapolated the same way. The
      negative half of the rule holds trivially (nothing is derived from extractor
      output, because no extractor has run) while the positive half has no referent.
      Out of scope for 5.1, which delivers the schema and validating fixtures, but
      the scripts must be authored before any fixture is ground truth for a real run.
    severity: medium
  - summary: >-
      qa.answer_must_contain terms are not checked against the planted item the
      qa entry cites.
    evidence: |-
      demo-001 Q2 requires ["tax table", "Friday"] and AI1 happens to contain both,
      by hand. A term the planted item never contains validates clean and only fails
      during story 5.4's judge run, far from the file that caused it. This is the
      same class of cross-entry rule the loader already implements for
      expected_moment. Not patched because a legitimate answer may paraphrase the
      planted text, so the rule risks rejecting correct ground truth.
    location: >-
      evals/harness/groundtruth.py
    severity: low
  - summary: >-
      Test builders live in conftest.py and are imported by module path, under an
      unpinned pytest import mode.
    evidence: |-
      Three test modules do `from evals.tests.conftest import ...`. conftest.py is
      pytest's own module and holds no fixtures here, so the builders belong in a
      plain module. The eval suite has no pytest ini section of its own and there is
      no root pyproject.toml, so both the conftest import and the __init__.py
      sys.path arrangement rely on pytest's default prepend import mode; setting
      --import-mode=importlib anywhere upstream breaks both.
    location: >-
      evals/tests/conftest.py
    severity: low
  - summary: >-
      duration_minutes is a number, and the two checks that read it round it
      differently.
    evidence: |-
      _timestamp_problems computes int(float(duration) * 60), which truncates, while
      eval-design §2.2's over-capture guardrail uses ceil(duration_minutes) on the
      same field. Every fixture and test uses an integer, so neither rounding is
      exercised and the disagreement is invisible today. It becomes real the moment
      a fixture declares a fractional duration.
    location: >-
      evals/harness/groundtruth.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** Epic 5's every check needs a machine-readable declaration of what a scripted meeting
should produce, and none exists — `evals/` is a placeholder README. Without an authored manifest
there is no recall denominator, so "100% capture recall" would be measured against the extractor's
own output and would report success while measuring nothing.

**Approach:** Land the ground-truth contract as data plus a thin validating loader: a closed JSON
Schema for the YAML manifest, a Python loader that enforces the rules JSON Schema cannot express
(anchor uniqueness, id references, timestamps inside the meeting), a derived expected-screenshot
count, an eval-subject selector that matches manifests to ingested meetings by `sourceId` and admits
only `corpus: scripted`, and one validating fixture per archetype. No checks, no run folders, no
report writing — those are stories 5.2/5.3.

## Boundaries & Constraints

**Always:**
- The manifest is authored from the meeting script; nothing in this story may derive a manifest,
  an anchor, or a count from pipeline output (eval-design §2.1 independence rule).
- Expected screenshot count = `len(slides or screens) + len(participant_segments)`. One formula,
  one implementation, exposed as a property on the loaded manifest.
- Every slide/screen entry carries a non-empty `ocr_anchor`; anchors are unique within a manifest
  after normalization (lowercase, collapsed whitespace). Missing or duplicate fails validation.
- Eval subjects are meetings with `corpus == "scripted"` matched by `sourceId`. A `corpus: real`
  meeting is never a subject, even when a manifest names its `sourceId` — that combination is a
  ground-truth authoring error and must be reported, not silently skipped.
- AD-16: the harness reads the corpus through the public API (`GET /meetings`) and imports no
  server module that mutates state.
- Schema style matches `docs/source-drop.schema.json`: draft 2020-12, `additionalProperties: false`
  at every level, the description carrying the contract prose.

**Block If:**
- The real scripted meetings must be recorded/pulled before this story can land. They must not:
  fixtures carry placeholder `source_id` values, replaced when the recordings are pulled.

**Never:**
- No check implementations (recall, over-capture, classification, dedup, recall@5, publish gate).
- No `evals/runs/` folder creation, report writing, or config snapshotting.
- No OCR, no store queries, no ingestion, no `POST /ingests` call.
- No edit to `docs/source-drop.schema.json`, `config.yaml`, or anything under `server/`.
- No invented "distinctiveness" threshold for anchors beyond non-empty + unique — the story's
  acceptance names missing and duplicate only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid ui-demo manifest | fixture with `archetype: ui-demo`, `screens`, `participant_segments` | loads; `expected_screenshot_count == len(screens) + len(participant_segments)` | No error expected |
| Valid slide-deck manifest | fixture with `archetype: slide-deck`, `slides` | loads; count uses `slides` | No error expected |
| Archetype/section mismatch | `archetype: ui-demo` with a `slides:` key | validation error naming the wrong section | schema `if/then`, message lists the offending key |
| Missing anchor | a `screens` entry without `ocr_anchor` | validation error | schema `required` |
| Duplicate anchor | two entries whose normalized anchors are equal | validation error naming both entry ids | loader rule (JSON Schema cannot express it) |
| Duplicate entry / planted / qa id | two `screens` share `id: SC1` | validation error naming the id | loader rule |
| Dangling `qa.expected_moment` | `expected_moment: D9` with no planted `D9` | validation error naming the reference | loader rule |
| Timestamp past the meeting | `at: "00:99:00"` or `at` beyond `duration_minutes` | validation error naming field and value | loader rule; `HH:MM:SS` shape is schema-enforced |
| Duplicate `source_id` across fixtures | two manifests declare the same `source_id` | corpus-level validation error | `load_all` rule |
| Subject selection over a mixed corpus | `GET /meetings` returns scripted + real rows | only scripted rows matched to manifests are subjects | real rows dropped |
| Manifest names a `real` meeting | manifest `source_id` matches a `corpus: real` row | that pairing is reported as a corpus mismatch, never a subject | selector returns it in `corpus_mismatches` |
| Manifest matches nothing ingested | placeholder `source_id` | reported as an unmatched manifest | selector returns it in `unmatched`; 5.2 decides run failure |

</intent-contract>

## Code Map

- `evals/README.md` -- placeholder to replace; states the AD-16 client rule the new content keeps.
- `docs/source-drop.schema.json` -- the schema-authoring convention to mirror: draft 2020-12, closed
  objects, contract prose in `description`, `if/then` for conditional shape.
- `server/tests/test_drop_schema.py` -- the schema-test convention to mirror: module-level
  `Draft202012Validator` with `FormatChecker`, an `errors(instance)` helper, parametrized
  missing-field / invalid-value cases, and tests asserting the schema *documents* its own rules.
- `server/tests/test_projections_single_writer.py:26-50` -- the AST import-boundary convention
  (`imported_roots`, plus a guard test that the walk is non-empty). Reuse the shape for AD-16.
- `server/meetingminer/api/meetings.py:34-45,50-55` -- `_MEETINGS_WITH_STAGES` and `MeetingListItem`:
  `GET /meetings` already returns `sourceId`, `corpus`, `meetingId`, `jobId` per row, camelCased by
  `alias_generator=to_camel`. That is the entire read surface subject selection needs.
- `_bmad-output/specs/spec-meetingminer/eval-design.md:5-60` -- §1 ground-truth schema (the YAML
  example this schema formalizes) and the unique-anchor authoring rule.
- `_bmad-output/specs/spec-meetingminer/scope.md:18-21` -- the corpus rule (scripted = sole eval
  basis; real = demo corpus, never eval subjects).
- `server/pyproject.toml:14,20,64-65` -- `pyyaml`, `jsonschema[format-nongpl]` are runtime deps and
  `httpx`/`pytest` are dev deps, so the eval suite runs under the existing server venv with no new
  dependency.
- `infra/Makefile:74,186,193` -- `.PHONY` list and the `test` / `web-test` / `puller-test`
  targets; the store-free suites run before `infra-up`. `evals-test` joins them there.

## Tasks & Acceptance

**Execution:**
- `evals/ground-truth.schema.json` -- new: draft 2020-12 schema for the manifest (`meeting`,
  `slides` | `screens`, `participant_segments`, `planted`, `qa`), closed at every level, with
  `if/then` binding `archetype` to its section and forbidding the other -- the machine-checkable
  half of eval-design §1.
- `evals/__init__.py`, `evals/harness/__init__.py` -- new: make `evals` importable as a package so
  `evals/tests` can `from evals.harness...` without sys.path manipulation.
- `evals/harness/groundtruth.py` -- new: `parse_timestamp`, `normalize_anchor`, `validate_manifest`
  (returns a list of messages, schema errors first then the loader rules), `Manifest` dataclass with
  `expected_screenshot_count` / `entries` / `anchors`, `load_manifest`, `load_all` (adds the
  cross-file `source_id` and `meeting.id` uniqueness rules), `GroundTruthError`.
- `evals/harness/subjects.py` -- new: `Subject` dataclass, `select_subjects(meeting_rows, manifests)`
  returning subjects plus `unmatched` and `corpus_mismatches`, and `fetch_meetings(base_url)` — the
  only network call, a `GET /meetings` read — kept separate so selection is unit-testable offline.
- `evals/ground-truth/demo-001-orders-ui-demo.yaml` -- new: ui-demo archetype fixture.
- `evals/ground-truth/demo-002-q3-architecture-review.yaml` -- new: slide-deck archetype fixture.
- `evals/tests/__init__.py`, `evals/tests/conftest.py` -- new: shared valid-manifest builders
  (`valid_ui_demo()`, `valid_slide_deck()`) mirroring `conftest.valid_metadata`'s override style.
- `evals/tests/test_ground_truth_schema.py` -- new: schema-level cases from the I/O matrix plus
  schema self-documentation assertions.
- `evals/tests/test_ground_truth_loader.py` -- new: loader-rule cases (anchors, ids, references,
  timestamps, counts, cross-file uniqueness) and the timestamp parser.
- `evals/tests/test_fixtures_validate.py` -- new: every file under `evals/ground-truth/` loads, both
  archetypes are present, and each fixture's expected-screenshot count matches its manifest.
- `evals/tests/test_subject_selection.py` -- new: the selection matrix rows over synthetic
  `GET /meetings` payloads.
- `evals/tests/test_harness_boundary.py` -- new: AST walk over `evals/` asserting no import of
  `meetingminer.pipeline|projections|worker|db` (AD-16).
- `evals/README.md` -- rewrite: what a manifest declares, the authoring rules, how to add a fixture,
  how to run the suite, and that `source_id` is filled in when the scripted meeting is pulled.
- `infra/Makefile` -- add a store-free `evals-test` target, list it in `.PHONY` and `help`, and make
  `test` depend on it beside `web-test`.

**Acceptance Criteria:**
- Given the fixtures in `evals/ground-truth/`, when the suite loads them, then both archetypes
  (`ui-demo`, `slide-deck`) parse and validate with zero errors.
- Given a fixture, when its expected screenshot count is computed, then it equals
  slides (or screens) + participant segments.
- Given a manifest whose slide/screen entries have a missing or duplicate `ocr_anchor`, when it is
  validated, then validation fails and the message names the offending entry.
- Given a `GET /meetings` payload containing both `scripted` and `real` rows, when eval subjects are
  selected, then only `scripted` rows whose `sourceId` matches a manifest become subjects, and a
  `real` row matching a manifest is reported as a corpus mismatch rather than becoming a subject.
- Given the repository, when `make evals-test` runs, then the eval suite executes with no Docker
  store and no API running, and passes.

## Auto Run Result

Status: done

**Implemented change.** Epic 5's ground-truth contract lands as data plus a thin
validating loader: a closed draft-2020-12 JSON Schema, a loader carrying the rules
JSON Schema cannot express, the single implementation of the recall-denominator
formula, an eval-subject selector that admits only `corpus: scripted` matched by
`sourceId`, one validating fixture per archetype, and a store-free pytest suite
wired into `make test`. No checks, no run folders, no report writing.

**Files changed**

- `evals/ground-truth.schema.json` — the manifest contract; `if/then` binds `archetype` to exactly one of `slides`/`screens` and forbids the other.
- `evals/harness/groundtruth.py` — `parse_timestamp`, `normalize_anchor`, `validate_manifest`, `Manifest.expected_screenshot_count`, `load_manifest`, `load_all`.
- `evals/harness/subjects.py` — `select_subjects` (pure), `fetch_meetings` (the one network call), `Selection` with `subjects`/`unmatched`/`corpus_mismatches`.
- `evals/ground-truth/demo-001-orders-ui-demo.yaml`, `evals/ground-truth/demo-002-q3-architecture-review.yaml` — one fixture per archetype.
- `evals/tests/` — 194 store-free tests across five modules plus shared builders.
- `evals/__init__.py`, `evals/harness/__init__.py`, `evals/tests/__init__.py` — package layout so tests import the harness without sys.path manipulation.
- `evals/README.md` — what a manifest declares, the authoring rules, how to add one, how to run the suite.
- `infra/Makefile` — `evals-test` in `.PHONY`, `help`, and as a store-free `test` prerequisite.
- `AGENTS.md` — `make evals-test` added to the store-free concurrent-suite list.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` — additive schema note reconciling §1 with the shipped schema.

**Review findings breakdown.** 16 patched (8 medium, 8 low), 6 deferred (3 medium,
3 low), 9 rejected. No intent gaps and no spec-level defects: all four layers
found omissions in coverage and small robustness rules, not a wrong design, so no
code was re-derived.

**Follow-up review recommendation:** true. Patched this pass: 0 high, 8 medium,
8 low. Score = 3 × 8 + 1 × 8 = 32, which is at or above 5.

**Verification performed** (each command run and observed after the patch pass):

- `make evals-test` — 194 passed in 0.58s, no Docker store and no api running.
- `uv run --project server pytest evals/tests -q` — 194 passed.
- `uv run --project server pytest server/tests/test_drop_schema.py -q` — 34 passed, unchanged.
- `make web-test` — 38 passed, unchanged.

The I/O matrix audit passes: every one of the 13 rows maps to at least one named
test that ran and passed, with no skips in the run.

**Residual risks**

- Both fixtures carry placeholder `source_id` values, so they match nothing until
  the scripted meetings are recorded and pulled. `test_shipped_source_ids_are_still_placeholders`
  is the tripwire; its docstring says to delete the test, not edit it, when the
  real ids land.
- No meeting script exists for either fixture to have been transcribed from, so
  the independence rule's positive half has no referent yet (deferred above).
- The harness's spelling of the `GET /meetings` contract is maintained by hand.
  AD-16 forbids importing the response model, so a server-side rename of `corpus`
  or `viewable` leaves the eval suite green while every manifest silently lands in
  `unmatched`.

## Spec Change Log

## Review Triage Log

### 2026-08-19 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 0, medium 8, low 8)
- defer: 6: (high 0, medium 3, low 3)
- reject: 9: (high 0, medium 0, low 9)
- addressed_findings:
  - `[medium]` `[patch]` `fetch_meetings` had no test at all; a reviewer changed both its request path and its response-envelope key with the suite staying green. Added a transport injection seam and seven `httpx.MockTransport` tests pinning the URL and the unwrap, plus a `CorpusReadError` wrapping transport, status, non-JSON and malformed-envelope failures. Rescoped `test_the_only_network_call_lives_in_one_place` to walk `harness/` only — at its original scope the guard and the missing test were in direct conflict.
  - `[medium]` `[patch]` The planted-timestamp range check covered only `decisions`; narrowing the loop to that one kind left the suite green. The three kinds now come from one shared `PLANTED_SECTIONS` tuple and the parametrization covers all five timestamp paths.
  - `[medium]` `[patch]` `Subject.title` and `Subject.viewable` were populated and never asserted — hardcoding either survived the suite. Both are now pinned, including a row built with `viewable=False`. Added `Subject.status`, the field the docstring says story 5.2 decides duplicates with.
  - `[medium]` `[patch]` An `ocr_anchor` normalizing to nothing (`"---"`, `"   "`) passed validation and could never be recalled. Rejected, naming the entry.
  - `[medium]` `[patch]` Duplicate `participant_segments[].at` values inflated the recall denominator, putting 100% out of reach. Rejected, naming both.
  - `[medium]` `[patch]` `shown_at` was optional on `screens`, which checks 2.3 and 2.5 both need. Required on `screens`, left off `slides`, matching eval-design §1.
  - `[medium]` `[patch]` eval-design.md §1 contradicted the schema it is the source for — no `meeting.source_id`, and a combined `slides:`+`screens:` example the schema rejects. Appended a dated schema note recording both, additively.
  - `[medium]` `[patch]` AGENTS.md named the store-free suites agents may run concurrently without listing `make evals-test`. Added.
  - `[low]` `[patch]` `manifest_paths` raised a bare `FileNotFoundError` on a missing directory and matched suffixes case-sensitively. Wrapped in `GroundTruthError`; suffix match is case-insensitive; discovery stays flat, pinned by a test.
  - `[low]` `[patch]` `load_manifest` caught only `yaml.YAMLError`. Now wraps `OSError` and `UnicodeDecodeError` too.
  - `[low]` `[patch]` With a known archetype and entries in the other section, the loader rules skipped them, contradicting `validate_manifest`'s promise to report every problem in one pass. Both sections are walked when present.
  - `[low]` `[patch]` `test_fixtures_validate.py` loaded at module import, so a broken fixture errored collection and the guard-on-the-guards never ran. Loads lazily now.
  - `[low]` `[patch]` The fixture-count assertion derived both sides from one discovery call and could not fail. Filenames are pinned explicitly.
  - `[low]` `[patch]` Makefile help listed the suites in a different order than the prerequisites, and the README layout block omitted the package inits and `conftest.py`. Both corrected.
  - `[low]` `[patch]` Exact-match anchor uniqueness against check 2.1's fuzzy ≥ 0.8 leaves a residual collision risk that nothing recorded. Documented in the schema description and the README; added tests pinning what `normalize_anchor` does with underscores and non-ASCII punctuation.
  - `[low]` `[patch]` `CorpusMismatch.describe()` rendered an absent `corpus` key as the string `'None'`. Distinguished from a real tag; added `UnmatchedManifest.describe()` and `Selection.problems()` for symmetry.

## Design Notes

**`meeting.source_id` is an addition to eval-design §1.** The §1 example keys the manifest on
`meeting.id: demo-001` and says nothing about `sourceId`, but the story's acceptance and AD-16 both
require matching manifests to ingested meetings *by `sourceId`*. Rather than overload `meeting.id`
(which is the manifest's own human-facing label and appears in reports), the schema adds a required
`meeting.source_id` holding the drop's `sourceId`. Assumption under attack: that the scripted drop's
`sourceId` is knowable at authoring time. It is not, until the meeting is pulled — hence placeholder
values in the shipped fixtures and an explicit `unmatched` result from the selector rather than a
silent empty subject list.

**Validation is two-layer on purpose.** JSON Schema carries shape, enumerations and required-ness;
the loader carries every rule that spans entries (anchor uniqueness, id uniqueness, `expected_moment`
references, timestamps inside `duration_minutes`) because JSON Schema cannot express them. Both
layers report through one `validate_manifest` list so an author sees every problem at once.

**Anchor normalization matches the check that will consume it.** eval-design §2.1 normalizes OCR text
to lowercase, collapsed whitespace, stripped punctuation before matching. Uniqueness here uses the
same normalization, so two anchors that would be indistinguishable to check 2.1 are rejected at
authoring time rather than silently colliding during a run.

```python
@dataclass(frozen=True)
class Manifest:
    ...
    @property
    def expected_screenshot_count(self) -> int:
        return len(self.entries) + len(self.participant_segments)
```

## Verification

**Commands:**
- `make evals-test` -- expected: the new eval suite passes; needs no Docker store and no running API.
- `uv run --project server pytest evals/tests -q` -- expected: same suite, run directly; all pass.
- `uv run --project server pytest server/tests/test_drop_schema.py -q` -- expected: unchanged and
  passing, proving the new schema did not disturb the existing one (store-free).
- `make web-test` -- expected: unchanged and passing (store-free sanity that the Makefile edit did
  not break delegation).

### Review Findings

- [x] [Review][Patch] Reject non-finite meeting durations [evals/harness/groundtruth.py:379]
- [x] [Review][Patch] Do not silently skip broken manifest symlinks [evals/harness/groundtruth.py:461]
- [x] [Review][Patch] Reject non-object rows from `GET /meetings` [evals/harness/subjects.py:225]
- [x] [Review][Patch] Match the specified lowercase anchor normalization [evals/harness/groundtruth.py:111]
