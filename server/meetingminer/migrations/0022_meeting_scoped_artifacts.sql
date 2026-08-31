-- Story 12.2: the meeting summary — an artifact scoped to the MEETING rather
-- than to a moment (AD-6). A meeting summary analyses the whole transcript and
-- has no single moment to hang from, so `moment_id` becomes nullable and a new
-- kind joins the CHECK.

-- Nullable, not defaulted: a NULL `moment_id` is the positive statement "this
-- artifact is scoped to its meeting", which the constraint below turns into a
-- checked fact rather than a convention.
ALTER TABLE artifact ALTER COLUMN moment_id DROP NOT NULL;

-- 0009 wrote this CHECK inline and unnamed, so Postgres named it
-- `artifact_kind_check`; widening it is a drop-and-recreate, the same shape
-- 0014 used to widen 0010's `extraction_source` kind CHECK.
ALTER TABLE artifact DROP CONSTRAINT artifact_kind_check;
ALTER TABLE artifact ADD CONSTRAINT artifact_kind_check
    CHECK (kind IN ('adr', 'action-item', 'summary'));

-- THE SINGLE DECLARATION OF WHICH KINDS ARE MEETING-SCOPED.
--
-- Read it as an equivalence: a row's kind is meeting-scoped if and only if it
-- names no moment. That makes the two scopes impossible to confuse — a reader
-- or a query can branch on `moment_id IS NULL` alone and be right by
-- construction — and it puts the kind list in exactly one place. No Python,
-- TypeScript or other SQL in this repository carries a second copy of it, so
-- there is nothing that can drift out of step with this line. Adding a
-- meeting-scoped kind later is an edit of this constraint and of nothing else.
--
-- Both operands are total: `kind` is NOT NULL and `IS NULL` never yields NULL,
-- so this CHECK is always TRUE or FALSE and never passes by three-valued
-- accident.
ALTER TABLE artifact ADD CONSTRAINT artifact_scope_matches_kind CHECK (
    (kind IN ('summary')) = (moment_id IS NULL)
);

-- 0009's composite `FOREIGN KEY (moment_id, meeting_id) REFERENCES moment
-- (id, meeting_id)` is deliberately LEFT UNTOUCHED. Widening the scope must
-- not weaken the anchor, and it does not: under the SQL default MATCH SIMPLE a
-- row satisfies the FK when any referencing column is NULL, so a meeting-scoped
-- row skips it, while a row that names a moment still has both columns
-- populated and is still held to the pair. An artifact therefore still cannot
-- name a moment belonging to another meeting.
COMMENT ON COLUMN artifact.moment_id IS
    'The moment whose evidence yielded this artifact, or NULL when the artifact'
    ' is scoped to its meeting as a whole (story 12.2). Which kinds are'
    ' meeting-scoped is declared by artifact_scope_matches_kind and nowhere'
    ' else.';
