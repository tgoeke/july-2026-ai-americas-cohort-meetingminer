# Reviewer handoff — Story 11.3: Eval Runs Own Their Namespace

## REQUIRED OUTPUT — READ THIS FIRST

Your review does not exist until it is a committed file. Six reviews in this
repository produced their report only as terminal text; do not be the seventh.

- **Report path:**
  `_bmad-output/implementation-artifacts/review-story-11-3-2026-08-30.md`
- **Finding structure:** Location / Severity (high|medium|low) / Finding /
  Evidence / Suggested direction. **Report findings — do not fix them.**
- **REPORT-FIRST:** create and commit the report file as a skeleton (scope,
  review range, empty findings section) BEFORE reading any code. Append each
  finding as it is confirmed and commit incrementally. A crashed session must
  lose prose, never the artifact.
- **Closeout:** before reporting completion, run `make check-reviews` (it
  fails while any dispatched review lacks a committed report — including this
  one) and state the SHA carrying the report's final version.

Work in your own worktree: `make worktree STORY=11-3-review` from the main
checkout, then rebase `story/11-3` in — never review in the main checkout or
the builder's worktree.

## Repo, branch, range

- Repository: `/Users/devopsterus/current/cohort/meetingminer` (worktree per
  above), branch `story/11-3`, upstream pushed.
- Review range: `211857c..644faa0` (baseline before the story:
  `5cdfce72813d68c2d81f5e02f715b8863f8492af`; the branch was rebased onto
  main `211857c` before its last commit). Commits, oldest first:
  - `5cd354a` docs: add Story 11.3 spec (eval runs own their namespace)
  - `3f7ba63` fix(evals): a lost mkdir race gets the ownership refusal, not a create error
  - `b5e2463` feat(evals): read-only probe-eligibility helpers — moments_for, stage_status, moment_in_graph
  - `b88ab4e` feat(evals): publish_gate measures the gate on a run-owned probe
  - `7ee401f` feat(evals): the run-owned publish-gate probe layer, erased on exit
  - `a63fdb3` test(evals): admit gate_probe to the driver guard, pinned erasure-only
  - `b863795` feat(evals): 2.11 glue reads subjects read-only and delegates to the probe
  - `60ac058` docs(evals): replace the serial-rule narrative with the probe mechanism
  - `0fb67dc` fix(evals): review patch pass — race, cleanup and pin hardening for 2.11
  - `c68fae9` docs: Story 11.3 spec — review triage log for the four-layer pass
  - `644faa0` docs: Story 11.3 to review — the serial eval rule is replaced

## Spec and frozen intent

- Spec: `_bmad-output/implementation-artifacts/spec-11-3-eval-runs-own-their-namespace.md`.
  The `<intent-contract>` block is frozen intent (from
  `build-prompt-story-11-3-2026-08-30.md` and epics.md Story 11.3, NFR20);
  everything outside it — Code Map, Design Notes, Tasks, the triage log, the
  Auto Run Result — is planner/builder work you may critique freely.

## Architecture authorities

- `docs/architecture.md` **AD-16** (the eval harness is a client: mutates only
  through the public api, asserts through api reads and read-only store
  access) — this story deliberately runs ahead of its wording with a
  delete-only cleanup sanction; the spec's frontmatter `deferred` item routes
  the spine amendment to integration. Judge whether the mechanism honors the
  decision's *intent*.
- **AD-4** (publish gate inside the projection module; unpublished artifacts
  in no retrieval store) — what check 2.11 measures.
- **AD-6** (identity is the Postgres-minted UUID) — why "run-id-prefixed ids"
  became a run-id-prefixed title marker.
- The single-writer invariant (only `meetingminer.projections` writes the
  stores, pinned by server tests) — untouched; the probe writes stores only
  via the api's projection, and erases via the pinned delete-only module.

## Scope

In scope: everything under `evals/**` in the range; the one AGENTS.md bullet
and the one dispatch.md step-2 line (both in `644faa0`); the sprint files and
the spec. Out of scope: `infra/Makefile` (deliberately unchanged),
`server/**` (footprint-forbidden, untouched — verify that), the owner's live
concurrent measurement (spec `## Verification`, not yet run), and
`docs/project-record.md` (written at integration).

