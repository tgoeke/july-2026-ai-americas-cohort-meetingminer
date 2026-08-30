---
title: 'Story 4-3: Per-Moment Approval & Publishing'
type: 'feature'
created: '2026-08-20'
status: 'done'
baseline_revision: '2e375a7b3d069a4d77b1adf758618a077828dd0c'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-1a-whole-transcript-extraction.md'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/storage-layout.md'
warnings: [oversized]
deferred:
  - summary: >-
      A partial multi-artifact approve batch can leave earlier artifacts'
      export files and (for ADRs) git commits durably on disk even though
      Postgres correctly rolls the whole request back to `extracted`.
    evidence: |-
      `approve_moment_artifacts` runs one shared Postgres transaction for the
      whole moment's pending artifacts, but each artifact's file export and
      git commit happen as non-transactional side effects inside the same
      loop. If artifact N of a batch fails, the transaction rollback correctly
      reverts every row's Postgres state to `extracted`, but artifacts before
      N already had their file written and (if `adr`) their git commit made —
      neither is undone. Self-healing on a retry of the same underlying cause
      (idempotent export/commit reproduce the same path/sha), but a
      permanently-failing artifact anywhere in a batch leaves earlier
      artifacts' disk/git state permanently out of sync with their `extracted`
      Postgres state. Does not violate the unpublished-never-in-retrieval
      invariant (Postgres state, not the filesystem, gates projection), but is
      a real data-hygiene gap the frozen spec's Design Notes did not fully
      reason through for N>1 artifacts.
    location: >-
      server/meetingminer/api/moments.py (approve_moment_artifacts)
    severity: medium
  - summary: >-
      Two concurrent approve requests on the same moment can hit a Postgres
      serialization failure that surfaces as an unhandled 500 instead of a
      named Problem.
    evidence: |-
      The route uses `SELECT ... FOR UPDATE` under `REPEATABLE READ`. Once
      the first concurrent transaction commits, Postgres raises SQLSTATE
      40001 on the second, blocked transaction rather than silently
      re-evaluating the WHERE clause. Nothing in the route catches this. Not
      exercised by any test (all existing tests call the route sequentially).
      Low-probability (requires two genuinely concurrent approve clicks on
      the same moment) and recoverable by a client retry, but the response
      shape breaks the RFC 9457 contract this route otherwise honors
      everywhere else.
    location: >-
      server/meetingminer/api/moments.py (approve_moment_artifacts)
    severity: medium
  - summary: >-
      require_publish_root's startup write-probe uses a fixed filename,
      racy under two API instances sharing MM_PUBLISH_ROOT.
    evidence: |-
      Copied verbatim from require_content_root's existing probe pattern
      (touch a fixed-name file, then unlink it) per the spec's own
      instruction to match that function's shape exactly. The race is
      pre-existing in require_content_root too — not unique to this story's
      new function — so fixing it here alone would leave the older root's
      startup gate with the same gap.
    location: >-
      server/meetingminer/config.py (require_publish_root, require_content_root)
    severity: low
  - summary: >-
      Migration 0011 adds no CHECK constraint tying publish_commit_sha's
      nullability to kind = 'adr'; the invariant relies entirely on this
      story being the only writer of both columns.
    evidence: |-
      The migration's own comment states this explicitly as a deliberate
      choice ("no CHECK enforces that split — this story is the only writer
      of both columns"). A future direct SQL fix-up, backfill, or additional
      writer could violate the invariant with nothing at the schema level to
      catch it.
    location: >-
      server/meetingminer/migrations/0011_artifact_publish_metadata.sql
    severity: low
---

<intent-contract>

## Intent

**Problem:** `extracted` artifacts sit in Postgres, visible only through the API, with no way for a human to move them forward. The moment view's right rail (story 2.2) already renders the `artifacts` field but it is hardcoded `[]`, and nothing exists to advance the one-way `extracted → approved → published` lifecycle or to export a published artifact anywhere.

**Approach:** Wire the right rail's read to the real `artifact` table, and add one per-moment API gesture that advances every `extracted` artifact belonging to a moment straight through `approved → published` in one call: each is exported to a configured publish folder, and ADRs are additionally committed to a plain local git repository there. The moment view gets one "Approve & publish" button per moment (not per artifact) and renders each published artifact's export path / commit sha as its outbound link.

## Boundaries & Constraints

**Always:**
- AD-5 table ownership: this story's API code writes only `artifact.state`, `approved_at`, `published_at`, `publish_relative_path`, `publish_commit_sha` — never `kind`/`title`/`body`/`provenance`/`moment_id`/`meeting_id` (worker-owned).
- The lifecycle stays one-way and API-only: `extracted → approved → published`, no unpublish path. The per-moment gesture advances every `extracted` artifact under that moment through both transitions inside one request/transaction; there is no separate "approved but not yet published" resting state exposed to the human (AD-4/AD-5, epics AC2).
- ADRs (`kind = 'adr'`) are exported to the publish folder **and** committed to the local git repo there; `action-item` artifacts are exported to the same folder but never git-committed (epics AC3, verbatim).
- `MomentArtifact`'s existing wire fields (`id`, `kind`, `state`, `title`, `body`) keep their names and meaning (frozen by story 2.2's spec); this story only adds new optional fields.
- The publish folder is a third configured, machine-specific location (`storage-layout.md` §1) — not a "root" in AD-3's two-anchor sense, validated fail-fast at API startup the same way `MM_DROPS_ROOT` already is.
- No projection/indexing of any kind on publish — story 4.4 owns wiring `publish_gate.project_artifact` to Neo4j/Meilisearch. This story may read `publish_gate.ARTIFACT_STATES`/`PUBLISHED_STATE` as constants only.
- File export + git commit happen before the Postgres `UPDATE`/commit inside the request handler, so a filesystem or git failure leaves every affected row `extracted` (no half-published artifact ever becomes visible as `published` in Postgres). A retried request is safe: re-exporting identical content and re-committing an unchanged file are both no-ops that still yield a usable path/sha.
- Follow existing `api/moments.py` conventions: `Problem`/`ProblemDetails` for errors, `REPEATABLE READ` for the read-then-write query, `to_camel` aliasing, no auth (matches every other route).

