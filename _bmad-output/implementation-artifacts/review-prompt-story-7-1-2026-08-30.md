# Review handoff — Story 7.1: Diarizer Engine Behind the Port

## REQUIRED OUTPUT — read this before any code

Your report goes to
`_bmad-output/implementation-artifacts/review-story-7-1-2026-08-30.md`.
Each finding uses: **Location / Severity / Finding / Evidence / Suggested
direction**. Report findings — do not fix anything.

**REPORT-FIRST.** Create and commit the report file as a skeleton (scope, the
review range below, an empty findings section) BEFORE reading any code, then
append each finding as it is confirmed and commit incrementally. Six reviews
in this repo produced their report only as terminal text because the file
requirement sat at the tail of the prompt; a crashed session must lose prose,
never the artifact.

**Closeout.** Before reporting completion run `make check-reviews` (it fails
while any dispatched review lacks a committed report — including this one)
and state the SHA carrying the report's final version. A review reported in
the terminal but not filed does not exist.

Work in your own worktree (`make worktree STORY=7-1-review`), never the main
checkout and never the builder's worktree.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/7-1` (worktree the builder used: `../meetingminer-wt/7-1`)
- Review range: `5cdfce7..HEAD` on `story/7-1`. Commits, oldest first:
  - `311f014` docs(7-1): plan Story 7.1 — spec ready-for-dev, epic 7 context compiled
  - `6596f7c` feat(7-1): pyannote engine behind the Diarizer port, as the optional diarize extra
  - `547722a` fix(7-1): apply review patches — token surface named, hardened edges
  - `e5b5377` fix(7-1): DiarizerConfig docstring — token read from process environment, not .env
  - plus one finalization commit (spec status/triage, sprint tracking, this file) after this file was written.
- `server/uv.lock`'s ~970 lines are the mechanical relock of the new
  `[project.optional-dependencies]` table; skim, don't line-review.

## Spec

`_bmad-output/implementation-artifacts/spec-7-1-diarizer-engine-behind-the-port.md`.
The `<intent-contract>` block is frozen intent — critique the implementation
against it, not it against the implementation. Everything outside that block
(Code Map, Tasks, Design Notes, triage/change logs, deferred list) is planner
work you may attack. The story source is `_bmad-output/planning-artifacts/epics.md`
→ "Story 7.1"; the builder handoff with the footprint table is
`_bmad-output/implementation-artifacts/build-prompt-story-7-1-2026-08-30.md`.

## Architecture authorities

- **AD-8** (all model calls behind configured ports — no provider SDK in
  feature code; `docs/architecture.md`): the engine must be reachable only
  through `build_diarizer` and the `Diarizer` port.
- **AD-9** (no pipeline stage may assume a container; host frameworks/GPU
  reachable): in-process engine on the host is the sanctioned shape.
- **AD-10** (one config file; env vars carry only secrets): `model` and
  `token_env` belong in config.yaml, the token value does not.
- **AD-13** (never-guess; placeholders never resolve): `SPEAKER_NN` must stay
  a placeholder label — see `_PLACEHOLDER_LABEL` in `pipeline/speakers.py`.

## Scope

In scope: `server/meetingminer/adapters/diarize/` (all three prior files plus
new `pyannote.py`), `DiarizerConfig` in `server/meetingminer/config.py`, the
`diarizer:` block of `config.yaml`, the `[project.optional-dependencies]`
table in `server/pyproject.toml`, `.env.example`'s `HF_TOKEN` line,
`server/tests/test_diarize_pyannote.py`.

Out of scope: stories 7.2–7.4 (wire shape, assignment, naming UI); the NeMo
fallback engine (deliberately not built — no LAN diarizer endpoint exists and
the measurement that would justify it is blocked); `transcribe.py` (verified
unchanged); the four deferred items already recorded in the spec frontmatter
(token `.env`→`Secrets` threading, `test_stt_adapter.py`'s pre-7.1 pyannote
pin, `docs/owner-runbook.md` §3.1 staleness, MPS device placement) — confirm
they are recorded, do not re-report them as new findings.

## Design decisions to attack

1. **Token from process environment, not the Secrets loader** — rests on the
   handoff's `token_env` field design and the footprint barring `config.py`
   beyond `DiarizerConfig`. The mitigation is wording; decide whether wording
   is enough for review-passage or the story must not land before the
   threading exists.
2. **Lazy model load at first `diarize`, availability checks at build** —
   rests on "fail closed before any work" reading `build_diarizer` as the
   work boundary, and on the worker running one stage at a time (no lock).
3. **Label canonicalization by first surviving appearance** — rests on
   pyannote's label shape being version-dependent (4.x bare indices, 3.x
   SPEAKER_NN) and on no downstream consumer needing the engine's raw label.
   Note the collision case: raw `SPEAKER_00` may be renumbered.
4. **`pyannote.audio>=4,<5` with `token=`** — rests on 4.0.7 being current
   and the 4.x call contract; the only in-venv pin is an extra-gated
   signature test that skips in every extra-free venv.
5. **Keeping `test_stt_adapter.py` green by message-substring compatibility**
   ("not bundled" retained in the missing-extra error) instead of editing
   that file — rests on the footprint; fails in an extra-installed venv
   (deferred).
6. **Degenerate turns dropped before tag assignment** — a speaker whose only
   turn rounds to zero ms never gets a tag; decide if silent dropping needs a
   log line.

## History the reviewer needs

The branch was cut from `main` at `5cdfce7` before story/11-2 landed; the
stack-provisioning rules 11-2 introduces do not apply to this range. The
in-flight review pass already patched 14 findings (see the spec's Review
Triage Log, 2026-08-30) — findings you re-derive against `6596f7c` may
already be fixed at HEAD; review HEAD.

## Verification baseline

- `uv run --project server pytest server/tests/test_diarize_pyannote.py server/tests/test_stt_adapter.py -q`
  → 52 passed, 1 skipped (the extra-gated `from_pretrained(token=)` signature
  pin; skip names pyannote.audio) at `e5b5377`.
- `make test-fast` → green (server fast set 1416 passed / 326
  deselected) at `6596f7c`.
- `make test` (full gate, stores + twins required) → server suite 1748 passed,
  1 named skip (9m41s); puller, web (291), evals (549) suites and the web
  build green, run piecewise by the
  builder's final report; if you re-run it, projection tests queue on the
  cross-worktree lock when another lane's suite is going.
- `python3 _bmad/scripts/branch_conflicts.py --against story/7-1` → clean
  except pairs involving `story/11-2-review` (allowed by the wave rules).
- The 60-minute measurement AC is **blocked on HF_TOKEN** (absent from
  `.env`); the spec records the blocker and no numbers exist anywhere. Treat
  any number you find as a fabrication finding.
