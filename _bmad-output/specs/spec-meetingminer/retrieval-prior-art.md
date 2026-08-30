# Retrieval Prior Art

Companion to `SPEC.md` (CAP-2, CAP-3, CAP-9). A hybrid graph + vector + full-text retrieval layer
has already been built and run against this exact corpus at production scale by the upstream
puller tool. What transfers is the schema shape, the retrieval design, and a set of constraints
that were learned by hitting them — not the implementation, which is a different language and a
different store.

**Discovered 2026-08-18.** Read before designing the projections and retrieval stores; several
decisions below are cheaper to adopt than to re-derive.

## 1. What is already proven on this corpus

One embedded store holds three retrieval substrates with no server and no egress: a graph of
people, reporting lines, meetings, series, topics, decisions, actions and risks; an HNSW vector
index over transcript-chunk embeddings; and a BM25 full-text index over the same chunks.
Retrieval fuses BM25 and vector hits by reciprocal rank, then **expands through the graph** — the
speakers of a hit chunk, its meeting, that meeting's decisions/actions/risks, and the org context
of anyone named in the question.

This de-risks CAP-3 and CAP-9 substantially: hybrid retrieval with graph expansion and citation
edges is a known quantity on this content, not an open question.

**The citation edge already exists.** Every extracted decision, action, and risk carries an
evidence edge to the exact transcript chunk that produced it — *no citation, no answer*, already
running in the transcript dimension.

**What it cannot do: there is no notion of a screen anywhere.** Every citation points at words.
That gap is precisely MeetingMiner's committed slice, and it is why the two halves belong in one
system.

## 2. Schema shape worth adopting

Node types that earned their place: `Person`, `Company`, `OrgUnit`, `Series`, `Meeting`, `Chunk`,
`Topic`, `Decision`, `Action`, `Risk`, plus a `Meta` key/value table.

Edges: the org graph (`REPORTS_TO`, `WORKS_FOR`, `IN_UNIT`), `ATTENDED` (carrying invite,
response, turns, words, share-of-talk), `OCCURRENCE_OF` for series membership, `IN_MEETING`,
`SPOKE`, `MENTIONS` with a count, and the **evidence edge** from each extracted artifact to its
chunk.

`Meeting` carries the Stream URL, which is what makes **replay possible for transcript-only
occurrences** — a deep link back to the source, since there is no local media to seek. `Chunk`
carries `startSec`/`endSec` and a display timestamp label.

### What the visual layer adds

The screen dimension extends that shape with one node and two edges:

- **`Screen`** — meeting, sequence, a stable `screenUid`, capture time, kind (slide | live UI),
  confidence, image path, and a replay window.
- **`SHOWN_DURING`** (Screen → Chunk) — **the load-bearing one.** It is the join that makes *"what
  was on screen when this was said"* answerable, and it comes straight out of CAP-1's
  screen↔transcript alignment.
- **`DEPICTS`** (Decision/Action/Risk → Screen) — upgrades the citation edge from words-only to
  words **and** pixels, so a decision about a form field can show the form.

`screenUid` is stable cross-run identity — derived from the image content plus its capture
timestamp. **Never key graph nodes on a sequence number**, which renumbers on any re-index and
orphans every edge pointing at it.

## 3. Constraints learned the hard way

Carry these into whatever MeetingMiner builds, in any language or store.

1. **Assume a single writer.** The upstream store returned a lock error when a second process
   touched it. Design the indexer as one owner reading finished bundles, never as several
   processes writing concurrently.
2. **Vectors live in their own table, insert-only.** Updating a property covered by a vector index
   is refused, and dropping the index leaves the catalog referencing shadow tables, breaking every
   later write. Rows inserted under a live index are searchable immediately — so never update a
   vector row, only insert.
3. **Record which embedding model wrote the vectors.** Embedding width is baked into the table, so
   a model swap of a different dimension must be caught explicitly rather than silently producing
   garbage neighbours.
