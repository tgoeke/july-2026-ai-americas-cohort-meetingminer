# Review — story ui-4 (2026-08-21)

Reviewer: Claude (story/ui-4-review worktree)
Status: COMPLETE
Verdict: **pass-with-findings** (one low-severity test-robustness gap; two informational integrator notes; nothing blocking merge)

## Scope

- Branch under review: `story/ui-4`, single commit `7b6ae17`, branched from `52e9ca0`.
  Verified: `git merge-base story/ui-4 main` = `52e9ca0c7c0c6ac81a0249e71ef0e5017882cbb7`, and `git log 52e9ca0..story/ui-4` shows exactly one commit, `7b6ae17`.
- Contract: `_bmad-output/specs/spec-ui-reimagine/SPEC.md` (CAP-3) + companions, stories.yaml entry "4", `build-prompt-story-ui-4-2026-08-21.md`.
- Dispatch-time amendment: only `web/src/features/settings/**` may be touched.
- Code inspected read-only from the builder's worktree `../meetingminer-wt/ui-4` (clean checkout of `7b6ae17`); a merge of story/ui-4 into this review branch was denied by the permission layer, so tests were run in that worktree instead, without modifying it.

## Priority-by-priority

### 1. File boundary — PASS

`git diff --stat 52e9ca0..story/ui-4` touches exactly four files, all inside the boundary:

- `web/src/features/settings/SettingsPage.route.tsx` (+7)
- `web/src/features/settings/SettingsPage.test.tsx` (+249)
- `web/src/features/settings/SettingsPage.tsx` (+303)
- `web/src/features/settings/settings.ts` (+91)

Nothing outside `web/src/features/settings/**`. No App.tsx edit, no client hand-edits, no server files, no Makefile/config changes.

### 2. Secret discipline — PASS with one low finding (F1)

The read-only contract is real, not decorative:

