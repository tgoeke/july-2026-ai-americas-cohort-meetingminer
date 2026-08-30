-- Story 10.1: topics — machine-derived, moment-anchored navigation metadata.
--
-- The `extract` stage derives per-meeting topics from the whole transcript
-- through the same `Llm(extraction)` port as the two artifact documents, and
-- anchors each topic to the moments where it was discussed. Both tables are
-- WORKER-OWNED and MACHINE-DERIVED, and every reader must label them as such:
-- topics are navigation metadata, NOT artifacts — they never enter the
-- `extracted → approved → published` lifecycle, never get an `artifact` row,
-- and are replaced wholesale on every extraction rerun (`DELETE FROM topic
-- WHERE meeting_id = ...`; mentions cascade). Story 10.2 projects them to the
-- graph; this story writes only the record.

CREATE TABLE topic (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    meeting_id uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    -- The topic's short name and one-line gist, as extracted. Both NOT NULL:
    -- a nameless topic is a parse the stage refuses, never a row.
    name       text NOT NULL,
    gist       text NOT NULL,
    -- Which prompt/model configuration produced this row — the same shape
    -- `artifact.provenance` carries, so machine derivation is legible per row.
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, meeting_id)
);

-- Rerun replacement and the 10.2 projection both read by meeting.
CREATE INDEX topic_meeting_id_idx ON topic (meeting_id);

CREATE TRIGGER topic_set_updated_at
    BEFORE UPDATE ON topic
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- A topic and its first mention are inserted in one transaction by the
-- extraction stage, so the parent-side invariant must be checked at commit,
-- after the mention has had a chance to arrive. It also covers direct SQL:
-- no transaction may commit a topic that was never given a mention.
CREATE FUNCTION require_topic_mention() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM topic WHERE id = NEW.id)
       AND NOT EXISTS (
           SELECT 1 FROM topic_mention WHERE topic_id = NEW.id
       ) THEN
        RAISE EXCEPTION 'topic % requires at least one mention', NEW.id
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

-- One mention per (topic, containing moment): the moment is the citation
-- unit, so two stamps inside one moment collapse onto one row — the primary
-- key makes that a constraint, not a stage convention. `anchor_ms` is the
-- earliest stamp inside the moment.
CREATE TABLE topic_mention (
    topic_id   uuid NOT NULL,
    moment_id  uuid NOT NULL,
    meeting_id uuid NOT NULL,
    anchor_ms  bigint NOT NULL CHECK (anchor_ms >= 0),
    PRIMARY KEY (topic_id, moment_id),
    -- Pin the denormalized meeting id to the topic as well as the moment. A
    -- caller cannot make a cross-meeting edge internally consistent merely
    -- by supplying the moment's meeting id.
    FOREIGN KEY (topic_id, meeting_id)
        REFERENCES topic (id, meeting_id) ON DELETE CASCADE,
    -- The composite edge 0009 added for `artifact`, reused: the pair pins
    -- `meeting_id` to the moment's own meeting, so a mention can never name
    -- another meeting's moment. CASCADE, unlike `artifact`'s deliberate
    -- refusal to cascade: a mention is navigation metadata, not cited
    -- evidence, and a deleted moment takes its mentions with it rather than
    -- blocking on them.
    FOREIGN KEY (moment_id, meeting_id)
        REFERENCES moment (id, meeting_id) ON DELETE CASCADE
);

CREATE CONSTRAINT TRIGGER topic_requires_mention
    AFTER INSERT ON topic
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_topic_mention();

-- A topic without a mention is navigation to nowhere. Enforce that invariant
-- at the record, not in one pipeline stage: a moment cascade can happen while
-- extract remains settled during augmentation. Locking the topic serializes
-- concurrent removals of different mentions so two transactions cannot each
-- observe the other's still-present edge and leave an orphan after both commit.
CREATE FUNCTION delete_topic_when_last_mention_removed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM topic WHERE id = OLD.topic_id FOR UPDATE;
    DELETE FROM topic
    WHERE id = OLD.topic_id
      AND NOT EXISTS (
          SELECT 1 FROM topic_mention WHERE topic_id = OLD.topic_id
      );
    RETURN OLD;
END;
$$;

CREATE TRIGGER topic_mention_delete_or_move_orphan_topic
    AFTER DELETE OR UPDATE OF topic_id ON topic_mention
    FOR EACH ROW EXECUTE FUNCTION delete_topic_when_last_mention_removed();

-- Row triggers do not run for TRUNCATE. A statement-level trigger closes that
-- route so bulk removal preserves the same no-orphan invariant.
CREATE FUNCTION delete_topics_when_mentions_truncated() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM topic;
    RETURN NULL;
END;
$$;

CREATE TRIGGER topic_mention_truncate_topics
    AFTER TRUNCATE ON topic_mention
    FOR EACH STATEMENT EXECUTE FUNCTION delete_topics_when_mentions_truncated();

-- The 10.2 projection and the moment views read mentions by moment.
CREATE INDEX topic_mention_moment_id_idx ON topic_mention (moment_id);

-- 0010's comment says widening the document-kind CHECK is a story; this is
-- it. The topics document joins the two artifact documents in
-- `extraction_source`, always with origin 'generated' — no drop declares a
-- topics file, so there is no adoption path.
ALTER TABLE extraction_source
    DROP CONSTRAINT extraction_source_kind_check;
ALTER TABLE extraction_source
    ADD CONSTRAINT extraction_source_kind_check
    CHECK (kind IN ('arch-summary', 'action-items', 'topics'));
