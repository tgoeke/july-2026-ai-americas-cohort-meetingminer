# docs

Project documentation, plus the one contract that is not a document:
[`source-drop.schema.json`](source-drop.schema.json), the versioned source-drop
contract every producer validates against (AD-1). `agent-kickoff-prompt.md` is
the prompt used to start an agent on this repository.

---

## Bringing your own recording

You have a video on disk — a screen recording, a downloaded meeting, a scripted
fixture you just recorded — and you want MeetingMiner to ingest it.

### What has to exist first

**A source drop.** Evidence never enters MeetingMiner as a loose file. It enters
as a *drop*: one directory holding a required `metadata.json` and at least one
of `recording.mp4`, `transcript.vtt`, `transcript.txt`. A drop is write-once —
once it is finalized nothing renames, rewrites, or deletes it — and it is the
only thing the system consumes. The Teams puller emits drops; so does the
command below; nothing else can feed the pipeline.

**A drops root.** `MM_DROPS_ROOT` in `.env` is the directory those drops live
in. It is permanent, backed-up storage, not a landing zone: replay serves the
recording out of the drop, transcripts are re-parsed from it on every stage run,
and the augmentation door re-reads its `metadata.json` long after ingest. The
command reads the value out of `.env`; you do not restate it.

**Nothing watches the folder.** Copying a directory into the drops root ingests
nothing. The producer tells intake about the drop, and there is no other door.

**`ffprobe` on `PATH`, for a video.** Minting from an `.mp4` checks the file is
really a video and reads its `creation_time`; both need `ffprobe` (`brew install
ffmpeg`). `make bootstrap` verifies it, but `make mint-drop` deliberately does
not depend on the rest of the stack, so a machine that skipped bootstrap gets a
named refusal instead. Minting from a transcript alone needs nothing.

### The command

```bash
make mint-drop MINT_ARGS="'~/Downloads/standup.mp4' --corpus scripted --title 'Daily Standup'"
```

or, equivalently, from `server/`:

```bash
.venv/bin/python -m meetingminer.mintdrop ~/Downloads/standup.mp4 \
    --corpus scripted --title 'Daily Standup'
```

It copies the file into a new drop under `MM_DROPS_ROOT`, writes a conforming
`metadata.json` beside it, and POSTs the finished drop to `POST /ingests`.

The arguments worth knowing:

| Argument | What it does |
|---|---|
| `FILE ...` | the evidence. `.mp4` becomes `recording.mp4`, `.vtt` becomes `transcript.vtt`, `.txt` becomes `transcript.txt`. Pass a video, a transcript, or both — a transcript-only meeting is first-class. Two files that would take the same canonical name (two `.mp4`s) are refused. |
| `--corpus scripted\|real` | **required**, never guessed. `scripted` meetings are eval subjects; `real` ones are demo corpus only. The tag lands on the meeting row. |
| `--title` | the meeting's human label, shown in the app. Defaults to the stem of the *primary* file — the recording when you supply several, otherwise the transcript. |
| `--started-at` | when the meeting started: `2026-08-05T12:00:19Z` (any explicit offset works and is converted to UTC), or `2026-08-05` for a day you know without a time. Optional only when the video carries its own `creation_time`. |
| `--supplied-by` | who provided the file, recorded in the drop's provenance. Defaults to the account running the command. |
| `--drops DIR` | mint into `MM_DROPS_ROOT` itself or a child directory beneath it, except its reserved `.staging` assembly area. A sibling or external root is refused before staging, because intake stores only drops-root-relative paths. |
| `--api URL` | the api to hand the drop to. Defaults to `$MM_API_URL`, else `http://127.0.0.1:8000`. It must be an HTTP(S) base URL with a host and no query or fragment. |
| `--no-post` | mint the drop but do not call the api; print the request instead. |

### What it prints, and what to do with it

```
created  /Volumes/evidence/drops/2026-08-05-daily-standup-4a5a0a9f
           sourceId  sha256:522b4c1cd0e813a7188d87f8138d2068b263fa2af1acf75a01f027deadde8821
           startedAt 2026-08-05T12:00:19Z (second), corpus scripted
           files     metadata.json, recording.mp4
           intake created (201) jobId 0f7c3a52-6d41-4a0e-9b8e-2d5f1c9a7e30
```

That is the whole procedure: the job is queued, the worker picks it up, and the
meeting appears in the app as it processes. Nothing else is required of you.

The first word is the outcome:

- **`created`** — a new drop was minted.
- **`exists`** — this exact content was already minted. Identity is the primary
  file's own `sha256`, so re-running on the same file finds the drop you already
  have rather than making a second one; a different `--title` or `--started-at`
  does not change that. Nothing is rewritten.
  - If the re-run supplies evidence the existing drop does not hold — you minted
    a video, and now pass the video *and* a transcript — an `ignored` line names
    it. That evidence is **not** added: a finalized drop is never written into,
    and bringing it to the meeting is an *augmenting* drop, which this command
    does not emit. Nothing is lost, but nothing happens either.
  - Adding a video to a transcript-only drop is a different case: the recording
    becomes the primary file, so the content hash — and therefore the identity —
    is a new one, and you get a second drop that intake reads as a second
    meeting. Mint the video and the transcript together in one command.

