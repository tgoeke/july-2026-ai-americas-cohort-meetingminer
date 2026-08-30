# Code Review — Story 4-3: Per-Moment Approval & Publishing

## Scope

- Reviewed branch: `story/4-3` at `154e1e3defaad2f6c390cc23547d1a0acfaec72a`
- Reviewed range: `69b767b50a42c04ba726c707fb68f0f7aa113219..154e1e3defaad2f6c390cc23547d1a0acfaec72a`
- Review date: 2026-08-21
- Review mode: full, against `spec-4-3-per-moment-approval-publishing.md` and its declared context

## Findings

### Location
`server/tests/test_publish_export.py:210-221`

### Severity
high

### Finding
The required store-free publish-export suite fails: its fake `git` program
cannot start `sleep` after the test deliberately replaces `PATH` with a
directory that contains only that program. This means the test proves neither
the timeout mapping nor the story's stated verification baseline.

### Evidence
Running `uv run --project server pytest server/tests/test_publish_export.py
server/tests/test_publish_root.py -q` on `154e1e3` produced one failure. The
script at line 215 runs `sleep 60`, while line 218 sets `_GIT_ENV["PATH"]` to
`fake_bin`; the observed `GitExportError` is `sleep: command not found`, not
the expected `timed out` error.

### Suggested direction
Make the fake executable self-contained (for example, an infinite shell loop)
or preserve the absolute path required by its wait command, then confirm the
test fails against the unfixed version and exercises `TimeoutExpired` after
the fix.

### Location
`web/src/features/moments/MomentView.tsx:126-151`

### Severity
medium

### Finding
The approval request has no timeout, unlike the moment read despite the frozen
contract requiring reuse of its AbortController/timeout pattern. A hung API
request leaves the only publishing control permanently disabled as
“Publishing…”.

### Evidence
`load` creates an expiry controller and timer at lines 79-110, but
`handleApprove` supplies only `controller.signal` at lines 126-151. Its
`finally` cannot clear `approving` until the request settles, which a stalled
connection need not do.

### Suggested direction
Give approval the same cancellable expiry pattern as the initial load and
render a recoverable timeout error; add a test that advances the timer and
asserts the button becomes usable again.

### Location
`server/meetingminer/publish/export.py:182-204`

### Severity
high

### Finding
Publishing to the shared Git repository is neither serialized nor scoped to
the artifact being published. Concurrent approvals for different moments can
race the index, commit each other's staged files, fail on `index.lock`, or
store an unrelated HEAD as an artifact's commit SHA.

### Evidence
The route's `FOR UPDATE` lock is per `moment_id` (`api/moments.py:625-631`),
while every ADR shares `MM_PUBLISH_ROOT`. `commit_artifact` runs `git add` and
then unrestricted `git commit` at lines 182-190, followed by a separate
`git rev-parse HEAD` at lines 201-204. Another approval (or a human-staged
file) can intervene in each gap; an action-item staged by that other writer is
then included despite AC3's requirement that action-items are never committed.

### Suggested direction
Make the complete repo mutation critical section safe for all API processes,
commit only the intended artifact path, and derive the recorded SHA from that
artifact's commit. Add a concurrent-different-moments regression that proves
each row gets its own correct commit and no extra staged file is committed.

### Location
`server/meetingminer/publish/export.py:44, 150-168`; `server/meetingminer/api/moments.py:641-668`

### Severity
high

### Finding
The publish-root ownership policy is internally inconsistent: an existing
operator-created repository is rejected without the private marker, yet the
route writes the artifact before it performs that rejection; an action-item
only approval never performs the ownership check at all.

### Evidence
`ensure_git_repo` raises for every existing `.git` without
`meetingminer-publish-root-owner` (lines 150-165), although the story promises
to commit ADRs to a plain repository rooted at `MM_PUBLISH_ROOT`. The route
calls `export_artifact` first (lines 641-645), and calls `ensure_git_repo`
only for `adr` rows (654-668). Therefore a configured foreign repository can
receive an untracked export before the ADR request returns 500, or a successful
action-item export with no ownership validation.

### Suggested direction
Resolve and record the intended trust model for an already initialized
`MM_PUBLISH_ROOT` (operator-owned repos versus a MeetingMiner-created-only
directory). Apply its validation before any export, consistently for both
artifact kinds, and cover a legitimate pre-existing repository and a rejected
foreign target. This needs a frozen-contract amendment before implementation.

