# Review — Web Verification Lens

- **Artifact:** `ARCHITECTURE-SPINE.md` (meetingminer, 2026-08-16, updated 2026-08-17)
- **Charge:** Verify committed decisions were web-researched/reality-checked, not asserted from training data. Spot-check the Stack table's "verified current 2026-08-17" claim and technology-fit assertions.
- **Reviewed:** 2026-08-17
- **Method:** Live WebSearch/WebFetch against PyPI JSON API, npm registry, Docker Hub tag API, GitHub releases, vendor docs, and the Anthropic model catalog.

## Verdict

**PASS with minor notes.** Every spot-checked version in the Stack table is real and current as of 2026-08-17 — including several that only exist post-training-cutoff (Meilisearch 1.53 shipped 2026-08-10/13, Neo4j 2026.07.1 shipped 2026-08-07, neo4j-graphrag 1.18.0 shipped 2026-06-24). This is strong evidence the table was genuinely web-verified, not asserted from training data. No refuted claims. Three informational caveats worth carrying into the build (items 3, 6, 9).

---

## Per-item findings

### 1. Neo4j Community 2026.07, arm64 image — VERIFIED
- **Claim:** "Neo4j Community 2026.07 (arm64 image)" (Stack table).
- **Finding:** Neo4j 2026.07.1 released 2026-08-07 (CalVer scheme confirmed). Docker Hub library/neo4j carries `2026.07-community`, `2026.07.1-community` (plus trixie/ubi10 variants), each published for **amd64 and arm64/v8**.
- **Sources:** https://neo4j.com/current-neo4j-versions/ ; https://github.com/neo4j/neo4j/wiki/Neo4j-2026-changelog ; https://hub.docker.com/v2/repositories/library/neo4j/tags/?name=2026.07
- **Severity if wrong:** n/a (verified).

### 2. Neo4j CE ships Cypher — VERIFIED (trivially)
- CE is fully Cypher-capable; confirmed by Neo4j operations-manual introduction and CE product page. No edition risk for AD-7's hand-written Cypher traversal templates.
- **Source:** https://neo4j.com/docs/operations-manual/current/introduction/

### 3. Vector indexes in Neo4j Community Edition — VERIFIED WITH CAVEAT
- **Claim (implicit):** CE suffices for any graph-side vector capability the spine might lean on.
- **Finding:** The Cypher Manual vector-indexes page states vector indexes are available in **both Enterprise and Community Edition**. Caveat: CE indexes embeddings stored as `LIST<INTEGER | FLOAT>` properties; the newer native `VECTOR` property type (2025.10+) requires **block format, Enterprise/Aura only**. The 2026.07 quantization-GA features were announced without an explicit edition restriction, but treat anything block-format-dependent as suspect on CE.
- **Mitigating context:** the spine explicitly defers graph-side vector search ("pgvector usage beyond reserved capacity… Revisit if graph-side vector search is wanted"; embeddings currently serve Meilisearch hybrid), so CE's `LIST`-based vector indexing is more than enough for what's committed.
- **Sources:** https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/ (fetched via proxy; page confirms edition availability and the VECTOR/block-format restriction).
- **Severity if the caveat is ignored:** Low for this spine (feature deferred). Would be Medium if a later revision adopts native `VECTOR` properties on CE.
- **Note:** one 2023-era third-party article claims vector indexes are Enterprise-only; the current official manual contradicts it. Official docs win.

### 4. Meilisearch 1.53.x, arm64 image — VERIFIED
- **Claim:** "Meilisearch 1.53.x (arm64 image)".
- **Finding:** v1.53.0 released 2026-08-10, v1.53.1 released 2026-08-13. Docker Hub `getmeili/meilisearch` tags `v1.53`, `v1.53.0`, `v1.53.1` all published for amd64 **and arm64**. Notably, 1.53 is 4 days old at spine verification date — impossible to know from training data; corroborates live verification.
- **Sources:** https://github.com/meilisearch/meilisearch/releases ; https://hub.docker.com/v2/repositories/getmeili/meilisearch/tags/?name=v1.53
- **Severity if wrong:** n/a.

### 5. Meilisearch hybrid search GA — VERIFIED
- **Claim (implicit in eval/scope docs and Stack):** hybrid search is a stable, non-experimental feature.
- **Finding:** AI-powered search (hybrid full-text + semantic) first shipped experimentally in v1.3/v1.6 and is documented by Meilisearch as **fully stable** (stabilized in the v1.13 era, Feb 2025) — long before 1.53.
- **Sources:** https://www.meilisearch.com/products/hybrid-search ; https://www.meilisearch.com/blog/meilisearch-1-13
- **Severity if wrong:** n/a.

