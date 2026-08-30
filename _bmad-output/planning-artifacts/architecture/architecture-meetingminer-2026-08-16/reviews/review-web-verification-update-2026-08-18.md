# Review — Web-Verification / Reality-Check of the 2026-08-18 Amendment

- **Target:** `ARCHITECTURE-SPINE.md` (updated 2026-08-18)
- **Lens:** every committed decision verified against the web or the existing project, not asserted from training data
- **Scope:** the 2026-08-18 amendment only (corp-tenant acquisition plan, puller claims, source-list hygiene). The stack table was fully web-verified 2026-08-17 (memlog) and was not re-verified; it was only scanned for entries the amendment could have invalidated.
- **Reviewer basis:** repo inspection of `/Users/devopsterus/current/cohort/meetingminer/pull_transcript/` (README.md, CLAUDE.md, on-disk output), git history (`fc3abd2`, `e502197`, `98a3f76`), spine working copy.

## Verdict

The amendment introduces no unverified technical claims — every factual statement about the puller checks out against the actual tool, and the deleted sandbox guide is cleanly gone. Two accuracy defects exist, one of them pre-existing but sitting in the exact list the amendment edited: **all five frontmatter `sources:` paths are dangling (wrong relative depth)**, and the spine misstates the puller's credential mechanism as a `.env` file.

## Findings

### F1 — MODERATE: every frontmatter `sources:` path is dangling

The spine lives at
`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`.
Its sources are written as `../../specs/spec-meetingminer/<file>`, which resolves to
`_bmad-output/planning-artifacts/specs/spec-meetingminer/…` — a directory that does not exist. The actual files are one level higher, at
`_bmad-output/specs/spec-meetingminer/` (all five — SPEC.md, scope.md, eval-strategy.md, eval-design.md, ux-spine.md — exist there). Correct prefix from the spine's location is `../../../specs/spec-meetingminer/`.

This is pre-existing, not introduced today: the e502197 version has the same depth error, including the now-removed `../../../msft-sandbox-setup-guide.md` entry, which likewise resolved to `_bmad-output/` while the file lived at repo root (four levels up). The whole list was apparently written as if the spine sat one directory shallower. The amendment edited this exact list (removing the sandbox entry) and was the natural moment to catch it. **Fix:** change `../../` to `../../../` on all five entries.

The `companions:` entry (`solution-design.md`) resolves correctly.

### F2 — VERIFIED: all puller claims match the real tool

Reality-checked against `pull_transcript/README.md`, `pull_transcript/CLAUDE.md`, and on-disk output:

| Spine claim | Reality | Status |
| --- | --- | --- |
| "Playwright Stream scrape, user login" (component table, Structural Seed edge) | Node + Playwright driving a logged-in Chromium against the Stream page (`stream.aspx`); `--login` caches the session | Confirmed |
| Native `<Title>/<M.D.YY>/` output layout (AD-1) | README output spec and CLAUDE.md layout section both document exactly this occurrence layout; 28 such occurrence directories exist on disk | Confirmed |
| Speaker-attributed `[m:ss] Speaker: text` export (AD-1) | The tool's core output format, stated in both docs | Confirmed |
| Optional VTT transcript (AD-1) | `.vtt` + `.docx` originals are saved alongside the `.txt` | Confirmed |
| `_source.json` provenance sidecar (AD-1) | CLAUDE.md: "`<Title>/<M.D.YY>/_source.json` — provenance and replay-completion marker"; present in real occurrence dirs (e.g. `Boomi Data Hub Demo/6.10.26/_source.json`) | Confirmed |
| Per-meeting mp4 when downloadable | README: `.mp4` "(recording, when downloadable)" with a three-step fallback chain (source download → archive fallback → transcript only) | Confirmed |
| "the existing puller's generated summaries fall here [ignored at intake]" (AD-1) | The puller does generate Ollama summaries + action-item files per occurrence, so the ignore rule is grounded in real files | Confirmed |
| "black box … original language … JS CLI" | Single Node script, no server code shared | Confirmed |
| "no server component calls Microsoft Graph" | The puller uses cookie-authenticated SharePoint/Stream endpoints, not Graph; nothing server-side is Graph-dependent | Confirmed |
| "~25 real pulled meetings" (CAP-7 row) | 28 occurrence directories on disk — consistent with a tilde figure | Confirmed |
| "survives corporate-tenant permission walls" (solution-design.md §"source-drop seam") | The documented 403-accessDenied archive-fallback chain is exactly this | Confirmed |

### F3 — MINOR: the puller does not keep credentials in a `.env`

Two places state a `.env` mechanism that does not exist:

- Consistency Conventions, Config row: "it keeps its own tenant credentials in `puller/.env`"
- Component responsibilities, `puller` row: "Consumes: its own `.env`; no server code"

Reality: `pull_transcript/` contains no `.env` file, and the README states "no credentials are stored in the script" — the session lives in the persisted browser profile `./.transcript-profile/` (created by `--login`, gitignored). The tool's only env-var configuration is plain environment variables (`OLLAMA_URL`, `OLLAMA_MODEL`, `SUMMARY_PROMPT`, `TRUST_MP4_DATE`, …), not a dotenv file, and none carry tenant credentials. The architectural point being made (puller credentials stay outside MeetingMiner's `config.yaml`/`.env` regime — the AD-1 black-box seam) is correct; the stated mechanism is not. **Fix:** replace "`puller/.env`" with the actual mechanism, e.g. "its persisted browser session profile (`.transcript-profile/`)".

### F4 — INFO: "emit-drop step" tense is inconsistent

The source-tree seed correctly says the puller "**gains** a small emit-drop step" (future work). But AD-1 ("the puller's emit-drop step maps its native … output") and the component table ("drop assembly via its emit-drop step") read as existing capability. No such step exists in `pull_transcript/` today. Cosmetic, but a reader auditing the puller against the spine will look for code that isn't there. **Fix:** mark the step as to-be-added in AD-1 and the component table, matching the source-tree wording.

### F5 — VERIFIED: sandbox guide cleanly removed, nothing dangling on it

- `msft-sandbox-setup-guide.md` (repo root) was deleted in commit `fc3abd2` ("Update spec for corp-tenant plan; add epics; drop sandbox guide"); `git ls-files` confirms no sandbox file remains anywhere in the repo.
- The spine body and frontmatter no longer mention it.
- Remaining textual mentions are intentional supersession notes, not dangling references: `_bmad-output/planning-artifacts/epics.md` line 88 explicitly says the guide "is superseded", and the two `.memlog.md` files record the history.

### F6 — INFO: the amendment is uncommitted

`ARCHITECTURE-SPINE.md`, `solution-design.md`, and the architecture `.memlog.md` are all modified in the working tree and not yet committed. The companion `solution-design.md` was amended consistently (corp tenant, drop folder, puller-as-black-box, no Graph). Commit when the F1/F3 fixes land.

### Stack table — no flags

The amendment names no new technology, and nothing in it invalidates a 2026-08-17-verified entry. Spot checks against the amendment's subject: "Node (puller) — current LTS" is compatible with the actual puller's stated requirement (Node 18+); Playwright is not a stack-table entry (it is the puller's own dependency, correctly outside MeetingMiner's stack). No concrete reason to believe any verified version row changed in one day; no re-verification performed per scope.

## Fix list (ordered)

1. F1 — correct all five `sources:` paths to `../../../specs/spec-meetingminer/…`.
2. F3 — replace the `puller/.env` credential claim with the browser-profile mechanism (two locations).
3. F4 — align emit-drop tense with the source-tree seed ("gains").
4. F6 — commit the amendment once 1–3 are in.
