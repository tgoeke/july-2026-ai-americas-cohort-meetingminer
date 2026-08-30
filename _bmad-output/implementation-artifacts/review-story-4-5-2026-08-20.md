---
title: 'Code Review: Story 4-5 — Morning Digest Example Email'
story: '4-5-morning-digest-example-email-could-droppable'
reviewed_range: '72d49bb..1d150e0'
status: 'passed'
date: '2026-08-20'
---

# Code Review — Story 4-5

Independent full-spec review of `story/4-5` against `main`, at
`72d49bb7a13abfd5fec5e04d77d2f5983dcd5207..1d150e00c3d1f7e00ae5eea02e3118aad81b9b75`.

## Review outcome

The frozen intent contract is implemented: the acceptance audit found no
contract violation. The date policy and all five accepted code/test patches
are resolved.

### Digest date has no defined display timezone

- **Location:** `server/meetingminer/digest/generator.py:120`
- **Severity:** low
- **Finding:** The meeting date is derived from the timezone of the database
  connection (`meeting.started_at.date()`), but the contract requires a date
  label without specifying whether it is UTC, the meeting locale, or a
  configured reader locale.
- **Evidence:** `started_at` is `timestamptz`; the same instant can produce a
  different calendar date when Postgres or psycopg uses a different session
  timezone. The repository has no existing digest display-timezone policy.
- **Suggested direction:** Choose and document one display-timezone policy;
  then make rendering and its test deterministic under that policy.

**Resolution (2026-08-20):** Preserve the database session's calendar date.
This is the intended display policy for the one-shot example file; no code
change is required.

### Output writes are not atomic

- **Location:** `server/meetingminer/digest/cli.py:108`
- **Severity:** medium
- **Finding:** `Path.write_text()` truncates an existing requested digest
  before the full replacement has been written. An interrupted or failed
  write can therefore leave a previously complete digest partial or empty,
  despite the command returning an error.
- **Evidence:** The `OSError` handler only reports after the direct write; it
  does not preserve the previous destination. A temporary sibling file plus
  atomic replacement avoids this state.
- **Suggested direction:** Publish the completed text atomically at the
  supplied path and clean up a failed temporary file.

### Owner parsing removes meaningful body whitespace

- **Location:** `server/meetingminer/digest/generator.py:57-58`
- **Severity:** low
- **Finding:** After taking the owner line, `_split_owner()` calls
  `rest.strip()`, discarding leading/trailing blank paragraphs in the artifact
  body.
- **Evidence:** `Owner: Alice\n\nFollow up` is rendered without the intentional
  paragraph break, even though only the leading owner line should be removed.
- **Suggested direction:** Remove only the owner line and preserve the exact
  remaining body content.

### Whitespace-only continuation lines escape Markdown indentation

- **Location:** `server/meetingminer/digest/generator.py:115`
- **Severity:** low
- **Finding:** `textwrap.indent()` does not prefix blank or whitespace-only
  lines by default. Blank paragraphs in an artifact body therefore escape the
  list-item indentation and can terminate or distort the Markdown item.
- **Evidence:** The generator deliberately emits Markdown headings and
  indented multi-line bodies; `textwrap.indent(..., predicate=lambda _: True)`
  is needed to preserve indentation for every line.
- **Suggested direction:** Indent whitespace-only continuation lines as well,
  with a blank-paragraph regression test.

### Published-artifact ordering has an unstable tie

- **Location:** `server/meetingminer/digest/generator.py:74`
- **Severity:** low
- **Finding:** The query has no unique tie-breaker after `a.created_at`.
- **Evidence:** PostgreSQL `now()` is transaction-stable, so multiple
  artifacts inserted in one transaction may share that timestamp and render
  in unspecified order on repeated runs.
- **Suggested direction:** Add a stable final ordering key (such as `a.id`) and
  cover the equal-timestamp case.

### Happy-path test does not prove sections are grouped per meeting

- **Location:** `server/tests/test_digest.py:123-129`
- **Severity:** low
- **Finding:** The test asserts that each heading occurs somewhere in the
  aggregate file, not that each of the two seeded meetings includes both its
  own Decisions and Action Items sections.
- **Evidence:** A grouping regression that emits all headings only for one
  meeting can satisfy the existing global substring assertions.
- **Suggested direction:** Split the rendered output by meeting boundary (or
  assert each meeting's bounded block) and require both sections in both.

### Triage notes

- The plain-text/Markdown body is a defensible implementation of "one example
  email file": the frozen contract and architecture intentionally leave the
  exact format to build time and explicitly exclude delivery. MIME is not a
  missing requirement.
- Exact `Owner: ` matching is the contract's specified extraction convention;
  accepting case/whitespace variants would invent behavior rather than meet a
  current requirement.
- The remaining reported test gaps (generic `psycopg.Error`, output `OSError`,
  config overrides, installed-command/Make integration, non-ASCII text, and
  all-corpus memory bounds) are worthwhile hardening but are outside the
  frozen I/O matrix or lack a defined policy. They are not blockers for this
  focused story.

## Remediation and verification

- **Resolved decision:** The date label intentionally preserves the database
  session's calendar date; no timezone conversion is applied.
- **Resolved patches:** `9536c8c` writes through a temporary sibling then
  atomically replaces the requested output, preserves post-owner whitespace,
  indents blank body lines, and adds `a.id` as the final query ordering key.
  `fdc9e5c` adds the covering regression tests, including per-meeting section
  assertions.
- **Verification:** `tests/test_digest_generator.py` — 11 passed;
  `tests/test_digest.py` — 7 passed; `make web-test` — 166 passed. Two full
  server-suite attempts each recorded 1,459 passed and one unrelated
  Meilisearch primary-key inference failure, but in different projection-search
  tests. Both failing tests passed in isolation. This is a shared-store test
  fixture flake, not a Story 4-5 regression; it prevents claiming a clean full
  suite in this session.

**Review verdict:** passed. No must-fix Story 4-5 findings remain. Integration
must wait for one clean full-server run under a healthy shared Meilisearch
store; this review does not merge the branch while that required command is red.
