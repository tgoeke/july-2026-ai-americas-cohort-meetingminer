---
title: 'Story 6.5: Add-Meeting UI'
type: 'feature'
created: '2026-08-31'
status: 'ready-for-dev'
baseline_revision: '2d68dcc6dba31007c7d6fd84f0884edbc79508d5'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** The chrome's **Add meeting** button links to `/add`, and no route claims that path, so every click falls through the unknown-path catch-all back to the front door — a visible primary action that does nothing (Story 6.5; FR34; UX-DR13). Story 6.4 landed the whole api surface behind it (`POST /acquisitions`, `POST /acquisitions/probe`, `GET /acquisitions/{id}`), already regenerated into `web/src/client/`, with nothing in the web app calling it.

**Approach:** Add one discovered child route at `/add` — the Add-meeting screen — carrying the four-tab source chrome the story 6.1 design defines, with the **YouTube URL** tab built: an offline shape check, a debounced pre-flight probe that writes nothing, Submit, then the acquisition stepper (launch → running → posted → ingesting) polling `GET /acquisitions/{id}`, handing over on `posted` to the existing `useJobEvents` stream and the existing meeting-card rendering. Every refusal renders in place as a refusal box carrying the api's own `rule`, `detail`, and `remediation`.

## Boundaries & Constraints

**Always:**
- The screen is a discovered route: a new `*.route.tsx` under `web/src/features/` exporting `route` (story 2.8). `App.tsx`, `web/src/routes/registry.ts`, and `web/src/routes/navigation.ts` are **read-only** — adding the file is the whole registration, and the existing `childOpen` logic then gives `/add` the `← Back` control automatically.
- Progress is the mechanism that already exists. `useJobEvents`, `StageProgress`, `stageStyles`, and the `rows.ts` helpers are imported from `@/features/meetings/` — the same cross-feature reuse `features/speakers/SpeakerNaming.tsx:18-19` already makes. No second SSE subscription mechanism, no second stage-bar renderer, no polling of `/meetings` for stage progress.
- The three acquisition calls go through the **generated client** (`startAcquisition`, `probeAcquisition`, `getAcquisition` in `@/client/sdk.gen`). No hand-rolled `fetch` transport for them — unlike `features/threads/threadsApi.ts`, which exists only because its operations were not generated yet.
- **Nothing is written before Submit.** The shape check is offline; the probe calls `POST /acquisitions/probe`, which story 6.4 guarantees mints no drop, starts no process, and writes no state.
- **Asynchronous ownership** (EXPERIENCE.md · Interaction Model): every probe carries a monotonically increasing generation plus the normalized URL that started it. A response may update visible state only when both still equal the control's current state; late success and late failure are discarded, and a superseded request is aborted.
- **Refusals are fields, never prose** (AD-18). A refusal box renders `rule` in mono, then `detail`, then `→ remediation`, read from the RFC 9457 body's extension members that `server/meetingminer/api/acquisitions.py:_refusal_problem` sets, or from `GET /acquisitions/{id}`'s `refusal` object. Nothing is paraphrased, invented, or parsed out of the log tail. `role="alert"`, in place, never a toast, dismissed only by changing the input that caused it.
- A refusal the api did **not** issue is never dressed as one: the offline shape check renders muted helper text under the field (not a refusal box), and an unreachable api renders a transport sentence naming `API_BASE`.
- Polling: `GET /acquisitions/{id}` every 2s while `queued | running`, stopped on `posted | failed` and on unmount. A failed poll keeps the stepper's last state, renders `Cannot reach the api at {API_BASE}: {message}.` with a **Retry** that resumes polling, and infers nothing about the acquisition.
- The form locks (fields read-only, Submit disabled) from Submit until `posted | failed`; it unlocks on `failed`. No Cancel is offered — story 6.4 defines none.
- The four source tabs are a real `role="tablist"` with arrow-key movement, `aria-selected`, `aria-controls`, and roving `tabindex`; switching tabs never submits and never clears the other tab's state.
- Every element rendered is backed by a field the api serves. A count, title, duration, or caption line the api did not send does not render.

