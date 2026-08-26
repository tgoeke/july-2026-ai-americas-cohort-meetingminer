-- Story 2.5: series, projects, products and meeting assignment (AD-5, ERD).
-- All five tables are API-written only: the worker never reads or writes them,
-- and no worker-owned table gains a column. The ERD's cardinalities are
-- schema-enforced here, not by convention:
--   MEETING }o--o| SERIES   -> meeting_series(meeting_id PRIMARY KEY)
--   PROJECT ||--o{ MEETING  -> meeting_project(meeting_id PRIMARY KEY)
--   PRODUCT ||--o{ PROJECT  -> project.product_id (nullable FK)
-- Membership is declared row by row by a human (FR25); nothing infers it.

CREATE TABLE series (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    name       text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER series_set_updated_at
    BEFORE UPDATE ON series
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE product (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    name       text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER product_set_updated_at
    BEFORE UPDATE ON product
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- A project optionally belongs to one product (PRODUCT ||--o{ PROJECT). No
-- ON DELETE action beyond the default RESTRICT: entity deletion semantics
-- against projected graphs is future work (no delete endpoints exist).
CREATE TABLE project (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    name       text NOT NULL UNIQUE,
    product_id uuid NULL REFERENCES product (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER project_set_updated_at
    BEFORE UPDATE ON project
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Postgres does not auto-index FK referencing columns, and `GET /projects`
-- joins through this one.
CREATE INDEX project_product_id_idx ON project (product_id);

-- One row per meeting: the PRIMARY KEY on meeting_id is what enforces the
-- ERD's at-most-one series per meeting. Reassignment is an upsert; clearing
-- deletes the row. Cascades from meeting so retiring a meeting takes its
-- assignment with it; the series itself is never deleted by that.
CREATE TABLE meeting_series (
    meeting_id uuid PRIMARY KEY REFERENCES meeting (id) ON DELETE CASCADE,
    series_id  uuid NOT NULL REFERENCES series (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER meeting_series_set_updated_at
    BEFORE UPDATE ON meeting_series
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- `GET /series` aggregates meeting ids through this FK; no auto-index exists.
CREATE INDEX meeting_series_series_id_idx ON meeting_series (series_id);

-- Same shape for the at-most-one project per meeting (PROJECT ||--o{ MEETING).
CREATE TABLE meeting_project (
    meeting_id uuid PRIMARY KEY REFERENCES meeting (id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES project (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER meeting_project_set_updated_at
    BEFORE UPDATE ON meeting_project
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- `GET /projects` aggregates meeting ids through this FK; no auto-index exists.
CREATE INDEX meeting_project_project_id_idx ON meeting_project (project_id);
