# Design: Retrieval Eval (checks 2.8/2.9)

**Status: documented only — not implemented.** This is the full retrieval eval
design promised to instructors: `docs/architecture.md`
commits the capstone to "Document (not implement): the retrieval eval
strategy" and to "Produce designs for ALL retrieval items" — design
everything, build the slice. The contract of record is `eval-design.md`
§2.8/§2.9 (with §2.7 supplying the Q&A rubric); this file expands those
sketches. **Two slices of this design are BUILD, not document, and land with
story 5.3:** doc-index search recall (§2.10) and the publish-gate projection
assert (§2.11). They are noted below where they carve out of the larger
design; nothing here duplicates their specification.

Retrieval spans two derived stores (CAP-9): the full-text document index and
the domain graph. The eval has three legs, one per query shape the corpus must
answer.

## Leg 1 — Topic/mention search: recall@k on planted phrases and topics

**What it checks.** That searching for something the scripts planted surfaces
the meeting containing the plant.

**Algorithm.** For each planted probe, issue the search through the public api
(AD-16) and assert the containing meeting appears in the top *k* results:

- **Phrase probes:** every `planted.phrases[].text` — verbatim plants, so the
  index has no excuse. *The doc-index slice of this leg is promoted to BUILD
  as check 2.10 (story 5.3): recall@5 = 1.0 on planted phrases against the
  full-text index, k = 5 provisional per §6.*
- **Topic probes:** the topics the scripts deliberately exercise (each
  script's subject matter is known at authoring time, so topic probes are
  authored beside the manifest, not derived from pipeline output — the same
  independence rule as the capture denominator). A topic may span several
  scripted meetings, so "the containing meeting" is not one meeting: each
  topic probe is authored with its **expected meeting set** — every scripted
  meeting whose script exercises the topic — and the probe passes only when
  **each** meeting in that set appears within the top *k*. An authoring rule
  requires `k >= 1`, a nonempty `expected_meetings` list with unique meeting
  ids, and `len(expected_meetings) <= k`; an impossible probe is rejected, not
  reported as weak retrieval. (A phrase probe's expected set is the single
  meeting whose script plants it; this is the same rule with a one-element
  set.) Topic queries are paraphrase-shaped, so unlike
  phrase probes they exercise the semantic half of retrieval; their threshold
  starts at recall@5 = 1.0 on the scripted corpus (a scripted topic's meeting
  set is unambiguous by construction) and is expected to be the first number
  §6 recalibrates on observed results.

**Metric.** recall@k per probe class, reported per probe in `detail` with the
rank at which each expected meeting appeared (or that it did not).

## Leg 2 — Graph traversal: exact-set comparison

**What it checks.** The participants → meetings → topics → moments traversal
(the Clarence demo query): starting from a participant, walk their meetings,
the topics of those meetings, and the moments grounding those topics.

**Algorithm.** For each scripted participant, the expected result set is
**fully known from the meeting scripts**: the manifests declare participants,
the scripts declare topics and planted moments, so expected =
`{(participant, meeting, topic, moment_anchor)}` is authored ground truth.
Run the traversal through the public api and compare **exact set equality** —
not recall@k — because the graph is a projection of declared facts, and a
missing edge or an invented one are both defects:

- `missing` — expected tuples absent from the result;
- `extra` — returned tuples no script declares (a hallucinated edge, a
  mis-attributed participant, a topic bleeding across meetings).

**Threshold.** Both sets empty of surprises: `missing = extra = 0`. No fuzz —
identity in the graph is keyed (participants by `mail:`/`name:` key, moments
by id), so nothing here needs similarity tolerance. Moment membership is
matched by the planted item's moment (the join defined in
`citation-timestamp-window.md`), which is the one fuzzy-adjacent edge; a join
failure reports as its own named problem, not as `missing`.

## Leg 3 — Cited Q&A: rubric §2.7 plus right-moment-cited (§2.8)

**What it checks.** That each manifest `qa` question is answered correctly
*and* the answer's citations hold up.

**Algorithm.** For each `qa` entry, ask `question` through the public api and
score the structured answer twice:

