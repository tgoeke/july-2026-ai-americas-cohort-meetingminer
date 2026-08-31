# Builder Handoff — Story 12.1 F5 Provenance Decision

Work in the MeetingMiner repository. Read `AGENTS.md` before touching the tree.
Create an isolated worktree and branch from `story/12-1-review`; do not work in
the main checkout and do not merge to `main`. Commit and push each coherent
unit. Rebase onto the latest `origin/main` before handoff.

Story 12.1 is **in progress**, not done. The adversarial review is complete in:

- `_bmad-output/implementation-artifacts/review-story-12-1-2026-08-31.md`
- `_bmad-output/implementation-artifacts/spec-12-1-retain-the-extraction-documents.md`

Review commits `c840f2b4` and `58f4eebc` resolve F1-F4 and F6. Preserve those
fixes: required-but-nullable `documentText`, typed problem bodies, named UTF-8
refusal, the AD-4 wording boundary, and the exact-byte negative tests.

## The one open finding

F5 is high severity and needs an owner ruling before implementation:

> A rerun can preserve approved or published artifact rows while replacing the
> only `(meeting_id, kind)` `extraction_source` row with a later document. The
> surviving artifact is then presented beside text that did not produce it,
> and the original producer document is gone.

This is a conflict between settled Story 4.1 lifecycle behavior and Story
12.1's single-row replacement contract. Do not choose a design implicitly.
The owner must amend the frozen contract to select and fully specify one of
these directions:

1. Version extraction-source rows and add an immutable artifact-to-source
   reference, including migration/backfill, rerun, endpoint, and Story 12.4
   identity semantics.
2. Freeze a document kind once any artifact produced from it is approved,
   including the expected behavior for other moments that would otherwise
   receive fresh extraction.
3. Change the approved-artifact rerun lifecycle, including what may be replaced
   or removed and how publication remains stable.

If no ruling has been recorded, stop with F5 open; do not make a schema or
product-policy choice on the owner's behalf.

## Once the ruling exists

Implement it red-first. Before production changes, add a regression that:

1. extracts a document and artifacts;
2. approves or publishes one artifact;
3. reruns with different document bytes;
4. proves every surviving approved/published artifact still resolves to the
   exact retained document that produced it, with matching `sha256` and
   `byte_size`.

Also cover sibling draft behavior and all four document kinds. Keep the
transactional guarantee: a failed stage must not leave artifacts or source
metadata partially advanced.

Do not weaken the existing Story 12.1 invariants:

- stored UTF-8 bytes exactly reproduce the bytes parsed;
- adopted documents are reverified after their separate hash/read operations;
- `NULL` means pre-retention and `""` means an honestly empty document;
- NUL and lone-surrogate input fail by document name;
- extraction documents remain claims about evidence, never evidence or
  citation targets;
- the route keeps its settled 404/409/empty-list behavior.

## Repository constraints

- Do not start the shared API or worker, and never run `make evals-run`.
- Never call a paid model.
- Never stage or commit `config.yaml`; the main checkout has local paid-model
  and remote-diarizer bindings.
- If the OpenAPI client changes, generate it from `app.openapi()` locally. Do
  not hand-merge generated files. The known `story/12-1 × story/8-2a`
  overlap on `web/src/client/index.ts` is resolved by regeneration at
  integration time.

## Required verification

Run in the foreground and read the real output:

- `uv run --project server pytest -m "" server/tests/test_worker_extract.py server/tests/test_api_extraction_documents.py -q`
- `make lint`
- `make typecheck`
- `make web-test`
- `make test` with the worktree's private stack
- `python3 _bmad/scripts/branch_conflicts.py --against <your-branch>`
- `make check-reviews`

Update the spec's Review Triage Log, the review report, and
`sprint-status.yaml` from `in-progress` only after F5 is resolved and all gates
pass. The owner performs integration.
