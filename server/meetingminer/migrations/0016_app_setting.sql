-- Story 8.2: app_setting — the user's own declarations about how the system runs.
--
-- This table is API-OWNED and USER-DECLARED, and every reader must label it as
-- such (AD-5, AD-10). Only the api writes it, through `api/settings.py`; the
-- worker reads it when it resolves a role for a job and never writes it. That
-- split is the whole point of putting the selection here rather than in
-- `config.yaml`: the file keeps declaring what is *allowed* (each role's
-- `catalog[]` and `default`, story 8.1), while a person's pick among those
-- allowed entries is data, not configuration, and must survive a restart
-- without anyone editing a tracked file.
--
-- Deliberately a generic key/value table rather than a `role_model_selection`
-- table with a `role` column. The rows are settings, plural in kind and few in
-- number, and the alternative would mean a migration for every future setting
-- of a different shape. The trade is that the *meaning* of a key lives in code
-- (`domain/model_selection.py` owns the `llm.role.<role>.binding` spelling)
-- rather than in the schema, so no constraint here can tell a valid model
-- binding from a typo. That check belongs where the catalog is known anyway:
-- the api refuses a binding outside its role's catalog on write, and the
-- resolver re-checks it on read, because `config.yaml`'s catalog can be edited
-- after a row is written.
--
-- No foreign keys and no cascade: a setting is not evidence, it references no
-- meeting, and no ingest rerun may clear it.

CREATE TABLE app_setting (
    -- Dotted, namespaced, and owned by the code that reads it. Constrained to
    -- non-blank so a client cannot write an unaddressable row.
    key        text PRIMARY KEY CHECK (btrim(key) <> ''),
    -- Text rather than jsonb: every setting this story writes is one scalar
    -- the api validated before writing, and jsonb would invite storing a shape
    -- nothing validates. Widening to jsonb is a later migration if a setting
    -- ever needs structure.
    value      text NOT NULL CHECK (btrim(value) <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Same trigger every mutable table here uses (0001_jobs.sql), so an upsert
-- records when the choice was actually changed.
CREATE TRIGGER app_setting_set_updated_at
    BEFORE UPDATE ON app_setting
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
