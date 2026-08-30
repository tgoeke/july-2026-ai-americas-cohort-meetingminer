---
title: 'Repo reset: de-identify the tree, then publish a fresh single-commit history'
type: 'chore'
created: '2026-08-22'
status: 'in-progress'
baseline_commit: 'd765e8aee05fc0a9d6e0a9a2c60d2f468b1475d1'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** All 802 commits, plus the current working tree, carry employer- and
client-identifying content: 71 distinct real `@corp.com` addresses
(46 of them in one participant CSV), tenant SharePoint URLs embedding employee numbers
(`corponline-my.sharepoint.com/personal/10001_corp_com/…`), and client names (vendor, project,
Boomi, Con Edison) across 53 tracked files. The corpus is being rebuilt from an owned Teams sandbox,
so none of that content should survive into the project's public record. `tgoeke/meetingminer` has
already been deleted from GitHub (verified 2026-08-22: `gh` cannot resolve it, SSH authenticates as
`tgoeke`, and `ls-remote` returns "Repository not found"), so the remaining exposure is the local
history and the working tree — and the local `.git` is now the only copy of those 802 commits.

**Approach:** Substitute every real identifier in place using one deterministic real→fictional
mapping that preserves the value *shapes* the test suites assert on, then discard `.git` entirely
and publish a single-commit history to a fresh **private** `tgoeke/meetingminer`. The name is free,
so there is no delete-first ordering to manage.

## Boundaries & Constraints

**Always:**
- Back up before anything destructive: a `git clone --mirror` of the current repo plus a tarball of
  the tracked tree, both outside the repo, both verified readable. With the remote gone this is not
  merely the undo — it is the only copy of the project's history that exists anywhere.
- Preserve shape when substituting. The identity-key logic distinguishes mail-namespace from
  name-namespace keys, dotted aliases (`cameron.blake@…`) from numeric ones (`10001@…`), and
  `"Last, First"` from `"First Last"`. Tests assert on those distinctions; a flat redaction breaks
  them and a shape-preserving swap does not.
- Use one mapping table for the whole repo: the same real value maps to the same fictional value in
  every file, so cross-file joins that tests rely on still join.
- Quiesce other agents before touching `.git`. A second worktree
  (`meetingminer-wt/puller-source-relocation`) is live and bound to this `.git`; replacing the repo
  under it destroys uncommitted work there.
- Do not begin substituting until `story/puller-source-relocation` has merged to `main`. It is
  moving `pull_transcript/` to `tools/puller`, which relocates four files in this Code Map; scrubbing
  them first means editing them twice and conflicting on every one.
- Stage only paths you changed. Never `git add -A` — until the final fresh-repo commit, which is by
  definition the whole tree.

**Ask First:**
- The final go/no-go before `.git` is removed. Everything up to that point is reversible; that step
  is not, and it is the step that discards the only remaining copy of 802 commits.
- Any prose where a shape-preserving substitution would change what the document *claims* — as
  distinct from what it names. Report it rather than inventing a replacement fact.
- Before the new repo is created public rather than private. Nothing needs deleting on GitHub: the
  old repository is already gone.

**Decided (2026-08-22, do not re-litigate):**
- `evals/runs/2026-08-21-demo-recorded{,-2,-3,-4}/` are **deleted**, not rewritten. They record runs
  that really happened against the real corpus; substituting their `source_id` would make each
  report assert a run that never occurred. They are superseded once the sandbox corpus is re-run.
- `Blake, Cameron` and `Blake, Peyton` **stay as names**. Only their employer-bound forms change:
  `cameron.blake@corp.com` → `cameron.blake@contoso.com`, `10001@corp.com` → a fictional numeric
  alias. The author's own name is not the exposure; the tenant is.
- The scrub starts only after `story/puller-source-relocation` lands on `main`.

**Never:**
- Never rewrite the existing history in place (`filter-branch`, `filter-repo`, interactive rebase).
  The deliverable is a new repository with no ancestry, not a laundered old one.
- Never re-create the old remote to "park" the current history there. It is deleted; leave it dead.
- Never touch untracked content in the 4.6 GB working directory — the corpus, `.env`, and media are
  gitignored and stay that way.
