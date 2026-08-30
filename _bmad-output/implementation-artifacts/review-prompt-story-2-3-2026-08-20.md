# Reviewer handoff — Story 2.3: Meeting Drill-Down with Screenshot Series (2026-08-20)

You are reviewing with none of the build run's context. Everything you need is named here.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (work the branch in its worktree
  `/Users/devopsterus/current/cohort/meetingminer-wt/2-3` if it still exists, or check out the
  branch fresh — never review in another story's working tree).
- Branch: `story/2-3` (pushed; upstream `origin/story/2-3`).
- Review range: `c61e9175f6f5d532520ecfd9c72dbd629d0614ed..80cb6cc` — seven commits:
  - `7de00d1` docs(2-3): plan meeting drill-down with screenshot series (the spec)
  - `8fe76cf` feat(api): meeting drill-down route with enriched 409
  - `7df564f` chore(client): regenerate TS client with getMeetingDrilldown
  - `5907187` feat(web): rebuild meeting view on the drill-down
  - `6d25ac9` docs(deferred): mark the 1.9 server-side gate obligation resolved
  - `e43c355` fix(2-3): apply review triage patches (15 findings from the build run's own review)
  - `80cb6cc` docs(2-3): record review triage and auto-run result
- Below the base, the branch also carries `33b4eb4` (regenerated `epic-2-context.md`) and a merge
  of main's sprint-claim commit — docs only, different concern, not part of this story's review.

## Spec and what you may critique

- Spec: `_bmad-output/implementation-artifacts/spec-2-3-meeting-drill-down-with-screenshot-series.md`.
- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O & Edge-Case Matrix) is
  frozen intent distilled from `_bmad-output/planning-artifacts/epics.md` §Story 2.3 — judge the
  code against it, and judge *it* only against the epics story text.
- Everything below `</intent-contract>` — Code Map, Tasks, Design Notes, the triage log — is
  planner/builder work. Critique freely.

## Architecture authorities that govern this change

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:
  - **AD-14** — an augmenting run must be distinguishable at the API from a never-ingested meeting,
    derivable from `job.status` + stage rows with no schema change; empty states must never key on
    `viewable` alone. This story's `augmentation_in_flight` predicate is the discharge; attack it.
  - **AD-5** — table ownership: this story must be a pure read (an AST-walk test enforces no store
    clients in `api/`).
  - **AD-3** — relative paths only; `screenshotPath`/`sourceDeepLink` must never leak a root or
    server-built URL.
  - **AD-15** — consumers render from structured data, never trust markup: the client-side
    `highlightRuns` and the raw-`provenance` deep link (guarded by web `safeHref`) both lean on it.
- `server/meetingminer/domain/jobs.py` comments (AUGMENTATION_STAGES excluding `extract`) are the
  factual basis for the predicate's soundness argument.

## Scope

