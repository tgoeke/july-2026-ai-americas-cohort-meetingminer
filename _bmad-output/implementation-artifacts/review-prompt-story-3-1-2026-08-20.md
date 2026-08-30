# Reviewer handoff — Story 3.1: Corpus Search

For the Codex `bmad-code-review` agent. You have none of the build run's
context; everything you need is below.

## Repo, branch, range

- **Repo:** `/Users/devopsterus/current/cohort/meetingminer` (worktree for this
  branch: `/Users/devopsterus/current/cohort/meetingminer-wt/3-1`)
- **Branch:** `story/3-1`, pushed to `origin/story/3-1`, in sync (`git rev-list
  --left-right --count HEAD...@{u}` = `0	0`), working tree clean.
- **Review range:** `65f0b1cabd724735842afab6c8bb2a912326c98b..HEAD`

Read AGENTS.md at the repo root first. Work in your own worktree; never reset a
tree you do not exclusively own. Store-backed server suites are safe to run
concurrently (per-run Postgres database; projection tests take a bounded
cross-worktree file lock). `make evals-run` is still serial — announce it.

### Commits in the range, newest first

- `d57d69f5070d5f1434994c10adb2667ab5fbf4c0` docs(story 3.1): record the review pass and close the story
- `b8027716360679feccf9e336e08a6600bb8ae985` docs(story 3.1): correct the bookkeeping the review caught
- `5ae2b44946957c6d61891a7378123e082511fe2a` fix(web): tell the three search failures apart, and stop wedging on "Searching…"
- `4d2b83e24240cf8ba470342969c1d7d63090ba86` chore(web): regenerate the client for indexMissing and the dated startedAt
- `5f3408f04dfbb12e7b3a4be50761286d2cba0878` fix(search): name every refusal, and test the ranking rather than the set
- `6d594a9258b152b70f9d92e54ec862653d890b4e` docs(story 3.1): correct the client-regeneration command in the spec
- `ac541e78936f99c3274de77813d399a11db50869` test(story 3.1): cover the unreachable-search-store refusal
- `a92b376d126735d04d02c9b7f9e2b07841b71441` docs(story 3.1): move corpus search to review and record what landed
- `7babd411e09ae6f6282d6eca8270c003b3f32dfc` feat(web): corpus search view with highlighted snippets and inline replay
- `037290301ed3d6d4ce7b62e6d7579354768c3e14` feat(search): floor the semantic lane and cover /search end to end
- `39609941343681d9df85db952c3802677cb802c6` feat(search): add the query side of the search projection and GET /search
- `1ee383dada16ce6e96b6f62a333cf59ac23ed145` docs(story 3.1): frozen contract for corpus search
- `325b990223c7629bc3e57aaba6394691899c415c` docs(story 3.1): compile epic 3 context for build-auto planning

Every commit in this range belongs to story 3.1. None belongs to another story.

## The spec, and which part of it is frozen

`_bmad-output/implementation-artifacts/spec-3-1-corpus-search.md`

- **Frozen intent — do not critique as if it were a proposal.** Everything
  inside the `<intent-contract>` block: Intent, Boundaries & Constraints, and
  the I/O & Edge-Case Matrix. It was written before implementation and was not
  modified during it (verify: the only deletions in that file across the range
  are the `status:` line and one Verification command).
- **Planner work — attack this freely.** Code Map, Tasks & Acceptance, Design
  Notes, Spec Change Log, Review Triage Log, Auto Run Result. The design
  decisions listed below all live here.

