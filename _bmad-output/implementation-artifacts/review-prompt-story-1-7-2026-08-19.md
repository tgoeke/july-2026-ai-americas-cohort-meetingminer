# Reviewer handoff — Story 1.7: Evidence Projections & Rebuild CLI

You are reviewing a single commit. You have none of the context of the run that produced it;
everything you need is below.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `main` (pushed; `git rev-list --left-right --count HEAD...@{u}` reports `0	0`)
- Review range: `4e705e37954b9b43057798727e1f2c59eae03eee..HEAD`

One commit is in range, and all of it is this story:

- `bebbcc7b7dd157407f4d534f8cfb1467ce1742b7` — feat(projections): project the evidence bundle into
  Neo4j and Meilisearch (story 1.7)

No commit in the range belongs to another story. Story 1.9 was built in parallel in the same
working tree and landed immediately before this range (`848db81`, `7f6b76b`, `4e705e3`). Those are
**out of range and out of scope** — do not review them. See *History you need* below, because the
two stories share files.

## The spec

`_bmad-output/implementation-artifacts/spec-1-7-evidence-projections-rebuild-cli.md` (committed in
this range).

- Everything between `<intent-contract>` and `</intent-contract>` — Intent, Boundaries &
  Constraints, I/O & Edge-Case Matrix — is **frozen intent**. Treat it as the requirement. If you
  believe it is wrong, say so separately; do not treat a deviation from it as acceptable.
