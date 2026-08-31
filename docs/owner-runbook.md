# Owner runbook — Epics 6–11

The steps only the owner can do, in the order they block builders. Everything
else in `_bmad-output/planning-artifacts/epics.md` (Epics 6–11) is builder
work. Source: the sprint change proposal of 2026-08-29 and its two addenda;
the handoff line there reads "Owner: approve; choose the videos; name
speakers on the featured meetings; record."

Work the phases top to bottom. A phase's steps can be done in any order.
Tick the box, and where a step asks for a value, write it in the
**Decision record** at the end so a builder can read it without asking.

## Phase 0 — Two decisions that reorder the plan

Settle these before any story past Epic 11 is dispatched. Both are choices,
not work; together they decide whether Epic 10 and the upload path are on the
critical path or trail the recording.

- [ ] **0.1 What the walkthrough shows.** Story 9.2's script today is: add a
      YouTube meeting → watch it ingest → dense meeting view → name a speaker →
      replay a moment → search → pick a model → ask → cited answer → open the
      cited moment → YouTube deep link → status/config. It does not open
      Moments or Threads (Epic 10) and does not upload a Zoom or Teams export
      (6.3, 6.4 upload half, 6.5 file tabs, 7.5). Choose one:
      - **A. Keep the script.** Epic 10 and the upload slices move after 9;
        order becomes 11 → 6 (URL path only) → 7 → 8 → 9 → 10 → upload slices.
      - **B. Grow the script** to open on Moments and zoom one Thread. Order
        stays 11 → 6 → 10 → 7 → 8 → 9, and 9.1's corpus must include a
        recurring series (step 1.2).
- [ ] **0.2 Story granularity.** The assessment of 2026-08-29 proposed splitting
      11.2, 6.1, 6.2, 6.4, 6.5, 8.2, 10.2, 10.6 and merging 7.5→7.2/7.4 and
      10.7→10.5. Accept, reject, or accept in part. Accepted changes are
      written into `epics.md` and `sprint-status.yaml` is regenerated.

## Phase 1 — Corpus selection (blocks 6.2's first real run and 9.1)

- [ ] **1.1 List the YouTube videos.** Public watch URLs. Constraints from
      story 6.2: a video stream must exist, duration under the configured cap
      (default 180 minutes), English captions preferred (manual or
      auto-generated both work). Conference talks with screen shares and
      recorded community meetings are the intended kinds. Every video becomes
      `corpus: real` and is never an eval subject.
- [ ] **1.2 Pick at least one recurring series** if 0.1 = B — a playlist of a
      community's weekly meeting, so Threads (Epic 10) has more than one
      meeting per topic. Story 6.2's `--playlist` mints one drop per entry.
- [ ] **1.3 Mark the featured meetings** — the two or three the walkthrough
      opens. These are the ones whose speakers get named (step 4.2).
- [ ] **1.4 Record the list** in the Decision record. URLs, playlist URL, and
      which are featured.

## Phase 2 — Exports handoff (blocks 6.3, 7.5, and the upload half of 6.4/6.5)

Skip this phase entirely if 0.1 = A and you defer the upload path.

- [ ] **2.1 Teams recordings with transcripts.** The archive copy of the puller
      (`/Users/devopsterus/current/pull_transcript` on this machine) already
      produces drops for Teams meetings; those enter through
      `make ingest-drop DROP=<dir>` today and need nothing from this epic.
      Only if you want the *upload* tab exercised with a raw Teams export
      (`.txt` with speakers plus a speaker-less `.vtt`) put one pair in the
      handoff directory (2.3).
- [ ] **2.2 Zoom calls with transcripts.** Zoom's export is a recording (`.mp4`)
      plus a `.vtt` whose cues read `Name: text`. Story 6.3 converts that
      dialect; a dialect is always declared, never inferred, so keep Zoom and
      Teams files apart.
- [ ] **2.3 Put the files in one directory outside the repo**, absolute path,
      one subdirectory per meeting, and record the path in the Decision
      record. Nothing under `MM_DROPS_ROOT` — that root is write-once and
      minted into, never copied into.
- [ ] **2.4 Confirm every recording is unencumbered.** The 2026-08-22 purge
      removed the prior client corpus; nothing from that set returns.

## Phase 3 — Credentials and hosts (blocks 7.1)

- [ ] **3.1 Hugging Face token for `pyannote.audio`.** Story 7.1's option A
      runs pyannote in-process on this machine. The models are gated: sign in
      at huggingface.co, accept the terms on `pyannote/speaker-diarization-3.1`
      and `pyannote/segmentation-3.0`, create a read token, and add it to
      `.env` under the variable name story 7.1 declares in `.env.example`
      (`.env` is gitignored; never commit it). Until 7.1 lands there is no
      variable to set — have the token ready.
- [ ] **3.2 LAN GPU host (option B, only if A is too slow).** 7.1 measures
      pyannote on a 60-minute recording first. If the builder reports it too
      slow, standing up NeMo diarization as an endpoint on the LAN GPU host
      (the VM that already serves parakeet) is yours; the builder binds it
      through `config.yaml` `diarizer.engine`.
