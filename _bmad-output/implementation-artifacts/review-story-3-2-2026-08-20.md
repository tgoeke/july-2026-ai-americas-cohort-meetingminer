# Code review — Story 3.2: Graph Traversal Templates

Date: 2026-08-20

## Review target

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Review handoff: `_bmad-output/implementation-artifacts/review-prompt-story-3-2-2026-08-20.md`
- Original branch/range: `story/3-2`, `444469d..HEAD`, as recorded in the
  handoff. The branch was subsequently rebased for integration; the completed
  work is in `main` at merge commit `e3a8fe7`.
- Frozen contract:
  `_bmad-output/implementation-artifacts/spec-3-2-graph-traversal-templates.md`
- Architecture authority: AD-4, AD-6, and AD-7 in
  `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`.

## Initial findings

The review found five actionable issues. All were fixed during this review;
the remediation and verification are recorded below. Findings that merely
repeated frozen design choices or were not reachable on the story's consumer
path were dismissed rather than converted into speculative work.

### 1. Same-offset rows had no final deterministic tie-break

- **Location:** `server/meetingminer/projections/traversals.py:158,174`
- **Severity:** medium
- **Finding:** Both Cypher statements ended their ordering at `mo.startMs`.
  Two distinct moments in one meeting can validly share that offset, leaving
  Neo4j free to return them in an arbitrary order.
- **Evidence:** The initial screen-history tests covered cross-meeting
  `startedAt` and `meeting.id` ties, but no fixture created two matching
  moments with the same `startMs`. The participant template had the same
  ordering statement.
- **Why it matters:** Story 3.3 presents traversal rows to the answer
  orchestrator, and Epic 5 compares deterministic retrieval results. A
  nondeterministic order can shuffle otherwise identical evidence between
  requests.

### 2. Offset-aware non-UTC timestamps passed the ordering guard

- **Location:** `server/meetingminer/projections/traversals.py:265-274`
- **Severity:** medium
- **Finding:** `_moment_of()` rejected a naive `meetingStartedAt`, but accepted
  any offset-aware timestamp. Lexical comparison is chronological only when
  the projection uses its required UTC representation, so a corrupt `+01:00`
  value could be returned in the wrong temporal position.
- **Evidence:** `datetime.fromisoformat("2026-08-05T12:00:19+01:00")` passed
  the original `tzinfo is not None` guard. The initial handoff explicitly
  identified this as design assumption 6.
- **Why it matters:** Incorrect time order causes Story 3.3 to synthesize from
  misleading chronology and makes the graph leg unsuitable for an exact-order
  retrieval assertion.

### 3. Invalid moment intervals reached the typed result surface

- **Location:** `server/meetingminer/projections/traversals.py:280-285`
- **Severity:** medium
- **Finding:** The parser established only that `startMs` and `endMs` were
  integers. It accepted negative offsets and `endMs < startMs` as valid
  traversal rows.
- **Evidence:** Before remediation, a canned row with `startMs=-1` and
  `endMs=-2` returned a `TraversalMoment` unchanged.
- **Why it matters:** Story 3.3 passes retrieved context toward citations and
  replay consumers. An invalid range is projection corruption that should be
  named, never surfaced as an impossible playback interval.

### 4. Nullable display fields were not type-checked

- **Location:** `server/meetingminer/projections/traversals.py:278,287,352-353`
- **Severity:** low
- **Finding:** `meetingTitle`, `sourceDeepLink`, `screenLabel`, and
  `screenViewType` were copied directly from Neo4j even though the public
  dataclasses declare them as `str | None`.
- **Evidence:** Before remediation, a canned graph row carrying a list in
  `sourceDeepLink` produced a `TraversalMoment` containing that list.
- **Why it matters:** The story is the router-facing typed boundary for Story
  3.3. Permitting arbitrary graph values past it makes later display and
  citation-context code handle malformed projection data without a named
  failure.

### 5. Rowan traversal ordering lacked a behavioural regression test

- **Location:** `server/tests/test_projections_traversals.py:415-458`
- **Severity:** low
- **Finding:** The participant-topic test had only one matching result, so it
  could not prove the participant template's required time ordering.
