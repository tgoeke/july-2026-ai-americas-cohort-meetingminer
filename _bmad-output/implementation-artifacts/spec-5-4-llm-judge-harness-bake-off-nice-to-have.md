---
title: 'Story 5.4: LLM Judge Harness & Bake-Off (nice-to-have)'
type: 'feature'
created: '2026-08-20'
status: 'done'
baseline_revision: 'f20b8e4acdd33909ed1dc42f4f0d304847ef6458'
baseline_commit: '40c71719d956ae8d97f731c5323920307b377fca'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/specs/spec-meetingminer/eval-design.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-2-deterministic-capture-checks.md'
warnings: ['oversized']
deferred:
  - summary: >-
      POST /chat is corpus-wide, not meeting-scoped, so run_judge's per-meeting
      Q&A scoring has no way to confirm a returned citation belongs to the
      meeting being scored rather than another ingested scripted meeting.
    evidence: |-
      server/meetingminer/api/chat.py's /chat route takes only a question, no
      meeting filter. run_judge (evals/harness/judge.py:_score_qa_items) calls
      ask_chat with just the planted question and trusts citations[0] verbatim.
      With exactly one scripted meeting ingested today this cannot manifest,
      but if a second scripted meeting with similar planted content were
      ingested, a correct-sounding answer citing the wrong meeting's moment
      would still score faithful against that wrong moment's transcript.
      Pre-existing chat API constraint, not introduced by this story.
    location: >-
      evals/harness/judge.py (_score_qa_items); server/meetingminer/api/chat.py
    severity: low
  - summary: >-
      The bake-off's winner selection has no minimum-agreement floor: a lone
      surviving candidate with low absolute agreement still wins outright.
    evidence: |-
      _select_winner's `len(tied) == 1` short-circuit returns that candidate
      regardless of its agreement score. eval-design §7 describes the grading
      order (agreement, then consistency, then pool) but sets no acceptance
      threshold a winner must clear. The report still records the exact
      agreement score for a human to judge before editing config.yaml, so this
      is an open policy question for eval-design rather than a code defect.
    location: >-
      evals/harness/bakeoff.py:_select_winner
    severity: low
---

<intent-contract>

## Intent

**Problem:** Tier-2 judging (eval-design §3) has a `judge` LLM role already reserved in
`config.yaml` and defaulted to the chat model, but nothing selects it empirically and nothing
calls it. Every quality claim rubric 2.7 gates (ADR/decision faithfulness, cited Q&A quality) would
be asserted by the same model that also answers chat, chosen by fiat rather than by measured
agreement with human judgment — exactly what FR29 and eval-design §7 exist to prevent.

**Approach:** Add a rubric-2.7 scorer behind the `Llm` port (AD-8), a bake-off CLI that runs
candidates from all three pools (frontier API, local Ollama, hosted open-weight) blind against a
committed sample scored gold by a human, and a second CLI that runs the pinned judge over a real
run's extraction/Q&A outputs into `llm-judge-report.yaml`. Both are manual, RUNBOOK-invoked CLIs —
neither runs under `make evals-test` or `make evals-run` — because the frontier and hosted-open-weight
pools cost real money per call and must never fire unattended.

## Boundaries & Constraints

**Always:**
- No automated test (`make evals-test`, pytest collection of any kind) calls a real LLM. Every
  test exercises `judge.py`/`bakeoff.py` against a fake `Llm` stub. Real invocation is
  `python -m evals.harness.bakeoff` / `python -m evals.harness.judge`, run by a human, documented in
  `evals/RUNBOOK.md` — mirroring `verdict.py`'s existing manual-CLI, not-pytest-collected pattern.
- Rubric 2.7's four criteria split by how they're decided, not left to LLM judgment where code
  already can: `citation_present` and `contains_required_terms` are computed mechanically (citation
  array non-empty; normalized substring match against `answer_must_contain`); only `faithful` and
  `no_unsupported_claims` are asked of the judge model. `passed` is the conjunction of all four.
