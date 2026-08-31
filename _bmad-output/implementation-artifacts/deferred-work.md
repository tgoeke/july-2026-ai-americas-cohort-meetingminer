# Deferred Work

## Deferred from: story 11-4 build (lint and type tooling, 2026-08-30)

The dated ruff/mypy baseline in `server/pyproject.toml` is debt by design:
story 11.4's contract forbade editing any existing source or test file, so
every violation live on main at measurement went into a committed ignore
instead of a sweep. Each item below retires part of it; retiring an entry
also edits the pinned sets in `server/tests/test_lint_contract.py`.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Retire ruff I001 from the global ignore — sort/format the import blocks per module (69 hits at measurement), then drop the code from `[tool.ruff.lint] ignore` and from BASELINE_GLOBAL_IGNORE in test_lint_contract.py.
  evidence: Measured 2026-08-30 at ruff 0.16.5 on main (5cdfce7); mechanical and auto-fixable (`ruff check --select I001 --fix`), deferred only by the no-sweep constraint while five other branches were in flight.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Retire ruff UP035 (deprecated typing aliases, 50 hits) the same per-module way.
  evidence: Same 2026-08-30 measurement; auto-fixable modernization, no behavior change.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Retire ruff PLW1510 (`subprocess.run` without explicit `check=`, 33 hits) — each fix is a one-argument edit but wants a per-call decision about which failures should raise.
  evidence: Same 2026-08-30 measurement; most hits are in tests and the Makefile-process suites.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Retire ruff UP017 (`timezone.utc` for `datetime.UTC`, 30 hits in 11 files) — auto-fixable alias modernization.
  evidence: Surfaced only by the committed config: `requires-python = ">=3.12,<3.13"` sets ruff's target-version to py312, which the story's `--isolated` baseline run did not reach; added to the global ignore as the seventh dated code during the 11-4 build.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Retire ruff SIM117 (nested `with` statements, 17 hits) per module.
  evidence: Same 2026-08-30 measurement; auto-fixable joins of adjacent context managers.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Retire ruff RUF100 (unused noqa directives, 14 hits) — delete the dead directives.
  evidence: Same 2026-08-30 measurement; several guard codes for tools no longer configured.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Retire ruff UP037 (quoted annotations, 12 hits) per module.
  evidence: Same 2026-08-30 measurement; auto-fixable under `from __future__ import annotations`.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Retire the 49-pair `[tool.ruff.lint.per-file-ignores]` baseline entry by entry — fix a file, delete its line; a new file is exempt only from the seven globally ignored codes, since this table names existing files alone.
  evidence: 49 file-code pairs across 38 files at the 2026-08-30 measurement; test_lint_contract.py fails when an entry names a file that no longer exists, so the table cannot rot silently.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Raise mypy strictness per module (disallow_untyped_defs and friends as `[[tool.mypy.overrides]]` blocks) and widen the scope beyond the 13 decision-core files once adapters and api modules type-check.
  evidence: Story 11.4 scoped `[tool.mypy] files` to the architecture's database-free, model-free decision cores with check_untyped_defs only — green at mypy 2.3.1; anything stricter or wider was outside the no-sweep contract.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Add `types-jsonschema` to the dev group and drop the jsonschema `ignore_missing_imports` override.
  evidence: The override exists only because adding a stub package would have exceeded 11-4's named dev-group edit (ruff and mypy exactly); a one-line dep retires it.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Refresh two comments that now under-describe the fast loop: `server/tests/test_compose_contract.py:286-293` (the block above TEST_FAST_PREREQUISITES still says "the client check and the three store-free suites") and the `test-fast` comment block in `infra/Makefile` (same phrase).
  evidence: Story 11.4's footprint permitted only test_compose_contract.py lines 294-308 and the two Makefile edit sites (11-2 and the wave rules own the surrounding regions), so the prose was left stale deliberately; the contract tests, not these comments, pin the behavior.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Add `lint typecheck` to the full gate's `test:` prerequisite line (infra/Makefile:278), plus a dry-run assertion that `make -n test` prints a ruff and a mypy command — today the gate passes with a lint error present, and the loop is a strict superset of the gate for the first time. Severity: medium.
  evidence: 2026-08-30 review pass on story 11.4. The footprint permitted only the `test-fast:` rule line, so `make test` — the documented only gate, with no CI — gained neither target; a gate-only merge that lands a violation on main would break `make test-fast` in every other worktree.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`
  summary: Add `lint` and `typecheck` to `.PHONY` in infra/Makefile; a file or directory named `lint` or `typecheck` under `infra/` would satisfy either target silently. One-word fix at integration.
  evidence: 2026-08-30 review pass on story 11.4. The footprint forbade the `.PHONY` line ("No `.PHONY`/`help`/other Makefile lines").


## Deferred from: code review of spec-4-3-per-moment-approval-publishing.md (2026-08-21)

- source_spec: `_bmad-output/implementation-artifacts/spec-4-3-per-moment-approval-publishing.md`
  summary: Story 4-1a can duplicate one decision as both an ADR and an action item at the same moment anchor; deduplicate upstream before Story 4.4 makes both artifacts citable.
  evidence: The first authorized extraction run recorded `A9` and `D4` at 2736 seconds with near-identical contract-value titles (`sprint-notes.md:201-230`). Story 4.3 correctly publishes every `extracted` artifact under a moment, so it would publish both; the source is whole-transcript extraction's independent per-kind passes, not this story's approval code.

- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-graph-traversal-templates.md`
  summary: Make the projection-lock timeout test robust under a concurrent suite holding the shared lock.
  evidence: 2026-08-20, story 3.2's full-suite run — `test_projection_lock_times_out_with_holder_details_then_releases` failed mid-run while story 2-3's suite held the cross-worktree projection lock, then passed on re-run after that suite exited. The e567d1e fix removed the timed-hold race but the test still manipulates the real endpoint-keyed shared lock, so a concurrent holder from another worktree makes its holder queue and its metadata assertions see the wrong holder. Likely fix: point the test at its own lock via an env override for the lock key/path instead of the shared one.