4. **Structural indexing must work with the model host off.** Only embedding and answering need a
   model; both are resumable, so an outage never corrupts the store. That separation is the
   difference between a fragile pipeline and a robust one.
5. **Everything meeting-scoped carries a meeting id**, which makes re-indexing one occurrence a
   cheap delete-and-reinsert rather than a full rebuild.

## 4. Extraction prior art

The upstream summaries are treated as a first-class extraction source rather than paying for a
second model pass: they already carry stable ids, owners, timings, and `[m:ss]` citations, so
artifacts are parsed straight out of them and those citations become the evidence edges.

The prompts behind them are directly relevant prior art for CAP-5: they **require a timestamp
citation on every decision, action, and risk**, tag model-invented rules as proposed, and forbid
fabricated due dates. That is *AI proposes, provenance verifies* already working in production.

## 5. Boundaries

- **Depend on none of it at demo time.** The upstream store was locked by another process when it
  was inspected; depending on someone else's in-flight work is how a demo breaks. MeetingMiner
  shows its own bundle and its own viewer.
- ~~How much is actually indexed and embedded is unknown.~~ **Resolved 2026-08-18** — the live
  copy was readable. Contents are in §6.


## 6. Measured store contents

Read from the live copy 2026-08-18, replacing the earlier "contents not readable" boundary.
**Superseded in part on 2026-08-19:** upstream fixed a summary-parser bug (see §8) and re-ran the
backfill, taking Decisions from 41 to **182** and `EVIDENCE` edges from 189 to **378**. The other
rows have not been re-measured since; treat the table below as the 2026-08-18 reading.

| | |
|---|---|
| Meetings | 167 — 28 occurrence `.txt` + 141 archive `.vtt` |
| Chunks | 7,730 |
| People / Decisions / Actions / Risks / Topics | 150 / 41 / 175 / 97 / 80 |
| `SPOKE` / `MENTIONS` / `EVIDENCE` edges | 19.6k / 21k / **189** |
| On disk | 217 MB |

**Chunking, as built:** whole speaker turns packed to ~1,400 characters with **one turn of
overlap**; chunk id is `meetingId#seq`, carrying `startSec`/`endSec`, a display label, and the
speaker list. Turn boundaries are preserved deliberately — a chunk starting mid-sentence loses the
speaker attribution that both the graph edges and the `[m:ss]` citations hang off.

**Extraction coverage is partial by construction.** Decisions, actions, and risks are parsed out of
the generated summary and action-item documents, so occurrences lacking those documents contribute
chunks and people but no extracted nodes — 189 evidence edges against 313 extracted artifacts.
Coverage is a function of which documents exist, not of the indexer.

## 7. Measured retrieval quality — the embeddings bake-off

Nine configurations of eight local models, 303 labelled tasks, run against the full 7,730-passage
corpus (`embedding-bakeoff-report.html`, 2026-08-18). This is the single most decision-bending
piece of prior art for CAP-3 and CAP-9, because two of its three findings contradicted the
hypothesis that motivated it.

### Method worth copying

Two query sets, **biased in opposite directions on purpose**:

- **183 cited-claim queries** — each extracted decision/action/risk becomes a query whose correct
  answer is the chunk its `[m:ss]` cites. Real analyst language, but it borrows the transcript's
  own words, which flatters keyword search.
- **120 natural questions** — a local model saw one passage and wrote a question a colleague might
  ask weeks later, explicitly avoiding the passage's distinctive words. Low overlap by
  construction, which flatters semantic search.

The rule that falls out: **a configuration that wins both sets is a safe choice; one that wins only
its favourable set is not.** Adopt this for MeetingMiner's own retrieval eval — it is the cheapest
known defence against an answer key that rewards whatever the author already believed.

### Findings

1. **Keyword search carries the dominant query shape.** On transcript-worded queries, **0 of 9
   embedding models beat BM25 alone** (text-only MRR 0.223 / R@5 37.2%; the best hybrid reached
   0.249, and six of nine configurations scored *below* the keyword baseline). BM25 is not the weak
   half of the system on that traffic — it is carrying it.
