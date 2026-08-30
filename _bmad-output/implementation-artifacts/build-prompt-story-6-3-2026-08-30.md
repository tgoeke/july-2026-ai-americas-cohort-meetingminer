# Builder handoff — Story 6.3: Local-Files Acquisition with Transcript Dialect Conversion

Agent: `bmad-build-auto`. Read `wave-2026-08-30-rules.md` in this directory
first (wave-wide rules and the conflict check), then this file.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `../meetingminer-wt/6-3`, branch `story/6-3`, cut from current `main`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 6.3: Local-Files
  Acquisition with Transcript Dialect Conversion" (FR35). Three
  Given/When/Then clauses. Stories 6.4 / 6.4a / 6.5 / 6.5a are NOT in scope.

## The one real coupling — read this before writing any code

`story/6-2` (YouTube acquisition, in review) added **keyword overrides on
`mint()` and `build_metadata()`** in `server/meetingminer/mintdrop.py`, at
lines 541-593 and 615-690. You need a provenance field of your own
(`provenance.transcriptDialect`), which is the same mechanism.

**Do not invent a second mechanism, and do not edit those two regions
blind.** Read 6-2's landed shape first:

```bash
git fetch origin && git show origin/story/6-2 -- server/meetingminer/mintdrop.py
```

Reuse its parameter names exactly and extend the same override path. This is
the sanctioned union pattern in `.claude/skills/integrate/conflict-playbook.md`
(the `seed_meeting()` precedent): two stories adding to one low-level
signature is fine **when both pin the same exact definition**, and integrate
unions them. Pin the shape you used in your spec, naming 6-2's commit you read
it from, so the union is mechanical.

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/transcripts/dialects.py` (or an equivalently scoped NEW module) | NEW. Zoom `.vtt` (`Name: text` cue payloads) → the trusted speaker-attributed `.txt` (`<Name> \| MM:SS` blocks) plus a `.vtt` carrying timing. `teams-vtt` and `plain` pass through. A dialect is NEVER inferred from content. |
| `server/meetingminer/mintdrop.py` | `classify_supplied` (~267-305), the extension map (~145-146), and the CLI parser (~950+) for `--transcript-dialect`. In `build_metadata`/`mint`, extend ONLY through 6-2's existing keyword-override path as described above — no new mechanism, no signature reshuffle. |
| `docs/README.md` | A dialect section. 6-2 adds "Ingesting a YouTube video" to the same file — put yours in its own section and do not touch theirs. |
| `server/tests/test_transcript_dialects.py` | NEW. All coverage here — never append to `test_mint_drop.py`. |
| `_bmad-output/implementation-artifacts/` | Your spec, `sprint-status.yaml`, `sprint-notes.md`, `review-prompt-story-6-3-<date>.md`. |

Not yours: `server/meetingminer/pipeline/transcripts.py` — the AC requires the
pipeline transcript contract to be **unchanged**; `align` must resolve Zoom
names through the roster exactly as Teams labels resolve today, with no edit
to the aligner. Also not yours: `conftest.py`, `AGENTS.md`, `infra/Makefile`,
`config.py`, `config.yaml`, root `README.md`.

## Verification

- `uv run --project server pytest server/tests/test_transcript_dialects.py -q`
- A round-trip test: a Zoom `.vtt` fixture → minted drop → `align` resolves
  the converted names through the roster.
- `make test-fast`; `make test` once before `review`.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-3` — expect
  clean against `main`; a `mintdrop.py` pair with `story/6-2` is the pinned
  union above and must be named in your spec if it appears.

## Completion

Spec `status: review`,
`6-3-local-files-acquisition-with-transcript-dialect-conversion: review` in
`sprint-status.yaml`, review prompt written, all pushed, SHAs reported. Do not
merge, do not mark done.
