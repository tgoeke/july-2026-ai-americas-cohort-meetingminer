# Adversarial Review Update — ARCHITECTURE-SPINE.md (meetingminer), 2026-08-18 amendment

**Lens:** adversary. Method: construct pairs of units one level down that each obey every AD to the letter yet build incompatibly. Every surviving pair is a hole to close with a new or tightened AD.

**Scope:** the 2026-08-18 amendment only — M365 sandbox discontinued; scripted mock meetings on the corp production Teams tenant; retrieval by the existing `pull_transcript` puller (Playwright scrape, user login, outside MeetingMiner) emitting drop directories; participants from transcript speakers + metadata sidecar (no server Graph calls); corpus split (~25 real pulled meetings = ingested demo corpus, scripted mocks = sole eval subjects, CAP-7 map row). The 2026-08-17 full review (`review-adversarial.md`) closed C1–C3, H1–H3, M1–M4, L1–L2; those closures were re-checked against the amended text and hold except where noted below.

**Evidence base:** the amended spine; `epics.md`; `SPEC.md` + `scope.md` + `eval-design.md`; and the puller's actual output tree at `pull_transcript/` — 28 occurrence directories with `_source.json` inspected directly.

**Verdict: THE AMENDMENT REOPENS THE AD-1 SEAM IT AMENDED AND LEAVES THE CORPUS SPLIT PROSE-ONLY.** The prior review's fixes hold for the server-internal seams (projections, publish gate, citations, evals-as-client). But the amendment replaced a hypothetical Graph-fed drop with a real tool whose real output is now on disk — and that output contradicts the drop contract's assumptions in verifiable ways: most of the demo corpus has no video file, the sidecar has no participants and no usable timestamp, the two transcript exports disagree on speakers, and nothing in any data structure distinguishes an eval subject from a demo meeting. Ten findings: 2 critical, 4 high, 3 medium, 2 low (one is cross-document drift rather than a spine hole).

---

## CRITICAL

### C1. The drop contract requires a video file; 20 of the 28 real occurrences don't have one

- **Units:** puller emit-drop step vs pipeline (`probe`→`moments` stages) vs the API's schema validation at `POST /ingests` (AD-1, AD-14). scope.md Corpus is collateral.
- **The clash.** AD-1: a source drop is "one directory containing **the video file**, an optional transcript … and `metadata.json`." Video is the one required content; transcript is optional. Verified against the archive the amendment promotes to demo corpus: **20 of 28 occurrence directories contain no `.mp4`** — the puller's documented fallback chain ends at "transcript only" whenever a recording is shared view-only and the archive fallback misses (README §"How the video download works"). This is not an edge case; it is the majority of the corpus. scope.md: real pulled meetings are "Part of the demo corpus: **ingested**, searchable, and visible in the live demo."
  - *Build B (puller epic):* emit-drop emits video-less drops. The API either rejects them at schema validation (same outcome as A) or — if the schema author marked video optional to make the corpus fit — the pipeline crashes or improvises at `probe`/`frames`/`ocr`/`screens`, and `moments` must invent semantics for a moment with no screenshot. The ERD already permits `MOMENT }o--o| SCREENSHOT` (zero-or-one), so a transcript-only moment is *representable* — but no AD says whether it is *legal*, so the pipeline builder and the web builder (moment view: "screenshot on top") will decide differently.
  - Note the scripted mocks are exposed to the same fallback chain: a mock recorded under a view-only share arrives transcript-only too, and then it is an **eval subject** whose capture-recall denominator (slides/screens + participant segments) is unsatisfiable — the run fails with no pipeline bug.
- **Why it survives review:** every build above is internally complete and AD-cited; the corpus count only surfaces at integration, during demo week.
- **Minimal tightening (AD-1 amendment + scope.md touch):** decide once: **(a)** video is required; transcript-only occurrences are excluded from the demo corpus and scope.md's Corpus section says so and gives the real number; or **(b)** the drop schema declares `dropKind: "av" | "transcript-only"`; for `transcript-only` the pipeline runs `align → moments` only, moments carry no screenshot (ERD already allows it), the moment view renders a transcript-only layout, and such meetings are ineligible as eval subjects for capture checks (2.1–2.4). Pin (a) or (b); do not leave it to the schema author. For scripted mocks, add an eval precondition: the mock's recording must be download-accessible before it is accepted as an eval subject.

