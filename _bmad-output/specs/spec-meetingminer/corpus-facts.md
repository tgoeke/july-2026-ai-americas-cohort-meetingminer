# Corpus Facts

Companion to `SPEC.md` (CAP-1, CAP-2). What the real ingestion input actually contains, measured
rather than assumed. Read before building anything that parses a drop, a transcript, or a
participant list — several fields here are already solved upstream and should be lifted, not
rediscovered.

**Measured 2026-08-18** by the parallel spike track. That track designs a different system; only
its measurements are canonical here.

## 1. Inventory

| Measure | Value (re-measured 2026-08-19) | Was (2026-08-18) |
|---|---|---|
| Occurrences pulled locally | 28 | 28 |
| …with a recording | **8** | 8 |
| …transcript-only | **20** | 20 |
| Participant graphs (`org chart.json`) | 28 — one per occurrence | 28 |
| Archive videos indexed | 103 (24.7 GB) | 103 |
| Archive videos **fetched** | **77 `.mp4` on disk** | **0** |
| Archive transcripts fetched | **193 `.vtt`** | 141 |
| Archive design documents | 58 `.docx` | not present |
| Total transcript sources on disk | **221** — 28 occurrence `.txt` + 193 archive `.vtt` | 169 |
| Local video on disk | **19.5 GB across 85 `.mp4`** | ~8 recordings |

**The recovery predicted on 2026-08-18 is happening now.** The archive mirror held 0 videos then; it
holds 77 today, and its index (`_index.json`, generated 2026-08-19T15:00Z) reports 45 downloaded
against 58 still missing of 103 known — the two counts disagree because the fetch is running as this
was measured. Local video went from roughly 8 recordings to 19.5 GB across 85 files, heading toward
the indexed 24.7 GB.

Transcript-only remains the majority of *occurrences* (20 of 28) but is no longer the shape of the
corpus as a whole. Re-measured 2026-08-19 against the live copy at
`/Volumes/nvmepool/mm_current/pull_transcript`.

**These ratios are a dated snapshot moving in the recovery direction, not a property of the corpus.**
Recovering video for the transcript-only backlog is active work in progress inside the
organisation, so the transcript-only share is expected to fall — possibly a long way. Two
consequences follow, and they point in opposite directions:

- **Do not justify the transcript-only path by the ratio.** It is first-class because some meetings
  will *never* have retrievable video — retention expiry (§1), per-recording permission settings,
  and externally-hosted sessions — not because most of them currently don't. If the justification
  rests on the count, the path gets deprioritised exactly as the count falls.
- **Do not size the video path for 8 recordings.** The capture pipeline, the over-capture guardrail
  (`capture-measurements.md`), and storage should be sized against a corpus where most of these
  transcripts eventually acquire ~120-minute recordings. As of 2026-08-19 this is no longer a
  forecast: 77 archive recordings are already on disk and the fetch is still running. The capture
  baselines in `capture-measurements.md` were measured against the original 8, so treat them as a
  sample that the recovered corpus has not yet been checked against.
- **Augmentation is now the dominant ingest path.** Every archive transcript already ingested is a
  meeting whose video is arriving afterwards, which is exactly CAP-1's augment-in-place flow — at
  the scale of the whole mirror rather than a handful of edge cases.

The archive `.vtt` files are speaker-less subtitle tracks (§3), so they yield chunks and topics
but not speaker attribution — they enlarge the searchable corpus without enlarging the
participant graph.

**The video gap is largely recoverable, and closing it is active work.** The 103 archive videos sit
in a SharePoint team site where path-based download already works; only the index step has ever run
against that folder.

**Why the gap exists: a Teams recording lands in the personal OneDrive of whoever hit record.** The
Stream URLs make the ownership explicit (`…-my.sharepoint.com/personal/<employee-number>_corp_com/
Documents/Recordings/…`), and across the 28 occurrences they resolve to **5 distinct owners**:

| Owning OneDrive | Occurrences | With a local `.mp4` |
|---|---|---|
| owner A | 16 | 5 |
| owner B | 8 | 1 |
| owner C | 2 | 2 |
| owner D | 1 | 0 |
| owner E | 1 | 0 |

Two things follow. The gap is **concentrated** — one owner accounts for 16 of 28 occurrences and
holds only 5 of them locally, so most of the backlog is one person's OneDrive, not twenty scattered
problems. And the pattern is **per-recording, not per-owner** (both large owners hold a mix), so it
is a settings change on specific recordings rather than a tenant policy question.

The consequence for planning: recovery is gated on **other people acting on files they own**, so
its timing is not under the project's control. Design for video arriving late and unpredictably —
see the transcript-only note below. Teams retention expires recordings,
so pulling is time-sensitive: a lost recording is a permanent hole, since the transcript survives
and the screens never can.

## 2. Media properties

| | Primary demo | Secondary |
|---|---|---|
| Duration | **7055 s = 117.6 min** | 3692 s = 61.5 min |
| Resolution / size | 1920×1080 / 408 MB | 1920×1080 / 248 MB |
| Frame rate | — | **16 fps**, not 30 |
| Codec / bitrate | h264 | h264, ~540 kbps |
| Audio | **mono** | **mono**, 16 kHz |

