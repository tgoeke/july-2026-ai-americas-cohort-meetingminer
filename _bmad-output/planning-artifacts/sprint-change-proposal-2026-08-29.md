# Sprint Change Proposal — 2026-08-29 (revision 2)

Status: APPROVED by the owner 2026-08-29 ("yes - approved"). Mode: batch. Revision 2 replaces the
first draft after the owner's answers: no deadline; a full UI experience is
required; sources are YouTube, past Teams recordings, and Zoom calls with
transcripts; both provider keys are valid and the model is to be selectable in
the UI; speaker attribution for YouTube content is assigned after the fact.

## 1. Issue summary

**Trigger.** The AI engineering cohort closes with a recorded ~five-minute
walkthrough of MeetingMiner. The application is not running, the corpus holds
only the two scripted demos, and the planned sandbox corpus does not exist.
Owner direction (2026-08-29, recorded in the spec memlog):

1. Build the corpus from published YouTube videos (conference talks with
   screen shares, recorded community meetings), past Teams recordings with
   transcripts, and Zoom calls with transcripts. Leave every source option open.
2. The acquisition flow is a first-class UI experience — not a CLI with a UI
   afterthought. There is no deadline.
3. Both OpenAI and Anthropic keys are valid; either provider may be used; the
   model must be a configurable option in the UI.
4. YouTube content gets speaker attribution after the fact: the system finds
   who spoke when; a human assigns names.

**Category.** New requirements from the stakeholder plus a corpus-source
change. Nothing delivered is being reversed.

**Evidence.**
- Tracking: 38/38 stories done, 5/5 epics done, no forward epic
  (`sprint-status.yaml`, regenerated 2026-08-29).
- Corpus: `demo-001`, `demo-002` only; no `evals/runs/` anywhere.
- Contract already anticipates the source: `docs/architecture.md` AD-1
  ("… future YouTube — lands as a source drop"); `meetingminer.mintdrop`
  (story 2-1b) is the local-file producer to extend.
- Seams verified in the tree 2026-08-29: `Diarizer` port with `noop` bundled
  and `pyannote` named-not-vendored (`adapters/diarize/`); diarization turns
  already stamped onto STT segments as `SPEAKER_NN`
  (`stages/transcribe.py:74-105`); participants resolved only through the
  api-owned `participant_alias` table (`stages/align.py:376-390`, migration
  0005); the VTT parser is speaker-less by contract while the legacy
  `<Name> | MM:SS` `.txt` format is the trusted speaker-bearing input
  (`pipeline/transcripts.py:13-16`); `yt-dlp 2026.07.04`, `ffmpeg`, `ffprobe`
  installed.
- Demo path last verified 2026-08-22 on real data (`demo-readiness`,
  break-fix `884404f`).

## 2. Impact analysis

**Epics.** Epics 1–5 complete and unchanged. Four new epics, each delivering
user value on its own, sequenced by dependency: acquisition → speakers →
model selection → close-out. No rollback, no resequencing of delivered work.

**Requirements (SPEC kernel / PRD role).** CAP-1 gains sources; CAP-2's
participants gain a human-assignment path; CAP-3/CAP-5 gain a model selector.
The spec's sandbox-corpus premise is superseded (memlog 2026-08-29).

**Architecture.**
- *No change* for acquisition: producers emit drops and call `POST /ingests`
  (AD-1, AD-14). Zoom transcripts are converted at acquisition into the
  trusted `.txt` speaker format plus `.vtt` timing — the pipeline contract and
  the schema stay as they are. A UI-initiated acquisition is *launched* by the
  api as a separate host process and enters through the same door (AD-11: no
  pipeline work in the api process).
- *No change* for speakers: diarization is evidence the worker writes
  (turns tagged `SPEAKER_NN`); assignment is curation the api writes as
  `participant_alias` rows (AD-5); a re-run of `align → moments → extract`
  re-attributes segments while moment ids survive because identity keys on
  the provided cue timing (AD-13). Extract's rerun replaces drafts only.