And the line after `intake`:

- **`created` / `requeued`** — the job is queued. You are done.
- **`already ingested`** — this occurrence is already in the system. Also fine;
  the command exits 0.
- **`intake FAILED`** — the drop is minted and finalized; only the hand-off
  failed (most often: the api is not running — `make up`). The command prints
  the exact `curl` for **that drop**; run it once the api is up. Re-running the
  same `mint-drop` command works too — it reports `exists` and POSTs that drop
  again — but the `curl` needs nothing except the drop, so it still works after
  you have moved or deleted the file you minted from.

`--no-post` ends at the same `curl`, for when you want to mint now and ingest
later.

### When it refuses

It refuses before writing anything, rather than leaving a drop that can never be
ingested and can never be deleted:

- **No `--started-at`, and the video carries no `creation_time`.** A meeting's
  wall clock is never taken from the file's modification time — copying and
  downloading reset it, and a wrong start time cannot be corrected once the drop
  is written. Pass `--started-at`. (A `creation_time` sitting at the 1904 or 1970
  epoch counts as none: that is a recorder saying it did not know.)
- **The file is not a video.** Checked with `ffprobe` up front, so a renamed
  document or an audio-only file is caught here rather than at ingest.
- **`ffprobe` is not installed** and you supplied a video. Named as such — the
  refusal is about the missing tool, not about your file.
- **Nothing ingestible was supplied**, or a file whose extension is none of
  `.mp4` / `.vtt` / `.txt`.
- **Two files map to the same canonical name** — two `.mp4`s, say. A drop holds
  one of each, so the second would silently be the only one kept.
- **A supplied file is empty**, unreadable, or not there.
- **The drops root cannot be written to**, or does not exist.
- **`--drops` is outside `MM_DROPS_ROOT`, or inside its reserved `.staging`
  assembly area.** A normal nested directory is accepted; either invalid
  placement is rejected before staging so no permanent, un-ingestible drop can
  be created.
- **A drop directory carrying this content's digest exists but its
  `metadata.json` cannot be read.** "Cannot tell" must not read as "not there",
  so the command stops and names the directory: look at it yourself, because
  minting past it would put a second write-once drop for the same content in the
  root.
- **`--api` is not an HTTP(S) base URL with a host, or carries a query or
  fragment.** Checked before anything is minted, so an unusable url never costs
  you a finalized drop plus a re-POST line that cannot be run.

A failure part-way through leaves nothing behind: the drop is assembled in a
staging directory under the drops root and moved into place with a single
rename, so a directory visible in the drops root is always a whole drop.

### What it never does

It does not copy anything back to where your file came from, modify the
original, transcode or re-encode the copy (`recording.mp4` is byte-identical to
what you supplied), write inside a drop that already exists, or open a second
way into the pipeline.

### Hand-authoring a drop

Don't. The schema is the contract, not the procedure: a hand-written
`metadata.json` has to get the content-derived `sourceId`, the `startedAt`
precision pair, the embedded provenance, and the atomic finalize right, and a
drop that gets any of them wrong is write-once and unusable. Use the command; it
validates what it produces against `source-drop.schema.json` before the drop
becomes visible.

## Ingesting a YouTube video

`make youtube-drop URL=<url>` turns a published YouTube video into a source
drop and hands it to the same intake door as everything else:

    make youtube-drop URL='https://www.youtube.com/watch?v=jNQXAC9IVRw'

Watch, `youtu.be`, and Shorts URLs all work; a `&list=` on a watch URL is
ignored (the single video is acquired — playlists are not supported). The
recording lands as a browser-playable MP4; the caption track is English manual
captions when the video has them, otherwise the auto-generated ones, converted
to VTT — a video with no English captions still mints a valid, recording-only
drop. `corpus` is always `real`, and `startedAt` comes from the video's own
publish metadata (`release_timestamp` at second precision, else `upload_date`
at day precision).

Like `mint-drop`, it refuses **before writing anything**, each refusal named:

- the URL is not a YouTube *video* URL (a playlist-only URL is refused);
- `yt-dlp` or `ffmpeg` is not on PATH (`brew install yt-dlp ffmpeg`) — checked
  at run time, by name; `make check-tools` knows nothing about them;
- the video is private or removed (the refusal carries yt-dlp's own message);
- the video has no video stream;
- it is longer than `acquisition.youtube.max_duration_minutes` (config.yaml,
  default 180);
- it carries neither `release_timestamp` nor `upload_date` — a wall clock is
  never guessed from a file's mtime.

Re-running on a video already minted reports `exists` before anything is
downloaded — `youtube:<videoId>` is the drop's `sourceId`, so the check needs
no network — and still POSTs that drop, which is how a dropped hand-off is
recovered. `--no-post`, `--drops`, and `--api` behave exactly as `mint-drop`'s
(pass them in `YT_ARGS='--no-post'`); the sections above on what the output
means and what the command never does apply here unchanged. The video's
`info.json` is read for metadata and never copied into the drop.