Two consequences. Capture is designed against **~120 minutes**, not the earlier 60–90 minute
working bar. And single-channel audio means there is no channel-based speaker separation to
exploit — speaker identity comes from the transcript and the participant graph, which is a
property of the source, not a design choice.

## 3. Transcripts — two lineages

**Teams is the sole go-forward source.** Earlier meetings were also captured by third-party
transcribers, and that dual capture is where the speaker-name discrepancies originate — Teams
itself supplies real `Lastname, Firstname` values. No third-party transcriber is used from here
on, and no two *raw* sources are ever merged.

| | Teams (go-forward) | Third-party (legacy) |
|---|---|---|
| Format | `[m:ss] Lastname, Firstname: text` | `<Name or Speaker N> \| MM:SS` |
| Speakers | real names | sometimes real, sometimes `Speaker 2`, `Speaker 8` |
| Status | source of record | read-only legacy support |

**The legacy parser stays required.** The two NDA demo recordings are the only long videos with
full transcripts — the primary capture-eval assets — and they carry the legacy format. Dropping
the parser strands the eval corpus. Counting the corpus precisely: 29 `.txt` files across 28
occurrence directories; 27 occurrences hold exactly one, and one holds both lineages.

### For story 1.5 — parsing facts already established

- Both lineages are **second-precision**, so the alignment anchor window defaults to **±2 s**, not
  the ±60 s a minute-granularity assumption would imply.
- The long transcript **switches form past the hour** (`08:47` early, `01:57:24` late). Parse by
  field count: 2 fields → `MM:SS`, 3 fields → `HH:MM:SS`. A parser assuming a fixed field count
  mis-reads half the file.
- The legacy NDA file opens with a `<Name> started transcription` preamble line that is **not** a
  speaker block.
- Legacy speaker labels are inconsistent *within one file*: `Blake, Cameron` and `Cameron Blake`,
  `Reed, Avery` and bare `Avery`, bare `Jordan`/`Jamie`, and an unresolvable `Speaker 8`.
  This is the evidence behind the never-guess constraint in `SPEC.md`.
- Occurrence filenames are all prefixed `<M.D.YY> ` with the meeting title repeated in the stem,
  and titles contain spaces, commas, and hyphens. **Glob by extension inside the occurrence
  directory; never reconstruct a filename or assume a slug.** One directory name in the sample
  carries a trailing space — quote all paths.
- `.vtt` exports may be speaker-less subtitle tracks, so they are not a substitute for the `.txt`.

## 4. Participant graph — `org chart.json`

Each occurrence carries one, already resolved upstream. Story 1.5 derives participants from this
plus transcript speakers; the fields below are observed across all 28 files.

**Resolution rates, measured across all 28 charts (2026-08-18):** 225 person-rows, 50 distinct
people, **3 unresolved (1.3%)**, **222 rows carry `mail` (98.7%)**, **208 carry a `managerChain`
(92.4%)** running 5-6 levels to the CEO. Resolution is good enough to treat the chart as the
participant source of record and the transcript as the corroborating signal, not the reverse.

Top level: `generatedAt`, `meeting{title, dateISO, streamUrl, transcript}`, `attendeeSources[]`,
`orgSource`, `people[]`, `notes[]`.

`people[]` fields, union across the corpus: `name`, `mail`, `title`, `department`, `deptCode`,
`lineOfBusiness`, `office`, `org`, `guest`, `unresolved`, `managerChain`, `foundIn`, `response`,
`invite`, `spokeTurns`, `spokeWords`.

Behaviours that will otherwise be rediscovered the hard way:

- **`unresolved: true` marks external vendor attendees** not in the tenant directory. They are
  kept deliberately — never drop them, and never merge them into a resolved person.
- **Do not key that check on `guest`.** `guest` is `false` on all 225 rows corpus-wide; the three
  external attendees carry `unresolved: true` with `org: "Unknown"`. Prose upstream describes them
  as "guests", but the field of that name is not the marker — code keying on `guest` finds nothing.
- **`mail` is a real directory identifier and it exists without Microsoft Graph.** It is present on
  222/225 rows (`cameron.blake@corp.com`), sourced from the SharePoint user-profile service over the
  puller's existing cookie session. This corrects an earlier premise — recorded in the story-1.5
  reconciliation — that no directory identifier was available because Graph is a non-goal. `mail`
  is the stable cross-meeting join key; use it, and fall back to roster-scoped name normalization
  only for the rows that lack it.
- **The employee-number login is a different field.** Tenant *login* names are employee numbers
  (`10001@corp.com`); that is not the same value as `mail`, and joining the two will miss.
- **`department` is the readable org name** (`CORPORATE IT 452A - 102`); `deptCode` is the
  cost-center code. The readable name comes from a custom HR property, not the standard
  `Department` field — do not "correct" this back.
