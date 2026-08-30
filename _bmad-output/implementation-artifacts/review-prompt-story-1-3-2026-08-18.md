# Codex review prompt — Story 1.3: Checkpointed Ingestion Worker (probe + frames)

Repo: `/Users/devopsterus/current/cohort/meetingminer` · Branch: `main` (pushed, in sync with `origin/main`)

Review range: `5a9da4b..HEAD` — three commits:

```
0186664 feat: checkpointed ingestion worker — probe + frames (story 1.3)
a56440e fix: story 1.2 review findings — VTT intake coverage, consistent job read
26186a8 docs: story 1.3 spec, story 1.2 review, and sprint status
```

---

You are reviewing Story 1.3 of the MeetingMiner capstone. The work is committed and pushed;
diff `5a9da4b..HEAD`. The working tree is clean, so `git diff 5a9da4b HEAD` is the whole change
set.

One piece of history you need, because it affects what "pre-existing" means: story 1.3 was
originally implemented on a local branch that had diverged from `origin/main` at `3f0b52b`.
Both sides implemented story 1.10 independently. The local variant was dropped and these three
commits were rebased onto the remote's 1.10 line, which carries two extra commits we did not
have (`b88906a` close story 1.1 review gaps, `5a9da4b` harden story 1.10 environment
lifecycle). Every file story 1.3 extends was byte-identical across both variants, and the full
suite passes on the rebased result — but if you find an interaction between story 1.3 and that
1.10 hardening work, it was never exercised before the rebase and deserves extra scrutiny.

## Contract

`_bmad-output/implementation-artifacts/spec-1-3-checkpointed-ingestion-worker-probe-frames.md`
is the specification. The block inside `<intent-contract>` is frozen and human-owned: treat it
as the acceptance surface, not as something to critique for style. Everything outside that
block (Code Map, Tasks, Design Notes, Verification) is the planner's work and **is** in scope —
if the spec itself is wrong, say so and mark the finding as a spec defect rather than a code
defect.

Architecture authority, in precedence order:

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  — AD-1 (source drop), AD-3 (binaries on disk / relative paths), AD-5 (table ownership),
  AD-9 (runtime split), AD-11 (jobs as Postgres rows), AD-13 (immutable transcripts)
- `_bmad-output/planning-artifacts/epics.md` § "Story 1.3" — the five original acceptance criteria
- `_bmad-output/implementation-artifacts/epic-1-context.md` — distilled epic constraints

## Scope

**In scope** — the story 1.3 change set:

```
new:      server/meetingminer/domain/drops.py
          server/meetingminer/logs.py
          server/meetingminer/migrations/0002_meetings_media_frames.sql
          server/meetingminer/pipeline/{media,runner,stage}.py
          server/meetingminer/pipeline/stages/{__init__,probe,frames}.py
          server/tests/{test_content_root,test_drops,test_pipeline_media,test_worker_runner}.py
modified: server/meetingminer/{config.py,worker/main.py,domain/jobs.py,api/ingests.py}
          server/tests/{conftest.py,test_config.py,test_migrations.py}
          config.yaml, .env.example, infra/Makefile
```

Roughly 1,070 lines of new source plus 240 changed lines.

**Out of scope** — do not report findings against these:

- `pull_transcript/` (vendored, read-only)
- Anything already recorded in `_bmad-output/implementation-artifacts/deferred-work.md`
- Stories 1.4–1.6 functionality (`ocr`, `screens`, `transcribe`, `align`, `moments`) and
  Epic 4's `extract` — deliberately unimplemented here
- SSE / job-progress API surface (story 1.9)

**Separate secondary check** — commit `a56440e` (`server/meetingminer/api/jobs.py`,
`server/tests/test_jobs.py`, `server/tests/test_ingests.py`) is **not** story 1.3. It is the fix
for the two findings in your own
`_bmad-output/implementation-artifacts/review-story-1-2-2026-08-18.md`. Verify those two fixes
are correct and complete, and report that verdict in its own short section. In particular: the
`GET /jobs/{id}` rewrite swapped two statements for one `LEFT JOIN`, which changes the shape of
the returned rows — check the stage-ordering and no-stages paths, and satisfy yourself that the
new `test_requeue_committed_mid_read_cannot_split_job_from_its_stages` proves what it claims
rather than passing vacuously.

