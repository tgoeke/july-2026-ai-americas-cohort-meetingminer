# Scoped Verification Review — Story 10-1 (Topic Extraction), Remediation Round

## Scope

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/10-1-review`
- Remediation range: `93215b8..7d68ef4`
- Review boundary: remediation commits only

## Findings

### 1. The finding #8 regression cannot fail against its own fix

- **Location:** `server/meetingminer/pipeline/extraction.py:371,416-425,1068`; `server/tests/test_extraction_topics.py:337`
- **Severity:** Low
- **Finding:** The regression for remediation finding #8 no longer observes either production line added by that fix. Later owner-boundary hardening routes topic timestamp labels through `_TOPIC_TIMESTAMP_HEADERS` and canonicalizes topic bodies to `Gist:` only, so the two generic `"anchor"` additions are shadowed while the test stays green.
- **Evidence:** Applied the exact full-fix mutation `_TIMESTAMP_HEADERS = ("timestamp", "time", "when", "stamp", "anchor")` → `_TIMESTAMP_HEADERS = ("timestamp", "time", "when", "stamp")` and `_GIST_SKIP_LABELS = ("timestamp", "time", "when", "stamp", "anchor")` → `_GIST_SKIP_LABELS = ("timestamp", "time", "when", "stamp")`; `test_an_anchors_header_is_timestamp_bookkeeping_not_gist_text` still passed (`1 passed`).
- **Resolution:** **Resolved** in `f2a14f0`. Added a malformed-`Anchors` regression that fails when the exact `"anchor", "anchors"` entries are removed from `_TOPIC_TIMESTAMP_HEADERS` (`1 failed`) and passes when restored (`2 passed` with the original valid case). Removed the two obsolete generic-label additions that later hardening had shadowed.

### 2. An ID-less contentful foreign table bypasses the fairly-strict boundary

- **Location:** `server/meetingminer/pipeline/extraction.py:942-955`; `server/tests/test_extraction_topics.py:270-315`
- **Severity:** Medium
- **Finding:** Owner ruling #5 requires a contentful foreign `Decisions`/`Notes` table to fail by name and earn the generate retry, but the parser treats every short, non-empty ID-less data row as another header. Such a response returns an honest zero and bypasses retry. Existing foreign-shape cases all carry a parser-recognized item ID, while the header-only regression does not add a data row.
- **Evidence:** Parsed exact input `## Decisions` plus table `Decision | Context | Timestamp` and row `Rotate the vendor key | Required by policy | [0:10]`; the current code returned `artifacts=()`, `populated_target_sections=()`, and `layout='none'` instead of raising `ArtifactParseError`.
- **Resolution:** **Resolved** in `ca80520`. The topics parser now permits the first table header (and later headers that establish topic semantics) but refuses a subsequent ID-less row under a foreign heading by section name. The parser and generate-path regressions were observed red on the prior code (`2 failed`) and green after the fix; the original foreign-ID cases, genuine heading drift, canonical neutral table, and shared header-only zero also passed (`10 passed`).

### 3. The remediation range contains main-owned changes outside Story 10.1

- **Location:** `_bmad/custom/bmad-build-auto.toml:102-112`; `_bmad-output/implementation-artifacts/owner-decisions-2026-08-30.md:8-16`; commit `f675e2c`
- **Severity:** Medium
- **Finding:** The frozen Story 10.1 footprint does not include `_bmad/custom/`, and the wave owner-decision artifact carries a Story 7.1 telemetry ruling. Both nevertheless appear in the exact remediation range, so the range widened beyond the story even though the content is independently reasonable.
- **Evidence:** `git diff --name-status 93215b8..7d68ef4` includes both paths. `f675e2c` is a merge with first parent `e5ff7e8` and second parent the Story 10.1 head `93215b8`; the out-of-scope content came from its `main@f17b87a` integration baseline rather than from a Topic Extraction fix.
- **Resolution:** **Open — owner disposition required.** Reverting these paths on `story/10-1-review` would undo policy already owned by `main`, while rewriting the historical remediation range is outside this review lane's authority. The owner must either accept the merge-baseline exception explicitly or redefine the review range/topology so main-owned changes are excluded.

### 4. The integration-conflict check stays green when the integration fix is reverted

