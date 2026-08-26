# CLAUDE.md — Teams/Stream Transcript Grabber

Context for an AI coding agent taking over this project. Read this first.

## Two locations, and which one you are in

The source lives in the MeetingMiner repo at `tools/puller/`. The **working
archive** — every occurrence folder, `.transcript-profile/`, `pulls.jsonl`,
`archives.txt`, `_index.json`, `SESSION_HANDOFF.md`, `migration-plan.txt` and
the launchd logs — lives outside the repo at
`/Users/devopsterus/current/pull_transcript`, which holds its own copy of this
source so the tool can run beside the data.

That split matters because `--all`, `--login`, `--replay` and the prompt files
all resolve against `__dirname`. Run them in the archive copy; `--all` inside
the repo checkout finds no occurrences, says so, and exits **1**. Do not run
`--login` in the repo copy either — it would write a second signed-in
`.transcript-profile/` inside the repo tree.

Edit the source in the repo: it is the tracked copy, and the one
`make puller-test` reads. Then push it across with
`make puller-sync MM_PULLER_ARCHIVE=<archive>`; `make puller-archive-check`
reports drift and fails when the two differ. That matters because the repo copy
is the tested one while the archive copy is the one that pulls real meetings, so
a fix that passes the gate does not reach production until it is synced.

## What this is

A CLI tool that extracts the **full** transcript of a Microsoft Teams meeting
from its Microsoft Stream recording page and prints/saves it as clean
`[m:ss] Speaker: text`. Single script: `grab-teams-transcript.js` (Node +
Playwright).

## The problem it solves (important — don't "simplify" this away)

The obvious approaches all fail, for concrete reasons:

1. **Copy/paste from the Teams meeting recap** drops the middle of the meeting.
   The transcript is a **virtualized list**: only the rows currently on screen
   exist in the DOM. Select-all captures the top + bottom that were rendered,
   never the un-rendered middle.
2. **A console script in the Teams recap page** can't reach it either — the
   transcript there is inside a **cross-origin iframe**, so `contentDocument`
   is null and parent-page scroll/keyboard events don't route into it.
3. **A plain HTTP fetch (curl/requests)** can't work: the page is behind
   Microsoft SSO and the transcript is loaded client-side from a
   token-authenticated SharePoint API. There is no stable fetchable URL.

**What works, and why this uses a browser:** open the recording's **Stream
page** (the "Watch in browser" link → `…/stream.aspx?id=…`). There the
transcript renders in a **same-origin** scrollable container, so a script can
scroll it and harvest the rendered rows. This tool drives a real, logged-in
Chromium (Playwright) to do exactly that.

## How the scrape works (in `scrapeInPage`, runs via `page.evaluate`)

1. **Open** the Transcript panel (clicks a button/tab labeled "Transcript" or
   "Read transcript").
2. **Find** the container: the tallest scrollable element whose text contains
   ≥3 `m:ss` timestamps.
3. **Harvest**: scroll top→bottom in ~0.75×viewport steps; at each step read
   `innerText` and stitch onto the accumulator with a longest-overlap merge.
   Because the list is virtualized, one pass sees overlapping windows; the
   overlap merge reassembles them in order.
4. **Parse**: each turn's short `m:ss` line is the anchor; the speaker name is
   2 lines above it, and the text follows (a leaked combined
   "Name X minutes Y seconds" label and verbose time lines are filtered out).
5. **De-dupe**: the scroll produces the same turns many times. Key each turn by
   `timestamp|speaker` and keep the text variant seen **most often** (mode),
   **penalizing abnormally long captures** (span > 15 lines, weight ~0). This
   is the critical bit: without the penalty, a turn whose next-anchor landed
   far away at a scroll boundary absorbs unrelated later text.
6. Sort by time, emit `[m:ss] Speaker: text`.

## Layout

