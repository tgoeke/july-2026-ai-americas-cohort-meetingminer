# Reviewer Handoff — Story 4-2: Visible, Swappable Extraction Prompts

## REPORT-FIRST — read this before anything else

Your report goes at:

```
_bmad-output/implementation-artifacts/review-story-4-2-2026-08-21.md
```

Finding structure, one entry per finding:

```markdown
### <short title>

- **Location:** file:line
- **Severity:** high | medium | low
- **Finding:** what is wrong
- **Evidence:** why it is wrong — the specific behavior, code, or contract it violates
- **Suggested direction:** what a fix would need to address (do not fix it yourself)
```

**Report findings — do not fix them.** You are reviewing, not patching.

**Do this before reading any code:**
1. Create `_bmad-output/implementation-artifacts/review-story-4-2-2026-08-21.md` as a skeleton: a scope/range header and an empty `## Findings` section.
2. Commit that skeleton immediately.
3. As you confirm each finding, append it and commit incrementally — one commit per finding or small batch is fine. A crashed or closed session must lose at most your unwritten prose, never the artifact itself.

**Before you report completion:** run `make check-reviews` (repo root). It fails while any dispatched review lacks a committed report — including this one. State the exact SHA carrying the report's final version. A review reported only in the terminal, with no committed file, does not exist as far as this project's tooling is concerned.

---

## Repo, branch, range

- Repo: `meetingminer` (this checkout, or a fresh worktree via `make worktree STORY=4-2-review` — do not review from the shared main checkout).
- Branch: `story/4-2`
- Review range: `64363f7527f613c3b3ebcfeb3d245c7c621be1d5..HEAD`

Commits in range, by revision and subject:

```
116fe47 docs(4-2): mark in-progress, capture baseline revision
8fb87d4 feat(4-2): visible, swappable extraction prompts
ec4bfd5 fix(4-2): correct prompt_hash comment, add symmetric hash-change test
1292e96 docs(4-2): close review — 2 patched, 3 deferred, story done
```

`8fb87d4` is the substantive implementation commit. `ec4bfd5` applies two
patch findings from an automated review pass already run against `8fb87d4`
(details below — read them before re-finding the same two issues).
`116fe47` and `1292e96` are spec-frontmatter-only (no source changes).

## Spec: frozen intent vs. planner work

Spec path: `_bmad-output/implementation-artifacts/spec-4-2-visible-swappable-extraction-prompts.md`

- **Frozen intent** (do not second-guess the *goal*, only the *execution*):
  the `<intent-contract>` block — Intent, Boundaries & Constraints, I/O &
  Edge-Case Matrix. This came from `_bmad-output/planning-artifacts/epics.md`
  Story 4.2's acceptance criteria, verbatim in substance.
- **Planner work you may critique freely**: everything below the
  `<intent-contract>` closing tag — Code Map, Tasks & Acceptance, Design
  Notes. These are this run's own decisions, not handed-down requirements.

## Architecture authority

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:
  **AD-8** (all model calls through configured ports), **AD-10** (one config
  file drives everything). The spec's Design Notes explicitly argue that
  widening `LlmRoleBinding` with two prompt-text fields is *consistent* with
  AD-10 rather than a violation of its "nothing else lives there" language —
  attack that argument if you disagree; it is a judgment call, not a settled
  fact.
- `_bmad-output/implementation-artifacts/epic-4-context.md`: UX & Interaction
  Patterns section states "The extraction area exposes the complete active
  prompt text" — this is why the implementation put the new section inside
  the moment-view right rail rather than a separate settings page. If you
  think that's the wrong reading, the epic context is the thing to argue
  against, not the diff.

## Scope

