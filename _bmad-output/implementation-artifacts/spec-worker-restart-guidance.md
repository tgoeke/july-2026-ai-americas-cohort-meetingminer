---
title: 'Worker-stopped remediation states facts and makes no cost claim'
type: 'bugfix'
created: '2026-08-22'
status: 'done'
baseline_commit: '8b99f1c4dbb1500024777b688b21219b97cf0a9d'
review_loop_iteration: 2
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `/status` tells the owner that restarting the worker "resumes the paused backlog, which can make paid model calls — so start it only on a fresh explicit yes." Both halves are false under the committed config: the worker's only `llm.roles.*` call is `extraction`, bound to `ollama/gpt-oss:120b`, and the worker never invokes the paid `chat`/`judge` roles. The sentence is a hardcoded constant, so it reads the same whether the queue holds 850 jobs or zero — and it did block a real restart that turned out to claim nothing and cost nothing.

**Approach:** Replace the constant with a function that reports facts and renders no verdict: how much work is currently paused, which extraction binding this API process has loaded, and that a newly started worker reloads `config.yaml` rather than inheriting the API's snapshot. The endpoint must not claim that its loaded binding is necessarily the one a future worker will use, and it makes **no cost claim at all**. A first attempt derived cost by classifying the provider and failed open — an unrecognized prefix rendered as "spends no money" — so the cost judgement is removed rather than re-derived, and left to the owner who can see the binding.

## Boundaries & Constraints

**Always:**
- The remediation stays non-null while the worker is stopped (`status.test.tsx:180-187` requires it).
- "This page only reports; it never starts, restarts, or resumes anything." survives verbatim — SPEC constraint `spec-system-status/SPEC.md:35` — and is asserted in **every** branch that builds a remediation, not just one.
- The remediation names the binding this API process loaded as `` `llm.roles.extraction` `` with its model, and names `extraction.fallback` too whenever one is configured. It states that a newly started worker reloads `config.yaml`; it does not claim the API and future-worker snapshots match.
- State only what the worker path establishes: `extraction` is the worker's only **`llm.roles.*`** call. Do not call it the worker's only model stage — STT and the embedder are also models.

**Never:**
- **No cost claim, in any branch.** The worker remediation's authored prose must not contain "spend", "paid", "free", "no money", "costs", or "explicit yes". Exact primary/fallback identifiers are quoted configuration facts and are exempt from this vocabulary scan; they must remain unmodified. This is an invariant to assert, not a wording preference.
- Do not classify providers here: no `provider_of`, no `KEY_ENV_VARS`, no key-state reasoning in this function. Those stay in `_role_row`, where a key claim is about keys, not money.
- No change to `detail`, `WorkerStatus` fields, or any schema — message content only, so `make client` is not needed.
- Nothing on the status path starts, restarts, resumes, or requeues the worker.
- Do not correct the same stale premise in `SPEC.md`, `project-context.md`, `sprint-notes.md`, `ops-order.md`, or any `.memlog.md` — all logged in `deferred-work.md` under "worker restart guidance (2026-08-22)", and owned by `bmad-spec` / `bmad-project-context`.

**Ask First:**
- Removing "deliberately" from the worker `detail`. It asserts intent the endpoint cannot verify (a crashed worker reads identically), but it is owner direction of record at `status.py:370-372`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior |
|----------|--------------|---------------------------|
| Stopped, empty queue | `pending == 0` | Says no work is currently paused; names the API-loaded binding; says a new worker reloads `config.yaml`; no cost vocabulary in authored prose |
| Stopped, work waiting | `pending == 3` | Names the 3 paused job(s); names the API-loaded binding; says a new worker reloads `config.yaml`; no cost vocabulary in authored prose |
| Key-required binding | extraction `openai/gpt-5.2` | Identical shape and no cost vocabulary in authored prose — regression guard: this once emitted a spend gate |
| Unrecognized provider | extraction `gemini/gemini-2.5-pro` | Identical shape and no cost vocabulary in authored prose — regression guard: this once emitted "spends no money" |
| Vocabulary-bearing identifier | extraction `openrouter/example:free` | Identifier survives exactly; authored prose still carries no cost vocabulary |
| Fallback configured | `extraction.fallback` set | Fallback named exactly alongside the primary; authored prose still has no cost vocabulary |
| Worker running | advisory lock held | Unchanged: `remediation` is `None`; the stopped sentence is never built |
| Postgres down | `postgres_up` false | Unchanged: `state="unknown"`, existing stores remediation; the stopped sentence is never built |

</frozen-after-approval>

## Code Map