- `grab-teams-transcript.js` — the whole tool (CLI parsing + Playwright + scrape).
- `emit-drop.js` — maps one occurrence folder into a MeetingMiner **source
  drop** and POSTs it to `POST /ingests`. Module + CLI; also the `--all`
  backfill over the archive. See "MeetingMiner hand-off" below.
- `test/emit-drop.test.js` — `node --test` suite for the mapping. It is the only
  place `docs/source-drop.schema.json` is read, and it finds the schema by
  searching **upward** from its own directory, so the package can sit at any
  depth. When it can see `infra/Makefile` above it, it is inside a MeetingMiner
  checkout, where the schema is always present: a miss there means the search
  broke, so the cases fail rather than skip. A genuine standalone checkout skips
  them with a named reason. `MM_REQUIRE_DROP_SCHEMA=1` forces the strict
  behaviour anywhere. A schema that is present but unreadable or uncompilable
  always fails the suite at load.
- `test/finish-pull.test.js` — pins the ORDER of the post-download tail
  (`writeSource`/`logPull` → `generateDocs` → `emitDrop`/`postIngest`), which is
  the contract, with stubs.
- `test/summarize-docs.test.js` — the Ollama summariser paths, including the
  stall and total-elapsed timeouts.
- `migrate-layout.js` — completed one-time migration to the
  `<Title>/<M.D.YY>/` occurrence layout; dry-run by default.
- `seed-pull-log.js` — one-time browser-history backfill for `pulls.jsonl`.
- `index-archives.sh`, `.probe-item.js`, `package.json`, `package-lock.json`,
  `README.md`, this file, and the three `*_prompt*.md` files.

`npm test` runs all three suites (`node --test test/*.test.js`). Everything
listed above is tracked in the MeetingMiner repo — `git ls-files tools/puller`
returns exactly these 17 files. The rest of the layout exists solely in the
working archive:

- `pulls.jsonl` — append-only source/run ledger used by `--replay`.
- `<Title>/<M.D.YY>/_source.json` — provenance and replay-completion marker for
  each local occurrence.
- `archives.txt` — the team-site archives `--index` and the fallback enumerate.
- `migration-plan.txt` — historical pre-migration dry-run output, not a current
  task list and not an instruction to reapply the migration.
- `SESSION_HANDOFF.md` — current closeout status, verification, and remaining
  optional work.
- `.transcript-profile/` — persisted browser session (created on `--login`).
  It never leaves the machine that owns it and is never committed or packaged.

## Setup & usage

```bash
npm install
npx playwright install chromium
node grab-teams-transcript.js --login               # sign in once (headful)
node grab-teams-transcript.js "<stream-url>"         # -> "<Meeting Title>/" with "<M.D.YY> <Meeting Title>.txt" + .mp4 + .md + " action items.md" inside (date prefix separates recurring meetings; same occurrence overwrites on re-run)
node grab-teams-transcript.js "<stream-url>" --no-video # transcript only
node grab-teams-transcript.js "<stream-url>" --no-summary # skip the Ollama architecture summary
node grab-teams-transcript.js --summarize "<file.txt>" # summarize an existing transcript (backfill/testing)
node grab-teams-transcript.js "<stream-url>" out.txt # transcript -> specific file
node grab-teams-transcript.js "<stream-url>" -       # transcript -> stdout
node grab-teams-transcript.js "<stream-url>" --headful  # watch it
node grab-teams-transcript.js "<folder-url>"         # BATCH: mirror a whole library folder (recordings+transcripts)
node grab-teams-transcript.js "<folder-url>" --index # INDEX only: log downloaded/missing, no download
./index-archives.sh                                  # index every folder in archives.txt (on demand)
node grab-teams-transcript.js "<stream-url>" --no-emit # skip the MeetingMiner drop + POST /ingests hand-off
node emit-drop.js --all --dry-run                    # what the backfill would emit; writes nothing
node emit-drop.js --all                              # emit every already-pulled occurrence as a drop and POST it
node emit-drop.js --all --re-emit --dry-run          # what bringing the archive up to contract would emit
node emit-drop.js --all --re-emit                    # emit a NEW sibling drop ("<name>-002") wherever the newest one is out of date
npm test                                             # emit-drop suite (validates drops against the shared schema)
```