- Everything outside that block — Code Map, Tasks & Acceptance, Spec Change Log, Review Triage Log,
  Design Notes, Verification, Auto Run Result — is **planner work you may attack freely**.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`,
specifically these decision records:

- **AD-4** (line 188) — exactly one writer to Neo4j and Meilisearch; evidence projects at
  ingest-complete and artifacts at publish; the publish gate lives inside the module; embeddings go
  through the port; store-native auto-embedders stay disabled; `rebuild` regenerates from Postgres +
  config alone.
- **AD-6** (line 200) — a row's Postgres UUID is carried verbatim as the Neo4j node key and the
  Meilisearch document id.
- **AD-7** (line 206) — hand-written Cypher templates; no library owns graph structure.
- **AD-8** (line 212) — embedder model and dimension are projection state; a swap forces a rebuild.
- **AD-11** — the ingest pipeline's stage contract.
- Line 408 (`Deferred`) handed Neo4j naming and Meilisearch index settings to *this* story, so the
  node/edge names and index settings are decisions to judge, not givens.

`_bmad-output/specs/spec-meetingminer/retrieval-prior-art.md` is the measured upstream evidence the
design leans on — §2 node/edge shape and the never-key-on-a-sequence-number rule, §3 the five hard
constraints, §6 chunking measurements, §7 the model bake-off.

## Scope

**In scope — the 28 files in the commit:**

- `server/meetingminer/projections/` — `stores.py`, `evidence.py`, `chunking.py`, `graph.py`,
  `search.py`, `publish_gate.py`, `cli.py`, `__init__.py`
- `server/meetingminer/adapters/embed/` — `port.py`, `ollama.py`, `__init__.py`
- `server/meetingminer/migrations/0007_projection_state.sql`
- `server/meetingminer/pipeline/runner.py` (the `_maybe_project` trigger only)
- `server/meetingminer/config.py`, `config.yaml` (the `projections:` section and the `embedder.model`
  correction)
- `server/pyproject.toml`, `server/uv.lock`, `infra/Makefile`
- `server/tests/` — `projection_seed.py`, `test_embed_adapter.py`, `test_projections_chunking.py`,
  `test_projections_graph.py`, `test_projections_search.py`, `test_projections_rebuild.py`,
  `test_projections_single_writer.py`, plus additions to `conftest.py` and `test_config.py`
- the story spec

**Explicitly out of scope:**

- Story 1.9's work — `server/meetingminer/api/events.py`, `api/meetings.py`, `api/main.py`,
  `api/jobs.py`, the whole `web/` tree, and the `web-test` Makefile wiring. Committed before this
  range.
- `server/meetingminer/domain/jobs.py` — the shared `evidence_complete` / `EVIDENCE_STAGES`
  contract. Both stories specified it identically; story 1.9 committed it in `848db81`. It is *not*
  in this range and is not this story's to defend.
- `server/meetingminer/pipeline/stages/**` — evidence computation, settled by stories 1.3–1.6.
- Anything already recorded in the spec frontmatter's `deferred:` list (7 items) or in
  `_bmad-output/implementation-artifacts/deferred-work.md`. Confirming one is real is useful;
  reporting it as a new finding is not.
- No API route, UI, `/search`, or `/chat` endpoint — those are Epic 3 reading these stores.

## Design decisions to attack

The planner is not a neutral judge of its own calls. These are the choices this story made; each is
stated as the decision plus the assumption under it.

1. **The trigger is "evidence-complete", not `job.status = 'done'`, and it sits *inside* the runner's
   stage loop.** Assumption: `extract` is in `STAGE_NAMES`, has no implementation, and the runner
   pauses there, so no job reaches `done` and the code after the loop is unreachable for every job in
   the system. If that reading is wrong, the trigger is in the wrong place. Also judge the claim that
   this definition stays correct unchanged once Epic 4 registers `extract`.
2. **Projection failure never fails the job.** Assumption: evidence is already durable, a store
   outage is operational, and `rebuild` recovers it. Judge whether a silently-unprojected meeting is
   an acceptable outcome given nothing but a log line reports it.
3. **`_maybe_project` is called at three settle points per pass, guarded by the
   `meeting_projection` row plus a per-pass attempted-set.** Assumption: the guard makes repeat calls
   free and the whole thing idempotent across restarts.
4. **Graph naming (the spine deferred this to build).** Nodes `Meeting`, `Moment`, `Screen`,
   `Screenshot`, `Participant`, `Chunk`; edges `HAS_MOMENT`, `SHOWS`, `OF_SCREEN`, `SHOWN_DURING`,
   `ATTENDED`, `SPOKE_IN`, `COVERS`. Assumption: `Screen` is cross-meeting and must never be deleted
   by a per-meeting pass, which is what makes screen lineage traversable. Judge whether the asymmetry
   is handled correctly everywhere, and whether these names serve Epic 3's traversal templates.
5. **Two Meilisearch indexes, not one** — `moments` (citation-shaped, one document per moment) and
   `chunks` (retrieval-shaped, ~1,400-char turn-packed). Assumption: a citation must resolve to a
   moment while retrieval quality was measured at chunk granularity.
6. **The structural/embedding split is a hard boundary rather than an optimization.** Assumption:
   BM25-only is *fully functional*, not degraded, on the dominant query shape, so an ingest that
   cannot reach the model host should still complete.
7. **A `userProvided` Meilisearch embedder is declared and structural documents write
   `_vectors.default: null`.** Assumption: this is the documented opt-out and does not count as a
   store-native auto-embedder under AD-4. Judge that reading.
8. **Field boosts are expressed as `searchable_attributes` ordering.** Assumption: Meilisearch has no
   per-field weight and the `attribute` ranking rule makes the ordered list the boost — therefore the
   spec's *Ask First* clause did not fire. If that is wrong, the clause should have fired.
9. **A Postgres advisory lock guards `rebuild` against the live worker**, and every projection entry
   point takes it. Assumption: broader mutual exclusion is safer than the asymmetric lock the spec
   described. Note the consequence: a worker projection during a rebuild is refused and logged with a
   "run `rebuild --meeting <id>`" hint that is misleading in exactly that case.
10. **`--all` is now a required opt-in for the corpus-wide destructive run** (a bare `rebuild` is a
    usage refusal). This changed during review; judge whether it is the right ergonomics.
11. **The `meilisearch` client floor was raised to `>=0.43`** — the tested version — rather than
    researching the release each used API actually landed in. Deliberate; judge it.
12. **The publish gate is built and tested with no artifact table and no production caller**, because
    AD-4 requires it from day one. Judge whether shipping an uncalled contract is right, and whether
    `project_artifact(client=None)` returning a document while writing nothing is a safe default.

## History you need to tell a regression from a pre-existing condition

- **Story 1.9 was built concurrently in the same working tree.** `config.yaml`, `config.py`, and
  `test_config.py` carry both stories' additions. Story 1.9 committed its portions first; this commit
  adds only the `projections:` / `ProjectionsConfig` portions on top. If a hunk in those three files
  looks unrelated to projections, it is 1.9's and already committed.
- **`config.yaml`'s `embedder.model` was corrected from `qwen3-embedding` to
  `qwen3-embedding:0.6b`.** The untagged name resolves to a nonexistent `:latest` and 404'd every
  embedding pass. The value was unused before this story, so this is a latent bug fixed, not a model
  choice.
- **The development Postgres database was destroyed during this run** by a `docker compose down -v`
  (that flag removes every named volume, including `postgres-data`). All 23 ingested meetings were
  lost and rebuilt from the source drops, which are the immutable recovery root. The corpus is now 28
  meetings with different meeting ids than any earlier artifact records. Any figure in an older
  document that says 23 meetings or 1687 moments predates this. ~3.6 GB of orphaned media under
  retired meeting ids is still on disk.
- **Two tests fail at the baseline and are not this story's**:
  `test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error` and
  `test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields`. Both were
  reproduced in a clean worktree at `89a1a0b`.
- **A prior review pass already happened on this code.** Four layers produced 26 findings, all
  applied in place before the commit; the `## Review Triage Log` in the spec lists them. Writing the
  missing embedder-adapter tests uncovered a real bug (a non-numeric vector component escaping as a
  bare `ValueError`), which is fixed. Re-finding a triaged item is fine, but the log tells you what
  was already considered.

## Verification baseline

So that a skip or a failure during your review reads as a finding rather than noise, this is the
current state, each command run and its output read:

- `cd server && uv run pytest tests/ -q` → **681 passed, 2 failed** (the two baseline failures above).
- `cd server && uv run pytest tests/test_embed_adapter.py -q` → 21 passed.
- `cd server && uv run pytest tests/ -k projections -q` → 60 passed, zero skips, against live
  Neo4j 2026.07 and Meilisearch 1.53 (measured before the review patches added more).
- `make -f infra/Makefile rebuild` → 28 meetings; structural 28, embedded 28, failed 0.
- Store state agrees across all three: Postgres 28 meetings / 1473 moments / 28 `meeting_projection`
  rows / 0 failed jobs; Neo4j 28 Meeting / 1473 Moment / 1012 Chunk / 512 Screen / 617 Screenshot /
  51 Participant, all seven edge types; Meilisearch 1473 moment + 1012 chunk documents.

Two caveats about running these yourself:

- **`cd server && uv run rebuild --all` fails** — config and `.env` resolve relative to the working
  directory. `make -f infra/Makefile rebuild` is the working entry point. The spec's `## Verification`
  section still lists the broken form; that is a fair finding.
- **The store-backed tests write to the developer's real Neo4j and Meilisearch**, and the
  `meeting_projection` guard then stops the worker restoring what they erase. If you run them, run
  `make -f infra/Makefile rebuild` afterwards or you will leave the corpus unsearchable. Test runs
  also contend on the single fixed `meetingminer_test` database — a concurrent run corrupts both.
  Both are recorded deferred items.

## Required output

Write your findings to:

`_bmad-output/implementation-artifacts/review-story-1-7-2026-08-19.md`

Structure each finding as: location (`file:line`), what is wrong, why it matters (the concrete
failure, not a principle), and what the fix would need to do. Group by severity. Separate findings
about shipped behavior from findings about test coverage.

**Report findings; do not apply fixes.** Leave the working tree clean.
