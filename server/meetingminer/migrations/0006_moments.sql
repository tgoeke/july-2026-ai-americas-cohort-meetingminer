-- Story 1.6: moments — the addressable unit every later epic cites, replays and
-- extracts from (AD-2, AD-5, AD-6; ERD `MEETING ||--o{ MOMENT`,
-- `MOMENT }o--o| SCREENSHOT`, `MOMENT ||--o{ TRANSCRIPT_SEGMENT`).

-- One span of the meeting timeline, cut at the union of transcript-derived and
-- screenshot-derived boundaries. A moment id is minted once and is the citation
-- currency (AD-6), so this table is the one meeting-scoped store the `moments`
-- stage upserts rather than replaces: "augmentation adds, never destroys"
-- (SPEC Constraints) means a rerun must not delete, renumber or re-key a moment
-- that already exists.
CREATE TABLE moment (
    id                   uuid PRIMARY KEY DEFAULT uuidv7(),
    meeting_id           uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    -- What idempotence keys on, in place of a delete-and-rewrite:
    -- `transcript:<start_ms>` or `screen:<start_ms>`. Derived from the moment's
    -- own start offset, which comes from the provided transcript and does not
    -- move when a recording arrives later (story 1.12), so a pre-existing
    -- moment converges on its own row across augmentation.
    identity_key         text NOT NULL,
    -- NO ORDINAL COLUMN, deliberately. Order is `start_ms`. An ordinal cannot
    -- survive a new moment being inserted between two existing ones — exactly
    -- what story 1.12 does when a recovered recording adds screen-derived
    -- moments alongside the transcript-derived ones — without renumbering rows
    -- the SPEC forbids renumbering.
    derived_from         text NOT NULL
                         CHECK (derived_from IN ('transcript', 'screen', 'both')),
    -- Integer milliseconds from recording start, the project-wide convention.
    start_ms             bigint NOT NULL CHECK (start_ms >= 0),
    end_ms               bigint NOT NULL CHECK (end_ms >= 0),
    -- The meeting's wall clock plus `start_ms`, with the meeting's own
    -- precision carried alongside so a day-precision meeting never reads as if
    -- its moments were timed to the second.
    started_at           timestamptz NOT NULL,
    started_at_precision text NOT NULL
                         CHECK (started_at_precision IN ('second', 'day')),
    -- The screenshot on display when this moment starts. NULL on a
    -- transcript-only meeting (the ERD already makes it optional), and also
    -- NULL on a moment starting after the last capture ended -- a transcript
    -- routinely outruns its recording in this corpus, and nothing was on
    -- screen there to name. SET NULL rather than CASCADE: a `screens` rerun
    -- must not delete moment evidence, it must leave the dangling reference
    -- visible.
    screenshot_id        uuid REFERENCES screenshot (id) ON DELETE SET NULL,
    -- UX-DR11's transitional deep link: the drop's Stream URL verbatim, on a
    -- meeting that has no replay evidence. Cleared once one arrives.
    source_deep_link     text,
    segment_count        integer NOT NULL DEFAULT 0 CHECK (segment_count >= 0),
    -- The boundary reason and the config the boundary was decided against, so a
    -- retune is legible after the fact (AD-10, AD-13).
    provenance           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (end_ms >= start_ms),
    UNIQUE (meeting_id, identity_key)
);

-- Order is `start_ms`, and the stage reads one meeting's moments in that order.
CREATE INDEX moment_meeting_start_idx ON moment (meeting_id, start_ms);
CREATE INDEX moment_screenshot_id_idx ON moment (screenshot_id);

CREATE TRIGGER moment_set_updated_at
    BEFORE UPDATE ON moment
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Which transcript segments a moment covers. `UNIQUE (transcript_segment_id)`
-- is the ERD's `MOMENT ||--o{ TRANSCRIPT_SEGMENT` enforced in the schema rather
-- than assumed: a segment belongs to exactly one moment, so two moments can
-- never claim the same words. Both sides CASCADE — `align` replaces this
-- meeting's `transcript_segment` rows wholesale on a rerun, so these links are
-- rebuilt by the `moments` stage and never assumed durable.
CREATE TABLE moment_segment (
    moment_id             uuid NOT NULL REFERENCES moment (id) ON DELETE CASCADE,
    transcript_segment_id uuid NOT NULL REFERENCES transcript_segment (id)
                          ON DELETE CASCADE,
    created_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (moment_id, transcript_segment_id),
    UNIQUE (transcript_segment_id)
);
