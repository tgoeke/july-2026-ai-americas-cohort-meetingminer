---
title: 'Story 2.1a remediation: Anchor Integrity and Upgrade Safety'
type: 'bugfix'
created: '2026-08-19'
status: 'done'
review_loop_iteration: 0
baseline_commit: '41bd4fa0d04bd4c5060412931cc83cf48063934a'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-1a-evidence-paths-anchored-to-configured-roots.md'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/storage-layout.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The completed 2.1a path-anchor change has review-confirmed integrity gaps during an
upgrade: its backfill can accept or overwrite unsafe evidence state, direct SQL can create invalid
anchors, and two API/provenance decisions need their selected contract made real.

**Approach:** Harden conversion, provenance, root validation, and database constraints without
changing the intake request shape. Preserve the `GET /jobs` field name while ensuring it never
contains an absolute path, and fail a rerun when the same arrived recording's bytes have changed.

## Boundaries & Constraints

**Always:** Arrived evidence remains read-only; neither API nor worker writes, creates, or
write-probes the drops root. A changed checksum at the same recording path is a hard stage failure
and leaves prior provenance intact. `GET /jobs` retains `dropPath`, but it now carries a nullable
`MM_DROPS_ROOT`-relative value only. Backfill must never overwrite a current re-arm and must report
every unconvertible or provenance-mismatched row non-zero. Database paths must be unambiguous,
non-escaping, and anchored to exactly one root.

**Ask First:** Halt if preserving `dropPath` requires exposing an absolute legacy value, or if the
unreleased migration is known to have been applied outside this development deployment.

**Never:** Do not restore the pre-probe replay behavior, change the `POST /ingests` wire contract,
copy recordings, alter media range behavior, relax symlink refusal, or address deferred operational
batching/locking concerns beyond preventing stale backfill overwrites.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Changed arrived recording | Rerun finds a different digest at the same recorded path | Prior recording provenance remains unchanged | `probe` fails with a named stage error |
| Recording augmentation | Rerun uses a sibling drop path with a new recording | New path and digest are recorded | No error expected |
| Legacy backfill races a re-arm | Job path changes after enumeration | Backfill uses the locked current row and never restores stale path | Current re-arm survives |
| Invalid legacy drop | Symlink, regular file, or malformed drop under root | No conversion is written | Reported; command exits non-zero |
| Tampered legacy provenance | Recording/transcript bytes differ from recorded digest or size | No anchor is widened/accepted | Reported; command exits non-zero |
| Invalid direct SQL path | Root alias, bare evidence filename, or two job anchors | Database rejects write | CHECK violation |
| Job response during migration | Legacy row has only absolute `job.drop_path` | `dropPath` is null and absolute path is absent | No leak |
| Empty quoted environment value | `.env` has `MM_DROPS_ROOT=""` | `make check-env` fails by name | Non-zero before process startup |

</frozen-after-approval>

## Code Map

- `server/meetingminer/backfill.py` — conversion order, legacy-drop validation, provenance checks,
  and requeue behavior; reuse shared drop-domain functions rather than new path logic.
- `server/meetingminer/domain/drops.py` — canonical non-mutating drop reader, symlink guard,
  containment resolver, and checksum/size helper.
- `server/meetingminer/pipeline/stages/probe.py` — recording provenance upsert and rerun behavior.
- `server/meetingminer/api/jobs.py` and `web/src/client/types.gen.ts` — compatible `dropPath`
  read-model wire contract and generated client surface.
- `server/meetingminer/migrations/0008_drop_root_anchored_paths.sql` — unreleased anchor
  constraints; strengthen in place only after confirming it has not landed elsewhere.
- `server/meetingminer/config.py` and `infra/Makefile` — non-mutating startup/early config gates.
- `server/tests/test_drops_root.py`, `test_jobs.py`, and `test_makefile_procs.py` — store-backed
  integrity and API contracts plus store-free Makefile guard coverage.

## Tasks & Acceptance

**Execution:**
- [x] `pipeline/stages/probe.py` and story contract — fail same-path recording substitutions before
  upsert; retain legitimate sibling-drop augmentation and correct conflicting matrix wording.
- [x] `api/jobs.py`, `types.gen.ts`, `test_jobs.py` — restore `dropPath` as nullable root-relative
  response data and prove legacy rows do not leak their absolute value.
- [x] `backfill.py` and `test_drops_root.py` — lock/fetch each current job before converting,
  validate real source drops, and validate recording/transcript digest and size on both new and
  already-anchored paths.
- [x] `migrations/0008_drop_root_anchored_paths.sql` and tests — enforce XOR job anchors and reject
  root aliases or evidence paths lacking a drop-directory component, including transcripts.
- [x] `config.py`, `infra/Makefile`, and process tests — detect unusable drops-root mounts without
  mutation and reject absent or quoted-empty environment values before startup.

**Acceptance Criteria:**
- Given a same-path recording substitution, when `probe` reruns, then the job fails and its existing
  `meeting_media` checksum/path remain unchanged.
- Given a concurrent retry or augmentation, when backfill runs, then it cannot replace the current
  relative path with the initial legacy path.
- Given tampered or non-drop legacy input, when backfill runs, then it reports failure and writes no
  successful anchor for that input.
- Given an old job row, when it is fetched, then the response retains `dropPath` as `null` and never
  includes the legacy absolute path.
- Given direct SQL, when invalid anchor shapes are inserted, then the database rejects them.

## Design Notes

The same recording path identifies immutable arrived bytes. A different drop-relative path is a
legitimate augmentation; the same path with a different digest is evidence mutation. Backfill is
an upgrade tool operating beside live API traffic, so its safety boundary is the job row it locks,
not an earlier table snapshot.

## Verification

**Commands:**
- `cd server && .venv/bin/python -m pytest tests/ -q` — all server tests pass; hold shared stores.
- `make web-test` — unchanged web suite passes.
- `git diff --check` — no whitespace errors.

## Suggested Review Order

### Upgrade safety

- [Lock the current job before validating and converting it](../../server/meetingminer/backfill.py#L289)
- [Reject bad drop metadata or evidence before anchoring legacy jobs](../../server/meetingminer/backfill.py#L332)
- [Preserve old provenance when same-path recording bytes change](../../server/meetingminer/pipeline/stages/probe.py#L90)

### Persistent invariants

- [Enforce one job anchor and unambiguous root-relative evidence paths](../../server/meetingminer/migrations/0008_drop_root_anchored_paths.sql#L37)

### Runtime boundaries

- [Reject malformed legacy spellings before filesystem resolution](../../server/meetingminer/domain/drops.py#L82)
- [Revalidate read-only drops roots at request time](../../server/meetingminer/config.py#L667)
- [Turn an unavailable ingest root into a named API problem](../../server/meetingminer/api/ingests.py#L152)
- [Apply the same root guard before serving recording bytes](../../server/meetingminer/api/media.py#L111)

### Compatibility and proof

- [Keep nullable root-relative data under the established dropPath wire name](../../server/meetingminer/api/jobs.py#L51)
- [Exercise upgrade races, tampering, malformed paths, and CLI configuration](../../server/tests/test_drops_root.py#L1898)
- [Reject omitted and quoted-empty roots before startup](../../infra/Makefile#L138)
