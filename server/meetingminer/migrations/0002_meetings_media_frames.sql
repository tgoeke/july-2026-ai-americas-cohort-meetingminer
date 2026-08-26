-- Story 1.3: the Meeting row plus the probe/frames evidence tables (AD-2, AD-3, AD-5).
-- IDs are UUIDv7 minted by Postgres (uuidv7() is native in pg18).

-- updated_at maintenance (story 1.2 deferred item, closed here now that the
-- worker mutates job/job_stage on every checkpoint): a trigger, not a
-- convention every future UPDATE has to remember.
CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER job_set_updated_at
    BEFORE UPDATE ON job
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER job_stage_set_updated_at
    BEFORE UPDATE ON job_stage
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Exactly one meeting per job (AD-5/AD-14, ERD `JOB ||--|| MEETING`), minted
-- by the worker when it claims the job. source_id is unique too: re-processing
-- an occurrence re-runs its existing job, never a second Meeting row.
CREATE TABLE meeting (
    id                   uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id               uuid NOT NULL UNIQUE REFERENCES job (id) ON DELETE CASCADE,
    source_id            text NOT NULL UNIQUE,
    corpus               text NOT NULL CHECK (corpus IN ('scripted', 'real')),
    -- Wall clock comes from the drop's metadata.json and is never re-derived
    -- from media metadata (AD-1); precision records how much of it is real.
    started_at           timestamptz NOT NULL,
    started_at_precision text NOT NULL
                         CHECK (started_at_precision IN ('second', 'day')),
    -- Best-effort human label from the source side's provenance record.
    title                text,
    has_recording        boolean NOT NULL,
    provenance           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER meeting_set_updated_at
    BEFORE UPDATE ON meeting
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ffprobe facts for the drop's recording.mp4, written by the `probe` stage.
-- One row per meeting (the meeting id is the primary key), so a rerun upserts
-- rather than accumulating.
CREATE TABLE meeting_media (
    meeting_id        uuid PRIMARY KEY REFERENCES meeting (id) ON DELETE CASCADE,
    duration_ms       bigint,
    container         text,
    size_bytes        bigint,
    video_codec       text,
    width             integer,
    height            integer,
    frame_rate        numeric,
    video_bit_rate    bigint,
    audio_codec       text,
    audio_channels    integer,
    audio_sample_rate integer,
    audio_bit_rate    bigint,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER meeting_media_set_updated_at
    BEFORE UPDATE ON meeting_media
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ffmpeg-sampled JPEGs written by the `frames` stage. `path` is relative to
-- MM_CONTENT_ROOT and nothing else (AD-3) — the binaries live on disk, only
-- the path lives here.
CREATE TABLE frame (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    meeting_id uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE,
    offset_ms  bigint NOT NULL CHECK (offset_ms >= 0),
    path       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (meeting_id, offset_ms)
);

CREATE TRIGGER frame_set_updated_at
    BEFORE UPDATE ON frame
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
