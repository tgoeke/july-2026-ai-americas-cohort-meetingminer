# Builder handoff — Story 10.3: Thread Timeline API with Level-of-Detail

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/10-3`, branch
`story/10-3`, from current `main`. Story: `epics.md` line 1733, four
Given/When/Then clauses. **Story 10.2 landed** — `thread`, `topic_thread` and
the graph projection exist; read them first.

**This API backs the demo's headline beat** (zooming a thread), so its shape is
consumed by story 10.6 building in parallel. Implement the AC's field names
exactly as written — 10.6 is coding against them.

## Footprint

| Path | Edit |
|---|---|
| `server/meetingminer/api/threads.py` | NEW. `GET /threads` and `GET /threads/{id}/timeline?from=&to=&level=`. Auto-discovered — never hand-edit `api/main.py`. |
| `server/meetingminer/migrations/0017_thread_color_ordinal.sql` | NEW. **0015 and 0016 are taken.** A transactional per-corpus sequence for `colorOrdinal`. |
| `server/meetingminer/projections/` or a new domain module | The four level queries. |
| `server/tests/test_api_threads.py`, `test_thread_timeline_levels.py` | NEW. |

## The clauses that carry the risk

- **Four levels, each returning exactly its tier**: `bands` (mention density
  per time bucket), `meetings` (counts + topic membership), `moments`
  (`momentId`, `meetingId`, `title`, `startMs`, `occurredAt`,
  `occurredAtPrecision`, speakers-where-known, opaque `screenshotId`),
  `evidence` (adds transcript excerpt, artifact anchors, `hasRecording`,
  opaque media ids). **Never a storage path** — ID-addressed through
  `GET /media/files/{mediaId}` (AD-17).
- **`colorOrdinal` is allocated once and never recycled** within a corpus. A
  merge survivor keeps its ordinal; a split gets a new one. Concurrent creates
  must not duplicate — that is what the transactional sequence is for. Test it
  under concurrency.
- **`occurredAt` is derived server-side** from meeting start + `startMs`,
  RFC 3339 UTC. A date-only source anchors at `00:00:00Z + startMs` and keeps
  `occurredAtPrecision: day`. Ties break by `meetingId` then `momentId`.
  Clients use the served value; they never reconstruct it.
- **Coarse levels are cheap aggregates bounded by the window — never a full
  scan of moments.** Prove it with a query-shape test, not a hope.

## Standing rules

Read `wave-2026-08-30-rules.md` in this directory. Your worktree owns a private
Docker stack — `make bootstrap` first, `uv sync --project server` before
`make lint`. `make test-fast` runs lint and typecheck; your branch cannot land
until both pass, and the ruff baseline is shrink-only. New tests in NEW files —
never append to `conftest.py`, `test_config.py` or `test_compose_contract.py`.
`sprint-notes.md` has no merge driver: short entry, expect a union. Backlog ids
are a shared counter — file in `docs/backlog.md` or it does not exist; highest
in use is **B-40**.

**This is demo-critical work with a hard deadline of early afternoon
2026-08-31.** Build the acceptance criteria and nothing more. If you find
something adjacent that wants fixing, file it rather than doing it.

## Completion

Spec `status: review`, sprint keys set, `review-prompt-story-<id>-<date>.md`
written stating **the review lane fixes what it finds**, everything pushed.
Report SHAs and real verification output. Do not merge, do not mark done.