Pass the **Stream** URL (from "Watch in browser") for a single recording, or a
document-library **folder URL** (`…/Forms/AllItems.aspx?id=…`) for batch/index
mode. Any URL without `stream.aspx` is treated as a folder.

## Modes & moving parts

- **Single recording** — transcript via the media API when possible, scrape
  as fallback: `fetchTranscripts` lists
  `_api/v2.1/drives/{id}/items/{id}/media/transcripts` (cookie auth; ids come
  from `watchForItemIds` player-traffic sniffing, polled up to ~12s) and
  downloads content via each transcript's tempauth `temporaryDownloadUrl` +
  `&format=json|vtt|docx` (WITHOUT cookies; constructed streamContent URL
  needs `Accept: */*` — application/json gets a 406). The `.txt` is built from
  the **json** format (speaker names + offsets — what the player renders);
  the vtt export can be a speaker-less subtitle track, so it's only a
  fallback parse. `.vtt` + `.docx` originals are saved alongside. txt/srt
  formats: `400 notSupported`. Recordings merely shared (not owned) 403/404
  → scrape. `DEBUG_TRANSCRIPTS=1` traces each step. Then the video fallback
  chain:
  (1) item-scoped source download → (2) `tryArchiveFallback` matches the file by
  name in `archives.txt` archives and pulls it from the team site →
  (3) transcript only. Before the MeetingMiner hand-off, `generateDocs` sends
  the transcript to
  Ollama (`gpt-oss:120b` on `10.77.0.52`, override via
  `OLLAMA_URL`/`OLLAMA_MODEL`) twice: `arch_summary_prompt.md` →
  `<same stem>.md`, then `action_items_prompt.md` (owner-grouped checklist)
  → `<same stem> action items.md`. Prompt files overridable via
  `SUMMARY_PROMPT`/`ACTIONS_PROMPT` env vars.
  Streaming request with `num_ctx: 65536` (Ollama's default context would
  silently truncate). The user message injects the meeting date (from the
  file's `M.D.YY` prefix) + a "due dates only if stated" rule — without this,
  models fabricate calendar due dates for vague commitments like "next week".
  The prompt requires [m:ss] timestamp citations on decisions/actions/risks
  (verifiability), a participants roster (name consistency), [Proposed] tags
  on model-invented rules, and Mermaid process diagrams. Original pre-7/16/26
  prompt kept at `arch_summary_prompt.orig.md`. `SUMMARY_PROMPT=<path>` env
  var swaps the prompt file for A/B testing. The action-items prompt follows
  the same grounding rules (timestamps, owners explicit-vs-inferred, timing
  only as stated).
  Summary failure never fails the grab — retry with `--summarize "<file.txt>"`.
  Model bake-off (7/16/26, same transcript): gpt-oss:120b best overall (~3 min,
  correct names, best structure); nemotron-3-super deeper analysis but 5+ min
  and mangles names; qwen3.5:35b fast but numerically unstable. `:cloud` models
  send transcripts off-network — don't use.
- **MeetingMiner hand-off** (`emit-drop.js`) — see the dedicated section below.
- **Batch** (`runBatch`) — enumerate a folder recursively, mirror
  recordings+transcripts locally, skip files already present at matching size.
- **Index** (`runIndex`, `--index`) — same enumeration, but only writes
  `<archive>/_index.json` + appends `<archive>/_index-log.txt`; no downloads.
- **Cross-host auth** — `warmSession` navigates to the site once so the `rtFa`
  root cookie mints a per-host `FedAuth`; REST/download calls need it and the
  saved profile only has it for hosts it has visited.
- **Failure flag** — `.run-state.json`; set on auth/systemic failure, surfaced
  at the next run's start with a suggested fix, cleared after a clean run.
- **Schedule** — launchd agent `com.contoso.grabtranscript.index` runs
  `index-archives.sh` daily at 08:00. Turn off with
  `launchctl bootout gui/$(id -u)/com.contoso.grabtranscript.index` (see README).

## MeetingMiner hand-off (`emit-drop.js`)

MeetingMiner ingests **only** source drops, and the only intake door is
`POST /ingests {"dropPath": "<absolute>"}`. `emit-drop.js` is the bridge. It is
a deliberate **black box seam**: it imports nothing from the MeetingMiner
server, reads no `config.yaml` and no `.env`, uses no Microsoft Graph and no
credential file (auth is still the persisted `.transcript-profile/` session),
and never loads the drop JSON Schema at emit time — so the puller keeps working
as a standalone checkout outside the MeetingMiner repo. Do not "helpfully"
import server code or read server config here; that is the one thing this file
must not do.

**Drop layout.** `<drops-root>/<YYYY-MM-DD>-<title-slug>-<sha1(sourceId)[0:8]>/`
holding `metadata.json` plus whichever of `recording.mp4`, `transcript.vtt`,
`transcript.txt` the occurrence has (at least one is required), plus the two
generated extraction documents when they exist: `<stem>.md` maps to
`extraction-summary.md` and `<stem> action items.md` to
`extraction-action-items.md`. Only files whose name matches the occurrence stem
`"<M.D.YY> <Title>.<ext>"` map. The generated `.docx`, `_source.json` itself,
and stray transcripts (e.g. `11_59 AM - …_transcript.txt`) are ignored by
design — do not add them. `<stem> org chart.json` is *read* — it becomes
`metadata.participants` (below) — but is never copied into the drop: the drop's
contract is the schema's key set, not this tool's file layout.

The two extraction documents are **derivative, not evidence**. They live in
`plan.summaries`, never in `plan.files`, because `dropIsCurrent()` and
`evidencePresentIn()` both read `plan.files` as the evidence set — folding
summaries in would silently change re-emit semantics and make a summary look
like a reason to re-arm an occurrence. They also never make a drop ingestible
on their own.

**`metadata.json`** is emitted with these keys: `schemaVersion` (1 normally, 3
when the drop carries extraction documents), `sourceId`, `corpus`, `startedAt`,
`startedAtPrecision`, `provenance`, `participants` when the occurrence has a
usable participant graph, and `extractions` when it carries extraction
documents. `provenance` is the occurrence's `_source.json` object embedded
verbatim.

**`extractions`** names the canonical drop filename of each extraction document
the drop carries — `{"archSummary": "extraction-summary.md", "actionItems":
"extraction-action-items.md"}` — and requires `schemaVersion: 3` so a consumer
pinned to an older version fails closed rather than ignoring the declaration
and paying for a model pass that re-derives what is already there. The key is
**omitted, never emitted as `{}`**, when neither document exists, which is the
same rule `participants` follows.

**`participants` is the occurrence's `<stem> org chart.json`, mapped.** The
chart's `name` becomes the schema's `displayName`; every other field
(`mail`, `title`, `department`, `deptCode`, `lineOfBusiness`, `office`, `org`,
`guest`, `unresolved`, `managerChain`, `foundIn`, `invite`, `response`,
`spokeTurns`, `spokeWords`) passes through verbatim, which is what carries the
reporting chain across without a new field on either side. `mail` is what makes
a person one identity across meetings: MeetingMiner keys participants on it
when the graph supplies one and falls back to the normalized display name only
where it does not, so a drop with no graph keys everyone on how their name
happened to be typed in that meeting's transcript. No Microsoft Graph call is
involved on either side — the chart is written by the puller's own org-chart
step from the SharePoint user-profile service.

The key is **omitted, never emitted as `[]`**, when there is no chart, the file
is unreadable or not JSON, `people` is absent or not an array, or no row has a
usable `name`. `[]` is a different statement — MeetingMiner reads it as "the
source looked and found nobody" and does not fall back to transcript labels — so
emitting it for a broken chart would silently strip a meeting of its
participants. An unusable chart is a named warning on stderr and never a skip:
the transcript is the occurrence's evidence, the chart is auxiliary. A single
nameless row is dropped with its own warning and the rest of the chart maps.

**`augments` and `--re-emit`.** At `schemaVersion: 2` the schema defines an
`augments` object naming the already-ingested occurrence a drop adds evidence
to. An ordinary emit never declares it: a re-pull has the same sourceId, date
and title, so it resolves to the same drop directory and is reported `exists`.
`--re-emit` is the opt-in path that does. For each occurrence it compares the
newest existing drop against what this pass would emit — the participant graph
and which canonical evidence files the occurrence has — and:

- nothing existing yet: emits the plain version 1 drop at the base name (you
  cannot augment an occurrence that was never ingested);
- newest drop already says the same: reports `current` and writes nothing;
- a non-empty participant graph or a recording the newest drop lacks: emits a **new sibling** drop at `<base-name>-002`, then
  `-003`, …, carrying `schemaVersion: 2` and `augments: { sourceId }` naming its
  own sourceId, which routes intake to the re-arm path that keeps the meeting id
  instead of answering 409 on the live job.

The finalized drop is never renamed, rewritten or deleted — that is why
sequence 1 *is* the existing unsuffixed name and the discriminator starts at
`-002`. A three-digit zero-padded sequence rather than a timestamp so a repeat
pass is a no-op and lexical sort within an occurrence's prefix is emit order;
`-999` is the ceiling and exhausting it is a named error that writes nothing.
Because `--re-emit` is opt-in per occurrence, a half-finished migration leaves
one person mail-keyed in one meeting and name-keyed in another, so every
`--re-emit` pass ends by reporting how many drop prefixes in the drops folder
still have a newest drop with no `participants` key.

What still holds is `additionalProperties: false` at the top level, so any key
the schema does not define is a validation failure, and a version 1 drop
carrying `augments` is refused.

**`sourceId` is the canonicalized Stream URL** — `origin + pathname + ?id=…`,
with the `referrer` / `referrerScenario` / `isDarkMode` params dropped. Those
vary with how the link was copied, so using the raw URL would let one
occurrence produce two sourceIds and therefore two job rows. The recording's
drive-item id would also be acceptable to MeetingMiner but is only observable
from live player traffic, so the backfill could not produce one.

**`startedAt` precision — the `UTC` suffix is the discriminator.** Only a
`-YYYYMMDD_HHMMSSUTC-` stamp names an instant (`precision: "second"`). An
un-suffixed stamp is in the **organizer's** timezone, which this tool does not
know (see the date gotcha below), so converting it would write a wrong UTC
instant under a precision that claims a real time of day. Anything that is not
a UTC stamp therefore falls back to the occurrence date at `00:00:00Z` with
`precision: "day"`; the raw stamp survives inside `provenance.recordingName`.
This makes all three `dateSource` variants fall out of one rule. Measured over
the 28-occurrence archive: 9 `second`, 19 `day`.

**Impossible dates and times skip the occurrence.** The stamp digits are
matched positionally, so a corrupt recording name can yield month 13 or hour 99
— a well-formed but impossible `startedAt` that the api rejects with 422. By
then the drop would already be finalized write-once, so the occurrence could
never be ingested and nothing is allowed to delete the drop. `parseStamp` and
`parseOccurrenceDate` therefore reject impossible clock fields and non-existent
calendar days (round-tripped through `Date.UTC`) *before* anything is written,
raising `SkipError`.

**The undated layout is handled.** When `_source.json` has no `date`, the
occurrence's files are `"<title>.<ext>"` with no prefix (run() sets
`base = stem`), and the stem is built without the leading `"<date> "`. A
UTC-stamped recording still supplies the instant; without one the occurrence is
skipped for having no usable date.