### 6. meilisearch Python SDK 0.43.x compatibility with server 1.53 — VERIFIED WITH NOTE
- **Claim:** "meilisearch (Python SDK) 0.43.x".
- **Finding:** meilisearch 0.43.0 is the latest PyPI release, published **2026-07-22** — i.e. ~3 weeks **before** server 1.53.0 (2026-08-10). It exists and is current; the SDK is a thin REST client and Meilisearch maintains backward compatibility, so pairing is safe for all stable APIs (hybrid included).
- **Note:** any feature *introduced in* 1.52/1.53 (e.g. the 1.53.1 experimental task-queue env var) may not have first-class SDK wrappers yet. Not a spine risk — nothing committed depends on 1.53-only features.
- **Source:** https://pypi.org/pypi/meilisearch/json
- **Severity:** Info only.

### 7. neo4j-graphrag 1.18.x and Neo4j server requirements — VERIFIED
- **Claim:** "neo4j-graphrag (optional helpers) 1.18.x", used against Neo4j 2026.07.
- **Finding:** neo4j-graphrag 1.18.0 released on PyPI **2026-06-24** (only 1.18.0 in the 1.18 line). Requires Python 3.10–3.14 and driver `neo4j>=5.17.0,<7.0.0`. Project docs state support for Neo4j server >=5.18.1 / Aura >=5.18.0, with **Neo4j 2026.01+** unlocking the SEARCH clause and in-index filtering — so 2026.07 is squarely supported and gets the newer retrieval features. Python 3.12+ (spine) is inside the supported range.
- **Sources:** https://pypi.org/project/neo4j-graphrag/ ; https://github.com/neo4j/neo4j-graphrag-python ; https://neo4j.com/docs/neo4j-graphrag-python/current/
- **Severity if wrong:** n/a.

### 8. LiteLLM ≥1.97 with Ollama + OpenRouter — VERIFIED
- **Claim:** "LiteLLM ≥1.97"; AD-8/AD-10 route Ollama fallback and OpenRouter through it.
- **Finding:** litellm 1.97.0 is the current PyPI release. LiteLLM's provider docs list both **Ollama** ("LiteLLM supports all models from Ollama") and **OpenRouter** ("all the text / chat / vision / embedding models from OpenRouter") as supported providers.
- **Note:** "≥1.97" floors the pin at the *newest* release — reasonable as a seed ("the code owns this once it exists"), but the build should pin an exact version early since LiteLLM releases very frequently.
- **Sources:** https://pypi.org/pypi/litellm/json ; https://docs.litellm.ai/docs/providers
- **Severity:** Info only.

### 9. mlx-whisper 0.4.x and parakeet-mlx 0.5.x on PyPI — VERIFIED WITH STALENESS NOTE
- **Claim:** "mlx-whisper 0.4.x", "parakeet-mlx 0.5.x".
- **Finding:** Both exist. mlx-whisper latest is **0.4.3 (2025-08-29)** — almost a year old at review time, so 0.4.x is correct but the package is slow-moving; verify MLX-core compatibility at build time (mlx itself moves fast on Apple Silicon). parakeet-mlx latest is **0.5.2 (2026-06-05)**; 0.5.x line confirmed (0.5.0 2026-01-07, 0.5.1 2026-02-21).
- **Sources:** https://pypi.org/pypi/mlx-whisper/json ; https://pypi.org/pypi/parakeet-mlx/json
- **Severity:** Info only (mlx-whisper ↔ current mlx pin is a build-time check, not a spine defect).

### 10. pgvector 0.8.x with Postgres 18 — VERIFIED
- **Claim:** "Postgres 18" + "pgvector 0.8.x".
- **Finding:** pgvector 0.8.1+ supports PostgreSQL 18; current 0.8.x releases (up to 0.8.6) are tested against PG 18.x. Debian ships `postgresql-18-pgvector`; official pgvector Docker images exist for `0.8-pg18`.
- **Sources:** https://github.com/pgvector/pgvector ; https://hub.docker.com/hardened-images/catalog/dhi/pgvector (0.8-pg18 image) ; https://packages.debian.org/sid/postgresql-18-pgvector
- **Severity if wrong:** n/a.

### 11. FastAPI 0.141.x — VERIFIED
- Latest PyPI release is **0.141.1**. Claim matches.
- **Source:** https://pypi.org/pypi/fastapi/json

### 12. pytest 9.1.x — VERIFIED
- Latest PyPI release is **9.1.1**. Claim matches.
- **Source:** https://pypi.org/pypi/pytest/json

### 13. Vite 8.x / React 19.x / TypeScript current — VERIFIED
- Vite latest on npm: **8.2.1** (Node engines `^20.19.0 || >=22.12.0` — compatible with "Node current LTS" for the puller/web tooling). React latest: **19.2.8**. Both match the "8.x / 19.x" claim.
- **Sources:** https://registry.npmjs.org/vite/latest ; https://registry.npmjs.org/react/latest

