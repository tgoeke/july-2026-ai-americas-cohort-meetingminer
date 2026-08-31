-- Story 10.2a: thread curation — the API-owned half of thread grouping.
--
-- Migration 0015 declared `thread` and `topic_thread` WORKER-OWNED and
-- MACHINE-DERIVED, and said human curation would arrive "as separate
-- API-owned rows on top (AD-5)". These are those rows. Nothing here is
-- written by the worker; the worker only *reads* them, and it reads them
-- before it writes, which is the whole mechanism by which a correction
-- survives the next re-derivation.
--
-- **Why curation cannot be an edit of `thread` or `topic_thread`.**
-- `domain/threads.py:derive_threads` re-derives every thread from the stored
-- topics on every pass. It reuses a `thread` row by `identity_key`, then by
-- attachment, then mints; it rewrites `thread.name` from the cluster's seed
-- topic; and it moves each topic's `topic_thread` row onto whichever thread
-- the partition put it in. Any curation written into those columns is
-- therefore overwritten by the next pass — silently, which is the failure
-- AD-18 forbids and the failure a user would watch happen to their own
-- correction. Curation lives in its own tables, and the derivation resolves
-- it as an *input* rather than colliding with it as an output. That is the
-- same shape `participant_alias` already has (migration 0005): the API writes
-- the alias, `align` resolves it before every insert, and a merge survives
-- every re-ingest.
--
-- **What each table corrects, and how a rerun preserves it:**
--
--   rename → `thread_curation`     — a name in a column the derivation never
--                                    writes. Preserved because the derivation
--                                    writes `thread.name` and readers display
--                                    `COALESCE(thread_curation.name,
--                                    thread.name)`. The two never collide.
--   merge  → `thread_alias`        — absorbed thread → survivor. Preserved
--                                    because the derivation resolves a
--                                    cluster's thread through it before
--                                    writing memberships, so the absorbed
--                                    row re-derives into the survivor every
--                                    pass instead of re-splitting.
--   split  → `thread_topic_pin`    — this subject, in this meeting, belongs
--                                    to this thread regardless of what the
--                                    partition said. Preserved because the
--                                    derivation applies the pin *before* the
--                                    membership UPSERT, so a pinned topic is
--                                    written to its pinned thread exactly
--                                    once and an unchanged rerun still writes
--                                    nothing at all.
--
-- **`thread.color_ordinal` is untouched by every one of them** (0017). A merge
-- writes an alias row and moves memberships — the survivor keeps its own
-- ordinal and the absorbed row keeps its, because neither is UPDATEd. A split
-- inserts a *new* `thread` row, which takes a new ordinal by the ordinary
-- insert path, exactly as 0017's own comment anticipated.

-- A resolved pin is human provenance in the worker-owned output, not one of
-- the three machine legs migration 0015 originally admitted. The curation
-- record remains API-owned; this fourth value lets the derivation faithfully
-- state which input decided the membership after a replacement topic UUID has
-- made the split-time hint stale.
ALTER TABLE topic_thread DROP CONSTRAINT topic_thread_linked_by_check;
ALTER TABLE topic_thread ADD CONSTRAINT topic_thread_linked_by_check
    CHECK (linked_by IN (
        'seed', 'normalized-name', 'embedding-similarity', 'curated'
    ));

-- ---------------------------------------------------------------------------
-- Rename.
-- ---------------------------------------------------------------------------

-- A human name for a thread, keyed by the thread it names. Separate from
-- `thread.name` rather than replacing it: keeping both is what lets a reader
-- tell a curated name from a derived one, which AD-18 requires of anything
-- that presents machine output and human output in the same place. The
-- derived name is not discarded — a curation that is later cleared falls back
-- to whatever the machine currently calls the thread, not to a stale copy.
CREATE TABLE thread_curation (
    thread_id  uuid PRIMARY KEY REFERENCES thread (id) ON DELETE CASCADE,
    -- Non-blank by constraint, not by API convention: a curated name whose
    -- only content is whitespace would render as an unnamed band while
    -- suppressing the machine name that would have named it.
    name       text NOT NULL CONSTRAINT thread_curation_name_not_blank
                   CHECK (btrim(name) <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER thread_curation_set_updated_at
    BEFORE UPDATE ON thread_curation
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Merge.
-- ---------------------------------------------------------------------------

-- One absorbed thread and the thread it was merged into. `thread_id` is the
-- PRIMARY KEY, so a thread can be absorbed by at most one survivor and a
-- concurrent double-merge loses cleanly on the constraint rather than
-- producing two answers.
CREATE TABLE thread_alias (
    thread_id      uuid PRIMARY KEY REFERENCES thread (id) ON DELETE CASCADE,
    merged_into_id uuid NOT NULL REFERENCES thread (id) ON DELETE CASCADE,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT thread_alias_not_self CHECK (thread_id <> merged_into_id)
);

CREATE INDEX thread_alias_merged_into_id_idx ON thread_alias (merged_into_id);

CREATE TRIGGER thread_alias_set_updated_at
    BEFORE UPDATE ON thread_alias
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The map is FLAT: no A→B→C. Every resolver in the codebase follows exactly
-- one hop (`domain/thread_curation.py`, and the SQL fragment it owns), so a
-- chain would silently strand A on a thread that is itself merged away — the
-- reader would land on an empty band and no component would report why.
-- `participant_alias` states the same rule and enforces it only in the API;
-- here it is enforced at the record as well, because thread curation has two
-- writers of the resolved answer (the API's read path and the worker's
-- derivation) and a convention held in one of them is not a guarantee for the
-- other. The cure for a wanted A→B→C is to merge A directly onto C, which the
-- API offers once B→C exists.
CREATE FUNCTION thread_alias_is_flat() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM thread_alias WHERE thread_id = NEW.merged_into_id) THEN
        RAISE EXCEPTION
            'thread % is itself merged away and cannot be a merge target'
            ' (thread_alias is a flat map, never a chain)',
            NEW.merged_into_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM thread_alias
        WHERE merged_into_id = NEW.thread_id AND thread_id <> NEW.thread_id
    ) THEN
        RAISE EXCEPTION
            'thread % has already absorbed another thread and cannot itself'
            ' be merged away (thread_alias is a flat map, never a chain)',
            NEW.thread_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER thread_alias_flat
    BEFORE INSERT OR UPDATE ON thread_alias
    FOR EACH ROW EXECUTE FUNCTION thread_alias_is_flat();