### Location
`server/meetingminer/publish/export.py:44, 223-231`

### Severity
medium

### Finding
Git subprocesses inherit process-wide Git control variables, so a deployment
environment containing `GIT_DIR`, `GIT_WORK_TREE`, or `GIT_INDEX_FILE` can
redirect operations away from `MM_PUBLISH_ROOT` despite the supplied `cwd`.

### Evidence
`_GIT_ENV` is `{**os.environ, "LC_ALL": "C", "LANG": "C"}` at line 44 and
is passed directly to every git invocation at lines 223-231. Git gives these
environment variables precedence over repository discovery.

### Suggested direction
Construct a deliberately minimal Git environment that preserves only required
execution settings and removes Git repository/index overrides; regression-test
that a hostile inherited Git directory cannot redirect an artifact commit.

### Location
`server/meetingminer/publish/export.py:167-168`

### Severity
medium

### Finding
Failures from the two required local-identity configuration commands are
ignored. A later commit can then use an unintended global identity or fail with
a less specific error, instead of reporting the configuration failure that
caused it.

### Evidence
`_run` deliberately returns nonzero subprocess results to its callers, and
the function checks them for `init`, `add`, `commit`, and `rev-parse`; lines
167-168 are the only Git calls whose `returncode` is discarded.

### Suggested direction
Translate a nonzero local `git config` result into `GitExportError` before
attempting a commit, with coverage for each identity-setting failure.

### Location
`server/tests/test_failfast.py:128-176`; `server/tests/conftest.py:137-145`

### Severity
low

### Finding
The new fail-fast publish-root gate is tested only through its helper, while
the process-wide fixture always supplies `MM_PUBLISH_ROOT` before importing
the API. Its required startup behavior can regress without a subprocess/API
startup test detecting it.

### Evidence
`test_publish_root.py` calls `require_publish_root` directly. The real API
startup test module already launches isolated imports for other startup gates,
but no case reaches a valid config/drops root with `MM_PUBLISH_ROOT` absent;
the global fixture populates that value at `conftest.py:143-145`.

### Suggested direction
Add a subprocess import or Uvicorn test using otherwise-valid configuration
and no publish root, asserting exit status 1, the named diagnostic, and no
traceback.

### Location
`_bmad-output/implementation-artifacts/sprint-notes.md:201-230`

### Severity
medium

### Finding
Cross-story operational finding: whole-transcript extraction can mint an ADR
and an action-item for the same decision at the same anchor. Story 4-3
correctly publishes every extracted artifact in a moment, so it will publish
both members of this upstream duplicate pair.

### Evidence
The first authorized extraction run recorded a concrete pair at 2736s with
near-identical titles (`A9` action-item and `D4` ADR), and explains that the
per-moment approval gesture publishes both. This behavior is outside 4-3's
frozen “publish everything extracted” contract.

### Suggested direction
Do not patch Story 4-3 for this. Route the evidence to Story 4-1a/Epic 4
triage for an upstream deduplication and artifact-kind policy decision before
Story 4-4 makes the duplicates citable.

## Decision Resolution

On 2026-08-21, the user selected an operator-created existing Git repository
as a valid `MM_PUBLISH_ROOT`: configuration is authorization. The remediation
is therefore to initialize Git only when `.git` is absent and to remove the
private-marker rejection; a regression test must publish successfully to an
existing configured repository.

## Remediation Closeout

All seven patch findings are resolved by `d402788` and `6910744`, then reviewed
again with blind-hunter, edge-case, and verification-gap layers. The follow-up
closed bounded cross-process locking, existing-repository identity preservation,
path-specific retry provenance, and deadline-signal coverage.

Verified on the remediated branch:

- `38 passed` — publish-export, publish-root, and API fail-fast tests
- `46 passed` — artifact-publish and moments API tests
- `24 passed` — `MomentView` tests
- `pnpm --dir web exec tsc --noEmit`, `make check-reviews`, and `git diff --check`

**Review result: pass.** The only remaining duplicate-artifact-pair item is
the explicitly deferred upstream Story 4-1a/Epic 4 concern, not a 4-3 defect.
