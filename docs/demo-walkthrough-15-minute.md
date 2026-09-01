# MeetingMiner — 15-minute capstone walkthrough

Companion to `docs/MeetingMiner-15-minute-capstone.pptx` (12 slides). The deck
carries the argument; this carries the live minutes and the exact strings to
type. Every query, URL and number below was run against the live corpus on
2026-08-31, after re-deriving threads and rebuilding both stores, and is
recorded here as verified rather than intended.

---

## Before you present

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
| Argument | 1–6 | 0:00–7:30 |
| **Live demo** | **7** | **7:30–12:30** |
| Close and Q&A | 8–9 | 12:30–15:00 |
| Appendix, only if asked | 10–12 | — |

Slides 10–12 are your strongest material under questioning — the measured
retrieval numbers especially. Do not spend the main fifteen on them.

---

## The live demo (slide 7) — five minutes

Slide 7 plans two arcs. Run them in this order; the second answers the
question the first provokes.

### Arc 1 · Ask → evidence → replay (2:30)

> Everything in this section was re-run on 2026-08-31 after the thread rebuild.
> **About half of all reasonable questions are refused by the citation gate** —
> that is not rare, and you must be ready to name it. The three below passed
> twice each, and every citation carried a screenshot.

**Primary question — verified twice, stable, use this one:**

```
What is the DBE participation goal and how is it tracked?
```

Returns a specific, quotable answer with **one citation carrying a
screenshot**: the goal is 15%, they were running around 22% as of October, and
tracking was "on pause". Numbers, a caveat, and a named pause — the kind of
answer a person actually wanted. It also sets up Arc 2, because DBE is a thread
running through **8 meetings** across 1,360 days.

**Second question — verified twice, two citations, both with screenshots:**

```
What was said about heated sidewalks?
```

Returns a real exchange: someone asks whether heated sidewalks are going in at
the larger stations because ice is treacherous, and someone else answers that
they did consider it and did something on Central. Good because it shows a
conversation rather than a summary.

**Third, if you want range — verified, but the answer varies:**

```
What is the outlook for reopening the Cedar Lake Trail?
```

Sometimes three citations across three meetings spanning 2022 to 2025;
sometimes one. It always passes, but do not promise the three-citation version
from the stage.

**Questions that trigger the citation gate**, to show deliberately — each was
refused on a real run:

```
What are the risks to the 2027 revenue service start date?
What has been reported about tunnel construction progress?
What did they say about ridership trends?
```

The API returns **422 `no-citable-answer`**: *"every sentence must carry at
least one moment marker; this one carries none."* The model wrote a good
answer, one sentence lacked a marker, and the whole thing was rejected. That is
slide 5's promise executing. It reads as an error because it is one, and it is
the strongest possible evidence that the citation boundary is code rather than
a prompt. Say: *"it wrote an answer, one sentence had no evidence behind it, so
you get nothing."*

**Extraction documents are now indexed.** Story 12-4 landed: 224 documents are
in the search index and reachable from search and chat, labelled as unreviewed
machine output. Artifacts are still gated on publishing — 1 of 1,001 — so the
decision tables reach you as documents, not as artifacts.

**Beats:**

1. Type the question in the Ask box. Say: *"one question, across fifty-nine
   meetings."*
2. The answer streams with citations attached. Say: *"every claim carries a
   moment — the meeting, and the exact second."*
3. Click the citation. The moment opens with its screenshot.
4. Press **Replay**. The recording seeks to that second. Let it play three
   seconds with audio.

That is the promise from slide 1, closed in under a minute.

### Arc 2 · Corpus → threads → meeting (2:30)

1. **Threads.** Click **Threads**. The view is empty by design — a box and the
   subjects the corpus suggests. Say: *"a thread is a question you ask, not a
   list you browse."*
2. Choose **Trail reopening outlook (Cedar Lake Trail segments)** — **12 meetings
   across 1,548 days**, March 2022 to June 2026. Or type `trail` and pick from
   the candidates.

   Other verified subjects: Communications/outreach metrics (18 meetings), DBE
   participation (8), Suburban Transit ridership trend (9), Tunnel construction
   progress (7), Hopkins Rail Support Facility (6), Train testing safety
   awareness (6).

   **Avoid the widest threads — they are meeting procedure, not content:**
   "Presentation logistics (screen share)" (47 meetings), "Meeting opening &
   apologies" (22), "Meeting close: announcements". If the suggestions are
   ordered by breadth these sit at the top and they are terrible material.
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
| Threads | 1,473 derived; 130 span 2+ meetings, 48 span 3+, widest 47 |
| Search | 7,000 chunks · 5,292 moments · 224 documents indexed; hybrid BM25 + vector |
| Retrieval (slide 11) | paraphrase: embeddings 60.0% vs BM25 42.5%; exact wording: BM25 37.2% vs embeddings 32.8% |

Slide 11 is the honest one: embeddings lost on 0 of 9 exact-wording tasks and
won 5 of 9 on paraphrase. That is why retrieval is hybrid rather than
fashionable.

---

## Known rough edges — say them before you are asked

- **Six artifact-kind counters read zero** on a moment (Decisions, Stories,
  Requirements, Bug fixes, Change requests). The pipeline produces two kinds;
  those five have no producer. Avoid that panel, or name it as unfinished.
- **Only 4 of 59 meetings have named speakers.** YouTube auto-captions carry no
  speaker labels, and a supplied transcript means diarization never runs.
  Everywhere else the speaker reads `Unknown` or `SPEAKER_03`. The two Green
  Line Corridor Management Committee meetings are named because they were
  re-ingested from the recording alone — **demo from those two** and citations
  look right.
- **About half of all reasonable questions are refused** by the citation gate
  (422 `no-citable-answer`). The model writes a good answer, one sentence lacks
  a moment marker, and the whole answer is rejected. This is the design working,
  but it is frequent enough that you should show it deliberately rather than be
  caught by it.
- **Artifacts are still not searchable** — 1 of 1,001 indexed, because indexing
  is gated on publishing and publishing means export, not visibility. Extraction
  documents *are* now indexed (224 of them, story 12-4), so the decision tables
  reach you as documents rather than as artifacts.
- **Three meetings failed re-extraction** on a malformed model reply. The stage
  refused the document rather than storing a half-parsed one.

Each of these is a boundary you chose to leave visible rather than paper over.
Slide 8 invites the question; answering it plainly is stronger than hoping it
is not asked.

---

## Verified search terms

Exact-phrase hits, run on 2026-08-31 after the rebuild (moments / documents):

| term | moments | documents |
|---|---|---|
| `tunnel` | 107 | 24 |
| `Kenilworth` | 57 | 9 |
| `functional classification` | 52 | 8 |
| `travel demand management` | 48 | 5 |
| `ridership` | 45 | 29 |
| `revenue service` | 40 | 22 |
| `inflow and infiltration` | 36 | 0 |
| `Cedar Lake Trail` | 24 | 8 |
| `landscaping` | 12 | 8 |
| `punch list` | 6 | 3 |

**Do not type these — all return zero moments:** `station art`, `noise wall`,
`participation goal`, `trail reopening`.

`Kenilworth`, `revenue service`, `Cedar Lake Trail`, `landscaping` and
`punch list` hit the meetings that have named speakers, so their results look
best on screen.