- source_spec: `_bmad-output/implementation-artifacts/spec-2-1b-review-remediation.md`
  summary: RESOLVED 2026-08-20 (main `e567d1e`) — the lock-timeout test's holder now holds until the parent releases it instead of sleeping a fixed 1.0s.
  evidence: `test_projection_lock_times_out_with_holder_details_then_releases` lost the race whenever the waiter's ~0.9s conftest import outlasted the timed hold; with the dev stack running it failed even solo. The release-file design removes the timing dependence; verified 3x solo plus the full file green on the machine where it failed.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-one-command-development-environment.md`
  summary: Validate that llm role model/fallback strings in config.yaml resolve to declared providers at startup.
  evidence: Review found a typo in a model/provider binding passes config validation and only fails at first LLM call; proper validation belongs to the adapters implementation (stories 1.2+).

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-one-command-development-environment.md`
  summary: Add server-side lint/type tooling (ruff, optionally mypy) with a make target.
  evidence: Review found .gitignore anticipates .ruff_cache/.mypy_cache but no tooling is declared or configured; web has oxlint, server has nothing.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-one-command-development-environment.md`
  summary: Add a quickstart section (make bootstrap / make up / make test) to the root README.
  evidence: Review found the story's entry commands are discoverable only via make help; the existing root README predates the scaffold.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-source-drop-intake-endpoint.md`
  summary: Add migration drift detection — checksums for applied files, plus out-of-order and schema-ahead-of-code checks.
  evidence: Review found schema_migrations records only filenames, so editing an applied migration, inserting a lower-numbered file, or booting old code against a newer schema all go undetected; matters once more than one contributor or deployment exists.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-source-drop-intake-endpoint.md`
  summary: IMPLEMENTED by story `2-7-parallel-safe-store-backed-tests` — pending final review and merge, server suites safely overlap on shared stores.
  evidence: Each pytest run owns distinct Postgres databases from creation through teardown with a session advisory lock; `make test-db-prune` takes that same candidate lock before it drops, so it skips an owned database even during the no-target-backend startup window and removes abandoned idle ones. Neo4j Community remains one database and AD-4 fixes Meilisearch index names, so projection tests serialize through a temp-dir file lock keyed by their endpoints. The wait is bounded and reports the lock path and holder metadata; a separate Meilisearch index prefix is neither needed nor permitted by AD-4. `make evals-run` remains serial because it reads the shared corpus/stores and writes an immutable run folder.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-10-development-environment-hardening.md`
  summary: Ship docs/source-drop.schema.json as package data instead of resolving it from the config file's parent directory.
  evidence: Review found the docs_root() anchor forces any relocated MM_CONFIG_PATH to relocate docs/ too (visible as the symlink workaround in the migration tests), while migrations were deliberately moved into the package so they ship with the wheel; the schema is a second, path-fragile mechanism for the same problem. The single-anchor design was a deliberate spec choice, so revisit when non-editable installs become real.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-10-development-environment-hardening.md`
  summary: Detect drift between the committed TS client and the live OpenAPI schema (regenerate and diff when the api is reachable).
  evidence: Review found committing web/src/client/ removes the fresh-clone failure but adds a staleness risk with no detector; the original finding 23 suggested make client plus a diff check, which needs a running api and so needs a gating decision.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-10-development-environment-hardening.md`
  summary: Emit the MM_CONTENT_ROOT warning through structured JSON logging, once, rather than a bare stderr print on every load_config().
  evidence: Review found config.py prints a plain-text warning while the worker emits JSON events the Makefile readiness poll greps; make api prints it twice (preflight plus reloader) and every make migrate prints it, so it is both unparseable by the tooling and noisy.


- source_spec: `_bmad-output/implementation-artifacts/spec-1-10-development-environment-hardening.md`
  summary: Test-suite hygiene — move REPO_ROOT out of conftest into a normal module, mark the slow orchestration suite so the fast suite stays fast, and collapse the duplicate _make/_run_make helpers.
  evidence: Review found five test modules import conftest by name relying on pytest sys.path insertion, and test_makefile_procs.py is a 728-line process-spawning suite with 60-180s timeouts that always runs, unlike the DB tests which skip with a named reason.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-10-development-environment-hardening.md`
  summary: Validate docs/source-drop.schema.json against its metaschema (Draft202012Validator.check_schema) at API startup.
  evidence: Independent code review found a syntactically valid but structurally invalid JSON Schema bypasses the startup error path and fails at first intake instead of as a named startup failure; pre-existing since story 1.2.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-9-ingestion-progress-in-the-ui.md`
  summary: Bound the meetings list and the job-event stream — pagination on GET /meetings, and an updated_at watermark instead of a full job x job_stage re-read per tick.
  evidence: Review found neither query carries a WHERE, LIMIT, or OFFSET, while the module docstring and the spec's Design Notes both cite the job_stage.updated_at trigger (migration 0002) as what makes cheap change detection possible. Cost grows with total ingests rather than with in-flight ones, and every reconnect re-fetches the whole list. The spec scoped this out explicitly as a single-user-machine decision, so it is a scale deferral rather than a defect.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-9-ingestion-progress-in-the-ui.md`
  summary: RESOLVED by stories 2.2 and 2.3 — the evidence_complete gate is enforced server-side on every meeting-scoped evidence read.
  evidence: Story 2.2 discharged the moment routes (`GET /meetings/{id}/moments`, `GET /moments/{id}`) and story 2.3 the meeting-detail half (`GET /meetings/{id}/drilldown`): all three read `projections.evidence.meeting_evidence_complete` under REPEATABLE READ, header-first (404) → gate (409 `meeting-not-viewable`) → payload, in `server/meetingminer/api/moments.py`. Story 2.3 additionally enriched the 409 with `augmenting`/`jobStatus` extensions so the empty state can tell an augmentation from a first ingest (AD-14).

- source_spec: `_bmad-output/implementation-artifacts/spec-1-9-ingestion-progress-in-the-ui.md`
  summary: Give the browser a heartbeat timeout so a half-open job-event stream is distinguishable from a healthy idle one.
  evidence: useJobEvents marks the connection live on any received frame but arms no timer, so a connection where no bytes arrive and no error is raised leaves the header reading live forever while the list silently stops updating. The server emits a heartbeat precisely to make this detectable; the client does not yet act on its absence.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-9-ingestion-progress-in-the-ui.md`
  summary: Type the SSE payload from the generated client instead of by hand once openapi-ts reads OpenAPI 3.2 itemSchema.
  evidence: StreamJobEventsResponses is `{ 200: unknown }`, so the three wire names exist as two independent sources of truth — EVENT_STAGE/EVENT_DONE/EVENT_ERROR in events.py and WIRE_EVENT_NAMES in useJobEvents.ts — reconciled only by a hand-written isJobEvent guard. Nothing fails if they drift.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-12-late-recording-augmentation.md`
  summary: CLOSED by story 1.13 — `pull_transcript/emit-drop.js` emits augmenting drops under `--re-emit`.
  evidence: The blocker was drop identity: a re-pull resolves to the same `<date>-<title-slug>-<sha1(sourceId)[0:8]>` directory and `emitDrop` returns `{status: 'exists'}`. Story 1.13 kept that identity and added a sequence discriminator beside it — `--re-emit` writes a new sibling drop at `<name>-002`, `-003`, … carrying `schemaVersion: 2` and `augments`, and reports `current` when the newest drop already carries everything the pass would bring — the same test intake applies, so the puller never finalizes a drop the door would refuse. The 28 finalized drops are never renamed, rewritten or deleted, and emit order stays recoverable from the drops folder by lexical sort within an occurrence's prefix.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-13-drops-carry-the-participant-graph.md`
  summary: Decide how a participant identity migrates incrementally — today a partial `--re-emit` pass splits one human across a `name:` and a `mail:` participant row with nothing linking them.
  evidence: `--re-emit` is opt-in per occurrence, so the same person is `mail:avery.reed@corp.com` in a re-emitted meeting and `name:avery reed` in one left alone. `align` resolves through `participant_alias` by `alias_key` and nothing writes an alias automatically, so those are two unrelated `participant` rows and the participants -> meetings -> topics -> moments traversal returns half that person's meetings. Story 1.13's mitigation is operational — the migration is one `--all --re-emit` pass over 28 occurrences and every pass reports how many prefixes are still on the old contract — because the structural fix (`align` writing a `name:` -> mail-keyed-participant alias when the graph first supplies a mail for a name it has already seen) gives the worker write access to a table AD-5 assigns to the API. That is an AD-5 amendment, not an implementation choice, and it is the real fix if identity ever has to migrate incrementally rather than in one pass. State 2026-08-19: the one-pass migration HAS NOW BEEN RUN and this entry's failure mode did not occur, because the pass covered all 28 occurrences at once. Participants linked to a meeting are 47 `mail:`-keyed and 3 `name:`-keyed (Morgan Hayes, Taylor Brooks, Riley Parker — transcript speakers the org chart did not resolve, which is the designed fallback), and 48 superseded `name:`-keyed rows are now orphaned with no meeting link. Whether those orphans should be reaped or aliased to their mail-keyed counterparts is the remaining open question here. Historical record of the state before the pass: All 28 finalized drops carry `schemaVersion: 1` with the `participants` array omitted, none declares `augments`, and no occurrence prefix has a `-002` sibling — so no `--re-emit` pass has run against any occurrence. All 28 have nonetheless ingested (28 meetings, 28 jobs, 8 with a recording), and every one of the 51 `participant` rows is `name:`-keyed with zero `mail:`-keyed rows. The corpus is therefore internally consistent — a uniform old-contract corpus splits nobody, because the split this entry describes needs a PARTIAL pass — but it is consistent on the key the SPEC calls the fallback rather than the default: no directory mail address, no reporting chain, and two same-named humans would collapse into one row. Running `--all --re-emit` and re-ingesting is the operational task that closes it; running it over only some occurrences is the one way to make things worse than they are now.

