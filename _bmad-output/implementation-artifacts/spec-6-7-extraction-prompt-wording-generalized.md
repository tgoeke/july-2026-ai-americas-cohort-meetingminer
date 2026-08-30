---
title: 'Story 6.7: Extraction Prompt Wording Generalized'
type: 'chore'
created: '2026-08-29'
status: 'done'
baseline_revision: 'e5510c7caf385720851b199382b62aa1221f4051'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred:
  - summary: >-
      Neither extraction prompt tells the model what the `Unknown` speaker label means, and the speech-to-text noise rule describes Teams live captions only.
    evidence: |-
      `render_transcript` (server/meetingminer/pipeline/extraction.py:151) emits `Unknown` for a turn with no speaker label; a YouTube caption track or a single-mic Zoom recording carries none, so every line reads `[m:ss] Unknown: text`, and the action-items prompt's owner rule ("whoever accepted or was assigned the work") has no label to resolve. Auto-generated YouTube captions also lack punctuation and carry markers like [Music]/[Applause], which the "Expect speech-to-text noise" rule does not mention. Pre-existing; surfaced by generalizing the preamble. Story 7.1 (diarizer) changes what the label carries, so revisit after it lands.
    location: >-
      config.yaml:88-93 and config.yaml:118-123
    severity: low
  - summary: >-
      The code-composed prompt header still frames every input as a meeting ("Meeting: ...", "This meeting took place on ...", "untitled meeting").
    evidence: |-
      `_document_header` (server/meetingminer/pipeline/extraction.py:166-172) is prepended to both templates on every generate call, and `test_a_prompt_survives_a_missing_title_and_a_missing_date` pins "untitled meeting". Story 6.7's Given clause names only `config.yaml`'s two prompts, so this residue is outside its intent; generalize the header (and its date-grounding sentence) when YouTube ingestion (story 6.2) lands.
    location: >-
      server/meetingminer/pipeline/extraction.py:166-172
    severity: low
---

<intent-contract>

## Intent

**Problem:** Both extraction prompts in `config.yaml` open with "one Microsoft Teams meeting transcript", so a YouTube talk or a Zoom call brought in by Epic 6 is framed to the model as a Teams meeting (FR19; Sprint Change Proposal 2026-08-29).

**Approach:** Reword only the preamble paragraphs of `arch_summary_prompt` and `action_items_prompt` so the input is described as "one meeting or recorded session transcript" and the coverage line no longer says "the whole meeting", leaving every line the parser keys on byte-identical.

## Boundaries & Constraints

**Always:**
- The two `## Decisions` / `## Risks and open questions` / `## Action items` headings, both table header rows and separator rows, the example rows, the `D1, D2, D3...` / `R1, R2` / `O1, O2` / `A1, A2, A3...` ID sentences, the `Committed, Assigned, or Tentative` status sentence, and every `[m:ss]` timestamp rule stay byte-identical.
- Only the first two paragraphs of each prompt (the role sentence and the "The transcript is verbatim..." sentence) change; the "Ground rules" block and everything after it are untouched.
- The change is a `config.yaml` edit plus one pinning test in `server/tests/test_extraction_core.py`; no other file changes. `PROMPT_VERSION` (`server/meetingminer/pipeline/extraction.py:59`) stays `2`: it tracks prompt constants in code, and a config-text change is already recorded per artifact by `prompt_hash` (migration 0012).
- The committed default stays parseable and every existing parser and prompt test passes unchanged.

**Block If:**
- Any test in `server/tests/test_extraction_core.py` or `server/tests/test_config.py` asserts on a phrase that lives only in the preamble (none found at planning time — `Microsoft Teams` appears in no test).

**Never:**
- Do not touch `tools/puller/arch_summary_prompt.md` or `tools/puller/action_items_prompt.md` — the puller is Teams-only and shares no code with the server.
- Do not change `_document_header` in `server/meetingminer/pipeline/extraction.py` ("Meeting: ...", "This meeting took place on ..."): it is code, not one of the two config prompts, and tests pin its text.
- Do not add a `{rules}` fragment, a shared preamble, or any templating — each value remains the literal, complete text sent to the model (AD-10).
- Do not bump `PROMPT_VERSION`, add a migration, or re-run extraction over the corpus.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Committed default still loads | `load_config(REPO_ROOT / "config.yaml")` | Both prompts load; `test_config.py`'s shipped-config tests pass | No error expected |
| Parser contract intact | `build_summary_prompt`/`build_actions_prompt` over the new templates | `## Decisions`, `D1, D2, D3`, `## Action items`, `A1, A2, A3`, `Committed, Assigned, or Tentative`, `[m:ss]`, `[Proposed]`, `Do not invent facts` all present | No error expected |
| Teams framing gone | Both committed templates via `app_config` | Neither contains `Microsoft Teams`; both contain `one meeting or recorded session transcript` | No error expected |

