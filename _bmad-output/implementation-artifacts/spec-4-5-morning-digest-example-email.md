---
title: 'Story 4-5: Morning Digest Example Email'
type: 'feature'
created: '2026-08-20'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      No Markdown escaping of artifact title/body/owner before interpolation into the digest.
    evidence: |-
      A title containing `#`, `*`, `_`, or backticks can corrupt the rendered
      Markdown structure (e.g. an accidental heading). Low consequence: a
      single local demo file, not multi-tenant or user-facing content.
    location: >-
      server/meetingminer/digest/generator.py:_render_meeting
    severity: low
  - summary: >-
      `started_at.date()` has no documented timezone handling for the digest's date label.
    evidence: |-
      Taking the date component off a UTC timestamptz with no conversion or
      documented assumption could show the wrong calendar date for a reader
      in another timezone.
    location: >-
      server/meetingminer/digest/generator.py:_render_meeting
    severity: low
  - summary: >-
      The per-meeting accumulator's `dict[str, object]` shape needs four `# type: ignore` suppressions.
    evidence: |-
      A `TypedDict` (or building `DigestMeeting` incrementally) would remove
      the suppressions and reduce the risk of a real typo going unnoticed.
    location: >-
      server/meetingminer/digest/generator.py:read_published_artifacts
    severity: low
  - summary: >-
      No test for same-meeting artifact ordering or a `started_at` tie-break between two meetings.
    evidence: |-
      The SQL's `a.created_at` and `m.id` secondary sort keys are untested,
      so a real change to that ordering would not be caught.
    location: >-
      server/meetingminer/digest/generator.py:read_published_artifacts
    severity: low
  - summary: >-
      No test for the generic `psycopg.Error` branch in the CLI's database-failure handling.
    evidence: |-
      Only `psycopg.OperationalError` is exercised; the `except psycopg.Error`
      "database error" path is unverified.
    location: >-
      server/meetingminer/digest/cli.py:main
    severity: low
  - summary: >-
      No test for an `OSError` writing the output file (e.g. a nonexistent parent directory).
    evidence: |-
      The `OSError` handling around `output_path.write_text` is unverified by
      any test.
    location: >-
      server/meetingminer/digest/cli.py:main
    severity: low
  - summary: >-
      No test for the `MM_CONFIG_PATH`/`MM_ENV_PATH` override branch in `_load_cli_config`.
    evidence: |-
      Only the default repository-config path is covered by the test suite.
    location: >-
      server/meetingminer/digest/cli.py:_load_cli_config
    severity: low
  - summary: >-
      No test for an owner line present but with an empty name (`"Owner: \n..."`).
    evidence: |-
      The `owner or None` fallback for this case is real behavior but
      untested.
    location: >-
      server/meetingminer/digest/generator.py:_split_owner
    severity: low
  - summary: >-
      No unicode/non-ASCII content test for titles, bodies, or owner names.
    evidence: |-
      Nothing confirms the `encoding="utf-8"` write path round-trips
      non-ASCII content correctly.
    location: >-
      server/tests/test_digest.py
    severity: low
  - summary: >-
      No test for `--output` pointing at a pre-existing file (overwrite behavior).
    evidence: |-
      The CLI silently overwrites via `write_text`; that behavior is
      undocumented and untested for a rerun scenario.
    location: >-
      server/meetingminer/digest/cli.py:main
    severity: low
  - summary: >-
      The owner-line parser matches only the exact `"Owner: "` prefix, not case or whitespace variants.
    evidence: |-
      Couples the digest to extraction.py's exact string convention; a
      differently-cased or -spaced owner line renders as unassigned instead
      of parsed.
    location: >-
      server/meetingminer/digest/generator.py:_split_owner
    severity: low
baseline_revision: 'b0206320060bdba6914eefc6b409a1dc89342cb3'
---

<intent-contract>

## Intent

**Problem:** The capstone must demonstrate the Morning Digest concept (FR31) without building delivery — nothing today reads published artifacts and renders them as an example email.

**Approach:** Add a standalone, read-only CLI (`digest`) mirroring the `rebuild` CLI's shape (`server/meetingminer/projections/cli.py`): connect to Postgres via `config.yaml`, select every `artifact` row with `state = 'published'`, group by meeting, and write one example email file to a caller-supplied path.

