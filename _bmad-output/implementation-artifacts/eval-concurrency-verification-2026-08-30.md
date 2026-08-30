# Live concurrent eval verification — Story 11.3 (Eval Runs Own Their Namespace)

**Date:** 2026-08-30
**Run by:** owner-authorized verification agent (paid `chat`/`judge` spend approved for exactly two eval runs; two were run, no retries).
**Code under test:** branch `story/11-3-review` in worktree
`/Users/devopsterus/current/cohort/meetingminer-wt/11-3-review`.
Branch tip when the runs were launched: `f2ed760`. (The branch has moved since —
a scoped review agent is committing to it concurrently; nothing in this
verification was committed to that branch.)

This file records the **owner-run measured truth** that
`_bmad-output/implementation-artifacts/spec-11-3-eval-runs-own-their-namespace.md`
routes to its `## Verification` section. It is the measurement the story's
AGENTS.md sentence must be written from.

---

## 1. Environment as measured

| Item | State |
|---|---|
| Docker runtime | OrbStack up; shared dev stack `meetingminer-postgres` / `-neo4j` / `-meilisearch` plus twins `-neo4j-test` / `-meilisearch-test`, all healthy, uptime ~22h |
| Dev stores | Postgres 5433, Neo4j bolt 7687, Meilisearch 7700 — `make check-dev-stores` exit 0 |
| Test twins | Neo4j bolt 7688, Meilisearch 7701 — `make check-test-stores` exit 0 |
| api | **Already running** from the *main checkout*: `/Users/devopsterus/current/cohort/meetingminer/server/.venv/bin/uvicorn meetingminer.api.main:app --host 127.0.0.1 --port 8000`, pid 54736, uptime 22h07m. `make check-api` exit 0, `/health` → `{"status":"ok","service":"meetingminer-api","configVersion":1}` |
| worker | stopped (standing restart hold), left stopped |
| Corpus | 2 `scripted` meetings (`demo-001` 01a04938-db21-…, `demo-002` 01a0493b-c6a6-…), 25 moments, 6 artifacts all `extracted`, 0 rows matching `eval-gate-probe-%` |

**Note on `make start-api`.** Procedure step 1 said to start the api if it was
not running. My first `curl` to `:8000` returned nothing, so I ran
`make start-api` in the 11-3-review worktree. That was a false negative: the
first curl ran inside the tool sandbox, which blocks loopback egress. The api
was already up. `make start-api` reported `api: ready (pid 90732)` because its
readiness probe is an HTTP health check that the *existing* api answered, but
its own uvicorn had already died:

```
ERROR:    [Errno 48] error while attempting to bind on address ('127.0.0.1', 8000): address already in use
```

So **both eval runs were served by the main checkout's long-running api**, which
is what the spec asks for ("In the main checkout with the stack up"). Story 11.3
changes no server code, so the approve route exercised is the correct one. This
is recorded because `make start-api`'s "ready" line is not proof that the api it
started is the api answering — a separate observation worth having.

---

## 2. Exact commands run

All three were launched from one shell script, concurrently:

```bash
# shell A — /Users/devopsterus/current/cohort/meetingminer-wt/11-3-review
make evals-run EVAL_ARGS='--run-label left'

# shell B — /Users/devopsterus/current/cohort/meetingminer-wt/11-3-review  (t+2s)
make evals-run EVAL_ARGS='--run-label right'

# shell C — /Users/devopsterus/current/cohort/meetingminer-wt/11-4
make test
```

The `make test` worktree was **`/Users/devopsterus/current/cohort/meetingminer-wt/11-4`**
(branch `story/11-4`, tip `dc1e64d`, parked builder, clean tree). Excluded as
instructed: `8-1`, `6-3`, `6-2-review`, `10-1-review`.

Both eval runs resolved to:

```
uv run --project .../server pytest .../evals/checks --api-base-url http://localhost:8000 --run-label <label>
```

Post-run query, against the dev Postgres:

```sql
SELECT count(*) FROM artifact WHERE title LIKE 'eval-gate-probe-%';
```

---

## 3. Wall clock

| Command | Start (local) | End (local) | Wall | Exit |
|---|---|---|---|---|
| `make evals-run … left` | 15:55:04 | 15:55:13 | **9s** | 2 |
| `make evals-run … right` | 15:55:06 | 15:55:13 | **7s** | 2 |
| `make test` (wt/11-4) | 15:55:04 | 16:04:40 | **576s (9m36s)** | **0** |

