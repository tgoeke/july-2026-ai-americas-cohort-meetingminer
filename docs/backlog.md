# Backlog

Work that is known, evidenced, and not yet done. Every item here was found by a
code review, an incident, or a measurement — none is speculative. Items are
grouped by what they cost you, not by which epic produced them.

Sizes are rough: **S** under a day, **M** a day or two, **L** more, or unbounded
until a decision is made.

---

## Now — these cost something every day

### B-2 · Add a LICENSE — S

There is no `LICENSE`, `LICENCE`, or `COPYING` anywhere in the tree, while the
README opens with `git clone`. Cloning grants no usage rights without one, which
matters the moment the repository is shared.

**Do:** pick a license, or record deliberately that the project is unlicensed.
This is an owner decision, not a code change.

### B-3 · Review `server/meetingminer/prune/` — S

It landed on `main` with no code review. The review gate that was in place at the
time passed vacuously — no review prompt was ever dispatched, so it had nothing
to look for — and that gate has since been removed along with the process record
it read. It is the only code in the repository that **deletes evidence**, and it
never received the review it was owed.

**Do:** review it against the merge commit, not the working tree.

### B-4 · Add server lint and type tooling — S

`.gitignore` anticipates `.ruff_cache/` and `.mypy_cache/`, but nothing is
declared or configured. The web app has a linter; the server has none.

**Do:** ruff (and optionally mypy) with a make target.

---

## Correctness — wrong answers or silent failures

### B-5 · Deduplicate an extraction that proposes one decision twice — M

Whole-transcript extraction runs independent per-kind passes, so the same
decision can be recorded as both a decision record and an action item at the same
moment anchor with near-identical titles. Publishing correctly publishes both.
The fix belongs upstream in extraction, not in the approval path.

### B-6 · Person-scoped retrieval unions two legs that should intersect — M

A question about one person unions the graph-traversal results with the search
results instead of intersecting them, so an answer about that person can cite
moments they were not in. The fix needs a re-projection, which is why it was
deferred rather than patched.

### B-7 · Validate model bindings at startup, and that the endpoint serves them — M

Two related holes. A typo in an `llm.roles.*` model or fallback string passes
config validation and only fails at the first model call. Separately, nothing
verifies that a configured model tag is actually served by the endpoint it
resolves to — found when a fallback tag was configured that the endpoint did not
have.

**Do:** resolve bindings against declared providers at startup, and probe the
endpoint's model list. Fail closed with a named error, consistent with the rest
of startup.

### B-8 · Reject empty model bindings — S

`LlmRoleBinding.model` and `.fallback` accept empty or whitespace-only strings,
so the status page can render a blank binding and the worker can reach an
unusable one.

### B-9 · Validate the drop schema against its metaschema at startup — S

A syntactically valid but structurally invalid JSON Schema bypasses the startup
error path and fails at first intake instead — presenting as a bad drop when the
fault is the schema. Pre-existing since the intake endpoint was built.

**Do:** `Draft202012Validator.check_schema` at startup. Pairs naturally with B-10.

### B-10 · Detect migration drift — M

`schema_migrations` records only filenames. Editing an applied migration,
inserting a lower-numbered file, or booting old code against a newer schema all
go undetected. Matters as soon as there is more than one contributor or
deployment — which is now.

**Do:** checksum applied files; add out-of-order and schema-ahead-of-code checks.

### B-11 · Give the job-event stream a client heartbeat timeout — S

The server emits a heartbeat precisely so a half-open stream is detectable. The
browser hook marks the connection live on any frame but arms no timer, so a
connection where no bytes arrive and no error is raised reads as healthy forever
while the list silently stops updating.

### B-12 · Fix the chat panel's re-submit abort — S

A re-submit aborts and clears in a way that loses the in-flight state.

### B-13 · Pin the shell's child-screen placement with a test — M

The `<Outlet />` sits above the persistent search chrome so an opened moment is
not buried below a viewport-taller result list. Nothing pins that order, so a
future edit can silently reintroduce "Open moment does nothing". Covering it
means mocking the whole generated client surface plus every child route's
fetches — which is why it was skipped under time pressure, not because it does
not matter.

---

### B-34 · Keep `source_deep_link` on moments that also have replay — S

The `moments` stage writes a moment's `source_deep_link` only when the meeting
has neither a recording nor screenshots, and nulls it on the superseded-row
update once replay exists (`server/meetingminer/worker/moments.py`, the write
at ~295-302 and the update at ~385-399). Every YouTube meeting with a recording
— all of what story 6.2 will mint — therefore carries `sourceDeepLink: null` on
`MomentDetail`, `SearchHit`, and `CitationModel`, and the secondary link story
6.6 renders beside replay appears only on the drill-down header, which reads the
meeting-level field.

