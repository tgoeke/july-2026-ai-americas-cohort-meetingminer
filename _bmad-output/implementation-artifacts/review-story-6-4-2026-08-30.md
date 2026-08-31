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

### F4 — A known intake outage is published as the unknown fallback token

- **Location:** `server/meetingminer/acquisitions.py:764-783` and
  `server/meetingminer/youtube.py:188-196`
- **Severity:** Medium — Open, owner decision required
- **Finding:** `IntakeError` is a distinct, expected failure after a finalized
  drop exists, but `youtube.refusal_rule()` maps it to the catch-all
  `unclassified` token. The acquisition does provide an excellent failure-
  specific re-POST remediation, yet the stable machine field cannot distinguish
  "the intake API did not answer" from any genuinely unknown exception. That
  weakens the purpose of a stable refusal vocabulary for the future UI.
- **Evidence:** `refusal_rule()` has explicit branches for `YoutubeError`,
  `MintError`, and `ConfigError`, then returns `unclassified` for every other
  type. `run_acquisition()` catches `IntakeError` separately but calls that
  fallback, and
  `test_an_intake_failure_is_failed_and_names_the_repost_command` explicitly
  pins `rule == "unclassified"`. Thus this is shipped behavior, not a missing
  test. The detail and remediation remain failure-specific, confirming the
  condition itself is already distinguishable.
- **Suggested direction:** Owner to authorize a closed-vocabulary extension
  such as `intake-failed` in `youtube.REFUSAL_RULES`, with literal remediation
  and status-table entries and the existing intake regression updated. Do not
  invent a second vocabulary. This review leaves it open because changing the
  pre-existing refusal set/function exceeds the lane's allowed `youtube.py`
  addition and needs an explicit footprint ruling.

### F5 — The table tests do not guard most rule-to-status semantics

- **Location:** `server/tests/test_api_acquisitions.py:799-822`
- **Severity:** Medium
- **Finding:** The implementation deliberately hand-writes every refusal table
  entry so a future rule cannot acquire a silent default, but the claimed guard
  checks only key completeness, non-empty remediation text, the overall set of
  three status values, and seven selected rule values. Most existing rules can
  be moved among 400/422/503—or have their remediation text swapped—without a
  failure. The costly literal tables are therefore protected against missing
  keys but not against the desynchronization risk used to justify them.
- **Evidence:** As a review mutation, changing only
  `PROBLEM_STATUS["probe-failed"]` from 422 to 400 preserved the keys and the
  aggregate value set. All table-focused tests stayed green: 3 passed, 32
  deselected. `probe-failed` is an actual probe response consumed by the UI,
  so this is observable contract drift rather than an internal refactor.
- **Suggested direction:** Pin the complete expected status buckets explicitly
  in the test (one declared host set, one bad-request set, and an exact
  remainder assertion), so moving any rule is a reviewed contract change.
  Add rule-specific remediation assertions or a compact checked snapshot for
  entries whose action differs materially; do not compare responses back to
  the same production dict, which is tautological.

### F6 — Server/tool failures are mislabeled as client-content refusals

- **Location:** `server/meetingminer/acquisitions.py:276-310`
- **Severity:** Medium
- **Finding:** The table rationale says 503 is for conditions where this host
  cannot answer and the URL may be fine, but several rules with exactly that
  meaning are assigned 422. Most importantly, `probe-unreadable` is reachable
  directly through the probe API when this host's yt-dlp returns output the
  server cannot parse. `identity-mismatch`, `format-id-missing`,
  `download-incomplete`, `tool-version-missing`, `drops-root-changed`, and an
  incomplete existing local drop likewise direct the operator to upgrade or
  repair the host, not change the submitted video. A UI can therefore present
  a server/tool outage as invalid user content and suppress appropriate retry
  behavior.
- **Evidence:** `_refusal_problem()` maps these table values straight to the
  response. Direct classification showed `probe-unreadable`,
  `identity-mismatch`, `drops-root-changed`, and `existing-drop-incomplete` all
  become 422, while their literal remediations respectively say to upgrade
  yt-dlp, restart/check the host configuration, or quarantine corrupt host
  state. This also explains why the F5 mutation survives: the suite pins only
  the six originally selected host rules.
- **Suggested direction:** Reclassify the unambiguous tool-output and local-
  host-state rules as 503, keeping source/video conditions such as private
  video, duration cap, no video stream, and missing publication metadata at
  422. Encode the full reviewed partition in the F5 regression so future
  category changes cannot pass as key-complete edits.

### F7 — The recorded focused verification count is not reproducible

- **Location:** `_bmad-output/implementation-artifacts/review-prompt-story-6-4-2026-08-30.md:227-229`
- **Severity:** Low
- **Finding:** The handoff says the registry/YouTube/playlist command produced
  201 passed and 1 skipped, but the exact command has only 168 collected tests
  and produces 167 passed and 1 skipped. A precise baseline that cannot come
  from its named command makes later count changes look like regressions.
- **Evidence:** The command was rerun verbatim after the required rebase and
  reported 167 passed / 1 known network skip; `--collect-only` reported 168.
  None of the three named test files or `server/pyproject.toml` changed between
  dispatched baseline `e5e0ff9` and current main. The only intervening
  `conftest.py` edit adds Story 10.2 thread tables to database cleanup and does
  not alter collection. The likely 201 figure was copied from a combined count,
  not this command.
- **Suggested direction:** Correct the handoff's recorded result to 167 passed,
  1 skipped, leaving the known network-skip explanation unchanged.