## Boundaries & Constraints

**Always:**
- Read-only against Postgres: `SELECT` only, on `artifact`, `meeting`, `moment` — no writes, no new migration.
- Include only `artifact.state = 'published'` rows. `extracted`/`approved` rows are never included.
- One output file per run, at the path given by a required `--output PATH` CLI argument (no default path, no new config/env key — mirrors `rebuild`'s "no implicit scope" refusal).
- Group content by meeting (title + date), meetings ordered by `started_at` descending (most recent first); within a meeting, ADRs under a "Decisions" section and action items under an "Action Items" section.
- For an action-item artifact, parse a leading `Owner: <name>` line off `artifact.body` (written by `extraction.py`, e.g. `pipeline/extraction.py:892`) and render it as the assignee; when absent, render as unassigned. Never invent an owner.
- Follow the `rebuild` CLI's operational shape: `main(argv) -> int`, config loaded like `cli.py:54` (`_load_cli_config`), `psycopg.connect(db.conninfo(config))`, `db.check_migrations_current(conn)` before querying, `fatal: digest aborted: ...` on stderr with non-zero exit for config/DB failures, plain progress/report on stdout.
- Register a `digest` console script in `server/pyproject.toml` `[project.scripts]` (beside `rebuild`, `:67`) and a `make digest` target in `infra/Makefile` mirroring `rebuild:` (`:745-747`), added to the `.PHONY` list (`:78-79`) and `help:`.

**Never:**
- No delivery mechanism (no SMTP/API call), no scheduler/cron, no per-user or per-recipient filtering, no "yesterday's meetings" windowing — scope.md Cluster F and the architecture spine both pin this to one example file per run, not a real digest.
- No dependency on Story 4.3's approval endpoint — tests seed `state = 'published'` rows directly via SQL (`server/tests/conftest.py`, `projection_seed.py`), the same way the `artifact` table already supports the state today.
- No new Postgres migration, no new config.yaml keys, no new `MM_*_ROOT` env var.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | 2 meetings, each with one published ADR and one published action item (one with `Owner:`, one without) | One file at `--output PATH` with both meetings, most-recent first, Decisions + Action Items sections, owner rendered where present | No error |
| No published artifacts | Postgres has meetings/artifacts but none `state = 'published'` | File is still written, stating no artifacts are published yet; exit 0 | Not an error — this is a normal pre-publish state |
| `--output` missing | CLI invoked with no `--output` | `fatal: digest aborted: --output PATH is required` on stderr | Exit 2, nothing written |
| DB unreachable / migrations pending | Postgres down, or schema behind | Same failure shape as `rebuild` (`cli.py:197-202`) | Exit 1, nothing written |
| Mixed states in one meeting | Meeting has `extracted`, `approved`, and `published` artifacts | Only the `published` ones appear | No error |

</intent-contract>

## Code Map

- `server/meetingminer/projections/cli.py` -- sibling CLI to model structurally: `_load_cli_config` (:54), `_parser`/`main` shape, `psycopg.connect(db.conninfo(config))` + `db.check_migrations_current` (:186-187), `fatal: ... aborted` stderr convention.
- `server/meetingminer/projections/evidence.py` -- read-only query-module pattern to copy: frozen dataclasses as row shapes, plain `conn.execute(...)` (psycopg, no ORM); `read_meeting` (:160) is the closest precedent for "one connection, several SELECTs, one assembled value object".
- `server/meetingminer/pipeline/extraction.py:892` -- `body = f"Owner: {owner}\n{body}".strip()`; the only place an assignee is recorded, as free text prefixed on `artifact.body`.
- `server/meetingminer/migrations/0009_artifacts.sql` -- `artifact` columns: `id, moment_id, meeting_id, kind CHECK IN ('adr','action-item'), state CHECK IN ('extracted','approved','published'), title, body, provenance jsonb`; index `artifact_meeting_state_idx (meeting_id, state)` is the query shape to use.
- `server/meetingminer/migrations/0002_meetings_media_frames.sql` -- `meeting` columns: `id, title (nullable), started_at, started_at_precision`.
- `server/meetingminer/db.py` -- `conninfo(config)` (:45), `check_migrations_current(conn)` (:149).
- `server/pyproject.toml:64-75` -- `[project.scripts]` block; add `digest = "meetingminer.digest.cli:main"` beside `rebuild`/`backfill`/`mint-drop`.
- `infra/Makefile:745-747` -- `rebuild:` target to model `digest:` on; `.PHONY` list `:78-79`; `help:` block.
- `server/tests/test_projections_rebuild.py` -- in-process CLI test pattern: `from meetingminer.projections.cli import main as rebuild_main`, asserts on return codes, uses `test_pool`/`test_database` fixtures (`server/tests/conftest.py:193-241`).
- `server/tests/projection_seed.py:75` -- `seed_meeting(...)`; extend or add a story-local helper to also insert `artifact` rows with `state='published'`.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/digest/__init__.py`, `server/meetingminer/digest/generator.py` -- new module: read-only query (published artifacts joined to meeting/moment) + render function producing the example email text -- keeps store I/O separate from rendering, testable without Postgres for the render half.
- `server/meetingminer/digest/cli.py` -- new module: `main(argv) -> int` following `projections/cli.py`'s shape (`--output PATH` required, config/DB gates, `fatal: digest aborted: ...`) -- gives `digest` an entry point identical in feel to `rebuild`.
- `server/pyproject.toml` -- add `digest = "meetingminer.digest.cli:main"` under `[project.scripts]` -- installs the console script via `make bootstrap`.
- `infra/Makefile` -- add `digest: check-env | infra-up migrate` target mirroring `rebuild:`, plus `.PHONY` and `help:` entries -- keeps the one-shot-script convention consistent.
- `server/tests/test_digest.py` -- new store-backed test module covering the I/O matrix above, using `test_pool`/`test_database` and a seeded set of `published`/`extracted`/`approved` artifacts across two meetings.
- `server/tests/test_digest_generator.py` -- new store-free unit tests for the render function: owner-present/owner-absent formatting, meeting ordering, empty-state text.

**Acceptance Criteria:**
- Given two meetings with published ADRs and action items (one action item with an `Owner:` line, one without), when `digest --output <path>` runs, then `<path>` contains both meetings ordered most-recent-first, each with a Decisions section and an Action Items section, and the owner is rendered only when present.
- Given a corpus with no `published` artifacts, when `digest --output <path>` runs, then it exits 0 and writes a file stating no artifacts are published yet.
- Given `--output` omitted, when `digest` runs, then it exits 2 with a `fatal: digest aborted: --output PATH is required` message and writes nothing.
- Given the database unreachable, when `digest` runs, then it exits 1 with a `fatal: digest aborted: ...` message, matching `rebuild`'s failure shape.
- Given an `extracted` or `approved` artifact alongside a `published` one in the same meeting, when `digest` runs, then only the `published` one appears in the output.

## Review Triage Log

### 2026-08-20 — Review pass

Four layers over `b020632..d8d6b3d` (pre-rebase SHAs `112e38b..9f7b827`; the review itself ran before the rebase onto `main` below, and the rebase did not change file contents): blind hunter, edge-case hunter,
verification-gap, intent-alignment.

- intent_gap: 0
- bad_spec: 0
- patch: 3: (high 0, medium 1, low 2)
- defer: 11: (high 0, medium 0, low 11)
- reject: 5
- addressed_findings:
  - `[medium]` `[patch]` `_render_meeting` (`generator.py`) only indented the first line of a multi-line `artifact.body` (`f"  {artifact.body}"`), so a real action item or decision — whose body is routinely multi-line per `extraction.py`'s table-column join — rendered with continuation lines flush-left, detached from its bullet. Confirmed independently by the blind-hunter and verification-gap layers. Fixed to indent every line.
  - `[low]` `[patch]` The `_OWNER_PREFIX` docstring cited `pipeline/extraction.py:892` as the line writing the `Owner:` prefix; the actual line is `:893`. Fixed the citation.
  - `[low]` `[patch]` `test_output_missing_fails_with_exit_2_and_writes_nothing` asserted `list(tmp_path.iterdir()) == []`, but `digest_main([])` is never pointed at `tmp_path` (no `--output` is passed at all), so the assertion was vacuously true regardless of CLI behavior. Fixed to stop asserting a claim the test doesn't exercise.

Not actioned (reject — false premise or unreachable):
- Unknown `artifact.kind` falling into the `action_items` bucket: `artifact.kind` is `CHECK`-constrained to `('adr','action-item')` at the schema level (`migrations/0009_artifacts.sql`), so this branch is unreachable.
- `digest`'s Makefile prereq depending on the "full stack": `infra-up` (`infra/Makefile:374-375`) only brings up the three Docker stores, not api/worker/web — identical to `rebuild`'s own prereq, not an inefficiency introduced here.
- A meeting with zero published artifacts never appearing in the digest: this is the SQL's correct behavior (nothing to summarize), not a bug.
- Sprint/story tracking (`sprint-status.yaml`) not updated by this diff: tracking updates are the integration session's responsibility, confirmed out of band with the peer session coordinating this wave.
- Missing bare `except Exception` fallback in `cli.py`: mirrors `rebuild`'s own cli.py exactly (same set of caught exceptions) — not a regression this diff introduces.

Deferred (real but low-severity, pre-existing-shaped or coverage-depth beyond the frozen I/O matrix — see frontmatter `deferred`): no Markdown escaping of artifact title/body/owner; `started_at.date()` has no documented timezone handling; the per-meeting accumulator's `dict[str, object]` typing needs `# type: ignore` suppressions; no test for same-meeting artifact ordering or a `started_at` tie-break; no test for the generic `psycopg.Error` CLI branch; no test for an `OSError` writing the output file; no test for the `MM_CONFIG_PATH`/`MM_ENV_PATH` override branch in `_load_cli_config`; no test for an owner line with an empty name (`"Owner: \n..."`); no unicode/non-ASCII content test; no test for `--output` pointing at a pre-existing file (overwrite behavior); the owner-line parser matches only the exact `"Owner: "` prefix, not case/whitespace variants.

## Design Notes

- **Why a required `--output`, no default path.** `rebuild` refuses an implicit `--all` scope so a mistyped invocation can't silently drop both stores; `digest` has no destructive default to protect against, but a silent default path (e.g. a hidden repo-relative file) risks landing in the git tree unnoticed. Requiring `--output` keeps the generator's only side effect explicit and keeps `.gitignore` untouched.
- **Why no new config key.** Story 4.3/4.4's "publish folder" doesn't exist in code yet (confirmed: no `publish_folder`/`PUBLISH_ROOT` symbol anywhere in `config.py` or `config.yaml`), and this story's own scope note says "no architectural footprint beyond the generator" — inventing a new root just for one demo file would be exactly that footprint.
- **Plain-text/markdown email body, not MIME.** Nothing in scope.md or the architecture spine asks for a real `.eml`/MIME file (no delivery mechanism exists to consume one); a single readable text file demonstrating the digest content satisfies "one example email file."

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_digest_generator.py -q` -- expected: all pass, store-free.
- `cd server && uv run pytest tests/test_digest.py -q` -- expected: all pass, store-backed (per-run test database).
- `cd server && uv run pytest tests/ -q` -- expected: all pass; no regression in `rebuild`/extraction suites.
- `make web-test` -- expected: all pass, unaffected (no web changes).

## Auto Run Result

**Summary:** Added a standalone, read-only `digest` CLI mirroring `rebuild`'s
`cli.py` shape. It selects every `artifact` row with `state = 'published'`,
joined to `meeting`, groups by meeting (newest first), and writes one example
Morning Digest text file to a required `--output PATH`. No migration, no api
route, no delivery mechanism or scheduler. Owner attribution for action items
is parsed off the `Owner: <name>` line convention `pipeline/extraction.py`
already writes into `artifact.body`.

**Files changed:**
- `server/meetingminer/digest/__init__.py` -- new package, re-exports the generator's public names.
- `server/meetingminer/digest/generator.py` -- new: `read_published_artifacts` (the one SELECT) + `render_digest` (store-free render), plus `DigestArtifact`/`DigestMeeting` value objects.
- `server/meetingminer/digest/cli.py` -- new: `main(argv) -> int`, mirroring `rebuild`'s config/DB/fatal-message conventions; `--output PATH` is required.
- `server/pyproject.toml` -- added `digest = "meetingminer.digest.cli:main"` under `[project.scripts]`.
- `infra/Makefile` -- added a `digest:` target (mirrors `rebuild:`), `.PHONY` entry, help text, and a `DIGEST_ARGS` variable.
- `server/tests/test_digest_generator.py` -- 8 store-free unit tests for `render_digest` (owner present/absent, section presence, ordering, empty state, untitled meeting, multi-line body indentation).
- `server/tests/test_digest.py` -- 6 store-backed tests covering the full I/O matrix (happy path, no published artifacts, missing `--output`, DB unreachable, migrations pending, mixed states in one meeting).

**Review findings breakdown:**
- Patches applied: 3 (medium 1, low 2) -- multi-line artifact body only had its first line indented (real rendering defect, now uses `textwrap.indent` on every line, with a new covering test); a stale `extraction.py:892` line-number citation (now line-number-free); a vacuous filesystem assertion in `test_output_missing_fails_with_exit_2_and_writes_nothing` (removed rather than asserting a claim the test never exercised).
- Deferred: 11 (all low) -- see frontmatter `deferred`. No Markdown escaping of artifact text; undocumented timezone handling on the digest's date label; `# type: ignore`-laden accumulator typing; several test-coverage gaps beyond the frozen I/O matrix (same-meeting ordering/tie-break, generic `psycopg.Error`, `OSError` on write, config env-var override, empty owner name, unicode content, `--output` overwrite); the owner-line parser's exact-prefix matching.
- Rejected: 5 -- unknown `artifact.kind` bucketing (unreachable: DB `CHECK`-constrained to `('adr','action-item')`); the Makefile prereq "starting the full stack" (false: `infra-up` is Docker-stores-only, identical to `rebuild`'s own prereq); a meeting with zero published artifacts never appearing (correct behavior, not a bug); `sprint-status.yaml` not updated by this diff (integration session's responsibility, confirmed out of band); no bare `except Exception` fallback in the CLI (mirrors `rebuild`'s own cli.py exactly).

**Follow-up review recommendation:** `true`. Patched-finding score = 3 × medium(1) + 1 × low(2) = 5, which meets the ≥5 threshold (independent of the "any high severity" clause, which did not trigger — 0 high).

**Verification performed:**
- `cd server && uv run pytest tests/test_digest_generator.py -q` -- 8 passed, store-free.
- `cd server && uv run pytest tests/test_digest.py -q` -- 6 passed, store-backed.
- `cd server && uv run pytest tests/ -q` -- 1456 passed (full suite, post-patch run). An earlier full-suite run (pre-patch) showed one unrelated flake, `test_projection_lock_times_out_with_holder_details_then_releases`, caused by a concurrent worktree (`4-3`) holding the cross-worktree projection lock at the same moment — confirmed via `ps aux` during that run, and the `digest` module makes no calls into the projections module. The post-patch full run was clean with no contention.
- `make web-test` -- 157 passed (9 files), unaffected as expected (no web changes).
- Live smoke test against the real dev Postgres (read-only): `digest --output /tmp/...` with no published artifacts yet -> exit 0, wrote "No artifacts are published yet."; `digest` with no `--output` -> exit 2 with the exact fatal message.

**Residual risks:** None blocking. The 11 deferred items are real but low-severity and out of this story's frozen I/O matrix; the most notable is the exact-prefix owner-line coupling to `extraction.py`'s current convention, which would silently degrade (render "Unassigned") rather than fail loudly if that convention ever changes shape.

**Note for the next person who sees a red `test_parallel_store_safety.py` run:** the one full-suite flake observed mid-run (`test_projection_lock_times_out_with_holder_details_then_releases`) was a concurrent worktree (`4-3`) holding the cross-worktree projection lock at that moment, confirmed via `ps aux`. That is Story 2.7's bounded-queue mechanism working as designed, not corruption — no need to re-investigate it if it recurs under concurrent worktree activity; just confirm no worktree of your own is the reason.

### Review Findings

- [x] [Review][Decision] Digest date display timezone — resolved 2026-08-20: preserve the database session's calendar date; no code change required.
- [x] [Review][Patch] Publish output atomically [server/meetingminer/digest/cli.py:108]
- [x] [Review][Patch] Preserve body whitespace after the owner line [server/meetingminer/digest/generator.py:57]
- [x] [Review][Patch] Indent whitespace-only body lines [server/meetingminer/digest/generator.py:115]
- [x] [Review][Patch] Make same-timestamp artifact ordering stable [server/meetingminer/digest/generator.py:74]
- [x] [Review][Patch] Assert sections within each meeting block [server/tests/test_digest.py:123]