**Block If:**
- Landing this requires a change to `server/`, to `web/src/client/`, or to `App.tsx`/`routes/` — those are out of this story's boundary and two builders are in flight (6.4a on the server upload endpoint, 10.2a on `web/src/features/threads/`). Record the gap in Design Notes and stay inside the boundary.

**Never:**
- No server change, no `make client` regeneration, no hand-edit of `web/src/client/`.
- No file input, drop zone, upload progress, dialect select, or `title`/`startedAt` fields — those are stories 6.5a and 6.4a. The three file tabs render their chrome and one honest sentence naming what they wait on.
- No toast, no modal (Add-meeting is a route so Back and deep links work), no disabled control without a sentence saying why, no autoplay.
- Never start the shared worker or api, never run `make evals-run`, never call a paid model.
- No edit to `docs/backlog.md`, `docs/architecture.md`, or `docs/project-record.md` (epic-level, and in-flight elsewhere).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Idle | `/add` opened | YouTube tab selected, URL field focused, Submit disabled with a stated reason; no request made | No error expected |
| Shape-invalid URL | `https://vimeo.com/12345` | Muted helper `Not a YouTube video URL — paste a watch or youtu.be link.`; Submit disabled; **no probe sent** | Not a refusal box — nothing was refused |
| Playlist URL | `https://www.youtube.com/playlist?list=PL9` | Muted helper `Playlist URLs are not accepted on this tab — paste one video's watch link.`; Submit disabled; no probe sent | Not a refusal box (F-19) |
| Shape-valid shapes | `youtube.com/watch?v=<11>` (extra query ok), `youtu.be/<11>`, `youtube.com/shorts/<11>`, any `*.youtube.com`, http/https only | Accepted by the shape check; probe scheduled 600 ms later | Mirrors `server/meetingminer/youtube.py:video_id_from_url` |
| Probe running | shape check just passed | Muted mono `Probing…`; Submit disabled; `aria-busy` on the field group | Editing the URL supersedes and aborts the request |
| Probe answered | `{title, durationMs, captions:{kind,language}, sourceId}` | Mono line `<title> · <duration> · captions: <kind> <language> · <sourceId>`; Submit enabled; note `Nothing has been written.` | No error expected |
| Probe answered, no captions | `captions: null` | Same line with `captions: none` — a recording-only drop is valid, not a refusal | No error expected |
| Probe refused | 400/422/503 ProblemDetails with `rule`, `detail`, `remediation` | Refusal box under the field; Submit stays disabled; note `Nothing was sent — the probe answered before submit.` | Rendered verbatim from the body |
| Probe transport failure | fetch rejects | `Cannot reach the api at {API_BASE}: {message}.` under the field with Retry; Submit disabled | Not styled as a rule refusal |
| Submit accepted | `POST /acquisitions` → 202 `{acquisitionId, sourceId, status}` | Form locks; stepper appears with **launch** done; polling starts | No error expected |
| Submit refused, 409 | ProblemDetails `type: …acquisition-in-progress` with `acquisitionId`, `sourceId` | Refusal box under Submit with the api's sentence and an **Open the running acquisition** control that attaches the stepper to that `acquisitionId` | Form stays unlocked |
| Submit refused, 4xx/5xx | any other ProblemDetails | Refusal box under Submit from `rule`/`detail`/`remediation`, falling back to `problemMessage()` when the body carries no `rule` | Form stays unlocked |
| Running | poll → `status: running`, `logTail: [...]` | **launch** done, **running** amber pulsing; log tail region, newest last, `aria-live="off"`, with **Copy log** | No error expected |
| Posted, created | poll → `posted`, `result: created`, `jobId`, `meetingId`, `source` | **posted** emerald with `posted — job <8 chars>…`; polling stops; `/jobs/events` subscribed for that job; meeting card renders with its stage bars | No error expected |
| Posted, exists | poll → `posted`, `result: exists` | Same, plus the note `Already in the corpus — nothing downloaded.` | No error expected |
| Failed | poll → `failed`, `refusal{rule,detail,remediation}` | Third bar **failed** rose, **ingesting** stays queued; refusal box; form unlocks; the log tail stays | Never read from the log tail |
| Poll transport failure | `GET /acquisitions/{id}` rejects | Stepper keeps its last state; `Cannot reach the api at {API_BASE}: {message}.` with Retry | Nothing inferred about the acquisition |
| Ingesting | job events arrive for the posted `jobId` | The meeting card's stage bars patch live via `applyEvent`; **ingesting** tracks the job; `Open` enables when `viewable` | Blocked reason rendered from `blockedReason(row)` |
| Meeting row not yet minted | `posted` but `meetingId: null` | Stepper shows posted; the card region says the worker has not minted the meeting row yet — no half-row invented | No error expected |
| File tab selected | Local files / Zoom export / Teams export | Panel swaps, one sentence naming that the tab needs the upload endpoint; no Submit on that panel; the YouTube tab's state survives a switch away and back | No error expected |

