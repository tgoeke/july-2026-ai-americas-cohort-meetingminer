# Story 8.1 Review — AD-10 Amendment and Binding Catalog

## Scope

Adversarial review of Story 8.1 on `story/8-1-review`, including the eight changed paths named in the review handoff, the frozen intent contract, planner-owned design decisions, architecture decisions AD-10 and AD-8, and post-review fixes that are patchable without an owner or frozen-spec decision.

## Range

- Original story range: `82f864b51d210920ab07770720c2d81bde200355..story/8-1`
- Review basis: `story/8-1`, rebased onto `origin/main` before implementation inspection
- Review branch: `story/8-1-review`

## Findings

### Finding 1 — Synthesized prefixed entries discard required provider metadata (patch)

- **Location:** `server/meetingminer/config.py:314-354`; `server/tests/test_config_catalog.py:72-88`
- **Severity:** High
- **Finding:** A legacy role whose `model` has a `<provider>/` prefix is synthesized with `provider: None`. This contradicts the frozen I/O matrix, which requires `model: openai/gpt-5.2` to produce a one-entry catalog whose provider is `openai`.
- **Evidence:** `_catalog_from_model` creates `{"binding": tag, "label": tag}` without deriving the prefix, and `test_legacy_prefixed_model_becomes_a_one_entry_catalog` explicitly asserts `entry.provider is None`. Backward compatibility requires a synthesized entry to bypass the new undeclared-provider refusal; it does not require throwing away derivable provider metadata. The current representation also leaves a legacy prefixed entry without the provider identity later catalog and health consumers need.
- **Suggested direction:** Preserve an explicit internal authored/synthesized distinction. Derive the provider for a synthesized prefixed binding as the frozen matrix requires, but skip the catalog×providers refusal for entries marked synthesized so pre-catalog files with undeclared prefixes still load.

### Finding 2 — The active `model` can sit outside its allowed catalog (patch)

- **Location:** `server/meetingminer/config.py:397-419`
- **Severity:** High
- **Finding:** An authored role can declare `catalog: [a, b]`, `default: a`, and `model: z`; the file loads while `z` remains the binding every current call path uses. The system therefore runs a binding outside the catalog AD-10 calls allowed.
- **Evidence:** `_default_is_a_catalog_binding` validates only `default in catalog` and then leaves `model` untouched. The frozen intent says the catalog contains bindings the role may be served by and simultaneously says `model` remains the active field until Story 8.2. This is not an 8.2 selection question: before 8.2, the active binding must still be inside the boundary the new catalog declares. Legacy roles remain compatible because their synthesized one-entry catalog already contains their model.
- **Suggested direction:** Refuse an authored catalog whose active `model` is absent, with a named error listing the catalog bindings. Keep synthesized legacy roles exempt from any new spelling/normalization rule beyond their existing one-entry projection.

### Finding 3 — The shipped config still makes two stale Anthropic claims (patch)

- **Location:** `config.yaml:195-202`
- **Severity:** High
- **Finding:** AC clause 3 remains unmet: the committed chat comment says the Anthropic key was deliberately invalidated and that `claude-sonnet-5` is AD-10's superseded default, although the key was restored and the catalog amendment replaced that history.
- **Evidence:** Both statements remain verbatim after rebasing onto the main that contains Story 10.1, so the former line-overlap blocker is gone. The surrounding rules are still true: OpenAI remains the owner-selected chat model, chat has no runtime fallback, and `_BARE_OPENAI_PREFIXES` does not include `gpt-5`, so the `openai/` prefix is still required for configured endpoint resolution.
- **Suggested direction:** Delete only the invalidated-key and superseded-default claims. Preserve the current OpenAI choice, no-fallback rule, and `openai/` prefix rationale.

### Finding 4 — A bare binding can declare one provider and route to another (open — owner/spec decision)

- **Location:** `server/meetingminer/config.py:215-237,356-395`; `server/meetingminer/adapters/llm/litellm.py:54-75`
- **Severity:** High
- **Finding:** An authored prefix-less binding may explicitly declare any configured provider, but the runtime independently routes recognized bare spellings. The catalog can therefore promise one endpoint and call another.
- **Evidence:** A real `Settings` validation of `model: gpt-4o`, catalog entry `{binding: gpt-4o, provider: ollama}`, and `default: gpt-4o` succeeds. The resulting entry reports `ollama`, while `resolve_api_base('gpt-4o', providers)` resolves `https://api.openai.com/v1`. A future picker/health surface could show a local Ollama provider while the call reaches paid OpenAI. The same class of mismatch exists for bare `claude-*`. `_provider_prefix` intentionally cannot detect it because it is narrower than the runtime rule.
- **Suggested direction:** Owner/spec decision required. Either make catalog provider identity the single call-time routing fact in Story 8.2, move the shared spelling rule to a dependency-neutral module used by config and runtime, or amend the frozen prefix-less-entry rule to reject bare spellings whose routing cannot be verified here. Do not add a third hardcoded provider table to `config.py`.