**Block If:** None identified — the export path/filename convention, publish-root config key, and git-init behavior are build-time decisions, resolved in Design Notes below rather than left open.

**Never:**
- No changes to `server/meetingminer/projections/` (publish_gate.py's `Artifact` dataclass, `artifact_document`, `project_artifact`) beyond reading its two constants — that is story 4.4.
- No worker or pipeline changes; this story is API + web only.
- No new Python dependency for git (no GitPython) — shell out to the system `git` binary, which every dev/CI environment already has for the repo itself.
- No unpublish / no state rollback endpoint.
- No per-artifact approve/publish endpoint — the gesture is per-moment only, matching the epics' AC1 wording ("the per-moment approval gesture to publish its artifacts").
- No downstream status sync (NFR9) — MeetingMiner never reads back GitHub/wherever the folder or repo is later pushed to.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path, mixed kinds | Moment has 2 `extracted` artifacts (1 adr, 1 action-item) | Both become `published`; adr file is git-committed, action-item file is exported only; response returns both rows with `publishRelativePath`/`publishCommitSha` (adr) set | No error |
| Nothing to approve | Moment exists, has zero `extracted` artifacts (none yet, or all already `approved`/`published`) | No writes, no file/git side effects | 409 `nothing-to-approve` |
| Unknown moment | `moment_id` matches no row | No writes | 404 `not-found`, same shape as `GET /moments/{id}` |
| Meeting not viewable | Moment's meeting has evidence still settling | No writes | 409 `meeting-not-viewable`, same gate as `GET /moments/{id}` |
| Retry after partial failure | A prior call exported files but the DB `UPDATE` never committed (crash mid-request) | Re-running finds the same rows still `extracted`; re-export overwrites identical content; git commit for an unchanged file yields "nothing to commit", so the handler falls back to `git rev-parse HEAD` for that path's current sha instead of failing | No error — idempotent retry |
| Publish folder unusable | `MM_PUBLISH_ROOT` unset, not absolute, or not writable | API refuses to start | Fail-fast at startup (`SystemExit(1)`), same contract as `MM_CONTENT_ROOT`/`MM_DROPS_ROOT` |
| Git binary missing/fails on an ADR | `git` not on `PATH`, or `git commit` exits non-zero for a reason other than "nothing to commit" | No artifacts in that moment become `published` (handler raises before the DB write) | 500 problem naming the artifact id and the git failure |

</intent-contract>

## Code Map

**Migration**
- `server/meetingminer/migrations/0011_artifact_publish_metadata.sql` -- new file (never edit 0009/0010). Adds to `artifact`: `approved_at timestamptz`, `published_at timestamptz`, `publish_relative_path text`, `publish_commit_sha text`. All nullable (populated only once `state` advances past `extracted`). No new CHECK beyond what already exists on `state`; `publish_commit_sha` is naturally NULL for `action-item` rows and non-NULL for published `adr` rows — no constraint needed, this story is the only writer.

**Config**
- `server/meetingminer/config.py:645-659` (`Secrets`) -- add `mm_publish_root: Path | None = None`, following `mm_content_root`'s exact shape and doc-comment style.
- `server/meetingminer/config.py:687-730` (`_load_secrets`) -- add `mm_publish_root=root("MM_PUBLISH_ROOT")` beside the two existing `root(...)` calls.
- `server/meetingminer/config.py:772-808` (`require_content_root`) -- add a sibling `require_publish_root(config: AppConfig) -> Path`, identical shape (set, absolute, creatable via `mkdir(parents=True, exist_ok=True)`, directory, write-probed) since the API both creates and writes into this location, unlike the read-only drops root.
- `.env.example` -- add `MM_PUBLISH_ROOT=/Users/you/meetingminer-publish` beside the two existing roots, with a comment in the same voice: an export the API writes into once per publish; not backed by evidence re-read the way the other two roots are, but still must be backed up (per `storage-layout.md` §1's "third configured location").
- `_bmad-output/specs/spec-meetingminer/storage-layout.md` -- out of scope to edit (spec-kernel file owned by bmad-spec); the publish folder is already documented there at line 37-40 as a third configured location. No change needed.

**Export + git**
- `server/meetingminer/publish/__init__.py` -- new package, empty.
- `server/meetingminer/publish/export.py` -- new file. `export_artifact(publish_root: Path, artifact_id: UUID, kind: str, title: str, body: str) -> Path` writes `{publish_root}/{kind}/{artifact_id}.md` (content: `# {title}\n\n{body}\n`), creating the kind subdirectory as needed; returns the path relative to `publish_root`. `ensure_git_repo(publish_root: Path) -> None` runs `git init` under `publish_root` only when `{publish_root}/.git` is absent, then sets local `user.name`/`user.email` (e.g. `MeetingMiner`/`meetingminer@localhost`) via `git config` so a commit never fails on a missing global git identity in a fresh environment. `commit_artifact(publish_root: Path, relative_path: Path, title: str, artifact_id: UUID) -> str` runs `git add <relative_path>` then `git commit -m "Publish ADR: {title} ({artifact_id})"`; if commit exits non-zero because there is nothing to commit (stderr containing `nothing to commit`), instead returns the current `git rev-parse HEAD` for that path; any other non-zero exit raises a named `GitExportError` carrying the artifact id and `stderr`. All calls use `subprocess.run(..., cwd=publish_root, capture_output=True, text=True)` — no shell=True, args always passed as a list.

**API**
- `server/meetingminer/api/moments.py:215-224` (`MomentArtifact`) -- add three optional fields: `published_at: datetime | None = None`, `publish_relative_path: str | None = None`, `publish_commit_sha: str | None = None`. All `None` for `extracted`/`approved` rows.
- `server/meetingminer/api/moments.py:502-556` (`get_moment`) -- replace the hardcoded `artifacts=[]` (line 552) with a real read: `SELECT id, kind, state, title, body, published_at, publish_relative_path, publish_commit_sha FROM artifact WHERE moment_id = %s ORDER BY created_at, id`, run inside the same `pool.connection()` block as the existing header/segments reads (same REPEATABLE READ snapshot), mapped to `MomentArtifact` rows.
- `server/meetingminer/api/moments.py` -- new route `POST /moments/{moment_id}/approve`, `operation_id="approveMomentArtifacts"`, `response_model=list[MomentArtifact]`. Reuses `_MOMENT_WITH_MEETING` + `_require_viewable` for the same 404/409 gate as `get_moment`. Selects `FOR UPDATE` the moment's `extracted` artifact rows; 409 `nothing-to-approve` if none. For each row: `export.export_artifact(...)`; if `kind == 'adr'`, `export.ensure_git_repo(...)` then `export.commit_artifact(...)` for the commit sha. `UPDATE artifact SET state = 'published', approved_at = now(), published_at = now(), publish_relative_path = %s, publish_commit_sha = %s WHERE id = %s` per row, all inside the one `with pool.connection()` block so the transaction commits once, after every export/commit has already succeeded. Reads `request.app.state.publish_root` (set at startup, see `main.py` below).
- `server/meetingminer/api/main.py:38-45` (drops-root gate) -- add a sibling fail-fast block calling the new `require_publish_root(CONFIG)` right after it, same `try/except ConfigError` shape, storing the result for the app to use.
- `server/meetingminer/api/main.py` -- `app.state.publish_root = <the validated path>`, set beside `app.state.config`/`app.state.embedder` (no registration-order hazard: `POST /moments/{moment_id}/approve` is a 3-segment path, `GET /moments/{moment_id}` is 2-segment, FastAPI does not confuse them).

**Web**
- `web/openapi-ts.config.ts`, `make client` (`infra/Makefile:749-753`) -- run after the API changes land, to regenerate `web/src/client/{sdk.gen.ts,types.gen.ts}` with `approveMomentArtifacts` and the three new `MomentArtifact` fields. Requires the api reachable on `:8000` (`make api` or `make up`); announce before running per AGENTS.md.
- `web/src/features/moments/moments.ts:20-35` -- no changes to `ARTIFACT_CATEGORIES`/`artifactsOfKind`; add a small pure helper `hasApprovableArtifacts(artifacts: Array<MomentArtifact>): boolean` (`artifacts.some(a => a.state === 'extracted')`) for the button's visibility, testable the same way as the file's other helpers.
- `web/src/features/moments/MomentView.tsx:257-303` (right rail) -- inside each artifact `<li>` (line ~284), when `artifact.state === 'published'`, render its `publishRelativePath` (and `publishCommitSha` when present) as a small text line under the title/state span — the "outbound link" AC4 requires, rendered as text since it names a local filesystem/git location, not a URL. Above the rail's `<ul>`, add an "Approve & publish" `<Button>` (reuse the same `Button` component already imported for replay) shown only when `hasApprovableArtifacts(detail.artifacts)`, calling `approveMomentArtifacts({ path: { momentId } })` from `@/client/sdk.gen` on click, disabling itself while in flight, and on success replacing `detail.artifacts` with the response (reuse the existing `AbortController`/timeout pattern already in this file for the initial load). On failure, surface the `Problem` body via the same `problemMessage`/`problemType` helpers `moments.ts` already exports.
- `web/src/features/moments/MomentView.test.tsx` -- extend with cases for: button hidden with no `extracted` artifacts, button visible and click triggers the approve call, success replaces the rail with published state + outbound link text, failure surfaces a message and leaves state unchanged.

**Tests**
- `server/tests/conftest.py:258-283` (`EVIDENCE_TABLES`) -- no change (`artifact` already present since story 4.1).
- `server/tests/test_moments_api.py` (existing file, extend) or a new `server/tests/test_artifact_publish.py` -- a local `insert_artifact(conn, moment_id, meeting_id, kind, state='extracted', ...)` seed helper (raw SQL, matching `test_worker_extract.py:151`'s `artifact_rows` style — no shared factory exists yet). Cover: `GET /moments/{id}` returns real `extracted` artifacts (not `[]`); `POST /moments/{id}/approve` happy path (mixed adr/action-item) writes files under a `tmp_path`-backed `MM_PUBLISH_ROOT`, git-commits only the adr, updates Postgres, and the response carries `publishRelativePath`/`publishCommitSha`; 409 when nothing to approve; 404 for an unknown moment; retry-after-partial-failure is idempotent (call twice, second call finds nothing left to approve once the first succeeded — or, to exercise the git "nothing to commit" path directly, call `export.commit_artifact` twice against the same unchanged file and assert the second call returns the same sha without raising).
- `server/tests/test_publish_export.py` -- new, unit-level, store-free: `export_artifact` writes the expected path/content; `ensure_git_repo` is idempotent (safe to call twice); `commit_artifact` returns a real sha, and returns the same sha on a no-op second commit; a `git` failure (e.g. commit into a non-repo directory) raises `GitExportError` naming the artifact id. Uses `tmp_path` and the real `git` binary — this is local, offline tooling, not a "store" under AGENTS.md's docker-stack rule, so exercising it for real (rather than faking it) is the right call, unlike the LLM guard.
- `server/meetingminer/config_test.py` / wherever `require_content_root`'s tests live -- add the equivalent cases for `require_publish_root`.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0011_artifact_publish_metadata.sql` -- add the four nullable publish-metadata columns -- AD-5: this is the API's half of the disjoint column split.
- `server/meetingminer/config.py` -- add `mm_publish_root`, wire it in `_load_secrets`, add `require_publish_root` -- the publish folder needs the same fail-fast startup discipline as the other two roots (AD-10).
- `.env.example` -- document `MM_PUBLISH_ROOT` -- so a fresh clone's first `make bootstrap`/`make api` names the missing config instead of failing opaquely.
- `server/meetingminer/publish/export.py` -- add `export_artifact`/`ensure_git_repo`/`commit_artifact`/`GitExportError` -- the epics' AC3 file-export-plus-git-commit behavior, isolated from the API route so it is unit-testable without a live server.
- `server/meetingminer/api/moments.py` -- extend `MomentArtifact`, wire `get_moment`'s real artifact read, add `POST /moments/{moment_id}/approve` -- the read half (AC1's precondition) and the per-moment approval gesture (AC1/AC2/AC3) together, since both are moment-scoped artifact operations already living in this file.
- `server/meetingminer/api/main.py` -- fail-fast `require_publish_root` startup gate, `app.state.publish_root` -- same contract as the drops-root gate immediately above it.
- `make client` -- regenerate the web SDK against the updated OpenAPI schema -- so the new endpoint and fields are typed on the web side.
- `web/src/features/moments/moments.ts` -- add `hasApprovableArtifacts` -- pure, testable gate for the button's visibility.
- `web/src/features/moments/MomentView.tsx` -- add the per-moment "Approve & publish" button and each published artifact's outbound-link text -- AC1 and AC4.
- `server/tests/test_artifact_publish.py` (or extended `test_moments_api.py`) -- cover the I/O matrix above -- store-backed, exercises the real endpoint end to end.
- `server/tests/test_publish_export.py` -- cover `export.py`'s edge cases directly -- store-free, faster feedback than going through the API for the git-specific behaviors.

**Acceptance Criteria:**
- Given a moment with `extracted` artifacts, when I open the moment view, then I see those artifacts in the right rail and an "Approve & publish" gesture (epics AC1).
- Given that gesture, when I invoke it, then the API advances every `extracted` artifact under that moment one-way through `extracted → approved → published` in a single request, and no unpublish path exists anywhere in the system (epics AC2).
- Given a published `adr` artifact, when publishing completes, then a markdown file exists under `MM_PUBLISH_ROOT/adr/` and that file is committed to a git repository rooted at `MM_PUBLISH_ROOT`; given a published `action-item` artifact, then a markdown file exists under `MM_PUBLISH_ROOT/action-item/` and it is not committed to git (epics AC3).
- Given published artifacts, when I view the moment afterward, then each shows its export path (and git commit sha, for ADRs) in context, and nothing in the UI reflects or polls any status beyond that local export (epics AC4, NFR9).
- Given an artifact I do not approve, when I leave it alone, then it remains `extracted` indefinitely and visible only in its own moment's right rail — never in search or chat (epics AC5; unpublished-artifacts-never-in-retrieval remains structurally true because this story never calls `publish_gate.project_artifact`).

### Review Findings

- [x] [Review][Patch] Honor an operator-created Git repository at `MM_PUBLISH_ROOT` [server/meetingminer/publish/export.py:143] — resolved by remediation `6910744`; configuration is authorization and existing local identity/history are preserved.
- [x] [Review][Patch] Bound the approval request in the web UI and recover after timeout [web/src/features/moments/MomentView.tsx:126] — resolved by remediation `d402788`.
- [x] [Review][Patch] Serialize shared-repository mutations, commit only the target artifact, and record that artifact's commit [server/meetingminer/publish/export.py:129] — resolved by remediations `d402788`, `6910744`.
- [x] [Review][Patch] Remove inherited Git repository/index overrides from subprocesses [server/meetingminer/publish/export.py:324] — resolved by remediation `d402788`.
- [x] [Review][Patch] Fail explicitly when local Git identity configuration fails [server/meetingminer/publish/export.py:153] — resolved by remediation `d402788`.
- [x] [Review][Patch] Repair the timeout test so its fake Git process actually times out [server/tests/test_publish_export.py:374] — resolved by remediation `d402788`.
- [x] [Review][Patch] Exercise `MM_PUBLISH_ROOT` through a real API startup failure path [server/tests/test_failfast.py:84] — resolved by remediation `d402788`.
- [x] [Review][Defer] Upstream extraction can duplicate the same decision as an ADR and action item [_bmad-output/implementation-artifacts/sprint-notes.md:201] — deferred, pre-existing in Story 4-1a/Epic 4 triage; Story 4-3 correctly publishes all extracted rows under its frozen contract.

## Review Triage Log

### 2026-08-20 — Review pass

Four layers over `75dd706..05730e6`: blind hunter, edge-case hunter,
verification-gap, intent-alignment.

- intent_gap: 0
- bad_spec: 0
- patch: 8: (high 3, medium 4, low 1)
- defer: 4: (high 0, medium 2, low 2)
- reject: 3
- addressed_findings:
  - `[high]` `[patch]` A git subprocess `OSError` (missing `git` binary,
    permission error) was uncaught — it propagated past the
    `GitExportError` handler as an unhandled 500 instead of the RFC 9457
    `Problem` the spec's own I/O matrix requires for a git failure.
  - `[high]` `[patch]` `export.export_artifact`'s file write ran with no
    try/except, so a disk-full/permission `OSError` on *any* artifact's
    plain export (not just ADRs) surfaced as an unhandled 500.
  - `[high]` `[patch]` The approve response was built from `published_ids`
    (only the rows just transitioned) instead of `refreshed` (every
    artifact under the moment), so a moment with artifacts from an earlier
    approve, or new extraction after one, would have them silently vanish
    from the right rail once the frontend replaced its state with the
    response.
  - `[medium]` `[patch]` The git subprocess calls had no timeout, risking a
    hung `git` process blocking the open Postgres transaction's `FOR
    UPDATE` locks indefinitely.
  - `[medium]` `[patch]` `commit_artifact`'s "nothing to commit" detection
    matched an English-only substring, breaking the idempotent-retry path
    under a non-English git locale.
  - `[medium]` `[patch]` The `PublishRootNotOwnedError` → `500
    publish-root-not-owned` mapping was implemented in the API route but
    only unit-tested against `ensure_git_repo` directly, never through the
    route itself.
  - `[medium]` `[patch]` `MomentView.tsx`'s approve handler had no
    stale-response guard, unlike the initial load's existing
    `controllerRef` pattern (story 1.10 finding 22) — a moment switch or
    unmount mid-request could apply a response to the wrong moment or after
    unmount.
  - `[low]` `[patch]` The button's in-flight disabled state and label were
    specified in the Code Map and implemented, but every test mocked the
    approve call synchronously, so the pending state was never asserted.
  - `[medium]` `[defer]` A partial multi-artifact approve batch can leave
    earlier artifacts' export files and ADR git commits durably on disk
    even though Postgres correctly rolls the whole request back to
    `extracted` — self-healing on retry of the same cause, doesn't violate
    the unpublished-never-in-retrieval invariant, but a real disk/DB
    inconsistency the frozen Design Notes didn't fully reason through for
    N>1 artifacts. Recorded in frontmatter `deferred`.
  - `[medium]` `[defer]` Two genuinely concurrent approve requests on the
    same moment can hit a Postgres serialization failure (40001) that
    surfaces as an unhandled 500 rather than a `Problem`. Recorded in
    frontmatter `deferred`.
  - `[low]` `[defer]` `require_publish_root`'s write-probe uses a fixed
    filename, racy under two API instances sharing `MM_PUBLISH_ROOT` — a
    pre-existing pattern copied from `require_content_root`, not unique to
    this story. Recorded in frontmatter `deferred`.
  - `[low]` `[defer]` Migration 0011 has no CHECK tying
    `publish_commit_sha`'s nullability to `kind = 'adr'`; the invariant
    relies entirely on this story being the only writer, which the
    migration's own comment already states as a deliberate choice.
    Recorded in frontmatter `deferred`.
  - `[reject]` No confirmation dialog before the irreversible bulk-publish
    click — the click itself is the explicit gesture the epics call for;
    not a stated requirement.
  - `[reject]` `epic-4-context.md` dropped an RFC 9457/logging line in its
    regeneration — it is a distillation cache file permitted to omit
    anything re-derivable or already enforced in code, and the code
    enforces RFC 9457 `Problem`/`ProblemDetails` everywhere.
  - `[reject]` Untested non-`adr`/`action-item` artifact kinds in the
    approve loop — unreachable given migration 0009's own CHECK
    constraining `kind` to those two values; later kinds are explicitly
    future stories' scope per that migration's comment.

## Design Notes

- **One gesture, two transitions, no exposed middle state.** The epics text says "I'm offered the per-moment approval gesture to publish its artifacts" — one click — while AD-4/AD-5 name three lifecycle states. Resolved by treating `approved` as an internal waypoint the same request also advances past, rather than a second human decision. **Attack point:** if a future story wants "approve now, publish later" as two separate human gestures, this collapses them and would need a second endpoint; nothing here forecloses adding one, since the state column and its CHECK already support the middle state.
- **The publish folder becomes a git repo lazily, on first ADR publish**, not at API startup, so an install that never publishes an ADR never gets a `.git` directory it didn't ask for. `ensure_git_repo` is called from the approve route, not from startup validation.
- **A local `user.name`/`user.email` is set on init** rather than relying on the operator's global git config, because a fresh dev machine or CI container commonly has neither — and a commit failing on "Please tell me who you are" would be a confusing first-publish error unrelated to anything this story is actually testing.
- **Filesystem/git side effects precede the Postgres write, not the reverse.** A failed `UPDATE` after a successful export leaves an orphan file on disk but no artifact wrongly marked `published` — recoverable by retry. The reverse ordering (DB first) would risk a `published` row whose file was never actually written, which is worse: an artifact search/chat could later cite as published (once 4.4 wires indexing) something that doesn't exist on disk.
- **Filename is `{artifact_id}.md`, not a slugified title.** Titles are free text from an LLM and not guaranteed filesystem-safe or unique; the artifact's own UUID is already the citation key everywhere else in the system (AD-6), so reusing it here avoids inventing a second identifier scheme.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_publish_export.py -q` -- expected: all pass, store-free.
- `cd server && uv run pytest tests/test_artifact_publish.py tests/test_moments_api.py -q` -- expected: all pass; store-backed, needs the shared Postgres stack (announce per AGENTS.md before running).
- `cd server && uv run pytest tests/ -q` -- expected: all pass, full regression.
- `make web-test` -- expected: all pass, including the new `MomentView.test.tsx` cases.
- `make client` -- expected: regenerates `web/src/client/*` with no manual edits needed afterward (diff review only).
- `rg -n "import git|GitPython" server/meetingminer --glob '!server/meetingminer/publish/**'` -- expected: no matches (no git dependency leaked outside the one module that shells out to it).

## Auto Run Result

**Status:** implemented; review round 1 applied — all 8 patch findings fixed.
(The triage also recorded 4 deferred and 3 rejected; those are in frontmatter
`deferred` and the Review Triage Log above.)

**Summary of implemented change:** The moment view's right rail now reads real
`artifact` rows (replacing the hardcoded `[]`), and a new per-moment
`POST /moments/{moment_id}/approve` gesture advances every `extracted`
artifact under a moment straight through `approved → published` in one
request: each is exported to a configured `MM_PUBLISH_ROOT` folder, and `adr`
artifacts are additionally committed to a plain local git repository rooted
there. File export and git commit happen before the Postgres `UPDATE`, so a
failure never leaves an artifact wrongly marked `published`. The web view
gained an "Approve & publish" button (shown only when the moment has
`extracted` artifacts) and renders each published artifact's export path /
commit sha as its outbound link.

**Files changed, with one-line descriptions:**
- `server/meetingminer/migrations/0011_artifact_publish_metadata.sql` — four
  nullable publish-metadata columns on `artifact` (AD-5's API-owned half).
- `server/meetingminer/config.py`, `.env.example` — `MM_PUBLISH_ROOT` secret +
  `require_publish_root`, fail-fast at startup like the other two roots.
- `server/meetingminer/publish/export.py` (new) — `export_artifact`,
  `ensure_git_repo` (with a foreign-repo ownership guard,
  `PublishRootNotOwnedError`), `commit_artifact`, `GitExportError`; git
  subprocess calls are timeout-bounded, locale-pinned, and every failure mode
  (missing binary, permission error, timeout) raises a named error.
- `server/meetingminer/api/moments.py` — `MomentArtifact` gained
  `publishedAt`/`publishRelativePath`/`publishCommitSha`; `get_moment` reads
  real artifact rows; new `POST /moments/{moment_id}/approve` route.
- `server/meetingminer/api/main.py` — `require_publish_root` startup gate,
  `app.state.publish_root`.
- `web/src/features/moments/moments.ts` — `hasApprovableArtifacts`.
- `web/src/features/moments/MomentView.tsx` — the approve button (with a
  stale-response guard mirroring the existing load-abort pattern) and each
  published artifact's outbound-link text.
- `web/src/client/*` — regenerated via `make client`.
- `server/tests/test_publish_export.py`, `test_publish_root.py`,
  `test_artifact_publish.py` (new); `MomentView.test.tsx` (extended).

**Review findings breakdown:** 8 patched (high 3, medium 4, low 1 — all
applied and re-verified independently), 4 deferred to frontmatter `deferred`,
3 rejected as out of scope or already honored elsewhere in the code.

**Follow-up review recommendation:** `true`. Counting only this pass's `patch`
findings: high 3, medium 4, low 1 — any high severity alone triggers `true`;
score = 3 × 4 + 1 × 1 = 13, also at or above the threshold of 5.

**Verification performed (re-run independently, post-patch, then again after
rebasing onto `main` at `69b767b` to pick up story 3-4's landing):**
- `cd server && uv run pytest tests/test_publish_export.py tests/test_publish_root.py tests/test_artifact_publish.py tests/test_api_moments.py -q` -> 66 passed (both runs).
- `cd server && uv run pytest tests/ -q` (full regression) -> pre-rebase: 1471
  passed, 1 failed (`test_projections_graph.py::test_graph_chunks_retain_nonresolved_speaker_turn_metadata`,
  a Neo4j projection test this story never touches), re-run in isolation ->
  1 passed — confirmed transient cross-worktree Neo4j contention per
  AGENTS.md, not a regression. Post-rebase: 1472 passed, 0 failed.
- `npx vitest run` (web, full suite) -> pre-rebase 164 passed; post-rebase 176
  passed (the extra cases are story 3-4's, picked up by the rebase).
- `rg -n "import git|GitPython" server/meetingminer --glob '!server/meetingminer/publish/**'` -> no matches (both runs).
- `git status --porcelain` empty after every commit, including the rebase.

**Residual risks (see frontmatter `deferred` for full evidence):**
- A partial multi-artifact approve batch can leave earlier artifacts' export
  files / ADR git commits durably on disk even though Postgres correctly
  rolls the whole request back to `extracted` — self-healing on retry of the
  same cause, does not violate the unpublished-never-in-retrieval invariant.
- Two genuinely concurrent approve requests on the same moment can hit an
  unhandled Postgres serialization failure instead of a named `Problem`.
- `require_publish_root`'s write-probe shares a pre-existing race with
  `require_content_root`'s, not unique to this story.
- Migration 0011 has no CHECK tying `publish_commit_sha` to `kind = 'adr'`;
  relies entirely on this story being the only writer (a deliberate,
  documented choice).
- `.env` in the worktree is symlinked from the main checkout and was
  read-permission-blocked for the implementation subagent, so
  `MM_PUBLISH_ROOT` was not added there — a human needs to add it before
  `make api`/`make up` will start cleanly in this worktree.
