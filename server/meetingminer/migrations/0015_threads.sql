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
-- `thread.id`. So a thread is identified by `identity_key`, a value the
-- derivation computes from the cluster alone (the normalized name of its
-- earliest topic), and the derivation UPSERTs on it rather than deleting and
-- re-minting. `DELETE FROM thread` on every run would satisfy the record but
-- break every reference the moment a rerun changed nothing.

CREATE TABLE thread (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    -- What makes a rerun land on this same row. The normalized name of the
    -- cluster's seed topic — the earliest by (meeting.started_at, meeting.id,
    -- normalized name, topic.id). UNIQUE because the derivation upserts on
    -- it, and because two clusters cannot present the same seed name: every
    -- topic sharing a normalized name is already unioned into one cluster.
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

-- A thread and its seed link are inserted in one transaction by the
-- derivation, so the parent-side invariant must be checked at commit, after
-- the link has had a chance to arrive. Same construction as 0014's
-- `topic_requires_mention`, and for the same reason: it also covers direct
-- SQL, so no transaction may commit a thread that was never given a topic.
CREATE FUNCTION require_thread_topic() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM thread WHERE id = NEW.id)
       AND NOT EXISTS (
           SELECT 1 FROM topic_thread WHERE thread_id = NEW.id
       ) THEN
        RAISE EXCEPTION 'thread % requires at least one topic', NEW.id
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER thread_requires_topic
    AFTER INSERT ON thread
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_thread_topic();

-- A thread with no topics is navigation to nowhere. Enforce it at the record,
-- not in the derivation: a topic cascade can happen at any time (an
-- extraction rerun replaces a meeting's topics wholesale), and re-derivation
-- moves memberships between threads. Locking the thread serializes concurrent
-- removals of different memberships so two transactions cannot each observe
-- the other's still-present link and leave an empty thread after both commit.
CREATE FUNCTION delete_thread_when_last_topic_removed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM thread WHERE id = OLD.thread_id FOR UPDATE;
    DELETE FROM thread
    WHERE id = OLD.thread_id
      AND NOT EXISTS (
          SELECT 1 FROM topic_thread WHERE thread_id = OLD.thread_id
      );
    RETURN OLD;
END;
$$;

CREATE TRIGGER topic_thread_delete_or_move_orphan_thread
    AFTER DELETE OR UPDATE OF thread_id ON topic_thread
    FOR EACH ROW EXECUTE FUNCTION delete_thread_when_last_topic_removed();

-- Row triggers do not run for TRUNCATE. A statement-level trigger closes that
-- route so bulk removal preserves the same no-orphan invariant.
CREATE FUNCTION delete_threads_when_memberships_truncated() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM thread;
    RETURN NULL;
END;
$$;

CREATE TRIGGER topic_thread_truncate_threads
    AFTER TRUNCATE ON topic_thread
    FOR EACH STATEMENT EXECUTE FUNCTION delete_threads_when_memberships_truncated();
