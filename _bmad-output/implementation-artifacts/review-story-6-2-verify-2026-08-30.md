# Story 6-2 Remediation Verification Review

## Scope

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/6-2-review`
- Remediation range: `9b51bc7..a0a3da6`
- Review scope: remediation diff only
- Prior report: `_bmad-output/implementation-artifacts/review-story-6-2-2026-08-30.md`

## Findings

### VF1 — The supplied remediation range contains unrelated edits outside Story 6.2's frozen footprint

Location: `.claude/skills/integrate/dispatch.md:4` · Severity: medium · Finding: The exact range is not limited to Story 6.2 remediation. It changes integration policy and Story 11.2 artifacts that neither the original Story 6.2 footprint nor the remediation spec permits. · Evidence: `git diff --name-status 9b51bc7..a0a3da6` includes `.claude/skills/integrate/dispatch.md`, `_bmad-output/implementation-artifacts/build-prompt-story-11-2-remediation-2026-08-30.md`, and `_bmad-output/implementation-artifacts/spec-11-2-per-run-store-isolation.md`; `git log --reverse 9b51bc7..a0a3da6` attributes them to `b902420`, `211857c`, `73257eb`, and `a011695`, before the Story 6.2 remediation commits. · Resolution: Open — owner decision required. Reverting shared integration and Story 11.2 work on this lane would widen the review again and could undo work already present on `main`; the owner must either narrow the declared remediation range to the actual fix commits or explicitly accept these ancestors as range noise.

### VF2 — Valid-URL refusals still write-probe the drops root before refusing

Location: `server/meetingminer/youtube.py:772` · Severity: high · Finding: `main()` called `resolve_drops_root()` before `acquire()` could issue tool, probe, duration, stream, timestamp, publisher, or identity refusals. The shared resolver creates and removes `.staging`, so those refusals did not satisfy the frozen Story 6.2 guarantee that every refusal occurs before anything is written to the drops root. · Evidence: `server/meetingminer/mintdrop.py:440-453` executes `staging_root.mkdir(...)` and then best-effort `rmdir()`. Red test `test_main_defers_the_drops_root_write_probe_until_acquisition_accepts` failed because the mutating resolver left `.staging` before a simulated probe refusal. · Resolution: Resolved (VF2). `main()` now performs equivalent root/namespace checks through a read-only resolver and passes the shared writable probe into `acquire()` as a deferred callback; `acquire()` invokes it only after all downloaded metadata and caption gates pass, immediately before `mint()`. The focused regression plus existing invalid-URL and CLI-parity tests pass (4 passed).

### VF3 — The `exists` validator's checksum resolution has a mutation-surviving test gap

Location: `server/tests/test_youtube.py:702` · Severity: high · Finding: The post-build report claims that the local `exists` path validates checksum and byte-size evidence before POST, but its only malformed-legacy regression removes `formatId`. It cannot fail when the checksum branch is deleted. · Evidence: Exact mutation `if entry.get("sha256") != digest or entry.get("byteSize") != size:` → `if False:` at `server/meetingminer/youtube.py:589`; both `test_incomplete_legacy_existing_drop_is_refused_without_yt_dlp` and `test_an_already_minted_video_short_circuits_before_any_yt_dlp_call` still passed (`2 passed`). · Resolution: Open pending a checksum/size regression observed red against that mutation, then green after restoration.