- `matchSecretMarker` (settings.ts) folds case and strips `_`/`-`, then substring-matches 11 markers (`apikey`, `meili_master_key`, `password`, `secret`, `access_token`, `credential`, ...). The test runs it over **both** `JSON.stringify(fixture)` and `document.body.textContent`. I verified by inspection that adding e.g. `meiliMasterKey: '...'` to the fixture would fail the payload assertion (folded `meilimasterkey` contains the folded marker), so a secret-bearing key entering the client-side payload shape does fail the suite. The fixture is typed `ConfigResponse`, so a regenerated client that grows such a field forces the fixture to change and the marker check to see it (`tsc -b` is part of `make test`'s web build).
- No-edit-affordance assertion is real: `queryAllByRole('textbox')` and `queryAllByRole('button')` both asserted length 0 over the loaded page; the only interactive elements are `<details>/<summary>` prompt disclosures (not edit affordances) and the `/status` link. The component itself contains no input, form, or mutation call — the only network call is `getConfiguration` (GET /config).
- Change-path copy asserted on all 7 sections plus the page-level `READ_ONLY_CONTRACT` sentence.

See F1 for the one normalization gap in the rendered-document half of the check.

### 3. CAP-3 completeness vs SPEC — PASS

All SPEC/stories.yaml sections render, each inside a `Section` that states its change path via `changePath()`:

| Section | Content | Change path |
|---|---|---|
| LLM roles | per-role model/fallback/provider/endpoint/fallbackEndpoint/timeout/numCtx + **both full extraction prompt texts** (collapsed `<details>`), plus provider endpoints | api + worker restart |
| Embedder | model, dimension | api + worker restart |
| Speech, vision, and speakers | STT engine/model, OCR engine/fallback, diarizer engine | worker restart |
| Pipeline capture thresholds | frames, screens, align, moments groups | worker restart |
| API search and chat knobs | poll/heartbeat, search knobs, chat knobs | api restart |
| Projections | chunking, embedBatchSize, both index configs, synonyms | api + worker restart **+ `make rebuild`** |
| Store coordinates | postgres host:port/db+user, neo4j uri+user, meilisearch url — coordinates only, with an explicit ".env never serializes" note | api + worker restart |

The test asserts the change-path sentence appears exactly 7 times and that the projections section names `make rebuild`. The page relates to `/status` ("status is live health, this page is the declared stack") via a link rather than duplicating it, exactly as the build prompt asked.

### 4. Route registration — PASS

- `SettingsPage.route.tsx` exports `route: RouteModule { path: '/settings', element: <SettingsPage /> }`, matching the story-2.8 registry contract in `web/src/routes/registry.ts`, whose glob is `import.meta.glob('../features/**/*.route.tsx', { eager: true })` — the new file is under `features/settings/`, so it is discovered with no `App.tsx` edit (and the diff confirms none was made).
- No collision with `/status`: `StatusPage.route.tsx` declares `path: '/status'`; paths are distinct and react-router ranks by specificity, with the registry's `order` default identical for both.

### 5. Test quality / fixture fidelity — PASS

- The fixture is declared `function configFixture(): ConfigResponse` importing the type from `@/client/types.gen`. I confirmed `ConfigResponse` in the regenerated client (`web/src/client/types.gen.ts` line 199) requires exactly the fields the fixture provides (service, configVersion, llmRoles, providers, embedder, stt, ocr, diarizer, pipeline, projections, api, stores), and `getConfiguration` in `sdk.gen.ts` targets `url: '/config'`.
- `pnpm exec tsc -b` in the ui-4 worktree exits 0 — the fixture type-checks against the generated client, so its shape cannot silently diverge.
- Failure path tested (fetch rejection renders the api address and the `make api` fix); pure helpers (`matchSecretMarker`, `labelize`, `changePath`) unit-tested including the separator/casing folding.

## Verification run

Observed directly, in `/Users/devopsterus/current/cohort/meetingminer-wt/ui-4` at `7b6ae17` (clean tree):

- `make web-test`: **14 test files, 215 tests, all passed** (vitest 4.1.10, 11.3s). Store-free, per AGENTS.md.
- `pnpm exec tsc -b` in `web/`: exit 0.
- `git status --short` in that worktree before and after: clean; nothing there was modified.

## Findings

### F1 (low) — rendered-document secret check misses space-separated markers

`matchSecretMarker` folds `_` and `-` but not whitespace. The page renders key names through `labelize()`, which *inserts spaces* (`meiliMasterKey` → `meili master key`), so the rendered-document half of the secret assertion would not match multi-word markers like `apikey`/`masterkey`/`access_token` against their labelized on-page form (`"api key"`, `"master key"`). The payload-side check still catches any such key entering the endpoint shape (camelCase survives `JSON.stringify`), and single-word markers (`password`, `secret`, `credential`) are unaffected, so the endpoint contract is guarded — but the rendered-page half is weaker than it looks. One-line fix: fold `/[\s_-]/g` instead of `/[_-]/g` in `matchSecretMarker` (settings.ts line 75). Non-blocking.

### F2 (info, integrator follow-up) — /settings is not reachable from the chrome

The build prompt asked to "link it from the persistent chrome", but the dispatch-time amendment confines the diff to `web/src/features/settings/**`, and the chrome lives in `App.tsx`. The builder correctly stayed inside the boundary, so the page is currently reachable only by typing the URL (or via any future chrome link). Whoever integrates should add the nav link in the chrome-owning story or as an integration commit.

### F3 (info) — MomentView "Active extraction prompts" duplication remains, unrecorded in an artifact

The build prompt's conditional task ("move/absorb the prompts block in MomentView.tsx ... otherwise leave it and note the duplication in your report") could not be done inside the boundary — `MomentView.tsx` still carries its own prompt rendering (story 4.2 block, `web/src/features/moments/MomentView.tsx` ~lines 54–140, 382–388), now duplicated by the settings page's prompt blocks. The builder's commit message does not note it and no story-report artifact exists on the branch (the boundary also forbade writing one). Recorded here so it is not lost: the duplication is real and should be collapsed to a link post-merge.

## Not done, per instructions

- No merge performed; worker untouched; no stores used (web-test is store-free).
