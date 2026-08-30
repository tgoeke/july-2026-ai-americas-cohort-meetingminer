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
