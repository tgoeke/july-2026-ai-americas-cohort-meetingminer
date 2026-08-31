# Builder handoff — Story 10.4: Moments Feed Ranking

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/10-4`, branch
`story/10-4`, from current `main`. Story: `epics.md` line 1757.

**This API backs the demo's opening screen.** Story 10.5 is building its view in
parallel against the AC's exact field names — implement them as written.

## Footprint

| Path | Edit |
|---|---|
| `server/meetingminer/api/moments_feed.py` | NEW. `GET /moments/feed` returning `{items, total, limit, offset}`. Auto-discovered. Do NOT edit `api/moments.py` — story 2.2 owns it. |
| `server/meetingminer/migrations/0018_ranking_signals.sql` | NEW. **0015, 0016, 0017 are taken** (0017 by story 10.3, in parallel). `risk`/`question` ranking-signal rows. |
| `server/meetingminer/pipeline/extraction.py`, `stages/extract.py` | The risk/question extraction pass. |
| `config.yaml` | Ranking weights **with recorded rationale**, appended at the END. |
| `server/tests/test_api_moments_feed.py`, `test_ranking_signals.py` | NEW. |

## The clauses that carry the risk

- **Deterministic score over stored signals** — decision and ADR artifacts,
  action items with stated timing (soonest first), risks, open questions,
  meeting recency, publication recency, thread membership. **Every weight in
  `config.yaml` with rationale.**
- **Each item carries a non-empty ordered `reasons[]`** of
  `{kind, label, ref?, at?}` where `kind` is an artifact kind or
  `due | risk | question | recency | published | thread`.
- **Reason validation happens BEFORE pagination**: an item with no valid reason
  is dropped and logged, and `items`, `total` and offsets are computed only
  from remaining serializable rows. Getting this backwards produces wrong
  totals — test it directly.
- **Risk/question rows are worker-owned, replaced on rerun, and never enter the
  artifact approval lifecycle.** They are ranking signals, not artifacts.
- `screenshotId` resolves only through `GET /media/files/{mediaId}` (AD-17).

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
