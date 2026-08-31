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