- [ ] **3.3 Provider keys.** Both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in
      `.env` were verified valid 2026-08-29. Nothing to do unless one is
      rotated.

## Phase 4 — Ops checklist (before any story; repeat before 9.1 and 9.2)

```
open -a OrbStack          # Docker runtime; with it off, 665 server tests skip silently
docker info               # must answer
make up                   # 3 dev stores + 2 test twins, migrate, api :8000, worker, web :5173
curl -s http://127.0.0.1:8000/status | jq   # every component ok; extraction binding is local
open http://127.0.0.1:5173                   # home shows the corpus; replay one moment
```

- [ ] **4.1** All of the above green. `/status` also shows key validity per
      provider once 8.2 lands; before that, confirm keys by a single chat
      turn.
- [ ] **4.2** `ollama list` shows `qwen3-embedding:0.6b` (search dies without
      it) and the extraction model `config.yaml` binds (`gpt-oss:120b` as of
      2026-08-22).

## Phase 5 — Inside story 9.1: Demo corpus (human steps)

Do these after 6.2/6.5 (acquire), 7.4 (name), and the existing approval UI
are available. Each is a screen, not a command.

- [ ] **5.1 Acquire each meeting from Phase 1.** Through the Add-meeting flow
      (`http://127.0.0.1:5173`, once 6.5 lands) or, while 6.5 is in flight,
      `make youtube-drop URL=<url>` per video and
      `make youtube-drop URL=<playlist-url> --playlist` for the series (exact
      flag form per story 6.2 when it lands). A repeat run answers `exists`
      and downloads nothing. Watch each meeting reach every stage on the home
      card; a stage that refuses names its rule — report it, do not retry
      blindly.
- [ ] **5.2 Name the speakers on the featured meetings.** Open
      `/meetings/<id>` → speakers panel (story 7.4). For each `SPEAKER_NN`
      tag: play the three sample clips, then pick an existing participant,
      type a new name, or choose **unresolved**. Suggestions are never
      auto-applied; the machine never guesses — every name here is your
      call. The rerun (`align → moments → extract`) re-attributes the
      transcript; moment ids and citations survive.
- [ ] **5.3 Approve and publish artifacts on several moments.** Open a
      moment (`/moments/<id>`), review the extracted ADRs and action items,
      approve the ones that are right, publish. Approval is deliberately a
      human gate (story 4.3); published documents land in `MM_PUBLISH_ROOT`.
      Aim for enough that the walkthrough's cited answer can cite a
      published artifact.
- [ ] **5.4 Authorize paid calls.** Chat and judge roles are paid
      (`openai/gpt-5.2`; Anthropic selectable once Epic 8 lands). The
      2026-08-29 authorization covers walkthrough-scale chat turns. Any
      corpus-wide paid batch is announced to you first — answer it; nothing
      paid starts on silence.
- [ ] **5.5 Exercise the two backlog items on the demo path**: re-submit a
      chat question mid-answer (B-12) and leave the app idle on a meeting
      card for several minutes (B-11). They are fixed only if they
      reproduce; note what you saw.

## Phase 6 — Story 9.2: Five-minute walkthrough (fully yours)

- [ ] **6.1 Script.** A builder drafts it from the 3-minute capstone script
      (`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/demo/demo-script.md`,
      local only) using the beat list in 0.1. It is committed under `docs/`.
      Fill in the blanks it leaves: the rehearsed search query (must return a
      hit **with a screenshot**), the featured meeting, the question for the
      cited answer, the model to pick.
- [ ] **6.2 Rehearse once, end to end**, on the demo machine, with audio
      audible. Time each beat; the capstone script's discipline applies —
      know which beats are the sacrifice if you run long.
- [ ] **6.3 Pre-flight 30 minutes before recording.** Phase 4 again; browser
      zoomed for legibility; every other tab closed; Do Not Disturb on.
- [ ] **6.4 Record** (⌘⇧5 or your screen recorder). Store the recording
      **outside git**; record its path in the Decision record. If a screen
      fails during recording, the honesty rule holds: show what exists, do
      not narrate what does not.

## Phase 7 — Sign-offs and small items

- [ ] **7.1 Review story 6.1's design spec** when `bmad-ux` produces it — a
      read, not work. The brief includes the color system you asked for
      ("a bit of color", meaning-bearing, accessible).
- [ ] **7.2 `reference-competitor-meeting-view.png`.** `spec-ui-reimagine`'s
      `reference-ui.md` cites it; the file exists only on the archive server.
      Either restore it beside that companion or say so and the companion is
      reworded without it.

## Decision record

| # | Decision / value | Answer | Date |
|---|---|---|---|
| 0.1 | Walkthrough scope (A keep / B grow) | | |
| 0.2 | Story splits/merges accepted | | |
| 1.1 | YouTube URLs | see **Corpus candidates** below | 2026-08-30 |
| 1.2 | Recurring-series playlist URL | Green Line Extension CMC series on @MetropolitanCouncilMeetings (6 sessions Jun 2025 – Jun 2026) | 2026-08-30 |
| 1.3 | Featured meetings | not yet chosen | |
| 2.3 | Exports handoff directory (absolute path) | | |
| 3.1 | HF token ready (yes/no; never the value) | | |
| 3.2 | LAN GPU host needed (yes/no) | | |
| 6.1 | Rehearsed search query | | |
| 6.1 | Question for the cited answer | | |
| 6.4 | Recording path (outside git) | | |