**Do:** retain the link beside replay in the stage and on the superseded-row
update; the web side already renders the field when present and keeps replay
primary for non-YouTube hosts. The store-backed tests are
`test_worker_moments.py` and `test_augmentation.py`, which story 11.1 owned
while 6.6 was in flight — 11.1 has landed, so nothing blocks this now.

**Done when:** a recorded YouTube meeting's moments carry the deep link on all
three models and the 6.6 secondary link shows on search hits and citations.

### B-37 · Surface total projection refusal from approve — M

The Story 11.3 live concurrency measurement at main commit `5a9676d` captured
`POST /moments/{moment_id}/approve` publishing a probe in Postgres, logging
`artifacts.projection.failed` with `ProjectionLockedError` when the projection
writer lock refused the entire store write, and then returning `200 OK`. The
probe was absent from both Meilisearch and Neo4j. A caller such as eval check
2.11 cannot distinguish that transient refusal from a real publish-gate
regression. This server behavior is independent of eval namespace ownership and
is outside Story 11.3's frozen footprint.

**Do:** give the approve response an explicit failure contract for total
projection refusal (for example a non-2xx problem response or a typed projection
outcome) and pin the behavior with an API regression. Preserve the durable
Postgres publication and the existing recovery hint so clients know whether to
retry, rebuild, or report a gate defect.

**Done when:** a caller can distinguish total projection refusal from successful
projection without scraping logs, and check 2.11 reports lock contention rather
than a false story-4.4 regression.

### B-38 · Fail loudly when a provider does not serve the configured model — CLOSED

**Closed 2026-08-30 by `ca9689a` (story 8.2).** `LiteLlmCompleter.complete` used
to map connection, timeout, service, rate-limit, authentication and permission
failures to `LlmUnavailableError` — the deliberate outage path `FallbackLlm`
absorbs — while a model-not-found response fell through the generic SDK-exception
branch as an `LlmError` naming neither provider nor endpoint. `FallbackLlm`
caught that base error, so a wrong binding was answered by a different model.

`litellm.exceptions.NotFoundError` now maps to
`LlmModelNotServedError` (`adapters/llm/port.py`), whose message opens with the
mandated template `provider {provider!r} at {api_base!r} does not serve model
{model!r}` and which carries `provider`, `model`, `api_base` and
`upstream_status` as fields. The provider is derived from the shared
`provider_for_model` rule config and runtime routing already use, never from the
SDK's own `llm_provider`. `FallbackLlm.complete` re-raises it ahead of the
`except LlmError` that engages the substitute, and `api/chat.py` surfaces it as
`urn:meetingminer:problem:binding-failed`. Genuine `LlmUnavailableError` outages
keep today's fallback behaviour, unchanged.

Pinned by `server/tests/test_settings_resolution.py`: the adapter mapping, the
provider derivation (the SDK is deliberately handed a *different* provider name),
a configured primary whose missing model never calls its fallback, and the
unchanged outage fallback beside it. The 2026-08-30 owner ruling also makes
endpoint provenance a load-time invariant: `test_config_catalog.py` refuses
authored and synthesized catalog bindings whose provider prefix has no matching
`providers.<prefix>.base_url`, so every binding that reaches this runtime path
has an endpoint URL the error can name.

### B-39 · Invoke thread derivation from the worker settle point — M

Story 10.2 delivers and tests `domain.threads.derive_threads`, but no production
path calls it. The correct settle point belongs to Story 10.1's extraction/job
orchestration, which was deliberately outside 10.2's wave footprint; today a
real corpus can accumulate topics indefinitely without producing `thread` or
`topic_thread` rows unless a developer calls the function directly.

**Do:** invoke thread derivation after topic replacement has settled, through
the configured `Embedder` port and the worker's existing transaction/error
discipline. Preserve whole-pass rollback on embedder failure, do not fall back
to name-only clustering, and make retry/restart behavior explicit.

**Done when:** a production worker run that replaces topics also refreshes
thread membership, an embedder outage leaves prior thread state intact, and an
integration regression proves both paths without a real model call.

### B-40 · Allocate durable per-corpus thread color ordinals — CLOSED

**Closed 2026-08-31 by story 10.3.** Migration 0017 adds `thread.color_ordinal`,
allocated from a Postgres sequence with a trigger that refuses any later change
to it, and `GET /threads` serves it. The open question this item held — what
"per corpus" means when `thread` has no corpus column — is answered in the
migration header: threads are derived corpus-wide and can span `meeting.corpus`
values, so the owning corpus is the database of record (AD-2) and one monotone
sequence in it gives every thread exactly one colour. Partitioning by
`meeting.corpus` would have given a cross-corpus thread two.

The original entry follows.


Epic 10 requires a server-owned positive color ordinal that is allocated once,
never recycled, and survives human merge/split/rename. Story 10.2 cannot define
it correctly because `thread` currently has no corpus column and a thread may
span corpora; adding a global counter now would silently choose the wrong
scope for the Threads view.

