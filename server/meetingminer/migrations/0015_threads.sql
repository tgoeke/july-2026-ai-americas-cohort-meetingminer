-- Story 10.2: threads — machine-derived, cross-meeting navigation metadata.
--
-- A thread is one subject followed across meetings. `domain/threads.py`
-- derives them corpus-wide from the `topic` rows story 10.1's extract stage
-- wrote: topics union by normalized name and by embedding cosine similarity
-- at or above the configured threshold, and each resulting cluster is one
-- thread. Both tables here are WORKER-OWNED and MACHINE-DERIVED, and every
-- reader must label them as such: threads are navigation metadata, NOT
-- artifacts — they never enter the `extracted → approved → published`
-- lifecycle and never get an `artifact` row. Story 10.2a adds human curation
-- (merge, split, rename) as separate API-owned rows on top (AD-5); nothing in
-- this migration is written by the api.
--
-- The difference from 0014's `topic`, and the reason this table is not simply
-- replaced on every rerun: derivation must be IDEMPOTENT — a rerun over
-- unchanged topics must yield the *same* threads, ids included, because the
-- graph projection, 10.2a's curation and 10.3's timeline all key on
-- `thread.id`. So a thread is identified by `identity_key`, a value derived
-- from normalized cluster content rather than topic chronology, and the
-- derivation reuses an existing row before minting. Empty identity rows are
-- retained because story 10.1 replaces a meeting's topic rows wholesale; a
-- later explicit sweep may remove rows proven genuinely dead.

CREATE TABLE thread (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    -- What makes a rerun land on this same row. The canonical normalized name
    -- selected from cluster content, independent of meeting chronology.
    -- UNIQUE because topics sharing normalized content are already unioned.
    identity_key text NOT NULL UNIQUE,
    -- The display name, taken verbatim from the seed topic. The machine may
    -- rewrite this on a rerun when the seed's own name changed; it never
    -- invents one. Human renaming is story 10.2a and does not write here.
    name         text NOT NULL,
    -- Which rule produced this thread's membership, recorded per row so a
    -- config change is legible in the data rather than only in config.yaml.
    link_rule    text NOT NULL,
    -- The derivation's parameters — the threshold, the embedder model and
    -- dimension. Same shape and same purpose as `topic.provenance` and
    -- `artifact.provenance`: machine derivation is legible per row.
    derivation   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER thread_set_updated_at
    BEFORE UPDATE ON thread
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- One thread per topic: `topic_id` is the PRIMARY KEY, not half of a
-- composite. A topic discussed in one meeting belongs to exactly one subject
-- thread, so a second membership row is a derivation bug the record refuses
-- rather than a fan-out a reader has to collapse. That is also what lets the
-- derivation move a topic between threads with a single ON CONFLICT UPDATE.
CREATE TABLE topic_thread (
    topic_id  uuid PRIMARY KEY REFERENCES topic (id) ON DELETE CASCADE,
    thread_id uuid NOT NULL REFERENCES thread (id) ON DELETE CASCADE,
    -- Which leg of the rule attached this topic. 'seed' is the cluster's own
    -- identity topic; the other two say whether the name or the vector
    -- carried it in. Checked here so a future leg is a migration, not a typo.
    linked_by text NOT NULL
        CHECK (linked_by IN ('seed', 'normalized-name', 'embedding-similarity')),
    similarity real CHECK (similarity IS NULL OR (similarity >= 0.0 AND similarity <= 1.0)),
    created_at timestamptz NOT NULL DEFAULT now(),
    -- A name link carries no similarity score and an embedding link must
    -- carry one: the row states which leg fired *and* the evidence for it, so
    -- a threshold change can be audited against what was actually linked.
    CONSTRAINT topic_thread_similarity_matches_leg CHECK (
        (linked_by = 'embedding-similarity' AND similarity IS NOT NULL)
        OR (linked_by <> 'embedding-similarity' AND similarity IS NULL)
    )
);

-- The projection and the traversal both read a thread's membership.
CREATE INDEX topic_thread_thread_id_idx ON topic_thread (thread_id);

-- A thread row is durable identity, not an assertion that a membership exists
-- at this instant. In particular, story 10.1 deletes and recreates all topics
-- for one meeting before thread derivation runs again. Cascades and TRUNCATE
-- therefore remove memberships only; they never delete thread identity as a
-- side effect. Genuinely dead rows require a separate, explicit sweep with a
-- retention policy rather than an eager last-link trigger.
