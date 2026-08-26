-- Story 1.2: ingestion job tables (AD-11).
-- IDs are UUIDv7 minted by Postgres (uuidv7() is native in pg18).

CREATE TABLE job (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    source_id  text NOT NULL,
    drop_path  text NOT NULL,
    corpus     text NOT NULL CHECK (corpus IN ('scripted', 'real')),
    status     text NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued', 'running', 'done', 'failed')),
    error      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- One live (non-failed) job per sourceId (AD-14); a failed job is re-queued
-- in place by the intake endpoint, never duplicated.
CREATE UNIQUE INDEX job_source_id_live_key
    ON job (source_id)
    WHERE status <> 'failed';

CREATE TABLE job_stage (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id     uuid NOT NULL REFERENCES job (id) ON DELETE CASCADE,
    name       text NOT NULL,
    status     text NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued', 'running', 'done', 'failed', 'skipped')),
    error      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, name)
);
