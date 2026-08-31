# The thread embedding threshold, measured — 2026-08-31

`config.yaml`'s `threads.embedding_similarity_threshold` is documented as "a
starting value, not a measured one … nothing here has been scored against
ground truth, and that is stated rather than implied." This is that
measurement, on the real corpus rather than on scripted fixtures.

**Verdict: leave it at 0.82.** The measurement was taken expecting to raise or
lower it and found the committed value is the right one for this data.

## What prompted it

Two things looked wrong before any numbers existed.

First, the derivation reported **zero name links** across the whole corpus —
every link came from the embedding leg. Second, the threshold's recorded
rationale reasons from a premise the data does not match: "These are short
strings — three or four words — and embedders score short strings high against
one another." The real topic names have a **median length of 6 words** and run
much longer:

    Additional Louisiana area 2022 work (storm sewer, piling, specific walls
    incl. future 2023 work)

Nothing produces two byte-identical strings of that shape, which is why the
name leg never fires. The premise behind the number is wrong even though, as
it turns out, the number is not.

## Method

381 topics carrying at least one mention, from 13 ingested meetings. Each name
embedded with the configured `qwen3-embedding:0.6b`, vectors L2-normalised,
all ~72,000 pairs scored by cosine, then union-find over the pairs at or above
each candidate threshold — the same partition the derivation itself computes,
so the counts below are what a real run would produce.

| threshold | links | threads | multi-meeting threads | widest (meetings) |
|---|---|---|---|---|
| 0.90 | 6 | 375 | 5 | 2 |
| 0.86 | 13 | 369 | 6 | 2 |
| 0.84 | 27 | 355 | 14 | 3 |
| **0.82 (committed)** | **37** | **345** | **18** | **3** |
| 0.80 | 62 | 326 | 20 | 5 |
| 0.78 | 99 | 299 | **21** | 10 |
| 0.76 | 154 | 260 | 16 | 13 |
| 0.72 | 365 | 179 | 11 | 13 |

## Why the apparent optimum is a trap

Counting multi-meeting threads alone, 0.78 looks best: 21 against 0.82's 18.
Reading the clusters shows why that count is the wrong objective. At 0.78 the
widest cluster spans 10 meetings and contains:

    Reports: overview & built-in reports
    Meeting agenda & deck
    Approving prior meeting minutes
    Dashboards: overview & refreshing
    Calendar: events & external sync

Two unrelated subjects — a CRM product's reporting features and the procedure
of running a public meeting — fused into one thread. That is exactly the
failure the committed rationale prefers to avoid, and its reasoning holds up:
a missed link is two threads a human merges, visible and reversible; a false
link produces a timeline interleaving unrelated meetings, which reads as a bug
rather than as a setting.

Below 0.78 the multi-meeting count *falls* while the widest cluster saturates
at 13 meetings — the partition is collapsing into one blob that absorbs
everything, so the apparent peak at 0.78 is the last point before fusion, not a
quality maximum.

At 0.82 every wide cluster is coherent:

| cluster | meetings |
|---|---|
| Cedar Lake Trail closure / reopening outlook / corridor openings | 3 |
| Calendar & events sync, schedule changes | 3 |
| Reports & dashboards, custom dashboards | 2 |

## Two things this does not settle

- **It is 13 meetings of an intended 59.** The distribution will move as the
  corpus grows, and the right time to re-measure is after the ingest completes.
  Re-running the script is cheap and free: it uses the local embedder only.
- **Procedural boilerplate threads cleanly and uselessly.** "Closing remarks",
  "Adjournment / announcements", "Meeting wrap-up/closing" form a legitimate
  7-meeting cluster at 0.78 that no reader wants. Suppressing it is a curation
  question — story 10.2a's human merge surface, or a stop-list — and not a
  threshold question; no threshold separates it, because it genuinely is one
  recurring subject.