### C2. Participant identity: the primary dedup key never fires and the fallback key provably fragments on the real data

- **Units:** puller emit-drop (sidecar participants) vs pipeline intake derivation vs API curation (AD-1, AD-5).
- **The clash.** AD-5: worker dedupes participants "by AAD object ID **when present**, else case-folded display name." The amendment removed every path by which an AAD object ID could be present: no server Graph calls (AD-1), Graph lookup product-later, and the sidecar comes from a Playwright scrape of the Stream page. So the fallback — case-folded display name — is the *only* key for the entire capstone corpus. Verified against the actual transcripts: speaker labels mix `Blake, Cameron` (Last-comma-First), `Devon Price` (First Last), `Bennett, Skyler (CNTR)` (contractor suffix), `(Foster, Logan)` (parenthesized), and bare `Robin`. Case-folding none of these onto each other:
  - *Build A (puller epic):* the emit-drop step scrapes the Stream/Teams roster and writes sidecar participants as the roster renders them — typically `Cameron Blake` (First Last).
  - *Build B (pipeline epic):* for drops whose sidecar omits participants, intake derives them from transcript attribution — `Blake, Cameron`.
  - Same human, two Participant rows, meeting by meeting depending on which path ran. The Rowan traversal (participants → meetings → topics → moments) returns a fraction of the true result set with zero bugs. Since real corp colleagues also appear in the scripted mocks (production tenant, real accounts), the fragmentation crosses the eval/demo corpus boundary too.
  - **Second unpinned rule inside the same seam:** AD-1 triggers derivation "when a drop **omits** them." A sidecar with a *partial* roster (scrape caught 3 of 7; attendees who never spoke; speakers who joined anonymously) is not "omitted": Build A skips derivation entirely → transcript segments reference speakers with no Participant row (dangling attribution or an FK violation, builder's choice); Build B unions sidecar + transcript speakers. And no rule joins a sidecar entry to a transcript speaker string at all (`Cameron Blake` vs `Blake, Cameron` share no key), so even the union build double-mints.
- **Minimal tightening (AD-5 + AD-1 amendment):** (1) State the truth: for this corpus the participant identity key **is** the normalized display name; delete "AAD object ID when present" or demote it to a schema-reserved field. (2) Define the normalization once, in `server/domain`, used by *both* sidecar intake and transcript derivation: fold `Last, First` → `First Last`, strip parenthetical suffixes (`(CNTR)`, enclosing parens), casefold, collapse whitespace. (3) Participants at intake are always the **union** of sidecar entries and transcript speakers, joined through the same normalization — derivation is unconditional, not a fallback. (4) The sidecar carries names verbatim as scraped; normalization happens server-side only, so the puller needs no shared code (black-box seam preserved).

---

## HIGH

### H1. API merges vs worker upserts: merged participants resurrect on the next ingest

- **Units:** API epic (participant merge, AD-5 human-curated half) vs worker epic (intake upsert, AD-5 + AD-11).
- **The clash.** AD-5 gives the API merges; AD-11 has the worker upsert cross-meeting entities "by identity key" on every intake and stage rerun, "never deleted by a rerun." Sequence: human merges `Blake, Cameron` into `Cameron Blake` (Story 2.4: segments, attendance, graph edges re-point to the survivor). The next drop — or an idempotent rerun of an *old* job — contains speaker `Blake, Cameron`; the worker's upsert finds no row with that identity key and **re-mints it**. Both processes obey their AD exactly: the worker never wrote the survivor's row (no lost update, so AD-5's protection never triggers), and the merge is undone. Every re-ingest makes participant curation Sisyphean, and the C2 normalization above *reduces* but does not eliminate this (genuinely distinct labels for one person — `Robin` vs `Robin Shaw` — still need human merges).
- **Minimal tightening (AD-5, one sentence):** a merge writes a persistent alias record (API-owned): `alias_key → surviving_participant_id`. The worker's upsert resolves its identity key through the alias table before insert. Aliases are user-declared data (API-owned table), so no ownership rule changes.

### H2. Meeting identity: re-pull + re-POST duplicates the meeting; nothing carries an occurrence key

- **Units:** puller emit-drop (per Story 1.8: POST `/ingests` after every completed pull) vs API/worker (AD-14: a Meeting row is minted per job) vs the recovery convention.
- **The clash.** The puller re-pulls the same occurrence routinely — its README documents "re-running the same occurrence overwrites its generated artifacts in place," and `--replay` re-pulls in bulk from `pulls.jsonl`. AD-11's idempotency is **per job**; AD-14 mints a Meeting per job; no natural key ties a Meeting to the occurrence it came from. Two compliant builds:
  - *Build A:* emit-drop POSTs unconditionally on every pull → every re-pull is a new job → a second Meeting row for the same occurrence. Search, drill-down, and eval-subject selection (H3) now see duplicates; citations split across two Meeting IDs.
  - *Build B:* emit-drop consults its own ledger and skips the POST — but it has still overwritten the drop directory in place, violating AD-13's "source-drop contents are read-only after intake" from the outside, and breaking the recovery convention: "Postgres + content root are reconstructed by re-ingesting drops" now replays bytes that differ from what was originally ingested.
- **Minimal tightening (AD-1 + AD-14 amendment):** `metadata.json` carries a required `sourceId` — the stable occurrence identity the puller already holds (the recording's drive-item id / Stream URL from `_source.json`). `POST /ingests` for a `sourceId` that already has a non-failed job is rejected with a problem+json conflict (capstone: no supersede path; re-processing is a rerun of the existing job). Drop directories are write-once: emit-drop assembles in a staging path and finalizes atomically; a re-pull of an already-ingested occurrence refuses to overwrite the finalized drop.

### H3. Eval subject vs demo corpus: the distinction exists only in prose

- **Units:** evals epic (subject selection, checks 2.1–2.4, 2.10) vs puller/pipeline (identical path for both corpora) — AD-16, CAP-7 map row.
- **The clash.** Scripted mocks and real meetings arrive via the same puller, same tenant, same drop schema, same `POST /ingests`, into the same Postgres and the same projections. No field in the drop schema, the Meeting row, or any API response says which corpus a meeting belongs to. The CAP-7 rule "only scripted mocks are eval subjects" is enforceable only by out-of-band knowledge. Compliant divergent builds:
  - *Evals A:* binds ground-truth manifests to meetings by title match. Collides with H2 duplicates (two Meetings titled identically — which is the subject?) and with any real meeting whose title happens to match; selection is silently wrong, checks pass or fail against the wrong meeting.
  - *Evals B:* assumes a dedicated instance containing only scripted meetings; the demo instance holds the mixed corpus. Check 2.10 (recall@5) and any corpus-scoped count then yield different verdicts on identical code depending on which instance the operator ran against — and the runbook precondition ("every scripted meeting is ingested") is satisfied in both. Nothing detects a real meeting accidentally scored, or a scripted mock accidentally excluded.
- **Minimal tightening (AD-1 + CAP-7 row + runbook precondition):** `metadata.json` (hence the Meeting row) carries `corpus: "scripted" | "real"`, and scripted drops additionally carry `groundTruthId` matching the manifest's `meeting.id`. The eval harness selects subjects **only** by `groundTruthId` (never by title). Every deterministic check scopes its queries and denominators by meeting ID — no corpus-wide counts — so a mixed instance is a legal eval environment; state that in the runbook preconditions.

### H4. Two transcript exports in one drop, no precedence: named speakers or millisecond timing — pick one, the ADs let you pick either

- **Units:** puller emit-drop vs pipeline `align`/participant derivation (AD-1, AD-13).
- **The clash.** AD-1 admits "VTT **and/or** the puller's speaker-attributed `[m:ss] Speaker: text` export" in one drop. Verified against the archive: the puller's `.vtt` export is a **speaker-less subtitle track** (no `<v>` voice tags — confirmed in the files, and the puller's own docs call the vtt "a speaker-less subtitle track … only a fallback parse"), while the `.txt` carries speakers at minute:second precision with **no end times**. Two compliant `align` builds over the same drop:
  - *Build A:* treats the VTT as "the provided transcript" (standard format, millisecond cues) → zero speakers → every segment attributed `Unknown`, and transcript-derived participants (C2) yield nothing.
  - *Build B:* parses the `.txt` → named speakers, but `startMs` is fabricated from `m:ss` (±999 ms) and `endMs` must be invented (next-segment start? fixed duration?). Citations' `startMs`/`endMs` (AD-15) and the documented ±15 s check (2.5) then measure different things per build.
  - Same drop, two incompatible evidence bundles; neither violates any AD.
- **Minimal tightening (AD-1/AD-13 amendment):** when both exports are present, the speaker-attributed `.txt` is authoritative for **speaker attribution and turn segmentation**; the VTT is authoritative for **cue-level timing**; `align` joins them (nearest-cue match on start time) and writes derived rows with provenance to both, per AD-13. Segment `endMs` = the matched VTT cue-run end, else next-segment `startMs`. A drop with only one export uses it for both roles; VTT-only drops accept `Unknown` speakers (AD-13 already covers this).

---

## MEDIUM

### M1. Meeting wall-clock start is underdetermined by the sidecar

- **Units:** puller emit-drop vs pipeline (moment wall-clock = start + offset; conventions require ISO 8601 UTC and "a moment carries both").
- **The clash.** The real `_source.json` carries `"date": "6.10.26"` — day precision, locale-ambiguous, sourced variously from `createdDateTime`, migration scripts, or the filename. The recording filename embeds `-YYYYMMDD_HHMMSS-`, **sometimes with a `UTC` suffix and sometimes without** (verified: `20260610_181541UTC` vs `20260805_100227`). The puller's own docs document a third source (mp4 `mvhd`) as unreliable. Two emit-drop builds legally map `startedAt` from different sources (midnight-local vs filename stamp; naive vs UTC), shifting every moment's wall-clock by hours; cross-meeting ordering and any date-scoped feature (Morning Digest COULD) diverge between builds.
- **Minimal tightening (schema field rule under AD-1):** `startedAt` is required, full ISO 8601 UTC; emit-drop derives it from the recording-filename stamp when present (treating an unsuffixed stamp per the puller's documented convention), else from `date` at 00:00 UTC with a companion `startedAtPrecision: "second" | "day"`. The pipeline never re-derives wall-clock from media metadata.

### M2. "Drops folder" vs the puller's working archive: the immutable recovery root is a mutable working directory

- **Units:** structural seed ("drops folder (puller output)") vs recovery convention ("source drops are the immutable recovery root … the only thing needing backup") vs the puller's actual behavior.
- **The clash.** The puller's native tree is a working archive: re-pulls overwrite occurrence dirs in place, a daily launchd job writes `_index.json`/log files into it, and it contains `node_modules`, ledgers, and prompt files. If "drops folder" = the puller's output root (one legal reading of the seed), the recovery root is mutated daily and immutability is false; if it is a separate directory emit-drop copies into (the other legal reading), then the ~25 existing occurrences reach it only via a backfill emit pass that **no story owns** — Story 1.8 covers URL-triggered pulls only, so the demo corpus's arrival is nobody's deliverable.
- **Minimal tightening (structural seed + Story 1.8 scope note):** the drops folder is a dedicated directory, distinct from the puller's archive; emit-drop finalizes write-once copies into it (per H2). Add to Story 1.8 (or a sibling story): a one-time `--emit-existing` backfill pass over the archive, puller-side, producing schema-valid drops for the demo corpus — with C1's transcript-only decision applied.

### M3. Cross-document drift: epics still authorize puller-side Microsoft Graph the SPEC now rules out

- **Units:** puller epic builder reading `epics.md` vs the amended SPEC/spine.
- **The clash.** SPEC constraint (amended): the corp-tenant arrangement "rules out tenant-side automation, **Graph app registration**, and any MeetingMiner-to-Teams integration"; non-goals: "Microsoft Graph integration, **including participant pull**." But `epics.md` FR1 and Story 1.8 still read "scraped roster on the corp corporate tenant, **Microsoft Graph where accessible**" — pre-amendment wording. A puller builder following epics attempts Graph acquisition (possibly an app registration on the production tenant) that the SPEC forbids. Not a two-build incompatibility inside the spine, but a direct instruction conflict on an amended surface.
- **Fix:** strike "Microsoft Graph where accessible" from epics FR1 and Story 1.8; participants come from the scraped roster and transcript derivation only, per AD-1.

---

## LOW

### L1. Ground-truth offsets vs recording start

Manifest times (`shown_at`, `planted.*.at`) are offsets — but offsets from *what*? On a production tenant the recording starts when someone presses record, not at the scheduled start, and the scriptwriter cannot control the lag. Capture recall doesn't use times, but 2.5 (±15 s, documented) and `shown_at` do. One sentence in eval-design §1: all ground-truth times are offsets from **recording start** (t=0 = first video frame), and mock-meeting operators start the script clock at record-press.

### L2. `_source.json` inside the drop

AD-1 says emit-drop maps the native output "including `_source.json` provenance," but not whether the file is copied into the drop (where the schema's ignore-unknown-files rule would drop it from intake) or embedded into `metadata.json`'s provenance object. Since drops are the recovery root, provenance must survive in the schema-named file: one sentence — emit-drop embeds the `_source.json` content under `metadata.json.provenance`; copying the original alongside is permitted and ignored at intake.

---

## Attacks that failed (the amended spine holds)

- **Puller gaining a second write path** (direct DB seed, folder watcher): AD-14's single door plus "no folder watchers" is airtight; the puller's only server contact is `POST /ingests`.
- **Puller-generated summaries/action-items entering as artifacts:** AD-1's ignore-unknown-files rule names exactly this case; the `.md` files never reach intake.
- **Evals mutating around the publish gate under the new corpus rules:** AD-16 (added after the prior review) holds; check 2.11's approve-via-API path is unambiguous.
- **A second Neo4j/Meilisearch writer smuggled in via the amendment:** AD-4 unchanged and airtight.
- **Server code reaching for Graph to "fix" participants:** AD-1's "No server component calls Microsoft Graph" forecloses it cleanly (the drift in M3 is document-level, not an AD hole).
- **Config/credential bleed between puller and server:** the `puller/.env` black-box seam in the conventions table survives every construction tried.

## Disposition summary

| ID | Severity | Seam | Fix locus |
|---|---|---|---|
| C1 | Critical | video-required drop vs transcript-only majority corpus (20/28) | AD-1 + scope.md |
| C2 | Critical | participant identity key dead (no AAD) + partial-sidecar union + no join rule | AD-5 + AD-1 |
| H1 | High | API merge vs worker upsert — merged participants resurrect | AD-5 (alias rule) |
| H2 | High | no occurrence key — re-pull duplicates Meetings; drop mutability | AD-1 + AD-14 |
| H3 | High | eval-subject membership prose-only; no corpus marker in data | AD-1 schema + CAP-7 row + runbook |
| H4 | High | speaker-less VTT vs m:ss txt — no precedence rule | AD-1/AD-13 |
| M1 | Medium | `startedAt` underdetermined (day-precision sidecar, mixed filename stamps) | AD-1 schema field rule |
| M2 | Medium | drops folder = mutable puller archive; backfill pass unowned | Structural seed + Story 1.8 |
| M3 | Medium | epics still authorize Graph the SPEC forbids | epics.md edit |
| L1 | Low | ground-truth time origin | eval-design §1 sentence |
| L2 | Low | `_source.json` placement in the drop | AD-1 sentence |

Every fix is a tightening of AD-1/AD-5/AD-14 field rules or a one-sentence convention — no new components, no paradigm change. The pattern across C1, C2, H2, H3, and M1 is the same: the amendment pinned *that* the puller's output maps into the drop schema but deferred *what the schema requires*, and the puller's real output — now inspectable on disk — fails the deferred assumptions. The schema content stopped being safely deferrable the moment a real tool with real output became the producer; the tightenings above are the minimum field-level decisions the spine must own before Story 1.2/1.8 builders touch it.
