# Review prompt — Story 6.4a: Upload Sessions (2026-08-31)

## What you must produce, before you read any code

Write your report to
`_bmad-output/implementation-artifacts/review-story-6-4a-2026-08-31.md`.

**REPORT FIRST.** Create that file as a skeleton — scope, range, an empty
findings section — and **commit it** before you read a line of the diff. Then
append each finding as you confirm it and commit incrementally. Six reviews in
this repository produced their report only as terminal text and were lost; a
crashed session must lose prose, never the artifact.

Every finding carries: **Location / Severity / Finding / Evidence / Suggested
direction**.

**This review lane applies its own patch findings.** Report every finding in the
report file first, then fix the patchable ones yourself on branch
`story/6-4a-review`, cut from `story/6-4a`, in its own worktree
(`make worktree STORY=6-4a-review` — never the main checkout). Red first: the
test observed failing against the unfixed code, then the fix, then green. You
hand nothing back to a builder.

What you must **not** fix: anything needing an owner decision, and anything
whose root cause is the frozen spec. Report those, mark them open, and leave
them for the owner. Never merge to `main`; the owner runs `integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report, including this one) and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

---

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`, worktree
  `/Users/devopsterus/current/cohort/meetingminer-wt/6-4a`
- Branch: `story/6-4a`, cut from `main` at `2d68dcc6`
- Review range: **`2d68dcc6..HEAD`** — six commits, all this story's:

| Revision | Subject |
|---|---|
| `3a007e0e` | spec(6-4a): upload sessions — the plan, and the multipart dependency |
| `ba06dcb3` | feat(6-4a): upload sessions — stage the bytes, mint through mint-drop |
| `dd110905` | test(6-4a): the upload surface, its refusals, and the identity it must keep |
| `e65794eb` | chore(6-4a): regenerate the TS client, with the multipart body declared |
| `5e76589d` | docs(6-4a): the upload door, and the two things it deliberately does not do |
| `1db5b9b7` | test(6-4a): register the new router and the new slow row in their pins |

No commit in the range belongs to another story.

## The spec, and which half is frozen

`_bmad-output/implementation-artifacts/spec-6-4a-upload-sessions.md`.

