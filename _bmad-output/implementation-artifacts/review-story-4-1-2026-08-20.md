# Code review — Story 4.1: Artifact Extraction Pipeline Stage

**Verdict: pass after remediation.** The initial review found two medium
contract defects and one low verification defect; all three are fixed and
verified below.

## Findings

### Medium — malformed JSON can bypass the required retry and named stage error

**Evidence:** `server/meetingminer/pipeline/extraction.py:211-216` and
`server/meetingminer/pipeline/stages/extract.py:95-110`.

`parse_artifacts()` checks `kind not in KNOWN_KINDS` before establishing that
`kind` is a string. A syntactically valid model reply such as
`{"artifacts":[{"kind":[],"title":"T","body":"B"}]}` therefore raises
`TypeError: unhashable type: 'list'`, not `ArtifactParseError`. `_propose()`
catches only `ArtifactParseError`, so it does not perform the matrix-required
retry and the runner records an unexpected failure rather than a moment-named
`StageError`. Require `kind` to be a string before membership testing, and add
a regression test that demonstrates the retry/StageError behavior on the
unfixed code.

### Medium — a normal bare OpenAI model binding ignores `providers.openai`

**Evidence:** `server/meetingminer/adapters/llm/litellm.py:38-56`.

`resolve_api_base("gpt-4o", providers)` returns `None`. LiteLLM then uses its
ambient OpenAI default instead of the configured `providers.openai.base_url`.
Changing the extraction role to the common bare LiteLLM model spelling thus
does not keep endpoint binding in `config.yaml`, contrary to AD-8/AD-10. Map
recognized bare OpenAI model IDs to the configured OpenAI provider (or reject
an ambiguous bare identifier explicitly), and cover the chosen contract in the
adapter tests.

### Low — the documented LiteLLM-boundary verification command is false-red

**Evidence:**
`_bmad-output/implementation-artifacts/spec-4-1-artifact-extraction-pipeline-stage.md:189`.

The specified command uses `--glob '!adapters/llm/*'` while searching
`server/meetingminer` from the repository root. That glob does not exclude
`server/meetingminer/adapters/llm/litellm.py`, so the permitted lazy import is
printed even though the expected result is no matches. Correct the glob (for
example, `!server/meetingminer/adapters/llm/**`) or run the command from the
package root so the declared verification is executable as written.

## Verification run by reviewer

- `cd server && uv run pytest tests/test_extraction_core.py -q` — 46 passed.
- `cd server && uv run pytest tests/test_worker_extract.py -q` — 9 passed.
- `cd server && uv run pytest tests/test_migrations.py -q` — 10 passed.
- `cd server && uv run pytest tests/ -q` — 1141 passed, 0 failed, 0 skipped
  (4m55s).
- `make web-test` — 90 passed.
- `git diff --check main...story/4-1` — passed.
- The literal spec `rg` command printed the allowed adapter import, confirming
  the low finding. With a corrected exclusion glob, the same search returned
  no disallowed imports.

## Scope conformance

All 25 files in `main...story/4-1` are within the reviewer handoff's declared
scope. No out-of-scope implementation changes were found.

## Remediation

All three review findings were fixed on `story/4-1-review`. The parser now
turns array/object kinds into `ArtifactParseError`, which the stage retries;
common bare OpenAI identifiers resolve through `providers.openai`; and the
documented `rg` glob excludes the adapter path correctly. The relevant focused
tests and the full verification suite were re-run after this change: 1,143
server tests and 90 web tests passed.