In scope (the story's file boundary):
- `server/meetingminer/domain/jobs.py`, `server/meetingminer/api/moments.py`
- `server/tests/{test_domain_jobs.py,test_api_moments.py,projection_seed.py}`
- `web/src/features/moments/*`, `web/src/client/*` (generated), the five web test mock factories
- `_bmad-output/implementation-artifacts/{spec-2-3-*,deferred-work.md}`

Out of scope:
- Story 2-6's files (`api/ingests.py`, `config.py`, `api/main.py`) — in flight, untouched here.
- Media caching validators (`ETag`/`Last-Modified`) — story 2.1's deferred item, deliberately
  re-declined in this spec's Never list; flag only if you think the re-declination is wrong, not
  as a missing feature.
- Pagination of the drill-down payload — recorded as this spec's own `deferred` frontmatter item.
- Epic 4 artifact rendering, topic data models, any capture-side behavior.

## Design decisions to attack (the planner is not a neutral judge of these)

1. **Augmentation = out-of-order stage settlement.** Choice: `augmenting` is true iff a `done`
   stage follows an unsettled evidence stage in `STAGE_NAMES` order. Rests on: first ingests
   settle strictly in order (skips are an intake-time prefix) and both augmentation tuples exclude
   `extract`, so a settled `extract` above re-queued evidence stages is the signal. Known blind
   spot pinned conservative: a pre-4.1 job whose `extract` never settled reads as first ingest.
   Tested only against snapshots built from the real tuples — never against a live mid-augmentation
   run.
2. **Highlighting is a drill-down-local input, client-side.** Choice: no carried-over search term,
   no topic mentions, no Meilisearch. Rests on: the epics AC's "search-term **or** topic mentions"
   disjunction, the absence of any topic data model, and the index being moment-grained. The
   intent-alignment audit called this the largest interpretive narrowing in the change.
3. **The moments list is replaced, not kept.** Choice: 2.2's meeting view (`MeetingMoments`) was
   rebuilt as the drill-down; every live moment stays reachable (segments via `moment_segment`,
   screen-derived moments via their screenshot). Rests on: redundancy of a bare list beside a full
   transcript. Consequence: `listMeetingMoments` remains a served API route with no web consumer.
4. **Drill-down route on the moments router.** Choice: no new module/`include_router`. Rests on:
   avoiding the `api/main.py` chokepoint while story 2-6 is in flight. Cost: `moments.py` grows.
5. **Raw meeting-level `sourceDeepLink`.** Choice: `provenance->>'url'` verbatim (unvalidated at
   write, unlike moment links); web `safeHref` is the only guard. Rests on: the 2.2-litigated
   affordance pattern being sufficient.
6. **409 extensions untyped.** Choice: `augmenting`/`jobStatus` ride as free-form RFC 9457
   extensions (house pattern since 2.2's `meetingId`), pinned by parallel server and web tests
   rather than a shared generated type.
7. **`notViewableMessage` precedence failed → augmenting → preparing**, changed by review patch
   from the build's original augmenting-first ordering.

## History you need to tell regressions from pre-existing conditions

- `MeetingMoments.tsx` and its tests were rewritten wholesale in `5907187` — diff-reading it as
  edits will mislead; compare behavior, not hunks. The 2.2-remediation regression pins (stale
  response suppression, hang tests, untyped-null handler) were deliberately preserved/restored —
  their absence anywhere would be a regression.
- The generated client was regenerated twice via the 2.2-pinned fallback (schema dump +
  `pnpm --dir web run client -i`) because :8000 served another checkout's api; `types.gen.ts`
  carries the literal `baseUrl` drift already recorded as a 2.2 deferred item — pre-existing, not
  this story's.
- The spec's AC5 (server-side gate) was mostly discharged by story 2.2; this story added the
  meeting-detail half and flipped the `deferred-work.md` entry — the gate logic itself is 2.2 code.
- The implementation agent ran `make migrate` against the shared dev database (additive `0009`,
  already on main) to boot the branch api for its manual check.

## Verification baseline (all run by the build workflow owner after the patches)

- `cd server && .venv/bin/python -m pytest tests/test_domain_jobs.py tests/test_api_moments.py -q`
  → 47 passed (11 + 36).
- `cd server && .venv/bin/python -m pytest tests/ -q` → 1190 passed, 0 failed, 0 skipped, 4m52s
  (safe to run concurrently with other worktrees; per-run database — AGENTS.md).
- `make web-test` → 156 passed, 9 files. `pnpm --dir web run lint` → clean bar the pre-existing
  `button.tsx` fast-refresh warning. `pnpm --dir web run build` → clean.
- Manual end-to-end on the real corpus (implementation agent): 122-screenshot series in order,
  35 highlight marks, single moving inline player, 206 replay at offset, transcript-only degraded
  mode, 404/422 live. Any deviation you observe from these numbers is a finding, not noise.

## Required output

Write findings to `_bmad-output/implementation-artifacts/review-story-2-3-2026-08-20.md`:
frontmatter with a verdict, then one section per finding — severity, file:line, what is wrong, why
it matters, and the evidence — followed by a section listing what you verified clean. **Report
findings; do not apply fixes.** The build run's own review already patched 15 findings (triage log
in the spec) — re-raising one of those unchanged is noise, but attacking a patch's adequacy is in
scope.