- source_spec: `_bmad-output/implementation-artifacts/spec-2-1-media-streaming-replay-foundation.md`
  summary: FILED as story `2-1a-evidence-paths-anchored-to-configured-roots` — give the recording a row carrying a drop-relative path, the way transcript_source already does for the transcript.
  evidence: The schema already distinguishes the two cases and documents the distinction in migration 0005 — `transcript_source.content_path` for material the pipeline produced (relative to MM_CONTENT_ROOT) and `transcript_source.drop_relative_path` for material that arrived in the drop (relative to the drop directory), alongside `sha256` and `byte_size` so a re-ingest can prove whether the input changed. The transcript is drop-resident and is recorded that way. The recording is drop-resident and is recorded nowhere: no table has a row per recording, so story 2.1's route resolves it as `job.drop_path` (data) plus `RECORDING_FILENAME` (a Python constant in domain/drops.py). Half the path is in the database and half is hardcoded. AD-3 is therefore less violated than first written up: the architecture's actual position across the schema is content-root-relative for derived material and drop-relative for arriving material, and the recording is the one arriving artifact that got neither. Two consequences follow. `job.drop_path` is absolute (intake requires it, api/ingests.py:133), so moving the drops folder breaks replay for every ingested meeting while frames and screenshots survive — which is the failure AD-3 exists to prevent. And there is no recorded sha256 for the recording, so a swapped recording is undetectable where a swapped transcript is not. The fix is to follow the existing convention rather than to copy multi-GB files under the content root. Resolved 2026-08-19: AD-3 was underspecified rather than violated, and both halves are now settled. The contract half is done — AD-3 is retitled "relative to one of two roots", names MM_DROPS_ROOT and MM_CONTENT_ROOT, states the arrived-versus-produced anchor rule and points at the new `_bmad-output/specs/spec-meetingminer/storage-layout.md` companion (commits 01c8dfd, ecdbb61, both on main). The code half is story 2.1a, which adds MM_DROPS_ROOT, replaces the absolute `job.drop_path` with a drops-root-relative path, gives meeting_media a drop_relative_path and sha256, and backfills the existing absolute rows. The earlier reading — copy the recording under the content root, filed as `spec-2-1-recording-under-the-content-root.md` — was WITHDRAWN: it fixes replay only and leaves transcript re-parse and the augmentation door still resolving through an absolute path, for the price of a permanent duplicate of a permanent file (19.5 GB across the measured corpus). That spec was never merged to main and its branch is deleted, so the copy-versus-hard-link trade it escalated is moot — nothing is copied.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-13-drops-carry-the-participant-graph.md`
  summary: DONE (46/46 merged, 2026-08-21) — story `2-4-participant-curation` built the merge endpoint; the user drove the remaining 45 merges through `POST /participants/{id}/merge` after the API restart onto merged code. Verified live: 46 rows carry `mergedIntoParticipantId`, 0 chained aliases. Six `name:`-keyed rows remain unaliased and correctly so: the 2 mononyms below plus 4 post-pass orphans (`Taylor Brooks`, `Morgan Hayes`, `Riley Parker`, `Peyton Blake`) with no directory counterpart — see sprint-notes.md under 2-4.
  evidence: After the 2026-08-19 backfill every meeting resolves through the participant graph, leaving 48 `name:`-keyed rows with no `meeting_participant` link. They are inert today but not worthless: `align._resolve_participants` consults `participant_alias` FIRST and unconditionally, so an alias is what stops a legacy drop re-ingested without a graph from silently re-minting all 48. That is the table's stated purpose — its docstring frames an alias as recording a merge a human performed in Epic 2. Measured mapping: 46 of the 48 map 1:1 to a live `mail:`-keyed row by `normalized_name` with no contention (no two orphans compete for one target); the remaining 2 are `name:venkatmylavarapu` and `name:saitejaswi`, mononym Teams display names with no directory counterpart, which must stay unaliased rather than be force-matched. The same-name hazard the mail key exists to prevent does NOT apply here, because a `name:` alias is only ever consulted when the graph supplied no mail for that speaker. Not done by hand: AD-5 assigns `participant_alias` writes to the API and no such path exists yet — building it IS story 2.4, and `participant_alias` held 0 rows before this story, so this is its first use and a design moment rather than a cleanup.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-source-drop-intake-endpoint.md`
  summary: FILED as story `2-6-source-drop-schema-reloaded-on-change` — the api loads `docs/source-drop.schema.json` once at startup and caches it, so a schema change never reaches a running api.
  evidence: Found in operation 2026-08-19, not by review. The api had been up since 08:07; story 1.13 committed the v1-to-v2 schema at 14:42. Every one of the 28 augmenting drops was refused `422 invalid-drop` — "Additional properties are not allowed ('augments' was unexpected); schemaVersion: 1 was expected" — against a schema file that had accepted version 2 for six hours. `load_drop_schema()` caches into a module global at startup and uvicorn `--reload` watches `.py` only, so nothing invalidates it. Restarting the api accepted all 28 unchanged. Nothing was lost because drops are write-once, but the failure presents as a bad drop when the fault is a stale process, which is the expensive kind of wrong. Minimum fix is a startup log line naming the loaded schema version and its mtime; the fuller fix is reloading on mtime change or failing closed when the file is newer than the load. Compounds the existing `docs_root()` item above: the schema is resolved from the config file's parent directory, so which copy got loaded is already environment-dependent.