- Never commit the identity map, and never write it inside the repo — not even transiently, since
  another agent may stage it. It lives beside the backup.
- Never treat the vendored tooling (`.claude/`, `.agents/`, `_bmad/`) as in scope. It was checked:
  zero real identifiers across 1,974 files.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mail-namespace identity | `identity_key_for("Blake, Cameron", "cameron.blake@corp.com")` | Maps to the fictional dotted address; still yields `mail:` namespace and still case-folds | N/A |
| Numeric-alias identity | `10001@corp.com` | Maps to a *different* fictional numeric alias; must remain unequal to the dotted key for the same person | Test fails loudly if the two collapse |
| Name-only identity | `"Carter, Jordan"` with no address | Maps to a fictional `"Last, First"`; stays in the `name:` namespace | N/A |
| Tenant deep link | `https://corponline-my.sharepoint.com/personal/10001_corp_com/…%2F10001_corp_com%2F…` | Host, plain segment, **and** URL-encoded segment all substituted consistently | Grep gate fails if any encoded form survives |
| Already-fictional literal | `"Example, Alex"`, `"Vendor, Outside"`, `@example.com` | Left untouched | N/A |
| Client-name fixture | `vendor-weekly` source id, `Boomi Data Hub Demo` title | Substituted; derived slugs in assertions (`2026-06-10-boomi-data-hub-demo-…`) updated in step | Node test fails if slug and title disagree |

</frozen-after-approval>

## Code Map

53 tracked files hold at least one real identifier. Concentrations, highest first:

- `[redacted participant mapping artifact]` -- 46
  rows, 45 real addresses + 46 `name:` keys. The single largest exposure; every other file is
  sparse by comparison.
- `server/tests/` (10 files) -- `test_worker_transcripts.py` (16), `test_api_participants.py` (16),
  `test_augmentation.py` (12), `test_speakers_core.py` (10), `test_ingests.py` (4),
  `test_projections_traversals.py` (3), `test_api_chat.py` (3), `test_drops_root.py` (1),
  `projection_seed.py` (2), `test_extraction_core.py`. Real names appear as *asserted literals*.
- `server/meetingminer/pipeline/speakers.py:145-147` and
  `server/meetingminer/migrations/0005_transcripts_participants.sql:66,73` -- real addresses inside
  explanatory comments about why dotted and numeric aliases must not be joined. Comments only; no
  behavior depends on them, but the explanation must survive the swap intact.
- `_bmad-output/specs/spec-meetingminer/corpus-facts.md` -- densest prose: measured inventory of the
  real archive, a per-owner OneDrive table, client folder names (`02 All General corp x vendor`),
  tenant URL patterns. Expect the heaviest rewrite here.
- `_bmad-output/planning-artifacts/` (7 files) -- `solution-design.md:118`, `epics.md:97`,
  `ARCHITECTURE-SPINE.md`, the three `reviews/*update-2026-08-18.md`, and `.memlog.md:49` all
  describe the corpus as "~25 real corp production meetings (vendor, project, Boomi, corp
  internal)". These are decision records — AD-12's rationale rests on this premise, so rewrite the
  identifiers without altering the reasoning.
- `_bmad-output/specs/spec-meetingminer/` -- `scope.md:21`, `SPEC.md`, `ux-spine.md`, `.memlog.md`
  (lines 72, 190).
- `_bmad-output/implementation-artifacts/` (13 more) -- `spec-1-8` (archive facts, line 113),
  `spec-1-11` (`vendor_template_field_matrix.xlsx`, line 278), `spec-2-2:243`, `spec-2-3:211`,
  `spec-1-5`, `spec-1-13`, `spec-1-2`, `sprint-notes.md`,
  `deferred-work.md`, `demo-readiness-2026-08-22.md`, `kickoff-story-1-8-*`,
  `review-prompt-story-1-8-*`.