**Do:** decide the corpus ownership model with Stories 10.3/10.6, then allocate
ordinals transactionally within that scope. A merge survivor keeps its ordinal,
a split product receives a new one, and deleted ordinals are never reused.

**Done when:** the API serves a stable per-corpus ordinal for every thread and
concurrent allocation, merge, split, rename, and deletion tests prove uniqueness
and non-reuse.

### B-42 · AD-17's id-addressed media route does not exist — M

AD-17 says the api resolves a media request by looking the row up from an id,
never by joining a client-supplied path onto a root. `api/media.py` does that
for one case only — `GET /media/recordings/{meetingId}` — while stills are
served through the path-addressed `GET /media/{path:path}`, which means
`screenshot.path` has to reach the client for a still to render.

Story 10.3's timeline and story 10.4's feed both serve opaque `screenshotId`
values on the strength of a `GET /media/files/{mediaId}` route their acceptance
criteria name and no story has built; `api/media.py` was outside both
footprints. Until it exists, a client holding a `screenshotId` cannot fetch the
bytes without going back to a path-serving route for them.

**Do:** add an id-addressed route that resolves `screenshot.id` (and any other
evidence-file row) to its stored path server-side and streams it through the
existing containment check and range parser, then retire path-addressed still
serving from the clients that use it.

**Done when:** every id the api serves for a still resolves through the
id-addressed route, and no response body anywhere carries a storage path.

### B-41 · Adopt persisted judge selection in the eval harness — M

Story 8.2 persists per-role choices, but the manual judge still binds
`config.settings.llm.roles.judge` directly and passes that file role to
`build_llm` (`evals/harness/judge.py:499-500`). Advertising a persisted judge
choice as effective while this call ignores it would misreport which paid model
was used, so the owner excluded `judge` from `GET /settings/models` and made
`PUT /settings/roles/judge` a named file-only refusal until adoption is real.
The gap went undetected because `evals/tests/test_run_judge.py` replaced
`build_llm` without asserting which binding was passed; Story 8.2 now pins that
file-role behavior explicitly.

**Do:** wire judge selection through `evals/harness/judge.py` using the public
settings boundary appropriate to the AD-16 client rule, then deliberately add
`judge` to the selectable settings policy. Ensure the binding used by
`build_llm`, the judge report, and the eval config snapshot all name the same
effective choice; never guess or fall back to the file value if selection
provenance is unavailable.

**Done when:** changing the persisted judge choice changes the next judge call
without editing `config.yaml`, the report and snapshot record that exact
binding, and paired tests fail if either the settings surface or judge harness
can drift from the other.

### B-42 · Serve provider health per provider, not per role — CLOSED

The model picker (story 8.3) shows each catalog entry's provider health, and
the only place the api reports key state today is `GET /status.llmRoles[]` —
one row per configured role, carrying that role's `provider`, `keyState`,
`state` and remediation. `providerHealthIndex`
(`web/src/features/settings/models.ts`) therefore joins by exact provider id
and keeps the worst row for a provider.

For a credential that is exactly right: `OPENAI_API_KEY` being missing is a
fact about the provider, true for every option on it. Endpoint reachability is
not. `llm.roles.extraction` has its own `base_url` (a different Ollama host
from `providers.ollama`), so an unreachable extraction host makes every
`ollama/…` option read `unreachable`, including one whose call would resolve
through the provider endpoint that is answering. The remediation sentence names
the host, so a reader can see which machine is meant, but the word beside the
option is broader than the evidence behind it.

**Do:** story 8.2a's `GET /status.providers[]` — health per provider id, probed
once per provider rather than once per role. `providerHealthIndex` then reads
it directly and the role rows stop standing in for it.

**Done when:** an option's health word comes from a probe of the endpoint that
option's call would actually use, and a role-specific `base_url` outage no
longer colours options bound to a different endpoint.

**Closed 2026-08-31 by story 8.2a.** `GET /status` serves
`providers[]{provider, keyState, detail, remediation, state, observedBy}` — one
row per provider `config.yaml` declares, probed once behind the existing 60s
cache. `providerHealthIndex` reads it for the credential verdict, which is
provider-wide; the role rows now supply only per-endpoint reachability, keyed
by role plus provider, and `healthFor` prefers a role's own endpoint over the
provider's default one. A configured provider no role binds today is covered
for the first time.

*Numbering note:* two entries in this file carry the id `B-42` — this one
(added by story 8.3) and "AD-17's id-addressed media route does not exist"
above it. They were filed in parallel branches on the same day. Renumbering
either would break references already written into landed story specs, so the
collision is recorded here rather than resolved; a reference to B-42 must name
its subject.