- A candidate/judge call receives only text already derived in Postgres or via the public API —
  transcript segments, `qa` answers, `artifact.title`/`body` — never a recording path or media
  bytes (AD-12's judge-scoped egress rule). Enforced by a boundary test asserting `judge.py` and
  `bakeoff.py` import nothing from `meetingminer.pipeline`/`.projections`/`.worker` and never read
  `MM_CONTENT_ROOT`/`MM_DROPS_ROOT`, mirroring `evals/tests/test_harness_boundary.py`'s existing guard.
- The bake-off's per-candidate `Llm` is built with `fallback=None` — substitution would attribute a
  reply to the wrong exact model id, which is the one thing the bake-off exists to pin.
- Extraction items are read read-only from the `artifact` table (`corpus.py`'s only-DB-module rule,
  story 5.2) — never via a new API route, since story 4.3 (which would add one) is still backlog.
- A candidate that raises `LlmUnavailableError`/`LlmError` is recorded as excluded with the error,
  never silently dropped from the report or silently substituted.
- An agreement tie between candidates is never broken by iteration order. It resolves by
  `--repeats`-based consistency (fraction of items scored identically across repeats) when
  `--repeats > 1`, then by pool order (local-ollama, hosted-open-weight, frontier-api); if still tied
  with `--repeats == 1`, `winner` is written `null` and the tie is named — no arbitrary pick.
- `bakeoff-report.yaml` and `llm-judge-report.yaml` are written once per run folder via `Run.create`
  (story 5.2's immutability/config-snapshot rule), and record the exact `LlmReply.model` string per
  call, not the configured role's nominal model.

**Block If:** none — every open question above is resolved by this spec.

**Never:**
- No change to `evals/harness/run.py`, `checks.py`, `corpus.py`'s public surface beyond one addition
  (`artifacts_for`), `conftest.py`, or any story 5.2/5.3 file's Tasks — new logic lives in new modules.
- No new pytest module under `evals/checks/` (store-backed, pytest-collected) for judge/bake-off —
  that would make a real, possibly-paid LLM call part of `make evals-run`.
- No write to `config.yaml`'s `llm.roles.judge` by any code path. Pinning the bake-off winner there
  is a human edit the RUNBOOK documents as the next manual step; `AD-10` config bindings are edited
  by humans.
- No `evals/bakeoff-candidates.yaml` entry with a hardcoded API key; keys stay in `.env`,
  resolved the same way `LiteLlmCompleter` already resolves them.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Judge call parses | Judge model replies with valid `{"faithful":bool,"no_unsupported_claims":bool,"reason":str}` JSON | `RubricScore` built, `passed` = AND of all four criteria | No error expected |
| Judge reply unparsable | Non-JSON or missing keys | One retry with a stricter prompt; still bad → item recorded not-applicable naming the raw reply, never silently passed | Recorded defect, not a crash |
| Candidate unreachable | `LlmUnavailableError` from `build_llm(...).complete()` | Candidate excluded from the round; report names it and the error | No exception escapes `run_bakeoff` |
| Mechanical citation check | Q&A item with empty `citations` | `citation_present=False`, `passed=False` regardless of judge output | No LLM call needed for this criterion |
| Extraction item | `artifact` row + its moment's covering transcript segments | Judge scores `faithful`/`no_unsupported_claims` against that transcript; `citation_present` is mechanically true (FK-backed) | No error expected |
| Agreement tie, `--repeats=1` | Two candidates score identical agreement with gold | `winner: null`, tie named in report | Never an arbitrary pick |
| Agreement tie, `--repeats>1` | Same, but consistency differs | Higher-consistency candidate wins; both scores recorded | No error expected |
| Empty sample or empty candidate list | `--sample`/`--candidates` file has zero items/candidates | Bake-off refuses before scoring, naming which is empty | Named failure, never a vacuous winner |

</intent-contract>

## Code Map

- `server/meetingminer/adapters/llm/port.py:24-82` -- `Llm` Protocol, `LlmOptions`, `LlmReply`
  (`.model` is the exact id that answered — what gets pinned), `LlmError`/`LlmUnavailableError`.
- `server/meetingminer/adapters/llm/__init__.py:63-109` -- `build_llm(role_binding, providers, log)`
  and `FallbackLlm`; `RoleBinding` (40-56) is a structural Protocol matching
  `meetingminer.config.LlmRoleBinding` field-for-field, so candidate bindings can be built with the
  real `LlmRoleBinding` class (already the sanctioned import per 5.2's boundary allowance).
- `server/meetingminer/config.py:141-179` -- `LlmRoleBinding` (model, fallback, base_url,
  fallback_base_url, timeout_seconds, num_ctx) and `LlmRoles` (`extra="forbid"`, so bake-off
  candidates are never added as new config roles — they are ad-hoc `LlmRoleBinding` instances built
  in-memory from `evals/bakeoff-candidates.yaml`, not new keys under `llm.roles`).
- `config.yaml:69-71,80-88` -- current `judge` role (defaults to chat model) and the `providers` map
  (`anthropic`, `openai`, `openrouter`, `ollama`) every candidate resolves through unchanged; hosted
  open-weight candidates (e.g. Kimi) route as `openrouter/<model>`, local candidates as `ollama/<tag>`.
- `server/meetingminer/pipeline/stages/extract.py:209-238,274-277` -- the extraction-role calling
  convention to mirror: bind role → `build_llm` → `.complete()` in a `try/except LlmError` with one
  retry on parse failure. `judge.py`'s `score_with_llm` follows the same shape.
- `server/meetingminer/api/chat.py:858-882,944-946` -- the `POST /chat` calling convention (AD-16
  public-API read) for pulling a real Q&A answer + its `citations` array for a planted `qa` entry.
- `server/meetingminer/migrations/0009_artifacts.sql:15-44` -- `artifact` (`kind`, `state`, `title`,
  `body`, `moment_id`, `meeting_id`, `provenance`). `provenance` is explicitly commented as what "the
  Epic 5 eval harness snapshots per run" — confirms the intended read path is this table directly,
  not a not-yet-built API route (story 4.3, still backlog).
- `server/meetingminer/api/moments.py:496-556` -- `_COVERING_SEGMENTS` query shape to mirror for
  reading an artifact's moment's transcript (the judge's faithfulness haystack).
- `evals/ground-truth.schema.json:108-150` -- `planted.decisions`/`planted.action_items` and `qa`
  (`question`, `expected_moment`, `answer_must_contain`) — the fixture fields rubric 2.7 judges.
- `evals/harness/run.py:206-260` -- `Run.create(run_id, config=...)`: folder creation, immutability
  refusal, redacted config snapshot. Reused as-is for both `bakeoff-<date>/` and a real run's
  `llm-judge-report.yaml`; its `write_report`/`record` (checks-specific) are not reused — the new
  modules write their own YAML via `run.folder / <name>`.
- `evals/harness/corpus.py` -- the one DB-connection module (5.2's boundary rule); gains
  `artifacts_for(meeting_id)` (read-only, mirrors `captures_for`'s row-to-dataclass shape) and
  `segments_for_moment(moment_id)` mirroring moments.py's `_COVERING_SEGMENTS`.
- `evals/harness/verdict.py:432-444` -- the `main()`/`argparse`/`python -m evals.harness.<module>`
  CLI convention `judge.py`/`bakeoff.py` follow; also the "manual CLI, not pytest-collected" precedent.
- `evals/tests/test_harness_boundary.py` -- extend with the no-media-import guard for the two new
  modules, same AST-guard convention as the existing one-network/one-database-module tests.
- `evals/RUNBOOK.md:255-270` -- Step 4, currently "Not yet built" placeholder text naming exactly
  the artifacts and sequence this story implements; replace with the real procedure and commands.
- `_bmad-output/specs/spec-meetingminer/eval-design.md:213-226` -- §7, the frozen bake-off contract
  this story implements; gains an additive note (5.1/5.2 discipline) pinning the judge JSON schema,
  the mechanical-vs-LLM criterion split, and the tie-break algorithm.

## Tasks & Acceptance

**Execution:**
- `evals/harness/judge.py` -- new: `JudgeItem` (qa | artifact variant), `RubricScore`
  (`faithful`, `citation_present`, `contains_required_terms`, `no_unsupported_claims`, `passed`,
  `raw_reply`), `build_judge_prompt(item)`, `score_with_llm(llm, item)` (one retry on unparsable
  JSON, then a recorded not-applicable result), `main()` CLI: `python -m evals.harness.judge
  <run-folder> --meeting-id ...` scoring real qa/artifact items with the pinned
  `config.settings.llm.roles.judge` binding, writing `llm-judge-report.yaml` (never touching
  `deterministic-report.yaml` or `Run.passed`).
- `evals/harness/bakeoff.py` -- new: `Candidate` (pool, `LlmRoleBinding`, label), `load_candidates`,
  `Sample`/`GoldVerdict`, `load_sample`, `agreement()`, `consistency()`, `run_bakeoff(run_id,
  candidates, sample, config, *, repeats=1)` implementing the tie-break order above, `main()` CLI:
  `python -m evals.harness.bakeoff --run-id bakeoff-<date> --candidates
  evals/bakeoff-candidates.yaml --sample <path> [--repeats N]`, writing `bakeoff-report.yaml` via
  `Run.create`.
- `evals/harness/corpus.py` -- extend: `artifacts_for(meeting_id)`, `segments_for_moment(moment_id)`,
  both read-only, both unit-tested store-free for their row mapping (mirroring 5.2's
  `capture_from_row` review fix).
- `evals/checks/test_corpus_artifacts.py` -- new, store-backed: `artifacts_for`/`segments_for_moment`
  against real Postgres rows. No LLM call — this is `corpus.py`'s own query coverage, distinct from
  the judge/bake-off "no pytest-collected LLM call" rule above.
- `evals/bakeoff-candidates.yaml` -- new: one entry for each of the three pools (frontier API, local
  Ollama, hosted open-weight), each an `LlmRoleBinding`-shaped mapping plus `pool`/`label`.
- `evals/bakeoff-samples/sample-001.yaml` -- new: a small (3-5 item) committed fixture mixing qa and
  artifact items with authored human gold verdicts, used by the CLI's `--sample` and by tests.
- `evals/tests/test_judge_scoring.py` -- new, store-free: prompt construction, JSON parse + one-retry
  behavior, the mechanical/LLM criterion split, the no-media-content assertion, against a fake `Llm`.
- `evals/tests/test_bakeoff.py` -- new, store-free: `agreement`/`consistency` math, the tie-break
  order (including the `--repeats==1` unresolved-tie case), candidate/sample schema validation,
  empty-sample and empty-candidate refusal, against fake `Llm`s with scripted replies.
- `evals/tests/test_harness_boundary.py` -- extend: the no-media-import AST guard covering
  `judge.py` and `bakeoff.py`.
- `evals/RUNBOOK.md` -- replace Step 4's placeholder with the real procedure: bake-off first (with
  the cost/manual-invocation note), then judge scoring, both via the CLIs above.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` -- additive note under §7 recording: the
  judge JSON schema, the mechanical-vs-LLM split for the four criteria, and the tie-break order.

**Acceptance Criteria:**
- Given the three candidate pools in `evals/bakeoff-candidates.yaml` and a committed sample with
  human gold verdicts, when `python -m evals.harness.bakeoff` runs, then every candidate is scored
  blind against the same sample, agreement with gold is computed per candidate, and the winner is
  written to `bakeoff-report.yaml` in `evals/runs/bakeoff-<date>/` pinned by the exact `LlmReply.model`
  string that answered.
- Given a frontier-api or hosted-open-weight candidate, when it is scored, then the prompt sent to it
  contains only transcript-derived text (never a recording path or media bytes), asserted by a
  boundary test.
- Given the pinned judge role and a real eval subject's extracted artifacts and Q&A answers, when
  `python -m evals.harness.judge` runs, then `llm-judge-report.yaml` records each item's rubric score
  and the exact judge model id/version, and this report never affects `deterministic-report.yaml` or
  `Run.passed`.
- Given no automated test suite (`make evals-test`, `make evals-run`), when either runs, then no real
  LLM network call occurs — every judge/bake-off test exercises a fake `Llm`.
- Given two candidates tied on agreement with `--repeats=1`, when the bake-off completes, then
  `winner` is `null` and the tie is named in the report rather than resolved arbitrarily.
- Given a later change to the pinned judge model, when the runbook's rerun rule (eval-design §4.7,
  already in force) is followed, then prior verdicts are treated as invalidated — no new code is
  needed for this since the rule already names "a judge-model change" explicitly.

## Design Notes

**Why two separate manual CLIs instead of one pytest-collected suite.** Every other harness surface
this epic has built runs under `make evals-test` (free, store-free) or `make evals-run` (store-backed,
free — Postgres and the public API cost nothing to call). This story's core operation calls paid
cloud APIs (Anthropic, OpenAI-compatible hosted open-weight) by design — that is the whole point of
comparing pools. Folding that into a pytest suite would make `pytest`/`make test` a money-spending
operation by accident the first time someone runs the full suite. `verdict.py` already established
the "manual, argparse, `python -m evals.harness.<module>`, RUNBOOK-documented, not pytest-collected"
shape for an operator-run step; this story reuses it rather than inventing a second convention.

**Why citation-present and required-terms are computed, not judged.** Rubric 2.7 lists four criteria
under "LLM judge" grading, but two of them — a citation array being non-empty, and a normalized
string being a substring of another — are exactly the kind of fact an LLM answers less reliably than
a three-line function. Story 5.2 already set the precedent (the fuzzy-match threshold, the
distinct-captures definition) of pinning an implementation-level reading the higher-level spec left
open; this is the same move; scoping the LLM to genuinely subjective judgment (faithfulness,
unsupported claims) keeps the judge's job — and its cost — proportional to what only it can decide.

**Why extraction items read `artifact` directly instead of waiting for story 4.3's API.** AD-16 permits
direct read-only Postgres queries, not only the public API, and `0009_artifacts.sql`'s own comment
says the eval harness is the intended reader of `provenance`. Story 4.3 (per-moment approval/publishing)
is still backlog; blocking this story on it would make a nice-to-have depend on an unstarted one for no
architectural reason the spine states.

## Verification

**Commands:**
- `uvx ruff check --isolated evals/` -- expected: clean.
- `uv run --project server pytest evals/tests/test_judge_scoring.py evals/tests/test_bakeoff.py
  evals/tests/test_harness_boundary.py -q` -- expected: passes, store-free, no real LLM call (grep
  the test files for any provider SDK import or live HTTP client to confirm none is used).
- `make evals-test` -- expected: still passes with the new store-free tests included; no api, no
  Docker store, no run folder left behind.
- Manual: `python -m evals.harness.bakeoff --help` and `python -m evals.harness.judge --help` both
  print usage without making a network call.

**Manual checks:**
- Grep `evals/harness/judge.py` and `bakeoff.py` for any import of `meetingminer.pipeline`,
  `.projections`, `.worker`, or a reference to `MM_CONTENT_ROOT`/`MM_DROPS_ROOT` — none should appear.
- Confirm `evals/bakeoff-candidates.yaml` contains no literal API key or token.
- Confirm neither new CLI is invoked from `infra/Makefile`.

## Spec Change Log

## Review Triage Log

### 2026-08-20 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 0, medium 6, low 7)
- defer: 2: (high 0, medium 0, low 2)
- reject: 8: (high 0, medium 0, low 8)
- addressed_findings:
  - `[medium]` `[patch]` `score_with_llm` called the judge model even when
    `citation_present=False`, which already forces `passed=False` — wasted a
    real, possibly-paid call on an item that could not pass regardless of the
    model's answer. Moved the skip from `_score_qa_items` (which had it) into
    `score_with_llm` itself so every caller, including the bake-off's direct
    calls, gets it.
  - `[medium]` `[patch]` `--meeting-id` could be repeated, causing a duplicate
    real `POST /chat` call and a duplicate scored item. `judge.py:main` now
    dedupes via `dict.fromkeys` before scoring.
  - `[medium]` `[patch]` `run_bakeoff` graded agreement from `repeat_scores[-1]`
    (the last repeat), so `--repeats` could silently change which pass was
    scored. Changed to `repeat_scores[0]`: agreement is always the first pass;
    repeats only ever feed the secondary consistency signal.
  - `[medium]` `[patch]` The bake-off's reachability probe only checked that
    `.complete()` did not raise, so a misconfigured candidate answering
    garbage instead of erroring proceeded into real, paid scoring calls. The
    probe now also rejects an empty/whitespace-only reply.
  - `[medium]` `[patch]` No test exercised `run_bakeoff`'s `repeats>1` wiring
    end-to-end — every existing test used the default `repeats=1`, so a bug in
    the accumulation feeding `consistency()`/`_select_winner()` would only
    surface on a real, paid run. Added an end-to-end `repeats=3` test with a
    scripted `FakeLlm` proving the actual wiring, not hand-built inputs.
  - `[medium]` `[patch]` `run_judge`'s entire orchestration (`run_judge`,
    `_score_qa_items`, `artifact_item`, `qa_item`) had zero test coverage —
    only the pure `score_with_llm`/`build_judge_prompt` layer was tested. Added
    `evals/tests/test_run_judge.py` covering the missing-folder refusal,
    already-judged refusal, unmatched `--meeting-id` refusal, the citation-skip
    path, and the happy path, all against fakes (no real network/LLM/store).
  - `[low]` `[patch]` The `try/except LlmError` around `run_bakeoff`'s
    repeat-scoring loop was dead code — `score_with_llm` catches `LlmError`
    internally and never propagates it. Removed the misleading wrapper.
  - `[low]` `[patch]` `_write_yaml_once`'s exists-check-then-write had a narrow
    TOCTOU window. Now claims the path atomically via
    `os.O_CREAT | os.O_EXCL | os.O_WRONLY`, catching `FileExistsError`.
  - `[low]` `[patch]` `bakeoff-report.yaml`'s per-candidate scores carried no
    item metadata (kind/manifest), unlike `llm-judge-report.yaml`. Now merges
    each item's `to_dict()` with its score, matching the other report's shape.
  - `[low]` `[patch]` `evals/RUNBOOK.md` didn't mention that
    `evals/checks/test_corpus_artifacts.py` now rides along under
    `make evals-run`, holding the shared Postgres briefly. Added a note.
  - `[low]` `[patch]` Checked whether `evals/RUNBOOK.md`'s step 4 repeats
    eval-design §7.1's named-tie operator guidance (re-run with `--repeats`
    raised, or extend the sample) where an operator reading the runbook would
    look. Confirmed it already does (RUNBOOK.md:300-301); no edit needed.
  - `[low]` `[patch]` `evals/bakeoff-candidates.yaml`'s hardcoded LAN address
    for the local-ollama candidate had no explanatory comment, unlike
    `config.yaml`'s identical value. Added one, mirroring that convention.
  - `[low]` `[patch]` `bakeoff.py`/`judge.py`'s `main()` only caught their own
    domain error, so any other failure (a `RunError`, a config-load error)
    surfaced as a raw traceback to an operator-facing CLI. Added a broad
    `except Exception` beneath the specific one in both.

## Auto Run Result

Status: done

### Review Findings — 2026-08-21

- [x] [Review][Patch] Artifact-backed judge runs cannot serialize PostgreSQL UUIDs [evals/harness/corpus.py:150] — fixed: IDs normalize to strings at the corpus boundary, with UUID-backed report serialization coverage.
- [x] [Review][Patch] A candidate that fails during scoring can still win the bake-off [evals/harness/bakeoff.py:293] — fixed: a failed scored call excludes the candidate and records its error.
- [x] [Review][Patch] Reports omit models from retry, probe, and later repeat calls [evals/harness/judge.py:254] — fixed: reports retain call-level model lists, probe model, and per-repeat call provenance.
- [x] [Review][Patch] Malformed bake-off samples are silently coerced into different rubric inputs [evals/harness/bakeoff.py:150] — fixed: optional fields are validated and malformed input is refused.
- [x] [Review][Patch] The judge accepts replies that omit the required reason field [evals/harness/judge.py:198] — fixed: `reason` is required, validated, and recorded.
- [x] [Review][Patch] Failed report serialization can permanently consume an immutable run folder [evals/harness/judge.py:387] — fixed: serialization completes in a temporary file and only a completed report claims the final path.
- [x] [Review][Patch] Direct bake-off use validates repeats too late [evals/harness/bakeoff.py:266] — fixed: `run_bakeoff()` validates repeats before `Run.create`.
- [x] [Review][Patch] The committed default candidate file is not checked for all required pools [evals/bakeoff-candidates.yaml:16] — fixed: store-free coverage pins all three pools in the shipped configuration.

### Independent Review Remediation — 2026-08-21

- Applied all eight review patches. New regression coverage includes UUID-backed artifact reporting, call-failure exclusion, retry/repeat model provenance, strict sample typing, required judge reasons, failed serialization cleanup, direct invalid-repeat refusal, and required default-pool coverage.
- `uvx ruff check --isolated evals/` passed; focused judge/bake-off/boundary tests passed **123**; `make evals-test` passed **456**.

**Implemented change.** A rubric-2.7 LLM-judge scorer behind the `Llm` port, a three-pool
(frontier-api, local-ollama, hosted-open-weight) bake-off, and a pinned-judge scorer for real
eval runs — both manual, RUNBOOK-invoked CLIs, never pytest-collected, so no automated suite can
trigger a real, possibly-paid LLM call. Rubric 2.7's four criteria are split: `citation_present`
and `contains_required_terms` are computed mechanically; only `faithful` and
`no_unsupported_claims` are asked of the judge model, and a missing citation skips the judge call
entirely (already-decided fail). Every candidate/judge call is tracked by the exact `LlmReply.model`
that answered, not the configured binding's nominal string. Extraction items read the `artifact`
table directly (read-only), since story 4.3's API route doesn't exist yet.

**Files changed.**
- `evals/harness/judge.py` — new; `JudgeItem`, `RubricScore`, `build_judge_prompt`,
  `score_with_llm` (mechanical/LLM criterion split, citation-skip, one retry, atomic write-once),
  `run_judge` + CLI.
- `evals/harness/bakeoff.py` — new; `Candidate`/`load_candidates`, `Sample`/`load_sample`,
  `agreement`/`consistency`/`_select_winner` (agreement from the first repeat, consistency/pool
  tie-break, never an arbitrary pick), `run_bakeoff` + CLI.
- `evals/harness/corpus.py` — extended; `artifacts_for`, `segments_for_moment`, read-only.
- `evals/checks/test_corpus_artifacts.py` — new, store-backed, no LLM call.
- `evals/bakeoff-candidates.yaml`, `evals/bakeoff-samples/sample-001.yaml` — new fixtures.
- `evals/tests/test_judge_scoring.py`, `evals/tests/test_bakeoff.py`, `evals/tests/test_run_judge.py`
  (new) — store-free, every LLM call is a fake.
- `evals/tests/test_harness_boundary.py` — extended: the `meetingminer.adapters.llm` allowance and
  the no-media-import/no-evidence-root guard for `judge.py`/`bakeoff.py`.
- `evals/RUNBOOK.md`, `_bmad-output/specs/spec-meetingminer/eval-design.md` (§7.1) — the real
  Step 4 procedure and an additive note pinning the judge JSON schema, the mechanical/LLM split,
  and the tie-break order.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — story marked in-progress.

**Review findings.** 13 patches applied (0 high, 6 medium, 7 low), 2 deferred (pre-existing,
low severity, not caused by this story), 8 rejected. Rejected as unreachable or already correct
given the code's actual structure, verified by reading `judge.py`/`bakeoff.py` directly rather
than trusting the reviewing subagents' hypotheses: a consistency-is-None tie-break path that
cannot occur because `repeats` is uniform per run; an `LlmRoleBinding` field-drop that cannot
happen because the class has exactly the six fields the code already passes; a duplicate-meeting_id
crash guarded upstream by 5.1/5.2's subject-matching rules; a missing-key crash on
schema-guaranteed manifest/response fields; a right-moment-cited check that belongs to eval-design
check 2.8 (human judge, unbuilt), not rubric 2.7; dead defensive fallback code the schema already
forecloses; and a `run_judge` fallback-forcing "gap" already correctly handled by per-call model
recording.

**Follow-up review recommended.** Patched this pass: 0 high, 6 medium, 7 low.
Score = 3×6 + 1×7 = 25, which is ≥ 5, so `true`.

**Verification performed.** All commands run by me after the patches:
- `uvx ruff check --isolated evals/` → **All checks passed!**
- `uv run --project server pytest evals/tests/test_judge_scoring.py evals/tests/test_bakeoff.py
  evals/tests/test_harness_boundary.py evals/tests/test_run_judge.py -q` → **114 passed**.
- `make evals-test` → **447 passed**, store-free, no api, no Docker store, no run folder created.
- `uv run --project server pytest evals/checks/test_corpus_artifacts.py -q` → **4 passed**, against
  the live shared dev Postgres; `evals/runs/` empty afterward.
- `uv run --project server python -m evals.harness.bakeoff --help` /
  `... -m evals.harness.judge --help` → usage only, no network call.
- Manual: grepped `judge.py`/`bakeoff.py` for `meetingminer.pipeline`/`.projections`/`.worker`
  imports and `MM_CONTENT_ROOT`/`MM_DROPS_ROOT` references — none found. Grepped
  `bakeoff-candidates.yaml` for a literal key/token — none found. Grepped `infra/Makefile` for
  either new CLI — not present.
- Matrix Test Audit: all 8 I/O & Edge-Case Matrix rows are covered by a test in the passing suites
  above (judge-parses, judge-unparsable-retry, candidate-unreachable, mechanical-citation,
  extraction-item, tie-at-repeats-1, tie-broken-by-consistency-at-repeats-gt-1,
  empty-sample-or-candidates).

**Residual risks.**
- `run_judge`'s live path (real `POST /chat` + real Postgres against a genuine scripted meeting)
  is exercised only against fakes — no scripted meeting is ingested yet (both ground-truth
  fixtures still carry placeholder `source_id`s, the same pre-existing gap story 5.2 documented).
  Designed state, not a defect.
- No real bake-off or real judge run has ever executed (confirmed: `evals/runs/` does not exist in
  this worktree) — by design, per this story's money-safety scoping. `config.yaml`'s
  `llm.roles.judge` is unchanged by this diff; pinning a real winner is the next, separate, human
  step the RUNBOOK documents.
- The two deferred items above (chat's lack of meeting-scoping, no minimum-agreement floor) are
  pre-existing/policy questions, not regressions from this story.
