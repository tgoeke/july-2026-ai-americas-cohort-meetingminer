---
title: 'Code Review: Worker Restart Guidance'
story: 'worker-restart-guidance'
reviewed_range: '8b99f1c4dbb1500024777b688b21219b97cf0a9d..7b88adb'
remediated_through: '3119d7c'
status: 'passed'
date: '2026-08-22'
---

# Code Review — Worker Restart Guidance

## Scope

- **Reviewer/tool:** OpenAI Codex, `bmad-code-review`
- **Repository:** `/Users/devopsterus/current/cohort/meetingminer`
- **Original branch:** `story/worker-restart-guidance`
- **Remediation branch:** `story/worker-restart-guidance-codex-review`
- **Reviewed range:** `8b99f1c4dbb1500024777b688b21219b97cf0a9d..7b88adb`
- **Final verified implementation head:** `3119d7c`
- **Spec:** `_bmad-output/implementation-artifacts/spec-worker-restart-guidance.md`
- **Note:** the story branch moved after the pinned review target; the original
  findings apply to the exact range above, while the
  resolutions and final verdict include the remediation through `3119d7c`.

## Findings

### 1. API and worker can use different configuration snapshots

- **Severity:** high
- **Action:** decision needed; specification amendment, then re-derivation
- **Location:** `server/meetingminer/api/status.py:396`; `server/meetingminer/api/main.py:42`; `server/meetingminer/worker/main.py:91`
- **Finding:** The remediation reports the extraction binding from the API's
  import-time `AppConfig`, but `make worker` starts a fresh process and reloads
  `config.yaml`. Editing the file without restarting the API makes the claimed
  future binding stale.
- **Concrete failure:** Start the API while extraction is bound to
  `ollama/gpt-oss:120b`, then edit `config.yaml` to `openai/gpt-5.2` and run
  `make worker`. `/status` still tells the owner the worker binding is Ollama,
  while the new worker loads OpenAI. This recreates the dangerous outcome the
  story exists to prevent: owner guidance can understate the operational
  consequence of a restart.
- **Why this is not a patch yet:** The frozen contract explicitly instructs the
  implementation to thread `request.app.state.config` into `_worker_status`.
  The owner must choose whether the remediation describes the API's loaded
  snapshot, reloads/compares the config file, or gains a shared config-version
  contract.

**Resolution (2026-08-22):** Owner selected the qualified-snapshot approach.
The amended contract requires the message to identify the API-loaded binding
and say that a new worker reloads `config.yaml`; it must not assert the two
snapshots match. Reloading config inside `/status` was rejected. This finding
is now a patch.

**Implemented:** `status.py` now labels the binding as this API process's
loaded snapshot, states that a new worker reloads configuration, and reports
the current paused-work snapshot without predicting successful startup.

### 2. The frozen cost-vocabulary invariant conflicts with exact model naming

- **Severity:** medium
- **Action:** decision needed; specification amendment, then re-derivation
- **Location:** `server/meetingminer/api/status.py:398-400`; `server/tests/test_api_status.py:121-124`
- **Finding:** The spec simultaneously requires exact primary/fallback model
  names and bans `spend`, `paid`, `free`, `no money`, `costs`, and `explicit
  yes` from the complete remediation for *any* extraction binding. Those rules
  cannot both hold when a configured identifier contains a banned token.
- **Concrete failure:** I rebound extraction to
  `openrouter/example:free` and called `_worker_stopped_remediation(1,
  config)` on the reviewed code. The returned remediation necessarily contains
  `free`, violating AC1 while correctly satisfying AC2 by naming the model.
- **Why this is not a patch yet:** Sanitizing the identifier violates exact
  naming; preserving it violates the literal blacklist. The likely resolution
  is to apply the no-cost-claim check to authored prose while exempting quoted
  configuration values, but that changes frozen intent and needs owner approval.

**Resolution (2026-08-22):** Owner selected the prose-only invariant. Exact
primary/fallback identifiers remain unchanged and are exempt from the vocabulary
scan; authored text remains subject to both the blacklist and the broader
no-cost-verdict rule. Identifier transformation was rejected. This finding is
now a patch.

