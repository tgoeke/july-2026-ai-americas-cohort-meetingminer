# Review prompt — Story 2.1: Media Streaming & Replay Foundation

Hand this file to the Codex `bmad-code-review` agent. It stands alone; the reviewer has none of the build run's context.

## Repo, branch, range

- Repo: `github.com:tgoeke/meetingminer`, worktree `../meetingminer-wt/2-1`, branch `story/2-1` (pushed, `0 0` against upstream).
- Review range: `961254eb69eae2ff0d5859b4ac7e2a31dbb731fe..HEAD`.
- Baseline `961254eb` is the branch point from `main` ("docs(sprint): close Epic 1 for development").

Commits in range, all story 2.1 — no foreign commits:

| Revision | Subject |
| --- | --- |
| `82791b601d68a74bef6af81b2effcaa7717acdb2` | docs(story 2.1): plan the media streaming and replay foundation |
| `f3285d4` | feat(story 2.1): serve media with range requests and a seeking player |
| `261d06d` | fix(story 2.1): close the review findings on media streaming |
| `3e3a931` | docs(story 2.1): record the review outcome and the AD-3 divergence |

## Spec

`_bmad-output/implementation-artifacts/spec-2-1-media-streaming-replay-foundation.md`.

- **Frozen intent** — everything inside `<intent-contract>`: Intent, Boundaries & Constraints, and the I/O & Edge-Case Matrix. This was derived from Story 2.1 in `_bmad-output/planning-artifacts/epics.md`. Do not critique it as authored text; critique it only where the code fails to satisfy it.
- **Planner work, fair game** — Code Map, Tasks & Acceptance, Design Notes, Verification, the triage log, and the deferred list. The Design Notes in particular contain the decision this review exists to test.

## Architecture authority

- **AD-3 (Binaries on disk, paths in the DB)** — the governing decision, and the one this story departs from. `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md:182`.
- **AD-1 / AD-14 (source drops are write-once)** — why the recording is read from the drop rather than copied out of it.
- **AD-5 / AD-11 (table ownership; the api never runs pipeline stages)** — the media routes must stay read-only.
- **AD-13** — the pipeline never writes into a source drop.
- Conventions: RFC 9457 problem bodies, camelCase at the API boundary, plural-noun REST paths.

## Scope

**In scope (the whole change set):**

- `server/meetingminer/api/media.py` — new; both routes, range parser, containment guard, chunked responder.
- `server/meetingminer/api/main.py` — router registration only.
- `server/tests/test_api_media.py` — new; 72 tests.
- `web/src/lib/media.ts`, `web/src/lib/media.test.ts` — new.
- `web/src/features/replay/ReplayPlayer.tsx`, `ReplayPlayer.test.tsx` — new.
- `_bmad-output/implementation-artifacts/` — the spec, `epic-2-context.md`, `deferred-work.md`, `sprint-status.yaml`.

**Explicitly out of scope:**

- The moment view, the drill-down, and the screenshot series (stories 2.2 / 2.3). Nothing mounts `ReplayPlayer` yet and no route emits a media path — that is the story being a foundation, not an omission.
- The `evidence_complete` / `viewable` gate on a detail route — story 2.3 owns it.
- Anything in `pipeline/`, `worker/`, `config.py`, or the migrations — untouched by design.
- The eleven items already recorded in the spec's frontmatter `deferred` list. Re-finding them is noise; **contradicting** one is valuable.

## Design decisions to attack

Each is a choice plus the assumption under it. The planner is not a neutral judge of its own calls.

1. **The recording is served from the write-once drop, not from under `MM_CONTENT_ROOT`.** AD-3 says video lives under the content root with a root-relative path in the DB. Frames and screenshots do; the recording does not, and no column names it (`meeting_media` holds ffprobe facts only). The route resolves `meeting -> job.drop_path -> recording.mp4` server-side and exposes it as `/media/recordings/{meetingId}`.
   *Assumption:* that "media files under `MM_CONTENT_ROOT`" in the acceptance criteria describes the frames/screenshots case, and that the recording's location is an unstated gap rather than a requirement to relocate it. The alternative — a new column plus a multi-GB copy in a worker-owned stage — was judged outside this story. **If this assumption is wrong, the story is built on the wrong reading.** Recorded as deferred item 1 and in `deferred-work.md`.