</intent-contract>

## Code Map

- `config.yaml:83-84` -- `arch_summary_prompt` role sentence: "Turn one Microsoft Teams meeting transcript into architecture-ready analysis." (change)
- `config.yaml:86` -- arch coverage line: "...and covers the whole meeting." (change)
- `config.yaml:113-114` -- `action_items_prompt` role sentence: "...from one Microsoft Teams meeting transcript, with owners." (change)
- `config.yaml:116` -- actions coverage line, identical to line 86 (change)
- `config.yaml:64-82` -- the comment block naming the parser-load-bearing parts; the rule it states is the boundary above (read-only)
- `config.yaml:99-112`, `config.yaml:136-146` -- table headers, example rows, ID sentences, closing rules (read-only, byte-identical)
- `server/meetingminer/pipeline/extraction.py:166-221` -- `_document_header`, `build_summary_prompt`, `build_actions_prompt`: template + header + transcript joined verbatim (read-only)
- `server/meetingminer/pipeline/extraction.py:288-370, 697-810` -- `parse_extraction_document` keys on item-ID prefixes, `[m:ss]` presence, and recognized target headings (read-only evidence of what the contract is)
- `server/meetingminer/pipeline/stages/extract.py:368` -- `prompt_hash = sha256(template)[:16]`; why no code change is needed for provenance (read-only)
- `server/tests/test_extraction_core.py:113-172` -- prompt tests against the committed `config.yaml` via `app_config` (store-free; must stay green)
- `server/tests/test_config.py:269-271, 787-788` -- shipped-config loader checks (store-free)
- `server/tests/test_api_prompts.py` -- `GET /extraction/prompts` serves the text verbatim, asserts `## Decisions` / `## Action items` (needs Postgres via `client` fixture)

## Tasks & Acceptance

**Execution:**
- `config.yaml` -- rewrite `arch_summary_prompt` line 84 to "You are an enterprise-architecture analyst. Turn one meeting or recorded session transcript into architecture-ready analysis." and line 86 to end "...and covers the whole recording." -- removes the Teams framing without touching the parser contract
- `config.yaml` -- rewrite `action_items_prompt` line 114 to "You are an expert meeting analyst. Extract every action item, commitment, and next step from one meeting or recorded session transcript, with owners." and line 116 to end "...and covers the whole recording." -- same
- `config.yaml` -- confirm with `git diff` that exactly four lines changed -- proves the boundary held
- `server/tests/test_extraction_core.py` -- add one store-free test beside `test_the_summary_prompt_pins_decisions_and_the_actions_prompt_pins_actions` (line ~143) that, via `app_config`, asserts `"Microsoft Teams" not in` each of `binding.arch_summary_prompt` / `binding.action_items_prompt` and `"one meeting or recorded session transcript" in` each -- pins the matrix row "Teams framing gone" so a later edit cannot quietly re-introduce the framing

**Acceptance Criteria:**
- Given the committed `config.yaml`, when `grep -c 'Microsoft Teams' config.yaml` runs, then it prints `0`.
- Given the committed `config.yaml`, when `git diff main -- config.yaml` is read, then every changed line is one of the four preamble lines and the diff contains no `|`, `##`, or `[m:ss]` line.
- Given the reworded prompts, when `server/tests/test_extraction_core.py` and `server/tests/test_config.py` run, then every test passes (baseline: 159 passed, plus the one new pinning test = 160).
- Given a running Postgres, when `server/tests/test_api_prompts.py` runs, then it passes — or, if the stores cannot be claimed, the run states that it was not executed.

## Spec Change Log

## Review Triage Log

### 2026-08-29 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 1: (high 0, medium 0, low 1)
- defer: 2: (high 0, medium 0, low 2)
- reject: 16
- addressed_findings:
  - `[low]` `[patch]` The pinning test only rejected the two-word brand name, so "a Teams meeting" / "MS Teams" would have passed — replaced with a word-boundary check on the capitalized word `Teams` (commit d39bf0a62e782a6c3e29d3ec631ec22e2950ecec).
- rejected, for the record: body-text "meeting" in the ground rules and "expert meeting analyst" (the intent's Given/When scope the change to the preambles; those are generic English, not Teams framing); "covers the whole recording" vs "transcript" (every source the system ingests is a recording); `PROMPT_VERSION` bump / eval re-baseline (Design Notes; `prompt_hash` exists for this); no live-model run (the intent's acceptance surface is the parser tests, which ran); exact-phrase pin (same style as the existing `D1, D2, D3` pins on the committed default); `None` template TypeError (the loader refuses a missing prompt); a future third prompt (story 10.x's own AC); "Story 6.7" citation style (repo convention); other UI copy naming Teams (story 6.5's surface); overridden deployments (none exist); no project-record entry (the change proposal records epic-level entries as epics land); puller prompt copies (excluded by the story's Given); "no evidence the parser suite ran" (160 passed, observed in this run); the AC line "no `|`, `##`, or `[m:ss]` line" read literally (the two coverage lines carry the `[m:ss]` format description; the AC's only coherent reading, given the Always boundary and the Execution tasks, is "no timestamp-rule line", and none changed).