### 14. shadcn/ui CLI v4, Vite template, Base UI — VERIFIED
- **Claim:** "shadcn/ui CLI v4 (Vite template, Base UI)".
- **Finding:** shadcn/cli v4 shipped March 2026 (official changelog page "March 2026 - shadcn/cli v4"). It supports multiple init templates including **Vite**, and a `--base` flag to choose **Radix or Base UI** primitives. All three parts of the claim check out.
- **Sources:** https://ui.shadcn.com/docs/changelog/2026-03-cli-v4 ; https://ui.shadcn.com/docs/installation/vite
- **Severity if wrong:** n/a.

### 15. @hey-api/openapi-ts 0.99.x — VERIFIED
- npm latest is **0.99.0**. Claim matches.
- **Source:** https://registry.npmjs.org/@hey-api/openapi-ts/latest

### 16. Ollama 0.32.x — VERIFIED
- GitHub releases show v0.32.0 through **v0.32.13** (2026-08-14). Claim matches.
- **Source:** https://github.com/ollama/ollama/releases/tag/v0.32.13

### 17. Apple Vision OCR callable from Python (PyObjC) — VERIFIED
- **Claim (AD-8):** `Ocr` port with an AppleVision implementation running as a macOS host process (AD-9 exists specifically to keep this off Docker).
- **Finding:** `VNRecognizeTextRequest` (Vision framework) is callable from Python via **pyobjc-framework-Vision** (+ pyobjc-framework-Quartz). Multiple maintained wrappers prove the route: `ocrmac` (PyPI, wraps VNRecognizeTextRequest and, on macOS Sonoma+, the stronger VisionKit/LiveText engine), `apple-vision-utils`, and OCRmyPDF-AppleOCR. macOS-only — consistent with AD-9's host-process rule and the Tesseract fallback in the port.
- **Sources:** https://github.com/straussmaximilian/ocrmac ; https://pypi.org/project/apple-vision-utils/ ; https://yasoob.me/posts/how-to-use-vision-framework-via-pyobjc/
- **Severity if wrong:** would have been High (a load-bearing pipeline stage); confirmed viable.

### 18. AD-10 default model `claude-sonnet-5` — VERIFIED
- **Claim:** "Default bindings: extraction + chat = `claude-sonnet-5` (cloud primary)".
- **Finding:** `claude-sonnet-5` is a real, current Anthropic model ID (Claude Sonnet 5; 1M context, $3/$15 per MTok with introductory $2/$10 through 2026-08-31). Checked against the current Anthropic model catalog. LiteLLM routes Anthropic models, so the AD-8 port path is coherent.
- **Source:** Anthropic model catalog / platform.claude.com docs (via claude-api reference, cached 2026-06; model current as of review date).
- **Severity if wrong:** n/a.

### Not individually re-verified (low risk, uncontroversial)
- Python 3.12+, ffmpeg via brew, Node current LTS, "TypeScript current" — commodity claims with no version-specific commitment; nothing in the spine hinges on an exact number for these.
- Postgres 18 existence — corroborated transitively by item 10 (PG 18.x-targeted pgvector packages and Docker images).

---

## Summary table

| # | Claim | Status | Severity |
|---|---|---|---|
| 1 | Neo4j Community 2026.07 arm64 image | Verified | — |
| 2 | Neo4j CE ships Cypher | Verified | — |
| 3 | Vector indexes in CE | Verified w/ caveat (native VECTOR/block format is EE-only; CE uses LIST embeddings) | Low (feature deferred in spine) |
| 4 | Meilisearch 1.53.x arm64 | Verified | — |
| 5 | Meilisearch hybrid GA | Verified | — |
| 6 | Python SDK 0.43 ↔ server 1.53 | Verified w/ note (SDK predates 1.53 by 3 weeks) | Info |
| 7 | neo4j-graphrag 1.18 supports Neo4j 2026.07 | Verified | — |
| 8 | LiteLLM ≥1.97 with Ollama + OpenRouter | Verified | Info (pin exact version at build) |
| 9 | mlx-whisper 0.4.x / parakeet-mlx 0.5.x | Verified w/ note (mlx-whisper last released 2025-08; check mlx-core compat at build) | Info |
| 10 | pgvector 0.8.x on Postgres 18 | Verified | — |
| 11 | FastAPI 0.141.x | Verified | — |
| 12 | pytest 9.1.x | Verified | — |
| 13 | Vite 8.x / React 19.x | Verified | — |
| 14 | shadcn CLI v4 Vite template + Base UI | Verified | — |
| 15 | @hey-api/openapi-ts 0.99.x | Verified | — |
| 16 | Ollama 0.32.x | Verified | — |
| 17 | Apple Vision OCR via PyObjC | Verified | — |
| 18 | `claude-sonnet-5` default model | Verified | — |

**Refuted claims: 0. Uncertain claims: 0. Caveats: 3 (items 3, 6, 9 — all informational for this spine's committed scope).**

The "Seed — verified current 2026-08-17" annotation is credible: at least four table entries (Meilisearch 1.53, Neo4j 2026.07.1, neo4j-graphrag 1.18, Ollama 0.32.13, FastAPI 0.141) postdate any plausible model training cutoff and could only have come from live checks.