- `server/meetingminer/api/status.py:373-378` -- `_WORKER_STOPPED_REMEDIATION`, the constant to replace.
- `:381-414` -- `_worker_status(request, postgres_up)`. `pending` at `:397` is `queued + running`; correct for both, since `requeue_orphaned_jobs` (`server/meetingminer/worker/main.py:132`) re-queues crash-orphaned `running` jobs at startup. Reads no config today.
- `:423,446` -- `get_status` already binds `config: AppConfig = request.app.state.config` and calls `_worker_status(request, pg_up)`; thread `config` through for the binding name only.
- `:98` -- `WorkerStatus.remediation: str | None`. No model change needed.
- `:19-26` -- module docstring; `:23-26` pins the `` `llm.roles.<role>` `` spelling the sentence must use. Note `:19-21` claims remediation is "always the file contract" — stale for this row, logged as deferred, do not fix here.
- `server/meetingminer/pipeline/stages/extract.py:283-284` -- read-only evidence: the only `build_llm` in the worker path, on `roles.extraction`. `chat` is request-path (`api/chat.py:968`); `judge` is evals-only.
- `server/meetingminer/adapters/llm/__init__.py:140-148` -- read-only evidence: `fallback` is built as its own completer and engaged on any primary `LlmError`. That is why it must be named.
- `config.yaml:30-31` -- extraction `ollama/gpt-oss:120b`, fallback `ollama/qwen3:30b`.
- `server/tests/test_api_status.py:205-233` -- the single stopped-worker test to replace.
- `web/src/features/status/status.test.tsx:20-29,73-80,130-135` -- the `healthy()`/`degraded()` fixtures and the worker assertions. `degraded()` inherits `llmRoles[0]` from `healthy()`, so the fixture's extraction row and its worker remediation must name the same binding or the payload is one the server cannot emit.
- `web/src/features/status/status.ts:101-107` -- read-only evidence: `degradedRows` branches on `state`, never message text.

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/api/status.py` -- replace the constant with `_worker_stopped_remediation(pending: int, config: AppConfig) -> str` composing a claim clause and a binding clause, with no cost branch; add `config` to `_worker_status` and pass it at the `get_status` call site. Keep two blank lines before the new top-level `def` (E302).
- [x] `server/meetingminer/api/status.py` -- rewrite the owner-direction comment at `:370-372` to record that this row reports facts and renders no cost verdict.
- [x] `server/tests/test_api_status.py` -- replace the single stopped test with one case per matrix row. Assert the absence of the whole cost vocabulary, not one phrase. Vary the binding via a helper that also sets `fallback`. Annotate every helper parameter; type the raise-only stub `NoReturn`; document why the running-worker case needs `app_config` rather than `fake_secret_config` (`FAKE_SECRETS` would fail Postgres auth).
- [x] `server/tests/test_api_status.py` -- take the worker lock with `pg_try_advisory_lock` and assert it returned true, matching `worker/main.py:52` and making a leaked lock fail instead of hang. Put per-case reasoning in docstrings rather than a floating block comment.
- [x] `web/src/features/status/status.test.tsx` -- update the fixture so its `llmRoles` extraction row and its worker remediation name the same binding, and assert the rendered remediation carries no cost vocabulary.

**Acceptance Criteria:**
- Given any extraction binding — keyless, key-required, unrecognized, vocabulary-bearing, or with a fallback — when the worker is stopped, then the remediation's authored prose contains none of "spend", "paid", "free", "no money", "costs", "explicit yes", while primary/fallback identifiers survive exactly.
- Given the worker is stopped, then the remediation names the API process's loaded `` `llm.roles.extraction` `` model, names the fallback when one is configured, and states that a newly started worker reloads `config.yaml` rather than asserting the snapshots match.
- Given the worker is stopped under any config, then `overall` is `degraded` and `worker.remediation` is non-null and carries the read-only sentence verbatim.
- Given the worker is running or Postgres is down, then the stopped sentence is never built and `remediation` is `None` / the stores remediation respectively.

### Review Findings

- [x] [Review][Patch] Qualify the binding as the API's loaded snapshot and state that a new worker reloads `config.yaml` [server/meetingminer/api/status.py:396]
- [x] [Review][Patch] Preserve exact model identifiers while applying the no-cost-claim invariant only to authored prose [server/tests/test_api_status.py:121]
- [x] [Review][Patch] The tests do not protect the semantic no-cost-verdict requirement from unlisted wording [server/tests/test_api_status.py:54]
- [x] [Review][Patch] The restart claim has no stopped-worker regression case containing orphaned `running` jobs [server/tests/test_api_status.py:323]
- [x] [Review][Defer] LLM primary and fallback model fields accept empty or whitespace-only strings [server/meetingminer/config.py:168] — deferred, pre-existing

## Spec Change Log

- **Trigger:** review loop 2, Finding 2. The literal whole-string vocabulary ban contradicted the simultaneous requirement to preserve arbitrary model identifiers; `openrouter/example:free` demonstrated both rules could not be satisfied together.
- **Amended:** owner chose the prose-only invariant on 2026-08-22. Exact primary/fallback identifiers are configuration facts and remain unchanged; the banned vocabulary and broader no-cost-verdict requirement apply to authored prose around them. Identifier sanitization was explicitly rejected.

- **Trigger:** review loop 2, Finding 1. The API loads configuration at import (`api/main.py:42`), while `make worker` loads it again on startup (`worker/main.py:91`), so an edit between those events makes the API snapshot differ from the prospective worker snapshot.
- **Amended:** owner chose qualified-snapshot wording on 2026-08-22. The remediation reports the API-loaded extraction binding, says a newly started worker reloads `config.yaml`, and no longer predicts that the future worker necessarily uses the API's snapshot. Reloading config on the status request was explicitly rejected; there remains one loader lifecycle per process.

- **Trigger:** review loop 1. Three independent reviewers found the cost derivation fails open — any provider prefix outside the three-entry `KEY_ENV_VARS` map rendered as "served keyless by local {provider}, so starting it spends no money", demonstrated live for `gemini/`, `azure/`, `bedrock/`, `groq/`. A second confirmed defect: `extraction.fallback` was never consulted, so a keyless primary with a paid fallback also read as free.
- **Amended:** the root cause was the frozen constraint "classify paid-vs-free only through `KEY_ENV_VARS`; never hardcode provider names", which is fail-open by construction — so this was an intent_gap, not a patch. The owner renegotiated the intent: drop the cost claim entirely and report facts instead. The classification requirement, the conditional spend warning, and the four spend-gate matrix rows are all removed; two regression rows (key-required and unrecognized provider) replace them.
- **Known-bad state avoided:** an endpoint whose whole purpose is to stop misinforming the owner about spend, silently telling them a paid provider is free.
- **KEEP:** deriving the claim clause from `pending` (`queued + running`) worked and was never in question. So did threading `config` through `_worker_status` from the existing `get_status` binding, the fail-safe instinct in the Design Notes, and the two matrix rows for worker-running and Postgres-down with raise-if-reached stubs proving the stopped branch is not entered. The `pg_try_advisory_lock` correction and the web fixture self-consistency fix are carried in as tasks.

## Design Notes

The first attempt replaced a frozen false premise with a derived one and inherited a new failure mode: `KEY_ENV_VARS` answers "which env var holds this provider's key", and its own comment says an unknown prefix "gets no key opinion here" — absence is not evidence of keyless. Reading it as a free/paid oracle turned a missing map entry into a money claim.

Naming the API process's loaded binding without judging it gives the owner a concrete configuration snapshot while avoiding a cost verdict. A newly started worker reloads `config.yaml`, so the message identifies that snapshot's scope and does not predict which binding the future process will load.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_api_status.py` -- expected: pass, one case per matrix row.
- `cd web && pnpm vitest run src/features/status` -- expected: pass.
- `curl -s localhost:8000/status | python3 -m json.tool` -- expected: worker running ⇒ `remediation` null.

## Suggested Review Order

**Fact-only worker guidance**

- Compose current queue and API-loaded binding facts without a cost verdict.
  [`status.py:384`](../../server/meetingminer/api/status.py#L384)

- Count queued and crash-orphaned running jobs before building stopped guidance.
  [`status.py:413`](../../server/meetingminer/api/status.py#L413)

**Invariant verification**

- Pin every authored word while preserving arbitrary configuration identifiers.
  [`test_api_status.py:111`](../../server/tests/test_api_status.py#L111)

- Prove the paused snapshot includes queued and orphaned running jobs.
  [`test_api_status.py:403`](../../server/tests/test_api_status.py#L403)

- Exercise vocabulary-bearing primary and fallback identifiers independently.
  [`test_api_status.py:482`](../../server/tests/test_api_status.py#L482)

- Keep UI fixture prose separate from exact primary and fallback values.
  [`status.test.tsx:65`](../../web/src/features/status/status.test.tsx#L65)

**Deferred documentation**

- Record pre-existing configuration and status-contract gaps outside this story.
  [`deferred-work.md:187`](deferred-work.md#L187)
