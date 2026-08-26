-- Story 1.4: per-frame OCR, cross-meeting screens, and per-meeting screenshots
-- (AD-2, AD-3, AD-5, AD-11; ERD `SCREEN ||--o{ SCREENSHOT`, `MEETING ||--o{ SCREENSHOT`).

-- Recognized text and block geometry for one sampled frame, written by the
-- `ocr` stage. A separate table rather than columns on `frame` because stage
-- ownership is what makes reruns safe: `frames` owns `frame`, `ocr` owns this,
-- so an `ocr` rerun replaces only these rows and a `frames` rerun cascades
-- them away rather than leaving text attached to regenerated JPEGs.
CREATE TABLE frame_ocr (
    frame_id          uuid PRIMARY KEY REFERENCES frame (id) ON DELETE CASCADE,
    meeting_id        uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    -- Which engine produced this, so a corpus mixing apple-vision and
    -- tesseract output stays interpretable (AD-8).
    engine            text NOT NULL,
    -- Reading-order text as recognized, and the normalization the `screens`
    -- stage actually compares (lower-cased, punctuation folded to spaces).
    text              text NOT NULL,
    normalized_text   text NOT NULL,
    -- Block geometry summary, normalized 0-1, feeding view-type
    -- classification. The blocks themselves stay in jsonb: no query joins on
    -- them, and their shape belongs to the Ocr port, not to the schema.
    block_count       integer NOT NULL CHECK (block_count >= 0),
    text_density      numeric NOT NULL CHECK (text_density >= 0),
    mean_block_height numeric NOT NULL CHECK (mean_block_height >= 0),
    blocks            jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- The `ocr` and `screens` stages both read/replace one meeting's rows.
CREATE INDEX frame_ocr_meeting_id_idx ON frame_ocr (meeting_id);

CREATE TRIGGER frame_ocr_set_updated_at
    BEFORE UPDATE ON frame_ocr
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- A distinct application screen or slide. Cross-meeting by design (AD-5): it
-- is upserted by `identity_key` and never deleted or truncated by a stage
-- rerun, which is what gives a Screen lineage across meetings.
CREATE TABLE screen (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    -- SHA-256 of the normalized signature, or `meeting:<id>:<ordinal>` when
    -- the signature carries too few tokens to identify anything (a camera
    -- gallery); scoping those to their meeting keeps every textless screen in
    -- the corpus from collapsing onto one row.
    identity_key text NOT NULL UNIQUE,
    signature    text NOT NULL,
    -- Human-editable label (Epic 2); the worker never writes it.
    label        text,
    view_type    text NOT NULL
                 CHECK (view_type IN ('slide', 'ui-screen', 'participant-gallery')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER screen_set_updated_at
    BEFORE UPDATE ON screen
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- One capture of a screen inside one meeting: the image on disk plus the span
-- of frames it covers and the cue(s) that produced it. Per-meeting evidence,
-- so a `screens` rerun replaces these rows (and only this meeting's) while the
-- `screen` rows they point at survive.
CREATE TABLE screenshot (
    id                      uuid PRIMARY KEY DEFAULT uuidv7(),
    meeting_id              uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    screen_id               uuid NOT NULL REFERENCES screen (id) ON DELETE RESTRICT,
    ordinal                 integer NOT NULL CHECK (ordinal >= 1),
    start_offset_ms         bigint NOT NULL CHECK (start_offset_ms >= 0),
    end_offset_ms           bigint NOT NULL CHECK (end_offset_ms >= 0),
    frame_count             integer NOT NULL CHECK (frame_count > 0),
    -- The most text-rich frame the capture covers — the one copied to `path`.
    -- SET NULL rather than CASCADE: a `frames` rerun must not silently delete
    -- screenshot evidence, it must leave the dangling reference visible.
    representative_frame_id uuid REFERENCES frame (id) ON DELETE SET NULL,
    -- Relative to MM_CONTENT_ROOT and nothing else (AD-3).
    path                    text NOT NULL,
    view_type               text NOT NULL
                            CHECK (view_type IN ('slide', 'ui-screen', 'participant-gallery')),
    -- Which cue(s) produced this capture: text-change, size-delta,
    -- dwell-drift, first-frame.
    capture_cues            text[] NOT NULL DEFAULT '{}',
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CHECK (end_offset_ms >= start_offset_ms),
    UNIQUE (meeting_id, ordinal)
);

CREATE INDEX screenshot_screen_id_idx ON screenshot (screen_id);

CREATE TRIGGER screenshot_set_updated_at
    BEFORE UPDATE ON screenshot
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
