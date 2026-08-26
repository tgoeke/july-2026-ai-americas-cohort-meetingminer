# Teams/Stream Transcript Grabber

Extract the **full** transcript of a Microsoft Teams meeting from its Microsoft
Stream recording page, as clean `[m:ss] Speaker: text`. Copy/paste from Teams
silently drops the middle of long meetings (the transcript list is virtualized);
this scrolls the whole thing in a logged-in browser and reassembles it.

## Requirements

- Node 18+
- Google Chrome installed (or remove `channel: 'chrome'` in the script to use
  Playwright's bundled Chromium)

## Setup

```bash
npm install
npx playwright install chromium
```

## Log in once

```bash
node grab-teams-transcript.js --login
```

A browser window opens. Sign in with your work account, then press Enter in the
terminal. The session is cached in `./.transcript-profile` and reused on later
runs (re-run `--login` if it expires).

## Grab a transcript

```bash
# Default: creates/reuses a folder named after the meeting and writes
#   <Meeting Title>/<M.D.YY>/<M.D.YY> <Meeting Title>.txt   (transcript)
#   <Meeting Title>/<M.D.YY>/<M.D.YY> <Meeting Title>.mp4   (recording, when downloadable)
# plus original transcript exports, an architecture summary, action items,
# and a _source.json provenance sidecar. Re-running the same occurrence
# overwrites its generated artifacts in place.
node grab-teams-transcript.js "<stream-url>"

# Transcript only (skip the video download)
node grab-teams-transcript.js "<stream-url>" --no-video

# Skip Ollama-generated summary and action items
node grab-teams-transcript.js "<stream-url>" --no-summary

# Backfill the summary and action items for an existing transcript
node grab-teams-transcript.js --summarize "<file.txt>"

# Re-pull logged recordings that are not already represented by _source.json
node grab-teams-transcript.js --replay --dry-run

# Transcript to a specific file (video, if enabled, goes next to it)
node grab-teams-transcript.js "<stream-url>" transcript.txt

# Transcript to the terminal
node grab-teams-transcript.js "<stream-url>" -

# Watch the browser do it (also the manual-fallback mode)
node grab-teams-transcript.js "<stream-url>" --headful
```

Use the **Stream** URL — open the meeting recap in Teams, click
**Watch in browser**, and copy that page's address (`…/stream.aspx?id=…`).

## MeetingMiner source drops (`emit-drop.js`)

After a successful single-recording pull, the occurrence is also emitted as a
**source drop** — a write-once directory in MeetingMiner's canonical layout —
and its path is POSTed to MeetingMiner's `POST /ingests`. This is the only way
a meeting enters MeetingMiner; dropping files into a folder ingests nothing.

```
<drops-root>/<YYYY-MM-DD>-<title-slug>-<hash>/
  metadata.json     always
  recording.mp4     when the occurrence has a downloadable video
  transcript.vtt    when the occurrence has the original VTT export
  transcript.txt    the speaker-attributed export
```

Only those four names are mapped. The generated `.docx` / `.md` /
` action items.md` summaries, `_source.json` itself, and any stray transcript
whose filename does not match the occurrence stem are **ignored** — they never
enter a drop. `_source.json` is embedded verbatim as the drop's `provenance`.

**Write-once.** Each drop is assembled under `<drops-root>/.staging/…` and
finalized with a single atomic rename. A drop that already exists is reported
and left untouched: re-pulling an occurrence never rewrites its drop, and
nothing in your archive is moved, renamed, or modified by an emit.

**Meeting time.** Teams stamps recording filenames `-YYYYMMDD_HHMMSS[UTC]-`.
Only the `UTC`-suffixed form names a real instant, so that becomes
`startedAt` with `startedAtPrecision: "second"`. An un-suffixed stamp is in the
*organizer's* timezone, which this tool does not know, so it is not converted:
those occurrences get the meeting date at `00:00:00Z` with precision `"day"`.
The raw stamp is still preserved inside `provenance.recordingName`. A stamp or
date that could not be real (month 13, hour 99, February 31) skips the
occurrence with a named reason rather than writing a drop the API would refuse.
Occurrences pulled without a date use their bare `<Title>.<ext>` filenames.

```bash
# One occurrence (the folder that holds _source.json)
node emit-drop.js "Fabrikam Data Hub Demo/6.10.26"

# Backfill: every already-pulled occurrence under this directory
node emit-drop.js --all

# See what would be emitted, write nothing
node emit-drop.js --all --dry-run

# Emit without handing anything to MeetingMiner
node emit-drop.js --all --no-post

# Tag Epic-5 mock meetings pulled from the same tenant
node emit-drop.js "Scripted Demo/8.1.26" --corpus scripted
```

| Setting | Flag | Env var | Default |
| --- | --- | --- | --- |
| Drops folder | `--drops <dir>` | `MM_DROPS_ROOT` | `/Users/devopsterus/current/meetingminer-drops` |
| API base URL | `--api <url>` | `MM_API_URL` | `http://127.0.0.1:8000` |
| Corpus tag | `--corpus real\|scripted` | `MM_CORPUS` | `real` |

The drops folder is deliberately **outside** this archive: drop contents are
read-only after intake, while re-pulls mutate the archive in place.

The same flags work on `grab-teams-transcript.js`, plus `--no-emit` to skip the
hand-off entirely. **The hand-off never fails a pull** — if the drop cannot be
built or the API is unreachable, the transcript, video, and summaries are still
saved and the tool prints the `emit-drop.js` command to retry with. The intake
POST also times out (30s) rather than waiting forever on an API that answers
the connection but not the request.

`emit-drop.js` talks to MeetingMiner only through the drop layout and
`POST /ingests`: it imports no MeetingMiner code, reads no MeetingMiner config,
and needs no credentials of its own.

## If it can't find the transcript

Re-run with `--headful`, click the **Transcript** tab in the window that opens,
then press Enter. The script retries and captures it.

## How the video download works (and the fallback chain)

The recording is an ordinary `.mp4` in the owner's OneDrive/SharePoint. For a
single recording the script tries, in order:

1. **Source download** — reads the recording's drive/item id from the Stream
   player's own API traffic and fetches a pre-authenticated, item-scoped
   download URL. Works whenever you have download rights.
2. **Archive fallback** — if the source says `403 accessDenied` (you can *view*
   but not *download* — common for recordings shared view-only), it looks for
   the same recording by name in the SharePoint archive folders listed in
   `archives.txt` and downloads it from there (team-site libraries you belong to
   usually allow downloads).
3. **Transcript only** — if neither works, it keeps the transcript and says so.

Downloads stream to disk (no buffering); large files take a while. `--no-video`
skips the video entirely.

## Batch mode: a whole library folder

Pass a **document-library folder URL** (the `…/Forms/AllItems.aspx?id=…` address
from the SharePoint folder view) instead of a Stream URL to mirror the entire
folder — every recording and transcript, recursing subfolders — into a local
folder tree named after the leaf folder:

```bash
# Download everything in the folder (recordings + transcripts)
node grab-teams-transcript.js "<folder-url>"

# Transcripts only
node grab-teams-transcript.js "<folder-url>" --no-video
```

Files already present with a matching size are skipped, so re-runs resume rather
than re-download.

## Indexing the archive

`--index` scans a folder (or the folders in `archives.txt`) and records which
recordings you hold locally — **without downloading anything**:

```bash
node grab-teams-transcript.js "<folder-url>" --index
```

It writes, inside the local archive folder:

- `_index.json` — every recording with size and a `downloaded` / `missing` flag.
- `_index-log.txt` — one timestamped line per run (`N videos: X downloaded, Y missing`).

## Scheduled (automatic) indexing

`index-archives.sh` indexes every folder listed in `archives.txt` and appends to
`index-cron.log`. Run it on demand any time:

```bash
./index-archives.sh
```

A macOS **launchd** agent runs it automatically once a day at **08:00**:
`~/Library/LaunchAgents/com.contoso.grabtranscript.index.plist`.

### Turning the schedule off (or back on)

```bash
# Stop it now and disable it (survives reboot):
launchctl bootout gui/$(id -u)/com.contoso.grabtranscript.index

# Start it again later:
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.contoso.grabtranscript.index.plist

# Remove it permanently: bootout (above), then delete the plist:
rm ~/Library/LaunchAgents/com.contoso.grabtranscript.index.plist

# Check whether it's currently loaded:
launchctl list | grep grabtranscript      # a line = loaded; no output = off

# Run the scheduled job right now (manual trigger):
launchctl kickstart -k gui/$(id -u)/com.contoso.grabtranscript.index
```

To change the time, edit `Hour`/`Minute` in the plist, then bootout and
bootstrap again. To index more archives, add their folder URLs to `archives.txt`.

## When a run fails

If a run fails in a way you need to act on (e.g. the session expired), the
script records it in `.run-state.json` and **surfaces it at the top of the next
run** with a suggested fix. It clears automatically after the next successful
run. The usual fix is re-running `node grab-teams-transcript.js --login`.

## Notes

- Output is verbatim automatic speech recognition; expect occasional mis-hears.
- Only works for recordings you're authorized to view. Your login lives in the
  browser profile; no credentials are stored in the script.

See `CLAUDE.md` for architecture and how the scrape/de-dupe works.
