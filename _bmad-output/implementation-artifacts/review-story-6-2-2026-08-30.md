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
