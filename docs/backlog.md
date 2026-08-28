# Backlog

Work that is known, evidenced, and not yet done. Every item here was found by a
code review, an incident, or a measurement — none is speculative. Items are
grouped by what they cost you, not by which epic produced them.

Sizes are rough: **S** under a day, **M** a day or two, **L** more, or unbounded
until a decision is made.

---

## Now — these cost something every day

### B-1 · Split the test suite so a routine run takes seconds, not half an hour — S

`pytest server/tests` runs 1,684 tests in ~33 minutes. Almost none of that is
test logic.

Measured: collecting all 1,684 tests takes **1.0s**; a pure decision-core module
runs 34 tests in **0.04s**. But **215 tests (16%)** live in seven modules that
spawn real processes — `test_makefile_procs.py` alone makes 46 subprocess calls
running actual `make start-api` / `start-worker` / `client` targets with live
readiness polls; `test_mint_drop.py` shells out to ffprobe and ffmpeg;
`test_migrations.py` issues real `CREATE DATABASE`; `test_parallel_store_safety.py`
waits on a file lock whose default timeout is 300s. Their combined timeout budget
is ~1,500s. These are integration tests with no marker, sitting in the same
directory, so every run pays for all of them.

**Do:** mark those seven modules `slow`, default the runner to `-m "not slow"`,
and keep the unmarked full run for `make test`. While there, move `REPO_ROOT` out
of `conftest.py` into a normal module (five modules import conftest by name,
relying on pytest's `sys.path` insertion) and collapse the duplicate
`_make`/`_run_make` helpers.

**Done when:** an iteration run executes ~1,169 tests in a couple of seconds, the
215 integration tests still run under `make test`, and no test changes behaviour.

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

## Robustness and hygiene

### B-14 · Make the projection-lock timeout test independent — S

`test_projection_lock_times_out_with_holder_details_then_releases` manipulates the
real endpoint-keyed shared lock, so a concurrent holder from another worktree
makes its holder-queue and metadata assertions see the wrong holder. It has
already failed mid-run for this reason and passed on re-run.

**Do:** point the test at its own lock via an env override for the lock key,
rather than the shared one.

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