## Corpus candidates — gathered 2026-08-30, not yet ingested

Two sets, serving different halves of the demo. Every entry below was probed
with `yt-dlp` (metadata only, nothing downloaded): all are available, all carry
English captions, and **all are under the 180-minute cap**, so no config change
is needed.

### Set A — public meetings, for threads and speakers

`https://www.youtube.com/@MetropolitanCouncilMeetings` — 676 videos. A 40-video
sample ran 1–91 minutes, median ~42.

- **Recurring series present**, which is what Epic 10 threads need: the *METRO
  Green Line Extension Corridor Management Committee* appears six times between
  June 2025 and June 2026 — same committee, same project, a year apart, so
  funding/construction/engagement topics genuinely recur across meetings rather
  than producing singleton threads. A Blue Line Extension series and a large
  "PlanIt:" webinar series also exist.
- **Captions are auto-generated, not manual — so they carry no speaker labels.**
  This set is therefore the case that justifies diarization: `/diarize`
  (backlog B-36, landed) supplies `SPEAKER_NN` tags and story 7.3 names them.
  Without it these meetings ingest as unattributed text.
- Committee and Council meetings are multi-speaker; the "PlanIt:" items are
  one- or two-presenter webinars. Prefer the committee meetings when the demo
  needs participants.

`https://www.youtube.com/channel/UCT9EK-ykJu6796jqDPHRNdg` — Waipā District
Council (NZ). A second jurisdiction, and a second recurring committee:

- `53yPfrqbpkE` — Finance & Corporate Committee, Zoom meeting, **104 min**,
  auto-captions.
- *Finance and Corporate Committee Meeting – 10 December 2025*, **111 min** —
  the same committee again, so pairing the two gives cross-meeting thread
  continuity for this council as well.
- Being Zoom recordings, these carry screen-shared reports and documents, which
  exercises the capture path more than a podium-and-slides recording does.

**Two cautions if this channel is ever ingested wholesale rather than
hand-picked:**

1. **One item exceeds the 180-minute cap** — *Plan Change 14 – Hearing,
   6 March 2025* at **384 minutes**. Story 6.2 will refuse it by name and
   story 6.2a's per-entry survival keeps the rest of the run going, so this
   is correct behaviour rather than a failure — but expect it in the outcome
   table rather than being surprised by it. *Private Plan Change 33* at 172
   min sits just under the cap.
2. **Most of the channel is short comms clips** (0–4 min: explainers, drone
   footage, rates videos). Bulk-ingesting would fill the corpus with material
   that has no meeting structure to extract. Prefer a hand-picked list over
   `--playlist` here.

### Set B — recorded software demonstrations, for capture and citation

Seven vendor demos and tutorials, all confirmed available with captions:

| id | min | source | subject |
|---|---:|---|---|
| `RXfQ5xD1tFg` | 35 | Zycus | agentic AI in procurement, live demo |
| `mH4RPo5F-Uw` | 2 | Zycus | supplier onboarding |
| `a5oxfjdoJOg` | 44 | Brockbank Consulting | Salesforce CRM tutorial |
| `ntZbRd-DPII` | 5 | Thrive Media | Salesforce CRM walkthrough |
| `jHzIGGU-Ph0` | 40 | Nick Boardman | Salesforce CRM training |
| `6JuI53YY_6E` | 4 | TechnologyAdvice | Workday demo |
| `VRVSH2yGPE4` | 4 | Workday | navigating Workday HCM |

**This set is on-thesis.** The product's stated purpose is turning *recorded
software demonstrations* into searchable, citable evidence, and these carry
real application UI on screen — which is what the capture → frames → OCR →
screens → moments path was built for, and what makes "every artifact traces to
the video moment that produced it" demonstrable. Set A is talking heads and
slides by comparison.

**Together they cover more than either alone:** Set A demonstrates threads,
topics, speakers and cross-meeting search; Set B demonstrates screen capture,
screenshots and moment-level citation.

**One note on character, not a blocker:** Set B is commercial vendor content
rather than public record. Nothing is redistributed — only locally derived
transcripts and screenshots — but it is worth a moment's thought if the
recorded walkthrough is published beyond the cohort.

## What blocks what

| Owner step | Story it unblocks |
|---|---|
| 0.1 | Sequencing of Epic 10 and the upload slices |
| 0.2 | Regeneration of `sprint-status.yaml` |
| 1.1–1.4 | 6.2 first real run; 9.1 |
| 2.1–2.4 | 6.3, 7.5, 6.4/6.5 upload half |
| 3.1 | 7.1 |
| 3.2 | 7.1 only if option A is too slow |
| 4.x | Every story's ops checklist; 9.1; 9.2 |
| 5.1–5.5 | 9.1 done |
| 6.1–6.4 | 9.2 done |
