# Code Review — Story 7.4: Speaker Naming UI

Date: 2026-08-31

## Scope

Adversarial review of the Story 7.4 web implementation, with emphasis on unsettled-evidence state retention, AD-13 identity handling, all three speaker-assignment paths, rerun event folding, combobox accessibility, replay behavior, and the meeting-view insertion. Server code and generated clients are out of scope; owner-decision or frozen-spec issues remain open.

## Review range

- Source branch: `story/7-4`
- Review branch: `story/7-4-review`
- Implementation-only range: `4e35269..6cdd1d2`
- Review base supplied by the handoff: `4e35269`
- Source head at review start: `6cdd1d2`

## Findings

### F1 — Cold recovery still cannot read speaker tags

- **Location:** `server/meetingminer/api/speakers.py:211`; `server/tests/test_api_speaker_assignment.py:581`
- **Severity:** High
- **Status:** Fixed on `story/7-4-review`
- **Finding:** `GET /meetings/{id}/speakers` still calls `_require_viewable` unconditionally, so a curator cold-loading a meeting whose speaker rerun failed cannot obtain the tag needed by the route-local recovery `PUT`. This contradicts the owner ruling in `docs/backlog.md` B-41.
- **Evidence:** Commit `7d8d93e` rules that the read must receive the same narrow, route-local recovery exception while drilldown and unrelated operations remain gated. The route still returns `meeting-not-viewable`, and `test_only_speaker_put_bypasses_the_failed_evidence_gate` currently asserts that obsolete 409 for the speakers read.
- **Suggested direction:** Red-first, change the failed-rerun boundary test to require a successful speakers response with the meeting's tags while retaining 409 for drilldown/moments and unrelated writes; implement the exception locally in the speakers read without changing `_require_viewable`.
- **Red/green evidence:** The revised boundary test first failed with `409 meeting-not-viewable`; after the route-local exception it passed. The adjacent fast API suites passed: 45 passed, 6 slow tests deselected.
