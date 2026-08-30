---
epic: 1
title: Meeting Ingestion & Evidence Bundle
documentType: user-acceptance-testing-runbook
status: ready-for-operator
date: 2026-08-19
author: Devopsterus
---

# Epic 1 UAT — Operator Runbook

This document walks a human through Epic 1 from an empty development machine to a signed acceptance decision. It includes the folders, fixture files, copy/paste commands, expected responses, interpretation guidance, evidence worksheet, and cleanup.

## 1. What you are testing

MeetingMiner has four moving parts:

1. You place evidence in a **source-drop folder**. It contains `metadata.json` and one or more canonical evidence files.
2. The API validates that folder at `POST /ingests` and creates a **job**. Intake does not process video.
3. The worker claims the job and runs durable checkpoints: `probe → frames → ocr → screens → transcribe → align → moments → extract`.
4. The web app displays the job and marks the meeting **viewable** when all evidence stages through `moments` are `done` or `skipped`.

`extract` is not part of Epic 1's evidence gate. It may remain queued/running because artifact extraction belongs to Epic 4. A viewable meeting is ready evidence; Epic 2 owns the detailed moment/replay screen.

### How to interpret statuses

| Status | Meaning | Operator action |
| --- | --- | --- |
| `queued` | Accepted, waiting for worker. | Wait; do not resubmit. |
| `running` | Worker is processing. | Wait and watch the named stage. |
| `done` | Stage output exists. | Continue. |
| `skipped` | Not applicable, normally no recording. | Expected for transcript-only video stages. |
| `failed` | Stage stopped and stored an error. | Save the error; follow the retry test. |
| `viewable: false` | Evidence is incomplete. | **Open** must remain disabled. |
| `viewable: true` | Evidence through `moments` is complete. | Record the meeting/moment IDs. |

## 2. Prepare a disposable UAT workspace

Run from the repository checkout:

```sh
cd /Users/devopsterus/current/cohort/meetingminer
export UAT_ROOT="$PWD/.uat/epic-1"
export UAT_DROPS="$UAT_ROOT/drops"
export UAT_CONTENT="$UAT_ROOT/content"
export UAT_EVIDENCE="$UAT_ROOT/evidence"
export DROP_COMBINED="$UAT_DROPS/combined-recording"
export DROP_TRANSCRIPT="$UAT_DROPS/transcript-only"
export DROP_INVALID="$UAT_DROPS/invalid-no-evidence"
export DROP_FAILURE="$UAT_DROPS/controlled-failure"
export DROP_AUGMENT="$UAT_DROPS/late-recording-augment"
export DROP_PARTICIPANTS="$UAT_DROPS/participant-graph-augment"
mkdir -p "$DROP_COMBINED" "$DROP_TRANSCRIPT" "$DROP_INVALID" "$DROP_FAILURE" "$DROP_AUGMENT" "$DROP_PARTICIPANTS" "$UAT_CONTENT" "$UAT_EVIDENCE"
find "$UAT_ROOT" -maxdepth 3 -type d | sort
```

You should see `drops/combined-recording`, `drops/transcript-only`, `drops/invalid-no-evidence`, `drops/controlled-failure`, `drops/late-recording-augment`, `drops/participant-graph-augment`, `content`, and `evidence`.

### Configure the content root

The worker writes derived frames below `MM_CONTENT_ROOT`. The drop folders remain outside it.

```sh
test -f .env && echo ".env exists" || echo ".env is missing"
grep '^MM_CONTENT_ROOT=' .env 2>/dev/null || true
```

If `.env` is missing, run `make bootstrap`, then edit `.env` and set this line (replace `your-user`):

```dotenv
MM_CONTENT_ROOT=/Users/your-user/path/to/meetingminer/.uat/epic-1/content
```

Keep the existing password/key lines. Verify the directory:

```sh
mkdir -p "$UAT_CONTENT"
test -w "$UAT_CONTENT" && echo "content root is writable" || echo "content root is NOT writable"
```

## 3. Create the source-drop fixtures

Every valid drop needs `metadata.json` plus at least one of `recording.mp4`, `transcript.vtt`, or `transcript.txt`. Other files are ignored. Use a real authorized MP4 for recording tests; a zero-byte fake will fail `ffmpeg`.

### Fixture A — recording plus transcript

Set the source path first:

```sh
export RECORDING_SOURCE="/absolute/path/to/an/authorized/meeting.mp4"
test -s "$RECORDING_SOURCE" && echo "recording found" || echo "Set RECORDING_SOURCE first"
cp "$RECORDING_SOURCE" "$DROP_COMBINED/recording.mp4"
cat > "$DROP_COMBINED/transcript.txt" <<'EOF'
[0:00] Cameron Ellis: Welcome to the MeetingMiner acceptance test.
[0:12] Drew Collins: We are checking the source drop and evidence bundle.
[0:27] Cameron Ellis: The screen changes here so capture can be reviewed.
EOF
cat > "$DROP_COMBINED/metadata.json" <<'EOF'
{
  "schemaVersion": 1,
  "sourceId": "uat-epic1-combined-20260819",
  "corpus": "scripted",
  "startedAt": "2026-08-19T15:00:00Z",
  "startedAtPrecision": "second",
  "provenance": {"title": "Epic 1 UAT combined recording", "url": "https://example.invalid/uat/combined", "source": "manual-uat"}
}
EOF
```

### Fixture B — transcript only

```sh
cat > "$DROP_TRANSCRIPT/transcript.txt" <<'EOF'
[0:00] Cameron Ellis: This is the transcript-only acceptance path.
[0:08] Drew Collins: There is no local recording in this drop.
[0:19] Cameron Ellis: The meeting should still produce transcript moments.
EOF
cat > "$DROP_TRANSCRIPT/metadata.json" <<'EOF'
{
  "schemaVersion": 1,
  "sourceId": "uat-epic1-transcript-only-20260819",
  "corpus": "scripted",
  "startedAt": "2026-08-19T00:00:00Z",
  "startedAtPrecision": "day",
  "provenance": {"title": "Epic 1 UAT transcript-only meeting", "url": "https://example.invalid/uat/transcript-only", "source": "manual-uat"}
}
EOF
```

### Fixture C — invalid

This folder deliberately has metadata but no recognized evidence file:

```sh
cat > "$DROP_INVALID/metadata.json" <<'EOF'
{
  "schemaVersion": 1,
  "sourceId": "uat-epic1-invalid-20260819",
  "corpus": "scripted",
  "startedAt": "2026-08-19T15:00:00Z",
  "startedAtPrecision": "second",
  "provenance": {"title": "Epic 1 UAT invalid drop"}
}
EOF
find "$UAT_DROPS" -maxdepth 2 -type f -print | sort
```

Expected: combined has three files including `recording.mp4`; transcript-only has metadata and transcript; invalid has only metadata.

## 4. Start the system and learn the normal screen

```sh
make bootstrap
make up
```

Open <http://127.0.0.1:5173>. You should see **MeetingMiner**, **Meetings**, and an `api /health` panel showing `status`, `service`, and `configVersion`. An empty Meetings list is normal before intake.

Verify without the browser:

```sh
curl -i http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/meetings
docker compose --env-file .env -f infra/docker-compose.yml ps
```

Expected: `/health` is HTTP 200, `/meetings` returns JSON with a `meetings` array, and the three store containers are healthy. If startup fails, stop and save:

```sh
tail -n 40 .logs/api.log
tail -n 40 .logs/worker.log
tail -n 40 .logs/web.log
```

## 5. Repeatable intake and polling commands

Use this exact procedure for each “submit” step. It saves the response and returns a job ID.

```sh
export DROP_TO_SUBMIT="$DROP_TRANSCRIPT"
export RESPONSE_FILE="$UAT_EVIDENCE/intake-$(basename "$DROP_TO_SUBMIT").json"
curl -sS -D "$UAT_EVIDENCE/intake-$(basename "$DROP_TO_SUBMIT").headers" \
  -o "$RESPONSE_FILE" -X POST http://127.0.0.1:8000/ingests \
  -H 'content-type: application/json' \
  --data "{\"dropPath\":\"$DROP_TO_SUBMIT\"}"
cat "$RESPONSE_FILE"
```

The first accepted drop should return HTTP 201 and `{"jobId":"UUID"}`. Copy that UUID:

```sh
export JOB_ID="paste-the-jobId-here"
curl -sS "http://127.0.0.1:8000/jobs/$JOB_ID" | jq .
```

Poll while it runs:

```sh
while true; do
  date
  curl -sS "http://127.0.0.1:8000/jobs/$JOB_ID" | jq '{status,error,stages: [.stages[] | {name,status,error}]}'
  sleep 10
done
```

Press `Ctrl+C` when you have observed the needed state. Do not submit again while a job is `queued` or `running`.

## 6. Guided scenarios

### UAT-01 — Environment and health (P0)

**What is happening?** Docker supplies Postgres, Neo4j, and Meilisearch. The API, worker, and web server run on the host. This proves the foundation before evidence is involved.

**Do:** Complete sections 2–4, click **Re-check** in the browser, and save the `/health` response and `docker compose ps` output.

**Pass when:** the page renders, `/health` is 200, all three stores are healthy, and `make up` reports all host processes. `make down` later leaves no stray processes.

Result: ☐ Pass ☐ Fail ☐ Blocked — evidence: ____________________

### UAT-02 — Accept a recording-backed drop (P0)

**What is happening?** The API validates the folder and creates a job; it does not modify the folder or process the MP4.

**Do:** Set `DROP_TO_SUBMIT="$DROP_COMBINED"` and run section 5. Then record the source checksums:

```sh
find "$DROP_COMBINED" -type f -print -exec shasum -a 256 {} \; | tee "$UAT_EVIDENCE/combined-checksums.txt"
```

**Pass when:** HTTP 201 returns one `jobId`; the source folder is unchanged; no second meeting is created. Save the job ID and response.

Result: ☐ Pass ☐ Fail ☐ Blocked — job ID: ____________________

### UAT-03 — Watch live progress and the readiness gate (P0)

**What is happening?** The browser subscribes to server-sent events while also reading `/meetings`. The row can appear before the worker has minted a meeting.

**Do:** Leave the Meetings page open, submit UAT-02 from another terminal, watch the row, and refresh once while it runs.

**Pass when:** stages visibly advance in order; connection says `live` or shows a retry warning; **Open** stays disabled while any evidence stage is unsettled. A later `extract` state does not make the Epic 1 evidence gate fail.

Result: ☐ Pass ☐ Fail ☐ Blocked — screenshot/file: ____________________

### UAT-04 — Confirm a completed evidence bundle (P0)

**What is happening?** “Viewable” is calculated from durable checkpoints, not from the job status string alone.

**Do:** After UAT-02 settles:

```sh
curl -sS "http://127.0.0.1:8000/jobs/$JOB_ID" | tee "$UAT_EVIDENCE/combined-job.json" | jq .
curl -sS http://127.0.0.1:8000/meetings | tee "$UAT_EVIDENCE/combined-meetings.json" | jq '.meetings[] | select(.jobId == "'"$JOB_ID"'")'
```

Copy the returned `meetingId` into `COMBINED_MEETING_ID`.

**Pass when:** `probe` through `moments` are `done`, `viewable` is true, and the same meeting ID appears in API/UI evidence.

Result: ☐ Pass ☐ Fail ☐ Blocked — meeting ID: ____________________

### UAT-05 — Complete a transcript-only meeting (P0)

**What is happening?** No recording means video stages are deliberately skipped. Transcript alignment and transcript-derived moments still make the meeting complete.

**Do:** Set `DROP_TO_SUBMIT="$DROP_TRANSCRIPT"`, run section 5, and poll the job.

**Pass when:** `probe`, `frames`, `ocr`, `screens`, and `transcribe` are `skipped`; `align` and `moments` are `done`; the UI shows **transcript only**; `viewable` becomes true; no screenshot is expected.

Result: ☐ Pass ☐ Fail ☐ Blocked — job ID: ____________________

### UAT-06 — Reject invalid input safely (P0)

**What is happening?** Intake must reject a bad drop before a job row exists.

```sh
curl -i -sS -X POST http://127.0.0.1:8000/ingests \
  -H 'content-type: application/json' \
  --data "{\"dropPath\":\"$DROP_INVALID\"}" \
  | tee "$UAT_EVIDENCE/invalid-response.txt"
curl -sS http://127.0.0.1:8000/meetings | jq '.meetings[] | select(.sourceId == "uat-epic1-invalid-20260819")'
```

**Pass when:** response is HTTP 422 with `application/problem+json`, says no recording/transcript is present, and the second command prints nothing.

Result: ☐ Pass ☐ Fail ☐ Blocked — response file: ____________________

### UAT-07 — Reject a duplicate source (P0)

