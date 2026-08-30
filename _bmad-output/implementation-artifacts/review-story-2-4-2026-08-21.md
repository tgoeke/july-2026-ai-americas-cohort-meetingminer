# Code Review — Story 2-4: Participant Curation

**Review date:** 2026-08-21  
**Reviewer branch:** `story/2-4-review`  
**Reviewed branch:** `story/2-4`  
**Range:** `9f9d895..57b9359`

## Scope

Independent adversarial review of the Story 2-4 implementation, tests,
generated client changes, and frozen contract. The reviewer-handoff commit
`21a58ad` is context only and is not part of the reviewed range.

## Findings

### Decision needed

1. **Frozen transaction-isolation contract contradicts the implementation.**
   The frozen `Always` constraint requires `REPEATABLE READ` for each write,
   but [participants.py](../../server/meetingminer/api/participants.py:211)
   deliberately uses PostgreSQL's default `READ COMMITTED`. The implementation
   explains why a fresh post-lock alias read is needed, but that is still a
   departure from frozen intent. The owner must either amend the contract or
   require a different concurrency design.

2. **The required one-time backfill is incomplete.** Task 10 and its
   acceptance criterion require all 46 pairs, while
   [deferred-work.md](deferred-work.md:89) confirms only 1 is merged. This is
   an operational acceptance decision, not a code patch: finish the 45 calls
   or formally retain an explicit exception rather than presenting the story
   as fully done.

**Owner decisions (2026-08-21):** amend the frozen contract to authorize the
documented READ COMMITTED locking design; keep Story 2-4 in progress until a
human or permitted agent completes the remaining 45 backfill calls.

### Patch findings

1. **High — sequential merges create a forbidden alias chain.**
   **Location:** [participants.py](../../server/meetingminer/api/participants.py:274)

   **Evidence:** After `A -> B`, B's own identity is not an `alias_key`, so
   `B -> C` passes both `_is_aliased()` checks and inserts a second row. The
   worker's [single alias lookup](../../server/meetingminer/pipeline/stages/align.py:385)
   maps A only to B, which is now merged away, violating the no-chained-alias
   invariant and producing wrong re-ingest attribution. Reject a source or
   survivor that participates in an existing alias relationship as required to
   keep the map flat; add sequential and concurrent regression tests.

2. **Medium — a second merge can leave the UI stale after an aborted request.**
   **Location:** [Participants.tsx](../../web/src/features/participants/Participants.tsx:163)

   **Evidence:** Every merge shares `mergeControllerRef`; starting B aborts
   A's client request, although an already-received A request can commit on
   the server. A's result is ignored and only B's row is disabled, so an error
   from B leaves A rendered canonical and invites invalid follow-up actions.
   Serialize mutations globally, or reload state after an ambiguous abort or
   conflict.

3. **Medium — duplicate merge targets are indistinguishable.**
   **Location:** [Participants.tsx](../../web/src/features/participants/Participants.tsx:339)

   **Evidence:** The target picker renders only `displayName`. Exact name
   duplicates — the reason curators open this screen — yield identical options
   despite different identity keys. Show a safe discriminator such as the
   identity key/email before the irreversible request.

4. **Low — NUL input reaches PostgreSQL as a 500.**
   **Location:** [participants.py](../../server/meetingminer/api/participants.py:41)

   **Evidence:** `StringConstraints` trims and bounds the name but accepts a
   JSON `\u0000`; PostgreSQL text rejects NUL bytes. Reject it as
   `invalid-request` in the request model and add an API test.

5. **Low — the UI promises a projection-only effect that does not occur.**
   **Location:** [Participants.tsx](../../web/src/features/participants/Participants.tsx:227)

   **Evidence:** A projection reads existing `meeting_participant` ids. Only a
   re-ingest makes `align._resolve_participants` consume the alias; projection
   comes afterwards. Correct the curator-facing copy.

6. **Low — merge selectors are unnamed for assistive technology.**
   **Location:** [Participants.tsx](../../web/src/features/participants/Participants.tsx:332)

   **Evidence:** Each `<select>` has neither a `<label>` nor `aria-label`, so
   a screen reader cannot identify the participant being absorbed. Give every
   picker an accessible name and test it.

7. **Low — OpenAPI documents the wrong error representation.**
   **Location:** [participants.py](../../server/meetingminer/api/participants.py:141)

   **Evidence:** The app-wide handler emits `application/problem+json`; the
   response declaration generates a typed `application/json` alternative and
   leaves the actual media type empty, so the generated client exposes common
   errors as `unknown`. Declare `ProblemDetails` under the actual media type
   and update the contract test/client.

8. **Low — the only Shell entry point has no integration coverage.**
   **Location:** [App.tsx](../../web/src/App.tsx:162)

   **Evidence:** `Participants.test.tsx` mounts the component directly and
   registry coverage predates this route. A bad button path or absent route
   file leaves the component suite green while the feature is unreachable.
   Add an App-level navigation/deep-link test.

### Triage notes

- Deferred as previously acknowledged in the story: merge confirmation/undo,
  list pagination, and pipeline-level alias-consumption coverage.
- Dismissed: generated-client base URL (configured by `lib/api.ts`), the
  case-insensitive helper-file rename, timeout implementation speculation, and
  a generic lack-of-retry suggestion.
- Layer coverage: blind hunter, edge-case hunter, verification-gap reviewer,
  and acceptance auditor all completed. No layer failed.

## Remediation outcome

All eight code findings were patched on the reviewer branch and verified on
2026-08-21: `server/.venv/bin/python -m pytest
server/tests/test_api_participants.py -q` (17 passed), `pnpm run test` (199
passed), `pnpm run lint` (only the three pre-existing Fast Refresh warnings),
and `pnpm run build` (passed). The generated TypeScript client was regenerated
from the current in-process OpenAPI schema.

Story 2-4 remains **in-progress** solely because the owner chose to complete
the required remaining 45 production backfill merges before closing it.
