# Review — Story 5-3 (2026-08-21)

**Review target:** `story/5-3`, `main...b8a9cb3fbfaddb220018eb872f01a146a6c736d5`.

## Scope and evidence

- Full branch diff: 22 files, 3,249 additions, 42 deletions.
- Contract reviewed: `spec-5-3-retrieval-publish-gate-checks.md`, including its
  frozen zero-subject and projection-on-publish caveats.
- Independent review layers: blind-hunter, edge-case-hunter,
  verification-gap, and acceptance-auditor. No layer failed. The acceptance
  audit found no direct acceptance-criteria violation.

## Triage

### Resolved decision

1. **[high] Prove that the API target is the same environment as the direct stores before approving.** `evals/checks/test_publish_gate.py:92-96` reads the corpus tag and artifacts from the local `AppConfig` database, `:135-136` opens that configuration's Meilisearch and Neo4j stores, and `:165-196` selects and approves through arbitrary `--api-base-url`. The Make target intentionally permits `EVAL_ARGS` after its local default, and the option is documented as a selectable API address. A remote API can therefore be approved after a local, same-UUID row was found scripted—or after entirely unrelated local stores were inspected. **Resolution (2026-08-21): reject non-local API targets for 2.11.**

### Patches

1. **[medium] Reject malformed search metadata instead of converting it into a passing observation.** `evals/harness/retrieval.py:145-150` coerces an omitted/non-boolean `indexMissing` to `False` and an omitted/non-string `ranking` to `"unknown"`. That can produce a passing recall result without recording the response fields the contract requires. Require the promised types and add shape-drift tests.
2. **[medium] Translate malformed Neo4j result records into the named store-read failure.** `evals/harness/stores.py:206-210` parses records outside the `try` that maps driver errors to `StoreAssertError`. A changed record shape can instead raise `AttributeError` and bypass the check layer's named not-applicable result and run diagnosis. Validate/translate record and moments shapes, with a regression test.
3. **[low] Make the retrieval observation-set guard symmetric.** `evals/harness/checks.py:815-822` rejects stray successful outcomes but ignores stray `unqueried` keys. A caller can record a failed request for a non-manifest phrase while the calculated result still passes. Treat extra unqueried IDs as the same divergence and test it.
4. **[low] Persist the effective API endpoint in the immutable run snapshot.** `evals/conftest.py:197-200` passes only resolved local configuration to `Run.create`, while the new search and approval calls use `--api-base-url`. The run artifact cannot identify the public API surface it actually measured or mutated. Record the effective endpoint in the secret-free snapshot and test it.

## Dismissed findings

Ten candidates were dismissed: missing live-subject execution, the planned 4-4 projection absence, and immediate post-approval reads are explicitly frozen designed states; the one-at-a-time eval-run limitation is already a project-wide operational constraint; Meilisearch's permissive 404 behavior is deliberately tested; store credentials and duplicated graph-node notes follow the frozen contract; implicit offset is the public route's pinned default; approval transport ambiguity still produces a blocking failure rather than a false pass; and configurable HTTP timeouts are already deferred in the story frontmatter.

## Remediation

All five findings were fixed in `3fdf03a`:

1. The publish-gate layer now refuses non-loopback API targets before any
   direct-store read or approval request; custom local ports remain supported.
2. Search responses now require string `ranking` and boolean `indexMissing`.
3. Malformed Neo4j records are translated to `StoreAssertError`.
4. Extra failed-query IDs now fail the recall observation-set invariant.
5. The fixture writes the effective API base URL into the secret-free immutable
   configuration snapshot.

New regression coverage includes a store-free check-layer guard for the
remote-API refusal, shape tests, graph-record tests, set-invariant coverage,
and snapshot coverage.

## Verification

- `uv run --project server pytest evals/tests/test_retrieval.py evals/tests/test_store_asserts.py evals/tests/test_run_artifacts.py evals/tests/test_publish_gate_check_layer.py -q` — 100 passed.
- `make evals-test` — 550 passed; no `evals/runs/` folder remained afterwards.
- `uv run --project server pytest evals/checks -q --run-id review-5-3-2026-08-21-external` — expected 2 zero-subject failures, 7 passed, 7 skipped; no new failure. Its temporary artifact was moved to Trash after inspection.
- `uvx ruff check --isolated evals/` — clean.
- `git diff --name-only main...HEAD -- server/` — empty.

## Review result

The story **passes review**. No must-fix findings remain.