**What is happening?** `sourceId` identifies one occurrence; resubmitting a live or completed occurrence must not create a second meeting.

```sh
curl -i -sS -X POST http://127.0.0.1:8000/ingests \
  -H 'content-type: application/json' \
  --data "{\"dropPath\":\"$DROP_COMBINED\"}" | tee "$UAT_EVIDENCE/duplicate-response.txt"
```

**Pass when:** response is HTTP 409, identifies a duplicate source, and the Meetings list still has one row for that source ID.

Result: ☐ Pass ☐ Fail ☐ Blocked — evidence: ____________________

### UAT-08 — Observe and retry a failure (P1)

**What is happening?** The worker must persist the failed stage/error rather than silently swallowing it. The source drop remains an immutable input.

Prepare a unique malformed recording:

```sh
cp "$DROP_COMBINED/metadata.json" "$DROP_FAILURE/metadata.json"
cp "$DROP_COMBINED/transcript.txt" "$DROP_FAILURE/transcript.txt"
sed -i '' 's/uat-epic1-combined-20260819/uat-epic1-failure-20260819/' "$DROP_FAILURE/metadata.json"
printf 'not a video' > "$DROP_FAILURE/recording.mp4"
export DROP_TO_SUBMIT="$DROP_FAILURE"
```

Submit with section 5 and poll. If intake itself rejects the malformed file, save that response; it is still a real boundary result. If the worker claims it, inspect:

```sh
curl -sS "http://127.0.0.1:8000/jobs/$JOB_ID" | jq .
grep -n "$JOB_ID" .logs/worker.log | tail -n 30
```

After the job is `failed`, submit the same drop once more. **Pass when:** the failed stage, readable error, and timestamp are visible in API/UI/logs; retry behavior is documented; the drop was not edited or deleted.

Result: ☐ Pass ☐ Fail ☐ Blocked — stage/error: ____________________

### UAT-09 — Review correlated logs (P1)

**What is happening?** Logs are the operator’s evidence after the browser is closed.

```sh
grep -n "$JOB_ID" .logs/worker.log | tail -n 30
```

**Pass when:** relevant entries contain both the same `job_id` and a stage, and failures contain useful text.

Result: ☐ Pass ☐ Fail ☐ Blocked — log lines: ____________________

### UAT-10 — Review screen evidence (P1)

**What is happening?** Capture quality cannot be accepted from a green job alone; a human must compare derived frames with the source video.

```sh
find "$UAT_CONTENT" -type f -print | sort | tee "$UAT_EVIDENCE/content-files.txt"
```

Open representative image files in Finder/Preview. Check a settled shared-screen frame, a screen change, and a gallery/loading transition if present. For the measured 57-minute fixture, record `screenshot count / 57`; target is under one capture per minute.

**Pass when:** captures are settled share-region evidence, webcam/gallery noise is not misclassified as an application screen, and transitions are retained/tagged rather than silently lost.

Result: ☐ Pass ☐ Fail ☐ Blocked — count/duration/files: ____________________

### UAT-11 — Verify transcript, people, and provenance (P1)

**What is happening?** The evidence bundle must preserve what was supplied and separately retain derived alignment/identity decisions.

Use the team’s development database inspection tool to inspect rows for `COMBINED_MEETING_ID`. Compare the original transcript byte-for-byte with the provided transcript row. Capture one transcript segment, speaker, participant identity, moment ID, UTC time, video offset, and provenance URL.

**Pass when:** supplied text is verbatim; derived alignment has provenance; mail-keyed participants dedupe; unresolved/ambiguous speakers remain unresolved instead of being guessed.

Result: ☐ Pass ☐ Fail ☐ Blocked — export/query file: ____________________

### UAT-12 — Validate projections and rebuild (P1)

**What is happening?** Postgres is authoritative; Neo4j and Meilisearch are regenerable projections.

```sh
curl -sS http://127.0.0.1:7700/health
open http://127.0.0.1:7474
```

In Neo4j Browser, connect with the `.env` credentials and run:

```cypher
MATCH (n) WHERE n.meetingId = 'REPLACE_WITH_COMBINED_MEETING_ID' RETURN labels(n), n LIMIT 20;
```

For Meilisearch, do not save the key in the UAT record:

```sh
curl -sS -H "Authorization: Bearer $MEILI_MASTER_KEY" http://127.0.0.1:7700/indexes | jq .
```