### B-43 · Render a failed binding as its own refusal beside the answer — S

Story 8.3's clause is that a failed binding surfaces where it happens. In the
picker it does: the entry is muted and carries its remediation. At the ask, a
`urn:meetingminer:problem:binding-failed` 502 reaches `ChatPanel` through
`classifyFailure`'s generic `problem` kind and renders as "The api at … could
not answer that question: `<detail>`" — the api's own sentence, naming the
provider, the binding and the upstream status, so nothing is hidden or
misattributed.

What the design asks for and this does not do (EXPERIENCE.md § Ask box) is
render it as a refusal box in the answer region *without clearing the previous
answer*: today every failure clears the answer, so a binding change that fails
costs the reader the answer they were reading. Story 8.3 left it alone
deliberately — its footprint is a minimal insertion into the ask box, and the
clearing rule is shared by all five failure kinds, so changing it is a change
to chat's failure taxonomy rather than to the picker.

**Do:** give `binding-failed` its own kind in `features/chat/chat.ts`, render it
as a refusal box, and leave `answer`/`citations`/`route` untouched when it
arrives.

**Done when:** a binding failure on a re-ask leaves the previous cited answer on
screen with the refusal beneath it, and no other failure kind changes behaviour.

## Robustness and hygiene

### B-15 · Stop embed-only projection from opening Neo4j — S

The embed-only pass writes only search-store vectors, but still opens and
health-checks the graph store.

### B-16 · Ship the drop schema as package data — M

`docs_root()` anchors the schema to the config file's parent directory, so a
relocated config must relocate `docs/` too — visible as a symlink workaround in
the migration tests. Migrations were deliberately moved into the package so they
ship with the wheel; the schema is a second, path-fragile mechanism for the same
problem. Revisit when non-editable installs become real.

### B-17 · Detect drift between the committed TS client and the live schema — M

Committing `web/src/client/` removes the fresh-clone failure but adds a staleness
risk with no detector. The check needs a running api, so it needs a gating
decision about when it runs.

### B-18 · Type the SSE payload from the generated client — S

The three wire event names exist as two independent sources of truth — the
server's constants and the web hook's — reconciled only by a hand-written type
guard. Nothing fails if they drift. Blocked until the generator reads OpenAPI 3.2
`itemSchema`.

### B-19 · Route the content-root warning through structured logging — S

`config.py` prints a plain-text warning while the worker emits JSON events the
Makefile readiness poll greps. It prints twice under `make api` (preflight plus
reloader) and on every `make migrate`, so it is both unparseable by the tooling
and noisy.

### B-20 · If review gating returns, check authorship and not just existence — S

The gate this project used to run verified that a review report *existed*, never
who wrote it — so a review dispatched by the same agent that wrote the code
passed identically to an independent one. It also passed vacuously when no
review had been dispatched at all, which is how B-3 slipped through.

The gate is gone, so there is nothing to fix today. The lesson is a condition on
whatever replaces it: an existence check is not a review check. Whatever gates
review next — a required approval, a CI job, a convention — needs to answer
"who reviewed this, and were they independent of the author", or it will report
green on work nobody independently read.

### B-35 · Per-worktree api and web ports — S

`API_PORT` (8000) and `WEB_PORT` (5173) are fixed in `infra/Makefile`, so
`make up` in a worktree collides with another checkout's api and web even
though the stores are private since story 11.2 (`.env.worktree`). The
committed TS client bakes `http://localhost:8000` in as its default `baseUrl`
(`CLIENT_URL`), so the api port is more than a Makefile variable.

**Do:** allocate the two ports in `.env.worktree` beside the store ports and
have the Makefile, the web dev server and the client's base URL read them;
keep the main checkout on 8000/5173.

---

## Scale — deferred deliberately, still true

### B-21 · Bound the meetings list and the job-event stream — M

Neither query carries a `WHERE`, `LIMIT`, or `OFFSET`, and every reconnect
re-fetches the whole list. Cost grows with total ingests rather than with
in-flight ones. The `job_stage.updated_at` trigger already exists to make cheap
change detection possible; the watermark was never built. Scoped out as a
single-user-machine decision, so this is a scale deferral rather than a defect.

### B-22 · Recording-blind ranking can fill a page with unplayable hits — M

A top-20 search page can contain zero results that have a recording, even on a
healthy fully-rebuilt index. Residual risk after the corpus-wipe fix.

---

## Data lifecycle

### B-23 · Decide how participant identity migrates incrementally — L

A partial re-emit pass splits one person across a name-keyed and a mail-keyed
participant row with nothing linking them, so a traversal returns half that
person's meetings. The one-pass migration has been run and this failure did not
occur, but the structural fix — the alignment stage writing an alias when the
graph first supplies a mail address for a name it has already seen — gives the
worker write access to a table AD-5 assigns to the api. **That is an AD-5
amendment, not an implementation choice**, and it is the real fix if identity
ever has to migrate incrementally rather than in one pass.

