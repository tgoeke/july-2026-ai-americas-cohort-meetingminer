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
- **Resolution:** **Open while reported.** Distinguish the first table header from subsequent ID-less data rows, reject a contentful row under a foreign topic heading by section name, prove the generate path retries, and preserve the header-only shared document as an honest zero.