## Design decisions to attack specifically

These are deliberate choices made during planning. Each one is defensible but unproven — press
on them rather than accepting the stated rationale:

1. **The Meeting row is minted at claim time, not inside `probe`.** The epic's first acceptance
   criterion says "the first stage mints the Meeting row", but `probe` is skipped for
   transcript-only drops. Is minting at claim the right reconciliation, and is the
   `ON CONFLICT (job_id) DO UPDATE` upsert actually idempotent under a re-claim?
2. **Jobs pause at the first unimplemented stage and stay `running` forever.** Nothing ever
   moves such a job to `done`. Does anything else in the system assume `running` means
   "actively being worked on"? What happens after many worker restarts?
3. **Orphan recovery is a blanket `UPDATE job SET status='queued' WHERE status='running'` at
   worker startup, with no lease or heartbeat.** The justification is AD-9 (one worker, one Mac)
   plus the Makefile pidfile guard. Find the case where that assumption breaks — `make worker`
   run manually alongside a backgrounded `make up` worker is the obvious candidate.
4. **Frame offsets are computed as `(index - 1) * interval_ms`** rather than read from ffmpeg
   PTS. Verify this holds for variable-frame-rate input, for recordings shorter than one
   interval, and where the `fps` filter's first emitted frame actually lands.
5. **`MM_CONTENT_ROOT` became fatal at worker startup**, and the worker creates the directory
   when missing. Consider the blast radius: the shipped `.env.example` placeholder is
   `/Users/you/meetingminer-content`, so a fresh `make bootstrap && make up` now fails. Is the
   error message good enough to make that self-service?
6. **`frames` deletes its own output subtree before regenerating.** Audit the guard that keeps
   that delete inside `MM_CONTENT_ROOT` and scoped to one meeting id. This is the highest-blast-
   radius code in the change set.
7. **`updated_at` triggers were added to `job` and `job_stage`**, which story 1.2 shipped
   without. Confirm nothing depended on the old behavior, and that the trigger fires on every
   mutation path.

## Review lenses

Run these as independent passes and mark any finding confirmed by more than one lens with `(xN)`:

- **adversarial** — correctness, concurrency, idempotency, resource leaks, error paths
- **edge-case-hunter** — boundary and degenerate inputs: zero-length recording, drop with both
  transcripts, drop mutated between intake and claim, meeting id collisions, disk full
- **verification-gap** — claims the tests appear to cover but do not actually pin. Story 1.2's
  review found exactly this (`transcript.vtt` accepted in code, asserted only in prose), so
  weight it heavily. For each gap, name the mutation that would keep `make test` green.
- **acceptance-auditor** — the five epics.md Story 1.3 acceptance criteria and the nine rows of
  the spec's I/O & Edge-Case Matrix, each traced to a test that actually runs

## Verification baseline

Current state, so you can tell regression from pre-existing:

```
make test                                    # 205 passed, web build clean (verified at HEAD)
uv run --project server pytest server/tests  # same suite standalone
make migrate && make migrate                 # applies 0002 once, then no-op
```

Postgres must be up (`make infra-up`); ffmpeg and ffprobe are on PATH, so no test should skip.
If any test skips during your run, treat the skip itself as a finding.

## Output

Write to `_bmad-output/implementation-artifacts/review-story-1-3-2026-08-18.md`, matching the
structure of your story 1.2 review:

- A header block: date, content reviewed (with commit), lenses run and signal counts, exclusions
- Findings grouped by theme, each with: a one-line claim, the anchoring `file.py:line`, a
  concrete demonstration of the failure (inputs → wrong outcome, or the mutation that keeps the
  suite green), and a specific fix
- Mark cross-lens confirmations `(xN)`
- A short section with your verdict on the two story-1.2 fixes

Report findings; do not apply fixes. If you believe the specification rather than the code is
at fault, say so explicitly — that routes to a different repair path.