**Write-once.** A drop is assembled under `<drops-root>/.staging/<name>.<pid>.<n>/`
and finalized with a single `fs.renameSync`. A finalized drop is never
overwritten, re-copied into, or deleted — an existing target is reported as
`exists` and skipped, and an `EEXIST`/`ENOTEMPTY` on the rename (a concurrent
finalize) is the same outcome, not an error. Staging is removed on every exit
path. Files are copied with `COPYFILE_FICLONE` (an APFS clone when possible),
so the recordings cost no extra disk while the drop stays independent of the
archive that re-pulls mutate. Nothing in the occurrence folder is ever touched.

**Resolution order.** drops folder: `--drops <dir>` > `MM_DROPS_ROOT` >
`/Users/devopsterus/current/meetingminer-drops`. API base URL: `--api <url>` >
`MM_API_URL` > `http://127.0.0.1:8000`. Corpus: `--corpus` > `MM_CORPUS` >
`real` (`scripted` tags Epic-5 mock meetings pulled from the same tenant). The
drops folder must stay outside this archive: drop contents are read-only after
intake, while re-pulls mutate the archive in place.

**Intake results.** `201` → queued (`jobId` printed); `200` → a previously
failed job was re-queued; `409` → this occurrence already has a live job,
reported as "already ingested" and **not** an error. Anything else, including
an unreachable API, is reported with the drop path so it can be re-POSTed. The
POST carries an `AbortSignal.timeout` (30s default, `opts.timeoutMs`): an api
that accepts the connection and then never answers must not park a pull
forever — "never fails a pull" is only true if it also always finishes.

