# Adversarial Code Review — Story 6.2

## Scope

Review of the Story 6.2 YouTube Acquisition Command implementation, limited to the files and edits named in the external review prompt. Findings are judged against the frozen intent contract, the cited architecture decisions, the source-drop schema, and repository invariants.

## Review range

- Subject branch: `story/6-2`
- Baseline: `5cdfce7`
- Range: `5cdfce7..story/6-2`
- Review worktree branch: `story/6-2-review`
- Review date: 2026-08-30

## Findings

### F1 — Unrestricted provenance overrides can falsify immutable evidence metadata

- **Location:** `server/meetingminer/mintdrop.py:572-589`
- **Severity:** high
- **Finding:** `provenance_extra` is merged after every mint-owned provenance field, so a producer can replace `files`, `mintedAt`, `startedAtSource`, `title`, or `suppliedBy`, not only the intended `tool` value. That defeats the one assembly path's guarantee that provenance describes the bytes copied into the write-once drop.
- **Evidence:** `provenance.update(provenance_extra)` has no collision guard. A targeted reproduction passed `{"files": [], "startedAtSource": "fabricated", "mintedAt": "never"}` and the resulting metadata still validated against `docs/source-drop.schema.json`, despite no longer describing the supplied `recording.mp4`. This conflicts with AD-1/AD-17 and the repository's fail-closed invariant.
- **Suggested direction:** Reserve mint-owned integrity keys and reject collisions by name. Give producers explicit parameters for the small set of intentional variations (at minimum `tool`) rather than a map that can overwrite the evidence manifest.

### F2 — Unknown or invalid duration bypasses the configured refusal boundary

- **Location:** `server/meetingminer/youtube.py:244-267`, `server/meetingminer/youtube.py:394-396`
- **Severity:** high
- **Finding:** The duration guard only acts when `duration` is already an `int` or `float`. Missing, string-valued, negative, or `NaN` durations pass the probe gate; the mapper then silently omits `durationSeconds` for some of those values. The command can therefore start an unbounded download and mint metadata missing a field the frozen contract requires.
- **Evidence:** Calling `refuse_unacceptable({"formats": [{"vcodec": "avc1"}]}, max_duration_minutes=180)` returns successfully. `provenance_extra_from_info()` conditionally adds `durationSeconds`, while the source-drop schema leaves provenance open, so schema validation does not restore the story guarantee. This violates the configured cap, the exact provenance field list, and fail-closed behavior.
- **Suggested direction:** Require a finite, non-negative numeric duration at probe time and refuse missing or malformed duration by name before download. Apply the same invariant to the downloaded metadata before it can reach `mint()`.

### F3 — Downloaded metadata can invalidate the probe decision and still be minted

- **Location:** `server/meetingminer/youtube.py:435-463`
- **Severity:** high
- **Finding:** `acquire()` applies the duration and timestamp refusal matrix only to probe data, then derives the finalized wall clock and provenance from a separate downloaded `info.json` without revalidation or consistency checks. If the two responses differ, an over-cap video can be finalized, or a timestamp refusal occurs only after the media download that the contract says must never start for refused input.
- **Evidence:** A targeted acquisition with a 60-second probe and downloaded metadata reporting `duration=999999` reached `mint()` with `durationSeconds=999999` under the 180-minute configuration. The code calls `refuse_unacceptable(info, ...)` before `download()`, but calls only `started_at_from_info(downloaded)` and `provenance_extra_from_info(downloaded, ...)` afterward.
- **Suggested direction:** Define and enforce a probe-to-download consistency boundary. Revalidate every refusal and required metadata invariant on downloaded `info.json` before minting, and refuse named on disagreement; adjust the yt-dlp interaction if strict pre-media refusal is required even under metadata drift.

### F4 — Requested source identity is never checked against yt-dlp's result

- **Location:** `server/meetingminer/youtube.py:423-463`
- **Severity:** high
- **Finding:** The source ID is fixed from the input URL, but neither probe nor downloaded `info.json` is required to report that same video ID. A redirect, extractor inconsistency, or changed response can mint another video's bytes and metadata under `youtube:<requested-id>`, after which the exists short-circuit permanently treats the requested video as already acquired.
- **Evidence:** Both yt-dlp metadata objects carry an `id`, but the implementation never reads it. A targeted acquisition with requested ID `aB3dEfGhIj0` and downloaded `id="different01"` reached `mint()` with `source_id="youtube:aB3dEfGhIj0"`. No schema rule can compare provenance to the source ID.
- **Suggested direction:** Require the probe and downloaded metadata IDs to equal the offline-parsed video ID, with a named refusal on absence or mismatch before finalization. Add a regression test that proves mismatched bytes cannot be minted under the requested identity.

### F5 — Required YouTube provenance fields are treated as optional

- **Location:** `server/meetingminer/youtube.py:213-220`, `server/meetingminer/youtube.py:380-400`
- **Severity:** medium
- **Finding:** The frozen contract requires `channel`, `ytDlpVersion`, and `formatId`, but the mapper omits blank/missing channel and format ID, while `yt_dlp_version()` accepts empty stdout. These inputs still produce schema-valid drops because provenance is intentionally open in the shared schema.
- **Evidence:** `provenance_extra_from_info({}, "aB3dEfGhIj0", "")` returns only `tool`, `url`, and an empty `ytDlpVersion`. The conditional assignments at lines 391-399 have no later guard, and the successful acquisition path sends that partial map directly to `mint()`.
- **Suggested direction:** Validate every story-required provenance value as non-empty (and of the expected type) before minting. Refuse with a named metadata error rather than silently producing a contract-incomplete drop.

### F6 — The preflight checks `ffmpeg` but omits the `ffprobe` binary actually used by minting

- **Location:** `server/meetingminer/youtube.py:166-179`, `server/meetingminer/mintdrop.py:326-345`
- **Severity:** medium
- **Finding:** `ensure_tools()` declares the tool gate complete after finding `yt-dlp` and `ffmpeg`, but `mint()` independently requires `ffprobe`. PATH installations are not guaranteed to contain both names. With `ffmpeg` present and `ffprobe` absent, the full media download occurs before the late mint refusal, contradicting the promised pre-download tool gate.
- **Evidence:** A targeted run stubbed `yt-dlp` and `ffmpeg` as present and `ffprobe` as absent. `download()` ran and wrote media into the temporary directory; only then did `_assert_is_a_video()` raise `MintError: ffprobe is not on PATH`. The offline tests stub `probe_media` and never exercise this dependency ordering.
- **Suggested direction:** Include `ffprobe` in the acquisition preflight (with the existing `brew install ffmpeg` remediation), and cover the split-PATH case so no media download begins when the actual validation binary is missing.

### F7 — Malformed release timestamps escape the named-refusal path

- **Location:** `server/meetingminer/youtube.py:270-295`
- **Severity:** medium
- **Finding:** Any numeric `release_timestamp` is passed directly to `datetime.fromtimestamp()`. Non-finite or out-of-range values raise `ValueError`, `OverflowError`, or `OSError`, bypassing `YoutubeError`, the valid `upload_date` fallback, and `main()`'s named refusal handling.
- **Evidence:** `started_at_from_info({"release_timestamp": float("nan"), "upload_date": "20260812"})` raises raw `ValueError: Invalid value NaN (not a number)`. `main()` catches only `ConfigError`, `MintError`, and `YoutubeError`, so the operator receives a traceback and non-contract failure despite a usable fallback date.
- **Suggested direction:** Treat `release_timestamp` as usable only when finite and convertible; catch platform datetime range errors, then try `upload_date`. If neither value is usable, raise the existing named wall-clock refusal.