Related and still open: after the pass, a number of superseded name-keyed rows
are orphaned with no meeting link. Whether they should be reaped or aliased to
their mail-keyed counterparts is undecided.

### B-24 · Retire the `job.drop_path` column — S

Migration 0008 kept the column and lifted its NOT NULL rather than dropping it,
because the backfill had to read the pre-migration absolute value. Every writer
since leaves it NULL and a CHECK enforces exactly one anchor. One migration drops
the column and the CHECK, safe as soon as no row has a null relative path.

### B-25 · Reap orphaned content directories — M

A content directory can exist under the content root with no meeting row —
left behind when a meeting is deleted by hand or re-ingested under a new id.
`prune` only removes directories for the meetings it deletes, so these are
outside it by design, and no other tool reaches them.

---

## Acquisition

### B-27 · The tracked puller cannot produce a participant graph — L

The puller in this repository has no org-chart code at all, so any drop it emits
alone omits `participants` — which contradicts the requirement that a drop carry
the participant graph the puller already resolved. The producer of that graph
exists only in a separate lineage outside this repository. Reunifying the two was
left out of scope, and the workaround that papered over it (packaging both side
by side for a second machine) has now been retired with the demo.

**Decide:** reunify the lineages, or accept that drops carry no participant graph
and let identity fall back to normalized display names.

### B-28 · Point the puller's drop output at the configured drops root — S

The puller finalizes drops into its own configured output directory and posts the
absolute path. Intake refuses a drop outside the configured drops root with a
clear error naming both paths — correct behaviour, but the two settings are
related only by an operator remembering it.

### B-29 · Fail loudly when the archive catalog is missing — S

The archive-index script and the archive fallback both read a catalog file beside
themselves. It is untracked and lives only in the working archive, so in a repo
checkout both now read nothing: the script logs a start and a finish, indexes
zero folders, and exits 0. The two-copy split makes the empty case ordinary
rather than impossible.

---

## Documentation accuracy

### B-30 · Purge the expired paid-worker premise — S

Several live artifacts still justify constraints with a paid-model worker backlog
that no longer exists: the status page's SPEC constraint, the status module
docstring, and further documents asserting the same premise. The extraction role
is now bound to a local model and the queue is empty.

### B-31 · Fix two stale cross-references — S

`solution-design.md` and the top-level spec both state the architecture holds 16
decisions. It holds 17 — the last was added later and neither reference was
updated. Separately, the eval README describes a failed job as leaving a row that
creates a second subject on re-ingestion, but intake re-queues an all-failed
source id in place.

### B-32 · Correct the over-capture budget formula in the eval design — S

The design document still documents the budget as `ceil(duration_minutes)`; the
shipped formula has an additional term.

### B-33 · Add screenshots and a sample drop to the README — M

The README describes a visual product — moment view, screenshot series,
audio-and-video replay — with no screenshots, no clip, and no ingestible sample.
A new reader cannot see what it does or try it without supplying their own
recording.

---

## Removed from this list

Twenty items were retired rather than carried forward. Ten were already resolved
and said so in their own text: the lock-timeout hold race, parallel-safe store
tests, the server-side viewability gate, augmenting drops, the recording's
drop-relative row, the participant merge backfill, schema reload on change, the
committed client gaining the chat operation, the artifact-publish lock bypass,
and a config-test failure fixed at a later integrate.

Ten more were obsoleted by events rather than fixed: the packaging path and its
two findings retired with the demo; the import of recordings that are no longer
in the corpus; a capture-volume measurement taken against that same set;
stale-worktree drift for worktrees that no longer exist; the scheduled
archive-index job, whose plist was never installed and whose archive is no
longer a corpus source; and several documentation items already corrected in
place.