- source_spec: `_bmad-output/implementation-artifacts/spec-2-1b-bring-your-own-recording-drops.md`
  summary: AFTER 2.1b lands — import the recordings sitting on the NAS that the ingested corpus does not have. User decision 2026-08-19: wait for 2.1b, then bring them over.
  evidence: The NAS working copy at `/Volumes/nvmepool/mm_current/pull_transcript` carries a `Recordings and Transcripts/` tree of 77 mp4 pulled from the VMS team SharePoint site, a different source from the personal-OneDrive recaps that produced the 28 drops. Matching it against the transcript-only drops by recording timestamp and then by exact filename recovers a recording for 9 of them, which augment their meetings in place under AD-14 and retire the transitional source deep link. The other 68 are a second corpus and a scope decision, not a backfill. Neither can proceed today: no tool mints a drop from a loose video file, which is exactly what 2.1b builds. Also present and never ingested: the two NDA demo recordings under `Functional Demo Transcripts - R2C` dated 6.23.2026, which `corpus-facts.md` names the primary capture-eval assets. CORRECTION 2026-08-20: these do NOT replace the eval fixtures' placeholder `source_id`s — verified against `evals/ground-truth/*.yaml` and `eval-design.md` §1, the placeholders await the SCRIPTED meetings (demo-001 orders-ui-demo, demo-002 q3-architecture-review), which are `not-yet-recorded`: hosting and recording them on the corp tenant is a human task no import can satisfy. The NDA demos' value is capture-measurement on the real corpus.

- source_spec: `_bmad-output/implementation-artifacts/spec-2-1a-evidence-paths-anchored-to-configured-roots.md`
  summary: Retire the `job.drop_path` column once no deployment still carries un-backfilled rows.
  evidence: Migration 0008 keeps the column and lifts its NOT NULL rather than dropping it, because the backfill (`make backfill-drop-paths`) has to read the pre-2.1a absolute value and a migration cannot run between two migrations. Every writer since 2.1a leaves it NULL, and `job_has_a_drop` CHECKs that exactly one anchor is set. The follow-up is one migration dropping the column and the CHECK, safe as soon as `SELECT count(*) FROM job WHERE drop_relative_path IS NULL` is zero.

- source_spec: `_bmad-output/implementation-artifacts/spec-2-1a-evidence-paths-anchored-to-configured-roots.md`
  summary: Point the puller's drop output at `MM_DROPS_ROOT` explicitly, rather than relying on the operator to keep the two in step.
  evidence: `pull_transcript/emit-drop.js` finalizes drops into its own configured output directory and POSTs the absolute path, and the intake wire contract deliberately did not change. Intake now refuses a drop that is not under `MM_DROPS_ROOT`, so a puller writing anywhere else fails at the door with a clear 400 naming both paths — correct behaviour, but the two settings are only related by an operator remembering it.
## Deferred from: code review of spec-5-5-eval-runbook-documented-only-designs.md (2026-08-20)

- `evals/README.md:148` says a failed job leaves a row and re-ingestion creates another subject, but `POST /ingests` re-queues an all-failed source ID in place. This pre-existing reference-documentation error is outside Story 5.5’s pointer-only README edit.

## Deferred from: work-laptop puller package (2026-08-20)

- The tracked puller cannot produce participants at all. `pull_transcript/grab-teams-transcript.js` in this repo has no org-chart code (0 references); the participant graph is produced by `grab-org-chart.js`, which exists only in the summariser-lineage copy (`/Volumes/nvmepool/mm_current/pull_transcript/`) and is spawned there as a child process after `ctx.close()`. Any drop emitted from the repo copy alone therefore omits `participants`, which contradicts the SPEC constraint that the drop must carry the participant graph the puller already resolved. `tools/puller-package/build.sh` works around this by packaging the two files side by side and having the operator run them in sequence; it does not fix the repo copy. Reunifying the lineages was left out of scope by story 4-1a — this is the second load-bearing consequence of that split (the first was the summariser docs the adopt path needs).
- `grab-org-chart.js` launches a browser and creates `.transcript-profile` in the working directory even for `--help`. Found by smoke-testing the assembled package: the staged directory acquired a browser profile from a help run. The build script now audits the tarball for it, but a tool that touches the profile on `--help` is worth fixing at the source.

## Deferred from: story 3-3 cited Q&A (2026-08-20, landed)

- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-cited-qa-citation-gate.md`
  summary: Person-scoped retrieval unions the traversal and search legs rather than intersecting them, so a question about one person can cite moments that person was not in.
  evidence: The search leg is called with no filter arguments, so up to `api.chat.retrieval_limit` unfiltered hits are unioned with the traversal rows in `server/meetingminer/api/chat.py` and every one of them is citable. The dispatch note carried from sprint-notes recommended decomposing "where was Jordan confused" as participant traversal INTERSECT semantic search rather than relying on ranking to surface the right person. The story's design note argues the union buys a non-empty retrieval when classification is wrong. The one-line enabler — adding `speakers` to the moments index `filterable_attributes` — also requires a full re-projection, which is why it was not taken mid-story; that makes this a `make rebuild`-gated change, not a code-only one.

- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-cited-qa-citation-gate.md`
  summary: RESOLVED 2026-08-20 (main `f8d74de`) — the committed TypeScript client now carries the `askCorpus` operation and the `/chat` types.
  evidence: The story deferred `make client` because it generates from whatever api answers on the fixed port :8000 and its identity check cannot distinguish this worktree's api from another agent's. Run at integration instead, on the shared tree with only one api process, after restarting it onto merged code. Regeneration was additions only. Story 3.4 has the types it needs. The underlying staleness *detector* (story 1.10's deferred item) is still absent — `make check-client` asserts only that the three `.gen.ts` files exist, so it stayed silent on a client that predated the route.

- source_spec: `_bmad-output/implementation-artifacts/spec-4-1a-whole-transcript-extraction.md`
  summary: Nothing verifies that a configured model tag is actually served by the endpoint it resolves to. Found 2026-08-20 when `ollama/qwen3:32b` — the fallback for all three `llm.roles` — turned out to exist on neither `providers.ollama.base_url` nor the extraction role's `base_url`. The tag was fixed to `ollama/qwen3:30b`; the missing check is not.
  evidence: `server/tests/test_extraction_core.py:872` (`test_the_committed_extraction_binding_reaches_no_paid_provider`) asserts the committed binding as a *property* — both models `ollama/`-prefixed, host private, `num_ctx` and `timeout_seconds` above floors. That is deliberate, and the docstring says why: literal host strings make a suite that goes red on a clone behind a different network, which people learn to ignore. The consequence is that the assertion set is satisfied by any well-formed tag, served or not, so a fallback that could only ever produce "both models failed" stayed green. A network-dependent unit test is the wrong fix for the reason already recorded there. The right shape is a `make`-level preflight — resolve each role's primary and fallback to its endpoint, `GET /api/tags`, and name any tag the endpoint does not serve — run on demand and before a worker start, not inside `pytest`. Same class as story 1.10's still-absent client staleness detector: the committed artifact is checked for existence, never for agreement with the thing it points at.

- source_spec: `_bmad-output/implementation-artifacts/review-prompt-story-3-4-2026-08-20.md`
  summary: `make check-reviews` verifies that a review report exists, never who wrote it, so a builder-dispatched same-model review passes the gate identically to an independent Codex one. Found 2026-08-20 after story 3-4 merged on a Claude-reviewed range.
  evidence: The target's own handoff prompt names the intended reviewer at line 201 ("ready to hand to the Codex `bmad-code-review` agent"), and the history carries the precedent in `0098a96` and `6c4bd43` — yet neither the builder nor integration checked provenance, because the mechanical gate went green. The fix is small and belongs in the report contract rather than in reviewer discipline: require the report to carry a reviewer/tool line in its Scope section, and have `check-reviews` assert that line is present and names a non-Claude tool. Same class as story 1.10's absent client staleness detector and the absent served-tag preflight for `llm.roles`: each asserts an artifact exists rather than that it agrees with the thing it stands for. Until the gate checks it, the integration step must read the report's Scope section by hand before merging.

- source_spec: `_bmad-output/implementation-artifacts/spec-2-7-parallel-safe-store-backed-tests-remediation.md`
  summary: `test_projection_lock_times_out_with_holder_details_then_releases` (`server/tests/test_parallel_store_safety.py:318`) assumes it is the only contender for a machine-global lock, so it fails under exactly the concurrent-worktree use story 2.7 exists to support. Hit twice on 2026-08-20 during the four-worktree wave, both times traced to another worktree's suite holding the lock.
  evidence: The lock is deliberately machine-global — `_projection_lock_paths` puts it in the system temp dir keyed by the store URLs, precisely so worktrees sharing one compose stack get mutual exclusion (`conftest.py:966-973`, and the docstring at `:1025` says a repo-relative lock "would give each worktree its own file and no mutual exclusion at all"). That design is right. The test then spawns its own holder subprocess and asserts `holder_metadata["pid"] == holder.pid` — true only when this test's holder actually owns the global lock. With another worktree holding it, the holder blocks on acquisition and `_wait_for_path(ready)` never sees readiness, or the metadata names the other process. The test is not wrong about the mechanism; it is wrong about being alone. Re-running it isolated passes (12/12 observed), which is why it reads as a flake and gets re-run rather than fixed. Fix direction: have the test acquire the real lock itself before spawning its holder, or key its holder onto a test-scoped lock path (an `MM_PROJECTION_LOCK_PATH` override) so it exercises the timeout logic without competing for the shared one. Until then, a red `test_projection_lock_times_out...` during a parallel wave is contention, not a regression — verify by re-running it isolated before investigating.

## Deferred from: code review of spec-3-4-chat-ui-with-streaming-replay-citations.md (2026-08-20)

- `web/src/features/chat/ChatPanel.tsx:60` — A re-submit aborts and clears a
  partially streamed answer without telling the user that the prior question
  was interrupted. The Story 3.4 contract already records this as a low-severity
  product UX judgment; defer it rather than silently changing interaction
  semantics during a correctness review.

## Deferred from: rebuild crash recovery (2026-08-21) — RESOLVED by story 4-4 (2026-08-21)

- source_spec: `_bmad-output/implementation-artifacts/spec-rebuild-crash-recovery.md`
  summary: `publish_gate.project_artifact` was a store-writing path that took neither the store file lock nor the Postgres advisory lock — a latent bypass of the composed exclusion domain, at the time unreachable in production.
  evidence: `publish_gate.project_artifact` (in `server/meetingminer/projections/publish_gate.py`) writes to the `artifacts` index via its `client.index(ARTIFACTS_INDEX).add_documents(...)` call whenever a non-None client is passed, with no `store_file_lock` and no `projection_lock` around it. No production caller passed a client at the time (the function's own docstring said Epic 4 wires the real client "and until it does" the branch is unreached; the only caller passing a client was `tests/test_projections_search.py`, with a fake). When a real caller arrives it must take `store_file_lock` first, then `projection_lock`, like the four entrypoints in `projections/__init__.py`. Deliberately not fixed in the crash-recovery story: the spec's Never list said record it here rather than redesign a function with no production caller.
  resolution: Story 4-4 wired the production caller as `projections.project_published_artifacts` (`server/meetingminer/projections/__init__.py`), which takes `store_file_lock` first, then `projection_lock`, like every other store-writing entrypoint; the approve route and the per-meeting projection pass both reach the artifacts index only through it. `server/tests/test_projections_locks.py` pins that a held file lock refuses the call before either store is touched.

## Deferred from: demo-001 capture recall review (2026-08-21)

- source_spec: `_bmad-output/implementation-artifacts/spec-demo-001-capture-recall.md`
  summary: `eval-design.md` §2.2 still documents the over-capture budget as `ceil(duration_minutes)`; the shipped formula is now `max(ceil(duration_minutes), expected_screenshot_count)` and the contract lives only in `evals/harness/checks.py`.
  evidence: The story changed `over_capture` in `evals/harness/checks.py` (docstring cites "eval-design §2.2's guardrail") plus its reported `budget_formula` string and tests, but `_bmad-output/specs/spec-meetingminer/eval-design.md` was outside the story's file boundary and was not amended. Doc and code now disagree on the check's formula; the doc needs the one-line update plus the short-take rationale (demo-001 ran 247s against a planned 12 minutes, making the manifest's own recall denominator exceed the minute budget).

- source_spec: `_bmad-output/implementation-artifacts/spec-demo-001-capture-recall.md`
  summary: The settled-change gate raises real-corpus capture volume ~+30% (829 → 1076 replayed offline at floor 0.03), concentrated in real-world meetings already above 1/min — measured and stated per the spec's Ask-First clause, but no owner has accepted or bounded the cadence change for the 28-meeting corpus.
  evidence: Offline replay of the 13 stored meetings during the story: +247 captures (+30%) at 0.03, +179 (+22%) at 0.04, +116 (+14%) at 0.05; 0.05 was rejected because it sits above the weakest measured real page change (0.047 on demo-001). The scripted eval meetings stay inside budget, and demo-002 drops 11 → 10 (its opening slate folds). The open decision is whether the real-corpus cadence increase is acceptable as-is, tuned (0.04 keeps demo-001 green at lower volume), or bounded by a per-meeting cap — someone must own that call before the next corpus-wide re-capture.


## Deferred from: story 4-4 review remediation (2026-08-21)

- source_spec: `_bmad-output/implementation-artifacts/spec-4-4-citable-knowledge-review-remediation.md`
  summary: Embed-only projection still opens and health-checks Neo4j even though the pass writes only Meilisearch moment and chunk vectors.
  evidence: `project_meeting_embeddings` calls `_open_stores(..., ensure_graph=False)`, but `_open_stores` still enters `neo4j_driver` and verifies connectivity before `_project_one`; therefore a Neo4j outage prevents an otherwise independent vector repair. This behavior predates Story 4-4's artifact remediation and needs a search-only store context rather than an incidental patch here.
## Deferred from: worker restart guidance (2026-08-22)

- source_spec: `_bmad-output/implementation-artifacts/spec-worker-restart-guidance.md`
  summary: `_bmad-output/specs/spec-system-status/SPEC.md:35` still justifies the "status never touches the worker" constraint with "(the paused paid backlog stays paused)" — a premise that is false twice over, and which cannot be corrected by hand-editing SPEC.md.
  evidence: The rule itself is still correct and must survive; only its parenthetical justification is stale. Extraction is bound to `ollama/gpt-oss:120b` in the committed `config.yaml:30` ("no paid provider is reachable from this file as committed") and the live database holds 0 queued jobs (32 done, 2 failed), so there is neither a paid binding nor a backlog. `SPEC.md` is a derived artifact: `.claude/skills/bmad-spec/SKILL.md:55,57` states it is "DERIVED from `.memlog.md`, never hand-edited" and that an outside hand-edit "is overwritten on the next derive". The premise is baked into `_bmad-output/specs/spec-system-status/.memlog.md:25`, so the durable fix is a `--type constraint` memlog entry plus a `bmad-spec` re-derive — deliberately out of scope for a bmad-build run, which is not that skill.

- source_spec: `_bmad-output/implementation-artifacts/spec-worker-restart-guidance.md`
  summary: The `project-context.md:29-32` policy bullet "Never restart the worker incidentally" is wrong in every clause, and the file is a managed block whose owning skill has since migrated to `AGENTS.md`.
  evidence: The bullet claims "`config.yaml` sets every `llm.roles.*.model` to `claude-sonnet-5`, and as of 2026-08-20 that backlog is ~850 calls". Committed `config.yaml` sets extraction to `ollama/gpt-oss:120b` (keyless/local) and only `chat`/`judge` to `openai/gpt-5.2` (`config.yaml:155-160`); the backlog is 0. The block header (`project-context.md:2`) says edits inside it "are replaced on refresh", and `.claude/skills/bmad-project-context/SKILL.md:90` now targets `AGENTS.md` and treats a standalone `project-context.md` as a legacy artifact to absorb. AGENTS.md has no `bmad:context` block, so the two files have hand-diverged. Durable fix is a `bmad-project-context` refresh/audit that also settles the file migration — a separate decision from this code change.

- source_spec: `_bmad-output/implementation-artifacts/spec-worker-restart-guidance.md`
  summary: Four further live artifacts still assert the paid-Anthropic worker-backlog premise, plus one historical spec.
  evidence: `_bmad-output/implementation-artifacts/spec-search-common-terms-no-video-content.md:29` lists "Restarting the worker for any reason (paused extract backlog issues paid Anthropic calls)" as an Ask-First gate — that spec reached `status: done` on main at `e6d5782` while this investigation was running, so it is now historical record rather than a live gate, but it still greps as an instruction and is listed here for that reason; `_bmad-output/implementation-artifacts/sprint-notes.md:188` cites "the ~850-call extraction backfill" and `:785` claims "`chat` and `judge` still name `claude-sonnet-5`" (they are now `openai/gpt-5.2`); `.claude/skills/integrate/ops-order.md:61-65` claims "27 real-corpus jobs still sit at `extract`" against a live 0-queued database, with the same drift mirrored at `.agents/skills/integrate/ops-order.md`; `_bmad-output/specs/spec-chat-fallback-timeout/.memlog.md:14,16` repeats the "~850 queued paid extraction calls" figure. Historical build-prompt/review-prompt/completed-spec files that record the premise as it stood are deliberately excluded — they are a record of what was true at the time, not instructions.

## Deferred from: worker restart guidance (2026-08-22) — pre-existing, unrelated — RESOLVED (2026-08-21 integrate)

- source_spec: `_bmad-output/implementation-artifacts/spec-worker-restart-guidance.md`
  summary: All 34 non-trivial tests in `server/tests/test_config.py` fail on main (the entry originally said two — that was an artefact of the `-k` filter used to check) — the inline config fixture was never extended when `pipeline.screens.settled_change_threshold` and `settled_change_frames` became required fields.
  evidence: Verified by running `uv run --project server pytest server/tests/test_config.py -k "api_stream_intervals or heartbeat_is_capped"` — 2 failed. Both raise `pydantic_core.ValidationError: 2 validation errors for Settings`, naming `pipeline.screens.settled_change_threshold` and `pipeline.screens.settled_change_frames` as `Field required [type=missing]`, surfacing as `ConfigError` at `server/meetingminer/config.py:980`. The two fields became required in `config.py` at `22af138` (the screens settled-change emit gate); `server/tests/test_config.py` builds its own inline settings dict rather than reading `config.yaml`, and that dict was not extended to match. Not caused by the worker-restart-guidance story, which touches neither `config.py`, `config.yaml`, nor `test_config.py` — surfaced incidentally when the implementation agent ran a wider suite. Note the story's own suites are unaffected: `test_api_status.py` (11) and the web status tests (5) pass.
  resolution: Fixed during the 2026-08-21 integrate run at `2fd803f`. The
  scope was wider than recorded: every test in the file builds `VALID_CONFIG`,
  so an unfiltered run failed 34 of 55, not 2. Added
  `settled_change_threshold: 0.03` and `settled_change_frames: 3` to the
  fixture's `pipeline.screens` block, matching `config.yaml:230,234` and the
  model's field order. `server/tests` is now 1663 passed / 0 failed.

## Deferred from: code review of spec-worker-restart-guidance.md (2026-08-22)

- source_spec: `_bmad-output/implementation-artifacts/spec-worker-restart-guidance.md`
  summary: `LlmRoleBinding.model` and `.fallback` accept empty or whitespace-only strings, so status can render a blank binding and the worker can reach an unusable model configuration.
  evidence: `server/meetingminer/config.py:168-169` types both fields as plain `str` / `str | None`, unlike the existing `NonEmptyText` alias used for STT and prompt fields. This predates the reviewed change and already affects every LLM role; the new worker remediation only makes the malformed value visible a second time. Fix it in the shared config contract with migration/compatibility coverage, not inside this message-only story.

- source_spec: `_bmad-output/implementation-artifacts/spec-worker-restart-guidance.md`
  summary: The `/status` module docstring still says every remediation is a `.env` or `config.yaml` edit followed by a process restart, but the stopped-worker row now reports queue and loaded-binding facts without prescribing an edit.
  evidence: `server/meetingminer/api/status.py:19-21` predates this message-only change and describes the original system-status remediation contract globally. The frozen story Code Map explicitly identifies the mismatch and routes it out of scope; update the broader status-surface documentation in its owning spec rather than silently widening this bug fix.

## Deferred from: build of spec-readme.md (2026-08-22)

- source_spec: `_bmad-output/implementation-artifacts/spec-readme.md`
  summary: `project-context.md`'s worker-restart rule states that `config.yaml` sets every `llm.roles.*.model` to `claude-sonnet-5`, which no longer matches `config.yaml`.
  evidence: `config.yaml:30` binds `extraction` to `ollama/gpt-oss:120b` and `config.yaml:155-161` binds `chat` and `judge` to `openai/gpt-5.2`; no role names an Anthropic model. The bmad:context block in `project-context.md` is marked "Verified 2026-08-20 against 2896af5" and predates the 2026-08-21 owner decision that moved the paid roles to OpenAI. That block is regenerated by `bmad-project-context`, so hand-editing it inside a README build would be overwritten on the next refresh — it needs a context refresh run, not a patch. The restart-costs-money warning itself remains true; only the model name is stale.
  resolution: Fixed in follow-up work and landed 2026-08-22. The bullet now states that starting the worker costs
  nothing, names the local `ollama/gpt-oss:120b` extraction binding and its
  `ollama/qwen3:30b` fallback, and routes the paid `openai/gpt-5.2` `chat` and
  `judge` roles to the api rather than the worker. It was hand-edited outside
  the `bmad:context` block, so a `bmad-project-context` refresh will not
  overwrite it — but the block's own "Verified 2026-08-20 against 2896af5"
  stamp is still stale and a refresh is still owed.

- source_spec: `_bmad-output/implementation-artifacts/spec-readme.md`
  summary: The repository has no `LICENSE` file, so a README that opens with `git clone` grants no usage rights.
  evidence: `git ls-files` at the repository root lists no `LICENSE`, `LICENCE`, or `COPYING`. The README now states this plainly rather than implying a license, but choosing one (or deciding the capstone stays unlicensed) is an owner decision, not a documentation edit.

- source_spec: `_bmad-output/implementation-artifacts/spec-readme.md`
  summary: The README documents a visual product — moment view, screenshot series, audio+video replay — with no screenshots, no demo clip, and no sample drop a new reader can ingest.
  evidence: `web/public/` carries no product screenshots and the repository ships no fixture recording; `make mint-drop` presumes the reader already has a suitable video or transcript on disk. Capturing demo assets means running the stack against the real corpus and deciding what is shareable (the corpus includes NDA recordings), which is outside a documentation change.

## Deferred from: open-moment-below-fold hot fix (2026-08-22)

- source_spec: none (hot fix, `b41dea4`)
  summary: The shell's child-screen placement has no regression test. `b41dea4` moved the `<Outlet />` above the persistent search/ask chrome so an opened moment is not buried below a viewport-taller result list, but nothing pins that order — a future edit can silently reintroduce "Open moment does nothing".
  evidence: `web/src/App.tsx` exports only the default `App`, which wraps `BrowserRouter`; there is no `App.test.tsx`. Covering the invariant means a new test file that mocks the whole `@/client/sdk.gen` surface (the pattern `MomentView.test.tsx:14-31` uses) plus the fetches of every child route, `CorpusStats`, `MeetingsList`, `HealthPanel`, `StatusIndicator`, `ChatPanel`, and `CorpusSearch`. That was judged too large, and too likely to land a flaky test, in the ~30 minutes before a live demo. The fix itself was verified in a real browser instead: clicking search hit #10 from scroll offset 1800 puts the moment heading at viewport top, Back restores the query and all 20 hits, and the `hidden` wrapper measures 0px on home. The precedent to copy is `spec-meeting-artifacts-below-fold`, which pinned the analogous DOM order at `MeetingMoments.test.tsx:275` and `MomentView.test.tsx:110`.


## Deferred from: puller source relocation (2026-08-22)

- source_spec: `_bmad-output/implementation-artifacts/spec-puller-source-relocation.md`
  summary: The launchd agent `com.corp.grabtranscript.index` that both puller docs promise is not installed, and the plist they describe would point at the pre-move repo path.
  evidence: `tools/puller/CLAUDE.md` ("Schedule" section) says the agent runs `index-archives.sh` daily at 08:00 and `tools/puller/README.md` gives full bootout/bootstrap/kickstart instructions against `~/Library/LaunchAgents/com.corp.grabtranscript.index.plist`. No such plist is installed and `launchctl list` shows nothing matching. The relocation made the documented working directory stale on top of that. Deciding whether the daily index should run at all — and from the archive copy rather than the repo copy — is an operator decision, not a doc edit, and it is entangled with the corp-tenant corpus being retired.

- source_spec: `_bmad-output/implementation-artifacts/spec-puller-source-relocation.md`
  summary: `index-archives.sh` and the archive fallback degrade silently when `archives.txt` is absent, which is now the normal state of the repo copy.
  evidence: `tools/puller/index-archives.sh` does `cd "$(dirname "$0")"` and reads `archives.txt` beside itself; `grab-teams-transcript.js:805` loads the same file for `tryArchiveFallback`. `archives.txt` is untracked and moved out with the working data, so in `tools/puller/` both now read nothing: the script logs a start and a finish, indexes zero folders and exits 0, and the fallback reports no candidates rather than saying the catalog is missing. Pre-existing behaviour, but the two-copy split makes the empty case ordinary instead of impossible. The fix is a named error when the catalog is absent, which belongs with whoever also settles the launchd question above.

- source_spec: `_bmad-output/implementation-artifacts/spec-puller-source-relocation.md`
  summary: `tools/puller-package/build.sh` does not ship `index-archives.sh`, so the packaged README documents a script the package omits.
  evidence: `FROM_REPO` in `build.sh` lists seven files and `index-archives.sh` is not among them, while the `README.md` it copies documents `./index-archives.sh` and the launchd schedule around it. Harmless today because the work-laptop flow in `WORK-LAPTOP.md` and `pull.sh` never invokes it, but the package is self-contradictory to anyone reading it. Pre-existing; noted here because the relocation review is what surfaced it.

## Deferred from: story 6-6 YouTube deep links (2026-08-29)

- source_spec: `_bmad-output/implementation-artifacts/spec-6-6-youtube-deep-links.md`
  summary: The `moments` stage drops `source_deep_link` once replay exists, so every YouTube meeting with a recording (all of what story 6.2 will mint) carries `sourceDeepLink: null` on `MomentDetail`, `SearchHit`, and `CitationModel`; the secondary link 6-6 renders appears only on the drill-down header until the stage retains the link beside replay.
  evidence: `server/meetingminer/worker/moments.py:295-302` writes the link only when the meeting has neither recording nor screenshots and `:385-399` nulls it on the superseded-row update. Server-side change pinned by store-backed tests in `test_worker_moments.py` and `test_augmentation.py`, both owned by in-flight 11-1, so 6-6 left it. Owed: a `docs/backlog.md` entry once 11-1 lands (11-1 rewrites the B-1 paragraph there), then a small worker story; the web side already renders the field when present and replay stays primary for non-YouTube hosts.

## Deferred from: story 11-1 seconds-fast default suite (2026-08-30, landed)

- source_spec: `_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`
  summary: README's make-target table and testing section do not describe `make test-fast`, the `slow` mark, or `-m ""`.
  evidence: The spec's file boundary excluded `README.md`; review scored it medium and deferred it. `make help`, AGENTS.md, and `project-context.md` carry the fast-loop/full-gate text; README still predates the split.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`
  summary: `docs/project-record.md` has no entry for the fast/slow split.
  evidence: Outside the spec's file boundary; review scored it low. `docs/backlog.md` records B-1 as closed by 11.1 with the measured numbers, so the record has the facts in one place but not in the project record.

- source_spec: `_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`
  summary: The fast set is ~49s of pytest (~66–71s `make test-fast`), not seconds; the residue is ~1,000 Postgres-backed api/worker tests at 20–50ms each.
  evidence: Spec residual risk (1): the cost is per-test fixture setup against the per-run Postgres database, which the story's marks do not touch. Bringing the fast loop to single-digit seconds means changing the fixture cost (a shared per-session schema, or a decision-core split), which is a story, not a mark. Not yet in `docs/backlog.md`; the spec left filing it to the owner.

## Deferred from: Story 6.3 review finding F6 (2026-08-30, owner ruling)

- source_spec: `_bmad-output/implementation-artifacts/spec-6-3-local-files-acquisition-with-transcript-dialect-conversion.md`
  summary: DEFERRED — whole-second legacy stamps can erase a speaker turn's duration. Do not amend the truncation contract and do not change the converter until the corpus establishes that this occurs in genuine Zoom exports.
  evidence: Exact input: cues at 1.100s and 1.900s. Observed: `merge_vtt_end_timings() -> (None, 2200)`. Both converted legacy starts are 1.000s, so the first turn's fallback is bounded by the following 1.000s start, producing the resulting zero-duration boundary `(start_ms, end_ms) == (1000, 1000)`; the second turn ends at 2200ms. The mechanism is preserved unchanged. Story 6.3 review adds only the named structured warning `stage.align.zero-duration-fallback`, carrying the meeting, affected turn, and both colliding stamps.
  revisit_trigger: Real Zoom exports in the new corpus showing sub-second speaker changes.

## Deferred from: Story 6.3 review finding F1 (2026-08-30, owner ruling)

- source_spec: `_bmad-output/implementation-artifacts/spec-6-3-local-files-acquisition-with-transcript-dialect-conversion.md`
  summary: DEFERRED — transcript-only identity can ignore corrected speaker attribution. Do not amend the identity contract and do not change code unless the observed trigger occurs.
  evidence: Exact reproduction: the two exports `Alice: identical words` and `Bob: identical words` produce the identical `sha256:d53bde...` identity. `transcript.vtt` sorts before `transcript.txt` in `_digest_supplied(classify_supplied(...))`, so the speaker-less artifact determines the identity; `_evidence_not_in()` cannot warn because the existing drop already carries the canonical filename. Preserve both candidate fixes for a future decision: derive identity from the operator's original supplied file, or derive a deterministic digest over both converted artifacts.
  revisit_trigger: An operator re-mints a corrected Zoom export and the system reports `exists` while keeping the old attribution.

## Deferred from: model select notices overlap (2026-08-31, one-shot review)

- source_spec: `_bmad-output/implementation-artifacts/spec-model-select-notices-overlap-the-popover.md`
  summary: In the full (non-compact) `ModelSelect`, the popover is absolutely positioned and still overlays the notices that flow beneath the trigger.
  evidence: `web/src/features/settings/ModelSelect.tsx` — with `compact === false` the notices layer is `contents` (normal flow) and the panel keeps `absolute top-full right-0 z-50`. Pre-existing; the compact ask box was the reported surface and is the only one this change re-laid out. Fixing the full view means positioning its notices too, which changes `ChatPanel.tsx:237`'s header layout.

- source_spec: `_bmad-output/implementation-artifacts/spec-model-select-notices-overlap-the-popover.md`
  summary: A model-binding write in flight is never announced — `model-select-pending` sits in no live region, and the `aria-busy` that would cover it is unmounted before the PUT is awaited.
  evidence: `aria-busy={busyBinding !== undefined}` is on the listbox, but `choose()` calls `close()` before awaiting `select()`, so the listbox is gone by the time `busyBinding` is set. Pre-existing since story 8.3. A `role="status"` on the notices layer would announce it, but it would then wrap the refusal's `role="alert"`, so the nesting needs a decision.

- source_spec: `_bmad-output/implementation-artifacts/spec-model-select-notices-overlap-the-popover.md`
  summary: Someone arrowing through the catalog never hears which binding is in force or that a stored choice was discarded — the listbox does not `aria-describedby` the source and stale notices.
  evidence: `model-select-source` and `model-select-stale` render outside `role="listbox"` and carry no ids. Pre-existing since story 8.3; both notices were outside the listbox before this change too.

- source_spec: `_bmad-output/implementation-artifacts/spec-model-select-notices-overlap-the-popover.md`
  summary: `.gitignore` has no `~$*` rule, so an Office lock file in the tree is one `git add <dir>` away from being committed.
  evidence: `docs/~$MeetingMiner-15-minute-capstone.pptx` is untracked in the working tree and matches no ignore rule. Unrelated to this change and `.gitignore` is shared, so it is not staged here.

- source_spec: `_bmad-output/implementation-artifacts/spec-moment-back-to-meeting.md`
  summary: The moment view's "Open the meeting" control is a `Button`, so there is no URL behind it — no cmd/middle-click, no open-in-new-tab, no copy-link.
  evidence: `MomentView.tsx` cannot mount a react-router `Link` because `MomentView.test.tsx` renders the component 35 times with no router, and `components/ui/button.tsx` has no `asChild` escape hatch. The project's own mockup for the sibling affordance uses an anchor (`mockups/speaker-naming.html:210`). Fixing it properly means either `asChild` on the button or an optional `meetingHref`, plus wrapping that suite.

- source_spec: `_bmad-output/implementation-artifacts/spec-moment-back-to-meeting.md`
  summary: Two hand-copied back/up affordances now share byte-identical classes with different words and different a11y — a shared component would settle it and give `SpeakerNaming`'s control the accessible name it lacks.
  evidence: `SpeakerNaming.tsx:484-492` renders `variant="ghost" size="sm" className="self-start px-0 text-muted-foreground"` reading "← Back" with no `aria-label` and no `data-testid`; `MomentView.tsx`'s new control repeats the same classes with both. Pre-existing duplication surfaced by this change, not caused by it.

- source_spec: `_bmad-output/implementation-artifacts/spec-moment-back-to-meeting.md`
  summary: Nothing moves focus or announces the change when the app navigates between screens, so a keyboard or screen-reader user is left on `document.body` and restarts from the top of the shell.
  evidence: `App.tsx` has no route announcer and no focus reset on `pathname` change — only the two `focus()` calls for the search and chat shortcuts. App-wide and pre-existing; surfaced because this change adds a control whose whole purpose is that move.

## Deferred from: Story 12.4 review findings F-03 and F-11 (2026-08-31, owner ruling)

- source_spec: `_bmad-output/implementation-artifacts/spec-12-4-extraction-documents-are-searchable.md`
  summary: DEFERRED — an extraction document's claim can reach a cited answer wearing a co-located moment's marker. Land 12.4 as reviewed; do not remove document text from the synthesis prompt. Filed as story `12-4a-document-claims-anchor-to-moments`.
  evidence: `server/meetingminer/api/chat.py` — `_read_document_context()` groups by *meeting* because the retained schema carries no claim-to-moment anchor, and `_document_block()` appends the meeting's documents to the first selected moment's block. The deterministic gate is unaffected: a document contributes no marker (`test_a_document_adds_no_marker_and_no_citable_moment`), and a document whose meeting has no retrieved moment reaches nobody (`test_a_document_whose_meeting_has_no_retrieved_moment_reaches_nobody`). What no code checks is whether the marker's moment supports a document-derived sentence — only `SYNTHESIS_PROMPT` rule 5 asks the model not to use it as support. Prompt wording and delimiter escaping cannot enforce it; the two candidate fixes are to drop document text from synthesis, or to add a deterministic claim-to-moment relation and gate on it.
  revisit_trigger: A judged answer, or a demo question, whose cited moment does not support the sentence and whose sentence traces to a document in the same meeting.

- source_spec: `_bmad-output/implementation-artifacts/spec-12-4-extraction-documents-are-searchable.md`
  summary: DEFERRED — one exact unchunked record has a finite store ceiling. Do not add a size limit, truncation, or chunking until a real document approaches it.
  evidence: The private stack's Meilisearch 1.53.1 binary reports `--http-payload-size-limit` defaulting to `100000000` bytes, Compose supplies no override, and `search._add()` batches by record count rather than bytes. Arbitrary input length, exact full text, and one unchunked record cannot all hold above that boundary; in a delete-then-add flow an oversized replacement can also erase the prior projection before it fails. Not reachable in practice: extraction documents are model outputs of tens of KB (the story's own long-document test is ~79 KB), and the 224 rows carried by the 2026-08-31 rebuild are far below it. The candidate fixes to preserve are a retained-document size limit, a configured store limit, explicit searchable-text truncation, or revised chunking/identity.
  revisit_trigger: A `document_text` in Postgres approaching the configured Meilisearch payload ceiling, or a `projection.documents` failure naming a payload-size error.
