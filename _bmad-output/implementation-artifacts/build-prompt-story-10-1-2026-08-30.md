# Remediation handoff — Story 10.1: Topic Extraction

Agent: `bmad-build-auto`.

## Reviewed state

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Target branch: `story/10-1`
- Reviewed range: `5cdfce7..3cc35926e09913f2d248ef6dbdc251cd469a9bb9`
- Review report: `_bmad-output/implementation-artifacts/review-story-10-1-2026-08-30.md`
- Verdict: **fails review as it stands** — 2 contract decisions and 8 patch findings remain.
- The branch moved relative to current `main`: conflict verification now reports a
  `sprint-notes.md` conflict. Rebase before remediation, preserving both lanes' notes.

Read `wave-2026-08-30-rules.md`, the Story 10.1 spec, and the review report in
full before editing. Do not change the frozen `<intent-contract>` goals.

## Contract amendments required before dependent code changes

These are specification-rooted. Do not silently choose a patch around them.

1. `server/meetingminer/pipeline/extraction.py:704` — the planner explicitly
   made every heading a topics target, but that accepts wrong-document T-rows as
   topics. Amend the planner contract with an acceptance boundary that preserves
   real heading drift and the shared header-only zero document while rejecting a
   contentful Decisions/Tasks table. Re-derive parser tests from that rule.
2. `server/meetingminer/migrations/0014_topics.sql:38` — cascading mentions from
   deleted moments can leave a mention-less topic because augmentation reruns
   `moments` but deliberately not `extract`. Amend the contract to choose one
   cross-stage invariant: delete a topic with its last mention, clean orphans in
   the moment-change transaction, or provide a safe topic-only re-derivation.

Record both amendments in the spec change log before implementing them.

## Fix now after the contract amendments

### Integration first

- `sprint-notes.md:2704` — rebase onto current `main`, resolve the append-only
  notes collision, and rerun `branch_conflicts.py`. Preserve every lane's entry.

### Schema integrity

- `migrations/0014_topics.sql:39-51` — enforce that the topic and moment sides of
  `topic_mention` have the same `meeting_id`, not only that the moment matches
  the duplicated meeting column. Add the exact `(topic_a, moment_b, meeting_b)`
  regression; it must fail against the unfixed schema first.

### Parser correctness

- `pipeline/extraction.py:835-841` — a repeated T-id must not silently lose the
  later row's unique anchors. Merge anchors or reject by name according to the
  amended strictness contract; prove `[0:45]` cannot disappear.
- `pipeline/extraction.py:636-687,917-943` — extract Topic and Gist as required
  topic fields. Accept short names such as `AI`; reject missing name or gist;
  never promote/synthesize one field from the other.
- `pipeline/extraction.py:470-587` — make a labelled topics timestamp field
  authoritative. Reject mixed valid/invalid lists and do not fall back to a
  clock-like value in another cell when the labelled field is unusable.
- `pipeline/extraction.py:369-371,913-943` — handle `Anchor`/`Anchors` consistently
  as timestamp bookkeeping or reject that drift; never store it in `gist`.

### Verification gaps

- `stages/extract.py:324-359` — add an early-exit rerun regression with existing
  topic/mention rows; assert both are removed and `topics_replaced` is counted.
- `stages/extract.py:525-542` — add an approved-moment regression proving topics
  still attach when artifacts on the moment are approved.

Every new regression must be demonstrated against the unfixed behavior (or an
explicit local mutation for the two verification-only gaps) before its fix is
accepted.

## No action

Do not widen this remediation for the dismissed review candidates: generic
database enforcement of sole-writer properties, long-name truncation despite the
short-name prompt, extraction-source vocabulary, optional summary counters, the
Story 6.7 due-date-header deferral, module prose, or the existing/test-pinned
inclusive final-end anchor behavior.

## Verification required

Run all of the following after remediation:

- `uv run --project server pytest server/tests/test_extraction_topics.py server/tests/test_api_extraction_prompts_topics.py server/tests/test_migrations_topics.py -q`
- Any additional focused test files changed by the approved contract amendments.
- `make test-fast`
- `make web-test`
- `make test` once before returning to review; twins required.
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-1`
- `make check-reviews`

No real worker/model call, no `make evals-run`, no threads/derivation/projection,
no curation/chat/UI expansion, and no unrelated cleanup.

## Completion

Return the spec and sprint status to `review`, update the review prompt with the
new exact range, commit each coherent unit, push, and report every SHA. This
requires another independent review; do not merge directly to `main`.
