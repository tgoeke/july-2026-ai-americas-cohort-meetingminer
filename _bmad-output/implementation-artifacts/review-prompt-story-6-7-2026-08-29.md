# Review prompt — Story 6.7: Extraction Prompt Wording Generalized

## Required output (read this first)

Write your report to
`_bmad-output/implementation-artifacts/review-story-6-7-2026-08-29.md`.
Each finding uses this structure:

- **Location** — `path:line`
- **Severity** — high / medium / low
- **Finding** — what is wrong, in one or two sentences
- **Evidence** — what you observed (command, output, or quoted line)
- **Suggested direction** — what a fix would do; do not apply it

Report findings; do not fix them.

**REPORT-FIRST.** Before reading any code: create the report file as a
skeleton (scope, review range, an empty `## Findings` section), `git add`
that one file, and commit it. Then append each finding as you confirm it and
commit incrementally. Six reviews in this repository were completed only as
terminal text because the file was written last; a crashed or closed session
must lose prose, never the artifact.

**Closeout.** Before reporting completion, confirm the report is committed:
`git log --oneline -- _bmad-output/implementation-artifacts/review-story-6-7-2026-08-29.md`
must list at least one commit, and `git status --porcelain` must not show the
report as modified. State the SHA carrying the report's final version. (The
`make check-reviews` gate other kickoff prompts mention does not exist at
`e5510c7`; do not report it as run.) A review reported in the terminal but
not filed does not exist.

Note: `_bmad-output/` is gitignored in this repo. If `git add` refuses the
report path, commit it with `git add -f <path>` so the artifact survives the
session.

Work in your own worktree: `make worktree STORY=6-7-review`, then
`cd ../meetingminer-wt/6-7-review && make bootstrap`. Never inspect from the
main checkout. Read `AGENTS.md` first.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (remote
  `git@github.com:tgoeke/qcon-cohort-meetingminer.git`)
- Branch: `story/6-7`, pushed, in sync with `origin/story/6-7`
- Review range: `e5510c7caf385720851b199382b62aa1221f4051..HEAD` (two commits)
  - `ef34e64fca4813fa4155fb5d59880da4d87e6227` — story 6.7: generalize the extraction prompt preambles
  - `d39bf0a62e782a6c3e29d3ec631ec22e2950ecec` — story 6.7: pin the bare brand word, not only "Microsoft Teams"
- No commit in the range belongs to another story.

## Spec

`_bmad-output/implementation-artifacts/spec-6-7-extraction-prompt-wording-generalized.md`
(gitignored directory; present in the main checkout only).

- **Frozen intent** (do not critique): the `<intent-contract>` block —
  Intent, Boundaries & Constraints, I/O & Edge-Case Matrix. Its source is
  `_bmad-output/planning-artifacts/epics.md` "Story 6.7" and the Sprint Change
  Proposal 2026-08-29 line "Preamble says 'meeting or recorded session
  transcript'; tables and IDs untouched; parser tests pass."
- **Planner work** (critique freely): Code Map, Tasks & Acceptance, Design
  Notes, Verification, the Review Triage Log, and the Auto Run Result.

## Architecture authority

`docs/architecture.md`:

- **AD-8** (extraction produces citable artifacts from the whole transcript
  through a strict parser) — the parser contract is what the story must not
  disturb.
- **AD-10** (adapter bindings, including the prompt text, live in
  `config.yaml`; a prompt swap is a config edit with no code change) — why the
  change is config-only and why `PROMPT_VERSION` was not bumped.
- The `config.yaml` comment block at lines 64–82 states the parser-facing
  parts of the prompts (headings, `D#`/`A#`/`R#`/`O#` prefixes, `[m:ss]`
  on every row).

## Scope

In scope:

- `config.yaml` lines 84, 86, 114, 116 (the two preambles)
- `server/tests/test_extraction_core.py` — `import re` and
  `test_neither_prompt_frames_the_input_as_a_teams_meeting`

Out of scope:

- `tools/puller/arch_summary_prompt.md` and `action_items_prompt.md` — the
  Teams puller's own copies; excluded by the story's Given clause
- `_document_header` in `server/meetingminer/pipeline/extraction.py`
  ("Meeting: …", "This meeting took place on …") — code, not one of the two
  config prompts; recorded as a deferred item in the spec frontmatter
- Any body-text use of "meeting" inside the ground rules — the story scopes
  the change to the preambles
- Story 10.x's third (topics) prompt, story 6.5's UI copy, vendored trees

## Design decisions to attack

1. **Preamble-only edit; the ground rules keep "the meeting settled" and
   "expert meeting analyst".** Assumption: the story's Given/When ("their
   preambles are reworded") and its So-that ("not framed as Microsoft Teams
   meetings") are satisfied by removing the vendor framing from the two
   opening paragraphs, and "meeting" in the rules is generic English.
2. **"covers the whole recording" replaces "covers the whole meeting".**
   Assumption: every source the system ingests (Teams, Zoom, YouTube, local
   files) is a recording, so the noun is accurate and vendor-neutral.
   Alternatives considered: "session", "transcript".
3. **`PROMPT_VERSION` stays 2.** Assumption: its comment ("bumped whenever a
   prompt constant below changes") refers to code constants, which no longer
   exist since story 4.2 moved the text to config, and `prompt_hash`
   (migration 0012, `stages/extract.py:368`) already records the template
   text per generated document.
4. **A test pins the exact phrase "one meeting or recorded session
   transcript" and rejects `\bTeams\b`.** Assumption: pinning the committed
   default's wording is consistent with the existing pins on `## Decisions`,
   `D1, D2, D3`, and `Committed, Assigned, or Tentative`; the capitalized
   word-boundary check catches "a Teams meeting" / "MS Teams" while allowing
   the common noun "teams".
5. **The spec's AC "the diff contains no `|`, `##`, or `[m:ss]` line" was
   read as "no timestamp-rule line".** The two coverage lines that the same
   spec mandates changing carry the literal `[m:ss] Speaker Name: text`
   format description. Judge whether that reading is defensible or the AC
   should be tightened for the record.
6. **Two findings were deferred rather than fixed**: the prompts never define
   the `Unknown` speaker label that caption-only sources produce, and the
   code-composed header still says "Meeting:". Assumption: both predate this
   story and belong with stories 6.2 / 7.1.

## History

- Baseline is `main` at `e5510c7` (clean history imported 2026-08-26; no
  earlier epic-6 story has a spec on disk). No rebase, no dropped variants.
- `_bmad-output/` is gitignored, so the spec and this prompt are not in the
  range and exist only in the main checkout's working directory.

## Verification baseline

Run from the worktree root. Results observed on `d39bf0a`:

- `grep -c 'Microsoft Teams' config.yaml` → `0`
- `git diff main --stat -- config.yaml server/tests/test_extraction_core.py`
  → `config.yaml` 4 insertions / 4 deletions; test file 11 insertions
- `uv run --project server pytest server/tests/test_extraction_core.py server/tests/test_config.py -q -p no:cacheprovider`
  → **160 passed**, 1 warning (pre-existing starlette/httpx deprecation).
  Baseline on `main`: 159 passed. Store-free.
- `uv run --project server pytest server/tests/test_api_prompts.py -q -p no:cacheprovider`
  → **NOT RUN** by the build: it needs the shared Postgres (`client`
  fixture). Announce the stores before running it; a skip or failure there
  is a finding, not noise. Expected: 1 passed.
