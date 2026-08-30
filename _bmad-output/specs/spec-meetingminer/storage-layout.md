# Storage layout, path anchors, and file provenance

Where every byte of evidence lives, which root its recorded path is relative to, and what the
database says about it. This companion exists because that answer was previously spread across one
sentence of AD-3, two comments in migration `0005`, and a filename constant in `domain/drops.py` —
which is how two sessions came to disagree about where a recording belongs.

Read with `glossary.md` (term definitions) and spine AD-1, AD-3, AD-11, AD-13, AD-14.

---

## 1. Two roots, both configured, both permanent

| | **Drops root** | **Content root** |
|---|---|---|
| Holds | Material that **arrived**: recording, provided transcripts, `metadata.json` | Material this pipeline **produced**: frames, screenshots, extracted audio |
| Written by | The puller's `emit-drop`, or the bring-your-own-recording tool | The worker's pipeline stages |
| Mutability | Write-once per drop; never renamed, rewritten or deleted after finalize (AD-1, AD-13) | A stage overwrites its own outputs on rerun, via stage-then-replace (AD-11) |
| Configured as | `MM_DROPS_ROOT` | `MM_CONTENT_ROOT` |

Both are **permanent storage and must be backed up together**. The drops root is not a landing zone
that can be cleared once a meeting has ingested:

- Provided transcripts store no segments in Postgres. Their text is re-parsed from the drop on every
  stage run (migration `0005` states this in its own comment).
- The augmentation door re-reads an already-ingested occurrence's `metadata.json` to decide whether
  an incoming drop brings anything the meeting lacks (`api/ingests.py` `_target_drop_has_participant_graph`).
- Replay serves the recording out of the drop.

Deleting a drop after ingest therefore breaks replay, breaks any stage rerun, and makes the
augmentation comparison answer "no graph" for a meeting that has one.

**Neither root's absolute path is ever stored in the database or leaves the server.** The database
records a path plus which root it is anchored to; the API and the worker resolve it at use time.
Relocating either root is an environment change, not a data migration.

The publish folder is a **third configured location** and deliberately not a third root. A published
artifact is an export, not evidence: the API writes it once into a git working tree, humans and git
read it there, and no request is ever served by resolving a stored path against it — so nothing
records a path relative to it and the two-anchor rule does not reach it (spine AD-3, AD-4).

## 2. Anatomy of a drop

One directory per drop, under the drops root. Its name is the puller's
`<date>-<title-slug>-<sha1(sourceId)[0:8]>`, with `-002`, `-003`, … siblings for augmenting
re-emits (AD-1). Canonical filenames, pinned by `docs/source-drop.schema.json`:

```
<drops-root>/<drop-dir>/
  metadata.json      required — sourceId, corpus, startedAt + precision, provenance, participants
  recording.mp4      optional — the video, when the source had a downloadable one
  transcript.vtt     optional — VTT cue timing
  transcript.txt     optional — the speaker-attributed `[m:ss] Speaker: text` export
  <extraction docs>  optional — the summariser's architecture-summary and action-items markdown,
                     when the puller produced them; canonical names pinned by the schema addition
```

At least one of the three evidence files — recording, VTT, transcript — must be present; the
extraction documents are derivative and never satisfy that requirement on their own. When they are
present the extract stage parses them instead of calling a model (CAP-5), and each gets its own
per-file provenance row like any other arrived file. Files not named by the schema are ignored
at intake. Nothing in MeetingMiner writes inside a drop — the pipeline reads it and never modifies,
renames, or deletes anything in it (AD-13).

A drop is finalized atomically: its producer assembles in a staging path and moves it into the drops
root complete, so a directory visible under the drops root is always a whole drop.

## 3. The content root tree

```
<content-root>/meetings/<meeting_id>/
  frames/            ffmpeg-sampled JPEGs (the `frames` stage)
  screenshots/       per-screen JPEGs (the `screens` stage)
  audio/             extracted 16 kHz mono WAV for the STT lane (the `transcribe` stage)
```

Keyed by the Postgres-minted `meeting_id`, never by drop name or source id, so a meeting's derived
material survives a re-emit that changes the drop directory. Every write goes through the
containment guard that refuses a symlink at `meetings/`, at the meeting directory, or at the subdir
itself; a stage fails rather than following one out of the root.

## 4. The anchor rule

Every recorded path is relative to exactly one of the two roots, and which one is a property of how
the file came to exist — not of the file's type:

- **Arrived** → anchored to the drops root, recorded as `<drop-dir>/<filename>`.
- **Produced** → anchored to the content root, recorded as `meetings/<meeting_id>/<subdir>/<filename>`.

The recording is *arrived* material and stays in its drop. It is not copied under the content root:
the drop is already permanent by AD-1, so a copy would be a second permanent copy of a permanent
file — multi-gigabyte per meeting against a measured 19.5 GB corpus — and it would fix replay while
leaving transcript re-parse and the augmentation door still resolving through the drop.

AD-3's rule reads correctly under this split: binaries on disk, paths in the DB, no absolute path in
the database and none leaving the server. What AD-3's single sentence omitted was that there are two
roots to be relative *to*.

## 5. Provenance: what the database records per file

Every evidence file has a row that names it. A row carries, at minimum:

| Column | Why |
|---|---|
| The path, relative to its **root** — never to a nearer directory such as the drop's own folder | Resolution without an absolute path, and still resolvable after an augmenting re-emit repoints the job at a sibling drop |
| Which root it is anchored to | Implicit where a table has one column per anchor (`transcript_source.drop_relative_path` vs `content_path`); explicit where a table could hold either |
| `sha256` | Proves whether the bytes changed between runs, and makes a substituted file detectable |
| `byte_size` | Cheap corroboration of the checksum, and the size the API serves |
| The stage that wrote or read it | Which run produced this, for triage |

`transcript_source` (migration `0005`) is the reference for the path/checksum/size triple and for
that alone: it has no `stage` column, and its `drop_relative_path` currently stores a bare filename
rather than a root-relative one. Story 2.1a widens and backfills it. Match the triple; do not copy
the anchor.

A checksum mismatch is read by anchor. For **arrived** material it is a hard stage failure — a
write-once drop whose bytes changed means the write-once rule was broken and nothing derived from it
can be trusted. For **produced** material it is provenance rather than a gate: a rerun legitimately
writes different bytes (ffmpeg output is not bit-reproducible), so the new checksum replaces the old.

**No path may be half data and half code.** Composing a served path from a stored value plus a
hardcoded filename constant is prohibited: it is what left the recording with no checksum and no
row of its own, detectable only because a reviewer happened to compare it against the transcript.

## 6. Bringing your own recording

A local video file is a first-class source (AD-1) and reaches the system the same way a pulled
meeting does — as a drop, never by being handed to the API directly. The user places the video where
a tool can see it and that tool mints a conforming drop: it writes `recording.mp4` and a
`metadata.json` carrying a `sourceId` derived from the file's own content hash, `corpus`,
`startedAt` with its precision, and a `provenance` block naming the local file and who supplied it.
The drop is finalized atomically into the drops root and then POSTed to the intake door.

There is no second ingestion path. Anything that can produce a schema-valid drop can feed
MeetingMiner, and nothing else can.
