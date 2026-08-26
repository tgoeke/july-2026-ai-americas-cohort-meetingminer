-- Story 2.1a: every stored evidence path is relative to one *configured* root
-- (AD-3 as `storage-layout.md` §4 states it), and the recording finally gets a
-- row of its own.
--
-- There have always been two anchors and migration 0005 said so in a comment
-- for transcripts only. This makes the rule uniform:
--
--   * arrived material  -> relative to MM_DROPS_ROOT,   `<drop-dir>/<filename>`
--   * produced material -> relative to MM_CONTENT_ROOT, `meetings/<id>/<sub>/<file>`
--
-- No absolute path is written to this database from here on, and the CHECK
-- constraints below are what make that the database's rule rather than a
-- convention every future INSERT has to remember: a root-relative path may not
-- start with `/` and may not carry a `..` segment, which are the two spellings
-- that let a stored value escape the root it is supposed to be anchored to.
-- Relocating either root stays an environment change, not a data migration.

-- The job's drop directory, relative to MM_DROPS_ROOT. Nullable only for the
-- length of the backfill: `drop_path` below still holds the pre-2.1a absolute
-- value for rows written before this migration, and `make backfill-drop-paths`
-- converts them, reporting every row it cannot place under the configured root
-- and exiting non-zero.
ALTER TABLE job ADD COLUMN drop_relative_path text;

COMMENT ON COLUMN job.drop_relative_path IS
    'The job''s source drop directory, relative to MM_DROPS_ROOT. Never absolute. NULL only until the story 2.1a backfill has run.';

-- The pre-2.1a absolute path. Kept — not dropped — because the backfill has to
-- read it, and NOT NULL is lifted because every writer since 2.1a leaves it
-- NULL rather than storing an absolute path. A later migration retires the
-- column once no deployment still carries un-backfilled rows.
ALTER TABLE job ALTER COLUMN drop_path DROP NOT NULL;

COMMENT ON COLUMN job.drop_path IS
    'Pre-2.1a absolute drop directory, retained only so the backfill can read it. Every writer since 2.1a leaves it NULL.';

-- A job names its drop exactly one way. Both NULL would be a job pointing at
-- nothing, and both populated leaves two conflicting anchors; the CHECK is
-- what makes either a failed statement instead of an unreachable drop found
-- at the next claim.
ALTER TABLE job ADD CONSTRAINT job_has_a_drop
    CHECK (num_nonnulls(drop_relative_path, drop_path) = 1);

-- The recording's provenance row. Until now the recording was the one piece of
-- evidence with no recorded path and no checksum: half its served path was
-- `job.drop_path` and half was a Python constant, so a substituted recording
-- was undetectable where a substituted transcript is not (`transcript_source`
-- has carried the path/checksum/size triple since 0005).
--
-- `drop_relative_path` is anchored to MM_DROPS_ROOT and holds
-- `<drop-dir>/recording.mp4` — the *root*-relative path, never a bare filename
-- and never a path relative to the drop's own folder, so it stays resolvable
-- after an augmenting re-emit repoints the job at a sibling drop.
--
-- Both columns are nullable because a transcript-only meeting legitimately has
-- no recording: `probe` is skipped for it and the row, if any, carries ffprobe
-- facts for nothing. NULL here is "no recording", never "not recorded yet".
--
-- No second size column: `size_bytes` above already holds the byte size
-- ffprobe reported, and the `probe` stage now fails the stage when it and the
-- file's actual size disagree rather than recording two numbers that can drift.
ALTER TABLE meeting_media ADD COLUMN drop_relative_path text;
ALTER TABLE meeting_media ADD COLUMN sha256 text;

COMMENT ON COLUMN meeting_media.drop_relative_path IS
    'The recording, relative to MM_DROPS_ROOT: <drop-dir>/recording.mp4. Never absolute, never a bare filename. NULL means the meeting has no recording.';
COMMENT ON COLUMN meeting_media.sha256 IS
    'SHA-256 of the recording''s bytes, so a substituted recording is detectable on rerun. NULL exactly when drop_relative_path is.';

-- A path and no checksum is provenance that proves nothing, and a checksum
-- with no path describes a file nothing can find. They arrive together or not
-- at all.
ALTER TABLE meeting_media ADD CONSTRAINT meeting_media_recording_provenance_is_whole
    CHECK ((drop_relative_path IS NULL) = (sha256 IS NULL));

-- `transcript_source.drop_relative_path` was a bare filename ("transcript.txt")
-- — relative to the drop's own folder rather than to a root, which is the one
-- thing `storage-layout.md` §5 says a recorded path may never be. Widened to
-- the same `<drop-dir>/<filename>` form; the same backfill command converts
-- existing rows using their meeting's job drop directory.
COMMENT ON COLUMN transcript_source.drop_relative_path IS
    'Path relative to MM_DROPS_ROOT: <drop-dir>/<filename>. Never absolute. NULL for the STT lane, which has no drop file.';

-- The anchor rule, enforced. A root-relative path may not begin with `/`, use
-- root aliases (`.` and `./`), duplicate/trailing separators, or contain a
-- `..` segment. The evidence columns also require both a drop-directory
-- component and a filename: a bare `recording.mp4` or `transcript.txt` has no
-- anchor. The application guards refuse these at resolution time; these make
-- a row carrying one impossible to write in the first place, from any client,
-- including psql. The transcript constraint is deliberately NOT VALID: its
-- existing rows are precisely the legacy bare filenames this migration's
-- backfill must widen, while every later INSERT or UPDATE is still checked.
ALTER TABLE job ADD CONSTRAINT job_drop_relative_path_is_root_relative
    CHECK (
        drop_relative_path IS NULL
        OR (
            drop_relative_path <> ''
            AND drop_relative_path NOT LIKE '/%'
            AND drop_relative_path !~ '(^|/)\.\.(/|$)'
            AND drop_relative_path !~ '(^|/)\.(/|$)'
            AND drop_relative_path !~ '//'
            AND drop_relative_path !~ '/$'
        )
    );

ALTER TABLE meeting_media ADD CONSTRAINT meeting_media_drop_relative_path_is_root_relative
    CHECK (
        drop_relative_path IS NULL
        OR (
            drop_relative_path <> ''
            AND drop_relative_path NOT LIKE '/%'
            AND drop_relative_path !~ '(^|/)\.\.(/|$)'
            AND drop_relative_path !~ '(^|/)\.(/|$)'
            AND drop_relative_path !~ '//'
            AND drop_relative_path !~ '/$'
            AND drop_relative_path ~ '^[^/]+/[^/]+.*$'
        )
    );

ALTER TABLE transcript_source ADD CONSTRAINT transcript_source_drop_relative_path_is_root_relative
    CHECK (
        drop_relative_path IS NULL
        OR (
            drop_relative_path <> ''
            AND drop_relative_path NOT LIKE '/%'
            AND drop_relative_path !~ '(^|/)\.\.(/|$)'
            AND drop_relative_path !~ '(^|/)\.(/|$)'
            AND drop_relative_path !~ '//'
            AND drop_relative_path !~ '/$'
            AND drop_relative_path ~ '^[^/]+/[^/]+.*$'
        )
    ) NOT VALID;
