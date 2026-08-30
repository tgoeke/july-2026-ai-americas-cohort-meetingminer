**FIRST: file the report before reading any code.**

Create `_bmad-output/implementation-artifacts/review-story-2-4-2026-08-21.md`
as a skeleton — scope, range, an empty findings section — and commit it
*before* you read a single line of the diff. As you confirm each finding,
append it and commit again. A crashed or closed session must lose prose,
never the artifact; six prior reviews here were lost because the file
requirement sat at the end of a long prompt and got compacted out of context
before the review finished.

Each finding: **Location** (`file:line`) / **Severity** / **Finding** /
**Evidence** / **Suggested direction**. Report findings — do not fix them.

**Before you report completion**, run `make check-reviews` (it fails while
any dispatched review, including this one, lacks a committed report) and
state the exact commit SHA carrying the report's final version. A review
reported only in the terminal does not exist.

---

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`, worktree at
  `../meetingminer-wt/2-4` (or `make worktree STORY=2-4-review` for a fresh
  one — never review in the shared checkout).
- Branch: `story/2-4`.
- Review range: `9f9d895..57b9359` (`git log --oneline 9f9d895..HEAD`):
  - `57b9359` docs(2-4): close story — verified, Auto Run Result, status done
  - `0f363cc` fix(2-4): close review findings — locking, timestamps, per-row errors
  - `566d8ef` docs(2-4): record review triage — 6 patch, 3 defer, 3 reject
  - `30b0639` docs(2-4): begin review
  - `e36e0ce` docs(2-4): record verification results and the blocked backfill
  - `aeebe65` feat(2-4): participant curation API and web screen
  - `fbdcdb9` docs(2-4): begin implementation
  - `89b0128` docs(2-4): spec passes ready-for-development gate
  - `1bffbd7` docs(2-4): draft spec for participant curation

All nine commits belong to this story; none in the range belongs to another
story.

## Spec

`_bmad-output/implementation-artifacts/spec-2-4-participant-curation.md`.
The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O &
Edge-Case Matrix) is frozen intent — critique it, but a disagreement with it
is a finding about the plan, not license to treat it as wrong by assumption.
Everything below `</intent-contract>` (Code Map, Tasks & Acceptance, Design
Notes, Verification, Auto Run Result) is planner/implementer work product,
fully open to challenge.

This spec already went through one internal review pass inside the same
run that built it (four parallel automated review layers — a context-free
"find what's missing" hunter, an edge-case hunter, a verification-gap
hunter, and an intent-alignment auditor — see `## Review Triage Log` and
frontmatter `deferred:` in the spec for what they found and how it was
triaged: 6 patched, 3 deferred, 3 rejected). Do not treat that pass as
authoritative — re-derive your own findings from the diff — but do read it
first so you spend your attention on what it did *not* already catch, not on
rediscovering the same six items.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`,
**AD-5 ("Table ownership is disjoint")** specifically: the worker writes
`participant` rows during intake; the API owns human-curated columns
(`display_name` edits) and merge records (`participant_alias`, `alias_key →
surviving participant id`); the worker resolves an identity key through the
alias table before every insert, so a merge survives re-ingests and stage
reruns. This story's entire design is a literal reading of that one
sentence — check it against the rule, not just against the spec's own
restatement of it.

## Scope

**In scope:** `server/meetingminer/api/participants.py` (new router: list,
rename, merge), its tests (`server/tests/test_api_participants.py`, new
seed helpers in `projection_seed.py`), the web curation screen
(`web/src/features/participants/*`), the one `web/src/App.tsx` entry-point
edit, every SDK mock factory extended, the regenerated TS client, and
`_bmad-output/implementation-artifacts/deferred-work.md`'s 1.13 fold-in
entry update.

**Out of scope, do not review as if it should have changed:**
`server/meetingminer/pipeline/stages/align.py` (read-only reference for this
story — its alias-consuming behavior already existed before this story and
was verified by reading it, not by writing an integration test; that gap is
already recorded as a deferred item, see below), `server/meetingminer/api/
ingests.py`/`config.py`/`api/main.py` (story 2-6's chokepoint, unrelated and
already closed), any Neo4j/Meilisearch projection code (this story
deliberately writes Postgres only, per AD-5 and the AST-walk guard in
`test_projections_single_writer.py`).

**Called out separately:** none of the nine commits in range belong to a
different story — this is a clean single-story range.

## Design decisions to attack

- **READ COMMITTED instead of REPEATABLE READ on the write routes**
  (`rename_participant`, `merge_participants`), a deliberate deviation from
  the spec's own "Always" text, which said to mirror `moments.py`'s
  REPEATABLE READ pattern. The reasoning: `FOR UPDATE OF p` locks the
  participant row(s) a request touches, but under REPEATABLE READ the
  post-lock `_is_aliased` check would still see the snapshot taken when the
  transaction opened — stale, defeating the point of the lock. READ
  COMMITTED gives that check a fresh read after the lock wait resolves. This
  was added during the review-patch pass, verified by a real two-thread
  `threading.Barrier` concurrency test, not by sequential awaits. Attack
  both the reasoning and whether the test actually proves it (does it
  reliably create the race, or could it pass by accident on a fast
  machine?).
- **No chained aliases, enforced by requiring both merge sides to be
  canonical.** A user wanting A→B→C must merge A directly onto C once B→C
  exists, rather than the API resolving the chain for them. Attack whether
  this pushes real complexity onto the curator UI (which today does let a
  user pick any other canonical row as a target, with no visual indication
  that "C" used to be a merge target for someone else) versus whether
  chain-resolution server-side was rejected for a good reason (keeping
  `align.py`'s single unconditional lookup un-recursive).
- **Merge is forward-looking only — no rewrite of `meeting_participant`/
  `transcript_segment` for already-ingested meetings.** The assumption is
  that AD-5's stated mechanism (alias table, worker reads it before every
  insert) is what "survives re-ingests" means, and that immediate
  convergence of already-ingested evidence was never promised. Attack
  whether a curator using this screen would reasonably expect a merge to
  take effect immediately everywhere, and whether the UI's copy
  ("A merge only reaches already-ingested meetings at their next re-ingest
  or projection") is prominent enough to prevent that false expectation.
- **`GET /participants` returns every row unconditionally, merged-away
  included, with no pagination.** Rejected as out of scope for this pass
  (matches an existing deferred-work.md pattern for `GET /meetings`), but
  check whether the corpus's actual current row count (order of 100 rows
  today) makes this a non-issue for now or whether it's already marginal.
- **The web curation screen has no merge confirmation dialog and no
  unmerge/undo capability anywhere in the API.** Deferred in the internal
  review pass as medium severity. Attack whether that severity call was
  right — is an irreversible-in-the-UI action with real (if bounded)
  consequences an acceptable ship, or does it need to block?

## History the reviewer needs

None — this is new code on a new file, not a modification of prior
behavior. There is no rebase, no dropped variant, no superseded baseline to
account for. The two prior commits' Verification-section text
(`e36e0ce`, before the patch pass) describes an earlier, since-superseded
state (no row locking, no `updated_at` exposure, ephemeral `/tmp` backfill
list) — read the *current* file state and the *final* Verification section
appended by `57b9359`, not the intermediate one, if you open the spec's
history rather than just its HEAD content.

## Verification baseline

Every command below was run directly by the orchestrating session after the
patch pass, not accepted second-hand from either implementation subagent:

- `cd server && .venv/bin/python -m pytest tests/test_api_participants.py -q`
  — 15 passed.
- `cd server && .venv/bin/python -m pytest tests/ -q` — run twice: 1521/1518
  passed. The 1–4 failures each time were confined to `test_api_chat.py`
  (Meilisearch `index_primary_key_multiple_candidates_found`) or
  `test_parallel_store_safety.py` (the cross-worktree projection-lock
  timeout test) — both reproduce only under concurrent-worktree store
  contention (documented in this repo's `AGENTS.md`) and both passed
  cleanly in isolation. No participants-related test failed in any run. If
  you see either of those two tests fail again during your own review run,
  treat it as the same known environmental flake, not a regression — but
  confirm by rerunning that one file in isolation before dismissing it.
- `pnpm --dir web run test -- run` — 197 passed, 12 files.
- `pnpm --dir web run lint` — clean bar two pre-existing fast-refresh
  warnings (`button.tsx`, `MomentView.route.tsx`/`MeetingMoments.route.tsx`).
- `pnpm --dir web run build` — clean.
- Matrix Test Audit: all 11 I/O-matrix rows in the spec have a covering test,
  and every covering test ran and passed.
- **Not verified by a fresh manual pass in this run**: the implementation
  agent's own dev-stack manual check (open `/participants`, rename, merge)
  is recorded in the spec but was not independently repeated by the
  orchestrating session after the patch commit landed — if you have the dev
  stack available, that manual pass is worth doing fresh.
- **Known incomplete, not a code defect**: the one-time 46-pair
  orphaned-participant backfill this story folded in from `deferred-work.md`
  is 1/46 merged. The remaining 45 are blocked by this environment's
  tool-use policy on repeated write-mutation Bash calls (confirmed
  independently, twice). The reproducible pair list is committed at
  `[redacted participant mapping artifact]`.
  This is not something to flag as a review finding against the code — it is
  an operational task for whoever picks this up next, already durably
  recorded in `deferred-work.md`'s fold-in entry.

---

The report path is
`_bmad-output/implementation-artifacts/review-story-2-4-2026-08-21.md`. It is
ready to hand to the Codex `bmad-code-review` agent.