- **Evidence:** Removing or changing its `ORDER BY` could leave the original
  one-row test green, unlike the screen-history ordering test.
- **Why it matters:** Story 3.3 relies on both templates, not just screen
  history. Epic 5 needs deterministic graph retrieval under multi-meeting
  participant questions.

## Remediation outcome

All five findings were fixed in the review remediation (`fe32888` before
rebase; integrated equivalent `c137881`).

1. Both templates now order by `meeting.startedAt`, `meeting.id`,
   `mo.startMs`, and `mo.id`; a store-backed same-offset screen-history test
   pins the final key.
2. `_moment_of()` now requires an aware zero-UTC-offset timestamp and raises
   `ProjectionError` for non-UTC graph data; a canned-driver test covers it.
3. Negative or inverted moment intervals now raise named `ProjectionError`;
   tests cover both forms.
4. Nullable graph string properties now pass through `_nullable_string_of()`
   and reject non-string values with `ProjectionError`; canned-driver tests
   cover all four fields.
5. A two-meeting SFTP fixture independently proves
   `participant_topic_moments()` returns rows in deterministic time order.

The fixed findings are checked off in the contract's `### Review Findings`
section.

## Dismissed observations and design-assumption audit

- **SHOWS-only screen history (assumption 1):** safe for this story. It is the
  frozen, previously recorded `Screen ← Screenshot ← Moment → Meeting` shape;
  extending it through `SHOWN_DURING`/`COVERS` would change the contract.
- **Verbatim, case-insensitive topic substring (assumption 2):** safe for this
  story. The frozen contract expressly requires `toLower(...) CONTAINS` and
  assigns semantic/paraphrase matching to the search lane.
- **`ATTENDED` rather than `SPOKE_IN` (assumption 3):** safe. It implements the
  listener interpretation required by the Rowan example.
- **UUID template inputs (assumption 4):** safe. Name-to-id resolution is
  explicitly Story 3.3 scope, not an omission in these deterministic
  templates.
- **One-round-trip anchor/empty split (assumption 5):** safe. The live tests
  distinguish unknown anchors from resolved empty results for both templates.
- **UTC lexical ordering (assumption 6):** was unsafe at the typed read
  boundary and is now guarded; the projection remains required to write UTC.
- **AC4 proxy inspection (assumption 7):** retained as a documented residual
  risk, not a current contract violation. The review inspected this story's
  new code and found no second retrieval execution path; the specific required
  denylist test remains present.
- **No result limit/config knobs (assumption 8):** safe for the exact-set,
  demo-sized contract.
- **Store-backed traversal testing (assumption 9):** environment-dependent by
  design. The stores were available for this review and the live tests ran;
  a named skip when infrastructure is down remains an explicit contract fact.

## Verification performed

The newly added corruption tests were first confirmed against the unfixed code
with a canned driver: an offset-aware non-UTC timestamp, negative/inverted
offsets, and a list-valued `sourceDeepLink` all returned as normal rows before
the remediation.

Post-remediation commands and results:

- `uv run --project server pytest server/tests/test_projections_traversals.py`
  — **32 passed**, 0 skipped.
- `uv run --project server pytest server/tests/test_projections_graph.py server/tests/test_projections_single_writer.py`
  — **20 passed**.
- `uv run --project server pytest server/tests` — **1195 passed**, 0 failed;
  one pre-existing third-party Starlette/httpx deprecation warning; 384.32s.

The live Neo4j-backed tests ran under the repository's cross-process
projection-store lock. No `make evals-run` was run.

## Final verdict: pass

All four Story 3.2 / Epic 3 acceptance criteria hold as implemented:

1. Screen history uses registered, parameterized Cypher and returns the
   required complete, deterministic temporal history.
2. Participant-topic traversal follows `ATTENDED`, returns only attended
   meetings' matching moments, and exposes the participant identity key.
3. Traversal result moment ids remain parsed Postgres-minted UUIDs, with live
   seeded-store coverage.
4. The registry contains exactly the two templates, dispatches through
   `run_template`, and the required graph-library import guard passes.

No high- or medium-severity finding remains. The review report itself made no
production-code change; all later code changes are the documented remediation.
