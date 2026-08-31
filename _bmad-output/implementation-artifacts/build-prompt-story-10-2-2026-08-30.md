# Builder handoff — Story 10.2: Threads and the Graph Projection

Agent: `bmad-build-auto`.

- Worktree: `../meetingminer-wt/10-2`, branch `story/10-2`, cut from current `main`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 10.2: Threads and
  the Graph Projection" (FR42). Three Given/When/Then clauses. Stories 10.2a
  (curation), 10.2b (chat) and 10.3+ are NOT in scope.
- **Story 10.1 has landed**: `topic` and `topic_mention` tables exist
  (migration `0014_topics.sql`), worker-owned and replaced on rerun. You link
  those topics into threads.

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/migrations/0015_threads.sql` | NEW. `thread` and the topic↔thread link. Follow 0014's shape: worker-owned, machine-derived, labelled as such, outside the `extracted → approved → published` lifecycle. |
| `server/meetingminer/pipeline/` or `domain/` | NEW module for thread derivation: normalized-name match plus embedding similarity above a configured threshold. **Derivation must be idempotent** — a rerun over unchanged topics yields the same threads. That is the clause most likely to be got wrong; test it directly. |
| `config.yaml` | The threshold and the linking rule, **with recorded rationale** as the AC requires. Add a `threads:` block at the END of the file. |
| `server/meetingminer/config.py` | The matching config class, inserted immediately BEFORE `class Settings`, plus one field at the END of `Settings`. Nothing else. |
| `server/meetingminer/projections/graph.py` | `Topic` and `Thread` nodes and `MENTIONS` edges to moments. `projections` stays the **sole writer** (AD-4) — nothing outside `projections/` opens a store client. |
| `server/meetingminer/projections/traversals.py` | Register the thread template in `TRAVERSAL_TEMPLATES` (AD-7), exactly as the existing templates are registered. |
| `docs/architecture.md` | The AD-4 clarification the AC names: topics and threads are navigation metadata, outside the publish gate. **Edit only that clarification.** AD-10 was amended twice this week — do not touch it. |
| `server/tests/test_threads_*.py`, `server/tests/test_projections_threads.py` | NEW. All coverage here. Never append to `test_migrations.py`, `test_projections_graph.py` or `conftest.py`. |

Not yours: `pipeline/extraction.py` and `pipeline/stages/extract.py` (10.1 owns
topic production; you consume it), the artifact lifecycle, anything under `web/`.

## Contract details

- The traversal returns the thread's meetings and moments in **wall-clock
  order** with per-level aggregates: mentions per meeting, span, and
  participants where known.
- Threads are derived from stored topics; do not re-run extraction.
- The worker is not to be started — verify with fakes and store-backed tests.

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