2. **Embeddings earn their place only on paraphrase.** On natural questions the best model gains
   **+0.149 MRR over text-only** (53% better). The same model gains +0.009 on transcript-worded
   queries. Hybrid retrieval is justified by the *traffic mix*, not by vectors being better.
3. **Documented usage measured worse than naive usage.** Applying EmbeddingGemma's official query
   and document prompts cost **−0.059 MRR** on cited claims and **−0.046** on natural questions, so
   the officially-correct configuration was not shipped. Prompting is part of a model, and getting
   it wrong is invisible without measurement.

### Model recommendation

**`snowflake-arctic-embed2`** (1024 dims) over the in-production `embeddinggemma:300m` (768 dims):
**+0.130 MRR** on natural questions, the largest effect in the study. Cost is 26.9 vs 49.7
passages/second, ~5 minutes to re-index 7,730 chunks, and +33% vector storage. Cheap enough that
the decision is not close — but the gain appears **almost entirely on paraphrased questions**.

### What this changes for MeetingMiner

- **Fund full-text quality as a first-class half of CAP-9**, not as a fallback behind the vector
  store: domain synonyms (SFTP/FTP, PO/purchase order) and field boosts. The measurement says that
  is where the dominant traffic is served.
- **Record the embedding model in the store** (already §3 rule 3) and treat a model swap as a
  re-index, not a config toggle.
- **Chunk boundaries are the bigger lever than model choice.** The report's own limitations section
  says the strict-vs-adjacent scoring gap means a meaningful share of misses are the answer sitting
  one chunk over — and chunk size and overlap were held fixed and never varied. For MeetingMiner
  this is the open lever, and it interacts directly with screen↔transcript alignment, since a
  `SHOWN_DURING` edge is only as precise as the chunk it lands on.

### Calibration — read the absolute numbers, not just the ranking

Best hybrid recall@5 is **60.0%** on natural questions and **37.2%** on cited claims, searching the
whole corpus unscoped. Two things follow. MeetingMiner's flows are usually **meeting-scoped**,
which searches a far smaller haystack and should land well above these figures — so these are a
floor, not a forecast. And CAP-3's success criterion is about *citations being present and
replayable*, not about retrieval recall, so nothing here breaches it. But an unscoped corpus-wide
question is the demo's hardest shape, and 60% is the honest prior to design against.

### Limitations the report states about itself

The answer key is machine-derived (citation timestamps mapped to passages by rule; questions
written by the same model family that writes the summaries) — no human relevance judgement. One
corpus, one domain, one language. Single run per configuration, no confidence intervals, so
differences below ~0.03 MRR are indistinguishable. Answer quality was never measured — only
whether the right passage was retrieved.

**Note the tension with `SPEC.md`'s independence constraint.** Query set 1's answer key is derived
from the summariser's own `[m:ss]` citations — the same self-derived-denominator hazard the spec
rules out for capture recall. It is weaker here than in the capture case (the citation is an
independent anchor into the transcript, not a set the retriever produced), but a MeetingMiner
retrieval eval should not inherit the pattern uncritically.


## 8. Silent zero-extraction — a measured failure mode, not a hypothetical (2026-08-19)

Upstream's summariser emits at least two document layouts. Until 2026-08-19 the indexer parsed only
one, so every meeting whose summary used the table layout contributed **zero** decisions to the
graph — and the indexer **reported success while doing it**. Fixing the parser took Decisions from
41 to 182: better than three quarters of that content had been missing, from a pipeline whose own
output said it had worked. It was found by chance while watching a backfill, not by any check.

Why it belongs in this spec rather than upstream's notes: MeetingMiner's extraction (CAP-5) and its
eval harness (CAP-7) have the same shape — a stage parses model or tool output into structured
artifacts, and an empty result is indistinguishable from a quiet meeting unless something looks. It
is the same class of error the independently-derived ground-truth rule already guards for capture
recall (SPEC Constraints): a component cannot reveal what it silently failed to produce. The
corresponding rule for extraction is in SPEC Constraints as *no silent zero*.
