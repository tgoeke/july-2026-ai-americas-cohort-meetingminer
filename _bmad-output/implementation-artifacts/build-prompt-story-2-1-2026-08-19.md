# Builder handoff — Story 2.1 review closeout

## Review record

- **Repository / integration branch:** `meetingminer`, `main`
- **Reviewed implementation range:** `961254eb69eae2ff0d5859b4ac7e2a31dbb731fe..9633dd05bd2ef6ed26fe69e4e74dab674a5efc93`
- **Review artifact:** `review-story-2-1-2026-08-19.md`
- **Merged main head:** `eff0a75452194b90a7ca34ff25aa38aa92e43217`

## Outcome

The Story 2.1 media foundation **passes review and is already merged to `main`**. Do not modify
its media routes or build the withdrawn
`spec-2-1-recording-under-the-content-root.md`; that copy-the-recording proposal is rejected and
is absent from `main`.

Project tracking deliberately remains `in-progress`. The required conformance work is the separate
`spec-2-1a-evidence-paths-anchored-to-configured-roots.md`, which starts only from this merged
tree. It must keep recordings in their write-once source drop while it introduces `MM_DROPS_ROOT`,
relative paths resolved at use time, a recording provenance row (path, checksum, byte size), a
fail-closed backfill, and rejection of symlinked canonical drop evidence. The source-drop rule is
now decided by AD-1; hard links remain valid.

## Do not reopen as Story 2.1 patches

- The recording is **arrived** material and stays in the drops root under amended AD-3; it is not
  copied beneath `MM_CONTENT_ROOT`.
- The replay route's refusal of a symlinked recording is correct defensive behavior. 2.1a owns the
  intake/worker rule that prevents such a drop from ever minting a recording-backed meeting.
- Existing deferred media improvements and the unmounted replay UI remain outside this closeout.

## Verification already completed for the merged candidate

- `make web-test` — 52 passing tests.
- `cd server && .venv/bin/python -m pytest tests/test_api_media.py -q` — 72 passing tests.
- `cd server && uvx ruff check --isolated meetingminer/api/media.py tests/test_api_media.py` — clean.
- The builder's earlier verified full server suite was 816 passing; no production-code change was
  made after that verification, only architecture/review documentation and the merge.

For 2.1a, run its own `## Verification` commands and confirm each new regression test fails on the
unfixed code before reporting completion. Do not broaden into Story 2.1b or alter the media HTTP
contract while doing so.
