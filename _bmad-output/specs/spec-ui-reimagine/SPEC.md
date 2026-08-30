---
id: SPEC-ui-reimagine
companions:
  - current-ui-inventory.md
  - reference-ui.md
  - ../spec-meetingminer/SPEC.md
sources: []
---

> **Canonical contract** for the UI reimagining. Read the companions: `current-ui-inventory.md` is the gap map, `reference-ui.md` maps the visual target to available data, and the adopted parent SPEC's constraints (no citation no answer, published-only retrieval, AI never owns truth) bind every screen here.

# MeetingMiner UI Reimagining — Reveal the Corpus

## Why

The product's depth exists — cited chat, corpus search, moment replay, publishing — but the front door is a bare list of meeting rows that reveals none of it, evidence for one meeting is scattered across per-moment pages, and the 480-line configuration that runs the whole AI stack has no surface at all. The capstone demo is tomorrow morning (2026-08-22, ~12h away) and the current UI does not demonstrate the system it fronts. This spec is a demo-rescue: recompose what the server already serves into a corpus-revealing UI, modeled on the user-supplied reference view, buildable overnight.

## Capabilities

- **CAP-1 Corpus-revealing home**
  - **intent:** The home screen states the corpus's scale — real counts of meetings, hours of evidence, moments, screens, extracted artifacts, participants, published documents — and renders each meeting as an evidence card: poster screenshot, title, date, duration, corpus, transcript-only badge, ingestion state, and per-meeting counts (moments, screens, artifacts, participants), filterable by corpus and sortable by recency. Search and ask-the-corpus are persistent chrome on every screen, not panels buried on one page.
  - **success:** Opening the app answers "how much evidence does this corpus hold" in one screen without a click; every number is a database-of-record count, none is decorative.

- **CAP-2 Dense meeting evidence view**
  - **intent:** One meeting page modeled on `reference-ui.md`: a header stat line (date · duration · transcript turns · words · passages · source lineage), a screens film-strip column with timestamped thumbnails, the full timestamped speaker-attributed transcript center, and a right rail of extracted artifacts grouped by kind — each with its moment anchor, publish state, and jump — plus participants (with the explicit absence note when no graph exists) and published documents. Every element clicks through to its moment or replays in place.
  - **success:** A viewer sees a whole meeting's evidence — screens, discussion, extractions — on one page without visiting per-moment pages, and every claim shown still traces to a replayable moment.

- **CAP-3 Configuration transparency**
  - **intent:** A read-only configuration page renders the live stack from a new sanitized read-only endpoint: LLM roles with model/fallback/endpoint, extraction prompts, embedder, STT/OCR engines, capture thresholds, search knobs, store coordinates — each section stating the change path (`config.yaml` edit + restart). This extends the parent spec's existing prompt-visibility mandate (parent CAP-5) to the whole non-secret config.
  - **success:** "Where is the config, what models run this?" is answered by opening one page; no secret or `.env` value appears in any response.

- **CAP-4 Demo-path continuity**
  - **intent:** The three-minute demo path — ask the corpus, get a cited answer, open a cited moment, replay its evidence — runs through the reimagined chrome without regression.
  - **success:** A dry run of the demo script passes tonight against the new UI, and the existing web test suite passes.

## Constraints

- **Ship by tomorrow morning.** Build order CAP-1 → CAP-2 → CAP-3 → CAP-4 gate; each lands independently, and any unfinished piece falls back to the existing screen so the demo is never blocked on this spec.
- **New backend is read-only.** Aggregate counts, per-meeting roll-ups, and one sanitized config endpoint built as an allowlist projection of `Settings` — never a serialization of the whole object. No endpoint mutates `config.yaml`; the UI states the file-edit-plus-restart change path instead of pretending otherwise (spine AD-8/AD-10).
- **Secrets never serialize.** `.env` values, API keys, and store passwords never leave the server; the config endpoint is allowlist-only precisely so a future `Settings` field is hidden by default.
- **Render only data that exists.** No topic chips, risk sections, or metrics invented for visual parity with the reference; `reference-ui.md` marks which elements have backing data tonight.
- **Parent contract binds.** No citation no answer; only published artifacts read as knowledge; deterministic components own evidence display; adopted companion `../spec-meetingminer/SPEC.md`.
- **Recomposition over invention.** Prefer the unused server surface catalogued in `current-ui-inventory.md` (list-moments, search filters, unrendered `SearchHit` fields) before writing new queries.
- **No regression.** Existing done-story behavior and tests stay green; `make test`'s web build passes.

## Non-goals

- Config editing or hot reload from the UI — configuration remains a file contract.
- Topic modeling / frequency chips, and any extracted kind (e.g. risks) the pipeline does not produce.
- Graph browser, entity/screen pages, participant detail, multi-turn chat, full-length video player, job-detail screens — post-demo work, not tonight.
- Visual polish beyond the reference's dark data-dense idiom; no design system migration.

## Success signal

Tomorrow morning's demo opens on a home screen that states the corpus's scale, drills into one dense meeting view showing screens, transcript, and extractions together, answers a question with citations that replay their evidence, and — asked where the configuration lives — opens a page showing the live model stack. All against real counts, real artifacts, no invented data.

## Assumptions

- Corpus and per-meeting counts are cheap aggregates over the existing schema; no new pipeline stage or migration is needed.
- A read-only sanitized config endpoint is consistent with spine AD-8/AD-10 (visibility is mandated by parent CAP-5; only mutation is reserved to the file).
- The overnight build is done by agents working the existing story workflow (worktree, frozen contract, commit early); this spec is the contract they build from.

## Open Questions

- Topic chips (reference's TOPICS section): derive from search index term frequencies post-demo, or drop? Post-demo decision.
- Whether store host/port coordinates belong on the config page long-term (fine local-first single-user; revisit if the deployment story changes).