</intent-contract>

## Code Map

**Consumed, read-only — the api surface (story 6.4, already generated):**
- `web/src/client/sdk.gen.ts:142,156,170` -- `startAcquisition`, `probeAcquisition`, `getAcquisition`. Call these; do not hand-roll transport.
- `web/src/client/types.gen.ts:10,28,56,74` -- `AcquisitionAccepted`, `AcquisitionRefusal`, `AcquisitionSource`, `AcquisitionStatus`. `AcquisitionStatus.logTail` is always present (an empty list means "nothing logged yet"); `result`, `jobId`, `meetingId`, `source`, `refusal` are nullable.
- `web/src/client/types.gen.ts:1849` -- `ProblemDetails` has `[key: string]: unknown`, so the `rule` and `remediation` extension members survive typing.
- `web/src/client/client/client.gen.ts:186-218` -- on a non-2xx the client returns `{ error: <parsed JSON body> }`; on a transport failure `error` is the thrown `Error`. The two must be told apart before rendering.
- `server/meetingminer/api/acquisitions.py:_refusal_problem` (rule → status via `acquisitions.PROBLEM_STATUS`, `rule`/`remediation` as extension members), `:start_acquisition` (202, and the 409 carrying `acquisitionId`/`sourceId`), `:get_acquisition` (status file + resolved `meetingId` + bounded log tail). **Read-only evidence** for what the client may rely on.
- `server/meetingminer/youtube.py:214-250` `video_id_from_url` -- the exact accepted URL shapes the client shape check must mirror; `:114` `VIDEO_ID_PATTERN = [A-Za-z0-9_-]{11}`. `:265` `playlist_id_from_url` is why a `playlist?list=` URL gets its own sentence.
- `server/meetingminer/acquisitions.py:96` `STATUSES = ("queued","running","posted","failed")`.

**Reused, read-only — the progress mechanism:**
- `web/src/features/meetings/useJobEvents.ts` -- one `/jobs/events` connection per component, `{onEvent, onResync, onAlive}`, returns `ConnectionState`. Subscribed only after `posted`.
- `web/src/features/meetings/StageProgress.tsx` -- `StageProgress`, `StageLegend`. The per-stage bars, verbatim.
- `web/src/features/meetings/stageStyles.ts` -- `BAR_CLASS`, `LABEL_CLASS`, `asStageStatus`. The stepper's bars use these same values, which is what DESIGN.md · Colors · States requires.
- `web/src/features/meetings/rows.ts` -- `applyEvent`, `blockedReason`, `meetingLabel`, `startedLabel`, `durationLabel`, `countParts`.
- `web/src/features/speakers/SpeakerNaming.tsx:18-19` -- **precedent** that a sibling feature imports `useJobEvents` and `stageStyles` from `features/meetings/`.
- `web/src/lib/problems.ts` -- `problemType`, `problemMessage`. Extended use only; the file itself is not edited.
- `web/src/lib/api.ts` -- `API_BASE`, named in every transport sentence.
- `web/src/lib/media.ts` -- `mediaUrl` for the poster.
- `web/src/components/ui/button.tsx` -- `Button`, `buttonVariants`.

