-- Story 4.3: per-moment approval & publishing — the API's half of the
-- disjoint column split (AD-5). The worker (story 4.1/4.1a) owns `kind`,
-- `title`, `body`, `provenance`, `moment_id`, `meeting_id`; this migration
-- adds only the columns the API writes as it advances an artifact's
-- lifecycle state past `extracted`.

-- All four are nullable: they are populated once, together, the moment an
-- artifact's `state` advances to `published` — there is no intermediate
-- "approved but not yet published" resting state exposed to a human (Design
-- Notes), so nothing here is ever set while `state = 'approved'` in
-- practice, and NULL is exactly right for every row still `extracted`.
ALTER TABLE artifact
    ADD COLUMN approved_at           timestamptz,
    ADD COLUMN published_at          timestamptz,
    -- The exported file's path, relative to MM_PUBLISH_ROOT: `<kind>/<id>.md`
    -- (`publish/export.py`). The publish folder is a third configured
    -- location, not a two-anchor root (`storage-layout.md` §1) — this column
    -- is this story's own path convention, not a reuse of the drops/content
    -- anchor columns.
    ADD COLUMN publish_relative_path text,
    -- The git commit sha the ADR was committed under, in the git repo rooted
    -- at MM_PUBLISH_ROOT. NULL for every `action-item` row (exported but
    -- never committed) and for any row not yet published; no CHECK enforces
    -- that split — this story is the only writer of both columns, and the
    -- handler is what keeps them in step (epics AC3).
    ADD COLUMN publish_commit_sha    text;