**Implemented:** Primary and fallback identifiers remain exact. Server and web
tests apply the vocabulary scan only to authored prose, with independent
vocabulary-bearing primary and fallback cases.

### 3. Tests permit an unlisted cost verdict

- **Severity:** medium
- **Action:** patch after Finding 2's invariant is resolved
- **Location:** `server/tests/test_api_status.py:54-59,111-125`
- **Finding:** The test helper rejects six literal phrases, but the intent is
  semantic: the endpoint must render no cost verdict at all. Appending
  `Restarting will be billable.` to `_worker_stopped_remediation` avoids every
  blacklist term and leaves all positive assertions green.
- **Required result:** Pin the deterministic authored prose strongly enough
  that any new verdict fails, while implementing the identifier treatment
  selected for Finding 2. Confirm the new regression test fails against an
  intentionally unfixed/mutated implementation before accepting it.

**Resolution:** The server suite pins the complete deterministic remediation.
Appending `Restarting will be billable.` made the targeted test fail; removing
the mutation restored the pass.

### 4. Orphaned `running` jobs are absent from restart-count verification

- **Severity:** medium
- **Action:** patch
- **Location:** `server/meetingminer/api/status.py:427,443`; `server/tests/test_api_status.py:323-345`
- **Finding:** Production deliberately counts `queued + running` because worker
  startup requeues crash-orphaned running jobs. The only non-empty status test
  inserts queued rows. Passing only `jobs.get("queued", 0)` into the remediation
  would therefore leave the suite green.
- **Concrete failure:** After a crash leaves only running rows, that mutation
  reports `make worker` would claim no work even though
  `requeue_orphaned_jobs` immediately queues and processes them.
- **Required result:** Add a stopped-worker endpoint case with mixed queued and
  running jobs and assert the remediation count is their sum. Confirm the new
  test fails when the remediation is fed queued-only count.

**Resolution:** The endpoint suite now creates two queued jobs plus one orphaned
running job and requires the current paused-work count to be three. Feeding the
remediation queued-only count made that test fail; restoring `queued + running`
restored the pass.

### 5. LLM binding fields accept blank model identifiers

- **Severity:** medium
- **Action:** defer; pre-existing shared-config issue
- **Location:** `server/meetingminer/config.py:168-169`
- **Finding:** `model` and `fallback` are plain strings, so a valid `AppConfig`
  can contain empty or whitespace-only values. The new message then renders a
  blank binding. This predates the story and already affects the role status
  rows and worker execution; it belongs in shared config validation, not this
  message-only change. Recorded in `deferred-work.md`.

## Final review pass

Three fresh independent layers reviewed the remediated story. They found three
actionable gaps, all resolved in `e6345f6`: future-claim wording became a current
queue snapshot, vocabulary-bearing fallback coverage was added, and the web
assertion was scoped to authored prose. A follow-up inspection found no
remaining must-fix issue. The module-docstring mismatch and blank LLM binding
validation remain explicitly deferred.

## Triage notes

The four initial layers raised 24 raw hypotheses, normalized to 19 claims. The
initial triage retained five:
2 decision-needed, 2 patches, and 1 pre-existing defer. Fourteen were dismissed
as noise or frozen design choices, including requests to describe every worker
stage, omit the binding for an empty queue, name endpoint overrides, singularize
`job(s)`, and duplicate generic rendering coverage in the indicator.

## Verification

- `uv run --project server pytest server/tests/test_api_status.py -q` — 14
  passed, one Starlette deprecation warning.
- `cd web && pnpm vitest run src/features/status` — 5 passed.
- `cd web && pnpm lint` — exit 0; four pre-existing fast-refresh warnings.
- Deliberate mutations confirmed the new regressions are live: an added
  `billable` verdict, queued-only paused count, and sanitized
  `openrouter/example:free` fallback each failed their targeted test; each
  passed again after restoration.
- The requested `curl` reached an older API process on port 8000 and found the
  worker stopped, so it did not verify this branch or the expected running-row
  result. The running-worker endpoint branch is covered by the passing advisory
  lock integration case; the shared API process was not restarted across
  worktrees merely to satisfy a manual smoke command.

**Final verdict:** passed. No must-fix finding remains.
