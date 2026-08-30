# Spine Review — Update Amendment (corp-tenant plan), 2026-08-18

**Artifact:** `ARCHITECTURE-SPINE.md` (updated 2026-08-18)
**Reviewed against:** good-spine checklist + amendment-coherence focus (M365 sandbox discontinued; corp production tenant; puller-only Teams access; corpus split)
**Cross-checked:** `SPEC.md` (amended CAP-1, constraints, non-goals, assumptions), `scope.md` (Corpus section), `solution-design.md`, `.memlog.md` entries for the update intent
**Verdict:** PASS with fixes — the amendment landed coherently at every designated touch point; two medium inconsistencies remain, neither introduced by the amendment text itself but both exposed or left unresolved by it.

---

## 1. Did the amendment land everywhere it should?

| Touch point | Status | Evidence |
| --- | --- | --- |
| Frontmatter sources | Landed | `msft-sandbox-setup-guide.md` removed from `sources:`; `updated: 2026-08-18` set |
| AD-1 | Landed | Puller emit-drop mapping of native `<Title>/<M.D.YY>/` output; participants best-effort from sidecar, else transcript speakers; explicit "No server component calls Microsoft Graph; Graph participant lookup is product-later" |
| Component responsibilities (puller row) | Landed | "Teams acquisition from the corp tenant (Playwright Stream scrape, user login)"; consumes "its own `.env`; no server code" |
| Structural Seed prose | Landed | "no test tenant"; mocks hosted/recorded on corp production tenant; puller outside MeetingMiner, drops into a folder on the dev Mac; "external egress from MeetingMiner is provider APIs only" |
| Deployment diagram | Landed | `corp["corp Teams tenant (production)"]` node replaces the old sandbox/Graph node; `pullercli -->|Playwright Stream scrape (user login)| corp`; drops folder present under Filesystem |
| Conventions (Config row) | Landed | Puller excluded from the config regime; tenant credentials in `puller/.env` behind the AD-1 black-box seam |
| CAP-7 map row | Landed | Corpus rule carried: only scripted corp-tenant mocks are eval subjects; real pulled meetings are demo corpus only, never eval subjects |
| Deferred | Landed | Microsoft Graph participant lookup listed under product-later dimensions; nothing sandbox-flavored remains |

Stale-reference sweep: no occurrence of "sandbox", "M365", "test tenant", or Graph-as-used-capability anywhere in the spine body; every remaining Graph mention is an explicit exclusion. `solution-design.md` is also clean and carries the corpus split (line 118). Matches amended SPEC constraint (SPEC.md line 72), non-goal (line 86), assumptions (lines 95–96), and scope.md Corpus.

## 2. Findings

### F-1 (Medium) — Puller intake contract is stated three incompatible ways

- Component diagram (HLD): `puller -->|"POST /ingests"| api` — the puller actively calls MeetingMiner's REST API.
- Module structure: "`puller` shares no code with the server — **its only contract is the source-drop format (AD-1)**."
- Deployment diagram + amended Structural Seed + amended CAP-1: the puller only "drops its output into a folder on the dev Mac" (`pullercli --> drops`; no edge to `api`), and SPEC frames the local folder as the entry point.

AD-14 rules out folder watchers, so *something* must call `POST /ingests` — but the spine never decides who: puller, web UI gesture, or operator CLI. This is a real divergence point for independently built units: the puller's emit-drop step and the api's intake could each be built to a different handshake. The two diagrams currently disagree with each other and with AD-1's "the puller emits only drops and never knows the pipeline."

**Fix:** pick one. Either (a) delete the `puller → POST /ingests` edge and add the ingest trigger to web/api (user gesture with a drop path), keeping the puller pure-black-box per the amendment's framing; or (b) keep the edge and amend AD-1 and the module-structure caption to name *two* contracts (drop format + `/ingests` endpoint) and add the edge to the deployment diagram. Option (a) matches the amendment intent and SPEC ("dropped into a local folder... The Teams-side pull happens in the puller script, outside MeetingMiner").

### F-2 (Medium) — AD-12's recorded rationale is invalidated by the corpus split and was not re-affirmed

