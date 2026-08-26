-- Story 4.2: visible, swappable extraction prompts. `extraction_source` gains
-- a per-document record of exactly which prompt config produced it, beside
-- the `model`/`prompt_version` columns 0010 already carries.
--
-- `prompt_hash` is the truncated sha256 (first 16 hex characters) of the
-- resolved template text (`llm.roles.extraction.arch_summary_prompt` /
-- `.action_items_prompt`), not of the whole rendered prompt or the whole
-- config.yaml: two edits to unrelated config keys (e.g. `frames.jpeg_quality`)
-- must never perturb extraction provenance, and this answers "which prompt
-- text, specifically" at the per-artifact-row granularity `PROMPT_VERSION`
-- alone cannot — a config-only prompt edit does not bump that constant.
--
-- Nullable, no CHECK, same shape as `model`: NULL for an adopted document
-- (no prompt was sent), set for a generated one.
ALTER TABLE extraction_source
    ADD COLUMN prompt_hash text;
