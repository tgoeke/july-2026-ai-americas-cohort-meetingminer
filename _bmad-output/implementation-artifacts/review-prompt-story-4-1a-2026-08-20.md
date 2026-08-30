# Reviewer handoff — Story 4-1a: Whole-Transcript Extraction

Paste the block below to the Codex `bmad-code-review` agent. It stands alone:
assume the reviewer has none of the build run's context.

---

## FIRST: what this review must produce

**Write your report to
`_bmad-output/implementation-artifacts/review-story-4-1a-2026-08-20.md`.**
A review that exists only as terminal text does not exist. Six reviews in this
repository were lost that way, and one of them named its own output file in the
prompt and still did not write it.

**Create and commit the report as a skeleton BEFORE you read any code.** Scope,
review range, and an empty findings section. Then append each finding as you
confirm it and commit incrementally. A crashed or closed session must lose
prose, never the artifact.

Each finding carries: **Location / Severity / Finding / Evidence / Suggested
direction.** Report findings; do not fix them.

**Before you report completion:** run `make check-reviews` — it fails while any
dispatched review lacks a committed report, including this one — and state the
SHA carrying the report's final version.

---

## Repository, branch, range

- Repo: `github.com:tgoeke/meetingminer`, worktree `../meetingminer-wt/4-1a`,
  branch `story/4-1a` (pushed, in sync with its upstream).
- **Review range: `100b09921ecc0113912dab689c9c770cdba7cf76..HEAD`** (HEAD is
  `05b54fcab71ad48e6ffac4fea60451c150c2f1f7`).

Commits in range, oldest first:

| Revision | Subject |
|---|---|
| `7015d56e3af34c197011804a0654f7f221a4807f` | docs(4-1a): baseline revision and in-progress status |
| `e740b440457cf61fa9f6b1fda70989e8167cd5fd` | feat(4-1a): whole-transcript extraction — adopt when present, generate when absent |
| `ea722c8e34e96af3625809bebf0c98aa716ac3dc` | test(4-1a): rework the extract suites for whole-transcript extraction |
| `09ae3665892861ec2dbbf4e4d3de660f51837568` | feat(4-1a): the puller carries its generated documents into the drop |
| `4c4f20a1b0079eed66bfc53d42de9a36bea56492` | test(4-1a): pin the committed extraction binding, and record the run result |
| `8d74d9fadf634cc6ec7a8f6c5462f9d23d3395e4` | test(4-1a): cover the empty-transcript I/O matrix row |
| `c4cf887e4f964bd41fd1ee827f8a9ba8b4ff3676` | docs(4-1a): review triage — 9 deferred findings, spec fix for the fallback endpoint |
| `03bbcf9af44383f811e28cf8698c81839199f25c` | fix(4-1a): parser review findings — anchors, titles, owners, per-owner IDs |
| `d13b77b405b53d6d0594504a7d678cc482032350` | fix(4-1a): the fallback keeps its own endpoint, and an ignored num_ctx is named |
| `bab5ddd65f492ffc7510f8845178474f203dca83` | fix(4-1a): stage review findings — declaration cross-check, counts, refusals |
| `7bdfa3b64564873f7025528b8ee113a7a737f012` | test(4-1a): cover migration 0010's constraints and the new canonical filenames |
| `16b04abcfbae1c612a4290b7662369e0626b1f95` | fix(4-1a): sidecar before summaries, bound the summariser, pin the ordering |
| `3987d032b8deaab20a4a6ef3625ac2744cc299b2` | docs(4-1a): record the review round and the re-run verification counts |
| `ec791982475873f3fa623b81ebb0c261a9aec65e` | docs(4-1a): reconcile the run result with the coordinator's triage counts |
| `05b54fcab71ad48e6ffac4fea60451c150c2f1f7` | docs(4-1a): review triage log, follow-up recommendation, status done |

Every commit in this range belongs to story 4-1a. There is no foreign commit to
separate out.

## The spec, and which half of it you may attack

`_bmad-output/implementation-artifacts/spec-4-1a-whole-transcript-extraction.md`

- **Frozen intent — not yours to critique.** Everything inside
  `<intent-contract>`: Intent, Boundaries & Constraints, and the I/O &
  Edge-Case Matrix. This is the user's decision, re-rendered into SPEC CAP-5 on
  2026-08-20.
