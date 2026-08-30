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

Location: `server/tests/test_youtube.py:702` · Severity: high · Finding: The post-build report claims that the local `exists` path validates checksum and byte-size evidence before POST, but its only malformed-legacy regression removed `formatId`. It could not fail when the checksum branch was deleted. · Evidence: Exact mutation `if entry.get("sha256") != digest or entry.get("byteSize") != size:` → `if False:` at `server/meetingminer/youtube.py:589`; both prior `exists` tests still passed (`2 passed`). New `test_existing_drop_with_false_evidence_digest_is_refused_without_yt_dlp` then failed against that same mutation with `DID NOT RAISE YoutubeError`. · Resolution: Resolved (VF3). The checksum-specific regression passes after restoration and stubs `ensure_tools`, `probe`, and `download`, proving a corrupt existing manifest is refused locally without a media network path.

### VF4 — Duplicate evidence-manifest rows bypass the claimed exactness check

Location: `server/meetingminer/youtube.py:613` · Severity: high · Finding: `validate_existing_youtube_drop()` constructed `entries` with a dict comprehension keyed by `dropFilename`. Duplicate rows collapsed to one key, so a manifest containing two `recording.mp4` rows could satisfy `set(entries) == set(actual)` and be POSTed as if it exactly described the finalized evidence. · Evidence: The source-drop schema intentionally leaves `provenance` open and imposes no `uniqueItems` rule. Red test `test_existing_drop_with_duplicate_manifest_rows_is_refused_without_yt_dlp` failed with `DID NOT RAISE YoutubeError`; after the fix, exact mutation `if name in entries:` → `if False:` makes the same test fail. · Resolution: Resolved (VF4). The validator now refuses non-object rows, rows without a usable `dropFilename`, and duplicate names before comparing the manifest to actual evidence; the focused test passes restored.

### VF5 — The recorded existing-drop source-identity check is normally unreachable

Location: `server/meetingminer/youtube.py:695` · Severity: high · Finding: The post-build report said the local `exists` path validates source identity without yt-dlp, but `find_existing_drop()` filters candidates by `metadata.sourceId` before returning them. A directory whose name carries the requested source digest but whose metadata carries another source ID was silently treated as absent, so `validate_existing_youtube_drop()` never reached its source-ID refusal and acquisition proceeded toward the media network. · Evidence: `server/meetingminer/mintdrop.py:482-493` skips the readable digest-matching mismatch. Red test `test_digest_named_drop_with_wrong_source_id_refuses_without_yt_dlp` reached the `ensure_tools must not be invoked` sentinel; after the fix, exact mutation `_find_existing_youtube_drop(scope, source_id)` → `find_existing_drop(scope, source_id)` reproduces that failure. · Resolution: Resolved (VF5). A YouTube-specific wrapper retains the shared finder for normal matches, then fail-closes on stable digest-named identity conflicts before any tool or media call; the focused test passes restored.

### VF6 — Duration-cap and started-at-source branches in the `exists` matrix remain mutation-surviving

Location: `server/tests/test_youtube.py:678` · Severity: high · Finding: The recorded post-build resolution also claimed configured-cap and started-at provenance checks for existing drops, but none of the existing-path regressions exercised those branches. · Evidence: Exact mutation `if duration > max_duration_minutes * 60:` → `if False:` in the existing-drop validator initially left all five existing-path regressions green (`5 passed`). After restoration, exact mutation `if provenance.get("startedAtSource") != expected_start_source:` → `if False:` also left the same five green (`5 passed`). New cap and started-at-source regressions each failed with `DID NOT RAISE YoutubeError` under its respective mutation. · Resolution: Resolved (VF6). Both focused tests pass after restoration and independently stub the tool, probe, and download boundaries (`2 passed`).

### VF7 — The refusal-timing documentation correction has no mutation-sensitive proof

Location: `docs/README.md:182` · Severity: medium · Finding: Commit `20b3eb4` corrected the operator contract from the false blanket “before writing anything” promise to distinguish permanent drops-root writes from temporary download bytes, but no test observes that correction. · Evidence: Exact mutation `It refuses before any permanent write` → `Like mint-drop, it refuses before writing anything` (with the original Markdown emphasis restored) left the full Story 6.2 module green (`102 passed, 1 skipped`). · Resolution: Open pending a documentation contract regression observed red under the false wording and green after restoration.