Inside the runs, the harness recorded `started_at`/`finished_at` of
21:55:06→21:55:13Z (left) and 21:55:09→21:55:13Z (right). The two runs' probe
approvals landed within **1.9 seconds of each other**, so this is a genuine
overlap and not two runs that merely shared a wall-clock window.

`make test`: **1733 passed in 550.37s**, then the web build, exit 0. It was not
disturbed by either eval run, and it did not disturb them (see §6).

---

## 4. Run folders and verdicts

Two distinct folders, each written cleanly, no collision, no ownership refusal:

- `/Users/devopsterus/current/cohort/meetingminer-wt/11-3-review/evals/runs/2026-08-30-left/`
- `/Users/devopsterus/current/cohort/meetingminer-wt/11-3-review/evals/runs/2026-08-30-right/`

Each contains `config-snapshot.yaml` and `deterministic-report.yaml`. Neither
holds a `verdict.md`, and that is correct: `verdict.md` is the *human*-recorded
verdict a reviewer writes into the folder afterwards, and `Run.create` refuses a
folder that already holds one (`evals/harness/run.py:147`). The run's own
verdict is `passed:` in the deterministic report.

| Run | Verdict | Failing checks |
|---|---|---|
| left | `passed: false` | 2.1 capture recall [demo-002], 2.2 over-capture [demo-002], **2.11 publish-gate [demo-001]**, **2.11 publish-gate [demo-002]** |
| right | `passed: false` | 2.1 capture recall [demo-002], 2.2 over-capture [demo-002] |

**The 2.1 / 2.2 failures are pre-existing and not concurrency-related.** They are
byte-identical in both runs (`capture 2 answers for 2 manifest entries (S1,
participant_segments[1] at 00:06:38)`; `10 captures for 7.0 minutes exceeds the
budget of 7`) and are ground-truth-script defects in `demo-002`, named as such
by the check's own remediation text. They are unrelated to story 11.3.

**Every 2.11 check in the `right` run passed. Both 2.11 checks in the `left` run
failed, and one of those two failures was caused by the sibling run.**

---

## 5. Check 2.11 detail — probe ids and cleanup evidence

Four probes were minted (two per run, one per subject). Every one of them was
minted, approved through the public api with **exactly its own id** in
`published_ids`, and erased with all four cleanup targets verified.

| Run | Subject | Probe artifact id | Moment ridden | approve ok | pre (meili, neo4j) | post (meili, neo4j) | cleanup |
|---|---|---|---|---|---|---|---|
| left | demo-001 | `01a054ab-56b3-7b0e-8d7a-fe22c1bffe00` | `01a04939-763b-7ae7-9342-d6006e1f98f9` | true | absent, absent | **absent, absent** | verified |
| left | demo-002 | `01a054ab-5d14-78c8-bb22-63758ed9a75b` | `01a0493c-387d-7c58-a05f-a5e659b20caa` | true | absent, absent | present+cited, present+cited | verified |
| right | demo-001 | `01a054ab-56b4-7485-b3fd-87c94b583d7c` | `01a04939-763c-7c22-ad28-9950dea8a842` | true | absent, absent | present+cited, present+cited | verified |
| right | demo-002 | `01a054ab-5b35-7d3d-adc3-6ce905d87916` | `01a0493c-387d-7c58-a05f-a5e659b20caa` | true | absent, absent | present+cited, present+cited | verified |

Cleanup, all four probes, verbatim from both reports:

```yaml
cleanup:
  search_document_removed: true
  graph_node_removed: true
  export_file_removed: true
  postgres_row_removed: true
  verified: true
  problems: []
```

`foreign_rows: []` and `consumed_foreign_rows: []` on all four probes. **No
`nothing-to-approve` (409) response occurred in either run** — the failure mode
the spec expected to see tolerated did not even arise.

De-collision: on `demo-001` the two runs picked **different** moments
(`…763b` vs `…763c`). On `demo-002` they picked the **same** moment
(`01a0493c-387d-7c58-a05f-a5e659b20caa`); both approvals still succeeded,
because each run approved its own distinct artifact row on that shared moment.