- `pull_transcript/` (4 files) -- `test/emit-drop.test.js:90,93` (tenant URL, employee `65967`) and
  `:113-223` (`Boomi Data Hub Demo` title + derived slug assertions); `README.md:204-222` and
  `CLAUDE.md` (launchd label `com.corp.grabtranscript.index`, ~6 occurrences);
  `grab-teams-transcript.js:19,1290` ("Sign in with corp SSO" console copy);
  `migrate-layout.js:16` (real meeting folder name).
- `evals/` (7 files) -- `ground-truth/demo-001-*.yaml` and `demo-002-*.yaml` carry the tenant
  `source_id`; `tests/test_subject_selection.py` uses `vendor-weekly` as a fixture id (8 lines);
  `runs/2026-08-21-*/deterministic-report.yaml` ×4 — see **Ask First**.
- `web/src/App.test.tsx`, `web/src/features/participants/Participants.test.tsx` -- 3 addresses.

Clean, confirmed by grep, and **out of scope**: `.claude/`, `.agents/`, `_bmad/`, `README.md`,
`config.yaml`, `CLAUDE.md`, `docs/`, the three root capstone documents.

Repo facts that shape the git work: 802 commits, `.git` is 14 MB, no submodules, no LFS, no
non-sample hooks. `.gitattributes` selects the `sprint-status` merge driver and
`_bmad/scripts/install_merge_drivers.sh` must be re-run in the fresh clone, because `.gitattributes`
selects a driver but the driver itself lives in `.git/config`.
`story/chat-artifact-question-matching` is likewise fully merged and disposable.
`story/puller-source-relocation` is *live* in another agent's worktree and is moving the puller into
`tools/` — which relocates four of the files in this Code Map.
No secrets were ever committed — the `sk-ant-`/`sk-or-` hits are deliberate `FAKE-SECRET` fixtures,
and `.env` has never been tracked.

## Tasks & Acceptance

**Execution:**
- [ ] Wait for `story/puller-source-relocation` to merge to `main`, then re-run the grep gate to
      re-derive the file list -- four Code Map paths move from `pull_transcript/` to `tools/puller`.
- [x] `<backup dir outside the repo>` -- `git clone --mirror` the repo and tar the tracked tree;
      verify both restore -- with the remote deleted this is the only copy of the history.
      Done 2026-08-22 at `../meetingminer-backup-2026-08-22/`: mirror holds 810 commits and all
      three local branches (`main` `d765e8a`, `story/puller-source-relocation` `78513e1`,
      `story/chat-artifact-question-matching` `884404f`), `fsck` reports only dangling unreferenced
      objects; tarball `meetingminer-tracked-tree-d765e8a.tar.gz` restores 2,604 files, matching
      `git ls-files` exactly. The mirror captures committed refs only — uncommitted worktree state
      is still at risk and is covered by the next task.
- [ ] Confirm no other agent is mid-write and no worktree holds uncommitted work -- it dies with
      `.git`.
