# Builder handoff — Story 1.5: Transcript Verification, Alignment & Participants

Paste the block below as the `bmad-build-auto` invocation prompt.

---

Implement **Epic 1, Story 1.5 — Transcript Verification, Alignment & Participants**.

The story definition and its acceptance criteria are in `_bmad-output/planning-artifacts/epics.md` under `### Story 1.5`. No story spec file exists yet — planning writes it.

**Canonical contract.** `_bmad-output/specs/spec-meetingminer/SPEC.md` and every file in its `companions:` frontmatter. Architecture: `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`.

**Read `_bmad-output/specs/spec-meetingminer/corpus-facts.md` §3 and §4 before planning.** It holds measured facts about the real transcripts and participant graph that this story would otherwise spend its budget rediscovering. Treat them as established input properties, not as things to verify from the recordings:

- Both transcript lineages are **second-precision**, so alignment anchors within **~±2s** — not a minute floor.
- The long transcript **switches `MM:SS` → `HH:MM:SS` past the hour**. Parse by field count (2 → `MM:SS`, 3 → `HH:MM:SS`); a fixed-field-count parser mis-reads half the file.
- Two parsers are required: the Teams `[m:ss] Lastname, Firstname: text` source of record, and the legacy `<Name> | MM:SS` format. The legacy one is not optional — the primary capture-eval recordings carry it.
- The legacy files open with a `<Name> started transcription` preamble line that is **not** a speaker block.
- `.vtt` exports may be speaker-less subtitle tracks, so they are not a substitute for the text transcript.
- Each occurrence carries an already-resolved participant graph with 15 known fields, including `spokeTurns`/`spokeWords` (share-of-talk for free) and per-person `foundIn` provenance.
- **Tenant logins are employee numbers, not mail addresses.** Any join keyed on an email-shaped value silently misses.
- `unresolved: true` marks external attendees. Preserve them as such — never drop them, never merge them into a resolved person.
- Occurrence files are globbed by extension inside the occurrence directory. Never reconstruct a filename, never assume a slug; titles carry spaces, commas, and hyphens, and one sample directory name has a trailing space.

**SPEC constraints amended 2026-08-18 that bear directly on this story:**

- **Speaker attribution never guesses.** A label that resolves to no participant stays unresolved; one that resolves to more than one stays ambiguous. A wrong attribution is worse than an absent one, because who-said-it is half of *no citation, no answer*.
- **Teams is the sole go-forward transcript source.** Third-party transcripts already in the corpus are read-only legacy support, and no two raw sources are ever merged. Legacy-format parsing stays required regardless.

**Note on the story text.** Story 1.5's acceptance criteria were reconciled against the amended SPEC on 2026-08-18. The former "deduplicated by AAD object ID when present" criterion was removed: Microsoft Graph is an explicit SPEC non-goal, so no directory identifier is ever available. Identity resolves through normalized display name scoped to that meeting's roster, then the alias table, per AD-5. Do not reintroduce a directory-identifier path.

`epics.md` is newer than the cached `epic-1-context.md`, so epic context will recompile on this run and will pick up the reconciled criteria. Do not reuse the stale cache.

**Environment.** ASR wheels do not exist for the machine-default Python 3.14 — build against 3.12 via `uv`. `ffmpeg` and `ffprobe` are present on this machine.

**Out of scope. Do not widen into any of these:**

- Story 1.6 (moments), 1.7 (projections), 1.9 (UI/SSE), and 1.11 (screen capture retune).
- Screen capture, screenshots, and the `screens` stage generally. Story 1.4's captures are known to fail the over-capture guardrail; story 1.11 owns that and it is not this story's problem.
- `pull_transcript/` — it is the upstream ingest source of record and is not modified as a side effect of MeetingMiner work.
- Epic 2–5 work of any kind.

**Open question that does not block this story.** Whether a transcript-only moment gets a source deep-link replay affordance is unresolved; it blocks story 1.6's spec, not this one. If planning surfaces a decision that depends on it, record the dependency and proceed — do not resolve it unilaterally.