- **Frozen intent** — everything inside `<intent-contract>`: Intent,
  Boundaries & Constraints, and the I/O & Edge-Case Matrix. It is derived from
  the epic's own acceptance criteria
  (`_bmad-output/planning-artifacts/epics.md`, "### Story 6.4a: Upload
  Sessions"). Disagreeing with it is a finding marked open for the owner, not a
  patch.
- **Planner's work, fair game** — Code Map, Tasks & Acceptance, Design Notes,
  Verification. Attack these freely.

## Architecture authority

- `docs/architecture.md`: **AD-1** (one canonical inbox, the write-once drop),
  **AD-2** (Postgres is the sole database of record — the spec argues an upload
  session is not a domain object and needs no row; test that argument),
  **AD-3** (two roots; the staging area is under the drops root deliberately),
  **AD-10** (refusal boundaries are configuration), **AD-11** (no pipeline work
  in a request handler), **AD-14** (`POST /ingests` is the only intake door),
  **AD-18** (degradation is never silent — refusals are named fields).
- `docs/source-drop.schema.json` — the contract the minted drop must satisfy.
- `docs/README.md` — "Bringing your own recording" is the command this story
  mints through; the new "Uploading through the web app" subsection is part of
  the diff.

## Scope

**In scope:**

- `server/meetingminer/uploads.py` (new — the session, the streaming multipart
  reader, the refusal vocabulary, the sweep)
- `server/meetingminer/api/uploads.py` (new — three routes)
- `server/meetingminer/acquisitions.py` (record `kind`/`uploadSessionId`,
  `launch_upload`, `_start_child`, `run_upload_acquisition`,
  `upload_provenance`, `refusal_for`, `problem_status`, the child CLI)
- `server/meetingminer/api/acquisitions.py` (one-of source selection, `kind`)
- `server/meetingminer/config.py`, `config.yaml` (`acquisition.upload`)
- `server/pyproject.toml`, `server/uv.lock` (`python-multipart`)
- `server/tests/test_api_uploads.py` (new, 47 rows), and the three pinned
  contracts my additions required editing: `test_api_acquisitions.py`,
  `test_config.py`, `test_api_registry.py`, `test_compose_contract.py`
- `web/src/client/*.gen.ts` (regenerated), `docs/README.md`, `docs/backlog.md`

**Out of scope:**

- **All UI.** Story 6.5 owns `/add` and 6.5a will add the tabs that call these
  endpoints. There is deliberately no web feature code in this diff.
- `web/src/features/threads/` and server thread curation (story 10.2a),
  the extract stage and `api/extraction*` (story 12.1), `api/status.py`
  (story 8.2a) — all in flight elsewhere.
- The two items filed as backlog rather than fixed: **B-53** (a failed
  acquisition discards the upload — that is what the frozen criteria say) and
  **B-54** (acquisition status files are still unreaped, carried from 6.4).

## Design decisions to attack

Each is a call I made; the assumption under it is stated so you can go at the
assumption rather than rediscover the call.

1. **A hand-driven multipart parser instead of `await request.form()`.**
   Assumption: spooling every part into `TMPDIR` on the boot volume and then
   copying to `MM_DROPS_ROOT` is unacceptable for a multi-gigabyte recording,
   and a cap that can only be checked after the bytes land is not a cap. The
   cost is ~200 lines of callback handling over `python_multipart`'s API in
   `uploads._PartSink`. Attack the parser handling itself — header accumulation
   across chunk boundaries, a part with no `Content-Disposition`, a duplicate
   field, what happens when the socket dies mid-part, whether any path can leave
   a file handle open or a directory behind.
2. **The session's state is a `session.json` on disk, not a Postgres row, and
   there is no migration.** Assumption: a session is transient producer-side
   state like story 6.4's acquisition status file, so AD-2 does not reach it.
   Migration 0020 was reserved and left unused. If you think AD-2 does reach it,
   that is a finding.
3. **The claim key for an upload acquisition is `upload:<sessionId>`, not the
   drop's `sourceId`.** Assumption: the content id is not knowable before the
   mint, because a `zoom` transcript is *converted* on the way in, so the
   uploaded file's digest is not the drop's. The record's `source_id` therefore
   changes to the content id when the status becomes `posted`. Check that this
   cannot confuse `live_record_for_source`, and check the identity claim itself
   — `test_the_source_id_is_the_digest_of_the_bytes_that_enter_the_drop`.
4. **`url` stayed a required non-null string, carrying `upload:<sessionId>`.**
   Assumption: story 6.5 is being built in parallel against the current
   OpenAPI, so making a field it already consumes nullable is worse than a
   field whose meaning is qualified by the new `kind`. Attack the honesty of
   calling that value a `url`.
5. **`corpus` must be `real`; `scripted` is refused.** Assumption: the epic's
   criteria say `corpus: real`, and an eval subject that arrived through a
   browser cannot be reproduced from the repository.
6. **Day precision is refused.** `mint-drop` accepts `2026-08-05`; an upload
   does not. Assumption: the criteria's "the UI collects the timestamp and never
   infers one from a date". Both `Z` and `±HH:MM` are accepted, because refusing
   `Z` would break parity with `mint-drop`'s documented spelling.
7. **The multipart body is declared with `openapi_extra`.** The handler takes a
   raw `Request`, so FastAPI derives no body schema; the route declares one by
   hand. That declaration can now drift from what `uploads.py` enforces — is one
   test enough to hold them together?
8. **The role of an uploaded file is decided by its extension**, and any part
   with a filename is accepted regardless of its field name. Assumption: this is
   exactly the rule `mint-drop` applies to an operator's argv, and being strict
   about field names buys nothing while 6.5a is unwritten.
9. **Refusal rules are a second closed vocabulary in `uploads.py`.** Assumption:
   `test_api_acquisitions.py` pins `acquisitions.REMEDIATIONS` to
   `youtube.REFUSAL_RULES` exactly, and merging would weaken both pins. They
   meet at `refusal_for()` and `problem_status()`, where an unknown rule
   degrades to 503 rather than raising `KeyError` in a request handler — is that
   the right failure?
10. **The sweep runs at the start of every `POST /uploads`.** Assumption: cheap,
    bounded, and better than a timer nobody notices has stopped. It refuses to
    delete a directory whose name is not a session id, and leaves an in-flight
    upload (no `session.json` yet) alone until the TTL passes by mtime.

## History you need to tell a regression from a pre-existing condition

- The story was built directly rather than through the workflow's
  implementation subagent, on the operator's explicit "work synchronously, no
  background agents" instruction. Recorded in the spec's Design Notes.
- `epic-6-context.md` was recompiled as the workflow requires; the result was
  materially identical to the committed file, so it was left at its committed
  content. It is not in the diff on purpose.
- `make client` health-checks a live api on :8000 and this wave may not start
  one (a corpus ingest is running on the main stack). The client was regenerated
  from a dumped `app.openapi()` with `servers` injected, because generating from
  a URL is where openapi-ts otherwise gets the `baseUrl`. `client.gen.ts` is
  unchanged in the diff, which is where that difference would have shown. If you
  can reach a live api, regenerating with `make client` and getting no diff is
  the check worth running.
- The first full `make test` failed three pinned contracts (registration order,
  and the slow set twice). `1db5b9b7` fixes them; the failures were mine, not
  pre-existing.

## Verification baseline

Run these; anything worse than this is a finding, anything equal is noise.

| Command | Result at `1db5b9b7` |
|---|---|
| `make lint` | All checks passed |
| `make typecheck` | Success: no issues found in 13 source files |
| `uv run --project server pytest -m "" server/tests/test_api_uploads.py -q` | 47 passed |
| `uv run --project server pytest -m "" server/tests/test_api_acquisitions.py -q` | 40 passed |
| `make web-test` | 59 files, 669 tests passed |
| `make test` | see below |

`make test` at `1db5b9b7` is the number to reproduce; at the preceding commit it
was **2770 passed, 3 failed, 3 skipped in 729s**, and the three failures were the
pinned contracts that commit registers. The final gate result is recorded in the
spec's Verification section and in the builder's handoff message.

Stores: this worktree's own stack (`meetingminer-6-4a-*`) was up and healthy for
every run above. Never run `make evals-run`, never start the shared worker or
api, and never touch the main checkout.