1. **Rubric §2.7** (LLM judge when story 5.4 is built; human judge otherwise):
   (a) faithful to the cited moment's transcript; (b) citation present — no
   citation is an automatic fail per the SPEC's core constraint; (c) every
   `answer_must_contain` term present; (d) nothing asserted beyond evidence.
2. **Right-moment-cited (§2.8):** does the **top** citation resolve to the
   planted item `expected_moment` names? For the capstone this is the human
   judge's `qa-right-moment-cited` worksheet (RUNBOOK.md step 5); the
   documented deterministic replacement is the citation timestamp window
   (check 2.5, `citation-timestamp-window.md`) — a top citation within ±15 s
   of the expected plant's scripted `at` is the machine-checkable form of
   "the right moment".

**Escalation** follows §3: deterministic parts first ((b) and (c) are
deterministic — citation presence and term containment over the folded
answer), LLM judge advisory on (a)/(d), human final with verdicts in
`human-verdicts.yaml`.

## Data sources

- **Ground truth:** manifest `planted.*` (probes and expected moments),
  `qa[]` (`question`, `expected_moment`, `answer_must_contain`), participants
  and topics from the meeting scripts.
- **System under test:** the public api's search, traversal, and Q&A surfaces,
  per AD-16 — the harness stays a client. The projection internals
  (`server/meetingminer/projections/`) are never read directly by these
  checks; the publish-gate check (§2.11, story 5.3) is what asserts over store
  membership, and it, too, asserts through api-visible behavior plus the
  harness's read-only corpus connection.

## Failure modes

| Failure | Leg | Triage class |
|---------|-----|--------------|
| Verbatim phrase not in top k | 1 | pipeline bug — the index has no excuse on a verbatim plant |
| Topic probe misses | 1 | recalibration candidate (semantic retrieval quality) — record observed rank; §6 owns the threshold |
| `missing` traversal tuple | 2 | pipeline bug (projection or identity resolution — e.g. a `name:`-keyed participant split) |
| `extra` traversal tuple | 2 | pipeline bug (hallucinated or mis-scoped edge) |
| Q&A cites the wrong moment | 3 | pipeline bug (retrieval ranking) unless the plant is ambiguous in the script — then ground-truth script error |
| `answer_must_contain` term absent | 3 | genuine miss (answer quality); human confirms via worksheet |

## What implementing requires

1. **A query driver** for the three surfaces — search, traversal, Q&A —
   issuing manifest-derived probes through the public api and capturing
   structured results. Shared with check 2.5's design; the largest missing
   piece.
2. **Versioned retrieval-ground-truth companion:**
   `evals/retrieval-ground-truth.yaml`, versioned with the manifests, is the
   sole future companion (not a manifest extension or an alternative file).
   It declares topic probes as `{id, query, k, expected_meetings}` and graph
   tuples as `{participant_key, meeting_id, topic, moment_anchor}`. Keys use
   the canonical API comparison projection: participant identity is the
   returned `mail:<normalized-email>` or `name:<normalized-name>` key,
   meeting identity is manifest `meeting.id`, `topic` is normalized with
   `normalize_anchor`, and `moment_anchor` is the planted-item id. The future
   check normalizes the API traversal response into exactly those four fields
   before exact-set comparison, validates `k >= 1`, nonempty unique
   `expected_meetings`, `len(expected_meetings) <= k`, and rejects duplicate
   companion ids/tuples. Ground truth remains script-authored, never derived
   from output.
3. **The planted-item↔moment join** from `citation-timestamp-window.md`.
4. **Check modules** under `evals/checks/` in the shipped `CheckResult` shape,
   thresholds recorded beside results per §6.

## Why deferred

Legs 1–3 sit on retrieval surfaces that are themselves capstone-partial
(scope.md's Cluster C slice), and the eval strategy for them is explicitly the
"document" half of that slice. The two sub-checks with no open design
questions and direct SPEC-constraint weight — doc-index recall@5 (§2.10) and
the publish-gate assert (§2.11, defending "unpublished artifacts never enter a
store") — were promoted to BUILD and arrive with story 5.3. The rest is this
design, plus the human worksheets that stand in for leg 3 today.