**Never fails a pull.** The post-download tail is `finishPull()` — its own
exported function precisely because the ORDER is the contract and every other
suite stays green whichever way round it runs (`test/finish-pull.test.js`
asserts the sequence with stubs). The order is:

1. **`writeSource` + `logPull`.** The sidecar first, before anything slow.
   `--all` keys on `_source.json`, so an interrupt or a crash during the
   multi-minute summariser pass must not leave a transcript that neither the
   backfill nor a manual emit can ever see again.
2. **`generateDocs`.** Before the emit, because the drop now *carries* the two
   documents; emitting first would mean no drop could ever carry them.
   Non-fatal — a summariser failure costs the `extractions` declaration and
   nothing else, and MeetingMiner then generates what is missing.
3. **`emitDrop` + `postIngest`.** Last, and unconditional. A drop or intake
   failure prints a named diagnostic naming the retry command; the transcript,
   video, and summaries are untouched. `--no-emit` skips the hand-off entirely.

The ordering costs the drop one model pass per document (~3-6 minutes) and buys
MeetingMiner the whole extraction pass it would otherwise spend re-deriving
these same two documents. Because a stalled Ollama would now park the hand-off
rather than merely cost the summary, `summarizeTranscript` aborts on silence
between streamed chunks (`OLLAMA_STALL_TIMEOUT_MS`, default 120s) and on total
elapsed time (`OLLAMA_TOTAL_TIMEOUT_MS`, default 30min); a timeout surfaces as
a named error, still non-fatal.