Only after saving pre-rebuild evidence, run `make rebuild` against this disposable corpus, then repeat the checks.

**Pass when:** projected IDs exactly match API/Postgres IDs, rebuild restores the same records, and stale records are removed. If the embedder is unavailable but structural indexing succeeds, record that limitation explicitly.

Result: ☐ Pass ☐ Fail ☐ Blocked — pre/post evidence: ____________________

### UAT-13 — Exercise Teams puller (optional P1)

**What is happening?** The puller is a black-box source-side tool. It emits a write-once drop and posts only its path to `/ingests`.

Skip if you do not have an authorized Teams session. Otherwise:

```sh
cd pull_transcript
npm install
npx playwright install chromium
node grab-teams-transcript.js --login
```

Sign in, press Enter, then run a permitted recap URL:

```sh
node grab-teams-transcript.js "PASTE_AUTHORIZED_STREAM_URL_HERE"
node emit-drop.js --all --dry-run
cd ..
```

**Pass when:** a finalized drop contains `metadata.json` and canonical evidence files; re-running reports existing rather than overwriting; HTTP 201 means queued and HTTP 409 means already ingested, not a new failure; no server credentials or Graph integration is required.

Result: ☐ Pass ☐ Fail ☐ Skipped — drop/result: ____________________

### UAT-14 — Augment transcript-only with recovered video (P0)

**What is happening?** Late video re-arms the existing occurrence. It must not create a second meeting or invalidate old moment IDs.

Prepare with the same target transcript and a real recovered recording:

```sh
export TARGET_SOURCE_ID="uat-epic1-transcript-only-20260819"
export RECOVERED_RECORDING="/absolute/path/to/recovered-recording.mp4"
cp "$RECOVERED_RECORDING" "$DROP_AUGMENT/recording.mp4"
cp "$DROP_TRANSCRIPT/transcript.txt" "$DROP_AUGMENT/transcript.txt"
cat > "$DROP_AUGMENT/metadata.json" <<EOF
{
  "schemaVersion": 2,
  "sourceId": "uat-epic1-recovered-recording-20260819",
  "corpus": "scripted",
  "startedAt": "2026-08-19T00:00:00Z",
  "startedAtPrecision": "day",
  "provenance": {"title": "Epic 1 UAT late recording", "url": "https://example.invalid/uat/recovered", "source": "manual-uat"},
  "augments": {"sourceId": "$TARGET_SOURCE_ID"}
}
EOF
```

Save the transcript-only meeting JSON and moment IDs before submission. Submit `$DROP_AUGMENT` with section 5; expect HTTP 200 and the existing job ID.

**Pass when:** only previously skipped video stages plus `align`/`moments` re-run; meeting ID and old moment IDs remain; screenshots/replay evidence replaces transitional links where supported; new screen-derived moments are allowed; only this meeting is re-projected.

Result: ☐ Pass ☐ Fail ☐ Blocked — before/after files: ____________________

### UAT-15 — Add participant graph (Story 1.13 RC, P1)

**What is happening?** Directory identity should reach the drop so people are keyed by mail, not spelling variations. The current intake contract still requires an evidence file, so carry the target transcript unchanged.

```sh
export PARTICIPANT_TARGET_SOURCE_ID="uat-epic1-transcript-only-20260819"
cp "$DROP_TRANSCRIPT/transcript.txt" "$DROP_PARTICIPANTS/transcript.txt"
cat > "$DROP_PARTICIPANTS/metadata.json" <<EOF
{
  "schemaVersion": 2,
  "sourceId": "uat-epic1-participant-graph-20260819",
  "corpus": "scripted",
  "startedAt": "2026-08-19T00:00:00Z",
  "startedAtPrecision": "day",
  "provenance": {"title": "Epic 1 UAT participant graph", "source": "manual-uat"},
  "participants": [
    {"displayName":"Cameron Ellis","mail":"alex.morgan@example.invalid","title":"Product Lead","department":"Product","reportingChain":["Executive"]},
    {"displayName":"Drew Collins","mail":"casey.lee@example.invalid","title":"Engineer","department":"Engineering","reportingChain":["Engineering Lead"]}
  ],
  "augments": {"sourceId":"$PARTICIPANT_TARGET_SOURCE_ID"}
}
EOF
```

