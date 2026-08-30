# Code Review — Story 5.4: LLM Judge Harness & Bake-Off

## Scope

- **Story branch:** `story/5-4` at `b5fe6dc`
- **Review branch:** `story/5-4-review`
- **Reviewed range:** `69b767b50a42c04ba726c707fb68f0f7aa113219..b5fe6dca634f01bb06e812d9e578198426e3b714`
- **Contract:** `_bmad-output/implementation-artifacts/spec-5-4-llm-judge-harness-bake-off-nice-to-have.md`
- **Mode:** full, spec-backed review

## Findings

### Artifact-backed judge runs cannot serialize PostgreSQL UUIDs

- **Location:** `evals/harness/corpus.py:150`
- **Severity:** high
- **Finding:** `artifact_from_row()` passes psycopg UUID values through even though `ArtifactRow` declares string identifiers. `run_judge()` places `artifact.id` in the YAML payload, and `yaml.safe_dump()` cannot represent `uuid.UUID`.
- **Evidence:** The real SQL selects UUID columns; the row mapper returns `id=id_` and `moment_id=moment_id`. The store-backed assertions stringify IDs before comparing, while the orchestration test uses string-only fakes. A direct `yaml.safe_dump({"item": UUID(...)})` raised `yaml.representer.RepresenterError` in this review.
- **Suggested direction:** Normalize artifact identifiers to canonical strings at the corpus boundary and cover an artifact-bearing `run_judge()` payload with real UUID objects.

### A candidate that fails during scoring can still win the bake-off

- **Location:** `evals/harness/bakeoff.py:293`
- **Severity:** medium
- **Finding:** Only the reachability probe excludes `LlmError`/`LlmUnavailableError`. Later calls pass through `score_with_llm()`, which converts the failure to an inapplicable `passed=False` score, so the candidate remains eligible for agreement and selection.
- **Evidence:** A candidate can pass the probe then fail every scored request. Those false scores agree with every `gold_passed: false` item and can beat a functioning candidate, contrary to the contract requiring an unavailable/erroring candidate be recorded as excluded.
- **Suggested direction:** Propagate scoring-call failures to candidate-level exclusion (with the error recorded) rather than treating them as ordinary scored failures.

### Reports omit models from retry, probe, and later repeat calls

- **Location:** `evals/harness/judge.py:254`; `evals/harness/bakeoff.py:298`
- **Severity:** medium
- **Finding:** Retry handling overwrites the first reply model, while bake-off serialization retains only first-repeat scores and discards probe and later-repeat models.
- **Evidence:** The frozen contract requires the exact `LlmReply.model` string for each call. The report therefore cannot show all models that actually received a paid request or contributed to consistency.
- **Suggested direction:** Record call-level provenance for every probe and scoring attempt, including retries and all repeats, while preserving the first-repeat score used for agreement.

### Malformed bake-off samples are silently coerced into different rubric inputs

- **Location:** `evals/harness/bakeoff.py:150`
- **Severity:** medium
- **Finding:** `load_sample()` stringifies candidate text/transcript, applies truthiness to `citation_present`, and turns any iterable into `required_terms` without type validation.
- **Evidence:** For example, YAML `citation_present: "false"` becomes true and a scalar string `required_terms` becomes a tuple of characters. The bake-off can then choose a model from a sample other than the human-authored gold data the operator supplied.
- **Suggested direction:** Validate each optional sample field's documented type and refuse malformed entries with a named `BakeoffError`.

### The judge accepts replies that omit the required reason field

- **Location:** `evals/harness/judge.py:198`
- **Severity:** low
- **Finding:** `_parse_judge_reply()` validates only the two boolean verdicts despite the required JSON schema also containing a string `reason`.
- **Evidence:** A reply containing only `faithful` and `no_unsupported_claims` is accepted, rather than consuming the single retry reserved for malformed responses; the human-facing reason promised by the prompt is absent.
- **Suggested direction:** Validate `reason` as a string (and retain it in the recorded result if that is the chosen report shape).

### Failed report serialization can permanently consume an immutable run folder

- **Location:** `evals/harness/judge.py:387`; `evals/harness/bakeoff.py:342`
- **Severity:** medium
- **Finding:** The judge writer first creates an empty destination path, and the bake-off writer writes directly to its final path. A serialization or I/O failure can leave an empty/truncated report in a run folder that the immutability guard refuses to reuse.
- **Evidence:** The UUID serialization defect above takes exactly this path: `_write_yaml_once()` claims `llm-judge-report.yaml`, then `safe_dump()` raises and leaves the empty claimed file. Bake-off has the same non-recoverable outcome if its direct `write_text()` fails after paid calls.
- **Suggested direction:** Make both report writes failure-atomic and release only a failed, incomplete claim so the run remains retryable; retain the write-once refusal after a successful report is committed.

### Direct bake-off use validates repeats too late

- **Location:** `evals/harness/bakeoff.py:266`
- **Severity:** low
- **Finding:** The CLI rejects `--repeats < 1`, but public `run_bakeoff()` does not validate it before `Run.create()`.
- **Evidence:** A direct `repeats=0` call creates the immutable folder and snapshot, then indexes the empty `repeat_scores` list and crashes.
- **Suggested direction:** Validate `repeats >= 1` at the start of `run_bakeoff()` before creating a run folder, with regression coverage for direct callers.

### The committed default candidate file is not checked for all required pools

- **Location:** `evals/bakeoff-candidates.yaml:16`
- **Severity:** low
- **Finding:** No test loads the shipped default candidate file and verifies that frontier API, local Ollama, and hosted open-weight pools are all represented.
- **Evidence:** `load_candidates()` only requires a nonempty list, and its positive test deliberately uses a two-pool temporary file. Removing one committed candidate remains a valid, green configuration while violating the bake-off's three-pool contract.
- **Suggested direction:** Add a store-free regression test for the committed default configuration's required pool coverage.

## Verification

- `uvx ruff check --isolated evals/` — passed.
- Focused judge/bake-off/boundary tests — 114 passed.
- `make evals-test` — 447 passed.
- Both manual CLI `--help` commands completed without a network call.
- `evals/checks/test_corpus_artifacts.py` could not run: the shared Postgres rejected the reviewer worktree connection because no password was available (`fe_sendauth: no password supplied`).

## Triage

- **Patch:** 8 applied (high 1, medium 4, low 3)
- **Deferred:** 0
- **Dismissed as noise or unreachable:** 6

## Remediation Verification

- All eight findings were fixed on this review branch.
- `uvx ruff check --isolated evals/` passed.
- Focused judge/bake-off/boundary suite: **123 passed**.
- `make evals-test`: **456 passed**.
- The store-backed corpus command remains unverified in this reviewer worktree because its shared Postgres connection lacks a password.
