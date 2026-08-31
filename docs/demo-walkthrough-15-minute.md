# MeetingMiner — 15-minute capstone walkthrough

Companion to `docs/MeetingMiner-15-minute-capstone.pptx` (14 slides). The deck
carries the argument; this carries the live minutes and the exact strings to
type. Every query, URL and number below was run against the live corpus on
2026-08-31 and is recorded here as verified rather than intended.

---

## Before you present

### Credits — resolved, and worth understanding

Credits ran out mid-afternoon on 2026-08-31 and `POST /chat` returned **503
`chat-model-unavailable`**. $17.49 was added and Ask works again.

**Two numbers on the OpenAI dashboard mean different things**, and confusing
them cost time here. *Usage against a budget limit* — "$50.77 / $100.00" — is
what you have spent this period against a ceiling you set. The *API credit
balance* is the pot the API actually draws from. Only the second one stops
calls, and its error is specific: `credit_balance_exhausted`, HTTP 429.

**If Ask returns 503 on the day**, check the credit balance, not the usage
figure. To confirm it is billing and not the app, call OpenAI directly — the
app's own error repeats the provider's message verbatim, so a direct call
settles it in seconds.

**What a credit outage does and does not break.** Ask dies, because `chat`
deliberately has no fallback (owner decision, 2026-08-21) so the failure is
loud. Everything else survives: extraction falls back to a local model, and
search, threads, moments, replay, screenshots and the documents panel use no
paid model at all.

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

**Primary question — verified, and the one to use:**

```
What is the DBE participation goal and how is it tracked?
```

It returns a specific, quotable answer with **two citations, both carrying
screenshots**: the goal is 15%, they were running around 22% as of October, and
credit counting was "on pause". Numbers, a caveat, and a named pause — the kind
of answer a person actually wanted. It also sets up Arc 2, because DBE is a
thread running through **8 meetings**.

**Backup, if you want a second:**

```
What are the risks to the 2027 revenue service start date?
```

Returns a cited answer that is honest in the negative — the moments do not state
specific risks beyond not being ready to pinpoint the date. Say that out loud:
the system declines to manufacture risks nobody named.

**Two questions that trigger the citation gate**, which you may show
deliberately or must be ready to explain if you hit one:

```
What was said about heated sidewalks?
What did they say about the Cedar Lake Trail reopening?
```

Both are **refused**, not answered: *"every sentence must carry at least one
moment marker; this one carries none."* That is slide 7's promise executing —
the draft failed validation and no answer was streamed. It reads as an error
because it is one, and it is the strongest possible evidence that the citation
boundary is code rather than a prompt. If it happens live, name it and move on.

**Why Ask is thinner than the rest of the demo.** Retrieval runs over transcript
passages. The crisp material — the decision tables, the risks with timestamps —
lives in the extraction documents, and **those are not indexed** (1 of 1,001
artifacts, and no documents index at all). Story 12-4 is built and reviewed but
unlanded; landing it would put those documents into retrieval and make Ask
markedly better. Worth doing before the recording if there is time.

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
