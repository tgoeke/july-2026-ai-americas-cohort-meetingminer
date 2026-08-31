# MeetingMiner — 15-minute capstone walkthrough

Companion to `docs/MeetingMiner-15-minute-capstone.pptx` (14 slides). The deck
carries the argument; this carries the live minutes and the exact strings to
type. Every query, URL and number below was run against the live corpus on
2026-08-31 and is recorded here as verified rather than intended.

---

## Before you present

### The one blocker: OpenAI credits are exhausted

`POST /chat` returns **503 `chat-model-unavailable`** — *"You have no credits
remaining."* The system names the outage honestly rather than inventing an
answer, which is the behaviour slide 7 promises, but **Ask does not work until
this is resolved.** Ask is the climax of slide 9.

Two ways out, in order of preference:

1. **Add credits.** Restores the demo exactly as designed. A walkthrough plus
   rehearsals costs cents.
2. **Bind `chat` to a local model** — set `llm.roles.chat.model` to
   `ollama/gpt-oss:120b` in `config.yaml` and restart both api and worker.
   Answers get slower and a little weaker, and you lose the "same model as
   judge" symmetry. Note `chat` deliberately has **no fallback** (owner
   decision, 2026-08-21) precisely so this failure is loud rather than silent.

**What still works without credits:** everything else. Extraction falls back to
a local model, so Add-meeting completes an ingest and reports the substitution.
Search, moments, threads, replay, screenshots and the documents panel need no
model at all.

### Checklist

1. `make up` — stores, migrations, then api/worker/web on the host.
2. Ollama running, with `qwen3-embedding:0.6b`, `gpt-oss:120b` and `qwen3:30b`
   pulled. Search dies without the embedder.
3. Open `http://127.0.0.1:5173`. The header should read **59 meetings ·
   49.8 hours of evidence · 5,292 moments · 3,107 screens**.
4. Browser at `⌘+` twice, other tabs closed, Do Not Disturb on.
5. **Record a fallback run** (`⌘⇧5`) and keep it on the desktop.

---

## Run of show

| | Slides | Minutes |
|---|---|---|
| Argument | 1–8 | 0:00–7:30 |
| **Live demo** | **9** | **7:30–12:30** |
| Close and Q&A | 10–11 | 12:30–15:00 |
| Appendix, only if asked | 12–14 | — |

Slides 12–14 are your strongest material under questioning — the measured
retrieval numbers especially. Do not spend the main fifteen on them.

---

## The live demo (slide 9) — five minutes

Slide 9 plans two arcs. Run them in this order; the second answers the
question the first provokes.

### Arc 1 · Ask → evidence → replay (2:30)

> The deck's scripted question — *"What did the vendor say about API and SFTP
> support?"* — belongs to the earlier prototype corpus and finds **nothing**
> here. Use one of these instead. Both are grounded in this corpus.

**Primary question:**

```
Did they decide to install heated sidewalks at the stations?
```

Chosen because the corpus contains an explicit decision against it, so the
answer is a real finding rather than a summary. The METRO Green Line CMC
meeting's decision document carries it as **D2 — "Do not pursue heated
sidewalks at larger stations"**, with the context that heated sidewalks had
been done on Central previously.

**Backup question**, if the first disappoints:

```
What did we decide about the Cedar Lake Trail closures?
```

Verified to return a cited answer. Worth knowing: it answers *honestly in the
negative* — the moments do not contain a decision beyond noting the Kenilworth
Trail stays closed during construction. **That is a good demo, not a bad one.**
Say so out loud: the system declines to manufacture a decision that was never
made.

**Beats:**

1. Type the question in the Ask box. Say: *"one question, across fifty-nine
   meetings."*
2. The answer streams with citations attached. Say: *"every claim carries a
   moment — speaker, meeting, timecode."*
3. Click the citation. The moment opens with its screenshot.
4. Press **Replay**. The recording seeks to that second. Let it play three
   seconds with audio.

That is the promise from slide 4, closed in under a minute.

### Arc 2 · Corpus → threads → meeting (2:30)

1. **Threads.** Click **Threads**. The view is empty by design — a box and the
   subjects the corpus suggests. Say: *"a thread is a question you ask, not a
   list you browse."*
2. Choose **Trail reopening outlook (Cedar Lake Trail segments)** — 11 meetings
   across 1,542 days. Or type `trail closures` and pick from the candidates.
3. The timeline draws left to right across every meeting where it surfaced.
   **Scroll to zoom.** Say: *"the zoom is semantic — a meeting is a bar up
   here, a card lower down, its own moments at the bottom. Labels stay
   readable, like a map."*
4. Zoom in and **click a meeting**. It opens the meeting view.
5. In the right rail, open **Documents → Decisions & risks**. Say: *"this is
   what the extraction produced — a markdown document per meeting, decisions
   and risks with timestamps. This is the artifact you'd merge or publish."*

### If a minute remains: Add meeting

Click **Add meeting**, paste a public YouTube watch URL, and let the probe
return. It shows the title, duration and whether captions exist. Say: *"auto
captions carry no speaker labels — the system tells you before you commit."*
Do not wait for a full ingest on stage.

---

## Numbers you can quote

| | |
|---|---|
| Corpus | 59 meetings · 49.8 hours · 5,292 moments · 3,107 screens |
| Artifacts | ~1,000 line items, 224 retained markdown documents across 56 meetings |
| Threads | 1,392 derived; 114 span 2+ meetings, 44 span 3+, widest 25 |
| Search | 7,000 chunks indexed, hybrid BM25 + vector |
| Retrieval (slide 13) | paraphrase: embeddings 60.0% vs BM25 42.5%; exact wording: BM25 37.2% vs embeddings 32.8% |

Slide 13 is the honest one: embeddings lost on 0 of 9 exact-wording tasks and
won 5 of 9 on paraphrase. That is why retrieval is hybrid rather than
fashionable.

---

## Known rough edges — say them before you are asked

- **Six artifact-kind counters read zero** on a moment (Decisions, Stories,
  Requirements, Bug fixes, Change requests). The pipeline produces two kinds;
  those five have no producer. Avoid that panel, or name it as unfinished.
- **Speakers are `Unknown` on 29 of 31 meetings.** YouTube auto-captions carry
  no speaker labels, and a supplied transcript means diarization never runs.
  The two Green Line meetings have named speakers because they were re-ingested
  from the recording alone.
- **Artifacts are not searchable.** Indexing is gated on publishing, which is a
  category error already identified and filed — publishing means export to an
  external system, not visibility. Search finds the transcript, not the
  document.
- **Three meetings failed re-extraction** on a malformed model reply. The stage
  refused the document rather than storing a half-parsed one.

Each of these is a boundary you chose to leave visible rather than paper over.
Slide 10 invites the question; answering it plainly is stronger than hoping it
is not asked.