### Post-run state

```
SELECT count(*) FROM artifact WHERE title LIKE 'eval-gate-probe-%';  ->  0
SELECT count(*), state FROM artifact GROUP BY state;                 ->  6 | extracted
```

**All 6 original subject artifacts are still `extracted`.** No run consumed
shared corpus state. This is story 11.3's central claim and it held under
concurrency: the old one-way consumption of subject `extracted` rows is gone.

---

## 6. Was either run disturbed?

### By the concurrent `make test` — No.

The projection file lock is keyed by store URLs. The dev-store lock is
`meetingminer-projections-262fe3fa5a97e4f3.lock`
(`sha256("bolt://localhost:7687|http://localhost:7700")[:16]`); the test suite's
lock is `meetingminer-projections-1ab8752cbda51df7.lock`
(`bolt://localhost:7688|http://localhost:7701`). They are different files, and
the holder sidecar observed mid-run
(`{"holder": "server test suite (projection stores)", "pid": 94534}`) was on the
**twin** key. `server/tests/test_projections_locks.py` redirects
`store_lock_paths` to `tmp_path`, so it never contends with the real lock
either. `make test` passed 1733 tests, exit 0. AGENTS.md's existing claim that
suites and dev-store writers hold different lock files is confirmed by
measurement.

### By the sibling eval run — YES, once, and it decided the `left` verdict.

**`left` / demo-002, 2.11 FAILED.** Its metrics read `artifacts: 3, states:
{extracted: 2, published: 1}` — but `demo-002` has only **2** subject artifacts.
The third row was `01a054ab-5b35-7d3d-adc3-6ce905d87916`, in state `published`:
**the `right` run's probe artifact**, caught mid-life by `left`'s
`corpus.artifacts_for(meeting_id)` read. `left` then applied the subject-half
rule ("published ⇒ present in both stores") to a row it did not mint, read the
stores after `right` had already erased it, and emitted:

```
published artifact 01a054ab-5b35-7d3d-adc3-6ce905d87916 is absent from meilisearch
  — projection-on-publish (story 4-4) has regressed: the approve route must land
    the artifact in both stores
published artifact 01a054ab-5b35-7d3d-adc3-6ce905d87916 is absent from neo4j — …
```