**The `--all` backfill** scans recursively from this directory for
`_source.json` sidecars (skipping dotdirs and `node_modules`) — it keys on the
sidecar, not on an `M.D.YY` folder name, because the batch-mirror folders under
`Recordings and Transcripts/` look like occurrences but are not. Per-occurrence
failures never abort the pass; the run ends with a
`created / exists / skipped / failed` summary. It exits non-zero on a real
failure, and also when it emitted nothing at all while skipping something — a
backfill that produced no drops did not do its job, whatever the reason. An
unreadable subtree is named on stderr rather than silently vanishing from the
pass.

**Tests.** `npm test` runs `test/emit-drop.test.js` (`node --test`), which
builds fixture occurrence directories in a temp tree and validates every
emitted `metadata.json` against `docs/source-drop.schema.json` with ajv
(2020-12) + `ajv-formats` — `devDependencies`, and the schema is read **only**
there. Two distinct outcomes, deliberately not collapsed: schema file *absent*
(a standalone checkout) skips those cases with a named reason; schema file
*present but unusable* — corrupt, or ajv missing — fails the suite at load,
because a skip there would silently retire the contract check. The suite also
covers `grab-teams-transcript.js`'s `parseGrabArgs`, which is why that file
only runs its CLI under `require.main === module`. `make puller-test` fails
rather than skips when the dev deps are missing and this directory exists.

