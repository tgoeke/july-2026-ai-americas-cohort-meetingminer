# Code Review — Story 7.2: Speaker Tags on the Wire

Date: 2026-08-30  
Reviewer branch: `story/7-2-review`  
Review base: `origin/main` at `d1abe8a1c3ab1a7b7be7f63cde7d870737245147`  
Rebased story tip: `66ee0261e427726ac2b420f1587a5c074d200c50`  
Review range: `origin/main..66ee0261e427726ac2b420f1587a5c074d200c50`

## Scope

Adversarial review of the complete landed-but-unmerged Story 7.2 range, with
primary attention to the new speakers API route, its tests, route registration,
the regenerated TypeScript client, and the frozen intent contract. The review
also verifies the coordinator's five named claims and attacks the seven design
decisions in the handoff.

## Findings

### F-1 — Nullable attribution fields are optional in the published schema

- **Location:** `server/meetingminer/api/speakers.py:129`
- **Severity:** medium
- **Finding:** `participant_id` and `display_name` have `None` defaults, so
  Pydantic omits them from `SpeakerTag.required`. The runtime route currently
  supplies both keys, but the generated TypeScript contract exposes
  `participantId?` and `displayName?`. That breaks the story's one-shape
  contract at the consumer boundary: a conforming server or mock may omit the
  fields entirely instead of carrying explicit nullable attribution.
- **Evidence:** `SpeakerTag.model_json_schema()` lists only `speakerLabel`,
  `speakerResolution`, `talkTimeMs`, `segmentCount`, and `sampleOffsetsMs` in
  `required`; `web/src/client/types.gen.ts` consequently declares
  `participantId?: string | null` and `displayName?: string | null`. The
  runtime field-set tests do not inspect the OpenAPI required set.
- **Suggested direction:** Declare both fields as required nullable Pydantic
  fields (no default), add an OpenAPI contract assertion that they are required
  and nullable, then regenerate the TypeScript client so both properties lose
  the optional marker while retaining `| null`.
- **Disposition:** Patchable in the review lane; fix pending.