Submit it with section 5. Expect HTTP 200 and the existing target job ID. Inspect participant rows using the development database inspection tool.

**Pass when:** mail keys dedupe people, extra fields are retained, previous aliases still resolve, and unresolved external people are not guessed.

Result: ☐ Pass ☐ Fail ☐ Blocked — evidence: ____________________

### UAT-16 — Recover the browser after a lost stream (P2)

**What is happening?** The UI should warn and resync rather than silently displaying stale or empty data.

With Meetings loaded, disconnect browser network for 10–20 seconds, then restore it. **Pass when** a lost-stream warning appears, rows are retained, and the list converges after recovery.

Result: ☐ Pass ☐ Fail ☐ Blocked — screenshots: ____________________

### UAT-17 — Verify configuration and localhost binding (P2)

```sh
grep -nE '^(config_version|service|pipeline|projections|stores|embedder):' config.yaml
grep -nE '^(MM_CONTENT_ROOT|POSTGRES_PASSWORD|NEO4J_PASSWORD|MEILI_MASTER_KEY)=' .env | sed -E 's/=.*/=<redacted>/'
docker port meetingminer-postgres
docker port meetingminer-neo4j
docker port meetingminer-meilisearch
```

**Pass when:** settings are in `config.yaml`, secrets/content root are in `.env`, and store ports show `127.0.0.1` rather than `0.0.0.0`.

Result: ☐ Pass ☐ Fail ☐ Blocked — redacted output: ____________________

## 7. Evidence-bundle worksheet

Complete one column for the recording-backed meeting and one for transcript-only. `N/A` is valid only where video does not exist.

| Evidence | Recording-backed | Transcript-only |
| --- | --- | --- |
| job ID / meeting ID | | |
| source ID / corpus | | |
| job status and stage list | | |
| UUIDv7-style meeting and moment IDs | | |
| provided transcript checksum | | |
| derived alignment/provenance | | |
| participant identity/unresolved case | | |
| screenshots | | N/A |
| moment UTC time/video offset | | |
| replay evidence or transitional source link | | |
| Neo4j matching ID | | |
| Meilisearch matching document | | |

## 8. Acceptance decision and cleanup

Accept Epic 1 only when all P0 cases pass, all P1 cases pass or have an owner/reason/expiry waiver, and this worksheet is complete. P2 failures require triage but do not automatically block acceptance.

| Field | Value |
| --- | --- |
| Tester / date | |
| Git commit | |
| UAT root | `.uat/epic-1/` |
| Combined job / meeting ID | |
| Transcript-only job / meeting ID | |
| Augmentation job / meeting ID | |
| P0 failures | |
| P1 waivers | |
| Final decision | ☐ Accept ☐ Accept with waiver ☐ Do not accept |

Stop the application after recording results:

```sh
make down
```

Keep `.uat/epic-1/` until the decision is reviewed. Then remove only that exact disposable folder if permitted:

```sh
rm -rf "$PWD/.uat/epic-1"
```

This removes only UAT fixtures/evidence, not original recordings or Docker volumes.

## Troubleshooting

### API/web will not start

```sh
tail -n 80 .logs/api.log
tail -n 80 .logs/worker.log
tail -n 80 .logs/web.log
make down
```

Fix the named configuration, port, or content-root problem and run `make up` once. Do not reset or clean the repository.

### Job remains queued

```sh
cat .logs/worker.pid
kill -0 "$(cat .logs/worker.pid)" && echo "worker process is alive"
grep -n 'worker.startup' .logs/worker.log | tail -n 5
```

Save the output. A missing worker startup event is an environment problem, not an ingestion result.

### Drop is rejected

```sh
test -d "$DROP_TO_SUBMIT" && echo "folder exists"
find "$DROP_TO_SUBMIT" -maxdepth 1 -type f -print
python -m json.tool "$DROP_TO_SUBMIT/metadata.json"
```

The API requires an absolute directory, readable valid `metadata.json`, and at least one canonical evidence file. It ignores other filenames.

## References

- [Epic 1 requirements](../planning-artifacts/epics.md)
- [Epic 1 context](../implementation-artifacts/epic-1-context.md)
- [Source-drop schema](../../docs/source-drop.schema.json)
- [Teams puller guide](../../pull_transcript/README.md)
- [Current sprint status](../implementation-artifacts/sprint-status.yaml)