One item was done rather than retired. B-1 (split the test suite so a routine
run takes seconds) closed with story 11.1 on measured numbers, not its own
estimate. At `e5510c7` on 2026-08-29 the full server run was 1,683 tests in
9m17s (554s in pytest), not ~33 minutes, and 471 of its 527 test-seconds sat in
twelve modules bound by the Neo4j/Meilisearch test twins, spawned processes,
the projection file lock, or timers — not the seven process-spawning modules
B-1 named; `test_mint_drop`, on that list, ran its 68 tests in 2.8s and stays
in the fast set. Those twelve modules, plus the timer- and twin-bound tests in
otherwise fast modules, carry a `slow` mark with a reason and their measured
cost; `server/pyproject.toml` defaults every run to
`-m "not slow" --strict-markers`; `make test-fast` runs that selection plus
the store-free suites, and `make test` runs everything with `-m ""`. The
marks alone deselect 325 of the 1,683 baseline tests (the twelve modules'
322 plus three timing tests); with a fourth per-test mark and the regression
tests this story added, the split at `bd5fecb` on `story/11-1-review` is
1,393 of 1,719 with 326 deselected (`uv run --project server pytest
server/tests --co -q` shows the current figure). `server/tests/fast_budget.py`, loaded
from conftest's `pytest_plugins`, fails any unmarked test whose call phase
exceeds `mm_fast_test_budget_seconds` (2.0s), stops collection when a
`slow` mark lacks a `reason=` or an unmarked test requests the test twins,
and fails an unmarked test that requests them at run time
(`request.getfixturevalue`) before `projection_stores` runs for it,
whatever outcome the test then earns.
`REPO_ROOT` moved to `server/tests/repo_paths.py`, and the two make runners in
`test_makefile_procs.py` collapsed into one. Measured with the stores up at
`bd5fecb`: `make test-fast` took 66s wall, 48.6s of it the 1,393-test pytest
step; the rest is the three store-free suites and interpreter startup. The
fast set needs Postgres only — with the twins unreachable it still ran all
1,393 with no skips, because every twin-bound test is `slow` and deselected;
`make test` is the gate that requires the twins. Not the "couple of seconds"
B-1 asked for: the residue is roughly a thousand Postgres-backed api and
worker tests at 20–50ms each, which is fixture cost, and making those
fixtures cheaper changes what the tests do. That is a separate item if anyone
wants it.

---

### B-36 · Nothing binds the LAN GPU host that was built for inference — M

VM 120 `cuda-asr` has been serving `nvidia/parakeet-tdt-0.6b-v3` at
`http://10.77.0.120:8000` since 2026-08-19 — verified answering `/health` on
2026-08-30 at ~253x real time with native NeMo timestamps — and
`ARCHITECTURE-SPINE.md` records it as *the* LAN inference host under the
amended AD-9. **No code reaches it.** `stt.engine` is
`Literal["mlx-whisper", "parakeet-mlx"]`, both MLX engines running in-process
on the Mac; neither `adapters/stt/` nor `adapters/diarize/` contains an HTTP
client; and no tracked source file references the address. The box is idle
infrastructure the architecture already promised.

Two separable pieces of work, and the second is worth more than the first:

- **`Stt` over HTTP.** A remote engine bound as a third `stt.engine` value with
  the host in `config.yaml` (AD-9's rule: where inference runs is a config
  change, never a code change). This is an optimisation — transcription already
  works locally — but it is what makes the recorded architecture true.
- **`Diarizer` over HTTP — DONE 2026-08-30, landed at `2dec459`.** The
  `Diarizer` port has no working engine at all: `noop` returns nothing and
  `pyannote` needs a HuggingFace licence acceptance and a token this project
  does not have. The spine notes the guest's NeMo install "carries diarizer
  code but no weights and no endpoint", so this needs the service to grow a
  `/diarize` route and pull the speaker weights before an adapter has anything
  to call. The build request is drafted at
  `~/Downloads/RUNBOOK-threadripper-diarize-addendum.md` (owner-held, outside
  the repo). Story 7.1's acceptance criteria already name this endpoint as the
  config-swappable alternative, so the story contract anticipates it.

  **Delivered and verified 2026-08-30.** `POST /diarize` on the same guest
  returns `{"turns":[{"start","end","speaker"}],"model":...}` from NeMo's
  `ClusteringDiarizer` (`vad_multilingual_marblenet` + `titanet_large`). It
  meets the port's contract as specified: `SPEAKER_NN` is local to the
  recording, silence returns `{"turns": []}` with HTTP 200, overlaps use
  `drop_shorter` rather than inventing a split timestamp, and `/transcribe`
  and `/diarize` share one inference lock so they queue instead of contending.
  When VM116 owns the GPU the service stays reachable and returns 503 with a
  named reason rather than hanging — a named failure our caller can treat as
  data. Their measurements with ASR resident: 10 min in 15.41s (peak 3,461
  MiB), 60 min in 57.53s (RTF 0.0160, peak 8,817 MiB). Verified here against a
  real 247s meeting recording: 14s wall, 82 turns, 2 speakers, chronologically
  ordered, median turn 1.98s.

  **What remains is ours**: a remote `Diarizer` adapter plus a `diarizer.engine`
  value and endpoint binding in `config.yaml`. No `HF_TOKEN` and no licence
  acceptance is involved on this path, unlike the in-process `pyannote` engine,
  which is still blocked on accepting the gated model's conditions. Two facts
  any adapter must respect: the endpoint is operator-scheduled (VM120 is
  `onboot=0` and shares its GPU with VM116), so a stage bound to it must fail
  by name when it is down rather than silently degrading; and turn *quality*
  is still unvalidated — 2 speakers on a scripted two-person demo is plausible
  but is not ground truth, so judge it against the new corpus.

