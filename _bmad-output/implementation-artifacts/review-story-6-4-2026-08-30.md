# Review — Story 6.4: Acquisition Launch Surface

## Scope

Adversarial review and report-first remediation of Story 6.4 on
`story/6-4-review`, limited to the story paths and tracking artifacts named in
the review handoff. Frozen intent defects will be reported but not patched.

## Range

- Baseline: `e5e0ff9`
- Story tip at review dispatch: `6269ad9`
- Review range: `e5e0ff9..6269ad9`
- Review branch: `story/6-4-review`, cut from `story/6-4`

## Findings

### F1 — The parent can overwrite a fast child's terminal status with `queued`

- **Location:** `server/meetingminer/acquisitions.py:684-713`
- **Severity:** High
- **Finding:** `launch()` starts the detached child and only afterwards writes
  the returned pid using its stale pre-launch `queued` record. The child does
  not take the claim lock before its first status transition, so it can write
  `running`, `posted`, or `failed` before the parent resumes from `Popen`; the
  parent's final write then regresses that newer state to `queued`. A fast
  `exists` acquisition can therefore appear queued forever and lose its
  `result`, job id, provenance, or refusal.
- **Evidence:** A direct scheduling reproduction replaced `Popen` with the
  behavior a fast child is permitted to exhibit: read the already-created
  record, write `posted/result=exists`, then return its pid. Unfixed
  `launch()` returned and stored `status=queued, result=None`, proving the
  terminal write was lost. The existing launch test substitutes `/bin/sleep`,
  which never writes acquisition state and cannot expose this interleaving.
- **Suggested direction:** Make the child's initial read/transition wait on
  the same claim lock the parent holds through its pid write, so the parent
  establishes `queued+pid` before the child can advance it. Add a deterministic
  concurrency regression that observes the child blocked until the parent
  releases the lock and proves a terminal transition is never overwritten.

### F2 — Child config failure leaves a dead acquisition permanently `queued`

- **Location:** `server/meetingminer/acquisitions.py:628-640,840-848`
- **Severity:** Medium
- **Finding:** The detached child reloads config before it can derive the
  acquisition-state directory. If that load raises `ConfigError`, `main()`
  only prints to the log and exits. The status file remains `queued` with a
  dead pid and no `refusal`, contradicting the story's central contract that a
  failed acquisition explains itself through fields rather than requiring log
  parsing. This challenges deferred item 3: the API already knows the
  validated state root, and passing that location to its own child is wholly
  within the new launcher module's footprint.
- **Evidence:** With a real queued record in an isolated acquisition root and
  `_load_cli_config()` forced to raise `ConfigError("broken config")`, unfixed
  `main()` returned 1 while the stored record remained
  `status=queued, refusal=None`. No existing test invokes the CLI config-failure
  path; runner tests begin after a usable `AppConfig` already exists.
- **Suggested direction:** Include the already-resolved acquisition-state root
  in the child argv. On pre-run config failure, use that explicit root to
  atomically advance the existing record to `failed` with rule `config`, full
  detail, and the table remediation, while retaining the log line as diagnostic
  output. Validate the passed root as an absolute path owned by the parent, not
  a request-derived value.

### F3 — The probe performs provenance checks outside its frozen boundary

- **Location:** `server/meetingminer/youtube.py:608-642`
- **Severity:** Medium
- **Finding:** `probe_only()` calls the full acquisition `validate_info()`
  helper. Besides the required URL/identity, availability, stream, tool, and
  duration checks, that helper also requires a publication wall clock and a
  channel/uploader. The frozen intent says the probe performs the enumerated
  checks "and nothing else". Valid probe metadata can therefore be rejected as
  `started-at-unknown` or `channel-missing`, even though neither is part of the
  pre-submit probe contract.
- **Evidence:** Starting from the valid full probe fixture, removing only
  `release_timestamp`/`upload_date` (and unrelated publisher fields) while
  retaining a matching video id, playable video format, and valid duration
  made unfixed `probe_only()` refuse with `started-at-unknown`. Inspection of
  `validate_info()` confirms the additional calls to `started_at_from_info()`
  and `_channel_from_info()`. The new tests cover duration, stream, captions,
  and title but never isolate either extra provenance requirement.
- **Suggested direction:** Compose the probe from the identity check and
  `refuse_unacceptable()` rather than the full provenance validation helper.
  Add regressions showing missing publication time and missing publisher do
  not prevent the four-field probe response; acquisition remains free to
  refuse them later before minting write-once evidence.
