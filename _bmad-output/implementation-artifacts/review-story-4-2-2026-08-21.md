# Code Review — Story 4-2: Visible, Swappable Extraction Prompts

## Scope

- Reviewed branch: `story/4-2` at `65eaf65`
- Reviewed range: `main...story/4-2` (`bfa95b8..65eaf65`)
- Review date: 2026-08-21
- Review mode: full, against `spec-4-2-visible-swappable-extraction-prompts.md` and its declared context

## Findings

### Location

`web/src/features/moments/MomentView.tsx:138`

### Severity

low

### Finding

The prompts effect aborts on its five-second deadline and on cleanup, but it
does not check whether its controller was aborted before committing the
response. A request implementation that settles after the abort can therefore
render prompt text after the UI deliberately gave up on that request.

### Evidence

The effect aborts `controller` in its timer and cleanup, then calls
`setPrompts(data.prompts)` immediately after `getExtractionPrompts` resolves.
Unlike the moment loader, it has no `controller.signal.aborted` guard. A late
resolution is possible at the fetch/SDK boundary even after cancellation; the
current tests cover rejection but not that race.

### Suggested direction

Return without changing state when the controller is aborted, and add a test
that resolves the request after advancing the timeout (or after cleanup) and
asserts the section remains absent.

## Triage

- Active layers: blind hunter, edge-case hunter, verification-gap reviewer,
  and acceptance auditor. No layer failed.
- Disposition: 1 low-severity patch; 15 findings dismissed as spec-conformant,
  unreachable at the reviewed boundary, or a non-actionable future-regression
  concern.
- Focused verification rerun: 168 server/config/API/core tests, 24 worker
  tests, and 189 web tests passed; `git diff --check` passed; the LiteLLM
  import-boundary scan found no forbidden import.

## Remediation Closeout

The finding was fixed in this review branch. The regression test first failed
against the unfixed component (a late response rendered the section), then
passed after the abort guard was added. The focused MomentView suite passed 27
tests; the full web suite passed 190 tests, and TypeScript type-checking passed.

**Review result: pass.**
