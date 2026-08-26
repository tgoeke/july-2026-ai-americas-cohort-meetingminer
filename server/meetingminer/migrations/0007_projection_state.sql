-- Story 1.7: projection state — which meetings are projected into Neo4j and
-- Meilisearch, under which embedder and which chunking (AD-4, AD-8;
-- retrieval-prior-art.md §3 rules 3 and 4).
--
-- This is the projections module's ONLY Postgres write. Both retrieval stores
-- are disposable derived projections (AD-4), so nothing about their *content*
-- is recorded here; what is recorded is the three facts that cannot be
-- recovered from a wiped store:
--
--   * `structural_at` — the meeting's nodes and documents exist. Written by a
--     pass that never calls the `Embedder`, so it holds with the model host
--     down (§3 rule 4) and BM25 retrieval is fully functional in that state.
--   * `embedded_at` — NULL until the vectors are in. That nullability is the
--     whole resumability mechanism: an Ollama outage leaves a structurally
--     projected meeting that a later `rebuild --embed-only` finishes, with no
--     structural rewrite and no corrupt store in between.
--   * `embedder_model` / `embedder_dimension` — which model wrote the vectors
--     (§3 rule 3, AD-8). Embedding width is baked into the index, so a config
--     that disagrees with what a store already holds must be a named refusal
--     before any write, never a silent write of mismatched-width vectors.
--
-- The chunking columns are here for the same reason the embedder columns are:
-- chunk size and overlap are a recorded tuning lever read from config.yaml
-- (§6-§7), and retuning them makes every projected chunk stale. Recording the
-- values a meeting was projected under is what lets the worker and `rebuild`
-- tell a current projection from one that predates the retune.
CREATE TABLE meeting_projection (
    meeting_id          uuid PRIMARY KEY REFERENCES meeting (id) ON DELETE CASCADE,
    structural_at       timestamptz NOT NULL DEFAULT now(),
    -- NULL means "structurally indexed, not embedded" — a legitimate, fully
    -- searchable state, not a failure (see above).
    embedded_at         timestamptz,
    embedder_model      text NOT NULL,
    embedder_dimension  integer NOT NULL CHECK (embedder_dimension > 0),
    chunk_max_chars     integer NOT NULL CHECK (chunk_max_chars > 0),
    -- Zero overlap is a legitimate tuning choice; a negative one is not.
    chunk_overlap_turns integer NOT NULL CHECK (chunk_overlap_turns >= 0),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- `rebuild --embed-only` selects on this, and so does the worker's trigger
-- when it decides between a full projection and an embedding retry.
CREATE INDEX meeting_projection_embedded_at_idx
    ON meeting_projection (embedded_at);

CREATE TRIGGER meeting_projection_set_updated_at
    BEFORE UPDATE ON meeting_projection
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
