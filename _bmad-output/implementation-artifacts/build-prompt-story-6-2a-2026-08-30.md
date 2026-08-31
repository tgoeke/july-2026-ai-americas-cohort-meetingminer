# Builder handoff — Story 6.2a: Playlist Acquisition

Agent: `bmad-build-auto`.

- Worktree: `../meetingminer-wt/6-2a`, branch `story/6-2a`, cut from current `main`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 6.2a: Playlist
  Acquisition" (FR33). Three Given/When/Then clauses.
- **Story 6.2 has landed** — `server/meetingminer/youtube.py` on `main` is your
  foundation. Read it before designing anything: you are adding playlist
  enumeration around the single-video path it already implements, not
  reimplementing minting.

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/youtube.py` | Playlist enumeration (`--flat-playlist`), the per-entry loop, and the outcome table. Each entry mints and posts **exactly as 6.2 mints one video** — reuse its functions, do not fork them. Story 6.2's single-video path must behave identically when `--playlist` is absent. |
| `infra/Makefile` | The `youtube-drop` recipe only, to pass `--playlist`. |
| `docs/README.md` | The "Ingesting a YouTube video" section only — extend it, do not restructure it. |
| `server/tests/test_youtube_playlist.py`, `server/tests/fixtures/youtube/` | NEW. Enumeration and the per-entry outcome table covered offline from a recorded flat-playlist listing. Never append to `test_youtube.py`. |

Not yours: `mintdrop.py` (story 6.3 is extending it and its union is already
rehearsed), `config.py`, `config.yaml`, anything under `web/`.

## Contract details

- Entries are enumerated with `--flat-playlist`, then each is minted and posted
  **sequentially** — one drop and one `POST /ingests` per entry.
- The summary table names every entry's outcome as `minted | exists |
  refused:<rule>`. **A refused entry does not stop the run** — that is the
  clause most likely to be got wrong, so test it explicitly.
- 6.2's `exists` short-circuit applies per entry with no media download.

## Wave rules (this is a second wave — read the differences)

Read `wave-2026-08-30-rules.md` in this directory for the standing rules, then
these amendments, which come from what the first wave actually cost:

- **Your worktree owns a private Docker stack.** Story 11.2 landed: `make
  worktree` provisions `meetingminer-<slug>` on its own ports and writes
  `.env.worktree`. Suites in different worktrees no longer contend at all. Run
  `make bootstrap` first. `MM_STACK_NAME`/`MM_STACK_ID` are NOT overridable —
  do not try.
- **`make test-fast` now runs `make lint` and `make typecheck`** (story 11.4).
  Your branch cannot land until both pass. The ruff baseline is shrink-only, so
  fix real findings rather than widening it, and never sweep files outside your
  footprint. Run `uv sync --project server` in your worktree before `make lint`.
- **Two lint rules bite new code and are worth knowing up front**: `ISC004`
  wants implicit string concatenations inside list/tuple literals wrapped in
  parentheses (it cannot tell a deliberate multi-line string from a forgotten
  comma), and `DTZ` rules flag naive datetimes. If a finding is a genuine false
  positive, add a `# noqa: <CODE>` with a one-line rationale — never silently.
- **`sprint-notes.md` has no merge driver.** Keep your entry short and at the
  end; expect integrate to union it.
- **Backlog ids are a shared counter.** If you file one, take the next free id
  and say in your report that you took it — two lanes both grabbed `B-35` last
  wave. Highest currently used: **B-37**.
- **Do not flip `sprint-status.yaml` and assume it sticks** — say the final
  status in your report so integrate can verify it after the rebase.
- New tests go in NEW files. Never append to `conftest.py`,
  `test_compose_contract.py`, `test_config.py`, or another lane's module.

## Completion

Spec `status: review`, your sprint keys set, `review-prompt-story-<id>-<date>.md`
written (**the review lane fixes what it finds** — say so in the prompt; do not
copy the retired "report findings, do not fix" wording from older prompts in
this directory), everything committed and pushed. Report SHAs and the real
verification output. Do not merge to `main`, do not mark the story done.