Constraints for whoever picks this up: VM 120 and VM 116 pass through the same
RTX 4080 and must never run together, and VM 120 is `onboot=0` — so the
endpoint is operator-scheduled infrastructure, deliberately *not* a
best-effort dependency (spine, 2026-08-19). A stage bound to it fails by name
when it is down rather than falling back silently. GPU headroom is the other
limit: ASR alone peaked at 11,208 MiB of 16,376 in the handoff benchmark.

B-14 (make the projection-lock timeout test independent) closed with story
11.2. `server/meetingminer/projections/locks.py` honours

On 2026-08-30, B-14 (make the projection-lock timeout test independent)
closed with story 11.2, done rather than retired. `server/meetingminer/projections/locks.py` honours
`MM_PROJECTION_LOCK_KEY` — a named key, `[A-Za-z0-9._-]{1,64}`, in place of the
URL-derived one; unset, the derivation is byte-identical — and
`test_projection_lock_times_out_with_holder_details_then_releases` sets
`b14-<run id>` for its holder, its waiter and its own path assertions, so no
other process can be the holder it sees. The same story gave every worktree a
private compose stack on its own ports, so a holder from another worktree is on
another lock anyway; the key is what makes the test's own assertions exact.

---

### B-47 · A source-attributed speaker label cannot be pushed back to unresolved — S

*Renumbered from B-39 on 2026-08-31: four parallel lanes filed against a stale counter on the same day, so B-39 was claimed twice. Review reports and commit messages from that day cite the old id.*

Story 7.3's `PUT /meetings/{id}/speakers/{tag}` records `unresolved` by
*deleting* the `speaker:<meetingId>:<tag>` alias row, because
`participant_alias.participant_id` is `NOT NULL` and there is no way to store
"this tag names nobody". Deleting the key restores `align`'s own answer, which
for a diarizer tag is `placeholder` with no participant — the acceptance
criterion exactly.

For a label the *source* attributed (`Goeke, Timothy` in a Teams export),
`align`'s own answer is `resolved` against the meeting roster, so choosing
`unresolved` there is accepted, re-arms the job, and leaves the tag resolved.
A curator who believes a source got the attribution wrong has no way to say
so.

Fixing it needs somewhere to record a negative assertion — a nullable
`participant_id` with a state column, or a separate api-owned table — which is
a migration and a schema decision, deliberately outside the story that found
it. Until then the route's behavior is honest but incomplete: it can add an
attribution and remove one it added, not overrule the source.

---

### B-48 · A curator's typed speaker name splits one person across meetings — S

*Renumbered from B-40 on 2026-08-31: four parallel lanes filed against a stale counter on the same day, so B-40 was claimed twice. Review reports and commit messages from that day cite the old id.*

Story 7.3 mints a `participant` row for a display name typed into the speakers
screen, keyed `curated:<meetingId>:<tag>`. The key is per-meeting, so the same
human typed into two meetings gets two rows, both listed by `GET
/participants`.

This is deliberate rather than accidental. The api may not import `pipeline`
(`api/ingests.py`), so it cannot compute `pipeline/speakers.identity_key_for`'s
`name:<normalized>` key without a second copy of `normalize_display_name` —
and two spellings of an identity key silently collapse two humans onto one
row, which is the failure that module warns about at length. A split is the
recoverable direction: `POST /participants/{id}/merge` joins the rows, and
story 7.3 fixed the predicate that was blocking exactly that merge.

The real fix is to move `normalize_display_name` (and `identity_key_for`) out
of `pipeline/speakers.py` into `domain/`, where both layers may use the one
definition, and have the api mint `name:<normalized>` like the worker does.
That is a small move, but it edits a module story 7.1 and B-36 were both
holding when this was found.

---

### B-49 · A cold load into an unsettled meeting cannot list its speaker tags — M

**Closed 2026-08-31 by `2a86e69` (story 7.4 review, finding F1), under the owner ruling recorded below.** `GET /meetings/{id}/speakers` now serves an unsettled meeting whose job is not `running`, paired with the PUT that already did. The exception stayed route-local: `_require_viewable` is unchanged and every sibling read, drilldown included, still calls it.

*Renumbered from B-41 on 2026-08-31: four parallel lanes filed against a stale counter on the same day, so B-41 was claimed twice. Review reports and commit messages from that day cite the old id.*

Story 7.3's `PUT /meetings/{id}/speakers/{tag}` is deliberately admitted while
a meeting's evidence is unsettled, so a curator can correct the naming that
made a rerun fail. Its sibling read, `GET /meetings/{id}/speakers`, still
refuses that meeting with 409 `meeting-not-viewable`, as does
`GET /meetings/{id}/drilldown`.