## Design Notes

"Recorded session" is the term Sprint Change Proposal 2026-08-29 and Story 10.x's topics-prompt AC both use, so the three prompts will share one vocabulary once 10.x lands. "Covers the whole recording" replaces "the whole meeting" because it is true for a talk, a Zoom call, and a Teams meeting alike; later uses of "meeting" inside the ground rules ("something the meeting settled") are generic English, not Teams framing, and stay as they are so the diff proves the preamble-only boundary.

Provenance consequence, deliberate: the next worker `extract` run on a fresh process records the new template's `prompt_hash` on `extraction_source` while `prompt_version` stays 2 — that column exists precisely so a config-text change is visible per artifact without a code change. Not asserted here because it needs the shared Postgres.

Working tree: this story is implemented in the worktree `/Users/devopsterus/current/cohort/meetingminer-wt/6-7` on branch `story/6-7`, never in the main checkout; the implementer edits there and leaves committing to the run.

## Auto Run Result

Status: done

**Implemented:** the two extraction-prompt preambles in `config.yaml` no longer name Microsoft Teams — each opens on "one meeting or recorded session transcript" and says the transcript "covers the whole recording". Headings, table rows, item-ID sentences, and every `[m:ss]` rule are byte-identical to `main`. One store-free test pins the generic wording.

**Files changed:**
- `config.yaml` — four preamble lines (84, 86, 114, 116) reworded; nothing else.
- `server/tests/test_extraction_core.py` — `import re` and `test_neither_prompt_frames_the_input_as_a_teams_meeting` (asserts no `\bTeams\b` and the generic phrase in both templates).

**Commits on `story/6-7` (baseline e5510c7caf385720851b199382b62aa1221f4051):**
- ef34e64fca4813fa4155fb5d59880da4d87e6227 — story 6.7: generalize the extraction prompt preambles
- d39bf0a62e782a6c3e29d3ec631ec22e2950ecec — story 6.7: pin the bare brand word, not only "Microsoft Teams"

**Review findings:** 19 after dedup — 1 patched (low), 2 deferred (low; see frontmatter `deferred`), 16 rejected, 0 intent gaps, 0 bad-spec.

**Follow-up review recommendation:** false — patched: high 0, medium 0, low 1; score = 3×0 + 1×1 = 1 (< 5).

**Verification performed (worktree `../meetingminer-wt/6-7`, HEAD d39bf0a):**
- `grep -c 'Microsoft Teams' config.yaml` → `0`
- `git diff main --stat -- config.yaml server/tests/test_extraction_core.py` → `config.yaml` 4(+)/4(-), test file 11(+)
- `uv run --project server pytest server/tests/test_extraction_core.py server/tests/test_config.py -q -p no:cacheprovider` → 160 passed, 1 pre-existing starlette warning (baseline on `main`: 159 passed)
- `server/tests/test_api_prompts.py` — NOT RUN: it needs the shared Postgres through the `client` fixture and the run's operating rules require confirmation before claiming the stores, which an unattended run cannot obtain. Its assertions (`## Decisions` / `## Action items` present, text served verbatim) are covered at the config surface by the tests above.
- Matrix audit: rows 1–3 covered by `test_config.py`'s shipped-config tests, `test_the_summary_prompt_pins_decisions_and_the_actions_prompt_pins_actions` / `test_both_prompts_embed_the_title_the_date_line_and_the_transcript`, and the new pinning test; all ran and passed.

**Residual risks:** the next worker `extract` run records a new `prompt_hash` on generated documents (intended). Extraction quality on non-Teams sources was not exercised against a model. The spec AC's "no `[m:ss]` line" wording is imprecise (see triage log).

## Verification

**Commands:**
- `grep -c 'Microsoft Teams' config.yaml` -- expected: `0`
- `git diff main --stat -- config.yaml server/tests/test_extraction_core.py` -- expected: 2 files; `config.yaml` 4 insertions, 4 deletions
- `uv run --project server pytest server/tests/test_extraction_core.py server/tests/test_config.py -q -p no:cacheprovider` (run from the worktree root) -- expected: 160 passed, store-free
- `uv run --project server pytest server/tests/test_api_prompts.py -q -p no:cacheprovider` -- expected: 1 passed; needs the shared Postgres, so run only after announcing it, otherwise report it as not run
