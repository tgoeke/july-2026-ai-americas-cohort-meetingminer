# Review: search-wipe-fix (after-the-fact)

**Reviewer:** Claude (review agent), 2026-08-21
**Scope:** commit `88ac393` (diff vs its parent), merged into `main` at `2152934`
**Nature of this review:** after-the-fact. The fix was landed EXPEDITED, without
a dispatched review, because the live dev Meilisearch/Neo4j corpus was
observed actively shrinking (5 -> 3 moment docs) between verification steps —
active data loss in progress from a still-in-flight worktree running the
pre-fix test suite. This review does not gate a pending merge; it verifies the
already-landed fix was correct and complete, and flags anything that still
needs urgent follow-up.

## Summary of the change under review

`server/tests/conftest.py`'s `projection_stores` fixture was running
`drop_all` against the **dev** Meilisearch/Neo4j endpoints instead of
disposable twins. Every full server-suite run was wiping the live corpus
while Postgres `meeting_projection` kept reporting everything as projected —
the root cause of ui-5's zero-hit search.

Fix: two new disposable test-store containers (`neo4j-test` on 7475/7688,
`meilisearch-test` on 7701) in `infra/docker-compose.yml`; `conftest.py`
repoints the session `app_config` at the twins (env-overridable via
`MM_TEST_NEO4J_URI` / `MM_TEST_MEILI_URL`); a guard test in
`test_projections_search.py`; AGENTS.md amended with the new queueing
behavior.

## Findings

### 1. Isolation fix correctness — PASS

`infra/docker-compose.yml`'s `neo4j-test`/`meilisearch-test` twins use the
same digest-pinned images, env keys, and healthchecks as the dev stores;
only ports (127.0.0.1:7475/7688, 127.0.0.1:7701), container names, and named
volumes differ. `server/tests/conftest.py`'s `_repoint_stores_at_test_twins`
overrides `stores.neo4j.uri` / `stores.meilisearch.url` on the session
`app_config` (env-overridable via `MM_TEST_NEO4J_URI` / `MM_TEST_MEILI_URL`),
and the `projection_stores` fixture constructs its Neo4j driver and
Meilisearch client from that same `app_config` before calling `drop_all` —
so the wipe target is always the twin.

The commit also fixes a real second bypass: `client(test_pool, tmp_path)`
previously left `api_main.app.state.config` bound to whatever `api/main`
loaded from `config.yaml` at import time (the dev endpoints) — a store-backed
route test would seed data through the twin-pointed `app_config` fixture but
serve requests through a client reading the dev endpoints. The fix adds
`app_config` as a fixture dependency and sets
`api_main.app.state.config = app_config` inside the `client` fixture, which
closes that gap. `test_api_chat.py`'s `bind_chat_config` docstring
independently confirms this is a real, previously-live distinction
(`app/main` loads its own `AppConfig` instance at import).

Grepped all store-writing/reading constructs across `server/tests/` and
`server/meetingminer/`:
- `drop_all` appears only in `meetingminer/projections/stores.py` (definition),
  `meetingminer/projections/__init__.py:746` (the real `make rebuild` /
  `unproject` path — intentionally against the real config), and
  `tests/conftest.py`'s `projection_stores` fixture (against the twin
  `app_config`). No test calls it directly with a bypassed config.
- Every test file using `app_config` in `server/tests/*.py` derives its store
  clients from that fixture (checked `test_projections_locks.py`,
  `test_api_search.py`, `test_projections_graph.py`,
  `test_projections_search.py`).
- `test_parallel_store_safety.py` loads `config.yaml` directly (dev config)
  in a few places, but only to key the **lock file path**
  (`_projection_store_lock`/`_projection_lock_paths`) for cross-process lock
  tests — it never constructs a Neo4j driver or Meilisearch client from that
  config, so it never touches a real store. Not a bypass.
- No bare `meilisearch.Client(...)` or `neo4j.GraphDatabase.driver(...)`
  construction anywhere in `server/tests/` outside the `stores.py` helpers
  used via `app_config`.

Conclusion: no test-run code path reaches the dev Neo4j/Meilisearch. Verified
empirically too — see "Tests run" below: dev Meilisearch `moments` index
stayed at 1813 docs before and after running the guarded suites in this
worktree.

### 2. Guard test quality — PASS

`test_session_config_never_resolves_the_dev_stores` (`test_projections_search.py:525`)
re-loads `config.yaml` fresh on every run (`load_config(REPO_ROOT / "config.yaml", ...)`)
and asserts the session `app_config`'s `neo4j.uri` / `meilisearch.url` differ
from that freshly-loaded dev config's values. This is not a static "check the
override was applied once" test — it recomputes the dev baseline each run, so
if a future refactor removes or short-circuits
`_repoint_stores_at_test_twins` in the `app_config` fixture (or someone points
`MM_TEST_NEO4J_URI`/`MM_TEST_MEILI_URL` back at the dev ports), `test.neo4j.uri
== dev.neo4j.uri` and the assertion fails loudly, with a message naming the
live endpoint that would be wiped. Confirmed this actually ran and passed
(part of the 77/77 below).