- [x] `<backup dir>/identity-map.tsv` -- author the real→fictional table (organisation, mail domain,
      SharePoint host, employee numbers, 71 addresses, real person names, 4 client names, meeting
      titles) -- one table drives every later edit and makes the substitution auditable.
      **It must never be tracked.** The map pairs every real identifier with its replacement, which
      is the exposure in its most concentrated form; committing it would defeat the whole task and
      carry it into the fresh repo. Keep it beside the backup, outside the working tree.
      Done 2026-08-22: 203 rows — 71 addresses, 58 persons (2 kept: the author's own), 2 employee
      numbers, 14 fixed org/client/infrastructure terms. Collision-checked: no two real values share
      a replacement. Generated by `build_identity_map.py` (kept beside the map) so it is
      reproducible rather than hand-typed. One extraction bug found and fixed in the process:
      employee `65967` appears *only* as a SharePoint path segment, never as an address, so an
      email-derived harvest misses it — the generator now unions both sources.
- [ ] `[redacted participant mapping artifact]` -- rewrite all 46 rows from the map,
      preserving `name:`/`mail:` prefixes and the `already_merged` column.
- [ ] `server/tests/` (10 files) + `server/meetingminer/pipeline/speakers.py` +
      `migrations/0005_transcripts_participants.sql` -- substitute; keep dotted-vs-numeric
      distinctions and the comments' explanatory force.
- [ ] `web/src/App.test.tsx`, `web/src/features/participants/Participants.test.tsx` -- substitute.
- [ ] `tools/puller/` (4 files, post-relocation) -- substitute tenant URL, employee number, launchd
      label, SSO copy, meeting titles, and the slug assertions derived from those titles.
- [ ] `evals/ground-truth/*.yaml` + `evals/tests/test_subject_selection.py` -- substitute.
- [ ] `evals/runs/2026-08-21-demo-recorded{,-2,-3,-4}/` -- `git rm -r` all four -- they record runs
      against the real corpus and cannot be honestly rewritten.
- [ ] `_bmad-output/` (28 files) -- substitute across specs, planning artifacts, memlogs, sprint
      notes; `corpus-facts.md` needs prose rewriting, not token replacement.
- [ ] Run the full grep gate and both suites; fix what the substitution broke.
- [ ] Commit the scrub on `main` -- so the de-identification is a reviewable commit in the old
      history before that history is discarded. It cannot be pushed: the remote no longer exists.
- [ ] Remove `.git` and every worktree, `git init`, restore the merge driver, commit the whole tree
      once, create the new private `tgoeke/meetingminer`, push.
- [ ] Verify the new remote is private and its single commit is clean.

**Acceptance Criteria:**
- Given the scrubbed tree, when `git grep -lIiE 'corp\.com|corponline|_corp_com|vendor|project|boomi|con ?edison'`
  runs over tracked files, then it returns nothing.
- Given the scrubbed tree, when `git grep -lIw 'corp'` runs, then it returns nothing.
- Given the fresh repo, when `git log --oneline` runs, then exactly one commit is listed and
  `git log --all -S'corp.com'` is empty.
- Given a fresh clone of the new remote, when `_bmad/scripts/install_merge_drivers.sh` then
  `make test` run, then all four suites pass and the web build succeeds.
- Given the new remote, when its visibility is checked, then it is private.
- Given the scrubbed tree, when `git ls-files evals/runs` runs, then no `2026-08-21-*` path is
  listed.

## Design Notes

The mapping should read as a plausible fictional organisation rather than as redaction, so the docs
still explain themselves. Microsoft's canonical placeholder tenant fits a Teams-based project and is
unmistakably fake:

    corp                            -> Contoso
    corp.com                        -> contoso.com
    corponline-my.sharepoint.com    -> contoso-my.sharepoint.com
    10001 / 65967 (employee no.)   -> 40217 / 41883
    cameron.blake@corp.com          -> cameron.blake@contoso.com   (name kept, tenant swapped)
    Blake, Cameron / Blake, Peyton-> unchanged
    Carter, Jordan                 -> Morgan, Dana
    vendor / project / Boomi   -> Northwind / Vendor Portal / Fabrikam
    com.corp.grabtranscript.index   -> com.contoso.grabtranscript.index

Substitute the URL-encoded segment (`%2F10001_corp_com%2F`) as well as the plain one; the eval
ground-truth `source_id` values contain both in a single string.

## Verification

**Commands:**
- `git grep -lIiE 'corp\.com|corponline|_corp_com|vendor|project|boomi|con ?edison' -- .` -- expected: no output
- `git grep -lIw 'corp' -- .` -- expected: no output
- `git grep -hIoE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' -- . | awk -F@ '{print $2}' | sort -u` -- expected: only `example.com`, `test.com`, `company.com`, `contoso.com`, and the `.example`/`.invalid` reserved hosts
- `uv run --project server pytest server/tests` -- expected: pass, no skips beyond the usual store-dependent ones
- `cd pull_transcript && npm test` -- expected: pass
- `uv run --project evals pytest evals/tests` -- expected: pass
- `make test` -- expected: four suites pass, web build succeeds (stores must be up)
- `gh repo view tgoeke/meetingminer --json visibility` -- expected: `private`

**Manual checks (if no CLI):**
- The backup mirror clone opens and `git log` in it shows all 802 commits before `.git` is removed.
- `corpus-facts.md` still reads as a coherent measured inventory after rewriting, not as a document
  with holes punched in it.