- *One amendment* — **AD-10.** Today `config.yaml` is the only binding source
  and the UI states "edit the file and restart". Proposed wording: *"A single
  versioned `config.yaml` declares every adapter binding, model, threshold,
  and endpoint, and — for the LLM roles — the catalog of bindings a user may
  choose between plus the default. A user's selection is user-declared data
  (AD-5): persisted in Postgres by the api, resolved at call time by api and
  worker, recorded in every eval run's config snapshot beside the file
  values. Nothing outside the catalog can be selected, and no selection is a
  fallback: a failing binding surfaces as an error."* Secrets never serialize;
  keys stay in `.env`.

**UX.** Three new flows and one affordance, designed before they are built
(story 6.1 is a UX design spec): Add-meeting (URL / local files / Zoom / Teams
drop), Speaker naming, Model selection; "Open on YouTube at this moment" on
moments and citations.

**Other artifacts.**
- `config.yaml`: extraction prompts say "Microsoft Teams meeting transcript";
  generalize wording for talks and Zoom calls (no parser impact — the tables
  and IDs are the contract, not the preamble). Chat comment about the revoked
  key is stale; replaced by the catalog.
- `docs/README.md`: acquisition sections for YouTube, Zoom, local files.
  `docs/project-record.md`: entries for epics 6–9 as they land.
  `docs/architecture.md`: AD-10 amendment when Epic 8 lands.
- `docs/backlog.md`: B-12 (chat re-submit abort) and B-11 (idle SSE stream)
  are verified on the demo path in 9.1; B-27 (tracked puller lacks the
  participant-graph producer) is unaffected — Teams drops still come from the
  archive copy.
- Eval harness: new sources are `corpus: real`, never eval subjects.
- Contract of record: the committed `docs/` tree; the BMad spec folder is the
  process record (local, ignored). Requirements land in `epics.md` and `docs/`.

## 3. Recommended approach

**Direct adjustment** — four new epics on top of the delivered system; no
rollback; no MVP reduction. Effort: large in total, but every story is
independently shippable and the order is forced by dependency, not by a date.
Risk: low for acquisition and demo; medium for diarization (engine choice and
speed are measured, not assumed) and for the AD-10 amendment (touches api,
worker, status page, eval snapshot).