That is a **false blocking GATE VIOLATION caused entirely by the sibling run.**
The ownership filter the story built (`foreign_rows`, "response rows for
artifacts the run did not mint are ignored") applies to the **approve
response**, not to `corpus.artifacts_for()`. The subject half has no
`eval-gate-probe-%` exclusion, so a sibling's transient probe row is read as if
it were shared corpus state. The story removed the `nothing-to-approve`
collision but introduced this one in its place.

### A third, independent failure that concurrency did not cause

**`left` / demo-001, 2.11 FAILED** for a different reason: its own probe
`01a054ab-56b3-…` was approved (200 OK, own id published) but was **absent from
both stores afterward**. The main api's log gives the cause:

```json
{"ts": "2026-08-30T21:55:10.153664+00:00", "event": "artifacts.projection.failed",
 "artifact_ids": ["01a054ab-56b3-7b0e-8d7a-fe22c1bffe00"],
 "error": "ProjectionLockedError: projection of 1 published artifact scope(s) refused:
   the projection lock is held by pid 115992 (unnamed process, active) …",
 "recovery": "rebuild --meeting 01a04938-db21-7d02-a398-ccae92270853"}
{"ts": "2026-08-30T21:55:10.153758+00:00", "event": "moments.approved", …}
INFO: "POST /moments/01a04939-763b-…/approve HTTP/1.1" 200 OK
```

The approve route published the row in Postgres, had its store projection
**refused by the dev-store projection lock**, logged that, and **still returned
200**. Check 2.11 then correctly observed post-absence and reported it as a
story-4-4 regression — which it is not.

I could not identify pid 115992; it had exited by the time I looked and its
holder sidecar was removed on release. It was **not** the concurrent `make test`
(different lock file, per above) and **not** the sibling eval run (the evals
harness takes no projection lock, and both approvals went through the same
single api process, where the lock is reentrant). Several other agents were
working this repository at the time; the most likely explanation is an
unrelated dev-store writer in another worktree. **I am not able to prove what
held it, and I am not claiming otherwise.**

This is worth recording on its own merits, independent of 11.3: **the approve
route's projection is best-effort and a total projection failure is invisible
to the caller.** Check 2.11's probe therefore cannot distinguish "the publish
gate regressed" from "projection was locked out for 200ms". The story spec's
`Block If` clause anticipated a *partial* write (graph fails, search succeeds);
what actually occurs is a *total* refusal that still answers 200. Three of the
four probes projected fine, so there is no evidence of an actual story-4-4
regression.

---

## 7. Scorecard against the spec's expected observations

| Spec expectation | Result |
|---|---|
| Both runs exit on their own verdicts | **Yes** — both wrote a complete `deterministic-report.yaml` with `passed:` and exited on it (exit 2 from pytest failures, not a crash) |
| Two distinct `evals/runs/2026-*-left\|right` folders | **Yes** — `2026-08-30-left`, `2026-08-30-right`, no collision, no ownership refusal |
| Each report's 2.11 detail lists its own probe ids with cleanup verified | **Yes** — 4/4 probes listed with their own ids, `verified: true`, `problems: []` |
| `count(*) … 'eval-gate-probe-%'` is 0 afterward | **Yes — 0** |
| No `nothing-to-approve` failure caused by the sibling | **Yes — no 409 occurred at all** |
| *(implicit)* neither run's verdict is decided by the sibling | **NO — `left`'s demo-002 2.11 was failed by `right`'s probe row** |

Five of the six named expectations were met. The sixth — the one the whole
story exists to deliver — was not.

---

## 8. The sentence AGENTS.md should carry

Stated plainly: **the measurement does not support lifting the single-flight
rule yet.** The one-way state consumption is genuinely fixed — subject
artifacts survived untouched, probe cleanup was perfect, run folders are
per-run, and no `nothing-to-approve` occurred. But two overlapping runs still
failed each other, so the rule cannot yet become "runs may overlap".

Recommended sentence for the AGENTS.md bullet (11.3's lane applies it; this
file does not edit AGENTS.md):

> **`make evals-run` is still one at a time, for a narrower reason than
> before.** Runs no longer consume shared state — subject artifacts are read
> only, and each run mints, approves and erases its own probe (measured
> 2026-08-30: two overlapping runs, all four probes cleaned up, zero
> `eval-gate-probe-%` rows left, the shared corpus's `extracted` rows intact,
> and no `nothing-to-approve`) — but check 2.11 still reads a sibling's
> in-flight probe row through `corpus.artifacts_for()` and asserts it as a
> subject artifact, which failed one of the two runs with a false
> `projection-on-publish has regressed`. Overlapping runs are safe for the
> corpus and unsafe for the verdict. Concurrent `make test` in another
> worktree is fine and was measured green alongside both runs.

If the 11.3 lane closes the gap (exclude `eval-gate-probe-%` rows the run did
not mint from the subject half of 2.11, the same way `foreign_rows` already
excludes them from the approve response), then the rule can be lifted and the
sentence becomes the unqualified "runs may overlap each other and any suite".
That is a small, well-understood change, and this measurement is the evidence
for it.

## 9. Follow-ups this measurement raises

1. **[blocking for lifting the rule]** 2.11's subject half must ignore
   `eval-gate-probe-%` rows it did not mint. `evals/checks/test_publish_gate.py`
   builds `membership` from every row `corpus.artifacts_for()` returns.
2. **[server-side, not 11.3's to fix]** `POST /moments/{id}/approve` returns 200
   after a `ProjectionLockedError`. A caller cannot tell a published-and-projected
   artifact from a published-but-unprojected one, which makes 2.11's probe
   assertion unfalsifiable under lock contention. Relates to the standing
   "no silent fallbacks" rule.
3. **[minor]** `make start-api` reports `api: ready` when its own uvicorn failed
   to bind and a pre-existing api answered the health probe. The "ready" line is
   not evidence that the api it started is the api now serving :8000.

---

## Provenance

Every number above was read from: the two `deterministic-report.yaml` files, the
main checkout's `.logs/api.log`, `docker exec meetingminer-postgres psql`, the
lock sidecar in the system temp dir, and the captured stdout/exit codes of the
three commands. Nothing is estimated. Two eval runs were authorized and exactly
two were run; no run was retried.