-- ---------------------------------------------------------------------------
-- Split.
-- ---------------------------------------------------------------------------

-- One human decision that a subject, as discussed in one meeting, belongs to
-- a named thread — whatever the partition would otherwise have done with it.
--
-- **Why the key is (meeting_id, normalized_name) and not topic_id.** Story
-- 10.1 replaces a meeting's `topic` rows wholesale on re-extraction, minting
-- fresh UUIDs for the same subjects. A pin keyed on `topic_id` would be
-- deleted by that cascade and the split would vanish with no record that it
-- ever existed — the silent discard this story exists to prevent. The
-- normalized name is the same durable content key `thread.identity_key` uses
-- for the same reason (0015), and `domain/threads.py:normalized_topic_name`
-- is its single definition.
--
-- `topic_id` rides along as a *hint*, not a reference, and deliberately
-- carries no foreign key: it is the exact-match fast path the API's read
-- queries join on, so no reader has to reimplement NFKC-casefold
-- normalization in SQL and risk disagreeing with the Python that wrote the
-- row. After a re-extraction it dangles, a LEFT JOIN on it simply matches
-- nothing, and `derive_threads` re-matches the pin by its durable key and
-- reports having done so.
CREATE TABLE thread_topic_pin (
    meeting_id      uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    -- `normalized_topic_name(topic.name)`, computed by the API in Python.
    -- Non-empty by constraint: a topic whose name is entirely punctuation
    -- normalizes to the empty string, which is not an identity — two such
    -- topics in one meeting would claim the same pin. The API refuses to pin
    -- one by name rather than letting it collide here.
    normalized_name text NOT NULL CONSTRAINT thread_topic_pin_name_not_blank
                        CHECK (normalized_name <> ''),
    thread_id       uuid NOT NULL REFERENCES thread (id) ON DELETE CASCADE,
    -- The hint. UNIQUE because a topic belongs to one meeting and has one
    -- name, so two live pins can never name the same topic row.
    topic_id        uuid NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (meeting_id, normalized_name),
    CONSTRAINT thread_topic_pin_topic_id_unique UNIQUE (topic_id)
);

CREATE INDEX thread_topic_pin_thread_id_idx ON thread_topic_pin (thread_id);

CREATE TRIGGER thread_topic_pin_set_updated_at
    BEFORE UPDATE ON thread_topic_pin
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- The one thread row the API mints.
-- ---------------------------------------------------------------------------
--
-- A split needs a destination, and a destination needs a `thread.id` (story
-- 10.3's timeline and the graph's `Thread` node both key on it) and a
-- `color_ordinal` (0017). Migration 0015 said "nothing in this migration is
-- written by the api"; 0017 then wrote down what a split would be — "a split
-- is a *new* `thread` row, so it takes a new ordinal from the sequence by the
-- ordinary insert path". This migration reconciles the two: the API inserts
-- that row, and nothing else in `thread`. It is the same narrow exception
-- `api/speakers.py` already holds against worker-owned `participant`, where a
-- curator may mint the identity the machine could not produce on its own.
--
-- The minted row is distinguishable and un-stealable by construction, not by
-- convention:
--
--   * `identity_key` is namespaced `curated-split:<uuid>`. A derived key is
--     either a normalized name — which `normalized_topic_name` reduces to
--     alphanumerics and single spaces, so it can contain neither ':' nor '-'
--     — or the literal prefix `topic-name-sha256:`. The two key spaces are
--     therefore disjoint, and `_threads_by_identity_key` can never claim a
--     curated row for a derived cluster.
--   * `link_rule` is 'curated', so every reader of the row can say which
--     kind of thread it is holding without consulting another table.
--
-- `derive_threads` additionally refuses to reuse a curated row by
-- *attachment*, which is the subtler theft: a curated row is attached to the
-- very topics that were split onto it, so the ordinary attachment lookup
-- would hand it back to the cluster the split was correcting and overwrite
-- its identity and name on the next pass.
COMMENT ON TABLE thread_curation IS
    'API-owned (AD-5). A human name for a thread; overrides thread.name for'
    ' display and is never written by the worker.';
COMMENT ON TABLE thread_alias IS
    'API-owned (AD-5). Flat merge map, absorbed thread -> survivor, resolved'
    ' by derive_threads before it writes memberships.';
COMMENT ON TABLE thread_topic_pin IS
    'API-owned (AD-5). A split: this subject in this meeting belongs to this'
    ' thread, keyed on durable normalized content so a re-extraction cannot'
    ' silently discard it.';