**In scope (this story's files):**
- `config.yaml` (the two new prompt keys only)
- `server/meetingminer/config.py` (`ExtractionRoleBinding`)
- `server/meetingminer/pipeline/extraction.py` (prompt-building functions)
- `server/meetingminer/pipeline/stages/extract.py` (`prompt_hash` wiring)
- `server/meetingminer/migrations/0012_extraction_prompt_hash.sql`
- `server/meetingminer/api/extraction.py` (new)
- `web/src/features/moments/MomentView.tsx`, `moments.ts`
- `web/src/client/*.gen.ts` (generated — verify it matches the FastAPI route,
  don't review it as hand-written code)
- Test files: `server/tests/test_config.py`, `test_extraction_core.py`,
  `test_worker_extract.py`, `test_api_registry.py`, `test_api_prompts.py`
  (new), `web/src/features/moments/MomentView.test.tsx`

**Explicitly out of scope:**
- Story 4.3's approve/publish routes and UI (`approveMomentArtifacts`, the
  publish-link rendering) — present in `MomentView.tsx` but untouched by this
  diff, already shipped and reviewed under story 4-3.
- Story 4.4 (published artifacts as citable knowledge) — backlog, not
  touched.
- Any of the other five `ARTIFACT_CATEGORIES` kinds (`decision`, `story`,
  `requirement`, `bug-fix`, `change-request`) — these are wire-vocabulary
  placeholders for later stories; this story's extraction pipeline only ever
  produces `adr`/`action-item`.

**No commit in this range belongs to a different story.**

## Design decisions to attack

Each is a choice this run made, plus the assumption it rests on — hand these
back rather than hoping you rediscover them independently:

1. **Prompts belong in `config.yaml`, full stop — no `{rules}` shared
   fragment, no code-level fallback default.** Assumption: "the full active
   prompt text is visible" (epics AC1) is only true if what's shown *is* what
   gets sent, with nothing composited in from code at call time. Attack
   point: this duplicates ~10 lines of grounding-rules text across the two
   YAML block scalars, and nothing enforces the two copies stay in sync if
   someone edits one grounding rule but not the other.

2. **`prompt_hash` is a truncated sha256 (16 hex chars) of just the resolved
   template, not the whole rendered prompt, not the whole config file.**
   Assumption: per-artifact provenance needs to distinguish prompt-config
   edits from each other and from unrelated config changes, not prove exact
   text via cryptographic collision-resistance. Attack point: a historical
   hash cannot be reverse-mapped to its exact text without manually
   correlating against `config.yaml`'s git history — already flagged as a
   deferred item in the spec frontmatter; judge whether that deferral is
   actually acceptable for this story's stated audience ("provenance for the
   eval config snapshot").

3. **`GET /extraction/prompts` is a new, separate endpoint — not a field
   added to `MomentArtifact`/`MomentDetail`.** Assumption: the two prompts
   are global config, not per-artifact or per-moment data, so tying them to
   the moment-read response would be a category error. Attack point: this
   means an artifact's `provenance.prompt_hash` (which *would* let a caller
   verify a specific artifact against a specific prompt) is written to
   Postgres but never surfaced through any API route — only DB-queryable.
   Judge whether AC3 ("Given an extracted artifact, when inspected...") is
   satisfied by a column nothing exposes.

4. **The prompts fetch in `MomentView.tsx` is deliberately silent-fail: no
   `console.error`, no retry, just an omitted section.** Assumption: a
   missing "nice to have" UI section is better than surfacing a second,
   unrelated error banner alongside the moment-load error path. Attack
   point: there is no operator-facing signal at all if this starts failing
   in production — flagged as deferred; judge the severity.

5. **`PROMPT_VERSION` (the parser-contract version) is deliberately left
   unbumped by a config-only prompt edit — only `prompt_hash` changes.**
   Assumption: `PROMPT_VERSION` means "the output *shape* the parser expects
   changed" (a code change), while `prompt_hash` means "the exact
   *instructions* changed" (a config change), and conflating the two would
   make `PROMPT_VERSION` bump on every cosmetic prompt tweak, defeating its
   purpose. Attack point: verify this distinction is actually clean in the
   code — nothing should silently assume `PROMPT_VERSION` implies a specific
   prompt text, or vice versa.

## History context

This is a fresh addition on top of story 4-1a (whole-transcript extraction,
already `done`, merged). No rebase, no dropped variant, no superseded
baseline in this range — `git log --oneline 64363f75..HEAD` above is the
complete, linear history of this story's work. If you find something that
looks like a regression against pre-4-1a behavior, it is almost certainly
intentional (4-1a's own review already covered that transition); a
regression against 4-1a's *own* committed behavior is fair game.

## Automated review already run — do not re-surface these verbatim

A four-layer automated pass (blind hunter, edge-case hunter,
verification-gap, intent-alignment) already ran against `8fb87d4` before
`ec4bfd5` was written to fix it. Full triage is in the spec's
`## Review Triage Log` section. Two low-severity items were patched
(inaccurate `prompt_hash` migration comment; asymmetric test coverage across
the two prompt fields) — verify the fixes actually landed rather than
re-finding the same two issues. Three low-severity items were deferred (see
frontmatter `deferred:` in the spec) — feel free to disagree with the
"defer" triage if you think one is more severe than judged, but don't just
restate them as new findings without adding something.

## Verification baseline

Commands and their results as last run, independently, after `ec4bfd5`:

- `cd server && uv run pytest tests/test_worker_extract.py tests/test_extraction_core.py tests/test_config.py tests/test_api_prompts.py tests/test_api_registry.py -q` → **192 passed**
- `cd server && uv run pytest tests/ -q` → **1511 passed, 0 failed** (6m51s)
- `make web-test` → **189 passed** (11 files)
- `rg -n 'import litellm|from litellm' server/meetingminer --glob '!**/adapters/llm/**'` → **no matches** (AD-8 boundary intact)
- `git status --porcelain` → empty
- `git rev-list --left-right --count HEAD...@{u}` → `0	0`

No model call of any kind was made during this story's development: the
worker was never started, `make evals-run` was never run. If any command
above fails or behaves differently when you run it, that is itself a
finding — the baseline above is what this run observed, not an assumption to
take on faith.

## When you're done

Follow the REPORT-FIRST section at the top: commit the report, run
`make check-reviews`, and state the SHA carrying the report's final version
before declaring the review complete.