- **`spokeTurns` / `spokeWords` give share-of-talk for free** — no computation needed.
- `attendeeSources` and per-person `foundIn` (`invite` / `permissions` / `transcript`) already
  record provenance, which CAP-1's provenance requirement can consume directly. Attendance is
  genuinely dual-sourced — a chart records e.g. `recording permissions (6)` and
  `transcript speakers (11)` — and **recording permissions surface non-speaking attendees the
  transcript alone cannot**, which is what makes the "who was in the room but silent" query answerable.
- **`invite` / `response` are present but empty.** They are the calendar accept/decline fields, and
  filling them is the only thing enabling Microsoft Graph would add (`orgSource` is `sharepoint`;
  Graph is supported but unconfigured). The Graph non-goal costs nothing but RSVP status.
- **`meeting.streamUrl` is present on all 28 charts**, matching the `url` in each `_source.json`.
- Teams writes `Last, First`, and the comma is a separator in some query languages — a known
  source of silent breakage when joining on names.

### Speaker normalization, scoped

Reconciliation is `Last, First` ↔ `First Last`, initials, and bare-first-name resolution **scoped
to that meeting's roster**, with placeholder detection for `Speaker N`. The residue splits three
ways — resolved, ambiguous, unresolvable — and per the never-guess constraint the last two stay
that way. Going forward the Teams-only decision removes most of this problem for new pulls; the
normalizer is needed for the existing corpus and for the eval assets.

## 5. Environment

- Python 3.14 is the machine default in this environment but **ASR wheels do not exist for it** —
  build against 3.12 via `uv`.
- `ffmpeg` and `ffprobe` are present on this dev machine. They were **absent** on the parallel
  track's machine, which is why that track's findings use PyAV — a portability note, not a
  blocker here.
- An on-prem LAN model host is already in production use (Ollama, with `embeddinggemma:300m`
  installed), reachable without cloud egress. Cloud-suffixed models on that host send content
  off-network and are not used.
- A second on-prem GPU host is available: **VM 120 `cuda-asr`** on the ThreadRipper/Proxmox
  workstation — Ubuntu 24.04, RTX 4080, CUDA 12.9, serving `nvidia/parakeet-tdt-0.6b-v3` over
  FastAPI at `http://10.77.0.120:8000` (`/health`, `/transcribe`). Health verified 2026-08-19 from
  this machine. Measured on its own 600-second benchmark: **~227× real time end to end** (~2.4 s of
  model time per 10 minutes of audio), uploads normalized to 16 kHz mono PCM and split on exact
  sample-frame boundaries at ten minutes, with **native NeMo segment timestamps** — not estimated —
  and truthful `processed_ranges` on partial failure. It reports `language: "auto"` and cannot give
  a reliable detected-language label.
- **Diarization is available on that host, contrary to the handoff's silence on it.** Verified by
  inspection 2026-08-19: the installed NeMo carries `clustering_diarizer.py`, `msdd_models.py`,
  `online_diarizer.py`, `sortformer_diar_models.py` and TitaNet speaker-embedding `label_models.py`.
  What is missing is not capability but deployment — no diarization weights are in the caches and
  the running service exposes only `/health` and `/transcribe` (verified against its own
  `openapi.json`). GPU headroom is there: 3.6 GiB of 16.4 GiB in use at rest. So a diarizer for the
  `Diarizer` port is a model pull plus an endpoint on this host, not a different machine or stack.
- **What diarization would and would not fix.** It segments audio into speaker turns; it does not
  name them. The output is anonymous clusters — "speaker 1", "speaker 2" — so for the 193
  speaker-less archive `.vtt` tracks (§3) it would recover turn structure but not identity. Naming
  those clusters needs voice enrollment or a roster match that does not exist today, and the SPEC
  constraint *speaker attribution never guesses* forbids closing that gap by inference. Diarization
  is therefore a real gain for transcript structure and a partial one for the participant graph.
- **The GPU is shared but the scheduling is ours.** VM 120 and VM 116 pass through the same RTX
  4080 and must never run at once, and VM 120 does not start with the host (`onboot=0`) — so
  starting VM 116 means stopping VM 120 first. Scheduling is operator-controlled: the host is
  available on request, including for the demo, and further VMs can be provisioned on the same
  workstation if a stage needs one. Treat it as available infrastructure, not as a best-effort
  dependency.


## 6. Library inventory beyond the pulled occurrences (2026-08-19)

`VMS_Recordings_Transcripts_Inventory.csv` (new upstream) inventories the SharePoint library the
recovery draws from: 269 rows spanning 2026-02-18 to 2026-07-06 — 148 transcripts, 64 recordings,
57 design documents — across folders including `01 All Design`, `02 All General corp x vendor`, and
several `manual upload` session-recording folders.

Grouped by the CSV's own `meeting_key`: **37 meetings carry both a recording and a transcript, 21
carry a recording only, 104 carry a transcript only.** This is a different and wider population
than the 28 pulled occurrences, and it is the pool the transcript-only backlog is drawn from.

The 57 design documents are a content type MeetingMiner does not ingest — evidence capture is
scoped to meetings. Noted so the boundary is explicit rather than assumed.