Within one session the speakers screen (story 7.4) covers the gap: the rows it
read before the naming stay on screen through the rerun, so the recovery
gesture has a tag to act on. A *cold* load into an already-unsettled meeting
has no such rows — the reader arrives, both reads refuse, and the write that
would fix the meeting has no tag to name. The screen states the api's sentence
and offers Retry, which is honest and useless: retrying cannot succeed until
the rerun the curator is trying to fix has settled on its own.

The fix is on the api, not the client: extend story 7.3's route-local
recovery exception to the speakers read, so the one meeting state that admits
the write also admits the read that makes the write usable. That is a policy
decision about `_require_viewable`, which story 7.3's own comment explicitly
warns against generalizing, so it needs the owner rather than a builder. A
narrower version — the 409 body carrying the tag list — leaks aggregate data
into a refusal and is probably worse.

**Owner ruling, 2026-08-31: extend it.** The exception exists so a curator can
recover a meeting whose rerun failed, and a read that refuses makes that
recovery impossible from a cold page load — which is the case a curator is
most likely to arrive in, because the failure happened while they were away.
Extend story 7.3's recovery exception to `GET /meetings/{id}/speakers`, kept
route-local and narrow in exactly the way the write's exception is: this one
read, this one meeting state, no generalization of `_require_viewable` and no
change to `GET /meetings/{id}/drilldown`. Story 7.3's comment warning against
generalizing stands — it warns against widening the rule, not against the
second half of the same recovery path.

---

### B-50 · The speakers wire carries no provenance for a resolution — S

*Renumbered from B-42 on 2026-08-31: four parallel lanes filed against a stale counter on the same day, so B-42 was claimed twice. Review reports and commit messages from that day cite the old id.*

`GET /meetings/{id}/speakers` returns `speakerResolution` and, when resolved,
a `participantId` and `displayName`. It carries nothing saying *who* resolved
the row: a label the source supplied (a Teams export's `Goeke, Timothy`) and a
label a curator assigned through story 7.3 are byte-identical on the wire,
because `align` re-derives both and writes the same three columns.

EXPERIENCE.md's Speaker naming state table asks a resolved row to read
`from transcript`. Story 7.4 does not print that: on a row a curator named
five minutes earlier it would be a claim no served field backs, and this
product's first contract is that nothing on screen is invented. The screen
prints the api's own resolution word instead.

Restoring the designed copy needs a served field — a `resolvedBy`
(`source | curator`) on the speakers row, derivable from whether a
`speaker:<meetingId>:<tag>` alias exists. That is a story 7.2 response-shape
change, which 7.2's one-shape criterion pins, so it is a spec decision rather
than an edit.

---

### B-51 · Add a stable feed snapshot only when readers page deeply — M

Story 10.4 ranks every `GET /moments/feed` request against the corpus as it
exists at request time. That is the intended live-feed behavior, and the wire
contract says plainly that offset ordering is not stable across requests: a
candidate may repeat or be skipped across a boundary as ranking moves.

Two mechanisms could freeze a future paging session: a client-supplied `asOf`
used by every request in the session, or an opaque cursor that carries the
server-owned ranking snapshot. Either adds state and a new client contract for
little benefit while readers normally click “Show more” only once or twice.

**Do only when:** the feed has grown large enough that readers routinely page
deeply rather than click “Show more” once or twice. At that point, choose and
specify either `asOf` or an opaque cursor; do not silently strengthen offset
semantics without a wire mechanism.

**Done when:** one paging session has a documented stable-snapshot token and
tests prove that ranking movement cannot repeat or skip candidates inside it.

### B-52 · Let the api report the worker's loaded binding, not only that it differs — M

Story 8.2a made `GET /status` attribute every binding and key reading to the
api process, because the api and the worker hold independent `config.yaml`
snapshots (AD-10 as amended 2026-08-31) and the api cannot see the worker's.
The extraction row therefore names the worker as the process that makes the
call and says plainly that this row is the api's snapshot rather than the
worker's. That is honest, and it is as far as the api can go on its own.

What it still cannot do is *show* the worker's binding. The worker loads
`config.yaml` in its own process and writes no record of what it loaded, so
there is nothing for the api to read. The consequence is the 2026-08-31
incident's residue: the surface can now say "the two may disagree" but cannot
say "they do disagree, and here is how".

**Do:** have the worker record, on a row the api can read, the binding it
resolved for `llm.roles.extraction`, the provider that binding derives to, and
the timestamp at which it loaded `config.yaml` — written at startup and on
each job claim, alongside the advisory lock the status surface already reads.
`api/status.py` then reports the worker's own reading beside the api's, still
attributed to the worker, and marks the surface degraded when the two differ.

**Done when:** with the api and the worker started from different `config.yaml`
revisions, `GET /status` names both bindings, attributes each to the process
that loaded it, and reads degraded — and with both restarted from one revision
it reads healthy without either process asserting the other's state.
