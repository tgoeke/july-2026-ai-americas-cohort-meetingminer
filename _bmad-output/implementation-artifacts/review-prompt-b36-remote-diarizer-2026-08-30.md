# Review handoff — B-36 (diarizer half): the LAN diarization endpoint behind the `Diarizer` port

## REQUIRED OUTPUT — read this before any code

Your report goes to
`_bmad-output/implementation-artifacts/review-b36-remote-diarizer-2026-08-30.md`.
Each finding uses: **Location / Severity / Finding / Evidence / Suggested
direction**.

**REPORT-FIRST.** Create and commit the report file as a skeleton (scope, the
review range below, an empty findings section) BEFORE reading any code, then
append each finding as it is confirmed and commit incrementally. Reviews in
this repo have produced their report only as terminal text when the file
requirement sat at the tail of the prompt; a crashed session must lose prose,
never the artifact.

**Then FIX the patchable ones yourself** on `story/b36-remote-diarizer-review`
in your own worktree (`make worktree STORY=b36-remote-diarizer-review`),
red-first — the test observed failing against the unfixed code, then the fix,
then green — committing each with its finding number. Leave unfixed, and
clearly marked open, only what needs an owner decision or is rooted in the
frozen `<intent-contract>`. Never commit to `main`, never work in the main
checkout or the builder's worktree, never merge — the owner runs `integrate`.