Known cross-lane facts, not findings: `branch_conflicts.py --against
story/11-3` is clean against `main`, `story/6-2`, `story/10-1`; it conflicts
with `story/11-2*` on AGENTS.md/dispatch.md (11-2 rewrites the same section;
the build prompt ordered this edit anyway, post-rebase) and with
`story/11-4`/`story/7-1` on sprint-notes EOF appends — the 2026-08-30 second
amendment makes unioning these integrate's job.

## Design decisions to attack

1. **The probe rides a shared subject moment.** Choice: mint the probe
   artifact onto an existing projected moment. Assumption:
   `graph.project_artifacts` rolls back on a missing `Moment` node
   (`server/meetingminer/projections/graph.py:521-535`), and nothing but the
   worker/rebuild projects meetings — so a run-seeded meeting can never pass
   the positive half. Attack the assumption and the residual: the approve
   targets a shared moment, and ownership lives only in the minted row.
2. **Mint by direct SQL; erase by direct store deletes.** Choice: the
   `test_corpus_artifacts.py` writable-connection convention for the mint,
   and a delete-only module (`evals/checks/gate_probe.py`) admitted by name
   in the driver guard for the erasure. Assumption: no api create/delete
   surface exists, `rebuild` has no retirement mode, and server edits are
   footprint-forbidden — so this is the narrowest honest mechanism. Attack:
   is the textual pin (creation stems + raw query clauses) actually narrow
   enough, and is the AD-16 deviation acceptably documented?
3. **Race posture.** Choice: first-writer-wins; a losing run re-reads its own
   row at a present pre-read or a 409 slug and records a named race.
   Assumption: row state is the arbiter, and foreign published rows that were
   discovered `extracted` are the only consumed-state hazard (detected,
   failing the check). Attack the window analysis.
4. **Subject semantics preserved.** Choice: no-artifacts stays a blocking
   not-applicable; unconsumed `extracted` subject rows became the expected
   steady state (no divergence). Assumption: eval-design §2.11's "never a
   vacuous pass" applies to the subject halves, while the transition
   measurement moved wholly to the probe.
5. **"Measured truth" written before the live measurement.** Choice: docs and
   the AGENTS.md bullet state the built mechanism; the live concurrent
   procedure is written for the owner in the spec's Verification. Assumption:
   the no-paid-run constraint makes this the only lawful sequencing. Attack
   whether any sentence overclaims beyond the fakes-proven mechanism.

## History a reviewer needs

- The builder session was killed once mid-task-5 by a rate limit; work resumed
  on the same branch — no content was lost, but commit authorship timing may
  look odd around `7ee401f`.
- `0fb67dc` is the four-layer in-run review's patch pass; its 17 findings and
  9 rejections are itemized in the spec's Review Triage Log — re-attack the
  rejections if you disagree.
- This worktree's `.env` is a placeholder copy (the bootstrap symlink was
  destroyed and the permission gate refused restoring it). Not part of the
  diff; `make test-fast` failures on `test_mint_drop` in an unfixed
  environment are that, not a regression — verify with real storage roots or
  process-env overrides.

## Verification baseline (all run at `644faa0`)

- `make evals-test` — 616 passed (store-free; `evals/runs/` untouched,
  enforced by `runs_folder_untouched`).
- `uv run --project server pytest evals/tests evals/checks -q --collect-only`
  — 639 collected, clean.
- `make test-fast` — 1401 passed, 326 deselected (run with
  `MM_CONTENT_ROOT`/`MM_DROPS_ROOT` pointing at real directories; see the
  `.env` note above).
- `python3 _bmad/scripts/branch_conflicts.py --against story/11-3` — clean
  against `main`, `story/6-2`, `story/10-1`; the named process-file conflicts
  above are expected.
- NOT run: `make evals-run` (paid-adjacent, owner-gated). The live-surface
  gaps this leaves are listed in the spec's Auto Run Result residual risks —
  treat any of them you can falsify statically as a finding, not as noise.

When the report is filed and `make check-reviews` passes, hand the verdict
back through the report file. Do not merge; integration is a separate step.