## Known fragilities / gotchas

- **Meeting date: filename stamp wins; mvhd is only a fallback.** The
  `-YYYYMMDD_HHMMSS-` tail is the FILE's creation date, written by Teams at
  capture and normally correct. The mp4's mvhd atom (encode time, read by
  `mp4Date`) is NOT a reliable meeting date in *either* direction: a
  re-uploaded recording keeps its ORIGINAL (older) encode time, and a
  **recurring** series can carry the first occurrence's time forward onto
  every later recording (seen: a 7/22/26 weekly-connect whose mvhd read
  4/1/26, the series' April origin — the tool renamed the whole dataset to
  4.1.26 until this was fixed). So the reconcile block in `run()` **trusts
  the filename stamp by default** and uses the mvhd date only when the name
  has NO stamp. On a disagreement it keeps the stamp and prints a warning;
  set **`TRUST_MP4_DATE=1`** to override with the mvhd date (the fix for a
  genuinely copied recording whose stamp is the copy date, e.g. the old
  4/1-meeting-stamped-7/15 case). Earlier versions did the reverse (mvhd
  always won), which silently mis-dated every recurring meeting. `--no-video`
  runs have only the filename stamp — which is now the default anyway.

- **Panel button label drift.** Microsoft renames UI controls. If auto-open
  fails, the `--headful` path lets the user click Transcript manually, then the
  script retries. Keep that fallback.
- **`channel: 'chrome'`** in `launchPersistentContext` uses installed Chrome.
  Remove that line to use Playwright's bundled Chromium.
- **MFA/session expiry.** If the org forces MFA per session, `--login` must be
  re-run periodically. `stream.aspx` bouncing to `login.microsoftonline.com` is
  detected and the tool exits asking for `--login`.
- **Transcript is verbatim auto-ASR.** Expect mis-hears (names, "SQL"→"sequel",
  etc.). The tool does not correct content.
- **Timing waits are fixed** (6s load, 250ms/scroll step). Slow tenants/long
  meetings may need larger values; consider replacing with explicit
  `waitForSelector`/network-idle waits.
- **Two download endpoints, different rights.** Item-scoped
  `@content.downloadUrl` (from the vroom item API, fetched WITHOUT cookies so
  its tempauth token isn't overridden by the cookie identity) is used for a
  single recording; path-based `download.aspx?SourceUrl=` is used inside team
  sites (batch + archive fallback), where you have folder browse rights.
  A `403 accessDenied` on a personal share means view-but-not-download — that's
  what triggers the archive fallback, not a bug.
- **View-only recordings can't be downloaded at all**, only streamed (encrypted
  DASH from `*.svc.ms`, bearer-token gated). The archive fallback is the
  practical answer; capturing the stream would mean reimplementing the player.

## Good next tasks (unstarted)

- Replace fixed `waitForTimeout`s with robust `waitFor*` conditions.
- Optional `.docx`/`.md` output (a `docx`-based writer already exists in a
  sibling experiment; port it here if wanted).
- Tests: a recorded HTML fixture of the transcript container to unit-test the
  parse + mode-dedup without a live login.

## Constraints

- Only touch transcripts the user is authorized to view. Do not attempt to
  bypass auth, MFA, or bot-detection. Never hardcode credentials — the browser
  profile holds the session.