- **Planner work — attack freely.** Code Map, Tasks & Acceptance, Design Notes,
  Verification, Spec Change Log, Review Triage Log, Auto Run Result. A planner
  is not a neutral judge of its own calls; the design decisions below are the
  ones most worth your scepticism.

The original builder handoff is
`_bmad-output/implementation-artifacts/build-prompt-story-4-1a-2026-08-20.md`.

## Architecture authority that governs this change

From `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:

- **AD-5 (table ownership split by column)** — the worker inserts artifact rows
  and owns extraction content; `state` is the API's and is written only as the
  insert default `'extracted'`. No worker path may update it.
- **AD-8 (all model calls behind configured ports)** — `litellm` is importable
  only under `adapters/llm/`; swapping a model is a config edit.
- **AD-17 (every evidence file has a row)** — an adopted extraction document is
  *arrived* material and needs a row naming its drops-root-relative path,
  `sha256` and `byte_size`. `transcript_source` (migration 0005) is the
  reference for that triple; 0008 carries the root-relative CHECK constraints.
- **AD-11 (idempotence)**, **AD-4 (projections have one writer; nothing projects
  at extract)**, **AD-1/AD-14 (the drop is the one intake door; write-once)**.

From `_bmad-output/specs/spec-meetingminer/SPEC.md`: **CAP-5 as re-rendered
2026-08-20**, the **no silent zero** constraint, **no citation, no answer**, and
the constraint that **extraction defaults to a local model** and any paid call
needs fresh per-run authorization. `retrieval-prior-art.md` §8 is the measured
failure this story exists to close.

## Scope

**In scope** — the files this story owns:

- `server/meetingminer/pipeline/extraction.py`, `pipeline/stages/extract.py`
- `server/meetingminer/migrations/0010_extraction_sources.sql`
- `server/meetingminer/adapters/llm/{port,litellm,__init__}.py`
- `server/meetingminer/config.py`, `config.yaml`
- `server/meetingminer/domain/drops.py`, `docs/source-drop.schema.json`
- `pull_transcript/{emit-drop.js,grab-teams-transcript.js,CLAUDE.md}` and
  `pull_transcript/test/`
- `server/tests/{test_extraction_core,test_worker_extract,test_drop_schema,test_drops_root,test_ingests}.py`,
  `server/tests/conftest.py`

**Explicitly out of scope:**

- `meetingminer/api/` and `web/` — story 3.3 owns the API surface this wave and
  nothing here touches either. The right-rail read is 2.2; approval and
  publishing are 4.3; artifact re-indexing is 4.4; prompt visibility in the UI
  is 4.2; Epic 5 owns the extraction-quality checkers.
- The nine items already recorded in the spec's frontmatter `deferred` list.
  Read them before filing anything — re-reporting a recorded deferral costs a
  verification pass. They include: the api cannot re-run `extract` on an
  augmenting re-arm, screen evidence no longer reaching the prompt, and
  `_meeting_date` rendering UTC.
- Reunifying the two `pull_transcript` working copies.

## Design decisions to attack — each stated as the choice plus its assumption

1. **Two model calls per meeting, not one.** CAP-5 says extraction happens "in
   one pass per meeting"; the committed `config.yaml` comment says "twice per
   meeting". *Assumption:* "one pass" was written in opposition to *per moment*
   and names the unit of input, not the call count — and since the adopt path
   parses two documents, a single generate call could not converge on the same
   parser. **If that assumption is wrong the whole shape is wrong.** This
   contradiction is live in the repo; CAP-5 is spec-kernel text a story branch
   may not amend.
2. **Markdown, not JSON.** Story 4.1 parsed a pinned JSON reply. Because the
   adopt path receives summariser markdown and one parser must serve both
   paths, the generate prompts now emit markdown too. *Assumption:* the
   two-layout tests plus the no-silent-zero signal compensate for markdown being
   a looser contract than JSON.
3. **The parser keys on item ID plus timestamp, treating headings as
   advisory.** *Assumption:* sampled real output varies too much in heading
   style to key on, while the prompt-mandated IDs (`D1`, `A1`, `R1`, `BR1`) are
   stable. Attack: an ID *reference* in a later section that happens to carry a
   timestamp could become a second artifact.
4. **An unresolvable anchor raises and fails the whole meeting** rather than
   dropping one artifact. *Assumption:* the contract's "named error path, not a
   dropped artifact" selects raising, and a re-queueable failure beats an
   unrecoverable silent loss. Cost: one fabricated timestamp costs a meeting its
   whole artifact set.
5. **Three new optional `LlmRoleBinding` fields** (`base_url`,
   `timeout_seconds`, `num_ctx`) plus `fallback_base_url`, which the frozen
   contract did not name. *Assumption:* the story's own default cannot work
   without them — `providers.ollama.base_url` is shared with the embedder, the
   120s default is shorter than a measured ~3-minute pass, and an unset
   `num_ctx` truncates silently.
6. **`generateDocs` reordered ahead of the drop emit** in the puller.
   *Assumption:* without it the adopt path is unreachable for every future pull.
   Cost: the drop now lands 3–6 minutes later.
7. **A private LAN address, `http://10.77.0.52:11434`, is committed in
   `config.yaml`** with no environment override.
