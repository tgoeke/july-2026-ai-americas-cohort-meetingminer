---
id: SPEC-system-status
companions:
  - ../spec-chat-fallback-timeout/SPEC.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# System Status in the UI

Landed on `main` at `3f5a1ea` (2026-08-21). Re-derived 2026-08-29 to retire an
expired premise and record the Epic 8 amendment; the contract below is what
the landed code must keep satisfying.

## Why

A pain to solve. The owner's first real session hit an invalid `ANTHROPIC_API_KEY` and the UI gave no signal — no status surface, no statement that anything was wrong, no indication that fixing it was on the user. The only symptom was a misleading client timeout, dissected in the adopted companion `../spec-chat-fallback-timeout/SPEC.md` (which fixes the chat path specifically). Owner direction of record (2026-08-21): for this initial implementation, any condition that requires user action must be surfaced in the UI while the product is being used. This spec is that generalization: the product tells the user its own health and what to do about it.

## Capabilities

- **CAP-1 Status surface**
  - **intent:** The UI shows the health of every dependency the product needs to work — LLM role bindings and their keys, the stores (Postgres, Neo4j, Meilisearch), the api, the worker and its job backlog — in two places: a persistent indicator in the chrome that expands on click, and a dedicated status page. Health is polled periodically while the app is open, so the state on screen is current, not a snapshot from page load.
  - **success:** With any one dependency broken (e.g. an invalid provider key), a user opening the app sees the degraded state in the UI before issuing a chat or search; a dependency that breaks while the app is open changes the indicator without a reload; with everything healthy, the surface says so and stays out of the way.

- **CAP-2 Required actions stated as actions**
  - **intent:** When a condition requires user action, the UI states what is broken and what the user must do — e.g. "chat is unavailable: `OPENAI_API_KEY` is invalid; set it in `.env` and restart the api" — not just a red indicator.
  - **success:** For each detectable failure condition, the surfaced message names the failing dependency and a concrete remediation the owner can follow without reading server logs.

- **CAP-3 Failures point home**
  - **intent:** A feature that fails at point of use names the failing dependency consistently with the status surface (extending companion CAP-4 beyond chat), so the in-flow error and the status view tell one story.
  - **success:** Triggering a failure from a feature and opening the status surface show the same dependency and the same remediation; no path yields a generic or misattributed error while the real cause is known server-side.

## Constraints

- **Secrets never serialize.** Status may state that a key is missing or invalid; no fragment of any key or password appears in any response or the UI.
- **The status surface is read-only.** Key and configuration remediation remain the file contract (`.env` / `config.yaml` edit plus restart); the UI states that path and the status surface never offers to mutate it. *Amended 2026-08-29:* choosing a model from the catalog `config.yaml` declares is a persisted user selection (Epic 8, AD-10 amendment), not a file mutation, and lives on the settings page and ask box — not on the status surface.
- **Health checks are free.** No paid LLM completion as a probe — key validity comes from free provider endpoints (e.g. model list) or from recorded last-failure state; a paid call still requires a fresh explicit owner yes. Polling repeats these checks, so this holds per tick, not just per probe.
- **Status never touches the worker.** Reporting worker/backlog state is read-only observation; nothing on the status path starts, restarts, or resumes the worker.
- **No silent fallback** (owner direction of record): a degraded dependency reads as degraded; nothing auto-substitutes to make the status look green. A user-selected binding that fails reads as failed.
- **Companion binds.** The chat-path contract in `../spec-chat-fallback-timeout/SPEC.md` (accurate timeout wording, prompt failure surfacing) is not duplicated or weakened here.

## Non-goals

- Editing keys or configuration from the UI.
- Monitoring or alerting outside the running UI (email, push, dashboards).
- Auto-remediation, retries, or restarts triggered from the status surface.
- Historical uptime or metrics; this is current-state health only.
- Per-provider key validity and active binding per role on this surface — added by `epics.md` story 8.2a (FR39), specced there.

## Success signal

With a provider key invalid exactly as the Anthropic key was on 2026-08-21, the owner opens the app and, without running anything, the UI states which capability is degraded, which key is at fault, and what to do about it; after fixing the key per the stated instruction, the same surface reads healthy. No repeat of a session where the only symptom of a dead key is a misleading timeout.

## Assumptions

- Scope is the existing web UI — persistent chrome plus a status view sized for the initial implementation, not a separate ops product.
- Store and api liveness are cheap to probe from the server; key validity is checkable via free provider endpoints.
- The polling interval is an implementation choice, sized so provider free endpoints are not hammered (server-side caching of probe results between UI polls is acceptable).