**Closeout.** Before reporting completion run `make check-reviews` (it fails
while any dispatched review lacks a committed report — including this one) and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/b36-remote-diarizer` (builder's worktree:
  `../meetingminer-wt/b36-remote-diarizer`)
- Review range: `a401d6c..HEAD` on `story/b36-remote-diarizer`. Commits, oldest
  first:
  - `7c2c294` feat(b36): bind the LAN diarization endpoint behind the Diarizer port
  - plus one finalization commit (spec status and change log, sprint tracking,
    this file) written after this file was.

## Spec and its authorities

`_bmad-output/implementation-artifacts/spec-b36-remote-diarizer.md`. The
`<intent-contract>` block is frozen intent — critique the implementation
against it, not it against the implementation. Everything outside that block
(Code Map, Tasks, Design Notes, the change log) is planner work you may attack.
The builder handoff with the footprint table is
`build-prompt-b36-remote-diarizer-2026-08-30.md`; the wave rules are
`wave-2026-08-30-rules.md`; the item is `docs/backlog.md` B-36.

Architecture authorities:

- **AD-8** — all model calls behind configured ports. The engine must be
  reachable only through `build_diarizer` and the `Diarizer` port.
- **AD-9** — where inference runs is a config change, never a code change; a
  remote engine is a new adapter, not an architecture change.
- **AD-10** — one config file; env vars carry only secrets. The endpoint and
  the timeout belong in `config.yaml`.
- **AD-13** — never-guess; placeholders never resolve. `SPEAKER_NN` must stay a
  placeholder under `_PLACEHOLDER_LABEL` in `pipeline/speakers.py`.

## Scope

In scope: `server/meetingminer/adapters/diarize/remote_http.py` (new),
`server/meetingminer/adapters/diarize/__init__.py`, `DiarizerConfig` in
`server/meetingminer/config.py`, the `diarizer:` block of `config.yaml`,
`server/tests/test_diarize_remote.py` (new).

Out of scope: B-36's `Stt`-over-HTTP half, which stays open in
`docs/backlog.md`; `pyannote.py`, `noop.py`, `port.py`, `pipeline/**`, `web/**`
and the `llm`/provider regions of `config.py`, all verified unchanged; the
choice of default engine, which is the owner's and is deliberately not made
here.

## Design decisions to attack

1. **Not registered in `ENGINES`.** The build prompt said "register the engine
   in `ENGINES`". `ENGINES` is `dict[str, type[Diarizer]]` constructed
   `engine()` with no arguments, and this engine needs the endpoint and the
   timeout off the binding, so it is special-cased in `build_diarizer` the way
   story 7.1's `pyannote` is, with a new `ENGINE_CHOICES` keeping the
   unknown-engine diagnostic exhaustive. **This is the one place the letter of
   the footprint was not followed; the file is the one the footprint names.**
   The alternative — widening the registry to a factory map — refactors
   `noop`'s registration, which this footprint does not cover. Decide whether
   the precedent or the refactor is right, and whether a third special case
   means the registry has outlived its shape.
2. **Streaming multipart with an explicit `Content-Length`.** A 60-minute
   16 kHz mono WAV is ~115 MB, so the body is a `read()`-able chaining
   `prefix -> file -> suffix`, sized from `path.stat().st_size`. Two things to
   attack: the file is stat'd and then opened, so a file that changes size
   between the two would send a body that disagrees with its header; and
   `urllib` sends `Transfer-Encoding: chunked` if the header is ever dropped,
   which the endpoint may or may not accept.
3. **Rounding each boundary independently** (`round(x * 1000)`, banker's
   rounding at halves). Mirrors `pyannote.py::_to_turns`. Worst case is 0.5 ms
   at a boundary against spans `speaker_at` compares in seconds — check that
   claim rather than taking it.
4. **Canonicalizing labels after sorting, not in host order.** The spec's
   matrix asks for "first appearance after sorting", which differs from
   `pyannote.py`, where labels are assigned in iteration order and sorted
   afterwards. Two engines behind one port now number speakers by different
   rules. Decide whether that is a defect.
5. **A reversed turn fails the whole call rather than being dropped.** Frozen
   in the intent contract. Attack the blast radius instead: one bad turn in an
   82-turn meeting fails the transcribe stage.
6. **A turn that collapses to zero milliseconds is dropped silently** — no log
   line, and a speaker whose only turn collapses never gets a tag. Same
   question story 7.1's review raised about `pyannote.py`.
7. **The 1000-speaker cap raises rather than truncating.** Correct per AD-13,
   but check the arithmetic: `SPEAKER_{n:02d}` at n=999 is `SPEAKER_999`, three
   trailing characters, still a placeholder — and the test at exactly the limit
   asserts that. Verify `is_placeholder_label` agrees at the boundary.
8. **No build-time health probe.** `build_diarizer` returns the engine without
   contacting the host, so a transcribe run that never reaches the diarizer
   cannot be failed by a box that is merely off. The cost is that a
   misconfigured endpoint is discovered late, after the STT pass has run.
9. **Error-message construction.** Every message carries the endpoint, the
   model when the host named one, and the host's `reason` verbatim. Check that
   an unparseable error body degrades to its own text rather than to invented
   wording, and that nothing in the taxonomy is keyed on a single status code
   (the host answers 400 as well as 503).
10. **`timeout_seconds` default 900.** Reasoning is in the spec's Design Notes.
    Attack the number, and attack whether `allow_inf_nan=False` plus `gt=0` is
    the whole of "finite and enforced" — in particular whether every path
    through `_post` really carries the timeout.

## What the builder already recorded — confirm, do not re-report as new

The spec's Spec Change Log carries three deviations: the new `ENGINE_CHOICES`
constant; the two `test_compose_contract.py` registries the new test module
tripped (the pyannote-literal discovery and the exact slow-marked set), both
satisfied inside the footprint without editing that file; and `UP012`
(`.encode()`). Confirm they are recorded and accurate. If you think either
`test_compose_contract.py` registry *should* have been edited instead, that is
a finding worth making — it is a footprint question, not a code one.

## Verification baseline

At `7c2c294`, in the builder's worktree (which has its own compose stack under
story 11.2, so no cross-worktree store contention):

- `uv run --project server pytest server/tests/test_diarize_remote.py -q`
  → 36 passed, 1 skipped, 1.70s. The skip is the env-flagged live test; it
  is a skip, not a deselection.
- `make lint` → clean. `make typecheck` → 13 source files, clean.
- `make test-fast` → 1963 passed, 3 skipped (the live diarizer test naming
  `MM_DIARIZE_REMOTE_NETWORK_TEST`, the yt-dlp network test, the extra-gated
  pyannote signature pin), 378 deselected, 64.76s.
- `make test` → **2341 passed, 3 skipped, 673.08s (11m13s)**, then the web
  build; exit 0. The LAN host was never contacted.
- Every test in the new module was observed red before the engine existed
  (`ImportError: cannot import name 'REMOTE_HTTP_ENGINE'`), and eight mutations
  of the finished engine were each caught by the test that claims them:
  round-down instead of round; label in host order; drop the reversed turn;
  keep the collapsed turn; an off-by-one cap; a missing `Content-Length`; an
  empty-turns fallback on an unreachable host; swallowing the host's reason.
  **Re-run that mutation set on anything you change.**

## What has NOT been verified, and must not be assumed

- **Nothing on this branch has spoken to the live host.** The suite is offline
  by construction and the LAN box (VM120) is operator-scheduled. The
  env-flagged live test exists and has not been run here. Treat any claim about
  real-host behaviour that is not in `docs/backlog.md` B-36 or the spec's
  "Verified against the live host, 2026-08-30" block as unverified.
- **Turn quality is unvalidated against ground truth.** Two speakers on a
  scripted two-person demo is plausible, not measured. Out of scope for a code
  review; do not let a passing test read as a quality claim.
- **No end-to-end run through `transcribe`** with the remote engine bound —
  `config.yaml` still binds `noop`, deliberately.

## Branch state the reviewer must not misread

`main` advanced 50 commits while this was built, and **story 8.1 landed**. Two
consequences:

- The `config.py` proximity pair with `story/8-1` that the build prompt told
  the builder to expect does **not** appear — that branch is gone. `config.py`
  merges clean against current `main`.
- `branch_conflicts.py --against story/b36-remote-diarizer` reports exactly one
  conflict for this branch: `sprint-notes.md`, the shared tracking file the
  wave rules require every builder to append to. It conflicts
  `main x story/10-2` and `main x story/10-2-review` independently of this
  branch, so it is the wave's tracking-file seam that integrate unions — not a
  defect in this change, and not something narrowing this branch's edit fixes.

This branch has **not** been rebased onto the new `main`. Rebasing is
integrate's operation; review the range as it stands.
