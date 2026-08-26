# Run sheet — demo-001 "Scripted UI Demo — Orders Module" (ui-demo, 12 min)

Derived from `evals/ground-truth/demo-001-orders-ui-demo.yaml` — the manifest
is the contract; this sheet is how a human executes it. Timestamps are elapsed
time from **recording start**: start the Teams recording AND transcription the
moment the meeting begins, and keep a visible timer. The citation window is
±15s (`eval-design.md` §2.5), so hitting each mark within a few seconds is
enough — do not stop the clock to be exact.

**Participants:** Tim Goeke (presenter), Tiffany Goeke (reviewer). If the
reviewer is someone else, update `participants:` in the ground-truth YAML
*before* the recording is processed — ground truth is authored by
construction, and it must name whoever actually attends.

**Screens:** open `demo-001-screens.html` in a browser tab before the meeting;
it pages through the four screens with arrow keys. Each carries its planted
OCR anchor verbatim.

| Clock | Action |
|---|---|
| 00:00 | Meeting + recording start. Cameras on, **no screen share yet** (participant segment 1). Greet, one sentence of framing. |
| 00:01:30 | Share the browser. **Screen 1 "Order List"** (anchor: *Order Search Results*). Talk through the list view. |
| 00:03:05 | Arrow to **Screen 2 "Order Detail"** (anchor: *Line Items and Tax Breakdown*). |
| 00:03:20 | Tim says the planted phrase, naturally in a sentence: **"…we'll slot that into the purple elephant deployment window."** (P1) |
| 00:04:12 | Tim states action item AI1 verbatim: **"Update the tax table mapping by Friday."** (own the task aloud: "I'll update the tax table mapping by Friday.") |
| 00:05:40 | Arrow to **Screen 3 "Tax Table Admin"** (anchor: *Tax Table Mapping Editor*). |
| 00:06:02 | Tim states decision D1: **"The Orders module keeps optimistic locking."** Say it as a decision ("we've decided…"). |
| 00:08:55 | Arrow to **Screen 4 "Fulfillment Queue"** (anchor: *Fulfillment Queue Pending Pick*). |
| 00:09:40 | **Stop sharing** (participant segment 2). Closing discussion on camera. |
| 00:09:58 | Tiffany states action item AI2: **"I'll re-run the fulfillment backlog report after the fix."** |
| ~00:12:00 | Wrap up, stop recording, end meeting. |

**Expected captures (the recall denominator):** 4 screens + 2 participant
segments = 6. Every screen must be visibly on screen long enough to be a
distinct captured frame — a beat of silence on each new screen helps nothing;
just don't flash past one in under a couple of seconds.

## What actually matters (checked against the harness)

Screens/slides match by **OCR anchor**, participant segments by **count** —
their timestamps never enter the checks; the table above is pacing only.
Say the planted **phrase verbatim**; action items fuzzy-match and decisions
are judged, so natural phrasing around the key nouns is fine. The one exact
dependency is check 2.5's ±15s citation window against each planted item's
`at` — so after the meeting, true-up the `at` values in the ground-truth YAML
from the actual recording (reading the raw VTT/video is legitimate; the
independence rule bars extractor output, not source evidence). True-up the
**speaker names the same way**: whatever label the transcript actually shows
for Tiffany (e.g. "Goeke, Tiffany") is what `participants:` and each planted
item's `speaker:` must carry — attribution never guesses, so a mismatched
name is an unresolved speaker, not a near-match.

## After the meeting

The recording and its transcript are reachable only from the **work laptop's**
Teams session; MeetingMiner runs on the **engineering laptop**. The pull
therefore happens there and a finished drop travels back. The puller is what
makes this two-machine split necessary rather than a manual download: a `.vtt`
pulled by hand from Teams carries no speaker — `parse_vtt` sets
`speaker_label=None` unconditionally (AD-13) — and this manifest's planted
items each name a `speaker:`.

**On the machine holding the Teams session** — `npm install` and
`node grab-teams-transcript.js --login` once, on that machine.
2. `node grab-teams-transcript.js "<stream-url>" --no-emit --no-summary`
   — the transcript, VTT and recording. `--no-summary` because the summariser's
   Ollama host is on the engineering LAN.
3. `node grab-org-chart.js "<stream-url>" --from "<...>.txt"` — the participant
   graph, before the drop is built. A drop is write-once, so participants
   cannot be added afterwards.
4. `node emit-drop.js "<Title>/<M.D.YY>" --no-post --drops ./outbox --corpus scripted`
   — **`scripted`**, or this meeting is not an eval subject.
5. Copy `outbox/<drop-directory>` to the share, name unchanged. Nothing else
   leaves that machine — never `.transcript-profile`.

**On the engineering laptop:**

6. Move the drop directory into `MM_DROPS_ROOT`, then
   `make ingest-drop DROP=<that directory>`.
7. `GET /meetings` (or the web meetings list) → copy the new meeting's
   `sourceId`.
8. Replace `placeholder-demo-001-not-yet-recorded` in
   `evals/ground-truth/demo-001-orders-ui-demo.yaml` with that id; commit.
9. True-up the `at` values and speaker names per "What actually matters" above.
10. The subject selector now matches the manifest; `make evals-run` per
    `evals/RUNBOOK.md`.