Alternatives considered: Teams sandbox corpus (deferred, not rejected — it
becomes one more source when it exists); hand-minting downloads with
`mint-drop` (works today; kept as the fallback path and as the
"local files" tab's engine).

## 4. Detailed change proposals

### 4.1 `epics.md` — requirements added

```
FR33: User can acquire a published YouTube video by URL: the acquisition tool
      downloads the browser-playable MP4 and the caption track (manual
      captions preferred, auto-generated as fallback, VTT), finalizes a
      write-once drop — sourceId youtube:<videoId>, corpus real, startedAt
      from upload date (day) or release time (second), provenance carrying
      the watch URL, channel, duration, yt-dlp version, format — and calls
      POST /ingests; a repeat run reports `exists` without downloading
      (CAP-1, AD-1, AD-14, AD-17)
FR34: User can add a meeting from the web app: paste a YouTube URL, or supply
      a recording and/or transcript files (Teams .txt/.vtt, Zoom .vtt); the
      api validates, launches the acquisition tool as a separate host process,
      answers 202 with an acquisition id, and the meeting appears with live
      stage progress once the drop is posted (AD-11, AD-14)
FR35: A Zoom transcript (.vtt with `Name: text` cues) is converted at
      acquisition into the trusted speaker-attributed .txt format plus .vtt
      timing, recorded in provenance as `transcriptDialect: zoom`; the
      pipeline contract is unchanged (AD-1, AD-13)
FR36: The transcribe stage can bind a real diarizer through the existing
      Diarizer port; turns are stored as recording-local `SPEAKER_NN` tags
      on STT segments and surfaced per meeting with talk time and sample
      offsets; no tag is ever resolved to a person by the machine (AD-8,
      AD-13, never-guess)
FR37: User can assign each speaker tag to an existing participant or a new
      name (or leave it unresolved); the assignment is an api-owned alias row
      and triggers align → moments → extract to re-run for that meeting;
      moment ids, citations, and approved/published artifacts survive
      (AD-5, AD-13, AD-14)
FR38: config.yaml declares, per LLM role, a catalog of allowed bindings and a
      default; the api serves the catalog and persists the user's selection;
      chat resolves the selection per request, the worker per job; the
      selection is recorded in every eval snapshot (AD-10 amended)
FR39: The status surface reports key validity per configured provider and
      the active binding per role; a failing selected binding surfaces as a
      named error, never a substitute model (no-silent-fallback)
UX-DR12: A moment from a YouTube meeting offers "Open on YouTube at this
      moment" (sourceDeepLink + offset) beside replay; replay stays primary
UX-DR13: Add-meeting is one flow with source tabs, validation before any
      write, progress from launch through ingestion, and honest failure
      states naming the refusing rule
UX-DR14: Speaker naming shows each tag's talk share, three playable sample
      clips, and the tag-filtered transcript; names are assigned inline;
      unresolved is a first-class choice
UX-DR15: Model selection is available where it matters (the ask box, the
      settings page) and shows provider health beside each choice
```

### 4.2 `epics.md` — epics and stories

**Epic 6: Bring Any Meeting In** — *A user can add a meeting from a YouTube
URL, a Zoom export, a Teams export, or loose files, from the web app, and
watch it become evidence.* FRs: FR33, FR34, FR35, UX-DR12, UX-DR13.

- 6.1 UX design spec for Add-meeting, Speaker naming, Model selection — S.
  `bmad-ux` output adopted as the design companion for 6.x/7.x/8.x UI work;
  base idiom is the dark, data-dense reimagined UI.
- 6.2 YouTube acquisition command — M. `make youtube-drop URL=…` →
  `python -m meetingminer.youtubedrop`. Refuses before writing (URL shape,
  private/removed, no video stream, tools missing, duration over a config
  cap). `find_existing_drop(youtube:<id>)` before any download. Formats
  `bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]` merged to MP4;
  captions en manual→auto→VTT. `mint()` gains `source_id` and extra
  provenance keyword overrides defaulting to today's behaviour; one staging →
  validate → atomic-rename path. `--playlist` enumerates and mints one drop
  per video, sequentially. Tests offline from a recorded `info.json`; one
  network test behind an env flag.
- 6.3 Local-files acquisition with dialect conversion — M. `mint-drop` gains
  `--transcript-dialect zoom|teams-vtt|plain`; Zoom `.vtt` → `.txt` speaker
  format + `.vtt` timing; provenance records the dialect and the conversion.
  Teams archive drops unchanged.
- 6.4 Acquisition launch surface — M. `POST /acquisitions` (url | upload
  session), `GET /acquisitions/{id}` (`queued | running | posted | failed`,
  log tail); the api launches the tool as a detached host process with a
  per-acquisition status file under `.logs/`; uploads stream to a staging
  directory under the drops root; one running acquisition per source id.
  Route via the auto-discovered registry; `make client` here only.
- 6.5 Add-meeting UI — L. The 6.1 design: source tabs, pre-flight validation
  (URL probe / file classification) before submit, acquisition progress →
  meeting card → live stage progress, failure states naming the rule.
- 6.6 YouTube deep links — S. UX-DR12 on moment view, drill-down, chat
  citations; web tests for both hosts and both replay states.
- 6.7 Extraction prompt wording generalized — S. Preamble says "meeting or
  recorded session transcript"; tables and IDs untouched; parser tests pass.

**Epic 7: Know Who Spoke** — *A user can see who spoke when in any recording
and put names to the voices without the system ever guessing.* FRs: FR36,
FR37, UX-DR14.

- 7.1 Diarizer engine behind the port — M. Bind one real engine and measure
  on a 60-minute video: (A) `pyannote.audio` in-process on this machine (HF
  token in `.env`), or (B) NeMo diarization as an endpoint on the LAN GPU host
  (VM 120 already serves parakeet). Start with A for a self-sufficient demo
  machine; switch to B by config if A is too slow. Config-bound (AD-8);
  `DiarizerError` stays named.
- 7.2 Speaker tags on the wire — S. `GET /meetings/{id}/speakers`: tags,
  talk time, segment counts, three sample offsets each; segments carry their
  tag. Read-only.
- 7.3 Speaker assignment — M. `PUT /meetings/{id}/speakers/{tag}` →
  `participant_alias` row (`speaker:<meetingId>:<tag>` namespace) → re-arm
  `align → moments → extract` for that meeting; moment ids and
  approved/published artifacts survive (test pins it); unresolved is a valid
  state. Extraction reruns replace drafts only.
- 7.4 Speaker naming UI — M. The 6.1 design: clips play through the existing
  Range-correct media route, inline naming with existing-participant
  suggestions (never auto-applied), tag-filtered transcript.
- 7.5 Zoom-supplied speakers through the same path — S. Names from a Zoom
  transcript resolve through the roster like Teams labels; the naming UI
  shows them as already resolved and allows correction.

**Epic 8: Choose the Model** — *A user can pick which model answers and which
extracts, from the catalog the config allows, and see the provider's health
beside the choice.* FRs: FR38, FR39, UX-DR15. Amends AD-10.

- 8.1 AD-10 amendment and binding catalog — M. `config.yaml` schema:
  `llm.roles.<role>.catalog[]` (`binding`, `label`, `provider`) + `default`;
  loader validates that the default is in the catalog; `docs/architecture.md`
  AD-10 text per §2; `project-context.md` policy line updated.
- 8.2 Persisted selection — M. Api-owned `app_setting` table (migration);
  `GET /settings/models`, `PUT /settings/roles/{role}`; chat resolves per
  request, worker per job; eval snapshot records effective bindings; status
  reports active binding + key validity per provider (free endpoints only).
- 8.3 Model picker UI — M. The 6.1 design: selector in the ask box and on the
  settings page; provider health inline; a failing binding shows the named
  error where it happens. Builder loads the `claude-api` reference for exact
  Anthropic model ids and parameters.

**Epic 9: Cohort Close-out** — *The corpus is real, the walkthrough is
recorded.* No new FRs.

- 9.1 Demo corpus — M (wall-clock). Owner-chosen videos through 6.5 (or 6.2
  while 6.5 is in flight); speakers named on the featured meetings (7.4);
  artifacts approved and published on several moments; B-12/B-11 exercised on
  the demo path and fixed only if they reproduce; paid chat calls under the
  2026-08-29 authorization.
- 9.2 Five-minute walkthrough — S. Script from the 3-minute capstone script:
  add a YouTube meeting and watch it ingest → dense meeting view → name a
  speaker → replay a moment → search → pick a model → ask → cited answer →
  open the cited moment → YouTube deep link → status/config. Rehearse, record;
  script committed to `docs/`, recording stored outside git.

### 4.3 Architecture

AD-10 amended as in §2 (Epic 8). AD-1, AD-5, AD-8, AD-11, AD-13, AD-14 are
applied, not changed. Story 6.4's "launch, never run in-process" rule and
story 7.3's "assignment is an alias, attribution is a rerun" rule are recorded
in `docs/project-record.md` when they land.

### 4.4 UX

Story 6.1 produces the design companion; UX-DR12–15 above are its brief.

### 4.5 Spec folder

Not re-derived. The four owner directions are recorded in
`spec-meetingminer/.memlog.md` (2026-08-29). The committed `docs/` tree is the
contract of record.

### 4.6 Tracking

On approval: Epics 6–9 and their stories appended to `epics.md`;
`sprint-status.yaml` regenerated (`bmad-sprint-planning`); new entries
`backlog`; 6.1 and 6.2 set `ready-for-dev` once their story specs exist.

## 5. Implementation handoff

**Scope: Moderate** — backlog reorganization into four new epics plus one
architecture decision amendment (Epic 8), which is named and bounded.

**Ops checklist before any story:** `open -a OrbStack` → `docker info` →
`make up` → `GET /status` all `ok` (worker started; extraction is local) →
home shows the two demos and one moment replays → both provider keys verified
by the status page's free endpoints.

**Order.** 6.1 → 6.2 → 6.4 → 6.5 (6.3, 6.6, 6.7 alongside) → 7.1 → 7.2 → 7.3 →
7.4 → 7.5 → 8.1 → 8.2 → 8.3 → 9.1 → 9.2. One builder per story in its own
worktree; `bmad-code-review` by an independent session before each lands
(B-20). Paid calls: chat/judge under the 2026-08-29 authorization; any
corpus-wide paid batch announced first.

**Handoff.** Owner: approve; choose the videos; name speakers on the featured
meetings; record. `bmad-ux`: 6.1. `bmad-create-epics-and-stories` or this
session: write epics 6–9 into `epics.md`. `bmad-sprint-planning`: regenerate.
`bmad-build` + `bmad-code-review`: stories in order. `bmad-architecture`:
the AD-10 amendment with 8.1.

**Success criteria.** From the web app, a pasted YouTube URL or a dropped-in
Zoom/Teams export becomes an ingested meeting with live progress and working
replay; speakers in a YouTube meeting can be named and the transcript, graph,
and extractions reflect it without breaking a citation; the answering model
is selectable in the UI from the configured catalog with provider health
shown; the corpus holds the owner's chosen set; the five-minute recording
exists and every screen in it ran against real, unencumbered data.

## Addendum 2026-08-29 (after approval) — Epic 10: Moments & Threads

Owner direction after approval: "the UI needs to be amazing"; two primary views
from earlier prototypes — **Moments** (the most interesting or pressing items
first) and **Threads** (a topic followed across meetings on a timeline that
starts zoomed out and zooms in like Google Earth, details revealed per level).

Impact: the graph has no Topic nodes today (the participant-topic traversal is a
text `CONTAINS` over `Moment.text`), so this is a new epic, not a UI story:
topic extraction through the existing extract path (10.1), threads plus
`Topic`/`Thread` graph nodes and a thread traversal — navigation metadata
outside the publish gate, an AD-4 clarification recorded with the story
(10.2), a level-of-detail timeline API (10.3), a deterministic, explained
moments ranking (10.4), the Moments view (10.5), the zoomable Threads timeline
(10.6), and the front-door recomposition closing B-13 (10.7). FR40–FR43,
UX-DR16–UX-DR18 added; story 6.1's design brief widened to both views.

Revised order: 6 → 10 → 7 → 8 → 9, so the new corpus lands on the new front
door. Corpus selection for 9.1 should include recurring meeting series (a
playlist of a community's weekly meeting) so threads have something to show.
Treated as approved under the owner's 2026-08-29 direction; no separate
sign-off requested.

## Addendum 2 (2026-08-29) — Epic 11 first: Fast, Conflict-Free Test Suite

Owner direction after approval: "tests cause conflicts between builders and
tests take forever to run … I want the next thing built to be a much better
and more efficient test suite." Added as Epic 11 — 11.1 seconds-fast default
suite (B-1: `slow` markers, per-test budget, conftest cleanup), 11.2 per-run
store isolation (per-run Meilisearch prefix, ephemeral per-session Neo4j test
container, no test takes the cross-worktree lock; B-14), 11.3 eval runs own
their namespace, 11.4 ruff/mypy in the fast loop (B-4). NFR19/NFR20 added.

Order is now **11 → 6 → 10 → 7 → 8 → 9**. Story 6.1 (UX design spec) runs in
parallel with Epic 11 because it touches no code. Story 6.2 waits for 11.1 and
11.2 to land: both change `server/tests`, and the owner's no-caveat rule says
sequence rather than coordinate.

## Addendum 3 (2026-08-29) — story re-slicing

Owner accepted the story-size assessment of 2026-08-29. Applied to `epics.md`
and `sprint-status.yaml`; ids are stable, retired ids are not reused:

- Split: 6.2 → 6.2 + 6.2a (playlist); 6.4 → 6.4 (URL launch) + 6.4a (upload
  sessions); 6.5 → 6.5 (URL tab) + 6.5a (file tabs); 8.2 → 8.2 (persisted
  selection) + 8.2a (provider health on status); 10.2 → 10.2 (derivation +
  projection + template) + 10.2a (thread curation) + 10.2b (thread questions
  in chat); 10.6 → 10.6 (bands → meetings → moments) + 10.6a (evidence tier +
  inline replay).
- Merged: 7.5 into 7.2/7.4; 10.7 into 10.5 (now "Moments View and Front
  Door"). Topic-level curation removed from 10.1 (FR41 reworded).
- Simplified: 11.2 is one mechanism — a private stack per worktree including
  test twins; the per-session Neo4j container and Meilisearch index prefix are
  not built. `epic-11-context.md` updated to match.
- Not split: 6.1 — its `bmad-ux` run had already drafted DESIGN.md and
  EXPERIENCE.md across all five flows when the assessment landed.
- Not decided here: whether the 9.2 walkthrough shows Moments/Threads
  (owner runbook step 0.1). Epic order is unchanged until it is.
