# Builder handoff — Story 6.2 review remediation

Use `bmad-build-auto` to remediate the filed adversarial review. Story 6.2 does
**not** pass review and must not merge as it stands.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Implementation branch: `story/6-2`
- Exact reviewed range: `5cdfce7..9b51bc7`
- Review report:
  `_bmad-output/implementation-artifacts/review-story-6-2-2026-08-30.md`
- Review branch: `story/6-2-review`; final report commit at handoff time:
  `1510859763f96815e2d822abe7ad7642115ee5f7`
- Subject movement: none observed; `story/6-2` still resolved to `9b51bc7` when
  the report was finalized. If it has moved, review the intervening commits
  before applying this handoff.

Read the report first. Its Location / Severity / Finding / Evidence / Suggested
direction entries are authoritative. Implement requirements, not guessed patch
text.

## Specification decision required before code remediation

F13 is rooted in the frozen spec, not an implementation mistake.

- **F13 — `server/meetingminer/config.py:689-730`:** the defaulted acquisition
  models silently supply the 180-minute threshold when `config.yaml` omits it,
  while AD-10 says every threshold is declared by the versioned config file and
  cannot scatter into code defaults. Decide and amend the governing contract:
  either require the YAML block and update fixture configs, or amend AD-10 to
  make schema defaults an authoritative form of configuration. Re-derive the
  implementation task from that decision. Do not silently code around the
  contradiction.

## Fix now

Apply F1-F12. Recommended order follows dependencies.

### 1. Close the command-execution boundary

- **F10 — `infra/Makefile:554-557`:** raw `$(URL)` becomes shell program text;
  a quote and semicolon execute arbitrary commands before Python validation.
  Make URL travel as data, not recipe syntax, and prove harmless shell
  metacharacters cannot escape.

### 2. Make the shared mint override safe

- **F1 — `server/meetingminer/mintdrop.py:572-589`:** `provenance_extra` can
  replace `files`, `mintedAt`, `startedAtSource`, `title`, and `suppliedBy` with
  schema-valid lies. Mint must retain ownership of integrity provenance and
  reject protected collisions by name; expose only deliberately variable
  producer fields such as `tool` through constrained inputs.

This changes the surface used by the remaining YouTube fixes, so land it before
rewiring metadata mapping.

### 3. Establish one fail-closed metadata boundary

- **F2 — `server/meetingminer/youtube.py:244-267,394-396`:** missing,
  nonnumeric, negative, or non-finite duration bypasses the cap and may omit
  required `durationSeconds`. Require a finite non-negative duration before
  download and before mint.
- **F3 — `server/meetingminer/youtube.py:435-463`:** a passing probe followed by
  over-cap or timestamp-inconsistent downloaded info still reaches mint (or
  refuses only after downloading). Define and enforce probe/download
  consistency; downloaded metadata may never invalidate the accepted decision
  and still finalize.
- **F4 — `server/meetingminer/youtube.py:423-463`:** neither metadata object is
  checked against the offline-parsed ID. Require both to identify the requested
  video so different bytes cannot be frozen under `youtube:<requested-id>`.
- **F5 — `server/meetingminer/youtube.py:213-220,380-400`:** channel,
  yt-dlp version, and format ID are optional/blank in code but required by the
  story. Refuse incomplete values rather than relying on the open provenance
  schema.
- **F7 — `server/meetingminer/youtube.py:270-295`:** malformed numeric release
  timestamps throw raw datetime exceptions and skip a valid upload-date
  fallback. Accept only usable instants, fall back as specified, and otherwise
  raise the named wall-clock refusal.

### 4. Restore preflight and evidence guarantees

- **F6 — `server/meetingminer/youtube.py:166-179`:** ffmpeg is checked but the
  `ffprobe` binary later required by mint is not. A split PATH downloads media
  before refusing. Preflight the actual binary with the existing install
  remediation.
- **F8 — `server/meetingminer/youtube.py:347-374,445-464`:** a selected English
  caption can produce no VTT and silently become a recording-only drop. A
  selected track must materialize, or acquisition must refuse by name (unless a
  separately specified retry policy is adopted).
- **F9 — `server/meetingminer/youtube.py:506-530`:** `main()` write-probes the
  drops root before parsing an invalid URL. Classify before filesystem mutation
  while retaining the existing validation ordering for accepted input.

### 5. Close the verification gaps

- **F11 — `server/tests/test_youtube.py:198-231,363-424`:** normal tests replace
  `download()` and cannot catch broken selector/subtitle flags, conversion,
  filenames, info parsing, or missing VTT. Stub `_run()`, inspect commands, and
  materialize realistic outputs for manual, automatic, and no-caption paths.
- **F12 — `server/tests/test_youtube.py:319-357,501-526`:** no test calls
  `main()`. Cover created/exists, POST/duplicate/rejected intake, `--no-post`,
  `--drops`, `--api`, no root mutation for invalid URL, and forwarding a
  non-default configured duration cap.

For every new regression, first demonstrate that it fails against reviewed HEAD
`9b51bc7` for the intended reason; do not assume a green post-fix test proves it
guards the defect.

## No new deferred work

This review adds no deferred item. The network test's missing `slow` mark and
matching `SLOW_TESTS` pin were already recorded for integration and remain
outside this remediation footprint.

## Verification required before returning to review

Run all original story checks plus the new regressions:

```bash
uv run --project server pytest server/tests/test_youtube.py -q
make test-fast
make test
python3 _bmad/scripts/branch_conflicts.py --against story/6-2
```

Also run the harmless Make metacharacter regression and the focused tests for
protected provenance collisions, invalid/mismatched metadata, missing
`ffprobe`, missing selected captions, invalid-URL write ordering, and every
`main()` branch named above. A real network run remains optional but, if used,
must use `--no-post` and a scratch child of `MM_DROPS_ROOT`.

## Explicitly out of scope

Do not widen into playlists (6.2a), mint-drop CLI/file classification (6.3),
the B-34 deep-link issue, the existing slow-mark integration item,
`server/tests/conftest.py`, `test_mint_drop.py`, `test_compose_contract.py`,
`server/pyproject.toml`, root `README.md`, `AGENTS.md`, `docs/backlog.md`, or
anything under `web/`. If the F13 decision requires fixture/config-contract
changes outside the frozen footprint, amend and re-derive the spec before
touching them.