AD-12 (unrestricted egress, no allowlist layer) was adopted 2026-08-17 on a two-leg rationale (memlog): (a) the corpus is scripted sandbox meetings with no data-control concerns, and (b) provider access uses corp corporate API keys within the approved data-control set. The amendment breaks leg (a): the demo corpus now includes ~25 **real corp production meetings** (vendor, project, Boomi, corp internal), and AD-10's default sends extraction/chat content to a cloud provider. Leg (b) may still carry the decision, but the spine amendment did not revisit AD-12, and the ADOPTED tag now rests partly on a false premise.

**Fix:** re-affirm AD-12 explicitly for the real-meeting demo corpus (one sentence in AD-12 or the memlog: real pulled corp meetings may egress to configured providers under corp corporate keys), or scope it if that is not actually approved. No structural change needed either way — but the decision should be re-made consciously, not inherited.

### F-3 (Low) — Recovery convention overclaims what re-ingesting drops reconstructs

"Postgres + content root are reconstructed by re-ingesting drops... The drops directory is the only thing needing backup." Re-ingesting drops does **not** reconstruct API-owned human-curated state (AD-5): artifact approvals/publish lifecycle, participant display-name edits and merges, series membership, project/product assignment — nor the publish folder's local git history. Pre-existing (not amendment-caused), but the amendment raises its cost: the demo corpus now includes ~25 real meetings whose curation would be lost. **Fix:** either add Postgres (or its human-curated tables) and the publish repo to the backup line, or state explicitly that human-curated state is accepted-loss in recovery.

### F-4 (Nit) — CAP-7 row's "~25" is attributed to the wrong source

The row cites "(scope.md Corpus)", but scope.md carries no count; "~25" comes from the 2026-08-17 brownfield read (memlog) and `solution-design.md`. Harmless, but the citation should not name a source that cannot verify the number — drop the count or drop the parenthetical precision.

### F-5 (Nit) — "Outside MeetingMiner" vs. `puller/` in the monorepo source tree

Structural Seed says the puller "stays outside MeetingMiner" while the source tree seed places `puller/` inside the monorepo (reasonable: outside the *system boundary*, inside the *repo*). One clause distinguishing system boundary from repo layout would remove the ambiguity, especially alongside F-1.

## 3. Checklist verdicts

- **Fixes real divergence points; misses none:** Substantially yes — drop schema (AD-1), single DB of record (AD-2), single projection writer (AD-4), table ownership (AD-5), citation format (AD-15), config regime (AD-10), intake door (AD-14) are exactly the seams where independently built units would diverge. The one miss is the ingest-trigger ownership (F-1), which AD-14 half-decides.
- **Every Rule enforceable and preventing its divergence:** Yes. Each rule names a mechanical check (schema validation, module boundary, state column, code-path gate) rather than an aspiration; AD-6/AD-15 enforce "no citation, no answer" in code per the SPEC constraint. AD-12 is enforceable as a "may not build" prohibition (F-2 concerns its rationale, not its enforceability).
- **Deferred cannot cause divergence:** Yes. Every deferred item is either single-writer-owned (Neo4j naming, ADR file format), owned by a named companion doc (UI, retrieval eval), or attribute-level below the ERD. Product-later list matches scope.md.
- **Named tech verified-current:** Noted as verified 2026-08-17 with memlog evidence trails; another reviewer covers depth. Flag for that reviewer: `claude-sonnet-5` (AD-10 default) and the arm64 image tags. Minor: pinning Node "current LTS" for a component declared a black box outside the system is a mild boundary blur.
- **Covers CAP-1..9:** Yes — the Capability → Architecture Map rows all resolve to real components and ADs; amended CAP-1 (folder entry, sidecar participants, no Graph) is fully reflected in AD-1/AD-13/AD-14.
- **Every altitude-owned dimension decided/deferred/open:** Yes — deployment & environments (single Mac, host/Docker split, port map), infra strategy (compose, no cloud), operations (recovery, backup, logging, config, tooling) are all decided; the operational envelope is unusually complete for a spine. Only F-3 mars the recovery claim. Open questions: none, consistent with SPEC.

## 4. Summary

The amendment is coherent and complete at all eight designated touch points, and no stale sandbox/Graph assumption survives in the spine. Remaining work is small: resolve the puller ingest-trigger contradiction (F-1), consciously re-affirm AD-12 for real-meeting egress (F-2), and correct the recovery/backup overclaim (F-3). None require re-opening the finalized 2026-08-17 review's structural decisions.