8. **`item_count` was added to migration 0010 in place** rather than in an
   `0011`. *Assumption:* 0010 is introduced by this unmerged branch and has been
   applied nowhere.

## History you need to tell a regression from a pre-existing condition

- **This story replaces story 4.1, it does not extend it.** 4.1 shipped
  *per-moment* extraction and is `status: done`
  (`spec-4-1-artifact-extraction-pipeline-stage.md`). Its per-moment prompt,
  its JSON `parse_artifacts`, and its per-moment stage loop were deliberately
  removed. Do not report their absence as a regression.
- **133 per-moment artifacts exist in the dev database as unpublished drafts.**
  The reworked stage's rerun replaces drafts by design; nothing published
  exists, so no citation can break. There is no cleanup script and none is
  wanted.
- **A four-layer review already ran** (blind, edge-case, verification-gap,
  intent-alignment) over `100b0992..c4cf887`: 22 findings patched, 9 deferred,
  6 rejected, 0 intent gaps. The Review Triage Log lists every patch. Commits
  `03bbcf9` through `16b04ab` are those fixes. `followup_review_recommended` is
  `true` — score 38 against a threshold of 5 — which is part of why you are
  reading this.
- **One finding was spec-caused and handled as a patch rather than a
  revert-and-re-derive loopback.** The spec had instructed that the role's
  `base_url` reach both primary and fallback, which repointed
  `ollama/qwen3:32b` away from the host it resolved to before this story. The
  Spec Change Log records the amendment *and* the deliberate process deviation.
  Judge that call.
- **Rejected during triage, so decide for yourself rather than assuming it was
  missed:** falling back to the generate path when an adopted document fails to
  parse. It was rejected because it would mask a broken parser — precisely the
  §8 failure. The cost is that one unreadable document in a write-once drop
  fails that meeting's job permanently.

## Verification baseline

Run these; a skip or failure during your review is a finding, not noise. All
were run by the coordinator at `05b54fc` and observed green:

| Command | Observed |
|---|---|
| `cd server && uv run pytest tests/test_extraction_core.py -q` | 102 passed |
| `cd server && uv run pytest tests/ -q` | 1326 passed, 0 failed (5:31) |
| `make puller-test` | 118 tests, 118 pass, 0 fail |
| `make web-test` | 157 passed (9 files) |
| `rg -n 'import litellm\|from litellm' server/meetingminer --glob '!**/adapters/llm/**'` | no matches (exit 1) |

`git status --porcelain` is empty and
`git rev-list --left-right --count HEAD...@{u}` reports `0	0`.

**Store note:** the server suite is safe to run concurrently — it takes a
per-run Postgres database and the projection tests queue on a cross-worktree
file lock. `make web-test`, `make puller-test` and `make evals-test` are
store-free. **Do not run `make evals-run`** (one at a time, and it is not
needed here).

**Money and the worker — read before running anything.** The worker is
**STOPPED by user decision** and must stay stopped; restarting it before this
merges is the user's call, not the reviewer's. The Anthropic key is revoked and
extraction now defaults to a local model. **Make no paid model calls, and no
live Ollama calls either** — every test runs against fake-LLM fixtures, and it
must stay that way. If you add a migration ordering note: `make migrate` must
run before any worker restart onto this code (migration `0010`).
