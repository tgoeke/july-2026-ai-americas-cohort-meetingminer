-- Story 1.11: the screen-capture retune against measured baselines
-- (capture-measurements.md §2-§4; AD-5, AD-11, NFR8).

-- The share region of one meeting's frames, as fractions of the full frame
-- with the origin top left. Per-meeting derived evidence owned by the
-- `screens` stage: a rerun replaces this row, and only this meeting's.
--
-- It is a row rather than a config constant because §2 measured the layout as
-- *detect-once geometry* — stable for a whole recording, but a property of
-- that recording — and a row rather than nothing at all because change
-- detection ran on it: without it, a re-read of the capture set cannot say
-- what the extractor was actually looking at. `detected` records whether the
-- webcam column was found; an inconclusive survey falls back to the full
-- frame and says so rather than pretending.
CREATE TABLE meeting_crop (
    meeting_id      uuid PRIMARY KEY REFERENCES meeting (id) ON DELETE CASCADE,
    -- `left`/`right` are reserved words in SQL, so all four carry the suffix
    -- rather than only the two that need it.
    left_fraction   double precision NOT NULL CHECK (left_fraction >= 0 AND left_fraction <= 1),
    top_fraction    double precision NOT NULL CHECK (top_fraction >= 0 AND top_fraction <= 1),
    right_fraction  double precision NOT NULL CHECK (right_fraction >= 0 AND right_fraction <= 1),
    bottom_fraction double precision NOT NULL CHECK (bottom_fraction >= 0 AND bottom_fraction <= 1),
    -- Whether the survey found the webcam column that defines §2's two-part
    -- layout, and what it found (`webcam-column+bottom-strip`, `inconclusive`).
    detected        boolean NOT NULL,
    method          text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (right_fraction > left_fraction),
    CHECK (bottom_fraction > top_fraction)
);

CREATE TRIGGER meeting_crop_set_updated_at
    BEFORE UPDATE ON meeting_crop
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- What the classifier could not resolve about a capture, kept beside what it
-- did decide. §3 found loading pages are not separable from real UI on any
-- single threshold, and §4 found the brightness/saturation pair cannot tell
-- avatar-tile gallery from a screen. Per NFR8 those frames are tagged, never
-- dropped — `likely-transition`, `avatar-gallery-unresolved`.
--
-- No CHECK constraint, deliberately, exactly as `capture_cues` has none: a
-- new tag must not need a migration. `view_type` keeps its CHECK, and the
-- three values it allows are unchanged by this story.
ALTER TABLE screenshot
    ADD COLUMN classification_tags text[] NOT NULL DEFAULT '{}';