The story's own source of intent is `_bmad-output/planning-artifacts/epics.md`,
"Story 3.1: Corpus Search" (FR12, UX-DR3, UX-DR4) and its four acceptance
criteria. Epic-level distillation:
`_bmad-output/implementation-artifacts/epic-3-context.md`.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`.
The decision records that govern this change specifically:

- **AD-4 — projections have exactly one writer.** All Neo4j/Meilisearch access
  lives in `server/meetingminer/projections/`. Enforced by AST walk in
  `server/tests/test_projections_single_writer.py`, whose
  `test_the_api_package_never_reaches_a_store` is the check this story had to
  satisfy. The publish gate lives inside the projection module.
- **AD-6 — citations are Postgres-minted moment IDs, gated in code.** A
  moment's id is minted once and carried verbatim into every store and every
  answer.
- **AD-8 / AD-10 — model calls go through configured ports.** The `Embedder`
  port is `userProvided` on the Meilisearch side, so the store cannot embed the
  query; the caller must pass the vector. Every retrieval knob belongs in
  `config.yaml`, never as a Python constant.
- **AD-15 — one citation wire format.** Every search or chat result exposes at
  least one resolvable `momentId`; consumers render from structured data and
  never parse markers. This story extends that principle to highlights.
- **AD-2** (Postgres is the sole database of record) and the spine's
  Consistency Conventions (UUIDv7 ids, integer-millisecond offsets, camelCase
  at the API boundary, RFC 9457 errors) also bind.

Measurement authority for the retrieval decisions:
`_bmad-output/specs/spec-meetingminer/retrieval-prior-art.md` §7. NFR7 (only
`published` artifacts are retrievable) comes from `SPEC.md` Constraints.

## Scope

### In scope — the files this story owns

- `server/meetingminer/projections/query.py` (new)
- `server/meetingminer/api/search.py` (new)
- `server/meetingminer/api/main.py`
- `server/meetingminer/config.py`, `config.yaml`
- `server/meetingminer/projections/evidence.py`
- `server/meetingminer/projections/search.py`
- `server/tests/test_projections_query.py` (new), `server/tests/test_api_search.py` (new)
- `server/tests/test_failfast.py`, `server/tests/test_config.py`
- `web/src/features/search/{hits.ts,CorpusSearch.tsx,CorpusSearch.test.tsx}` (new)
- `web/src/App.tsx`, `web/src/App.test.tsx`
- `web/src/client/*.gen.ts` (generated output, committed on purpose)
- `_bmad-output/implementation-artifacts/{spec-3-1-corpus-search.md,epic-3-context.md,sprint-status.yaml,sprint-notes.md}`

### Explicitly out of scope

- **The meeting drill-down transcript page and the moment view.** Stories 2.3
  and 2.2 own these and are both `backlog`. This is the sharpest scope call in
  the change — see design decision 6 below.
- **Neo4j traversal retrieval.** Story 3.2.
- **Chat, synthesis, the citation validator.** Story 3.3.
- **The artifacts index and the publish path.** Epic 4. The `artifacts` index
  does not exist; this story only guarantees search cannot reach it.
- **`pull_transcript/` and `docs/`.** Story 2.1b was in flight there during
  this run; nothing in this range writes to either.
- Items already recorded as deferred in the spec's frontmatter `deferred` list
  (14 entries) — read them before filing a finding, so you do not re-report
  something already triaged with evidence.

## Design decisions to attack

These were made during planning or implementation. The planner is not a neutral
judge of its own calls; each is stated as the choice plus the assumption under
it.

1. **`/search` queries the `moments` index only, never `chunks`.** Assumption:
   moment granularity is close enough to chunk granularity for user-facing
   search, because moments are the citation-shaped unit (AD-6) and eval check
   2.10 is phrased in moments. The embeddings bake-off measured *chunks*, not
   moments, and nothing in this change re-measures it.

2. **Meilisearch ranks; Postgres cites.** Every citation field on the wire is
   re-read from the database of record in the same request, so a stale index
   document becomes a dropped-and-logged hit rather than a citation resolving
   nowhere. Assumption: the extra query per request is acceptable at demo
   scale. Note the asymmetry a reviewer should push on — the *citation fields*
   are re-verified against Postgres but the `meetingId`/`corpus` *scope
   filters* are not, so a stale document whose meeting changed corpus could
   leak into a scoped result set.

3. **`semantic_ratio` defaults to 0.3 (keyword-heavy).** Reasoned from
   `retrieval-prior-art.md` §7 finding 1: on transcript-worded queries — the
   measured dominant shape — no embedding model beat BM25 alone and six of nine
   hybrid configurations scored below the keyword baseline. Assumption: those
   findings transfer to this ratio. The number itself is unmeasured on this
   corpus.

4. **`semantic_score_floor` — a fifth config knob the frozen contract did not
   name.** This is the weakest link in the change and deserves the hardest
   look. Meilisearch's vector lane has no notion of "no match": with any
   `semanticRatio > 0` a nonsense query returns the k nearest moments, so the
   matrix's "empty is a valid answer" row and the typo-tolerance AC cannot both
   hold. Meilisearch's own `rankingScoreThreshold` spans both lanes, which do
   not share a scale (measured: keyword hit 0.1496, semantic hit on unrelated
   text ~0.65). The resolution filters the semantic tail alone, identified via
   `semanticHitCount`. Default 0.75, measured over **five** seeded moments with
   `qwen3-embedding:0.6b`: paraphrase 0.783, unrelated real query 0.734,
   nonsense 0.701. Assumptions worth attacking: (a) that gap generalises beyond
   five moments; (b) Meilisearch really does return keyword hits first with the
   semantic tail last — asserted only against a hand-built list, never against
   the live store; (c) the split has any defined meaning on an `offset > 0`
   page; (d) a legitimate paraphrase scoring 0.70–0.75 is silently discarded
   today.

5. **Highlights are structured `{text, highlighted}` runs, using U+E000/U+E001
   as the Meilisearch pre/post tags.** Keeps markup off the wire and out of
   React. Assumption: those private-use code points never occur in transcript
   or OCR text. The parser treats an unmatched sentinel as literal text and a
   test covers it.

6. **Scope boundary against Epic 2 — the call most worth disputing.** AC2 says
   a result "links into meeting drill-down with the matched terms highlighted"
   and AC3's path ends in a transcript view with inline replay. Story 2.3 owns
   that view verbatim ("transcript mentions are highlighted and each transcript
   region links to its moment") and story 2.2 owns the moment view; both are
   `backlog`. This story therefore delivers search → candidate moments →
   highlighted snippet → inline replay using story 2.1's existing
   `ReplayPlayer`, and the meeting title renders as **plain text, not a link**.
   Assumption: AC2's link clause is discharged by the hit carrying `momentId`
   and `meetingId`, with the anchor added when 2.3 lands. If you disagree, that
   is a legitimate finding — say so.

7. **OCR text was added to the index as a new `screenText` attribute** rather
   than treated as already-covered. AC1 requires the index to span "transcripts
   and OCR text"; nothing carried OCR text into either index before this story.
   Assumption: the representative frame's OCR text is the right granularity.
   Note it is indexed for BM25 but **never embedded**, so a paraphrase of
   on-screen content cannot reach the vector lane.

8. **The embedder is built at api import, not in `lifespan`.** Matches the
   `require_drops_root` house pattern and fails fast on a config error.
   Consequence a reviewer may object to: a config with no serving provider
   takes `/health`, `/meetings`, `/media` and the job stream down with it,
   which is wider than `/search` needs given `/search` degrades when the host
   is merely unreachable. Moving it to `lifespan` was considered and rejected
   because the `search_client` test fixture reads `app.state.embedder` without
   running lifespan.

9. **Embedder failures split two ways.** `EmbedderUnavailableError` (host down)
   degrades to keyword-only and announces `ranking: "keyword"`;
   `EmbedderError` (misconfiguration) is a named 503. Assumption: a config
   error must never masquerade as an outage.

## History you need to tell a regression from a pre-existing condition

- **The branch was cut from `65f0b1c` and never rebased.** `origin/main` has
  since advanced by four commits (`0df90af`, `e794365`, `533e591`, `67e0270`).
  The only file that overlaps is
  `_bmad-output/implementation-artifacts/sprint-status.yaml`, which has a
  key-wise merge driver (`_bmad/scripts/merge_sprint_status.py`) for exactly
  this. Rebase before merging, per AGENTS.md.
- **`web/src/client/*.gen.ts` gained `getRecording` and `getMediaFile`** on top
  of `searchCorpus`. Those two were missing from the committed client since
  story 2.1; regeneration emits the whole sdk. Not a change this story made to
  the API surface.
- **`client.gen.ts`'s `baseUrl: 'http://localhost:8000'` literal is restored by
  hand** after regeneration. Generating from a dumped OpenAPI file drops it,
  because FastAPI emits no `servers` block; only live-api generation injects
  it. `web/src/lib/api.ts` overrides it at runtime either way.
- **`server/tests/test_api_search.py` uses a local `SpreadEmbedder`, not
  `conftest.fake_embedder`** as the spec's task list named. `FakeEmbedder`
  produces near-parallel vectors, against which the semantic floor cannot be
  measured. Recorded in the spec's Spec Change Log.
- **One lint warning predates this story**: `react(only-export-components)` in
  `web/src/components/ui/button.tsx`, a file this range never touches.
- **A build-time review pass already ran** (four layers: blind hunter,
  edge-case hunter, verification-gap, intent-alignment). 23 findings were
  patched, 14 deferred with evidence into the spec's frontmatter, 5 rejected.
  The triage log in the spec lists what was fixed. Findings that duplicate a
  deferred entry are not new.

## Verification baseline

Run in the story worktree at `d57d69f`, observed directly. A skip or failure
during your review is a finding, not noise.

| Command | Result |
|---|---|
| `uv run --project server pytest server/tests` | **1009 passed**, 0 skipped, 0 failed, 1 pre-existing warning (277.53s) |
| `pnpm --dir web run test` | **86 passed**, 6 files |
| `pnpm --dir web run build` | clean (`tsc -b` + vite) |
| `pnpm --dir web lint` | clean except the pre-existing `button.tsx` warning |

The server suite needs the Docker stores up (`make infra-up`); with them down
the store-backed cases skip by name rather than fail, so **a skip count above
zero means you did not actually exercise the search path**.

Client-regeneration check (store-free, needs no running api), from the repo
root:

```
server/.venv/bin/python -c "import json,pathlib;from meetingminer.api.main import app;pathlib.Path('openapi.json').write_text(json.dumps(app.openapi()))"
pnpm --dir web run client -i ../openapi.json
```

`-i` resolves relative to `web/`. Expect `sdk.gen.ts` and `types.gen.ts`
byte-identical to what is committed, and `client.gen.ts` differing only by the
`baseUrl` literal. Delete the temp `openapi.json` afterwards.

## Required output

Write your findings to:

`_bmad-output/implementation-artifacts/review-story-3-1-2026-08-20.md`

**Report findings; do not apply fixes.** Structure each as:

- **Location** — `file:line`
- **Severity** — high / medium / low, by consequence to the user of the system
- **Finding** — what is wrong
- **Evidence** — why it is real: the input or state that triggers it and the
  wrong output or behaviour that follows. A finding that cannot name a failing
  case is a hypothesis; label it as one.
- **Suggested direction** — what a fix would have to do, not a patch

Close with an overall verdict (pass / pass with findings / fail) and say
explicitly which acceptance criteria you consider met and which not. If you
believe design decision 6 (the Epic 2 scope boundary) is wrong, say so plainly
— it is the call most likely to be contested and the one the build run most
wants challenged.