One gap, non-blocking: the guard only checks that the *session `app_config`*
differs from dev — it does not independently re-verify that `projection_stores`
actually *builds its clients from* `app_config` (that's currently true by
inspection, not by a second assertion). A belt-and-suspenders version could
additionally assert on the constructed `neo4j.Driver`/`meilisearch.Client`
objects, but this is a minor strengthening opportunity, not a defect — the
current test already fails the way it's meant to on the identified regression
class (a lost or reverted override).

### 3. AGENTS.md caveat accuracy — PASS

The amended "What worktrees do NOT isolate" section in `AGENTS.md` accurately
describes: (a) the two test twins and their ports, (b) that test suites
resolve only the twins and skip (never fall back to dev) when twins are down,
(c) that the file lock now self-partitions by endpoint (`neo4j.uri|meilisearch.url`),
so test suites queue against test suites and dev-store writers (rebuild,
worker) queue against dev-store writers, with no cross-contention between the
two groups. This matches `infra/Makefile`'s `check-stores` target, which now
probes both dev endpoints (7700, 7687) *and* both test-twin endpoints (7701,
7688), and matches `server/meetingminer/projections/locks.py`'s
`store_lock_paths` (SHA-256 of `neo4j.uri|meilisearch.url`) which is exactly
the described self-partitioning mechanism. Ran `make check-stores` in this
worktree with all five containers up — passed silently (no errors), consistent
with the described behavior.

### 4. Remaining bypass paths — none found (see Finding 1 for the grep detail)

### 5. Recovery completeness — PASS, with a clarification

Postgres `meeting` table currently holds **34** rows (32 `real`, 2 `scripted`),
not 33. The rebuild's "33/33 meetings, 0 failed" claim in sprint-notes and the
merge commit is consistent with this: the 34th meeting
(`01a01f6c-f6e1-7671-8648-de26ce61cf63`, "Review 2.1b Live Intake") has no
`meeting_projection` row at all (never structural, never embedded) — its `job`
(`01a01f6c-f509-783d-98fb-f0d275e0f7da`) has `status = 'failed'` with
`error = "stage align failed: align has no transcript to derive from: the
drop provided no transcript and no STT source was recorded for this
meeting"`, timestamped 2026-08-20, a day before this break-fix landed. This
meeting failed at the `align` pipeline stage before extraction ever ran and
was never eligible for projection — `make rebuild` iterates meetings with
projections/eligible for projection, not raw `meeting` rows, so excluding it
from the 33 is correct, not a rebuild gap. **Not a finding requiring
follow-up** — it predates and is unrelated to the search-wipe-fix.

### Tests run

Brought up infra with `make infra-up` in this worktree (idempotent, safe —
all 5 containers, including the two test twins, came up healthy). Ran:

```
server/.venv/bin/python -m pytest tests/test_projections_search.py \
  tests/test_projections_graph.py tests/test_api_search.py -q
```

Result: **77 passed**, 1 unrelated deprecation warning (`httpx`/starlette
testclient), 123s. Matches the 77/77 claimed in the merge commit and
sprint-notes.

Checked the dev Meilisearch `moments` index (`GET /indexes/moments/stats`)
before and after this run: **1813 documents both times**, matching the
recovery figure in sprint-notes. Confirms empirically, not just by code
inspection, that this guarded suite run did not touch the live corpus.

## Verdict

**pass** — no blocking or urgent findings. The isolation fix is correct and
complete: every test-store-writing code path traced resolves through the
twin-pointed `app_config`, the client/route-serving bypass (`app.state.config`)
is also closed, the guard test fails meaningfully on the regression class it
targets, AGENTS.md's amended caveat matches the actual lock-partitioning and
`check-stores` behavior, and the recovery (33/33 projected meetings, 1813/1813
moments) is complete — the 34th Postgres meeting row is a pre-existing
`align`-stage pipeline failure unrelated to this break-fix, not an
under-recovery. Empirically verified: 77/77 on the three specified suites
against the test twins, dev Meilisearch corpus unchanged (1813 docs) across
the run, `make check-stores` clean against all 5 containers.

One minor, non-blocking suggestion for a future pass: strengthen the guard
test to also assert on the constructed store clients inside
`projection_stores`, not just the session config, for defense in depth against
a refactor that decouples client construction from `app_config`.