- **Location:** `_bmad-output/implementation-artifacts/review-story-10-1-2026-08-30.md` (finding #10 resolution and verification); commit `f675e2c`
- **Severity:** Low
- **Finding:** `branch_conflicts.py` proves that two refs can merge; it does not prove that the review branch already contains the Story 10.1 head. Reverting the topology-only fix to its pre-merge first parent therefore leaves the claimed check green even though the implementation is absent.
- **Evidence:** Created a temporary ref at exact pre-fix parent `e5ff7e8` and ran `python3 _bmad/scripts/branch_conflicts.py --against story/10-1-review-premerge-verify`; it reported `story/10-1-review-premerge-verify × story/10-1 clean`. The temporary ref was removed. The mutation-sensitive assertion `git merge-base --is-ancestor 93215b8 <target>` returned `1` for `e5ff7e8` and `0` for the reviewed branch.
- **Resolution:** **Resolved** in `d96bcf4`. The prior report now requires both ancestry and mergeability and records the exact red/green ancestry assertion (`e5ff7e8` exit `1`; reviewed branch exit `0`).

## Mutation Verification

| Fix | Exact mutation | Claimed proof under mutation | Restored result |
|---|---|---|---|
| `f675e2c` (#10) | Replaced the merge commit with exact first parent `e5ff7e8` via a temporary ref. | `branch_conflicts.py` still said the pre-merge ref was `clean` against `story/10-1` → Finding 4. New `git merge-base --is-ancestor 93215b8 e5ff7e8` returned `1`. | Ancestry against the reviewed branch returned `0`; relevant `main`/Story 10.1 pairs were clean. |
| `6b788da` (#1) | `FOREIGN KEY (topic_id, meeting_id) REFERENCES topic (id, meeting_id)` → `FOREIGN KEY (topic_id) REFERENCES topic (id)`. | Cross-meeting regression: `1 failed` (`DID NOT RAISE`). | `1 passed`. |
| `018d36e` (#2) | `if document_kind == DOC_TOPICS:` → `if False and document_kind == DOC_TOPICS:` at duplicate-ID rejection. | Duplicate-ID regression: `1 failed`. | `1 passed`. |
| `940b180` (#3) | Disabled the topic-specific `_topic_title_and_body` branch with `if False and document_kind == DOC_TOPICS:`. | Short-name and required-field regressions: `6 failed`. | `6 passed`. |
| `340ab44` (#4) | `authoritative_topic_item_id=(item_id if document_kind == DOC_TOPICS else None)` → `authoritative_topic_item_id=None`. | Strict timestamp regressions: `3 failed`. | `3 passed`. |
| `797c718` (#6) | `deleted_topics = ctx.conn.execute(_DELETE_TOPICS, ...).rowcount` → `deleted_topics = 0`. | Early-exit replacement regression: `1 failed` with two stale topics. | `1 passed`. |
| `93ff86b` (#7) | `if moment_id in superseded:` → `if moment_id in superseded or moment_id in approved_moments:`. | Approved-moment regression: `1 failed` with no topic row. | `1 passed`. |
| `e0f0f8d` (#8) | Removed `"anchor"` from `_TIMESTAMP_HEADERS` and `_GIST_SKIP_LABELS`. | Original regression still passed (`1 passed`) → Finding 1. The replacement removed exact `"anchor", "anchors"` from `_TOPIC_TIMESTAMP_HEADERS` and failed (`1 failed`). | Original plus replacement regressions: `2 passed`. |
| `bc30b3b` (#5 initial) | Disabled the semantic boundary with `if False and document_kind == DOC_TOPICS and not _has_topic_semantics(...)`. | Four parser cases plus generate retry: `5 failed`. | `5 passed`. |
| `9c6d938` (#5 hardening) | Set `_TOPIC_HEADING_NEGATIONS = ()`; then changed exact/distinct Topic/Gist semantics to fuzzy/non-distinct; then changed `return topic, f"Gist: {gist}"` to join all cells; then changed exact topic timestamp lookup to fuzzy lookup. | Respectively: negated-heading case `1 failed`; fused-header case `1 failed`; canonical-gist cases `2 failed`; exact-anchor case `1 failed`. | Combined hardening selection: `7 passed`. |
| Owner ruling #5 adversarial probe | Added an ID-less `Decisions` table data row beneath a foreign header. | Prior code: parser and generate retry regressions `2 failed` → Finding 2. | Fixed boundary plus adjacent owner cases: `10 passed`. |
| `d6aa0a3` (#9 initial) | `AND NOT EXISTS (...)` → `AND FALSE AND NOT EXISTS (...)` in orphan deletion. | Last-moment and settled-extract augmentation regressions: `2 failed`. | `2 passed`. |
| `4f90844` (#9 completion) | `AFTER INSERT ON topic` → `AFTER UPDATE ON topic`; removed `UPDATE OF topic_id` from the row trigger; `DELETE FROM topic` → `PERFORM 1` in the truncate trigger; removed `FOR UPDATE` from the concurrency lock. | Direct orphan, moved mention, truncate, and concurrent-removal regressions each failed (`1 failed` apiece). | Each restored regression passed (`1 passed` apiece). |

## Verification

- `uv run --project server pytest server/tests/test_extraction_topics.py server/tests/test_api_extraction_prompts_topics.py server/tests/test_migrations_topics.py -q` — **60 passed**, 1 pre-existing Starlette deprecation warning.
- `make test-fast` — **passed in the foreground**: puller **128 passed**; web **294 passed**; eval harness **549 passed**; server **1,461 passed, 326 deselected, 0 skipped**, with the same one warning.
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-1-review` and `--against story/10-1` — both commands exit `1` because unrelated active-wave pairs conflict; the relevant pairs `main × story/10-1-review`, `main × story/10-1`, and `story/10-1-review × story/10-1` are all **clean**.
- `git merge-base --is-ancestor 93215b8 story/10-1-review` — **passed** (exit `0`).
- `make check-reviews` — **passed**: every dispatched review has a committed report.
- `make evals-run` — **not run**, as prohibited.

## Verdict

**Fail pending owner disposition.** Findings 1, 2, and 4 are resolved and all behavioral verification is green. Finding 3 remains open because the exact remediation range contains main-owned, out-of-footprint changes; safely removing them would revert shared policy already on `main`, so the owner must accept the merge-baseline exception or redefine the range/topology. No code defect remains open.