2. **`/media/{path:path}` trusts a client-supplied path behind a containment guard**, rather than taking a screenshot/frame id and looking the path up in the DB. *Assumption:* that the acceptance criterion's traversal clause implies client-supplied paths, since traversal is only a hazard if the client names the path. The cost is that any file under the content root is reachable, so the guard is the only line rather than defence in depth. Deferred item 2.

3. **Two routes under one prefix, with registration order load-bearing.** `/media/recordings/{meeting_id}` must precede the `/media/{path:path}` catch-all. *Assumption:* that `recordings/` cannot collide with a real file, because `pipeline/outputs.py` writes only a `meetings/` subtree. A future writer of a `recordings/` directory silently breaks this.

4. **The containment guard is reimplemented, not imported** from `pipeline/outputs.py:assert_private_meeting_subdir`. *Assumption:* that a read-only api must not reuse a function that creates and write-probes its target, and that `pipeline/` is off-limits to the api. The cost is two guards that can drift.

5. **A malformed `Range` is ignored in favour of the whole file** (RFC 9110 permits it) rather than refused. *Assumption:* that a player sending a bad header is better served bytes than an error.

6. **The web half ships as unmounted primitives.** *Assumption:* that "viewed and replayed in the browser" is satisfied by 2.2/2.3 mounting them.

## History the reviewer needs

- The branch was cut from `main` at `961254eb` and never rebased; the range is linear.
- `f3285d4` is the pre-review implementation; `261d06d` is the post-review fix round. Reviewing only the tip hides what the review already caught — **read the range, not the tip**.
- The story was built in a worktree because agents run concurrently here; the shared Docker stores were held for the test runs and released.
- Four review layers (blind, edge-case, verification-gap, intent-alignment) already ran. Two of them contradicted each other on whether FastAPI auto-adds `HEAD` to a `GET` route; measured on the installed FastAPI 0.141.1 / Starlette 1.6.0, it does **not** — `HEAD` answers 405. Do not re-derive that from memory.
- One I/O-matrix row cannot behave as written: `GET /media/../../etc/passwd` is collapsed by every conforming client before routing, so it 404s from the router rather than 400-ing from the guard. Both spellings are pinned as tests asserting no bytes are served. The matrix was **not** relaxed to match the code (the intent-contract is read-only). Treat the status-code mismatch as a known wording artifact, not a finding.

## Verification baseline

Run by the orchestrator on `3e3a931`, so a skip or failure during review is a finding, not noise:

| Command | Result |
| --- | --- |
| `cd server && .venv/bin/python -m pytest tests/test_api_media.py -q` | 72 passed, 0 skipped |
| `cd server && .venv/bin/python -m pytest tests/ -q` | 816 passed, 0 failed, 0 skipped (3m43s) |
| `make web-test` | 52 passed, 5 files |
| `uvx ruff check --isolated meetingminer/api/media.py tests/test_api_media.py` | clean |

Two caveats:

- **`ruff` is installed nowhere in this repo** and has no `pyproject.toml` config — the spec's `.venv/bin/ruff` command cannot run (a standing deferred item since story 1.1). `uvx ruff check --isolated` was used. Its two findings are both in `main.py` and are pre-existing: linting `main.py` at `961254eb` produces the identical two.
- The store-backed suites need Postgres, Neo4j and Meilisearch on their fixed ports. They are shared across agents — hold them one agent at a time (`AGENTS.md`).

A mutation check was run and is worth repeating if you doubt the new coverage: forcing `_iter_chunks` single-shot (`remaining -= len(chunk)` -> `remaining = 0`) fails exactly the two multi-chunk tests and nothing else.

## Required output

Write findings to `_bmad-output/implementation-artifacts/review-story-2-1-2026-08-19.md`.

**Report findings; do not apply fixes.** Structure each as:

- Location (`file:line`), severity (high / medium / low), and category.
- The defect stated in one sentence.
- A concrete failure scenario: inputs or state, and the wrong output or behaviour that results.
- Whether it is caused by this change or pre-existing.

Rank most severe first. Where you disagree with one of the six design decisions above, say so explicitly and give the consequence — that is the most useful thing this review can produce. An empty findings list is an acceptable outcome if the change holds up; say so plainly rather than manufacturing findings.
