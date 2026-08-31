# Handoff — Story 10.6 review decisions

Repository: MeetingMiner

Review branch: `story/10-6-review`

Source branch: `story/10-6`

Original reviewed range:
`3211a7f96b86d7df496cefa451b2cbd431e6d8b4..d766ce518496351b145171abe4bd0b463f58bb3e`

Review/remediation range: `d766ce5..2396caf`

Primary review artifact:
`_bmad-output/implementation-artifacts/review-story-10-6-2026-08-31.md`

## Review outcome

The story does **not** pass review as it stands. All 16 patchable findings are
already fixed red-first and pushed on `story/10-6-review`; do not reimplement
them. Two decisions remain open. They are not ordinary builder patches and must
not be silently coded around.

## Owner/tooling decision — 10.6-F17

Anchor: `web/src/features/threads/threads.css` (`.mm-at`, `.mm-span`) and
`web/src/features/threads/useTimelineView.ts` (root CSS-property writes).

The demo-critical browser geometry has pure-math and jsdom tests, but no durable
browser-layout check. The requested Chrome 151 remeasurement could not run in
the review session because the Chrome connection was unavailable. Adding a
browser test requires choosing and wiring a harness outside the frozen Story
10.6 footprint.

Owner action required: either provide a Chrome connection for the recorded
measurement or choose the repository browser-test harness and authorize its
tooling/config footprint. The resulting check must execute the real
`.mm-at/.mm-span` CSS and compare rendered x/width against `(t-from)/scale`
across an ordinary view, negative offset, fractional scale, and epoch
re-anchor. Do not substitute a different browser family while claiming the
Chrome recording target was verified.

## Frozen-spec decision — 10.6-F18

Anchor: `web/src/features/threads/ThreadFocus.route.tsx:13` and
`web/src/features/threads/Threads.tsx` (`routeThreadId` initialization/sync).

The UX says a thread chip opens meetings around the calling moment, but
`/threads/:threadId` carries no time or window. The current frozen acceptance
test only selects the thread, and the client has no truthful way to choose
between latest mention, the whole thread span, or the calling moment.

Owner action required: amend the spec to choose one contract. If the calling
moment is required, define the URL parameter/state and navigation producer. If
the server's latest/first occurrence anchors the view, name the exact field and
fit window. Re-derive implementation and tests from that amendment; do not
invent a default in code first.

## Already fixed — no action

- `4210665`: Story 10.3 live envelopes, complete payload validation, timeout
  ownership, and problem/transport classification (10.6-F1, F11).
- `1acb509`: shared data-track geometry, keyboard/pointer activation and pan,
  focus retention, real-width clustering, affordances, and visible density
  (10.6-F4, F5, F7, F8, F12, F13, F15).
- `6eebbd3`: retry and generation/key ownership, payload/thread pairing, common
  ordering, bands-floor fit, and route-param synchronization (10.6-F2, F3, F6,
  F9, F10, F14).
- `b06a8aa`: inert outgoing/incoming 160ms tier cross-fade (10.6-F16).

## Verification required after the owner decisions

Run in an isolated worktree, in the foreground:

```bash
pnpm --dir web exec vitest run src/features/threads
pnpm --dir web exec tsc -b --force
make test-fast
make check-reviews
python3 _bmad/scripts/branch_conflicts.py --against story/10-6-review
```

Any new regression must first be observed failing against the pre-fix tree.
The branch-conflict script may report only the wave-sanctioned concurrent EOF
appends to `sprint-notes.md`; do not resolve other lanes' sections.

## Out of scope

Do not add the evidence tier, inline replay, curation, pins, or a corpus-wide
bands endpoint. Never run `make evals-run`, `make up`, or start the shared API
or worker. Never merge this branch; the owner runs `integrate`.