**Read-only shell, must not be edited:**
- `web/src/App.tsx:290-299` (the chrome link already pointing at `/add`), `:207-209` (the `n` shortcut already navigating there), `:130-135` (`childOpen`), `:352-362` (`<Outlet />`).
- `web/src/routes/registry.ts` -- globs `../features/**/*.route.tsx`; validates `path`, `element`, `order`.
- `web/src/features/settings/SettingsPage.route.tsx` -- the two-line route-file pattern to copy.

**Existing tests that touch `/add` and must keep passing:**
- `web/src/shellPlacement.test.tsx:216` (the chrome link's href) and its "resolves the Threads route rather than the catch-all" case — the model for the new route-resolution pin.
- `web/src/globalShortcuts.ruling.test.tsx:74` -- `n` navigates to `/add`; the screen will now actually mount there, so **mount must issue no request**.
- `web/src/features/moments/MomentsFeedStates.review.test.tsx:121` -- the empty-corpus Add-meeting link.

**Design authority:**
- `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md:93` (acquisition stepper), `:99` (refusal box), `:131-142` (every Add-meeting state row), `:170-172` (banned patterns, asynchronous ownership), `:212` (focus order), `:298-307` (the data contract), `:370-383` (Flows 1 and 2).
- `.../DESIGN.md:292-315` (`refusal-box`, `source-tab`, `acquisition-stepper` tokens), `:440` (acquisition state colors; `posted` is emerald), `:616` (`form-max-width` 720px, centered), `:646-648`.
- `.../mockups/add-meeting-youtube.html`, `.../mockups/add-meeting-refusal.html` -- the rendered states.

## Tasks & Acceptance

**Execution:**
- `web/src/features/acquisitions/youtubeUrl.ts` -- new: `classifyYoutubeUrl(raw)` returning `{kind:'valid', videoId, normalized}` | `{kind:'playlist'}` | `{kind:'invalid'}`, mirroring `video_id_from_url`'s accepted shapes; plus `durationLabel`-style helpers only if not already available from `rows.ts`. Pure, so the whole shape-check matrix is a unit test with no DOM.
- `web/src/features/acquisitions/acquisitions.ts` -- new: `refusalOf(error)` → `{rule, detail, remediation} | null` from a ProblemDetails body; `failureOf(error)` → a discriminated `{kind:'refusal'|'problem'|'transport'}` that tells a parsed problem body from a thrown transport error and builds the `Cannot reach the api at {API_BASE}: …` sentence; `stepperSteps(status, jobStatus)` → the four labelled steps with their `RenderedStageStatus`. Pure and unit-tested.
- `web/src/features/acquisitions/RefusalBox.tsx` -- new: `role="alert"`, rule in mono, detail, `→ remediation`, optional action slot (the 409's "Open the running acquisition").
- `web/src/features/acquisitions/AcquisitionStepper.tsx` -- new: the four bars using `BAR_CLASS`/`LABEL_CLASS`, each `role="img"` named `<step> <state>`; the log-tail region (`aria-live="off"`, newest last, follows only while scrolled to bottom) with **Copy log**.
- `web/src/features/acquisitions/useAcquisitionStatus.ts` -- new: poll `getAcquisition` every 2s while `queued|running`, stop on `posted|failed` and on unmount, expose `{status, failure, retry}` and never overwrite a newer generation.
- `web/src/features/acquisitions/AddMeeting.tsx` -- new: the screen — tablist, the YouTube panel (field, shape check, debounced generation-owned probe, Submit), the stepper, the refusal boxes, and the posted meeting card driven by `useJobEvents` + `applyEvent` + `StageProgress`.
- `web/src/features/acquisitions/AddMeeting.route.tsx` -- new: `export const route: RouteModule = { path: '/add', element: <AddMeeting /> }`.
- `web/src/features/acquisitions/youtubeUrl.test.ts` -- new: the shape-check matrix rows, including every accepted shape and the playlist case.
- `web/src/features/acquisitions/acquisitions.test.ts` -- new: `refusalOf`/`failureOf`/`stepperSteps`, including a transport `Error` versus a problem body.
- `web/src/features/acquisitions/AddMeeting.test.tsx` -- new: the component matrix — idle, shape-invalid, playlist, probing, probe answered, probe refused, submit accepted, 409, running, posted+created, posted+exists, failed, poll lost + Retry, tab switching keeps state.
- `web/src/features/acquisitions/AddMeetingRoute.test.tsx` -- new: rendering `<App />` at `/add` resolves the Add-meeting screen rather than the front-door catch-all, and mount issues no request.

**Acceptance Criteria:**
- Given the app is at any route, when **Add meeting** is clicked, then the Add-meeting screen renders at `/add` under the existing chrome with a `← Back` control, and the front-door feed is not what appears.
- Given the Add-meeting screen mounts, when no URL has been typed, then no network request has been made and Submit is disabled with a visible sentence saying why.
- Given a shape-valid URL is typed, when 600 ms pass, then exactly one `POST /acquisitions/probe` is sent for the current normalized URL, and a URL edited during the probe supersedes it so the earlier response never updates the screen.
- Given an acquisition reaches `posted`, when job events arrive for its `jobId`, then the meeting card's stage bars patch live without a reload and without a second SSE mechanism, and `Open` enables exactly when the api reports `viewable`.
- Given any refusal — probe, submit, or a failed acquisition — when it renders, then the rule name, the detail, and the remediation shown are the api's own strings, and the screen states nothing about the acquisition that the api did not report.
- Given `make web-test`, `make lint`, and `make typecheck`, when run, then all pass and the pre-existing `/add` tests (`shellPlacement`, `globalShortcuts.ruling`, `MomentsFeedStates.review`) still pass unchanged.

## Spec Change Log

## Review Triage Log

## Design Notes

**Why the shape check is client-side and duplicated.** `video_id_from_url` is the authority, but the probe is a network round trip and the design requires Submit to stay disabled with an explanation *before* one is spent (EXPERIENCE.md:132). The client check therefore mirrors the server's accepted shapes exactly and is pinned by a table test naming the server function as its source; it never invents a refusal the server would not make, and anything it accepts still faces the probe.

**Why `posted` hands over rather than continuing to poll.** `GET /acquisitions/{id}` stops being informative once the drop is posted — from acquisition's point of view it is done, which is why DESIGN.md:440 colours `posted` emerald. The remaining truth lives on the job, and the job already streams. Continuing to poll would be the second progress mechanism this story is told not to build.

**Why the three file tabs render now.** The AC requires the YouTube tab "inside the tab chrome the story 6.1 design defines for all four sources". Building the tablist, its keyboard model, and its per-tab state preservation now means story 6.5a fills three panels and changes nothing else. The panels stay selectable rather than disabled so the keyboard model is complete and testable, and each states plainly what it waits on rather than showing an inert form.

**Stepper step 4.** `ingesting` is not an acquisition status — it is the job. Its bar reads `queued` until the posted job's first event, `running` while the job runs, `done` when the job's stages have settled and the api reports `viewable`, and `failed` when the job fails. On a `failed` acquisition it stays `queued`, because ingestion never started (mockup `add-meeting-refusal.html`, section 1).

## Verification

**Commands:**
- `make web-test` -- expected: the full vitest suite passes, including the new `features/acquisitions/` files and the three pre-existing `/add` tests.
- `make lint` -- expected: ruff clean (no server files change, so this must be unchanged from baseline).
- `make typecheck` -- expected: mypy clean, unchanged from baseline.
- `pnpm --dir web run lint` -- expected: oxlint clean over the new files.
- `pnpm --dir web run build` -- expected: `tsc -b` type-checks the new TSX against the generated client types, then vite builds.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-5` -- expected: no overlapping changed regions with the in-flight 6.4a and 10.2a branches.
