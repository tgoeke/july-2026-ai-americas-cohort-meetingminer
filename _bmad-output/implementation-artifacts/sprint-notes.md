# Sprint notes

Narrative that used to live as comments inside `sprint-status.yaml`, keyed by
the same story ids.

**Why it moved.** That file is merged by a custom driver
(`_bmad/scripts/merge_sprint_status.py`) so two branches advancing two different
stories stop conflicting. The driver merges *values* by key and takes the
surrounding text from `ours` — which means a note added on the other branch is
**silently dropped**. Narrative therefore cannot live there safely. Here it
merges like any other prose: cleanly when two branches touch different notes,
and with a visible conflict when they touch the same one, which is correct.

Keep `sprint-status.yaml` to `story-id: status` lines. Put the reasoning here.

---

## Dispatch and sequencing

**DISPATCH RULE (standing user direction, 2026-08-19).** Stories are recommended
for parallel work ONLY when they are completely caveat-free and completely
independent. A recommendation carrying conditions ("coordinate the store-backed
suites", "the files are mostly disjoint") is NOT a parallel recommendation —
give it as a sequence instead.

**Test-harness status: fixed (story 2.7, merged 2026-08-20).** Store-backed
suites may now overlap. Each run owns a per-run Postgres database; the
projection tests queue on a bounded cross-worktree file lock. `make evals-run`
is still one at a time.

**But the harness was not the only chokepoint.** `server/meetingminer/api/main.py`
now is. Every API story appends an `app.include_router(...)` line, and those
lines are adjacent (107-118) — so two API stories conflict there for exactly the
reason two stories used to conflict in `sprint-status.yaml`: proximity, not
disagreement. `web/src/App.tsx` is the same shape on the front end; it has no
router at all, so any story adding a page edits it.

Measured against the rule, that leaves:

| story | touches | caveat-free with |
| --- | --- | --- |
| `2-1b` | `pull_transcript/`, `docs/` only | **everything** |
| `3-1` | new search modules + `api/main.py` + `App.tsx` | 2-1b |
| `2-2` | new moment modules + `api/main.py` + `App.tsx` | 2-1b |
| `2-6` | `api/ingests.py`, `config.py`, `api/main.py:62` | 2-1b |

So a genuinely caveat-free pair today is **2-1b plus exactly one server story**.
A caveat-free trio does not exist while `api/main.py` is edited by hand.

Two ways forward, and the second is the same force-multiplier bet story 2.7
turned out to be:

1. Run 2-1b + one of {3-1, 2-2, 2-6}, then the next, sequentially.
2. First make router registration auto-discovering (and give the web app a real
   router), removing the shared-file edit — after which all four are caveat-free
   in parallel.

**Order when sequencing** (unchanged): 3-1 is the longest pole on the demo path;
2-2 is the other half of it and does not wait on Epic 4 (its right rail has an
explicit empty state); 2-1b closes the eval gap by minting drops from the two
NDA recordings that replace story 5.2's placeholder `source_id`s; 2-6 is a small
isolated defect fix.

**The live demo is one path only** (SPEC: ~3 minutes, CAP-3 -> CAP-4): ask the
corpus, get a cited answer, open the moment, replay it. That is Epic 3 plus 2-2
and nothing else in Epic 2. Epic 3 is four stories, all backlog — it is the
schedule risk, not Epic 2's tail.

---

## Epic 2

### `2-1-media-streaming-replay-foundation` — done
Reviewed, passed, and merged to main (`review-story-2-1-2026-08-19.md`; merged
head `eff0a75`). The conformance work the review split out is tracked as 2-1a,
so leaving 2-1 in-progress would advertise a story nobody is working on.

### `2-1a-evidence-paths-anchored-to-configured-roots` — done
Storage-layout conformance, split out of the 2.1 review. Replaces the withdrawn
`2-1-recording-under-the-content-root` (drafted on branch `story/2-1`): the
recording is NOT copied under the content root — both roots become configured
anchors instead. See `specs/spec-meetingminer/storage-layout.md`.

Applied to the running dev environment 2026-08-19: migration `0008`, then
`make backfill-drop-paths` converted 29 jobs, 51 transcript paths and 8
recording rows with 0 unplaceable. **Ordering matters and is not obvious** — the
backfill must run *before* the api and worker are restarted onto 2.1a code.
Restarting first makes the worker fail every job for a missing
`drop_relative_path`; recoverable (the backfill re-queues them) but it turns a
clean migration into 29 failures.

### `2-1b-bring-your-own-recording-drops` — done
On landing, unblocks importing the recordings the corpus lacks: 9 that augment
existing transcript-only meetings, plus the 2 NDA demo recordings story 5.2's
eval fixtures need. User decision 2026-08-19: wait for 2.1b, then bring them
over. See `deferred-work.md`.

### `2-4-participant-curation` — in-progress
Carries the alias backfill discovered by the 2026-08-19 participant pass: 48
orphaned `name:`-keyed rows, 46 of which map 1:1 to a mail-keyed row. AD-5
assigns `participant_alias` writes to the API and no path exists yet, so this
story owns both the merge path and the one-time backfill. Details and the 2
unmappable rows: `deferred-work.md`.

Independent review on 2026-08-21 remediated the API/UI findings and amended
the write-isolation contract by owner decision. The story remains in progress
because the required production backfill is still 1/46 complete; finish the
remaining 45 API merges before it can return to done.

**Landed on `main` 2026-08-21 at `c6afab2`** (fast-forward from
`story/2-4-review`, rebased onto `main` after 4-2). Status stays
`in-progress` by owner decision — the code is merged; the story closes when
the 45 remaining backfill merges are done. Review report
`review-story-2-4-2026-08-21.md` is committed, verdict: all eight code
findings patched and verified; `make check-reviews` passed on the branch and
after the merge. The report does not name the tool that ran it — the handoff
commit (`21a58ad`) targeted the Codex reviewer, and the review commits are
authored under the user's name as usual; recorded here per the
check-reviews-provenance lesson rather than re-verified.

Rebase conflicts and how they were resolved: `test_api_registry.py`'s
baseline route list unioned (`extraction` from 4-2, then `participants`,
both at default order, name tie-break — pinned by the ordered baseline
test); `web/src/client/*` regenerated from the rebased code's in-process
OpenAPI schema (the API on :8000 serves pre-2-4 code, so `make client`
against it would have dropped the participants routes) and committed, so
`make client` is not owed. Suites on the rebased branch: participants +
registry + prompts API (28), projection-seed dependents
`test_projections_traversals.py` + `test_api_moments.py` (68), web 202/202,
web build — all passed.

**Post-merge operations owed: none.** No migration (`participant_alias`
exists since `0005`), no projected field, client committed. The worker
stayed stopped; the restart hold stands.

**What the backfill needs, for whoever runs it:** the running API predates
this merge, so `/participants` is not live until the next deliberate API
restart (mind the `MM_PUBLISH_ROOT` fail-fast gate and the placeholder
worktree `.env` note under 4-5). Then 45 merge calls from
`[redacted participant mapping artifact]` (1 of 46 already done).
The high-severity chained-alias fix means order within the CSV cannot create
chains; each call is an independent API merge.

`origin/story/2-4-review` still points at the pre-rebase tip `f7732ac`
(force-push declined), so ancestry checks against it report "not merged";
the landed content is `c6afab2`. Both remote 2-4 branches await a deletion
yes.

**Remote branch cleanup DONE (2026-08-21).** All four branches deleted on
user instruction, with the 2-4 pair verified superseded (content landed via
the rebase) rather than ancestry-merged, and the 4-2 pair ancestry-merged.
The `2-4` and `2-4-review` worktrees and local branches are removed too.
Recovery SHAs, should any be wanted back (`git branch <name> <sha>`):

    story/4-2          65eaf65cad392360b60c2d00897dcae5f1120276
    story/4-2-review   52f56e71890880c446cad7f6cda775e36201962e
    story/2-4          21a58ad8df496da9030da34b4c805cbbbe259453
    story/2-4-review   f7732ac9ab3ca34b4ac179eac2dd9675b1f6f8d9

**Backfill COMPLETE — story done, 2026-08-21.** The user ran the API restart
and drove all 45 remaining merges from
`[redacted participant mapping artifact]` through
`POST /participants/{id}/merge` (the loop from the integration session; every
call returned ok). Verified through `GET /participants` on the live API: 46
rows carry `mergedIntoParticipantId` (45 + the 1 pre-done), and 0 survivors
are themselves merged rows — the alias map is flat, as the chained-alias fix
requires.

**Six `name:`-keyed rows remain unaliased, and all six are correct to leave.**
The two mononyms the mapping pass named (`name:venkatmylavarapu`,
`name:saitejaswi`) plus four orphans minted by ingests AFTER the 2026-08-19
pass: `name:taylor brooks`, `name:morgan hayes`, `name:riley parker`,
`name:Peyton Blake`. Checked against the live mail-keyed rows: none has a
directory counterpart (`Peyton Blake`'s only surname match is
`mail:cameron.blake@corp.com` — a different person, not a merge). They stay
unaliased under the same rule as the mononyms; the curation screen is the
path if counterparts ever appear. The CSV is a historical record of a
completed run, not a live worklist.

### Wave 3 merge coordination (2-3 / 3-2 / 2-6), 2026-08-20
`story/3-2` and `story/2-3` both changed `server/tests/projection_seed.py::seed_meeting`
divergently: 3-2 added a `started_at` parameter, 2-3 added `screen_view_types`.
**Whoever merges second must union both parameters** and re-run both suites
(`test_projections_traversals.py` and `test_api_moments.py`) — an auto-merge
that drops either breaks the other story's tests. 2-6 is clear of both.
Also: 2-3's implementation agent applied migration 0009 to the shared dev
database, so `make migrate` is already done there — the only remaining trigger
for the ~850-call extraction backfill is the deliberate worker restart.

### `story/2-3-remediation` — orphaned, superseded, do not land (2026-08-20)
`git branch --no-merged` lists `origin/story/2-3-remediation` (commit `d560e92`,
"remediate drill-down review findings") as unlanded while `sprint-status.yaml`
says `2-3` is done. Both are accurate: the commit is not an ancestor of `main`,
but its content arrived by another path and was then **improved**.

Checked file by file against `main`. Of the 7 files `d560e92` touched, 2 are
byte-identical (`test_api_moments.py`, `useJobEvents.test.tsx`) and the other 5
have `main` strictly ahead:

- `moments.ts` — the branch folds case **per character**
  (`character.toLowerCase()`); `main` folds the **whole string** and maps each
  lowercased code unit back to source code-point boundaries. Whole-string is
  the correct one: `'ΟΣ'.toLowerCase()` is `'ος'`, context-sensitively, and
  per-character folding loses that. `main` got there via `79c3426`
  ("preserve Unicode folding semantics", branch `story/2-3-review-fixes`),
  which post-dates the remediation.
- `moments.test.ts` — `main` carries the regression test for exactly that
  (`preserves whole-string lowercase semantics while mapping to source text`);
  the branch does not.
- `MeetingMoments.tsx` / `.test.tsx` — `main`'s aria-label is
  `Open moment at {where}: {segment.text}`; the branch's is the shorter
  `Open moment at {where}`.
- the remediation spec — `main`'s copy is 31 lines longer.

**Merging it would revert the Unicode fix and delete its regression test.**
It is a delete candidate, not a merge candidate. `story/2-3-review-fixes` is
likewise fully landed (story files byte-identical to `main`) and equally safe
to delete. `origin/story/2-3` is a plain ancestor of `main` and is the third.

**Cleanup DONE (2026-08-20).** All three remote branches deleted by the user,
and the local `story/2-3-remediation` with them. `origin` now carries `main`
plus the in-flight `story/3-3` and `story/4-1a` and nothing else. Recovery
SHAs, should any be wanted back (`git branch <name> <sha>`):

    story/2-3                5c7b735b380fe3c89ceb9a70a4162db488b785f3
    story/2-3-review-fixes   79c34267eed174f34e0be196d350f9ed47abad16
    story/2-3-remediation    d560e92da1c03d91b109b366c0347bc5404a823e

### Next-wave dispatch notes (3-3, 3-4, 4-1a), 2026-08-20
Recommended caveat-free trio once dispatched: 3-3 (api + Q&A engine), 3-4
(web chat UI — sequence after 3-3, same surfaces), 4-1a (worker-side, no
overlap). For 3-3's contract: `speakers` is searchable but NOT filterable in
the moments index — one line in `projections.search.moments.filterable` plus
a re-projection makes speaker a hard filter for queries like "where was Jordan
confused", which 3-3 should decompose as participant-traversal (3-2 registry)
∩ semantic search. Operational state: the worker is STOPPED by user decision
(paid-ops rule; Anthropic key revoked). Do not restart it before 4-1a lands —
the old per-moment extract would fail over to qwen3:32b and burn local
compute making wrong-granularity drafts. The two NDA ingests sit queued;
their evidence stages are free and run whenever the worker next starts.

### `make check-reviews` does not check who wrote the review, 2026-08-20
Found by the user after story 3-4 was merged on a review that did not meet the
bar. The gate asserts that a `review-story-<id>-<date>.md` exists for every
dispatched review prompt. It says nothing about provenance, so a review the
builder dispatched into its own Claude worktree passes it exactly like a real
one.

**House process, stated so it is not inferable-only:** independent review runs
in a **Codex** session. The builder writes the handoff prompt and stops; a
Codex `bmad-code-review` agent consumes it and files the report. The precedent
was already in the history — `0098a96` ("reviewer handoff prompt for the Codex
bmad-code-review agent") and `6c4bd43` ("close the builder/reviewer handoff
loop between Claude and Codex") — and story 3-4's own handoff prompt says it at
line 201. It was still missed by the builder and by integration, which is the
argument for writing it here.

**The distinction that caused the confusion**, confirmed by the 4-3 and 4-5
sessions: `bmad-build-auto`'s step-04 — four context-free Claude subagents
(blind-hunter, edge-case, verification-gap, intent-alignment) triaged into
patch/defer/reject — is the workflow's own quality loop, run against the diff
before handoff. It files no `review-story-*.md` and does not touch the gate.
It is not a substitute for independent review and was never claimed to be. What
went wrong in 3-4 was separate: a *fifth* Claude review dispatched into a review
worktree, which did file a report.

**Integration lesson:** a green `check-reviews` is not evidence of an
independent review. Read the report's Scope section and confirm which tool ran
it before merging. Making the gate check provenance — a reviewer/tool line in
the report, asserted by `check-reviews` — would close this properly; filed in
`deferred-work.md`. It is the third instance today of the same shape: a check
that asserts an artifact exists rather than that it agrees with what it stands
for (`check-client` versus a stale client; the committed-binding test versus a
model tag nothing serves).

### One hallucinated timestamp discards a whole meeting's extraction, 2026-08-21
First extraction failure of the authorized run, on the 14th meeting attempted.
The mechanism worked exactly as specified; the *granularity* is the question.

    stage extract failed: artifact A10 ('Provide sample data/mapping between
    Job/Task numbers and Project Charging Codes for ENA region') from the
    action-items document cannot be anchored: anchor 1:47:57 (6477000 ms)
    falls outside the meeting's moment span 0:18-1:44:20 (18000-6260029 ms)

**It is a hallucinated timestamp, not a moment-coverage gap.** Checked on
meeting `01a01a4e-c850-76d3-a1ab-ef4dc7a85877`: the last moment ends at 6260s
and the last transcript segment also ends at 6260s — they match exactly, so
moments cover the whole transcript. The model's anchor sits 217 seconds past
the end of the meeting itself, where no transcript content exists. The
prompt's grounding rule against invented timestamps does not fully hold on real
transcripts.

**The blast radius is the whole meeting.** That job now has **0 artifacts and 0
`extraction_source` rows** — the transaction rolled back the architecture
summary too, which had parsed fine and had nothing wrong with it. One bad item
out of roughly twenty discarded a complete extraction. The worker did not
wedge; it moved on to the next job, and the failed job's status is `failed`, so
it will not be re-claimed without a decision.

**The design choice is right and the granularity is worth revisiting.** The I/O
matrix deliberately chose "a named error rather than a dropped artifact",
because silently discarding an unanchorable item is the no-silent-zero failure
through another door. That reasoning holds. But there is a middle path the
contract did not consider: refuse the *single* artifact with a recorded, named
refusal — the same shape as `stage.extract.zero_artifacts` — and let the rest of
the meeting land. Failing the whole meeting protects nothing that per-artifact
refusal would not also protect, and it throws away good work.

Note also that no retry occurred. The spec gives the generate path one retry on
a *parse* failure; anchor resolution is a separate step and gets none. A
hallucinated timestamp is a sampling artifact, so a single retry would likely
have produced a valid one.

**Rate so far: 1 in 14 attempted (~7%).** If it holds, expect roughly 2 more
failures across the remaining 17. Re-measure at the end of the run before
treating that as the real rate.

### Extraction's two passes duplicate the same item, 2026-08-21
Found on the first real meeting of the authorized run and **re-measured across
18 completed meetings** (86 adr + 147 action-item whole-transcript artifacts).
A handful of meetings remain, so the rates may move slightly, but the sample is
now large enough to act on.

The whole-transcript stage makes two independent calls over the *same*
transcript: one for the architecture summary, one for action items. Neither
sees the other's output and nothing reconciles them, so a single real-world
item can land twice with different `kind`. Measured on meeting
`01a01a38-7384-709a-bda3-5340413923b2` (14 artifacts, 5 adr / 9 action-item):

    A9 @ 2736s  action-item  "Make contract-value column non-mandatory for teaming agreements"
    D4 @ 2736s  adr          "The 'contract value' field should be non-mandatory for teaming agreements"

    A1 @ 337s   action-item  "Forward the variation PDF(s) to Cameron"
    D1 @ 345s   adr          "Hayden will forward the variation PDF (and related PDFs) to Cameron"

D4 and A9 resolve to the **identical anchor**, which is both the clearest proof
they are one item and the obvious dedupe key: same meeting, same `anchor_ms`,
near-identical title.

**Measured over 18 meetings, 86 ADRs** (superseding an earlier 6-meeting
reading that put the exact rate at 10% — the small sample understated it by
half; do not quote that figure):

    adr artifacts                                  86
    adr sharing an EXACT anchor with an action-item  18   (21%)
    adr within 15s of an action-item                 29   (34%)
    meetings with at least one exact collision       10 of 18  (56%)

The exact-anchor cases are certainties — same meeting, same millisecond, near
identical title. Proximity alone is not duplication, so the 15s figure
overstates: reading the closest pairs by title on the earlier sample, about 7
in 10 were genuinely one item and 3 were different things sitting close
together. Applying that to the 11 non-exact pairs suggests a true rate near
**30%**, with **21% established beyond argument**. The 21% is a measurement;
the 30% is an estimate built on a human read of ten titles, and anyone
re-deriving it should re-read rather than trust the ratio.

Confirmed duplicate pairs read like this — decision framing against task
framing for one event:

    0s   "The 'contract value' field should be non-mandatory..."  /  "Make contract-value column non-mandatory..."
    0s   "Exclude 'do not delete' files from migration"           /  "Update the algorithm to exclude 'do-not-delete' files"
    8s   "Hayden will forward the variation PDF..."               /  "Forward the variation PDF(s) to Cameron"

**A second, separable problem the same data shows.** Several artifacts typed
`adr` are not architecture decisions at all — "Hold a one-hour working
session", "Schedule follow-up review meetings next week", "Hayden will forward
the variation PDF". Those are action items that the arch-summary prompt
admitted. That is prompt scope, not deduplication, and fixing one will not fix
the other.
A third, `D5 @ 3520s` "Schedule follow-up review meetings next week", is an
action item by any reading rather than an architecture decision — that one is
prompt scope, not deduplication.

**Why this needs settling before Epic 4 finishes, not after.** Story `4-3`'s
approve gesture advances *every* `extracted` artifact on a moment in one call,
so a duplicated pair on the same moment publishes both. Story `4-4` then makes
published artifacts citable, so the corpus can cite one decision twice under
two kinds — and `4-5`'s digest would list it twice. Each of those stories is
correct on its own contract; the duplication arrives from upstream.

Not filed as a `4-1a` defect: 4-1a implemented the frozen contract, which
pinned one strict parser per document and never asked for cross-document
reconciliation. This is a gap in the contract. It also bears on CAP-5's
still-unresolved "one pass per meeting" wording — the reading that settled the
implementation ("one logical pass, two document calls") is exactly the shape
that produces this, so the spec-owner clarification now has a concrete
consequence attached rather than being a wording nit.

### `4-5` lands from two branches, not one, 2026-08-21
Observed on origin while the Codex review was in flight. Not a defect —
just an assembly step that will fail the gate if it is missed at merge time.

The story's code and its review report are on disjoint lineages:

    story/4-5-review-remediation   9536c8c   4-5's build + 2 remediation commits
                                             carries review-PROMPT-story-4-5, no report
    story/4-5-review               741229b   main + 3 docs-only commits
                                             carries review-STORY-4-5 report, no digest code

`story/4-5-review` was built over `main` rather than over `story/4-5`, so it
holds no `server/meetingminer/digest/` files at all. Merging the remediation
branch alone therefore puts the review *prompt* on `main` with no matching
*report*, and `make check-reviews` fails — the Phase 1 gate, tripped by an
assembly mistake rather than by a missing review.

**At merge: bring the report onto the code lineage first** (merge
`story/4-5-review` into `story/4-5-review-remediation`, or cherry-pick the
report commit), verify `make check-reviews` passes on the assembled branch, and
land that. This is the shape story 3-3 used — its notes record that
`story/3-3-review` merged `main` into itself before being pushed, which is why
that one landed as a single fast-forward.

Status when observed: the report's frontmatter says `status: in-progress` —
one product decision resolved (digest display timezone: preserve the database
session's calendar date, no code change) and five patches outstanding, two of
which are already committed on the remediation branch. Not landable yet;
nothing was merged.

**Resolved at landing (2026-08-21):** the remediation branch's report copy was
the review branch's report plus a remediation section, so no cherry-pick was
needed — the assembly had already happened on the branch. `make check-reviews`
passed on the branch and on `main` after the merge.

### `4-5-morning-digest-example-email-could-droppable` — done, 2026-08-21
Landed as a fast-forward at `45926af`; the reviewed range is the range on
`main`. Read-only digest CLI: `server/meetingminer/digest/`, a
`[project.scripts]` `digest` entry, `make digest`, and 438 lines of tests. No
migration, no API route, no web change, no projected field — **no post-merge
operation was owed**, and none was run. The worker stayed stopped throughout.

Review provenance: the report was authored on `story/4-5-review` (the Codex
review the earlier note recorded as in flight) and closed on the remediation
branch with verdict passed. Its frontmatter still said `in-progress`; flipped
to `passed` at landing, no content change.

**The verdict's condition — one clean full-server run — was met on the rebased
branch: 1,460 passed, 0 failed.** The Meilisearch primary-key flake from the
review session did not reproduce; both suite runs today ran with the worker
stopped, consistent with the projection-contention note above.

**The first run today failed 2 tests for a different reason, worth knowing
before the next worktree suite:** the `4-5-review-remediation` worktree's
`.env` was the raw template — `MM_CONTENT_ROOT=/Users/you/meetingminer-content`.
Most tests use temp roots, but `test_digest.py::test_database_unreachable_fails_like_rebuild`
and `test_mint_drop.py::test_a_drop_minted_into_the_configured_root_resolves_for_intake`
assert exact stderr, and the loader's "MM_CONTENT_ROOT is not a directory"
warning pollutes it. Fixed by pointing that worktree's `.env` at the real
roots (`/Users/devopsterus/current/meetingminer-{content,drops}`). Other
worktrees minted the same way likely carry the same placeholder `.env`.

**Known upstream caveat, not a 4-5 defect:** the digest lists what extraction
produced, so the ~20% ADR/action-item duplication (see the extraction notes
above) appears twice in a digest until the dedupe question is settled.

### `4-3-per-moment-approval-publishing` — done, 2026-08-21
Landed at `a82b219` from `story/4-3-review` after remediation (`6ea4f92`),
rebased onto `main` at `1fe6c6b`. The only conflict was the generated
`epic-4-context.md`; it was recompiled from current planning artifacts as an
isolated commit rather than hand-merged. Review report
`review-story-4-3-2026-08-21.md` is committed; `make check-reviews` passes.

What landed: `POST /moments/{moment_id}/approve` in the existing `moments.py`
(no new router — the `main.py` edits are the `require_publish_root` fail-fast
gate and `app.state.publish_root`, per the wave note above); synchronous
publish export (`server/meetingminer/publish/export.py`) — markdown file, git
commit, Postgres `UPDATE`, no job queue, so `5-3`'s check 2.11 can approve
through the API with the worker stopped; migration
`0011_artifact_publish_metadata.sql`; regenerated TS client committed with the
merge, so `make client` was not owed.

Post-merge operations: `make migrate` verified 2026-08-21 — reported nothing
to apply and the `artifact` publish columns are present on the shared dev
database, so 0011 is applied. No rebuild owed (no projected field change). The
worker stayed stopped throughout; the restart hold stands.

**Before the next `make start-api`:** the fail-fast gate refuses startup unless
`MM_PUBLISH_ROOT` is set, absolute, and usable (`.env.example:51` documents
it). `.env` files were not inspected at landing — check yours, and note the
4-5 note above about worktree `.env` files still carrying raw placeholders.

The nested-repo hazard from the wave note was fixed in-branch with a test:
after `ensure_git_repo`, `git rev-parse --show-toplevel` must resolve (both
sides `.resolve()`d) to `publish_root` itself, else `GitExportError`. Nothing
is owed there.

**Caution for anyone using the new endpoint:** 5 meetings still carry 133
legacy per-moment drafts (`provenance->>'source' IS NULL` — see the note
above). Approving one of those publishes the granularity the user rejected in
4.1, and `4-4` would then make it citable. The re-queue decision is still with
the user; until then, check provenance before approving.

### Running the worker during a parallel test wave corrupts the projections, 2026-08-21
My error, and worth writing down because the tradeoff that makes it possible is
deliberate and documented — only its precondition was violated.

Four `projection.failed` events at 04:22, 04:29, 04:36 and 04:38, all at the
`probe` stage, all the same Meilisearch error:

    index_primary_key_multiple_candidates_found — "The primary key inference
    failed as the engine found ... fields ending with `id`: 'id' and 'meetingId'"

That error only fires when an index is being **created**, and all three indexes
(`artifacts`, `chunks`, `moments`) exist with `primaryKey=id`. The timestamps
match the 4-3 and 5-4 sessions running full store-backed server suites.

**Mechanism.** `server/tests/conftest.py:1060-1082` wipes the shared stores —
`drop_all`, then `ensure_graph_schema` / `ensure_search_schema` — because Neo4j
Community serves one database and AD-4 fixes the Meilisearch index names, so
there is no namespace for a test run to hide in. The docstring is explicit that
this is accepted: "these tests write to the same stores the developer's worker
writes to. That is acceptable precisely because AD-4 makes both stores
disposable projections — `make rebuild` regenerates them from Postgres." The
worker projecting concurrently hits the window between `drop_all` and
`ensure_search_schema`, adds documents to an index that does not exist yet, and
Meilisearch tries to infer a primary key from a document carrying both `id` and
`meetingId`.

**The gap in story 2.7, stated precisely.** Its cross-worktree lock serializes
test runs against *each other*. Nothing serializes a test run against a
*running worker* — the worker does not take that lock, and has no reason to
know it exists. That was fine while the worker was stopped, which it has been
for this entire epic. I started it during a four-worktree wave without
considering store contention; I had thought about model contention on the
Ollama box and stopped there.

**What is and is not damaged.** No extraction work is lost. Artifacts, meetings
and moments live in Postgres, which test runs never touch (story 2.7 gives each
run its own database). Only the *projections* are affected, and they are
regenerable by construction. But the drift is larger than the four failed
events suggested. Measured against Postgres at 05:35 UTC:

    index        documents   postgres truth        state
    moments            396   1693 moments          23% coverage — 1,297 missing
    chunks             322   —                     partial
    artifacts           79   0 published artifacts  every document is a phantom

The `artifacts` index is the sharper problem. It holds 79 documents while
Postgres has **no** artifact in `published` state at all — nothing has ever been
published, since story 4-3 is not merged. Sampling them shows UUIDv4 ids and
null titles, where production mints uuidv7; spot-checking one
(`e32f697d-d1a7-40a3-a2a3-719ba6013cb9`) confirms neither it nor its
`meetingId` exists in Postgres. They are test fixtures left behind when a
per-run test database was dropped but the shared Meilisearch index was not.

That matters beyond tidiness: search and chat retrieve from these indexes, so
the corpus can currently surface artifacts that do not exist and never were
published — the precise thing "only published artifacts are retrievable"
forbids. It is projection state rather than durable data, so `make rebuild`
clears it, but until then the demo path is retrieving over a polluted index.

**Remedy, owed but not yet run:** `make rebuild` once the wave's suites stop,
which is the remedy the conftest docstring already names. It needs
`ollama pull qwen3-embedding:0.6b` present, or `ARGS='--structural-only'` keeps
the corpus searchable without re-embedding. Not run tonight: it would race the
same suites and the still-running worker, and re-embedding the corpus while 18
extractions are queued would contend for the same box.

**For the next parallel wave:** either keep the worker stopped while
store-backed suites run, or give the worker the same lock. The second is a real
story, not a footnote — a worker that queues behind test runs is a different
operational contract.

### Extraction backfill COMPLETE, 2026-08-21 — final tally
Authorized by the user at 04:18 UTC ("go for ollama"), drained by 05:40, worker
stopped once the queue emptied. Stopping was not separately authorized: the
sanctioned work was draining the queue, that finished, and an idle worker keeps
contending with the other worktrees' suites over the shared projection stores
(see the projection note below). Restarting needs a fresh yes as always.

    jobs                     30 done, 2 failed, 0 queued
    meetings extracted       25
    artifacts                320   (125 adr, 195 action-item)
    documents generated      50
    documents adopted         0
    fallback engaged          0
    legacy per-moment drafts 133   (still stale, see below)

**Everything ran on local Ollama `gpt-oss:120b` at `num_ctx: 65536`, verified
resident on the box mid-run. No paid call was made or reachable.** Cadence was
roughly 2 minutes per meeting, well under the 3 minutes the spec estimated.

**Failure rate: 2 of 32 jobs, and both failed by refusing rather than
inventing.** One is tonight's hallucinated anchor (see its own note). The other
predates the run: `align has no transcript to derive from: the drop provided no
transcript and no STT source was recorded for this meeting — refusing to
invent`. Neither produced partial or silent output. That is the design working.

**Two halves of 4-1a remain unexercised on real data.** Every one of the 50
documents was `generated`; the adopt-when-present path has never run, because
every existing drop predates the puller change that emits summariser documents.
And `fallback_engaged` is false on all 320 artifacts — the primary never
missed, so `ollama/qwen3:30b` has still never been called. Today's config fix
made the fallback name a model that exists; it did not prove the fallback path
works end to end.

**Duplication held steady as the sample grew** — 20% of ADRs share an exact
anchor with an action item (25 of 125), across 14 of 25 meetings. The
mid-run figure of 21% over 18 meetings was not a small-sample artifact.

### The 133 legacy drafts: RESOLVED by an authorized re-queue, 2026-08-21
The user re-queued `extract` for the 5 meetings below (job + stage flipped to
`queued` by `provenance->>'source' IS NULL`, run by their hand after the
worker was started with `make up`). All 5 jobs reached `done`; the queue is
fully drained. Result: 0 artifacts with `provenance->>'source' IS NULL`
remain; the 133 per-moment drafts were deleted (all were still `extracted` —
no approvals to carve out) and replaced by 68 whole-transcript artifacts
(9/9/32/9/9 per meeting), total corpus now 388. `fallback_engaged` stayed
false throughout — the fallback path remains unexercised. The 4-3 caution
about approving legacy drafts is void; every artifact is now whole-transcript.

### The 133 per-moment drafts will NOT be replaced by this run, 2026-08-21 — RESOLVED, see above
Found while watching the first live extraction of the authorized worker run.
Needs a user decision; nothing was changed.

`4-1a`'s spec and the notes above both say the reworked stage's rerun replaces
4.1's per-moment drafts "by design". The stage does do that — `_DELETE_DRAFTS`
with the approved-moment carve-out. **But there is no rerun.** Those 5 meetings
already have `job_stage.name='extract'` at `status='done'` from the 4.1 run, and
the worker resumes done stages rather than repeating them. We watched it skip
seven done stages on the first job of this run; `extract` is treated no
differently.

Measured on the live database at 04:25 UTC:

    extract status   meetings   legacy per-moment   whole-transcript
    done                    6                 133                 14
    queued                 23                   0                  0
    running                 1                   0                  0

So the run now in progress will finish with 24 meetings carrying correct
whole-transcript artifacts and **5 meetings still carrying 133 wrong-granularity
per-moment drafts that nothing will clean up**. Two extraction models coexisting
in one `artifact` table, distinguishable only by whether `provenance->>'source'`
is set (the whole-transcript stage sets it; 4.1's did not).

Why it matters beyond tidiness: story `4-3` adds per-moment approve-and-publish
and `4-4` makes published artifacts citable. A legacy draft approved through
that path would publish 4.1's per-moment granularity — the exact thing the user
rejected when they stopped the 4.1 backfill — and it would then be citable.

The fix is to re-queue `extract` for those 5 meetings so the stage runs and
replaces the drafts. That costs roughly 5 x 6 minutes of local GPU. It is a
data-mutating operation on rows the user may want to inspect first, so it was
**not** done unattended and is not implied by "go for ollama", which authorized
draining the queue rather than reopening finished work. Identify them with
`provenance->>'source' IS NULL`, not by date — the two generations were both
written on 2026-08-20/21.

### Parallel-wave coordination, 2026-08-20 (3-4, 4-3, 4-5, 5-4)
Four stories were dispatched into worktrees at once, against the standing rule
that only caveat-free independent work goes parallel. They are not
caveat-free, so the caveats are written down here rather than left in session
chat. All four branched at or after `9cbf73b`, so all four already carry the
4-1a landing and the fallback-tag fix.

**Migration 0011 is reserved for `4-3`** (per-moment approval and publishing).
Highest on `main` is `0010`. `4-5` confirmed 2026-08-20 that it needs no
migration. Anyone else needing one takes `0012` and amends this line before
creating the file — two branches minting the same number cannot be resolved
without rewriting one.

**`server/meetingminer/api/main.py`** — **no contest after all.** This note
first said `4-3` and `2-8` would collide on the `include_router` block. Reading
`4-3`'s spec settles it: `4-3` adds no router. `POST /moments/{moment_id}/approve`
goes into the existing `moments.py`, already registered. Its `main.py` edits
are the `require_publish_root` fail-fast gate and `app.state.publish_root` —
the startup-gate region, which `2-8` leaves alone; `2-8` replaces only the
registration block below it. Different regions, so a rebase at worst. `4-5`
adds no router either. Nothing in this wave contests the block.

**`web/src/App.tsx`** — `3-4` has already modified it and is the only branch
that has. `2-8` rewrites it. `3-4` lands first; `2-8` rebases behind it and
converts whatever `3-4` added to the view union into a route file. `3-4` was
asked to keep `ChatPanel`'s coupling to the union thin for that reason — a
plain callback prop survives the 2-8 rewrite, a new `AppView` variant does not.

**`4-5` scope, confirmed by its session 2026-08-20:** standalone read-only
`digest` CLI mirroring `rebuild`'s `cli.py` — `server/meetingminer/digest/`,
a `pyproject.toml [project.scripts]` entry, an `infra/Makefile` target, and
tests. No migration, no api route, no `include_router` edit. It is genuinely
independent of the other three.

**`4-3` scope, confirmed by its session 2026-08-20:** migration
`0011_artifact_publish_metadata.sql` per the reservation; `POST
/moments/{moment_id}/approve` is a synchronous API-only write — file export,
git commit, Postgres `UPDATE`, no job queue — so story `5-3`'s check 2.11 can
approve through the public API with the worker stopped.

**Hazard raised to `4-3` 2026-08-20, verified, not yet resolved.** Its
`ensure_git_repo(publish_root)` runs `git init` only when `{publish_root}/.git`
is absent. Checked against a throwaway repo: when `publish_root` is a
*subdirectory* of an existing repo the init runs and `git rev-parse
--show-toplevel` afterwards correctly reports `publish_root` — contained. When
`publish_root` **is already a git repo root**, init is skipped by design and
`git add`/`git commit` with `cwd=publish_root` commit into *that* repo. Setting
`MM_PUBLISH_ROOT` to the MeetingMiner checkout would make every ADR publish
commit into the shared source tree, which four agents are working in and which
AGENTS.md forbids writing to. `require_publish_root` does not catch it: set,
absolute, creatable, directory and writable are all true of a repo you must not
commit to. Suggested guard — after `ensure_git_repo`, require `git rev-parse
--show-toplevel` to resolve to `publish_root` itself, raising `GitExportError`
naming the discovered toplevel otherwise, plus a `test_publish_export.py` case
for a publish root nested in a pre-existing repo. **Accepted by `4-3` the same day** as a direct
in-branch fix with a matching test, not a deferred item, so nothing is owed
here.

One implementation trap in that guard, verified on this machine: `/tmp` is a
symlink to `/private/tmp` on macOS, and `git rev-parse --show-toplevel` returns
the *real* path. Comparing it against a configured `MM_PUBLISH_ROOT` of
`/tmp/...` without calling `.resolve()` on **both** sides compares
`/tmp/somepublishroot` to `/private/tmp/somepublishroot` and they are not equal.
The failure mode is a false positive — refusing a valid publish root — so it
fails safe, but it reads as a bug rather than as a guard doing its job. The
same applies to a pytest `tmp_path` under `/var` versus `/private/var`.

**`5-4` scope, confirmed by its session 2026-08-20:** no migration — the
harness reads the existing `artifact` table read-only. The live bake-off is a
RUNBOOK-only CLI (`python -m evals.harness.bakeoff`), never invoked by
`make evals-test`, `make evals-run`, or any pytest-collected test; those bind a
fake `Llm`, because two of the three candidate pools are paid cloud APIs and
nothing that can fire a real model call runs unattended. So `5-4` is not the
Ollama load and does not take the `evals-run` serial lock during its build.

**Correction, same day:** the Ollama contention the user reported is therefore
*not* `5-4`, and this note originally guessed that it was. Whatever is holding
the box is outside this wave. The queued worker restart — roughly 50
whole-transcript generations against `gpt-oss:120b` on `10.77.0.52` — still
waits on the box being free, but waiting on `5-4` specifically would wait on
the wrong thing.

### `4-1a-whole-transcript-extraction` — done (files 4.1's granularity correction)
User decision 2026-08-20: extraction operates on the WHOLE transcript, not
per-moment — a decision emerges across minutes and almost never sits inside
one moment; 4.1's per-moment design burned 358 paid claude-sonnet-5 calls over
5 meetings before the user stopped it and revoked the key. Adopt the proven
`pull_transcript` mechanism: entire timestamped transcript to Ollama
`gpt-oss:120b` (10.77.0.52, `num_ctx: 65536`, bake-off winner) with prompts
adapted from `arch_summary_prompt.md` / `action_items_prompt.md` — grounding
rules (no invented dates, [m:ss] anchors per item, [Proposed] tags) carry
over; output format gets pinned strictly (the two-layout parser lesson,
retrieval-prior-art §8). Each artifact's timestamp anchor resolves
deterministically to its containing moment for the FK link, preserving
no-citation-no-answer. Config default flips extraction to the local model;
paid models need fresh per-run authorization (now a SPEC constraint).
**Design choice RESOLVED by the user 2026-08-20: adopt-when-present,
generate-when-absent.** If the drop carries the puller summariser's docs, the
stage parses them — zero model calls; only a transcript arriving without
extractions goes to Ollama. One strict parser (both known summariser layouts)
serves both paths. Follow-on for the puller: emit-drop carries the summary
docs when they exist (optional drop-schema addition), so adopted extractions
arrive with provenance — per-file row, sha256, drops root — like all arrived
material. Note:
the two pull_transcript working copies (repo = emit-drop lineage, NVMe =
org-chart + Graph RAG + summariser lineage, ~241 diff lines) need eventual
reunification — the prompts are identical in both today. The 133 existing
per-moment artifacts are unpublished drafts; the reworked stage's rerun
replaces drafts by design.

**Landed 2026-08-20.** `main` is at `77ce4ef`; the branch was rebased and
fast-forwarded, so the reviewed range is the range on `main` and there is no
merge commit named for the story. `make check-reviews` passes
(`review-story-4-1a-2026-08-20.md` is committed). Review verdict was pass after
remediation: the malformed-markdown refusal, stale-document adoption, final
NDJSON handling, and the standalone `--summarize` failure status were all fixed
on the branch. Suites at merge: 1,329 server, 124 puller, 157 web.

**Post-merge operations.** `make migrate` was owed and is done — migration
`0010_extraction_sources.sql` applied to the shared dev database on 2026-08-20;
the `extraction_source` table exists. Nothing else was owed and nothing else
was run: no file under `api/` changed, so `make client` is not owed; the
`config.yaml` change is confined to the `llm.roles.extraction` block and
touches no embedder or chunking setting, so `make rebuild` is not owed. The api
did not need a restart for the changed `docs/source-drop.schema.json` — story
2.6 made `api/ingests.py` re-check the schema file per request.

**The worker restart is no longer a paid operation, but it is still a
decision.** Extraction's default model is now `ollama/gpt-oss:120b` and its
fallback `ollama/qwen3:32b`; no paid provider is reachable from the extraction
role as committed. Verified in Postgres 2026-08-20: 27 jobs sit at the
`extract` stage (26 `queued`, 1 stuck `running`), and 133 per-moment artifacts
from 4.1 are the unpublished drafts the rerun replaces. At the measured ~3
minutes per whole-transcript pass and two document calls per meeting, a restart
is on the order of 50+ local generations — hours of local GPU, not dollars.
`chat` and `judge` still name `claude-sonnet-5`, so those roles remain dead
while the Anthropic key is revoked.

**The configured fallback was a model tag nothing served — fixed 2026-08-20.**
Found at landing: checked against both `http://10.77.0.52:11434` (the
extraction role's `base_url`) and `http://localhost:11434`
(`providers.ollama.base_url`), the two endpoints returned identical `/api/tags`
lists, both served `gpt-oss:120b`, and **neither served `qwen3:32b`**. As
committed, a primary failure fell through to a model that does not exist, so
"both models failed" was the only outcome that path could produce — the exact
failure the config comment above it warns about.

Fixed on user instruction: all three roles now name `ollama/qwen3:30b`, which
both endpoints serve. `extraction`, `chat`, and `judge` all carried the same
dead tag, so all three were corrected — it is one defect in three places, not
three changes. Verified by generating against `qwen3:30b` on both endpoints,
not merely by reading `/api/tags`. `test_config.py` and `test_extraction_core.py`
pass (155). Note that `test_the_committed_extraction_binding_reaches_no_paid_provider`
(`test_extraction_core.py:872`) asserts the binding is Ollama-served and
private-hosted as a *property* — deliberately not literal tags — so it stayed
green through a dead tag and would do so again. **A served-tag check is what
was missing**: nothing in the suite asks the endpoint whether the model it
names exists. Filed in `deferred-work.md`.

The comment block at `config.yaml:32-49` was corrected with it. Its claim that
the embedder's model is served here while `gpt-oss:120b` is served only on the
other box is not what the tag lists show; the host separation is kept anyway,
since the lists diverge again the moment either box pulls or drops a model.

**CAP-5 still needs a spec-owner clarification.** The kernel says extraction
runs "in one pass per meeting" (`SPEC.md:47`) while the frozen I/O matrix and
the implementation do one whole-transcript generation per document kind. The
review resolved this in favour of "one logical pass, two document calls" and
the code follows that reading; the kernel wording was not edited.

**Deferred, and now filed twice.** The two `pull_transcript` working copies
(repo = emit-drop lineage, NVMe = org-chart + summariser lineage) are still not
reunified. 4-1a took the summariser-documents half into the repo copy but left
the org-chart half out of scope, so a drop emitted from the repo copy alone
still omits `participants`. See `deferred-work.md`.

**Remote branch cleanup DONE (2026-08-20).** All four remaining story
branches deleted on user instruction; `origin` now carries `main` and nothing
else. Each was verified superseded before deletion, not merely "merged":
`story/3-3` and `story/3-3-review` had zero commits unreachable from
`origin/main`; `story/4-1a` and `story/4-1a-review-remediation` carried
pre-rebase lineage whose every differing line was an older version of a file
`main` already had. Two worth naming, since a line count alone would have
looked alarming. `server/tests/conftest.py`: the branches bound only
`extract_stage.build_llm`, while `main`'s `_no_real_llm` generalizes the guard
to `LLM_CALL_SITES`, covering extract and chat — `main` is ahead, not missing
14 lines. `build-prompt-story-4-1a-2026-08-20.md`: 143 lines on the branch
against 42 on `main`, because `main`'s own last commit `77ce4ef` deliberately
replaced the build instructions with the completed handoff. Recovery SHAs,
should any be wanted back (`git branch <name> <sha>`):

    story/3-3                       501bad3bc86a494182685fd631974cfbb2ef9faa
    story/3-3-review                4014a666a7f3cc47f0a42de58dd88f151a209ebc
    story/4-1a                      c6f87817caf82f00c90dc95d7721c45bfbf89bad
    story/4-1a-review-remediation   5dce88bf7260e8a36a1975414f0b6d4ba4434ed1

The local `story/4-1a` (ancestor of `main`) and `story/4-1a-review-remediation`
still exist in this checkout; they hold nothing the remotes did not.

### `2-8-auto-discovered-route-registration` — ready-for-dev
Minted 2026-08-20 into `sprint-status.yaml` and `epics.md`, like `2-6` and
`2-7` before it; not in the original Epic 2 definition. Spec:
`spec-2-8-auto-discovered-route-registration.md`, baseline `9cbf73b`.

Removes the two hand-edited registration points — `api/main.py`'s
`include_router` block and `App.tsx`'s view union — which are the only two
entries in the integrate skill's `conflict-playbook.md` that disqualify a pair
of stories from parallel work. Server side is a `pkgutil` scan for modules
exposing an `APIRouter`; web side is a react-router layout route with children
discovered through `import.meta.glob`.

**Two constraints the spec makes into tests, because today they are only
comments.** (1) Registration order changes route matching: `events` is
registered before `jobs` so `/jobs/{job_id}` cannot swallow `/jobs/events`.
Alphabetical discovery satisfies this only because `e` sorts before `j`, so
`events.py` gets an explicit `ROUTER_ORDER`. (2) The web home view is rendered
with `hidden` and never unmounted, because the verify-a-claim loop is search →
moment → back → next hit and unmounting blanks the query. A plain `<Routes>`
swap would destroy this; the layout-route + `<Outlet />` shape preserves it.

**Two findings that shrink the job.** `AppView` and `OpenView` are exported
from `App.tsx` but imported nowhere else in `web/src`, despite the comment at
`App.tsx:11-16` claiming stories 2.3 and 3.4 reuse them — feature components
take plain callbacks, so no feature file or feature test changes. And
`App.test.tsx` already pins all three behaviors at risk (search state survives
Back, Back returns to origin, a double-clicked Open costs one Back), so the
spec requires its assertions to pass unmodified rather than asking the builder
to write a new safety net.

**Sequencing.** Pays only if it lands before `4-2`/`4-3`/`4-4`. `3-4` does not
need it — but `3-4` is a web story that will edit `App.tsx`, so whichever lands
second resolves a conflict there. `2-8` first makes `3-4` add a route file
instead.

**Deliberately not taken:** sorting routes by path specificity, which would
remove the ordering-hazard class outright instead of preserving it. It changes
matching for every route at once, and this story's value rests on the route
table being provably unchanged. Recorded in the spec's Design Notes as a
follow-on, not as a deferred item — nothing is broken today.

### `2-8-auto-discovered-route-registration` — done, landed 2026-08-21
Landed as a fast-forward at `199672e` via `story/2-8-review`; the reviewed
range is the range on `main`. Both hand-edited registration points are gone:
`server/meetingminer/api/registry.py` discovers every module in
`meetingminer.api` exposing an `APIRouter` (baseline order pinned per-module
via `ROUTER_ORDER`), and `web/src/routes/registry.ts` discovers `*.route.tsx`
screens through `import.meta.glob`. Adding an endpoint or a screen is now
adding a file. `conflict-playbook.md` and `dispatch.md` were updated on the
branch to retire the two chokepoints.

Review provenance: Codex `bmad-code-review`
(`review-story-2-8-2026-08-21.md`), 2 findings (1 medium — discovery order
diverged from the baseline route table; 1 low — the attributed import-failure
diagnostic had no regression test), both remediated on the branch
(`a4213e1`); verdict passed. Rebased twice during this integration — `5-3`
landed on `main` mid-run — cleanly both times; the two stories share only the
sprint docs. Verification on the final rebased branch: `make check-reviews`
passed, full `make test` chain exit 0 (server pytest, web 187/187, puller,
evals, web build).

**Post-merge operations owed: none.** No migration, no projected field or
index, and no route or response-model change — the route table is provably
unchanged (asserted by `test_api_registry.py`'s ordered baseline test), so
`make client` is not owed. The worker stayed stopped; the restart hold
stands.

**Caution for the next merge:** any branch cut before `199672e` that edited
`api/main.py`'s `include_router` block or `App.tsx`'s view union will
conflict with the rewrite. Resolve by moving the addition into the new shape
— a router module with an optional `ROUTER_ORDER`, or a `*.route.tsx` file —
never by restoring the hand-edited block.

The remote `origin/story/2-8` still points at the pre-rebase tip `f837f43`,
so ancestry checks against it report "not merged"; the landed content came
via `story/2-8-review`. Both remote branches await a deletion yes.

### `4-1-artifact-extraction-pipeline-stage` — done
**Merge-day cautions, verified against the branch (2026-08-20):** (1) `make
migrate` must run before the worker restarts onto 4-1 code (migration
`0009_artifacts.sql`) — same ordering lesson as 2.1a. (2) The 28 real-corpus
jobs are all paused at `extract`; the first worker restart on merged 4-1 code
runs ~850 real claude-sonnet-5 calls. Restart deliberately, not incidentally.
(3) `story/4-1` and in-flight `story/2-2` overlap on `server/tests/conftest.py`
(4-1 adds fake-LLM fixtures near the fixture block 2-2's api tests may also
extend) — whoever merges second resolves it; the suites themselves are
concurrency-safe. 4-1 does not touch `api/main.py` or the web app.

### `2-6-source-drop-schema-reloaded-on-change` — done
Defect found in operation 2026-08-19, not by review: the api caches
`docs/source-drop.schema.json` at startup, so a schema change never reaches a
running api. Cost 28 false `422 invalid-drop` refusals against a schema that had
accepted the drops for six hours. See `deferred-work.md`.

**Not in `epics.md`.** Epic 2 is defined there as stories 2.1–2.5 only; this id
was minted directly into `sprint-status.yaml` when the defect was found. There
is no epic-level acceptance criteria to look up.

### `2-7-parallel-safe-store-backed-tests` — done
Per-run Postgres database names and a bounded cross-worktree file lock for the
projection tests, so store-backed suites may overlap. Neo4j Community serves one
database and AD-4 fixes the Meilisearch index names, so the projection tests
queue rather than pretending to be isolated. `make evals-run` remains one at a
time.

Built without a spec file — unlike every other story here. The contract was the
`deferred-work.md` entry plus the dispatch rule. Reviewer handoff:
`review-prompt-story-2-7-2026-08-20.md`; the review remediated the unbounded
lock (now a bounded `LOCK_NB` retry loop), the `pg_stat_activity` prune race,
and the lock file's truncating `"w"` open mode.

**Not in `epics.md`**, same as 2-6.

---

## Epic 3

### `3-1-corpus-search` — done
Merged to main at `64d295b`; all 13 review findings patched and checked off in
the story spec.

**The report was missing, and now is not.** For a period this story was the
third unfiled review in the repo, and the first where the per-story prompt
named the required output file and it still did not land. It was subsequently
written and committed — `review-story-3-1-2026-08-20.md` (`6b8251d`, 265 lines,
`status: passed`, `followup_review_recommended: false`), so the severity and
evidence behind the 13 checkmarks is on disk rather than in one session's
terminal.

**The lesson outlived the defect.** Naming the file in the prompt is not enough;
the requirement has to be checked mechanically. That is now `make check-reviews`
(`_bmad/scripts/check_review_reports.py`), which asserts every
`review-prompt-story-*` artifact has a committed `review-story-*` report and is
the Phase 1 gate in the `integrate` skill. It passes as of 2026-08-20.
`GET /search` over the moments index, plus the web search view. The query side
of the projection lives in `projections/query.py`, so no module under
`meetingminer/api/` imports `meilisearch` — which is the property
`test_projections_single_writer.py` asserts, by AST walk over the imports. The
route does bind a client (`stores.meili_client` returns one and it is handed
straight to `search_moments`); what stays inside the projections package is the
client type, the index handle, and every store call.

Meilisearch ranks, Postgres cites: the index decides the order and produces the
snippet, and every citation field on the wire is re-read from the database of
record in the same request. `test_api_search.py` proves it by poisoning the
index documents with a wrong `startMs` and `meetingId` and asserting the
response still carries the row's values. A hit whose moment row is gone is
dropped and logged as `search.stale_hit`.

**One knob was added that the frozen contract did not name:
`api.search.semantic_score_floor`.** Measured against Meilisearch 1.53, the
vector lane ranks by similarity and has no notion of "no match" — a hybrid
query returns the k nearest moments for any input at all, which made the
contract's "no matches → `hits: []`" row unreachable. Meilisearch's own
`rankingScoreThreshold` cannot fix it: it applies to both lanes, and the two do
not share a scale (a typo-tolerant keyword hit scores 0.15 where a semantic hit
on unrelated text scores 0.65, so one number either keeps the noise or throws
away the typo tolerance the AC requires). The floor is therefore applied to the
semantic tail alone, in `projections/query.py`. Its default of 0.75 was measured
on the seeded corpus with `qwen3-embedding:0.6b`: a paraphrase query scored
0.783 against the moment that answers it while nonsense queries topped out at
0.701. That is a narrow gap measured over five moments — Epic 5's retrieval
eval is what settles it, the same as `semantic_ratio`.

**`screenText` needs a re-projection to take effect.** Documents written before
this story do not carry the field, so OCR text is searchable on already-ingested
meetings only after `make rebuild`. The code is correct before that happens; the
corpus simply is not re-indexed yet.

**Scope held at Epic 2's boundary.** Stories 2.2 (moment view) and 2.3 (meeting
drill-down with the highlighted transcript) are still backlog, so UX-DR3's full
path does not terminate here. Search delivers candidate moments, a highlighted
snippet, and an inline replay via story 2.1's `ReplayPlayer`; the drill-down
page stays 2.3's deliverable.

**Client regeneration picked up two unrelated exports.** `web/src/client` had
been stale since story 2.1 — regenerating for `searchCorpus` also added
`getRecording` and `getMediaFile`. Regeneration produces the whole sdk, and a
committed client that matches the api is the point of committing it.

### `3-2-graph-traversal-templates` — done
The graph query half of AD-7 landed as
`server/meetingminer/projections/traversals.py`: two hand-written,
parameterized Cypher templates — `screen-history` (`Screen ← Screenshot ←
Moment → Meeting`, ordered by `startedAt`, then `meeting.id`, then `startMs`)
and `participant-topic-moments` (the Rowan query: `ATTENDED` presence, no
topic hop, case-insensitive substring over `Moment.text`) — exposed through
`TRAVERSAL_TEMPLATES` and `run_template`, the registry story 3.3's router
classifies onto. Each registration carries its Cypher text, so
"hand-written, parameterized" is asserted by a test (every declared parameter
appears as a `$`-parameter; the statement contains no quote character, so no
literal can hide in it), not just reviewed.

**No API surface exists yet — deliberately.** The template functions and the
registry are this story's outermost surface; the `/chat` orchestrator (3.3)
and Epic 5's retrieval-eval driver are the consumers. Nothing under
`meetingminer/api/` changed.

The no-silent-zero split is structural: an unknown anchor comes back as
`screen`/`participant` `= None`, a resolved anchor with no matching moments as
an empty `rows` tuple — one Cypher round trip (`MATCH` anchor + `OPTIONAL
MATCH` traversal) distinguishes them. A blank topic is refused with
`ValueError` (it would match the whole corpus), a non-UUID node id is a named
`ProjectionError` (AD-6), driver failures wrap into
`StoreUnavailableError`/`ProjectionError` — no raw `neo4j` exception leaves
the package. No result limit: the deferred retrieval eval compares exact sets.

One pinned shared addition per the contract: `seed_meeting` gained
keyword-only `started_at` (default unchanged), because cross-meeting
time-order assertions need distinct `startedAt` values — 3.3's tests will
want the same lever. Tests: `server/tests/test_projections_traversals.py` —
store-free ones for the registry, the refusals, and the AC4 walk that no
`neo4j_graphrag`/`graphdatascience`/`langchain`/`llama_index` import exists
under `meetingminer/`, plus store-backed ones covering every I/O-matrix row,
including the `meeting.id` tie-break for meetings sharing a `startedAt`.

### `3-3-cited-q-a-with-deterministic-citation-gate` — done
`POST /chat` closes the Epic 3 retrieval path: a question is classified by
`api/chat_router.py` onto 3.2's `TRAVERSAL_TEMPLATES` and/or 3.1's moments
index, retrieval runs deterministically, `Llm(chat)` synthesizes prose carrying
`[[moment:<uuid>]]` markers, and `api/citations.py` decides whether anything is
emitted at all. The gate is code: every marker must name a moment that was
placed in this request's synthesis prompt **and** re-resolve against Postgres,
and every sentence unit containing an alphanumeric character must carry at
least one marker. A failure rejects the whole answer as `422`
`application/problem+json`, slug `no-citable-answer`, with a `reason` extension
(`no-evidence` | `no-citations` | `uncited-claim` | `unresolvable-marker` |
`empty-answer`) so 3.4 can render one explicit state and still tell it from a
transport error. Every citation field on the wire is read from Postgres, never
from Meilisearch, Neo4j, or the model's text.

The endpoint is content-negotiated: `Accept: text/event-stream` replays an
**already-validated** answer as `chat.token` / `chat.citations` / `chat.done`.
Validation completes before the stream opens, so a rejected draft cannot leak
token by token — a rejection is the same `422` problem in both representations.

`config.yaml` gained `api.chat.retrieval_limit` (30) and
`api.chat.traversal_row_limit` (20). Both are read per request and store
nothing, so **no `make rebuild` was owed by this merge** — unlike the
`projections:` block, changing these re-tunes only what the model is shown.
Note the coupling recorded in the config comments: chat's search leg runs the
same query path `/search` does, so `semantic_ratio`, `semantic_score_floor`,
and `crop_length` govern chat too. Retune one, re-check the other.

**How it landed.** `story/3-3-review` merged `main` into itself (`4014a66`) and
that tip was pushed to `origin/main` by the session that built it, so `main`
fast-forwarded rather than taking a merge commit named for the story. The
reviewed range is the range on `main`; `git log --oneline --graph` shows the
build commits under `fd40619`. `make check-reviews` passes.

**Post-merge operations.** `make client` was owed and is done (`f8d74de`): the
merge added a route, and the api had to be restarted onto merged code first —
the process running at merge time still served a schema with no `/chat`, and
`make client` generates from whatever answers on :8000. Only the api was
restarted; the worker stayed down under the paid-ops hold. The regenerated
client is additions only (`askCorpus`, `ChatRequest`, `ChatResponse`,
`CitationModel`, `RouteModel`) and `pnpm --dir web run build` passes. Note that
`make check-client` only asserts the three `.gen.ts` files exist — it is not a
staleness detector, so it stayed silent on a client that predated the route.
That detector is still a deferred item from story 1.10.

**One of the story's two deferred items is now discharged** by that
regeneration: 3.4 has the generated `/chat` types it needs. The other stands —
person-scoped retrieval **unions** the traversal and search legs instead of
intersecting them, so "where was Jordan confused" can cite moments Jordan was not
in. Its one-line enabler (adding `speakers` to the moments index
`filterable_attributes`) requires a full re-projection, which is why it was not
taken mid-story. Filed in `deferred-work.md`.

**Caution for the next merge.** This story touched two of the playbook's shared
files. `api/main.py` gained `app.include_router(chat.router)` in the router
block — union it, do not pick a side. `server/tests/conftest.py` gained
`fake_chat_llm` and `_bind_llm_call_sites`, in the same fixture block story 4.1
extended; 4-1a extends it again. Both are text conflicts only.

Tests: `test_api_chat.py`, `test_chat_citations.py`, `test_chat_router.py`,
`test_config.py` — 163 passed on `main` after the fast-forward. The independent
review (`review-story-3-3-2026-08-20.md`) raised 10 findings and all 10 were
remediated on `story/3-3-review` before the push, including two that let an
uncited claim or a leaked marker prefix through the gate.

### `3-4-chat-ui-with-streaming-replay-citations` — done (Codex remediation, 2026-08-20)

Landed via `story/3-4-codex-review`, fast-forwarded onto `main` at `e752cdb`
before this integration session opened — the branch was already an ancestor of
`origin/main` by the time this pass started; this entry records what shipped.

**Why a second review round.** The story's original in-repo review
(`review-story-3-4-2026-08-20.md`, pre-Codex-section) was dispatched by the
building session into its own Claude worktree — same model family as the
builder, which fails the independence gate documented in [`make check-reviews`
does not check who wrote the review](#make-check-reviews-does-not-check-who-wrote-the-review-2026-08-20)
above. `check-reviews` still passed because it only asserts a report exists.
The Codex `bmad-code-review` re-review of the complete range (`b93285b..f950bdc`)
is appended to the same report file under "Codex independent re-review
(post-landing)."

**Findings and remediation.** Codex ran all four layers (Blind Hunter, Edge
Case Hunter, Verification Gap Reviewer, Acceptance Auditor); no frozen-contract
or AC violation. Three confirmed findings, all patched in `976f437`:
1. **medium** — `ChatPanel.tsx` ended stream consumption on transport close
   rather than on `chat.done`; an intermediary holding the connection open
   past the complete answer would time out and discard it. Fixed to finish the
   turn on `chat.done`, citations promoted at that boundary.
2. **low** — local question-length validation counted UTF-16 code units
   against a server that validates Unicode code points, so a >250-astral-char
   question could pass client-side and fail server-side (or vice versa around
   the 1000 boundary). Fixed to count code points; added an astral-character
   regression test.
3. **low** — the controllable timeout added by the first review pass had no
   executable regression test. Added.

A fourth, low, **deferred**: re-submitting mid-stream silently discards a
partial answer with no interruption signal. Recorded in `deferred-work.md` as
a product UX call, not a merge blocker — same disposition the first review
pass gave it.

**Verification after remediation:** `make web-test` 169/169, `pnpm exec tsc -b`
clean, `pnpm run lint` clean (one pre-existing unrelated `button.tsx` warning),
`make check-reviews` passes. **Final Codex verdict: passes.**

**Post-merge operations owed: none.** No migration, no API route or response
shape change, no projected field or index change — `web/src/features/chat/`
only. `epic-3` is now fully `done` in `sprint-status.yaml`.

---

## Epic 5

### `5-4-llm-judge-harness-bake-off-nice-to-have` — done, 2026-08-21
Landed as a fast-forward at `f22c028`; the reviewed range is the range on
`main`. Everything sits under `evals/` plus docs: the judge harness
(`evals/harness/judge.py`), the bake-off (`evals/harness/bakeoff.py`,
`evals/bakeoff-candidates.yaml`, `evals/bakeoff-samples/`), the store-backed
corpus checks (`evals/checks/test_corpus_artifacts.py`), and RUNBOOK sections.
No migration, no API route, no web change, no projected field — **no
post-merge operation was owed**, and none was run. The worker stayed stopped.

Review provenance: handoff prompt authored for the Codex `bmad-code-review`
agent (`79a9b18`); the review followed its report-first pattern on
`story/5-4-review` and raised 8 findings (1 high — psycopg UUIDs break the
YAML report writer — 4 medium, 3 low), all 8 fixed on the branch. The report
carries no explicit reviewer/tool line — the known `check-reviews` provenance
gap, still filed in `deferred-work.md`.

Verification at landing, on the rebased branch: `make check-reviews` passed,
`make evals-test` 456 passed. **The reviewer's one blocked item is now
closed:** `evals/checks/test_corpus_artifacts.py` could not run in the
reviewer worktree (no Postgres password in its `.env` — same worktree-template
trap as 4-5) and was run post-merge from the main tree against the shared
stores instead: 4 passed, serial slot taken and released.

**Standing caveat, per the story's own scope note above:** the live bake-off
is a RUNBOOK-only CLI (`python -m evals.harness.bakeoff`), never collected by
pytest or any make target, because two of the three candidate pools are paid
cloud APIs. Running it for real is a paid operation and needs a fresh explicit
yes; nothing merged here can fire a model call unattended. The `judge` config
role still names `ollama/qwen3:30b` from the 4-1a fallback fix.

### `5-3-retrieval-publish-gate-checks` — backlog
**Blocked on 4-3**, which the epic numbering hides: check 2.11 must assert an
artifact is in neither store, then *approve it via the public API*, then assert
it is in both. That endpoint is story 4.3, per-moment approval and publishing.

### `5-3-retrieval-publish-gate-checks` — review (2026-08-21, build-auto on story/5-3)
Implemented on `story/5-3`: checks 2.10 (recall@5 through the public
`GET /search`, unfiltered, k=5) and 2.11 (publish-gate assert — corpus
discovery, read-only Meilisearch/Neo4j membership reads in the new
`evals/harness/stores.py`, approval via `POST /moments/{id}/approve`). Both
joined `REQUIRED_CHECKS`; guards extended (driver one-module pins over the
whole evals tree, stem-matched write-method pin). Review pass triaged 14
patches (7 medium, 7 low), all applied; 1 deferred (hardcoded HTTP timeouts);
follow-up review recommended (score 28). Two standing expectations, both
recorded in the spec and RUNBOOK: every live run still fails the zero-subject
gate (placeholder source_ids), and 2.11's post-approval half will FAIL against
real subjects until 4-4 wires projection-on-publish — that failure is the
check working; never green it. Codex review prompt generated beside this note.

### `5-3-retrieval-publish-gate-checks` — done, landed 2026-08-21
Landed as a fast-forward at `68fdefa`; the reviewed range is the range on
`main`. The Codex review (`review-story-5-3-2026-08-21.md`) raised 15
findings: 5 fixed on `story/5-3` (through `321b8d1`), 10 dismissed with
reasons in the report, 0 deferred. Verification at landing, on the rebased
branch: `make check-reviews` passed, `make evals-test` 550 passed. The
expected zero-subject live-check result was confirmed during review — that is
the placeholder-source_ids gate working, not a regression.

One rebase conflict, in this file only: the branch's 5-3 review note vs.
main's Wave 5 dispatch section, unioned. `sprint-status.yaml` merged itself by
key (`in-progress` + `review` → `review`, then the branch's own `done` line).

**Post-merge operations owed: none.** No migration, no API route or response
shape change, no projected field or index change — `evals/` plus docs and a
two-line `infra/Makefile` help-text update. The worker stayed stopped; no
`make evals-run` was started by this integration.

**Standing expectations carry forward unchanged** (spec + RUNBOOK): every live
run fails the zero-subject gate until real source_ids replace the
placeholders, and check 2.11's post-approval half fails against real subjects
until `4-4` wires projection-on-publish. Both failures are the checks working;
never green them.

---

## Wave 5 dispatch, 2026-08-21

Launched in parallel per the dispatch rule — both fully caveat-free and
disjoint:

- `2-8-auto-discovered-route-registration` — spec baseline `9cbf73b`. Sole
  claimant of `api/main.py`'s `include_router` block and `App.tsx`; nothing
  else in flight touches either.
- `5-3-retrieval-publish-gate-checks` — unblocked by `4-3` (merged); operates
  from `evals/` as a public-API client only, worker stays stopped (check 2.11
  approves through the API, no job queue). No file overlap with `2-8`.

Held back until `2-8` lands: `2-4`, `2-5`, `4-2` (would hand-edit the
registration regions `2-8` rewrites) and `4-4` (sequenced after `2-8`; also
carries the duplicate-artifact and legacy-draft provenance caveats).

Reminder for whoever runs `5-3`'s checks: `make evals-run` remains one at a
time, and the worker restart hold stands.

---

## Wave 6 dispatch, 2026-08-21

Wave 5 is fully landed (`2-8` at `199672e`, `5-3` at `68fdefa`; epic-5 done
at `bcc1960`). Remaining backlog: `2-4`, `2-5`, `4-2`, `4-4`. None has a spec
minted yet.

**Dispatch `4-4-published-artifacts-become-citable-knowledge` next, alone.**
It is a sequence, not a parallel recommendation, because it carries the
documented provenance caveats: the 5 meetings with 133 legacy per-moment
drafts (`provenance->>'source' IS NULL`) must not become citable through the
publish path, and the duplicate-artifact behavior from the 4-3 note applies.
It is also the highest-value remaining story: it completes the
approve → publish → citable chain and flips `5-3`'s check 2.11 post-approval
half from expected-fail to required-pass — its spec should say so
explicitly so the eval expectation is retired with the story, not left
stale.

After `4-4`, the best parallel candidate pair is `2-4` + `4-2` — participant
curation and extraction prompts share no domain surface. Confirm at
spec-minting that neither edits `server/tests/conftest.py` or
`projection_seed.py` before calling them parallel; if either does, sequence
them. `2-5` follows `2-4`, not beside it: both are meeting-metadata curation
feeding the Neo4j projection.

Route/screen additions in all four stories are file-additions now (2-8);
the old registration chokepoint no longer sequences anything.

---

## Story 4-2 landed, 2026-08-21

`4-2-visible-swappable-extraction-prompts` merged to `main` at `52f56e7`
(review branch `story/4-2-review`; review target `story/4-2` at `65eaf65`).
Review: pass (`review-story-4-2-2026-08-21.md`) — one low-severity race
(late-settling aborted prompt fetch could still render) fixed on the review
branch at `52805a6` with a regression test; 190 web tests and TypeScript
passed after the fix.

**Post-merge operations.** `make migrate` run at integration: nothing to
apply — `0012_extraction_prompt_hash.sql` was already applied to the shared
dev database (verified in `schema_migrations`) by the implementing agent.
The regenerated TS client for the new `GET /extraction/prompts` route was
committed on the branch, so no `make client` owed. No `make rebuild` owed:
the `config.yaml` change is prompt text under `llm:`, not embedder/chunking
or a projected field. Worker stayed stopped; no `make evals-run` started.

**What the next person should know.**
- The two whole-transcript prompt templates now live verbatim in
  `config.yaml` under `llm:`. Editing them is a live behavior change on the
  next fresh worker process — no code change, no migration. The table
  header, `D#`/`A#`/`R#`/`O#` item-ID prefixes, and `[m:ss]` timestamps are
  required by `parse_extraction_document`; keep the committed defaults
  parseable.
- `GET /extraction/prompts` serves that text verbatim to the moment view's
  "Active extraction prompts" section.
- `0012` stores a prompt hash per extraction, so provenance now records
  which prompt text produced an artifact.
- The worker restart hold stands unchanged: 27 real-corpus jobs still sit at
  `extract` and will run (hours of local GPU, no paid calls) on the next
  worker start — fresh explicit yes required.

---

## Bugfix rebuild-crash-recovery landed, 2026-08-21

`story/rebuild-crash-recovery` merged to `main` at `f368c43` (fast-forward
after rebase onto `ef85270`; landed second behind 2-4 by agreement, zero file
overlap). Freeform bugfix, no sprint-status key. Spec:
`spec-rebuild-crash-recovery.md` (done; carries a Suggested Review Order).

**What landed.** The `make rebuild` crash (Neo4j `EntityNotFound`, stores
left near-empty) was a cross-worktree race: rebuild/worker held only the
Postgres advisory lock while every worktree's projection tests wipe the same
shared stores under the conftest file lock — two exclusion mechanisms that
never saw each other. Now `projections/locks.py` holds the one file-lock
implementation (conftest delegates to it, byte-compatible paths), all four
store-writing entrypoints take file lock then advisory lock, one meeting's
graph projection is a single Neo4j transaction, and a raw
`Neo4jError`/`MeilisearchError` on one meeting is a recorded rebuild failure
instead of a run abort. AGENTS.md and `make rebuild` help now state the
single-flight rule.

**Post-merge operations.** None owed: no migrations, no projected-field or
index-shape change, no API surface change. The corpus recovery ran as part of
the story before landing: `make rebuild` 33/33 meetings, 0 failures —
Meilisearch moments 1811 (= Postgres `moment` count), chunks 1191, Neo4j
4557 nodes, `artifacts` untouched. No Neo4j volume wipe was needed (the
crash did not reproduce serialized; it was a live race, not corruption).

**What the next person should know.**
- `make rebuild` and the worker now queue up to
  `MM_PROJECTION_LOCK_TIMEOUT_SECONDS` (default 300s) behind a running
  projection-test suite, then fail with a named `ProjectionLockedError` —
  a refusal naming a pytest holder means wait, not debug.
- A rebuild longer than that window will starve a concurrently-projecting
  worker meeting into the same named refusal; the worker is stopped today so
  this is theoretical until the restart.
- `publish_gate.project_artifact` still writes Meilisearch without either
  lock (no production caller) — recorded in deferred-work, deliberately not
  fixed here.
- Worker restart hold unchanged.

---

## Remote branch cleanup, 2026-08-21 (integration pass)

Deleted 8 stale remote branches; each tip's content was verified already on
`main` (patch-id plus file diff — the one code commit, `6357903` on
`story/5-4-review`, landed as `f22c028`). Recovery SHAs:

- `story/4-5` @ `1d150e0`
- `story/4-5-review` @ `741229b`
- `story/4-5-review-remediation` @ `bd88fe3`
- `story/4-5-review-remediation-rebased` @ `76d9c53`
- `story/5-3` @ `321b8d1`
- `story/5-4` @ `b5fe6dc`
- `story/5-4-review` @ `6357903`
- `story/rebuild-crash-recovery` @ `16f37fd`

Also deleted the matching stale local branches (`5dce88b`, `1d150e0`,
`741229b`, `76d9c53`) and removed a leftover clean detached-HEAD worktree at
`a16c198` (ancestor of main). No ops owed; worker restart hold unchanged.

---

## Store-wipe attribution, 2026-08-21 (eval session follow-up)

After the rebuild-crash-recovery landing above, the shared Meilisearch/Neo4j
stores were found near-empty again (moments 2, chunks 1, Neo4j 10 nodes)
despite the recorded 33/33 recovery rebuild. Investigated and attributed:

**The wiper was the projection-store test suite itself, run as landing
verification for this very branch, ~50 seconds before the landing record was
committed.** Evidence:

- The stray documents left in Meilisearch carried meeting ids
  (`01a025da-*`) that exist in no corpus database. They are uuidv7; the
  embedded timestamps decode to 19:44:53–19:45:01 UTC — minted live, seconds
  before being projected. They are per-run test-database fixture rows.
- The Meilisearch task log for that window is ~5 cycles of
  `indexDeletion → indexCreation → settingsUpdate → project one tiny meeting
  (2 moments, 1 chunk)` — exactly one `projection_stores` fixture setup per
  test (`server/tests/conftest.py`: function-scoped, calls `drop_all` on the
  shared stores per test, by documented design).
- Timeline (UTC−6): recovery-complete commit `f368c43` at 13:43:12; the
  burst 13:44:53–13:45:02; landing record `cb9f575` at 13:45:45. Run the
  suite, then commit the landing note.

So: the recovery rebuild restored 1811 moments → the landing-verification
test run wiped the shared stores and left the last test's fixture rows →
the "corpus fully reprojected, don't touch" status was accurate when written
and stale within two minutes. A second `make rebuild` (33/33, 0 failures, on
the landed fix) restored the corpus; counts re-verified at moments 1811,
chunks 1191, Neo4j 4557.

**Standing implication — not a code bug, but a footgun:** the file lock
serializes store access; it does not change that projection tests wipe and
abandon the shared stores. Running any projection-store suite (including via
`make test`) destroys the developer's corpus projection until the next
`make rebuild`. "Ran the test suite" now implies "owe a rebuild", and
nothing says so at the point of impact. Candidate cheap fix, deliberately
not done here: a post-suite notice (conftest teardown print, or `make test`
epilogue) stating the shared stores now hold fixture data and naming
`make rebuild` as the remedy.

---

## Eval run 2026-08-21-demo-recorded-3 triage, 2026-08-21

First run with the scripted demos actually recorded, so these are first
measurements, not regressions. 19/23; the two `2.11 publish-gate projection`
failures are the standing expected-fail that story `4-4` retires. The three
unexpected failures triage to one break-fix plus one threshold decision:

- **Break-fix (real defect): `2.3 view classification` on demo-002
  (q3-architecture-review).** Captures 4–7 contain the right slides — OCR
  matched all five slide anchors at score 1.0 — but the classifier labeled
  them `participant-gallery` (capture 1: `ui-screen`); accuracy 0.29. The
  failure shape is a slide shared inside the Teams meeting window with the
  gallery strip visible, classified by the surrounding layout instead of the
  shared content. Dispatch as a freeform story (`rebuild-crash-recovery`
  pattern, no sprint-status key): `story/capture-view-classification`.
- **Probably the same root cause: `2.2 over-capture guardrail` on demo-002.**
  11 captures against a budget of 7 (1.571/min). Misclassified gallery frames
  plausibly defeat the dedup/budget selection. Do not fix separately — re-run
  the eval after the 2.3 fix and only then treat any residue as its own item.
- **Threshold decision, not automatically code: `2.1 capture recall` on
  demo-001 (orders-ui-demo).** Recall 0.5; SC2 (line items/tax breakdown),
  SC3 (tax table mapping editor), SC4 (fulfillment queue) unmatched. SC2/SC3
  are the dense-screen category the standing capture-priority stance accepts
  as misses, yet the check is `blocking: true` at recall 1.0 — the ground
  truth or threshold should encode that stance if it is to stand. SC4 at
  score 0.0 (no capture resembles it at all) is the one entry worth an
  actual look before writing it off.

Iteration is free and local: capture plus `make evals-run` (one at a time),
worker stays stopped, no paid calls. Worker restart hold unchanged.

---

## Chat model binding change and fallback removal, 2026-08-21

The web chat "Cannot reach the api … timed out after 60000ms" report traced
to: the Anthropic key is invalid — deliberately revoked by the owner after
unauthorized paid use, not an accident — so every chat turn silently rode the
`ollama/qwen3:30b` fallback at ~102s, past the chat panel's 60s bound.
Evidence and contract: `_bmad-output/specs/spec-chat-fallback-timeout/`.

Owner decisions of record:

- Paid LLM roles use the OpenAI key from now on. `config.yaml` chat and judge
  are now `openai/gpt-5.2` (prefix required — the adapter's bare-name routing
  predates gpt-5). Api restarted; worker untouched, restart hold unchanged.
- The silent fallback mechanism (spine AD-10 default bindings, implemented in
  story 4-1's `build_llm` composer) was never agreed to by the owner. Chat
  and judge fallbacks are removed; a failing primary must surface as a
  visible error. Extraction's local-to-local fallback is a pending owner
  decision — do not remove it incidentally.
- The spine's AD-10 default-bindings sentence is stale; an architecture
  amendment via bmad-architecture is owed.

---

## chat-fallback-timeout landed, 2026-08-21

Merged at 8080a1a (story/chat-fallback-timeout, d45db76 + e318215; freeform
break-fix, no sprint-status key). CAP-3: the chat panel's 60s expiry now says
"the api did not finish within 60s" and a stream cut before `chat.done` reads
as an interruption; "Cannot reach the api" is reserved for a fetch that never
connected. CAP-4: a chat-model 503's detail names the `llm.roles.chat`
binding, model tag, and fallback state (problem extensions `binding`/`model`
added — additive only, slugs and shapes unchanged, no client regeneration).
Verified on the rebased range: web-test 203/203; test_api_chat.py 47/47,
including an end-to-end no-fallback primary-failure test through the real
FallbackLlm composition. Api restarted onto the merged code (health 200);
worker untouched, restart hold unchanged. No migrate/rebuild/backfill owed.
Still owed elsewhere: the spine's AD-10 default-bindings amendment
(bmad-architecture), and the live paid `openai/gpt-5.2` turn from the UI is
owner-triggered by design. Remote branch story/chat-fallback-timeout left in
place pending the owner's ok to delete.

---

## system-status landed, 2026-08-21

Merged at 3f5a1ea (story/system-status, rebased range 015f28a..badd275;
freeform story, no sprint-status key). CAP-1: `GET /status` read-only
aggregate health (stores, api, every `llm.roles.*` binding with key state,
worker + job/stage backlog), polled at 15s by a persistent chrome indicator
and a dedicated `/status` page. CAP-2: every degraded row names the broken
dependency and a concrete file-edit-plus-restart remediation. CAP-3: bindings
are named `` `llm.roles.<role>` `` exactly as the chat panel's 503 spells
them. Secrets: payload is an explicit allowlist, adversarially reviewed and
test-pinned (no value, prefix, or length of any key/password can serialize).
Probes are free list endpoints only, cached 60s (`PROBE_TTL_SECONDS`) — no
completion exists on the path; missing keys are reported without probing.
Worker: observation only through pg_locks (the exact
`hashtext('meetingminer-worker')` advisory lock, database-scoped — verified
held/scoped/released against a scratch database); the stopped worker reads
as deliberate with the restart-is-a-spend-decision caveat and still degrades
`overall`. Review: review-story-system-status-2026-08-21.md — pass, 3
non-blocking findings (cold-cache concurrent free probes; status surface's
own unreachable copy conflates timeout/HTTP error; unknown-provider rows
read ok). Verified on the rebased range by the reviewer: test_api_status.py
+ test_api_registry.py 15/15; web-test 208/208. Worker untouched, restart
hold unchanged; no live provider endpoint called. No
migrate/rebuild/backfill owed. Registry baseline gained `status`
(default-order, no parameterized sibling); App.test.tsx chat-citation fetch
mock is now URL-aware so the status poll cannot eat the chat stream body.

---

## ui-1 landed, 2026-08-21

Merged at 7f8871f (story/ui-1 rebased 4e16556..4c7a797; freeform story from
spec-ui-reimagine, no sprint-status key — same convention as system-status).
Three read-only surfaces: `GET /corpus/stats` (getCorpusStats), `GET /config`
(getConfiguration — field-by-field allowlist, never a model dump, secret pin
proven by mutation in review), and `listMeetings` extended with durationMs,
posterScreenshot, and moment/screenshot/artifact/participant counts. Client
regenerated (picked up getSystemStatus drift from the status story — the
client catching up, not a bug; baked baseUrl overridden in web/src/lib/api.ts).
Review: review-story-ui-1-2026-08-21.md — pass, 2 non-blocking (stats
byKind/byState are separate READ COMMITTED statements vs the "one snapshot"
comment; nothing else). Suites: 1555 server on branch, 33 targeted + 208 web
on the rebased range. No migrate/rebuild/backfill owed. Api restarted onto
merged code (pid 78943, /corpus/stats verified serving); worker untouched,
restart hold unchanged. Next wave ui-2/3/4 dispatched in parallel with an
explicit file-boundary amendment: ui-2 owns App.tsx/chrome including the nav
links to /settings and /status; ui-3 owns features/moments meeting view; ui-4
adds its route file + feature dir only and does NOT touch App.tsx or
MomentView (prompt duplication noted in report instead). ui-5 gate holds the
≤5 paid chat-call authorization; demo 2026-08-22 morning.

---

## ui-4 landed, 2026-08-21

Merged at 70d69c6 (single commit 7b6ae17 off 52e9ca0, no rebase owed; review
a820739 brings report b11386b — pass-with-findings, none blocking). New
`/settings` screen: read-only config transparency from GET /config, all 7 SPEC
sections with change-path sentences, secret-marker + no-edit-affordance tests.
Boundary held exactly (4 files under web/src/features/settings/). Open
follow-ups recorded in the review: F1 low — secret matcher folds _/- but not
whitespace, so multi-word markers can't match labelized document text
(payload-side check still guards); F2 — chrome link to /settings is ui-2's and
lands with it; F3 — MomentView still renders its own extraction-prompts block
(duplication deliberate, boundary-forced). No ops owed (UI files only; api
untouched). Worker untouched, restart hold unchanged.

---

## ui-3 landed, 2026-08-21

Merged at 06b1650 (story/ui-3 rebased onto post-ui-4 main; review 7c9f48b
brings report 43610f5 — pass, advisories only). /meetings/:id recomposed to
the reference three-column anatomy: header stat line (counts computed over
served data only; duration = evidence extent, drilldown serves no duration
column), timestamped screens film-strip, full transcript center (2.2/2.3
behaviors preserved), right rail of artifacts by kind + participants (with
absence note) + published docs. web-test 236 on the rebased range. Advisories
for post-demo: F1 unbounded per-moment getMoment fan-out for the rail (fine
locally; wants bounded concurrency or a per-meeting artifacts endpoint), F2
timeout-vs-incomplete copy, F5 untested abort paths, and lineage names no
transcript container ("Teams VTT") because transcript_source isn't served —
a ui-1-style roll-up field would restore it. Chrome width note: ui-3 built
against pre-ui-2 chrome and flags the container as tight for lg 3-column;
ui-2 widened to max-w-5xl — ui-5's live pass judges whether that suffices.
No ops owed. Worker untouched.

---

## ui-2 landed, 2026-08-21 — all four CAP-1/2/3 stories now on main

Merged at 60b3bcd (story/ui-2 rebased onto post-ui-3/ui-4 main; review 897b1ac
brings report 457af17 — clean pass). Home recomposed: CorpusStats header from
GET /corpus/stats, MeetingsList became evidence cards (poster, duration,
served per-meeting counts, corpus filter, recency sort), CorpusSearch+ChatPanel
promoted to persistent chrome on every route, nav links to /status and
/settings added. Rebase over ui-3/ui-4 was conflict-free; web-test 250 green
on the rebased range (up from 208 at ui-1). No invented data anywhere —
verified by the reviewer via explicit no-zero assertions.

**ui-1/ui-2/ui-3/ui-4 all merged.** This completes CAP-1 (home), CAP-2
(meeting view), CAP-3 (config page) of spec-ui-reimagine. No migrate/rebuild/
backfill owed — UI-only + one prior read-only api surface, api already
restarted at ui-1's landing and still current (no api file changed since).
Worker untouched throughout the whole chain. Next: ui-5 demo dry-run gate
(CAP-4), the spec's done_checkpoint — ≤5 paid openai gpt-5.2 /chat calls
authorized 2026-08-21 for that story alone. Two carried-forward advisories for
after the demo: ui-3's unbounded per-moment artifact fan-out on large
meetings, and ui-4's secret-matcher whitespace-fold gap (F1, low severity).

## Bugfix demo-001-capture-recall landed, 2026-08-21

`story/demo-001-capture-recall` merged to `main` at `0cb44ff` (fast-forward,
rebased onto post-ui-2 main; conflict-free). `spec-demo-001-capture-recall.md`
(done; carries a Suggested Review Order). No dispatched review-prompt file for
this freeform bugfix — bmad-build's own three-layer review (blind hunter,
edge-case hunter, verification-gap) stands in, per the `rebuild-crash-recovery`
precedent; `make check-reviews` passes since no review was dispatched to omit.

Root cause of the missing screenshots on demo-001 (orders UI demo, meeting
`01a02545-fbdb-7baa-b895-20791a06299a`): the emit gate in
`server/meetingminer/pipeline/screens.py` compared each frame only against the
last *emitted* shot at a single `change_threshold: 0.10`. Three dense
same-chrome pages (order detail, tax table admin, fulfillment queue) sat at
sustained distances of 0.047–0.077 from the emitted shot — all under the gate
— so 176s of paging collapsed into one capture (recall 0.5, 3/6). Fix: a new
`settled-change` cue fires when a frame is pixel-quiet at a sustained distance
≥ `settled_change_threshold: 0.03` from the emitted shot for
`settled_change_frames: 3` consecutive samples — separating a real page change
(arrives and stays) from a transient (spikes and returns) — plus a fold for
the recorder's one-sample opening title slate. Also fixed a structural bug in
the eval harness: check 2.2's budget could be smaller than a manifest's own
expected-capture count on a take shorter than planned; it is now
`max(ceil(duration_minutes), expected_screenshot_count)`.

Verified live: demo-001 re-captured, recorded run
`evals/runs/2026-08-21-demo-recorded-4` — 2.1 recall 1.0 (6/6), 2.2/2.3/2.4 all
pass. 170 tests green on the rebased range (server screens/config/worker suites
+ eval-check suite). Two items filed in `deferred-work.md` rather than fixed
here: the `eval-design.md` §2.2 doc now disagrees with the shipped formula
(outside this story's file boundary), and the new gate raises real-corpus
capture volume ~+30% (829 → 1076 replayed offline at the 0.03 floor) with no
owner yet for whether that cadence increase is accepted, tuned down, or capped.

No migrate/rebuild/backfill/client-regen owed — only `pipeline.screens`
thresholds and eval-harness code changed, no migration, no projected field, no
API surface. Worker untouched, restart hold unchanged.

**Ordering note for the next agent:** this story was deliberately landed
*before* `story/capture-view-classification` (demo-002's view-classification
break-fix) because both name `screens.py`, `frameimage.py`, and `ScreensConfig`
in their file boundaries and neither had started when the conflict was
noticed. That story is now clear to kick off from current `main`.

---

## ui-5 landed, 2026-08-21 — spec-ui-reimagine chain complete, DEMO IS AT RISK

Merged at ea10f39 (report-only commit dc704c3, no code changes — the live
walkthrough found nothing in web/src to fix or fall back). Full report:
demo-readiness-2026-08-22.md.

**UI is demo-ready:** home dashboard (real counts), both meeting-view shapes
(with screens / transcript-only), moment pages with real video replay synced
to transcript, /settings, /status. web-test 250/250, build clean.

**Two demo-blocking infra issues, NOT UI, NOT fixed by this chain:**
1. Meilisearch corpus search returns zero hits for everything; one query
   503'd `invalid_search_embedder`. Blocks the search step of the 3-minute
   demo path.
2. Paid chat role (openai gpt-5.2) is out of OpenAI credits — confirmed live
   (call 1 of 5 authorized; agent stopped rather than burn the rest against a
   deterministic provider failure). Blocks ask-the-corpus → cited answer,
   which is the spine of the demo (parent SPEC: "the live demo runs about
   three minutes... ask a question, get a cited answer, open a cited moment,
   replay").

Neither is a code regression from this chain; both need owner attention
(re-embed/rebuild for search embedder config, and either OpenAI billing or a
provider swap for chat) before tomorrow morning. This is the spec's
done_checkpoint — chain stops here for the owner.

---

## 2-5 landed, 2026-08-21 — epic-2 complete

Merged at c0f599e (review c0f599e..b51422f brings report
review-story-2-5-2026-08-21.md — pass, 15 hypotheses raised by the
independent review layers and dismissed, no must-fix findings). Gives
meetings a series/project/product structure: five new API-written-only
tables (`0013_series_projects_products.sql`), write-path routes at
`server/meetingminer/api/structure.py`, and graph projection linkage so
assignments surface on the next projection or `rebuild`. This was the last
open `epic-2` story — **`epic-2` is now `done`** (all ten stories).

**Rebase carried through a moving target.** `origin/main` advanced three
times while this integration was in flight (ui-2's landing-entry doc commit,
then ui-5 landing) — each rebase after the first was conflict-free since
none of those stories touch `2-5`'s files. The one real conflict was the
`BASELINE_ROUTER_ORDER` list in `test_api_registry.py`: `ui-1`/system-status
added `stats`/`status` on one side, `2-5` added `structure` on the other —
proximity, not disagreement, per the playbook. Resolved by union in
alphabetical order among the default-order (tie-break-by-name) modules:
`config_view, extraction, participants, stats, status, structure`.

**Client-regen hazard for the next agent doing this at the same time as
someone else:** another concurrent agent held `:8000` with an API instance
built from a *different* checkout (plain `main`, pre-2-5). `make client`'s
identity check only confirms the service on the port answers `/health` as
`"meetingminer-api"` — it cannot tell two different commits of the same
service apart, so pointing `make client` at a shared port during concurrent
integration can silently bake in the wrong schema (caught here only because
the diff came back suspiciously small — no `structure`/`series`/`project`/
`product` paths). Fix used: `make start-api API_PORT=18000` to run this
branch's own instance on a private port, `make client API_PORT=18000` to
generate against it, then hand-restore the two literal `baseUrl` occurrences
(`client.gen.ts`, `types.gen.ts`) from `:18000` back to the committed
`:8000` — `CLIENT_URL` is deliberately independent of which port the api
actually bound, so the override doesn't self-correct. Worth a real fix
(e.g. a build/commit identifier in `/health`) rather than repeating this
by hand next time two agents integrate at once.

**Post-merge operations.** `make migrate` applied `0013` — run once against
the shared dev database from the `2-5-integration` worktree, confirmed
idempotent afterward from the main checkout (`nothing to apply`). No
`make rebuild` owed: the five new tables are empty until a human assigns a
meeting (FR25, nothing inferred), so there is no existing corpus data to
backfill or reindex. `make client` regenerated and committed as above. Worker
untouched — these tables are API/projection-only, the worker never reads or
writes them (stated in the migration's own header comment) — restart hold
unchanged.

---


## 4-4 landed, 2026-08-21 — published artifacts become citable knowledge

Merged at `79a6fc8` (`merge(story/4-4-review)`, no-ff). `story/4-4-review`
carries the full remediation: story 4-4's original build (9 review findings,
all patched) plus a follow-up adversarial review that found 13 more (P1-P13),
also patched. `sprint-status.yaml`'s
`4-4-published-artifacts-become-citable-knowledge` key flipped `backlog` ->
`done` by the merge driver (single-sided change, no conflict). Review:
`review-story-4-4-2026-08-21.md`, verdict recorded in the branch's own
history at `5688786`.

**What it does:** the publish gate projects every `published` artifact into
both stores — a Neo4j `Artifact` node with a `CITES` edge to its source
moment, and a keyword-only Meilisearch `artifacts` index (no embedder
declared, so an embed-only rebuild pass never touches it) — surfaced through
`/search` (artifact-first combined paging) and `/chat` (ranked artifact
evidence with reserved prompt capacity, reported in route metadata). An
augmented moment remaps its artifact's source to the unique live
evidence-equivalent replacement rather than leaving it uncitable.

**Rebase, not a clean fast-forward.** `story/4-4-review` predates a 28-commit
chain rebased onto `main` at `e6d5782`. Conflicts resolved by hand, verified non-blind:
- `projections/graph.py`, `projections/stores.py`: proximity — story 2.5's
  `Series`/`Project`/`Product` node-type list and story 4-4's `Artifact`
  entry both appended at the same docstring/tuple position; unioned.
- `test_projections_graph.py`, `test_projections_rebuild.py`,
  `test_projections_search.py`: same shape — story 2.5's and story 4-4's test
  sections both inserted at the same point; unioned in full, each file
  `py_compile`d clean before staging. A later commit's helper-consolidation
  refactor (`insert_artifact` -> delegates to `projection_seed.insert_artifact`)
  auto-merged correctly against the unioned content.
- `deferred-work.md`, twice: not proximity — the *same* entry edited two
  different ways. First time, `main` still
  called the `publish_gate` lock bypass "unreachable, not fixed" while story
  4-4's own remediation had actually fixed it; took the accurate/updated
  text with its `resolution:` field, left every other entry alone. Second
  time, a genuinely new entry (embed-only rebuild still health-checks Neo4j
  even though it writes no graph data) got its own header rather than being
  misfiled under the already-resolved one.
- `api/chat.py`: a real conflict, not proximity. `HEAD` already used
  `_binding_phrase(binding)` — system-status's convention of naming the
  actual `llm.roles.chat` binding in a 503 — while story 4-4's own commit
  still had the older generic "the configured chat model" wording. Kept
  `HEAD`'s version; nothing in `test_api_chat.py` depended on the old phrase.

**Verified post-rebase, before merging:** server targeted suite 299/299;
full server suite 1,620 passed / 34 failed — all 34 the pre-existing
`test_config.py` fixture gap (`pipeline.screens.settled_change_threshold`/
`settled_change_frames` missing from a test template), independently
confirmed unrelated to this story's files; web 257/257; evals 549/549.
Generated client already regenerated and committed within the branch's own
history (`types.gen.ts` +18 lines for artifact fields) — confirmed via `git
diff origin/main..HEAD -- web/src/client/`, not re-derived live.

**Post-merge ops, in order:** no migration owed (no `migrations/` file
touched). `config.yaml` gained a new Meilisearch index shape (the `artifacts`
index — keyword-only, `searchable_attributes: [title, text]`), so `make
rebuild ARGS='--all'` was owed and run: 33/33 meetings, structural 33 /
embedded 33 / failed 0, both stores dropped first. Postgres held 11
already-`published` artifacts (out of 399 total, 388 `extracted`) from prior
epic-4 work that had never been projected before this story's code existed —
confirmed live post-rebuild: `GET /corpus/stats` reports
`publishedDocuments: 11`, and `GET /search?q=decision` returns hits carrying
`artifactId`/`artifactKind`/`artifactTitle`. Api restarted onto the merged
code via `make stop-api start-api` (pid 21473) — not `make up`, which would
also start the worker. Worker untouched; restart hold unchanged; no live
provider endpoint called (Ollama `qwen3-embedding:0.6b` is local).

**Deferred (recorded, out of this story's scope):** embed-only projection
still opens and health-checks Neo4j even though it writes only Meilisearch
vectors — predates this story, needs a search-only store context rather than
an incidental patch (`deferred-work.md`, "story 4-4 review remediation").

**Not yet done:** `story/4-4` and `story/4-4-review` worktrees still exist on
disk (`meetingminer-wt/4-4`, `meetingminer-wt/4-4-review`) and need
`make worktree-remove`; the now-merged remote branches need a delete (ask
first, per the integrate skill's outward-facing gate). `story/4-4`'s own
branch is now superseded non-ancestor content — the review remediation carried its full
intent forward through `story/4-4-review`, not through `story/4-4` itself.

## worker-restart-guidance landed, 2026-08-22 — /status reports worker facts, renders no cost verdict

Merged `story/worker-restart-guidance-codex-review` at `dbd40cc`. Not an epic
story, so it has no `sprint-status.yaml` line — same as `system-status`
and `ui-*`.

**What was wrong.** `_WORKER_STOPPED_REMEDIATION` was a hardcoded constant
telling the owner that restarting "resumes the paused backlog, which can make
paid model calls — so start it only on a fresh explicit yes." Both halves were
false against the committed config: the worker's only `llm.roles.*` call is
`extraction` (`pipeline/stages/extract.py` holds the single `build_llm`;
`chat` is request-path, `judge` is evals-only), and `config.yaml` binds it to
keyless local `ollama/gpt-oss:120b`. The queue depth in the sentence was
hardcoded too, so it read identically at 850 jobs and at zero. It cost a real
session: the owner read it, believed a restart would spend money, and had to
ask before running `make worker` — which then claimed nothing (`requeuedJobs:
0`) and made no calls.

**What it does now.** Reports two facts and no verdict: what `make worker`
would claim, and which binding this api process has loaded, naming
`extraction.fallback` alongside the primary. It states explicitly that a newly
started worker re-reads `config.yaml` and may load a different binding — the
api can only report its own loaded config, not the worker's future one.

**The failed first attempt, because the shape recurs.** The first
implementation derived the cost by classifying the provider through
`KEY_ENV_VARS` and failed open: that map answers "which env var holds this
provider's key", and its own comment says an unknown prefix "gets no key
opinion here", so absence is not evidence of keyless. Reading it as a
free/paid oracle made `gemini/`, `azure/`, `bedrock/`, `groq/` all render as
"served keyless by local {provider}, so starting it spends no money" — the
exact false-free the function existed to prevent. Three independent review
layers converged on it, one by executing the function. Root cause sat inside
the spec's frozen block ("classify paid-vs-free only through `KEY_ENV_VARS`"),
so it was an intent_gap, not a patch: the code was reverted to baseline and
the owner renegotiated the intent to drop the cost claim entirely. **The
lesson: replacing a frozen false premise with a derived one can inherit a new
failure mode. Reporting a fact beats rendering a verdict.**

The invariant is now testable rather than judgemental — the remediation must
contain none of `spend`, `paid`, `free`, `no money`, `costs`, `explicit yes`,
asserted across keyless, key-required, unrecognized, and fallback bindings.
Two of the 14 server cases are pure regression guards pinning `openai/gpt-5.2`
and `gemini/gemini-2.5-pro`. The suite was mutation-checked: reintroducing a
cost claim fails 5 cases, disabling either guard branch fires a raise-only
stub.

**Ops.** Nothing owed — no migration, no projected field, no index shape, no
route or response model (`WorkerStatus` untouched, so no `make client`). The
api was restarted onto merged code via `make stop-api start-api` (pid 43683),
never `make up`. **Worker untouched and still stopped**; the restart hold is
unchanged and nothing here releases it.

**Rebase note for the next lander.** The only conflict in 19 replayed commits
was `deferred-work.md`, and it was pure proximity — two branches appending
different sections at the end. Union both sides; never pick one. Expect this
file to conflict on essentially every landing now.

**Deferred, recorded in `deferred-work.md`.** The same stale paid-backlog
premise still sits in five live artifacts — `spec-system-status/SPEC.md:35`
and its `.memlog.md:25`, `project-context.md:29-32`,
`spec-chat-fallback-timeout/.memlog.md:14,16`, and this repo's own
`.claude/skills/integrate/ops-order.md:61-65`, which still claims "27
real-corpus jobs still sit at `extract`" against a live 0-queued database and
says `chat`/`judge` name `claude-sonnet-5` when `config.yaml` now sets
`openai/gpt-5.2`. **Read that file with that in mind until it is corrected.**
`SPEC.md` and `project-context.md` are derived/managed artifacts — hand-edits
there are overwritten, so they belong to `bmad-spec` and `bmad-project-context`
respectively, not to a build or integrate run.

Also logged: `test_config.py::test_api_stream_intervals_load_from_config` and
`::test_heartbeat_is_capped_at_fastapis_own_keepalive` fail on main, verified
by running them — that file's inline settings dict was never extended when
`pipeline.screens.settled_change_threshold`/`settled_change_frames` became
required at `22af138`. Unrelated to this story.

**Cleanup, done.** Four worktrees existed for this story
(`worker-restart-guidance`, `-review`, `-codex-review`, `-integration`); all
are removed and the working tree is the main checkout alone. Only
`-codex-review` carried the landing content: `-integration` was fully
contained in it, and `story/worker-restart-guidance-review` was a 23-line
`status: in-progress` review stub superseded by the completed 170-line
`status: passed` report — landing it would have regressed the report, so it
was deliberately not merged. Verified main carries the full report before
removing anything. All three remote branches deleted on explicit owner
approval; the remote is `main` only. Recovery SHAs if ever needed:
`story/worker-restart-guidance` 55098fa, `-codex-review` 2186055, `-review`
3054971. Two local refs (`story/worker-restart-guidance`,
`-integration`) survived as non-ancestor superseded content; both were
verified and deleted in the 2026-08-21 integrate run below.

**For the next lander:** a story branch that gets rebased before merge lands
its content without its ref, so `make worktree-prune` reports it as "not
merged" and keeps it. That is the prune working as documented, not a failure —
confirm the content is on main, then `make worktree-remove` explicitly.

## integrate sweep (2026-08-21)

No story landed — nothing was unmerged. `main` and `origin/main` were already
identical at `4bd684f`, the remote carried only `main`, `make check-reviews`
passed, `git worktree list` showed the main checkout alone, and
`make worktree-prune` had nothing to take. Every epic in `sprint-status.yaml`
reads `done`.

**The two surviving local refs are gone.** Before deleting, each was checked
against `main` file by file rather than by ancestry: `status.py`,
`test_api_status.py`, `status.test.tsx`, `spec-worker-restart-guidance.md` and
`review-story-worker-restart-guidance-2026-08-22.md` were byte-identical
between `story/worker-restart-guidance-integration` and `main`, and
`build-prompt-story-worker-restart-guidance-2026-08-22.md` exists only on
`main`. In `deferred-work.md` every line the branches held is present on `main`
in a later form — the crash-recovery entry rewritten as RESOLVED by 4-4, and
"Five further live artifacts" corrected to "Four … plus one historical spec".
`main` was strictly ahead everywhere, so nothing was lost. Recovery SHAs:
`story/worker-restart-guidance` `55098fa`, `-integration` `1631912`.
An empty `meetingminer-wt/` holding only a `.DS_Store` was removed.

**`make test` was red on main and is now green.** The gate ran in full:
`check-client` clean, `puller-test` 124, `web-test` 257, `evals-test` 549,
`server/tests` 1663, `pnpm build` ok. The server half failed 34 tests first —
all of `test_config.py`. The cause was the one already filed in
`deferred-work.md`, but the filed *scope* was wrong: it recorded two failures
because it had been checked through a `-k` filter, and every test in the file
builds the same `VALID_CONFIG` string, so all 34 fail together. Fixed at
`2fd803f` by adding `settled_change_threshold: 0.03` and
`settled_change_frames: 3` to the fixture's `pipeline.screens` block —
`config.yaml:230,234` values, placed in the model's field order. That entry is
now marked RESOLVED. **The lesson: a `-k`-filtered check measures the filter,
not the breakage — count a suspected fixture break by running the file.**

**Ops.** Nothing owed. The fix touches a test fixture only: no migration, no
projected field, no index shape, no route or response model, so no
`make migrate` and no `make client`. The api process from the previous landing
is still up (pid 43683) and needs no restart — no product code changed.

**Worker still stopped; the hold is unchanged and nothing here releases it.**
Measured queue state, for whoever next weighs a restart: `job` is 32 done /
2 failed, and `job_stage` holds exactly one `extract` queued and one `moments`
queued, both belonging to the same failed job (`01a01f6c`). Not the "~850 paid calls" or "27 jobs at
`extract`" that several artifacts still assert — the stale-premise entries in
`deferred-work.md` remain open and still need correcting at the source.

**Test stores.** `meetingminer-postgres` carries no leaked
`meetingminer_test_*` databases, so `make test-db-prune` was not needed. Note
`make` targets live in `infra/Makefile`; the root `Makefile` is a 15-line
forwarder, so grepping the root for a target name finds nothing.

**Stray process, not cleaned up.** A `vite` dev server (pid 41433, port 5183)
is still running out of the deleted `meetingminer-wt/2-3` worktree, and a VS
Code window (pid 59339) still points at the deleted `meetingminer-wt/4-1a`.
Both are host processes outside the repo and were left alone; kill them by
hand if that port is wanted.

## 2026-08-22 — ask-the-corpus break-fix (`884404f`)

**Reported as "test suites are RED on main"; the tests were green.** Full
`make test` on `401ee14` passed end to end: `check-client` clean,
`puller-test` 124, `web-test` 257, `evals-test` 549, `server/tests` 1663,
`pnpm build` ok. The RED was the 34 `test_config.py` failures already fixed at
`2fd803f` during the 2026-08-21 integrate sweep — the report predated the fix.

**The stores were down because OrbStack was not running.** Not a container
crash: the Docker runtime itself was off, so all five containers were absent
and `docker info` failed. Docker Desktop is not installed on this machine —
`open -a Docker` fails; the runtime is `/Applications/OrbStack.app`. Nothing
was lost: 34 meetings, 1813 moments, 1191 chunks, 11 published artifacts, 0
leaked `meetingminer_test_*` databases.

**A green `pytest server/tests` can hide the whole store half.** With the
stores down the suite reported "998 passed" and *skipped 665*. Only
`MM_REQUIRE_TEST_STORES=1` — which `make test` sets and a bare `pytest` does
not — turns those skips into failures. Check `docker info` before trusting a
bare server-suite result.

**Both `demo-readiness-2026-08-22.md` blockers are cleared.** Corpus search
(blocker 1) was a symptom of the stores being unreachable and works now:
`pipeline`, `purchase order`, `retrieval split` each return 20 hybrid hits.
The OpenAI account behind `llm.roles.chat` (blocker 2) has credits again —
verified with a 17-token direct call, HTTP 200.

**The real defect was underneath blocker 2, and it survived the top-up.**
`/chat` answered "the provided moments do not state any decision" for
questions the corpus plainly answers. Cause: `chat._artifact_leg` forwards the
user's whole question into the keyword-only artifacts lane, which ran under
Meilisearch's `last` matching default. `last` drops query words from the *end*
until a match appears, so a question keeps its leading "what did we decide
about" and matches nothing in an index of 11 published titles and bodies.
Measured against the live index: that question returned 0 artifact hits under
`last` and the 2 correct ADR/action-item rows under `frequency`. With the
artifact leg empty only raw transcript text reached the prompt, and the
transcript around the decision is conversational rather than declarative — so
the model's refusal was correct given what it was shown.

Fixed at `884404f` by pinning `matchingStrategy: "frequency"` in
`build_artifact_search_parameters`, with a test. The moments lane is
deliberately unchanged: it is hybrid and its embedder already carries
sentence-shaped input. No fallback was added — `no-silent-fallbacks` (owner
decision, 2026-08-21) removed chat/judge fallbacks on purpose.

Before → after on the same question: cited the 3s welcome moment and reported
nothing found → cites the 259s ADR moment and reports that Peyton committed
to write the ADR for the retrieval split. "What action items came out of the
Q3 Architecture Review?" went from "do not state any action items" to a clean
one-line cited answer.

**Ops.** `make migrate` not needed (no schema change), `make client` not
needed (no route or response-model change). The api was restarted onto the
fix (pid 43683 → 90740) with owner approval; the worker stays stopped.
Targeted suites run: `test_projections_query.py`, `test_api_chat.py`,
`test_api_search.py` — 150 passed. The full `make test` has NOT been re-run
since the merge.

**Vite is bound to IPv6 only.** The dev server (pid 77160) was hand-started as
`pnpm exec vite --port 5173 --strictPort`, without the `--host 127.0.0.1` that
`start-web` passes, so it answers on `[::1]:5173` and not on `127.0.0.1:5173`.
A browser is fine; `make up`'s readiness poll is not. `.logs/web.pid` holds
52548, which is dead, so `make stop-web` will not stop the live process. Left
running rather than restarted mid-demo-prep.

### Corpus publish sweep (2026-08-22, same session)

**All 388 remaining `extracted` artifacts were published on owner instruction**
ahead of the demo. There is no bulk publish surface: the gesture is
`POST /moments/{moment_id}/approve`, which advances every `extracted` artifact
under one moment through `approved` and `published` in a single request. 276
moments held extracted rows, so the sweep was 276 sequential calls — sequential
deliberately, because each `adr` row is git-committed into `MM_PUBLISH_ROOT`
and concurrent calls would collide on that repo's `index.lock`.

Result: 276/276 calls returned 200, 0 failures. Postgres now holds 399
`published` and 0 `extracted`, across 32 of 34 meetings (`Review 2.1b Live
Intake` and one `project- R2C Functional Demo - Task
Order-Standalone-SOW Request` row hold no artifacts at all). The publish repo
went from 4 commits / 11 files to 157 commits / 399 files — 153 new ADR
commits, action items exported as files without commits, which is what
`export.publish_adr` does by design.

**No rebuild was owed.** `approve_moment_artifacts` projects the published rows
after its transaction commits, so the artifacts index moved 11 → 399 documents
during the sweep. Verified directly against Meilisearch.

**Why it mattered for chat.** The artifacts lane is published-only, so before
this sweep ask-the-corpus could cite 11 documents, all from the two scripted
meetings — every question about the 24 real meetings fell back to raw
transcript. After it, questions against the real corpus answer with citations:
"What did we decide about document name collisions during the migration?"
returns the enforce-unique-filenames decision, cited. This is the other half of
the `884404f` fix — that one made question-shaped queries reach the artifacts
lane, this one gave the lane something to find.

**Undo, if it is ever wanted.** There is no unpublish endpoint. Reversal is
manual: `git -C $MM_PUBLISH_ROOT reset --hard 3554757` (the pre-sweep HEAD),
delete the untracked exports, `UPDATE artifact SET state='extracted'` for the
388 ids, then reproject. Recorded here because the api offers no path back.

**UI confirmation.** The meeting rail now tags each row `published ·
adr/<id>.md @ <sha>`, and the "Published documents" section appears on meetings
that had none.

### Hot fix: "Open moment does nothing" from search (2026-08-22, `b41dea4`)

**Reported as a dead button; the button was never dead.** Clicking `Open
moment` on a search hit changed the route and rendered the moment view every
time — DOM inspection confirmed the heading, screenshot, transcript, and all
six published artifacts present. It rendered in the `<Outlet />` *after* the
persistent search/ask chrome, and that chrome stays mounted deliberately so
Back returns to the same result list rather than a blanked query. With a full
page of hits the chrome is taller than the viewport: measured live, the child
sat at 4010px in a 5021px document against a 1610px viewport, so it was not
merely below the fold — maximum scroll (3411px) could not bring it to the top.

**Why only one of the two buttons looked broken.** `Replay` opens its player
inline beside the hit that was clicked, so its result is always on screen.
`Open moment` was the only gesture whose result rendered elsewhere. That
asymmetry is what made it read as a broken button rather than a layout bug.

**Why it surfaced only now.** Search returned zero hits for everything last
night (`demo-readiness-2026-08-22.md` blocker 1), so nobody could reach a
search hit to click. Restoring the stores exposed a UI bug that predates all
of today's work — it is not a regression from `884404f` or from the publish
sweep, though the sweep did put artifact hits at the top of the result list,
which is where the click was tried.

**Fix.** Document order, not scrolling — the same remedy
`spec-meeting-artifacts-below-fold` applied to the analogous rail bug, so DOM
order, tab order, and screen-reader linearization match what the eye should
reach first. The wrapper uses `hidden` rather than unmounting so `main`'s
`gap-8` opens no stray gap on home (a display:none flex child joins neither
layout nor gap). A `scrollIntoView` remains for the other half of the gesture:
the clicked hit may sit far down the list, and opening it should return the
reader to the top.

**Verification.** Live browser, not just unit tests: hit #10 clicked from
scroll offset 1800 lands the moment heading at viewport top (was unreachable);
Back restores the query string and all 20 results; the hidden wrapper measures
0px on home. `pnpm --dir web run test` 257 passed after the edit, and the
production build type-checks and bundles.

**Test gap, recorded not papered over.** No regression test pins the new child
placement — see `deferred-work.md`. `App.tsx` exports only the router-wrapping
default, so covering it needs a new file mocking the entire sdk surface and
every child route's fetches; that was too large to land safely ~30 minutes
before a live demo.

**Full gate.** `make test` passed at 1664 tests, exit 0, run against the
`884404f` tree. Its web half predates this hot fix; the web suite and build
were re-run separately afterwards and both pass. `make test` has NOT been run
end-to-end against `b41dea4`.


## Puller source relocation (2026-08-22)

`pull_transcript/` became `tools/puller/`. Only 17 of its files were ever
tracked; the other 3.0 GB — occurrence folders, `.transcript-profile/`,
`node_modules`, `pulls.jsonl`, `archives.txt`, launchd logs — moved to
`/Users/devopsterus/current/pull_transcript`, which keeps its own copy of the
source because `--all`, `--login` and `--replay` all resolve against
`__dirname`. Only the untracked entries were moved, so the shared main checkout
never went dirty in `git status`.

**It did break `make test` there, though, and the first version of this note
claimed otherwise.** `node_modules` went with the untracked entries, and
`puller-test` is the FIRST prerequisite of `test:`, so the whole gate stopped at
"puller dev deps missing" for every agent on that checkout. Restored with
`npm --prefix pull_transcript install`; the merge removes that directory and the
320K remainder with it. Clean in `git status` is not the same as working, and
the move is invisible to `git log` — which is why it is written down here.

The move would have silently retired AD-1's puller-side contract check.
`test/emit-drop.test.js` resolved `docs/source-drop.schema.json` by counting two
`../` segments; at `tools/puller/test/` that lands on `tools/docs/…`, and the
ENOENT it produces is exactly what the standalone-checkout branch converts into
a skip. `npm test` would still have exited 0, and neither the `puller-test`
Makefile guard nor `test_makefile_procs.py` catches it — both stay intact while
only the JS resolution breaks. Fixed twice over: resolution searches upward so
depth cannot matter, and `puller-test` runs with `MM_REQUIRE_DROP_SCHEMA=1` so a
miss inside this repo fails loudly instead of skipping. That mirrors
`MM_REQUIRE_TEST_STORES=1` in `make test`, and `test_makefile_procs.py` now
asserts the recipe carries it, the way `test_compose_contract.py` does for the
stores flag.

The root `puller -> pull_transcript` symlink is deleted rather than repointed.
Nothing operational traversed it — `infra/Makefile` and
`tools/puller-package/build.sh` both used the real path — and a root entry
pointing at the puller works against moving it out of the root.
`build.sh`'s `ORG_CHART_SRC` still names `/Volumes/nvmepool/mm_current/`; that
is the external summariser lineage, not this directory, and must not be
retargeted.

**Testing deferred by owner decision (2026-08-22).** `make test` was NOT run for
this change — the full gate is deferred to a dedicated testing pass once the
whole reorg is finished, rather than paid per reorg story. What did run:
`make puller-test` (125 pass, 0 skipped), `test_makefile_procs.py -k puller`,
`make puller-package`, and `emit-drop.js --all --dry-run` against the relocated
archive (29 planned, 0 skipped, 0 failed). The server suite, web suite, eval
suite and web build remain unverified for this change and are owed to that pass.

## 2026-08-22 — integrate: `puller-source-relocation` landed at `86a763b`

Rebased onto `371634c` and merged `--no-ff`. Two conflicts, both the proximity
kind `conflict-playbook.md` describes and both resolved by union, not by
picking: `sprint-notes.md` and `deferred-work.md` (two
independent entry blocks). No code file conflicted, so no suite outside the
branch's own was invalidated.

**The remote is gone.** `git@github.com:tgoeke/meetingminer.git` answers
"Repository not found" while SSH still authenticates as `tgoeke`; it was
reachable earlier the same day. So nothing here was pushed and nothing can be
— `origin/main` is a stale local ref, and every branch listed under
`remotes/origin/` is a tracking ref for a repository that no longer exists.
Local `main` is now the only copy of this work. Treat Phase 1's
`git fetch origin && git rebase origin/main` as `git rebase main` until a
remote exists again.

Operations owed from `ops-order.md`: **none**, verified against the diff rather
than assumed — `git diff --name-only 371634c..86a763b` touches no file under
`server/meetingminer/migrations/`, no `server/pyproject.toml`, no
`web/src/client/`, no `config.yaml`, and nothing under `server/meetingminer/api/`.
The worker was not started and the gate on it is untouched.

**Two things the merge leaves for any other clone or worktree.** `puller-test`
resolves `$(PULLER)` to `tools/puller` now, so a tree whose `node_modules` still
sits at the old path errors with "puller dev deps missing" — and because
`puller-test` is the FIRST prerequisite of `test:`, that takes down the whole
gate, not just the puller suite. Run `npm --prefix tools/puller install`. The
main checkout also kept an untracked `pull_transcript/` holding only
`node_modules` and a `.DS_Store` after the merge deleted the tracked files;
removed here, but another worktree will have its own.

The puller now exists twice on purpose: tracked source at `tools/puller/`, and a
working archive outside the repo holding the meeting corpus and the signed-in
browser profile (`/Users/devopsterus/current/pull_transcript` on this machine).
The archive is what pulls real meetings, `tools/puller/` is what `make test`
covers, and they drift — they had already drifted on the commit that created the
split. `make puller-archive-check MM_PULLER_ARCHIVE=<dir>` reports it,
`make puller-sync` fixes it. Neither joins `make test`, because the path is
per-machine.

**Testing deferred by owner decision.** `make test` was not run for this change;
the full gate is one dedicated pass after the whole reorg. What ran:
`make puller-test` (128 pass, 0 skipped), `pytest -k puller` (4, negative-tested
against a stale binding and a disagreeing `build.sh`), `make puller-package`,
and the archive drift check. The server, web, eval and web-build halves remain
unverified for this change and are owed to that pass.

**This unblocks `spec-repo-reset-to-clean-history.md`,** which held its scrub
until this landed. Two things for whoever picks it up: re-derive the file list,
since the four puller Code Map paths moved from `pull_transcript/` to
`tools/puller/` and `test/emit-drop.test.js` line numbers all shifted (the
tenant URL and employee number it names were at `:90,93`); and that spec's
Verification line still reads `cd pull_transcript && npm test`, which is now
`make puller-test`. Worth knowing before the scrub: no meeting content was ever
committed — exactly 17 paths were ever added under `pull_transcript/`, all
source — and the largest blob in the entire history is a 3.66 MB screenshot.

## 11-1 dispatched, 2026-08-29

Story 11-1 (Seconds-Fast Default Suite) dispatched under Sprint Change Proposal
2026-08-29, Addendum 2, which sets the order **11 → 6 → 10 → 7 → 8 → 9**.
Build prompt: `build-prompt-story-11-1-2026-08-29.md`. Worktree
`../meetingminer-wt/11-1` on `story/11-1`, bootstrapped, no commits yet at the
time of this note. `epic-11` and `11-1` flipped to `in-progress` at 12:52.

Sequencing while it runs: 11-2 follows on the same files and does not start
until 11-1 lands. 6-1 (UX design spec) is the only other story cleared to run
alongside — it touches no code. 6-2 waits for both 11-1 and 11-2.

**6-1 prompt written, 2026-08-29 13:10 — not dispatched.**
`build-prompt-story-6-1-2026-08-29.md`. Design-only story (`bmad-ux`,
headless, creative tools on, local files only); cleared to run alongside 11-1
by Addendum 2. Its output path is under the gitignored `_bmad-output/`, so the
spec will not reach GitHub until the owner decides on that ignore. Launch is
the owner's call; 6-1 stays `backlog` until then.

**6-1 and 6-7 launched by the owner, 2026-08-29 13:03.** Three
lanes in flight: 11-1 (tests/pyproject/Makefile/AGENTS/project-context/
backlog B-1), 6-7 (`config.yaml` only), 6-1 (design workspace only). Under
the no-caveat rule no further story is independent of all three; see the
status report of this time for the per-story blocker.

## 2026-08-29 — 6.7 landed at `ab07263`

Story 6.7 (extraction prompt wording generalized) landed on `main` as a
cherry-pick of `story/6-7` (`ef34e64`, `d39bf0a`) onto `5af6fbd`; pushed.
Review `review-story-6-7-2026-08-29.md`: triage clean, no findings; its
verification was left pending by the review session and run by the
dispatcher before landing — `Microsoft Teams` count 0, 160 store-free tests
passed, `test_api_prompts.py` 1 passed against the running stores. Branches
`story/6-7` and `story/6-7-review` and their worktrees are left for the
owner to prune (`make worktree-remove STORY=6-7`, `STORY=6-7-review`).

## Sprint-planning refresh, 2026-08-29 13:26

`bmad-sprint-planning` re-run against `epics.md` (11 epics, 66 stories).
Readiness gate: PASS — FR33–FR43, NFR19–NFR20 and UX-DR12–UX-DR18 are all in
the requirements inventory and the FR coverage map; every story in epics 6–11
cites at least one of them (6.7 cites the existing FR19); every AD cited
(AD-1…AD-17) is defined in `docs/architecture.md`; every backlog id cited
(B-1, B-4, B-11, B-12, B-13, B-14) exists in `docs/backlog.md`; no unmerged
branch touches `docs/architecture.md`. Generator report: in sync, no new
entries, no orphans, nothing upgraded from disk.

One status changed by hand: **6-7 → `review`.** Evidence: `story/6-7` carries
two build commits (`ef34e64`, `d39bf0a`) touching `config.yaml` and
`test_extraction_core.py`; `spec-6-7` frontmatter reads `status: done`; the
reviewer's report is filed on `story/6-7-review` (`f0336df`, `53e9318`) with no
surviving findings and Verification still "Pending". Not merged to main, so
not `done` under the "done, landed" convention this file uses.

**Hazard on `story/6-7-review`.** That worktree has a real `_bmad-output/`
directory (not the symlink `11-1` and `6-1` use), and the branch force-added
`_bmad-output/implementation-artifacts/sprint-status.yaml` (142 lines,
`6-7: done` at 13:18) past the `.gitignore` entry from `cf0214b`. Merging the
branch as-is makes a stale snapshot of the tracking file tracked on main.
Whoever integrates it: take the review report, drop the yaml from the merge.

Stale comment in `sprint-status.yaml`: its header names
`_bmad/scripts/merge_sprint_status.py` as the key-wise merge driver; that
script is not in the tree.

`story/6-7` and `story/6-1` were cut at `e5510c7`, one commit behind main's
`5af6fbd` (`docs/owner-runbook.md`); a `git diff main..story/6-7` shows the
runbook as deleted for that reason only — the rebase-before-merge rule
resolves it.

Design companion for 6.5 / 7.4 / 8.3 / 10.5 / 10.6: story 6.1 is writing
`_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/`
(`DESIGN.md` status `draft` at this refresh). The main checkout owns that
directory and `11-1`/`6-1` reach it through the symlink, so a builder in a
worktree created the same way reads the current copy; it is not on GitHub.

## 6-1 integration check, 2026-08-29 ~16:15

Confirmed on main `183bdf1` = `origin/main`: fast-forward, no merge commit;
13-file design set + review report + build prompt tracked; `DESIGN.md` and
`EXPERIENCE.md` `status: final`; review verdict `approved`; `6-1: done`.

Three things the completion report did not say:

1. **Story 6.7 landed on main with it.** The 6-1 review chain was based on
   `story/6-7-review`, so `f1d3ad9` and `ab07263` (byte-identical to
   `story/6-7`'s `ef34e64`/`d39bf0a`) are on main. 6.7's review report is not
   on main and its Verification step was still "Pending". `6-7` stays `review`
   until that verification is filed; `story/6-7`, `story/6-7-review` and their
   worktrees are now redundant.
2. **Tracked but ignored.** `sprint-status.yaml`, `review-story-6-1`, and
   `build-prompt-story-6-1` are tracked while `.gitignore:47` still matches
   them. Edits to them show up; a *new* file beside them (the next review
   report) is silently ignored unless `git add -f`.
3. **The `_bmad-output` symlink convention breaks at this commit.** Probed in
   a throwaway worktree: with `_bmad-output` replaced by the symlink, `git
   status` at main shows 17 tracked files as deleted plus `?? _bmad-output`,
   and `git add` under it fails "beyond a symbolic link". `11-1`, `11-1-review`
   and `6-1` use that symlink; the moment they rebase onto main they go dirty,
   and a `git commit -a` there would delete the design set. Either drop the
   symlink (real dir, sync the untracked notes another way) or stop tracking
   under `_bmad-output/`.

`story/6-1` build worktree (`e5510c7`, no commits) and branch
`story/6-1-review` (local + origin) are leftover; removable.

**Cleanup, 2026-08-29 ~16:25.** Removed: worktree `6-1` (symlink unlinked
first; main's `_bmad-output` untouched) and branches `story/6-1`,
`story/6-1-review` (local + origin). `make worktree-prune` removed worktree
`6-7` and local `story/6-7` (`origin/story/6-7` still exists) — content is on
main as `f1d3ad9`/`ab07263`. Kept: `11-1`, `11-1-review` (dirty),
`6-7-review` (holds the unmerged 6.7 review report; verification still owed).

## Epic 6

### `6-1-ux-design-spec-for-the-new-flows` — done, landed 2026-08-29

Landed on main by fast-forward at `183bdf1` (review chain `82541fe..2c7af74`,
remediation `a0f0aad`, status `a201a79`, handoff `183bdf1`); `origin/main`
matches. Tracked: `DESIGN.md`, `EXPERIENCE.md` (both `status: final`),
`adoption.md`, `findings-for-epics.md`, `validation-report.{md,html}`, seven
mockups under `mockups/`; `.gitignore` allowlists exactly that set.
`review-story-6-1-2026-08-29.md`: verdict approved, 14 retained findings all
resolved. `make check-reviews` passes (restored at `9826866`).

What a follow-on builder needs: every UI story in epics 6, 7, 8, 10 cites this
design and deviates only with a recorded reason. `findings-for-epics.md`
carries 25 decisions the design forced; F-1/F-2/F-23/F-24 (dark class, shell
widths, focus ring, control borders) belong to 10.5, F-15 to 6.6, F-25 (nine
glossary terms) to whoever next edits `docs/glossary.md`.

Post-merge operations: none owed — the landing changed `.gitignore`, the
design set, and (via 6.7) `config.yaml` prompt text; no migrations, no
`pyproject`, no api surface, no client.

### `6-7-extraction-prompt-wording-generalized` — done, landed 2026-08-29

Code landed with 6-1's fast-forward as `f1d3ad9`/`ab07263` (rebased copies of
`story/6-7`). Review (`story/6-7-review`, `53e9318`): no surviving findings,
verification left pending. Verified on main `9826866` during the 6-1 integrate
pass: `server/tests/test_extraction_core.py` 105 passed. Review report copied
into this directory from the review worktree; the worktree and local branch
are removed; `origin/story/6-7` and `origin/story/6-7-review` deleted on the
owner's go, 2026-08-29 ~18:00.

**Worker restarted by the owner 2026-08-29 17:50:39 (pid 55352, `worker.startup` logged); `config.yaml` in that checkout carries the generalized wording (2 hits, 0 Teams-specific). Nothing remains owed for 6-7.** Earlier text kept for the record: worker restart. The worker (pid 7604) started 13:49:25
from the main checkout and `worker/main.py:91` loads `config.yaml` once at
startup; the generalized prompt wording reached that checkout at ~16:06. Until
a restart, extraction runs with the "Microsoft Teams meeting" preamble. Queue
is empty (`/status`: 0 in flight, `done: 2`), so a restart drains nothing —
the paid-ops gate still needs a fresh yes.

## Integrate pass, 2026-08-29 ~17:45 (6-1 double-check)

- Addendum 3 re-sliced the epics (71 live stories). `7.5` and `10.7` were kept
  as `### Story` headings with a "merged, id retired" note, which the tracking
  generator read as two new backlog stories; demoted both to bold paragraphs
  so the ids stay recorded and nothing re-creates them.
- 11-1: build complete on `story/11-1` (`15fdbe2`, spec `done`); review
  **failed** — 10 patch findings, 0 decisions (`review-story-11-1-2026-08-29.md`,
  on disk only, not force-added by reviewer policy). Stays `in-progress`;
  remediation goes back to the builder via `build-prompt-story-11-1`.
- The `_bmad-output` symlink hazard recorded earlier did not bite 11-1-review:
  that worktree now has a real directory (the rebase onto `183bdf1` checked the
  tracked files out). `11-1` still has the symlink and is still based at
  `e5510c7`; it hits the hazard when it rebases.
- `merge.sprint-status` driver is registered in this clone (relative path).

## Wave dispatched by the owner, 2026-08-29 ~18:05

Two lanes in flight: **11-1 remediation** (worktree `11-1`, `story/11-1` at
`15fdbe2`; ten patch findings from `review-story-11-1-2026-08-29.md`) and
**6-6 YouTube deep links** (worktree `6-6`, `story/6-6` cut from `a720310`).
`6-6` flipped to `in-progress`; `epic-6` already was.

Caution for the 6-6 lane: its worktree's `_bmad-output/` is a real directory
containing only the tracked files (the 6-1 design set and
`sprint-status.yaml`). `epics.md`, `spec-*`, this file and `deferred-work.md`
are reachable only from the main checkout's `_bmad-output/`. The `11-1`
worktree still uses the hand-made symlink and is based at `e5510c7`; it
meets the tracked-files-under-a-symlink hazard when it rebases onto main.

Under the no-caveat rule nothing else is independent of both lanes: 11-2/11-3/
11-4 and every server-test-adding story wait for 11-1; 6-2 waits for 11-1 and
11-2; the remaining UI stories wait for their APIs.

## `_bmad-output/` is never pushed — owner rule, 2026-08-29 ~18:15

The repository will be visible to the cohort, and this directory is the
process record (specs, build/review prompts, review reports, tracking, the
design workspace). Owner: do not disclose it. Actions: the 16 files tracked
today (design set, `review-story-6-1`, `build-prompt-story-6-1`,
`sprint-status.yaml`) are untracked at the tip and `.gitignore` is back to a
plain `_bmad-output/`. Files stay on disk. **Never `git add -f` under this
directory** — the 6-1 review prompt's instruction to do so is withdrawn.

Consequences:
- `sprint-status.yaml` is local again; flips happen in the main checkout's
  copy (worktrees reach it through the symlink). The `merge.sprint-status`
  driver and `.gitattributes` line stay registered but have nothing to merge.
- The 6-1 design set is shared the same way; a worktree whose `_bmad-output`
  is a real directory (`6-6`, `11-1-review`) keeps a frozen copy — read the
  main checkout's for the current one.
- The tracked-files-under-a-symlink hazard is gone with the tracking.
- The 13 commits `82541fe..d8a279f` still carry these files in history on
  `origin/main`, `story/11-1-review`, and `story/6-6`. Removing them needs a
  history rewrite and force-push — owner decision pending.

## 11-1 re-review: changes requested, 2026-08-29 (integrate pass, no merge)

`review-story-11-1-rereview-2026-08-29.md` (on disk only, `_bmad-output` is
never pushed). All ten first-round findings verified fixed on
`story/11-1-review` at `31ff539`. Three new medium findings, all
verification/enforcement gaps, none in the mechanism itself:

1. The `test-fast` contract pins the server argv but not the four store-free
   prerequisites; dropping `web-test` from the target line stays green.
2. The exact slow-set inventory covers module-level `pytestmark` only; the
   four function-level marks are uninventoried, so a fifth shrinks the fast
   set silently.
3. The twin-fixture collection rule reads the static fixture closure;
   `request.getfixturevalue("projection_stores")` from an unmarked test
   bypasses it. No production use today.

Verified against the code before writing the handoff; all three hold.

**Not landed.** `11-1` stays `in-progress`; spec stays `in-review`. Round-2
builder handoff written: `build-prompt-story-11-1-remediation-2-2026-08-29.md`
— rebase onto `a22d67c` first (Makefile `.PHONY`/`help` union conflict, known),
then F3 plugin backstop with pytester probes, F1/F2 contracts, gate, push,
stop. **Dispatched by the owner from another session** (recorded here
~22:00). A third review follows it.

No post-merge operation is owed: nothing merged. Worker stays stopped; the
restart hold stands. No worktree removed: `11-1-review` is the live lane;
`11-1` (`story/11-1` at `15fdbe2`, base `e5510c7`) is superseded by the
rebased review branch and can go with it once the story lands — not before,
its branch is the reviewed provenance. `6-6` and `6-6-review` belong to the
in-flight 6-6 lane.

Cautions carried forward: after the rebase the `11-1-review` worktree's real
`_bmad-output/` empties (main untracked those files at `a22d67c`); every
process artifact is read and edited under the main checkout. `story/11-1`
and `story/11-1-review` stay on the remote until the story lands and the
owner says delete.

Dispatch under the no-caveat rule: unchanged from 18:05 — 11-2/11-3/11-4 and
every server-test-adding story wait for 11-1; 6-2 waits for 11-1 and 11-2;
6-6 is in flight. Nothing new is independent of both lanes.

## 6-6 landed at `28ea43d`, 2026-08-29 ~21:45 (integrate pass)

Landed by the review agent as a fast-forward: `story/6-6` (`a8ae945`,
`f5c4918`) rebased onto `a22d67c` as `story/6-6-review-integrate`, plus the
review's one remediation (`eef842d` → `28ea43d`, unsafe source text stays
visible as inert text beside Replay). `main` = `origin/main` = `28ea43d`.
Review `review-story-6-6-2026-08-29.md`: 1 low finding, patched; verdict
passed. `6-6: done` was already flipped. Web-only: 13 files under `web/src`
(`SourceLinkAnchor`, `affordance.ts`, chat/moments/search surfaces and tests).

Verified on `main` at `28ea43d` this pass: `make web-test` 16 files / 291
passed. Reviewer also ran the production build and lint on the identical tree.

**Post-merge operations owed: none.** No migration, no projected field, no
route or response model — `make client` is not owed. Worker stays stopped.

**Known gap, filed in `deferred-work.md`:** the `moments` stage nulls
`source_deep_link` once replay exists, so recorded YouTube meetings show the
secondary link only on the drill-down header. Server-side fix waits for 11-1
(it owns `test_worker_moments.py`/`test_augmentation.py`); the backlog entry
waits for 11-1 too (it rewrites `docs/backlog.md`).

Cleanup done: `make worktree-prune` removed worktree `6-6` and local
`story/6-6`; local `story/6-6-review` and `story/6-6-review-integrate`
deleted. Remote `origin/story/6-6`, `origin/story/6-6-review`,
`origin/story/6-6-review-integrate` deleted on the owner's yes, ~21:55. Kept: `11-1`
(superseded, `?? _bmad-output` symlink only) and `11-1-review` (live lane).

Dispatch: one lane in flight — 11-1 remediation round 2, launched by the
owner from another session. Nothing is caveat-free of it: 11-2/11-3/11-4 and every
server-test-adding story (6-2, 10-1, 7-1) wait for 11-1; 10-5/10-6/7-4 wait
for their APIs; 6-2 additionally waits for 11-2 (Addendum 2).

## Sprint-planning refresh, 2026-08-29 21:50

`bmad-sprint-planning` re-run against `epics.md` (11 epics, 71 stories).
Readiness gate: PASS — unchanged from the 13:26 refresh; FR33–FR43,
NFR19–NFR20, UX-DR12–UX-DR18 in the inventory and coverage map; every
epic 6–11 story cites at least one; the 6-1 design set is `final` on disk
under the main checkout's `_bmad-output/` (local only, per the 18:15 rule).
Generator: in sync, 46 done / 3 in-progress (`epic-6`, `epic-11`, `11-1`) /
33 backlog, no new entries, no orphans. Only `last_updated` changed.

State confirmed on disk, not in the earlier notes:

- **6-6 is done and landed.** `a5b851c` feat, `51d4182` review patch, `28ea43d`
  follow-up on `main`; `review-story-6-6-2026-08-29.md` filed (one low finding,
  patched in the review lane); `spec-6-6` `status: done`. Worktree `6-6` and
  branches `story/6-6`, `story/6-6-review` (local and origin) are gone.
- **11-1 remediation round 2 is in flight**, not waiting on a go: worktree
  `11-1-review` on `story/11-1-review` rebased onto `a22d67c`, tip `ba1d39e`
  at 21:49, `test_fast_budget.py` dirty. Superseded worktree `11-1`
  (`story/11-1` at `15fdbe2`) still registered as reviewed provenance.
- The "pin the fast-set count" in 11-1 is a Makefile recipe comment
  (`infra/Makefile`, counts re-pinned each rebase), not a test assertion — a
  later story that adds server tests does not break 11-1's contract on merge.

**Dispatch under the no-caveat rule: nothing is launchable beside 11-1.**
11-1's diff edits `server/pyproject.toml`, `conftest.py`, and 24 existing
test modules (marks and timeouts), plus `infra/Makefile`, AGENTS.md and
`project-context.md`. Per remaining story, the shared file:

- 11-2, 11-3, 11-4 — `conftest.py`, `infra/Makefile`, AGENTS.md (recorded order)
- 6-2 — `server/tests` (recorded: waits for 11-1 *and* 11-2); 6-2a after 6-2
- 6-3 — `test_mint_drop.py` is in 11-1's diff
- 6-4 / 6-4a / 6-5 / 6-5a — depend on 6-2 / 6-3 tools and on each other
- 7-1 — `server/pyproject.toml` (engine dependency); 7-2 → 7-3 → 7-4 chain
- 8-1 — `test_config.py` and `project-context.md` are in 11-1's diff; 8-2 → 8-2a → 8-3 after it
- 10-1 — new server tests under 11-1's marker/budget rules; 10-2 … 10-6a chain after it
- 9-1, 9-2 — need epics 6, 7, 8 (and 10 per the revised order)

Next unlock: when 11-1 lands, **11-2 alone**. Chokepoints to expect after
that, before assuming a wider fan-out: `infra/Makefile` (6-2's target, 11-3,
11-4) and `config.yaml` / `config.py` (6-2's caps, 7-1's engine, 8-1's
catalog, 10-1's prompt) — each pair sharing one of those is a sequence, not a
pair.

## `11-1-seconds-fast-default-suite` — done, landed 2026-08-30

**What landed.** `main` fast-forwarded to `71b3ccb` (story/11-1-fourth-review)
at 09:23 by the review lane, then `8b55dc1` (status done) and `0e30294`
(completion handoff). Reviewed range `28ea43d...2ce91b3`; fourth-review
patches `b66636a`, `484f886`, `7228d70`. Gate as reported by the review lane:
1,727 server tests with `-m ""`, `make test-fast` 1401 passed / 326
deselected in ~51s, store-free suites and web build green.

**What is true now.** `server/pyproject.toml` defaults every pytest run to
`-m 'not slow' --strict-markers` with a 2.0s per-test call-phase budget
(`tests/fast_budget.py`, loaded via `pytest_plugins` in `conftest.py`).
`make test` and `make check-test-stores` pass `-m ""`; `make test-fast` is
`check-client` + the fast selection + the store-free suites. A by-path run
of a `slow` module without `-m ""` deselects everything and exits 5 with a
hint. `REPO_ROOT` moved from `conftest.py` to `tests/repo_paths.py`. B-1 in
`docs/backlog.md` is closed on measured numbers (9m17s full run at `e5510c7`,
not ~33 minutes).

**Post-merge operations: none owed.** No migration, no API surface, no
`config.yaml`, no projected field, no new `[project.scripts]` (the venv
already carries all five). The worker was not touched; the restart hold
stands as before.

**Caution — `_bmad-output` was re-tracked and pushed.** The 11-1 review
branches force-added six files under `_bmad-output/implementation-artifacts/`
(the spec, `sprint-status.yaml`, two review reports, two build prompts)
despite the ignore rule from `a22d67c`, and they reached `origin/main` in
`71b3ccb`..`0e30294`. `a3ffdc9` untracks them again (working files kept).
They remain in history on the private remote by owner decision
(2026-08-30: a rewrite is "useless"); forward untracking is the whole fix. Anyone rebasing a branch that still tracks
those paths will re-add them — check `git ls-tree -r --name-only HEAD --
_bmad-output` is empty before pushing.

**Deferred** (filed in `deferred-work.md`): README fast-loop text,
`project-record.md` entry, the ~1,000-test fixture-cost residue.

**Unblocked by this landing.** The 6-6 note's owed `docs/backlog.md` entry
for `source_deep_link` retention beside replay (the stage nulls it once a
recording exists; tests live in `test_worker_moments.py` /
`test_augmentation.py`, which 11-1 owned) is filed in this session.

**Cleanup.** Worktrees `11-1-review` (pruned, merged) and `11-1` (superseded
provenance, symlink only, force-removed) are gone; `11-1-fourth-review` was
removed by the review lane. Local `story/11-1`, `story/11-1-review`,
`story/11-1-fourth-review` deleted. Remote `origin/story/11-1`,
`origin/story/11-1-review`, `origin/story/11-1-fourth-review` deleted on the
owner's yes, 2026-08-30 ~09:45.

**Dispatch.** Per the 2026-08-29 21:50 note: **11-2 alone.** 11-3 and 11-4
share `infra/Makefile` / `conftest.py` / AGENTS.md with it; 6-2 waits for
11-2 (Addendum 2); everything else chains behind one of those.

### `6-2-youtube-acquisition-command` — review, 2026-08-30

Built inside the wave footprint. `server/meetingminer/youtube.py` (new) owns
URL classification, the named refusal matrix, caption selection, the
`yt-dlp` download, and the `info.json` -> metadata mapping; assembly goes
through `mint()` via three new keyword overrides (`source_id`,
`started_at_override`, `provenance_extra`) that default to today's behaviour
— `test_mint_drop.py` and `test_config.py` unchanged and green.
`AcquisitionConfig`/`YoutubeAcquisitionConfig` sit immediately before
`Settings` with `acquisition` as its last, defaulted field; `config.yaml`
carries the block explicitly at EOF; `youtube-drop:` sits directly after the
`mint-drop` recipe with a named `URL=` guard; `docs/README.md` gained
"Ingesting a YouTube video" at the end of the file, after "Bringing your own
recording".

Verified: `server/tests/test_youtube.py` 43 passed offline (network test
skipped by name); `make test-fast` 1444 passed; the env-flagged network test
passed for real against a 19-second public video (real download, minted drop
schema-valid, `exists` on re-run, no POST). The machine's Homebrew `yt-dlp`
had gone stale (2026.07.04 -> HTTP 403 on media); upgraded to 2026.08.19,
after which the real run passed — expect the same on other machines.

Deferred (recorded in the spec frontmatter): the network test is env-flagged
but not `slow`-marked; at integrate add the `pytest.mark.slow` decorator plus
the one-line `SLOW_TESTS` pin in `test_compose_contract.py`, which is outside
this story's footprint.

## Sprint-planning, 2026-08-30 ~13:30 — the dispatch rule is measured now; six lanes

**Owner direction (verbatim in substance).** "The whole reorg and redesign of
the testing and stories being broken down was to allow for more parallel
stories to run. No more excuses. Come up with a way to run more stories." And,
minutes later: "let's just stop gitignoring `_bmad-output` since it's causing
so much chaos. Go ahead and commit it and push it. Remove any mention that it
should be gitignored."

**What was wrong with the rule as applied.** The 2026-08-19 no-caveat rule was
being tested by *filename*: any shared file meant sequence. Git does not
conflict on filenames; it conflicts on overlapping or adjacent changed regions.
Tested by region, 11-2's branch (`config.py` 2–50 / 750–1010, `test_config.py`
appended at EOF, `AGENTS.md` 37–175, `test_compose_contract.py` 10–100,
`Makefile` hunks listed by `branch_conflicts.py --hunks story/11-2`) leaves
`ExtractionRoleBinding`, `DiarizerConfig`, `Settings`, `mintdrop.py`, `evals/`,
the `evals-run`, `mint-drop` and `test-fast` recipes, and `[project]` /
`[dependency-groups]` in `pyproject.toml` all untouched.

**The amended rule.** Two stories run in parallel when (1) their changed
regions are disjoint — checked with `git merge-tree --write-tree`, now wrapped
as `_bmad/scripts/branch_conflicts.py` (pairwise matrix of every `story/*`
branch and `main`; `--hunks` prints a branch's regions in `main` line numbers),
(2) neither's acceptance criteria reference the other's deliverable, (3) no
operational gate (paid roles, the worker) binds one of them, and (4) docs
overlap is by *section*, not by file. A footprint written into a builder's
prompt — exact files, exact anchors, new tests in new files, never
`conftest.py` — is part of that story's contract, not a caveat: it is not
dropped at handoff, it is what the builder is held to. `dispatch.md` is
updated to this wording at 11-2's integrate (11-2 edits its step 2).
Common rules for the wave: `wave-2026-08-30-rules.md`.

**11-2 review outcome.** `review-story-11-2-2026-08-30.md` (on
`story/11-2-review` at `d3792db`, copied beside this file): does not pass — 10
patch findings (4 high: metadata validation, two pruner-ownership paths,
pre-11.2 recovery routing; 3 medium; 3 low), 0 decisions, 0 spec defects. The
provisioning itself worked: the review lane got its own stack
(`meetingminer-11-2-review`, ports 20431–20437). `11-2` is `in-progress`;
remediation prompt `build-prompt-story-11-2-remediation-2026-08-30.md`. The
lane also force-added three `_bmad-output` files and pushed them — the third
time a review lane did this, because `_bmad/custom/bmad-code-review.toml`
mandates committing the report. That contradiction is what the owner ended.

**`_bmad-output` is tracked** from this session's commit. Removed: the
`.gitignore` block, the `.git/info/exclude` line, the "gitignored" sentences in
`.claude/skills/integrate/SKILL.md` and `_bmad/scripts/check_review_reports.py`.
Ignored underneath it: `.cc-writes/`, `.snapshots-tmp`, `.DS_Store`. Before
adding: 489 files, 24 MB, no file over 1 MB, no secret-shaped strings; mail
domains and tenant hosts are placeholder vocabulary only (the 2026-08-29
redaction pass covered this tree — see the scrub spec's inventory). Person and
client names could not be re-verified here: the identity map is on the
archive server. Worktrees created before this commit hold `_bmad-output` as a
hand-made symlink; `rm` the link before rebasing onto `main` (the 11-2
remediation prompt says so). Worktrees created after it get the directory from
git and need no symlink. 11-2's branch text saying the directory is never
pushed is corrected at its integrate.

**Dispatched prompts (owner launches).** Wave A, now, beside 11-2 remediation:

| lane | prompt | why it is clean against the others |
|---|---|---|
| `6-2` | `build-prompt-story-6-2-2026-08-30.md` | `youtube.py` new; `mint()`/`build_metadata()` keywords; `AcquisitionConfig` before `Settings`; `youtube-drop` after `mint-drop`; `docs/README.md`. Supersedes Addendum 2's "6.2 waits for 11.2" by owner direction. |
| `10-1` | `build-prompt-story-10-1-2026-08-30.md` | `ExtractionRoleBinding.topics_prompt`; extraction modules; migration 0014; new test files only. |
| `7-1` | `build-prompt-story-7-1-2026-08-30.md` | new engine module; `DiarizerConfig`; `[project.optional-dependencies]`; `HF_TOKEN` in `.env.example`'s keys block. Owner input: the token. |
| `11-3` | `build-prompt-story-11-3-2026-08-30.md` | `evals/**`; `evals-run` recipe; one AGENTS.md sentence edited after rebase. No paid run. |
| `11-4` | `build-prompt-story-11-4-2026-08-30.md` | `pyproject` dev group + tool tables at EOF; `lint`/`typecheck` before `test-fast`; `TEST_FAST_PREREQUISITES`. No lint sweep. |

Wave B, when 11-2 lands: `8-1` (its AD-10 wording and `project-context.md`
policy line overlap 11-2's — a real same-paragraph overlap, not proximity).
Then the chains: `6-3` and `6-2a` after `6-2` (both edit `mint()` — 6-3's
dialect conversion should ride 6-2's keyword overrides); `6-4` after 6-2 and
6-3; `10-2` after `10-1`; `7-2` after `7-1`; `8-2` after `8-1`. `9-1`/`9-2`
after the epics they demo.

**Cross-lane fact every prompt carries.** 11-2's `check-env` refuses a linked
worktree without `.env.worktree`; after rebasing onto a `main` that contains
11-2, each lane runs `make worktree-provision` once. Six private stacks at
~1.9 GiB idle each sit inside the 23.5 GiB OrbStack VM bound 11-2 measured.

## Second amendment, 2026-08-30 ~14:00 — merge conflicts are integrate's job

Owner: "if we launch a bunch of stories in parallel, the integrate skill
should be able to merge them all together" — correct, and now doctrine. The
2026-08-19 no-caveat rule is superseded in `dispatch.md`: parallel is the
default; proximity conflicts are unioned at integrate per the playbook with
both suites re-run; sequence only for same-statement disagreement risk,
contract dependency, or an operational gate. Footprints in build prompts keep
conflicts rare; `branch_conflicts.py` keeps them visible. Wave A launched as
six unattended lanes (11-2 remediation, 6-2, 10-1, 7-1, 11-3, 11-4) at ~14:00.
## 10-1 topic extraction — built, in review, 2026-08-30

Story 10.1 built on `story/10-1` (worktree `../meetingminer-wt/10-1`, cut from
`5cdfce7`). The third extraction document lands: `DOC_TOPICS` through the same
port, parser machinery, and one-retry discipline as the summary and action
items; migration 0014 adds worker-owned `topic`/`topic_mention` (one mention
per containing moment, composite FK, cascade — navigation metadata, not cited
evidence) and widens `extraction_source`'s kind CHECK; the prompt is committed
config served as `kind="topic"`; the prompts UI renders whatever the endpoint
returns; client regenerated from the in-process schema (2.2 pattern).

Four named footprint deviations, each mechanically forced, all recorded in the
spec's change log and verified pairwise clean with `branch_conflicts.py`
(notably `story/10-1 × story/11-2` is clean):

- `conftest.py` `EVIDENCE_TABLES` += topic, topic_mention (TRUNCATE's static
  FK refusal — without it every DB-backed test fails once 0014 applies).
- `test_worker_extract.py` — expectation counts only (+1 call for the
  always-generated topics pass, sources 2→3, adopted/generated split).
- `test_config.py` — one fixture line: the now-required `topics_prompt` key.
- `test_api_prompts.py` — 2→3 entries, kind set gains `topic`.

Build interrupted once mid-lane by an API rate limit; resumed from the
committed tree with no loss. Pre-existing and not mine: `main × story/11-2`
conflicts on 11-2's own spec file (remediation divergence; resolves at its
integrate).

## `11-3-eval-runs-own-their-namespace` — review, 2026-08-30

Built in worktree `11-3` on `story/11-3` (baseline `5cdfce7`, rebased onto
`211857c`). Check 2.11 no longer approves subject artifacts: subjects get one
read-only membership read, and the gate transition is measured on a run-owned
probe artifact — minted onto an eligible projected subject moment (extract
stage settled, no `extracted` rows on the moment, `Moment` node present),
approved through `POST /moments/{id}/approve`, asserted in both stores, and
erased with per-target verification (Postgres row, publish-root export,
Meilisearch document, Neo4j node). Concurrent runs resolve approve races by
re-reading their own row; `Run.create` refuses a lost `mkdir` race by name.
The delete-only store sanction is pinned in `test_harness_boundary.py`
(driver guard admits `checks/gate_probe.py` for the Meilisearch error family
only; textual pin forbids creation stems and raw query clauses). Four-layer
review triaged 17 patches (1 high: the pre-read race false-violation), all
applied; 0 bad_spec, 0 defers. Store-free proof only (`make evals-test` 616
green; no paid run) — the live concurrent measurement is written for the
owner in the spec's Verification section. Worktree note: this lane's `.env`
became a placeholder copy (the bootstrap symlink was lost and the permission
gate refused restoring it); `make test-fast` was verified green with
process-env storage roots — restore the symlink at integrate.

## Integrate pass, 2026-08-30 ~17:10 — 10-1, 6-2 and 11-3 landed

Three of the wave's stories are on `main`, in this order, each rebased onto the
previous one and re-gated before merging (not merged on the reviewer's numbers):

| story | landed at | gate re-run at integrate |
|---|---|---|
| 10-1 topic extraction | `54e1a11` | story suites `-m ""` 84 passed; `test-fast` 1461 |
| 6-2 YouTube acquisition | `bf7a993` | story suites 233 passed; `test-fast` 1571 |
| 11-3 eval namespace | `b670166` | `evals-test` 643; `test-fast` 1571 |

**Ops run:** `make migrate` applied `0014_topics.sql` (10-1's tables) — the only
operation owed by these three. No API-surface change, so no `make client`; no
projected field or index-shape change, so no `make rebuild`; `pyproject.toml`
untouched, so no venv sync. The worker was not started and the hold stands.

**Backlog ids reconciled.** Three lanes each filed "the next free number they
could see", which is only correct when one lane is filing: B-35 is 11-2's
per-worktree api/web ports, B-36 is the LAN GPU host binding, and 11-3's
projection-refusal item was renumbered to B-37 before landing. **Backlog ids
are a shared counter with no coordination — treat them like `sprint-status.yaml`
keys, not like free text.** That belongs in `conflict-playbook.md`.

**`sprint-notes.md` conflicted on every branch after the first**, exactly as the
2026-08-30 wave rules made inevitable by sending every lane to append here.
Resolution each time was a union keeping both entries; no entry was dropped.
The file has no merge driver, unlike `sprint-status.yaml`. Either give it one or
give each lane its own file — this is the wave's clearest process defect.

**7-1 is HELD OUT of `main`, and this is the integration's real finding.** Its
suites pass extra-free but two fail whenever the optional `diarize` extra is
installed — `test_stt_adapter.py::test_pyannote_is_documented_not_bundled` and
`test_worker_transcripts.py::test_a_pyannote_binding_fails_the_stage_with_the_documented_reason`,
both `AttributeError: 'Binding' object has no attribute 'token_env'` from stubs
that predate the adapter's new field. Extra-free, `build_diarizer` raises
`PYANNOTE_UNAVAILABLE` before reaching that line, so the stubs are never
exercised and the tests pass — which is why review never saw it. The root cause
is not the two stubs: `make diarize-extra-test` exists to gate the
extra-installed configuration and does not cover these modules, so the
configuration story 7.1 is *for* had no gate. Routed back with both fixes
required. **Note for the next lander: the main checkout's venv is extra-free
and must stay that way, or these two tests will fail there too.**

**Still out:** 6-3 (review running), 7-1 (above), 11-4 and 11-2 (deliberately
last — 11-4 puts lint/typecheck inside `test-fast` and would fail later
branches for unrelated tidiness; 11-2 switches every worktree to a private
stack and each existing worktree then owes `make worktree-provision`), 8-1
(built, review not yet dispatched; its AD-10 edit unions with 11-2's).
## 11-4-lint-and-type-tooling-in-the-fast-loop — 2026-08-30, build complete (review)

Pinned ruff 0.16.5 and mypy 2.3.1 in the server dev group with committed
configuration green on main untouched: ruff's default rule set held still by
the `<0.17` pin (plus `required-version`), a dated seven-code global ignore,
49 file-code pairs across 38 per-file entries; mypy over the 13 decision-core modules with
`check_untyped_defs` and one jsonschema override. `make lint` and
`make typecheck` join `test-fast` directly after `check-client`, pinned by
the extended `TEST_FAST_PREREQUISITES` and the new self-contained
`server/tests/test_lint_contract.py`. Build deltas from the spec, all in its
change log: the "51 remaining pairs" recounted to 49 (ruff's two summary
lines had been tallied as pairs), and UP017 joined the global ignore as a
seventh code — it fires only under the committed config, whose
target-version comes from `requires-python` (py312) rather than the isolated
baseline's default. Retirement plan filed in `deferred-work.md`.
Integration note: `branch_conflicts.py` is clean everywhere except the
excepted story/11-2-review pairs and story/7-1 x story/11-4 on
`server/uv.lock` — the spec's named merge surface; take either side and
re-run `uv sync --project server` after the merge.

## 11-4 landed, 2026-08-30 ~18:05 — the fast loop now lints and typechecks

`main` at `c3149f5`. `make lint` and `make typecheck` run inside `make
test-fast`, pinned by `test_lint_contract.py` and the compose contract.

**Measured cost, because the story sits inside a speed epic and the question is
fair:** `make lint` 0.11s, `make typecheck` 0.25s — 0.36s on a ~55s fast loop.
Not the wall-clock that matters; the friction does. From now on every branch
must be lint-clean to pass integration.

**It failed on first rebase, and that is the lesson.** 11.4 measured its ruff
baseline before 10-1, 6-2 and 11-3 landed, so three violations in newly-landed
code sat outside its dated ignore list. A baseline is a snapshot of a tree, and
it goes stale the moment anything lands beside it — expect this whenever a
lint-gate story is sequenced late in a wave. Resolved on `main` in `ec178b6`
rather than by widening the baseline:

- `test_extraction_topics.py` — two `ISC004` implicit concatenations inside a
  `parametrize` collection. Ruff cannot tell a deliberate multi-line markdown
  table from a forgotten comma, which is the whole point of the rule.
  Parenthesized; no behaviour change.
- `youtube.py:377` — `DTZ007` on a date-only `strptime`. A false positive:
  only the date is taken and it is reformatted with an explicit `T00:00:00Z`
  (the schema's `day` precision), so no naive instant is ever stored, and
  attaching a timezone would assert a wall-clock time YouTube does not give us.
  Annotated with that rationale instead of changing behaviour — a lint fix that
  silently changes a timestamp is worse than the lint finding.

**What is enforced:** seven mechanical codes are ignored tree-wide (import
ordering, deprecated typing aliases, `subprocess` without `check=`, UP017) with
a 49-pair per-file baseline that is shrink-only; every other rule is live in
every file. `mypy` covers the 13 decision-core modules — the database-free,
model-free logic where branch-heavy code hides type errors from tests. It fixes
nothing that existed; its value is preventing new problems, and B-4 is closed.

**Post-merge ops:** none owed — no migration, no API surface, no projected
field. `server/pyproject.toml` gained the dev-group pins, so `uv sync --project
server` was run in the main checkout; **every other clone and worktree owes the
same sync** before `make lint` will work there.
## 7-1 — Diarizer engine behind the port (2026-08-30)

Built to review by the wave builder. pyannote.audio rides the new optional
`diarize` extra (`uv sync --project server --extra diarize`); `noop` stays the
default and every unavailability is a named fail-closed `DiarizerError`. The
60-minute measurement is BLOCKED on a Hugging Face token: `HF_TOKEN` is absent
from `.env` (presence-only check), so no wall-clock or turn-quality numbers
exist anywhere — by instruction, none were fabricated. Review found one high
finding worth the owner's eye: the worker reads the token from its process
environment, and nothing loads `.env` into that environment today — wording
now says so everywhere, and the `.env`-to-`Secrets` threading is deferred
because `config.py`'s secrets region sits outside this story's footprint (and
inside 11-2's). Three more deferred items live in the spec frontmatter,
including `test_stt_adapter.py`'s pre-7.1 pyannote pin, which fails only in an
extra-installed venv. Integration heads-up: `story/7-1 × story/11-4` conflict
on `server/uv.lock` alone (both relock for their disjoint pyproject regions);
regenerate with `uv lock` when the second of the two lands.

## 7-1 landed, 2026-08-30 ~18:25 — and the gate that was missing now exists

`main` at `2b865d6`. The pyannote engine is bound behind the `Diarizer` port as
the optional `diarize` extra; `noop` remains the default, so nothing changes
for anyone who does not opt in.

**Why it was held out at first, recorded because the shape recurs.** Its suites
passed for everyone who ran them, and failed the moment I rebased it during
integrate — because the worktree I tested in had the `diarize` extra installed
and every earlier run did not. Two tests used stub `Binding` objects predating
the adapter's `token_env` field; extra-free, `build_diarizer` raises
`PYANNOTE_UNAVAILABLE` before reaching that line, so the stubs were never
exercised. **A configuration with no gate is a configuration nobody tests.**
The root cause was not the two stubs: `make diarize-extra-test` existed
precisely to cover the extra-installed path and did not include those modules.
Both are fixed — the stubs, and the gate widened with its module list pinned so
a future module cannot silently escape it.

**Verified in the configuration that was broken**, not just the default one:
with the extra installed, the two previously-failing modules give 61 passed,
`make diarize-extra-test` 90 passed, `make test-fast` 1617 passed, `make lint`
and `make typecheck` clean.

**Keep the main checkout's venv extra-free.** `make lint`, `make typecheck` and
`make test-fast` are all green there and `pyannote.audio` is absent; installing
the extra in the main checkout would put it back in the configuration these
tests now cover but the default gate does not run.

**Telemetry is disabled in code, by owner ruling.** The locked pyannote 4.0.7
wheel ships an OpenTelemetry exporter that defaults ON to an external endpoint;
the adapter disables it before `Pipeline.from_pretrained`, and a regression
fails if that call is removed. A verification round proved the egress is
actually closed, not merely documented.

**The 60-minute measurement its AC asks for is still owed, and deliberately.**
`HF_TOKEN` is now in `.env` and resolves, but the account has not accepted the
gated model's licence conditions at
`https://huggingface.co/pyannote/speaker-diarization-community-1` (self-service,
`gated=auto`, immediate). Beyond that, the owner ruled the current corpus — two
recordings, longest ~7 minutes — is not a basis for judging turn quality; the
real measurement waits for the new corpus. See B-36 for the LAN GPU
alternative, which needs no token at all.

## 11-2 landed, 2026-08-30 ~19:00 — Epic 11 is complete

`main` at `c045d76`. Every worktree now provisions its own compose stack
(`meetingminer-<slug>`, ports in a generated `.env.worktree`), so suites,
rebuilds and workers in different checkouts never contend. `make
worktree-remove` tears the stack down; `make test-db-prune` sweeps orphans.
Epic 11 (11-1 → 11-4) is done.

**Owner ruling implemented (option b, 2026-08-30):** `MM_STACK_NAME` and
`MM_STACK_ID` are the ownership record and are NOT overridable from the process
environment; the port and endpoint values still are, because those are location
rather than identity. Paired with the assertion that the effective project and
id equal the file's immediately before Compose runs. This closed a demonstrated
foot-gun: `MM_STACK_NAME=meetingminer-victim make infra-up` previously proved
ownership of `probe` and then started `victim` — the main stack included —
with no ownership check on what it actually started.

**Every existing worktree owes `make worktree-provision` once**, and clones owe
`uv sync --project server` (11-4's dev pins). A worktree without
`.env.worktree` is refused by name rather than silently using the main stack.

**Two integrate conflicts here were supersessions, not proximity, and the
distinction matters.** `AGENTS.md` and `dispatch.md` both had 11-2 rewriting
the store rules while `main` carried 11-3's newer eval-measurement wording.
Neither side was wholly right: 11-2's stack description supersedes the
shared-store text, but its eval paragraph predates 11-3's failed live
measurement. Resolved by taking each side's true half, not by unioning — a
blind union would have shipped a document claiming both that evals are
single-flight for the old reason and for the new one. **When two branches
rewrite the same statement, read both and merge by meaning; union is for
additions.**

**Lint findings fixed here, not baselined.** 11-4's gate landed while this
branch was open, so seven findings surfaced in this story's own new test
module: three function-local re-imports shadowing a module-level one (F811 +
F401 — the local imports were redundant, the function is not a fixture), two
ISC004 implicit concatenations, and one FLY002 that would have made a
four-row fixture less readable, so it carries a `noqa` with that rationale.
183 story tests and `test-fast` at 1832 passed afterwards.

**Post-merge ops:** `projections/locks.py` changed but the lock is a filesystem
key, not a projected field — no `rebuild`, no `migrate`, no `client` owed.

## Status regression at integrate, 2026-08-30 ~19:10 — the merge driver does not cover rebases

`7-1` and `11-2` were both flipped to `done` on `main` as they landed, and both
came back reading `review` a few merges later. `epic-11` likewise stayed
`in-progress` with all four of its stories done. Restored here.

**Cause, and it is structural rather than a slip.** `sprint-status.yaml` has a
key-wise merge driver (`_bmad/scripts/merge_sprint_status.py`) that takes the
furthest-along status on a two-sided change. It runs on **merge**. The
integrate loop rebases each branch onto `main` and then fast-forwards — a
fast-forward performs no merge at all, so the driver never runs, and the
branch's own copy of the file (written before the flip existed) replaces
main's. The protection everyone relies on is bypassed by the very workflow
`SKILL.md` prescribes.

**How to apply:** after landing a branch, re-read `sprint-status.yaml` and set
the story's line again; do not assume the flip you made before the rebase
survived. Better, and cheap: make the status flip the *last* commit on `main`
after the merge, never before it. Both were done here in the wrong order —
the flip preceded later merges — which is why it regressed twice.

This is the third shared-file lesson from this wave, alongside `sprint-notes.md`
having no driver at all and backlog ids being an uncoordinated counter. All
three belong in `conflict-playbook.md`.

## Story 6.3 — local files with transcript dialect conversion — 2026-08-30

`mint-drop --transcript-dialect {plain,teams-vtt,zoom}`. A Zoom `.vtt` whose
cue payloads read `Name: text` is converted **at acquisition** into a
legacy-lineage `transcript.txt` plus a speaker-less `transcript.vtt`;
`pipeline/transcripts.py` and `pipeline/stages/align.py` are unchanged, so a
Zoom name resolves through the roster by the same path a Teams label takes.
The converter re-reads its own output with the pipeline's parser and refuses
rather than minting a write-once drop `align` would fail on, and a cue prefix
becomes a speaker only if it reads like a name — otherwise `Unknown`, never
the previous speaker.

The wave's pinned coupling worked: `mintdrop.py`'s override hunk was taken
verbatim from 6-2's `7625b79`, so `6-3 × 6-2` is **clean**. `6-2-review`
hardened `provenance_extra` afterwards; that one mechanical conflict resolves
by taking 6-2-review's block whole, executed and tested (103 green).

Detail, mutation matrix and gate output: `spec-6-3-local-files-acquisition-with-transcript-dialect-conversion.md`.

## 6-3 landed, 2026-08-30 ~19:40 — Zoom transcripts convert at acquisition

`main` at `d29ed0f`. A Zoom `.vtt` (`Name: text` cues) becomes a trusted
speaker-attributed `transcript.txt` plus a speaker-less `transcript.vtt` at
mint time; `teams-vtt` is a pass-through declaration and `plain` is unchanged.
A dialect is never inferred from content. `pipeline/transcripts.py` and the
aligner are untouched, as the AC requires — Zoom names resolve through the
roster exactly as Teams labels do.

**Two findings deferred by owner decision, not fixed** (2026-08-30), both with
their reproductions preserved verbatim in `deferred-work.md` so nobody
re-derives them:

- **F1** — a transcript-only Zoom drop takes its identity from the generated
  speaker-less VTT, so two exports differing only in speaker labels collide:
  re-minting a corrected export reports `exists` and keeps the old attribution.
  Trigger for revisiting is exactly that. Both candidate fixes are recorded
  (identity from the operator's original file, or a digest over both converted
  artifacts).
- **F6** — whole-second `MM:SS` truncation gives two speaker changes inside one
  second the same start, collapsing the first turn to zero duration. Real
  mechanism, unmeasured frequency; revisit when the new corpus shows sub-second
  speaker changes.

Owner's reasoning for both, given twice: do not design against issues we have
not encountered. Recorded here because a future reader will otherwise read the
open reproductions as neglect.

**The rehearsed union worked.** 6-3's builder took story 6.2's
`mint()`/`build_metadata()` override hunk **verbatim** from `7625b79` rather
than re-typing it, so both branches carried one identical change. The only real
conflict at integrate was 6-2-review's later `provenance_extra` hardening,
which the builder had already executed and tested as a resolution rather than
asserting — taking main's validated version whole was exactly right, and 224
story tests passed after it. **This is the pattern to copy when two lanes must
extend one signature.**

**Its worktree predated 11.2** and `make test-fast` refused by name rather than
running against the main checkout's stack — the guard working as designed.
`make worktree-provision` wrote `.env.worktree`, started
`meetingminer-6-3-review`, and the gate then passed: 1,880 tests, 2 named skips.
## Story 6.2a — Playlist Acquisition (2026-08-30)

`youtube-drop --playlist` enumerates a playlist with one
`yt-dlp -J --flat-playlist` call, then mints and posts every entry
**sequentially through story 6.2's own code**: `acquire()` unchanged, plus a new
`_deliver()` holding what was `main()`'s post-acquire tail, so an entry and a
single video print the same thing. Without the flag, 6.2's path is unchanged —
its 110 tests are untouched and green.

Two calls for the reviewer to attack. **`--playlist` is a flag, not an option
carrying the URL** (`make youtube-drop URL=<playlist url> PLAYLIST=1`):
`test_youtube.py` is read-only here and pins the recipe to a `URL is required`
guard and to the contiguous `"$${MM_YOUTUBE_URL}" $(YT_ARGS)`, so the flag is
appended after it via `$(if $(PLAYLIST),--playlist)` — Make tests emptiness, so
any non-empty value enables it, documented rather than left as a trap. And
**`refused:<rule>` needed a stable token**, so `YoutubeError` gained an optional
`rule=` set at all 27 raise sites: additive, every message byte-identical,
vocabulary closed in `REFUSAL_RULES` and pinned by a test reading the module's
own source. Classifying a refusal by matching its prose would have mislabelled
a row the day someone reworded a message.

A refused entry never stops the run — asserted from three directions (a refusal
from `acquire`, a listing row that is not a video, an intake failure after a
successful mint). Exit is 0 only when every entry ended `minted` or `exists`
and every POST succeeded; the table prints either way.

No live playlist run: the suite is offline by construction and a real
multi-video acquisition is minutes of downloads. Gates in this worktree's own
stack — `make test-fast` 1877 passed, `make test` 2255 passed / 2 skipped with
the web build, lint and typecheck clean.

## Story 6.2a review — 2026-08-30

Review branch `story/6-2a-review` rebased the story onto `f92cb9c` and fixed all
three findings: the pre-enumeration gate now requires only `yt-dlp`, so an
already-minted playlist entry keeps Story 6.2's media-tool-free `exists` path;
the refusal vocabulary is enforced both at construction and over every raise
site by AST; and `ConfigError` continuation has a loop-level regression test.
No owner decision or deferred item remains. Focused tests: 157 passed / 1 named
network skip; `make test-fast`: 1927 passed / 2 named skips; `make test`: 2305
server tests passed / 2 named skips plus the web build. Review report:
`review-story-6-2a-2026-08-30.md`.

## 6-2a landed, 2026-08-30 ~20:10 — playlist acquisition; epic 6's acquisition half is done

`main` at `b4a71fc`. `make youtube-drop URL=<playlist> PLAYLIST=1` enumerates
with one `yt-dlp --flat-playlist` call, then mints and posts each entry through
story 6.2's own unchanged `acquire()` — one drop and one `POST /ingests` per
entry, `exists` short-circuiting per entry before any probe or download. A
refused entry is recorded `refused:<rule>` and the run continues; the summary
table names every entry's outcome and the run exits non-zero if anything failed.

Review found three (1 medium, 2 low), all fixed red-first: the media-tool-free
`exists` path was not preserved for playlist entries, the refusal-rule
vocabulary was not actually closed (now enforced by runtime *and* AST checks),
and per-entry `ConfigError` continuation had no regression. Gate at landing:
`make test` 2,305, `test-fast` 1,927, lint and typecheck clean.

**`YoutubeError` gained an optional `rule=` at 27 raise sites.** Additive, every
message byte-identical, and the vocabulary is now pinned two ways so a new
raise site cannot invent a rule token silently. Worth knowing before touching
that module.

**Still never exercised against a live playlist.** The suite is offline by
construction and a real multi-video run is minutes of downloads. Recorded as a
residual risk rather than quietly assumed away — the first real playlist run is
the test that matters, and it has not happened.
## Story 7.2 — Speaker Tags on the Wire, 2026-08-30

`GET /meetings/{id}/speakers` is one read-only aggregation over the transcript
segments story 7.1 already tags. No migration, no change to the tag-producing
side: every column it reads existed before the branch.

Two things a later lane should know.

**One shape, two sources, is a test rather than a claim.** The diarized meeting
and the name-carrying meeting are seeded from one timing table, so the
"identical talk time and sample offsets" clause is asserted by comparing two
live payloads, not by reading the two code paths and agreeing they look alike.

**`projection_seed.seed_meeting` cannot express this story.** Its turns
hard-code `end_ms = start_ms + 2000`, so every segment has the same duration
and neither talk time nor longest-segment sampling is observable through it.
The story seeds its own segments on top of `seed_meeting(turns=())`, which
still supplies the job, stage rows, meeting and `transcript_source` the gate
and the foreign keys need. A future story that needs varying durations should
do the same rather than widening the shared helper mid-wave.

**Footprint departure, recorded not widened:** `server/tests/test_api_registry.py`
pins `BASELINE_ROUTER_ORDER` with `==`, so any new router module must be added
to that list — demonstrated by reverting the line and watching
`test_existing_routers_keep_the_baseline_registration_order` fail. No other
in-flight branch touches that file.

## Story 7.2 review — 2026-08-30

Review branch `story/7-2-review` rebased onto current `origin/main` and found one
medium wire-contract defect: runtime responses always carried nullable
`participantId` and `displayName`, but their Pydantic defaults made OpenAPI and
the generated TypeScript client advertise both properties as optional. A new
schema assertion failed against the original model; removing the defaults and
regenerating the client made the fields required-but-nullable and the test
green. No owner decision, deferred item, or open finding remains.

The coordinator's claims were independently checked: registry-baseline removal
failed its order test; the client reproduced from an in-process schema with no
api running; the two source shapes really share one timing table; one/exactly
three/tied/single-speaker sampling boundaries pass; and a raw-label display-name
fallback makes all three identity-safety tests fail. Final gates on the rebased
review branch: `make test-fast` 1,944 passed / 2 named skips / 378 deselected;
`make test` 2,322 server tests passed / 2 named skips plus puller, evals,
diarization-extra, web tests, and production build. Report:
`review-story-7-2-2026-08-30.md`.

## 7-2 landed, 2026-08-30 ~20:40 — speaker tags reach the wire

`main` at `d825769`. `GET /meetings/{meetingId}/speakers` is one read-only
aggregation over the transcript segments story 7.1 already tags: one row per
voice with `speakerLabel`, `speakerResolution`, nullable
`participantId`/`displayName`, `talkTimeMs`, `segmentCount`, and
`sampleOffsetsMs` — the `startMs` of the tag's three longest segments, never
padded. No migration; every column already existed. Registration is the file
itself, so `api/main.py` was untouched (story 2.8's discovery still holds).

**The generated TS client is regenerated and committed on this branch** —
`index.ts`, `sdk.gen.ts`, `types.gen.ts` — reproducibly from an in-process
`app.openapi()` dump with no api started. So `make client` is NOT owed at
integration; the committed client already matches the api.

**Review found one and fixed it red-first:** `participantId` and `displayName`
were optional in the OpenAPI schema and the generated client, rather than
required-but-nullable. A consumer could not tell "no participant resolved"
from "the field was omitted" — which for this route is the whole point, since
an unresolved tag is a first-class answer.

**The one-shape criterion was proved by construction, not asserted.** The
diarized meeting and the name-carrying meeting are seeded from a single timing
table, so "identical talk time and sample offsets" is checked by comparing two
live payloads rather than two hand-written expectations. Story 6.3 landing
mid-build made the Zoom half real: a converted Zoom name reaches
`transcript_segment` by the same path a Teams label takes, and this route reads
the columns without caring about lineage.

**AD-13 held under attack.** Reverting `displayName`'s fallback so it returns
the raw `SPEAKER_NN` label turns three tests red, including the one-shape
criterion — a tag resolves to a person only when the source or an alias says
so, never by guessing.

**Unblocks 7-3** (speaker assignment), which writes `PUT
/meetings/{id}/speakers/{tag}` into this same route file and was held for
exactly that reason.
## 8-1 — AD-10 amendment and binding catalog, 2026-08-30

`llm.roles.<role>` now declares a `catalog[]` of authored `binding` / `label`
plus a derived `provider`, and a `default`, validated when `config.yaml` loads. Two named
refusals, both raised from `Settings` validation — the layer `load_config`
already wraps into `ConfigError`: a `default` outside its own catalog, and a
catalog binding whose derived provider `providers:` does not declare. After the
owner's Finding 4 ruling, `provider_for_model` is the single dependency-neutral
spelling rule consumed by config, `resolve_api_base`, and `/status`; an authored
`provider` key is forbidden, known bare OpenAI and Anthropic spellings derive
their runtime provider, and ambiguous bare spellings refuse by name. A
*synthesized* prefixed entry remains marked internally and exempt from the
declared-provider cross-check because it projects a file written before that
rule existed. A role that declares only a routable `model` therefore still
loads as a one-entry catalog with `default` equal to `model`.

Declaration only: `model` remains what `build_llm`, `resolve_api_base` and
`_role_view` read. Runtime routing behavior is unchanged, no selection is persisted, no route
or picker exists — 8.2 / 8.2a / 8.3.

**Owner ruling addendum, 2026-08-30.** A provider that does not serve the
requested model must eventually raise
`provider {provider!r} at {api_base!r} does not serve model {model!r}` and must
not engage fallback; genuine `LlmUnavailableError` outages keep fallback. The
current adapter instead drops endpoint identity into generic `LlmError`, which
`FallbackLlm` catches. Because Story 8.1's frozen boundary changes no call path
and marks the adapter read-only, that verified call-time defect is filed as
B-38 rather than widened into this config-contract story.

The owner-remediation fast gate found two bake-off tests whose fake `x` and
`flaky-model` bindings became correctly ambiguous under the new loader rule.
Those fixtures now use an explicit `test/` prefix (including the stable peer),
the eval suite passes 643, and the restarted fast gate passes. A local review
also normalized outer whitespace on the active `model` and pinned status as the
third consumer of the shared provider rule.

**Review closeout.** The branch was rebased through final integration base
`9ac3264298d65619be91493d2db5df876dad5571`. The foreground gate passed:
lint clean, mypy clean in 13 source files, fast server 1,962 passed / 2
intentional skips / 378 deselected, full server 2,340 passed / the same 2
skips, diarization 92, reachability 1, puller 128, web 294, evals 643, and the
production web build. All in-scope review findings are closed; B-38 remains
the filed call-time follow-up outside Story 8.1's frozen boundary.

The committed `config.yaml` gains a two-entry catalog per role (extraction:
the two local Ollama bindings it already names; chat and judge: `openai/gpt-5.2`
beside the free local `ollama/gpt-oss:120b`), with each `default` equal to the
`model` that role already used, so which model runs is unchanged.

Coverage is a new module, `server/tests/test_config_catalog.py` — 18 collected cases
covering the spec's I/O matrix, the committed file, and review regressions;
each behavior-changing test was observed failing against the unfixed loader
first. `test_config.py` was not touched (11-2 appends there).

**Gap closed by the follow-up review after Story 10.1 landed.** At build time,
the stale invalidated-Anthropic-key and superseded-`claude-sonnet-5` claims were
live at the lines Story 10.1 was editing, so the wave rules required narrowing.
With that lane landed, the review deleted those two claims and kept the live
OpenAI choice, no-fallback rule, and `openai/` prefix rationale.

**Addendum, 8-1.** `make test` earned its keep. The first implementation derived
a provider for the one-entry catalog synthesized from a role's `model` and then
checked it against `providers:`, which made every pre-catalog file whose tag
prefix names an undeclared provider refuse to load. `make test-fast` was green:
the test that catches it, `test_failfast.py`'s embedder gate, is in a `slow`
module and is deselected there. A synthesized entry now retains any provider
derivable from its prefix but carries an internal marker that skips the new
provider refusal; authored entries keep the strict rule.

Two cross-lane facts follow from that. First, `server/tests/test_failfast.py` is
edited outside 8-1's footprint — its fixture removes `providers.ollama` and
needs the roles' authored catalogs removed with it — and no in-flight lane
touches that file, measured against all seven `story/*` branches. Second, any
lane that adds a role tag or removes a provider from `config.yaml` now touches a
unit surface: `test_config_catalog.py` loads the committed file and asserts every
catalog entry's provider is declared.

## 8-1 landed, 2026-08-30 ~21:00 — one rule decides which provider serves a model

`main` at `c4c54da`. `config.yaml` declares a per-role `catalog[]` and
`default`; the loader fails closed when a default is outside its catalog or a
binding names an undeclared provider, and a pre-catalog single-`model` file
still loads as a one-entry catalog.

**Owner ruling A, 2026-08-30 — the shape of the fix, not just the fix.** Review
found that an authored entry could declare `provider: ollama` beside
`model: gpt-4o` while the runtime routed to OpenAI: the catalog promised one
endpoint and the call reached another. The owner rejected the framing of
"which rule wins" and gave a plainer instruction — *show what is actually
happening*. So the declared provider is gone as a source of truth. A new
`server/meetingminer/domain/model_providers.py` holds the single spelling rule,
and `api/status.py`'s `provider_of` is now an **alias** to it rather than a
wrapper — deliberately, so config, call-time endpoint resolution and the
display surface execute the same function object and cannot drift. An
ambiguous bare spelling is refused at load by name rather than guessed.

The acceptance test is the owner's own sentence: the picker showing
`ollama/gpt-oss:120b` means local and free, `openai/gpt-5.2` means remote and
paid, with nothing in between that can be wrong.

**Owner ruling B was filed rather than built, and that was the right call.**
Making a model-not-found failure loud — naming the provider, the endpoint and
the model, and never engaging the fallback — changes call-time adapter and
fallback semantics, which is outside this story's frozen boundary. It is
**B-38**, with the evidence and the exact required message, so the next lane
inherits a specification rather than a memory.

**No post-merge ops owed.** `api/status.py` changed but only swapped a private
helper for the shared one — no route decorator, no response model, so the
OpenAPI schema is unchanged and the committed TS client stays valid. Verified
by diffing the api surface rather than assuming.

## B-36 (diarizer half) built, in review — 2026-08-30

Branch `story/b36-remote-diarizer`, worktree `../meetingminer-wt/b36-remote-diarizer`.
The `Diarizer` port now has an engine that can actually run here. `remote-http`
(`adapters/diarize/remote_http.py`) POSTs the audio to the LAN GPU host's
`/diarize` over `urllib` — the convention `adapters/embed/ollama.py` set, no new
dependency — and turns the endpoint's float seconds into the port's integer
milliseconds. The name is transport-descriptive on purpose: it claims nothing
about the model, and it leaves the same name free for B-36's `Stt` half, which
stays open.

**The engine is bound but not chosen.** `diarizer.engine` is still `noop` in the
committed `config.yaml`; `base_url` and `timeout_seconds` are new keys beside the
existing pyannote ones. Whether the LAN engine or in-process `pyannote` becomes
the recommendation is the owner's call, pending the capacity measurement.

**Not in `ENGINES`.** That registry maps a name to a *zero-argument* class and
constructs it `engine()`; this engine needs the endpoint and the timeout off the
binding, so it is special-cased in `build_diarizer` the way story 7.1's
`pyannote` already is. Both are now enumerated in a new `ENGINE_CHOICES`, so the
unknown-engine diagnostic still lists every value config.yaml accepts, and a test
asserts that set is exactly the three engines.

**Every failure is named; none is survivable.** Unreachable host, timeout, 503
with the GPU held elsewhere, 400 from ffmpeg, a non-JSON body, a malformed turn,
a turn whose end precedes its start, more than 1000 distinct speakers — each
raises `DiarizerError` carrying the endpoint, the model the host named, and the
host's own `reason` verbatim. No engine is ever substituted: an empty turn list
from a healthy host is legitimate success, which makes it indistinguishable
after the fact from a silent fallback. An empty list is the one no-signal answer
this engine returns.

**Two contract details worth knowing.** Each boundary rounds independently
(`round(x * 1000)`, never `start + round(duration)`), so a boundary two turns
share lands on the same millisecond in both — the same rounding `pyannote.py`
applies, and it matters because `transcribe` assigns each segment the tag with
the longest overlap. And labels are canonicalized to `SPEAKER_NN` by first
appearance *after* sorting by start, capped at 1000: `speakers.py`'s placeholder
pattern matches `speaker` plus at most three trailing characters, so a
`SPEAKER_1000` would stop being a placeholder and could resolve to a participant.

**Coverage is offline by construction** — 36 tests against a scripted
`BaseHTTPRequestHandler` on `127.0.0.1:0`, so the multipart encoding, the
`Content-Length`, the status codes and the socket failures are all real while the
LAN host stays untouched. The one live test is env-flagged
(`MM_DIARIZE_REMOTE_NETWORK_TEST=1`) and skipped by default, the shape story
6.2's network test has. Every test was observed red before its code existed, and
eight mutations of the finished engine — round-down instead of round, label in
host order, drop the reversed turn, keep the collapsed turn, an off-by-one cap, a
missing `Content-Length`, an empty-turns fallback on an unreachable host, and
swallowing the host's reason — were each caught by the test that claims them.

**Two contract tests reacted to the new module and were satisfied inside it.**
`test_compose_contract.py` discovers pyannote-sensitive test modules by searching
for the literal string, so the test file names the engine through
`PYANNOTE_ENGINE` instead; and it pins an exact set of `slow`-marked tests, so
the live test carries only its `skipif`, as story 6.2's does. Neither contract
file was edited.

**Never exercised against the live host from this branch.** The suite is offline
by design and the LAN box is operator-scheduled; the flagged test exists and has
not been run here. The endpoint's own behaviour is what the backlog entry
records from 2026-08-30, and turn *quality* remains unvalidated against ground
truth — 2 speakers on a scripted two-person demo is plausible, not measured.

## B-36 diarizer half landed, 2026-08-30 ~21:40 — the port finally has a real engine

`main` at `2dec459`. A `remote-http` engine sits behind the unchanged
`Diarizer` port and calls the LAN service's `/diarize` over the standard
library — no new dependency, following `adapters/embed/ollama.py`'s precedent.
Float seconds convert to integer milliseconds **per boundary**
(`round(x*1000)` on start and end independently, never
`start + round(duration)`), turns are validated, sorted, then relabelled into
the recording-local `SPEAKER_NN` namespace.

**`noop` is still the committed default, deliberately.** The engine choice is
the owner's; `config.yaml` now offers `noop | pyannote | remote-http`.

**Nothing falls back, and that is tested rather than asserted.** Every failure
raises a named `DiarizerError` carrying the endpoint, the model when the host
reported one, and the host's `reason` verbatim. The builder's own mutation
matrix included "silently return no turns when the host is unreachable" and it
was caught. An empty `turns` list from a *healthy* host is success; an empty
list produced by a *failure* is the defect, and the two are distinguishable.

**Review found four, all the same shape — a failure escaping as something
other than a named `DiarizerError`:** invalid or non-finite timestamps getting
through, a truncated HTTP response surfacing as `IncompleteRead`, the timeout
behaving as an inactivity timeout rather than a total request deadline, and
multipart size taken from stale path metadata. All fixed red-first. The
timeout one matters most operationally: an inactivity timeout against a host
that dribbles bytes never returns, which is exactly the hang the finite-timeout
requirement existed to prevent.

**One deliberate deviation, recorded and reviewed:** the engine is not in
`ENGINES`, because that registry constructs engines with no arguments and this
one needs an endpoint and a timeout off the binding. It follows story 7.1's
`pyannote` special-case, with `ENGINE_CHOICES` keeping the unknown-engine
diagnostic exhaustive.

**The suite never contacts the host** — `make test` is green with VM120
untouched, and the live test is env-flagged behind
`MM_DIARIZE_REMOTE_NETWORK_TEST`.

**B-36's `Stt` half stays open.** Those engines already work locally, so it is
an optimisation rather than an unblock.

**Measured context for the engine choice** (see
`diarization-provisional-measurement-2026-08-30.md`): 60 minutes of audio takes
57.5s on the LAN GPU versus 35m51s in-process on this Mac, CPU-only with MPS
unused — 37.4x apart. The Mac is a viable fallback for unattended work but the
substitution must be explicitly configured, never automatic.
**Backlog id collision, third of the wave — resolved by the 10.2 owner
correction.** Story 10.2 had named two ids without filing them; 8-1 filed its
model-routing item first. Story 10.2's production-derivation and color-ordinal
items are now actually filed as **B-39** and **B-40**. Naming an id in a spec
does not reserve it; filing it does.

## Story 10.2 — Threads and the Graph Projection (2026-08-30)

Landed to `review` on `story/10-2`. Migration 0015 (`thread`, `topic_thread`),
`domain/threads.py`, `Topic`/`Thread` nodes with `MENTIONS`/`INCLUDES` edges,
and the `thread-timeline` traversal template. Full gate green: 2287 passed,
2 skipped. Its two deferred items are now filed as **B-39** and **B-40**;
Story 8.1 owns B-38.

**A footprint table can be under-specified without being wrong.** The build
prompt named `graph.py` for the graph write but no way for the graph to *learn*
about topics: `graph.project_meeting` takes a driver and a `MeetingEvidence`,
never a connection. Four files outside the table were required and are recorded
in the spec's change log — `projections/evidence.py`, `projections/stores.py`,
`tests/conftest.py` (without which `TRUNCATE` is refused and *every* DB-backed
test in the suite fails), and `api/chat_router.py`. Each was checked against
every in-flight branch first; `main × story/10-2` is clean. Worth adding to the
dispatch checklist: when a footprint names a writer, check it also names the
writer's input surface.

**A registry with a completeness tripwire needs a way to say "deliberately not
yet".** Registering a third traversal broke the chat router's rule that
`TEMPLATE_ANCHORS` covers the whole registry — correctly, since that rule exists
so a template cannot be registered and never dispatched. But wiring it would
have been a live `AttributeError` (the orchestrator reads `result.rows`, which
`ThreadTimelineResult` does not have), and adapting it is story 10.2b's job.
Resolved with a declared `DEFERRED_TEMPLATES` map naming the template and the
story that frees it, so an omission and a decision stay distinguishable.

**Two mutants were equivalent, and are reported as such rather than counted.**
`test_the_partition_does_not_depend_on_the_order_topics_arrive_in` cannot fail
against the current implementation, because the partition is order-independent
through both the union-find and an explicit `min`. Named in the review prompt
so the reviewer decides whether that is protection or decoration.

## Story 10.2 owner remediation — durable thread identity (2026-08-30)

The owner accepted review findings F1 and F5 and required them fixed before
10.2a attaches human curation to `thread.id`. Diagnosis: two mutable facts were
being used as identity — which topic happened to be chronologically first and
whether the thread currently had members. Identity keys now come from normalized
cluster content, an existing member's row is reused across earlier backfills,
and empty thread rows survive Story 10.1's replace-all interval so the same
content reclaims the same UUID. Both regressions were observed red against the
rebased pre-fix implementation; the existing unchanged-rerun test could not
expose either because it never deleted and reinserted topic rows.

The two unfiled deferrals were corrected at the same time: production invocation
is **B-39** and per-corpus color ordinals are **B-40**, both now present with
evidence and completion contracts in `docs/backlog.md`.

Final review on current `origin/main` (`e5e0ff9`) found and fixed one more
high-severity edge case: two products of a split could both reuse the same old
thread row. Existing content-key rows are now reserved and every retained row
can be claimed once per derivation. Final gates: focused threads 63 passed;
`test-fast` server 2071 passed / 3 named skips / 405 deselected; full server
2476 passed / 3 named skips plus puller, web, eval harness, diarization,
store reachability, and the production build. Review verdict: **Pass**.

## 10-2 landed, 2026-08-30 ~22:30 — threads, and a durable identity for them

`main` at `063e331`; migration `0015_threads.sql` applied. Topics link into
threads by normalized name and embedding similarity above a configured
threshold; `projections` writes `Topic` and `Thread` nodes with `MENTIONS`
edges and stays the sole store writer (AD-4); the thread traversal is
registered like the existing templates.

**Owner ruling, 2026-08-30 — fix identity in this story rather than in 10.2a.**
Review found thread ids were not durable, and reproduced it against a real
database: story 10.1 replaces every `topic` row for a meeting on rerun, so a
thread whose only member was an *unchanged* topic lost its last link, a trigger
deleted it, and derivation reminted it with a new UUID. Changing an unrelated
topic in the same meeting silently changed another thread's id. A second path
did the same when a backfilled earlier meeting became the cluster's
chronological seed.

The diagnosis in one sentence, and the reason the fix is small: **two mutable
facts were being used as identity** — which topic happens to be chronologically
first, and whether the thread currently has any members. Neither is stable.
Identity is now derived from the cluster's content, and a thread survives
temporarily having no members so its id is reclaimed rather than reminted. The
owner's reasoning for fixing it here: 10.2a is thread curation, it is the next
story, and it attaches human work to these ids — building curation on an
identity already known to be unstable means building it twice.

A third defect surfaced while fixing those: split clusters were collapsing onto
one retained row instead of receiving thread rows one-to-one. Also fixed.

**`make rebuild` is owed but deliberately not run.** `projections/graph.py`,
`evidence.py`, `stores.py` and `traversals.py` all changed, so meetings
projected before this landing carry no `Topic`/`Thread` nodes. The corpus is
about to be replaced wholesale anyway — a large YouTube ingest is downloading
now — so the rebuild belongs after that ingest, not before it. Whoever runs the
ingest should treat `make rebuild` as part of it.

**Backlog ids, filed properly this time.** B-39 (nothing calls `derive_threads`
in production yet — the worker settle point is 10.1's file) and B-40
(`thread.color_ordinal` scoping, a 10.3/10.6 decision) are in
`docs/backlog.md`, not merely named in a spec. Highest in use is now B-40.
## Story 8.2 — Persisted Selection (2026-08-30)

**The selector is real.** `app_setting` (migration 0016, api-owned) holds one row
per role; `GET /settings/models` serves each role's catalog beside the binding in
force, `PUT /settings/roles/{role}` persists a choice bounded by that catalog.
Chat resolves it inside the request that uses it, the extract stage inside the
job's own transaction — no restart for either to take effect.

**One rule.** `domain/model_selection.py` decides catalog membership on write and
again on read, deriving provider identity from 8.1's `provider_for_model`. Api,
worker and eval snapshot all go through it. A stored pick the catalog no longer
offers is never applied: the role falls back to the file's `default` and the
discard is named in the payload (`staleSelection`) and a `llm.selection_stale`
event.

**B-38 closed (`ca9689a`).** `litellm.exceptions.NotFoundError` maps to
`LlmModelNotServedError` naming provider, endpoint, model and upstream status;
`FallbackLlm` re-raises it ahead of the clause that substitutes; chat surfaces
`urn:meetingminer:problem:binding-failed` (502 — the call answers identically
forever, so 503's "try later" would be a lie). Genuine outages keep today's
fallback, pinned by a test beside the new one.

**Importing `litellm` calls `load_dotenv()`**, injecting the real `.env` into
`os.environ` for the whole session — enough to make `test_config.py`'s
env-precedence tests read the developer's real `POSTGRES_PASSWORD`. Contained in
a module-scoped fixture here; filed as deferred, because nothing stops the next
module that imports the SDK from reintroducing it.

**Three edits outside the footprint**, each with its reason in the spec's change
log: `test_api_registry.py`'s `BASELINE_ROUTER_ORDER`, `test_extraction_core.py`'s
`litellm` stub (which needed `NotFoundError` or the adapter's new `except` raised
`AttributeError`), and `test_harness_boundary.py`'s httpx allowlist — which grew
the same way for stories 5.3 and 5.4. No coverage appended to a shared module.

## 8-2 landed, 2026-08-30 ~23:15 — the model choice is real, and it cannot lie

`main` at `420325c`; migration `0016_app_setting.sql` applied. An api-owned
`app_setting` table holds the selection; `PUT /settings/roles/{role}` persists
it and `GET /settings/models` serves the catalog with the active choice; chat
reads the selection per request and the worker per job; the eval snapshot
records the effective binding beside the file value.

**Backlog B-38 closed here** (`ca9689a`). A provider that does not serve the
configured model now raises a distinct `LlmModelNotServedError` naming the
provider — taken from story 8.1's single `provider_for_model` rule rather than
the SDK's own guess — plus the endpoint and the model, and `FallbackLlm`
re-raises it **ahead** of the clause that substitutes. A test pins that a
model-not-found never reaches the fallback. Genuine host outages keep the
deliberate `LlmUnavailableError` fallback.

**Two owner rulings, 2026-08-30, both from one principle — nothing may mislead
about which model is being called:**

- **`judge` is excluded from the settings surface.** Review found that a stored
  judge choice was persisted and reported as `effectiveBinding` while the only
  production judge path still bound the file role in
  `evals/harness/judge.py`, so a selection could be displayed as in effect and
  silently ignored. Rather than widen this story into the eval harness, `judge`
  is now explicitly file-only: absent from `GET /settings/models`, refused by
  name on write, and pinned by a test that fails if it reappears while the
  harness still binds the file role. Wiring it properly is **B-41**, filed with
  the evidence — including that `evals/tests/test_run_judge.py` replaces
  `build_llm` without asserting which binding was passed, which is why the
  non-adoption went unnoticed.
- **A catalog binding with no resolvable endpoint is refused at config load.**
  Previously such a binding produced a runtime error naming only "the
  provider's default endpoint", which does not meet B-38's requirement that the
  message name an actionable URL. Guessing one from the SDK would contradict
  AD-10, so the config now fails closed instead. **This amends story 8.1's rule
  that a synthesized legacy entry may load without a matching `providers:`
  entry — an existing `config.yaml` relying on that exemption will now fail to
  load, which is the intent.**

Gate at landing: 2,510 server tests, 655 evals, 294 web, 128 puller, plus lint,
typecheck and the production build.

**The committed TS client is regenerated on this branch**, so `make client` is
not owed for 8-2. Note story 6.4 does NOT regenerate it and its
`/acquisitions` routes are therefore missing from the client — that
regeneration is owed at 6.4's integration and blocks story 6.5.
## Story 7.3 — Speaker Assignment (2026-08-30)

`PUT /meetings/{meetingId}/speakers/{tag}` takes a participant id, a new display
name, or `unresolved`. It writes an api-owned `participant_alias` row under
`speaker:<meetingId>:<tag>` and re-arms the meeting's job for `align → moments →
extract` only; `align` reads that namespace back before writing each segment,
follows one merge hop, and records attendance so the graph's `SPOKE_IN` edge has
a `Participant` node to match. `unresolved` is a deletion of the alias, because
`participant_alias.participant_id` is `NOT NULL` — which restores `align`'s own
`placeholder` answer and guesses nothing.

The story's real clause is pinned: a rename leaves every pre-existing moment id,
approved artifact and published artifact untouched, and extraction replaces
drafts only. Proved by mutation — perturbing segment timing by 1 ms re-keys
`transcript:40000` to `transcript:40001` and the test catches it.

Two defects surfaced red-first and were fixed: a curator-minted participant keyed
by its own alias key could never be merged away, and any participant named as a
speaker read to Epic 2's merge predicate as having absorbed someone. Four
recorded footprint departures (`pipeline/stages/align.py`, `api/participants.py`,
and one forced line each in `test_api_speakers.py` and `test_compose_contract.py`)
are in the spec's Change Log. B-39 and B-40 filed. Left at `review`.

## 7-3 landed, 2026-08-30 ~23:35 — a rename cannot break a citation

`main` at `ee21eb5`. `PUT /meetings/{meetingId}/speakers/{tag}` accepts a
participant id, a new display name, or `unresolved`; it writes an api-owned
`participant_alias` row under `speaker:<meetingId>:<tag>` (AD-5) and re-arms
the meeting's job for `align → moments → extract` only. `unresolved` is a
deletion of the alias, which restores `align`'s own `placeholder` and guesses
no name. No migration — every column already existed.

**The story's real risk was proved, not asserted.** The citation test was
written first and observed failing whole, then demonstrated by mutation:
perturbing segment timing by 1 ms re-keys `transcript:40000` to
`transcript:40001`, mints a new moment id, and the test catches it. After a
rerun every pre-existing moment id, citation, and approved or published
artifact still resolves; extraction replaces drafts only.

**Two silent defects were caught during the build, both fixed:** a
curator-minted participant keyed by its own alias key could never be merged,
because `participants.py` reads "own identity key appears as an alias key" as
"merged away" — minted rows now use a separate `curated:` space; and any
participant named as a speaker looked to Epic 2's merge predicate as having
absorbed someone, silently blocking every later merge of them.

**Two owner rulings, 2026-08-30:**

- **The frozen matrix row was amended, not the code.** The row required the
  minted participant's `identity_key` to equal the speaker alias key, which
  specifies the unmergeable design above. The spec now names the `curated:`
  space and records why.
- **The speaker PUT is admitted when a meeting's evidence is unsettled.** A
  failed `align`/`moments` rerun previously made the meeting unviewable, which
  locked the curator out of the very surface needed to undo the assignment that
  caused it. This is one deliberate PUT-only exception with explicit
  recovery-state fields — every other read and write keeps today's viewability
  behaviour, pinned by a regression, and an unknown meeting is still 404.

**Generated-client conflict, resolved by regeneration rather than merge.**
Stories 7.3 and 8.2 both regenerated `web/src/client/`, so their generated
files conflicted at integrate. Generated output is never hand-merged: main's
side was taken through the rebase and the client was then regenerated once from
an in-process `app.openapi()` dump on the rebased tree, so it now carries both
8.2's `/settings` routes and 7.3's speaker assignment. **The dump must add a
`servers` entry** — generating from a file rather than a URL otherwise drops
`client.gen.ts`'s `baseUrl`, which would quietly break the web client's default
host. That was caught by reading the diff rather than trusting the tool.
## Story 6.4 — Acquisition Launch Surface, 2026-08-30 (review)

Branch `story/6-4`, rebased onto `main` at `e5e0ff9`. Three routes in one new auto-discovered
router, and the api performs no acquisition: `POST /acquisitions` classifies
the URL offline, claims the source id under one `fcntl.flock`, writes a status
file under `.logs/acquisitions/`, starts `python -m meetingminer.acquisitions
--run` detached with that acquisition's log as its stdout, and answers 202.

**The footprint held exactly.** Five paths: two new modules, one new test
module, one addition to `youtube.py` (`ProbeReport` + `probe_only`, composed
from 6.2's existing checks — no existing function changed or forked), and the
one-entry `BASELINE_ROUTER_ORDER` extension the spec pre-declared.
`mintdrop.py`, `config.py`, `conftest.py`, `api/main.py` and `web/` are
untouched.

**Two decisions worth carrying forward.** The rule → HTTP status and rule →
remediation tables are *literal dicts* keyed on `youtube.REFUSAL_RULES`, not
comprehensions over it: a comprehension would give a rule added later a silent
default and make the completeness test vacuous. And `refusal_rule()` classifies
an intake failure as `unclassified` — correct, the tool refused nothing — so
that row keeps the token and carries its own remediation, the exact `curl`
re-POST for the finalized drop.

**`make client` is owed and was not run.** The epic's last clause puts the TS
client regeneration in this story; `web/` is outside the footprint and
`make client` needs a running api, which this wave forbids starting.
`check-client` only asserts the three files exist, so the gate stays green
while `web/src/client/` knows nothing about `/acquisitions`. **Story 6.5
cannot start until integration runs it.** Filed as the spec's first deferred
item, severity high.

**Backlog ids: none claimed.** Five deferred items are recorded in the spec's
frontmatter rather than in `docs/backlog.md`, which the wave rules put off
limits to this lane. They need real ids filed at integration — naming one here
would not reserve it.

**Verified on the final tree.** `make test-fast` green (lint clean, mypy clean,
2042 passed, 3 skipped); `make test` green — 2420 passed, 3 skipped, web build
clean, 9m42s; `branch_conflicts.py --against story/6-4` clean against `main` and
against every other `story/*` except `sprint-notes.md`, where three lanes append
at the same EOF and two of them already conflict with `main` there. The tests
were written after the code, so coverage was proved by mutation instead: sixteen
single-edit mutations across the three source files and the registry baseline,
**fifteen red**. The one that stayed green is the log-path hardening, which the
`read_record` id guard makes provably equivalent — defence in depth, not
coverage.

**Rebased after the build** onto `origin/main` at `e5e0ff9` (the B-36 diarizer
work, 17 commits, none touching this story's paths). One conflict —
`sprint-notes.md`, both sides appending at EOF — resolved as a union;
`sprint-status.yaml` merged key-wise through its driver. `make test-fast` and
`make test` re-run green afterwards, and `main × story/6-4` is clean.

## 6-4 landed, 2026-08-31 ~00:05 — the acquisition surface, and the client caught up

`main` at `c4fac35`, plus the client regeneration that followed it. The api
accepts and reports on an acquisition rather than performing one: `POST
/acquisitions` launches the tool as a detached host process with a status file
and log under `.logs/`, answers 202, and refuses a second running acquisition
for the same source id; `POST /acquisitions/probe` runs story 6.2's checks with
no download, mint, process start or state write; `GET /acquisitions/{id}`
reports `queued | running | posted | failed` with the log tail, maps 6.2's
`exists` short-circuit to `posted`/`result: exists`, and a `failed` status
carries `refusal{rule, detail, remediation}` so no client parses a log tail.

**Red-first was NOT followed by this lane**, and it disclosed that itself:
tests were written after the code, with coverage argued from 16 mutations
(15 red). The review was told to treat that evidence as the claim under audit
rather than accept it, and re-ran a sample. Worth remembering when reading this
story's coverage — it is the one lane in the wave whose tests were not written
against failing code first.

**Two rulings closed it, and they were different in kind:**

- **`intake-failed` was a coordinator call, not an owner decision.** The lane
  left it open because extending story 6.2a's closed refusal vocabulary looked
  like a footprint breach. But the footprint I wrote said "reuse 6.2's existing
  checks; do not fork them" and "use that vocabulary; do not invent a second
  one" — extending the closed set is what that meant, so the ambiguity was
  mine. Added red-first.
- **The frozen 404/422 matrix row was amended under story 7.3's precedent.**
  The row predicted 422 for a non-UUID id; an encoded-separator id is
  legitimately refused a step earlier as 404. The owner had ruled hours before,
  on 7.3's F-6, that a frozen row disagreeing with correct code is amended
  rather than the code weakened. Applied here without waiting, and flagged in
  the report as reversible — the owner has not seen this specific row.

**`make client` was owed and is now run.** 6.4 left it to integration
deliberately (web/ outside its footprint), and it blocked story 6.5. The
client now carries all three `/acquisitions` routes; `web-test` 294 passed and
the production build is clean. **6.5 is unblocked.**

## Story 10.3 — Thread Timeline API with Level-of-Detail — 2026-08-31

Two read-only routes (`GET /threads`, `GET /threads/{threadId}/timeline`),
migration 0017, and a pure `domain/thread_timeline.py`. Left in `review`.

**The four risk clauses, and how each is proven.**

- **Each level returns exactly its tier.** Four response models discriminated
  on `level`, so a `bands` response has no `moments` key rather than an empty
  one. Asserted by whole-key-set comparison per level, not by spot checks.
- **`colorOrdinal`.** A Postgres sequence, because two concurrent derivations
  reading `max(color_ordinal) + 1` get the same answer and the UNIQUE
  constraint then turns a colour clash into a failed derivation. A trigger
  refuses any `UPDATE` that changes the value, so "a merge survivor keeps its
  ordinal" is a record guarantee rather than a caller convention; a split is a
  new row and takes a new value. Tested with two open, uncommitted
  transactions.
- **`occurredAt`.** Derived server-side twice over — once in Python for the
  fine levels, once as a SQL twin for the aggregates — and the two are pinned
  against each other by test. Day precision anchors at `00:00:00Z + startMs`
  and keeps `occurredAtPrecision: day`. Ties break by `meetingId`, then
  `momentId`.
- **Coarse levels are cheap.** `bands` and `meetings` aggregate over
  `topic_thread → topic_mention → meeting` and never join `moment` —
  `topic_mention` already carries `meeting_id` and `anchor_ms`. Proven
  statically (no coarse statement names `moment` as a relation, with a
  self-test that the pattern can fail and does not trip on `topic_mention`)
  and live by `EXPLAIN`, with the fine level as a control so the assertion
  cannot be vacuous. Band size is bounded by a bucket ladder, not by window
  width.

**A wrong allocator hung the suite rather than failing it.** Mutating the
migration to `max(color_ordinal) + 1` made the second concurrent insert block
on the unique index until the first transaction ended — an unbounded wait that
reads as a hung run, not a caught defect. The concurrency test now sets
`lock_timeout`, so the mutation fails it in seconds. Found by mutation
testing, not by review.

**Mutation sweep: 12 deliberate breakages, 12 caught.** Level leakage, a
storage path served as a moment title, `max()+1` allocation, the immutability
trigger removed, day anchoring dropped (SQL half and Python half separately),
the tie-break reversed, `moment` joined into the coarse projection, the window
predicate removed, unresolved speakers printed as names, an emptied identity
row listed as navigable, and superseded moments interleaved with live ones.
The eleventh needed a second attempt: the first version converted two of three
joins to `LEFT JOIN` and the surviving inner join to `meeting` still dropped
the row, so the mutant was equivalent rather than the test weak.

**One edit outside the footprint**, recorded in the spec change log:
`server/tests/test_api_registry.py`, one line appended to
`BASELINE_ROUTER_ORDER`. That assertion is exact equality, so *any* new router
module must edit it. `threads.py` was left at default `ROUTER_ORDER` on
purpose, which puts the addition at the end of the list rather than mid-list
and keeps it clear of where story 10.4's `moments_feed` will land.

**B-40 closed, B-42 filed.** B-40's open question was the scope of "per
corpus"; the answer is the database of record, because threads are derived
corpus-wide and can span `meeting.corpus` values, so partitioning by that
column would give a cross-corpus thread two colours. B-42 is the gap this
story could not close inside its footprint: AD-17's
`GET /media/files/{mediaId}` is named by both 10.3's and 10.4's acceptance
criteria and exists in neither footprint, so this API serves the opaque ids
that route will take and never a path, and the route itself remains unbuilt.

**Verification.** `make test-fast`: 2222 passed, 3 named skips, 411
deselected, with ruff and mypy clean. `branch_conflicts.py --against
story/10-3`: 15 clean pairs, 0 conflicting. Full `make test` result recorded
with the story's SHAs.
