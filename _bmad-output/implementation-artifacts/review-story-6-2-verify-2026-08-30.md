# Story 6-2 Remediation Verification Review

## Scope

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/6-2-review`
- Remediation range: `9b51bc7..a0a3da6`
- Review scope: remediation diff only
- Prior report: `_bmad-output/implementation-artifacts/review-story-6-2-2026-08-30.md`

## Findings

### VF1 — The supplied remediation range contains unrelated edits outside Story 6.2's frozen footprint

Location: `.claude/skills/integrate/dispatch.md:4` · Severity: medium · Finding: The exact range is not limited to Story 6.2 remediation. It changes integration policy and Story 11.2 artifacts that neither the original Story 6.2 footprint nor the remediation spec permits. · Evidence: `git diff --name-status 9b51bc7..a0a3da6` includes `.claude/skills/integrate/dispatch.md`, `_bmad-output/implementation-artifacts/build-prompt-story-11-2-remediation-2026-08-30.md`, and `_bmad-output/implementation-artifacts/spec-11-2-per-run-store-isolation.md`; `git log --reverse 9b51bc7..a0a3da6` attributes the merge-side baseline history to the main-owned commits `b902420`, `211857c`, `73257eb`, and `a011695`, before the Story 6.2 remediation commits. The same main-owned policy lineage was subsequently made explicit by `f17b87a`, which corrected `_bmad/custom/bmad-build-auto.toml` and added `_bmad-output/implementation-artifacts/owner-decisions-2026-08-30.md` carrying Story 7.1's telemetry ruling; `f17b87a` postdates this range and is named here to identify the owner-disposed shared policy, not as a reachable commit in `9b51bc7..a0a3da6`. · Resolution: Resolved by owner disposition (2026-08-30). The owner accepts the merge-baseline exception. These are main-owned changes outside Story 6.2's footprint by construction, not builder overreach; the reviewer-facing error was defining the range from the story-branch tip across a remediation merge. No shared policy was reverted and history was not rewritten.

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

Location: `docs/README.md:182` · Severity: medium · Finding: Commit `20b3eb4` corrected the operator contract from the false blanket “before writing anything” promise to distinguish permanent drops-root writes from temporary download bytes, but no test observed that correction. · Evidence: Exact mutation `It refuses before any permanent write` → `Like mint-drop, it refuses before writing anything` (with the original Markdown emphasis restored) initially left the full Story 6.2 module green (`102 passed, 1 skipped`). New `test_readme_distinguishes_temporary_downloads_from_permanent_writes` failed under the same mutation because the permanent-write contract disappeared. · Resolution: Resolved (VF7). The focused documentation contract test passes after restoration and also pins the temporary-bytes disclosure and absence of the false blanket claim.

### VF8 — Malformed blank or non-string `vcodec` values pass the no-video refusal

Location: `server/meetingminer/youtube.py:316` · Severity: high · Finding: The shared probe/download validator treated every `vcodec` value except `None` and literal `"none"` as proof of a video stream. Empty strings, whitespace, booleans, and other malformed values therefore passed the pre-download refusal despite the remediation's fail-closed metadata contract. · Evidence: Red `test_malformed_video_codec_is_refused_at_probe` reached the `download must not be invoked` sentinel for all six malformed values. After the fix, exact mutation of the strict four-clause predicate back to `isinstance(entry, dict) and entry.get("vcodec") not in (None, "none")` reproduces all six failures. · Resolution: Resolved (VF8). The shared validator now requires a non-blank string codec whose normalized value is not `none`; the six-case regression passes restored and therefore covers both probe and downloaded calls to `validate_info()`.

## Mutation evidence

All mutations were made in the isolated review worktree, run in the foreground, and restored immediately. A “failed” result below is the required red result.

1. F1 protected provenance: `collisions = sorted(MINT_OWNED_PROVENANCE_KEYS.intersection(normalized))` → `collisions = []`. Collision regression: 5 failed; restored: 5 passed.
2. F1 non-mapping correction: `if not isinstance(extra, Mapping):` → `if False:`. Non-mapping regression failed because the wrong collision error replaced the named mapping refusal; restored: 1 passed.
3. F1 early refusal correction: deleted `_validate_provenance_extra(provenance_extra)` before classification. Existing-source collision regression failed with `DID NOT RAISE MintError`; restored: 1 passed.
4. F2 duration boundary: `if not _is_finite_number(duration) or duration < 0:` → `if False:`. Probe/downloaded-duration selection: 9 failed, 7 passed; restored: 16 passed.
5. F3 downloaded boundary: deleted the downloaded `validate_info(...)` block. Downloaded-metadata matrix: 2 failed (over-cap and lost video stream), 7 passed because downstream mappers independently retained other guards; restored: 9 passed.
6. F4 source identity: deleted `_validate_video_identity(info, expected_video_id)` from `validate_info()`. Probe identity selection: 2 failed by reaching the forbidden download; restored: 2 passed.
7. F5 publisher normalization: `if isinstance(value, str) and value.strip(): return value.strip()` → `if isinstance(value, str): return value`. Publisher selection: 3 failed, 1 passed; restored: 4 passed.
8. F5 provenance completeness: deleted `"formatId": _format_id_from_info(info)`. Exact provenance-map test failed; restored: 1 passed.
9. F6 tool preflight: deleted `(FFPROBE, FFMPEG)` from `ensure_tools()`. Missing-ffprobe regression failed by invoking yt-dlp; restored: 1 passed.
10. F7 timestamp defense, first probe: `_is_finite_number(release)` → `isinstance(release, (int, float))`. All 4 tests still passed because the exception guard independently preserved the fallback; this was a non-breaking mutation, not evidence of a weak test.
11. F7 timestamp defense, breaking probe: `except (OSError, OverflowError, ValueError):` → `except OSError:`. Out-of-range timestamp selection: 1 failed, 3 passed; restored: 4 passed.
12. F8 caption materialization: exact `{video_id}.{language}.vtt` selection → the first `*.vtt` in the work directory. Manual/automatic regression: 2 failed by accepting the French VTT; restored: 2 passed.
13. F8 caption drift: deleted the downloaded/probe caption comparison block. Drift regression failed by reaching the forbidden mint; restored: 1 passed.
14. F9 CLI ordering: `video_id_from_url(args.url)` → `pass` in the early classifier. Invalid-URL main regression failed because `.staging` appeared; restored: 1 passed.
15. F10 Make-time injection correction: deleted `unexport URL`. Hostile Make test: shell payload passed, literal `$(shell ...)` payload failed by creating the sentinel; restored: 2 passed.
16. F10 shell injection correction: recipe `"$${MM_YOUTUBE_URL}"` → `"$(URL)"`. Both hostile payload cases failed by creating the sentinel; restored: 2 passed.
17. F11 command coverage: automatic/manual branch → unconditional `--write-subs`. Download command matrix: automatic-caption case failed, other 2 passed; restored: 3 passed.
18. F12 configured-cap forwarding: configured value → `max_duration_minutes=180`. Created/exists CLI cases both failed (`180 != 37`); restored: 2 passed.
19. Post-build existing-drop validator: validation call → direct JSON metadata read. Incomplete legacy regression failed with `DID NOT RAISE YoutubeError`; restored incomplete/happy selection: 2 passed.
20. Metadata precision trap: release-timestamp precision `"second"` → `"day"`. Precision mapping regression failed; restored: 1 passed.
21. Existing checksum claim, original tests: checksum/size guard → `if False:`. Both prior existing-path tests still passed (`2 passed`), producing VF3. The new checksum regression then failed with `DID NOT RAISE YoutubeError` under the same mutation and passed restored.
22. VF4 duplicate manifest fix: `if name in entries:` → `if False:`. Duplicate-row regression failed with `DID NOT RAISE YoutubeError`; restored: 1 passed.
23. VF5 source-identity fix: `_find_existing_youtube_drop(scope, source_id)` → `find_existing_drop(scope, source_id)`. Corrupt digest-named drop regression failed by invoking `ensure_tools`; restored: 1 passed.
24. Existing duration-cap claim, original tests: cap guard → `if False:`. Five prior existing-path regressions still passed, producing VF6. The new cap regression then failed with `DID NOT RAISE YoutubeError` under the same mutation and passed restored.
25. Existing started-at-source claim, original tests: source/precision guard → `if False:`. Five prior existing-path regressions still passed, producing VF6. The new source regression then failed with `DID NOT RAISE YoutubeError` under the same mutation and passed restored.
26. Refusal-timing documentation: `It refuses before any permanent write` → the original blanket `Like mint-drop, it refuses before writing anything` wording. After correcting three VF2 test fixtures to create their configured roots, the full module still passed (`102 passed, 1 skipped`), producing VF7. The new documentation contract test failed under the same mutation and passed restored.
27. VF8 video-stream fix: strict non-blank string codec predicate → `entry.get("vcodec") not in (None, "none")`. All 6 malformed-codec cases failed by reaching the forbidden download; restored: 6 passed.

VF2 used the pre-fix implementation directly rather than an artificial mutation: `test_main_defers_the_drops_root_write_probe_until_acquisition_accepts` failed because the resolver created `.staging` before the simulated probe refusal, then passed after the deferred-probe patch.

## Verification

- `uv run --project server pytest server/tests/test_youtube.py -q` — 109 passed, 1 skipped by the named `MM_YOUTUBE_NETWORK_TEST` gate, 1 dependency deprecation warning.
- `make test-fast` — puller 128 passed; web 291 passed; eval harness 549 passed; server 1,510 passed, 1 named YouTube network skip, 326 slow tests deselected, 1 dependency deprecation warning.
- `make check-reviews` — `check-reviews: every dispatched review has a committed report`.
- `make evals-run` was not run.

## Open items

- **F13 — owner architecture/spec decision, intentionally untouched:** decide whether `acquisition.youtube.max_duration_minutes` may retain code defaults or must be required in versioned `config.yaml` under AD-10.
- **Known integration item, not a finding:** `server/meetingminer/mintdrop.py` has an already-rehearsed union with `story/6-3`. That builder took the `mint()` / `build_metadata()` override hunk verbatim from `7625b79`, so the branches were clean at that shared change. Story 6.3 also executed and tested the exact later merge resolution with this lane's `provenance_extra` mint-owned-key refusal; `transcriptDialect` is not a mint-owned key. Integrate still owns the union, but no speculative reconciliation belongs on this branch.

## Verdict

The remediation behavior and its added fixes pass verification: F1-F12 and VF2-VF8 are mutation-backed and green. The lane does **not** receive an unconditional pass because VF1 and prior F13 remain owner decisions. There are no open code patches from this verification round, the branch was not merged, and `main` was not touched.

Verified implementation head before this report-only closeout: `8d557327d43cbb3713696ba8ee88e2d065ddbc18`.
